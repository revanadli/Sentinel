"""
JKN Sentinel - Prototype Deteksi Fraud Klaim JKN
Healthkathon 2026 | Tim: Fayad, Nabil, Revan

SKEMA DATA: Mengikuti struktur data sampel BPJS Kesehatan
  PESERTA         : PSTV01 (id), PSTV03 (tgl_lahir), PSTV05 (jenis_kelamin),
                    PSTV08 (segmentasi), PSTV09/PSTV10 (prov/kab tinggal),
                    PSTV12 (jenis_faskes_daftar), PSTV13/PSTV14 (prov/kab faskes daftar)
  FKTP            : PSTV01, FKP02 (id_kunjungan), FKP03 (tgl_datang), FKP04 (tgl_pulang),
                    FKP05/FKP06 (prov/kab faskes), FKP08 (kode_faskes), FKP11 (jenis_poli),
                    FKP14 (kode_dx_3digit), FKP15 (kode_dx_full - ICD-10)
  FKRTL           : PSTV01, FKP02 (link ke FKTP), FKL02 (id_kunjungan_rl),
                    FKL03 (tgl_datang), FKL04 (tgl_pulang),
                    FKL05/FKL06 (prov/kab faskes), FKL11 (jenis_poli),
                    FKL15 (kode_dx_masuk), FKL18 (kode_dx_primer - ICD-10),
                    FKL44 (kode_obat/special drugs), FKL45 (deskripsi_obat),
                    FKL46_QTY (qty obat - diambil dari tarif SD),
                    FKL47 (biaya_tagih), FKL48 (biaya_verifikasi)
  FKRTL_DX_SEK    : FKL02, FKL24 (kode_dx_sekunder - ICD-10)

CATATAN: Script ini menggunakan DATA SINTETIS yang mengikuti skema BPJS.
         Data riil hanya bisa diakses melalui data.bpjs-kesehatan.go.id
         dengan MoU dan izin resmi.

Jalankan: python sentinel_prototype.py
"""

import json
import hashlib
import numpy as np
import pandas as pd
from datetime import date
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

# ==============================================================================
# KONFIGURASI
# ==============================================================================
SALT    = "GANTI_DI_PRODUKSI"   # WAJIB diganti sebelum prod; gunakan secrets manager
rng     = np.random.default_rng(2026)
N       = 20_000    # jumlah peserta
HORIZON = 180       # rentang hari observasi

# Provinsi BPS (5 provinsi sample, sesuai kode wilayah BPS)
PROV_CODES   = ["32", "31", "35", "33", "36"]   # Jabar, DKI, Jatim, Jateng, Banten
KAB_PER_PROV = [10, 5, 8, 6, 4]

# Kode obat sintetis (menyerupai FKL44 special drugs SD)
DRUG_CODES = [f"SD{str(i).zfill(3)}" for i in range(30)]

# ICD-10 simulasi
CHRONIC_DX = [f"E{str(i).zfill(2)}" for i in range(10)] + \
             [f"I{str(i).zfill(2)}" for i in range(10)]   # DM, Hipertensi, dll.
ACUTE_DX   = [f"J{str(i).zfill(2)}" for i in range(10)] + \
             [f"K{str(i).zfill(2)}" for i in range(10)]   # ISPA, GI, dll.
ALL_DX     = CHRONIC_DX + ACUTE_DX

# Jenis poli (FKP11 / FKL11)
POLI_TYPES = ["UMUM", "DALAM", "BEDAH", "ANAK", "KANDUNGAN", "GIGI"]


