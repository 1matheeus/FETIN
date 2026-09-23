"""
AeroScan — Detecção Persistente de Focos
Projeto FETIN 2026 — Equipe 49

Lógica:
  - IA detecta foco com confiança > 60%
  - Se mantiver por TEMPO_CONFIRMACAO segundos → confirma
  - Localização de cada foco, em ordem de prioridade:
      1) GPS real do celular transmitido pela rede (--gps-rede), se
         configurado — é o mais preciso de todos (nível de satélite,
         ~5-20 m), porque usa o chip de GPS de verdade do celular
      2) GPS real de um módulo externo (serial/NMEA), se conectado
      3) Localização por rede via Wi-Fi do sistema operacional
         (serviço de Localização do Windows ou CoreLocation no
         macOS). Em cidades pequenas, na prática costuma devolver
         sempre a mesma estimativa "de cidade" (erro de ~1-2 km,
         podendo cair no bairro errado) — não é uma triangulação de
         Wi-Fi de verdade se a região não estiver bem mapeada no
         banco de pontos de acesso do sistema operacional
      4) Localização aproximada por IP público (ipinfo.io) — só como
         último recurso, ainda menos precisa que a opção acima
      5) 0.0, 0.0 se nada estiver disponível (ex.: sem internet)
  - Antes de gravar, a foto passa pelo borrão de rostos do blur_lgpd.py
    — nenhuma imagem sai daqui sem anonimização
  - Salva o CSV e as fotos na Área de Trabalho (Desktop), sempre no
    mesmo arquivo — cada nova detecção só adiciona uma linha nele
  - Se AEROSCAN_TOKEN estiver definido (ou --token-api), cada foco
    confirmado TAMBÉM é publicado na API de vigilância (POST
    /api/deteccoes) — aparece no dashboard pra qualquer pessoa, sem
    precisar de "Importar focos" manual. Falha de rede aqui nunca
    derruba a sessão: o CSV local já foi salvo antes desta tentativa
  - Sem token, ou como reserva se a API estiver fora do ar: use o botão
    "Importar focos" do dashboard e selecione o CSV (+ as fotos) na
    Área de Trabalho

Como usar:
  pip install ultralytics opencv-python pyserial
  # Windows: pip install winsdk
  # macOS:   pip install pyobjc-framework-CoreLocation
  python drone/detectar_foco.py

Flags opcionais:
  --gps-rede 192.168.0.42:11123   IP:porta do celular transmitindo GPS real pela rede
  --porta /dev/ttyUSB0    porta serial do GPS de módulo externo (padrão: auto-detecta)
  --conf 0.60             confiança mínima (padrão: 0.60)
  --tempo 3               segundos para confirmar (padrão: 3)
  --camera 0              índice da câmera (padrão: 0)
  --sem-gps               modo sem GPS (usa coordenadas manuais)
  --sem-rede              não tenta localização por rede (Wi-Fi do SO / IP)
  --saida ~/Desktop       pasta onde salvar o CSV e as fotos (padrão: Área de Trabalho)
  --api URL               URL base da API de vigilância (padrão: a API em produção)
  --sem-api               não publica as detecções na API — fica só no CSV local
  --token-api TOKEN       token de cadastro da API (Bearer). Prefira a variável de
                          ambiente AEROSCAN_TOKEN — assim ele não fica no histórico
                          do terminal nem em capturas de tela da demo:
                            export AEROSCAN_TOKEN="o-token-de-verdade"
                            python drone/detectar_foco.py --gps-rede ...

GPS real do celular pela rede (--gps-rede, recomendado sem módulo GPS):
  O celular roda um app que transmite as sentenças NMEA do GPS dele por
  TCP na rede local — o script se conecta nesse IP:porta e lê como se
  fosse um GPS serial de verdade. Precisão de satélite (~5-20 m), bem
  melhor que qualquer localização por Wi-Fi/IP do computador.
    iPhone:  app "GPS2IP" (ou similar) — mostra o IP e a porta na tela.
    Android: um app de "NMEA over TCP/network" (ex.: "Share GPS",
             "BlueNMEA" no modo rede) — varia por app; procure a opção
             de servidor TCP e a porta configurada nele.
  Celular e computador precisam estar na mesma rede Wi-Fi.

Localização por rede (Wi-Fi do sistema operacional, fallback automático):
  Usa o mesmo serviço de Localização que o SO usa para mapas e clima —
  no Windows, pip install winsdk; no macOS, pip install
  pyobjc-framework-CoreLocation. Em ambos, é preciso liberar o acesso
  à localização para o app/terminal que roda o Python nas
  configurações de privacidade do sistema. Sem isso, cai para
  localização por IP (bem menos precisa) e depois para 0.0, 0.0.
"""

