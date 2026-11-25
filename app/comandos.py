"""Comandos rápidos do Rigel (grátis, sem IA): entende frases curtas em português."""
import copy, re, uuid

from pipeline import mmss, sem_acento

AJUDA = (
    "Comandos que eu entendo:\n"
    "• corta de 02:10 a 02:30\n"
    "• corta os primeiros 15 segundos · corta os últimos 20 segundos\n"
    "• corta tudo depois de 18:40\n"
    "• mantém o corte 3 · corta o corte 3\n"
    "• mantém todas as chamadas · corta todas as chamadas\n"
    "• sem pausas · com pausas\n"
    "• cor docu · cor neutra · cor original\n"
    "• saída playout · saída youtube\n"
    "• lista · desfaz · renderiza"
)

T = r"(\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d+)?|\d+(?:[.,]\d+)?\s*(?:min(?:utos?)?|m)(?:\s*e?\s*\d+(?:[.,]\d+)?\s*(?:s|seg(?:undos?)?)?)?|\d+(?:[.,]\d+)?\s*(?:s|seg(?:undos?)?)?)"


def tempo(txt):
    txt = txt.strip().replace(",", ".")
    if ":" in txt:
        partes = [float(x) for x in txt.split(":")]
        s = 0.0
        for p in partes:
            s = s * 60 + p
        return s
    m = re.match(r"([\d.]+)\s*(?:min(?:utos?)?|m)\s*e?\s*([\d.]+)?", txt)
    if m:
        return float(m.group(1)) * 60 + float(m.group(2) or 0)
    return float(re.match(r"[\d.]+", txt).group(0))


def ordenar(job):
    job["cortes"].sort(key=lambda c: c["t0"])


def _guardar(job):
    h = job.setdefault("historico", [])
    h.append(copy.deepcopy({k: job.get(k) for k in ("cortes", "usar_silencios", "look", "destino")}))
    del h[:-20]


def _manual(job, a, b, txt):
    dur = job["midia"]["duracao"]
    a, b = max(0.0, a), min(dur, b)
    if b - a < 0.1:
        return f"Esse trecho não cabe no vídeo (duração {mmss(dur)})."
    _guardar(job)
    job["cortes"].append({"id": "m" + uuid.uuid4().hex[:5], "tipo": "manual", "t0": a, "t1": b,
                          "texto": txt, "ativo": True})
    ordenar(job)
    return f"Feito: corto de {mmss(a)} a {mmss(b)} ({b - a:.1f} s)."


def lista(job):
    if not job["cortes"]:
        return "Nenhum corte na lista."
    linhas = []
    for i, c in enumerate(job["cortes"], 1):
        marca = "✂" if c["ativo"] else "·"
        linhas.append(f"{marca} {i}. {mmss(c['t0'])}–{mmss(c['t1'])} {c.get('categoria') or c['tipo']}: {c.get('texto', '')[:60]}")
    return "\n".join(linhas)


