# API do banco de vigilância

Guia para a frente que consome os dados. Se você está integrando o dashboard do
AeroScan, é este o documento.

O banco é **Cloudflare D1** (SQLite gerenciado), servido por um Worker. Só
leitura, sem chave, com CORS liberado — dá para chamar direto do JavaScript do
navegador, de qualquer origem.

```
https://projetofetin.<subdominio>.workers.dev/api/
```

> ⚠️ **Os casos são fictícios**, gerados por simulação. A geografia (setores,
> população, ruas) é real, do Censo 2022 do IBGE e do OpenStreetMap.

---

## Comece por aqui

```js
const API = 'https://projetofetin.<subdominio>.workers.dev/api'

const r = await fetch(`${API}/incidencia/bairros?desde=2026-01-01&ate=2026-03-31`)
const { dados, recorte } = await r.json()

dados.sort((a, b) => (b.incidencia ?? -1) - (a.incidencia ?? -1))
console.log(dados[0])
// { bairro: 'Jardim Santo Antônio', populacao: 720, casos: 20,
//   graves: 2, obitos: 0, incidencia: 11103.4 }
```

`GET /api/rotas` lista tudo o que existe, com uma linha de descrição cada.

---

## Rotas

| Rota | Devolve |
|---|---|
| `GET /api/meta` | período, população, fontes, declaração de privacidade |
| `GET /api/bairros` | os 58 bairros com população do Censo |
| `GET /api/celulas` | as 539 células da grade de 150 m |
| `GET /api/casos` | casos anonimizados, paginados |
| `GET /api/incidencia/bairros` | **incidência anualizada por bairro, no recorte pedido** |
| `GET /api/incidencia/celulas` | idem, por célula de 150 m |
| `GET /api/canal` | canal endêmico: mediana e quartis por semana |
| `GET /api/deteccoes` | focos detectados pela frente aérea |

**Filtros** (valem em `/casos` e nas duas de incidência):
`desde`, `ate` (AAAA-MM-DD), `bairro`, `celula`, `sexo`, `faixa_etaria`,
`classificacao`, `sorotipo`. Em `/casos` também `limite` (máx. 5000, padrão
2000) e `offset`.

---

## As três coisas que mais importam

### 1. Incidência não é contagem, e a diferença é o projeto

Ranking por número de casos mede parcialmente a população: bairro grande tem
mais casos porque tem mais gente. No período inteiro, os três primeiros de cada
critério **não têm nenhuma sobreposição**:

| Por incidência | | Por contagem | |
|---|---|---|---|
| Jardim Santo Antônio | 4.510 /100 mil | Chácara M. A. Baracat | 90 casos |
| Fortaleza | 4.351 /100 mil | Eletrônica | 69 casos |
| Monte Verde | 4.248 /100 mil | Anchieta | 67 casos |

Se o painel ordenar só por contagem, ele manda a equipe de campo para o lugar
errado — e essa é a crítica mais fácil de fazer a um dashboard de vigilância.
Use `/api/incidencia/*` como padrão e ofereça a contagem como alternativa; a
comparação entre as duas é, por si só, um argumento para a banca.

### 2. `incidencia: null` não é zero

Abaixo do piso populacional a taxa vira ruído: um caso em 15 moradores dá 6.600
por 100 mil. A API devolve `null` nesses casos.

**São dois pisos**, e a diferença é deliberada:

| Território | Piso | Por quê |
|---|---|---|
| Bairro | 60 hab. | tamanho variável; 60 é onde a taxa começa a significar algo |
| Célula de 150 m | 25 hab. | pequena por construção; exigir 60 apagaria a área urbana de baixa densidade, que é onde a priorização geográfica tem mais a dizer |

Com o piso de 25, 211 das 539 células ficam sem taxa. Cada resposta traz
`metodo.populacao_minima` com o valor aplicado — leia de lá em vez de fixar o
número no código de vocês.

Não converta para 0. Um `0` na tela diz "não há risco", e o que existe é "não
dá para calcular". Mostre um traço, e no tooltip: *população insuficiente para
a taxa*.

### 3. A incidência muda com o filtro, porque é anualizada

```
casos / população × 100.000 × (12 / meses do recorte)
```

O mesmo bairro dá 4.510 no período inteiro e 11.103 num recorte de três meses —
os dois estão certos, medem coisas diferentes. Toda resposta traz o bloco
`recorte` com os meses e o fator usados.

Por isso a API **calcula na hora** em vez de guardar o número: um valor gravado
ficaria a um JOIN de distância de aparecer ao lado de um filtro que não o
produziu.

---

## O cadastro de casos

**`POST /api/casos` aceita o formulário de vocês como ele é.** Nome, endereço,
número, CEP, telefone, cartão do SUS, data de nascimento, coordenada do
domicílio — manda tudo. Nenhum campo precisa ser removido do formulário.

```js
await fetch(`${API}/casos`, {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    Authorization: `Bearer ${TOKEN}`,
  },
  body: JSON.stringify({
    nome: 'Maria da Silva Souza',
    data_nascimento: '1987-03-14',
    endereco: 'Rua Cel. José Augusto',
    numero: '120',
    cep: '37540-000',
    telefone: '(35) 99999-1234',
    cartao_sus: '706000000000000',
    lat_domicilio: -22.2518,
    lon_domicilio: -45.7041,
    sexo: 'F',
    data_entrada: '2026-05-23',
    data_inicio_sintomas: '2026-05-20',
    classificacao: 'Dengue com sinais de alarme',
    sorotipo: 'DENV-2',
  }),
})
```