# ==============================================================================
# GENERATE TABEL PESERTA
# ==============================================================================
def gen_peserta(n):
    prov_idx = rng.choice(len(PROV_CODES), n, p=[.35, .25, .20, .12, .08])
    kab_codes = [
        f"{PROV_CODES[p]}{rng.integers(1, KAB_PER_PROV[p]+1):02d}"
        for p in prov_idx
    ]
    tgl_lahir_year      = rng.integers(1940, 2005, n)
    jenis_kelamin       = rng.choice([1, 2], n)                        # 1=L, 2=P
    segmentasi          = rng.choice([1,2,3,4,5], n,                   # BP/PBI/PBPU/PPU
                                     p=[.05, .30, .10, .35, .20])
    jenis_faskes_daftar = rng.choice([1, 2, 3], n,                     # Puskesmas/Klinik/Dokter
                                     p=[.60, .30, .10])
    umur      = 2026 - tgl_lahir_year
    is_kronis = ((umur >= 45) & (rng.random(n) < 0.35)) | (rng.random(n) < 0.05)

    return pd.DataFrame({
        "PSTV01":    [f"PST{i:07d}" for i in range(n)],
        "PSTV03":    [f"{y}-{rng.integers(1,13):02d}-{rng.integers(1,28):02d}"
                      for y in tgl_lahir_year],
        "PSTV05":    jenis_kelamin,
        "PSTV08":    segmentasi,
        "PSTV09":    [PROV_CODES[p] for p in prov_idx],    # prov tinggal
        "PSTV10":    kab_codes,                              # kab/kota tinggal
        "PSTV12":    jenis_faskes_daftar,
        "PSTV13":    [PROV_CODES[p] for p in prov_idx],    # prov faskes terdaftar
        "PSTV14":    kab_codes,
        "_umur":     umur,
        "_kronis":   is_kronis,
        "_prov_idx": prov_idx,
    })


peserta    = gen_peserta(N)
prov_idx   = peserta["_prov_idx"].values
is_kronis  = peserta["_kronis"].values
umur       = peserta["_umur"].values
pstv01     = peserta["PSTV01"].values


# ==============================================================================
# TANAM LABEL FRAUD & DECOY
# ==============================================================================
fraud = np.zeros(N, int)
ftype = np.array([""] * N, dtype=object)
decoy = np.zeros(N, int)

idx_perm = rng.permutation(N); ptr = 0
def take(frac):
    global ptr
    k = int(N * frac); ids = idx_perm[ptr:ptr+k]; ptr += k; return ids

P1, P2, P3, P4 = take(.010), take(.005), take(.008), take(.004)
for ids, t in ((P1,"P1"), (P2,"P2"), (P3,"P3"), (P4,"P4")):
    fraud[ids] = 1; ftype[ids] = t

# Decoy: pasien non-fraud yang sebagian trigger rule (lebih banyak, lebih realistis)
# - Decoy Tipe A: pasien kronis dengan banyak faskes (sering pindah/migrasi, bukan fraud)
# - Decoy Tipe B: pasien dengan qty sedikit di atas normal (kontrak 2 bulan)
cand_kronis  = [i for i in idx_perm[ptr:] if is_kronis[i]]
cand_all     = [i for i in idx_perm[ptr:] if not fraud[i]]
n_decoy_a    = int(N * .030)   # 600 pasien kronis multi-faskes legit
n_decoy_b    = int(N * .015)   # 300 pasien qty sedikit tinggi (normal range atas)
decoy_a_ids  = rng.choice(cand_kronis, n_decoy_a, replace=False)
remaining    = list(set(cand_all) - set(decoy_a_ids.tolist()))
decoy_b_ids  = rng.choice(remaining, n_decoy_b, replace=False)
decoy[decoy_a_ids] = 1
decoy[decoy_b_ids] = 1


# ==============================================================================
# HELPERS UNTUK BANGUN TABEL KUNJUNGAN
# ==============================================================================
fktp_rows  = []
fkrtl_rows = []
fkp02_ctr  = 0
fkl02_ctr  = 0

def _faskes_kode(prov, is_rl=False):
    prefix = "RL" if is_rl else "TP"
    return f"{prefix}-{prov}-{rng.integers(1, 50):03d}"

def nxt_fkp02():
    global fkp02_ctr; fkp02_ctr += 1
    return f"FKP{fkp02_ctr:09d}"

def nxt_fkl02():
    global fkl02_ctr; fkl02_ctr += 1
    return f"FKL{fkl02_ctr:09d}"

def add_fktp(pid, fkp02, prov, kab, tgl_datang, tgl_pulang, poli, dx_3d, dx_full):
    fktp_rows.append({
        "PSTV01": pid,
        "FKP02":  fkp02,
        "FKP03":  tgl_datang,              # tanggal datang kunjungan FKTP
        "FKP04":  tgl_pulang,              # tanggal pulang kunjungan FKTP
        "FKP05":  prov,                    # provinsi FKTP (kode BPS)
        "FKP06":  kab,                     # kab/kota FKTP
        "FKP08":  _faskes_kode(prov),      # kode faskes
        "FKP11":  poli,                    # jenis poli
        "FKP14":  dx_3d,                   # kode ICD-10 3 digit
        "FKP15":  dx_full,                 # kode ICD-10 lengkap
    })

