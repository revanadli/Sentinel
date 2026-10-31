<?php
/**
 * JKN Sentinel — Database & App Config
 * Membaca dari backend/.env (tidak masuk git).
 * Fallback ke default XAMPP jika .env tidak ada.
 *
 * PRODUKSI: Gunakan environment variable OS, bukan .env file.
 */

// ── Load .env ──
$envFile = __DIR__ . '/.env';
if (file_exists($envFile)) {
    foreach (file($envFile, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES) as $line) {
        if (str_starts_with(trim($line), '#') || !str_contains($line, '=')) continue;
        [$key, $val] = explode('=', $line, 2);
        $key = trim($key); $val = trim($val);
        if (!empty($key) && !isset($_ENV[$key])) {
            $_ENV[$key] = $val;
            putenv("$key=$val");
        }
    }
}

function env(string $key, string $default = ''): string {
    return $_ENV[$key] ?? getenv($key) ?: $default;
}

// ── Database ──
define('DB_HOST',    env('DB_HOST',    'localhost'));
define('DB_PORT',    env('DB_PORT',    '3306'));
define('DB_NAME',    env('DB_NAME',    'sentinel_db'));
define('DB_USER',    env('DB_USER',    'root'));
define('DB_PASS',    env('DB_PASS',    ''));
define('DB_CHARSET', 'utf8mb4');

// ── Gemini ──
define('GEMINI_API_KEY_DEFAULT', env('GEMINI_API_KEY', ''));
define('GEMINI_MODEL',           env('GEMINI_MODEL',   'gemini-2.0-flash-exp'));

// ── App ──
define('APP_ENV',   env('APP_ENV',   'local'));
define('APP_DEBUG', env('APP_DEBUG', 'true') === 'true');

/**
 * Singleton PDO connection.
 */
function db(): PDO {
    static $pdo = null;
    if ($pdo !== null) return $pdo;

    $dsn = sprintf('mysql:host=%s;port=%s;dbname=%s;charset=%s',
        DB_HOST, DB_PORT, DB_NAME, DB_CHARSET);
    try {
        $pdo = new PDO($dsn, DB_USER, DB_PASS, [
            PDO::ATTR_ERRMODE            => PDO::ERRMODE_EXCEPTION,
            PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
            PDO::ATTR_EMULATE_PREPARES   => false,
        ]);
    } catch (PDOException $e) {
        $hint = APP_DEBUG
            ? ' | ' . $e->getMessage()
            : ' Pastikan MySQL XAMPP aktif dan database sentinel_db sudah di-import.';
        http_response_code(503);
        header('Content-Type: application/json; charset=utf-8');
        die(json_encode(['error' => 'Database tidak bisa diakses.' . $hint]));
    }
    return $pdo;
}

/**
 * Respond JSON dan exit.
 */
function respond(array $data, int $code = 200): void {
    http_response_code($code);
    header('Content-Type: application/json; charset=utf-8');
    echo json_encode($data, JSON_UNESCAPED_UNICODE | JSON_PRETTY_PRINT);
    exit;
}

/**
 * CORS — localhost only (dev). Di produksi: ganti dengan origin spesifik.
 */
function cors(): void {
    $origin = $_SERVER['HTTP_ORIGIN'] ?? '';
    $allowed = ['http://localhost', 'http://127.0.0.1'];
    foreach ($allowed as $a) {
        if (str_starts_with($origin, $a)) {
            header("Access-Control-Allow-Origin: $origin");
            header('Access-Control-Allow-Methods: GET, POST, OPTIONS');
            header('Access-Control-Allow-Headers: Content-Type, X-Requested-With');
            break;
        }
    }
    if ($_SERVER['REQUEST_METHOD'] === 'OPTIONS') { http_response_code(204); exit; }
}
