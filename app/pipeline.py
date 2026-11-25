"""Rigel Edit Pro — pipeline de edição (modo automático).

Etapas: baixar/receber -> analisar (ffprobe, áudio, Whisper, chamadas, silêncios, tela final)
-> revisão (o Kennedy aprova os cortes) -> renderizar (cortes, punch-in, voz, cor, loudness)
-> entregar (MP4 + EDL para o DaVinci).
"""
import json, os, re, subprocess, unicodedata, shutil, math
from pathlib import Path

from frases import CHAMADAS

FPS = 25                       # padrão playout Órion
SR = 48000
CHUNK = SR // FPS              # 1920 amostras = 1 quadro de vídeo (sincronia exata nos cortes)
FRAME = 1.0 / FPS


# ---------------------------------------------------------------- utilidades
def run(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode != 0:
        raise RuntimeError(f"{cmd[0]} falhou: {r.stderr[-1500:]}")
    return r


def sem_acento(s):
    return "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn")


def snap(t):
    return round(t * FPS) / FPS


def tc(seg, fps):
    f = int(round(seg * fps))
    return f"{f // (3600*fps):02d}:{f // (60*fps) % 60:02d}:{f // fps % 60:02d}:{f % fps:02d}"


def mmss(t):
    return f"{int(t // 60):02d}:{t % 60:04.1f}"


# ---------------------------------------------------------------- entrada
VIDEO_EXT = (".mp4", ".mkv", ".webm", ".mov", ".m4v")
CLIENTES_YT = ["default", "tv,web_safari", "mweb", "android_vr", "web_embedded", "ios"]
COOKIES_YT = Path(os.environ.get("RIGEL_DADOS", "/dados")) / "youtube-cookies.txt"