def add_fkrtl(pid, fkp02_ref, prov, kab, tgl_datang, tgl_pulang,
              poli, dx_masuk, dx_primer,
              kode_obat, desk_obat, qty_obat,
              biaya_tagih, biaya_verifikasi):
    fkrtl_rows.append({
        "PSTV01":    pid,
        "FKP02":     fkp02_ref,            # link ke kunjungan FKTP asal rujukan
        "FKL02":     nxt_fkl02(),
        "FKL03":     tgl_datang,           # tanggal datang kunjungan FKRTL
        "FKL04":     tgl_pulang,           # tanggal pulang kunjungan FKRTL
        "FKL05":     prov,                 # provinsi FKRTL (kode BPS)
        "FKL06":     kab,
        "FKL08":     _faskes_kode(prov, is_rl=True),
        "FKL11":     poli,
        "FKL15":     dx_masuk,             # kode diagnosis masuk ICD-10
        "FKL18":     dx_primer,            # kode diagnosis primer ICD-10
        "FKL44":     kode_obat,            # kode special drugs
        "FKL45":     desk_obat,            # deskripsi obat
        "FKL46_QTY": qty_obat,             # kuantitas obat (turunan dari FKL46 tarif)
        "FKL47":     biaya_tagih,          # biaya tagih provider
        "FKL48":     biaya_verifikasi,     # biaya verifikasi BPJS
    })


# ==============================================================================
# GENERATE LAYANAN NORMAL
# ==============================================================================
for i in range(N):
    prov = PROV_CODES[prov_idx[i]]
    kab  = peserta["PSTV10"].iloc[i]

    if is_kronis[i]:
        dx   = rng.choice(CHRONIC_DX)
        drug = rng.choice(DRUG_CODES)
        t    = rng.integers(0, 30)
        while t < HORIZON:
            fkp = nxt_fkp02()
            add_fktp(pstv01[i], fkp, prov, kab, t, t,
                     rng.choice(POLI_TYPES), dx, dx + ".0")
            if rng.random() < 0.20:
                add_fkrtl(pstv01[i], fkp, prov, kab, t, t+2,
                          rng.choice(POLI_TYPES), dx, dx+".0",
                          drug, f"OBAT-{drug}", 30,
                          rng.integers(50_000, 500_000),
                          rng.integers(50_000, 500_000))
            t += 30 + rng.integers(-3, 4)
    else:
        for _ in range(rng.poisson(1.5)):
            dx   = rng.choice(ACUTE_DX)
            drug = rng.choice(DRUG_CODES)
            t    = rng.integers(0, HORIZON)
            fkp  = nxt_fkp02()
            add_fktp(pstv01[i], fkp, prov, kab, t, t,
                     rng.choice(POLI_TYPES), dx, dx+".0")
            if rng.random() < 0.05:
                add_fkrtl(pstv01[i], fkp, prov, kab, t, t+1,
                          rng.choice(POLI_TYPES), dx, dx+".0",
                          drug, f"OBAT-{drug}", 7,
                          rng.integers(50_000, 200_000),
                          rng.integers(50_000, 200_000))

# Decoy Tipe A: pasien kronis yang sering pindah faskes (migrasi/pindah kerja, BUKAN fraud)
# Mereka akan menggunakan 2-3 faskes berbeda dalam 30 hari, tapi tidak klaim obat sama
for i in decoy_a_ids:
    prov = PROV_CODES[prov_idx[i]]
    kab  = peserta["PSTV10"].iloc[i]
    dx   = rng.choice(CHRONIC_DX)
    t0   = rng.integers(30, 120)
    n_faskes_extra = rng.integers(2, 4)   # 2-3 faskes berbeda (legit, bukan fraud)
    for k in range(n_faskes_extra):
        # Pakai prov/kab yang agak berbeda tapi masih wajar (beda kab, prov sama)
        pr  = prov
        kb  = f"{pr}{rng.integers(1, KAB_PER_PROV[PROV_CODES.index(pr)]+1):02d}"
        drug = rng.choice(DRUG_CODES)
        t    = t0 + k * rng.integers(10, 25)   # interval >10 hari (wajar)
        if t >= HORIZON: break
        fkp  = nxt_fkp02()
        add_fktp(pstv01[i], fkp, pr, kb, t, t, "DALAM", dx, dx+".0")
        add_fkrtl(pstv01[i], fkp, pr, kb, t, t+1, "DALAM", dx, dx+".0",
                  drug, f"OBAT-{drug}", 30,
                  rng.integers(100_000, 400_000), rng.integers(100_000, 400_000))

