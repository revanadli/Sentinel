@echo off
:: ═══════════════════════════════════════════════════════════════
:: JKN Sentinel — Setup Script untuk XAMPP (Windows)
:: Jalankan sebagai Administrator jika perlu
:: ═══════════════════════════════════════════════════════════════

title JKN Sentinel Setup

echo.
echo  ========================================
echo    JKN Sentinel - XAMPP Setup Script
echo  ========================================
echo.

:: ── Cek XAMPP terinstall ──
set XAMPP=C:\xampp
if not exist "%XAMPP%\mysql\bin\mysql.exe" (
    echo [ERROR] XAMPP tidak ditemukan di %XAMPP%
    echo         Install dulu dari https://www.apachefriends.org
    pause
    exit /b 1
)

:: ── Cek project folder ──
set PROJECT=%~dp0
echo [INFO] Project folder: %PROJECT%

:: ── Copy ke htdocs ──
set DEST=%XAMPP%\htdocs\sentinel
echo.
echo [STEP 1] Menyalin project ke htdocs\sentinel ...

if exist "%DEST%" (
    echo [WARN] Folder %DEST% sudah ada. Akan di-overwrite.
)

xcopy /E /I /Y "%PROJECT%." "%DEST%\" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Gagal copy ke htdocs. Coba jalankan sebagai Administrator.
    pause
    exit /b 1
)
echo [OK] Project disalin ke %DEST%

:: ── Buat database ──
echo.
echo [STEP 2] Membuat database sentinel_db ...

set MYSQL=%XAMPP%\mysql\bin\mysql.exe

:: Coba tanpa password dulu (default XAMPP)
"%MYSQL%" -u root -e "CREATE DATABASE IF NOT EXISTS sentinel_db CHARACTER SET utf8mb4;" 2>nul
if errorlevel 1 (
    echo [WARN] Mencoba dengan prompt password...
    "%MYSQL%" -u root -p -e "CREATE DATABASE IF NOT EXISTS sentinel_db CHARACTER SET utf8mb4;"
    if errorlevel 1 (
        echo [ERROR] Gagal membuat database. Pastikan MySQL XAMPP berjalan.
        pause
        exit /b 1
    )
)
echo [OK] Database sentinel_db siap

:: ── Import schema ──
echo.
echo [STEP 3] Import schema SQL ...

"%MYSQL%" -u root sentinel_db < "%DEST%\backend\schema.sql" 2>nul
if errorlevel 1 (
    "%MYSQL%" -u root -p sentinel_db < "%DEST%\backend\schema.sql"
)
echo [OK] Schema berhasil di-import

:: ── Jalankan Python script untuk generate data ──
echo.
echo [STEP 4] Menjalankan sentinel_prototype.py ...

where python >nul 2>&1
if errorlevel 1 (
    echo [WARN] Python tidak ditemukan di PATH. Skip step ini.
    echo        Jalankan manual: python "%DEST%\sentinel_prototype.py"
) else (
    cd /d "%DEST%"
    python sentinel_prototype.py
    echo [OK] Data sintetis berhasil digenerate
)

:: ── Import CSV ke DB ──
echo.
echo [STEP 5] Import kartu_kasus.csv ke database ...

curl -s -X POST "http://localhost/sentinel/backend/api/import.php" ^
     -d "use_default=1" >nul 2>&1

if errorlevel 1 (
    echo [WARN] Gagal import via API. Pastikan Apache XAMPP sudah jalan.
    echo        Import manual via: http://localhost/phpmyadmin
) else (
    echo [OK] Data berhasil diimport ke database
)

:: ── Selesai ──
echo.
echo  ========================================
echo    Setup Selesai!
echo  ========================================
echo.
echo  Buka dashboard di browser:
echo    http://localhost/sentinel/dashboard/
echo.
echo  phpMyAdmin:
echo    http://localhost/phpmyadmin
echo.
echo  Catatan:
echo    - Masukkan Gemini API Key di Settings dashboard
echo    - API Key gratis di: https://aistudio.google.com
echo.
pause

