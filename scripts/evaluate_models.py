"""
scripts/evaluate_models.py

Generates the paper's results tables and figures by comparing:
  1. TF-IDF + LogisticRegression (baseline)
  2. DistilBERT + KL Divergence  (novel)

Outputs:
  docs/results_table.csv         — main comparison table
  docs/figures/calibration_*.png — calibration curves
  docs/figures/shap_summary.png  — SHAP feature importance for TF-IDF
  docs/per_disease_*.csv         — per-disease F1 for each model

Run from project root:
    pip install shap matplotlib
    python scripts/evaluate_models.py
"""

import os, sys, json, pickle, logging
import numpy as np
import pandas as pd
import torch
import torch.nn.functional as F

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)

if __name__ != '__main__':
    sys.exit(0)

ROOT_DIR    = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DDX_DIR     = os.path.join(ROOT_DIR, 'data', 'ddxplus')
TFIDF_DIR      = os.path.join(ROOT_DIR, 'models', 'ddxplus_tfidf')
BERT_DIR       = os.path.join(ROOT_DIR, 'models', 'ddxplus_model')
PUBMEDBERT_DIR = os.path.join(ROOT_DIR, 'models', 'pubmedbert_model')
DOCS_DIR    = os.path.join(ROOT_DIR, 'docs')
FIGS_DIR    = os.path.join(DOCS_DIR, 'figures')
os.makedirs(FIGS_DIR, exist_ok=True)

# ── Label map ─────────────────────────────────────────────────────────────────
with open(os.path.join(BERT_DIR, 'ddxplus_label_map.json')) as f:
    id_to_label = json.load(f)
num_labels  = len(id_to_label)
label_names = [id_to_label[str(i)] for i in range(num_labels)]

# ── Load test data ─────────────────────────────────────────────────────────────
log.info("Loading test set…")
test = pd.read_parquet(os.path.join(DDX_DIR, 'processed_test.parquet'))
X_test   = test['text'].values
y_hard   = test['label'].values
y_soft   = np.vstack(
    test['ddx_probs'].apply(lambda s: np.fromstring(s, sep=',').astype(np.float32)).values
)
log.info(f"Test rows: {len(test):,}")

# ── Metrics helper ─────────────────────────────────────────────────────────────
def compute_metrics(probs: np.ndarray, y_hard: np.ndarray, y_soft: np.ndarray) -> dict:
    from sklearn.metrics import f1_score, ndcg_score, classification_report

    preds = probs.argmax(axis=1)
    acc1  = (preds == y_hard).mean()
    acc3  = np.mean([y_hard[i] in np.argsort(probs[i])[-3:] for i in range(len(y_hard))])
    acc5  = np.mean([y_hard[i] in np.argsort(probs[i])[-5:] for i in range(len(y_hard))])
    f1    = f1_score(y_hard, preds, average='macro', zero_division=0)

    eps   = 1e-10
    kl    = (y_soft * np.log((y_soft + eps) / (probs + eps))).sum(axis=1).mean()

    try:
        ndcg3 = ndcg_score(y_soft, probs, k=3)
        ndcg5 = ndcg_score(y_soft, probs, k=5)
    except Exception:
        ndcg3 = ndcg5 = float('nan')

    # Mean rank of true label
    ranks = []
    for i in range(len(y_hard)):
        sorted_idx = np.argsort(probs[i])[::-1]
        rank = int(np.where(sorted_idx == y_hard[i])[0][0]) + 1
        ranks.append(rank)
    mean_rank = np.mean(ranks)

    report = classification_report(
        y_hard, preds, target_names=label_names, zero_division=0, output_dict=True
    )

    return {
        'acc1': acc1, 'acc3': acc3, 'acc5': acc5,
        'macro_f1': f1, 'ndcg3': ndcg3, 'ndcg5': ndcg5,
        'mean_kl': float(kl), 'mean_rank': mean_rank,
        'per_disease': report,
        'preds': preds,
    }

# ── 1. TF-IDF + LR ────────────────────────────────────────────────────────────
log.info("\n=== Evaluating TF-IDF + LogisticRegression ===")
with open(os.path.join(TFIDF_DIR, 'tfidf_vectorizer.pkl'), 'rb') as f: tfidf = pickle.load(f)
with open(os.path.join(TFIDF_DIR, 'lr_classifier.pkl'),    'rb') as f: lr    = pickle.load(f)

