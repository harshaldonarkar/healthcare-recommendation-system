"""
scripts/prepare_ddxplus.py

Converts raw DDXPlus CSVs into training-ready parquet files.
  - Decodes coded evidence IDs (E_91, E_55_@_V_89, ...) to English symptom text
  - Builds demographics-aware text: "28 year old male. fever, pain: forehead..."
  - Parses DIFFERENTIAL_DIAGNOSIS into 49-dim probability vectors
  - Stratified-samples 150k rows from the 1M train set (keeps class balance)
  - Saves processed_train/val/test.parquet + ddxplus_label_map.json

Run from project root (venv activated):
    pip install pyarrow
    python scripts/prepare_ddxplus.py
"""

import os, sys, json, ast, logging
import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)

ROOT_DIR  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DDX_DIR   = os.path.join(ROOT_DIR, 'data', 'ddxplus')
OUT_DIR   = DDX_DIR                                        # processed parquets go here
MODEL_DIR = os.path.join(ROOT_DIR, 'models', 'ddxplus_model')
os.makedirs(MODEL_DIR, exist_ok=True)

TRAIN_SAMPLE = 150_000   # rows to sample from the 1M train set

# ── Load metadata ─────────────────────────────────────────────────────────────
log.info("Loading metadata…")
with open(os.path.join(DDX_DIR, 'release_evidences.json'))  as f: evidences  = json.load(f)
with open(os.path.join(DDX_DIR, 'release_conditions.json')) as f: conditions = json.load(f)

# ── Build canonical label map (sorted alphabetically, 0-indexed) ─────────────
diseases_sorted = sorted(conditions.keys())
label_map    = {d: i for i, d in enumerate(diseases_sorted)}   # disease → int
id_to_label  = {str(i): d for d, i in label_map.items()}       # str-int → disease

lm_path = os.path.join(MODEL_DIR, 'ddxplus_label_map.json')
with open(lm_path, 'w') as f:
    json.dump(id_to_label, f, indent=2)
log.info(f"Saved label map → {lm_path}  ({len(label_map)} classes)")

# ── Evidence decoder ──────────────────────────────────────────────────────────
_BOILERPLATE = [
    "Do you have ", "Do you feel ", "Have you had ", "Have you been ",
    "Are you ", "Is your ", "Were you ", "Did you ",
]

def evidence_to_text(code: str) -> str:
    """E_91 → 'fever'   |   E_55_@_V_89 → 'pain somewhere: forehead'"""
    parts = code.split('_@_')
    base, val = parts[0], (parts[1] if len(parts) > 1 else None)
    ev = evidences.get(base, {})
    q  = ev.get('question_en', base)
    for bp in _BOILERPLATE:
        q = q.replace(bp, '')
    q = q.rstrip('?').strip()
    if val:
        meaning = ev.get('value_meaning', {}).get(val, {})
        loc = meaning.get('en', '') if isinstance(meaning, dict) else ''
        if loc and loc.lower() not in ('n/a', 'none', ''):
            return f"{q}: {loc}"
    return q

# ── DDX prob vector parser ────────────────────────────────────────────────────
def parse_ddx_probs(ddx_str: str) -> np.ndarray:
    """Returns a normalised 49-dim float32 vector from the DIFFERENTIAL_DIAGNOSIS string."""
    vec = np.zeros(len(label_map), dtype=np.float32)
    try:
        pairs = ast.literal_eval(ddx_str)
        for disease, prob in pairs:
            if disease in label_map:
                vec[label_map[disease]] = float(prob)
    except Exception:
        pass
    total = vec.sum()
    if total > 0:
        vec /= total          # normalise — DDX probs may not sum exactly to 1
    return vec

