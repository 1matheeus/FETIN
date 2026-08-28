# API de vigilância epidemiológica

Camada de dados do projeto. Serve os casos de dengue, a grade de 150 m, a
incidência por habitante e as detecções do drone para o painel do AeroScan.

**Banco:** Cloudflare D1 (SQLite gerenciado).
**Servidor:** um Worker, sem build, sem framework.
**Consumo:** HTTP com CORS liberado — o painel chama direto do navegador.

> ⚠️ **Os casos são fictícios**, gerados por simulação. A geografia é real
> (Censo 2022 do IBGE + OpenStreetMap). Ver `dados/PROVENIENCIA.md`.

Para **consumir** a API: [`docs/api-banco.md`](docs/api-banco.md) — endpoints,
exemplos de `fetch`, formato do cadastro. É o documento que a frente do painel
precisa.

---

## Estrutura

```
api/
├── db/schema.sql          ← esquema; a fronteira de privacidade mora aqui
├── dados/                 ← snapshot do dado publicado (ver PROVENIENCIA.md)
├── scripts/
│   ├── exportar_para_banco.py   ← JSON → SQL de carga
│   └── testar_banco.py          ← 30 testes, só biblioteca padrão
├── worker/index.js        ← a API
├── wrangler.jsonc         ← configuração do deploy
└── docs/api-banco.md      ← guia de consumo
```

---

## Rodar local, sem conta e sem rede

```bash
cd api
npm run banco:exportar    # gera db/carga.sql a partir de dados/
npm run teste             # 30 testes
npm run banco:local       # cria e carrega um D1 local
npm run api:local         # sobe em http://127.0.0.1:8787
```

Depois: <http://127.0.0.1:8787/api/rotas>

Para testar o cadastro localmente, crie um `.dev.vars` (fora do git):

```
TOKEN_CADASTRO="qualquer-coisa"
```

## Publicar

```bash
npm run banco:exportar
npm run banco:aplicar     # precisa das credenciais da conta Cloudflare
npm run deploy
```

O segredo do cadastro se define uma vez, e não vive no repositório:

```bash
npx wrangler secret put TOKEN_CADASTRO
```

---

## A decisão de projeto que este código carrega

O painel de vigilância cadastra casos, e quem notifica um caso sabe o nome e o
endereço do paciente. Esse dado **existe** — fingir que não o faz ser guardado
num lugar pior, tipo uma planilha solta.

Então ele é **segregado**, não omitido, como no SINAN:

| Tabela | Conteúdo | Sai pela API? |
|---|---|---|
| `casos` | sexo, faixa etária, célula, datas, classificação | **sim** |
| `casos_identificados` | nome, endereço, CEP, telefone, cartão SUS, coordenada do domicílio | **não** |

A tabela `casos` **não tem colunas** para identificação. Não é validação que se
contorna: é ausência. Um `INSERT` com endereço falha com erro de SQL, na hora,
para quem escreveu.

O `POST /api/casos` recebe o formulário **inteiro** e faz a separação no
servidor — o painel manda tudo o que já coleta, sem mudar nada, e a fronteira é
aplicada de qualquer forma. A resposta devolve só a versão publicável, para quem
cadastrou ver na tela exatamente o que o mundo vai ver.

Três coisas fazem isso ser segregação e não teatro, e cada uma tem teste:

1. nenhuma rota de leitura consulta `casos_identificados` — há teste que varre
   o `worker/index.js` procurando `SELECT` nessa tabela;
2. a tabela `casos` continua sem colunas identificadoras;
3. o exportador do dado simulado nunca escreve na tabela identificada.

**O que ainda não existe:** criptografia em repouso, log de acesso e política de
retenção na tabela identificada. Para demonstrar o desenho, a segregação basta;
para dado de gente, não. Está dito no `db/schema.sql`, onde quem for mexer lê.

---

## Duas coisas que economizam tempo de quem consome

**Incidência não é contagem.** Ranking por número de casos mede parcialmente a
população: bairro grande tem mais casos porque tem mais gente. No período
inteiro, os três primeiros de cada critério não têm nenhuma sobreposição — a
tabela está em `docs/api-banco.md`. Ordenar só por contagem manda a equipe de
campo para o lugar errado.

**`incidencia: null` não é zero.** Abaixo do piso populacional (60 para bairro,
25 para célula) a taxa é ruído: um caso em 15 moradores dá 6.600 por 100 mil.
Não converta para 0 — um `0` na tela diz "não há risco", e o que existe é "não
dá para calcular".
