"""
scripts/train_pubmedbert_ddx.py

Fine-tunes PubMedBERT on DDXPlus with KL divergence loss for differential diagnosis.

Same architecture and loss as train_bert_ddx.py but uses a medical-domain
pre-trained model. Comparing general (DistilBERT) vs medical-domain (PubMedBERT)
pre-training is a key contribution of the paper.

Saves to: models/pubmedbert_model/

Hardware: designed for Apple Silicon MPS. Falls back to CPU automatically.
Expected runtime: ~2-3 hours on MPS for 3 epochs over 150k samples.

Run from project root:
    python scripts/train_bert_ddx.py
"""

import os, sys, json, logging
import numpy as np
import pandas as pd
import torch
import torch.nn.functional as F
from torch.utils.data import Dataset, DataLoader
from transformers import (
    AutoTokenizer,
    AutoModelForSequenceClassification,
    get_linear_schedule_with_warmup,
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    handlers=[
        logging.FileHandler('training_ddxplus_bert.log'),
        logging.StreamHandler(),
    ]
)
log = logging.getLogger(__name__)

if __name__ != '__main__':
    sys.exit(0)

# ── Config ────────────────────────────────────────────────────────────────────
MAX_LENGTH   = 128
BATCH_SIZE   = 16
EPOCHS       = 3
LR           = 2e-5
WEIGHT_DECAY = 0.01
WARMUP_RATIO = 0.1
ALPHA        = 0.7    # weight for KL loss; (1-ALPHA) for auxiliary CE loss
GRAD_ACCUM   = 4      # effective batch size = 64

ROOT_DIR   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DDX_DIR    = os.path.join(ROOT_DIR, 'data', 'ddxplus')
MODEL_DIR  = os.path.join(ROOT_DIR, 'models', 'pubmedbert_model')
CKPT_DIR   = os.path.join(MODEL_DIR, 'checkpoints')
os.makedirs(CKPT_DIR, exist_ok=True)

# ── Device ────────────────────────────────────────────────────────────────────
if torch.backends.mps.is_available():
    device = torch.device('mps')
    log.info("Device: Apple Silicon MPS")
elif torch.cuda.is_available():
    device = torch.device('cuda')
    log.info(f"Device: CUDA ({torch.cuda.get_device_name()})")
else:
    device = torch.device('cpu')
    log.info("Device: CPU")

# ── Load label map ────────────────────────────────────────────────────────────
# Label map is shared across all DDXPlus models — read from the canonical location
lm_path = os.path.join(ROOT_DIR, 'models', 'ddxplus_model', 'ddxplus_label_map.json')
with open(lm_path) as f:
    id_to_label = json.load(f)
num_labels  = len(id_to_label)
label_names = [id_to_label[str(i)] for i in range(num_labels)]
log.info(f"Classes: {num_labels}")

# ── Dataset ───────────────────────────────────────────────────────────────────
class DDXDataset(Dataset):
    def __init__(self, parquet_path: str, tokenizer, max_length: int):
        self.df        = pd.read_parquet(parquet_path)
        self.tokenizer = tokenizer
        self.max_len   = max_length

    def __len__(self):
        return len(self.df)

    def __getitem__(self, idx):
        row  = self.df.iloc[idx]
        text = str(row['text'])

        enc = self.tokenizer(
            text,
            max_length=self.max_len,
            padding='max_length',
            truncation=True,
            return_tensors='pt',
        )

        # soft_labels: float32 required for MPS compatibility
        soft = np.fromstring(row['ddx_probs'], sep=',').astype(np.float32)
        soft_tensor = torch.from_numpy(soft)           # float32

        return {
            'input_ids':      enc['input_ids'].squeeze(0),
            'attention_mask': enc['attention_mask'].squeeze(0),
            'soft_labels':    soft_tensor,
            'hard_label':     torch.tensor(int(row['label']), dtype=torch.long),
        }

# ── Load tokenizer & model ────────────────────────────────────────────────────
MODEL_HF_ID = 'microsoft/BiomedNLP-BiomedBERT-base-uncased-abstract-fulltext'
log.info(f"Loading PubMedBERT tokenizer and model ({MODEL_HF_ID})…")
tokenizer = AutoTokenizer.from_pretrained(MODEL_HF_ID)
model     = AutoModelForSequenceClassification.from_pretrained(
    MODEL_HF_ID,
    num_labels=num_labels,
)
model.to(device)

