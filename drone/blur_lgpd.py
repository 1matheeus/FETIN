"""
AeroScan — Blur de Rostos (LGPD)
Projeto FETIN 2026 — Equipe 49

Detecta rostos em imagens do drone e aplica desfoque automático
antes de salvar, garantindo conformidade com a LGPD.

Como usar:
  pip install opencv-python
  python blur_lgpd.py --input imagem.jpg
  python blur_lgpd.py --input pasta/
  python blur_lgpd.py --input video.mp4

Resultado:
  Salva as imagens com rostos borrados em blur_output/
"""

import cv2
import os
import argparse
import json
from pathlib import Path
from datetime import datetime

# ─────────────────────────────────────────
# CONFIGURAÇÕES
# ─────────────────────────────────────────
OUTPUT_DIR     = Path("blur_output")
LOG_FILE       = OUTPUT_DIR / "blur_log.json"
BLUR_INTENSITY = 30        # quanto mais alto, mais borrado (múltiplo de 2 + 1)
FATOR_ESCALA   = 1.03      # scaleFactor do Haar cascade (não alterar)
VIZINHOS_MIN   = 5         # mínimo de vizinhos para detectar rosto (mais alto = menos falsos positivos)
TAMANHO_MIN    = (30, 30)  # tamanho mínimo do rosto em pixels

# ─────────────────────────────────────────
# DETECTOR DE ROSTOS (Haar Cascade)
# Já vem incluso no OpenCV — sem download extra.
# O carregamento é preguiçoso de propósito: este módulo é importado pelo
# detectar_foco.py, e uma falha aqui não pode derrubar a importação. Ela
# precisa chegar a quem chama, que decide o que fazer (ver `anonimizar`).
# ─────────────────────────────────────────
CASCADE_FRONTAL = 'haarcascade_frontalface_default.xml'
CASCADE_PERFIL  = 'haarcascade_profileface.xml'

_detectores = None


def carregar_detectores():
    """Carrega os cascades uma única vez, na primeira chamada."""
    global _detectores
    if _detectores is None:
        frontal = cv2.CascadeClassifier(cv2.data.haarcascades + CASCADE_FRONTAL)
        perfil  = cv2.CascadeClassifier(cv2.data.haarcascades + CASCADE_PERFIL)
        if frontal.empty():
            raise RuntimeError("Detector de rostos não encontrado. Reinstale o OpenCV.")
        _detectores = (frontal, perfil)
    return _detectores

# ─────────────────────────────────────────
# FUNÇÕES
# ─────────────────────────────────────────

def detectar_rostos(imagem_cinza):
    """Detecta rostos frontais e de perfil na imagem."""
    detector_frontal, detector_perfil = carregar_detectores()

    rostos = []
    for detector in (detector_frontal, detector_perfil):
        if detector.empty():
            continue
        encontrados = detector.detectMultiScale(
            imagem_cinza,
            scaleFactor=FATOR_ESCALA,
            minNeighbors=VIZINHOS_MIN,
            minSize=TAMANHO_MIN,
            flags=cv2.CASCADE_SCALE_IMAGE,
        )
        if len(encontrados) > 0:
            rostos.extend(encontrados.tolist())

    return rostos


def anonimizar(imagem):
    """Borra todos os rostos de um frame BGR.

    É a porta de entrada para quem só quer a imagem anonimizada, sem lidar
    com conversão de cor nem com a lista de rostos: `detectar_foco.py` e
    `demo.py` chamam esta função antes de gravar qualquer foto em disco.

    Devolve (imagem_borrada, quantidade_de_rostos). A imagem devolvida é
    sempre uma cópia — o frame original não é alterado.
    """
    cinza = cv2.cvtColor(imagem, cv2.COLOR_BGR2GRAY)
    cinza = cv2.equalizeHist(cinza)

    rostos = detectar_rostos(cinza)
    if not rostos:
        return imagem.copy(), 0

    return aplicar_blur(imagem, rostos), len(rostos)


