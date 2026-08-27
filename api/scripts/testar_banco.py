#!/usr/bin/env python3
"""
Testes do banco de vigilância.

    python3 scripts/testar_banco.py

Roda só com a biblioteca padrão: o `sqlite3` do Python carrega o mesmo
`schema.sql` e a mesma `carga.sql` que vão para o D1, que também é SQLite. Não
precisa de wrangler, de conta na Cloudflare nem de rede.

O que se prova aqui:

  1. a fronteira de privacidade é ESTRUTURAL — a tabela de casos não tem
     coluna para identificação, então um INSERT com endereço falha;
  2. a carga aplica sem erro sobre o esquema;
  3. o que está no banco bate com o JSON publicado — se alguém regenerar os
     dados e esquecer de reexportar, os dois divergem e isto pega.

O item 3 é o que mais importa numa apresentação com duas frentes: um painel
mostrando um número e o outro mostrando outro é o defeito mais caro possível,
e o mais fácil de introduzir sem perceber.
"""

import json
import sqlite3
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
ESQUEMA = RAIZ / "db" / "schema.sql"
CARGA = RAIZ / "db" / "carga.sql"
JSON_CASOS = RAIZ / "dados" / "casos_dengue.json"

ok = 0
falhas = []


def t(nome, condicao, dica=""):
    global ok
    if condicao:
        ok += 1
    else:
        falhas.append((nome, dica))


if not CARGA.exists():
    print(f"{CARGA.relative_to(RAIZ)} não existe.")
    print("Rode: python3 scripts/exportar_para_banco.py")
    sys.exit(1)

# ------------------------------------------------------------------- carga
con = sqlite3.connect(":memory:")
con.executescript(ESQUEMA.read_text())
try:
    con.executescript(CARGA.read_text())
    t("a carga aplica sobre o esquema sem erro", True)
except sqlite3.Error as e:
    t("a carga aplica sobre o esquema sem erro", False, str(e))
    print("FALHOU na carga — os testes seguintes não fazem sentido.")
    print(f"  {e}")
    sys.exit(1)

con.execute("PRAGMA foreign_keys = ON")
n = lambda q: con.execute(q).fetchone()[0]  # noqa: E731

# ------------------------------------------------- privacidade estrutural
colunas = {r[1] for r in con.execute("PRAGMA table_info(casos)")}
PROIBIDAS = {"paciente", "nome", "endereco", "logradouro", "numero", "idade",
             "cpf", "cns", "telefone", "email", "latitude", "longitude"}
t("a tabela de casos não tem coluna identificadora",
  not (colunas & PROIBIDAS),
  f"presentes: {sorted(colunas & PROIBIDAS)}")

t("a idade aparece só como faixa",
  "faixa_etaria" in colunas and "idade" not in colunas)

# `latitude`/`longitude` seriam lidos como posição do domicílio. O nome no
# banco diz o que o valor é: coordenada da célula, sorteada.
t("a coordenada tem nome que diz que é da célula",
  {"lon_celula", "lat_celula"} <= colunas
  and not ({"latitude", "longitude"} & colunas))

# A prova de que a regra é estrutural e não convenção: tentar gravar endereço
# tem de falhar no banco, não num validador que alguém pode esquecer de chamar.
try:
    con.execute("INSERT INTO casos (id, endereco) VALUES ('X', 'Rua tal, 120')")
    t("INSERT com endereço é recusado pelo banco", False,
      "o INSERT passou — a coluna existe")
except sqlite3.OperationalError:
    t("INSERT com endereço é recusado pelo banco", True)

# Mesma coisa do lado da frente aérea: detecção aponta para criadouro, não
# para morador.
col_det = {r[1] for r in con.execute("PRAGMA table_info(deteccoes)")}
t("detecção não tem coluna de proprietário ou endereço",
  not (col_det & {"proprietario", "morador", "endereco", "nome"}))

