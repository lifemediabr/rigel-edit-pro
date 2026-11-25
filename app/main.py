"""Rigel Edit Pro — Constelação Órion.
Biblioteca (baixador), editor automático com revisão, comandos rápidos e conversa com IA (chave de cada usuário)."""
import json, os, queue, secrets, shutil, threading, time, traceback, uuid, hashlib
from pathlib import Path

from fastapi import FastAPI, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from itsdangerous import URLSafeSerializer, BadSignature

import pipeline as P
import comandos as C
import idiomas as I
import ia as IA

BASE = Path(__file__).parent
DADOS = Path(os.environ.get("RIGEL_DADOS", "/dados"))
JOBS, BIB, USR = DADOS / "jobs", DADOS / "biblioteca", DADOS / "usuarios"
for d in (JOBS, BIB, USR):
    d.mkdir(parents=True, exist_ok=True)
SEGREDO = os.environ.get("RIGEL_SEGREDO") or secrets.token_hex(32)
MODELO = os.environ.get("WHISPER_MODELO", "small")
assinador = URLSafeSerializer(SEGREDO, salt="rigel")


def _usuarios():
    """RIGEL_USUARIOS="kennedy:senha1,carlos:senha2" (ou só RIGEL_SENHA para um usuário 'admin')."""
    u = {}
    for par in (os.environ.get("RIGEL_USUARIOS") or "").split(","):
        if ":" in par:
            n, s = par.split(":", 1)
            u[n.strip().lower()] = s.strip()
    if not u and os.environ.get("RIGEL_SENHA"):
        u["admin"] = os.environ["RIGEL_SENHA"]
    return u


USUARIOS = _usuarios()

app = FastAPI(title="Rigel Edit Pro")
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
tpl = Jinja2Templates(directory=BASE / "templates")
tpl.env.filters["mmss"] = P.mmss
ETAPAS = {"fila": "Na fila", "baixando": "Baixando", "analisando": "Analisando", "revisao": "Em revisão",
          "renderizando": "Renderizando", "pronto": "Pronto", "erro": "Erro", "traduzindo": "Traduzindo",
          "dublando": "Dublando"}


# ---------------------------------------------------------------- armazenamento
def _ler(p: Path):
    return json.loads(p.read_text()) if p.exists() else None


TRAVA = threading.RLock()


def _gravar(p: Path, d):
    with TRAVA:
        tmp = p.with_name(p.name + f".{uuid.uuid4().hex[:6]}.tmp")
        tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1))
        tmp.replace(p)


def mexer_job(jid, **campos):
    """Atualiza só alguns campos relendo o arquivo (não apaga o que o usuário mudou no meio do render)."""
    with TRAVA:
        j = ler_job(jid)
        if j is None:
            return None
        j.update(campos)
        gravar_job(j)
        return j


ler_job = lambda jid: _ler(JOBS / jid / "job.json")
gravar_job = lambda j: _gravar(JOBS / j["id"] / "job.json", j)
ler_item = lambda lid: _ler(BIB / lid / "item.json")
gravar_item = lambda it: _gravar(BIB / it["id"] / "item.json", it)


def lista_jobs():
    js = [_ler(p / "job.json") for p in JOBS.iterdir() if (p / "job.json").exists()]
    return sorted([j for j in js if j], key=lambda j: j["criado"], reverse=True)


def lista_bib():
    its = [_ler(p / "item.json") for p in BIB.iterdir() if (p / "item.json").exists()]
    return sorted([i for i in its if i], key=lambda i: i["criado"], reverse=True)


def cfg_usuario(nome):
    return _ler(USR / f"{hashlib.sha1(nome.encode()).hexdigest()[:12]}.json") or {}


def salvar_cfg(nome, cfg):
    _gravar(USR / f"{hashlib.sha1(nome.encode()).hexdigest()[:12]}.json", cfg)


def novo_id():
    return time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4]


# ---------------------------------------------------------------- fila única (um trabalho pesado por vez)
fila: "queue.Queue[tuple]" = queue.Queue()


