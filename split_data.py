import os
import shutil
import random

# =========================
# CONFIG
# =========================
BASE_DIR = "data"          # search will start from here
TARGET_TRAIN = "data/train"
TARGET_VAL = "data/val"

SPLIT_RATIO = 0.8
SEED = 42
random.seed(SEED)

# =========================
# FIND colored_images AUTO
# =========================
SOURCE_DIR = None

for root, dirs, files in os.walk(BASE_DIR):
    if "colored_images" in dirs:
        SOURCE_DIR = os.path.join(root, "colored_images")
        break

if SOURCE_DIR is None:
    raise Exception("❌ colored_images folder NOT found inside data/")

print(f"✅ Found dataset at: {SOURCE_DIR}")

# =========================
# CREATE OUTPUT DIRS
# =========================
os.makedirs(TARGET_TRAIN, exist_ok=True)
os.makedirs(TARGET_VAL, exist_ok=True)

# =========================
# SPLIT DATA
# =========================
classes = os.listdir(SOURCE_DIR)

for cls in classes:
    cls_path = os.path.join(SOURCE_DIR, cls)
    if not os.path.isdir(cls_path):
        continue

    images = os.listdir(cls_path)
    random.shuffle(images)

    split_idx = int(len(images) * SPLIT_RATIO)
    train_imgs = images[:split_idx]
    val_imgs = images[split_idx:]

    train_cls_dir = os.path.join(TARGET_TRAIN, cls)
    val_cls_dir = os.path.join(TARGET_VAL, cls)

    os.makedirs(train_cls_dir, exist_ok=True)
    os.makedirs(val_cls_dir, exist_ok=True)

    for img in train_imgs:
        shutil.copy(
            os.path.join(cls_path, img),
            os.path.join(train_cls_dir, img)
        )

    for img in val_imgs:
        shutil.copy(
            os.path.join(cls_path, img),
            os.path.join(val_cls_dir, img)
        )

    print(f"✅ {cls}: {len(train_imgs)} train | {len(val_imgs)} val")

print("\n🎉 Dataset split completed successfully!")
