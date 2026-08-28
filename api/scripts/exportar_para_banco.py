#!/usr/bin/env python3
"""
Gera o SQL de carga do banco a partir do dado já publicado.

    python3 scripts/exportar_para_banco.py

Saída: `db/carga.sql`, aplicável com

    npx wrangler d1 execute vigilancia --remote --file=db/carga.sql

POR QUE ELE LÊ O JSON, E NÃO O GERADOR
--------------------------------------
Seria possível fazer o `gerar_dados.py` escrever JSON e SQL lado a lado. Não
faz: este script lê o **mesmo `public/data/casos_dengue.json`** que o dashboard
consome.

O motivo é que duas representações do mesmo dado divergem no dia em que alguém
mexe numa e esquece a outra — e a divergência entre um painel e outro é
justamente o defeito mais caro possível numa apresentação com duas frentes.
Derivando o banco do arquivo publicado, a única forma de eles discordarem é o
arquivo ter mudado sem este script rodar depois. E isso o teste pega.

O QUE ELE NÃO EXPORTA, DE PROPÓSITO
-----------------------------------
Os agregados por bairro do JSON (`casos`, `graves`, `obitos`, `incidencia`) não
vão para a tabela `bairros`. Só a população vai.

Aqueles números são do período INTEIRO. Guardados no banco, ficariam a um JOIN
de distância de serem exibidos ao lado de um filtro de três meses que não os
produziu — e incidência anualizada de um recorte não é a do período todo. A API
calcula sob demanda. Ver o comentário no `db/schema.sql`.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
# Snapshot do dado publicado, copiado do repositório da frente de priorização
# geográfica. Ver dados/PROVENIENCIA.md para saber de onde veio e como
# atualizar — o pipeline que GERA esses arquivos não mora aqui.
DADOS = RAIZ / "dados" / "casos_dengue.json"
GRADE = RAIZ / "dados" / "geo" / "grade.geojson"
DETECCOES = RAIZ / "dados" / "deteccoes.json"
SAIDA = RAIZ / "db" / "carga.sql"

# Espelha o CAMPOS_IDENTIFICADORES do gerar_dados.py. Se um destes aparecer no
# JSON publicado, alguma coisa deu muito errado antes de chegar aqui — e o
# banco é o último lugar onde ainda dá para parar.
PROIBIDOS = {"paciente", "nome", "endereco", "logradouro", "numero",
             "idade", "cpf", "cns", "telefone", "email"}


def sql(v):
    """Literal SQL. Sem interpolação solta: aspas dentro de texto quebram carga."""
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, (int, float)):
        return repr(v)
    return "'" + str(v).replace("'", "''") + "'"


def linhas(tabela, colunas, registros):
    """
    INSERTs em lotes de 200.

    O D1 tem limite de tamanho por comando, e um INSERT único com 2000 casos
    passa dele. Lote pequeno demais gera arquivo enorme; 200 fica confortável
    nos dois lados.
    """
    saida = []
    for i in range(0, len(registros), 200):
        lote = registros[i:i + 200]
        valores = ",\n  ".join(
            "(" + ", ".join(sql(r.get(c)) for c in colunas) + ")" for r in lote
        )
        saida.append(
            f"INSERT OR REPLACE INTO {tabela} ({', '.join(colunas)}) VALUES\n"
            f"  {valores};"
        )
    return saida


def main():
    if not DADOS.exists():
        sys.exit(f"{DADOS.relative_to(RAIZ)} não existe. Ver dados/PROVENIENCIA.md.")

    base = json.loads(DADOS.read_text())
    meta = base["meta"]

    # ------------------------------------------------ guarda de privacidade
    vazando = set(base["casos"][0].keys()) & PROIBIDOS
    if vazando:
        sys.exit(
            f"ABORTADO: o JSON publicado traz campos identificadores {sorted(vazando)}.\n"
            "O banco não pode recebê-los — a tabela `casos` nem tem colunas para\n"
            "eles. Corrija o gerar_dados.py antes de exportar."
        )

    partes = [
        "-- Carga do banco de vigilância. GERADO — não edite à mão.",
        f"-- Origem: {DADOS.relative_to(RAIZ)}",
        f"-- Gerado em: {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        "--",
        "-- Regenerar:  python3 scripts/exportar_para_banco.py",
        "-- Aplicar:    npx wrangler d1 execute vigilancia --remote --file=db/carga.sql",
        "",
        "DELETE FROM deteccoes;",
        "DELETE FROM canal_endemico;",
        "DELETE FROM casos;",
        "DELETE FROM celulas;",
        "DELETE FROM bairros;",
        "DELETE FROM meta;",
        "",
    ]

    # ------------------------------------------------------------- bairros
    bairros = [{"bairro": b["bairro"], "populacao": round(b["populacao"], 2)}
               for b in base["bairros"]]
    partes += ["-- bairros"] + linhas("bairros", ["bairro", "populacao"], bairros)

    # ------------------------------------------------------------- células
    grade = json.loads(GRADE.read_text())
    conhecidos = {b["bairro"] for b in bairros}
    celulas = []
    for f in grade["features"]:
        p = f["properties"]
        b = p.get("bairro")
        # Caixa envolvente e centroide, para o cadastro converter coordenada em
        # célula direto no SQL, sem carregar geometria no Worker. A grade veio
        # de UTM reprojetado, então as células não são retângulos exatos em
        # lon/lat — ver o comentário no schema.sql sobre a busca em dois passos.
        anel = f["geometry"]["coordinates"][0]
        xs = [pt[0] for pt in anel]
        ys = [pt[1] for pt in anel]
        celulas.append({
            "celula": p["celula"],
            # Célula cujo bairro não está na tabela viraria erro de chave
            # estrangeira e derrubaria a carga inteira. Área não classificada
            # é caso real na borda da malha — vira NULL, não erro.
            "bairro": b if b in conhecidos else None,
            "populacao": round(p.get("populacao") or 0, 2),
            "n_ancoras": p.get("n_ancoras") or 0,
            "lon_min": round(min(xs), 8), "lon_max": round(max(xs), 8),
            "lat_min": round(min(ys), 8), "lat_max": round(max(ys), 8),
            "lon_centro": round(sum(xs[:-1]) / (len(xs) - 1), 8),
            "lat_centro": round(sum(ys[:-1]) / (len(ys) - 1), 8),
        })
    partes += ["", "-- células da grade de 150 m"]
    partes += linhas("celulas", [
        "celula", "bairro", "populacao", "n_ancoras",
        "lon_min", "lon_max", "lat_min", "lat_max",
        "lon_centro", "lat_centro"], celulas)

    # --------------------------------------------------------------- casos
    cols_caso = [
        "id", "sexo", "faixa_etaria", "bairro", "celula", "setor", "cidade", "uf",
        "lon_celula", "lat_celula",
        "data_inicio_sintomas", "data_entrada", "ano", "mes", "ano_mes",
        "ano_epidemiologico", "semana_epidemiologica", "temporada",
        "semana_da_temporada",
        "unidade_notificadora", "classificacao", "sorotipo", "sintomas",
        "desfecho", "confirmado",
    ]
    validas = {c["celula"] for c in celulas}
    casos = []
    for c in base["casos"]:
        casos.append({
            **{k: c.get(k) for k in cols_caso if k in c},
            "bairro": c.get("bairro") if c.get("bairro") in conhecidos else None,
            "celula": c.get("celula") if c.get("celula") in validas else None,
            # Renomeadas na travessia: no banco o nome diz que é a coordenada
            # da CÉLULA, não a do domicílio.
            "lon_celula": c.get("longitude"),
            "lat_celula": c.get("latitude"),
            "sintomas": json.dumps(c.get("sintomas"), ensure_ascii=False),
            "confirmado": 1 if c.get("confirmado") else 0,
        })
    partes += ["", f"-- casos ({len(casos)})"]
    partes += linhas("casos", cols_caso, casos)

    # ------------------------------------------------------- canal endêmico
    canal = [{"posicao": c["posicao"], "semana_epi": c.get("semana_epi"),
              "q1": c["q1"], "mediana": c["mediana"], "q3": c["q3"]}
             for c in base.get("canal", [])]
    if canal:
        partes += ["", "-- canal endêmico"]
        partes += linhas("canal_endemico",
                         ["posicao", "semana_epi", "q1", "mediana", "q3"], canal)

    # ----------------------------------------------------------- detecções
    if DETECCOES.exists():
        det = json.loads(DETECCOES.read_text())
        registros = [{
            "deteccao_id": d["deteccao_id"],
            "celula": d.get("celula_id") if d.get("celula_id") in validas else None,
            "bairro": d.get("bairro"),
            "classe": d["classe"],
            "classe_origem": d.get("classe_origem"),
            "confianca": d["confianca"],
            "lon": d["centroide"][0],
            "lat": d["centroide"][1],
            "data_deteccao": d.get("data_deteccao"),
            "verificacao": d.get("verificacao") or "pendente",
            "origem_imagem": d.get("origem_imagem"),
        } for d in det["deteccoes"]]
        partes += ["", f"-- detecções da frente aérea ({len(registros)})"]
        partes += linhas("deteccoes", [
            "deteccao_id", "celula", "bairro", "classe", "classe_origem",
            "confianca", "lon", "lat", "data_deteccao", "verificacao",
            "origem_imagem"], registros)

    # ------------------------------------------------------------ metadados
    itens = [
        ("municipio", meta["municipio"]),
        ("uf", meta["uf"]),
        ("codigo_ibge", str(meta["codigo_ibge"])),
        ("periodo_inicio", meta["periodo_inicio"]),
        ("periodo_fim", meta["periodo_fim"]),
        ("populacao_municipio", str(meta["populacao_municipio"])),
        ("populacao_urbana_na_grade", str(meta["populacao_urbana_na_grade"])),
        ("lado_celula_m", str(meta["lado_celula_m"])),
        ("centro_lat", str(meta["centro"]["lat"])),
        ("centro_lon", str(meta["centro"]["lon"])),
        ("aviso", meta["aviso"]),
        ("privacidade", json.dumps(meta["privacidade"], ensure_ascii=False)),
        ("fontes", json.dumps(meta["fontes"], ensure_ascii=False)),
        ("carregado_em", datetime.now(timezone.utc).isoformat(timespec="seconds")),
    ]
    partes += ["", "-- metadados"]
    partes += linhas("meta", ["chave", "valor"],
                     [{"chave": k, "valor": v} for k, v in itens])

    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    SAIDA.write_text("\n".join(partes) + "\n")

    print(f"{len(bairros)} bairros")
    print(f"{len(celulas)} células")
    print(f"{len(casos)} casos")
    print(f"{len(canal)} semanas de canal endêmico")
    print(f"{SAIDA.relative_to(RAIZ)}: {SAIDA.stat().st_size / 1024:.0f} KB")


if __name__ == "__main__":
    main()
