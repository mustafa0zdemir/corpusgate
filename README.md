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
- FTS5/BM25 ile relevance sıralı arama yapar; sonuçları `top_k`, `max_chars` ve
  `max_tokens` bütçeleriyle sınırlar.
- Ham dosyaları dosya adıyla değil UUID ile saklar.
- Düşük kaynaklı tek sunucuda SQLite ve yerel volume'larla çalışır.
- Arama, parser, storage ve repository sınırları ileride pgvector/Qdrant/S3/PostgreSQL
  adaptörlerine açıktır.

## Mimari akış

```text
REST upload
    │
    ├─ extension + MIME + signature + size validation
    ├─ UUID path + SHA-256 ── unchanged? ── reuse cached record
    │
    └─ MarkItDown ──> cached Markdown ──> token-aware, metadata-carrying chunks
                                            │
                                            └─> SQLite metadata + FTS5/BM25 index
                                                        │
                              budget + dedup + cursor / read-only MCP tools
```

Katmanlar `api`, `services`, `repositories`, `parsers`, `storage`, `chunking`, `mcp`,
`models`, `schemas` ve `core` altında ayrılmıştır. MVP senkron olarak işler: upload isteği,
dönüşüm tamamlandığında `ready` döner; başarısız kayıtlar `failed` durumuyla saklanır.
SHA-256 aynıysa cache kaydı doğrudan kullanılır. Aynı dosya adı farklı içerikle yeniden
yüklendiğinde mevcut `document_id` korunur; yeni dönüşüm başarılı olduktan sonra eski Markdown,
chunk ve FTS kayıtları tek transaction ile değiştirilir. Başarısız yenileme hazır eski sürümü
bozmaz.

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

Chunk'lar Markdown başlığını ve dönüştürücü çıktısında bulunuyorsa sayfa/slayt/sheet bilgisini
taşır. PPTX slayt işaretleri ve XLSX sheet başlıkları korunur. PDF dönüştürücü sayfa işareti
üretmiyorsa uygulama bir sayfa numarası uydurmaz.

## Docker ile kurulum

Gerekenler: Docker Engine ve Compose v2.

```bash
git clone https://github.com/mustafa0zdemir/private-document-gateway.git
cd private-document-gateway
cp .env.example .env
openssl rand -hex 32
# REST için PDG_API_KEY, MCP için farklı bir PDG_MCP_AUTH_TOKENS değeri üretin.
docker compose up -d --build
docker compose ps
curl http://127.0.0.1:8000/health
```

Documents, Markdown cache, SQLite veritabanı ve backup çıktıları ayrı volume'larda kalıcıdır. Container
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

Önemli retrieval ayarları:

| Ortam değişkeni | Varsayılan | Açıklama |
|---|---:|---|
| `PDG_CHUNK_SIZE_TOKENS` | `500` | Hedef yaklaşık chunk token sayısı |
| `PDG_CHUNK_OVERLAP_TOKENS` | `50` | Ardışık token penceresi overlap'i |
| `PDG_MIN_CHUNK_TOKENS` | `40` | Birleştirilmesi tercih edilen küçük chunk eşiği |
| `PDG_DEFAULT_RESPONSE_MAX_TOKENS` | `2000` | Parametre verilmezse içerik bütçesi |
| `PDG_MAX_RESPONSE_TOKENS` | `6000` | İstemcinin aşamayacağı kesin token üst sınırı |
| `PDG_MAX_RESPONSE_CHARS` | `24000` | İstemcinin aşamayacağı kesin karakter üst sınırı |
| `PDG_MAX_NEIGHBOR_WINDOW` | `1` | Bir eşleşmenin iki yönündeki azami komşu sayısı |

Token sayıları sağlayıcıya özgü tokenizer değil, yerel ve deterministik bir tahmindir. Böylece
ürün bir LLM'e bağlanmadan bütçe uygulayabilir; gerçek model faturalama token'ı farklı olabilir.

## REST API

REST endpoint'leri `X-API-Key` ister. `/health` ve `/ready` kimlik doğrulaması olmadan yalnızca
durum döndürür. Örneklerde:

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
  --data 'top_k=5' --data 'max_chars=8000' --data 'max_tokens=1200' \
  --data 'neighbor_window=0' \
  'http://127.0.0.1:8000/api/v1/documents/DOCUMENT_ID/search'

