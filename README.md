# Private Document Gateway

Private Document Gateway, belgeleri üçüncü taraf bir belge veya LLM servisine göndermeden
Markdown'a dönüştüren, parçalayan, indeksleyen ve yalnızca gerekli bölümleri REST API ile
MCP üzerinden sunan self-hosted bir belge geçididir.

Ürünün temel sözü: **Belge içerikleri sizde kalır; LLM araçları varsayılan olarak tam belgeyi
değil, sınırlandırılmış ilgili parçaları alır.** Uygulama cevap üretmez ve herhangi bir LLM
sağlayıcısını zorunlu kılmaz.

## Neden?

- PDF, Office ve metin belgeleri için tek, kontrollü bir erişim yüzeyi sağlar.
- MarkItDown çıktısını bir kez üretip diskte önbelleğe alır.
- Arama sonuçlarını `top_k` ve `max_chars` bütçeleriyle sınırlar.
- Ham dosyaları dosya adıyla değil UUID ile saklar.
- Düşük kaynaklı tek sunucuda SQLite ve yerel volume'larla çalışır.
- Arama, parser, storage ve repository sınırları ileride pgvector/Qdrant/S3/PostgreSQL
  adaptörlerine açıktır.

## Mimari akış

```text
REST upload
    │
    ├─ extension + MIME + signature + size validation
    ├─ UUID path + SHA-256 ── duplicate? ── reuse cached record
    │
    └─ MarkItDown ──> cached Markdown ──> heading-aware chunks
                                            │
                                            └─> SQLite metadata + keyword search
                                                        │
                                  bounded REST responses / read-only MCP tools
```

Katmanlar `api`, `services`, `repositories`, `parsers`, `storage`, `chunking`, `mcp`,
`models`, `schemas` ve `core` altında ayrılmıştır. MVP senkron olarak işler: upload isteği,
dönüşüm tamamlandığında `ready` döner; başarısız kayıtlar `failed` durumuyla saklanır.

## Desteklenen formatlar

| Format | Uzantı | Not |
|---|---|---|
| PDF | `.pdf` | Metin tabanlı PDF; MVP'de harici OCR yoktur |
| Word | `.docx` | Office archive yapısı doğrulanır |
| PowerPoint | `.pptx` | Office archive yapısı doğrulanır |
| Excel | `.xlsx` | Office archive yapısı doğrulanır |
| Text | `.txt` | UTF-8 |
| Markdown | `.md`, `.markdown` | UTF-8 |
| HTML | `.html`, `.htm` | UTF-8; URL'den içerik alma yoktur |

Format bağımlılığı kurulu MarkItDown adaptöründe işlenemiyorsa API kontrollü bir
`conversion_failed` cevabı döndürür. Şifreli, bozuk veya yalnızca taranmış belgeler bu kapsama
girebilir.

## Docker ile kurulum

Gerekenler: Docker Engine ve Compose v2.

```bash
git clone https://github.com/mustafa0zdemir/private-document-gateway.git
cd private-document-gateway
cp .env.example .env
openssl rand -hex 32
# Üretilen değeri .env içindeki PDG_API_KEY alanına yazın.
docker compose up -d --build
docker compose ps
curl http://127.0.0.1:8000/health
```

Uploads, Markdown cache ve SQLite veritabanı üç ayrı named volume'da kalıcıdır. Container
UID `10001` ile, capability olmadan, read-only root filesystem ve yazılabilir geçici `/tmp`
ile çalışır. Kullanılan Python slim tabanı ve bağımlılıklar AMD64/ARM64 için uygundur.

Güncelleme:

```bash
git pull
docker compose up -d --build
```

Volume'ları silmek belge verisini kalıcı olarak siler; normal güncellemede `docker compose down
-v` kullanmayın.

## Yerel geliştirme

Python 3.12 ile:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env
# .env içindeki API anahtarını değiştirin.
uvicorn app.main:app --reload
```

Test ve kalite kontrolleri:

