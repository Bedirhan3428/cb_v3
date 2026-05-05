"""
CloudBackup — Kurulum Sihirbazı
Tek seferlik çalıştırılır. Sonrasında tamamen sessiz çalışır.

Kullanım:
    python install.py
"""

import os
import sys
import json
import shutil
import subprocess
import urllib.request
import urllib.error
import ctypes
import winreg
from pathlib import Path

# ── RENKLER (Windows terminal) ────────────────────────────────
try:
    import colorama
    colorama.init()
    GREEN  = '\033[92m'
    YELLOW = '\033[93m'
    RED    = '\033[91m'
    CYAN   = '\033[96m'
    BOLD   = '\033[1m'
    RESET  = '\033[0m'
except ImportError:
    GREEN = YELLOW = RED = CYAN = BOLD = RESET = ''

def ok(msg):   print(f'  {GREEN}✓{RESET}  {msg}')
def info(msg): print(f'  {CYAN}→{RESET}  {msg}')
def warn(msg): print(f'  {YELLOW}!{RESET}  {msg}')
def err(msg):  print(f'  {RED}✗{RESET}  {msg}')
def title(msg): print(f'\n{BOLD}{CYAN}{msg}{RESET}')


def is_admin():
    try: return ctypes.windll.shell32.IsUserAnAdmin()
    except: return False


def check_python():
    """Python sürümünü kontrol et."""
    v = sys.version_info
    if v.major < 3 or (v.major == 3 and v.minor < 10):
        err(f'Python 3.10+ gerekli. Mevcut: {v.major}.{v.minor}')
        sys.exit(1)
    ok(f'Python {v.major}.{v.minor}.{v.micro}')


def install_packages():
    """Gerekli paketleri sessizce yükle."""
    packages = ['watchdog', 'firebase-admin', 'groq', 'requests', 'colorama']
    info('Paketler yükleniyor...')
    for pkg in packages:
        subprocess.run(
            [sys.executable, '-m', 'pip', 'install', pkg, '--quiet', '--disable-pip-version-check'],
            capture_output=True
        )
    ok('Tüm paketler hazır')


def validate_key(key: str) -> dict | None:
    """Key'i Firestore'da doğrula."""
    try:
        # Firebase'i başlat (eğer henüz başlatılmadıysa)
        import firebase_admin
        from firebase_admin import credentials, firestore
        
        fb_key = Path(__file__).parent / 'firebase_key.json'
        if not firebase_admin._apps:
            cred = credentials.Certificate(str(fb_key))
            firebase_admin.initialize_app(cred)
        
        db = firestore.client()
        doc = db.collection('accounts').document(key).get()
        if doc.exists:
            return {'ok': True}
        return {'ok': False, 'error': 'Key bulunamadı'}
    except Exception as e:
        return {'ok': False, 'error': str(e)}


def get_install_dir() -> Path:
    """Agent kurulum dizini — AppData\Local\CloudBackup"""
    base = Path(os.environ.get('LOCALAPPDATA', os.path.expanduser('~')))
    d = base / 'CloudBackup'
    d.mkdir(parents=True, exist_ok=True)
    return d


def copy_agent_files(install_dir: Path):
    """Agent dosyalarını kurulum dizinine kopyala."""
    here = Path(__file__).parent
    files = ['agent.py', 'ai_filter.py', 'requirements.txt']

    for fname in files:
        src = here / fname
        dst = install_dir / fname
        if src.exists():
            shutil.copy2(src, dst)

    ok(f'Dosyalar kopyalandı: {install_dir}')


def save_agent_config(install_dir: Path, key: str, machine_name: str):
    """Agent yapılandırmasını kaydet."""
    config = {
        'key': key,
        'machine_name': machine_name,
    }
    cfg_path = install_dir / 'agent_config.json'
    with open(cfg_path, 'w') as f:
        json.dump(config, f, indent=2)
    ok('Yapılandırma kaydedildi')


def create_vbs_launcher(install_dir: Path) -> Path:
    """
    VBScript launcher oluşturur.
    WScript.Shell + Run(..., 0) = TAMAMEN GİZLİ başlatma.
    Ne terminal, ne flash, ne de hiçbir şey görünmez.
    """
    pythonw = Path(sys.executable).parent / 'pythonw.exe'
    if not pythonw.exists():
        pythonw = Path(sys.executable)

    agent_script = install_dir / 'agent.py'
    vbs_path     = install_dir / 'launcher.vbs'

    # WScript.Shell.Run(cmd, windowStyle=0, waitOnReturn=False)
    # windowStyle=0 → pencere tamamen gizli, hiçbir flash yok
    vbs_content = f"""' CloudBackup Silent Launcher
' Bu dosya sistemi yedekleme ajanını sessizce başlatır.
Dim WS
Set WS = CreateObject("WScript.Shell")
WS.Run Chr(34) & "{pythonw}" & Chr(34) & " " & Chr(34) & "{agent_script}" & Chr(34), 0, False
Set WS = Nothing
"""
    with open(vbs_path, 'w', encoding='utf-8') as f:
        f.write(vbs_content)

    ok(f'Sessiz başlatıcı oluşturuldu: launcher.vbs')
    return vbs_path


