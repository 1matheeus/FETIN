"""
AeroScan — Detecção Persistente de Focos
Projeto FETIN 2026 — Equipe 49

Lógica:
  - IA detecta foco com confiança > 60%
  - Se mantiver por TEMPO_CONFIRMACAO segundos → confirma
  - Localização de cada foco, em ordem de prioridade:
      1) GPS real do módulo externo (serial/NMEA), se conectado
      2) Localização aproximada pela rede (IP público, nível de
         cidade — só usada se o GPS não estiver disponível/fixado)
      3) 0.0, 0.0 se nada estiver disponível (ex.: sem internet)
  - Salva o CSV e as fotos na Área de Trabalho (Desktop), sempre no
    mesmo arquivo — cada nova detecção só adiciona uma linha nele
  - Para levar os focos para o site, use o botão "Importar focos"
    do dashboard e selecione esse CSV (+ as fotos) na Área de Trabalho

Como usar:
  pip install ultralytics opencv-python pyserial
  python drone/detectar_foco.py

Flags opcionais:
  --porta /dev/ttyUSB0    porta serial do GPS (padrão: auto-detecta)
  --conf 0.60             confiança mínima (padrão: 0.60)
  --tempo 3               segundos para confirmar (padrão: 3)
  --camera 0              índice da câmera (padrão: 0)
  --sem-gps               modo sem GPS (usa coordenadas manuais)
  --sem-rede              não tenta localização aproximada pela rede (IP)
  --saida ~/Desktop       pasta onde salvar o CSV e as fotos (padrão: Área de Trabalho)
"""

import os
import cv2
import csv
import json
import time
import argparse
import threading
from pathlib import Path
from datetime import datetime
from ultralytics import YOLO

CONF_MINIMA       = 0.60
TEMPO_CONFIRMACAO = 3.0
CLASSES           = ['pool', 'tire']
MODELO_PATH       = 'runs/drone_v1/weights/best.pt'
CSV_NOME          = 'focos_detectados_mvp.csv'
CENTRO_CIDADE     = (-22.2535, -45.7040)  # Santa Rita do Sapucaí, MG
RAIO_MAXIMO_KM    = 60  # além disso, a localização por rede é descartada

def pasta_area_trabalho():
    """Área de Trabalho (Desktop) do usuário atual.

    Em máquinas Windows com o OneDrive fazendo backup de pastas conhecidas,
    a Área de Trabalho real fica em outro lugar (ex.: 'OneDrive\\Área de
    Trabalho') e pode até ter nome traduzido — não é sempre '~/Desktop'.
    No Windows, perguntamos ao registro do Shell qual é o caminho real.
    """
    if os.name == 'nt':
        try:
            import winreg
            chave = r'Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders'
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, chave) as k:
                caminho, _ = winreg.QueryValueEx(k, 'Desktop')
                caminho = Path(os.path.expandvars(caminho))
                if caminho.exists():
                    return caminho
        except Exception:
            pass
    for candidata in (Path.home() / 'Desktop', Path.home() / 'OneDrive' / 'Desktop'):
        if candidata.exists():
            return candidata
    return Path.home()  # último recurso