```bash
pytest --cov=app
ruff check .
ruff format --check .
```

## REST API

`GET /health` dışındaki REST ve MCP istekleri `X-API-Key` ister. Örneklerde:

```bash
export PDG_CLIENT_API_KEY='your-.env-value'
```

Belge yükleme:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/documents \
  -H "X-API-Key: ${PDG_CLIENT_API_KEY}" \
  -F 'file=@./example.pdf'
```

Liste ve metadata:

```bash
curl -H "X-API-Key: ${PDG_CLIENT_API_KEY}" \
  'http://127.0.0.1:8000/api/v1/documents?offset=0&limit=20'

curl -H "X-API-Key: ${PDG_CLIENT_API_KEY}" \
  'http://127.0.0.1:8000/api/v1/documents/DOCUMENT_ID'
```

Sayfalı Markdown ve chunk okuma:

```bash
curl -H "X-API-Key: ${PDG_CLIENT_API_KEY}" \
  'http://127.0.0.1:8000/api/v1/documents/DOCUMENT_ID/markdown?offset=0&max_chars=8000'

curl -H "X-API-Key: ${PDG_CLIENT_API_KEY}" \
  'http://127.0.0.1:8000/api/v1/documents/DOCUMENT_ID/chunks?offset=0&limit=20'
```

Belge içinde arama ve silme:

```bash
curl -G -H "X-API-Key: ${PDG_CLIENT_API_KEY}" \
  --data-urlencode 'q=contract termination period' \
  --data 'top_k=5' --data 'max_chars=8000' \
  'http://127.0.0.1:8000/api/v1/documents/DOCUMENT_ID/search'

curl -X DELETE -H "X-API-Key: ${PDG_CLIENT_API_KEY}" \
  'http://127.0.0.1:8000/api/v1/documents/DOCUMENT_ID'
```

OpenAPI arayüzü `/docs` adresindedir. Endpoint'ler arayüz açık olsa da API anahtarı olmadan
çalışmaz.

## MCP bağlantısı

Streamable HTTP endpoint'i `http://127.0.0.1:8000/mcp` adresindedir. MCP istemcisinde URL ve
header tanımlama biçimi istemciye göre değişir; genel yapı şöyledir:

```json
{
  "mcpServers": {
    "private-documents": {
      "type": "streamable-http",
      "url": "http://127.0.0.1:8000/mcp",
      "headers": {
        "X-API-Key": "your-.env-value"
      }
    }
  }
}
```

Yerel süreç tabanlı istemciler için stdio giriş noktası da vardır:

```bash
PDG_API_KEY='at-least-24-characters-long' private-document-gateway-mcp
```

Araçlar:

- `list_documents`: sayfalı metadata listesi.
- `get_document_metadata`: içerik olmadan tek belge durumu.
- `search_documents`: tüm hazır belgelerde sınırlandırılmış arama.
- `search_document`: tek belgede sınırlandırılmış arama.
- `get_relevant_chunks`: bir soru için küçük, ilgili context seti.
- `get_document_section`: aramadan sonra belirli chunk sırasını sınırlı okuma.

Araçların tamamı salt okunurdur. Upload ve delete yalnızca REST'tedir. Ham dosya döndüren MCP
aracı yoktur.

## Oracle Cloud Ubuntu özeti

1. Ubuntu ARM64 veya AMD64 instance oluşturun; boot volume için düzenli snapshot planlayın.
2. Docker Engine ile Compose eklentisini kurun ve repoyu clone edin.
3. `.env` içinde güçlü `PDG_API_KEY` üretin. MCP için public DNS/Tailscale adresini
   `PDG_ALLOWED_HOSTS` listesine exact host ve `host:*` biçiminde ekleyin.
4. Tercihen Tailscale/VPN üzerinden erişin. Public yayın gerekiyorsa yalnızca 80/443 ingress
   açın, Caddy/Nginx ile TLS sonlandırın ve uygulamanın 8000 portunu internete doğrudan açmayın.