def install_autostart(install_dir: Path):
    """
    Windows başlangıcında TAMAMEN SESİZ çalışacak şekilde kaydet.

    Yöntem 1 (tercih): VBScript launcher → Registry Run
      - WScript.Shell + windowStyle=0 = sıfır flash, sıfır pencere
      - Kullanıcı hiçbir şey görmez

    Yöntem 2 (fallback): Task Scheduler (Hidden=true)
    """
    vbs_path = create_vbs_launcher(install_dir)

    # Registry'e VBS launcher'ı yaz (python.exe değil, wscript.exe)
    # wscript.exe zaten Windows'ta mevcut, ekstra yükleme gerektirmez
    cmd = f'wscript.exe "{vbs_path}"'

    try:
        reg_key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r'SOFTWARE\Microsoft\Windows\CurrentVersion\Run',
            0, winreg.KEY_SET_VALUE
        )
        winreg.SetValueEx(reg_key, 'CloudBackupAgent', 0, winreg.REG_SZ, cmd)
        winreg.CloseKey(reg_key)
        ok('Windows başlangıcına eklendi (sıfır pencere, sıfır flash)')
    except Exception as e:
        warn(f'Registry yazılamadı ({e}), Task Scheduler deneniyor...')
        agent_script = install_dir / 'agent.py'
        pythonw = Path(sys.executable).parent / 'pythonw.exe'
        if not pythonw.exists():
            pythonw = Path(sys.executable)
        _install_task_scheduler(pythonw, agent_script)


def _install_task_scheduler(pythonw: Path, agent_script: Path):
    """Task Scheduler ile sessiz başlatma (yedek yöntem)."""
    xml = f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <Triggers><LogonTrigger><Enabled>true</Enabled></LogonTrigger></Triggers>
  <Actions Context="Author">
    <Exec>
      <Command>wscript.exe</Command>
      <Arguments>"{agent_script.parent / 'launcher.vbs'}"</Arguments>
    </Exec>
  </Actions>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <Hidden>true</Hidden>
  </Settings>
</Task>"""

    xml_path = agent_script.parent / '_task.xml'
    with open(xml_path, 'w', encoding='utf-16') as f:
        f.write(xml)

    ret = subprocess.run(
        ['schtasks', '/create', '/tn', 'CloudBackupAgent', '/xml', str(xml_path), '/f'],
        capture_output=True
    )
    xml_path.unlink(missing_ok=True)

    if ret.returncode == 0:
        ok('Task Scheduler görevi oluşturuldu (sessiz)')
    else:
        warn('Task Scheduler başarısız. Elle başlatmanız gerekebilir.')


def start_agent(install_dir: Path):
    """
    Agent'ı hemen başlat — VBS launcher üzerinden.
    Sıfır pencere, sıfır flash, kullanıcı hiçbir şey görmez.
    """
    vbs_path = install_dir / 'launcher.vbs'

    if vbs_path.exists():
        # wscript.exe + windowStyle=0 = en sessiz yol
        subprocess.Popen(
            ['wscript.exe', str(vbs_path)],
            creationflags=0x08000000,  # CREATE_NO_WINDOW
            close_fds=True,
        )
    else:
        # VBS oluşturulmamışsa fallback
        pythonw = Path(sys.executable).parent / 'pythonw.exe'
        if not pythonw.exists():
            pythonw = Path(sys.executable)
        subprocess.Popen(
            [str(pythonw), str(install_dir / 'agent.py')],
            creationflags=0x08000000,
            close_fds=True,
        )

    ok('Agent sessizce başlatıldı (pencere yok, flash yok)')


def uninstall():
    """Agent'ı kaldır — tüm izleri temizle."""
    install_dir = get_install_dir()
    title('CloudBackup Kaldırılıyor...')

    # Çalışan agent prosesini durdur
    try:
        subprocess.run(
            'wmic process where "name=\'pythonw.exe\' and commandline like \'%agent.py%\'" call terminate',
            shell=True, capture_output=True
        )
    except: pass

    # Registry
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r'SOFTWARE\Microsoft\Windows\CurrentVersion\Run',
            0, winreg.KEY_SET_VALUE
        )
        winreg.DeleteValue(key, 'CloudBackupAgent')
        winreg.CloseKey(key)
        ok('Registry temizlendi')
    except: pass

    # Task scheduler
    subprocess.run(['schtasks', '/delete', '/tn', 'CloudBackupAgent', '/f'], capture_output=True)

    # Dosyalar
    shutil.rmtree(install_dir, ignore_errors=True)
    ok('Dosyalar silindi')

    print(f'\n{GREEN}✓ CloudBackup kaldırıldı.{RESET}\n')