def baixar(link, pasta: Path, idioma=""):
    """YouTube e demais sites do yt-dlp, ou Google Drive (gdown).
    idioma: 'pt', 'es', 'en'… tenta a faixa de áudio nesse idioma e baixa a legenda dele se existir.
    Retorna dict com arquivo, titulo, duracao, idioma_audio, legendas[]."""
    pasta.mkdir(parents=True, exist_ok=True)
    if "drive.google.com" in link:
        import gdown
        out = gdown.download(link, str(pasta / "video"), quiet=True, fuzzy=True)
        if not out:
            raise RuntimeError("Não consegui baixar do Drive. O arquivo está compartilhado como 'qualquer pessoa com o link'?")
        return {"arquivo": out, "titulo": Path(out).stem, "legendas": [], "idioma_audio": None}
    v = "bv*[vcodec^=avc1][height<=1080]"
    fmt = f"{v}+ba[language^={idioma}]/{v}+ba/bv*[height<=1080]+ba/b" if idioma else f"{v}+ba/bv*[height<=1080]+ba/b"
    base = ["yt-dlp", "-f", fmt, "--merge-output-format", "mp4", "--no-playlist", "--write-info-json",
            "--write-thumbnail", "--convert-thumbnails", "jpg", "-o", str(pasta / "video.%(ext)s")]
    if idioma:
        base += ["--write-subs", "--write-auto-subs", "--sub-langs", f"{idioma},{idioma}-*,{idioma}.*",
                 "--convert-subs", "srt"]
    # Mesma estratégia do Órion Lite: gerador de PO Token (127.0.0.1:4416, entra sozinho) + vários clientes do
    # YouTube; os cookies da conta (Configurações) entram por último, porque misturar com o PO Token às vezes atrapalha.
    tentativas = [(c, False) for c in CLIENTES_YT]
    if COOKIES_YT.exists():
        tentativas += [("default", True), ("tv,web_safari", True), ("mweb", True)]
    ultimo = ""
    for cliente, com_cookies in tentativas:
        cmd = list(base)
        if cliente != "default":
            cmd += ["--extractor-args", "youtube:player_client=" + cliente]
        if com_cookies:
            cmd += ["--cookies", str(COOKIES_YT)]
        r = subprocess.run(cmd + [link], capture_output=True, text=True, timeout=3 * 3600)
        if any(p.suffix in VIDEO_EXT for p in pasta.glob("video.*")):
            break
        erros = [l for l in r.stderr.splitlines() if "ERROR" in l]
        ultimo = (erros[-1] if erros else r.stderr.strip()[-300:]).replace("ERROR: ", "")
        if "Private video" in ultimo or ("not available" in ultimo and "format" not in ultimo) or "copyright" in ultimo.lower():
            break
    if not any(p.suffix in VIDEO_EXT for p in pasta.glob("video.*")):
        if "not a bot" in ultimo or "Sign in" in ultimo:
            raise RuntimeError("O YouTube barrou este servidor (anti-robô), mesmo com o gerador de PO Token e 7 caminhos diferentes. "
                               + ("Os cookies enviados também não passaram: envie cookies novos em Configurações. "
                                  if COOKIES_YT.exists() else
                                  "Resolva uma vez: envie os cookies da sua conta do YouTube em Configurações e tente de novo. ")
                               + "Enquanto isso, o Drive ou o envio do arquivo sempre funcionam.")
        if "Private video" in ultimo:
            raise RuntimeError("O vídeo é privado. No YouTube Studio, deixe como “Não listado” para baixar.")
        raise RuntimeError(ultimo[:300] or "O YouTube não entregou o vídeo.")
    arqs = [p for p in pasta.glob("video.*") if p.suffix in VIDEO_EXT]
    if not arqs:
        raise RuntimeError("Download não gerou arquivo de vídeo.")
    info = {}
    if (pasta / "video.info.json").exists():
        info = json.loads((pasta / "video.info.json").read_text())
        (pasta / "video.info.json").unlink()
    aud = None
    for f in info.get("requested_formats") or []:
        if f.get("acodec") not in (None, "none"):
            aud = f.get("language")
    legendas = []
    for s in pasta.glob("video.*.srt"):
        lang = s.name.split(".")[1]
        auto = lang not in (info.get("subtitles") or {})
        legendas.append({"idioma": lang.split("-")[0], "arquivo": s.name, "tipo": "automática" if auto else "original"})
    return {"arquivo": str(arqs[0]), "titulo": info.get("title") or link, "legendas": legendas,
            "idioma_audio": aud or info.get("language"), "canal_origem": info.get("channel") or info.get("uploader"),
            "plataforma": info.get("extractor_key")}


def tira_de_quadros(arq, duracao, destino, n=48):
    """Uma imagem com n quadros lado a lado para a timeline."""
    run(["ffmpeg", "-y", "-v", "error", "-i", str(arq), "-vf",
         f"fps={n}/{max(duracao, 1):.3f},scale=192:108:force_original_aspect_ratio=increase,crop=192:108,tile={n}x1",
         "-frames:v", "1", "-q:v", "5", str(destino)])


def forma_de_onda(arq, destino):
    run(["ffmpeg", "-y", "-v", "error", "-i", str(arq), "-filter_complex",
         "aformat=channel_layouts=mono,showwavespic=s=2400x160:colors=0xF6F3EC:scale=sqrt", "-frames:v", "1", str(destino)])


def srt_de_palavras(palavras, destino, max_chars=42, max_dur=6.0):
    """Legenda SRT a partir das palavras do Whisper (2 linhas de até 42 caracteres)."""
    cues, atual = [], []

    def fecha():
        if atual:
            cues.append((atual[0]["t0"], atual[-1]["t1"], " ".join(p["w"] for p in atual)))
            atual.clear()
    for i, p in enumerate(palavras):
        if atual and (p["t0"] - atual[-1]["t1"] > 0.6 or p["t1"] - atual[0]["t0"] > max_dur
                      or len(" ".join(x["w"] for x in atual)) + len(p["w"]) > max_chars * 2):
            fecha()
        atual.append(p)
        if re.search(r"[.!?]$", p["w"]):
            fecha()
    fecha()
    escrever_srt(cues, destino)
    return cues


