#!/bin/bash
# Testa o YouTube pelo IPv4 e pelo IPv6 do servidor; se o IPv6 passar, liga o Rigel nele. Rode como root:
#   bash /opt/rigel/consertar-youtube.sh
cd /opt/rigel && git pull -q
URL=${1:-https://www.youtube.com/watch?v=JV9b81aszAQ}
IMG=$(docker compose images rigel -q 2>/dev/null | head -1); IMG=${IMG:-rigel-rigel}
teste(){ docker run --rm --network host --entrypoint yt-dlp "$IMG" "$1" --simulate --print title "$URL" >/dev/null 2>&1 && echo OK || echo BARRADO; }
echo "IPv4: $(teste -4)"
R6=$(teste -6); echo "IPv6: $R6"
if [ "$R6" != OK ]; then
  echo; echo "RESULTADO: YouTube barra os dois. Caminho que resta: cookies (Configuracoes do Rigel)."; exit 0
fi
cat > docker-compose.override.yml <<'YML'
networks:
  default:
    enable_ipv6: true
    ipam:
      config:
        - subnet: fd52:6967:656c::/64
YML
sed -i '/^RIGEL_YT_IPV6=/d' .env; echo "RIGEL_YT_IPV6=1" >> .env
docker compose down && docker compose up -d --build
sleep 8
if docker compose exec -T rigel yt-dlp -6 --simulate --print title "$URL" >/dev/null 2>&1; then
  echo; echo "RESULTADO: YOUTUBE OK pelo IPv6. Pode baixar pelo link no Rigel."
else
  echo; echo "RESULTADO: IPv6 passou fora, mas nao dentro do Rigel. Avise o Claude: 'IPv6 dentro falhou'."
fi
