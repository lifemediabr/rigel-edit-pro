#!/bin/bash
# Rigel atras do nginx (quando o Orion Full esta na mesma maquina). Rode como root, DEPOIS de instalar o Full:
#   bash /opt/rigel/atras-do-nginx.sh
set -e
cd /opt/rigel && git pull -q
command -v nginx >/dev/null || { echo "nginx nao encontrado: instale o Full antes."; exit 1; }
sed -i '/^COMPOSE_PROFILES=/d' .env
docker compose stop caddy 2>/dev/null || true; docker compose rm -f caddy 2>/dev/null || true
docker compose up -d --build --remove-orphans
DOM=$(grep ^DOMINIO .env | cut -d= -f2)
cat > /etc/nginx/sites-available/rigel <<CONF
server {
	listen 80;
	server_name $DOM;
	client_max_body_size 20G;
	proxy_request_buffering off;
	proxy_read_timeout 2h;
	proxy_send_timeout 2h;
	location / {
		proxy_pass http://127.0.0.1:8800;
		proxy_set_header Host \$host;
		proxy_set_header X-Forwarded-Proto \$scheme;
		proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
	}
}
CONF
ln -sf /etc/nginx/sites-available/rigel /etc/nginx/sites-enabled/rigel
nginx -t && systemctl reload nginx
certbot --nginx -d "$DOM" --non-interactive --agree-tos --register-unsafely-without-email --redirect
echo; echo "PRONTO. Rigel em https://$DOM"
