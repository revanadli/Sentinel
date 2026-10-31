"""
JKN Sentinel — Dataset Generator untuk ML Testing
Menghasilkan train/test split dari data sintetis yang mengikuti skema BPJS.

Output:
  dataset_train.csv  - 80% data (features + label)
  dataset_test.csv   - 20% data (features + label)
  dataset_features.md - dokumentasi fitur

Jalankan: python generate_dataset.py
"""

import json
import numpy as np
import pandas as pd
from pathlib import Path
from sklearn.model_selection import train_test_split
from sklearn.ensemble import IsolationForest, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.svm import SVC
from sklearn.metrics import (classification_report, roc_auc_score,
                              average_precision_score, confusion_matrix)
from sklearn.preprocessing import StandardScaler

# ── Jalankan ulang sentinel_prototype.py untuk dapat feat matrix ──
# Daripada import ulang, kita rebuild fitur dari hasil CSV yang ada
KARTU = Path("kartu_kasus.csv")
R1    = Path("results.json")
R2    = Path("results2.json")

# ── Cek file ada ──
if not KARTU.exists():
    print("ERROR: kartu_kasus.csv tidak ditemukan. Jalankan sentinel_prototype.py dulu.")
    raise SystemExit(1)

print("=" * 60)
print("  JKN SENTINEL — ML DATASET GENERATOR")
print("=" * 60)

# ── Load data kartu kasus ──
kartu = pd.read_csv(KARTU)
print(f"\nLoaded kartu_kasus.csv: {len(kartu)} baris")
print(f"Kolom: {list(kartu.columns)}")

# ══════════════════════════════════════════════════════════════
# RE-BUILD FEATURE MATRIX DARI SENTINEL_PROTOTYPE
# Kita impor fungsi dari prototype untuk konsistensi
# ══════════════════════════════════════════════════════════════
print("\nMembangun ulang feature matrix dari sentinel_prototype...")

# Re-run generasi data (seed sama persis → reprodusibel)
import sys
import importlib.util

spec = importlib.util.spec_from_file_location("sentinel", "sentinel_prototype.py")

# Tangkap output (supaya tidak berisik)
import io
old_stdout = sys.stdout
sys.stdout = io.StringIO()
try:
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
except SystemExit:
    pass
finally:
    captured = sys.stdout.getvalue()
    sys.stdout = old_stdout

print("Feature matrix berhasil dibangun ulang.")

# Ambil variabel yang dibutuhkan dari modul
feat   = mod.feat       # DataFrame features (N x 7)
fraud  = mod.fraud      # label fraud (0/1)
ftype  = mod.ftype      # tipe fraud P1-P4
decoy  = mod.decoy      # flag decoy
is_kr  = mod.is_kronis  # flag kronis
score  = mod.score      # skor gabungan (rules + anom)
score_m = mod.score_m   # skor setelah fairness

N = len(fraud)
print(f"Peserta: {N:,} | Fraud: {fraud.sum():,} | Decoy: {decoy.sum():,}")

# ══════════════════════════════════════════════════════════════
# BUILD FULL DATASET
# ══════════════════════════════════════════════════════════════
df = feat.copy()
df["label"]      = fraud
df["tipe_fraud"] = ftype
df["is_kronis"]  = is_kr.astype(int)
df["is_decoy"]   = decoy
df["score_raw"]  = score
df["score_fair"] = score_m

# Hapus kolom helper (tidak dipakai sebagai fitur ML)
FEATURE_COLS = [
    "n_faskes_30d",
    "qty_ratio",
    "repeat_svc_60d",
    "dx_norm_z",
    "geo_time_conflict",
    "biaya_gap_mean",
    "use_vs_self",
]
META_COLS = ["label", "tipe_fraud", "is_kronis", "is_decoy", "score_raw", "score_fair"]

print(f"\nFitur ML ({len(FEATURE_COLS)}): {FEATURE_COLS}")

# ══════════════════════════════════════════════════════════════
# TRAIN / TEST SPLIT
# Stratified by label untuk menjaga distribusi fraud yang rendah
# ══════════════════════════════════════════════════════════════
X = df[FEATURE_COLS].values
y = df["label"].values

