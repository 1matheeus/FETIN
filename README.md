# 🚁 AeroScan — Drone + IA para Detecção de Focos de Dengue

> Projeto FETIN 2026 — Equipe 49  
> Detecção automática de focos de dengue (piscinas e pneus) via drone com visão computacional YOLOv8.

> Baseado no projeto original de [@RanderDLemos](https://github.com/RanderDLemos/FETIN), com o painel
> web (`dashboard/index.html`) adicionado nesta versão.

---

## 📊 Resultados do Modelo

| Métrica | Valor | Meta |
|---------|-------|------|
| **mAP@50** | **95.6%** | 60% ✅ |
| Precision | 91.2% | — |
| Recall | 92.3% | — |
| mAP@50-95 | 64.8% | — |

> Treinado com 6.749 imagens aéreas em 50 épocas usando YOLOv8, com 2 classes: `pool` e `tire`.

---

## 🎯 O Problema e a Solução

O Brasil registra milhões de casos de dengue por ano. A identificação manual de focos — piscinas abandonadas e pneus com água parada — é lenta, cara e depende de agentes de saúde indo casa a casa.

O AeroScan é um sistema de drone com IA que sobrevoa áreas de risco e detecta automaticamente esses focos em imagens aéreas, gerando um mapa interativo para as equipes de saúde priorizarem as vistorias.

---

## 🔄 Como o projeto funciona

1. Drone voa sobre área de risco com câmera e módulo GPS conectados
2. `drone/detectar_foco.py` processa cada frame com o modelo YOLOv8
3. Foco detectado com confiança > 60% inicia contagem de 3 segundos
4. Se mantiver acima de 60% por 3 segundos → foco confirmado
5. GPS lê as coordenadas reais do módulo externo (protocolo NMEA)
6. A foto passa pelo borrão de rostos antes de ir para o disco
7. Foco (com foto) é salvo na Área de Trabalho — sempre no mesmo arquivo
   `focos_detectados_mvp.csv`, uma linha adicionada por detecção
8. No dashboard, o botão **Importar focos** (seção Mapa de risco) permite selecionar esse CSV + as
   fotos da Área de Trabalho para colocá-los no mapa

---

## 🗂️ Estrutura do Repositório

```
FETIN/
├── datasets/
│   └── unified/           ← Dataset unificado (6.749 imagens)
│       ├── train/
│       ├── valid/
│       ├── test/
│       └── data.yaml
├── runs/
│   └── drone_v1/
│       └── weights/
│           └── best.pt    ← Modelo treinado ⭐
├── dashboard/
│   ├── index.html          ← Painel web completo (login, mapa, casos, gráficos) ⭐
│   ├── gerar_mapa.py        ← Gera o mapa Folium estático (mapa_aeroscan.html)
│   ├── areas_risco_mvp.csv
│   ├── casos_dengue_mvp.csv
│   └── focos_detectados_mvp.csv
├── api/                    ← API de vigilância epidemiológica (Cloudflare Worker + D1) — ver api/README.md
├── demo.py                ← Script de demo com câmera ao vivo
├── requirements.txt
└── README.md
```

### API de vigilância (opcional)

O dashboard tenta primeiro uma API real (`api/`, Cloudflare Worker + banco D1) com a base completa de
casos e bairros de Santa Rita do Sapucaí; se ela não responder, cai automaticamente nos CSV e depois nos
dados estáticos — ver detalhes em [`api/README.md`](api/README.md) e [`api/docs/api-banco.md`](api/docs/api-banco.md).

---

## ⚙️ Como Rodar em Qualquer PC

**Pré-requisitos:** Python 3.9+ → [python.org](https://python.org) | Git → [git-scm.com](https://git-scm.com)

```bash
# 1. Clonar o repositório
git clone https://github.com/1matheeus/FETIN.git
cd FETIN

# 2. Instalar dependências
pip install -r requirements.txt
```

### Demo com câmera ao vivo
```bash
python demo.py
```
Aponte a câmera para imagens aéreas de piscinas ou pneus — o modelo detecta e mostra as caixinhas em tempo real. Pressione `Q` para sair ou `S` para salvar um screenshot.

### Detecção em imagem ou vídeo
```python
from ultralytics import YOLO

model = YOLO('runs/drone_v1/weights/best.pt')

results = model.predict('sua_imagem.jpg', conf=0.25)  # imagem
results = model.predict('video_drone.mp4', conf=0.25, save=True)  # vídeo
```

### Detecção persistente com GPS (modo drone em campo)
```bash
python drone/detectar_foco.py --porta /dev/ttyUSB0
```
| Flag | Descrição | Padrão |
|------|-----------|--------|
| `--porta` | Porta serial do GPS (Linux/Mac: `/dev/ttyUSB0`, Windows: `COM3`) | auto |
| `--conf` | Confiança mínima para considerar detecção | `0.60` |
| `--tempo` | Segundos mantendo o threshold para confirmar foco | `3` |
| `--camera` | Índice da câmera | `0` |
| `--sem-gps` | Modo sem GPS para testes em bancada | — |
| `--saida` | Pasta onde salvar o CSV e as fotos | Área de Trabalho |

O CSV (`focos_detectados_mvp.csv`) e as fotos (`foco_<tipo>_<data>.jpg`) ficam sempre na Área de
Trabalho — cada nova detecção só adiciona uma linha ao mesmo arquivo. Para levar isso para o
dashboard, use o botão **Importar focos** (veja abaixo).

---

## 🖥️ Dashboard Web (Painel de Controle)

Painel completo em HTML/CSS/JS puro (sem build, sem dependências de servidor) que reúne login, visão
geral com indicadores e gráficos, mapa de risco interativo e a lista de casos notificados — tudo numa
única página.

**Acesse online:** https://1matheeus.github.io/FETIN/dashboard/index.html (GitHub Pages)

O painel carrega os casos e focos **ao vivo** a partir de `dashboard/casos_dengue_mvp.csv` e
`dashboard/focos_detectados_mvp.csv` via `fetch()`. Isso significa que qualquer foco novo gravado pelo
`drone/detectar_foco.py` aparece automaticamente ao recarregar a página.

**Rodando localmente:** navegadores bloqueiam `fetch()` de arquivos abertos direto como `file://`, então
dar duplo clique em `dashboard/index.html` funciona, mas mostra um aviso e cai para dados de exemplo
estáticos. Para ver os dados reais dos CSVs localmente, sirva a pasta por um servidor simples:

```bash
cd dashboard
python -m http.server 8000
# depois abra http://localhost:8000
```

No GitHub Pages isso não é um problema — o fetch funciona normalmente.

**Login de demonstração:** usuário `Admin`, senha `admin123` (autenticação simples no front-end, apenas
para fins de demonstração do MVP — não usar com dados reais sem um backend de verdade).

### O que tem no painel

- **Visão geral** — KPIs (casos no último mês, bairro com mais casos, foco mais comum, confiança média
  da IA), comparação com a semana anterior, ranking de bairros por risco, gráfico de casos ao longo do
  tempo e as métricas do modelo YOLOv8.
- **Mapa de risco** — zonas de calor por bairro, com três modos de visualização: pins agrupados
  (clustering), calor de todos os casos e calor por bairro (Leaflet.heat), além de um filtro por período
  (calendário) para ver a evolução ao longo do tempo. Cada foco detectado tem um link para a foto real da
  detecção (ou uma imagem de exemplo, se nenhuma foto foi importada). Centro, Jardim Santo Antônio,
  Jardim das Flores e Por do Sol têm contorno traçado nas ruas reais (OpenStreetMap via Overpass API);
  os demais bairros que vêm da API de vigilância (ver abaixo) ganham um território gerado a partir da
  própria distribuição espacial dos casos — um diagrama de Voronoi centrado no centróide de cada bairro,
  recortado na área da cidade, para que o mapa inteiro fique dividido em células vizinhas sem sobreposição.
- **Importar focos** — botão que abre um seletor de arquivos para escolher o
  `focos_detectados_mvp.csv` salvo pelo `drone/detectar_foco.py` na Área de Trabalho, junto com as
  fotos. O dashboard casa cada foco com sua foto pelo nome do arquivo e adiciona/atualiza os marcadores
  no mapa (só nesta sessão do navegador — para tornar permanente, substitua o CSV do repositório).
- **Casos notificados** — lista paginada (20 por página) com busca, filtro por status e por bairro
  (dropdown — a API de vigilância traz 58+ bairros, chip por bairro não era mais viável), cadastro de
  novos casos (com foto opcional do local), edição e exclusão, e exportação para CSV.
- **Sobre o projeto** — metodologia, métricas do modelo e equipe.
- **Modo escuro**, navegação com scroll suave entre seções e exportação de relatório (PDF via impressão
  do navegador).

> Os dados de casos e focos são simulados para fins de demonstração do MVP (mesma base do
> `dashboard/*.csv`), mas os bairros **Centro**, **Jardim Santo Antônio** e **Por do Sol** usam a
> localização oficial da Prefeitura de Santa Rita do Sapucaí (fonte OpenStreetMap). O bairro "Jardim das
> Flores" não corresponde a um bairro oficialmente registrado — é uma área simulada mantida do MVP
> original.

Também é possível gerar uma versão estática e mais simples do mapa (só o mapa, sem o restante do
painel) com Folium:

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

---

## 🔁 Como Retreinar

```python
from ultralytics import YOLO

model = YOLO('yolov8n.pt')
model.train(
    data='datasets/unified/data.yaml',
    epochs=50,
    imgsz=640,
    batch=16,
    name='drone_v1',
    flipud=0.5,
    fliplr=0.5,
    degrees=45,
    scale=0.5,
)
```

> ⚠️ Requer GPU. Use o Google Colab (T4 gratuita) — tempo estimado: 30–40 minutos.

---

## 🔒 Privacidade e LGPD

Nenhuma foto é gravada em disco sem passar antes pelo borrão de rostos. Tanto o
`drone/detectar_foco.py` (foto do foco confirmado) quanto o `demo.py`
(screenshot com a tecla `S`) chamam `anonimizar()` do `drone/blur_lgpd.py`
imediatamente antes do `cv2.imwrite` — o frame original nunca chega ao disco.

O comportamento é **falha fechada**: se a anonimização não puder rodar (OpenCV
sem os cascades, por exemplo), a foto não é salva e o foco entra no CSV sem
imagem. Perder a foto de um foco é um problema pequeno; publicar o rosto de um
morador não é.

Três limites que vale declarar, porque a detecção não é perfeita:

- O detector é Haar cascade frontal + perfil. Rosto muito pequeno (< 30 px),
  de costas, ou sob ângulo fechado pode passar sem ser borrado.
- O borrão cobre rosto, não os demais identificadores que uma imagem aérea pode
  conter — placa de veículo, número de casa, correspondência à vista.
- A verificação está travada por `drone/testar_anonimizacao.py`. Rode antes de
  qualquer alteração no caminho de gravação de imagem:

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
- [Python 3.10](https://python.org)

---

## 👥 Equipe

| Nome | GitHub |
|------|--------|
| Rander D. Lemos | [@RanderDLemos](https://github.com/RanderDLemos) |
| Matheus Borges Mariano | [@1matheeus](https://github.com/1matheeus) |
| [Adicionar demais membros] | — |
