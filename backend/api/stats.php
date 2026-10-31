<?php
/**
 * GET /api/stats.php
 * Statistik ringkasan untuk dashboard overview & model section.
 */

require_once __DIR__ . '/../config.php';
cors();

if ($_SERVER['REQUEST_METHOD'] !== 'GET') {
    respond(['error' => 'Method not allowed'], 405);
}

$pdo = db();

// ── Hitung dari tabel kartu_kasus ──
$summary = $pdo->query("
    SELECT
        COUNT(*)                                          AS total_kasus,
        SUM(label_sintetis)                               AS total_fraud_gt,
        SUM(potensi_kerugian)                             AS total_potensi,
        SUM(CASE WHEN pola_terdeteksi = 'P1' THEN 1 ELSE 0 END) AS p1,
        SUM(CASE WHEN pola_terdeteksi = 'P2' THEN 1 ELSE 0 END) AS p2,
        SUM(CASE WHEN pola_terdeteksi = 'P3' THEN 1 ELSE 0 END) AS p3,
        SUM(CASE WHEN pola_terdeteksi = 'P4' THEN 1 ELSE 0 END) AS p4,
        SUM(total_biaya_tagih)                            AS total_biaya,
        AVG(skor)                                         AS avg_skor,
        MAX(skor)                                         AS max_skor,
        SUM(CASE WHEN status = 'pending'         THEN 1 ELSE 0 END) AS status_pending,
        SUM(CASE WHEN status = 'in_review'       THEN 1 ELSE 0 END) AS status_review,
        SUM(CASE WHEN status = 'verified_fraud'  THEN 1 ELSE 0 END) AS status_verified,
        SUM(CASE WHEN status = 'cleared'         THEN 1 ELSE 0 END) AS status_cleared,
        SUM(CASE WHEN status = 'escalated'       THEN 1 ELSE 0 END) AS status_escalated
    FROM kartu_kasus
")->fetch();

// ── Provinsi breakdown ──
$provRows = $pdo->query("
    SELECT provinsi_terlibat, COUNT(*) as cnt
    FROM kartu_kasus
    GROUP BY provinsi_terlibat
    ORDER BY cnt DESC
    LIMIT 20
")->fetchAll();

// ── Timeline: group by waktu_kejadian bucket ──
$timeRows = $pdo->query("
    SELECT
        CAST(SUBSTRING_INDEX(REPLACE(waktu_kejadian, 'hari ', ''), '-', 1) AS UNSIGNED) AS day_start,
        COUNT(*) AS cnt
    FROM kartu_kasus
    GROUP BY day_start
    ORDER BY day_start
")->fetchAll();

// ── Model run terbaru ──
$lastRun = $pdo->query("SELECT * FROM model_run ORDER BY run_at DESC LIMIT 1")->fetch();

// ── Settings ──
$settingsRaw = $pdo->query("SELECT `key`, `value` FROM settings")->fetchAll();
$settings = [];
foreach ($settingsRaw as $s) $settings[$s['key']] = $s['value'];

// ── Cast ──
$cast = function($v) { return $v !== null ? (int)$v : 0; };
foreach (['total_kasus','total_fraud_gt','p1','p2','p3','p4',
          'status_pending','status_review','status_verified','status_cleared','status_escalated'] as $k) {
    $summary[$k] = $cast($summary[$k]);
}
$summary['total_potensi'] = $summary['total_potensi'] ? (int)$summary['total_potensi'] : 0;
$summary['total_biaya'] = $summary['total_biaya'] ? (int)$summary['total_biaya'] : 0;
$summary['avg_skor']    = round((float)($summary['avg_skor'] ?? 0), 4);
$summary['max_skor']    = round((float)($summary['max_skor'] ?? 0), 4);

respond([
    'summary'   => $summary,
    'provinsi'  => $provRows,
    'timeline'  => $timeRows,
    'last_run'  => $lastRun ?: null,
    'settings'  => $settings,
]);