import os
import sys
import cv2
import csv
import json
import time
import uuid
import argparse
import threading
import urllib.request
from pathlib import Path
from datetime import datetime
from ultralytics import YOLO

# blur_lgpd.py mora na mesma pasta. Rodando como `python drone/detectar_foco.py`
# o Python já põe drone/ no sys.path, mas garantimos para quem importa daqui.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from blur_lgpd import anonimizar

CONF_MINIMA       = 0.60
TEMPO_CONFIRMACAO = 3.0
CLASSES           = ['pool', 'tire']
MODELO_PATH       = 'runs/drone_v1/weights/best.pt'
CSV_NOME          = 'focos_detectados_mvp.csv'
API_BASE_PADRAO   = 'https://projetofetin.eduardo-filhagosa.workers.dev/api'
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


def localizar_por_wifi_windows(timeout=8):
    """Localização por rede usando o serviço de Localização do Windows.

    Não é GPS de hardware: o Windows estima a posição a partir dos pontos
    de acesso Wi-Fi visíveis (comparando com o banco de localização de
    redes Wi-Fi da Microsoft), o que costuma ser bem mais preciso que
    geolocalização por IP — no teste em Santa Rita do Sapucaí, ficou a
    menos de 1 km do centro da cidade, com precisão relatada de ~2 km,
    contra ~249 km de erro do método por IP puro.

    Requer:
      - Windows 10/11
      - pip install winsdk
      - Configurações > Privacidade e segurança > Localização:
        "Serviços de localização" ligado, e acesso liberado para
        aplicativos de área de trabalho
      - Estar conectado a alguma rede (Wi-Fi ou Ethernet com Wi-Fi
        próximo detectável) — sem isso, o serviço não tem como estimar

    Devolve (lat, lon) ou None se o serviço não estiver disponível/
    permitido, ou não conseguir uma posição dentro do timeout.
    """
    if os.name != 'nt':
        return None
    try:
        import asyncio
        from winsdk.windows.devices.geolocation import Geolocator, PositionAccuracy, GeolocationAccessStatus

        async def _obter():
            status = await Geolocator.request_access_async()
            if status != GeolocationAccessStatus.ALLOWED:
                return None
            geolocator = Geolocator()
            geolocator.desired_accuracy = PositionAccuracy.HIGH
            pos = await asyncio.wait_for(geolocator.get_geoposition_async(), timeout=timeout)
            coord = pos.coordinate
            return (coord.point.position.latitude, coord.point.position.longitude)

        return asyncio.run(_obter())
    except ImportError:
        return None
    except Exception:
        return None


def localizar_por_wifi_macos(timeout=8):
    """Localização por rede no macOS, via CoreLocation (o mesmo serviço que
    o Mapas e o Clima do macOS usam — também estima a posição pelos pontos
    de acesso Wi-Fi próximos, não precisa de GPS de hardware).

    Requer:
      - macOS
      - pip install pyobjc-framework-CoreLocation
      - Ajustes do Sistema > Privacidade e Segurança > Serviços de
        Localização: deixe ligado. Na primeira execução, o macOS deve
        pedir permissão para o Terminal (ou o app usado para rodar o
        Python) acessar a localização — é preciso permitir. Se não
        aparecer o pedido, adicione o Terminal manualmente em
        Ajustes do Sistema > Privacidade e Segurança > Localização.
      - Wi-Fi ligado (mesmo sem estar conectado a uma rede específica,
        o macOS já enxerga os pontos de acesso ao redor)

    Devolve (lat, lon) ou None se o serviço não estiver disponível/
    permitido, ou não conseguir uma posição dentro do timeout.

    Observação: esta função não pôde ser testada em uma máquina macOS
    real durante o desenvolvimento (feito em Windows) — teste antes da
    apresentação. Se o pedido de permissão do sistema não aparecer
    automaticamente, motive uma primeira execução manual e aceite o
    pedido assim que ele surgir.
    """
    if sys.platform != 'darwin':
        return None
    try:
        import time as _time
        import objc
        from Foundation import NSObject, NSRunLoop, NSDate
        from CoreLocation import CLLocationManager

        resultado = {}

        class _DelegadoLocalizacao(NSObject):
            def locationManager_didUpdateLocations_(self, manager, locations):
                if locations and len(locations) > 0:
                    coord = locations[-1].coordinate()
                    resultado['pos'] = (coord.latitude, coord.longitude)

            def locationManager_didFailWithError_(self, manager, error):
                resultado['erro'] = str(error)

        gerenciador = CLLocationManager.alloc().init()
        delegado    = _DelegadoLocalizacao.alloc().init()
        gerenciador.setDelegate_(delegado)
        if hasattr(gerenciador, 'requestWhenInUseAuthorization'):
            gerenciador.requestWhenInUseAuthorization()
        gerenciador.startUpdatingLocation()

        prazo = _time.time() + timeout
        while _time.time() < prazo and 'pos' not in resultado and 'erro' not in resultado:
            NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.2))

        gerenciador.stopUpdatingLocation()
        return resultado.get('pos')
    except ImportError:
        return None
    except Exception:
        return None


