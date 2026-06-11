# src/training/training_model.py
#
# Trains two models:
#   1. TF-IDF + LogisticRegression (fast, reliable, saved as pickle)
#   2. BERT fine-tuned classifier (saved to models/fine_tuned_model/)
#
# Primary data: data/dataset.csv (4,920 rows, 41 diseases, 17 symptom cols)
# Enrichment:   data/Symptom-severity.csv, symptom_precaution.csv,
#               symptom_Description.csv, medical_data_complete.csv

import os, sys, json, random, re, pickle, logging
import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report, accuracy_score
import torch

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler("training.log"), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

os.environ["TOKENIZERS_PARALLELISM"] = "false"

# On macOS, Python's multiprocessing default is 'spawn', which re-imports this
# script in every worker process. Guard here so workers exit immediately instead
# of restarting the full training run (which would cause exponential RAM usage).
if __name__ != '__main__':
    sys.exit(0)

# ── Paths ────────────────────────────────────────────────────────────────────
_HERE     = os.path.dirname(__file__)
ROOT_DIR  = os.path.dirname(os.path.dirname(_HERE))
DATA_DIR  = os.path.join(ROOT_DIR, 'data')
MODELS_DIR = os.path.join(ROOT_DIR, 'models')
BERT_DIR  = os.path.join(MODELS_DIR, 'fine_tuned_model')
TFIDF_DIR = os.path.join(MODELS_DIR, 'tfidf_model')
os.makedirs(BERT_DIR, exist_ok=True)
os.makedirs(TFIDF_DIR, exist_ok=True)

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
logger.info(f"Device: {device}")

# ── Load data ─────────────────────────────────────────────────────────────────
logger.info("Loading datasets…")

ds = pd.read_csv(os.path.join(DATA_DIR, 'dataset.csv'))
logger.info(f"dataset.csv: {len(ds)} rows, {ds['Disease'].nunique()} diseases")

severity_df = pd.read_csv(os.path.join(DATA_DIR, 'Symptom-severity.csv'))
severity_df.columns = [c.strip() for c in severity_df.columns]
severity_map = dict(zip(
    severity_df['Symptom'].str.strip().str.lower().str.replace(' ', '_'),
    severity_df['weight']
))

precaution_df = pd.read_csv(os.path.join(DATA_DIR, 'symptom_precaution.csv'))
desc_df       = pd.read_csv(os.path.join(DATA_DIR, 'symptom_Description.csv'))

# medical_data_complete.csv — for medicines/diets (some diseases may overlap)
try:
    mdc = pd.read_csv(os.path.join(DATA_DIR, 'medical_data_complete.csv'))
    logger.info(f"medical_data_complete.csv: {len(mdc)} rows")
except Exception:
    mdc = pd.DataFrame()

# ── Normalise disease names ───────────────────────────────────────────────────
def normalise(name: str) -> str:
    return re.sub(r'\s+', ' ', str(name).strip()).title()

ds['Disease'] = ds['Disease'].apply(normalise)

# ── Build symptom list per row ────────────────────────────────────────────────
SYMP_COLS = [c for c in ds.columns if c.lower().startswith('symptom_')]

def row_symptoms(row) -> list:
    syms = []
    for col in SYMP_COLS:
        val = row[col]
        if pd.notna(val) and str(val).strip():
            cleaned = str(val).strip().lower().replace(' ', '_')
            syms.append(cleaned)
    return syms

ds['symptom_list'] = ds.apply(row_symptoms, axis=1)
ds = ds[ds['symptom_list'].map(len) > 0].reset_index(drop=True)
logger.info(f"After dropping empty rows: {len(ds)}")

# ── Augmentation helpers ──────────────────────────────────────────────────────
# ── Config: set TRAIN_BERT=True only if you have a GPU or plenty of free RAM ─
TRAIN_BERT = False   # TF-IDF+LR is accurate enough for symptom matching

PREFIXES = [
    "i have {syms}",
    "my symptoms are {syms}",
    "i am experiencing {syms}",
    "{syms}",
    "patient presents with {syms}",
    "symptoms include {syms}",
]