# ------------------------------------------------------ integridade interna
t("nenhum caso aponta para célula inexistente",
  n("SELECT COUNT(*) FROM casos c LEFT JOIN celulas g ON c.celula = g.celula "
    "WHERE c.celula IS NOT NULL AND g.celula IS NULL") == 0)

t("nenhum caso aponta para bairro inexistente",
  n("SELECT COUNT(*) FROM casos c LEFT JOIN bairros b ON c.bairro = b.bairro "
    "WHERE c.bairro IS NOT NULL AND b.bairro IS NULL") == 0)

t("sintomas antes da entrada em todos os casos",
  n("SELECT COUNT(*) FROM casos WHERE data_inicio_sintomas > data_entrada") == 0)

t("semana da temporada dentro de 1..53",
  n("SELECT COUNT(*) FROM casos WHERE semana_da_temporada NOT BETWEEN 1 AND 53") == 0)

t("quartis do canal em ordem",
  n("SELECT COUNT(*) FROM canal_endemico WHERE NOT (q1 <= mediana AND mediana <= q3)") == 0)

t("confiança das detecções entre 0 e 1",
  n("SELECT COUNT(*) FROM deteccoes WHERE confianca <= 0 OR confianca > 1") == 0)

# ------------------------------------- o banco bate com o JSON publicado
base = json.loads(JSON_CASOS.read_text())
casos = base["casos"]

t(f"contagem de casos bate ({n('SELECT COUNT(*) FROM casos')} no banco, {len(casos)} no JSON)",
  n("SELECT COUNT(*) FROM casos") == len(casos))

t("contagem de bairros bate",
  n("SELECT COUNT(*) FROM bairros") == len(base["bairros"]))

t("contagem do canal endêmico bate",
  n("SELECT COUNT(*) FROM canal_endemico") == len(base.get("canal", [])))

# Agregação por bairro: é o número que aparece nos dois painéis. Se divergir,
# a banca vê dois valores diferentes para a mesma coisa.
por_bairro_json = {}
for c in casos:
    por_bairro_json[c["bairro"]] = por_bairro_json.get(c["bairro"], 0) + 1
por_bairro_db = dict(con.execute(
    "SELECT bairro, COUNT(*) FROM casos WHERE bairro IS NOT NULL GROUP BY bairro"))
t("casos por bairro idênticos entre banco e JSON",
  por_bairro_json == por_bairro_db,
  f"divergem em {set(por_bairro_json.items()) ^ set(por_bairro_db.items())}")

# População: é o denominador da incidência. Errar aqui erra o argumento inteiro.
pop_json = {b["bairro"]: round(b["populacao"], 2) for b in base["bairros"]}
pop_db = {b: p for b, p in con.execute("SELECT bairro, populacao FROM bairros")}
t("população por bairro idêntica entre banco e JSON", pop_json == pop_db)

# ------------------------------------------------ a carga não está velha
# Se alguém rodou `npm run dados` e não reexportou, o banco publica um retrato
# antigo enquanto o dashboard mostra o novo — e nada avisa.
ids_json = {c["id"] for c in casos}
ids_db = {r[0] for r in con.execute("SELECT id FROM casos")}
t("os mesmos IDs de caso nos dois lados",
  ids_json == ids_db,
  "carga.sql desatualizado — rode `npm run banco:exportar`"
  if ids_json != ids_db else "")

meta_db = dict(con.execute("SELECT chave, valor FROM meta"))
t("período do banco bate com o do JSON",
  meta_db.get("periodo_inicio") == base["meta"]["periodo_inicio"]
  and meta_db.get("periodo_fim") == base["meta"]["periodo_fim"])

t("o banco declara o aviso de dado fictício",
  "FICTÍCIOS" in (meta_db.get("aviso") or "").upper())

# ------------------------------------------- os dois pisos populacionais
#
# São DOIS pisos: 60 para bairro, 25 para célula. A primeira versão desta API
# usou 60 para os dois, e 81 células apareciam com taxa no dashboard de origem
# e como `null` na API — duas telas do mesmo projeto discordando sobre o mesmo
# território.
#
# No repositório de origem há um teste que lê o front e a API e compara os
# números. Aqui o front não está presente, então o que se trava é o valor
# documentado: mexer sem querer reprova, e obriga a conferir o outro lado.
import re  # noqa: E402

