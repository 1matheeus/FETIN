import os
import shutil

BASE = os.path.join(os.path.dirname(__file__), "datasets")
UNIFIED = os.path.join(BASE, "unified")

# Final classes
CLASSES = ["pool", "tire"]

# Per-dataset class remapping: source_class_id -> target_class_id (-1 = discard)
DATASETS = [
    {
        "path": os.path.join(BASE, "pool-images", "pool-detection-kmqaa"),
        "map": {0: 0},  # swimming-pool -> pool
    },
    {
        "path": os.path.join(BASE, "swimming-pools", "swimming-pools-detection"),
        "map": {0: 0},  # pool -> pool
    },
    {
        "path": os.path.join(BASE, "piscina-piloto", "swimming-pool-detection"),
        "map": {0: 0},  # '2' -> pool (dataset de piscina)
    },
    {
        "path": os.path.join(BASE, "testwheel", "wheeltester"),
        "map": {0: 1, 1: 1},  # Tire + car-tire -> tire
    },
    {
        "path": os.path.join(BASE, "king-mongkut-university-technology-of-thonburi", "tire-x4hgu"),
        "map": {0: -1, 1: 1},  # None -> discard, Tire -> tire
    },
    {
        "path": os.path.join(BASE, "computervision-f2lah", "tire-detection-xum3o"),
        "map": {0: -1, 1: 1},  # Jammed Tires -> discard (não é claramente água parada), Tires -> tire
    },
]

SPLITS = ["train", "valid", "test"]

for split in SPLITS:
    os.makedirs(os.path.join(UNIFIED, split, "images"), exist_ok=True)
    os.makedirs(os.path.join(UNIFIED, split, "labels"), exist_ok=True)

counters = {s: {"images": 0, "labels": 0, "skipped": 0} for s in SPLITS}

for ds in DATASETS:
    ds_path = ds["path"]
    class_map = ds["map"]
    ds_name = "/".join(ds_path.split("/")[-2:])

    for split in SPLITS:
        img_src = os.path.join(ds_path, split, "images")
        lbl_src = os.path.join(ds_path, split, "labels")

        if not os.path.isdir(img_src):
            continue

        img_dst = os.path.join(UNIFIED, split, "images")
        lbl_dst = os.path.join(UNIFIED, split, "labels")

        for img_file in os.listdir(img_src):
            if not img_file.lower().endswith((".jpg", ".jpeg", ".png", ".bmp", ".webp")):
                continue

            stem = os.path.splitext(img_file)[0]
            prefix = ds_name.replace("/", "_") + "__"

            # Copy image with prefixed name to avoid collisions
            new_img = prefix + img_file
            shutil.copy2(
                os.path.join(img_src, img_file),
                os.path.join(img_dst, new_img),
            )
            counters[split]["images"] += 1

            # Remap label
            lbl_file = stem + ".txt"
            lbl_path = os.path.join(lbl_src, lbl_file)
            new_lines = []

            if os.path.isfile(lbl_path):
                with open(lbl_path) as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        parts = line.split()
                        src_cls = int(parts[0])
                        tgt_cls = class_map.get(src_cls, -1)
                        if tgt_cls == -1:
                            counters[split]["skipped"] += 1
                            continue
                        new_lines.append(f"{tgt_cls} {' '.join(parts[1:])}")

            new_lbl = prefix + stem + ".txt"
            with open(os.path.join(lbl_dst, new_lbl), "w") as f:
                f.write("\n".join(new_lines) + ("\n" if new_lines else ""))
            counters[split]["labels"] += 1

# Write data.yaml
yaml_path = os.path.join(UNIFIED, "data.yaml")
with open(yaml_path, "w") as f:
    f.write(f"path: {UNIFIED}\n")
    f.write("train: train/images\n")
    f.write("val: valid/images\n")
    f.write("test: test/images\n")
    f.write(f"\nnc: {len(CLASSES)}\n")
    f.write("names:\n")
    for cls in CLASSES:
        f.write(f"  - {cls}\n")

print("=== Unificação concluída ===\n")
for split in SPLITS:
    c = counters[split]
    print(f"  {split:6s}: {c['images']:4d} imagens | {c['labels']:4d} labels | {c['skipped']:3d} anotações descartadas (None)")
print(f"\ndata.yaml salvo em: {yaml_path}")
