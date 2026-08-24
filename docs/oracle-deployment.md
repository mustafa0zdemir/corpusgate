# Oracle Cloud Ubuntu production deployment

Bu rehber CorpusGate `0.1.x` sürümünü tek Oracle Cloud Ubuntu VM üzerinde kalıcı
ve güvenli çalıştırır. Önerilen erişim Tailscale'dir. Public domain yalnızca gerçekten gerekliyse
Caddy profiliyle açılmalıdır.

## 1. VM ve ağ hazırlığı

- Ubuntu 24.04 LTS kullanın.
- AMD64 şekilleri ve Ampere A1/A2 ARM64 şekilleri desteklenir. Docker tabanı ile Python/bağımlılık
  image'ları iki mimari için yayınlanır.
- Boot volume boyutunu belge büyümesine göre seçin ve OCI snapshot politikası tanımlayın.
- SSH ingress'i yalnızca yönetici IP'nizle sınırlandırın.
- **8000/TCP için hiçbir OCI Security List veya NSG ingress kuralı eklemeyin.**
- Tailscale yönteminde uygulama için 80/443 ingress gerekmez; Tailscale dışarı doğru bağlantı
  kurar. Public Caddy yönteminde yalnızca 80/TCP, 443/TCP ve HTTP/3 isteniyorsa 443/UDP açılır.

OCI Security List/NSG ile host firewall birlikte değerlendirilmelidir. Docker published port'ları
host firewall beklentilerini aşabildiği için gateway yalnızca `127.0.0.1` adresine bind edilir.

## 2. Docker Engine ve Compose kurulumu

Docker'ın resmi Ubuntu apt deposunu kullanın:

```bash
sudo apt update
sudo apt install -y ca-certificates curl git
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

sudo tee /etc/apt/sources.list.d/docker.sources >/dev/null <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF

sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
sudo docker run --rm hello-world
```

Docker grubuna kullanıcı eklemek root eşdeğeri yetki verir. Bu tercihi bilinçli yapın; rehberdeki
komutlar `sudo docker` ile de çalışır.

## 3. Repo ve kalıcı klasörler

```bash
sudo install -d -o "$USER" -g "$USER" -m 0750 /opt/corpusgate
git clone https://github.com/mustafa0zdemir/corpusgate.git \
  /opt/corpusgate
cd /opt/corpusgate

sudo install -d -o 10001 -g 10001 -m 0700 \
  /srv/corpusgate/documents \
  /srv/corpusgate/cache \
  /srv/corpusgate/database \
  /srv/corpusgate/backups
install -d -m 0750 /srv/corpusgate/inbox
install -d -m 0700 secrets
```

Container UID/GID değeri `10001:10001`'dir. Bind mount klasörlerinin başka kullanıcıya ait veya
group/world writable olması startup sırasında kontrollü biçimde reddedilir.

## 4. Secret ve `.env`

REST anahtarı ile MCP Bearer token'ı farklı üretin:

```bash
cp .env.example .env
openssl rand -hex 32
openssl rand -hex 32 > secrets/mcp_auth_token
chmod 0600 .env secrets/mcp_auth_token
```

İlk komutun stdout değerini `.env` içindeki `CORPUSGATE_API_KEY` alanına yazın. İkinci değer yalnızca
Docker secret dosyasında kalır. Production `.env` için en az şu alanları düzenleyin:

```dotenv
CORPUSGATE_API_KEY=REPLACE_WITH_REST_KEY
CORPUSGATE_MCP_AUTH_TOKENS=
CORPUSGATE_MCP_AUTH_TOKEN_HOST_FILE=./secrets/mcp_auth_token
CORPUSGATE_INBOX_HOST_PATH=/srv/corpusgate/inbox
CORPUSGATE_DOCUMENTS_HOST_PATH=/srv/corpusgate/documents
CORPUSGATE_CACHE_HOST_PATH=/srv/corpusgate/cache
CORPUSGATE_DATABASE_HOST_PATH=/srv/corpusgate/database
CORPUSGATE_BACKUP_HOST_PATH=/srv/corpusgate/backups
CORPUSGATE_ALLOWED_HOSTS=localhost,localhost:*,127.0.0.1,127.0.0.1:*,YOUR_PRIVATE_HOST
CORPUSGATE_LOG_LEVEL=INFO
```

