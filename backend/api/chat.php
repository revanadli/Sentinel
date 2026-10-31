<?php
/**
 * POST /api/chat.php
 * Proxy ke Gemini API — mencegah API key terekspos di browser.
 *
 * Body JSON: { "message": "...", "history": [...] }
 * Response:  { "reply": "...", "model": "..." }
 */

require_once __DIR__ . '/../config.php';
cors();

if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    respond(['error' => 'POST only'], 405);
}

// ── Ambil API key: dari DB settings, lalu fallback ke config.php ──
$pdo = db();
$apiKeyRow = $pdo->query("SELECT `value` FROM settings WHERE `key` = 'gemini_api_key'")->fetch();
$apiKey    = ($apiKeyRow['value'] ?? '') ?: GEMINI_API_KEY_DEFAULT;

if (empty($apiKey)) {
    respond(['error' => 'Gemini API key belum dikonfigurasi. Masukkan di halaman Pengaturan.'], 400);
}

// ── Baca body request ──
$body = json_decode(file_get_contents('php://input'), true);
if (!is_array($body) || empty($body['message'])) {
    respond(['error' => 'Body JSON tidak valid. Butuh: { "message": "..." }'], 400);
}

$userMessage = substr(strip_tags($body['message']), 0, 8000);   // limit panjang input
$history     = is_array($body['history'] ?? null) ? $body['history'] : [];

// Sanitasi history — hanya ambil role & text
$safeHistory = [];
foreach (array_slice($history, -20) as $turn) {   // max 20 turn terakhir
    if (isset($turn['role'], $turn['parts'][0]['text'])) {
        $safeHistory[] = [
            'role'  => $turn['role'] === 'model' ? 'model' : 'user',
            'parts' => [['text' => substr($turn['parts'][0]['text'], 0, 4000)]],
        ];
    }
}

// ── Build system prompt ──
$statsRow = $pdo->query("
    SELECT COUNT(*) as total, SUM(label_sintetis) as fraud, SUM(total_biaya_tagih) as biaya
    FROM kartu_kasus
")->fetch();

$systemPrompt = <<<PROMPT
Kamu adalah Sentinel AI, asisten investigasi fraud klaim JKN (BPJS Kesehatan).

Konteks database saat ini:
- Total kasus terdeteksi: {$statsRow['total']}
- Fraud ground truth: {$statsRow['fraud']}
- Total biaya tagih: Rp {$statsRow['biaya']}

Metode deteksi: Rules (4 threshold) + IsolationForest (unsupervised ML)
Pola fraud: P1=Drug shopping, P2=Qty berlebihan, P3=Duplikasi layanan, P4=Identity fraud

Prinsip sistem:
- TIDAK ada blokir otomatis — semua keputusan di tangan verifikator manusia
- Output: "antrean kasus beralasan", bukan vonis
- Pseudonimisasi SHA-256 untuk proteksi identitas peserta
- Compliance: UU PDP 27/2022, Permenkes 16/2019

Jawab dalam Bahasa Indonesia. Singkat, spesifik, dan actionable.
Jika ditanya kasus spesifik, analisis pola dan rekomendasikan langkah verifikasi konkret.
PROMPT;

// ── Tambahkan pesan baru ke history ──
$contents = $safeHistory;
$contents[] = ['role' => 'user', 'parts' => [['text' => $userMessage]]];

// ── Call Gemini API ──
$model   = GEMINI_MODEL;
$url     = "https://generativelanguage.googleapis.com/v1beta/models/{$model}:generateContent?key={$apiKey}";
$payload = json_encode([
    'system_instruction' => ['parts' => [['text' => $systemPrompt]]],
    'contents'           => $contents,
    'generationConfig'   => [
        'temperature'     => 0.7,
        'topK'            => 40,
        'topP'            => 0.95,
        'maxOutputTokens' => 1024,
    ],
], JSON_UNESCAPED_UNICODE);

$ch = curl_init($url);
curl_setopt_array($ch, [
    CURLOPT_RETURNTRANSFER => true,
    CURLOPT_POST           => true,
    CURLOPT_POSTFIELDS     => $payload,
    CURLOPT_HTTPHEADER     => ['Content-Type: application/json'],
    CURLOPT_TIMEOUT        => 30,
    CURLOPT_SSL_VERIFYPEER => true,
]);

$raw  = curl_exec($ch);
$code = curl_getinfo($ch, CURLINFO_HTTP_CODE);
$err  = curl_error($ch);
curl_close($ch);

if ($err) {
    respond(['error' => "cURL error: $err"], 502);
}

$geminiResp = json_decode($raw, true);

if ($code !== 200) {
    $msg = $geminiResp['error']['message'] ?? "HTTP $code dari Gemini API";
    respond(['error' => $msg], 502);
}

$reply = $geminiResp['candidates'][0]['content']['parts'][0]['text'] ?? '(Tidak ada respons dari AI)';

// ── Log interaksi ke DB (opsional — untuk audit) ──
try {
    $pdo->prepare("
        INSERT INTO investigasi_log (kasus_id, action, catatan)
        VALUES (0, 'ai_chat', ?)
    ")->execute([substr($userMessage, 0, 500)]);
} catch (Exception $e) { /* non-fatal */ }

respond(['reply' => $reply, 'model' => $model]);