5. `docker compose up -d --build` çalıştırın; `docker compose ps` ve `/health` ile doğrulayın.
6. `gateway_uploads`, `gateway_markdown`, `gateway_database` volume'larını birlikte yedekleyin.

Oracle Security List/NSG ve Ubuntu firewall kuralları birlikte değerlendirilmelidir. Tailscale IP
ile doğrudan MCP kullanılacaksa bu IP'yi `PDG_ALLOWED_HOSTS` içine ekleyin.

## Güvenlik notları

- API anahtarı response veya uygulama loguna yazılmaz; `.env` git tarafından dışlanır.
- Dosya adı yalnızca metadata'dır. Disk yolu UUID + doğrulanmış uzantıdan oluşur.
- Uzantı, MIME ve temel dosya imzası birlikte kontrol edilir. Office archive'larında açılmış
  toplam boyut limiti uygulanır.
- Maksimum upload boyutu stream sırasında uygulanır; kısmi dosya hata halinde silinir.
- MarkItDown yalnızca saklanan yerel UUID yolunda çalışır; MVP URL kabul etmez.
- CORS varsayılan olarak kapalıdır. Gerekiyorsa kesin origin listesi verin.
- MCP DNS-rebinding koruması exact Host allowlist ile çalışır.
- Silme işlemi raw dosyayı, Markdown cache'i ve foreign-key cascade ile chunk kayıtlarını siler.
- Public kurulumda TLS, firewall/rate limit ve düzenli yedekleme hâlâ operatör sorumluluğudur.

## Token tasarrufu

- SHA-256 aynı dosyayı ikinci kez dönüştürmeyi engeller.
- Markdown bir kez dönüştürülür ve volume'da önbelleğe alınır.
- Başlık-aware chunk'lar arama sırasında sıralanır; sadece ilgili metin döner.
- `top_k`, `max_chars`, `offset` ve `limit` sunucu tarafında üst sınırlara sahiptir.
- MCP'nin tam belge veya ham dosya döndüren bir varsayılan aracı yoktur.
- Chunk overlap düşük ve `PDG_CHUNK_OVERLAP_CHARS` ile ayarlanabilir.

## Kısa ADR

### ADR-001 — Ürünleşmiş tek-sunucu MVP için SQLite

SQLite, Oracle VM üzerinde ek servis gerektirmeyen en düşük operasyon maliyetli seçenektir. Bu
sürüm WAL, foreign key, busy timeout, indeksler, transaction ve SHA-256 unique constraint ile
çalışır; yani yalnızca bir demo deposu olarak kullanılmaz. SQLAlchemy ve `DocumentRepository`
sınırı sayesinde çoklu instance, yoğun eşzamanlı yazma veya HA ihtiyacı doğduğunda PostgreSQL'e
geçiş servis/API katmanını değiştirmeden yapılabilir. Bu eşik gelmeden PostgreSQL eklemek ürünün
tek komut ve düşük kaynak avantajını azaltır.

### ADR-002 — İlk sprintte isteğe bağlı worker yok

Upload isteği dönüşümü aynı işlem içinde tamamlar ve kesin `ready`/`failed` sonucu verir. Kuyruk
ve worker, uzun belgelerde request süresi sorun olduğunda eklenebilir; Redis ilk sürüm bağımlılığı
değildir.

### ADR-003 — Retrieval-first MCP

MCP önce liste/metadata/arama, sonra bounded section akışını teşvik eder. Upload/silme REST'te
kalarak LLM aracının mutasyon yüzeyi kapalı tutulur.

## Yol haritası

- Background job/worker ve işlem progress'i
- SQLite FTS5 adaptörü; ardından opsiyonel pgvector/Qdrant semantic search
- PostgreSQL repository ve çoklu instance profili
- S3/MinIO uyumlu opsiyonel storage adaptörü
- OCR için tamamen yerel, opsiyonel adapter
- API key rotation, rate limit ve audit metadata (belge içeriği olmadan)
- İsteğe bağlı tenant/ACL modeli
