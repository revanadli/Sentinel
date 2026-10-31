# 🛡️ JKN Sentinel — Antrean Telaah Fraud Klaim JKN
**Healthkathon 2026** | Tim: Fayad, Nabil, Revan

Sistem yang mengubah data klaim JKN menjadi **antrean kasus beralasan** untuk petugas (Apoteker, Dokter, Verifikator). Bukan vonis, bukan blokir otomatis: setiap temuan berstatus *perlu verifikasi* dan keputusan akhir ada di manusia.

> ⚠️ **Prototipe ini berjalan pada data sintetis** yang mengikuti skema data sampel BPJS Kesehatan. Semua angka performa membuktikan bahwa mesin bekerja sesuai desain, **bukan** akurasi pada data JKN riil. Angka riil baru dapat diukur saat pilot (butuh MoU & izin data).

---

## 🎯 Masalah yang dijawab

| Masalah | Pola terdeteksi | Sinyal (rule) | Petugas |
|---|---|---|---|
| Penyalahgunaan obat/alkes | **P1** drug shopping · **P2** kuantitas berlebih / tebus dini | obat sama di ≥ 3 faskes / 30 hari · kuantitas ≥ 2,8× kebutuhan · tebus ulang sebelum 40% masa terapi | Apoteker |
| Pelayanan yang tidak perlu | **P3** layanan sama berulang | poli & diagnosis sama ≥ 5× / 60 hari | Dokter |
| Penyalahgunaan identitas | **P4** identitas dipakai lintas wilayah | kunjungan di provinsi berbeda ≤ 1 hari | Verifikator |
| Anomali tanpa rule tunggal | **AN** | skor IsolationForest tinggi (alasan = fitur paling menyimpang) | Verifikator |

Ambang rule hidup di satu tempat (`TH` di `sentinel_prototype.py`) dan diekspor ke `results.json`, sehingga dashboard selalu menampilkan angka yang sama dengan mesin.

**Pola dan role diturunkan dari rule yang menyala**, bukan dari label simulasi. Label sintetis (`label_sintetis`, `tipe_fraud`) hanya disimpan untuk evaluasi dan ditandai "hanya demo" di dashboard.

## 🔄 Alur

```
Data FKTP/FKRTL ─▶ Pseudonim (SHA-256) ─▶ 7 fitur ─▶ Rules + IsolationForest
   ─▶ normalisasi per kelompok (kronis × usia) ─▶ antrean top-K (kapasitas telaah)
   ─▶ kartu kasus + alasan + prioritas ─▶ keputusan petugas ─▶ precision terverifikasi
```

* **Titik operasi** = kapasitas telaah (`REVIEW_BUDGET_PCT`, default 3% peserta), *bukan* jumlah fraud sebenarnya.
* **Prioritas**: peringkat ≤ 100 *Segera*, ≤ 300 *Tinggi*, sisanya *Sedang*.
* **Potensi kerugian** = estimasi biaya klaim berlebih/berulang (bukan kerugian terbukti).
* **Break-even** (dashboard › Overview): `precision × potensi per kasus ≥ biaya telaah per kasus`. Setelah ≥ 20 keputusan, precision *terverifikasi* menggantikan precision simulasi.

## ⚡ Menjalankan

```bash
pip install -r requirements.txt
python sentinel_prototype.py          # ±15 detik → kartu_kasus.csv + results.json
python -m http.server 8080            # jalankan dari folder Sentinel (bukan dashboard/)
```
Buka **http://localhost:8080/dashboard/**.

Opsional: `SENTINEL_SALT=<rahasia>` untuk salt pseudonimisasi (default hanya untuk demo).

