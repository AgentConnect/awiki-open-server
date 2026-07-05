#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="${REPO_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
WORKSPACE_DIR="${WORKSPACE_DIR:-$(cd "$REPO_DIR/.." && pwd)}"
RUN_USER="${RUN_USER:-$(id -un)}"
RUN_GROUP="${RUN_GROUP:-$(id -gn)}"
PORT="${PORT:-8766}"
DOMAIN="${DOMAIN:-rwiki.cn}"
BASE_URL="${BASE_URL:-https://rwiki.cn}"
SERVICE_DID="${SERVICE_DID:-did:wba:rwiki.cn}"
CONFIG_DIR="${CONFIG_DIR:-/etc/awiki-open-server}"
DATA_DIR="${DATA_DIR:-/var/lib/awiki-open-server}"
ENV_FILE="${ENV_FILE:-$CONFIG_DIR/awiki-open-server.env}"
KEY_FILE="${KEY_FILE:-$CONFIG_DIR/rwiki-service-ed25519.pem}"
SYSTEMD_UNIT="${SYSTEMD_UNIT:-/etc/systemd/system/awiki-open-server.service}"
NGINX_CONF="${NGINX_CONF:-/etc/nginx/conf.d/rwiki.cn.conf}"
CERT_FILE="${CERT_FILE:-/etc/nginx/25883699_rwiki.cn_nginx/rwiki.cn.pem}"
CERT_KEY_FILE="${CERT_KEY_FILE:-/etc/nginx/25883699_rwiki.cn_nginx/rwiki.cn.key}"
PYTHON_BIN="${PYTHON_BIN:-/usr/bin/python3}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run with sudo or as root." >&2
  exit 1
fi

timestamp="$(date +%Y%m%d%H%M%S)"

backup_if_exists() {
  local path="$1"
  if [[ -e "$path" ]]; then
    cp "$path" "${path}.bak-${timestamp}"
  fi
}

install -d -m 0750 -o "$RUN_USER" -g "$RUN_GROUP" "$DATA_DIR"
install -d -m 0750 -o root -g "$RUN_GROUP" "$CONFIG_DIR"

if [[ ! -f "$KEY_FILE" ]]; then
  umask 077
  "$PYTHON_BIN" - <<PY > "$KEY_FILE"
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, NoEncryption
key = ed25519.Ed25519PrivateKey.generate()
print(key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()).decode(), end="")
PY
  chown root:"$RUN_GROUP" "$KEY_FILE"
  chmod 0640 "$KEY_FILE"
fi

backup_if_exists "$ENV_FILE"
cat > "$ENV_FILE" <<EOF
AWIKI_DATA_DIR=$DATA_DIR
AWIKI_PUBLIC_BASE_URL=$BASE_URL
AWIKI_DID_DOMAIN=$DOMAIN
AWIKI_SERVICE_DID=$SERVICE_DID
AWIKI_SERVICE_PRIVATE_KEY_PATH=$KEY_FILE
AWIKI_ANP_PUBLIC_RPC_PATH=/anp-im/rpc
AWIKI_ALLOW_UNSIGNED_PEER_DEV=false
AWIKI_ENABLE_CONTACT_VERIFICATION_COMPAT=false
EOF
chown root:"$RUN_GROUP" "$ENV_FILE"
chmod 0640 "$ENV_FILE"

pythonpath="$WORKSPACE_DIR/anp/anp:$REPO_DIR/src:/home/$RUN_USER/.local/lib/python3.10/site-packages"

backup_if_exists "$SYSTEMD_UNIT"
cat > "$SYSTEMD_UNIT" <<EOF
[Unit]
Description=Awiki Open Server
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$RUN_USER
Group=$RUN_GROUP
WorkingDirectory=$REPO_DIR
EnvironmentFile=$ENV_FILE
Environment=PYTHONPATH=$pythonpath
Environment=HOME=/home/$RUN_USER
ExecStart=$PYTHON_BIN -m uvicorn awiki_open_server.app.main:create_app --factory --host 127.0.0.1 --port $PORT
Restart=on-failure
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

backup_if_exists "$NGINX_CONF"
sed \
  -e "s#/etc/nginx/ssl/rwiki.cn.pem#$CERT_FILE#g" \
  -e "s#/etc/nginx/ssl/rwiki.cn.key#$CERT_KEY_FILE#g" \
  "$REPO_DIR/deploy/nginx-rwiki.cn.conf.example" > "$NGINX_CONF"

systemctl daemon-reload
systemctl enable awiki-open-server.service
nginx -t
systemctl restart awiki-open-server.service
systemctl reload nginx

systemctl --no-pager --full status awiki-open-server.service | sed -n '1,20p'
echo "Installed awiki-open-server for $BASE_URL on 127.0.0.1:$PORT"
