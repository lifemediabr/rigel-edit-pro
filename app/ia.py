"""Conversa com IA (opcional e paga): usa a chave do PRÓPRIO usuário logado, nunca uma conta central.
A IA responde em português e, quando precisa mexer no vídeo, devolve linhas 'COMANDO: …'
que passam pelo mesmo interpretador dos comandos rápidos (nada é feito fora dele)."""
import json, re, urllib.request

import comandos as C
from pipeline import mmss

PROVEDORES = {
    "anthropic": {"nome": "Claude (Anthropic)", "modelo": "claude-haiku-5-5"},   # [CONFIRMAR modelo no console]
    "openai": {"nome": "OpenAI ou compatível", "modelo": "gpt-4o-mini", "base": "https://api.openai.com/v1"},
}


def _transcricao(job, limite=14000):
    pal = job.get("palavras") or []
    linhas, bloco, t0 = [], [], None
    for p in pal:
        if t0 is None:
            t0 = p["t0"]
        bloco.append(p["w"])
        if p["t1"] - t0 > 10:
            linhas.append(f"[{mmss(t0)}] {' '.join(bloco)}")
            bloco, t0 = [], None
    if bloco:
        linhas.append(f"[{mmss(t0)}] {' '.join(bloco)}")
    txt = "\n".join(linhas)
    return txt if len(txt) <= limite else txt[:limite] + "\n[…transcrição cortada por tamanho…]"


def sistema(job):
    return (
        "Você é o Rigel, editor de vídeo da Constelação Órion. Responda em português do Brasil, curto e direto.\n"
        "Você NÃO edita sozinho: para mudar o vídeo, escreva no fim da resposta uma linha por ação no formato\n"
        "COMANDO: <comando>\nusando só estes comandos:\n" + C.AJUDA + "\n"
        "Use tempos mm:ss. Só peça 'renderiza' se a pessoa pedir para finalizar.\n\n"
        f"Vídeo: {job.get('titulo')} · duração {mmss(job['midia']['duracao'])} · cor {job.get('look')} · "
        f"saída {job.get('destino')} · pausas {'saem' if job.get('usar_silencios', True) else 'ficam'}\n"
        f"Cortes atuais (número, situação, tempos, tipo, texto):\n{C.lista(job)}\n\n"
        f"Transcrição com tempos:\n{_transcricao(job)}"
    )


def _post(url, corpo, headers):
    req = urllib.request.Request(url, data=json.dumps(corpo).encode(), headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        detalhe = e.read().decode(errors="ignore")[:300]
        if e.code in (401, 403):
            raise RuntimeError("A chave de IA foi recusada. Confira em Configurações.")
        raise RuntimeError(f"A IA respondeu erro {e.code}: {detalhe}")


def conversar(job, cfg, mensagem):
    prov = cfg.get("ia_provedor") or "anthropic"
    chave = cfg.get("ia_chave")
    if not chave:
        raise RuntimeError("Configure a sua chave de IA em Configurações para usar a conversa.")
    modelo = cfg.get("ia_modelo") or PROVEDORES[prov]["modelo"]
    hist = [m for m in job.get("chat", []) if m.get("modo") == "ia"][-8:]
    msgs = [{"role": "user" if m["de"] == "voce" else "assistant", "content": m["texto"]} for m in hist]
    msgs.append({"role": "user", "content": mensagem})
    if prov == "anthropic":
        r = _post("https://api.anthropic.com/v1/messages",
                  {"model": modelo, "max_tokens": 700, "system": sistema(job), "messages": msgs},
                  {"x-api-key": chave, "anthropic-version": "2023-06-01"})
        texto = "".join(b.get("text", "") for b in r.get("content", []))
        uso = r.get("usage", {})
        tokens = (uso.get("input_tokens", 0), uso.get("output_tokens", 0))
    else:
        base = (cfg.get("ia_base") or PROVEDORES["openai"]["base"]).rstrip("/")
        r = _post(f"{base}/chat/completions",
                  {"model": modelo, "max_tokens": 700, "messages": [{"role": "system", "content": sistema(job)}] + msgs},
                  {"Authorization": f"Bearer {chave}"})
        texto = r["choices"][0]["message"]["content"]
        uso = r.get("usage", {})
        tokens = (uso.get("prompt_tokens", 0), uso.get("completion_tokens", 0))

    feitos, acao = [], None
    for linha in re.findall(r"^\s*COMANDO:\s*(.+)$", texto, re.M):
        resp, a = C.executar(job, linha.strip())
        feitos.append(f"{linha.strip()} → {resp.splitlines()[0]}")
        acao = acao or a
    limpo = re.sub(r"^\s*COMANDO:.*$\n?", "", texto, flags=re.M).strip()
    if feitos:
        limpo += "\n\nO que apliquei:\n" + "\n".join("• " + f for f in feitos)
    return limpo, acao, {"entrada": tokens[0], "saida": tokens[1], "modelo": modelo}