# ── Text builder ──────────────────────────────────────────────────────────────
def build_text(age, sex, evidences_str: str, initial_ev: str) -> str:
    """Produces a human-readable clinical text string for the model input."""
    sex_str = 'male' if str(sex).strip().upper() == 'M' else 'female'
    demo    = f"{age} year old {sex_str}."

    try:
        ev_codes = ast.literal_eval(evidences_str)
    except Exception:
        ev_codes = []

    symptom_texts = [evidence_to_text(c) for c in ev_codes]
    symptoms = ', '.join(symptom_texts)

    init = evidence_to_text(str(initial_ev).strip()) if pd.notna(initial_ev) else ''
    init_part = f" Initial complaint: {init}." if init else ''

    return f"{demo} {symptoms}.{init_part}".strip()

# ── Process one split ─────────────────────────────────────────────────────────
def process_split(split: str, sample_n: int | None = None) -> pd.DataFrame:
    path = os.path.join(DDX_DIR, f'{split}.csv')
    log.info(f"Reading {split}.csv …")

    if sample_n:
        # Stratified sample: read in chunks, sample proportionally per disease
        target_per_class = sample_n // len(label_map)
        class_counts: dict[str, int] = {d: 0 for d in label_map}
        rows = []
        for chunk in pd.read_csv(path, chunksize=50_000):
            for disease, grp in chunk.groupby('PATHOLOGY'):
                if disease not in class_counts:
                    continue
                remaining = target_per_class - class_counts[disease]
                if remaining <= 0:
                    continue
                take = grp.sample(n=min(len(grp), remaining), random_state=42)
                rows.append(take)
                class_counts[disease] += len(take)
            if min(class_counts.values()) >= target_per_class:
                break
        df = pd.concat(rows, ignore_index=True)
        log.info(f"  Sampled {len(df):,} rows (target {sample_n:,})")
    else:
        df = pd.read_csv(path)
        log.info(f"  Loaded {len(df):,} rows")

    # Build features
    log.info(f"  Building text features…")
    df['text'] = df.apply(
        lambda r: build_text(r['AGE'], r['SEX'], r['EVIDENCES'], r['INITIAL_EVIDENCE']),
        axis=1
    )

    log.info(f"  Parsing differential diagnosis vectors…")
    ddx_arrays = df['DIFFERENTIAL_DIAGNOSIS'].apply(parse_ddx_probs)
    # Serialise as comma-separated string (parquet-safe, fast to reconstruct)
    df['ddx_probs'] = ddx_arrays.apply(lambda a: ','.join(f'{x:.6f}' for x in a))

    df['label']    = df['PATHOLOGY'].map(label_map).fillna(-1).astype(int)
    df['pathology'] = df['PATHOLOGY']

    # Drop rows whose PATHOLOGY isn't in our 49-disease map (shouldn't happen)
    dropped = (df['label'] == -1).sum()
    if dropped:
        log.warning(f"  Dropping {dropped} rows with unknown PATHOLOGY")
        df = df[df['label'] != -1]

    out = df[['text', 'label', 'ddx_probs', 'pathology']].reset_index(drop=True)
    return out

# ── Run all three splits ──────────────────────────────────────────────────────
for split, n in [('train', TRAIN_SAMPLE), ('validate', None), ('test', None)]:
    df = process_split(split, sample_n=n)
    out_path = os.path.join(OUT_DIR, f'processed_{split}.parquet')
    df.to_parquet(out_path, index=False)
    size_mb = os.path.getsize(out_path) / 1e6
    log.info(f"  Saved → {out_path}  ({len(df):,} rows, {size_mb:.1f} MB)")
    # Quick sanity check
    log.info(f"  Sample text: {df['text'].iloc[0][:120]}")
    log.info(f"  DDX probs non-zero: {(np.fromstring(df['ddx_probs'].iloc[0], sep=',') > 0).sum()} / {len(label_map)}")
    print()

log.info("=== Data preparation complete ===")
log.info(f"  Outputs : {OUT_DIR}/processed_{{train,validate,test}}.parquet")
log.info(f"  Labels  : {lm_path}")
log.info(f"\nNext: python scripts/train_baseline.py")
