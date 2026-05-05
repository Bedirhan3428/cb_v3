import re, json, logging
from pathlib import Path
log = logging.getLogger("AIFilter")

SYSTEM_PROMPT = """Sen akilli bir bulut yedekleme asistanisin.
Dosyanin yedeklenmesi gerekip gerekmedigine karar ver.

YEDEKLENMELI: Kullanici belgeleri (.docx,.pdf,.xlsx,.txt), gorseller, veri dosyalari (database yedekleri), arsivler (.zip,.rar - kullanici klasorunde)
YEDEKLENMEMELI: Kaynak kodlar (.js,.py,.cpp,.html,.css,.jsx,.tsx vb), .exe/.dll/.sys, gecici dosyalar, kütüphane klasörleri (node_modules, venv, .git)

Filtre Kurallari:
1. Yol 'node_modules','__pycache__','.git','Temp','dist','build','venv','bin','obj' iceriyorsa HAYIR.
2. Yazilim projesi dosyasi (.json, .py, .js, .cpp, .h, .java, .cs, .go, .rs, .php, .html, .css, .scss, .less, .jsx, .tsx, .vue) ise HAYIR.
3. Kullanici belgesi (Documents, Desktop, Pictures) ise EVET.

SADECE JSON don: {"should_backup": false, "reason": "kisa aciklama", "confidence": 0.95}"""

class AIFilter:
    def __init__(self, api_key, model="llama-3.3-70b-versatile"):
        try:
            from groq import Groq
            self.client = Groq(api_key=api_key); self.model = model; self.enabled = True
        except: self.enabled = False
        self._cache = {}
    def should_backup(self, filepath, size_bytes=0):
        if not self.enabled: return {"should_backup":True,"reason":"AI devre disi","confidence":1.0}
        if filepath in self._cache: return self._cache[filepath]
        p = Path(filepath)
        result = self._query(p.name, p.suffix.lower(), str(p.parent), round(size_bytes/1048576,3), filepath)
        self._cache[filepath] = result
        emoji = "YEDEKLE" if result["should_backup"] else "ATLA"
        log.info(f'AI [{emoji}] {p.name} - {result.get("reason","")} ({result.get("confidence",0):.0%})')
        return result
    def _query(self, name, ext, directory, size_mb, full_path):
        msg = f"Dosya: {name}\nUzanti: {ext}\nBoyut: {size_mb:.2f}MB\nKlasor: {directory}\nTam yol: {full_path}"
        try:
            r = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role":"system","content":SYSTEM_PROMPT},{"role":"user","content":msg}],
                max_tokens=120, temperature=0.05)
            raw = r.choices[0].message.content.strip()
            m = re.search(r"\{.*?\}", raw, re.DOTALL)
            if m:
                d = json.loads(m.group())
                return {"should_backup":bool(d.get("should_backup",True)),"reason":str(d.get("reason",""))[:80],"confidence":float(d.get("confidence",0.8))}
        except: pass
        return {"should_backup":True,"reason":"AI hatasi","confidence":0.5}