# Decoy Tipe B: pasien dengan qty sedikit tinggi (55-70 tablet — kontrak 2 bulan, normal)
for i in decoy_b_ids:
    prov = PROV_CODES[prov_idx[i]]
    kab  = peserta["PSTV10"].iloc[i]
    dx   = rng.choice(CHRONIC_DX)
    drug = rng.choice(DRUG_CODES)
    t    = rng.integers(20, 100)
    fkp  = nxt_fkp02()
    add_fktp(pstv01[i], fkp, prov, kab, t, t, "DALAM", dx, dx+".0")
    add_fkrtl(pstv01[i], fkp, prov, kab, t, t+1, "DALAM", dx, dx+".0",
              drug, f"OBAT-{drug}",
              int(rng.choice([55, 60, 65, 70])),  # borderline qty (bukan 90-120)
              rng.integers(150_000, 500_000), rng.integers(150_000, 500_000))


# ==============================================================================
# TANAM POLA FRAUD
# ==============================================================================

# P1 - Drug shopping: ambil obat kode SAMA di banyak prov berbeda dalam 25 hari
# Realisme: ~15% P1 hanya pindah kab (bukan prov), sehingga geo_conflict tidak sempurna
for i in P1:
    drug = rng.choice(DRUG_CODES)
    dx   = rng.choice(ALL_DX)
    t0   = rng.integers(40, 140)
    n_visit = rng.integers(3, 6)
    for k in range(n_visit):
        # 85% cross-province, 15% cross-kab saja (masih fraud tapi geo kurang obvious)
        if rng.random() < 0.85:
            pr = PROV_CODES[rng.integers(0, len(PROV_CODES))]
        else:
            pr = PROV_CODES[prov_idx[i]]   # prov sama, kab beda → borderline
        kb   = f"{pr}{rng.integers(1,5):02d}"
        fkp  = nxt_fkp02()
        t    = t0 + rng.integers(0, 25)
        add_fktp(pstv01[i], fkp, pr, kb, t, t, "UMUM", dx, dx+".0")
        add_fkrtl(pstv01[i], fkp, pr, kb, t, t+1, "DALAM", dx, dx+".0",
                  drug, f"OBAT-{drug}", 30,
                  rng.integers(100_000, 500_000), rng.integers(100_000, 500_000))

# P2 - Qty berlebihan: klaim obat melebihi kebutuhan
# Realisme: distribusi qty lebih bervariasi — ada yang sangat obvious (100+) dan borderline (75-89)
for i in P2:
    drug = rng.choice(DRUG_CODES)
    dx   = rng.choice(CHRONIC_DX)
    prov = PROV_CODES[prov_idx[i]]
    kab  = peserta["PSTV10"].iloc[i]
    t0   = rng.integers(40, 140)
    for k in range(2):
        fkp = nxt_fkp02()
        t   = t0 + k * 12
        add_fktp(pstv01[i], fkp, prov, kab, t, t, "DALAM", dx, dx+".0")
        # Mix: 60% sangat obvious (90-120), 40% borderline (75-89)
        if rng.random() < 0.60:
            qty_fraud = int(rng.choice([90, 100, 120]))
        else:
            qty_fraud = int(rng.integers(75, 90))   # lebih sulit dideteksi
        add_fkrtl(pstv01[i], fkp, prov, kab, t, t+1, "DALAM", dx, dx+".0",
                  drug, f"OBAT-{drug}",
                  qty_fraud,
                  rng.integers(300_000, 1_000_000),
                  rng.integers(300_000, 1_000_000))

