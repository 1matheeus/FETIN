/**
 * API de vigilância — Cloudflare Worker sobre D1.
 *
 * Serve os dados para as duas frentes do projeto. O dashboard React deste
 * repositório continua lendo os JSON estáticos; o dashboard da outra equipe
 * consome esta API.
 *
 * Rotas em `/api/*`. Qualquer outro caminho é servido como arquivo estático
 * pelo próprio Workers, sem passar por aqui.
 *
 * ---------------------------------------------------------------------------
 * POR QUE A INCIDÊNCIA É CALCULADA AQUI, E NÃO GUARDADA
 * ---------------------------------------------------------------------------
 * A incidência anualizada de um recorte de três meses não é a do período
 * inteiro. Guardar o número no banco o deixaria a um JOIN de distância de ser
 * exibido ao lado de um filtro que não o produziu — e um painel mostrando
 * "incidência 3.652" com o filtro em "últimos 30 dias" é pior que não mostrar
 * nada, porque parece certo.
 *
 * Então a API recebe o período e recalcula. As mesmas duas regras do dashboard:
 *
 *   - anualização: casos / população × 100.000 × (12 / meses do recorte);
 *   - piso de 60 habitantes: abaixo disso a taxa é ruído (um caso em 15
 *     moradores vira 6.600 por 100 mil), e a resposta traz `null`, não um
 *     número grande.
 */

// Piso populacional abaixo do qual a taxa é ruído e não se calcula.
//
// SÃO DOIS NÚMEROS, e a primeira versão desta API usou 60 para os dois — o que
// fazia 81 células aparecerem com taxa no dashboard e como `null` na API. Duas
// telas do mesmo projeto discordando sobre o mesmo território é exatamente o
// defeito que este banco existe para evitar.
//
// Os valores vêm de `src/App.jsx`: bairro usa o padrão de `POP_MINIMA` (60);
// célula passa 25 explicitamente. A diferença é deliberada — a célula de 150 m
// é pequena por construção, e exigir 60 moradores nela apagaria do mapa boa
// parte da área urbana de baixa densidade, que é justamente onde a priorização
// geográfica tem mais a dizer.
//
// Se mudar lá, mude aqui. `scripts/testar_banco.py` confere que os dois
// arquivos concordam.
const POP_MINIMA_BAIRRO = 60
const POP_MINIMA_CELULA = 25

// O dashboard da outra frente roda noutra origem (GitHub Pages). Sem CORS o
// navegador bloqueia toda chamada antes mesmo de ela sair — e o erro aparece
// no console deles, não aqui, o que torna o diagnóstico desnecessariamente
// difícil para quem estiver do outro lado.
const CORS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type, Authorization',
  'Access-Control-Max-Age': '86400',
}

/**
 * Campos que o formulário de cadastro pode enviar e que NÃO vão para a tabela
 * `casos`. Eles são desviados para `casos_identificados`, que nenhuma rota de
 * leitura consulta.
 *
 * A separação acontece AQUI, no servidor, e não no formulário. É deliberado: o
 * cadastro da outra frente pode mandar tudo o que já coleta, sem mudar uma
 * linha, e a fronteira é aplicada de qualquer forma. Se dependesse de o
 * cliente separar, dependeria de o cliente lembrar.
 */
const CAMPOS_IDENTIFICADOS = [
  'nome', 'data_nascimento', 'endereco', 'numero', 'complemento',
  'cep', 'telefone', 'cartao_sus', 'lon_domicilio', 'lat_domicilio',
  'registrado_por',
]

const CAMPOS_PUBLICOS = [
  'sexo', 'faixa_etaria', 'bairro', 'celula', 'setor',
  'data_inicio_sintomas', 'data_entrada',
  'unidade_notificadora', 'classificacao', 'sorotipo', 'desfecho', 'confirmado',
]

const json = (dados, status = 200) =>
  new Response(JSON.stringify(dados), {
    status,
    headers: {
      'Content-Type': 'application/json; charset=utf-8',
      // Mesma lógica do public/_headers: dado sem hash no nome precisa de
      // cache curto, senão uma correção não chega a quem já abriu a página.
      'Cache-Control': 'public, max-age=300, must-revalidate',
      ...CORS,
    },
  })

