<?php
/**
 * GET /api/cases.php
 * Ambil daftar kartu kasus dengan filter & paginasi.
 *
 * Query params:
 *   page      int   (default 1)
 *   per_page  int   (default 20, max 100)
 *   tipe      str   P1|P2|P3|P4|'' 
 *   status    str   pending|in_review|verified_fraud|cleared|escalated
 *   label     int   0|1
 *   q         str   search text (id_pseudonim, kode_obat, diagnosis, provinsi)
 *   sort      str   skor|jumlah_kunjungan|total_biaya_tagih (default: skor)
 *   order     str   desc|asc (default: desc)
 */

require_once __DIR__ . '/../config.php';
cors();

if ($_SERVER['REQUEST_METHOD'] !== 'GET') {
    respond(['error' => 'Method not allowed'], 405);
}

$page     = max(1, (int)($_GET['page']     ?? 1));
$per_page = min(100, max(1, (int)($_GET['per_page'] ?? 20)));
$offset   = ($page - 1) * $per_page;

$allowed_sort  = ['skor', 'jumlah_kunjungan', 'total_biaya_tagih', 'imported_at'];
$allowed_order = ['desc', 'asc'];

$sort  = in_array($_GET['sort']  ?? '', $allowed_sort,  true) ? $_GET['sort']  : 'skor';
$order = in_array(strtolower($_GET['order'] ?? ''), $allowed_order, true) ? strtolower($_GET['order']) : 'desc';

// Build WHERE clause
$where  = ['1=1'];
$params = [];

if (!empty($_GET['tipe'])) {
    $where[]    = 'tipe_fraud = :tipe';
    $params[':tipe'] = $_GET['tipe'];
}
if (isset($_GET['status']) && $_GET['status'] !== '') {
    $where[]    = 'status = :status';
    $params[':status'] = $_GET['status'];
}
if (isset($_GET['label']) && $_GET['label'] !== '') {
    $where[]    = 'label_sintetis = :label';
    $params[':label'] = (int)$_GET['label'];
}
if (!empty($_GET['q'])) {
    $q = '%' . $_GET['q'] . '%';
    $where[]    = '(id_pseudonim LIKE :q1 OR kode_obat_fkl44 LIKE :q2 OR kode_diagnosis LIKE :q3 OR provinsi_terlibat LIKE :q4 OR jenis_dugaan LIKE :q5)';
    $params[':q1'] = $q; $params[':q2'] = $q; $params[':q3'] = $q;
    $params[':q4'] = $q; $params[':q5'] = $q;
}

$whereSql = implode(' AND ', $where);

$pdo = db();

// Total count
$countSql  = "SELECT COUNT(*) FROM kartu_kasus WHERE $whereSql";
$countStmt = $pdo->prepare($countSql);
$countStmt->execute($params);
$total = (int)$countStmt->fetchColumn();

// Data
$dataSql  = "SELECT id, id_pseudonim, jenis_dugaan, tipe_fraud, waktu_kejadian,
                    provinsi_terlibat, kode_obat_fkl44, kode_diagnosis,
                    jumlah_kunjungan, total_biaya_tagih, skor,
                    label_sintetis, status, diverifikasi_at
             FROM kartu_kasus
             WHERE $whereSql
             ORDER BY $sort $order
             LIMIT :limit OFFSET :offset";

$stmt = $pdo->prepare($dataSql);
foreach ($params as $k => $v) {
    $stmt->bindValue($k, $v);
}
$stmt->bindValue(':limit',  $per_page, PDO::PARAM_INT);
$stmt->bindValue(':offset', $offset,   PDO::PARAM_INT);
$stmt->execute();
$rows = $stmt->fetchAll();

// Cast numeric types
foreach ($rows as &$r) {
    $r['jumlah_kunjungan']  = (int)$r['jumlah_kunjungan'];
    $r['total_biaya_tagih'] = (int)$r['total_biaya_tagih'];
    $r['skor']              = (float)$r['skor'];
    $r['label_sintetis']    = (int)$r['label_sintetis'];
}

respond([
    'data'       => $rows,
    'total'      => $total,
    'page'       => $page,
    'per_page'   => $per_page,
    'total_pages'=> (int)ceil($total / $per_page),
]);

