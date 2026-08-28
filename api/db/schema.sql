-- Esquema do banco de vigilância — Cloudflare D1 (SQLite).
--
-- Aplicar:
--     npx wrangler d1 execute vigilancia --remote --file=db/schema.sql
--
-- ---------------------------------------------------------------------------
-- A FRONTEIRA DE PRIVACIDADE ESTÁ NO ESQUEMA, NÃO NUMA CONVENÇÃO
-- ---------------------------------------------------------------------------
-- Até aqui a regra "nome, endereço, idade exata e coordenada de domicílio não
-- são publicados" morava no `anonimizar()` do gerar_dados.py e em cinco testes.
-- Isso funciona enquanto todo mundo passa por aquele caminho.
--
-- Com um banco compartilhado entre duas frentes, o caminho deixa de ser um só:
-- o dashboard da outra equipe tem cadastro de casos, e um formulário com campo
-- de endereço grava endereço. A regra precisa deixar de depender de quem
-- escreve.
--
-- Por isso a tabela `casos` **não tem colunas** para paciente, endereço, idade
-- exata, CPF, cartão do SUS, telefone ou logradouro. Não é validação que pode
-- ser contornada: é ausência. Um INSERT com essas colunas falha com erro de
-- SQL, no momento da escrita, para quem escreveu.
--
-- A idade aparece só como `faixa_etaria` — idade exata mais célula mais data é
-- quase-identificador num município de 42 mil habitantes.
--
-- A coordenada é sorteada uniformemente dentro da célula de 150 m, não é a
-- posição do domicílio. Está aqui porque o mapa de calor precisa de um ponto;
-- o nome das colunas diz isso.

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------- territórios

CREATE TABLE IF NOT EXISTS bairros (
  bairro      TEXT PRIMARY KEY,
  populacao   REAL NOT NULL,
  -- Casos, graves, óbitos e incidência NÃO ficam aqui.
  --
  -- São derivados: mudam conforme o período filtrado, e a incidência de um
  -- recorte de 3 meses não é a do período inteiro. Guardar o número agregado
  -- convidaria alguém a exibi-lo junto de um filtro que não o produziu — que é
  -- exatamente o erro que a anualização existe para evitar.
  --
  -- A API calcula sob demanda, a partir dos casos e desta população.
  CHECK (populacao >= 0)
);

CREATE TABLE IF NOT EXISTS celulas (
  celula      TEXT PRIMARY KEY,          -- 'C025009'
  bairro      TEXT REFERENCES bairros(bairro),
  populacao   REAL NOT NULL,             -- dasimétrica, Censo 2022
  n_ancoras   INTEGER NOT NULL DEFAULT 0,

  -- Caixa envolvente e centroide, para o cadastro converter coordenada em
  -- célula sem precisar da geometria completa dentro do Worker.
  --
  -- A grade foi construída em UTM e reprojetada para WGS84, então as células
  -- NÃO são retângulos perfeitos em lon/lat: deformam cerca de 1 m. Isso
  -- significa que caixas vizinhas se sobrepõem numa faixa estreita, e um ponto
  -- na borda pode cair em duas.
  --
  -- Por isso a busca é em dois passos: filtra pelas caixas que contêm o ponto,
  -- e entre as candidatas escolhe a de centroide mais próximo. Determinístico,
  -- e o erro máximo é sub-métrico numa célula de 150 m — irrelevante, já que a
  -- coordenada publicada é sorteada dentro da célula de qualquer forma.
  lon_min     REAL, lon_max REAL,
  lat_min     REAL, lat_max REAL,
  lon_centro  REAL, lat_centro REAL,
  CHECK (populacao >= 0)
);

CREATE INDEX IF NOT EXISTS idx_celulas_bairro ON celulas(bairro);
CREATE INDEX IF NOT EXISTS idx_celulas_caixa  ON celulas(lon_min, lon_max, lat_min, lat_max);

-- --------------------------------------------------------------------- casos

CREATE TABLE IF NOT EXISTS casos (
  id                     TEXT PRIMARY KEY,   -- 'SRS-00001'

  -- demografia mínima
  sexo                   TEXT NOT NULL CHECK (sexo IN ('M', 'F')),
  faixa_etaria           TEXT NOT NULL,      -- '20-29' — nunca idade exata

  -- localização na granularidade publicável
  bairro                 TEXT REFERENCES bairros(bairro),
  celula                 TEXT REFERENCES celulas(celula),
  setor                  TEXT,               -- setor censitário do IBGE
  cidade                 TEXT NOT NULL DEFAULT 'Santa Rita do Sapucaí',
  uf                     TEXT NOT NULL DEFAULT 'MG',

  -- Ponto SORTEADO dentro da célula, não o domicílio. O sufixo está no nome
  -- para que ninguém leia isto como endereço em nenhum lugar do código.
  lon_celula             REAL,
  lat_celula             REAL,

  -- tempo
  data_inicio_sintomas   TEXT NOT NULL,      -- ISO 'AAAA-MM-DD'
  data_entrada           TEXT NOT NULL,
  ano                    INTEGER NOT NULL,
  mes                    INTEGER NOT NULL CHECK (mes BETWEEN 1 AND 12),
  ano_mes                TEXT NOT NULL,
  -- Semana epidemiológica do SINAN: começa no DOMINGO, não é a semana ISO.
  ano_epidemiologico     INTEGER NOT NULL,
  semana_epidemiologica  INTEGER NOT NULL CHECK (semana_epidemiologica BETWEEN 1 AND 53),
  -- Temporada julho–junho, e a posição DENTRO dela. A posição existe porque a
  -- temporada atravessa a virada do ano: a SE 27 vem antes da SE 1, e usar a
  -- SE como eixo desenha a segunda metade antes da primeira.
  temporada              INTEGER NOT NULL,
  semana_da_temporada    INTEGER NOT NULL CHECK (semana_da_temporada BETWEEN 1 AND 53),

  -- clínica
  unidade_notificadora   TEXT,
  classificacao          TEXT NOT NULL,
  sorotipo               TEXT,
  sintomas               TEXT,               -- JSON array
  desfecho               TEXT,
  confirmado             INTEGER NOT NULL DEFAULT 1 CHECK (confirmado IN (0, 1)),

  CHECK (data_inicio_sintomas <= data_entrada)
);