def distancia_km(p1, p2):
    """Distância aproximada (haversine) em km entre dois pontos (lat, lon)."""
    import math
    lat1, lon1 = math.radians(p1[0]), math.radians(p1[1])
    lat2, lon2 = math.radians(p2[0]), math.radians(p2[1])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = math.sin(dlat/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
    return 2 * 6371 * math.asin(math.sqrt(a))


def localizar_por_rede(timeout=4):
    """Localização aproximada a partir do IP público, via ipinfo.io.

    Não precisa de GPS nem de Wi-Fi especial — só de internet. É bem
    menos preciso que um GPS real: costuma acertar só o nível de
    cidade/região (pode errar por vários quilômetros, ou até acertar
    a cidade errada se a rede usa VPN/proxy). Usado só como um
    fallback melhor que 0.0, 0.0 quando não há GPS disponível.
    Faz uma única consulta HTTPS de saída para ipinfo.io — não envia
    nada além do que qualquer acesso à internet já revela (o IP).
    """
    try:
        import urllib.request
        with urllib.request.urlopen('https://ipinfo.io/json', timeout=timeout) as resp:
            dados = json.loads(resp.read().decode('utf-8'))
        loc = dados.get('loc')
        if not loc or ',' not in loc:
            return None
        lat_str, lon_str = loc.split(',', 1)
        return (float(lat_str), float(lon_str))
    except Exception:
        return None

class GPS:
    def __init__(self, porta=None, baudrate=9600):
        self.latitude  = None
        self.longitude = None
        self.fixado    = False
        self._porta    = porta
        self._baudrate = baudrate
        self._serial   = None
        self._thread   = None
        self._rodando  = False

    def iniciar(self):
        try:
            import serial
            import serial.tools.list_ports
            if not self._porta:
                portas = list(serial.tools.list_ports.comports())
                for p in portas:
                    if any(x in p.description.lower() for x in ['gps', 'uart', 'usb serial', 'ch340', 'cp210']):
                        self._porta = p.device
                        print(f'  🛰️  GPS detectado em: {self._porta}')
                        break
                if not self._porta and portas:
                    self._porta = portas[0].device
                    print(f'  🛰️  Tentando GPS em: {self._porta}')
            if not self._porta:
                print('  ⚠️  Nenhuma porta serial encontrada. Use --sem-gps.')
                return False
            self._serial = serial.Serial(self._porta, self._baudrate, timeout=1)
            self._rodando = True
            self._thread = threading.Thread(target=self._ler_loop, daemon=True)
            self._thread.start()
            print(f'  ✅ GPS conectado em {self._porta}')
            return True
        except ImportError:
            print('  ⚠️  pyserial não instalado. Rode: pip install pyserial')
            return False
        except Exception as e:
            print(f'  ⚠️  Erro ao conectar GPS: {e}')
            return False

    def _ler_loop(self):
        while self._rodando:
            try:
                linha = self._serial.readline().decode('ascii', errors='replace').strip()
                if linha.startswith('$GPGGA') or linha.startswith('$GNGGA'):
                    self._parsear_gga(linha)
                elif linha.startswith('$GPRMC') or linha.startswith('$GNRMC'):
                    self._parsear_rmc(linha)
            except:
                pass

    def _parsear_gga(self, sentenca):
        try:
            partes = sentenca.split(',')
            if len(partes) < 7 or partes[2] == '' or partes[4] == '':
                return
            lat_raw = float(partes[2])
            lat_dir = partes[3]
            lon_raw = float(partes[4])
            lon_dir = partes[5]
            qualidade = int(partes[6])
            lat_graus = int(lat_raw / 100)
            lat_min   = lat_raw - lat_graus * 100
            self.latitude = lat_graus + lat_min / 60
            if lat_dir == 'S':
                self.latitude = -self.latitude
            lon_graus = int(lon_raw / 100)
            lon_min   = lon_raw - lon_graus * 100
            self.longitude = lon_graus + lon_min / 60
            if lon_dir == 'W':
                self.longitude = -self.longitude
            self.fixado = qualidade > 0
        except:
            pass

    def _parsear_rmc(self, sentenca):
        try:
            partes = sentenca.split(',')
            if len(partes) < 7 or partes[3] == '' or partes[5] == '' or partes[2] != 'A':
                return
            lat_raw = float(partes[3])
            lat_dir = partes[4]
            lon_raw = float(partes[5])
            lon_dir = partes[6]
            lat_graus = int(lat_raw / 100)
            self.latitude = lat_graus + (lat_raw - lat_graus * 100) / 60
            if lat_dir == 'S':
                self.latitude = -self.latitude
            lon_graus = int(lon_raw / 100)
            self.longitude = lon_graus + (lon_raw - lon_graus * 100) / 60
            if lon_dir == 'W':
                self.longitude = -self.longitude
            self.fixado = True
        except:
            pass

    def parar(self):
        self._rodando = False
        if self._serial:
            self._serial.close()

    @property
    def posicao(self):
        return (self.latitude, self.longitude) if self.fixado else None


class RegistradorFocos:
    def __init__(self, saida_dir):
        self.saida_dir = Path(saida_dir)
        self.csv_path  = self.saida_dir / CSV_NOME
        self.saida_dir.mkdir(parents=True, exist_ok=True)
        self._contador = self._proximo_id()

    def _proximo_id(self):
        if not self.csv_path.exists():
            return 1
        try:
            with open(self.csv_path, newline='', encoding='utf-8') as f:
                linhas = list(csv.DictReader(f))
                if not linhas:
                    return 1
                ultimo = linhas[-1].get('id_foco', 'FD-000')
                return int(ultimo.replace('FD-', '')) + 1
        except:
            return 1

    def registrar(self, classe, confianca, latitude, longitude, imagem_path=None):
        id_foco = f'FD-{self._contador:03d}'
        self._contador += 1
        nova_linha = {
            'id_foco':            id_foco,
            'data_detectado':     datetime.now().strftime('%Y-%m-%d'),
            'tipo_foco':          'piscina' if classe == 'pool' else 'pneu',
            'classe_ia':          classe,
            'latitude':           round(latitude, 6),
            'longitude':          round(longitude, 6),
            'confianca_ia':       round(confianca, 4),
            'origem_imagem':      imagem_path or f'drone-{id_foco}.jpg',
            'status_verificacao': 'pendente',
            'id_area':            'AR-001',
        }
        # Sempre o mesmo arquivo: se já existe, só adiciona uma linha (append).
        existe = self.csv_path.exists()
        with open(self.csv_path, 'a', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=nova_linha.keys())
            if not existe:
                writer.writeheader()
            writer.writerow(nova_linha)
        print(f'\n  📍 FOCO REGISTRADO: {id_foco}')
        print(f'     Tipo:       {nova_linha["tipo_foco"]}')
        print(f'     Confiança:  {confianca:.1%}')
        print(f'     GPS:        {latitude:.6f}, {longitude:.6f}')
        print(f'     → Salvo em: {self.csv_path}')
        print(f'     → No site, clique em "Importar focos" e selecione esse CSV + a foto.\n')
        return id_foco


class DetectorPersistente:
    def __init__(self, conf_minima, tempo_confirmacao):
        self.conf_minima       = conf_minima
        self.tempo_confirmacao = tempo_confirmacao
        self._deteccoes_ativas = {}

    def atualizar(self, deteccoes_frame):
        agora = time.time()
        classes_no_frame = set()
        confirmados = []
        for classe, confianca in deteccoes_frame:
            if confianca < self.conf_minima:
                continue
            classes_no_frame.add(classe)
            if classe not in self._deteccoes_ativas:
                self._deteccoes_ativas[classe] = agora
            else:
                tempo_detectando = agora - self._deteccoes_ativas[classe]
                if tempo_detectando >= self.tempo_confirmacao:
                    confirmados.append((classe, confianca))
                    del self._deteccoes_ativas[classe]
        for classe in list(self._deteccoes_ativas.keys()):
            if classe not in classes_no_frame:
                del self._deteccoes_ativas[classe]
        return confirmados

    def progresso(self, classe):
        if classe not in self._deteccoes_ativas:
            return 0.0
        tempo = time.time() - self._deteccoes_ativas[classe]
        return min(1.0, tempo / self.tempo_confirmacao)


def main():
    parser = argparse.ArgumentParser(description='AeroScan — Detecção Persistente de Focos')
    parser.add_argument('--porta',   type=str,   default=None)
    parser.add_argument('--conf',    type=float, default=CONF_MINIMA)
    parser.add_argument('--tempo',   type=float, default=TEMPO_CONFIRMACAO)
    parser.add_argument('--camera',  type=int,   default=0)
    parser.add_argument('--sem-gps', action='store_true')
    parser.add_argument('--sem-rede', action='store_true',
                         help='Não tenta localização aproximada pela rede (IP) como alternativa ao GPS')
    parser.add_argument('--saida',   type=str,   default=None,
                         help='Pasta onde salvar o CSV e as fotos (padrão: Área de Trabalho)')
    args = parser.parse_args()

    saida_dir = Path(args.saida).expanduser() if args.saida else pasta_area_trabalho()

    print('\n🚁 AeroScan — Detecção Persistente de Focos')
    print('=' * 50)
    print(f'  Confiança mínima:  {args.conf:.0%}')
    print(f'  Tempo confirmação: {args.tempo}s')
    print(f'  Salvando em:       {saida_dir / CSV_NOME}')
    print('=' * 50)

    print('\n🤖 Carregando modelo...')
    if not Path(MODELO_PATH).exists():
        print(f'  ❌ Modelo não encontrado: {MODELO_PATH}')
        return
    model = YOLO(MODELO_PATH)
    print('  ✅ Modelo carregado')

    gps = GPS(porta=args.porta)
    gps_ativo = False
    if not args.sem_gps:
        print('\n🛰️  Inicializando GPS...')
        gps_ativo = gps.iniciar()
    else:
        print('\n⚠️  Modo sem GPS ativo')

    localizacao_rede = None
    if not args.sem_rede:
        print('\n🌐 Tentando localização aproximada pela rede (IP)...')
        candidata = localizar_por_rede()
        if not candidata:
            print('  ⚠️  Sem internet ou serviço indisponível — usarei 0.0, 0.0 se o GPS também falhar.')
        else:
            dist = distancia_km(candidata, CENTRO_CIDADE)
            if dist > RAIO_MAXIMO_KM:
                print(f'  ⚠️  A rede aponta um local a {dist:.0f} km de Santa Rita do Sapucaí — precisão')
                print(f'     ruim demais (geolocalização por IP costuma acertar só a região do provedor,')
                print(f'     não a cidade exata). Descartando; usarei 0.0, 0.0 se o GPS também falhar.')
            else:
                localizacao_rede = candidata
                print(f'  ✅ Localização aproximada: {localizacao_rede[0]:.4f}, {localizacao_rede[1]:.4f}'
                      f' (~{dist:.0f} km do centro da cidade)')
                print('     Ainda é nível de cidade/bairro, não o ponto exato — use --sem-rede para desativar.')

    print('\n📷 Abrindo câmera...')
    cap = cv2.VideoCapture(args.camera)
    if not cap.isOpened():
        print(f'  ❌ Câmera {args.camera} não encontrada')
        return

    # Aquecimento: no Windows, o backend MSMF costuma falhar nos primeiros
    # frames logo após abrir a câmera. Tenta algumas leituras antes de seguir.
    for _ in range(30):
        ret, _ = cap.read()
        if ret:
            break
        time.sleep(0.05)
    print('  ✅ Câmera aberta')

    detector    = DetectorPersistente(args.conf, args.tempo)
    registrador = RegistradorFocos(saida_dir)
    focos_confirmados_sessao = 0
    falhas_seguidas = 0

    print('\n✅ Sistema ativo! Pressione Q para sair.\n')

    while True:
        ret, frame = cap.read()
        if not ret:
            falhas_seguidas += 1
            if falhas_seguidas > 60:
                print('  ❌ Câmera parou de responder.')
                break
            continue
        falhas_seguidas = 0

        results = model(frame, conf=args.conf * 0.8, verbose=False)
        result  = results[0]

        deteccoes_frame = []
        for box in result.boxes:
            cls  = int(box.cls[0])
            conf = float(box.conf[0])
            if conf >= args.conf:
                deteccoes_frame.append((CLASSES[cls], conf))

        confirmados = detector.atualizar(deteccoes_frame)

        for classe, confianca in confirmados:
            focos_confirmados_sessao += 1
            if gps_ativo and gps.posicao:
                lat, lon = gps.posicao
            elif localizacao_rede:
                lat, lon = localizacao_rede
            else:
                lat, lon = 0.0, 0.0
            ts       = datetime.now().strftime('%Y%m%d_%H%M%S')
            img_nome = f'foco_{classe}_{ts}.jpg'
            img_path = saida_dir / img_nome
            cv2.imwrite(str(img_path), frame)
            registrador.registrar(classe, confianca, lat, lon, img_nome)

        frame_display = result.plot()
        h, w = frame_display.shape[:2]

        if gps_ativo:
            if gps.fixado:
                gps_txt = f'GPS: {gps.latitude:.5f}, {gps.longitude:.5f}'
                gps_cor = (0, 255, 0)
            else:
                gps_txt = 'GPS: aguardando fix...'
                gps_cor = (0, 165, 255)
        else:
            gps_txt = 'GPS: desativado'
            gps_cor = (100, 100, 100)

        cv2.putText(frame_display, gps_txt, (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, gps_cor, 2)

        y_prog = 65
        for classe, confianca in deteccoes_frame:
            prog = detector.progresso(classe)
            if prog > 0:
                barra_w  = int(200 * prog)
                cor_barra = (0, int(255 * prog), int(255 * (1 - prog)))
                cv2.rectangle(frame_display, (10, y_prog), (210, y_prog + 18), (50, 50, 50), -1)
                cv2.rectangle(frame_display, (10, y_prog), (10 + barra_w, y_prog + 18), cor_barra, -1)
                cv2.putText(frame_display,
                            f'{classe} {confianca:.0%} — {prog*args.tempo:.1f}s/{args.tempo:.0f}s',
                            (215, y_prog + 14),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
                y_prog += 28

        cv2.putText(frame_display, f'Focos confirmados: {focos_confirmados_sessao}',
                    (10, h - 15), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        cv2.putText(frame_display, 'Q=sair',
                    (w - 80, h - 15), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (150, 150, 150), 1)

        cv2.imshow('AeroScan — Deteccao de Focos', frame_display)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()
    if gps_ativo:
        gps.parar()

    print(f'\n✅ Sessão encerrada. Focos confirmados: {focos_confirmados_sessao}')
    if focos_confirmados_sessao > 0:
        print(f'   → Arquivo: {registrador.csv_path}')
        print('   → No dashboard, clique em "Importar focos" e selecione o CSV e as fotos salvos aí.')

if __name__ == '__main__':
    main()
