# Ashfir Agent - Akıllı Yedekleme ve Sistem Yönetim Servisi

Ashfir Agent, Windows sistemler üzerinde sessizce çalışan, kritik verileri akıllı algoritmalar ile tespit edip uçtan uca şifreleyerek bulut ortamına yedekleyen gelişmiş bir Python tabanlı servis uygulamasıdır.

Bu proje, sistem programlama, ağ güvenliği ve yapay zeka entegrasyonu konularında teknik bir yetkinlik göstergesi olarak geliştirilmiştir.

## 🚀 Öne Çıkan Özellikler

- **Akıllı Dosya Filtreleme (AI Powered):** Groq (Llama 3.3) entegrasyonu sayesinde dosyaların içeriğini ve yolunu analiz ederek sadece değerli belgeleri (PDF, DOCX, veritabanı yedekleri vb.) yedekler, sistem dosyalarını ve gereksiz verileri atlar.
- **Hibrit Şifreleme Mimarisi:** Veriler yerelde **AES-256 (GCM)** ile şifrelenir. AES anahtarları ise **RSA-2048** (Public Key) ile şifrelenerek sunucuya iletilir. Bu sayede sunucu tarafında anahtar ele geçirilse bile veriler okunamaz.
- **Gelişmiş USB/Flash İzleme:** Sisteme takılan taşınabilir sürücüleri anlık olarak tespit eder, içindeki kritik verileri önce güvenli bir `stage` alanına kopyalar ve ardından arka planda buluta senkronize eder.
- **Dayanıklı Bağlantı Mimarisi:** 
  - Kısıtlı ağlarda (kurumsal filtreler, MEB vb.) çalışabilmek için özel SSL Context yapılandırması ve sertifika doğrulama bypass mekanizmaları içerir.
  - **Cloudflare Workers** tabanlı C2 (Command & Control) yapısı ile yüksek erişilebilirlik sağlar.
- **Güvenlik ve Gizlilik:** 
  - **Anti-Debug:** Uygulamanın analiz edilmesini zorlaştırmak için debugger kontrolleri içerir.
  - **Single Instance:** Mutex kullanarak sistemde aynı anda sadece bir kopyanın çalışmasını garanti eder.
  - **TOTP Auth:** Sunucu ile iletişimde zaman bazlı dinamik token üretimi (SHA-256) kullanır.

## 🛠️ Teknik Yığın (Tech Stack)

- **Dil:** Python 3.10+
- **Kütüphaneler:** `pycryptodome`, `watchdog`, `requests`, `psutil`, `winreg`, `groq`
- **Backend:** Cloudflare Workers (JavaScript/V8)
- **Veritabanı:** Firebase Firestore & Storage
- **Güvenlik:** RSA-2048, AES-256-GCM, HMAC/SHA-256

## 📂 Dosya Yapısı

- `agent.py`: Ana servis mantığı, network katmanı ve şifreleme motoru.
- `ai_filter.py`: Yapay zeka tabanlı karar mekanizması.
- `install.py`: Servisin sisteme kurulumu ve başlangıç ayarları.
- `public.pem`: RSA genel anahtarı.

## ⚠️ Yasal Uyarı

Bu proje tamamen eğitim ve güvenlik araştırması amacıyla geliştirilmiştir. Yazılımın izinsiz sistemlerde kullanılması yasal sorumluluk doğurabilir. Kullanıcı, bu yazılımı kullanırken yerel yasalara uymakla yükümlüdür.
