# Rigel Edit Pro · Constelação Órion

Editor pessoal com cara de editor: player, timeline com os cortes, painel lateral e o Rigel no canto.

## O que faz
- **Biblioteca com baixador:** link do YouTube, Vimeo, Facebook, Instagram, TikTok, Drive (yt-dlp/gdown) ou upload.
  Com idioma preferido, baixa a faixa de áudio e a legenda nesse idioma quando o vídeo tiver (grátis).
- **Idiomas:** legenda traduzida grátis (Whisper + Argos, local). Dublagem em voice-over com Piper (grátis)
  ou ElevenLabs (pago na conta de quem configurou; o Rigel mostra a estimativa e pede confirmação antes).
- **Editor:** acha as chamadas de YouTube, a tela final e as pausas. Prévia com cortes no navegador, liga e desliga cada corte,
  cor Docu-reality, Neutro ou Original [A VALIDAR com vídeo real], saída Playout (−23 LUFS) ou YouTube (−14 LUFS).
- **Rigel:** comandos rápidos grátis por padrão ("corta de 02:10 a 02:30", "sem pausas", "desfaz", "renderiza", "ajuda").
  Botão para a **conversa com IA (paga)**: cada usuário configura a PRÓPRIA chave (Claude ou OpenAI compatível) e o painel
  avisa o custo. A IA só mexe no vídeo pelos mesmos comandos.
- **Exportar:** MP4 final, legenda SRT já no tempo dos cortes, **XML para Filmora, DaVinci e Premiere**, **clipes numerados para CapCut**
  (ZIP), EDL e o vídeo original (para religar o XML).

## Instalar (VPS separado dos playouts, Ubuntu 22/24)
1. Aponte um subdomínio para o IP do VPS (ex.: `rigel.orionplayout.live`, registro A).
2. No VPS:
   ```bash
   curl -fsSL https://get.docker.com | sh
   # copie a pasta rigel-edit-pro para o servidor e entre nela
   cp .env.example .env && nano .env      # domínio, usuários e senhas, segredo
   docker compose up -d --build
   ```
3. Abra `https://rigel.orionplayout.live`. O HTTPS sai automático (Caddy).

Na primeira vez o servidor baixa o modelo do Whisper (~500 MB, `small`), os tradutores Argos e as vozes Piper que forem usados.
Tudo fica em cache em `dados/`.

## Abrir em outros editores
- **Filmora:** Arquivo → Importar → Importar arquivo XML. Se pedir mídia, aponte para o vídeo original (botão na aba Exportar).
- **DaVinci Resolve:** File → Import → Timeline → XML (ou o EDL).
- **Premiere:** Arquivo → Importar → XML.
- **CapCut:** descompacte o ZIP e arraste os clipes 001, 002… em ordem para a timeline. O CapCut não abre XML de forma oficial [A VALIDAR na sua versão].

## Avisos honestos
- Só conteúdo próprio ou licenciado (o formulário exige). Dublagem de terceiros precisa estar no acordo com o criador.
- O YouTube costuma bloquear downloads vindos de servidor. Se acontecer, use o Drive ou o arquivo do criador.
  Para atualizar o baixador: `docker compose exec rigel pip install -U yt-dlp`.
- Em CPU (4 a 6 vCPU) [A VALIDAR]: transcrição perto da duração do vídeo, render perto de tempo real. Um trabalho por vez.
- Testado aqui com vídeo sintético e transcrição simulada; Whisper, Argos, Piper e ElevenLabs só rodam de verdade no servidor
  (este ambiente bloqueia o download dos modelos). Primeira rodada real = teste de aceitação.
- Ainda não feito: GCs, blocos com "A seguir…", teaser de abertura e trilha com ducking.
