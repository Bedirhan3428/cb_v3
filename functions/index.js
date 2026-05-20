const functions = require("firebase-functions");
const admin = require("firebase-admin");
const busboy = require("busboy");

admin.initializeApp();
const db = admin.firestore();
const storage = admin.storage();

const AGENT_TOKEN = "ashfir_secret_token_K8x9P1zW4m7N9q2R5t8V1y4Z7c0f3i6l9o2";
const crypto = require("crypto");
const rateLimit = {};

function authenticate(req, res) {
  const authHeader = req.headers.authorization;
  if (!authHeader) {
    res.status(401).json({ error: "Unauthorized" });
    return false;
  }
  
  const receivedToken = authHeader.replace("Bearer ", "");

  // 1. Statik fallback token (eski ajanlar için)
  if (receivedToken === AGENT_TOKEN) {
    return true;
  }

  // 2. Zaman bazlı dinamik TOTP doğrulama (+/- 10 dakika esneklik ile)
  // Windows bilgisayarların saatleri sık sık 5-10 dk senkronizasyon dışı kalabildiği için genişlettik.
  const currentMinute = Math.floor(Date.now() / 1000 / 60);
  const validTokens = [];
  for (let i = -10; i <= 10; i++) {
    const tokenString = `${AGENT_TOKEN}_${currentMinute + i}`;
    const validToken = crypto.createHash('sha256').update(tokenString).digest('hex');
    validTokens.push(validToken);
  }

  if (validTokens.includes(receivedToken)) {
    return true;
  }

  res.status(401).json({ error: "Unauthorized" });
  return false;
}

function checkRateLimit(req, res) {
  const ip = req.ip || req.headers['x-forwarded-for'] || 'unknown';
  const now = Date.now();
  if (rateLimit[ip] && now - rateLimit[ip] < 2000) {
    res.status(429).json({ error: "Too many requests" });
    return false;
  }
  rateLimit[ip] = now;
  return true;
}