def _srt_tc(t):
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def escrever_srt(cues, destino):
    linhas = []
    for i, (a, b, txt) in enumerate(cues, 1):
        linhas += [str(i), f"{_srt_tc(a)} --> {_srt_tc(b)}", txt.strip(), ""]
    Path(destino).write_text("\n".join(linhas), encoding="utf-8")


def ler_srt(caminho):
    cues = []
    blocos = re.split(r"\n\s*\n", Path(caminho).read_text(encoding="utf-8", errors="ignore").replace("\r", ""))
    for b in blocos:
        m = re.search(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)", b)
        if not m:
            continue
        g = [int(x) for x in m.groups()]
        a = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000
        z = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000
        txt = " ".join(l for l in b[m.end():].strip().splitlines() if l.strip())
        txt = re.sub(r"<[^>]+>", "", txt)
        if txt and (not cues or cues[-1][2] != txt):   # legendas automáticas repetem linhas
            cues.append((a, z, txt))
    return cues


def analisar_midia(arq):
    r = run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(arq)])
    d = json.loads(r.stdout)
    v = next((s for s in d["streams"] if s["codec_type"] == "video"), None)
    a = next((s for s in d["streams"] if s["codec_type"] == "audio"), None)
    if not v or not a:
        raise RuntimeError("O arquivo precisa ter vídeo e áudio.")
    num, den = (v.get("r_frame_rate") or "25/1").split("/")
    return {
        "duracao": float(d["format"]["duration"]),
        "largura": v["width"], "altura": v["height"],
        "fps": round(float(num) / float(den or 1), 3),
    }


# ---------------------------------------------------------------- transcrição
def transcrever(arq, pasta: Path, modelo="small", idioma=None):
    """Whisper local (faster-whisper) com tempo por palavra. Cache em transcricao.json."""
    cache = pasta / "transcricao.json"
    if cache.exists():
        return json.loads(cache.read_text())
    wav = pasta / "audio16k.wav"
    run(["ffmpeg", "-y", "-v", "error", "-i", str(arq), "-vn", "-ac", "1", "-ar", "16000", str(wav)])
    from faster_whisper import WhisperModel
    m = WhisperModel(modelo, device="cpu", compute_type="int8")
    segs, info = m.transcribe(str(wav), language=idioma or None, word_timestamps=True, vad_filter=True)
    palavras = []
    for s in segs:
        for w in s.words or []:
            palavras.append({"t0": round(w.start, 3), "t1": round(w.end, 3), "w": w.word.strip()})
    out = {"idioma": info.language, "palavras": palavras}
    cache.write_text(json.dumps(out, ensure_ascii=False))
    wav.unlink(missing_ok=True)
    return out


# ---------------------------------------------------------------- detecção
def _frase_inteira(pal, i0, i1):
    """Expande o trecho achado até o começo/fim da frase (pontuação ou pausa > 0,7 s)."""
    while i0 > 0:
        ant = pal[i0 - 1]
        if re.search(r"[.!?]$", ant["w"]) or pal[i0]["t0"] - ant["t1"] > 0.7 or pal[i1]["t1"] - ant["t0"] > 12:
            break
        i0 -= 1
    while i1 < len(pal) - 1:
        if re.search(r"[.!?]$", pal[i1]["w"]) or pal[i1 + 1]["t0"] - pal[i1]["t1"] > 0.7 or pal[i1 + 1]["t1"] - pal[i0]["t0"] > 12:
            break
        i1 += 1
    return i0, i1