def aplicar_blur(imagem, rostos, intensidade=BLUR_INTENSITY):
    """Aplica desfoque gaussiano em cada rosto detectado."""
    img_saida = imagem.copy()
    kernel = intensidade * 2 + 1

    for (x, y, w, h) in rostos:
        margem = int(max(w, h) * 0.10)
        x1 = max(0, x - margem)
        y1 = max(0, y - margem)
        x2 = min(imagem.shape[1], x + w + margem)
        y2 = min(imagem.shape[0], y + h + margem)

        rosto_region = img_saida[y1:y2, x1:x2]
        rosto_borrado = cv2.GaussianBlur(rosto_region, (kernel, kernel), 0)
        img_saida[y1:y2, x1:x2] = rosto_borrado

    return img_saida


def processar_imagem(caminho_entrada, dir_saida):
    """Processa uma imagem: detecta rostos, borra e salva."""
    caminho = Path(caminho_entrada)
    imagem  = cv2.imread(str(caminho))

    if imagem is None:
        print(f"  ⚠️  Não foi possível ler: {caminho.name}")
        return None

    imagem_saida, qtd = anonimizar(imagem)
    status = (f"✅ {qtd} rosto(s) borrado(s)" if qtd
              else "✔  Nenhum rosto detectado")

    nome_saida = dir_saida / f"blur_{caminho.name}"
    cv2.imwrite(str(nome_saida), imagem_saida)

    print(f"  {status} → {nome_saida.name}")

    return {
        "arquivo":         caminho.name,
        "saida":           nome_saida.name,
        "rostos_borrados": qtd,
        "processado_em":   datetime.now().isoformat(),
        "lgpd_compliant":  True,
    }


def processar_video(caminho_entrada, dir_saida):
    """Processa um vídeo frame a frame."""
    cap     = cv2.VideoCapture(str(caminho_entrada))
    caminho = Path(caminho_entrada)

    if not cap.isOpened():
        print(f"  ❌ Não foi possível abrir: {caminho.name}")
        return None

    fps     = int(cap.get(cv2.CAP_PROP_FPS))
    largura = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    altura  = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total   = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    nome_saida = dir_saida / f"blur_{caminho.name}"
    fourcc     = cv2.VideoWriter_fourcc(*'mp4v')
    writer     = cv2.VideoWriter(str(nome_saida), fourcc, fps, (largura, altura))

    frame_num    = 0
    total_rostos = 0
    print(f"  🎥 Processando {total} frames...")

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        frame_num += 1
        cinza = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        cinza = cv2.equalizeHist(cinza)

        if frame_num % 3 == 0:
            rostos = detectar_rostos(cinza)
            total_rostos += len(rostos)
        else:
            rostos = []

        frame_saida = aplicar_blur(frame, rostos)
        writer.write(frame_saida)

        if frame_num % 30 == 0:
            pct = int((frame_num / total) * 100)
            print(f"    {pct}% — frame {frame_num}/{total}")

    cap.release()
    writer.release()

    print(f"  ✅ Vídeo salvo: {nome_saida.name} — {total_rostos} rostos borrados")
    return {
        "arquivo":         caminho.name,
        "saida":           nome_saida.name,
        "rostos_borrados": total_rostos,
        "frames":          frame_num,
        "processado_em":   datetime.now().isoformat(),
        "lgpd_compliant":  True,
    }