SEPARATORS = [", ", " and ", " "]

def human_name(sym: str) -> str:
    """Convert snake_case symptom to human-readable."""
    return sym.replace('_', ' ').strip()

def make_text(syms: list, prefix_tmpl: str, sep: str) -> str:
    text = sep.join(human_name(s) for s in syms)
    return prefix_tmpl.format(syms=text)

def weighted_subset(syms: list, keep_frac: float = 0.7) -> list:
    """Return a random subset weighted by severity (higher = more likely kept)."""
    if len(syms) <= 2:
        return syms
    weights = [severity_map.get(s, 3) for s in syms]
    total   = sum(weights)
    probs   = [w / total for w in weights]
    n_keep  = max(2, int(len(syms) * keep_frac))
    chosen  = np.random.choice(syms, size=min(n_keep, len(syms)), replace=False, p=probs)
    return list(chosen)

random.seed(42)
np.random.seed(42)

augmented = []

for _, row in ds.iterrows():
    disease = row['Disease']
    syms    = row['symptom_list']
    if not syms:
        continue

    # --- Full symptom set with all prefix/separator combos ---
    for pfx in PREFIXES:
        for sep in SEPARATORS:
            augmented.append({'text': make_text(syms, pfx, sep), 'disease': disease})

    # --- Reversed order ---
    rev = list(reversed(syms))
    augmented.append({'text': make_text(rev, random.choice(PREFIXES), ", "), 'disease': disease})

    # --- Severity-weighted 70% subset (2 variants) ---
    for _ in range(2):
        sub = weighted_subset(syms, keep_frac=0.7)
        augmented.append({'text': make_text(sub, random.choice(PREFIXES), ", "), 'disease': disease})

    # --- Random 50% subset (1 variant) ---
    n   = max(2, len(syms) // 2)
    sub = random.sample(syms, n)
    augmented.append({'text': make_text(sub, random.choice(PREFIXES), ", "), 'disease': disease})

    # --- Add description as training sample ---
    desc_row = desc_df[desc_df['Disease'].str.strip().str.lower() == disease.lower()]
    if not desc_row.empty:
        desc_text = str(desc_row.iloc[0]['Description'])
        augmented.append({'text': desc_text, 'disease': disease})

aug_df = pd.DataFrame(augmented)

def clean(text: str) -> str:
    text = str(text).lower()
    text = re.sub(r'[^\w\s,;.]', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()

aug_df['text'] = aug_df['text'].apply(clean)
aug_df = aug_df[aug_df['text'].str.len() > 4].reset_index(drop=True)
aug_df = aug_df.drop_duplicates(subset=['text']).reset_index(drop=True)

logger.info(f"Augmented dataset: {len(aug_df)} samples, {aug_df['disease'].nunique()} diseases")

# ── Label mapping ─────────────────────────────────────────────────────────────
diseases_sorted = sorted(aug_df['disease'].unique())
label_map       = {d: i for i, d in enumerate(diseases_sorted)}   # disease → int
id_to_label     = {str(i): d for d, i in label_map.items()}       # str-int → disease

aug_df['label'] = aug_df['disease'].map(label_map)

# Save label map (same format used by core.py: {"0": "Disease", "1": "Disease", ...})
lm_path = os.path.join(BERT_DIR, 'label_map.json')
with open(lm_path, 'w') as f:
    json.dump(id_to_label, f, indent=2)
logger.info(f"Saved label map → {lm_path}  ({len(label_map)} classes)")

# Also copy to tfidf dir
lm_path2 = os.path.join(TFIDF_DIR, 'label_map.json')
with open(lm_path2, 'w') as f:
    json.dump(id_to_label, f, indent=2)

# ── TF-IDF + LogisticRegression ───────────────────────────────────────────────
logger.info("\n=== Training TF-IDF + LogisticRegression ===")

X = aug_df['text'].values
y = aug_df['label'].values

X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.15, random_state=42, stratify=y
)
logger.info(f"Train: {len(X_train)}  Test: {len(X_test)}")

tfidf = TfidfVectorizer(
    ngram_range=(1, 3),
    max_features=30_000,
    sublinear_tf=True,
    min_df=2,
)
X_train_tfidf = tfidf.fit_transform(X_train)
X_test_tfidf  = tfidf.transform(X_test)

lr = LogisticRegression(
    max_iter=2000,
    C=5.0,
    solver='lbfgs',
    random_state=42,
)
lr.fit(X_train_tfidf, y_train)

y_pred = lr.predict(X_test_tfidf)
acc    = accuracy_score(y_test, y_pred)
logger.info(f"TF-IDF+LR Test Accuracy: {acc:.4f}")
logger.info("\n" + classification_report(y_test, y_pred,
    target_names=[diseases_sorted[i] for i in sorted(set(y_test))],
    zero_division=0))

tfidf_path = os.path.join(TFIDF_DIR, 'tfidf_vectorizer.pkl')
lr_path    = os.path.join(TFIDF_DIR, 'lr_classifier.pkl')
with open(tfidf_path, 'wb') as f: pickle.dump(tfidf, f)
with open(lr_path,    'wb') as f: pickle.dump(lr,    f)
logger.info(f"Saved TF-IDF vectorizer → {tfidf_path}")
logger.info(f"Saved LR classifier     → {lr_path}")

# ── BERT fine-tuning (skipped unless TRAIN_BERT=True) ────────────────────────
if TRAIN_BERT:
    try:
        from transformers import (BertTokenizer, BertForSequenceClassification,
                                  Trainer, TrainingArguments)
        from datasets import Dataset as HFDataset

        bert_train = aug_df.sample(frac=0.85, random_state=42)[['text', 'label']].rename(
            columns={'text': 'processed_text'})
        bert_test = aug_df.drop(bert_train.index)[['text', 'label']].rename(
            columns={'text': 'processed_text'})

        bert_tok = BertTokenizer.from_pretrained('bert-base-uncased')

        def tokenize_fn(batch):
            return bert_tok(batch['processed_text'],
                            padding='max_length', truncation=True, max_length=128)

        train_hf = HFDataset.from_pandas(bert_train.reset_index(drop=True))
        test_hf  = HFDataset.from_pandas(bert_test.reset_index(drop=True))
        train_hf = train_hf.map(tokenize_fn, batched=True)
        test_hf  = test_hf.map(tokenize_fn,  batched=True)

        bert_model = BertForSequenceClassification.from_pretrained(
            'bert-base-uncased', num_labels=len(label_map)
        )

        bert_args = TrainingArguments(
            output_dir='./results',
            num_train_epochs=5,
            per_device_train_batch_size=16,
            per_device_eval_batch_size=32,
            logging_dir='./logs',
            evaluation_strategy="epoch",
            save_strategy="epoch",
            logging_steps=50,
            learning_rate=3e-5,
            weight_decay=0.01,
            warmup_ratio=0.1,
            load_best_model_at_end=True,
            metric_for_best_model="eval_loss",
            dataloader_num_workers=0,
            fp16=torch.cuda.is_available(),
        )

        trainer = Trainer(
            model=bert_model,
            args=bert_args,
            train_dataset=train_hf,
            eval_dataset=test_hf,
            tokenizer=bert_tok,
        )

        trainer.train()
        bert_model.save_pretrained(BERT_DIR)
        bert_tok.save_pretrained(BERT_DIR)
        logger.info(f"BERT saved → {BERT_DIR}")

    except Exception as bert_err:
        logger.error(f"BERT training failed: {bert_err} — TF-IDF model is still available.")
else:
    logger.info("\n=== BERT training skipped (TRAIN_BERT=False) ===")
    logger.info("    Set TRAIN_BERT=True at the top of this file if you have a GPU.")

logger.info("\n=== Training complete ===")
logger.info(f"  Classes : {len(label_map)}")
logger.info(f"  Samples : {len(aug_df)}")
logger.info(f"  TF-IDF  : {tfidf_path}")
logger.info(f"  LR      : {lr_path}")
logger.info(f"  BERT    : {BERT_DIR}")