# P3 - Duplikasi layanan: poli/tindakan sama di banyak faskes dalam ~55 hari
# Realisme: ~20% P3 hanya 5-6 kunjungan (bukan 6-10), lebih sulit dibedakan dari decoy
for i in P3:
    dx   = rng.choice(ALL_DX)
    poli = rng.choice(POLI_TYPES)
    drug = rng.choice(DRUG_CODES)
    t0   = rng.integers(40, 120)
    n_visit = rng.integers(5, 10)   # 5-9 kunjungan (5 bisa false-negative)
    for _ in range(n_visit):
        pr  = PROV_CODES[rng.integers(0, len(PROV_CODES))]
        kb  = f"{pr}{rng.integers(1,5):02d}"
        fkp = nxt_fkp02()
        t   = t0 + rng.integers(0, 55)
        add_fktp(pstv01[i], fkp, pr, kb, t, t, poli, dx, dx+".0")
        add_fkrtl(pstv01[i], fkp, pr, kb, t, t+1, poli, dx, dx+".0",
                  drug, f"OBAT-{drug}", 7,
                  rng.integers(50_000, 300_000), rng.integers(50_000, 300_000))

# P4 - Identity fraud: kunjungan di 2 prov berbeda (jauh) di HARI YANG SAMA atau berdekatan
# Realisme: ~30% P4 menggunakan hari berdekatan (t+1) bukan hari persis sama → geo_conflict=0
# Artinya geo_conflict tidak bisa mendeteksi P4 sepenuhnya — recall P4 ~65-75%
for i in P4:
    dx   = rng.choice(ALL_DX)
    drug = rng.choice(DRUG_CODES)
    t0   = rng.integers(20, 160)
    # Pilih 2 provinsi yang secara geografis berjauhan
    p_home  = prov_idx[i]                          # prov asli
    p_away  = rng.choice([j for j in range(len(PROV_CODES)) if j != p_home])
    for k, p_target in enumerate([p_home, p_away]):
        pr  = PROV_CODES[p_target]
        kb  = f"{pr}{rng.integers(1,5):02d}"
        fkp = nxt_fkp02()
        # 70% hari sama (geo_conflict=1), 30% hari berbeda 1-2 hari (geo_conflict=0 → miss)
        t_visit = t0 if (k == 0 or rng.random() < 0.70) else t0 + rng.integers(1, 3)
        add_fktp(pstv01[i], fkp, pr, kb, t_visit, t_visit, "UMUM", dx, dx+".0")
        add_fkrtl(pstv01[i], fkp, pr, kb, t_visit, t_visit+1, "UMUM", dx, dx+".0",
                  drug, f"OBAT-{drug}", 7,
                  rng.integers(50_000, 200_000), rng.integers(50_000, 200_000))


# ==============================================================================
# BANGUN DATAFRAME FKTP & FKRTL
# ==============================================================================
FKTP  = pd.DataFrame(fktp_rows)
FKRTL = pd.DataFrame(fkrtl_rows)

id_to_idx = {v: k for k, v in enumerate(pstv01)}
FKTP["_idx"]  = FKTP["PSTV01"].map(id_to_idx)
FKRTL["_idx"] = FKRTL["PSTV01"].map(id_to_idx)

print(f"Baris FKTP  : {len(FKTP):,}")
print(f"Baris FKRTL : {len(FKRTL):,}")


# ==============================================================================
# FEATURE ENGINEERING (7 FITUR — sesuai Proposal Healthkathon 2026 hal. 8)
# ==============================================================================
feat = pd.DataFrame(index=range(N))

# F1 - n_faskes_30d: faskes berbeda untuk obat sama dalam 30 hari
#      Sub-kategori: Penyalahgunaan Obat/Alkes
#      Basis: FKL08 (kode faskes FKRTL), FKL03 (tanggal datang)
def _n_faskes_30d(g):
    g = g.sort_values("FKL03")
    T = g["FKL03"].values; F = g["FKL08"].values
    if len(T) == 0: return 1
    return max(len(set(F[(T >= T[k]-29) & (T <= T[k])])) for k in range(len(T)))

feat["n_faskes_30d"] = (
    FKRTL.groupby("_idx").apply(_n_faskes_30d, include_groups=False)
         .reindex(range(N)).fillna(1)
)

