<?php
/**
 * POST /api/import.php
 * Import kartu_kasus.csv ke database MySQL.
 * Bisa dipanggil via form upload browser atau dari CLI.
 *
 * Body: multipart/form-data dengan field "csv_file" (file upload)
 * ATAU: POST dengan field "use_default=1" → pakai kartu_kasus.csv di root project
 *
 * Response: { "imported": N, "skipped": M, "errors": [...] }
 */

require_once __DIR__ . '/../config.php';
cors();

if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    respond(['error' => 'POST only'], 405);
}

// ── Tentukan sumber CSV ──
$csvPath = null;

if (!empty($_POST['use_default'])) {
    // Pakai file default di root project (relative to XAMPP htdocs/sentinel/)
    $root    = realpath(__DIR__ . '/../../');
    $csvPath = $root . DIRECTORY_SEPARATOR . 'kartu_kasus.csv';
    if (!file_exists($csvPath)) {
        respond(['error' => "kartu_kasus.csv tidak ditemukan di: $csvPath"], 404);
    }
} elseif (isset($_FILES['csv_file']) && $_FILES['csv_file']['error'] === UPLOAD_ERR_OK) {
    $csvPath = $_FILES['csv_file']['tmp_name'];
} else {
    respond(['error' => 'Kirim file via csv_file atau gunakan use_default=1'], 400);
}

// ── Baca CSV ──
$handle = fopen($csvPath, 'r');
if (!$handle) respond(['error' => 'Gagal membaca CSV'], 500);

$header  = fgetcsv($handle);   // baris pertama = header
$header  = array_map('trim', $header);

// Kolom yang dibutuhkan
$required = ['id_pseudonim', 'jenis_dugaan', 'tipe_fraud', 'waktu_kejadian',
             'jumlah_kunjungan', 'total_biaya_tagih', 'skor', 'label_sintetis'];
$missing  = array_diff($required, $header);
if ($missing) {
    respond(['error' => 'Kolom wajib tidak ada: ' . implode(', ', $missing)], 422);
}

// ── Siapkan prepared statement ──
$pdo  = db();
$stmt = $pdo->prepare("
    INSERT INTO kartu_kasus
        (id_pseudonim, jenis_dugaan, tipe_fraud, waktu_kejadian,
         provinsi_terlibat, faskes_terlibat, kode_obat_fkl44, kode_diagnosis,
         tgl_terima_obat, jumlah_kunjungan, total_biaya_tagih, skor, label_sintetis)
    VALUES
        (:id_pseudonim, :jenis_dugaan, :tipe_fraud, :waktu_kejadian,
         :provinsi_terlibat, :faskes_terlibat, :kode_obat_fkl44, :kode_diagnosis,
         :tgl_terima_obat, :jumlah_kunjungan, :total_biaya_tagih, :skor, :label_sintetis)
    ON DUPLICATE KEY UPDATE
        skor              = VALUES(skor),
        tipe_fraud        = VALUES(tipe_fraud),
        total_biaya_tagih = VALUES(total_biaya_tagih),
        jumlah_kunjungan  = VALUES(jumlah_kunjungan)
");

// ── Catat model run ──
$statsRow = $pdo->query("SELECT COUNT(*) as c FROM kartu_kasus")->fetch();
$prevCount = (int)$statsRow['c'];

$imported = 0;
$skipped  = 0;
$errors   = [];
$rowNum   = 1;

while (($row = fgetcsv($handle)) !== false) {
    $rowNum++;
    if (count($row) < count($required)) { $skipped++; continue; }

    $data = array_combine($header, $row);
    if (!$data) { $skipped++; continue; }

    // Validasi & sanitasi
    $id_pseudo = substr(trim($data['id_pseudonim'] ?? ''), 0, 64);
    if (empty($id_pseudo)) { $errors[] = "Baris $rowNum: id_pseudonim kosong"; $skipped++; continue; }

    try {
        $stmt->execute([
            ':id_pseudonim'     => $id_pseudo,
            ':jenis_dugaan'     => substr(trim($data['jenis_dugaan']    ?? ''), 0, 120),
            ':tipe_fraud'       => substr(trim($data['tipe_fraud']      ?? ''), 0, 2),
            ':waktu_kejadian'   => substr(trim($data['waktu_kejadian']  ?? ''), 0, 30),
            ':provinsi_terlibat'=> substr(trim($data['provinsi_terlibat'] ?? ''), 0, 100),
            ':faskes_terlibat'  => trim($data['faskes_terlibat']   ?? ''),
            ':kode_obat_fkl44'  => substr(trim($data['kode_obat_fkl44'] ?? ''), 0, 200),
            ':kode_diagnosis'   => substr(trim($data['kode_diagnosis']  ?? ''), 0, 200),
            ':tgl_terima_obat'  => substr(trim($data['tgl_terima_obat'] ?? ''), 0, 200),
            ':jumlah_kunjungan' => max(0, (int)($data['jumlah_kunjungan'] ?? 0)),
            ':total_biaya_tagih'=> max(0, (int)($data['total_biaya_tagih'] ?? 0)),
            ':skor'             => round((float)($data['skor'] ?? 0), 4),
            ':label_sintetis'   => (int)(bool)($data['label_sintetis'] ?? 0),
        ]);
        $imported++;
    } catch (PDOException $e) {
        $errors[] = "Baris $rowNum: " . $e->getMessage();
        $skipped++;
    }
}
fclose($handle);

// ── Catat model_run ──
$newStats = $pdo->query("
    SELECT COUNT(*) as total, SUM(label_sintetis) as fraud FROM kartu_kasus
")->fetch();

$pdo->prepare("
    INSERT INTO model_run (n_fraud, notes)
    VALUES (:fraud, :notes)
")->execute([
    ':fraud' => (int)($newStats['fraud'] ?? 0),
    ':notes' => "Import dari CSV: $imported baris imported, $skipped dilewati",
]);

respond([
    'imported' => $imported,
    'skipped'  => $skipped,
    'errors'   => array_slice($errors, 0, 20),   // max 20 error messages
    'total_db' => (int)$newStats['total'],
]);