def localizar_por_rede_dispositivo(timeout=8):
    """Escolhe automaticamente o serviço de localização por rede do
    sistema operacional atual (Windows ou macOS). Em qualquer outro
    sistema (ex.: Linux), devolve None direto — sobra o fallback por IP.
    """
    if os.name == 'nt':
        return localizar_por_wifi_windows(timeout=timeout)
    if sys.platform == 'darwin':
        return localizar_por_wifi_macos(timeout=timeout)
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


class GPSRede(GPS):
    """GPS real, mas lido do celular pela rede em vez de um módulo serial.

    Reaproveita o mesmo parser NMEA da classe GPS (_parsear_gga/_parsear_rmc)
    — só troca de onde vêm as linhas de texto: em vez de uma porta serial,
    conecta por TCP no celular, que deve estar rodando um app que transmite
    a posição do GPS real dele nesse formato (ex.: GPS2IP no iPhone, ou um
    app de "NMEA sobre TCP/rede" no Android). Isso dá uma localização com
    precisão de satélite de verdade (tipicamente 5-20 m), bem melhor que
    qualquer localização por Wi-Fi/IP do próprio PC — útil quando não há
    um módulo GPS dedicado, mas há um celular na mesma rede.
    """
    def __init__(self, host, porta):
        super().__init__()
        self._host      = host
        self._porta_tcp = porta
        self._socket    = None

    def iniciar(self):
        try:
            import socket
            self._socket = socket.create_connection((self._host, self._porta_tcp), timeout=5)
            self._rodando = True
            self._thread = threading.Thread(target=self._ler_loop, daemon=True)
            self._thread.start()
            print(f'  ✅ Conectado ao GPS do celular em {self._host}:{self._porta_tcp}')
            return True
        except Exception as e:
            print(f'  ⚠️  Não foi possível conectar ao celular em {self._host}:{self._porta_tcp} ({e}).')
            print('     Confira se o app de GPS está aberto e transmitindo, e se o celular e este')
            print('     computador estão na mesma rede Wi-Fi.')
            return False

    def _ler_loop(self):
        buffer = b''
        while self._rodando:
            try:
                dados = self._socket.recv(1024)
                if not dados:
                    break
                buffer += dados
                while b'\n' in buffer:
                    linha_bytes, buffer = buffer.split(b'\n', 1)
                    linha = linha_bytes.decode('ascii', errors='replace').strip()
                    if linha.startswith('$GPGGA') or linha.startswith('$GNGGA'):
                        self._parsear_gga(linha)
                    elif linha.startswith('$GPRMC') or linha.startswith('$GNRMC'):
                        self._parsear_rmc(linha)
            except Exception:
                break

    def parar(self):
        self._rodando = False
        if self._socket:
            try:
                self._socket.close()
            except Exception:
                pass


