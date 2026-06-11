"""
scripts/download_doctors_india.py

Downloads updated Indian hospital/health facility data from public sources
to replace the outdated doctors_database.json.

Sources used:
  1. data.gov.in — Health Infrastructure dataset (official government open data)
  2. Kaggle "Indian Medical Facility Dataset" — hospital-level data (CC0 public domain)
  3. Health Facility Registry (ABDM) — government facility data

NOTE on individual doctor records:
  NMC (National Medical Commission) does NOT provide bulk download of individual
  doctor records. Only individual lookups are available at nmc.org.in/imr/.
  This script fetches facility/hospital data, which is what your doctor_search.py
  actually uses (it searches hospitals, not individual doctors).

Run from project root:
    pip install kaggle requests
    python scripts/download_doctors_india.py
"""

import os
import json
import requests
import pandas as pd

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR  = os.path.join(ROOT_DIR, 'data', 'doctors_updated')
os.makedirs(OUT_DIR, exist_ok=True)

print("=== Indian Health Facility Data Downloader ===\n")

# ── Option 1: data.gov.in Health Infrastructure (open API, no key needed) ────
# The National Health Profile dataset is published openly.
print("--- Option 1: data.gov.in National Health Profile ---")
print("Visit: https://data.gov.in/catalog/health-infrastructure")
print("Download: 'Health Infrastructure in States/UTs' CSV")
print("Direct API: https://api.data.gov.in/resource/<resource-id>?api-key=579b...&format=csv")
print("Note: Requires free API key from data.gov.in (register at data.gov.in/user/register)")
print()

# ── Option 2: Kaggle Indian Medical Facility Dataset (CC0) ───────────────────
print("--- Option 2: Kaggle — Indian Medical Facility Dataset ---")
print("Dataset: https://www.kaggle.com/datasets/chekoduadarsh/indian-medical-facility-dataset")
print("License: CC0 Public Domain")
print()
print("To download via Kaggle API:")
print("  1. Install Kaggle CLI:  pip install kaggle")
print("  2. Get your API token: kaggle.com → Account → Create New API Token → saves kaggle.json")
print("  3. Place kaggle.json at ~/.kaggle/kaggle.json")
print("  4. Run:")
print("       kaggle datasets download -d chekoduadarsh/indian-medical-facility-dataset -p data/doctors_updated --unzip")
print()

# Try Kaggle download automatically if credentials exist
kaggle_json = os.path.expanduser("~/.kaggle/kaggle.json")
if os.path.exists(kaggle_json):
    print("Kaggle credentials found — attempting download...")
    ret = os.system(
        f"kaggle datasets download -d chekoduadarsh/indian-medical-facility-dataset "
        f"-p {OUT_DIR} --unzip"
    )
    if ret == 0:
        print("Downloaded successfully.")
    else:
        print("Kaggle download failed — download manually using the URL above.")
else:
    print("No Kaggle credentials found. Follow the steps above to download manually.")

print()

# ── Option 3: ABDM Health Facility Registry (government, open) ───────────────
print("--- Option 3: ABDM Health Facility Registry ---")
print("Portal: https://facility.abdm.gov.in")
print("This is the official Ayushman Bharat Digital Mission facility registry.")
print("Individual facility lookup: https://facility.abdm.gov.in/nhrr")
print("No bulk download API is publicly available.")
print()

# ── Step: Merge with existing doctors_database.json ──────────────────────────
print("=== Checking existing doctors_database.json ===")
existing = os.path.join(ROOT_DIR, 'data', 'doctors_database.json')
if os.path.exists(existing):
    with open(existing) as f:
        data = json.load(f)
    if isinstance(data, list):
        df_existing = pd.DataFrame(data)
    elif isinstance(data, dict):
        # Try common keys
        key = next((k for k in ['doctors', 'hospitals', 'data', 'records'] if k in data), None)
        df_existing = pd.DataFrame(data[key]) if key else pd.DataFrame([data])
    print(f"Existing database: {len(df_existing):,} records")
    print(f"Columns: {list(df_existing.columns)}")
    sample_path = os.path.join(OUT_DIR, "existing_sample.csv")
    df_existing.head(20).to_csv(sample_path, index=False)
    print(f"Saved sample of existing data to: {sample_path}")
    print()
    print("RECOMMENDATION:")
    print("  Your existing doctors_database.json has 45k+ records which is more than")
    print("  what's publicly available in bulk. The main issue is it may be ~1 year old.")
    print("  Focus on enriching it rather than replacing it:")
    print("    - Add ABDM facility IDs (for credibility in paper)")
    print("    - Add state/district normalization")
    print("    - Cross-reference with Kaggle facility dataset for validation")
else:
    print("doctors_database.json not found at expected path.")

print("\n=== Summary ===")
print("For your research paper, your 45k hospital records is actually a contribution.")
print("Cite it as a 'curated Indian healthcare facility dataset' and document its")
print("collection methodology. That's publishable as part of your paper's data section.")