const erro = (mensagem, status = 400) => json({ erro: mensagem }, status)

/** Meses cobertos pelo recorte — o mesmo cálculo do dashboard. */
function mesesNoPeriodo(inicio, fim) {
  if (!inicio || !fim) return 12
  const [ai, mi] = inicio.split('-').map(Number)
  const [af, mf] = fim.split('-').map(Number)
  return Math.max(1, (af - ai) * 12 + (mf - mi) + 1)
}

const ISO = /^\d{4}-\d{2}-\d{2}$/

/**
 * Monta o WHERE a partir dos parâmetros da query.
 *
 * Tudo entra como bind (`?`), nunca por interpolação. O dado aqui é fictício,
 * mas o hábito é o que viaja para o próximo projeto — e este código foi
 * escrito para ser lido por outra equipe.
 */
function filtros(url) {
  const cond = []
  const args = []
  const p = url.searchParams

  const desde = p.get('desde')
  const ate = p.get('ate')
  if (desde) {
    if (!ISO.test(desde)) throw new Error('`desde` deve ser AAAA-MM-DD')
    cond.push('data_entrada >= ?'); args.push(desde)
  }
  if (ate) {
    if (!ISO.test(ate)) throw new Error('`ate` deve ser AAAA-MM-DD')
    cond.push('data_entrada <= ?'); args.push(ate)
  }
  for (const [param, coluna] of [
    ['bairro', 'bairro'], ['celula', 'celula'], ['sexo', 'sexo'],
    ['faixa_etaria', 'faixa_etaria'], ['classificacao', 'classificacao'],
    ['sorotipo', 'sorotipo'],
  ]) {
    const v = p.get(param)
    if (v) { cond.push(`${coluna} = ?`); args.push(v) }
  }

  return {
    where: cond.length ? 'WHERE ' + cond.join(' AND ') : '',
    args,
    desde, ate,
  }
}

/** Agrega casos por território e devolve a incidência anualizada do recorte. */
async function incidencia(db, url, chave, tabela, popMinima) {
  const { where, args, desde, ate } = filtros(url)
  const fator = 12 / mesesNoPeriodo(desde, ate)

  const { results } = await db.prepare(`
    SELECT t.${chave} AS territorio,
           t.populacao AS populacao,
           COUNT(c.id) AS casos,
           SUM(CASE WHEN c.classificacao = 'Dengue grave' THEN 1 ELSE 0 END) AS graves,
           SUM(CASE WHEN c.desfecho = 'Óbito' THEN 1 ELSE 0 END) AS obitos
      FROM ${tabela} t
      LEFT JOIN (SELECT * FROM casos ${where}) c ON c.${chave} = t.${chave}
     GROUP BY t.${chave}
     ORDER BY casos DESC
  `).bind(...args).all()

  const linhas = results.map((r) => ({
    [chave]: r.territorio,
    populacao: r.populacao,
    casos: r.casos,
    graves: r.graves ?? 0,
    obitos: r.obitos ?? 0,
    // `null`, não zero e não um número grande: abaixo do piso a taxa não
    // significa nada, e quem consome precisa conseguir distinguir "sem taxa"
    // de "taxa baixa".
    incidencia: r.populacao >= popMinima
      ? Math.round((r.casos / r.populacao) * 100000 * fator * 10) / 10
      : null,
  }))

  return json({
    recorte: { desde: desde ?? null, ate: ate ?? null,
               meses: mesesNoPeriodo(desde, ate), fator_anualizacao: fator },
    metodo: {
      formula: 'casos / população × 100.000 × (12 / meses do recorte)',
      populacao_minima: popMinima,
      nota: 'incidencia = null significa população abaixo do piso, não taxa zero',
    },
    total: linhas.length,
    dados: linhas,
  })
}