def achar_chamadas(transc):
    pal = transc["palavras"]
    if not pal:
        return []
    # texto normalizado com mapa caractere -> índice da palavra
    texto, mapa = "", []
    for i, p in enumerate(pal):
        tok = re.sub(r"[^a-z0-9 \-]", "", sem_acento(p["w"]))
        texto += tok + " "
        mapa += [i] * (len(tok) + 1)
    achados = []
    for tipo, pads in CHAMADAS.items():
        for pad in pads:
            for m in re.finditer(r"\b" + pad, texto):
                i0, i1 = mapa[m.start()], mapa[min(m.end(), len(mapa)) - 1]
                i0, i1 = _frase_inteira(pal, i0, i1)
                achados.append([i0, i1, tipo])
    # junta sobreposições
    achados.sort()
    juntos = []
    for a in achados:
        if juntos and a[0] <= juntos[-1][1] + 1:
            juntos[-1][1] = max(juntos[-1][1], a[1])
        else:
            juntos.append(a)
    cortes = []
    for i0, i1, tipo in juntos:
        t0 = max(0.0, pal[i0]["t0"] - 0.08)
        t1 = pal[i1]["t1"] + 0.12
        cortes.append({"tipo": "chamada", "categoria": tipo, "t0": t0, "t1": t1,
                       "texto": " ".join(p["w"] for p in pal[i0:i1 + 1]), "ativo": True})
    return cortes


def achar_silencios(arq, duracao, ruido="-35dB", minimo=0.8, respiro=0.15):
    r = subprocess.run(["ffmpeg", "-v", "info", "-i", str(arq), "-vn", "-af",
                        f"silencedetect=noise={ruido}:d={minimo}", "-f", "null", "-"],
                       capture_output=True, text=True)
    ini = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", r.stderr)]
    fim = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", r.stderr)]
    out = []
    for a, b in zip(ini, fim):
        if a < 0.5 or b > duracao - 0.5:       # começo/fim tratados à parte
            continue
        a2, b2 = a + respiro, b - respiro
        if b2 - a2 >= 0.3:
            out.append({"tipo": "silencio", "t0": a2, "t1": b2, "ativo": True})
    return out


def sugerir_tela_final(transc, duracao):
    pal = transc["palavras"]
    if not pal:
        return None
    fim_fala = pal[-1]["t1"]
    if duracao - fim_fala > 4:
        return {"tipo": "tela_final", "t0": fim_fala + 0.6, "t1": duracao,
                "texto": f"Sem fala nos últimos {duracao - fim_fala:.0f} s (provável tela final do YouTube)", "ativo": True}
    return None


def quadro(arq, t, destino):
    run(["ffmpeg", "-y", "-v", "error", "-ss", f"{max(0, t):.2f}", "-i", str(arq), "-frames:v", "1",
         "-vf", "scale=480:-2", "-q:v", "4", str(destino)])


# ---------------------------------------------------------------- render
LOOKS = {
    # [A VALIDAR] aprovar com quadro antes/depois
    "docu": "eq=contrast=1.08:saturation=0.94:gamma=0.98,"
            "colorbalance=rs=0.03:bs=-0.03:rm=0.02:bm=-0.02:rh=0.01:bh=-0.01,vignette=angle=PI/5",
    "neutro": "eq=contrast=1.02:saturation=1.0",
    "original": "null",
}

LOUDNESS = {"playout": -23, "youtube": -14}


def mantidos(cortes, duracao):
    """Complemento dos cortes ativos, alinhado a quadros de 25 fps."""
    ativos = sorted((snap(c["t0"]), snap(c["t1"]), c["tipo"]) for c in cortes if c.get("ativo"))
    segs, pos, tipo_ant = [], 0.0, None
    for a, b, tipo in ativos:
        if b <= pos:
            continue
        if a - pos >= (0.6 if tipo_ant else FRAME * 2):   # sobra minúscula entre dois cortes também sai
            segs.append({"t0": pos, "t1": a, "apos": tipo_ant})
        pos = max(pos, b)
        tipo_ant = tipo
    if snap(duracao) - pos >= FRAME * 2:
        segs.append({"t0": pos, "t1": snap(duracao), "apos": tipo_ant})
    return segs