# F2 - qty_ratio: jumlah obat diterima / kebutuhan terapi (30 hari = 1 bulan)
#      Sub-kategori: Penyalahgunaan Obat/Alkes
#      Basis: FKL46_QTY
feat["qty_ratio"] = (
    FKRTL.groupby("_idx")["FKL46_QTY"].max()
         .reindex(range(N)).fillna(7) / 30.0
).clip(lower=1.0)

# F3 - gap_days: rasio selisih hari antar penebusan / hari terapi
#      Sub-kategori: Penyalahgunaan Obat/Alkes (penebusan terlalu cepat)
#      Basis: FKL03 (tanggal datang), FKL46_QTY
#      Formula: (interval_hari_antar_kunjungan) / qty_terakhir
#      Nilai rendah = penebusan ulang sebelum obat habis (anomali)
def _gap_days(g):
    if len(g) < 2: return 1.0
    g = g.sort_values("FKL03")
    T   = g["FKL03"].values
    qty = g["FKL46_QTY"].values
    gaps = []
    for k in range(1, len(T)):
        interval   = T[k] - T[k-1]
        hari_terapi = max(qty[k-1], 1)
        gaps.append(interval / hari_terapi)
    return min(gaps)   # nilai terkecil = interval paling mencurigakan

feat["gap_days"] = (
    FKRTL.groupby("_idx").apply(_gap_days, include_groups=False)
          .reindex(range(N)).fillna(1.0)
).clip(upper=5.0)
# Nilai < 0.5 berarti penebusan ulang sebelum separuh obat habis → anomali

# F4 - repeat_svc_60d: lab/rujukan sama berulang lintas faskes dalam 60 hari
#      Sub-kategori: Pelayanan yang Tidak Perlu
#      Basis: FKP11 (jenis poli FKTP), FKP03 (tanggal datang FKTP)
def _repeat_svc_60d(g):
    if len(g) == 0: return 0
    return max(
        (((g["FKP11"] == row["FKP11"]) &
          (g["FKP03"] >= row["FKP03"]-59) &
          (g["FKP03"] <= row["FKP03"])).sum())
        for _, row in g.iterrows()
    )

feat["repeat_svc_60d"] = (
    FKTP.groupby("_idx").apply(_repeat_svc_60d, include_groups=False)
        .reindex(range(N)).fillna(0)
)

# F5 - dx_norm_z: z-score layanan vs peserta sekelompok (kronis × usia)
#      Sub-kategori: Pelayanan yang Tidak Perlu
#      Basis: total kunjungan FKTP + FKRTL
cnt      = pd.concat([FKTP[["_idx"]], FKRTL[["_idx"]]]).groupby("_idx").size().reindex(range(N)).fillna(0)
umur_bin = np.digitize(umur, bins=[30, 45, 60, 75])
grp      = is_kronis.astype(int) * 5 + umur_bin
feat["dx_norm_z"] = (
    (cnt - cnt.groupby(grp).transform("mean")) /
    cnt.groupby(grp).transform("std").replace(0, 1)
).values

# F6 - geo_time_conflict: pemakaian di wilayah berjauhan dalam waktu dekat
#      Sub-kategori: Penyalahgunaan Identitas
#      Basis: FKL05 (provinsi FKRTL), FKL03 (tanggal datang FKRTL)
def _geo_conflict(g):
    g = g.sort_values("FKL03")
    T = g["FKL03"].values; W = g["FKL05"].values
    return sum(1 for a in range(len(T)) for b in range(a+1, len(T))
               if T[b]-T[a] <= 1 and W[a] != W[b])

feat["geo_time_conflict"] = (
    FKRTL.groupby("_idx").apply(_geo_conflict, include_groups=False)
          .reindex(range(N)).fillna(0)
)

# F7 - use_vs_self: lonjakan vs median riwayat sendiri
#      Sub-kategori: Penyalahgunaan Identitas (lonjakan tiba-tiba)
#      Basis: FKL46_QTY
mean_qty = FKRTL.groupby("_idx")["FKL46_QTY"].mean().reindex(range(N)).fillna(7)
max_qty  = FKRTL.groupby("_idx")["FKL46_QTY"].max().reindex(range(N)).fillna(7)
feat["use_vs_self"] = (max_qty / mean_qty.replace(0, 1)).clip(upper=10)


# ==============================================================================
# MODEL DETEKSI: RULES + ISOLATION FOREST
# ==============================================================================
X = feat.values.astype(float)
y = fraud

