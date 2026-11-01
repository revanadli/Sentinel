<?php
// POST /api/import.php
// Import kartu_kasus.csv ke database MySQL.
// Body: multipart/form-data dengan field csv_file (upload)
//   ATAU field use_default=1 -> pakai kartu_kasus.csv di root project.
// Status verifikasi yang sudah diisi petugas TIDAK ditimpa saat re-import.

require_once __DIR__ . '/../config.php';
cors();

if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    respond(['error' => 'POST only'], 405);
}

$csvPath = null;
if (!empty($_POST['use_default'])) {
    $csvPath = realpath(__DIR__ . '/../../') . DIRECTORY_SEPARATOR . 'kartu_kasus.csv';
    if (!file_exists($csvPath)) {
        respond(['error' => "kartu_kasus.csv tidak ditemukan di: $csvPath"], 404);
    }
} elseif (isset($_FILES['csv_file']) && $_FILES['csv_file']['error'] === UPLOAD_ERR_OK) {
    $csvPath = $_FILES['csv_file']['tmp_name'];
} else {
    respond(['error' => 'Kirim file via csv_file atau gunakan use_default=1'], 400);
}

$handle = fopen($csvPath, 'r');
if (!$handle) respond(['error' => 'Gagal membaca CSV'], 500);

$header = array_map(fn($h) => trim($h, " \t\n\r\0\x0B\xEF\xBB\xBF"), fgetcsv($handle));

$required = ['id_pseudonim', 'jenis_dugaan', 'pola_terdeteksi', 'role_target',
             'waktu_kejadian', 'jumlah_kunjungan', 'total_biaya_tagih', 'skor'];
$missing = array_diff($required, $header);
if ($missing) {
    respond(['error' => 'Kolom wajib tidak ada: ' . implode(', ', $missing)], 422);
}

$cols = ['id_pseudonim', 'peringkat', 'prioritas', 'pola_terdeteksi', 'jenis_dugaan', 'role_target',
         'waktu_kejadian', 'provinsi_terlibat', 'faskes_terlibat', 'kode_obat_fkl44', 'kode_diagnosis',
         'tgl_terima_obat', 'jumlah_kunjungan', 'total_biaya_tagih', 'potensi_kerugian', 'skor',
         'alasan_flag', 'n_faskes_30d', 'qty_ratio', 'gap_days', 'repeat_svc_60d', 'dx_norm_z',
         'geo_time_conflict', 'use_vs_self', 'label_sintetis', 'tipe_fraud'];
$updatable = array_diff($cols, ['id_pseudonim']);

$sql = 'INSERT INTO kartu_kasus (' . implode(',', $cols) . ') VALUES (:' . implode(',:', $cols) . ') '
     . 'ON DUPLICATE KEY UPDATE ' . implode(',', array_map(fn($c) => "$c = VALUES($c)", $updatable));

$pdo  = db();
$stmt = $pdo->prepare($sql);

$ints  = ['peringkat', 'jumlah_kunjungan', 'total_biaya_tagih', 'potensi_kerugian', 'label_sintetis'];
$reals = ['skor', 'n_faskes_30d', 'qty_ratio', 'gap_days', 'repeat_svc_60d', 'dx_norm_z',
          'geo_time_conflict', 'use_vs_self'];
$roles = ['Apoteker', 'Dokter', 'Verifikator'];

$imported = 0; $skipped = 0; $errors = []; $rowNum = 1;

while (($row = fgetcsv($handle)) !== false) {
    $rowNum++;
    if (count($row) !== count($header)) { $skipped++; continue; }
    $data = array_combine($header, $row);

    $id = substr(trim($data['id_pseudonim'] ?? ''), 0, 64);
    if ($id === '') { $errors[] = "Baris $rowNum: id_pseudonim kosong"; $skipped++; continue; }

    $params = [];
    foreach ($cols as $c) {
        $v = trim($data[$c] ?? '');
        if (in_array($c, $ints, true))       $v = max(0, (int)$v);
        elseif (in_array($c, $reals, true))  $v = (float)$v;
        elseif ($c === 'role_target')        $v = in_array($v, $roles, true) ? $v : 'Verifikator';
        elseif ($c === 'pola_terdeteksi' || $c === 'tipe_fraud') $v = substr($v, 0, 2);
        $params[':' . $c] = $v;
    }
    $params[':id_pseudonim'] = $id;

    try {
        $stmt->execute($params);
        $imported++;
    } catch (PDOException $e) {
        $errors[] = "Baris $rowNum: " . $e->getMessage();
        $skipped++;
    }
}
fclose($handle);

$total = (int)$pdo->query('SELECT COUNT(*) FROM kartu_kasus')->fetchColumn();

$pdo->prepare('INSERT INTO model_run (n_fraud, notes) VALUES (:f, :n)')->execute([
    ':f' => (int)$pdo->query('SELECT COALESCE(SUM(label_sintetis),0) FROM kartu_kasus')->fetchColumn(),
    ':n' => "Import CSV: $imported baris, $skipped dilewati",
]);

respond([
    'imported' => $imported,
    'skipped'  => $skipped,
    'errors'   => array_slice($errors, 0, 20),
    'total_db' => $total,
]);
