#!/bin/sh
set -eu

project_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$project_root"
umask 077

semantic=false
if [ "${1:-}" = "--semantic" ]; then
    semantic=true
elif [ "$#" -gt 0 ]; then
    echo "Usage: ./corpusgate init [--semantic]" >&2
    exit 2
fi

command -v docker >/dev/null 2>&1 || {
    echo "Docker is required but was not found." >&2
    exit 1
}
docker compose version >/dev/null 2>&1 || {
    echo "Docker Compose v2 is required but is not available." >&2
    exit 1
}
command -v openssl >/dev/null 2>&1 || {
    echo "OpenSSL is required to generate authentication tokens." >&2
    exit 1
}

mkdir -p documents state/documents state/cache state/database backups secrets
chmod 700 state/documents state/cache state/database backups secrets
chmod 750 documents

if [ -e .env ]; then
    echo "Existing .env preserved."
else
    api_key=$(openssl rand -hex 32)
    mcp_token=$(openssl rand -hex 32)
    temporary_env=$(mktemp "${TMPDIR:-/tmp}/corpusgate-env.XXXXXX")
    while IFS= read -r line || [ -n "$line" ]; do
        case "$line" in
            CORPUSGATE_API_KEY=*) printf '%s\n' "CORPUSGATE_API_KEY=$api_key" ;;
            CORPUSGATE_MCP_AUTH_TOKENS=*) printf '%s\n' "CORPUSGATE_MCP_AUTH_TOKENS=$mcp_token" ;;
            *) printf '%s\n' "$line" ;;
        esac
    done < .env.example > "$temporary_env"
    mv "$temporary_env" .env
    chmod 600 .env
    printf '%s\n' "$mcp_token" > secrets/mcp_auth_token
    chmod 600 secrets/mcp_auth_token
    unset api_key mcp_token
    echo "Created .env and a production MCP token secret without printing their values."
fi

port=$(awk -F= '$1 == "CORPUSGATE_BIND_PORT" { print $2; exit }' .env | tr -d '[:space:]')
port=${port:-8000}
case "$port" in
    *[!0-9]*|'') echo "CORPUSGATE_BIND_PORT must be a valid port number." >&2; exit 1 ;;
esac
if command -v lsof >/dev/null 2>&1 && lsof -n -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "Port $port is already in use. Set CORPUSGATE_BIND_PORT in .env." >&2
    exit 1
fi

if grep -q 'replace-with-' .env; then
    echo "One or more placeholder settings remain in .env." >&2
    exit 1
fi

if [ "$semantic" = true ]; then
    available_kb=$(df -Pk . | awk 'NR == 2 { print $4 }')
    if [ "$available_kb" -lt 4194304 ]; then
        echo "Semantic setup needs at least 4 GiB of free disk space." >&2
        exit 1
    fi
    docker compose -f compose.yaml -f compose.semantic.yaml config >/dev/null
    echo "Semantic configuration validated; first start will download the local model."
else
    docker compose config >/dev/null
fi

if [ "$(id -u)" -ne 0 ] && [ "$(uname -s)" = "Linux" ]; then
    echo "Production bind mounts may require: sudo chown -R 10001:10001 state backups"
fi
if [ "$semantic" = true ]; then
    echo "Setup complete. Start with: ./corpusgate up --semantic"
else
    echo "Setup complete. Start with: ./corpusgate up"
fi