curl -X DELETE -H "X-API-Key: ${PDG_CLIENT_API_KEY}" \
  'http://127.0.0.1:8000/api/v1/documents/DOCUMENT_ID'
```

OpenAPI arayüzü `/docs` adresindedir. Endpoint'ler arayüz açık olsa da API anahtarı olmadan
çalışmaz.

Arama cevabı relevance sıralı `items`, iki bütçenin uygulanmış değerlerini, ölçüm alanlarını ve
devam varsa opaque `next_cursor` değerini içerir. Sonraki sayfa için aynı query ve belgeyle bu
cursor'ı `cursor=...` olarak gönderin. Cursor farklı bir sorguda kullanılırsa kontrollü
`invalid_cursor` hatası döner.

## MCP bağlantısı

Streamable HTTP endpoint'i `http://127.0.0.1:8000/mcp` adresindedir. MCP istemcisinde URL ve
header tanımlama biçimi istemciye göre değişir. HTTP MCP bağlantılarında `X-API-Key` kabul
edilmez; Bearer token zorunludur:

```json
{
  "mcpServers": {
    "private-documents": {
      "type": "streamable-http",
      "url": "http://127.0.0.1:8000/mcp",
      "headers": {
        "Authorization": "Bearer your-mcp-token"
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

Önerilen araç akışı:

```text
AI aracı
  → search_document(query, top_k, max_tokens)
  → BM25 relevance sıralı chunk'lar
  → karakter + yaklaşık token bütçesi
  → document/chunk/position kaynak bilgileri
  → gerekirse next_cursor veya sınırlı get_document_section
