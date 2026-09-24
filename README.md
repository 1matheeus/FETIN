# 🚁 AeroScan — Drone + IA para Detecção de Focos de Dengue

> Projeto FETIN 2026 — Equipe 49
> Detecção automática de focos de dengue (piscinas e pneus com água parada) via
> drone com visão computacional YOLOv8, com painel web de vigilância e API de
> dados epidemiológicos.

**Painel ao vivo:** https://1matheeus.github.io/FETIN/dashboard/index.html
**Guia de apresentação (MacBook + GPS do celular):** [GUIA_APRESENTACAO_MAC.md](GUIA_APRESENTACAO_MAC.md)

---

## 📊 Resultados do Modelo

| Métrica | Valor | Meta |
|---------|-------|------|
| **mAP@50** | **95.6%** | 60% ✅ |
| Precision | 91.2% | — |
| Recall | 92.3% | — |
| mAP@50-95 | 64.8% | — |

> Treinado com 6.749 imagens aéreas em 50 épocas usando YOLOv8, com 2 classes: `pool` e `tire`.
> Este é o modelo `runs/drone_v1/`, o que `demo.py` e `drone/detectar_foco.py` carregam.

### Retreinos em andamento (`drone_v2` e `drone_v3`)

| Execução | Modelo | Dataset | Resultado (validação) |
|----------|--------|---------|-----------------------|
| `drone_v1` | YOLOv8n, 50 épocas | 6.749 imagens | mAP@50 **95.6%** — em uso |
| `drone_v2` | YOLOv8s, até 80 épocas | ampliado (+ dataset de pneus `tire-detection-xum3o`) | parou por early stopping na época 45 (melhor: época 30) — mAP@50 **80.9%** (`pool` 91.2%, `tire` 70.6%), mAP@50-95 46.5% |
| `drone_v3` | YOLOv8n, até 50 épocas, `patience=15` | ampliado | treino em andamento — sem métricas ainda |

Os números do v2 **não são comparáveis** com os do v1: o conjunto de validação
é outro (272 imagens / 1.044 objetos) e mais difícil — o principal ponto fraco
é `pneu` (recall de ~55%). Por isso os scripts continuam usando o `drone_v1`
até um retreino superar o atual num conjunto de validação comparável. Curvas,
matriz de confusão e `args.yaml` de cada execução ficam em `runs/drone_v*/`.

---

## 🎯 O Problema e a Solução

O Brasil registra milhões de casos de dengue por ano. A identificação manual de
focos — piscinas abandonadas e pneus com água parada — é lenta, cara e depende
de agentes de saúde indo casa a casa.

O AeroScan é um sistema de drone com IA que sobrevoa áreas de risco e detecta
automaticamente esses focos em imagens aéreas, localizando cada um no mapa e
alimentando um painel de vigilância para as equipes de saúde priorizarem as
vistorias.

---

## 🔄 Como o projeto funciona, ponta a ponta

1. O drone (ou uma câmera de teste) grava, e `drone/detectar_foco.py` processa
   cada frame com o modelo YOLOv8.
2. Um foco (piscina ou pneu) detectado com confiança acima de 60% inicia uma
   contagem; se mantiver essa confiança por 3 segundos seguidos, o foco é
   **confirmado** (evita alarme falso de um único frame ruim).