def executar(job, frase):
    """Retorna (resposta, acao). acao = 'renderizar' quando pedirem o render."""
    f = sem_acento(frase).strip().rstrip(".!")
    dur = job["midia"]["duracao"]
    ordenar(job)

    if re.fullmatch(r"(ajuda|help|\?|o que voce faz|comandos)", f):
        return AJUDA, None
    if re.fullmatch(r"(lista|mostra|ver)( os)? cortes?|lista", f):
        return lista(job), None
    if re.fullmatch(r"desfaz(er)?|volta( atras)?|undo", f):
        h = job.get("historico") or []
        if not h:
            return "Não tenho nada para desfazer.", None
        job.update(h.pop())
        return "Desfeito.", None
    if re.search(r"\b(renderiza|renderizar|manda ver|pode renderizar|exporta|exportar|finaliza)\b", f):
        return "Mandei para o render. Acompanhe a barra no topo.", "renderizar"

    m = re.search(rf"(?:corta|corte|tira|remove|apaga)\w*\s+(?:de|do|desde)?\s*{T}\s*(?:a|ate|-|ao)\s*{T}", f)
    if m:
        a, b = tempo(m.group(1)), tempo(m.group(2))
        if b <= a:
            return "O fim precisa ser depois do início.", None
        return _manual(job, a, b, f"Corte pedido: {mmss(a)}–{mmss(b)}"), None
    m = re.search(rf"(?:corta|tira|remove)\w*\s+(?:os\s+)?primeiros?\s+{T}", f)
    if m:
        return _manual(job, 0, tempo(m.group(1)), "Começo cortado"), None
    m = re.search(rf"(?:comeca|inicia)\s+(?:em|no|a partir de)\s+{T}|(?:corta|tira)\w*\s+o\s+comeco\s+ate\s+{T}", f)
    if m:
        return _manual(job, 0, tempo(m.group(1) or m.group(2)), "Começo cortado"), None
    m = re.search(rf"(?:corta|tira|remove)\w*\s+(?:os\s+)?ultimos?\s+{T}", f)
    if m:
        return _manual(job, dur - tempo(m.group(1)), dur, "Final cortado"), None
    m = re.search(rf"(?:corta|tira|remove)\w*\s+(?:tudo|o final)\s+(?:depois de|a partir de|apos|desde)\s+{T}|termina\s+em\s+{T}", f)
    if m:
        return _manual(job, tempo(m.group(1) or m.group(2)), dur, "Final cortado"), None

    m = re.search(r"(mantem|mantenha|volta|restaura|desmarca|nao corta)\w*\s+(?:o\s+)?corte\s+(\d+)", f)
    if m or (m := re.search(r"(corta|marca|ativa)\w*\s+(?:o\s+)?corte\s+(\d+)", f)):
        i = int(m.group(2)) - 1
        if not 0 <= i < len(job["cortes"]):
            return f"Não existe o corte {i + 1}. Tenho {len(job['cortes'])}.", None
        _guardar(job)
        c = job["cortes"][i]
        c["ativo"] = m.group(1)[:3] in ("cor", "mar", "ati")
        return f"Corte {i + 1} ({mmss(c['t0'])}) {'vai sair' if c['ativo'] else 'fica no vídeo'}.", None
    m = re.search(r"(mantem|volta|corta|tira)\w*\s+(?:todas\s+)?(?:as\s+)?chamadas", f)
    if m:
        _guardar(job)
        ativo = m.group(1) in ("corta", "tira")
        n = 0
        for c in job["cortes"]:
            if c["tipo"] == "chamada":
                c["ativo"] = ativo
                n += 1
        return f"{n} chamadas {'vão sair' if ativo else 'ficam no vídeo'}.", None

    if re.search(r"\b(sem|tira|remove|corta)\w*\s+(as\s+|os\s+)?(pausas|silencios)", f):
        _guardar(job)
        job["usar_silencios"] = True
        return f"Pausas longas saem ({len(job.get('silencios', []))} trechos).", None
    if re.search(r"\b(com|mantem|deixa)\w*\s+(as\s+|os\s+)?(pausas|silencios)", f):
        _guardar(job)
        job["usar_silencios"] = False
        return "Pausas ficam no vídeo.", None
    m = re.search(r"\bcor\s+(docu|documentario|reality|neutr[ao]|broadcast|original)", f)
    if m:
        _guardar(job)
        job["look"] = {"neu": "neutro", "bro": "neutro", "ori": "original"}.get(m.group(1)[:3], "docu")
        return f"Cor: {job['look']}.", None
    m = re.search(r"\bsaida\s+(?:para\s+)?(o\s+)?(youtube|playout|canal)", f)
    if m:
        _guardar(job)
        job["destino"] = "youtube" if m.group(2) == "youtube" else "playout"
        return f"Saída: {job['destino']}.", None

    return ("Não entendi esse comando. Escreva “ajuda” para ver a lista, "
            "ou ligue a conversa com IA para pedidos livres."), None