Token rotation sırasında secret dosyasına `new-token,previous-token` yazıp gateway'i yeniden
oluşturun. İstemciler yeni token'a geçtikten sonra eski token'ı dosyadan kaldırıp tekrar oluşturun:

```bash
docker compose -f compose.prod.yaml up -d --force-recreate gateway
```

## 5. Yapılandırmayı doğrulama ve başlatma

```bash
docker compose -f compose.prod.yaml config --quiet
docker compose -f compose.prod.yaml build gateway
docker compose -f compose.prod.yaml up -d gateway
docker compose -f compose.prod.yaml ps
curl --fail http://127.0.0.1:8000/health
curl --fail http://127.0.0.1:8000/ready
docker compose -f compose.prod.yaml exec -T gateway corpusgate-admin doctor
```

Beklenen cevaplar sırasıyla `{"status":"ok"}` ve `{"status":"ready"}` biçimindedir. `health`
yalnızca process liveness, `ready` ise SQLite ve yazılabilir storage durumunu gösterir.

## 6. Önerilen: Tailscale ile private erişim

Tailscale'i resmi Linux paket yöntemiyle kurup node'u tailnet'e ekleyin. Gateway loopback'te
çalışırken Serve'i etkinleştirin:

```bash
sudo tailscale up
sudo tailscale serve --bg --https=443 http://127.0.0.1:8000
tailscale serve status
```

Serve URL'sindeki MagicDNS host'unu `CORPUSGATE_ALLOWED_HOSTS` içine ekleyip gateway'i yeniden oluşturun.
Tailnet ACL ile yalnızca gereken kullanıcı/cihazların 443'e erişmesine izin verin. Funnel
kullanmayın; Funnel servisi public internete açar.

MCP istemci örneği:

```json
{
  "mcpServers": {
    "corpusgate": {
      "type": "streamable-http",
      "url": "https://YOUR-NODE.YOUR-TAILNET.ts.net/mcp",
      "headers": {
        "Authorization": "Bearer YOUR_MCP_TOKEN"
      }
    }
  }
}
```

## 7. Alternatif: public domain ve Caddy HTTPS

Domain'in A/AAAA kaydını VM'e yönlendirin. OCI NSG'de 80/TCP ve 443/TCP açın; 8000 kapalı
kalır. `.env` alanlarını doldurun:

```dotenv
CORPUSGATE_PUBLIC_DOMAIN=documents.example.com
CORPUSGATE_PUBLIC_BASE_URL=https://documents.example.com
CADDY_EMAIL=admin@example.com
CORPUSGATE_ALLOWED_HOSTS=documents.example.com,documents.example.com:*
```

Ardından public profili başlatın:

```bash
docker compose -f compose.prod.yaml --profile public up -d --build
curl --fail https://documents.example.com/health
```

Caddy otomatik TLS termination, güvenlik header'ları, request body limiti ve MCP streaming için
düşük gecikmeli flush uygular. Uygulama ayrıca Bearer auth, rate limit ve response budget uygular.
Caddy access log'u özellikle açılmamıştır; query string'in loglara sızması engellenir.

## 8. Operasyonlar

Yapılandırılmış logları görüntüleme:

```bash
docker compose -f compose.prod.yaml logs --tail=100 gateway
docker compose -f compose.prod.yaml logs -f gateway
```

Restart:

```bash
docker compose -f compose.prod.yaml restart gateway
```

Güncelleme:

```bash
docker compose -f compose.prod.yaml stop gateway
docker compose -f compose.prod.yaml run --rm --no-deps gateway \
  corpusgate-admin backup
git pull --ff-only
docker compose -f compose.prod.yaml build --pull gateway
docker compose -f compose.prod.yaml up -d gateway
curl --fail http://127.0.0.1:8000/ready
docker compose -f compose.prod.yaml exec -T gateway corpusgate-admin status
```