X_train, X_test, y_train, y_test, idx_train, idx_test = train_test_split(
    X, y, np.arange(N),
    test_size=0.20, random_state=42, stratify=y
)

print(f"\nTrain: {len(X_train):,} baris ({y_train.sum()} fraud, {(y_train==0).sum()} non-fraud)")
print(f"Test:  {len(X_test):,}  baris ({y_test.sum()} fraud, {(y_test==0).sum()} non-fraud)")

# ── Simpan CSV ──
train_df = df.iloc[idx_train].reset_index(drop=True)
test_df  = df.iloc[idx_test].reset_index(drop=True)

train_df.to_csv("dataset_train.csv", index=False, encoding="utf-8-sig")
test_df.to_csv("dataset_test.csv",   index=False, encoding="utf-8-sig")
print(f"\n✓ dataset_train.csv ({len(train_df):,} baris)")
print(f"✓ dataset_test.csv  ({len(test_df):,} baris)")

# ══════════════════════════════════════════════════════════════
# EVALUASI MODEL — PERBANDINGAN 4 CLASSIFIER
# ══════════════════════════════════════════════════════════════
scaler = StandardScaler()
Xtr_s  = scaler.fit_transform(X_train)
Xte_s  = scaler.transform(X_test)

MODELS = {
    "IsolationForest (unsupervised)": None,   # baseline — skor sudah ada
    "Logistic Regression":            LogisticRegression(max_iter=500, class_weight='balanced', random_state=42),
    "Random Forest":                  RandomForestClassifier(n_estimators=200, max_depth=8, class_weight='balanced', random_state=42),
}

eval_results = {}

print("\n" + "=" * 60)
print("  EVALUASI MODEL")
print("=" * 60)

# ── Baseline: skor Isolation Forest dari prototype ──
score_test = score_m[idx_test]
score_norm = (score_test - score_test.min()) / (score_test.max() - score_test.min() + 1e-9)

print("\n[1] IsolationForest (skor dari prototype, threshold=top-K)")
aupr_iso = average_precision_score(y_test, score_norm)
auroc_iso = roc_auc_score(y_test, score_norm)
thresh    = np.percentile(score_norm, 100 * (1 - fraud.sum()/N))
pred_iso  = (score_norm >= thresh).astype(int)
cm_iso    = confusion_matrix(y_test, pred_iso)
print(f"  AUROC: {auroc_iso:.4f} | AUPR: {aupr_iso:.4f}")
print(f"  Confusion Matrix:\n{cm_iso}")
print(classification_report(y_test, pred_iso, target_names=["Non-fraud","Fraud"]))
eval_results["IsolationForest"] = {"auroc": auroc_iso, "aupr": aupr_iso}

# ── Supervised Models ──
for name, clf in list(MODELS.items())[1:]:
    print(f"\n[{list(MODELS.keys()).index(name)+1}] {name}")
    clf.fit(Xtr_s, y_train)
    prob  = clf.predict_proba(Xte_s)[:, 1]
    pred  = clf.predict(Xte_s)
    auroc = roc_auc_score(y_test, prob)
    aupr  = average_precision_score(y_test, prob)
    cm    = confusion_matrix(y_test, pred)
    print(f"  AUROC: {auroc:.4f} | AUPR: {aupr:.4f}")
    print(f"  Confusion Matrix:\n{cm}")
    print(classification_report(y_test, pred, target_names=["Non-fraud","Fraud"]))
    eval_results[name] = {"auroc": auroc, "aupr": aupr}

    # Feature importance untuk Random Forest
    if hasattr(clf, "feature_importances_"):
        print("  Feature importances:")
        for feat_name, imp in sorted(
            zip(FEATURE_COLS, clf.feature_importances_), key=lambda x: -x[1]
        ):
            bar = "█" * int(imp * 40)
            print(f"    {feat_name:<22} {bar} {imp:.4f}")

