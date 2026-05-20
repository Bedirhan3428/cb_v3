/**
 * Ashfir Cloudflare Worker Proxy
 * 
 * Bu Worker, agent'tan gelen tüm istekleri Firebase Cloud Functions'a
 * proxy eder. MEB ağlarında Firebase URL'sine doğrudan erişim
 * sertifika hatası verdiği için, agent bunun yerine Cloudflare URL'sine
 * bağlanır. Cloudflare sertifikaları okul ağlarında genellikle sorunsuz çalışır.
 * 
 * Kullanım:
 *   1. Cloudflare Dashboard -> Workers & Pages -> Create Worker
 *   2. Bu kodu yapıştırın ve Deploy edin
 *   3. Agent'taki CF_URL'yi Workers URL'nize güncelleyin
 *      Örn: https://ashfir-proxy.HESABINIZ.workers.dev
 */

const FIREBASE_BACKEND = "https://us-central1-sigalmedia.cloudfunctions.net/api";

export default {
  async fetch(request) {
    const url = new URL(request.url);
    
    // Worker'ın kendi path'ini Firebase backend'e yönlendir
    // Örn: /heartbeat -> https://us-central1-sigalmedia.cloudfunctions.net/api/heartbeat
    let targetUrl = FIREBASE_BACKEND + url.pathname + url.search;

    // Eğer Ajan, "X-Proxy-Target" başlığı gönderirse, Firebase'e değil doğrudan bu URL'ye yönlendir
    // Bu, Storage Signed URL için devasa dosyaları (100MB'a kadar) engelsiz aktarmamızı sağlar.
    const proxyTarget = request.headers.get("X-Proxy-Target");
    if (proxyTarget) {
      targetUrl = proxyTarget;
    }

    const newHeaders = new Headers(request.headers);
    newHeaders.delete("X-Proxy-Target"); // Storage'a gereksiz başlığı yollama
    newHeaders.delete("Host"); // Host başlığı hedef URL'ye göre otomatik ayarlansın
    if (proxyTarget) {
      newHeaders.delete("Authorization"); // GCS, hem Signed URL hem Authorization başlığını aynı anda kabul etmez (400 Bad Request verir)
    }

    // Orijinal isteğin tüm header, method ve body'sini koru
    const modifiedRequest = new Request(targetUrl, {
      method: request.method,
      headers: newHeaders,
      body: request.body,
      redirect: "follow",
    });

    try {
      const response = await fetch(modifiedRequest);
      
      // Response'u CORS header'larıyla birlikte döndür
      const modifiedResponse = new Response(response.body, response);
      modifiedResponse.headers.set("Access-Control-Allow-Origin", "*");
      modifiedResponse.headers.set("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS");
      modifiedResponse.headers.set("Access-Control-Allow-Headers", "*");
      
      return modifiedResponse;
    } catch (err) {
      return new Response(JSON.stringify({ error: "Proxy error", detail: err.message }), {
        status: 502,
        headers: { "Content-Type": "application/json" },
      });
    }
  },
};