/** Semana epidemiológica do SINAN — começa no DOMINGO, não é a semana ISO. */
function semanaEpidemiologica(iso) {
  const d = new Date(iso + 'T12:00:00Z')
  const domingoDaSE1 = (ano) => {
    const primeiro = new Date(Date.UTC(ano, 0, 1, 12))
    const dom = new Date(primeiro)
    dom.setUTCDate(primeiro.getUTCDate() - primeiro.getUTCDay())
    const sabado = new Date(dom)
    sabado.setUTCDate(dom.getUTCDate() + 6)
    if (sabado.getUTCDate() < 4 && dom.getUTCFullYear() < ano) {
      dom.setUTCDate(dom.getUTCDate() + 7)
    }
    return dom
  }
  let ano = d.getUTCFullYear()
  let dom1 = domingoDaSE1(ano)
  if (d < dom1) { ano -= 1; dom1 = domingoDaSE1(ano) }
  else if (d >= domingoDaSE1(ano + 1)) { ano += 1; dom1 = domingoDaSE1(ano) }
  const semana = Math.floor((d - dom1) / 604800000) + 1
  return { ano, semana }
}

/** Temporada julho–junho e a posição da semana dentro dela. */
function posicaoNaTemporada(iso) {
  const d = new Date(iso + 'T12:00:00Z')
  const mes = d.getUTCMonth() + 1
  const temporada = mes >= 7 ? d.getUTCFullYear() : d.getUTCFullYear() - 1
  const inicio = new Date(Date.UTC(temporada, 6, 1, 12))
  inicio.setUTCDate(inicio.getUTCDate() - inicio.getUTCDay())
  const domingo = new Date(d)
  domingo.setUTCDate(d.getUTCDate() - d.getUTCDay())
  return {
    temporada,
    posicao: Math.min(53, Math.max(1, Math.floor((domingo - inicio) / 604800000) + 1)),
  }
}

/** Faixa etária a partir da data de nascimento — a idade exata não é publicada. */
function faixaEtaria(nascimento, referencia) {
  if (!nascimento) return null
  const n = new Date(nascimento + 'T12:00:00Z')
  const r = new Date(referencia + 'T12:00:00Z')
  let idade = r.getUTCFullYear() - n.getUTCFullYear()
  const m = r.getUTCMonth() - n.getUTCMonth()
  if (m < 0 || (m === 0 && r.getUTCDate() < n.getUTCDate())) idade -= 1
  if (idade < 0 || idade > 130) return null
  if (idade >= 60) return '60+'
  const base = Math.floor(idade / 10) * 10
  return `${base}-${base + 9}`
}

/**
 * Célula da grade que contém a coordenada.
 *
 * Dois passos porque as células não são retângulos exatos em lon/lat — a grade
 * foi construída em UTM e reprojetada, então deforma cerca de 1 m e caixas
 * vizinhas se sobrepõem numa faixa estreita. Filtra pelas caixas candidatas e
 * desempata pelo centroide mais próximo: determinístico, erro sub-métrico numa
 * célula de 150 m.
 *
 * Fora da grade devolve null — e o caso é registrado assim mesmo, com aviso.
 * Perder a notificação porque o endereço caiu fora do perímetro urbano seria
 * pior que registrá-la sem célula.
 */
async function celulaDe(db, lon, lat) {
  const r = await db.prepare(`
    SELECT celula, bairro FROM celulas
     WHERE ? BETWEEN lon_min AND lon_max
       AND ? BETWEEN lat_min AND lat_max
     ORDER BY (lon_centro - ?) * (lon_centro - ?)
            + (lat_centro - ?) * (lat_centro - ?)
     LIMIT 1
  `).bind(lon, lat, lon, lon, lat, lat).first()
  return r ?? null
}

/**
 * Cadastro de caso. É aqui que a anonimização acontece.
 *
 * O corpo pode trazer tudo o que o formulário coleta. O que é identificador
 * vai para `casos_identificados`; o que é publicável vai para `casos`; e a
 * resposta devolve SÓ a versão publicável — para que quem chamou veja
 * exatamente o que o mundo vai ver.
 */
