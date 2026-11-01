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
                    FKL46 (tarif special drugs; kuantitas TIDAK ada di data sampel),
                    FKL47 (biaya_tagih), FKL48 (biaya_verifikasi)
  FKRTL_DX_SEK    : FKL02, FKL24 (kode_dx_sekunder - ICD-10)

CATATAN: Script ini menggunakan DATA SINTETIS yang mengikuti skema BPJS.
         Data riil hanya bisa diakses melalui data.bpjs-kesehatan.go.id
         dengan MoU dan izin resmi.

Jalankan: python sentinel_prototype.py
"""

import json
from datetime import date

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.preprocessing import StandardScaler

# ==============================================================================
# KONFIGURASI
# ==============================================================================
from keystore import buat_vault, pseudonim   # HMAC pseudonim + brankas identitas terenkripsi
rng     = np.random.default_rng(2026)
N       = 20_000    # jumlah peserta
HORIZON = 180       # rentang hari observasi

# Provinsi BPS (5 provinsi sample, sesuai kode wilayah BPS)
PROV_CODES   = ["32", "31", "35", "33", "36"]   # Jabar, DKI, Jatim, Jateng, Banten
KAB_PER_PROV = [10, 5, 8, 6, 4]
# Pusat provinsi (lat, lon) untuk menilai jarak: kunjungan berjauhan dalam waktu dekat = janggal.
# Jabodetabek (DKI-Banten-Jabar) berdekatan, sehingga tidak dianggap konflik.
PROV_COORD = {"32": (-6.92, 107.61), "31": (-6.20, 106.85), "35": (-7.25, 112.75),
              "33": (-6.97, 110.42), "36": (-6.12, 106.15)}
GEO_WINDOW_DAYS = 2      # selisih hari maksimum antar dua kunjungan
GEO_MIN_KM      = 150    # jarak minimum antar provinsi agar dianggap janggal

def _hav(a, b):
    la1, lo1, la2, lo2 = map(np.radians, (*a, *b))
    h = np.sin((la2 - la1) / 2) ** 2 + np.cos(la1) * np.cos(la2) * np.sin((lo2 - lo1) / 2) ** 2
    return float(6371 * 2 * np.arcsin(np.sqrt(h)))

DIST = np.array([[_hav(PROV_COORD[a], PROV_COORD[b]) for b in PROV_CODES] for a in PROV_CODES])

# Kode obat sintetis (menyerupai FKL44 special drugs SD)
DRUG_CODES = [f"SD{str(i).zfill(3)}" for i in range(30)]
# Data sampel BPJS tidak punya kuantitas obat; yang ada FKL46 = TARIF special drugs.
# Simulasi: tarif = harga paket obat x jumlah paket (kuantitas tidak disimpan di tabel).
UNIT_PRICE = rng.integers(2_000, 20_000, len(DRUG_CODES))

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

def _profil_faskes(pid):
    """Data sampel BPJS tidak memuat ID faskes: yang ada hanya lokasi (kab/kota) + jenis + tipe.
    Peserta punya 'profil' faskes langganan di kab/kota-nya (3 kemungkinan)."""
    v = int(pid[3:]) % 3
    return v + 1, "BCD"[v]          # (jenis, tipe)


def nxt_fkp02():
    global fkp02_ctr; fkp02_ctr += 1
    return f"FKP{fkp02_ctr:09d}"

def nxt_fkl02():
    global fkl02_ctr; fkl02_ctr += 1
    return f"FKL{fkl02_ctr:09d}"

def add_fktp(pid, fkp02, prov, kab, tgl_datang, tgl_pulang, poli, dx_3d, dx_full):
    jenis, tipe = _profil_faskes(pid)
    fktp_rows.append({
        "PSTV01": pid,
        "FKP02":  fkp02,
        "FKP03":  tgl_datang,              # tanggal datang kunjungan FKTP
        "FKP04":  tgl_pulang,              # tanggal pulang kunjungan FKTP
        "FKP05":  prov,                    # provinsi FKTP (kode BPS)
        "FKP06":  kab,                     # kab/kota FKTP
        "FKP08":  jenis,                   # jenis FKTP
        "FKP09":  tipe,                    # tipe FKTP
        "FKP11":  poli,                    # jenis poli
        "FKP14":  dx_3d,                   # kode ICD-10 3 digit
        "FKP15":  dx_full,                 # kode ICD-10 lengkap
    })

def add_fkrtl(pid, fkp02_ref, prov, kab, tgl_datang, tgl_pulang,
              poli, dx_masuk, dx_primer,
              kode_obat, desk_obat, qty_obat,
              biaya_lain, _biaya_verifikasi_tidak_dipakai=None):
    jenis, tipe = _profil_faskes(pid)
    tarif = int(UNIT_PRICE[int(kode_obat[2:])] * qty_obat * rng.uniform(0.9, 1.1))   # FKL46
    tagih = tarif + int(biaya_lain)                                                    # FKL47
    verif = int(tagih * rng.uniform(0.9, 1.0))                                         # FKL48
    fkrtl_rows.append({
        "PSTV01":    pid,
        "FKP02":     fkp02_ref,            # link ke kunjungan FKTP asal rujukan
        "FKL02":     nxt_fkl02(),
        "FKL03":     tgl_datang,           # tanggal datang kunjungan FKRTL
        "FKL04":     tgl_pulang,           # tanggal pulang kunjungan FKRTL
        "FKL05":     prov,                 # provinsi FKRTL (kode BPS)
        "FKL06":     kab,
        "FKL08":     jenis,                # jenis FKRTL
        "FKL09":     tipe,                 # tipe FKRTL
        "FKL11":     poli,
        "FKL15":     dx_masuk,             # kode diagnosis masuk ICD-10
        "FKL18":     dx_primer,            # kode diagnosis primer ICD-10
        "FKL44":     kode_obat,            # kode special drugs
        "FKL45":     desk_obat,            # deskripsi obat
        "FKL46":     tarif,                # tarif special drugs
        "FKL47":     tagih,                # biaya tagih provider
        "FKL48":     verif,                # biaya verifikasi BPJS
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
                          drug, f"OBAT-{drug}", 30,
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
    t0   = rng.integers(40, 120)
    n_visit = rng.integers(5, 10)   # 5-9 kunjungan (5 bisa false-negative)
    for _ in range(n_visit):
        pr  = PROV_CODES[rng.integers(0, len(PROV_CODES))]
        kb  = f"{pr}{rng.integers(1,5):02d}"
        fkp = nxt_fkp02()
        t   = t0 + rng.integers(0, 55)
        drug = rng.choice(DRUG_CODES)   # layanan berulang, bukan penebusan obat sama
        add_fktp(pstv01[i], fkp, pr, kb, t, t, poli, dx, dx+".0")
        add_fkrtl(pstv01[i], fkp, pr, kb, t, t+1, poli, dx, dx+".0",
                  drug, f"OBAT-{drug}", 30,
                  rng.integers(50_000, 300_000), rng.integers(50_000, 300_000))

# P4 - Identity fraud: kunjungan di 2 prov berbeda (jauh) di HARI YANG SAMA atau berdekatan
# Realisme: ~30% P4 menggunakan hari berdekatan (t+1) bukan hari persis sama → geo_conflict=0
# Artinya geo_conflict tidak bisa mendeteksi P4 sepenuhnya — recall P4 ~65-75%
for i in P4:
    dx   = rng.choice(ALL_DX)
    t0   = rng.integers(20, 160)
    # Pilih 2 provinsi yang secara geografis berjauhan
    p_home  = prov_idx[i]                          # prov asli
    p_away  = rng.choice([j for j in range(len(PROV_CODES)) if DIST[p_home, j] > GEO_MIN_KM])
    for k, p_target in enumerate([p_home, p_away]):
        pr  = PROV_CODES[p_target]
        kb  = f"{pr}{rng.integers(1,5):02d}"
        fkp = nxt_fkp02()
        drug = rng.choice(DRUG_CODES)   # identitas dipakai orang lain: obat bisa berbeda
        # 70% hari sama; 30% selisih 1-2 hari (selisih 2 hari lolos dari rule ≤1 hari)
        t_visit = t0 if (k == 0 or rng.random() < 0.70) else t0 + rng.integers(1, 3)
        add_fktp(pstv01[i], fkp, pr, kb, t_visit, t_visit, "UMUM", dx, dx+".0")
        add_fkrtl(pstv01[i], fkp, pr, kb, t_visit, t_visit+1, "UMUM", dx, dx+".0",
                  drug, f"OBAT-{drug}", 30,
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
# FEATURE ENGINEERING (7 FITUR) — hanya memakai kolom yang ADA di data sampel BPJS
# ==============================================================================
STD_DAYS = 30   # satu siklus penebusan obat kronis (hari)
FEATS = ["n_faskes_30d", "tarif_ratio", "gap_days", "repeat_svc_60d",
         "dx_norm_z", "geo_time_conflict", "use_vs_self"]
feat = pd.DataFrame(index=range(N))

# Kronis diamati dari diagnosis (ICD-10), BUKAN dari flag laten simulasi
obs_kronis = np.zeros(N, bool)
obs_kronis[FKTP.loc[FKTP["FKP14"].isin(CHRONIC_DX), "_idx"].unique()] = True

# Data sampel tidak punya ID faskes: "faskes" didekati dengan kab/kota + jenis + tipe (FKL06, FKL08, FKL09)
FKRTL["_fk"] = FKRTL["FKL06"].astype(str) + "-" + FKRTL["FKL08"].astype(str) + FKRTL["FKL09"].astype(str)

# F1 n_faskes_30d : lokasi faskes berbeda untuk OBAT YANG SAMA (FKL44) dalam jendela 30 hari
# F3 gap_days     : interval antar penebusan obat sama / siklus 30 hari (kecil = tebus ulang sebelum habis)
R = FKRTL.sort_values(["_idx", "FKL44", "FKL03"]).reset_index(drop=True)
gid    = R.groupby(["_idx", "FKL44"], sort=False).ngroup().to_numpy()
starts = np.flatnonzero(np.diff(gid, prepend=-1))
ends   = np.append(starts[1:], len(R))
Ti, Fi, Ii = R["FKL03"].to_numpy(), R["_fk"].to_numpy(), R["_idx"].to_numpy()
nf = np.ones(N); gp = np.full(N, np.inf)
for s, e in zip(starts, ends):
    if e - s < 2:
        continue
    i, T, F = Ii[s], Ti[s:e], Fi[s:e]
    for k in range(1, len(T)):
        lo = np.searchsorted(T, T[k] - 29, side="left")
        nf[i] = max(nf[i], len(set(F[lo:k + 1])))
    gp[i] = min(gp[i], (np.diff(T) / STD_DAYS).min())
feat["n_faskes_30d"] = nf
feat["gap_days"]     = np.where(np.isinf(gp), 1.0, gp).clip(max=5.0)

# F2 tarif_ratio : tarif special drugs (FKL46) tertinggi / median tarif obat yang sama
#                  (data sampel tidak memuat kuantitas; tarif adalah proksi yang tersedia)
med_tarif = FKRTL.groupby("FKL44")["FKL46"].median()
FKRTL["_rt"] = FKRTL["FKL46"] / FKRTL["FKL44"].map(med_tarif)
feat["tarif_ratio"] = FKRTL.groupby("_idx")["_rt"].max().reindex(range(N)).fillna(1.0).clip(lower=1.0).to_numpy()


# F4 repeat_svc_60d : kunjungan FKTP dengan poli DAN diagnosis sama dalam 60 hari
def window_max_count(df, keys, tcol, window):
    kid  = df.groupby(keys, sort=False).ngroup().to_numpy().astype(np.int64)
    t    = df[tcol].to_numpy().astype(np.int64)
    big  = 100_000
    comb = kid * big + t
    order = np.argsort(comb, kind="stable")
    cs   = comb[order]
    lo   = np.searchsorted(cs, kid[order] * big + (t[order] - (window - 1)), side="left")
    cnt  = np.empty(len(cs), int)
    cnt[order] = np.arange(len(cs)) - lo + 1
    return pd.Series(cnt).groupby(df["_idx"].to_numpy()).max()

feat["repeat_svc_60d"] = (
    window_max_count(FKTP, ["_idx", "FKP11", "FKP14"], "FKP03", 60)
    .reindex(range(N)).fillna(0).to_numpy()
)

# F5 dx_norm_z : z-score jumlah kunjungan vs peserta sekelompok (kronis x usia)
cnt      = pd.concat([FKTP[["_idx"]], FKRTL[["_idx"]]]).groupby("_idx").size().reindex(range(N)).fillna(0)
umur_bin = np.digitize(umur, bins=[30, 45, 60, 75])
grp      = obs_kronis.astype(int) * 5 + umur_bin
feat["dx_norm_z"] = (
    (cnt - cnt.groupby(grp).transform("mean")) /
    cnt.groupby(grp).transform("std").replace(0, 1)
).to_numpy()

# F6 geo_time_conflict : dua kunjungan dengan selisih <= GEO_WINDOW_DAYS hari di provinsi yang
#                        berjarak > GEO_MIN_KM (tidak mungkin ditempuh, atau kartu dipakai orang lain)
pidx = {c: k for k, c in enumerate(PROV_CODES)}
K_ = FKTP.sort_values(["_idx", "FKP03"]).reset_index(drop=True)
npv = K_.groupby("_idx")["FKP05"].nunique()
sub = K_[K_["_idx"].isin(set(npv[npv > 1].index.tolist()))]
geo = np.zeros(N)
for i, g in sub.groupby("_idx"):
    T = g["FKP03"].to_numpy()
    W = np.array([pidx[c] for c in g["FKP05"]])
    d = T[None, :] - T[:, None]
    far = DIST[W[:, None], W[None, :]] > GEO_MIN_KM
    geo[i] = np.triu((d >= 0) & (d <= GEO_WINDOW_DAYS) & far, 1).sum()

feat["geo_time_conflict"] = geo

# F7 use_vs_self : lonjakan tarif obat vs rata-rata riwayat sendiri
mean_t = FKRTL.groupby("_idx")["FKL46"].mean().reindex(range(N)).fillna(1.0)
max_t  = FKRTL.groupby("_idx")["FKL46"].max().reindex(range(N)).fillna(1.0)
feat["use_vs_self"] = (max_t / mean_t.replace(0, 1)).clip(upper=10).to_numpy()


# ==============================================================================
# MODEL DETEKSI: RULES (transparan) + ISOLATION FOREST (anomali)
# ==============================================================================
# Ambang rule = satu-satunya sumber kebenaran; ikut diekspor ke results.json
TH = {"n_faskes_30d": 3, "tarif_ratio": 2.2, "gap_days": 0.45,
      "repeat_svc_60d": 5, "geo_time_conflict": 1}
KATEGORI = {"n_faskes_30d": "obat", "tarif_ratio": "obat", "gap_days": "obat",
            "repeat_svc_60d": "layanan", "geo_time_conflict": "identitas"}
# Sinyal STRUKTURAL (bukti multi-lokasi / pengulangan) cukup berdiri sendiri. Sinyal LEMAH
# (tarif tinggi saja, atau tebus dini saja) punya penjelasan sah yang umum -> butuh sinyal kedua.
STRUKTURAL = ["n_faskes_30d", "repeat_svc_60d", "geo_time_conflict"]

fired = pd.DataFrame({
    "n_faskes_30d":      feat["n_faskes_30d"]      >= TH["n_faskes_30d"],
    "tarif_ratio":       feat["tarif_ratio"]       >= TH["tarif_ratio"],
    "gap_days":          feat["gap_days"]          <= TH["gap_days"],
    "repeat_svc_60d":    feat["repeat_svc_60d"]    >= TH["repeat_svc_60d"],
    "geo_time_conflict": feat["geo_time_conflict"] >= TH["geo_time_conflict"],
})
rules = fired.sum(axis=1).to_numpy().astype(float)
kuat  = (fired[STRUKTURAL].any(axis=1) | (fired.sum(axis=1) >= 2)).to_numpy()   # lolos pembersih salah-tuduh

X  = feat[FEATS].to_numpy().astype(float)
y  = fraud
Xs = StandardScaler().fit_transform(X)
iso  = IsolationForest(n_estimators=300, contamination="auto", random_state=42).fit(Xs)
anom = -iso.score_samples(Xs)
anom = (anom - anom.min()) / (anom.max() - anom.min())

score   = rules + anom                                          # tanpa fairness
anom_g  = pd.Series(anom).groupby(pd.Series(grp)).rank(pct=True).to_numpy()
score_m = rules + anom_g                                        # skor final (fairness)


# ==============================================================================
# TITIK OPERASI: antrean telaah = bukti kuat, dibatasi kapasitas (bukan jumlah fraud sebenarnya)
# ==============================================================================
REVIEW_BUDGET_PCT = 0.03                    # asumsi: verifikator sanggup telaah 3% peserta
K_BUDGET = round(N * REVIEW_BUDGET_PCT)
TIER     = {"segera": 100, "tinggi": 300}   # peringkat <=100 segera, <=300 tinggi, sisanya sedang
Ks = sorted({50, 100, 200, 300, 400, K_BUDGET, 800})
prev = float(y.mean())


def antrean(sc):
    """Peringkat skor, hanya kasus berbukti kuat, maksimum K_BUDGET."""
    o = np.argsort(-sc, kind="stable")
    return o[kuat[o]][:K_BUDGET]


# ==============================================================================
# EVALUASI
# ==============================================================================
tie = np.random.default_rng(7).random(N) * 1e-9   # pemecah seri deterministik untuk rules

def at_k(sc, K):
    top = np.argsort(-sc, kind="stable")[:K]
    tp  = y[top].sum()
    return [round(float(tp / K), 3), round(float(tp / y.sum()), 3),
            round(float(decoy[top].sum() / max(decoy.sum(), 1)), 3)]

def auc_pair(sc):
    return {"roc": round(float(roc_auc_score(y, sc)), 4),
            "pr":  round(float(average_precision_score(y, sc)), 4)}

methods = {"rules": rules + tie, "iforest": anom, "gabungan": score, "fair": score_m}

def flags(idx):
    f = np.zeros(N, bool); f[idx] = True; return f

def summ(f):
    nk = ~obs_kronis & (y == 0)
    return {
        "recall":     round(float(f[y == 1].mean()), 4),
        "kronis":     round(float(f[obs_kronis & (y == 0)].mean() * 100), 2),
        "non_kronis": round(float(f[nk].mean() * 100), 2),
        "decoy_pct":  round(float(f[decoy == 1].mean() * 100), 2),
    }

order_idx   = antrean(score_m)
flag_before = flags(antrean(score))
flag_after  = flags(order_idx)
K_Q = len(order_idx)

tp_k = int((flag_after & (y == 1)).sum())
fp_k = int((flag_after & (y == 0)).sum())
rec_k = tp_k / y.sum()
fpr_k = fp_k / (N - y.sum())

def prec_at_prevalence(p):
    nfp = p * N
    return round(float(rec_k * nfp / (rec_k * nfp + fpr_k * (N - nfp))), 3)

# Kasus bersinyal lemah: tidak ditelaah, hanya dipantau
pantau_mask = (rules >= 1) & ~flag_after
lolos_mask  = (y == 1) & ~flag_after


# ==============================================================================
# KARTU KASUS (antrean telaah) — pola & role diturunkan dari RULE yang menyala
# ==============================================================================
CAT_ORDER = ["obat", "layanan", "identitas"]   # prioritas bila jumlah rule sama
def klasifikasi(i):
    f = fired.iloc[i]
    n = {c: int(sum(f[k] for k, cat in KATEGORI.items() if cat == c)) for c in CAT_ORDER}
    if sum(n.values()) == 0:
        return "AN", "anomali"
    kat = max(CAT_ORDER, key=lambda c: n[c])
    if kat == "obat":
        return ("P1" if f["n_faskes_30d"] else "P2"), kat
    return ("P3" if kat == "layanan" else "P4"), kat

JENIS   = {"obat": "Penyalahgunaan obat/alkes", "layanan": "Pelayanan yang tidak perlu",
           "identitas": "Penyalahgunaan identitas", "anomali": "Anomali umum (perlu telaah)"}
ROLE    = {"obat": "Apoteker", "layanan": "Dokter",
           "identitas": "Verifikator", "anomali": "Verifikator"}

rl_f = FKRTL[FKRTL["_idx"].isin(order_idx.tolist())]
tp_f = FKTP[FKTP["_idx"].isin(order_idx.tolist())]
rl_g = {k: v.sort_values("FKL03") for k, v in rl_f.groupby("_idx")}
tp_g = {k: v for k, v in tp_f.groupby("_idx")}
EMPTY_RL = FKRTL.iloc[0:0]; EMPTY_TP = FKTP.iloc[0:0]

kartu = []
for rank, i in enumerate(order_idx, start=1):
    rl_i, fk_i = rl_g.get(i, EMPTY_RL), tp_g.get(i, EMPTY_TP)
    pola, kat = klasifikasi(i)
    f = fired.iloc[i]

    days = rl_i["FKL03"] if len(rl_i) else fk_i["FKP03"]
    t_min, t_max = (int(days.min()), int(days.max())) if len(days) else (0, 0)
    provs = sorted(set(rl_i["FKL05"]) | set(fk_i["FKP05"]))

    alasan = []
    if f["n_faskes_30d"]:      alasan.append(f"n_faskes_30d={feat['n_faskes_30d'].iloc[i]:.0f}")
    if f["tarif_ratio"]:       alasan.append(f"tarif_ratio={feat['tarif_ratio'].iloc[i]:.1f}x")
    if f["gap_days"]:          alasan.append(f"gap_days={feat['gap_days'].iloc[i]:.2f}")
    if f["repeat_svc_60d"]:    alasan.append(f"repeat_svc={feat['repeat_svc_60d'].iloc[i]:.0f}")
    if f["geo_time_conflict"]: alasan.append(f"geo_conflict={feat['geo_time_conflict'].iloc[i]:.0f}")

    # Kerugian: (a) estimasi = kelebihan tarif di atas median obat sama, atau tagihan kunjungan berulang;
    #           (b) terverifikasi = selisih biaya tagih (FKL47) - biaya verifikasi BPJS (FKL48)
    if len(rl_i):
        excess = (rl_i["FKL46"] - rl_i["FKL44"].map(med_tarif)).clip(lower=0).sum()
        dup    = rl_i["FKL47"].iloc[1:].sum() if len(rl_i) > 1 else 0
        potensi   = int(max(excess, dup))
        biaya     = int(rl_i["FKL47"].sum())
        terverif  = int((rl_i["FKL47"] - rl_i["FKL48"]).clip(lower=0).sum())
    else:
        potensi = biaya = terverif = 0

    kartu.append({
        "id_pseudonim":      pseudonim(pstv01[i]),
        "peringkat":         rank,
        "prioritas":         "Segera" if rank <= TIER["segera"] else
                             "Tinggi" if rank <= TIER["tinggi"] else "Sedang",
        "pola_terdeteksi":   pola,
        "jenis_dugaan":      JENIS[kat],
        "role_target":       ROLE[kat],
        "waktu_kejadian":    f"hari {t_min}-{t_max}",
        "provinsi_terlibat": ";".join(provs),
        "faskes_terlibat":   ";".join(rl_i["_fk"].unique().tolist()),
        "kode_obat_fkl44":   ";".join(rl_i["FKL44"].unique().tolist()),
        "kode_diagnosis":    ";".join(fk_i["FKP15"].unique().tolist()),
        "tgl_terima_obat":   ";".join(rl_i["FKL04"].astype(str).unique().tolist()),
        "jumlah_kunjungan":  len(rl_i),
        "total_biaya_tagih": biaya,
        "potensi_kerugian":  potensi,
        "kerugian_terverifikasi": terverif,
        "skor":              round(float(score_m[i]), 4),
        "alasan_flag":       ";".join(alasan),
        **{k: round(float(feat[k].iloc[i]), 3) for k in FEATS},
        # --- kolom evaluasi sintetis (TIDAK ada pada data riil) ---
        "label_sintetis":    int(fraud[i]),
        "tipe_fraud":        ftype[i],
    })

df_kartu = pd.DataFrame(kartu)
df_kartu.to_csv("kartu_kasus.csv", index=False, encoding="utf-8-sig")

# Brankas identitas terenkripsi: pseudonim -> ID asli (antrean + pantauan)
vault_ids = set(order_idx.tolist()) | set(np.flatnonzero(pantau_mask).tolist())
buat_vault({pseudonim(pstv01[i]): str(pstv01[i]) for i in vault_ids})


# ==============================================================================
# RINGKASAN HASIL -> results.json (satu-satunya sumber angka untuk dashboard)
# ==============================================================================
EXPECT_KAT = {"P1": "obat", "P2": "obat", "P3": "layanan", "P4": "identitas"}
top_set = set(order_idx.tolist())
akurasi_kat = {}
for t, kat_exp in EXPECT_KAT.items():
    ids = [i for i in np.where(ftype == t)[0] if i in top_set]
    ok  = sum(1 for i in ids if klasifikasi(i)[1] == kat_exp)
    akurasi_kat[t] = round(ok / len(ids), 3) if ids else None

hs = (feat["n_faskes_30d"] >= 2).values
out = {
    "run_at":            date.today().strftime("%d %b %Y"),
    "data_sintetis":     True,
    "n_peserta":         N,
    "n_fraud_tertanam":  int(y.sum()),
    "n_decoy":           int(decoy.sum()),
    "prevalensi":        round(prev, 4),
    "horizon_hari":      HORIZON,
    "n_kunjungan_fktp":  len(FKTP),
    "n_kunjungan_fkrtl": len(FKRTL),
    "tipe":              {t: int((ftype == t).sum()) for t in ("P1", "P2", "P3", "P4")},
    "threshold_rules":   TH,
    "geo": {"jendela_hari": GEO_WINDOW_DAYS, "jarak_min_km": GEO_MIN_KM},
    "hari_terapi_standar": STD_DAYS,
    "review_budget":     {"pct": REVIEW_BUDGET_PCT, "k": K_BUDGET},
    "tier_cuts":         TIER,
    "kurva":             {n: {str(K): at_k(s, K) for K in Ks} for n, s in methods.items()},
    "auc":               {n: auc_pair(s) for n, s in methods.items()},
    "operasi": {
        "k":                K_Q,
        "kapasitas":        K_BUDGET,
        "precision":        round(tp_k / K_Q, 4),
        "recall":           round(rec_k, 4),
        "lift_vs_acak":     round((tp_k / K_Q) / prev, 1),
        "fraud_di_antrean": tp_k,
        "bukan_fraud":      fp_k,
        "total_biaya":      int(df_kartu["total_biaya_tagih"].sum()),
        "total_potensi":    int(df_kartu["potensi_kerugian"].sum()),
        "total_terverifikasi": int(df_kartu["kerugian_terverifikasi"].sum()),
    },
    "pembersih": {
        "pantauan":            int(pantau_mask.sum()),
        "fraud_di_pantauan":   int((pantau_mask & (y == 1)).sum()),
        "fraud_lolos_total":   int(lolos_mask.sum()),
        "lolos_per_tipe":      {t: int((lolos_mask & (ftype == t)).sum()) for t in ("P1", "P2", "P3", "P4")},
    },
    "fairness": {"sebelum": summ(flag_before), "sesudah": summ(flag_after)},
    "recall_tipe":       {t: round(float(flag_after[ftype == t].mean()), 3) for t in ("P1", "P2", "P3", "P4")},
    "akurasi_kategori":  akurasi_kat,
    "hardstop": {
        "diblokir":           int(hs.sum()),
        "precision":          round(float(y[hs].mean()), 4),
        "recall":             round(float(hs[y == 1].mean()), 4),
        "decoy_diblokir_pct": round(float(decoy[hs].sum() / max(decoy.sum(), 1) * 100), 2),
    },
    "sensitivitas_prevalensi": [
        {"prevalensi": p, "precision": prec_at_prevalence(p)}
        for p in sorted({round(prev, 4), 0.01, 0.005, 0.002}, reverse=True)
    ],
}
with open("results.json", "w", encoding="utf-8") as fh:
    json.dump(out, fh, indent=1, ensure_ascii=False)

o = out["operasi"]
print(f"\nPeserta {N:,} | fraud tertanam {int(y.sum())} ({prev:.1%}) | decoy {int(decoy.sum())}")
print(f"Antrean telaah K={K_Q} (kapasitas {K_BUDGET}): precision {o['precision']:.1%} | recall {o['recall']:.1%} "
      f"| lift {o['lift_vs_acak']}x vs acak")
print(f"AUC skor final: ROC {out['auc']['fair']['roc']} | PR {out['auc']['fair']['pr']}")
print(f"Recall per tipe: {out['recall_tipe']} | akurasi kategori: {akurasi_kat}")
print(f"Pantauan (sinyal lemah, tidak ditelaah): {out['pembersih']['pantauan']} "
      f"(fraud di dalamnya {out['pembersih']['fraud_di_pantauan']}) | fraud lolos total: "
      f"{out['pembersih']['fraud_lolos_total']} {out['pembersih']['lolos_per_tipe']}")
print(f"Kartu kasus -> kartu_kasus.csv ({len(df_kartu)} baris) | results.json | brankas terenkripsi")
