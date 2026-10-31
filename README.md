# 🛡️ JKN Sentinel — AI Fraud Detection System
**Healthkathon 2026** | Tim: Fayad, Nabil, Revan

Sistem deteksi fraud klaim JKN/BPJS Kesehatan berbasis AI (Rules + Isolation Forest) yang transparan, adil, dan audit-ready.

---

## 🎯 Tentang Project

Sistem ini memantau dan mendeteksi **3 Masalah Utama Fraud Klaim BPJS**:
1. 💊 **Penyalahgunaan Obat (P1 & P2)**: Deteksi *drug shopping* lintas faskes/provinsi dan klaim kuantitas obat berlebihan (melebihi dosis terapi bulanan). Ditugaskan ke role **Apoteker**.
2. 🏥 **Pelayanan yang Tidak Perlu (P3)**: Deteksi duplikasi klaim rujukan/tindakan poli yang sama berkali-kali dalam 60 hari. Ditugaskan ke role **Dokter**.
3. 🪪 **Penyalahgunaan Identitas (P4)**: Deteksi kartu peserta yang sama dipakai berobat di 2 provinsi berbeda dalam 1 hari yang sama. Ditugaskan ke role **Verifikator**.

Semua temuan dialirkan ke antrean verifikasi petugas dengan opsi tindakan:
- **✅ Flag Salah (Bukan Fraud)**
- **🚨 Konfirmasi Fraud**
- **⬆️ Eskalasi Audit**
- **✨ Analisis Mendalam via AI (Google Gemini)**

---

## ⚡ Panduan Menjalankan Aplikasi (Untuk Rekan Tim)

Ada **2 Cara** menjalankan project ini:

### 🟢 CARA 1: Paling Cepat & Simpel (Mode CSV — Tanpa XAMPP)
*Gunakan cara ini untuk langsung melihat tampilan dashboard dan demo.*

1. **Pastikan dependencies Python terinstall:**
   ```bash
   pip install numpy pandas scikit-learn
   ```

2. **Jalankan script AI / Machine Learning (cukup sekali di awal):**
   ```bash
   cd c:/bejana/sentinel/Sentinel
   python sentinel_prototype.py
   ```
   *(Perintah ini akan memproses 20.000 data sampel dan menghasilkan `kartu_kasus.csv`, `results.json`, serta `results2.json`).*

3. **Nyalakan web server lokal:**
   > ⚠️ **PENTING:** Jalankan perintah ini dari folder utama `Sentinel`, **JANGAN** dari dalam folder `dashboard/`!
   ```bash
   python -m http.server 8080
   ```

