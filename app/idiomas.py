"""Idiomas: legenda traduzida (grátis, Argos local) e dublagem em voice-over
(Piper grátis, local) ou ElevenLabs (pago, com a chave do próprio usuário)."""
import json, math, subprocess, urllib.request, wave
from pathlib import Path

import pipeline as P

NOMES = {"pt": "Português", "es": "Espanhol", "en": "Inglês", "fr": "Francês", "it": "Italiano"}
# Vozes Piper padrão por idioma [A VALIDAR ouvindo no servidor]
VOZES_PIPER = {"pt": "pt_BR-faber-medium", "es": "es_ES-davefx-medium", "en": "en_US-lessac-medium",
               "fr": "fr_FR-siwis-medium", "it": "it_IT-riccardo-x_low"}
# ElevenLabs cobra por caractere; no modelo multilingual ~1 crédito por caractere [A VALIDAR no plano do usuário]
CREDITO_POR_CARACTERE = {"eleven_multilingual_v2": 1.0, "eleven_flash_v2_5": 0.5}


# ---------------------------------------------------------------- tradução (grátis)
def _argos_pronto(de, para):
    import argostranslate.package as pk, argostranslate.translate as tr
    instalados = {(p.from_code, p.to_code) for p in pk.get_installed_packages()}
    precisa = [(de, para)] if (de, para) not in instalados else []
    if precisa:
        pk.update_package_index()
        disp = pk.get_available_packages()
        direto = [p for p in disp if p.from_code == de and p.to_code == para]
        pares = [(de, para)] if direto else [(de, "en"), ("en", para)]
        for a, b in pares:
            if (a, b) in instalados or a == b:
                continue
            pkg = next((p for p in disp if p.from_code == a and p.to_code == b), None)
            if not pkg:
                raise RuntimeError(f"Não há tradutor livre de {a} para {b}.")
            pk.install_from_path(pkg.download())
    return tr


def traduzir_cues(cues, de, para):
    if de == para:
        return cues
    tr = _argos_pronto(de, para)
    return [(a, b, tr.translate(t, de, para)) for a, b, t in cues]


def legenda_no_idioma(item, pasta: Path, para, modelo_whisper="small"):
    """Garante uma legenda 'para' no item da biblioteca. Usa a que existir; senão transcreve e traduz."""
    leg = {l["idioma"]: l for l in item.get("legendas", [])}
    if para in leg:
        return pasta / leg[para]["arquivo"]
    origem = item.get("idioma_audio")
    if origem in leg and leg[origem]["tipo"] == "original":
        cues = P.ler_srt(pasta / leg[origem]["arquivo"])
    else:
        transc = P.transcrever(Path(item["arquivo"]), pasta, modelo_whisper, origem)
        origem = transc.get("idioma") or origem or "pt"
        item["idioma_audio"] = origem
        cues = P.srt_de_palavras(transc["palavras"], pasta / f"video.{origem}.srt")
        item.setdefault("legendas", []).append({"idioma": origem, "arquivo": f"video.{origem}.srt", "tipo": "transcrita"})
    novo = pasta / f"video.{para}.srt"
    P.escrever_srt(traduzir_cues(cues, origem, para), novo)
    item["legendas"].append({"idioma": para, "arquivo": novo.name, "tipo": "traduzida (grátis)"})
    return novo


# ---------------------------------------------------------------- dublagem
def estimar(cues, provedor, modelo="eleven_multilingual_v2"):
    chars = sum(len(t) for _, _, t in cues)
    if provedor == "piper":
        return {"caracteres": chars, "custo": "Grátis (voz local Piper, som mais robótico)"}
    cred = math.ceil(chars * CREDITO_POR_CARACTERE.get(modelo, 1.0))
    return {"caracteres": chars, "creditos": cred,
            "custo": f"Cerca de {cred:,} créditos ElevenLabs na SUA conta ({chars:,} caracteres) [A VALIDAR no seu plano]".replace(",", ".")}


