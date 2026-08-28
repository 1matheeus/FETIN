# 📋 Guia — Rodando o AeroScan no MacBook com GPS do celular (dia da feira)

Roteiro para apresentar a detecção de focos ao vivo, usando o GPS real de um
celular (via rede) em vez de um módulo GPS físico. Testado e documentado a
partir dos testes feitos com um Android rodando **GPS Tether Server**.

---

## 1. Montar a rede isolada (hotspot)

Redes de eventos/feiras costumam ter "isolamento de cliente" ativado, que
impede um celular de falar diretamente com um notebook mesmo estando na
mesma rede. Para evitar isso, use um hotspot pessoal só para os dois
aparelhos da demonstração:

1. No celular que vai virar o hotspot: ative o **Compartilhamento de
   Internet / Hotspot Pessoal** e defina uma senha.
2. No MacBook: conecte no Wi-Fi desse hotspot.
3. No Android (o que roda o GPS Tether Server): conecte no mesmo hotspot.

> ⚠️ O IP do Android muda toda vez que a rede muda — depois de conectar no
> hotspot, pegue o IP novo (passo 4), não reaproveite um IP de um teste
> anterior em outra rede.

---

## 2. Preparar o ambiente Python no MacBook

Fazer **com antecedência**, não no dia da apresentação:

```bash
git clone https://github.com/1matheeus/FETIN.git
cd FETIN
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

- `source venv/bin/activate` é o equivalente do `venv\Scripts\activate` do
  Windows — precisa rodar isso toda vez que abrir um Terminal novo, antes
  dos comandos dos passos seguintes.
- Se der erro instalando `ultralytics` ou `opencv-python` (comum em Macs
  com chip Apple Silicon — M1/M2/M3), guarde a mensagem de erro para
  resolver com calma antes do dia da feira.

## 3. Testar a câmera uma vez (webcam do Mac)

```bash
python demo.py
```

Na **primeira vez**, o macOS pergunta "Terminal gostaria de acessar a
câmera" — clique em **Permitir**. Se perder esse popup sem responder, vá em
`Ajustes do Sistema > Privacidade e Segurança > Câmera` e ative manualmente
para o Terminal. Teste isso com antecedência — não é bom descobrir esse
popup no meio da demonstração.

## 4. Iniciar o GPS Tether Server no Android

1. Abra o app, conceda a permissão de localização ("permitir sempre" se for
   oferecido).
2. Escolha o modo **TCP** (não UDP/broadcast) se o app perguntar.
3. Ative/inicie o servidor.
4. Anote o **IP** e a **porta** mostrados na tela (vão ser diferentes dos
   valores usados em testes anteriores, por causa da nova rede do hotspot).

> Se em algum momento voltarem a usar um iPhone com o GPS2IP Lite: em
> iPhones com Dynamic Island (ex.: 15 Pro), o botão de ativar o servidor
> pode ficar visualmente atrás dos ícones do sistema. Nesse caso, use
> `Ajustes > Acessibilidade > Voice Control > "Show numbers"` para tocar no
> botão por comando de voz em vez de mirar visualmente.

## 5. Rodar a detecção de verdade

```bash
python drone/detectar_foco.py --gps-rede IP_DO_ANDROID:PORTA --sem-rede
```

- `--gps-rede` conecta no celular e lê o GPS real dele (precisão de
  satélite, ~5-20 m) — é a fonte de localização mais precisa que o projeto
  tem, bem melhor que a localização por Wi-Fi do sistema operacional
  (~1-2 km, pode até cair no bairro errado numa cidade pequena).
- `--sem-rede` evita que o script também tente a localização por Wi-Fi do
  macOS como respaldo — sem isso, na primeira execução o macOS pode abrir
  um popup pedindo permissão de localização para o Terminal, o que
  interromperia a demonstração. Como já temos o GPS do celular, esse
  respaldo não é necessário.
- Aponte a câmera para a piscina/pneu por ~3 segundos para confirmar um
  foco (o tempo de confirmação existe para evitar falsos positivos de um
  único frame).

## 6. Encerrar e levar para o dashboard

1. Aperte **Q** para fechar a janela da câmera.
2. O CSV e as fotos ficam na Área de Trabalho do Mac
   (`~/Desktop/focos_detectados_mvp.csv` e as fotos `foco_<tipo>_<data>.jpg`
   — todas já passaram pelo borrão de rostos do LGPD antes de serem
   salvas).
3. Abra o dashboard (https://1matheeus.github.io/FETIN/dashboard/index.html
   ou local), vá em **Mapa de risco** e clique em **"Importar focos"** —
   selecione o CSV e as fotos da Área de Trabalho juntos. O dashboard casa
   cada foco com a foto pelo nome do arquivo e coloca o marcador no mapa.

---

## Referência rápida de comandos

```bash
# uma vez, antes da feira
git clone https://github.com/1matheeus/FETIN.git
cd FETIN
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# no dia, depois de conectar o hotspot e ligar o GPS Tether Server
source venv/bin/activate
python drone/detectar_foco.py --gps-rede IP_DO_ANDROID:PORTA --sem-rede
```
