"""
scripts/train_baseline.py

Trains TF-IDF + LogisticRegression on DDXPlus processed data.

Baseline for the paper — same architecture as the existing symptom model
but trained on 150k DDXPlus samples with 49 diseases.

At inference time we use predict_proba() to produce a 49-dim probability
distribution, giving us a soft "differential diagnosis" from a classical ML model.

Saves to: models/ddxplus_tfidf/

Run from project root:
    python scripts/train_baseline.py
"""

import os, sys, json, logging, pickle
import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, f1_score, classification_report

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    handlers=[
        logging.FileHandler('training_ddxplus_baseline.log'),
        logging.StreamHandler(),
    ]
)
log = logging.getLogger(__name__)

if __name__ != '__main__':
    sys.exit(0)

ROOT_DIR  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DDX_DIR   = os.path.join(ROOT_DIR, 'data', 'ddxplus')
MODEL_DIR = os.path.join(ROOT_DIR, 'models', 'ddxplus_tfidf')
os.makedirs(MODEL_DIR, exist_ok=True)

# ── Load label map ────────────────────────────────────────────────────────────
lm_path = os.path.join(ROOT_DIR, 'models', 'ddxplus_model', 'ddxplus_label_map.json')
with open(lm_path) as f:
    id_to_label = json.load(f)
label_names = [id_to_label[str(i)] for i in range(len(id_to_label))]
log.info(f"Classes: {len(label_names)}")

# ── Load data ─────────────────────────────────────────────────────────────────
log.info("Loading processed parquet files…")
train = pd.read_parquet(os.path.join(DDX_DIR, 'processed_train.parquet'))
val   = pd.read_parquet(os.path.join(DDX_DIR, 'processed_validate.parquet'))
test  = pd.read_parquet(os.path.join(DDX_DIR, 'processed_test.parquet'))

log.info(f"Train: {len(train):,}  Val: {len(val):,}  Test: {len(test):,}")

X_train, y_train = train['text'].values, train['label'].values
X_val,   y_val   = val['text'].values,   val['label'].values
X_test,  y_test  = test['text'].values,  test['label'].values

# Parse gold DDX probability matrices for evaluation
def load_ddx_matrix(df: pd.DataFrame) -> np.ndarray:
    return np.vstack(
        df['ddx_probs'].apply(lambda s: np.fromstring(s, sep=',').astype(np.float32)).values
    )

log.info("Parsing gold DDX probability matrices…")
y_test_soft = load_ddx_matrix(test)

# ── TF-IDF ────────────────────────────────────────────────────────────────────
log.info("\n=== Fitting TF-IDF vectorizer ===")
tfidf = TfidfVectorizer(
    ngram_range=(1, 3),
    max_features=30_000,
    sublinear_tf=True,
    min_df=2,
)
X_train_tfidf = tfidf.fit_transform(X_train)
X_val_tfidf   = tfidf.transform(X_val)
X_test_tfidf  = tfidf.transform(X_test)
log.info(f"Vocabulary size: {len(tfidf.vocabulary_):,}")

# ── Logistic Regression ───────────────────────────────────────────────────────
log.info("\n=== Training LogisticRegression ===")
lr = LogisticRegression(
    max_iter=2000,
    C=5.0,
    solver='lbfgs',
    random_state=42,
)
lr.fit(X_train_tfidf, y_train)
log.info("Training complete.")

# ── Evaluate on validation ────────────────────────────────────────────────────
val_pred  = lr.predict(X_val_tfidf)
val_acc   = accuracy_score(y_val, val_pred)
val_f1    = f1_score(y_val, val_pred, average='macro', zero_division=0)
log.info(f"Val  Accuracy: {val_acc:.4f}   Macro-F1: {val_f1:.4f}")

# ── Evaluate on test ──────────────────────────────────────────────────────────
log.info("\n=== Test set evaluation ===")
test_proba = lr.predict_proba(X_test_tfidf)  # (N, 49) soft predictions
test_pred  = np.argmax(test_proba, axis=1)

# Top-1
acc1 = accuracy_score(y_test, test_pred)

# Top-3
top3_hits = sum(
    y_test[i] in np.argsort(test_proba[i])[-3:]
    for i in range(len(y_test))
)
acc3 = top3_hits / len(y_test)

# Top-5
top5_hits = sum(
    y_test[i] in np.argsort(test_proba[i])[-5:]
    for i in range(len(y_test))
)
acc5 = top5_hits / len(y_test)

# Macro F1
f1 = f1_score(y_test, test_pred, average='macro', zero_division=0)

# Mean KL divergence  (gold || predicted)
eps = 1e-10
kl_per_sample = (y_test_soft * np.log((y_test_soft + eps) / (test_proba + eps))).sum(axis=1)
mean_kl = kl_per_sample.mean()

# NDCG@3 and NDCG@5
try:
    from sklearn.metrics import ndcg_score
    ndcg3 = ndcg_score(y_test_soft, test_proba, k=3)
    ndcg5 = ndcg_score(y_test_soft, test_proba, k=5)
except Exception:
    ndcg3 = ndcg5 = float('nan')

log.info(f"\n{'Metric':<25} {'TF-IDF+LR':>12}")
log.info("-" * 40)
log.info(f"{'Acc@1':<25} {acc1:>12.4f}")
log.info(f"{'Acc@3':<25} {acc3:>12.4f}")
log.info(f"{'Acc@5':<25} {acc5:>12.4f}")
log.info(f"{'Macro-F1':<25} {f1:>12.4f}")
log.info(f"{'NDCG@3':<25} {ndcg3:>12.4f}")
log.info(f"{'NDCG@5':<25} {ndcg5:>12.4f}")
log.info(f"{'Mean KL Div (↓)':<25} {mean_kl:>12.4f}")

# Per-disease report
report = classification_report(
    y_test, test_pred,
    target_names=label_names,
    zero_division=0,
    output_dict=True,
)
report_df = pd.DataFrame(report).T
report_path = os.path.join(MODEL_DIR, 'baseline_per_disease.csv')
report_df.to_csv(report_path)
log.info(f"\nPer-disease report saved → {report_path}")

# Full text report to log
log.info("\n" + classification_report(y_test, test_pred, target_names=label_names, zero_division=0))

# ── Save artifacts ────────────────────────────────────────────────────────────
tfidf_path = os.path.join(MODEL_DIR, 'tfidf_vectorizer.pkl')
lr_path    = os.path.join(MODEL_DIR, 'lr_classifier.pkl')
with open(tfidf_path, 'wb') as f: pickle.dump(tfidf, f)
with open(lr_path,    'wb') as f: pickle.dump(lr, f)

# Save label map alongside model
import shutil
shutil.copy(lm_path, os.path.join(MODEL_DIR, 'ddxplus_label_map.json'))

# Save metrics as JSON for the evaluation script to pick up
metrics = {
    'model': 'TF-IDF + LogisticRegression',
    'acc1': acc1, 'acc3': acc3, 'acc5': acc5,
    'macro_f1': f1, 'ndcg3': ndcg3, 'ndcg5': ndcg5,
    'mean_kl': float(mean_kl),
}
with open(os.path.join(MODEL_DIR, 'metrics.json'), 'w') as f:
    json.dump(metrics, f, indent=2)

log.info(f"\nSaved TF-IDF  → {tfidf_path}")
log.info(f"Saved LR      → {lr_path}")
log.info(f"\nNext: python scripts/train_bert_ddx.py")