CREATE INDEX IF NOT EXISTS idx_casos_data     ON casos(data_entrada);
CREATE INDEX IF NOT EXISTS idx_casos_bairro   ON casos(bairro);
CREATE INDEX IF NOT EXISTS idx_casos_celula   ON casos(celula);
CREATE INDEX IF NOT EXISTS idx_casos_temporada ON casos(temporada, semana_da_temporada);

-- ------------------------------------------------------- canal endêmico

CREATE TABLE IF NOT EXISTS canal_endemico (
  posicao     INTEGER PRIMARY KEY CHECK (posicao BETWEEN 1 AND 53),
  semana_epi  INTEGER,
  q1          REAL NOT NULL,
  mediana     REAL NOT NULL,
  q3          REAL NOT NULL,
  CHECK (q1 <= mediana AND mediana <= q3)
);

-- ------------------------------------------------ detecções da frente aérea

CREATE TABLE IF NOT EXISTS deteccoes (
  deteccao_id     TEXT PRIMARY KEY,          -- 'FD-001'
  celula          TEXT REFERENCES celulas(celula),
  bairro          TEXT,
  classe          TEXT NOT NULL,             -- vocabulário do contrato
  classe_origem   TEXT,                      -- classe crua do modelo ('pool')
  confianca       REAL NOT NULL CHECK (confianca > 0 AND confianca <= 1),
  lon             REAL NOT NULL,
  lat             REAL NOT NULL,
  data_deteccao   TEXT,
  verificacao     TEXT NOT NULL DEFAULT 'pendente',
  origem_imagem   TEXT
  -- Sem proprietário, sem endereço do imóvel, sem nome de morador. Detecção
  -- aponta para criadouro, não para pessoa — e o operador do drone recebe a
  -- célula, nunca o endereço.
);

CREATE INDEX IF NOT EXISTS idx_deteccoes_celula ON deteccoes(celula);

-- ------------------------------------------------------------------ metadados

CREATE TABLE IF NOT EXISTS meta (
  chave  TEXT PRIMARY KEY,
  valor  TEXT NOT NULL
);

-- ---------------------------------------------------------------------------
-- DADO IDENTIFICADO — SEGREGADO, NUNCA PUBLICADO
-- ---------------------------------------------------------------------------
-- Esta tabela existe porque o cadastro de casos precisa dela: quem notifica um
-- caso sabe o nome e o endereço do paciente, e a equipe de campo precisa
-- reencontrar o caso depois. Fingir que esse dado não existe não o faz sumir —
-- faz ele ser guardado em algum lugar pior, tipo uma planilha solta.
--
-- É como o SINAN funciona de verdade: o dado identificado existe, com acesso
-- restrito, e o que circula para análise é a visão anonimizada.
--
-- AS TRÊS REGRAS QUE FAZEM ISSO SER SEGREGAÇÃO E NÃO TEATRO:
--
--   1. nenhuma rota da API de leitura consulta esta tabela. Há teste que varre
--      o `worker/index.js` procurando o nome dela fora do caminho de escrita;
--   2. o `exportar_para_banco.py` nunca escreve aqui — os 2000 casos
--      simulados não têm identificação para exportar, e é assim que deve ser;
--   3. a tabela `casos` continua sem colunas identificadoras. Quem quiser
--      juntar as duas precisa de acesso de escrita ao banco, que é o que
--      distingue "restrito" de "público".
--
-- Se um dia isto tocar dado real: esta tabela precisa de criptografia em
-- repouso, log de acesso e política de retenção. Nada disso está aqui. Para
-- dado fictício de feira, a segregação já demonstra o desenho; para dado de
-- gente, não basta.

CREATE TABLE IF NOT EXISTS casos_identificados (
  caso_id         TEXT PRIMARY KEY REFERENCES casos(id) ON DELETE CASCADE,

  -- Campos que o formulário da outra frente coleta.
  nome            TEXT,
  data_nascimento TEXT,                  -- a faixa etária publicada sai daqui
  endereco        TEXT,
  numero          TEXT,
  complemento     TEXT,
  cep             TEXT,
  telefone        TEXT,
  cartao_sus      TEXT,

  -- Coordenada do DOMICÍLIO. Diferente da `lon_celula`/`lat_celula` da tabela
  -- `casos`, que é sorteio dentro da célula. O nome diferencia de propósito:
  -- confundir as duas é o erro que apaga a anonimização sem ninguém notar.
  lon_domicilio   REAL,
  lat_domicilio   REAL,

  registrado_em   TEXT NOT NULL,
  registrado_por  TEXT                   -- unidade ou usuário que notificou
);
