#!/usr/bin/env bash
# Deploy SearXNG to a Hetzner VPS instance.
#
# SSHs into the VPS, installs Docker if needed, pulls the SearXNG image,
# deploys with custom settings.yml, sets up nginx auth reverse proxy,
# and runs a health check.
#
# Usage:
#   ./scripts/deploy_searxng.sh <VPS_IP> [SETTINGS_FILE]
#
# Environment variables:
#   SEARXNG_AUTH_TOKEN  — Auth token for API gateway communication (required)
#   SSH_KEY_PATH        — Path to SSH private key (default: ~/.ssh/id_ed25519)

set -euo pipefail

VPS_IP="${1:?Usage: deploy_searxng.sh <VPS_IP> [SETTINGS_FILE]}"
SETTINGS_FILE="${2:-}"
AUTH_TOKEN="${SEARXNG_AUTH_TOKEN:?Error: SEARXNG_AUTH_TOKEN environment variable is required}"
SSH_KEY="${SSH_KEY_PATH:-$HOME/.ssh/id_ed25519}"
SSH_OPTS="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=30 -i ${SSH_KEY}"

echo "==> Deploying SearXNG to ${VPS_IP}"

# --- Wait for SSH ---
echo "==> Waiting for SSH..."
for i in $(seq 1 30); do
    if ssh ${SSH_OPTS} root@"${VPS_IP}" "echo ok" &>/dev/null; then
        break
    fi
    if [[ $i -eq 30 ]]; then
        echo "Error: SSH not available after 90 seconds" >&2
        exit 1
    fi
    sleep 3
done

echo "==> Waiting for cloud-init to finish..."
ssh ${SSH_OPTS} root@"${VPS_IP}" "cloud-init status --wait || true"

# --- Install Docker if needed ---
echo "==> Checking Docker installation..."
ssh ${SSH_OPTS} root@"${VPS_IP}" bash <<'INSTALL_DOCKER'
if ! command -v docker &>/dev/null; then
    echo "  Installing Docker..."
    apt-get update -qq
    apt-get install -y -qq docker.io
    systemctl enable docker
    systemctl start docker
    echo "  Docker installed."
else
    echo "  Docker already installed."
fi
INSTALL_DOCKER

# --- Upload or generate settings.yml ---
ssh ${SSH_OPTS} root@"${VPS_IP}" "mkdir -p /opt/searchclaw"

if [[ -n "$SETTINGS_FILE" ]] && [[ -f "$SETTINGS_FILE" ]]; then
    echo "==> Uploading custom settings.yml..."
    scp ${SSH_OPTS} "$SETTINGS_FILE" root@"${VPS_IP}":/opt/searchclaw/settings.yml
else
    echo "==> Generating default settings.yml on VPS..."
    ssh ${SSH_OPTS} root@"${VPS_IP}" bash <<'GEN_SETTINGS'
SECRET_KEY=$(openssl rand -hex 32)
cat > /opt/searchclaw/settings.yml <<SETTINGS
general:
  instance_name: "SearchClaw External Node"
  debug: false

search:
  safe_search: 1
  default_lang: "en"
  formats:
    - json

server:
  secret_key: "${SECRET_KEY}"
  limiter: false
  image_proxy: false
  method: "GET"
  bind_address: "0.0.0.0"
  port: 8080

outgoing:
  request_timeout: 5.0
  max_request_timeout: 10.0
  useragent_suffix: ""

engines:
  - name: google
    engine: google
    shortcut: g
    disabled: false
    weight: 1.2
  - name: bing
    engine: bing
    shortcut: b
    disabled: false
    weight: 1.0
  - name: duckduckgo
    engine: duckduckgo
    shortcut: ddg
    disabled: false
    weight: 0.9
  - name: brave
    engine: brave
    shortcut: br
    disabled: false
    weight: 1.0
  - name: wikipedia
    engine: wikipedia
    shortcut: wp
    disabled: false
    weight: 0.8
  - name: wikidata
    engine: wikidata
    shortcut: wd
    disabled: false
  - name: yahoo
    disabled: true
  - name: qwant
    disabled: true
SETTINGS
echo "  settings.yml generated."
GEN_SETTINGS
fi

# --- Pull and deploy SearXNG container ---
echo "==> Pulling SearXNG image..."
ssh ${SSH_OPTS} root@"${VPS_IP}" "docker pull searxng/searxng:latest"

echo "==> Deploying SearXNG container..."
ssh ${SSH_OPTS} root@"${VPS_IP}" bash <<'DEPLOY_CONTAINER'
docker stop searxng 2>/dev/null || true
docker rm searxng 2>/dev/null || true
docker run -d \
    --name searxng \
    --restart unless-stopped \
    -p 127.0.0.1:8080:8080 \
    -v /opt/searchclaw/settings.yml:/etc/searxng/settings.yml:ro \
    searxng/searxng:latest
DEPLOY_CONTAINER
echo "  SearXNG container deployed on 127.0.0.1:8080."

# --- Set up nginx reverse proxy with auth token ---
echo "==> Configuring nginx auth proxy..."
ssh ${SSH_OPTS} root@"${VPS_IP}" bash -s -- "${AUTH_TOKEN}" <<'NGINX_SETUP'
AUTH_TOKEN="$1"
apt-get install -y -qq nginx

cat > /etc/nginx/sites-available/searxng <<NGINX_CONF
server {
    listen 8888;

    # Authenticated endpoint — requires X-SearchClaw-Token header
    location / {
        if (\$http_x_searchclaw_token != "${AUTH_TOKEN}") {
            return 403;
        }
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_read_timeout 15s;
    }

    # Health check endpoint — no auth required
    location /healthz {
        proxy_pass http://127.0.0.1:8080/healthz;
        proxy_set_header Host \$host;
    }
}
NGINX_CONF

rm -f /etc/nginx/sites-enabled/default
ln -sf /etc/nginx/sites-available/searxng /etc/nginx/sites-enabled/searxng
nginx -t
systemctl enable nginx
systemctl restart nginx
echo "  Nginx auth proxy configured on port 8888."
NGINX_SETUP

# --- Health check ---
echo "==> Waiting for SearXNG to start..."
sleep 8

echo "==> Running health check..."
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
    "http://${VPS_IP}:8888/healthz" 2>/dev/null || echo "000")

if [[ "${HTTP_CODE}" == "200" ]]; then
    echo "==> Health check passed (HTTP ${HTTP_CODE})"
else
    echo "==> Health check returned HTTP ${HTTP_CODE} (may still be starting)"
    echo "    Retry in ~30s: curl http://${VPS_IP}:8888/healthz"
fi

# Verify auth is working
AUTH_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
    -H "X-SearchClaw-Token: ${AUTH_TOKEN}" \
    "http://${VPS_IP}:8888/search?q=test&format=json" 2>/dev/null || echo "000")

NOAUTH_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
    "http://${VPS_IP}:8888/search?q=test&format=json" 2>/dev/null || echo "000")

echo ""
echo "==> Deployment complete!"
echo "  SearXNG endpoint: http://${VPS_IP}:8888"
echo "  Auth header: X-SearchClaw-Token: <your-token>"
echo "  Health check (no auth): http://${VPS_IP}:8888/healthz"
echo "  Auth test: with_token=${AUTH_CODE}, without_token=${NOAUTH_CODE}"
echo ""
echo "  Add to SEARXNG_URLS in your API gateway config:"
echo "    http://${VPS_IP}:8888"
