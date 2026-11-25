FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg git curl unzip ca-certificates && rm -rf /var/lib/apt/lists/*
# Deno: o yt-dlp precisa de JavaScript para o YouTube; o gerador de PO Token também roda nele
RUN curl -fsSL -o /tmp/deno.zip https://github.com/denoland/deno/releases/latest/download/deno-x86_64-unknown-linux-gnu.zip \
 && unzip -q /tmp/deno.zip -d /usr/local/bin && rm /tmp/deno.zip && deno --version
# Gerador de PO Token (BgUtils) — servidor e plugin na MESMA versão
ARG BGUTIL=2.0.2
RUN git clone -q --depth 1 --single-branch --branch ${BGUTIL} https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git /opt/bgutil \
 && cd /opt/bgutil/server && deno install --allow-scripts=npm:canvas --frozen
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt "bgutil-ytdlp-pot-provider==${BGUTIL}"
COPY app/ .
COPY iniciar.sh /iniciar.sh
ENV RIGEL_DADOS=/dados HF_HOME=/dados/modelos TMPDIR=/dados/tmp PYTHONUNBUFFERED=1
CMD ["sh", "/iniciar.sh"]