### Mode database (XAMPP + MySQL, opsional)
1. Start Apache & MySQL, salin folder `Sentinel/` ke `C:\xampp\htdocs\sentinel\` (atau jalankan `setup_xampp.bat`).
2. Impor `backend/schema.sql` di phpMyAdmin. **Jika sebelumnya sudah pernah impor, hapus tabel `kartu_kasus` lebih dulu** (kolom berubah).
3. Salin `backend/.env.example` → `backend/.env`, isi `GEMINI_API_KEY` bila ingin AI.
4. Buka **http://localhost/sentinel/dashboard/** → klik **⬆ Import DB**. Re-import tidak menimpa status verifikasi yang sudah diisi petugas.

Di mode database, keputusan + catatan tersimpan di tabel `kartu_kasus` dan `investigasi_log` (jejak audit). Di mode CSV, keputusan tersimpan di browser dan dapat diekspor lewat tombol **⬇ Ekspor keputusan**.

## 📁 Struktur

```
sentinel_prototype.py   # generator data sintetis + fitur + model + evaluasi + kartu kasus
requirements.txt
kartu_kasus.csv         # antrean telaah (output)
results.json            # SATU-SATUNYA sumber metrik untuk dashboard
dashboard/              # index.html · app.js · style.css (responsif, tanpa angka hardcode)
backend/                # PHP + MySQL opsional: cases, stats, verify, import, chat (proxy Gemini)
```

## 📊 Hasil evaluasi (data sintetis, seed 2026)

Nilai persisnya selalu dibaca dari `results.json`; tabel ini hanya cuplikan run 31 Okt 2026.

| Metrik | Nilai | Catatan |
|---|---|---|
| Peserta · fraud tertanam · decoy | 20.000 · 540 (2,7%) · 900 | decoy = pasien sah yang mirip fraud |
| **Precision@100 / @300** | **100% / 100%** | kasus teratas bersih |
| **Precision@600** (kapasitas 3%) | **87,7%** | 526 benar, 74 bukan fraud |
| **Recall@600** | **97,4%** | |
| Lift vs acak | 32,5× | baseline = prevalensi 2,7% |
| ROC-AUC · PR-AUC | 0,990 · 0,977 | skor final |
| Recall per pola | P1 100% · P2 100% · P3 100% · **P4 82,5%** | P4 terendah: sebagian kasus sengaja borderline |
| Akurasi kategori (role tujuan sesuai pola) | ≈ 95% | |
| Flag pasien kronis non-fraud | 1,39% → 0,37% | setelah normalisasi per kelompok |
| Decoy ter-flag | 8,11% → 2,22% | |
| Pembanding blokir otomatis (n_faskes ≥ 2) | recall hanya 51,7%, ±46 peserta sah terblokir | alasan tidak dipakai |

**Sensitivitas prevalensi** (precision antrean pada ambang yang sama): 2,7% → 87,7% · 1% → 72,1% · 0,5% → 56,3% · 0,2% → 33,9%. Bila fraud riil lebih jarang, ambang dan K harus dikalibrasi saat pilot.

### Cara membaca Precision@K dengan benar
* Precision@K = dari K kasus teratas, berapa yang benar-benar fraud. Cocok karena verifikator punya kapasitas terbatas.
* Nilainya bergantung pada prevalensi dan definisi label. Di sini keduanya dibuat tim, sehingga **tidak berlaku umum** di data riil.
* Karena itu dashboard menampilkan lift vs acak, PR-AUC, sensitivitas prevalensi, dan **precision terverifikasi** dari keputusan petugas sebagai pengganti saat pilot.

## ⚖️ Etika & kepatuhan
* **Tanpa blokir otomatis** — hanya rekomendasi telaah (human-in-the-loop); tombol *Flag Salah* mengembalikan umpan balik.
* **Pseudonimisasi SHA-256 + salt**; mekanisme buka-identitas bagi verifikator berwenang **belum** diimplementasi dan salt demo wajib diganti di produksi.
* Setiap keputusan mencatat waktu, peran, dan catatan (log audit di mode database).
* Fitur *fairness*: skor anomali dinormalisasi per kelompok (kronis diamati dari ICD-10 × usia) agar pasien kronis/lansia tidak terdiskriminasi.
* Chat AI (Gemini): di mode CSV kunci API disimpan di browser (cukup untuk demo); untuk produksi gunakan mode backend (proxy PHP).

## 🚧 Batasan & langkah berikutnya
1. Pilot dengan data JKN riil (MoU, izin etik) untuk mengukur precision sebenarnya.
2. Kalibrasi ambang & K pada prevalensi riil; pantau precision terverifikasi.
3. Mekanisme buka-identitas terotorisasi, manajemen salt, autentikasi petugas.
4. SOP telaah formal dan pengukuran waktu telaah per kasus.