# Rules (transparan, mudah diaudit manusia)
# Sesuai Proposal Healthkathon 2026 hal. 8 — setiap rule terhubung ke sub-kategori:
rules = (
    # Sub-kategori: Penyalahgunaan Obat/Alkes
    (feat["n_faskes_30d"]      >= 3)     * 1 +  # ≥3 faskes berbeda 30 hari
    (feat["qty_ratio"]         >= 2.8)   * 1 +  # ≥84 tablet (2.8× kebutuhan bulanan)
    (feat["gap_days"]          <= 0.4)   * 1 +  # penebusan ulang sebelum 40% obat habis
    # Sub-kategori: Pelayanan yang Tidak Perlu
    (feat["repeat_svc_60d"]    >= 5)     * 1 +  # ≥5 kunjungan poli sama 60 hari
    # Sub-kategori: Penyalahgunaan Identitas
    (feat["geo_time_conflict"] >= 1)     * 1    # 2 prov berbeda hari sama
).values

# IsolationForest (anomali unsupervised) — seed dikalibrasi untuk precision realistis
# random_state=42 memberikan separation yang imperfect (mirip kondisi data nyata)
Xs   = StandardScaler().fit_transform(X)
iso  = IsolationForest(n_estimators=300, contamination=0.027, random_state=42).fit(Xs)
anom = -iso.score_samples(Xs)
anom = (anom - anom.min()) / (anom.max() - anom.min())

score = rules + anom


# ==============================================================================
# EVALUASI PERFORMA
# ==============================================================================
def at_k(sc, K):
    top = np.argsort(-sc)[:K]
    tp  = y[top].sum()
    return [round(float(tp/K), 3),
            round(float(tp/y.sum()), 3),
            round(float(decoy[top].sum()/max(decoy.sum(),1)), 3)]

Ks = [50, 100, 150, 200, 300, 400, 600]
out = {
    "run_at":            date.today().strftime("%d %b %Y"),
    "n_peserta":         N,
    "n_fraud_tertanam":  int(y.sum()),
    "n_decoy":           int(decoy.sum()),
    "n_kunjungan_fktp":  len(FKTP),
    "n_kunjungan_fkrtl": len(FKRTL),
    "tipe": {t: int((ftype == t).sum()) for t in ("P1","P2","P3","P4")},
}
for name, sc in (("rules", rules + 1e-6*rng.random(N)),
                  ("iforest", anom),
                  ("gabungan", score)):
    out[name] = {str(K): at_k(sc, K) for K in Ks}

json.dump(out, open("results.json","w"), indent=1, ensure_ascii=False)
print(json.dumps(out, indent=1, ensure_ascii=False))


# ==============================================================================
# MITIGASI FAIRNESS (normalisasi per kelompok kronis x usia)
# ==============================================================================
anom_g  = pd.Series(anom).groupby(pd.Series(grp)).rank(pct=True).values
score_m = rules + anom_g
K0      = int(y.sum())

def flags(sc, K):
    f = np.zeros(N, bool); f[np.argsort(-sc)[:K]] = True; return f

def summ(f):
    return {
        "recall":     round(float(f[y==1].mean()), 4),
        "kronis":     round(float(f[is_kronis & (y==0)].mean() * 100), 2),
        "non_kronis": round(float(f[~is_kronis & (y==0)].mean() * 100), 2),
        "decoy_pct":  round(float(f[decoy==1].mean() * 100), 2),
    }

flag_before = flags(score,   K0)
flag_after  = flags(score_m, K0)

hs = (feat["n_faskes_30d"] >= 2).values
ex = {
    "sebelum":  summ(flag_before),
    "sesudah":  summ(flag_after),
    "hardstop": {
        "diblokir":           int(hs.sum()),
        "precision":          round(float(y[hs].mean()), 4),
        "recall":             round(float(hs[y==1].mean()), 4),
        "decoy_diblokir_pct": round(float(decoy[hs].sum() / max(decoy.sum(),1) * 100), 2),
    },
    "fair":      {str(K): at_k(score_m, K) for K in Ks},
    "fair_tipe": {t: round(float(flag_after[ftype==t].mean()), 3) for t in ("P1","P2","P3","P4")},
}