## 9. Backup, restore ve cache recovery

Tutarlı uygulama snapshot'ı için yazmaları durdurup one-off bakım komutunu çalıştırın:

```bash
docker compose -f compose.prod.yaml stop gateway
docker compose -f compose.prod.yaml run --rm --no-deps gateway \
  corpusgate-admin backup
docker compose -f compose.prod.yaml start gateway
sudo tar -tzf /srv/corpusgate/backups/corpusgate-backup-TIMESTAMP.tar.gz
```

Arşiv documents, Markdown cache, SQLite'ın online backup snapshot'ı, manifest ve secretsız
`.env.example` içerir. Gerçek `.env` ve token dosyası arşive alınmaz; bunları ayrı bir secret
manager veya şifreli offline kasada saklayın.

Restore mevcut kalıcı veriyi değiştirir; gateway kapalıyken açık onay bayrağı gerekir:

```bash
docker compose -f compose.prod.yaml stop gateway
docker compose -f compose.prod.yaml run --rm --no-deps gateway \
  corpusgate-admin restore \
  /backups/corpusgate-backup-TIMESTAMP.tar.gz --confirm-restore
docker compose -f compose.prod.yaml start gateway
curl --fail http://127.0.0.1:8000/ready
```

Yalnızca Markdown cache kaybolduysa raw documents ve SQLite metadata'dan yeniden üretin:

```bash
docker compose -f compose.prod.yaml stop gateway
docker compose -f compose.prod.yaml run --rm --no-deps gateway \
  corpusgate-reindex-cache
docker compose -f compose.prod.yaml start gateway
```

Tek bozuk belge `failed` sayılır; diğer belgelerin rebuild işlemi devam eder.

## 10. Semantic profil

Semantic/hybrid özellik isteğe bağlıdır. Oracle Ampere A1 için önce en az 6 GB RAM ayırın; model
ve kendi corpus ölçümlerinize göre limitleri ayarlayın. Modeli bir kez indirip gateway'i offline
başlatın:

```bash
docker compose -f compose.prod.yaml -f compose.semantic.yaml \
  --profile semantic-setup run --rm model-downloader
docker compose -f compose.prod.yaml -f compose.semantic.yaml up -d --build gateway qdrant
docker compose -f compose.prod.yaml -f compose.semantic.yaml ps
```

OCI firewall'da Qdrant `6333` için ingress açmayın; port yalnız internal Docker network'tedir.
`model_cache` ve `vector_data` volume'larını güncellemede silmeyin. Semantic özelliği kapatmak için
normal `docker compose -f compose.prod.yaml up -d gateway` komutuna dönün. Ayrıntılar ve offline
model taşıma adımları [semantic search rehberindedir](semantic-search.md).

## 11. Sorun giderme

- `invalid owner` / `not writable`: `/srv/corpusgate` alt klasörlerini
  `10001:10001`, `0700` yapın.
- `401`: MCP'de `Authorization: Bearer ...`; REST'te `X-API-Key` kullanıldığını doğrulayın.
- `421` veya host hatası: URL host'unu exact biçimde `CORPUSGATE_ALLOWED_HOSTS` listesine ekleyin.
- `429`: istemci çağrı hızını düşürün veya kontrollü biçimde rate limit ayarını değiştirin.
- `507`: disk alanı ile `CORPUSGATE_MIN_FREE_DISK_MB` rezervini kontrol edin.
- `unhealthy`: `docker compose ... logs gateway`, `/health` ve `/ready` cevaplarını ayrı inceleyin.
- Caddy sertifika sorunu: DNS, OCI 80/443 kuralları ve `CADDY_EMAIL` değerini doğrulayın.
- ARM64 build sorunu: `uname -m`, `docker version` ve `docker buildx inspect` çıktılarını kontrol
  edin; repo platforma özel binary kopyalamaz.