worker = (RAIZ / "worker" / "index.js").read_text()


def numero(texto, padrao):
    m = re.search(padrao, texto)
    return int(m.group(1)) if m else None


piso_bairro_api = numero(worker, r"POP_MINIMA_BAIRRO\s*=\s*(\d+)")
piso_celula_api = numero(worker, r"POP_MINIMA_CELULA\s*=\s*(\d+)")

t(f"piso de bairro é 60, como no dashboard de origem (achado: {piso_bairro_api})",
  piso_bairro_api == 60,
  "Se mudou de propósito, mude também no dashboard — senão as duas telas "
  "discordam sobre as mesmas células.")

t(f"piso de célula é 25, como no dashboard de origem (achado: {piso_celula_api})",
  piso_celula_api == 25,
  "Célula de 150 m é pequena por construção; exigir 60 apagaria a área urbana "
  "de baixa densidade, que é onde a priorização geográfica tem mais a dizer.")

# ------------------------------------- segregação do dado identificado
#
# A tabela `casos_identificados` existe porque o cadastro precisa dela. O que
# faz isso ser segregação e não teatro é NENHUMA rota de leitura consultá-la —
# e essa é uma propriedade que se perde num refactor distraído, sem erro
# nenhum, publicando endereço para quem tiver o link.

col_ident = {r[1] for r in con.execute("PRAGMA table_info(casos_identificados)")}
t("a tabela identificada existe e guarda o que o formulário deles coleta",
  {"nome", "endereco", "numero", "cep", "telefone", "cartao_sus"} <= col_ident)

t("a coordenada do domicílio tem nome distinto da coordenada publicada",
  {"lon_domicilio", "lat_domicilio"} <= col_ident,
  "confundir as duas apaga a anonimização sem ninguém notar")

t("a chave estrangeira liga ao caso publicado",
  "caso_id" in col_ident)

# O teste central: varre o Worker atrás da tabela fora do caminho de escrita.
trechos = [ln for ln in worker.splitlines() if "casos_identificados" in ln]
# Aceitáveis: a constante do cadastro, o INSERT e as menções em comentário ou
# em texto de resposta. Inaceitável: SELECT.
selects = [ln for ln in trechos if re.search(r"\bSELECT\b", ln, re.I)]
t(f"nenhuma rota de leitura consulta casos_identificados ({len(trechos)} menções, 0 SELECT)",
  not selects,
  f"SELECT encontrado: {selects}")

t("o cadastro separa: os campos identificados não estão na lista de públicos",
  not (set(re.findall(r"'([a-z_]+)'", re.search(
      r"CAMPOS_IDENTIFICADOS = \[(.*?)\]", worker, re.S).group(1)))
      & set(re.findall(r"'([a-z_]+)'", re.search(
          r"CAMPOS_PUBLICOS = \[(.*?)\]", worker, re.S).group(1)))))

t("a escrita exige token",
  "TOKEN_CADASTRO" in worker and "401" in worker)

# A tabela `casos` continua sem colunas identificadoras DEPOIS de existir a
# tabela segregada — é a metade da promessa que o cadastro poderia ter comido.
t("a tabela casos segue sem coluna identificadora após a segregação",
  not (colunas & PROIBIDAS))

t("o exportador nunca escreve na tabela identificada",
  "casos_identificados" not in
  (RAIZ / "scripts" / "exportar_para_banco.py").read_text(),
  "os 2000 casos simulados não têm identificação, e é assim que deve ser")

# ---------------------------------------------------------------- resultado
print(f"{ok} testes passaram, {len(falhas)} falharam")
for nome, dica in falhas:
    print(f"  FALHOU: {nome}")
    if dica:
        print(f"          {dica}")
sys.exit(1 if falhas else 0)