def tarefa_baixar(it):
    pasta = BIB / it["id"]
    it["etapa"] = "baixando"; gravar_item(it)
    if it.get("link"):
        res = P.baixar(it["link"], pasta, it.get("idioma_pedido") or "")
        it.update(res)
    m = P.analisar_midia(Path(it["arquivo"]))
    it["duracao"] = m["duracao"]
    if not (pasta / "video.jpg").exists():
        P.quadro(Path(it["arquivo"]), min(5, m["duracao"] / 3), pasta / "video.jpg")
    it.setdefault("versoes", [{"nome": "Original", "arquivo": it["arquivo"]}])
    it["etapa"] = "pronto"; gravar_item(it)
    if it.get("editar_depois"):
        criar_job_de_item(it, it["versoes"][0]["arquivo"])


def tarefa_traduzir(it, para):
    it["etapa"] = "traduzindo"; gravar_item(it)
    I.legenda_no_idioma(it, BIB / it["id"], para, MODELO)
    it["etapa"] = "pronto"; gravar_item(it)


def tarefa_dublar(it, para, provedor, usuario):
    pasta = BIB / it["id"]
    it["etapa"] = "dublando"; it["progresso"] = 0; gravar_item(it)
    srt = I.legenda_no_idioma(it, pasta, para, MODELO)
    gravar_item(it)
    cues = P.ler_srt(srt)

    def prog(p):
        it["progresso"] = round(p); gravar_item(it)
    saida = I.dublar(Path(it["arquivo"]), cues, para, pasta, provedor, cfg_usuario(usuario), DADOS / "vozes", prog)
    nome = f"Dublado {I.NOMES.get(para, para)} ({'Piper' if provedor == 'piper' else 'ElevenLabs'})"
    it["versoes"] = [v for v in it["versoes"] if v["arquivo"] != str(saida)] + [{"nome": nome, "arquivo": str(saida)}]
    it["etapa"] = "pronto"; it["progresso"] = 100; gravar_item(it)


def tarefa_analisar(job):
    pasta = JOBS / job["id"]
    arq = Path(job["arquivo"])
    job["etapa"] = "analisando"; gravar_job(job)
    job["midia"] = P.analisar_midia(arq)
    transc = P.transcrever(arq, pasta, MODELO, job.get("idioma") or None)
    cortes = P.achar_chamadas(transc)
    fim = P.sugerir_tela_final(transc, job["midia"]["duracao"])
    if fim:
        cortes.append(fim)
    (pasta / "quadros").mkdir(exist_ok=True)
    for i, c in enumerate(sorted(cortes, key=lambda c: c["t0"])):
        c["id"] = f"c{i}"
        q = pasta / "quadros" / f"{c['id']}.jpg"
        P.quadro(arq, (c["t0"] + min(c["t1"], c["t0"] + 4)) / 2, q)
        c["quadro"] = q.name
    P.tira_de_quadros(arq, job["midia"]["duracao"], pasta / "tira.jpg")
    P.forma_de_onda(arq, pasta / "onda.png")
    job.update(cortes=sorted(cortes, key=lambda c: c["t0"]), silencios=P.achar_silencios(arq, job["midia"]["duracao"]),
               idioma_detectado=transc.get("idioma"), etapa="revisao")
    job.setdefault("chat", []).append({"de": "rigel", "modo": "rapido", "texto":
        f"Analisei o vídeo. Achei {len([c for c in cortes if c['tipo'] == 'chamada'])} chamadas"
        f"{', a tela final' if fim else ''} e {len(job['silencios'])} pausas longas. "
        "Confira na lista ou me diga o que mudar. Escreva “ajuda” para ver os comandos."})
    gravar_job(job)