### O que o servidor faz com isso

A separação acontece **no servidor**, não no formulário — de propósito. Se
dependesse de o cliente separar, dependeria de o cliente lembrar.

| O que vocês mandam | Onde vai parar |
|---|---|
| nome, endereço, número, CEP, telefone, cartão SUS, nascimento, coordenada do domicílio | `casos_identificados` — **nunca sai pela API de leitura** |
| sexo, datas, classificação, sorotipo, unidade | `casos` — publicado |
| *derivados no servidor* | |
| endereço → **célula de 150 m** | `casos.celula` |
| data de nascimento → **faixa etária** | `casos.faixa_etaria` |
| coordenada do domicílio → **ponto sorteado dentro da célula** | `casos.lon_celula` |

A resposta devolve **só a versão publicável** — para vocês verem na tela
exatamente o que o mundo vai ver:

```json
{
  "ok": true,
  "caso": { "id": "SRS-707FD2EF", "sexo": "F", "faixa_etaria": "30-39",
            "bairro": "Centro", "celula": "C019015",
            "lon_celula": -45.702864, "lat_celula": -22.251948, "...": "..." },
  "identificacao": {
    "armazenada": true,
    "campos": ["nome", "endereco", "numero", "cep", "telefone", "..."],
    "tabela": "casos_identificados",
    "nota": "Segregada. Nenhuma rota de leitura desta API consulta esta tabela."
  }
}
```

Repare: o domicílio enviado foi `-45.7041, -22.2518`; o publicado é
`-45.702864, -22.251948`. **Sorteado dentro da célula**, não ruído somado à
posição real — jitter gaussiano manteria a coordenada verdadeira como valor
esperado, sorteio uniforme não. Dá para desenhar mapa de calor; não dá para
voltar ao endereço.

### Por que duas tabelas e não uma coluna

O dado identificado existe: quem notifica sabe o nome e o endereço, e a equipe
de campo precisa reencontrar o caso. Fingir que não existe não o faz sumir —
faz ele ser guardado num lugar pior, tipo uma planilha solta no WhatsApp.

É como o SINAN funciona: o identificado existe com acesso restrito, e o que
circula para análise é a visão anonimizada. Separar em vez de omitir é um
argumento **mais forte** para a banca, não mais fraco.

Três coisas fazem isso ser segregação e não teatro, e cada uma tem teste:

1. nenhuma rota de leitura consulta `casos_identificados` — há teste que varre
   o `worker/index.js` procurando `SELECT` nessa tabela;
2. a tabela `casos` continua sem colunas identificadoras;
3. o exportador do dado simulado nunca escreve na tabela identificada.

### Sobre o token

`POST` exige `Authorization: Bearer <token>`. Sem ele, 401.

**Sejam realistas sobre o que ele protege:** se o token estiver no JavaScript do
formulário de vocês, ele é público para quem abrir o DevTools. Ele barra escrita
acidental e varredura automática — não uma pessoa determinada.

Para dado fictício de feira, essa é a troca certa. Para dado de gente, não é:
precisaria de sessão de usuário no servidor, e o dashboard de vocês é estático.
Vale dizer isso na apresentação em vez de esperarem perguntar.

O token é definido com `npx wrangler secret put TOKEN_CADASTRO`. Peçam ao
Eduardo — ele fica na conta da Cloudflare, não no repositório.

### Limites que ainda não existem

A tabela identificada **não tem** criptografia em repouso, log de acesso nem
política de retenção. Para demonstrar o desenho, a segregação basta. Para dado
real, não — e isso está escrito no `db/schema.sql`, para quem for ler o código.

---

## Detalhes que economizam tempo

**O eixo do canal endêmico é `posicao`, não `semana_epi`.** A temporada vai de
julho a junho e atravessa a virada do ano: a SE 27 vem *antes* da SE 1. Ordenar
por semana epidemiológica desenha a segunda metade da temporada antes da
primeira — e o gráfico continua parecendo normal. Use `posicao` no eixo e mostre
`semana_epi` só como rótulo.

**A semana epidemiológica é a do SINAN, que começa no domingo.** Não é a semana
ISO. Usar `isocalendar()` colocaria 48% dos casos na semana errada.

**Cache de 5 minutos** nas respostas. Se corrigirem algo e não aparecer na hora,
é isso — não é erro.

**Coordenada é `[longitude, latitude]`** nas detecções, ordem do GeoJSON. Nos
casos vêm em colunas separadas para não haver dúvida.

---

## Do lado de cá: como o banco é carregado

Para quem for mexer no pipeline:

```bash
npm run dados            # gera public/data/casos_dengue.json
npm run banco:exportar   # deriva db/carga.sql daquele JSON
npm run teste:banco      # 20 testes: privacidade estrutural e coerência
npm run banco:aplicar    # aplica no D1 (precisa das credenciais da conta)
```

O exportador lê o **mesmo JSON que o dashboard consome**, em vez de gerar SQL
direto do `gerar_dados.py`. Duas representações do mesmo dado divergem no dia em
que alguém mexe numa e esquece a outra — e um painel mostrando um número
enquanto o outro mostra outro é o pior defeito possível numa apresentação com
duas frentes. Derivando do arquivo publicado, a única divergência possível é a
carga estar velha, e há teste para isso.

Para testar sem tocar na nuvem:

```bash
npm run banco:local      # cria e carrega um D1 local
npm run api:local        # sobe a API em http://127.0.0.1:8787
```