async function cadastrar(request, env) {
  // Token compartilhado. Ver docs/api-banco.md: isto barra escrita acidental e
  // varredura automática, NÃO uma pessoa determinada que leia o JavaScript do
  // formulário. Para dado fictício de feira é a troca certa; para dado de
  // gente, não é — precisaria de sessão de usuário no servidor.
  const token = (request.headers.get('Authorization') || '').replace(/^Bearer\s+/i, '')
  if (!env.TOKEN_CADASTRO) {
    return erro('Cadastro desabilitado: o segredo TOKEN_CADASTRO não foi definido.', 503)
  }
  if (token !== env.TOKEN_CADASTRO) {
    return erro('Token de cadastro ausente ou inválido.', 401)
  }

  let corpo
  try {
    corpo = await request.json()
  } catch {
    return erro('Corpo inválido: esperado JSON.')
  }

  const entrada = corpo.data_entrada || new Date().toISOString().slice(0, 10)
  const sintomas = corpo.data_inicio_sintomas || entrada
  if (!ISO.test(entrada) || !ISO.test(sintomas)) {
    return erro('`data_entrada` e `data_inicio_sintomas` devem ser AAAA-MM-DD')
  }
  if (sintomas > entrada) {
    return erro('`data_inicio_sintomas` não pode ser depois de `data_entrada`')
  }
  if (!['M', 'F'].includes(corpo.sexo)) {
    return erro('`sexo` deve ser "M" ou "F"')
  }

  // Célula: aceita pronta, ou deduz da coordenada do domicílio. Deduzir é o
  // caminho normal — o formulário sabe o endereço, não a célula.
  let celula = corpo.celula ?? null
  let bairro = corpo.bairro ?? null
  let avisoCelula = null
  const lon = Number(corpo.lon_domicilio ?? corpo.longitude)
  const lat = Number(corpo.lat_domicilio ?? corpo.latitude)
  if (!celula && Number.isFinite(lon) && Number.isFinite(lat)) {
    const achada = await celulaDe(env.DB, lon, lat)
    if (achada) { celula = achada.celula; bairro = bairro ?? achada.bairro }
    else avisoCelula = 'Coordenada fora da grade urbana: caso registrado sem célula.'
  }

  // Faixa etária a partir da data de nascimento. A idade exata fica na tabela
  // identificada; o que é publicado é a faixa.
  const faixa = corpo.faixa_etaria || faixaEtaria(corpo.data_nascimento, entrada)
  if (!faixa) {
    return erro('Informe `faixa_etaria` ou `data_nascimento` válida.')
  }

  const { ano, semana } = semanaEpidemiologica(entrada)
  const { temporada, posicao } = posicaoNaTemporada(entrada)
  const [a, m] = entrada.split('-').map(Number)

  // Coordenada publicada: sorteio uniforme DENTRO da célula, não o domicílio.
  // Sorteio e não ruído somado à posição real — jitter gaussiano manteria a
  // coordenada verdadeira como valor esperado, sorteio uniforme não.
  let lonPub = null
  let latPub = null
  if (celula) {
    const c = await env.DB.prepare(
      'SELECT lon_min, lon_max, lat_min, lat_max FROM celulas WHERE celula = ?'
    ).bind(celula).first()
    if (c) {
      lonPub = Math.round((c.lon_min + Math.random() * (c.lon_max - c.lon_min)) * 1e6) / 1e6
      latPub = Math.round((c.lat_min + Math.random() * (c.lat_max - c.lat_min)) * 1e6) / 1e6
    }
  }

  const id = corpo.id || `SRS-${crypto.randomUUID().slice(0, 8).toUpperCase()}`

  const publico = {
    id,
    sexo: corpo.sexo,
    faixa_etaria: faixa,
    bairro, celula,
    setor: corpo.setor ?? null,
    cidade: corpo.cidade ?? 'Santa Rita do Sapucaí',
    uf: corpo.uf ?? 'MG',
    lon_celula: lonPub, lat_celula: latPub,
    data_inicio_sintomas: sintomas,
    data_entrada: entrada,
    ano: a, mes: m, ano_mes: entrada.slice(0, 7),
    ano_epidemiologico: ano, semana_epidemiologica: semana,
    temporada, semana_da_temporada: posicao,
    unidade_notificadora: corpo.unidade_notificadora ?? null,
    classificacao: corpo.classificacao ?? 'Dengue clássica',
    sorotipo: corpo.sorotipo ?? null,
    sintomas: JSON.stringify(corpo.sintomas ?? []),
    desfecho: corpo.desfecho ?? null,
    confirmado: corpo.confirmado === false ? 0 : 1,
  }

  const colunas = Object.keys(publico)
  const identificado = {}
  for (const campo of CAMPOS_IDENTIFICADOS) {
    if (corpo[campo] !== undefined && corpo[campo] !== null && corpo[campo] !== '') {
      identificado[campo] = corpo[campo]
    }
  }

  // As duas escritas num lote só: se a segunda falhar, a primeira não fica
  // órfã. Um caso publicado sem o registro identificado correspondente seria
  // uma notificação que a equipe de campo não consegue localizar.
  const comandos = [
    env.DB.prepare(
      `INSERT INTO casos (${colunas.join(', ')}) ` +
      `VALUES (${colunas.map(() => '?').join(', ')})`
    ).bind(...colunas.map((k) => publico[k])),
  ]
  if (Object.keys(identificado).length) {
    const ci = ['caso_id', ...Object.keys(identificado), 'registrado_em']
    comandos.push(env.DB.prepare(
      `INSERT INTO casos_identificados (${ci.join(', ')}) ` +
      `VALUES (${ci.map(() => '?').join(', ')})`
    ).bind(id, ...Object.values(identificado), new Date().toISOString()))
  }
  await env.DB.batch(comandos)

  return json({
    ok: true,
    // Devolve só a versão publicável, de propósito: quem cadastrou vê
    // exatamente o que o mundo vai ver, e a diferença fica evidente na tela.
    caso: { ...publico, sintomas: JSON.parse(publico.sintomas) },
    identificacao: {
      armazenada: Object.keys(identificado).length > 0,
      campos: Object.keys(identificado),
      tabela: 'casos_identificados',
      nota: 'Segregada. Nenhuma rota de leitura desta API consulta esta tabela.',
    },
    ...(avisoCelula ? { aviso: avisoCelula } : {}),
  }, 201)
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url)

    if (request.method === 'OPTIONS') {
      return new Response(null, { status: 204, headers: CORS })
    }
    if (!url.pathname.startsWith('/api/')) {
      // Não deveria chegar aqui: os assets estáticos são servidos antes. Se
      // chegou, o caminho não existe como arquivo nem como rota.
      return erro('Não encontrado', 404)
    }
    if (!env.DB) {
      return erro('Banco não vinculado a este Worker (binding DB ausente).', 503)
    }

    try {
      const rota = url.pathname.replace(/^\/api\//, '').replace(/\/$/, '')

      if (request.method === 'POST') {
        if (rota !== 'casos') {
          return erro(`POST só existe em /api/casos. Recebido: /api/${rota}`, 404)
        }
        return await cadastrar(request, env)
      }
      if (request.method !== 'GET') {
        return erro('Métodos aceitos: GET e POST /api/casos.', 405)
      }

      switch (rota) {
        case '':
        case 'rotas':
          return json({
            nome: 'API de vigilância epidemiológica — Santa Rita do Sapucaí/MG',
            aviso: 'Casos FICTÍCIOS, gerados por simulação. A geografia é real.',
            rotas: {
              'GET /api/meta': 'metadados: período, população, fontes, privacidade',
              'GET /api/bairros': 'população por bairro',
              'GET /api/celulas': 'as 539 células da grade de 150 m',
              'GET /api/casos': 'casos anonimizados; filtros: desde, ate, bairro, celula, sexo, faixa_etaria, classificacao, sorotipo, limite, offset',
              'GET /api/incidencia/bairros': 'incidência anualizada por bairro NO RECORTE',
              'GET /api/incidencia/celulas': 'idem, por célula de 150 m',
              'GET /api/canal': 'canal endêmico: mediana e quartis por semana',
              'GET /api/deteccoes': 'focos detectados pela frente aérea',
              'POST /api/casos': 'cadastro de caso; exige Authorization: Bearer <token>. Separa o identificado do publicável e devolve só o publicável',
            },
            privacidade: {
              publicado: CAMPOS_PUBLICOS,
              segregado: CAMPOS_IDENTIFICADOS,
              nota: 'Os campos segregados vão para `casos_identificados`, que '
                + 'nenhuma rota de leitura consulta. A separação é feita pelo '
                + 'servidor: o formulário pode mandar tudo o que coleta.',
            },
            documentacao: 'docs/api-banco.md no repositório',
          })

        case 'meta': {
          const { results } = await env.DB.prepare('SELECT chave, valor FROM meta').all()
          const m = {}
          for (const r of results) {
            try { m[r.chave] = JSON.parse(r.valor) } catch { m[r.chave] = r.valor }
          }
          return json(m)
        }

        case 'bairros': {
          const { results } = await env.DB.prepare(
            'SELECT bairro, populacao FROM bairros ORDER BY bairro').all()
          return json({ total: results.length, dados: results })
        }

        case 'celulas': {
          const { results } = await env.DB.prepare(
            'SELECT celula, bairro, populacao, n_ancoras FROM celulas ORDER BY celula'
          ).all()
          return json({ total: results.length, dados: results })
        }

        case 'casos': {
          const { where, args } = filtros(url)
          // Teto de 5000 por resposta. Sem ele, um cliente distraído pede a
          // base inteira a cada interação e a página trava no celular do
          // visitante — que é onde isto vai rodar.
          const limite = Math.min(Number(url.searchParams.get('limite')) || 2000, 5000)
          const offset = Number(url.searchParams.get('offset')) || 0

          const total = await env.DB.prepare(
            `SELECT COUNT(*) AS n FROM casos ${where}`).bind(...args).first()
          const { results } = await env.DB.prepare(
            `SELECT * FROM casos ${where} ORDER BY data_entrada LIMIT ? OFFSET ?`
          ).bind(...args, limite, offset).all()

          return json({
            total: total.n,
            devolvidos: results.length,
            limite, offset,
            dados: results.map((c) => ({ ...c, sintomas: JSON.parse(c.sintomas || '[]') })),
          })
        }

        case 'incidencia/bairros':
          return incidencia(env.DB, url, 'bairro', 'bairros', POP_MINIMA_BAIRRO)
        case 'incidencia/celulas':
          return incidencia(env.DB, url, 'celula', 'celulas', POP_MINIMA_CELULA)

        case 'canal': {
          const { results } = await env.DB.prepare(
            'SELECT posicao, semana_epi, q1, mediana, q3 FROM canal_endemico ORDER BY posicao'
          ).all()
          return json({
            // A posição é o eixo, não a semana epidemiológica: a temporada vai
            // de julho a junho e atravessa a virada do ano, então a SE 27 vem
            // ANTES da SE 1. Ordenar por SE embaralha a cronologia.
            eixo: 'posicao (1 a 53, a partir da semana que contém 1º de julho)',
            total: results.length,
            dados: results,
          })
        }

        case 'deteccoes': {
          const { results } = await env.DB.prepare(
            'SELECT * FROM deteccoes ORDER BY deteccao_id').all()
          return json({
            origem: 'AeroScan — YOLOv8 (Equipe 49)',
            total: results.length,
            dados: results,
          })
        }

        default:
          return erro(`Rota desconhecida: /api/${rota}. Veja GET /api/rotas.`, 404)
      }
    } catch (e) {
      // A mensagem do filtro é útil para quem chama (formato de data errado);
      // qualquer outra é interna e não deve vazar detalhe do banco.
      const doUsuario = e instanceof Error && e.message.startsWith('`')
      return erro(doUsuario ? e.message : 'Erro ao consultar o banco', doUsuario ? 400 : 500)
    }
  },
}
