"""
scripts/run_significance_tests.py
Statistical significance tests for the paper.

Outputs:
  docs/bootstrap_ci.csv    — 95% bootstrap confidence intervals
  docs/mcnemar_tests.csv   — McNemar's test (pairwise Acc@1)
  docs/wilcoxon_kl.csv     — Wilcoxon signed-rank test (per-sample KL)

Run from project root with the project venv:
    python scripts/run_significance_tests.py
"""

import os, sys, json, pickle, logging
import numpy as np
import pandas as pd
import torch
import torch.nn.functional as F
from scipy.stats import wilcoxon
from statsmodels.stats.contingency_tables import mcnemar as mcnemar_test

if __name__ != '__main__':
    sys.exit(0)

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)

ROOT     = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DDX_DIR  = os.path.join(ROOT, 'data', 'ddxplus')
TFIDF    = os.path.join(ROOT, 'models', 'ddxplus_tfidf')
BERT     = os.path.join(ROOT, 'models', 'ddxplus_model')
PUBMED   = os.path.join(ROOT, 'models', 'pubmedbert_model')
DOCS     = os.path.join(ROOT, 'docs')
os.makedirs(DOCS, exist_ok=True)

# ── Load test set ─────────────────────────────────────────────────────────────
log.info("Loading test set…")
test   = pd.read_parquet(os.path.join(DDX_DIR, 'processed_test.parquet'))
X_test = test['text'].values
y_hard = test['label'].values
y_soft = np.vstack(
    test['ddx_probs'].apply(lambda s: np.fromstring(s, sep=',').astype(np.float32)).values
)
log.info(f"Test rows: {len(test):,}")

# ── TF-IDF ────────────────────────────────────────────────────────────────────
log.info("Computing TF-IDF probabilities…")
with open(os.path.join(TFIDF, 'tfidf_vectorizer.pkl'), 'rb') as f: vec = pickle.load(f)
with open(os.path.join(TFIDF, 'lr_classifier.pkl'),    'rb') as f: lr  = pickle.load(f)
tfidf_probs = lr.predict_proba(vec.transform(X_test))