4. **Buka di Browser:**
   Buka URL berikut di Chrome/Edge/Firefox:
   👉 **[http://localhost:8080/dashboard/](http://localhost:8080/dashboard/)**  
   *(Pastikan ada garis miring `/` di ujung kata dashboard)*.

---

### 🔵 CARA 2: Full-Stack dengan Database (Mode XAMPP + MySQL)
*Gunakan cara ini jika ingin data kasus dan aksi verifikasi tersimpan permanen di MySQL.*

1. Buka **XAMPP Control Panel**, lalu klik **Start** pada **Apache** dan **MySQL**.
2. Salin seluruh isi folder `Sentinel/` ke folder web XAMPP Anda:
   `C:\xampp\htdocs\sentinel\`
3. Buka browser ke: `http://localhost/phpmyadmin`
   - Buat database baru dengan nama: `sentinel_db`
   - Klik tab **Import**, pilih file `backend/schema.sql`, lalu klik **Import**.
4. Buka file `backend/.env` (atau edit dari `backend/.env.example`), pastikan konfigurasi DB sesuai:
   ```env
   DB_HOST=localhost
   DB_NAME=sentinel_db
   DB_USER=root
   DB_PASS=
   GEMINI_API_KEY=your_gemini_api_key_here
   ```
5. Buka dashboard di browser:
   👉 **[http://localhost/sentinel/dashboard/](http://localhost/sentinel/dashboard/)**
6. Klik tombol **"⬆ Import DB"** di pojok kanan atas untuk memasukkan data CSV ke dalam database MySQL.

---

## 📁 Struktur Berkas

```
Sentinel/
├── sentinel_prototype.py      # Engine ML utama (Feature extraction 7 fitur + Rules + IsolationForest)
├── generate_dataset.py        # Dataset benchmark generator & evaluasi ML
├── audit_metrics.py           # Script audit cepat untuk memvalidasi metrik
│
├── dashboard/                 # Frontend Dashboard
│   ├── index.html             # Halaman utama (Overview, Alur, Kartu Kasus, Model, AI)
│   ├── style.css              # Styling dark-mode & glassmorphism
│   └── app.js                 # Logika interaktif, humanisasi alasan, role switcher & API
│
├── backend/                   # Backend PHP (Opsional / XAMPP)
│   ├── config.php             # Koneksi PDO & environment loader
│   ├── schema.sql             # Skema 4 tabel MySQL (kartu_kasus, investigasi_log, dll)
│   └── api/
│       ├── cases.php          # API filter, sort, & pagination kasus
│       ├── stats.php          # API statistik agregasi
│       ├── verify.php         # API audit status verifikasi
│       ├── chat.php           # API proxy aman Gemini AI
│       └── import.php         # API import CSV ke MySQL
│
├── kartu_kasus.csv            # 540 kasus terdeteksi lengkap dengan alasan & role
├── results.json               # Hasil metrik evaluasi model (Precision@K)
└── results2.json              # Metrik fairness per kelompok & tipe fraud
```

---

## 🤖 Menghubungkan Fitur AI Investigator (Gemini)

1. Dapatkan API Key Google Gemini gratis di **[aistudio.google.com](https://aistudio.google.com)**.
2. Pada Dashboard, klik menu **⚙️ Pengaturan** di pojok kanan bawah.
3. Tempel API Key Anda pada kolom **Google Gemini API Key**, lalu klik **Simpan**.
4. Masuk ke menu **Detail** kasus mana pun $\rightarrow$ klik **✨ Analisis AI** $\rightarrow$ AI akan membedah kasus secara klinis dan memberikan checklist investigasi lapangan.

---

## 📊 Metrik Performa Model (Hasil Evaluasi Terkini)

| Metrik | Nilai | Penjelasan untuk Dewan Juri |
| :--- | :--- | :--- |
| **Precision@100** | **100%** | Pada top 100 kasus teratas, rules menangkap pelanggaran berat yang sangat eksplisit. |
| **Precision@300** | **96.7%** | Menurun wajar karena model mulai menangani kasus anomali samar. |
| **Precision@600** | **84.3%** | Representasi realistis pada skala deteksi luas. |
| **Overall Recall** | **95.4%** | 95.4% fraud tertangkap setelah normalisasi fairness. |
| **P1 Recall (Obat)** | **94.5%** | Deteksi *drug shopping* lintas wilayah. |
| **P2 Recall (Qty Obat)** | **95.0%** | Deteksi klaim berlebihan dengan toleransi batas aman. |
| **P3 Recall (Layanan)** | **100%** | Deteksi pola kunjungan poli duplikat berulang. |
| **P4 Recall (Identitas)** | **88.7%** | Deteksi geo-time conflict 2 provinsi. |
| **Decoy False Positive** | **2.8%** | Pasien kronis sah tidak sembarangan terblokir. |

---

## ⚖️ Kepatuhan Regulasi & Etika
- **Permenkes No. 16 Tahun 2019**: **Tidak ada pemblokiran otomatis**. Semua hasil deteksi bersifat rekomendasi audit untuk petugas manusia (*Human-in-the-loop*).
- **UU PDP No. 27 Tahun 2022**: Identitas peserta dilindungi menggunakan **Pseudonimisasi Hashing SHA-256**.
- **Audit-Ready**: Setiap aksi verifikator tercatat waktu, identitas, dan catatannya di log investigasi.