3. A localização de cada foco confirmado vem da fonte mais precisa disponível,
   nesta ordem: **GPS real do celular via rede** → GPS de um módulo serial
   físico → localização por Wi-Fi do sistema operacional → geolocalização por
   IP → `0.0, 0.0` como último recurso. Detalhes na seção
   [Detecção persistente e localização](#-detecção-persistente-com-gps-modo-drone-em-campo).
4. Antes de qualquer foto ir para o disco, ela passa pelo borrão de rostos de
   `drone/blur_lgpd.py` — nenhuma imagem sai do processo sem anonimização
   (mais em [Privacidade e LGPD](#-privacidade-e-lgpd)).
5. O foco (com foto, se a anonimização deu certo) é salvo na Área de
   Trabalho/Desktop do computador, sempre no mesmo arquivo
   `focos_detectados_mvp.csv` — cada nova detecção só adiciona uma linha nele.
6. Se a variável de ambiente `AEROSCAN_TOKEN` estiver definida, o mesmo foco
   também é publicado direto na **API de vigilância** (`POST
   /api/deteccoes` — pasta `api/`), foto incluída (guardada num bucket R2).
   Isso é o que faz o foco aparecer no dashboard **para qualquer pessoa que
   abra o site**, sem precisar de nenhuma ação manual. É melhor esforço: se
   a rede falhar, o CSV local já foi salvo de qualquer forma.
7. Sem token, ou como reserva se a API estiver fora do ar: o botão
   **"Importar focos"** (seção Mapa de risco do dashboard) deixa selecionar
   o CSV + as fotos da Área de Trabalho manualmente — mas só entram no mapa
   **daquela sessão do navegador**, não ficam salvos para outras pessoas.
8. Em paralelo, o dashboard consome essa mesma **API real** de casos de
   dengue e detecções (Cloudflare Worker + D1 + R2 — pasta `api/`), com
   fallback automático para os CSVs locais e depois para dados estáticos se
   a API não responder.

---

## 🗂️ Estrutura do Repositório

```
FETIN/
├── datasets/
│   └── unified/                 ← Dataset unificado (6.749 imagens)
│       ├── train/ valid/ test/
│       └── data.yaml
├── runs/
│   ├── drone_v1/
│   │   └── weights/
│   │       └── best.pt          ← Modelo em uso (mAP@50 95.6%) ⭐
│   ├── drone_v2/                 ← Retreino YOLOv8s, dataset ampliado (ver Resultados)
│   └── drone_v3/                 ← Retreino em andamento
├── train.py                      ← Treino (YOLOv8, augmentações para vista aérea)
├── download_datasets.py          ← Baixa os datasets do Roboflow
├── unify_datasets.py             ← Unifica os datasets em datasets/unified/
├── train_drone_v2.log / train_drone_v3.log   ← Logs dos retreinos
├── .github/workflows/tests.yml   ← CI: testes de anonimização e do schema do banco
├── dashboard/
│   ├── index.html                ← Painel web completo (login, mapa, casos, gráficos) ⭐
│   ├── gerar_mapa.py              ← Gera o mapa Folium estático (mapa_aeroscan.html)
│   ├── areas_risco_mvp.csv
│   ├── casos_dengue_mvp.csv
│   ├── focos_detectados_mvp.csv
│   └── marcadores_mapa_mvp.geojson
├── drone/
│   ├── detectar_foco.py          ← Detecção persistente com localização (GPS/rede) ⭐
│   ├── blur_lgpd.py               ← Anonimização de rosto (DNN) antes de gravar qualquer foto
│   ├── instalar_modelo_dnn.py     ← Baixa os pesos do detector de rostos (obrigatório 1x por PC)
│   └── testar_anonimizacao.py     ← Testes que travam o caminho de gravação de imagem
├── api/                          ← API de vigilância epidemiológica (Cloudflare Worker + D1 + R2)
│   ├── worker/index.js
│   ├── db/schema.sql
│   ├── dados/                     ← snapshot dos dados publicados (ver PROVENIENCIA.md)
│   └── docs/api-banco.md          ← guia de consumo da API
├── demo.py                       ← Script de demo com câmera ao vivo
├── iniciar_deteccao.bat           ← Atalho Windows para abrir a detecção com um clique
├── GUIA_APRESENTACAO_MAC.md       ← Roteiro passo a passo para apresentar num MacBook
├── requirements.txt
└── README.md
```

### API de vigilância (opcional)

O dashboard tenta primeiro uma API real (`api/`, Cloudflare Worker + banco D1)
com uma base simulada, mas geograficamente real, de casos e bairros de Santa
Rita do Sapucaí (Censo 2022 do IBGE + OpenStreetMap); se ela não responder,
cai automaticamente nos CSVs locais e depois em dados estáticos.

A API segrega dado sensível como o SINAN faz: a tabela pública (`casos`) só
tem sexo, faixa etária, célula geográfica de ~150 m e datas — nunca nome ou
endereço exato. Ver [`api/README.md`](api/README.md) para rodar localmente
sem conta e sem rede, e [`api/docs/api-banco.md`](api/docs/api-banco.md) para
os endpoints e o formato de consumo.

---

## ⚙️ Como Rodar em Qualquer PC

**Pré-requisitos:** Python 3.9+ → [python.org](https://python.org) | Git → [git-scm.com](https://git-scm.com)

```bash
# 1. Clonar o repositório
git clone https://github.com/1matheeus/FETIN.git
cd FETIN

# 2. Criar e ativar um ambiente virtual (recomendado)
python -m venv venv
venv\Scripts\activate        # Windows
source venv/bin/activate     # Linux/macOS

# 3. Instalar dependências
pip install -r requirements.txt

# 4. Baixar os pesos do detector de rostos (uma vez por computador)
python drone/instalar_modelo_dnn.py
```

> ⚠️ **O passo 4 é obrigatório.** Os pesos do detector de rostos (~10 MB) não
> vão para o git. Sem eles a anonimização falha fechada — de propósito — e
> `drone/detectar_foco.py` e o `S` do `demo.py` **deixam de salvar fotos**
> (o foco ainda entra no CSV, só sem imagem).

### Demo com câmera ao vivo

```bash
python demo.py
```

Aponte a câmera para imagens aéreas de piscinas ou pneus — o modelo detecta e
mostra as caixinhas em tempo real. Pressione `Q` para sair ou `S` para salvar
um screenshot (a foto passa pelo borrão de rostos antes de ser salva).

No Windows, também dá para abrir a detecção persistente (veja a seção
seguinte) com um clique duplo em [`iniciar_deteccao.bat`](iniciar_deteccao.bat)
— ele já ativa o venv e roda com o modo de GPS/localização por rede ligado.

### Detecção em imagem ou vídeo

```python
from ultralytics import YOLO

model = YOLO('runs/drone_v1/weights/best.pt')

results = model.predict('sua_imagem.jpg', conf=0.25)  # imagem
results = model.predict('video_drone.mp4', conf=0.25, save=True)  # vídeo
```

---

## 🛰️ Detecção persistente com GPS (modo drone em campo)

```bash
python drone/detectar_foco.py --gps-rede 192.168.0.42:11123
```

| Flag | Descrição | Padrão |
|------|-----------|--------|
| `--gps-rede` | `IP:porta` do celular transmitindo GPS real pela rede (ex.: `192.168.0.42:11123`) | — |
| `--porta` | Porta serial do GPS de módulo externo (Linux/Mac: `/dev/ttyUSB0`, Windows: `COM3`) | auto |
| `--conf` | Confiança mínima para considerar detecção | `0.60` |
| `--tempo` | Segundos mantendo o threshold para confirmar foco | `3` |
| `--camera` | Índice da câmera | `0` |
| `--sem-gps` | Modo sem GPS para testes em bancada | — |
| `--sem-rede` | Não tenta localização por rede (Wi-Fi do SO / IP) como alternativa | — |
| `--saida` | Pasta onde salvar o CSV e as fotos | Área de Trabalho |
| `--api` | URL base da API de vigilância, para publicar cada foco automaticamente | a API em produção |
| `--sem-api` | Não publica as detecções na API — fica só no CSV/fotos local | — |
| `--token-api` | Token de cadastro da API (Bearer). Prefira a variável de ambiente `AEROSCAN_TOKEN` | `$AEROSCAN_TOKEN` |

Com o token definido, cada foco confirmado aparece sozinho no dashboard, para
qualquer pessoa — sem token, funciona do mesmo jeito de sempre, só ficando no
CSV local até alguém importar manualmente.

### De onde vem a localização de cada foco

Sem um módulo GPS físico conectado, cada foco ainda pode ganhar uma
localização real. O script tenta, em ordem:

1. **GPS real do celular via rede** (`--gps-rede`, recomendado) — o celular
   roda um app que transmite as sentenças NMEA do GPS dele (o chip de
   satélite de verdade) por TCP na rede local; o script lê essa transmissão
   como se fosse um GPS serial. Precisão de ~5-20 m, testada na prática — a
   mesma de qualquer app de mapa no celular.
   - **iPhone:** app "GPS2IP" (ou similar).
   - **Android:** um app de "NMEA sobre TCP/rede", como o **GPS Tether
     Server** (testado e funcionando neste projeto).
   - Celular e computador precisam estar na **mesma rede Wi-Fi** — em locais
     com Wi-Fi público (isolamento de cliente costuma bloquear a conexão
     direta entre os dois aparelhos), use um hotspot pessoal só para os dois.
   - Passo a passo completo (incluindo apresentação num MacBook) em
     [GUIA_APRESENTACAO_MAC.md](GUIA_APRESENTACAO_MAC.md).
2. **GPS serial de verdade** (`--porta`), se um módulo GPS físico estiver
   conectado.
3. **Localização por rede via Wi-Fi do sistema operacional** (o mesmo serviço
   que o Mapas e o Clima do SO usam) — fallback automático se nenhuma das
   opções acima estiver disponível.

   | Sistema | Dependência | Ativar localização |
   |---------|-------------|---------------------|
   | Windows | `pip install winsdk` | Configurações > Privacidade e segurança > Localização: ligar "Serviços de localização" e permitir para apps de área de trabalho |
   | macOS | `pip install pyobjc-framework-CoreLocation` | Ajustes do Sistema > Privacidade e Segurança > Localização: ligar, e autorizar o Terminal quando o sistema pedir na primeira execução |

   **Atenção:** em cidades pequenas como Santa Rita do Sapucaí, esse serviço
   costuma ter pouca cobertura de Wi-Fi mapeada e na prática devolve sempre
   uma estimativa fixa "de cidade" (erro de ~1-2 km — o suficiente para cair
   no bairro vizinho errado, como testamos). Não é uma limitação do código,
   é do banco de dados de localização do sistema operacional nessa região —
   por isso o GPS do celular (opção 1) é a alternativa recomendada quando não
   há módulo GPS físico. A implementação de macOS foi testada apenas por
   código; teste na prática antes de apresentar.
4. **Geolocalização por IP público** como último recurso — bem menos precisa
   ainda (testamos e chegou a errar por ~250 km).
5. `0.0, 0.0` se nenhuma fonte for confiável (mais de 60 km de Santa Rita do
   Sapucaí) ou disponível — melhor um foco sem coordenada do que com uma
   coordenada errada.

O CSV (`focos_detectados_mvp.csv`) e as fotos (`foco_<tipo>_<data>.jpg`) ficam
sempre na Área de Trabalho — cada nova detecção só adiciona uma linha ao
mesmo arquivo. Para levar isso para o dashboard, use o botão **Importar
focos** (veja abaixo).

---

## 🖥️ Dashboard Web (Painel de Controle)

Painel completo em HTML/CSS/JS puro (sem build, sem dependências de
servidor) que reúne login, visão geral com indicadores e gráficos, mapa de
risco interativo e a lista de casos notificados — tudo numa única página.

**Acesse online:** https://1matheeus.github.io/FETIN/dashboard/index.html (GitHub Pages)

O painel carrega os dados **ao vivo**, tentando nesta ordem: (1) a API real
(`api/`, se configurada), (2) os CSVs de `dashboard/*.csv` via `fetch()`, (3)
dados estáticos embutidos como último recurso — com um aviso visível quando
cai no fallback final. Isso significa que qualquer foco novo gravado pelo
`drone/detectar_foco.py` aparece automaticamente ao recarregar a página (ou
via importação manual, para dados que ainda estão só no computador local).

**Rodando localmente:** navegadores bloqueiam `fetch()` de arquivos abertos
direto como `file://`, então dar duplo clique em `dashboard/index.html`
funciona, mas mostra um aviso e cai para dados de exemplo estáticos. Para ver
os dados reais dos CSVs localmente, sirva a pasta por um servidor simples:

```bash
cd dashboard
python -m http.server 8000
# depois abra http://localhost:8000
```

No GitHub Pages isso não é um problema — o fetch funciona normalmente.

**Login de demonstração:** usuário `Admin`, senha `admin123`. ⚠️ É uma
checagem **client-side apenas**, feita só para dar uma tela de login na demo
do MVP — a senha fica em texto puro no próprio HTML/JS e todo o conteúdo do
painel já está carregado no navegador antes do login (o login só alterna
`display`). Ela **não protege nenhum dado real** nem substitui autenticação
de verdade. Uma versão de produção precisaria de autenticação no backend
(`api/`, o Worker) que só libere dados sensíveis para quem tiver uma sessão
válida — nunca confiar em checagem feita no JS do cliente.

### O que tem no painel

- **Visão geral** — KPIs (casos no último mês, bairro com mais casos, foco
  mais comum, confiança média da IA), comparação com a semana anterior,
  ranking de bairros por risco, gráfico de casos ao longo do tempo e as
  métricas do modelo YOLOv8.
- **Mapa de risco** — zonas de calor por bairro, com três modos de
  visualização: pins agrupados (clustering), calor de todos os casos e calor
  por bairro (Leaflet.heat), além de um filtro por período (calendário) para
  ver a evolução ao longo do tempo. Cada foco detectado tem um link para a
  foto real da detecção (ou uma imagem de exemplo, se nenhuma foto foi
  importada). Centro, Jardim Santo Antônio, Jardim das Flores e Por do Sol
  têm contorno traçado nas ruas reais (OpenStreetMap via Overpass API); os
  demais bairros que vêm da API de vigilância ganham um território gerado a
  partir da própria distribuição espacial dos casos — um diagrama de Voronoi
  centrado no centróide de cada bairro, recortado na área da cidade, para
  que o mapa inteiro fique dividido em células vizinhas sem sobreposição.
- **Importar focos** — botão que abre um seletor de arquivos para escolher o
  `focos_detectados_mvp.csv` salvo pelo `drone/detectar_foco.py` na Área de
  Trabalho, junto com as fotos. O dashboard casa cada foco com sua foto pelo
  nome do arquivo e adiciona/atualiza os marcadores no mapa (só nesta sessão
  do navegador — para tornar permanente, substitua o CSV do repositório).
- **Resolver ou remover um foco** — no popup de cada foco do mapa: **"Marcar
  como resolvido"** (o marcador vira verde com um check, e o foco deixa de
  contar no score do bairro e no KPI de focos ativos; dá para **Reabrir**) e
  **"Remover"** (tira o foco do mapa; o botão **"Restaurar focos removidos"**
  traz de volta, e importar o CSV de novo não ressuscita um foco removido).
  ⚠️ Isso vale **só no navegador de quem clicou** (fica no `localStorage`):
  a API só aceita `GET`/`POST` em `/deteccoes`, então ainda não há onde
  gravar o status de forma compartilhada, e os dados originais nunca são
  apagados. Para outras pessoas verem, o Worker precisaria de uma rota
  `PATCH`/`DELETE` autenticada.
- **Casos notificados** — lista paginada (20 por página) com busca, filtro
  por status e por bairro (dropdown — a API de vigilância traz 58+ bairros),
  cadastro de novos casos (com foto opcional do local), edição e exclusão, e
  exportação para CSV.
- **Sobre o projeto** — metodologia, métricas do modelo e equipe.
- **Modo escuro**, navegação com scroll suave entre seções e exportação de
  relatório (PDF via impressão do navegador).

> Os dados de casos e focos são simulados para fins de demonstração do MVP,
> mas os bairros **Centro**, **Jardim Santo Antônio** e **Por do Sol** usam a
> localização oficial da Prefeitura de Santa Rita do Sapucaí (fonte
> OpenStreetMap). O bairro "Jardim das Flores" não corresponde a um bairro
> oficialmente registrado — é uma área simulada mantida do MVP original.

Também é possível gerar uma versão estática e mais simples do mapa (só o
mapa, sem o restante do painel) com Folium:

```bash
python dashboard/gerar_mapa.py
```

Isso cria `mapa_aeroscan.html` na raiz do projeto.

---

## 📦 Fontes do Dataset

| Dataset | Classe |
|---------|--------|
| pool-images/pool-detection-kmqaa | `pool` |
| swimming-pools/swimming-pools-detection | `pool` |
| piscina-piloto/swimming-pool-detection | `pool` |
| king-mongkut-.../tire-x4hgu | `tire` |
| testwheel/wheeltester | `tire` |
| computervision-f2lah/tire-detection-xum3o | `tire` (só usado nos retreinos v2/v3; a classe "Jammed Tires" é descartada por não ser claramente água parada) |

> O dataset `test-aobpj/pool-u62qo` foi retirado de `download_datasets.py`: não
> tem versão publicada no Roboflow, então não é baixável via API.

---

## 🔁 Como Retreinar

```bash
python download_datasets.py    # baixa os datasets (precisa de chave do Roboflow)
python unify_datasets.py       # unifica em datasets/unified/ (train/valid/test)
python train.py                # treina e grava em runs/<name>/
```

O `train.py` usa YOLOv8n, 640 px, augmentações pensadas para vista aérea
(rotação livre, flip vertical e horizontal) e `patience=15` (early stopping se
a validação não melhorar por 15 épocas). O nome da execução (`name=`) e o
dispositivo (`device="mps"`, para Apple Silicon) estão fixos no arquivo —
ajuste-os para o seu ambiente antes de rodar (`device=0` para GPU NVIDIA).

> ⚠️ Treinar exige GPU (ou Apple Silicon). Sem uma, use o Google Colab (T4
> gratuita) — o v2 (YOLOv8s) levou ~7 h no Mac do Rander; o YOLOv8n é bem mais
> rápido.

---

## 🔒 Privacidade e LGPD

Nenhuma foto é gravada em disco sem passar antes pelo borrão de rostos. Tanto
o `drone/detectar_foco.py` (foto do foco confirmado) quanto o `demo.py`
(screenshot com a tecla `S`) chamam `anonimizar()` do `drone/blur_lgpd.py`
imediatamente antes do `cv2.imwrite` — o frame original nunca chega ao disco.

O comportamento é **falha fechada**: se a anonimização não puder rodar (por
exemplo, se os pesos do detector de rostos não foram baixados com
`python drone/instalar_modelo_dnn.py`), a foto não é salva e o foco entra no
CSV sem imagem. Perder a foto de um foco é um problema pequeno; publicar o
rosto de um morador não é.

A API de vigilância (`api/`) aplica o mesmo princípio nos dados de casos:
segrega em vez de omitir, como o SINAN — a tabela pública nunca carrega nome
ou endereço exato, só sexo, faixa etária, célula geográfica de ~150 m e
datas. Detalhes em [`api/README.md`](api/README.md).

Três limites que vale declarar, porque a detecção de rosto não é perfeita:

- O detector é uma rede neural (SSD sobre ResNet-10, `res10_300x300`), mais
  robusta que o Haar cascade usado antes em rosto pequeno, ângulo fechado e
  pouca luz — mas nenhum detector é perfeito: rosto muito pequeno, de costas
  ou parcialmente coberto ainda pode passar sem ser borrado.
- O borrão cobre rosto, não os demais identificadores que uma imagem aérea
  pode conter — placa de veículo, número de casa, correspondência à vista.
- A verificação está travada por `drone/testar_anonimizacao.py`. Rode antes
  de qualquer alteração no caminho de gravação de imagem (a CI do GitHub
  Actions roda esse teste, e o do schema do banco, a cada push):

```bash
python drone/testar_anonimizacao.py
```

---

## 🛠️ Tecnologias

- [YOLOv8](https://github.com/ultralytics/ultralytics) — Detecção de objetos
- [Roboflow](https://roboflow.com) — Gerenciamento de datasets
- [OpenCV](https://opencv.org) — Processamento de imagem
- [Folium](https://python-visualization.github.io/folium/) — Mapa estático gerado em Python
- [Leaflet](https://leafletjs.com) + Leaflet.heat + Leaflet.markercluster — Mapa interativo do dashboard web
- [d3-delaunay](https://github.com/d3/d3-delaunay) — Geração de territórios de bairro por Voronoi
- [Cloudflare Workers](https://workers.cloudflare.com) + [D1](https://developers.cloudflare.com/d1/) + [R2](https://developers.cloudflare.com/r2/) — API de vigilância epidemiológica (R2 guarda as fotos das detecções)
- [GitHub Actions](https://docs.github.com/actions) — CI dos testes de anonimização e do banco
- [winsdk](https://pypi.org/project/winsdk/) / [pyobjc-framework-CoreLocation](https://pypi.org/project/pyobjc-framework-Cocoa/) — Localização por rede (Windows/macOS)
- [Python 3.10+](https://python.org)

---

## 👥 Equipe

| Nome | GitHub |
|------|--------|
| Rander D. Lemos | [@RanderDLemos](https://github.com/RanderDLemos) |
| Eduardo F. Guimarães | [@EduardoFGuimaraes](https://github.com/EduardoFGuimaraes) |
| Matheus Borges Mariano | [@1matheeus](https://github.com/1matheeus) |
| Matheus Reis | *GitHub a confirmar* |