def plano_zoom(segs):
    """Alterna punch-in 110% a cada corte de chamada/manual (disfarça o salto). Tempo de saída."""
    out, t, zoom = [], 0.0, False
    for s in segs:
        if s["apos"] in ("chamada", "manual"):
            zoom = not zoom
        dur = s["t1"] - s["t0"]
        if zoom:
            out.append((t, t + dur))
        t += dur
    return out, t


def renderizar(arq, pasta: Path, cortes, duracao, look="docu", destino="playout", progresso=None):
    segs = mantidos(cortes, duracao)
    if not segs:
        raise RuntimeError("Nada sobrou depois dos cortes.")
    zooms, dur_final = plano_zoom(segs)
    sel = "+".join(f"between(t,{s['t0']:.3f},{s['t1'] - FRAME / 2:.3f})" for s in segs)
    asel = "+".join(f"between(t,{s['t0']:.3f},{s['t1'] - FRAME / 2:.3f})" for s in segs)
    en = "+".join(f"between(t,{a:.3f},{b - FRAME / 2:.3f})" for a, b in zooms) or "0"
    lufs = LOUDNESS.get(destino, -23)
    filtro = (
        f"[0:v]fps={FPS},scale=1920:1080:force_original_aspect_ratio=decrease,"
        f"pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1,"
        f"select='{sel}',setpts=N/{FPS}/TB,split[base][zin];"
        f"[zin]crop=iw/1.1:ih/1.1,scale=1920:1080[z];"
        f"[base][z]overlay=enable='{en}',{LOOKS.get(look, 'null')},format=yuv420p[v];"
        f"[0:a]aresample={SR},aformat=channel_layouts=stereo,asetnsamples=n={CHUNK}:p=0,"
        f"aselect='{asel}',asetpts=N/SR/TB,"
        f"highpass=f=80,afftdn=nf=-25,acompressor=threshold=-18dB:ratio=3:attack=10:release=200,"
        f"loudnorm=I={lufs}:TP=-1:LRA=11[a]"
    )
    script = pasta / "filtro.txt"
    script.write_text(filtro)
    saida = pasta / "rigel_final.mp4"
    cmd = ["ffmpeg", "-y", "-v", "error", "-progress", "pipe:1", "-i", str(arq),
           "-filter_complex_script", str(script), "-map", "[v]", "-map", "[a]",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-r", str(FPS),
           "-c:a", "aac", "-b:a", "192k", "-ar", str(SR), "-movflags", "+faststart", str(saida)]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    for linha in p.stdout:
        if linha.startswith("out_time_us=") and progresso:
            try:
                progresso(min(99, int(linha.split("=")[1]) / 1e6 / dur_final * 100))
            except ValueError:
                pass
    err = p.stderr.read()
    if p.wait() != 0:
        raise RuntimeError("Render falhou: " + err[-1500:])
    return saida, segs, dur_final


def gerar_edl(segs, nome_fonte, fps_fonte, destino: Path):
    """EDL CMX3600: abre no DaVinci Resolve (File > Import > Timeline) apontando para o vídeo original."""
    fps = int(round(fps_fonte)) or 25
    linhas = ["TITLE: RIGEL EDIT PRO", "FCM: NON-DROP FRAME", ""]
    rec = 3600.0  # timeline começa em 01:00:00:00
    for i, s in enumerate(segs, 1):
        d = s["t1"] - s["t0"]
        linhas.append(f"{i:03d}  AX       AA/V  C        {tc(s['t0'], fps)} {tc(s['t1'], fps)} {tc(rec, fps)} {tc(rec + d, fps)}")
        linhas.append(f"* FROM CLIP NAME: {nome_fonte}")
        linhas.append("")
        rec += d
    destino.write_text("\n".join(linhas))
    return destino


