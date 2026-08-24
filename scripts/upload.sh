#!/bin/sh
set -eu

project_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$project_root"
umask 077

usage() {
    cat <<'EOF'
Usage: ./corpusgate upload FILE [--url BASE_URL] [--api-key-env NAME] [--timeout SECONDS]

Streams FILE directly to CorpusGate's REST upload endpoint. Remote URLs must use HTTPS;
plain HTTP is accepted only for localhost. The API key is read from the named environment
variable, CORPUSGATE_API_KEY, or the local .env file and is never printed.
EOF
}

if [ "$#" -eq 0 ]; then
    usage >&2
    exit 2
fi
if [ "$1" = "-h" ] || [ "$1" = "--help" ]; then
    usage
    exit 0
fi

file_path=$1
shift
base_url=${CORPUSGATE_BASE_URL:-}
api_key_env=CORPUSGATE_CLIENT_API_KEY
timeout=${CORPUSGATE_UPLOAD_TIMEOUT_SECONDS:-180}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --url)
            [ "$#" -ge 2 ] || { echo "--url requires a value." >&2; exit 2; }
            base_url=$2
            shift 2
            ;;
        --api-key-env)
            [ "$#" -ge 2 ] || { echo "--api-key-env requires a value." >&2; exit 2; }
            api_key_env=$2
            shift 2
            ;;
        --timeout)
            [ "$#" -ge 2 ] || { echo "--timeout requires a value." >&2; exit 2; }
            timeout=$2
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown upload option: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

command -v curl >/dev/null 2>&1 || {
    echo "curl is required for direct document upload." >&2
    exit 1
}

[ -e "$file_path" ] || { echo "Upload file does not exist." >&2; exit 2; }
[ ! -L "$file_path" ] || { echo "Symlink uploads are not allowed." >&2; exit 2; }
[ -f "$file_path" ] || { echo "Upload target must be a regular file." >&2; exit 2; }
[ -r "$file_path" ] || { echo "Upload file is not readable." >&2; exit 2; }

file_name=$(basename -- "$file_path")
case "$file_name" in
    .*|~\$*|*~) echo "Hidden and temporary files cannot be uploaded." >&2; exit 2 ;;
    *';'*|*','*|*'"'*) echo "The filename contains unsupported punctuation." >&2; exit 2 ;;
esac
if printf '%s' "$file_name" | LC_ALL=C grep -q '[[:cntrl:]]'; then
    echo "The filename contains an invalid control character." >&2
    exit 2
fi

extension=${file_name##*.}
extension=$(printf '%s' "$extension" | tr '[:upper:]' '[:lower:]')
case "$extension" in
    pdf) content_type=application/pdf ;;
    docx) content_type=application/vnd.openxmlformats-officedocument.wordprocessingml.document ;;
    pptx) content_type=application/vnd.openxmlformats-officedocument.presentationml.presentation ;;
    xlsx) content_type=application/vnd.openxmlformats-officedocument.spreadsheetml.sheet ;;
    txt) content_type=text/plain ;;
    md|markdown) content_type=text/markdown ;;
    html|htm) content_type=text/html ;;
    *) echo "Unsupported file extension: .$extension" >&2; exit 2 ;;
esac

read_env_value() {
    [ -f .env ] || return 0
    awk -F= -v key="$1" '$1 == key { sub(/^[^=]*=/, ""); sub(/\r$/, ""); print; exit }' .env
}

if [ -z "$base_url" ]; then
    base_url=${CORPUSGATE_PUBLIC_BASE_URL:-}
fi
if [ -z "$base_url" ]; then
    base_url=$(read_env_value CORPUSGATE_PUBLIC_BASE_URL)
fi
if [ -z "$base_url" ]; then
    port=${CORPUSGATE_PORT:-}
    if [ -z "$port" ]; then
        port=$(read_env_value CORPUSGATE_PORT)
    fi
    port=${port:-8000}
    base_url="http://127.0.0.1:$port"
fi
base_url=${base_url%/}

case "$base_url" in
    *'?'*|*'#'*) echo "Upload URL must not contain a query or fragment." >&2; exit 2 ;;
esac
case "$base_url" in
    https://*) ;;
    http://127.0.0.1|http://127.0.0.1:*|http://localhost|http://localhost:*|http://\[::1\]|http://\[::1\]:*) ;;
    http://*) echo "Remote document uploads require HTTPS." >&2; exit 2 ;;
    *) echo "Upload URL must use HTTPS or localhost HTTP." >&2; exit 2 ;;
esac

authority=${base_url#*://}
case "$authority" in
    '') echo "Upload URL must include a host." >&2; exit 2 ;;
    *@*) echo "Credentials must not be embedded in the upload URL." >&2; exit 2 ;;
    */*) echo "--url must be a server base URL without a path." >&2; exit 2 ;;
esac

case "$timeout" in
    *[!0-9]*|'') echo "Upload timeout must be a positive integer." >&2; exit 2 ;;
esac
if [ "$timeout" -lt 1 ] || [ "$timeout" -gt 3600 ]; then
    echo "Upload timeout must be between 1 and 3600 seconds." >&2
    exit 2
fi

case "$api_key_env" in
    ''|[0-9]*|*[!A-Za-z0-9_]*)
        echo "--api-key-env must be a valid environment variable name." >&2
        exit 2
        ;;
esac

api_key=$(printenv "$api_key_env" 2>/dev/null || true)
if [ -z "$api_key" ] && [ "$api_key_env" = CORPUSGATE_CLIENT_API_KEY ]; then
    api_key=${CORPUSGATE_API_KEY:-}
    if [ -z "$api_key" ]; then
        api_key=$(read_env_value CORPUSGATE_API_KEY)
    fi
fi
if [ -z "$api_key" ]; then
    echo "API key is unavailable; set $api_key_env." >&2
    exit 2
fi

header_file=$(mktemp "${TMPDIR:-/tmp}/corpusgate-upload-header.XXXXXX")
trap 'rm -f "$header_file"' EXIT HUP INT TERM
chmod 600 "$header_file"
printf '%s\n' "X-API-Key: $api_key" > "$header_file"
unset api_key

curl \
    --silent \
    --show-error \
    --fail-with-body \
    --connect-timeout 10 \
    --max-time "$timeout" \
    --header "@$header_file" \
    --form "file=@-;filename=$file_name;type=$content_type" \
    "$base_url/api/v1/documents" < "$file_path"
printf '\n'
