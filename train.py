from ultralytics import YOLO
import os

DATA_YAML = os.path.join(os.path.dirname(__file__), "datasets", "unified", "data.yaml")
RUNS_DIR  = os.path.join(os.path.dirname(__file__), "runs")

model = YOLO("yolov8n.pt")

model.train(
    data=DATA_YAML,
    epochs=50,
    patience=15,       # early stopping se val não melhorar por 15 épocas
    imgsz=640,
    batch=16,
    device="mps",
    project=RUNS_DIR,
    name="drone_v3",
    # --- augmentações para imagens de drone (vista aérea) ---
    degrees=180,       # rotação livre — objetos aparecem em qualquer ângulo
    flipud=0.5,        # flip vertical — vista de cima, simetria vertical
    fliplr=0.5,        # flip horizontal — idem
    scale=0.6,         # variação de escala — simula altitude do drone
    translate=0.1,     # translação — objeto pode estar em qualquer posição
    perspective=0.0005,# leve perspectiva — drone quase sempre perpendicular
    mosaic=1.0,        # mosaic — aumenta diversidade de cenas
    mixup=0.1,         # mixup leve — regularização extra
    hsv_h=0.015,       # variação de matiz — hora do dia / iluminação
    hsv_s=0.5,         # variação de saturação — luz solar / nuvens
    hsv_v=0.4,         # variação de brilho — sombras e reflexo d'água
    shear=0.0,         # sem shear — drone fica ~perpendicular ao solo
)
