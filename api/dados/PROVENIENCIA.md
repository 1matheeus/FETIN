# De onde vêm estes arquivos

Snapshot do dado publicado pela frente de **priorização geográfica**. O pipeline
que os **gera** não mora aqui — mora no repositório daquela frente, junto com os
scripts que baixam IBGE e OpenStreetMap, constroem a grade de 150 m e distribuem
a população por dasimetria.

| Arquivo | O que é |
|---|---|
| `casos_dengue.json` | 2000 casos simulados, já anonimizados, mais bairros, canal endêmico e série semanal |
| `geo/grade.geojson` | as 539 células de 150 m, com população do Censo 2022 |
| `deteccoes.json` | as 5 detecções do modelo YOLOv8 atribuídas à grade |

> ⚠️ **Os casos de dengue são fictícios**, gerados por simulação. Nenhuma
> informação real de paciente foi usada. A **geografia é real**: setores
> censitários e população vêm do Censo 2022 do IBGE; ruas e bairros do
> OpenStreetMap (ODbL).

## Por que um snapshot e não uma dependência

O `exportar_para_banco.py` lê estes arquivos e produz o SQL de carga. Ele
poderia buscá-los pela rede a cada execução, mas aí o banco só carregaria com
internet e com o outro deploy no ar — dois pontos de falha a mais num comando
que roda na véspera da feira.

O preço é que estes arquivos podem **envelhecer**. O `testar_banco.py` compara o
banco com o JSON que está aqui, então ele pega divergência entre os dois — mas
não pega o caso de *este* snapshot estar atrás do repositório de origem.

## Como atualizar

No repositório da priorização geográfica:

```bash
npm run dados          # regenera public/data/casos_dengue.json
```

E aqui:

```bash
cp <origem>/public/data/casos_dengue.json  dados/
cp <origem>/public/data/deteccoes.json     dados/
cp <origem>/public/data/geo/grade.geojson  dados/geo/

npm run banco:exportar
npm run teste
npm run banco:aplicar
```

O `npm run teste` **antes** do `banco:aplicar` não é zelo excessivo: ele confere
que a carga corresponde ao JSON e que nenhum campo identificador escapou. Custa
dois segundos e é a última chance de pegar isso antes de o dado subir.
