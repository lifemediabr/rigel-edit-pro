#!/bin/sh
mkdir -p /dados/tmp
# yt-dlp sempre na versão mais nova (o YouTube muda toda hora)
pip install -q -U "yt-dlp[default]" >/dev/null 2>&1 &
# gerador de PO Token só para dentro do container (127.0.0.1:4416), reinicia se cair
( cd /opt/bgutil/server/node_modules && while true; do
    nice -n 10 deno run --allow-env --allow-net --allow-ffi=. --allow-read=. ../src/main.ts --host 127.0.0.1 >> /dados/potoken.log 2>&1
    sleep 5
  done ) &
exec uvicorn main:app --host 0.0.0.0 --port 8800 --workers 1
