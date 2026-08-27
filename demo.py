import cv2
import sys
import argparse
import time
from pathlib import Path
from ultralytics import YOLO

sys.path.insert(0, str(Path(__file__).resolve().parent / "drone"))
from blur_lgpd import anonimizar

WEIGHTS = "runs/drone_v1/weights/best.pt"
CLASSES = ["pool", "tire"]
COLORS  = {
    "pool": (0, 200, 255),   # amarelo
    "tire": (0, 255, 80),    # verde
}
FONT = cv2.FONT_HERSHEY_SIMPLEX


def find_usb_camera():
    """Tenta índices 0-4 e retorna o primeiro que abrir."""
    for i in range(5):
        cap = cv2.VideoCapture(i)
        if cap.isOpened():
            cap.release()
            return i
    return None


def draw_detections(frame, boxes):
    counts = {c: 0 for c in CLASSES}
    for box in boxes:
        cls_id = int(box.cls)
        label  = CLASSES[cls_id] if cls_id < len(CLASSES) else str(cls_id)
        conf   = float(box.conf)
        x1, y1, x2, y2 = map(int, box.xyxy[0])
        color = COLORS.get(label, (255, 255, 255))
        counts[label] = counts.get(label, 0) + 1

        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        text = f"{label} {conf:.2f}"
        (tw, th), _ = cv2.getTextSize(text, FONT, 0.55, 1)
        cv2.rectangle(frame, (x1, y1 - th - 8), (x1 + tw + 6, y1), color, -1)
        cv2.putText(frame, text, (x1 + 3, y1 - 4), FONT, 0.55, (0, 0, 0), 1)
    return counts


def draw_hud(frame, fps, counts, source_label):
    h, w = frame.shape[:2]

    # fundo semitransparente no topo
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (w, 70), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.45, frame, 0.55, 0, frame)

    cv2.putText(frame, f"FPS: {fps:.1f}", (10, 24), FONT, 0.7, (255, 255, 255), 2)
    cv2.putText(frame, f"Cam: {source_label}", (10, 52), FONT, 0.55, (180, 180, 180), 1)

    x = w - 10
    for label in reversed(CLASSES):
        color = COLORS.get(label, (255, 255, 255))
        text = f"{label}: {counts.get(label, 0)}"
        (tw, _), _ = cv2.getTextSize(text, FONT, 0.65, 2)
        x -= tw + 16
        cv2.putText(frame, text, (x, 28), FONT, 0.65, color, 2)

    # rodapé com atalhos
    overlay2 = frame.copy()
    cv2.rectangle(overlay2, (0, h - 26), (w, h), (0, 0, 0), -1)
    cv2.addWeighted(overlay2, 0.45, frame, 0.55, 0, frame)
    cv2.putText(frame, "q = sair   s = screenshot", (10, h - 8),
                FONT, 0.45, (180, 180, 180), 1)


def run(source, conf):
    model = YOLO(WEIGHTS)

    if isinstance(source, int):
        source_label = f"Camera {source}"
    else:
        source_label = str(source)

    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        print(f"Erro: nao foi possivel abrir '{source}'")
        return

    print(f"Fonte: {source_label}")
    print("Pressione 'q' para sair, 's' para salvar screenshot")

    prev_time = time.time()
    screenshot_n = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            print("Sem frame — encerrando.")
            break

        results = model(frame, conf=conf, verbose=False)
        counts  = draw_detections(frame, results[0].boxes)

        now = time.time()
        fps = 1.0 / max(now - prev_time, 1e-6)
        prev_time = now

        draw_hud(frame, fps, counts, source_label)
        cv2.imshow("FETIN — Pool & Tire Detection", frame)

        key = cv2.waitKey(1) & 0xFF
        if key == ord("q"):
            break
        if key == ord("s"):
            # O screenshot também passa pelo borrão: é a mesma câmera e o
            # mesmo disco do detectar_foco.py, e a demo costuma rodar com
            # gente na frente da lente.
            try:
                frame_anonimo, rostos = anonimizar(frame)
            except Exception as e:
                print(f"Anonimização falhou ({e}) — screenshot não salvo.")
                continue
            screenshot_n += 1
            path = f"screenshot_{screenshot_n:03d}.jpg"
            cv2.imwrite(path, frame_anonimo)
            extra = f" — {rostos} rosto(s) borrado(s)" if rostos else ""
            print(f"Screenshot salvo: {path}{extra}")

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="FETIN — demo em tempo real")
    parser.add_argument(
        "--source", default=None,
        help="0=webcam, 1=USB, caminho de arquivo ou URL. "
             "Omitir = detecta automaticamente.",
    )
    parser.add_argument(
        "--conf", type=float, default=0.4,
        help="Limiar de confiança (padrão: 0.4)",
    )
    args = parser.parse_args()

    if args.source is None:
        idx = find_usb_camera()
        if idx is None:
            print("Nenhuma câmera encontrada.")
            exit(1)
        print(f"Câmera detectada automaticamente: índice {idx}")
        source = idx
    elif args.source.isdigit():
        source = int(args.source)
    else:
        source = args.source

    run(source, args.conf)
