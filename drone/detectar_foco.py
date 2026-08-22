"""
AeroScan — Detecção Persistente de Focos
Projeto FETIN 2026 — Equipe 49

Lógica:
  - IA detecta foco com confiança > 60%
  - Se mantiver por TEMPO_CONFIRMACAO segundos → confirma
  - Lê GPS do módulo externo do drone (serial/NMEA)
  - Salva no CSV e atualiza o dashboard automaticamente

Como usar:
  pip install ultralytics opencv-python pyserial
  python drone/detectar_foco.py

Flags opcionais:
  --porta /dev/ttyUSB0    porta serial do GPS (padrão: auto-detecta)
  --conf 0.60             confiança mínima (padrão: 0.60)
  --tempo 3               segundos para confirmar (padrão: 3)
  --camera 0              índice da câmera (padrão: 0)
  --sem-gps               modo sem GPS (usa coordenadas manuais)
"""

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
DASHBOARD_CSV     = Path('dashboard/focos_detectados_mvp.csv')
DASHBOARD_DIR     = Path('dashboard')

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
    def __init__(self):
        DASHBOARD_DIR.mkdir(parents=True, exist_ok=True)
        self._contador = self._proximo_id()

    def _proximo_id(self):
        if not DASHBOARD_CSV.exists():
            return 1
        try:
            with open(DASHBOARD_CSV, newline='', encoding='utf-8') as f:
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
        existe = DASHBOARD_CSV.exists()
        with open(DASHBOARD_CSV, 'a', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=nova_linha.keys())
            if not existe:
                writer.writeheader()
            writer.writerow(nova_linha)
        print(f'\n  📍 FOCO REGISTRADO: {id_foco}')
        print(f'     Tipo:       {nova_linha["tipo_foco"]}')
        print(f'     Confiança:  {confianca:.1%}')
        print(f'     GPS:        {latitude:.6f}, {longitude:.6f}')
        print(f'     → Recarregue o dashboard para ver o novo marcador!\n')
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
    args = parser.parse_args()

    print('\n🚁 AeroScan — Detecção Persistente de Focos')
    print('=' * 50)
    print(f'  Confiança mínima:  {args.conf:.0%}')
    print(f'  Tempo confirmação: {args.tempo}s')
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

    print('\n📷 Abrindo câmera...')
    cap = cv2.VideoCapture(args.camera)
    if not cap.isOpened():
        print(f'  ❌ Câmera {args.camera} não encontrada')
        return
    print('  ✅ Câmera aberta')

    detector    = DetectorPersistente(args.conf, args.tempo)
    registrador = RegistradorFocos()
    focos_confirmados_sessao = 0

    print('\n✅ Sistema ativo! Pressione Q para sair.\n')

    while True:
        ret, frame = cap.read()
        if not ret:
            break

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
            else:
                lat, lon = 0.0, 0.0
            ts       = datetime.now().strftime('%Y%m%d_%H%M%S')
            img_nome = f'foco_{classe}_{ts}.jpg'
            img_path = DASHBOARD_DIR / img_nome
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
        print('   → Abra o dashboard para ver os marcadores no mapa!')

if __name__ == '__main__':
    main()