# ── Transformer inference ─────────────────────────────────────────────────────
def get_probs(model_dir, label):
    from transformers import AutoTokenizer, AutoModelForSequenceClassification
    if not os.path.exists(os.path.join(model_dir, 'config.json')):
        log.warning(f"{label} not found — skipping")
        return None
    device = torch.device('mps' if torch.backends.mps.is_available() else
                          'cuda' if torch.cuda.is_available() else 'cpu')
    log.info(f"Loading {label} on {device}…")
    tok = AutoTokenizer.from_pretrained(model_dir)
    mdl = AutoModelForSequenceClassification.from_pretrained(model_dir).to(device).eval()
    out = []
    with torch.no_grad():
        for i in range(0, len(X_test), 64):
            enc = tok(list(X_test[i:i+64]), max_length=128, padding=True,
                      truncation=True, return_tensors='pt')
            enc = {k: v.to(device) for k, v in enc.items()}
            out.append(F.softmax(mdl(**enc).logits, dim=-1).cpu().numpy())
            if (i // 64) % 200 == 0:
                log.info(f"  {label} batch {i//64}/{len(X_test)//64}")
    return np.vstack(out)

bert_probs   = get_probs(BERT,   'DistilBERT+KL')
pubmed_probs = get_probs(PUBMED, 'PubMedBERT+KL')

eps = 1e-10

# ── 1. Bootstrap 95% CI ───────────────────────────────────────────────────────
log.info("\n=== Bootstrap 95% Confidence Intervals (1,000 resamples) ===")

def bootstrap(probs, metric_fn, n=1000, seed=42):
    rng  = np.random.default_rng(seed)
    N    = len(y_hard)
    vals = []
    for _ in range(n):
        idx = rng.integers(0, N, N)
        vals.append(metric_fn(probs[idx], y_hard[idx], y_soft[idx]))
    return np.mean(vals), np.percentile(vals, 2.5), np.percentile(vals, 97.5)

def m_acc1(p, yh, _ys):  return (p.argmax(1) == yh).mean()
def m_ndcg3(p, _yh, ys):
    from sklearn.metrics import ndcg_score
    return ndcg_score(ys, p, k=3)
def m_kl(p, _yh, ys):    return (ys * np.log((ys + eps) / (p + eps))).sum(1).mean()

ci_rows = []
for name, probs in [('TF-IDF+LR', tfidf_probs),
                    ('DistilBERT+KL', bert_probs),
                    ('PubMedBERT+KL', pubmed_probs)]:
    if probs is None:
        continue
    a1,  a1l,  a1h  = bootstrap(probs, m_acc1)
    nd,  ndl,  ndh  = bootstrap(probs, m_ndcg3)
    kl,  kll,  klh  = bootstrap(probs, m_kl)
    log.info(f"  {name}:")
    log.info(f"    Acc@1  = {a1:.4f}  95% CI [{a1l:.4f}, {a1h:.4f}]")
    log.info(f"    NDCG@3 = {nd:.4f}  95% CI [{ndl:.4f}, {ndh:.4f}]")
    log.info(f"    Mean KL= {kl:.4f}  95% CI [{kll:.4f}, {klh:.4f}]")
    ci_rows.append({
        'Model': name,
        'Acc@1': f'{a1:.4f}',   'Acc@1 95% CI':  f'[{a1l:.4f}, {a1h:.4f}]',
        'NDCG@3': f'{nd:.4f}',  'NDCG@3 95% CI': f'[{ndl:.4f}, {ndh:.4f}]',
        'Mean KL': f'{kl:.4f}', 'KL 95% CI':     f'[{kll:.4f}, {klh:.4f}]',
    })

ci_path = os.path.join(DOCS, 'bootstrap_ci.csv')
pd.DataFrame(ci_rows).to_csv(ci_path, index=False)
log.info(f"Saved → {ci_path}")

# ── 2. McNemar's Test (pairwise Acc@1) ───────────────────────────────────────
log.info("\n=== McNemar's Test (pairwise Acc@1) ===")
log.info("  H0: both models make identical error patterns. Reject if p < 0.05.\n")

ct = (tfidf_probs.argmax(1)  == y_hard).astype(int)
cb = (bert_probs.argmax(1)   == y_hard).astype(int) if bert_probs   is not None else None
cp = (pubmed_probs.argmax(1) == y_hard).astype(int) if pubmed_probs is not None else None

def mcn(na, ca, nb, cb_):
    table = np.array([
        [int(((ca==1) & (cb_==1)).sum()), int(((ca==1) & (cb_==0)).sum())],
        [int(((ca==0) & (cb_==1)).sum()), int(((ca==0) & (cb_==0)).sum())],
    ])
    r   = mcnemar_test(table, exact=False, correction=True)
    sig = 'YES' if r.pvalue < 0.05 else 'NO'
    log.info(f"  {na} vs {nb}:")
    log.info(f"    Contingency: both_correct={table[0,0]:,}  {na}_only={table[0,1]:,}  "
             f"{nb}_only={table[1,0]:,}  both_wrong={table[1,1]:,}")
    log.info(f"    chi2={r.statistic:.4f}  p={r.pvalue:.2e}  Significant={sig}")
    return {
        'Comparison': f'{na} vs {nb}',
        'Both correct': table[0, 0],
        f'{na} only': table[0, 1],
        f'{nb} only': table[1, 0],
        'Both wrong': table[1, 1],
        'chi2': round(r.statistic, 4),
        'p-value': f'{r.pvalue:.2e}',
        'Significant (p<0.05)': sig,
    }

mcn_rows = []
if cb is not None: mcn_rows.append(mcn('TF-IDF+LR', ct, 'DistilBERT+KL',  cb))
if cp is not None: mcn_rows.append(mcn('TF-IDF+LR', ct, 'PubMedBERT+KL',  cp))
if cb is not None and cp is not None:
    mcn_rows.append(mcn('DistilBERT+KL', cb, 'PubMedBERT+KL', cp))

mcn_path = os.path.join(DOCS, 'mcnemar_tests.csv')
pd.DataFrame(mcn_rows).to_csv(mcn_path, index=False)
log.info(f"Saved → {mcn_path}")

# ── 3. Wilcoxon Signed-Rank Test (per-sample KL) ──────────────────────────────
log.info("\n=== Wilcoxon Signed-Rank Test (per-sample KL divergence) ===")
log.info("  H0: identical KL distribution. Reject if p < 0.05.\n")

def per_kl(p): return (y_soft * np.log((y_soft + eps) / (p + eps))).sum(1)

kt = per_kl(tfidf_probs)
kb = per_kl(bert_probs)   if bert_probs   is not None else None
kp = per_kl(pubmed_probs) if pubmed_probs is not None else None

# Subsample 10k for speed (Wilcoxon on 134k pairs is slow)
idx = np.random.default_rng(0).choice(len(kt), 10_000, replace=False)

def wcx(na, ka, nb, kb_):
    stat, pval = wilcoxon(ka[idx], kb_[idx], alternative='two-sided')
    sig = 'YES' if pval < 0.05 else 'NO'
    log.info(f"  {na} vs {nb}  (n=10,000 subsample):")
    log.info(f"    Mean KL: {ka.mean():.4f} vs {kb_.mean():.4f}")
    log.info(f"    W={stat:.0f}  p={pval:.2e}  Significant={sig}")
    return {
        'Comparison': f'{na} vs {nb}',
        f'Mean KL ({na})': round(float(ka.mean()), 4),
        f'Mean KL ({nb})': round(float(kb_.mean()), 4),
        'W statistic': int(stat),
        'p-value': f'{pval:.2e}',
        'Significant (p<0.05)': sig,
    }

wcx_rows = []
if kb is not None: wcx_rows.append(wcx('TF-IDF+LR',    kt, 'DistilBERT+KL',  kb))
if kp is not None: wcx_rows.append(wcx('TF-IDF+LR',    kt, 'PubMedBERT+KL',  kp))
if kb is not None and kp is not None:
    wcx_rows.append(wcx('DistilBERT+KL', kb, 'PubMedBERT+KL', kp))

wcx_path = os.path.join(DOCS, 'wilcoxon_kl.csv')
pd.DataFrame(wcx_rows).to_csv(wcx_path, index=False)
log.info(f"Saved → {wcx_path}")

# ── 4. Expected Calibration Error (ECE) ──────────────────────────────────────
log.info("\n=== Expected Calibration Error (ECE, 15 equal-width bins) ===")

def compute_ece(probs, y_hard, n_bins=15):
    """
    ECE = Σ_b (|B_b|/N) |accuracy(B_b) - confidence(B_b)|
    Bins are over the top-1 predicted probability (max confidence).
    """
    confidences = probs.max(axis=1)        # top-1 probability for each sample
    predictions = probs.argmax(axis=1)
    correct     = (predictions == y_hard).astype(float)
    N = len(y_hard)
    bin_edges = np.linspace(0.0, 1.0, n_bins + 1)
    ece = 0.0
    for lo, hi in zip(bin_edges[:-1], bin_edges[1:]):
        mask = (confidences >= lo) & (confidences < hi)
        if mask.sum() == 0:
            continue
        acc  = correct[mask].mean()
        conf = confidences[mask].mean()
        ece += (mask.sum() / N) * abs(acc - conf)
    return float(ece)

ece_rows = []
for name, probs in [('TF-IDF+LR', tfidf_probs),
                    ('DistilBERT+KL', bert_probs),
                    ('PubMedBERT+KL', pubmed_probs)]:
    if probs is None:
        continue
    ece = compute_ece(probs, y_hard)
    log.info(f"  {name}: ECE = {ece:.4f}")
    ece_rows.append({'Model': name, 'ECE': round(ece, 4)})

ece_path = os.path.join(DOCS, 'ece_scores.csv')
pd.DataFrame(ece_rows).to_csv(ece_path, index=False)
log.info(f"Saved → {ece_path}")

log.info("\n=== All significance tests complete ===")
log.info(f"Outputs in: {DOCS}")