```

Örnek `search_document` argümanları:

```json
{
  "document_id": "DOCUMENT_UUID",
  "query": "termination notice period",
  "top_k": 3,
  "max_chars": 4000,
  "max_tokens": 600,
  "neighbor_window": 0
}
```

Her retrieval item'ı aynı kaynak sözleşmesini kullanır:

```json
{
  "document_id": "DOCUMENT_UUID",
  "document_name": "agreement.pdf",
  "chunk_id": "CHUNK_UUID",
  "heading": "Termination",
  "position": {
    "chunk_index": 7,
    "char_start": 12840,
    "char_end": 14610,
    "page_number": null,
    "slide_number": null,
    "sheet_name": null
  },
  "score": 0.00001423,
  "content": "...bounded relevant content...",
  "content_length": 30,
  "token_count": 7,
  "relation": "match"
}
```

`neighbor_window` varsayılan olarak `0`'dır. Açıldığında önceki/sonraki chunk'lar da aynı toplam
`top_k`, `max_chars` ve `max_tokens` bütçesinden harcar. `next_cursor`, aynı araç ve sorguyla
sonraki relevance sayfasını almak içindir. `get_document_section` da cursor destekler ve tam
belge endpoint'i gibi davranmaz.

## Oracle Cloud production kurulumu

Önerilen yöntem, uygulamayı yalnızca `127.0.0.1` üzerinde yayınlayıp Tailscale Serve ile tailnet
içine açmaktır. Alternatif public yöntem Caddy otomatik HTTPS profilidir. Her iki yöntemde de
Bearer token zorunlu kalır ve uygulamanın 8000 portu genel internete açılmaz.

VM hazırlama, ARM64 notları, Docker kurulumu, OCI NSG/firewall, Tailscale, Caddy, kalıcı klasör
izinleri, backup/restore, güncelleme ve sorun giderme adımları için
[Oracle production deployment rehberine](docs/oracle-deployment.md) bakın.

## Güvenlik notları

- API anahtarı response veya uygulama loguna yazılmaz; `.env` git tarafından dışlanır.
- HTTP MCP yalnızca Bearer token kabul eder; token listesi environment veya `/run/secrets`
  dosyasından okunabilir ve rotation için geçici olarak iki token aktif tutulabilir.
- Dosya adı yalnızca metadata'dır. Disk yolu UUID + doğrulanmış uzantıdan oluşur.
- Uzantı, MIME ve temel dosya imzası birlikte kontrol edilir. Office archive'larında açılmış
  toplam boyut limiti uygulanır.
- Maksimum upload boyutu stream sırasında uygulanır; kısmi dosya hata halinde silinir.
- HTTP request body, rate limit, dönüşüm concurrency/timeout ve FTS search timeout sınırları
  birbirinden bağımsız uygulanır.
- MarkItDown yalnızca saklanan yerel UUID yolunda çalışır; MVP URL kabul etmez.
- CORS varsayılan olarak kapalıdır. Gerekiyorsa kesin origin listesi verin.
- MCP DNS-rebinding koruması exact Host allowlist ile çalışır.
- Silme işlemi raw dosyayı, Markdown cache'i, chunk kayıtlarını ve FTS satırlarını siler.
- JSON loglar query/body/header içermez; yalnızca allowlist işlem metadata'sı taşır.
- Public kurulumda TLS, firewall/rate limit ve düzenli yedekleme hâlâ operatör sorumluluğudur.

## Token tasarrufu

- SHA-256 aynı dosyayı ikinci kez dönüştürmeyi engeller.
- Markdown bir kez dönüştürülür ve volume'da önbelleğe alınır.
- Başlıkları koruyan token-aware chunk'lar FTS5/BM25 ile sıralanır; sadece ilgili metin döner.
- Başlık eşleşmesi içerik eşleşmesine göre daha yüksek BM25 ağırlığı alır.
- `top_k`, `max_chars`, `max_tokens`, cursor, `offset` ve `limit` sunucu tarafında üst
  sınırlara sahiptir.
- Büyük ölçüde örtüşen veya aynı chunk'lar bir MCP sayfasında tekrar edilmez.
- MCP'nin tam belge veya ham dosya döndüren bir varsayılan aracı yoktur.
- Chunk overlap düşük ve `PDG_CHUNK_OVERLAP_TOKENS` ile ayarlanabilir.

### Tekrarlanabilir ölçüm

Aşağıdaki değerler 24 Ağustos 2026 tarihinde, repodaki deterministik sentetik belgeyle ve
varsayılan `500/50` chunk ayarlarıyla gerçek upload → MarkItDown cache → FTS5 → REST retrieval
akışından ölçülmüştür. Token değerleri uygulamanın yaklaşık token estimator'ına aittir; başka
belgeler veya model tokenizer'ları için genellenmez.

```bash
.venv/bin/python scripts/measure_retrieval.py
```

| Ölçüm | Gözlenen değer |
|---|---:|
| Tam belgenin yaklaşık token sayısı | 5920 |
| Retrieval'ın döndürdüğü yaklaşık token sayısı | 240 |
| Döndürülen chunk sayısı | 1 |
| Arama süresi | 4.279 ms |
| Cache kullanıldı | evet |
| Bu fixture için ölçülen token azalması | %95.95 |

Arama süresi donanım, SQLite cache durumu ve container yüküne göre değişir. Ölçüm komutu aynı
tabloyla birlikte güncel sonucu JSON olarak üretir; README yüzdesi yalnızca yukarıdaki koşullar
için bir gözlemdir.

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

### ADR-004 — Yerel FTS5 ve model-bağımsız token tahmini

Sprint 2 araması harici bir vector servisi yerine SQLite FTS5'in `unicode61` tokenizer'ı ve
başlık ağırlıklı BM25 skoru üzerine kuruludur. `SearchIndex` sınırı ileride hybrid/semantic bir
adaptör eklenebilmesi için servis katmanından ayrıdır. Token bütçesi sağlayıcı SDK'sına bağlı
olmayan deterministik bir tahminle uygulanır; ürünün OpenAI, Claude veya başka bir LLM'e zorunlu
bağımlılığı yoktur.

### ADR-005 — Private-first production erişimi

Production Compose uygulamayı yalnızca loopback'e bind eder. Önerilen Tailscale Serve kurulumu
tailnet ACL ve HTTPS termination sağlar. Genel erişim gerektiğinde standart, multi-arch Caddy
image'ı ayrı profile ile 80/443'ü açar; gateway yalnızca internal Docker network üzerinden proxy
edilir. Rate limit uygulamada token/istemci bazlıdır ve Caddy request-size/timeout katmanıyla
birlikte çalışır.

## Yol haritası

- Background job/worker ve işlem progress'i
- Opsiyonel hybrid/semantic search ve pgvector/Qdrant adaptörleri
- PostgreSQL repository ve çoklu instance profili
- S3/MinIO uyumlu opsiyonel storage adaptörü
- OCR için tamamen yerel, opsiyonel adapter
- API key rotation, rate limit ve audit metadata (belge içeriği olmadan)
- İsteğe bağlı tenant/ACL modeli
