import os
from roboflow import Roboflow

API_KEY = "bhNth8QdfWTgdKvg67gX"
BASE_DIR = os.path.join(os.path.dirname(__file__), "datasets")
FORMAT = "yolov8"

DATASETS = [
    ("pool-images",                                    "pool-detection-kmqaa",          1),
    # test-aobpj/pool-u62qo: sem versão publicada no Roboflow (só imagens cruas,
    # sem export gerado) — não é baixável via API até o dono gerar uma versão.
    ("swimming-pools",                                 "swimming-pools-detection",      1),
    ("piscina-piloto",                                 "swimming-pool-detection",       1),
    ("king-mongkut-university-technology-of-thonburi", "tire-x4hgu",                   1),
    ("computervision-f2lah",                           "tire-detection-xum3o",          4),
    ("testwheel",                                      "wheeltester",                   1),
]

rf = Roboflow(api_key=API_KEY)

for workspace, project_name, version in DATASETS:
    dest = os.path.join(BASE_DIR, workspace, project_name)
    os.makedirs(dest, exist_ok=True)
    print(f"\n→ {workspace}/{project_name}/v{version}")
    try:
        project = rf.workspace(workspace).project(project_name)
        version_obj = project.version(version)
        version_obj.download(FORMAT, location=dest, overwrite=True)
        print(f"  ✓ salvo em datasets/{workspace}/{project_name}/")
    except Exception as e:
        print(f"  ✗ ERRO: {e}")

print("\nConcluído.")
