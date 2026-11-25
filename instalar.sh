#!/bin/bash
# Rigel Edit Pro — instalador (Ubuntu 22/24, como root)
# Uso:  bash <(curl -fsSL https://raw.githubusercontent.com/lifemediabr/rigel-edit-pro/main/instalar.sh)
set -e
PASTA=/opt/rigel
echo "== Rigel Edit Pro: instalando =="
[ "$(id -u)" = 0 ] || { echo "Rode como root."; exit 1; }
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq && apt-get install -y -qq git curl openssl >/dev/null
command -v docker >/dev/null || curl -fsSL https://get.docker.com | sh
if [ -d $PASTA/.git ]; then git -C $PASTA pull -q; else git clone -q https://github.com/lifemediabr/rigel-edit-pro $PASTA; fi
cd $PASTA
if [ ! -f .env ]; then
  echo; echo "Agora as contas (digite aqui no console; as senhas nao aparecem na tela)."
  echo "Senha sem virgula e sem dois-pontos."
  read -rp "Endereco [rigel.orionplayout.live]: " DOM </dev/tty; DOM=${DOM:-rigel.orionplayout.live}
  USUARIOS=""
  while true; do
    read -rp "Nome do usuario (Enter vazio = terminar): " N </dev/tty
    [ -z "$N" ] && [ -n "$USUARIOS" ] && break
    [ -z "$N" ] && continue
    read -rsp "Senha de $N: " S </dev/tty; echo
    USUARIOS="${USUARIOS:+$USUARIOS,}$N:$S"
  done
  cat > .env <<FIM
DOMINIO=$DOM
RIGEL_USUARIOS=$USUARIOS
RIGEL_SEGREDO=$(openssl rand -hex 32)
WHISPER_MODELO=small
RIGEL_HTTPS=1
FIM
  chmod 600 .env
fi
echo "== Montando (leva de 5 a 15 minutos na primeira vez) =="
docker compose up -d --build
echo; echo "PRONTO. Abra: https://$(grep ^DOMINIO .env | cut -d= -f2)"
