"""
scripts/evaluate_xray.py

Evaluates the pre-trained DenseNet-121 (torchxrayvision) on the NIH
ChestX-ray14 test split and generates paper-ready tables and figures.

Outputs:
    docs/xray_results.csv            — per-pathology AUROC / AUPRC table
    docs/per_pathology_xray.csv      — detailed per-pathology metrics
    docs/figures/xray_roc.png        — ROC curves for all 14 pathologies
    docs/figures/xray_gradcam_*.png  — Grad-CAM examples for top findings

── Dataset setup ─────────────────────────────────────────────────────────────
Download NIH ChestX-ray14 from Kaggle:

    pip install kaggle
    kaggle datasets download nih-chest-xrays/data -p data/chestxray14 --unzip

Or manually from: https://nihcc.app.box.com/v/ChestXray-NIHCC

Expected directory structure:
    data/chestxray14/
        images/                       ← all 112,120 PNG images
        Data_Entry_2017_v2020.csv     ← labels
        test_list.txt                 ← official test split (25,596 images)

Run from project root:
    pip install torchxrayvision grad-cam scikit-image
    python scripts/evaluate_xray.py
──────────────────────────────────────────────────────────────────────────────
"""

import os
import sys
import logging

import numpy as np
import pandas as pd
import torch

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)

if __name__ != '__main__':
    sys.exit(0)

ROOT_DIR   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR   = os.path.join(ROOT_DIR, 'data', 'chestxray14')
DOCS_DIR   = os.path.join(ROOT_DIR, 'docs')
FIGS_DIR   = os.path.join(DOCS_DIR, 'figures')
os.makedirs(FIGS_DIR, exist_ok=True)

# ── Check dataset ──────────────────────────────────────────────────────────────
IMG_DIR       = os.path.join(DATA_DIR, 'images')
LABELS_CSV    = os.path.join(DATA_DIR, 'Data_Entry_2017_v2020.csv')
TEST_LIST_TXT = os.path.join(DATA_DIR, 'test_list.txt')

for path in [IMG_DIR, LABELS_CSV, TEST_LIST_TXT]:
    if not os.path.exists(path):
        log.error(f"Missing: {path}")
        log.error("Please download NIH ChestX-ray14 — see docstring at top of this file.")
        sys.exit(1)

# ── Load model ─────────────────────────────────────────────────────────────────
try:
    import torchxrayvision as xrv
except ImportError:
    log.error("torchxrayvision not installed. Run: pip install torchxrayvision")
    sys.exit(1)

if torch.backends.mps.is_available():   device = torch.device('mps')
elif torch.cuda.is_available():          device = torch.device('cuda')
else:                                    device = torch.device('cpu')

log.info(f"Device: {device}")
log.info("Loading DenseNet-121 (densenet121-res224-all)…")
model = xrv.models.DenseNet(weights="densenet121-res224-all")
model.to(device).eval()
log.info(f"Model pathologies: {model.pathologies}")

# ── Load test set ──────────────────────────────────────────────────────────────
log.info("Loading NIH ChestX-ray14 test split…")
with open(TEST_LIST_TXT) as f:
    test_files = set(line.strip() for line in f if line.strip())

df_labels = pd.read_csv(LABELS_CSV)
df_test   = df_labels[df_labels['Image Index'].isin(test_files)].copy()
log.info(f"Test images: {len(df_test):,}")

# Build binary label matrix aligned to model.pathologies
NIH_TO_MODEL = {
    'Atelectasis':       'Atelectasis',
    'Cardiomegaly':      'Cardiomegaly',
    'Effusion':          'Effusion',
    'Infiltration':      'Infiltration',
    'Mass':              'Mass',
    'Nodule':            'Nodule',
    'Pneumonia':         'Pneumonia',
    'Pneumothorax':      'Pneumothorax',
    'Consolidation':     'Consolidation',
    'Edema':             'Edema',
    'Emphysema':         'Emphysema',
    'Fibrosis':          'Fibrosis',
    'Pleural_Thickening':'Pleural_Thickening',
    'Hernia':            'Hernia',
}

