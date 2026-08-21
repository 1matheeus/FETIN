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
├── demo.py                ← Script de demo com câmera ao vivo
├── requirements.txt
└── README.md
```

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

---

## 🖥️ Dashboard Web (Painel de Controle)

Painel completo em HTML/CSS/JS puro (sem build, sem dependências de servidor) que reúne login, visão
geral com indicadores e gráficos, mapa de risco interativo e a lista de casos notificados — tudo numa
única página.

**Como abrir:** basta dar duplo clique em `dashboard/index.html` (ou usar a extensão Live Server) e
abrir no navegador. Não precisa instalar nada.

**Login de demonstração:** usuário `Admin`, senha `admin123` (autenticação simples no front-end, apenas
para fins de demonstração do MVP — não usar com dados reais sem um backend de verdade).

### O que tem no painel

- **Visão geral** — KPIs (casos no último mês, bairro com mais casos, foco mais comum, confiança média
  da IA), comparação com a semana anterior, ranking de bairros por risco, gráfico de casos ao longo do
  tempo e as métricas do modelo YOLOv8.
- **Mapa de risco** — zonas de calor com o contorno real de cada bairro (traçado a partir das ruas do
  OpenStreetMap via Overpass API), com três modos de visualização: pins agrupados (clustering), calor
  de todos os casos e calor por bairro (Leaflet.heat), além de um filtro por período para ver a evolução
  semana a semana. Cada foco detectado tem um link para a imagem de exemplo da detecção.
- **Casos notificados** — lista completa com busca e filtros, cadastro de novos casos (com foto opcional
  do local), edição e exclusão, e exportação para CSV.
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

Todas as imagens passam por anonimização automática antes de serem armazenadas. Rostos são detectados e borrados em tempo real — nenhum dado biométrico é salvo ou transmitido.

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