# ---------------------------------------------------------------- exportar para outros editores
def gerar_xml_fcp7(segs, arq_original: Path, midia, destino: Path, titulo="Rigel Edit Pro"):
    """FCP7 XML (XMEML): abre no Filmora, DaVinci Resolve e Premiere. O editor pede para religar
    o vídeo original: aponte para o arquivo baixado junto."""
    from xml.sax.saxutils import escape
    fps_f = midia["fps"] or 25
    base = int(round(fps_f))
    ntsc = "TRUE" if abs(fps_f - base) > 0.01 else "FALSE"
    fr = lambda t: int(round(t * fps_f))
    total = fr(midia["duracao"])
    nome = escape(arq_original.name)
    rate = f"<rate><timebase>{base}</timebase><ntsc>{ntsc}</ntsc></rate>"
    arquivo_def = (f'<file id="f1"><name>{nome}</name><pathurl>file://localhost/{nome}</pathurl>{rate}'
                   f"<duration>{total}</duration><media><video><samplecharacteristics><width>{midia['largura']}</width>"
                   f"<height>{midia['altura']}</height></samplecharacteristics></video>"
                   f"<audio><channelcount>2</channelcount></audio></media></file>")
    v, a, pos = [], [], 0
    for i, s in enumerate(segs, 1):
        ini, fim = fr(s["t0"]), fr(s["t1"])
        d = fim - ini
        arq = arquivo_def if i == 1 else '<file id="f1"/>'
        comum = f"<name>{nome}</name><duration>{total}</duration>{rate}<start>{pos}</start><end>{pos + d}</end><in>{ini}</in><out>{fim}</out>{arq}"
        v.append(f'<clipitem id="v{i}">{comum}<link><linkclipref>v{i}</linkclipref></link><link><linkclipref>a{i}</linkclipref></link></clipitem>')
        a.append(f'<clipitem id="a{i}">{comum.replace(arquivo_def, chr(60) + "file id=" + chr(34) + "f1" + chr(34) + "/>")}'
                 f"<sourcetrack><mediatype>audio</mediatype><trackindex>1</trackindex></sourcetrack></clipitem>")
        pos += d
    xml = (f'<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n<xmeml version="5"><sequence id="seq1">'
           f"<name>{escape(titulo)}</name><duration>{pos}</duration>{rate}<media>"
           f"<video><format><samplecharacteristics>{rate}<width>{midia['largura']}</width><height>{midia['altura']}</height>"
           f"</samplecharacteristics></format><track>{''.join(v)}</track></video>"
           f"<audio><track>{''.join(a)}</track></audio></media></sequence></xmeml>")
    destino.write_text(xml, encoding="utf-8")
    return destino


def srt_editado(palavras, segs, destino: Path):
    """Legenda já no tempo do vídeo editado (serve para qualquer editor e para o playout)."""
    mapa, pos = [], 0.0
    for s in segs:
        mapa.append((s["t0"], s["t1"], pos))
        pos += s["t1"] - s["t0"]
    novas = []
    for p in palavras:
        for a, b, off in mapa:
            if a <= p["t0"] and p["t1"] <= b + 0.05:
                novas.append({**p, "t0": p["t0"] - a + off, "t1": min(p["t1"], b) - a + off})
                break
    return srt_de_palavras(novas, destino)


def pacote_clipes(arq, segs, pasta: Path, progresso=None):
    """Cada trecho mantido vira um MP4 numerado (01, 02…) num ZIP: arraste tudo, em ordem, para o CapCut."""
    import zipfile
    d = pasta / "clipes"
    d.mkdir(exist_ok=True)
    zipf = pasta / "rigel_clipes_capcut.zip"
    with zipfile.ZipFile(zipf, "w", zipfile.ZIP_STORED) as z:
        for i, s in enumerate(segs, 1):
            out = d / f"{i:03d}_{mmss(s['t0']).replace(':', 'm')}s.mp4"
            run(["ffmpeg", "-y", "-v", "error", "-ss", f"{s['t0']:.3f}", "-to", f"{s['t1']:.3f}", "-i", str(arq),
                 "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-c:a", "aac", "-b:a", "192k", str(out)])
            z.write(out, out.name)
            out.unlink()
            if progresso:
                progresso(i / len(segs) * 100)
    d.rmdir()
    return zipf