def _tts_piper(texto, idioma, destino: Path, dir_vozes: Path):
    from piper import PiperVoice
    nome = VOZES_PIPER.get(idioma, VOZES_PIPER["en"])
    modelo = dir_vozes / f"{nome}.onnx"
    if not modelo.exists():
        dir_vozes.mkdir(parents=True, exist_ok=True)
        subprocess.run(["python3", "-m", "piper.download_voices", "--download-dir", str(dir_vozes), nome], check=True)
    voz = _tts_piper.cache.get(nome) or PiperVoice.load(str(modelo))
    _tts_piper.cache[nome] = voz
    with wave.open(str(destino), "wb") as w:
        voz.synthesize_wav(texto, w)


_tts_piper.cache = {}


def _tts_eleven(texto, destino: Path, chave, voz_id, modelo):
    req = urllib.request.Request(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voz_id}?output_format=mp3_44100_128",
        data=json.dumps({"text": texto, "model_id": modelo}).encode(),
        headers={"xi-api-key": chave, "Content-Type": "application/json", "Accept": "audio/mpeg"})
    with urllib.request.urlopen(req, timeout=120) as r:
        destino.write_bytes(r.read())


def _dur(arq):
    r = P.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(arq)])
    return float(r.stdout.strip() or 0)


def dublar(video: Path, cues, idioma, pasta: Path, provedor, cfg, dir_vozes: Path, progresso=None):
    """Voice-over estilo documentário: original a 20% e a voz nova por cima, cada fala no seu tempo."""
    tmp = pasta / f"dub_{idioma}"
    tmp.mkdir(exist_ok=True)
    entradas, filtros = [], []
    for i, (a, b, txt) in enumerate(cues):
        bruto = tmp / (f"{i:04d}.wav" if provedor == "piper" else f"{i:04d}.mp3")
        if not bruto.exists():
            if provedor == "piper":
                _tts_piper(txt, idioma, bruto, dir_vozes)
            else:
                _tts_eleven(txt, bruto, cfg["eleven_chave"], cfg["eleven_voz"], cfg.get("eleven_modelo") or "eleven_multilingual_v2")
        # acelera no máximo 1,4x para caber no tempo da fala original (+0,4 s de folga)
        janela = (cues[i + 1][0] if i + 1 < len(cues) else b + 2) - a
        vel = min(1.4, max(1.0, _dur(bruto) / max(janela + 0.4, 0.5)))
        entradas += ["-i", str(bruto)]
        filtros.append(f"[{i + 1}:a]aresample=48000,atempo={vel:.3f},adelay={int(a * 1000)}:all=1[d{i}]")
        if progresso:
            progresso(i / len(cues) * 90)
    # junta em lotes para não estourar o limite de entradas
    voz = tmp / "voz.wav"
    lote = 200
    parciais = []
    for k in range(0, len(cues), lote):
        ins, fs = [], []
        for j, i in enumerate(range(k, min(k + lote, len(cues)))):
            ins += entradas[2 * i: 2 * i + 2]
            fs.append(filtros[i].replace(f"[{i + 1}:a]", f"[{j}:a]").replace(f"[d{i}]", f"[d{j}]"))
        n = len(fs)
        fs.append(("".join(f"[d{j}]" for j in range(n)) + f"amix=inputs={n}:normalize=0:duration=longest[o]") if n > 1 else "[d0]anull[o]")
        parc = tmp / f"parcial{k // lote}.wav"
        (tmp / "f.txt").write_text(";".join(fs))
        P.run(["ffmpeg", "-y", "-v", "error", *ins, "-filter_complex_script", str(tmp / "f.txt"),
               "-map", "[o]", "-ac", "1", str(parc)])
        parciais.append(parc)
    if len(parciais) == 1:
        parciais[0].replace(voz)
    else:
        ins = sum((["-i", str(p)] for p in parciais), [])
        P.run(["ffmpeg", "-y", "-v", "error", *ins, "-filter_complex",
               f"amix=inputs={len(parciais)}:normalize=0:duration=longest", str(voz)])
    saida = pasta / f"video.dub-{idioma}.mp4"
    P.run(["ffmpeg", "-y", "-v", "error", "-i", str(video), "-i", str(voz), "-filter_complex",
           "[0:a]aresample=48000,volume=0.2[o];[1:a]aresample=48000,loudnorm=I=-18:TP=-2,"
           "pan=stereo|c0=c0|c1=c0[v];[o][v]amix=inputs=2:normalize=0:duration=first[a]",
           "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", str(saida)])
    return saida