total_params = sum(p.numel() for p in model.parameters())
log.info(f"Parameters: {total_params / 1e6:.1f}M")

# ── DataLoaders ───────────────────────────────────────────────────────────────
log.info("Building datasets…")
train_ds = DDXDataset(os.path.join(DDX_DIR, 'processed_train.parquet'),    tokenizer, MAX_LENGTH)
val_ds   = DDXDataset(os.path.join(DDX_DIR, 'processed_validate.parquet'), tokenizer, MAX_LENGTH)

train_loader = DataLoader(train_ds, batch_size=BATCH_SIZE, shuffle=True,  num_workers=0, pin_memory=False)
val_loader   = DataLoader(val_ds,   batch_size=BATCH_SIZE, shuffle=False, num_workers=0, pin_memory=False)

log.info(f"Train batches: {len(train_loader):,}  Val batches: {len(val_loader):,}")

# ── Optimizer + Scheduler ─────────────────────────────────────────────────────
optimizer = torch.optim.AdamW(model.parameters(), lr=LR, weight_decay=WEIGHT_DECAY)

total_steps   = (len(train_loader) // GRAD_ACCUM) * EPOCHS
warmup_steps  = int(total_steps * WARMUP_RATIO)
scheduler     = get_linear_schedule_with_warmup(optimizer, warmup_steps, total_steps)
log.info(f"Total optimiser steps: {total_steps:,}  Warmup: {warmup_steps:,}")

# ── Training loop ─────────────────────────────────────────────────────────────
best_val_acc = 0.0

for epoch in range(1, EPOCHS + 1):
    model.train()
    total_loss = 0.0
    optimizer.zero_grad()

    for step, batch in enumerate(train_loader, 1):
        input_ids      = batch['input_ids'].to(device)
        attention_mask = batch['attention_mask'].to(device)
        soft_labels    = batch['soft_labels'].to(device)     # float32
        hard_labels    = batch['hard_label'].to(device)

        outputs = model(input_ids=input_ids, attention_mask=attention_mask)
        logits  = outputs.logits                             # (B, 49)

        # KL divergence loss: model distribution vs gold DDX distribution
        log_probs = F.log_softmax(logits, dim=-1)           # log-probs (required by kl_div)
        kl_loss   = F.kl_div(log_probs, soft_labels, reduction='batchmean')

        # Auxiliary cross-entropy on single ground-truth label (stabilises early training)
        ce_loss   = F.cross_entropy(logits, hard_labels)

        loss = ALPHA * kl_loss + (1 - ALPHA) * ce_loss
        loss = loss / GRAD_ACCUM
        loss.backward()

        total_loss += loss.item() * GRAD_ACCUM

        if step % GRAD_ACCUM == 0:
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            scheduler.step()
            optimizer.zero_grad()

        if step % 500 == 0:
            log.info(f"  Epoch {epoch}  step {step}/{len(train_loader)}  "
                     f"loss={total_loss/step:.4f}")

    avg_loss = total_loss / len(train_loader)
    log.info(f"Epoch {epoch} done — avg train loss: {avg_loss:.4f}")

    # ── Validation ──────────────────────────────────────────────────────────
    model.eval()
    correct = total = 0
    val_loss = 0.0

    with torch.no_grad():
        for batch in val_loader:
            input_ids      = batch['input_ids'].to(device)
            attention_mask = batch['attention_mask'].to(device)
            soft_labels    = batch['soft_labels'].to(device)
            hard_labels    = batch['hard_label'].to(device)

            outputs  = model(input_ids=input_ids, attention_mask=attention_mask)
            logits   = outputs.logits
            log_probs = F.log_softmax(logits, dim=-1)
            val_loss += F.kl_div(log_probs, soft_labels, reduction='batchmean').item()

            preds    = logits.argmax(dim=-1)
            correct += (preds == hard_labels).sum().item()
            total   += hard_labels.size(0)

    val_acc  = correct / total
    val_loss /= len(val_loader)
    log.info(f"Epoch {epoch} — Val Acc@1: {val_acc:.4f}  Val KL Loss: {val_loss:.4f}")

    # Save checkpoint
    ckpt_path = os.path.join(CKPT_DIR, f'epoch_{epoch}')
    model.save_pretrained(ckpt_path)
    tokenizer.save_pretrained(ckpt_path)
    log.info(f"  Checkpoint saved → {ckpt_path}")

    if val_acc > best_val_acc:
        best_val_acc = val_acc
        model.save_pretrained(MODEL_DIR)
        tokenizer.save_pretrained(MODEL_DIR)
        log.info(f"  *** New best model saved → {MODEL_DIR}  (val acc {val_acc:.4f}) ***")

# ── Final test-set evaluation ─────────────────────────────────────────────────
log.info("\n=== Final test set evaluation ===")
test_ds     = DDXDataset(os.path.join(DDX_DIR, 'processed_test.parquet'), tokenizer, MAX_LENGTH)
test_loader = DataLoader(test_ds, batch_size=BATCH_SIZE, shuffle=False, num_workers=0)

# Reload best model
model = AutoModelForSequenceClassification.from_pretrained(MODEL_DIR)
model.to(device)
model.eval()

all_probs   = []
all_hard    = []
all_soft    = []

with torch.no_grad():
    for batch in test_loader:
        input_ids      = batch['input_ids'].to(device)
        attention_mask = batch['attention_mask'].to(device)
        outputs        = model(input_ids=input_ids, attention_mask=attention_mask)
        probs          = F.softmax(outputs.logits, dim=-1).cpu().numpy()
        all_probs.append(probs)
        all_hard.extend(batch['hard_label'].numpy())
        all_soft.append(batch['soft_labels'].numpy())

all_probs = np.vstack(all_probs)
all_hard  = np.array(all_hard)
all_soft  = np.vstack(all_soft)

# Metrics
test_pred = all_probs.argmax(axis=1)
acc1 = (test_pred == all_hard).mean()
acc3 = np.mean([all_hard[i] in np.argsort(all_probs[i])[-3:] for i in range(len(all_hard))])
acc5 = np.mean([all_hard[i] in np.argsort(all_probs[i])[-5:] for i in range(len(all_hard))])

from sklearn.metrics import f1_score
f1   = f1_score(all_hard, test_pred, average='macro', zero_division=0)

eps     = 1e-10
kl      = (all_soft * np.log((all_soft + eps) / (all_probs + eps))).sum(axis=1).mean()

try:
    from sklearn.metrics import ndcg_score
    ndcg3 = ndcg_score(all_soft, all_probs, k=3)
    ndcg5 = ndcg_score(all_soft, all_probs, k=5)
except Exception:
    ndcg3 = ndcg5 = float('nan')

log.info(f"\n{'Metric':<25} {'DistilBERT+KL':>14}")
log.info("-" * 42)
log.info(f"{'Acc@1':<25} {acc1:>14.4f}")
log.info(f"{'Acc@3':<25} {acc3:>14.4f}")
log.info(f"{'Acc@5':<25} {acc5:>14.4f}")
log.info(f"{'Macro-F1':<25} {f1:>14.4f}")
log.info(f"{'NDCG@3':<25} {ndcg3:>14.4f}")
log.info(f"{'NDCG@5':<25} {ndcg5:>14.4f}")
log.info(f"{'Mean KL Div (↓)':<25} {kl:>14.4f}")

metrics = {
    'model': 'PubMedBERT + KL Divergence',
    'acc1': float(acc1), 'acc3': float(acc3), 'acc5': float(acc5),
    'macro_f1': float(f1), 'ndcg3': float(ndcg3), 'ndcg5': float(ndcg5),
    'mean_kl': float(kl),
    'best_val_acc': float(best_val_acc),
}
with open(os.path.join(MODEL_DIR, 'metrics.json'), 'w') as f:
    json.dump(metrics, f, indent=2)

log.info(f"\nFinal model saved → {MODEL_DIR}")
log.info(f"Metrics saved     → {os.path.join(MODEL_DIR, 'metrics.json')}")
log.info(f"\nNext: python scripts/evaluate_models.py")