# ══════════════════════════════════════════════════════════════
# DOKUMENTASI FITUR
# ══════════════════════════════════════════════════════════════
doc = """# Dataset JKN Sentinel — Dokumentasi Fitur

## Skema Data BPJS
Dataset dibuat mengikuti struktur data sampel BPJS Kesehatan (Healthkathon 2026).
Data bersifat **SINTETIS** dan reprodusibel (seed=2026).

## File
| File | Baris | Keterangan |
|------|-------|------------|
| `dataset_train.csv` | ~16.000 | Data pelatihan (80%) |
| `dataset_test.csv`  | ~4.000  | Data pengujian (20%) |

## Fitur ML (kolom input)
| Kolom | Variabel BPJS | Keterangan |
|-------|--------------|------------|
| `n_faskes_30d` | FKL08, FKL03 | Jumlah faskes FKRTL unik dalam 30 hari |
| `qty_ratio` | FKL46_QTY | Max qty obat / 30 (kebutuhan normal sebulan) |
| `repeat_svc_60d` | FKP11, FKP03 | Kunjungan poli sama berulang dalam 60 hari |
| `dx_norm_z` | All visits | Z-score kunjungan vs kelompok kronis×usia |
| `geo_time_conflict` | FKL05, FKL03 | Kunjungan di 2 provinsi berbeda dalam 1 hari |
| `biaya_gap_mean` | FKL47, FKL48 | Rata-rata |biaya tagih − biaya verifikasi| |
| `use_vs_self` | FKL46_QTY | Max qty / rata-rata qty peserta sendiri |

## Kolom Output & Metadata
| Kolom | Keterangan |
|-------|------------|
| `label` | 1=Fraud, 0=Non-fraud (ground truth sintetis) |
| `tipe_fraud` | P1/P2/P3/P4 atau '' untuk non-fraud |
| `is_kronis` | 1 jika peserta memiliki kondisi kronis |
| `is_decoy` | 1 jika peserta adalah decoy (perilaku mirip fraud tapi sah) |
| `score_raw` | Skor gabungan rules + IsolationForest (sebelum fairness) |
| `score_fair` | Skor setelah normalisasi per kelompok kronis×usia |

## Pola Fraud (Ground Truth)
| Tipe | N | Deskripsi |
|------|---|-----------|
| P1 | 200 | Drug shopping: obat kode sama di banyak provinsi dalam 25 hari |
| P2 | 100 | Qty berlebihan: klaim 90-120 tablet (normal 30/bulan) |
| P3 | 160 | Duplikasi layanan: poli sama di banyak faskes dalam 60 hari |
| P4 | 80  | Identity fraud: kunjungan di 2 provinsi jauh di hari sama |

## Distribusi Dataset
- Total: 20.000 peserta
- Fraud: 540 (2.7%)
- Decoy: 600 (3.0%) — peserta sah dengan perilaku mirip fraud

## Catatan Produksi
- Prevalensi fraud nyata kemungkinan < 2.7% → kalibrasi threshold diperlukan
- Model supervised hanya valid jika ada label ground truth (butuh pilot nyata)
- IsolationForest cocok untuk deployment awal tanpa label
"""

with open("dataset_features.md", "w", encoding="utf-8") as f:
    f.write(doc)

# ── Summary JSON ──
summary = {
    "dataset": {
        "total": N,
        "fraud": int(fraud.sum()),
        "decoy": int(decoy.sum()),
        "prevalensi_pct": round(fraud.sum() / N * 100, 2),
        "train_size": len(X_train),
        "test_size":  len(X_test),
        "features":   FEATURE_COLS,
    },
    "model_eval": eval_results,
}
with open("dataset_eval.json", "w", encoding="utf-8") as f:
    json.dump(summary, f, indent=2, ensure_ascii=False)

print("\n" + "=" * 60)
print("  SELESAI")
print("=" * 60)
print("Output:")
print("  dataset_train.csv   — training data")
print("  dataset_test.csv    — test data")
print("  dataset_features.md — dokumentasi fitur")
print("  dataset_eval.json   — ringkasan evaluasi model")