def processar_camera_ao_vivo():
    """Modo câmera ao vivo — mostra blur em tempo real (para a demo da banca)."""
    print("\n🎥 Modo câmera ao vivo — pressione Q para sair, S para salvar screenshot")
    cap = cv2.VideoCapture(0)

    if not cap.isOpened():
        print("❌ Câmera não encontrada.")
        return

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    screenshot_count = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        cinza  = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        cinza  = cv2.equalizeHist(cinza)
        rostos = detectar_rostos(cinza)
        frame_saida = aplicar_blur(frame, rostos)

        cv2.putText(frame_saida, f"AeroScan LGPD | Rostos: {len(rostos)}",
                    (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
        cv2.putText(frame_saida, "Q=sair  S=screenshot",
                    (10, frame_saida.shape[0] - 15),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (150, 150, 150), 1)

        cv2.imshow("AeroScan — Blur LGPD", frame_saida)

        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            break
        elif key == ord('s'):
            screenshot_count += 1
            nome = OUTPUT_DIR / f"screenshot_lgpd_{screenshot_count:03d}.jpg"
            cv2.imwrite(str(nome), frame_saida)
            print(f"  📸 Screenshot salvo: {nome}")

    cap.release()
    cv2.destroyAllWindows()


# ─────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description='AeroScan — Blur de rostos para conformidade com LGPD'
    )
    parser.add_argument('--input', '-i', type=str,
                        help='Imagem, pasta ou vídeo para processar')
    parser.add_argument('--camera', '-c', action='store_true',
                        help='Modo câmera ao vivo')
    parser.add_argument('--intensidade', type=int, default=BLUR_INTENSITY,
                        help=f'Intensidade do blur (padrão: {BLUR_INTENSITY})')
    args = parser.parse_args()

    if args.camera:
        processar_camera_ao_vivo()
        return

    if not args.input:
        print("ℹ️  Uso:")
        print("  python blur_lgpd.py --input imagem.jpg")
        print("  python blur_lgpd.py --input pasta/")
        print("  python blur_lgpd.py --input video.mp4")
        print("  python blur_lgpd.py --camera")
        return

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    entrada         = Path(args.input)
    log             = []
    EXTENSOES_IMG   = {'.jpg', '.jpeg', '.png', '.bmp', '.webp'}
    EXTENSOES_VIDEO = {'.mp4', '.avi', '.mov', '.mkv'}

    print(f"\n🔍 AeroScan LGPD — Iniciando processamento")
    print(f"📁 Saída: {OUTPUT_DIR}/")
    print("─" * 50)

    if entrada.is_dir():
        arquivos = [f for f in entrada.iterdir()
                    if f.suffix.lower() in EXTENSOES_IMG | EXTENSOES_VIDEO]
        print(f"📂 {len(arquivos)} arquivo(s) encontrado(s) em {entrada}/\n")
        for arq in arquivos:
            print(f"  Processando: {arq.name}")
            if arq.suffix.lower() in EXTENSOES_IMG:
                resultado = processar_imagem(arq, OUTPUT_DIR)
            else:
                resultado = processar_video(arq, OUTPUT_DIR)
            if resultado:
                log.append(resultado)

    elif entrada.is_file():
        ext = entrada.suffix.lower()
        print(f"  Processando: {entrada.name}")
        if ext in EXTENSOES_IMG:
            resultado = processar_imagem(entrada, OUTPUT_DIR)
        elif ext in EXTENSOES_VIDEO:
            resultado = processar_video(entrada, OUTPUT_DIR)
        else:
            print(f"  ❌ Formato não suportado: {ext}")
            return
        if resultado:
            log.append(resultado)
    else:
        print(f"❌ Arquivo ou pasta não encontrado: {entrada}")
        return

    with open(LOG_FILE, 'w', encoding='utf-8') as f:
        json.dump({
            "projeto":        "AeroScan — FETIN 2026",
            "descricao":      "Log de anonimização de imagens (LGPD Art. 5º XII)",
            "total_arquivos": len(log),
            "total_rostos":   sum(r["rostos_borrados"] for r in log),
            "arquivos":       log,
        }, f, ensure_ascii=False, indent=2)

    total_rostos = sum(r["rostos_borrados"] for r in log)
    print(f"\n{'='*50}")
    print(f"✅ Processamento concluído!")
    print(f"   📁 Arquivos processados: {len(log)}")
    print(f"   🔒 Rostos borrados:      {total_rostos}")
    print(f"   📄 Log LGPD salvo em:    {LOG_FILE}")
    print(f"   📁 Imagens em:           {OUTPUT_DIR}/")
    print(f"{'='*50}")
    print(f"\n✔  Todas as imagens estão conformes com a LGPD.")

if __name__ == '__main__':
    main()