def tarefa_render(job):
    pasta = JOBS / job["id"]
    jid = job["id"]
    mexer_job(jid, etapa="renderizando", progresso=0)
    ult = [0.0]

    def prog(p):
        if time.time() - ult[0] > 2:
            ult[0] = time.time(); mexer_job(jid, progresso=round(p))
    cortes = job["cortes"] + (job["silencios"] if job.get("usar_silencios", True) else [])
    saida, segs, dur = P.renderizar(Path(job["arquivo"]), pasta, cortes, job["midia"]["duracao"],
                                    job.get("look", "docu"), job.get("destino", "playout"), prog)
    arq = Path(job["arquivo"])
    P.gerar_edl(segs, arq.name, job["midia"]["fps"], pasta / "rigel_davinci.edl")
    P.gerar_xml_fcp7(segs, arq, job["midia"], pasta / "rigel_filmora_davinci_premiere.xml", job.get("titulo") or "Rigel")
    tr = _ler(pasta / "transcricao.json") or {}
    if tr.get("palavras"):
        P.srt_editado(tr["palavras"], segs, pasta / "rigel_legenda.srt")
    (pasta / "rigel_clipes_capcut.zip").unlink(missing_ok=True)
    with TRAVA:
        j = ler_job(jid)
        j.update(etapa="pronto", progresso=100, duracao_final=dur, saida=saida.name, renderizado_em=time.time(),
                 segmentos=segs, clipes=None)
        j.setdefault("chat", []).append({"de": "rigel", "modo": "rapido", "texto":
            f"Pronto: {P.mmss(j['midia']['duracao'])} → {P.mmss(dur)}. Veja em Final ou na aba Exportar "
            "(MP4, XML para Filmora/DaVinci/Premiere, clipes para CapCut, legenda)."})
        gravar_job(j)


def tarefa_clipes(job):
    pasta = JOBS / job["id"]
    mexer_job(job["id"], clipes="gerando", progresso_clipes=0)
    P.pacote_clipes(Path(job["arquivo"]), job["segmentos"], pasta, lambda p: mexer_job(job["id"], progresso_clipes=round(p)))
    mexer_job(job["id"], clipes="pronto")


def trabalhador():
    while True:
        tipo, ident, *extra = fila.get()
        alvo = ler_item(ident) if tipo in ("baixar", "traduzir", "dublar") else ler_job(ident)
        if not alvo:
            continue
        try:
            {"baixar": lambda: tarefa_baixar(alvo), "traduzir": lambda: tarefa_traduzir(alvo, *extra),
             "dublar": lambda: tarefa_dublar(alvo, *extra), "analisar": lambda: tarefa_analisar(alvo),
             "renderizar": lambda: tarefa_render(alvo), "clipes": lambda: tarefa_clipes(alvo)}[tipo]()
        except Exception as e:
            traceback.print_exc()
            if tipo in ("baixar", "traduzir", "dublar"):
                alvo.update(etapa="erro", erro=str(e)[:1200]); gravar_item(alvo)
            elif tipo == "clipes":
                mexer_job(ident, clipes="erro", erro_clipes=str(e)[:600])
            else:
                mexer_job(ident, etapa="erro", erro=str(e)[:1200])


def retomar():
    for it in lista_bib():
        if it["etapa"] in ("fila", "baixando"):
            fila.put(("baixar", it["id"]))
        elif it["etapa"] in ("traduzindo", "dublando"):
            it.update(etapa="erro", erro="O servidor reiniciou no meio. Peça de novo."); gravar_item(it)
    for j in lista_jobs():
        if j["etapa"] in ("fila", "analisando") and not j.get("midia"):
            fila.put(("analisar", j["id"]))
        elif j["etapa"] in ("fila", "renderizando") and j.get("midia"):
            fila.put(("renderizar", j["id"]))


threading.Thread(target=trabalhador, daemon=True).start()
retomar()


def criar_job_de_item(it, arquivo, titulo=None):
    jid = novo_id()
    (JOBS / jid).mkdir(parents=True)
    job = {"id": jid, "criado": time.time(), "titulo": titulo or it.get("titulo"), "item": it["id"],
           "arquivo": arquivo, "look": "docu", "destino": "playout", "usar_silencios": True, "etapa": "fila",
           "canal": it.get("canal", "Raíces"), "chat": []}
    gravar_job(job)
    fila.put(("analisar", jid))
    return job


# ---------------------------------------------------------------- login
def usuario(req: Request):
    try:
        n = assinador.loads(req.cookies.get("rigel", ""))
        return n if n in USUARIOS else None
    except BadSignature:
        return None