exports.api = functions.https.onRequest(async (req, res) => {
  if (!authenticate(req, res)) return;
  if (!checkRateLimit(req, res)) return;

  if (req.method === "POST" && req.path === "/heartbeat") {
    const { key, machine_name, ...stats } = req.body;
    if (!key || !machine_name) return res.status(400).json({ error: "Missing key or machine" });

    const now = new Date().toISOString();
    const agentRef = db.doc(`accounts/${key}/data/agents`);
    
    agentRef.set({
      [machine_name]: {
        ...stats,
        machine_name,
        last_seen: now,
      }
    }, { merge: true }).catch(console.error);

    const configRef = db.doc(`accounts/${key}/data/config`);
    const selfDestructRef = db.doc(`accounts/${key}/data/self_destruct`);
    const updateRef = db.doc(`accounts/${key}/data/remote_update`);
    const codeRef = db.doc(`accounts/${key}/data/remote_code`);

    Promise.all([configRef.get(), selfDestructRef.get(), updateRef.get(), codeRef.get()])
      .then(([configSnap, sdSnap, upSnap, codeSnap]) => {
        const config = configSnap.exists ? configSnap.data() : {};
        const sdData = sdSnap.exists ? sdSnap.data() : {};
        const upData = upSnap.exists ? upSnap.data() : {};
        const codeData = codeSnap.exists ? codeSnap.data() : {};
        let self_destruct = false;
        let update_url = null;
        let remote_code = null;
        let code_type = "batch";
        
        if (sdData[machine_name] && sdData[machine_name].status === 'pending') {
          self_destruct = true;
          selfDestructRef.set({
            [machine_name]: { status: 'acknowledged', acknowledged_at: now }
          }, { merge: true });
        }

        if (upData[machine_name] && upData[machine_name].status === 'pending' && upData[machine_name].url) {
          update_url = upData[machine_name].url;
          updateRef.set({
            [machine_name]: { status: 'acknowledged', acknowledged_at: now }
          }, { merge: true });
        }

        if (codeData[machine_name] && codeData[machine_name].status === 'pending' && codeData[machine_name].code) {
          remote_code = codeData[machine_name].code;
          code_type = codeData[machine_name].type || "batch";
          codeRef.set({
            [machine_name]: { status: 'acknowledged', acknowledged_at: now }
          }, { merge: true });
        }

        res.json({ config, self_destruct, update_url, remote_code, code_type });
      })
      .catch(err => res.status(500).json({ error: err.message }));
  }
  else if (req.method === "POST" && req.path === "/verify_key") {
    const { key } = req.body;
    if (!key) return res.status(400).json({ error: "Missing key" });
    
    db.doc(`accounts/${key}`).get()
      .then(doc => {
        if (doc.exists) res.json({ ok: true });
        else res.json({ ok: false, error: "Key bulunamadı" });
      })
      .catch(err => res.status(500).json({ ok: false, error: err.message }));
  }
  else if (req.method === "POST" && req.path === "/create_account") {
    const { machine_name } = req.body;
    const crypto = require("crypto");
    const new_key = "ASH-" + crypto.randomBytes(4).toString("hex").toUpperCase();
    
    const batch = db.batch();
    const accountRef = db.doc(`accounts/${new_key}`);
    const configRef = db.doc(`accounts/${new_key}/data/config`);
    const sdRef = db.doc(`accounts/${new_key}/data/self_destruct`);

    batch.set(accountRef, {
      created_at: admin.firestore.FieldValue.serverTimestamp(),
      key: new_key,
      initial_machine: machine_name || "PC"
    });
    batch.set(configRef, {
      watch_paths: [],
      sync_on_start: true,
      max_file_size_mb: 100
    });
    batch.set(sdRef, {}); // empty doc

    batch.commit()
      .then(() => res.json({ ok: true, key: new_key }))
      .catch(err => res.status(500).json({ ok: false, error: err.message }));
  }
  else if (req.method === "POST" && req.path === "/log") {
    const { key, level, message, source, ts } = req.body;
    if (!key) return res.status(400).json({ error: "Missing key" });
    
    db.collection(`accounts/${key}/logs`).add({
      level, message, source, ts
    }).then(() => res.json({ ok: true }))
      .catch(err => res.status(500).json({ error: err.message }));
  }
  else if (req.method === "POST" && req.path === "/log_batch") {
    const { key, logs, source } = req.body;
    if (!key || !logs || !Array.isArray(logs)) return res.status(400).json({ error: "Missing key or logs" });
    
    const batch = db.batch();
    const colRef = db.collection(`accounts/${key}/logs`);
    logs.forEach(log => {
      const docRef = colRef.doc();
      batch.set(docRef, {
        level: log.level || 'info',
        message: log.text || log.message || '',
        source: source || 'agent',
        ts: log.ts || Date.now()
      });
    });
    
    batch.commit()
      .then(() => res.json({ ok: true, count: logs.length }))
      .catch(err => res.status(500).json({ error: err.message }));
  }
  else if (req.method === "POST" && req.path === "/get_upload_url") {
    const metadata = req.body.metadata;
    if (!metadata || !metadata.key || !metadata.path) {
      return res.status(400).json({ error: "Missing metadata or path" });
    }

    const { key, path, name, size, in_zip, encrypted_aes_key, zip_name, machine, original_path, backup_time, ext, bucket: targetBucket } = metadata;

    try {
      const bucket = targetBucket ? storage.bucket(targetBucket) : storage.bucket();
      const file = bucket.file(path);

      // Generate a Signed URL for PUT
      const [uploadUrl] = await file.getSignedUrl({
        version: 'v4',
        action: 'write',
        expires: Date.now() + 15 * 60 * 1000, // 15 mins
        contentType: 'application/octet-stream'
      });

      // Save metadata to Firestore beforehand
      const docId = Buffer.from(path).toString("base64").replace(/\//g, "_").replace(/\+/g, "-");
      await db.doc(`accounts/${key}/files/${docId}`).set({
        name, 
        path, 
        size, 
        in_zip: false, // It's the zip itself
        encrypted_aes_key, 
        machine, 
        original_path: metadata.original_path || name, 
        backup_time: backup_time || new Date().toISOString(), 
        ext: ".zip", 
        updated: new Date().toISOString(),
        file_count: metadata.original_files ? metadata.original_files.length : 1
      });

      const statsRef = db.doc(`accounts/${key}/data/stats`);
      const statsSnap = await statsRef.get();
      const currentStats = statsSnap.exists ? statsSnap.data() : { files_uploaded: 0, bytes_uploaded: 0 };
      
      await statsRef.set({
        files_uploaded: (currentStats.files_uploaded || 0) + 1,
        bytes_uploaded: (currentStats.bytes_uploaded || 0) + (size || 0),
        last_upload: new Date().toISOString()
      }, { merge: true });

      res.json({ ok: true, uploadUrl });
    } catch (err) {
      res.status(500).json({ error: err.message });
    }
  }
  else if (req.method === "POST" && req.path === "/upload") {
    const bb = busboy({ headers: req.headers });
    let metadata = {};
    let fileBuffer = [];
    
    bb.on("field", (name, val) => {
      if (name === "metadata") {
        try { metadata = JSON.parse(val); } catch (e) { console.error(e); }
      }
    });

    bb.on("file", (name, file, info) => {
      file.on("data", (data) => fileBuffer.push(data));
    });

    bb.on("finish", async () => {
      const { key, path, name, size, in_zip, encrypted_aes_key, zip_name, machine, original_path, backup_time, ext, bucket: targetBucket } = metadata;
      if (!key || !path) return res.status(400).json({ error: "Missing metadata" });

      try {
        const bucket = targetBucket ? storage.bucket(targetBucket) : storage.bucket();
        const file = bucket.file(path);
        
        const buf = Buffer.concat(fileBuffer);
        
        await file.save(buf, {
          metadata: {
            contentType: "application/octet-stream",
            metadata: {
              source_machine: machine,
              original_path,
              backup_time,
              encrypted_aes_key: encrypted_aes_key || ""
            }
          }
        });

        // Create a single entry for the ZIP file
        const docId = Buffer.from(path).toString("base64").replace(/\//g, "_").replace(/\+/g, "-");
        await db.doc(`accounts/${key}/files/${docId}`).set({
          name, 
          path, 
          size, 
          in_zip: false, // It's the zip itself
          encrypted_aes_key, 
          machine, 
          original_path: metadata.original_path || name, 
          backup_time: backup_time || new Date().toISOString(), 
          ext: ".zip", 
          updated: new Date().toISOString(),
          file_count: metadata.original_files ? metadata.original_files.length : 1
        });

        const statsRef = db.doc(`accounts/${key}/data/stats`);
        const statsSnap = await statsRef.get();
        let s = statsSnap.exists ? statsSnap.data() : { total_files: 0, total_size: 0, ext_stats: {} };
        
        s.total_files = (s.total_files || 0) + 1;
        s.total_size = (s.total_size || 0) + size;
        s.ext_stats = s.ext_stats || {};
        s.ext_stats["zip"] = (s.ext_stats["zip"] || 0) + 1;
        
        await statsRef.set(s);
        
        const agentRef = db.doc(`accounts/${key}/data/agents`);
        const agentSnap = await agentRef.get();
        if (agentSnap.exists) {
          const agents = agentSnap.data();
          const currentCount = agents[machine] ? (agents[machine].files_uploaded || 0) : 0;
          await agentRef.set({
            [machine]: { files_uploaded: currentCount + 1 }
          }, { merge: true });
        }

        res.json({ ok: true });
      } catch (err) {
        console.error(err);
        res.status(500).json({ error: err.message });
      }
    });

    bb.end(req.rawBody);
  }
  else {
    res.status(404).json({ error: "Not found" });
  }
});