X_test_tfidf = tfidf.transform(X_test)
tfidf_probs  = lr.predict_proba(X_test_tfidf)
tfidf_m      = compute_metrics(tfidf_probs, y_hard, y_soft)
log.info(f"  Acc@1={tfidf_m['acc1']:.4f}  Acc@3={tfidf_m['acc3']:.4f}  "
         f"F1={tfidf_m['macro_f1']:.4f}  KL={tfidf_m['mean_kl']:.4f}")

# ── 2. DistilBERT + KL ────────────────────────────────────────────────────────
def eval_transformer_model(model_dir: str, model_name: str):
    """Load any HuggingFace model from model_dir and evaluate on the test set."""
    if not os.path.exists(os.path.join(model_dir, 'config.json')):
        log.warning(f"{model_name} not found at {model_dir} — skipping.")
        return None, None

    log.info(f"\n=== Evaluating {model_name} ===")
    from transformers import AutoTokenizer, AutoModelForSequenceClassification

    if torch.backends.mps.is_available(): device = torch.device('mps')
    elif torch.cuda.is_available():        device = torch.device('cuda')
    else:                                  device = torch.device('cpu')

    tok   = AutoTokenizer.from_pretrained(model_dir)
    mdl   = AutoModelForSequenceClassification.from_pretrained(model_dir)
    mdl.to(device).eval()

    all_probs = []
    BATCH = 64
    with torch.no_grad():
        for i in range(0, len(X_test), BATCH):
            batch_texts = list(X_test[i:i+BATCH])
            enc = tok(batch_texts, max_length=128, padding=True,
                      truncation=True, return_tensors='pt')
            enc = {k: v.to(device) for k, v in enc.items()}
            logits = mdl(**enc).logits
            all_probs.append(F.softmax(logits, dim=-1).cpu().numpy())
            if (i // BATCH) % 100 == 0:
                log.info(f"  Batch {i//BATCH}/{len(X_test)//BATCH}")

    probs = np.vstack(all_probs)
    m     = compute_metrics(probs, y_hard, y_soft)
    log.info(f"  Acc@1={m['acc1']:.4f}  Acc@3={m['acc3']:.4f}  "
             f"F1={m['macro_f1']:.4f}  KL={m['mean_kl']:.4f}")
    return probs, m

bert_probs, bert_m         = eval_transformer_model(BERT_DIR,       'DistilBERT + KL')
pubmed_probs, pubmed_m     = eval_transformer_model(PUBMEDBERT_DIR, 'PubMedBERT + KL')

# ── Comparison table ──────────────────────────────────────────────────────────
log.info("\n=== Results Comparison Table ===")
metrics_keys = ['acc1','acc3','acc5','macro_f1','ndcg3','ndcg5','mean_kl','mean_rank']
display_names = {
    'acc1': 'Acc@1', 'acc3': 'Acc@3', 'acc5': 'Acc@5',
    'macro_f1': 'Macro-F1', 'ndcg3': 'NDCG@3', 'ndcg5': 'NDCG@5',
    'mean_kl': 'Mean KL Div ↓', 'mean_rank': 'Mean Rank ↓',
}

all_models = [
    ('TF-IDF + LR',       tfidf_m),
    ('DistilBERT + KL',   bert_m),
    ('PubMedBERT + KL',   pubmed_m),
]

rows = {}
for model_name, m in all_models:
    if m is not None:
        rows[model_name] = {display_names[k]: f"{m[k]:.4f}" for k in metrics_keys}

results_df = pd.DataFrame(rows).T
print("\n" + results_df.to_string())

results_path = os.path.join(DOCS_DIR, 'results_table.csv')
results_df.to_csv(results_path)
log.info(f"\nResults table saved → {results_path}")

# ── Per-disease tables ─────────────────────────────────────────────────────────
per_disease_models = [
    ('tfidf_lr',      tfidf_m),
    ('distilbert_kl', bert_m),
    ('pubmedbert_kl', pubmed_m),
]
for name, m in per_disease_models:
    if m is None:
        continue
    per_d = pd.DataFrame(m['per_disease']).T
    path  = os.path.join(DOCS_DIR, f'per_disease_{name}.csv')
    per_d.to_csv(path)
    log.info(f"Per-disease table saved → {path}")

# ── Statistical significance tests ───────────────────────────────────────────
log.info("\n=== Statistical Significance Tests ===")

from scipy.stats import wilcoxon, chi2
from statsmodels.stats.contingency_tables import mcnemar as mcnemar_test

eps = 1e-10

def bootstrap_ci(probs, y_hard, y_soft, metric_fn, n_boot=1000, ci=95, seed=42):
    """Return (mean, lower, upper) via bootstrap resampling."""
    rng = np.random.default_rng(seed)
    n   = len(y_hard)
    vals = []
    for _ in range(n_boot):
        idx = rng.integers(0, n, size=n)
        vals.append(metric_fn(probs[idx], y_hard[idx], y_soft[idx]))
    lo = np.percentile(vals, (100 - ci) / 2)
    hi = np.percentile(vals, 100 - (100 - ci) / 2)
    return np.mean(vals), lo, hi

def _acc1(p, yh, _ys):   return (p.argmax(1) == yh).mean()
def _ndcg3(p, _yh, ys):
    from sklearn.metrics import ndcg_score
    return ndcg_score(ys, p, k=3)
def _kl(p, _yh, ys):
    return (ys * np.log((ys + eps) / (p + eps))).sum(axis=1).mean()

sig_rows = []

# ── 1. Bootstrap CIs ──────────────────────────────────────────────────────────
log.info("\n--- Bootstrap 95% Confidence Intervals (1,000 resamples) ---")
boot_models = [
    ('TF-IDF + LR',     tfidf_probs,  tfidf_m),
    ('DistilBERT + KL', bert_probs,   bert_m),
    ('PubMedBERT + KL', pubmed_probs, pubmed_m),
]
ci_rows = []
for name, probs, m in boot_models:
    if probs is None or m is None:
        continue
    a1_m, a1_lo, a1_hi       = bootstrap_ci(probs, y_hard, y_soft, _acc1)
    nd3_m, nd3_lo, nd3_hi    = bootstrap_ci(probs, y_hard, y_soft, _ndcg3)
    kl_m,  kl_lo,  kl_hi     = bootstrap_ci(probs, y_hard, y_soft, _kl)
    row = {
        'Model':          name,
        'Acc@1':          f"{m['acc1']:.4f}",
        'Acc@1 95% CI':   f"[{a1_lo:.4f}, {a1_hi:.4f}]",
        'NDCG@3':         f"{m['ndcg3']:.4f}",
        'NDCG@3 95% CI':  f"[{nd3_lo:.4f}, {nd3_hi:.4f}]",
        'Mean KL':        f"{m['mean_kl']:.4f}",
        'KL 95% CI':      f"[{kl_lo:.4f}, {kl_hi:.4f}]",
    }
    ci_rows.append(row)
    log.info(f"  {name}:")
    log.info(f"    Acc@1  = {m['acc1']:.4f}  95% CI [{a1_lo:.4f}, {a1_hi:.4f}]")
    log.info(f"    NDCG@3 = {m['ndcg3']:.4f}  95% CI [{nd3_lo:.4f}, {nd3_hi:.4f}]")
    log.info(f"    Mean KL= {m['mean_kl']:.4f}  95% CI [{kl_lo:.4f}, {kl_hi:.4f}]")

ci_df = pd.DataFrame(ci_rows).set_index('Model')
ci_path = os.path.join(DOCS_DIR, 'bootstrap_ci.csv')
ci_df.to_csv(ci_path)
log.info(f"Bootstrap CI table saved → {ci_path}")

# ── 2. McNemar's test (Acc@1 pairwise) ───────────────────────────────────────
log.info("\n--- McNemar's Test (pairwise Acc@1 comparisons) ---")
log.info("  H0: the two models make the same pattern of errors.")
log.info("  Reject H0 (significant difference) if p < 0.05.\n")

correct_tfidf  = (tfidf_m['preds']  == y_hard).astype(int)
correct_bert   = (bert_m['preds']   == y_hard).astype(int) if bert_m   else None
correct_pubmed = (pubmed_m['preds'] == y_hard).astype(int) if pubmed_m else None

def run_mcnemar(name_a, c_a, name_b, c_b):
    # Contingency table [[both correct, A only], [B only, both wrong]]
    both_correct  = ((c_a == 1) & (c_b == 1)).sum()
    a_only        = ((c_a == 1) & (c_b == 0)).sum()
    b_only        = ((c_a == 0) & (c_b == 1)).sum()
    both_wrong    = ((c_a == 0) & (c_b == 0)).sum()
    table = np.array([[both_correct, a_only], [b_only, both_wrong]])
    result = mcnemar_test(table, exact=False, correction=True)
    sig = "SIGNIFICANT" if result.pvalue < 0.05 else "not significant"
    log.info(f"  {name_a} vs {name_b}:")
    log.info(f"    Both correct={both_correct:,}  {name_a} only={a_only:,}  "
             f"{name_b} only={b_only:,}  Both wrong={both_wrong:,}")
    log.info(f"    chi2={result.statistic:.4f}  p={result.pvalue:.2e}  → {sig} (α=0.05)")
    return {
        'Comparison': f"{name_a} vs {name_b}",
        'Both correct': both_correct,
        f'{name_a} only correct': a_only,
        f'{name_b} only correct': b_only,
        'Both wrong': both_wrong,
        'chi2': round(result.statistic, 4),
        'p-value': f"{result.pvalue:.2e}",
        'Significant (α=0.05)': 'Yes' if result.pvalue < 0.05 else 'No',
    }

mcnemar_rows = []
if correct_bert is not None:
    mcnemar_rows.append(run_mcnemar('TF-IDF+LR', correct_tfidf, 'DistilBERT+KL', correct_bert))
if correct_pubmed is not None:
    mcnemar_rows.append(run_mcnemar('TF-IDF+LR', correct_tfidf, 'PubMedBERT+KL', correct_pubmed))
if correct_bert is not None and correct_pubmed is not None:
    mcnemar_rows.append(run_mcnemar('DistilBERT+KL', correct_bert, 'PubMedBERT+KL', correct_pubmed))

mcnemar_df = pd.DataFrame(mcnemar_rows)
mcnemar_path = os.path.join(DOCS_DIR, 'mcnemar_tests.csv')
mcnemar_df.to_csv(mcnemar_path, index=False)
log.info(f"McNemar results saved → {mcnemar_path}")

# ── 3. Wilcoxon signed-rank test (per-sample KL divergences) ─────────────────
log.info("\n--- Wilcoxon Signed-Rank Test (per-sample KL divergence) ---")
log.info("  H0: the two models produce identically distributed per-sample KL divergences.")
log.info("  Reject H0 if p < 0.05.\n")

def per_sample_kl(probs):
    return (y_soft * np.log((y_soft + eps) / (probs + eps))).sum(axis=1)

kl_tfidf  = per_sample_kl(tfidf_probs)
kl_bert   = per_sample_kl(bert_probs)   if bert_probs   is not None else None
kl_pubmed = per_sample_kl(pubmed_probs) if pubmed_probs is not None else None

wilcox_rows = []

def run_wilcoxon(name_a, kl_a, name_b, kl_b):
    # Use a subsample for speed (Wilcoxon on 134k pairs is slow)
    rng = np.random.default_rng(0)
    idx = rng.choice(len(kl_a), size=min(10_000, len(kl_a)), replace=False)
    stat, pval = wilcoxon(kl_a[idx], kl_b[idx], alternative='two-sided')
    sig = "SIGNIFICANT" if pval < 0.05 else "not significant"
    log.info(f"  {name_a} vs {name_b} (n=10,000 subsample):")
    log.info(f"    Mean KL: {kl_a.mean():.4f} vs {kl_b.mean():.4f}")
    log.info(f"    W={stat:.2f}  p={pval:.2e}  → {sig} (α=0.05)")
    return {
        'Comparison': f"{name_a} vs {name_b}",
        f'Mean KL {name_a}': round(kl_a.mean(), 4),
        f'Mean KL {name_b}': round(kl_b.mean(), 4),
        'W statistic': round(stat, 2),
        'p-value': f"{pval:.2e}",
        'Significant (α=0.05)': 'Yes' if pval < 0.05 else 'No',
    }

if kl_bert is not None:
    wilcox_rows.append(run_wilcoxon('TF-IDF+LR', kl_tfidf, 'DistilBERT+KL', kl_bert))
if kl_pubmed is not None:
    wilcox_rows.append(run_wilcoxon('TF-IDF+LR', kl_tfidf, 'PubMedBERT+KL', kl_pubmed))
if kl_bert is not None and kl_pubmed is not None:
    wilcox_rows.append(run_wilcoxon('DistilBERT+KL', kl_bert, 'PubMedBERT+KL', kl_pubmed))

wilcox_df = pd.DataFrame(wilcox_rows)
wilcox_path = os.path.join(DOCS_DIR, 'wilcoxon_kl.csv')
wilcox_df.to_csv(wilcox_path, index=False)
log.info(f"Wilcoxon results saved → {wilcox_path}")

# ── Calibration curves ────────────────────────────────────────────────────────
try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from sklearn.calibration import calibration_curve

    n_plots = 1 + (bert_probs is not None) + (pubmed_probs is not None)
    fig, axes = plt.subplots(1, n_plots, figsize=(6 * n_plots, 5))
    if n_plots == 1:
        axes = [axes]

    models_to_plot = [('TF-IDF + LR', tfidf_probs, tfidf_m)]
    if bert_probs is not None and bert_m is not None:
        models_to_plot.append(('DistilBERT + KL', bert_probs, bert_m))
    if pubmed_probs is not None and pubmed_m is not None:
        models_to_plot.append(('PubMedBERT + KL', pubmed_probs, pubmed_m))

    for ax, (name, probs, m) in zip(axes, models_to_plot):
        top_pred_probs = probs[np.arange(len(y_hard)), m['preds']]
        correct        = (m['preds'] == y_hard).astype(int)
        try:
            frac_pos, mean_pred = calibration_curve(correct, top_pred_probs, n_bins=10)
            ax.plot(mean_pred, frac_pos, 's-', label='Model')
            ax.plot([0,1], [0,1], 'k--', label='Perfectly calibrated')
            ax.set_xlabel('Mean predicted probability')
            ax.set_ylabel('Fraction of positives')
            ax.set_title(f'Calibration: {name}')
            ax.legend()
        except Exception as e:
            log.warning(f"Calibration plot failed for {name}: {e}")

    plt.tight_layout()
    cal_path = os.path.join(FIGS_DIR, 'calibration.png')
    plt.savefig(cal_path, dpi=150)
    plt.close()
    log.info(f"Calibration curves saved → {cal_path}")
except ImportError:
    log.warning("matplotlib not installed — skipping calibration plots. Run: pip install matplotlib")

# ── SHAP explanations (TF-IDF) ────────────────────────────────────────────────
try:
    import shap
    log.info("\n=== SHAP analysis for TF-IDF model ===")

    # Use a sample of 200 test instances for SHAP (it's slow on full test set)
    sample_idx   = np.random.choice(len(X_test), size=min(200, len(X_test)), replace=False)
    X_sample     = X_test_tfidf[sample_idx]
    feature_names = np.array(tfidf.get_feature_names_out())

    explainer   = shap.LinearExplainer(lr, shap.maskers.Independent(X_sample))
    shap_values = explainer.shap_values(X_sample)

    # Summary plot for the top-3 most frequent diseases
    top3_diseases = pd.Series(y_hard).value_counts().head(3).index.tolist()
    for disease_idx in top3_diseases:
        disease_name = label_names[disease_idx]
        sv = shap_values[disease_idx] if isinstance(shap_values, list) else shap_values
        shap_df = pd.DataFrame({'feature': feature_names, 'shap': np.abs(sv).mean(axis=0)})
        shap_df = shap_df.nlargest(20, 'shap')

        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(8, 6))
        ax.barh(shap_df['feature'], shap_df['shap'])
        ax.set_xlabel('Mean |SHAP value|')
        ax.set_title(f'Top features for: {disease_name}')
        ax.invert_yaxis()
        plt.tight_layout()
        safe_name = disease_name.replace('/', '_').replace(' ', '_')
        path = os.path.join(FIGS_DIR, f'shap_{safe_name}.png')
        plt.savefig(path, dpi=150)
        plt.close()
        log.info(f"  SHAP plot saved → {path}")

except ImportError:
    log.warning("shap not installed — skipping. Run: pip install shap matplotlib")
except Exception as e:
    log.warning(f"SHAP analysis failed: {e}")

log.info("\n=== Evaluation complete ===")
log.info(f"All outputs saved to: {DOCS_DIR}")
