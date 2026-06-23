@echo off
:: ═══════════════════════════════════════════════════════════
:: Ashfir — EXE Builder (İki Aşamalı Derleme)
:: ═══════════════════════════════════════════════════════════

title Ashfir Builder
set BASE_DIR=%~dp0
cd /d "%BASE_DIR%"

echo.
echo  Ashfir EXE Builder
echo  ═══════════════════════
echo.

:: Python Bulma Mantığı
set PY_CMD=
echo  [1/4] Python kontrol ediliyor...

py --version >nul 2>&1
if %ERRORLEVEL% equ 0 (
    set PY_CMD=py
) else (
    if exist "%LOCALAPPDATA%\Python\bin\python.exe" (
        "%LOCALAPPDATA%\Python\bin\python.exe" --version >nul 2>&1
        if %ERRORLEVEL% equ 0 set PY_CMD="%LOCALAPPDATA%\Python\bin\python.exe"
    )
)

if "%PY_CMD%"=="" (
    python --version >nul 2>&1
    if %ERRORLEVEL% equ 0 set PY_CMD=python
)

if "%PY_CMD%"=="" (
    echo  [HATA] Calisan bir Python bulunamadi!
    pause & exit /b 1
)

echo        Kullanilan: %PY_CMD%

:: Gerekli kütüphaneleri yükle
echo  [2/4] Bagimliliklar yukleniyor...
%PY_CMD% -m pip install watchdog groq requests certifi pycryptodome PyInstaller pyarmor --quiet --disable-pip-version-check
if %ERRORLEVEL% neq 0 ( echo  [HATA] Kutuphane yuklemesi basarisiz! & pause & exit /b 1 )

:: 1. AŞAMA: AGENT BUILD
echo  [3/4] Ashfir Agent derleniyor... (Sessiz mod)
cd /d "%BASE_DIR%..\agent"
%PY_CMD% convert_icon.py
%PY_CMD% -m PyInstaller ashfir_agent.spec --noconfirm --clean
if %ERRORLEVEL% neq 0 ( echo  [HATA] Agent derleme basarisiz! & pause & exit /b 1 )

:: cacert.pem kalmış olabilir, temizle (SSL bypass için gerekli)
echo  [3.1/4] Sertifika kalintilari temizleniyor...
del /s /q "dist\cacert.pem" >nul 2>&1
for /r "dist" %%f in (cacert.pem) do del /q "%%f" >nul 2>&1

:: 2. AŞAMA: SENKRONİZASYON
echo  [3.5/4] Dosyalar senkronize ediliyor (Agent -> Installer)...
cd /d "%BASE_DIR%"
%PY_CMD% sync_embedded.py
if %ERRORLEVEL% neq 0 ( echo  [HATA] Senkronizasyon basarisiz! & pause & exit /b 1 )

:: 3. AŞAMA: INSTALLER BUILD
echo  [4/4] Ashfir Setup derleniyor...
%PY_CMD% -m PyInstaller ashfir_setup.spec --distpath dist --workpath build --noconfirm --clean
if %ERRORLEVEL% neq 0 ( echo  [HATA] Installer derleme basarisiz! & pause & exit /b 1 )

echo.
echo  ═══════════════════════════════════════════
echo   ASHFIR hazır:
echo   dist\ashfir_setup.exe
echo  ═══════════════════════════════════════════
echo.
echo   Kurulum dosyasını kullanıcılara gönderebilirsiniz.
echo.
pause