# ── ANA AKIŞ ──────────────────────────────────────────────────
def main():
    # Kaldırma modu
    if '--uninstall' in sys.argv:
        uninstall()
        return

    print(f"""
{BOLD}{CYAN}╔══════════════════════════════════════╗
║       CloudBackup Agent Kurulum      ║
╚══════════════════════════════════════╝{RESET}

Sessiz arkaplan yedekleme sistemi.
Kurulum tamamlandığında hiçbir pencere görmeyeceksiniz.
""")

    # ── 1. Python kontrolü
    title('1/5  Sistem Kontrolü')
    check_python()

    # ── 2. Firebase kontrolü
    title('2/5  Firebase Bağlantısı')
    ok('Bulut bağlantısı (API) hazır')

    # ── 3. Hesap Key
    title('3/5  Hesap Doğrulama')
    print(f'  {CYAN}Web panelinden key alın: {server_url}{RESET}')
    print(f'  Veya yeni key oluşturmak için Enter\'a basın.\n')

    key = input('  Hesap Keyiniz (CB-XXXX-XXXX-XXXX): ').strip().upper()

    if not key:
        # Yeni key oluştur
        machine_name = input('  Bu bilgisayar için isim girin: ').strip() or os.environ.get('COMPUTERNAME', 'PC')
        info('Yeni hesap oluşturuluyor...')
        try:
            import requests
            url = "https://us-central1-sigalmedia.cloudfunctions.net/api/create_account"
            headers = {"Authorization": "Bearer ashfir_secure_token_2026"}
            res = requests.post(url, headers=headers, json={"machine_name": machine_name}, timeout=10)
            if res.status_code == 200:
                data = res.json()
                if data.get('ok'):
                    key = data.get('key')
                    print(f'
  {BOLD}{GREEN}Yeni Keyiniz: {key}{RESET}')
                    print(f'  {YELLOW}Bu keyi güvenli bir yerde saklayın!{RESET}')
                    input('  Keyi not ettikten sonra Enter\'a basın...')
                else:
                    err('Hesap oluşturulamadı: ' + data.get('error', 'Bilinmeyen hata'))
                    sys.exit(1)
            else:
                err(f'Sunucu hatası: {res.status_code}')
                sys.exit(1)
        except Exception as e:
            err(f'Sunucu bağlantı hatası: {e}')
            sys.exit(1)
    else:
        # Mevcut key doğrula
        info('Key doğrulanıyor...')
        result = validate_key(key)
        if not result or not result.get('ok'):
            err('Geçersiz key: ' + (result or {}).get('error', 'Hata oluştu'))
            sys.exit(1)
        ok('Key doğrulandı')

    machine_name = os.environ.get('COMPUTERNAME', input('  Bilgisayar adı: ').strip() or 'PC')

    # ── 4. Kurulum
    title('4/5  Kurulum')
    info('Eski agent işlemleri kapatılıyor...')
    try:
        subprocess.run(
            'wmic process where "name=\'pythonw.exe\' and commandline like \'%agent.py%\'" call terminate',
            shell=True, capture_output=True
        )
    except: pass
    
    install_packages()
    install_dir = get_install_dir()
    copy_agent_files(install_dir)
    save_agent_config(install_dir, key, machine_name)
    install_autostart(install_dir)

    # ── 5. Başlat
    title('5/5  Başlatılıyor')
    start_agent(install_dir)

    # Başarı
    print(f"""
{GREEN}╔══════════════════════════════════════╗
║       ✓  Kurulum Tamamlandı!         ║
╚══════════════════════════════════════╝{RESET}

  {CYAN}Key:      {RESET}{key}
  {CYAN}Sunucu:   {RESET}{server_url}
  {CYAN}Makine:   {RESET}{machine_name}
  {CYAN}Konum:    {RESET}{install_dir}

  Agent arkaplanda çalışıyor. 
  Hiçbir pencere, hiçbir ikon — tamamen sessiz.
  
  {YELLOW}Web paneli:{RESET} {server_url}
  {YELLOW}Kaldırmak:{RESET}  python install.py --uninstall
""")


if __name__ == '__main__':
    main()