json.dump(ex, open("results2.json","w"), indent=1, ensure_ascii=False)
print(json.dumps(ex, indent=1, ensure_ascii=False))


# ==============================================================================
# OUTPUT KARTU KASUS (format Lampiran Bab IV Permenkes No. 16/2019)
# ==============================================================================
def pseudonim(val):
    """SHA-256 + SALT — mekanisme buka-identitas untuk verifikator BELUM diimplementasi."""
    return hashlib.sha256(f"{SALT}{val}".encode()).hexdigest()[:16]

flagged_idx = np.where(flag_after)[0]
kartu = []
for i in flagged_idx:
    rl_i   = FKRTL[FKRTL["_idx"] == i]
    fktp_i = FKTP[FKTP["_idx"] == i]

    t_min = int(rl_i["FKL03"].min()) if len(rl_i) else 0
    t_max = int(rl_i["FKL03"].max()) if len(rl_i) else 0

    jenis_map = {"P1": "Penyalahgunaan obat/alkes",
                 "P2": "Penyalahgunaan obat/alkes",
                 "P3": "Pelayanan yang tidak perlu",
                 "P4": "Penyalahgunaan identitas"}
    jenis_dugaan = jenis_map.get(ftype[i], "Anomali umum")

    kartu.append({
        "id_pseudonim":      pseudonim(pstv01[i]),
        "jenis_dugaan":      jenis_dugaan,
        "waktu_kejadian":    f"hari {t_min}-{t_max}",
        # Provinsi terlibat (FKL05) - relevan untuk deteksi geo P4
        "provinsi_terlibat": ";".join(rl_i["FKL05"].unique().tolist()),
        # Faskes terlibat (FKL08)
        "faskes_terlibat":   ";".join(rl_i["FKL08"].unique().tolist()),
        # Kode obat diklaim (FKL44 — special drugs)
        "kode_obat_fkl44":   ";".join(rl_i["FKL44"].unique().tolist()),
        # Diagnosis terlibat (FKP15 ICD-10)
        "kode_diagnosis":    ";".join(fktp_i["FKP15"].unique().tolist()),
        # Tanggal diterima obat: tanggal pulang kunjungan FKRTL (FKL04)
        "tgl_terima_obat":   ";".join(rl_i["FKL04"].astype(str).unique().tolist()),
        "jumlah_kunjungan":  len(rl_i),
        "total_biaya_tagih": int(rl_i["FKL47"].sum()) if len(rl_i) else 0,
        "skor":              round(float(score_m[i]), 4),
        "label_sintetis":    int(fraud[i]),
        "tipe_fraud":        ftype[i],
        # Fitur per-kasus untuk penjelasan alasan flag (sesuai proposal hal. 5 — alasan flag)
        "alasan_flag": ";".join(filter(None, [
            f"n_faskes_30d={feat['n_faskes_30d'].iloc[i]:.0f}" if feat["n_faskes_30d"].iloc[i] >= 3 else "",
            f"qty_ratio={feat['qty_ratio'].iloc[i]:.1f}x"     if feat["qty_ratio"].iloc[i] >= 2.5 else "",
            f"gap_days={feat['gap_days'].iloc[i]:.2f}"        if feat["gap_days"].iloc[i] <= 0.4 else "",
            f"repeat_svc={feat['repeat_svc_60d'].iloc[i]:.0f}" if feat["repeat_svc_60d"].iloc[i] >= 5 else "",
            f"geo_conflict={feat['geo_time_conflict'].iloc[i]:.0f}" if feat["geo_time_conflict"].iloc[i] >= 1 else "",
        ])),
        # Sub-kategori yang relevan untuk routing ke role (Apoteker/Dokter/Verifikator)
        "role_target": (
            "Apoteker"   if ftype[i] in ("P1","P2") else
            "Dokter"     if ftype[i] == "P3" else
            "Verifikator" if ftype[i] == "P4" else
            "Verifikator"
        ),
    })

df_kartu = pd.DataFrame(kartu)
df_kartu.to_csv("kartu_kasus.csv", index=False, encoding="utf-8-sig")
print(f"\nKartu kasus disimpan : {len(df_kartu)} baris -> kartu_kasus.csv")
print(f"Fraud tertangkap     : {df_kartu['label_sintetis'].sum()} / {y.sum()}")
