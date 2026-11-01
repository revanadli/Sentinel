-- ═══════════════════════════════════════════════════════════════
-- JKN Sentinel — MySQL Schema
-- Database: sentinel_db
-- Import via: phpMyAdmin atau mysql -u root -p sentinel_db < schema.sql
-- ═══════════════════════════════════════════════════════════════

CREATE DATABASE IF NOT EXISTS sentinel_db
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE sentinel_db;

-- ─────────────────────────────────────────────────────────────
-- TABEL: kartu_kasus
-- Hasil deteksi dari sentinel_prototype.py
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS kartu_kasus (
  id               INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  id_pseudonim     VARCHAR(64)  NOT NULL UNIQUE COMMENT 'SHA-256 + salt, 16 hex char',
  jenis_dugaan     VARCHAR(120) NOT NULL,
  peringkat        INT UNSIGNED NOT NULL DEFAULT 0,
  prioritas        VARCHAR(10)  NOT NULL DEFAULT 'Sedang' COMMENT 'Segera/Tinggi/Sedang',
  pola_terdeteksi  VARCHAR(2)   NOT NULL DEFAULT '' COMMENT 'P1/P2/P3/P4/AN — dari rule yang menyala',
  tipe_fraud       CHAR(2)      NOT NULL DEFAULT '' COMMENT 'Ground truth sintetis (hanya demo)',
  waktu_kejadian   VARCHAR(30)  NOT NULL,
  provinsi_terlibat VARCHAR(100),
  faskes_terlibat  TEXT,
  kode_obat_fkl44  VARCHAR(200) COMMENT 'Kode special drugs BPJS (FKL44)',
  kode_diagnosis   VARCHAR(200) COMMENT 'Kode ICD-10 (FKP15/FKL18)',
  tgl_terima_obat  VARCHAR(200) COMMENT 'FKL04 — tanggal pulang kunjungan FKRTL',
  jumlah_kunjungan SMALLINT UNSIGNED DEFAULT 0,
  total_biaya_tagih BIGINT UNSIGNED DEFAULT 0 COMMENT 'FKL47 dalam rupiah',
  potensi_kerugian  BIGINT UNSIGNED DEFAULT 0 COMMENT 'Estimasi, bukan kerugian terbukti',
  n_faskes_30d      DECIMAL(8,3) DEFAULT 0,
  qty_ratio         DECIMAL(8,3) DEFAULT 0,
  gap_days          DECIMAL(8,3) DEFAULT 0,
  repeat_svc_60d    DECIMAL(8,3) DEFAULT 0,
  dx_norm_z         DECIMAL(8,3) DEFAULT 0,
  geo_time_conflict DECIMAL(8,3) DEFAULT 0,
  use_vs_self       DECIMAL(8,3) DEFAULT 0,
  skor             DECIMAL(8,4) DEFAULT 0 COMMENT 'Skor fairness-adjusted',
  label_sintetis   TINYINT(1)   DEFAULT 0 COMMENT '1=fraud (ground truth sintetis)',

  alasan_flag      VARCHAR(500) COMMENT 'Penjelasan rule yang terpicu per kasus',
  role_target      ENUM('Apoteker','Dokter','Verifikator') DEFAULT 'Verifikator',
  -- Status investigasi (diisi oleh verifikator manusia)
  status           ENUM('pending','in_review','verified_fraud','cleared','escalated')
                   DEFAULT 'pending',
  catatan_verif    TEXT,
  diverifikasi_oleh VARCHAR(80),
  diverifikasi_at  DATETIME,
  imported_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_tipe   (pola_terdeteksi),
  INDEX idx_skor   (skor DESC),
  INDEX idx_status (status),
  INDEX idx_label  (label_sintetis)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ─────────────────────────────────────────────────────────────
-- TABEL: model_run
-- Riwayat setiap kali Python script dijalankan
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS model_run (
  id            INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  run_at        DATETIME DEFAULT CURRENT_TIMESTAMP,
  n_peserta     INT UNSIGNED,
  n_fraud       INT UNSIGNED,
  n_decoy       INT UNSIGNED,
  n_fktp        INT UNSIGNED,
  n_fkrtl       INT UNSIGNED,
  precision_100 DECIMAL(5,4),
  recall_all    DECIMAL(5,4),
  notes         TEXT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ─────────────────────────────────────────────────────────────
-- TABEL: investigasi_log
-- Jejak audit setiap tindakan verifikator
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS investigasi_log (
  id           INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  kasus_id     INT UNSIGNED NOT NULL,
  action       VARCHAR(60)  NOT NULL,
  old_status   VARCHAR(30),
  new_status   VARCHAR(30),
  user_name    VARCHAR(80),
  catatan      TEXT,
  created_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (kasus_id) REFERENCES kartu_kasus(id) ON DELETE CASCADE,
  INDEX idx_kasus (kasus_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ─────────────────────────────────────────────────────────────
-- TABEL: settings
-- Konfigurasi sistem (threshold, Gemini API key)
-- API key JANGAN disimpan di DB produksi — gunakan env var
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS settings (
  `key`    VARCHAR(60) PRIMARY KEY,
  `value`  TEXT,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Default settings
INSERT IGNORE INTO settings (`key`, `value`) VALUES

  ('gemini_model',      'gemini-3.5-flash'),
  ('app_version',       '1.0.0-healthkathon2026');