@app.middleware("http")
async def protege(req: Request, call_next):
    livre = req.url.path.startswith("/static") or req.url.path in ("/entrar", "/saude")
    if not livre and not usuario(req):
        if req.url.path.startswith("/api/"):
            return JSONResponse({"erro": "sessão expirada"}, 401)
        return RedirectResponse("/entrar", 303)
    return await call_next(req)


@app.get("/saude")
def saude():
    return {"ok": True}


@app.get("/entrar", response_class=HTMLResponse)
def entrar_form(req: Request, erro: str = ""):
    return tpl.TemplateResponse(req, "entrar.html", {"erro": erro, "multi": len(USUARIOS) > 1 or "admin" not in USUARIOS})


@app.post("/entrar")
def entrar(nome: str = Form("admin"), senha: str = Form(...)):
    time.sleep(0.5)
    nome = (nome or "admin").strip().lower()
    if nome not in USUARIOS or not secrets.compare_digest(senha, USUARIOS[nome]):
        return RedirectResponse("/entrar?erro=1", 303)
    r = RedirectResponse("/", 303)
    r.set_cookie("rigel", assinador.dumps(nome), httponly=True, samesite="lax", max_age=60 * 60 * 24 * 30,
                 secure=os.environ.get("RIGEL_HTTPS", "1") == "1")
    return r


@app.get("/sair")
def sair():
    r = RedirectResponse("/entrar", 303)
    r.delete_cookie("rigel")
    return r


# ---------------------------------------------------------------- páginas
@app.get("/", response_class=HTMLResponse)
def inicio(req: Request):
    return tpl.TemplateResponse(req, "inicio.html", {"itens": lista_bib(), "jobs": lista_jobs(), "etapas": ETAPAS,
                                                     "nomes": I.NOMES, "usuario": usuario(req)})


@app.get("/editor/{jid}", response_class=HTMLResponse)
def editor(req: Request, jid: str):
    job = ler_job(jid)
    if not job:
        return RedirectResponse("/", 303)
    cfg = cfg_usuario(usuario(req))
    return tpl.TemplateResponse(req, "editor.html", {"job": job, "usuario": usuario(req), "tem_ia": bool(cfg.get("ia_chave")),
                                                     "ia_nome": IA.PROVEDORES.get(cfg.get("ia_provedor") or "anthropic")["nome"]})


@app.get("/config", response_class=HTMLResponse)
def config(req: Request, ok: str = ""):
    cfg = cfg_usuario(usuario(req))
    seguro = {k: v for k, v in cfg.items() if "chave" not in k}
    seguro["tem_ia"] = bool(cfg.get("ia_chave"))
    seguro["tem_eleven"] = bool(cfg.get("eleven_chave"))
    seguro["tem_cookies"] = P.COOKIES_YT.exists()
    return tpl.TemplateResponse(req, "config.html", {"cfg": seguro, "usuario": usuario(req), "ok": ok,
                                                     "provedores": IA.PROVEDORES})