def _multipart_encode(campos, arquivo=None):
    """Monta um corpo multipart/form-data à mão (só biblioteca padrão — sem
    puxar `requests` como dependência nova só por causa disto).

    `campos` é {nome: valor} (texto); `arquivo`, se houver, é
    (nome_do_arquivo, bytes, content_type) e vai no campo "foto".
    Devolve (corpo_em_bytes, content_type_com_boundary).
    """
    boundary = uuid.uuid4().hex
    partes = []
    for chave, valor in campos.items():
        partes.append(
            f'--{boundary}\r\n'
            f'Content-Disposition: form-data; name="{chave}"\r\n\r\n'
            f'{valor}\r\n'.encode('utf-8')
        )
    if arquivo:
        nome, dados, tipo = arquivo
        partes.append(
            f'--{boundary}\r\n'
            f'Content-Disposition: form-data; name="foto"; filename="{nome}"\r\n'
            f'Content-Type: {tipo}\r\n\r\n'.encode('utf-8')
            + dados + b'\r\n'
        )
    partes.append(f'--{boundary}--\r\n'.encode('utf-8'))
    return b''.join(partes), f'multipart/form-data; boundary={boundary}'


def enviar_deteccao_api(api_base, token, classe, confianca, lat, lon, data_deteccao, caminho_foto):
    """Espelha a detecção pra API de vigilância (Cloudflare Worker + D1 + R2),
    pra ela aparecer no dashboard pra QUALQUER pessoa que abrir o site — não só
    em quem importar o CSV manualmente na própria sessão do navegador.

    Melhor esforço, de propósito: a detecção já foi salva no CSV local antes
    desta função ser chamada (ver RegistradorFocos.registrar), então uma falha
    aqui — sem internet, API fora do ar, token errado — não pode derrubar a
    sessão de detecção. Só avisa e segue. Nunca levanta exceção pra quem chama.
    """
    campos = {
        'classe_origem': classe,
        'confianca':     f'{confianca:.4f}',
        'lon':           f'{lon:.6f}',
        'lat':           f'{lat:.6f}',
        'data_deteccao': data_deteccao,
    }
    arquivo = None
    if caminho_foto and Path(caminho_foto).exists():
        arquivo = (Path(caminho_foto).name, Path(caminho_foto).read_bytes(), 'image/jpeg')

    corpo, content_type = _multipart_encode(campos, arquivo)
    req = urllib.request.Request(
        f'{api_base}/deteccoes', data=corpo, method='POST',
        headers={'Authorization': f'Bearer {token}', 'Content-Type': content_type},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            resposta = json.loads(resp.read().decode('utf-8'))
        id_api = resposta.get('deteccao', {}).get('deteccao_id', '?')
        print(f'  ☁️  Também publicado na API (id {id_api}) — já aparece no dashboard pra todo mundo.')
        return True
    except Exception as e:
        print(f'  ⚠️  Não deu pra publicar na API ({e}). Sem problema: já está salvo no CSV local,')
        print('     dá pra importar manualmente pelo dashboard depois.')
        return False


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
            'origem_imagem':      imagem_path or '',
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


def salvar_foto_anonimizada(frame, destino):
    """Grava a foto do foco com os rostos borrados.

    Falha fechada, de propósito: se a anonimização não puder rodar, a foto
    NÃO é salva e o foco entra no CSV sem imagem. Perder a foto de um foco é
    um problema pequeno; publicar o rosto de um morador não é.

    Devolve (caminho_salvo_ou_None, quantidade_de_rostos_borrados).
    """
    try:
        frame_anonimo, rostos = anonimizar(frame)
    except Exception as e:
        print(f'  ⚠️  Anonimização falhou ({e}).')
        print('     A foto NÃO foi salva — o foco entra no CSV sem imagem.')
        return None, 0

    if not cv2.imwrite(str(destino), frame_anonimo):
        print(f'  ⚠️  Não foi possível gravar {destino.name}.')
        return None, rostos

    return destino, rostos


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
    parser.add_argument('--gps-rede', type=str, default=None,
                         help='IP:porta do celular transmitindo GPS real pela rede '
                              '(ex.: 192.168.0.42:11123) — usa o GPS de satélite do celular '
                              'em vez de um módulo serial. Tem prioridade sobre --porta/--sem-gps.')
    parser.add_argument('--sem-rede', action='store_true',
                         help='Não tenta localização aproximada pela rede (Wi-Fi do SO / IP) como alternativa ao GPS')
    parser.add_argument('--saida',   type=str,   default=None,
                         help='Pasta onde salvar o CSV e as fotos (padrão: Área de Trabalho)')
    parser.add_argument('--api', type=str, default=API_BASE_PADRAO,
                         help='URL base da API de vigilância — cada foco confirmado também é '
                              'publicado lá, e aparece no dashboard pra qualquer pessoa, sem '
                              'precisar de importação manual de CSV (padrão: a API em produção)')
    parser.add_argument('--sem-api', action='store_true',
                         help='Não publica as detecções na API — fica só no CSV/fotos local, '
                              'pra importar manualmente depois')
    parser.add_argument('--token-api', type=str, default=os.environ.get('AEROSCAN_TOKEN'),
                         help='Token de cadastro da API (Bearer). Pega da variável de ambiente '
                              'AEROSCAN_TOKEN se não for passado aqui — assim o token não fica '
                              'salvo no histórico do terminal nem em capturas de tela da demo.')
    args = parser.parse_args()

    if not args.sem_api and not args.token_api:
        print('\nℹ️  Sem --token-api nem AEROSCAN_TOKEN definido: as detecções vão ficar só no')
        print('    CSV/fotos local (Área de Trabalho) — nada é publicado na API automaticamente.')
        print('    Pra publicar, defina AEROSCAN_TOKEN ou use --sem-api pra sumir com este aviso.')

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

    gps_origem = None
    if args.gps_rede:
        host, _, porta_str = args.gps_rede.partition(':')
        porta_tcp = int(porta_str) if porta_str else 11123
        print(f'\n📱 Conectando ao GPS do celular via rede ({host}:{porta_tcp})...')
        gps = GPSRede(host, porta_tcp)
        gps_ativo = gps.iniciar()
        gps_origem = 'celular'
    elif not args.sem_gps:
        print('\n🛰️  Inicializando GPS...')
        gps = GPS(porta=args.porta)
        gps_ativo = gps.iniciar()
        gps_origem = 'serial'
    else:
        gps = GPS()
        gps_ativo = False
        print('\n⚠️  Modo sem GPS ativo')

    localizacao_rede = None
    if not args.sem_rede:
        nome_servico_so = 'Wi-Fi do Windows' if os.name == 'nt' else ('Wi-Fi do macOS' if sys.platform == 'darwin' else None)
        if nome_servico_so:
            print(f'\n📶 Tentando localização pela rede ({nome_servico_so})...')
        else:
            print('\n📶 Tentando localização pela rede...')
        candidata = localizar_por_rede_dispositivo()
        origem = nome_servico_so or 'rede'
        if not candidata:
            if nome_servico_so:
                print(f'  ⚠️  {nome_servico_so} indisponível (serviço desligado, sem permissão, ou pacote ausente).')
            print('     Tentando por IP como alternativa...')
            candidata = localizar_por_rede()
            origem = 'IP público'
        if not candidata:
            print('  ⚠️  Sem internet ou nenhum serviço disponível — usarei 0.0, 0.0 se o GPS também falhar.')
        else:
            dist = distancia_km(candidata, CENTRO_CIDADE)
            if dist > RAIO_MAXIMO_KM:
                print(f'  ⚠️  A localização por {origem} aponta um local a {dist:.0f} km de Santa Rita')
                print(f'     do Sapucaí — precisão ruim demais para essa fonte. Descartando; usarei')
                print(f'     0.0, 0.0 se o GPS também falhar.')
            else:
                localizacao_rede = candidata
                print(f'  ✅ Localização via {origem}: {localizacao_rede[0]:.4f}, {localizacao_rede[1]:.4f}'
                      f' (~{dist:.0f} km do centro da cidade)')
                if origem == 'IP público':
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

            salvo, rostos_borrados = salvar_foto_anonimizada(frame, img_path)
            if rostos_borrados:
                print(f'  🔒 {rostos_borrados} rosto(s) borrado(s) antes de salvar.')

            registrador.registrar(classe, confianca, lat, lon,
                                  img_nome if salvo else None)

            if not args.sem_api and args.token_api:
                enviar_deteccao_api(args.api, args.token_api, classe, confianca, lat, lon,
                                     datetime.now().strftime('%Y-%m-%d'),
                                     img_path if salvo else None)

        frame_display = result.plot()
        h, w = frame_display.shape[:2]

        rotulo_origem = ' (celular)' if gps_origem == 'celular' else ''
        if gps_ativo:
            if gps.fixado:
                gps_txt = f'GPS{rotulo_origem}: {gps.latitude:.5f}, {gps.longitude:.5f}'
                gps_cor = (0, 255, 0)
            else:
                gps_txt = f'GPS{rotulo_origem}: aguardando fix...'
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