for nih_name in NIH_TO_MODEL:
    df_test[nih_name] = df_test['Finding Labels'].apply(
        lambda s: int(nih_name in s.split('|'))
    )

# ── Inference ──────────────────────────────────────────────────────────────────
import torchvision.transforms as T
from PIL import Image

transform = T.Compose([
    xrv.datasets.XRayCenterCrop(),
    xrv.datasets.XRayResizer(224),
])

all_probs  = []
all_labels = []
BATCH = 32
rows  = df_test.to_dict('records')

log.info(f"Running inference on {len(rows):,} images (batch={BATCH})…")

for start in range(0, len(rows), BATCH):
    batch_rows  = rows[start:start + BATCH]
    batch_imgs  = []
    batch_lbls  = []

    for row in batch_rows:
        img_path = os.path.join(IMG_DIR, row['Image Index'])
        if not os.path.exists(img_path):
            continue
        try:
            arr = np.array(Image.open(img_path).convert('L'), dtype=np.float32)
            arr = xrv.datasets.normalize(arr, maxval=255, reshape=True)
            arr = transform(arr)          # (1, 224, 224)
            batch_imgs.append(arr)
            batch_lbls.append([row[NIH_TO_MODEL[p]] for p in model.pathologies
                                if p in NIH_TO_MODEL])
        except Exception as e:
            log.warning(f"Skipping {row['Image Index']}: {e}")

    if not batch_imgs:
        continue

    tensor = torch.from_numpy(np.stack(batch_imgs)).to(device)  # (B,1,224,224)
    with torch.no_grad():
        probs = torch.sigmoid(model(tensor)).cpu().numpy()       # (B,14)

    all_probs.append(probs)
    all_labels.append(np.array(batch_lbls))

    if (start // BATCH) % 50 == 0:
        log.info(f"  {start:,}/{len(rows):,}")

all_probs  = np.vstack(all_probs)   # (N, 14)
all_labels = np.vstack(all_labels)  # (N, 14)
log.info(f"Inference done — {len(all_probs):,} images evaluated")

# ── Metrics ────────────────────────────────────────────────────────────────────
from sklearn.metrics import roc_auc_score, average_precision_score

pathologies = [p for p in model.pathologies if p in NIH_TO_MODEL]
records = []
for i, path_name in enumerate(pathologies):
    y_true = all_labels[:, i]
    y_score = all_probs[:, i]
    if y_true.sum() == 0:
        auroc = auprc = float('nan')
    else:
        auroc = roc_auc_score(y_true, y_score)
        auprc = average_precision_score(y_true, y_score)
    prevalence = y_true.mean()
    records.append({
        'Pathology':  path_name,
        'AUROC':      round(auroc, 4),
        'AUPRC':      round(auprc, 4),
        'Prevalence': round(float(prevalence), 4),
        'N_positive': int(y_true.sum()),
    })
    log.info(f"  {path_name:<25} AUROC={auroc:.4f}  AUPRC={auprc:.4f}  "
             f"Prev={prevalence:.3f}")

results_df = pd.DataFrame(records)
macro_auroc = results_df['AUROC'].dropna().mean()
log.info(f"\nMean AUROC: {macro_auroc:.4f}")

results_df.to_csv(os.path.join(DOCS_DIR, 'xray_results.csv'), index=False)
log.info(f"Results saved → {os.path.join(DOCS_DIR, 'xray_results.csv')}")

# ── ROC curves ─────────────────────────────────────────────────────────────────
try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from sklearn.metrics import roc_curve

    fig, axes = plt.subplots(4, 4, figsize=(20, 20))
    axes = axes.flatten()

    for i, path_name in enumerate(pathologies):
        ax = axes[i]
        y_true  = all_labels[:, i]
        y_score = all_probs[:, i]
        if y_true.sum() == 0:
            ax.text(0.5, 0.5, 'No positive samples', ha='center')
            ax.set_title(path_name)
            continue
        fpr, tpr, _ = roc_curve(y_true, y_score)
        auroc = records[i]['AUROC']
        ax.plot(fpr, tpr, lw=2, label=f'AUC={auroc:.3f}')
        ax.plot([0, 1], [0, 1], 'k--', lw=1)
        ax.set_xlabel('FPR', fontsize=8)
        ax.set_ylabel('TPR', fontsize=8)
        ax.set_title(path_name, fontsize=9)
        ax.legend(fontsize=8)

    # Hide unused subplots
    for j in range(len(pathologies), len(axes)):
        axes[j].set_visible(False)

    plt.suptitle(f'ROC Curves — DenseNet-121 on NIH ChestX-ray14 test split\n'
                 f'Mean AUROC = {macro_auroc:.4f}', fontsize=14)
    plt.tight_layout()
    roc_path = os.path.join(FIGS_DIR, 'xray_roc.png')
    plt.savefig(roc_path, dpi=150)
    plt.close()
    log.info(f"ROC curves saved → {roc_path}")

except ImportError:
    log.warning("matplotlib not installed — skipping plots")

# ── Grad-CAM examples ──────────────────────────────────────────────────────────
try:
    from pytorch_grad_cam import GradCAM
    from pytorch_grad_cam.utils.image import show_cam_on_image
    from pytorch_grad_cam.utils.model_targets import ClassifierOutputTarget
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    log.info("\nGenerating Grad-CAM examples for top 3 pathologies by AUROC…")
    top3 = results_df.dropna().nlargest(3, 'AUROC')['Pathology'].tolist()

    for path_name in top3:
        path_idx = pathologies.index(path_name)
        # Find a positive example
        pos_indices = np.where(all_labels[:, path_idx] == 1)[0]
        if len(pos_indices) == 0:
            continue
        example_row = df_test.iloc[pos_indices[0]]
        img_path    = os.path.join(IMG_DIR, example_row['Image Index'])
        if not os.path.exists(img_path):
            continue

        arr     = np.array(Image.open(img_path).convert('L'), dtype=np.float32)
        arr_n   = xrv.datasets.normalize(arr, maxval=255, reshape=True)
        arr_t   = transform(arr_n)
        tensor  = torch.from_numpy(arr_t).unsqueeze(0).to(device)

        target_layers = [model.features.denseblock4.denselayer16.norm1]
        cam     = GradCAM(model=model, target_layers=target_layers)
        targets = [ClassifierOutputTarget(path_idx)]
        mask    = cam(input_tensor=tensor, targets=targets)[0]  # (224,224)

        # Create RGB version for overlay
        img_rgb = np.stack([arr_t[0]] * 3, axis=-1)
        img_rgb = (img_rgb - img_rgb.min()) / (img_rgb.max() - img_rgb.min() + 1e-8)
        visualization = show_cam_on_image(img_rgb.astype(np.float32), mask, use_rgb=True)

        fig, axes = plt.subplots(1, 2, figsize=(10, 5))
        axes[0].imshow(img_rgb, cmap='gray')
        axes[0].set_title('Original X-ray')
        axes[0].axis('off')
        axes[1].imshow(visualization)
        axes[1].set_title(f'Grad-CAM: {path_name}')
        axes[1].axis('off')
        plt.tight_layout()

        safe_name = path_name.replace(' ', '_')
        out_path  = os.path.join(FIGS_DIR, f'xray_gradcam_{safe_name}.png')
        plt.savefig(out_path, dpi=150)
        plt.close()
        log.info(f"  Grad-CAM saved → {out_path}")

except ImportError:
    log.warning("grad-cam not installed — skipping: pip install grad-cam")
except Exception as e:
    log.warning(f"Grad-CAM generation failed: {e}")

log.info("\n=== X-ray evaluation complete ===")
log.info(f"Outputs in: {DOCS_DIR}")