@app.post("/config")
async def config_salvar(req: Request):
    nome = usuario(req)
    cfg = cfg_usuario(nome)
    f = await req.form()
    for k in ("ia_provedor", "ia_modelo", "ia_base", "eleven_voz", "eleven_modelo"):
        cfg[k] = (f.get(k) or "").strip()
    for k in ("ia_chave", "eleven_chave"):       # só troca se digitar algo; nunca é devolvida à tela
        v = (f.get(k) or "").strip()
        if v:
            cfg[k] = v
        if f.get(f"apagar_{k}"):
            cfg.pop(k, None)
    salvar_cfg(nome, cfg)
    ck = f.get("yt_cookies")
    if ck is not None and getattr(ck, "filename", ""):
        txt = (await ck.read()).decode("utf-8", "ignore")
        if "youtube.com" not in txt:
            return RedirectResponse("/config?ok=cookies_invalidos", 303)
        fd = os.open(str(P.COOKIES_YT), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as fh:
            fh.write(txt)
    if f.get("apagar_cookies"):
        P.COOKIES_YT.unlink(missing_ok=True)
    return RedirectResponse("/config?ok=1", 303)


# ---------------------------------------------------------------- biblioteca
@app.post("/importar")
async def importar(link: str = Form(""), titulo: str = Form(""), idioma: str = Form(""), canal: str = Form("Raíces"),
                   destino: str = Form("biblioteca"), autorizado: str = Form(""), arquivo: UploadFile | None = File(None)):
    if not autorizado:
        return RedirectResponse("/?erro=autorizacao", 303)
    lid = novo_id()
    pasta = BIB / lid
    pasta.mkdir(parents=True)
    it = {"id": lid, "criado": time.time(), "titulo": titulo or link or (arquivo.filename if arquivo else lid),
          "link": link.strip(), "idioma_pedido": idioma, "canal": canal, "etapa": "fila", "legendas": [],
          "editar_depois": destino == "editar"}
    if arquivo and arquivo.filename:
        dest = pasta / f"video{Path(arquivo.filename).suffix.lower() or '.mp4'}"
        with dest.open("wb") as fh:
            shutil.copyfileobj(arquivo.file, fh, 8 * 1024 * 1024)
        it.update(arquivo=str(dest), link="", titulo=titulo or Path(arquivo.filename).stem)
    elif not it["link"]:
        shutil.rmtree(pasta)
        return RedirectResponse("/?erro=sem_video", 303)
    gravar_item(it)
    fila.put(("baixar", lid))
    return RedirectResponse("/#biblioteca", 303)


@app.post("/biblioteca/{lid}/editar")
def bib_editar(lid: str, versao: int = Form(0)):
    it = ler_item(lid)
    if not it or it["etapa"] == "erro" and not it.get("versoes"):
        return RedirectResponse("/", 303)
    v = it["versoes"][min(versao, len(it["versoes"]) - 1)]
    job = criar_job_de_item(it, v["arquivo"], f"{it['titulo']}" + ("" if versao == 0 else f" · {v['nome']}"))
    return RedirectResponse(f"/editor/{job['id']}", 303)


@app.post("/biblioteca/{lid}/traduzir")
def bib_traduzir(lid: str, para: str = Form(...)):
    fila.put(("traduzir", lid, para))
    return RedirectResponse("/#biblioteca", 303)


@app.post("/api/biblioteca/{lid}/estimar")
async def bib_estimar(req: Request, lid: str):
    d = await req.json()
    it = ler_item(lid)
    para, prov = d.get("para"), d.get("provedor")
    if prov == "eleven":
        cfg = cfg_usuario(usuario(req))
        if not (cfg.get("eleven_chave") and cfg.get("eleven_voz")):
            return {"erro": "Configure a sua chave e a voz da ElevenLabs em Configurações."}
    leg = {l["idioma"]: l for l in it.get("legendas", [])}
    if para in leg:
        cues = P.ler_srt(BIB / lid / leg[para]["arquivo"])
        base = "legenda pronta"
    else:
        # sem legenda ainda: estima pela duração (~14 caracteres por segundo de fala) [A VALIDAR]
        cues = [(0, 0, "x" * int(it.get("duracao", 0) * 14))]
        base = "estimativa pela duração; o número exato sai depois da tradução"
    e = I.estimar(cues, "piper" if prov == "piper" else "eleven", cfg_usuario(usuario(req)).get("eleven_modelo") or "eleven_multilingual_v2")
    e["base"] = base
    return e


@app.post("/biblioteca/{lid}/dublar")
def bib_dublar(req: Request, lid: str, para: str = Form(...), provedor: str = Form("piper"), confirmo: str = Form("")):
    if provedor != "piper" and not confirmo:
        return RedirectResponse("/#biblioteca", 303)
    fila.put(("dublar", lid, para, provedor, usuario(req)))
    return RedirectResponse("/#biblioteca", 303)


@app.post("/biblioteca/{lid}/apagar")
def bib_apagar(lid: str):
    p = (BIB / lid).resolve()
    if BIB.resolve() in p.parents and p.is_dir():
        shutil.rmtree(p)
    return RedirectResponse("/#biblioteca", 303)


@app.get("/biblioteca/{lid}/arquivo/{nome:path}")
def bib_arquivo(lid: str, nome: str):
    return _servir(BIB / lid, nome)


def _servir(pasta: Path, nome: str):
    pasta = pasta.resolve()
    alvo = (pasta / nome).resolve()
    if pasta not in alvo.parents or not alvo.is_file():
        return JSONResponse({"erro": "não encontrado"}, 404)
    baixa = alvo.suffix in (".edl", ".srt", ".xml", ".zip") or alvo.name.startswith("rigel_final")
    return FileResponse(alvo, filename=alvo.name if baixa else None)


# ---------------------------------------------------------------- editor (API)
def _estado(job):
    j = {k: v for k, v in job.items() if k not in ("historico",)}
    j["pode_desfazer"] = bool(job.get("historico"))
    return j


@app.get("/api/job/{jid}")
def api_job(jid: str):
    j = ler_job(jid)
    return _estado(j) if j else JSONResponse({"erro": "não encontrado"}, 404)


@app.post("/api/job/{jid}/corte")
async def api_corte(jid: str, req: Request):
    d = await req.json()
    TRAVA.acquire()
    try:
        return _api_corte(jid, d)
    finally:
        TRAVA.release()


def _api_corte(jid, d):
    job = ler_job(jid)
    C._guardar(job)
    for c in job["cortes"]:
        if c["id"] == d.get("id"):
            c["ativo"] = bool(d.get("ativo"))
    for k in ("usar_silencios", "look", "destino"):
        if k in d:
            job[k] = d[k]
    gravar_job(job)
    return _estado(job)


@app.post("/api/job/{jid}/mensagem")
async def api_mensagem(jid: str, req: Request):
    d = await req.json()
    texto, modo = (d.get("texto") or "").strip()[:2000], d.get("modo", "rapido")
    job = ler_job(jid)
    if not texto or not job or not job.get("midia"):
        return _estado(job)
    job.setdefault("chat", []).append({"de": "voce", "modo": modo, "texto": texto})
    acao, uso = None, None
    try:
        if modo == "ia":
            tr = _ler(JOBS / jid / "transcricao.json") or {}
            job["palavras"] = tr.get("palavras", [])
            resp, acao, uso = IA.conversar(job, cfg_usuario(usuario(req)), texto)
            job.pop("palavras", None)
        else:
            resp, acao = C.executar(job, texto)
    except Exception as e:
        job.pop("palavras", None)
        resp = f"⚠ {e}"
    job["chat"].append({"de": "rigel", "modo": modo, "texto": resp, "uso": uso})
    del job["chat"][:-80]
    with TRAVA:   # junta só o que a conversa mexe com o estado mais novo (o render pode ter andado)
        novo = ler_job(jid)
        for k in ("cortes", "usar_silencios", "look", "destino", "historico", "chat"):
            if k in job:
                novo[k] = job[k]
        if acao == "renderizar" and novo["etapa"] not in ("fila", "renderizando"):
            novo["etapa"] = "fila"
            fila.put(("renderizar", jid))
        gravar_job(novo)
    return _estado(novo)


@app.post("/api/job/{jid}/renderizar")
def api_render(jid: str):
    job = ler_job(jid)
    if job and job.get("midia") and job["etapa"] not in ("fila", "renderizando"):
        job["etapa"] = "fila"; job.pop("erro", None); gravar_job(job)
        fila.put(("renderizar", jid))
    return _estado(job)


@app.post("/api/job/{jid}/clipes")
def api_clipes(jid: str):
    job = ler_job(jid)
    if job and job.get("segmentos") and job.get("clipes") not in ("gerando", "fila"):
        job["clipes"] = "fila"; gravar_job(job)
        fila.put(("clipes", jid))
    return _estado(job)


@app.get("/job/{jid}/arquivo/{nome:path}")
def job_arquivo(jid: str, nome: str):
    return _servir(JOBS / jid, nome)


@app.get("/job/{jid}/original")
def job_original(jid: str, baixar: int = 0):
    job = ler_job(jid)
    if not job:
        return JSONResponse({}, 404)
    return FileResponse(job["arquivo"], filename=Path(job["arquivo"]).name if baixar else None)


@app.post("/job/{jid}/apagar")
def job_apagar(jid: str):
    p = (JOBS / jid).resolve()
    if JOBS.resolve() in p.parents and p.is_dir():
        shutil.rmtree(p)
    return RedirectResponse("/", 303)
