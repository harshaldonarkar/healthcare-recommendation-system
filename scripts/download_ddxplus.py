"""
scripts/download_ddxplus.py

Downloads the DDXPlus differential diagnosis dataset (Mila/McGill, NeurIPS 2022)
from HuggingFace and saves it to data/ddxplus/.

Dataset: 1.3M patient cases, 49 diseases, 223 evidences (symptoms + antecedents)
License: CC-BY 4.0

Run from project root:
    pip install datasets huggingface_hub
    python scripts/download_ddxplus.py
"""

import os
import json
import pandas as pd

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR  = os.path.join(ROOT_DIR, 'data', 'ddxplus')
os.makedirs(OUT_DIR, exist_ok=True)

print("=== DDXPlus Dataset Downloader ===")
print(f"Saving to: {OUT_DIR}\n")

# ── Step 1: Download via HuggingFace datasets library ────────────────────────
try:
    from datasets import load_dataset
except ImportError:
    raise SystemExit("Run: pip install datasets  — then retry.")

print("Downloading DDXPlus from HuggingFace (aai530-group6/ddxplus)...")
print("Total size ~286 MB compressed. This may take a few minutes.\n")

ds = load_dataset("aai530-group6/ddxplus")

print(f"\nSplits available: {list(ds.keys())}")
for split in ds:
    print(f"  {split}: {len(ds[split]):,} rows")

# ── Step 2: Save to CSV ───────────────────────────────────────────────────────
for split in ds:
    out_path = os.path.join(OUT_DIR, f"{split}.csv")
    df = ds[split].to_pandas()
    df.to_csv(out_path, index=False)
    print(f"Saved {split}.csv  ({len(df):,} rows, {os.path.getsize(out_path)/1e6:.1f} MB)")

# ── Step 3: Download metadata files from official Figshare ───────────────────
# These JSON files map coded evidence/condition IDs to human-readable names.
# They are small and essential for interpreting the CSV columns.
import urllib.request

meta_files = {
    "release_evidences.json":   "https://raw.githubusercontent.com/mila-iqia/ddxplus/main/release_evidences.json",
    "release_conditions.json":  "https://raw.githubusercontent.com/mila-iqia/ddxplus/main/release_conditions.json",
}

print("\nDownloading metadata files from GitHub...")
for fname, url in meta_files.items():
    out_path = os.path.join(OUT_DIR, fname)
    try:
        urllib.request.urlretrieve(url, out_path)
        print(f"  Saved {fname}")
    except Exception as e:
        print(f"  WARNING: Could not download {fname}: {e}")
        print(f"  Get it manually from: https://github.com/mila-iqia/ddxplus")

# ── Step 4: Print schema summary ─────────────────────────────────────────────
print("\n=== Schema Summary ===")
train_df = pd.read_csv(os.path.join(OUT_DIR, "train.csv"))
print(f"Columns: {list(train_df.columns)}")
print(f"\nSample row:\n{train_df.iloc[0].to_dict()}")

# Load and summarise conditions
cond_path = os.path.join(OUT_DIR, "release_conditions.json")
if os.path.exists(cond_path):
    with open(cond_path) as f:
        conditions = json.load(f)
    print(f"\nTotal pathologies (diseases): {len(conditions)}")
    print("Diseases:", sorted(conditions.keys())[:10], "...")

evid_path = os.path.join(OUT_DIR, "release_evidences.json")
if os.path.exists(evid_path):
    with open(evid_path) as f:
        evidences = json.load(f)
    print(f"\nTotal evidences (symptoms + antecedents): {len(evidences)}")

print("\n=== Download complete ===")
print(f"Files saved to: {OUT_DIR}")
print("\nNext step: run  python scripts/explore_ddxplus.py  to understand the format")
print("           before integrating into training.")
