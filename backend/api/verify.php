<?php
/**
 * POST /api/verify.php
 * Update status verifikasi kasus oleh investigator.
 *
 * Body JSON:
 * {
 *   "id": 123,
 *   "status": "verified_fraud|cleared|in_review|escalated",
 *   "catatan": "Keterangan verifikator",
 *   "user_name": "dr. Budi"
 * }
 */

require_once __DIR__ . '/../config.php';
cors();

if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    respond(['error' => 'POST only'], 405);
}

$body = json_decode(file_get_contents('php://input'), true);
if (!is_array($body) || empty($body['id'])) {
    respond(['error' => 'Body JSON tidak valid. Butuh: { "id": N, "status": "..." }'], 400);
}

$allowed_status = ['pending', 'in_review', 'verified_fraud', 'cleared', 'escalated'];
$newStatus = $body['status'] ?? '';
if (!in_array($newStatus, $allowed_status, true)) {
    respond(['error' => 'Status tidak valid. Pilih: ' . implode(', ', $allowed_status)], 422);
}

$pdo = db();

// Ambil kasus dan status lama
$kasus = $pdo->prepare("SELECT id, status FROM kartu_kasus WHERE id = :id");
$kasus->execute([':id' => (int)$body['id']]);
$row = $kasus->fetch();

if (!$row) {
    respond(['error' => "Kasus ID {$body['id']} tidak ditemukan"], 404);
}

$oldStatus = $row['status'];
$userName  = substr(trim($body['user_name'] ?? 'anonim'), 0, 80);
$catatan   = substr(trim($body['catatan']   ?? ''), 0, 5000);

// Update kasus
$pdo->prepare("
    UPDATE kartu_kasus
    SET status             = :status,
        catatan_verif      = :catatan,
        diverifikasi_oleh  = :user,
        diverifikasi_at    = NOW()
    WHERE id = :id
")->execute([
    ':status'  => $newStatus,
    ':catatan' => $catatan,
    ':user'    => $userName,
    ':id'      => (int)$body['id'],
]);

// Catat ke audit log
$pdo->prepare("
    INSERT INTO investigasi_log (kasus_id, action, old_status, new_status, user_name, catatan)
    VALUES (:kid, 'status_update', :old, :new, :user, :catatan)
")->execute([
    ':kid'     => (int)$body['id'],
    ':old'     => $oldStatus,
    ':new'     => $newStatus,
    ':user'    => $userName,
    ':catatan' => $catatan,
]);

respond([
    'success'    => true,
    'id'         => (int)$body['id'],
    'old_status' => $oldStatus,
    'new_status' => $newStatus,
]);

