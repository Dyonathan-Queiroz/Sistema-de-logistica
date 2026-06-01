from fastapi import FastAPI, Request, Form, Depends, Cookie, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from sqlalchemy import func, case as sql_case, or_
from passlib.context import CryptContext
from datetime import date, datetime, timedelta
from app.utils import agora
import re
import os

from app.database import get_db
from app.models import Entrega, Usuario, Veiculo, Cliente, Filial
from app.utils import gerar_link_rota

app = FastAPI()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Paths absolutos — funcionam tanto local quanto no Railway
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))

_static_dir = os.path.join(_BASE_DIR, "static")
if os.path.isdir(_static_dir):
    app.mount("/static", StaticFiles(directory=_static_dir), name="static")
templates = Jinja2Templates(directory=os.path.join(_BASE_DIR, "templates"))


# ---------------------------------------------------------------------------
# AUTH
# ---------------------------------------------------------------------------

@app.get("/")
async def root():
    return RedirectResponse(url="/login")


@app.get("/login")
async def login_page(request: Request):
    return templates.TemplateResponse(request=request, name="login.html", context={})


@app.post("/login")
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = db.query(Usuario).filter(Usuario.username == username).first()
    if not user or not user.senha or not pwd_context.verify(password, user.senha):
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={"error": "Usuário ou senha inválidos"},
        )

    redirect_map = {
        "gestor": "/gestor",
        "entregador": "/entregador",
        "operador": "/gestor",  # operador usa painel do gestor por ora (Fase 2 terá tela própria)
    }
    dest = redirect_map.get(user.perfil, "/login")
    res = RedirectResponse(url=dest, status_code=303)
    res.set_cookie(key="user_role", value=user.perfil)
    res.set_cookie(key="user_id", value=str(user.id))
    res.set_cookie(key="user_filial_id", value=str(user.filial_id or ""))
    return res


@app.get("/logout")
async def logout():
    res = RedirectResponse(url="/login")
    res.delete_cookie("user_role")
    res.delete_cookie("user_id")
    res.delete_cookie("user_filial_id")
    return res


# ---------------------------------------------------------------------------
# DASHBOARD DO GESTOR
# ---------------------------------------------------------------------------

@app.get("/gestor")
async def dashboard_gestor(
    request: Request,
    data: str = None,
    db: Session = Depends(get_db),
    user_role: str = Cookie(None),
):
    if user_role not in ("gestor", "operador"):
        return RedirectResponse(url="/login")

    try:
        filtro = date.fromisoformat(data) if data else date.today()
    except ValueError:
        filtro = date.today()

    total_dia = db.query(Entrega).filter(
        func.date(Entrega.data_criacao) == filtro
    ).count()

    finalizadas_dia = db.query(Entrega).filter(
        func.date(Entrega.data_finalizacao) == filtro,
        Entrega.status == "finalizado",
    ).count()

    # Pendentes criadas no dia filtrado
    entregas_loja = db.query(Entrega).filter(
        func.date(Entrega.data_criacao) == filtro,
        Entrega.status == "pendente",
    ).all()

    # Em rota: todas ativas independente da data (visão operacional)
    entregas_rota = db.query(Entrega).filter(Entrega.status == "em_rota").all()

    # Entregas com erro — sempre visíveis, independente da data
    entregas_erro = db.query(Entrega).filter(Entrega.status == "erro_entrega").all()

    # Stats agregados por filial para o dia filtrado
    stats_filiais = (
        db.query(
            Filial.id,
            Filial.nome,
            Filial.cidade,
            func.count(Entrega.id).label("total"),
            func.sum(sql_case((Entrega.status == "pendente", 1), else_=0)).label("pendentes"),
            func.sum(sql_case((Entrega.status == "em_rota", 1), else_=0)).label("em_rota"),
            func.sum(sql_case((Entrega.status == "finalizado", 1), else_=0)).label("finalizadas"),
        )
        .outerjoin(
            Entrega,
            (Entrega.filial_id == Filial.id)
            & (func.date(Entrega.data_criacao) == filtro),
        )
        .group_by(Filial.id, Filial.nome, Filial.cidade)
        .all()
    )

    filiais_map = {f.id: f.nome for f in db.query(Filial).all()}

    return templates.TemplateResponse(
        request=request,
        name="gestor.html",
        context={
            "total_dia": total_dia,
            "finalizadas": finalizadas_dia,
            "entregas_loja": entregas_loja,
            "entregas_rota": entregas_rota,
            "entregas_erro": entregas_erro,
            "loja": len(entregas_loja),
            "rota": len(entregas_rota),
            "erros": len(entregas_erro),
            "data_filtro": filtro.isoformat(),
            "stats_filiais": stats_filiais,
            "filiais_map": filiais_map,
        },
    )


# ---------------------------------------------------------------------------
# DASHBOARD DO ENTREGADOR
# ---------------------------------------------------------------------------

@app.get("/entregador")
async def dashboard_entregador(
    request: Request,
    db: Session = Depends(get_db),
    user_role: str = Cookie(None),
    user_id: str = Cookie(None),
    user_filial_id: str = Cookie(None),
):
    if user_role != "entregador":
        return RedirectResponse(url="/login")

    uid = int(user_id) if user_id and user_id.isdigit() else None
    disponiveis = db.query(Entrega).filter(Entrega.status == "pendente").all()
    em_rota = (
        db.query(Entrega)
        .filter(Entrega.status == "em_rota", Entrega.entregador_id == uid)
        .all()
        if uid
        else []
    )

    # Cidade da filial usada como sufixo nos endereços do Maps
    fid = int(user_filial_id) if user_filial_id and user_filial_id.isdigit() else None
    filial = db.query(Filial).filter(Filial.id == fid).first() if fid else None
    cidade_filial = filial.cidade.strip() if filial and filial.cidade else ""

    link_rota = gerar_link_rota(em_rota, cidade=cidade_filial)

    filiais_map = {f.id: f for f in db.query(Filial).all()}

    return templates.TemplateResponse(
        request=request,
        name="dashboard_entregador.html",
        context={
            "disponiveis":  disponiveis,
            "em_rota":      em_rota,
            "link_rota":    link_rota,
            "filiais_map":  filiais_map,
        },
    )


@app.post("/entregador/aceitar/{entrega_id}")
async def aceitar_entrega(
    entrega_id: int,
    db: Session = Depends(get_db),
    user_id: str = Cookie(None),
    user_role: str = Cookie(None),
):
    if user_role != "entregador":
        return RedirectResponse(url="/login")

    uid = int(user_id) if user_id and user_id.isdigit() else None
    entrega = db.query(Entrega).filter(Entrega.id == entrega_id).first()
    if entrega and entrega.status == "pendente" and uid:
        entrega.status = "em_rota"
        entrega.entregador_id = uid
        entrega.data_aceite = agora()
        db.commit()
    # Abre automaticamente a aba "Em Rota" após aceitar
    return RedirectResponse(url="/entregador?aba=emrota", status_code=303)


@app.get("/entregador/entrega/{entrega_id}")
async def detalhe_entrega(
    request: Request,
    entrega_id: int,
    db: Session = Depends(get_db),
    user_role: str = Cookie(None),
    user_id: str = Cookie(None),
):
    if user_role != "entregador":
        return RedirectResponse(url="/login")

    uid = int(user_id) if user_id and user_id.isdigit() else None
    entrega = db.query(Entrega).filter(
        Entrega.id == entrega_id,
        Entrega.entregador_id == uid,
        Entrega.status == "em_rota",
    ).first()

    if not entrega:
        return RedirectResponse(url="/entregador")

    cliente = db.query(Cliente).filter(Cliente.id == entrega.cliente_id).first()
    telefone_raw = (cliente.telefone or "") if cliente else ""
    telefone_wa = re.sub(r"\D", "", telefone_raw)
    if telefone_wa and not telefone_wa.startswith("55"):
        telefone_wa = "55" + telefone_wa

    # Municipio/UF: prioriza o snapshot da entrega (vindo do Consinco),
    # cai no cadastro do cliente como fallback
    municipio_cliente = (entrega.municipio or (cliente.municipio if cliente else "") or "")
    estado_cliente    = (entrega.uf        or (cliente.estado    if cliente else "") or "")

    partes_maps = [f"{entrega.rua}, {entrega.numero}", entrega.bairro]
    if municipio_cliente:
        partes_maps.append(municipio_cliente)
    if estado_cliente:
        partes_maps.append(estado_cliente)
    partes_maps.append("Brasil")
    endereco_maps = ", ".join(p for p in partes_maps if p)

    return templates.TemplateResponse(
        request=request,
        name="detalhe_entrega.html",
        context={
            "entrega": entrega,
            "telefone": telefone_raw,
            "telefone_wa": telefone_wa,
            "endereco_maps": endereco_maps,
            "nome_cliente": cliente.nome if cliente else "",
            "municipio_cliente": municipio_cliente,
            "estado_cliente": estado_cliente,
        },
    )


@app.post("/entregador/finalizar/{entrega_id}")
async def finalizar_entrega(
    entrega_id: int,
    db: Session = Depends(get_db),
    user_id: str = Cookie(None),
    user_role: str = Cookie(None),
):
    if user_role != "entregador":
        return RedirectResponse(url="/login")

    uid = int(user_id) if user_id and user_id.isdigit() else None
    entrega = db.query(Entrega).filter(Entrega.id == entrega_id).first()
    if entrega and entrega.status == "em_rota" and entrega.entregador_id == uid:
        entrega.status = "finalizado"
        entrega.data_finalizacao = agora()
        db.commit()
    return RedirectResponse(url="/entregador", status_code=303)


@app.post("/entregas/{entrega_id}/reportar-erro")
async def reportar_erro(
    entrega_id: int,
    motivo: str = Form(...),
    db: Session = Depends(get_db),
    user_role: str = Cookie(None),
    user_id: str = Cookie(None),
):
    if user_role != "entregador":
        return RedirectResponse(url="/login")

    uid = int(user_id) if user_id and user_id.isdigit() else None
    entrega = db.query(Entrega).filter(
        Entrega.id == entrega_id,
        Entrega.entregador_id == uid,
        Entrega.status == "em_rota",
    ).first()

    if entrega:
        entrega.status = "erro_entrega"
        entrega.motivo_erro = motivo
        db.commit()

    return RedirectResponse(url="/entregador", status_code=303)


@app.post("/entregas/{entrega_id}/reiniciar")
async def reiniciar_entrega(
    entrega_id: int,
    rua: str = Form(None),
    numero: str = Form(None),
    bairro: str = Form(None),
    db: Session = Depends(get_db),
    user_role: str = Cookie(None),
):
    if user_role not in ("gestor", "operador"):
        return RedirectResponse(url="/login")

    entrega = db.query(Entrega).filter(Entrega.id == entrega_id).first()
    if entrega and entrega.status == "erro_entrega":
        entrega.status = "pendente"
        entrega.entregador_id = None
        entrega.data_aceite = None
        entrega.motivo_erro = None
        if rua and rua.strip():
            entrega.rua = rua.strip()
        if numero and numero.strip():
            entrega.numero = numero.strip()
        if bairro and bairro.strip():
            entrega.bairro = bairro.strip()
        db.commit()

    return RedirectResponse(url="/gestor", status_code=303)


# ---------------------------------------------------------------------------
# AJUSTE DE ENTREGA (Gestor — página dedicada)
# ---------------------------------------------------------------------------

@app.get("/gestor/ajustar-entrega/{entrega_id}")
async def pagina_ajustar_entrega(
    request: Request,
    entrega_id: int,
    db: Session = Depends(get_db),
    user_role: str = Cookie(None),
):
    if user_role not in ("gestor", "operador"):
        return RedirectResponse(url="/login")

    entrega = db.query(Entrega).filter(
        Entrega.id == entrega_id,
        Entrega.status == "erro_entrega",
    ).first()
    if not entrega:
        return RedirectResponse(url="/gestor")

    cliente = db.query(Cliente).filter(Cliente.id == entrega.cliente_id).first()
    return templates.TemplateResponse(
        request=request,
        name="ajustar_entrega.html",
        context={"entrega": entrega, "cliente": cliente},
    )


@app.post("/gestor/ajustar-entrega/{entrega_id}")
async def salvar_ajuste_entrega(
    entrega_id: int,
    rua: str = Form(...),
    numero: str = Form(...),
    bairro: str = Form(...),
    observacao: str = Form(default=""),
    db: Session = Depends(get_db),
    user_role: str = Cookie(None),
):
    if user_role not in ("gestor", "operador"):
        return RedirectResponse(url="/login")

    entrega = db.query(Entrega).filter(
        Entrega.id == entrega_id,
        Entrega.status == "erro_entrega",
    ).first()

    if not entrega:
        return RedirectResponse(url="/gestor")

    entrega.rua = rua.strip()
    entrega.numero = numero.strip()
    entrega.bairro = bairro.strip()
    if observacao.strip():
        entrega.observacao = observacao.strip()
    entrega.status = "pendente"
    entrega.entregador_id = None
    entrega.data_aceite = None
    entrega.motivo_erro = None
    db.commit()

    return RedirectResponse(url="/gestor", status_code=303)


# ---------------------------------------------------------------------------
# LOG DE ENTREGAS
# ---------------------------------------------------------------------------

_PER_PAGE = 20

# ---------------------------------------------------------------------------
# GESTÃO DE DESEMPENHO
# ---------------------------------------------------------------------------

_PERF_GRADIENTS = [
    {"header":"linear-gradient(135deg,#7c3aed,#4f46e5)","avatar":"linear-gradient(135deg,#f59e0b,#b45309)","ring":"#7c3aed"},
    {"header":"linear-gradient(135deg,#1e40af,#3b82f6)","avatar":"linear-gradient(135deg,#374151,#111827)","ring":"#3b82f6"},
    {"header":"linear-gradient(135deg,#c2410c,#f97316)","avatar":"linear-gradient(135deg,#f97316,#c2410c)","ring":"#f97316"},
    {"header":"linear-gradient(135deg,#5b21b6,#7c3aed)","avatar":"linear-gradient(135deg,#6366f1,#4338ca)","ring":"#6366f1"},
    {"header":"linear-gradient(135deg,#065f46,#16a34a)","avatar":"linear-gradient(135deg,#16a34a,#065f46)","ring":"#16a34a"},
    {"header":"linear-gradient(135deg,#9f1239,#e11d48)","avatar":"linear-gradient(135deg,#e11d48,#9f1239)","ring":"#e11d48"},
]
_DIAS_PT = ["SEG","TER","QUA","QUI","SEX","SÁB","DOM"]


@app.get("/gestor/desempenho")
async def desempenho_gestor(
    request: Request,
    db: Session = Depends(get_db),
    user_role: str = Cookie(None),
    inicio: str = None,
    fim: str = None,
    entregador_id: str = None,
    filial_id: str = None,
):
    if user_role not in ("gestor", "operador"):
        return RedirectResponse(url="/login")

    hoje       = agora().date()
    inicio_str = inicio or hoje.replace(day=1).strftime("%Y-%m-%d")
    fim_str    = fim    or hoje.strftime("%Y-%m-%d")
    try:
        inicio_dt = datetime.strptime(inicio_str, "%Y-%m-%d")
        fim_dt    = datetime.strptime(fim_str, "%Y-%m-%d") + timedelta(days=1)
    except ValueError:
        inicio_dt = datetime.combine(hoje.replace(day=1), datetime.min.time())
        fim_dt    = datetime.combine(hoje + timedelta(days=1), datetime.min.time())

    filiais_map       = {f.id: f for f in db.query(Filial).all()}
    todos_entregadores = (
        db.query(Usuario).filter(Usuario.perfil == "entregador").order_by(Usuario.username).all()
    )
    entregas_periodo = db.query(Entrega).filter(
        Entrega.data_criacao >= inicio_dt,
        Entrega.data_criacao <  fim_dt,
    ).all()
    sete_atras  = datetime.combine(hoje - timedelta(days=6), datetime.min.time())
    entregas_7d = db.query(Entrega).filter(Entrega.data_criacao >= sete_atras).all()
    em_rota_ids = {
        e.entregador_id for e in db.query(Entrega).filter(Entrega.status == "em_rota").all()
        if e.entregador_id
    }
    dias_labels = [_DIAS_PT[(hoje - timedelta(days=i)).weekday()] for i in range(6, -1, -1)]

    ranking = []
    for u in todos_entregadores:
        minhas      = [e for e in entregas_periodo if e.entregador_id == u.id]
        total       = len(minhas)
        finalizadas = sum(1 for e in minhas if e.status == "finalizado")
        erros       = sum(1 for e in minhas if e.status == "erro_entrega")
        concluidas  = finalizadas + erros
        taxa_sucesso = round(finalizadas / concluidas * 100) if concluidas > 0 else None

        tr, te, tt = [], [], []
        for e in minhas:
            if e.status == "finalizado" and e.data_aceite and e.data_finalizacao:
                r   = (e.data_aceite      - e.data_criacao).total_seconds() / 60
                en  = (e.data_finalizacao - e.data_aceite).total_seconds()  / 60
                tot = (e.data_finalizacao - e.data_criacao).total_seconds() / 60
                if 0 < r   < 180: tr.append(r)
                if 0 < en  < 300: te.append(en)
                if 0 < tot < 480: tt.append(tot)

        t_reacao  = round(sum(tr) / len(tr)) if tr else None
        t_entrega = round(sum(te) / len(te)) if te else None
        t_total   = round(sum(tt) / len(tt)) if tt else None

        status_atual = (
            "em_rota"    if u.id in em_rota_ids else
            "disponivel" if total > 0            else
            "inativo"
        )

        spark_counts = []
        for i in range(6, -1, -1):
            dia = hoje - timedelta(days=i)
            spark_counts.append(
                sum(1 for e in entregas_7d if e.entregador_id == u.id and e.data_criacao.date() == dia)
            )
        spark_max = max(spark_counts) if any(c > 0 for c in spark_counts) else 1
        spark_avg = round(sum(spark_counts) / 7, 1)
        spark_bars = [
            {
                "pct":     max(int((c / spark_max) * 100), 4) if c > 0 else 4,
                "opacity": round(0.3 + (c / spark_max) * 0.7, 2) if c > 0 else 0.15,
                "label":   dias_labels[i],
            }
            for i, c in enumerate(spark_counts)
        ]

        filial      = filiais_map.get(u.filial_id)
        ring_offset = round(263.9 * (1 - (taxa_sucesso or 0) / 100), 1)

        ranking.append({
            "usuario":      u,
            "filial_nome":  filial.nome if filial else "—",
            "total":        total,
            "finalizadas":  finalizadas,
            "erros":        erros,
            "taxa_sucesso": taxa_sucesso,
            "ring_offset":  ring_offset,
            "t_reacao":     t_reacao,
            "t_entrega":    t_entrega,
            "t_total":      t_total,
            "status_atual": status_atual,
            "spark_bars":   spark_bars,
            "spark_avg":    spark_avg,
        })

    ranking.sort(key=lambda x: (x["finalizadas"], x["total"]), reverse=True)
    for idx, item in enumerate(ranking):
        item["colors"] = _PERF_GRADIENTS[idx % len(_PERF_GRADIENTS)]
        item["rank"]   = idx + 1

    lista_filtrada = ranking[:]
    if entregador_id and entregador_id.isdigit():
        lista_filtrada = [r for r in ranking if r["usuario"].id == int(entregador_id)]
    if filial_id and filial_id.isdigit():
        lista_filtrada = [r for r in lista_filtrada if r["usuario"].filial_id == int(filial_id)]

    ativos      = sum(1 for r in ranking if r["total"] > 0)
    em_rota_cnt = sum(1 for r in ranking if r["status_atual"] == "em_rota")
    total_ent   = sum(r["total"] for r in ranking)
    total_fin   = sum(r["finalizadas"] for r in ranking)
    total_err   = sum(r["erros"] for r in ranking)
    conc_geral  = total_fin + total_err
    taxa_media  = round(total_fin / conc_geral * 100) if conc_geral > 0 else None
    tempos_g    = [r["t_total"] for r in ranking if r["t_total"] is not None]
    tempo_medio = round(sum(tempos_g) / len(tempos_g)) if tempos_g else None

    destaque = ranking[0] if ranking else None
    top3     = ranking[:3]
    filiais  = db.query(Filial).order_by(Filial.nome).all()

    return templates.TemplateResponse(
        request=request,
        name="gestao_desempenho.html",
        context={
            "ranking":        lista_filtrada,
            "top3":           top3,
            "destaque":       destaque,
            "ativos":         ativos,
            "em_rota_cnt":    em_rota_cnt,
            "total_entregas": total_ent,
            "taxa_media":     taxa_media,
            "tempo_medio":    tempo_medio,
            "entregadores":   todos_entregadores,
            "filiais":        filiais,
            "filtros": {
                "inicio":        inicio_str,
                "fim":           fim_str,
                "entregador_id": entregador_id or "",
                "filial_id":     filial_id or "",
            },
        },
    )


# ---------------------------------------------------------------------------
# LOG DE ENTREGAS
# ---------------------------------------------------------------------------

@app.get("/gestor/log")
async def log_entregas_page(
    request: Request,
    db: Session = Depends(get_db),
    user_role: str = Cookie(None),
    inicio: str = None,
    fim: str = None,
    status: str = None,
    filial_id: str = None,
    q: str = None,
    page: int = 1,
):
    if user_role not in ("gestor", "operador"):
        return RedirectResponse(url="/login")

    # ── Datas padrão: últimos 30 dias ──
    hoje = agora().date()
    inicio_str = inicio or (hoje - timedelta(days=30)).strftime("%Y-%m-%d")
    fim_str    = fim    or hoje.strftime("%Y-%m-%d")

    try:
        inicio_dt = datetime.strptime(inicio_str, "%Y-%m-%d")
        fim_dt    = datetime.strptime(fim_str,    "%Y-%m-%d") + timedelta(days=1)
    except ValueError:
        inicio_dt = datetime.combine(hoje - timedelta(days=30), datetime.min.time())
        fim_dt    = datetime.combine(hoje, datetime.max.time())

    # ── Query base (com filtros de data) ──
    base_q = db.query(Entrega).filter(
        Entrega.data_criacao >= inicio_dt,
        Entrega.data_criacao <  fim_dt,
    )

    # ── Stats (contagens por status no período, sem filtro de status) ──
    cnt_total     = base_q.count()
    cnt_pendente  = base_q.filter(Entrega.status == "pendente").count()
    cnt_em_rota   = base_q.filter(Entrega.status == "em_rota").count()
    cnt_finalizado= base_q.filter(Entrega.status == "finalizado").count()
    cnt_erro      = base_q.filter(Entrega.status == "erro_entrega").count()

    # ── Filtros adicionais para a tabela ──
    lista_q = db.query(Entrega).filter(
        Entrega.data_criacao >= inicio_dt,
        Entrega.data_criacao <  fim_dt,
    )
    if status:
        lista_q = lista_q.filter(Entrega.status == status)
    if filial_id:
        try:
            lista_q = lista_q.filter(Entrega.filial_id == int(filial_id))
        except ValueError:
            pass
    if q:
        # busca por cupom fiscal
        lista_q = lista_q.filter(
            or_(
                Entrega.cupom_fiscal.ilike(f"%{q}%"),
            )
        )

    lista_q = lista_q.order_by(Entrega.data_criacao.desc())
    total   = lista_q.count()
    total_pages = max(1, (total + _PER_PAGE - 1) // _PER_PAGE)
    page    = max(1, min(page, total_pages))

    entregas_raw = lista_q.offset((page - 1) * _PER_PAGE).limit(_PER_PAGE).all()

    # ── Enriquece com dados de cliente / filial / entregador ──
    clientes_map  = {c.id: c for c in db.query(Cliente).all()}
    filiais_map   = {f.id: f for f in db.query(Filial).all()}
    usuarios_map  = {u.id: u for u in db.query(Usuario).all()}

    entregas = []
    for e in entregas_raw:
        cli  = clientes_map.get(e.cliente_id)
        fil  = filiais_map.get(e.filial_id)
        ent  = usuarios_map.get(e.entregador_id)
        entregas.append({
            "entrega":        e,
            "cliente_nome":   cli.nome      if cli  else "",
            "cliente_doc":    cli.documento if cli  else "",
            "cliente_tel":    cli.telefone  if cli  else "",
            "filial_nome":    fil.nome      if fil  else "",
            "entregador_nome":ent.username  if ent  else "",
        })

    # ── Querystring preservada para paginação ──
    params = {}
    if inicio: params["inicio"]   = inicio
    if fim:    params["fim"]      = fim
    if status: params["status"]   = status
    if filial_id: params["filial_id"] = filial_id
    if q:      params["q"]        = q
    qs = "&".join(f"{k}={v}" for k, v in params.items())

    filiais = db.query(Filial).order_by(Filial.nome).all()

    return templates.TemplateResponse(
        request=request,
        name="log_entregas.html",
        context={
            "entregas":      entregas,
            "total":         total,
            "page":          page,
            "total_pages":   total_pages,
            "qs":            qs,
            "filiais":       filiais,
            "cnt_total":     cnt_total,
            "cnt_pendente":  cnt_pendente,
            "cnt_em_rota":   cnt_em_rota,
            "cnt_finalizado":cnt_finalizado,
            "cnt_erro":      cnt_erro,
            "filtros": {
                "inicio":    inicio_str,
                "fim":       fim_str,
                "status":    status or "",
                "filial_id": filial_id or "",
                "q":         q or "",
            },
        },
    )


@app.post("/gestor/log/editar/{entrega_id}")
async def salvar_edicao_log(
    entrega_id: int,
    rua:              str  = Form(...),
    numero:           str  = Form(...),
    bairro:           str  = Form(...),
    municipio:        str  = Form(default=""),
    uf:               str  = Form(default=""),
    cep:              str  = Form(default=""),
    observacao:       str  = Form(default=""),
    novo_status:      str  = Form(default=""),
    motivo_erro:      str  = Form(default=""),
    motivo_alteracao: str  = Form(default=""),
    db: Session = Depends(get_db),
    user_role: str = Cookie(None),
):
    if user_role not in ("gestor", "operador"):
        return RedirectResponse(url="/login")

    entrega = db.query(Entrega).filter(Entrega.id == entrega_id).first()
    if not entrega:
        return RedirectResponse(url="/gestor/log", status_code=303)

    # Atualiza campos de endereço
    entrega.rua       = rua.strip()
    entrega.numero    = numero.strip()
    entrega.bairro    = bairro.strip()
    entrega.municipio = municipio.strip() or entrega.municipio
    entrega.uf        = uf.strip().upper() or entrega.uf
    entrega.cep       = cep.strip() or entrega.cep
    if observacao.strip():
        entrega.observacao = observacao.strip()

    # Atualiza status (se solicitado)
    if novo_status in ("pendente", "finalizado", "erro_entrega"):
        entrega.status = novo_status
        if novo_status == "pendente":
            # Reabrir: limpa entregador e datas
            entrega.entregador_id  = None
            entrega.data_aceite    = None
            entrega.data_finalizacao = None
            entrega.motivo_erro    = None
        if novo_status == "finalizado" and not entrega.data_finalizacao:
            entrega.data_finalizacao = agora()

    # Registra motivo do erro quando aplicável
    if motivo_erro.strip():
        entrega.motivo_erro = motivo_erro.strip()

    db.commit()
    return RedirectResponse(url="/gestor/log", status_code=303)


# ---------------------------------------------------------------------------
# GESTÃO DE FUNCIONÁRIOS
# ---------------------------------------------------------------------------

@app.get("/gestao-funcionario")
async def pagina_gestao_funcionario(
    request: Request,
    db: Session = Depends(get_db),
    user_role: str = Cookie(None),
):
    if user_role != "gestor":
        return RedirectResponse(url="/login")

    funcionarios = db.query(Usuario).all()
    filiais = db.query(Filial).order_by(Filial.nome).all()
    return templates.TemplateResponse(
        request=request,
        name="gestao_funcionarios.html",
        context={"funcionarios": funcionarios, "filiais": filiais},
    )


@app.post("/salvar-funcionario")
async def salvar_funcionario(
    username: str = Form(...),
    perfil: str = Form(...),
    senha: str = Form(...),
    filial_id: int = Form(None),
    db: Session = Depends(get_db),
):
    novo = Usuario(
        username=username,
        perfil=perfil,
        senha=pwd_context.hash(senha),
        filial_id=filial_id or None,
    )
    db.add(novo)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
    return RedirectResponse(url="/gestao-funcionario", status_code=303)


@app.get("/editar-funcionario/{func_id}")
async def pagina_editar_funcionario(
    request: Request,
    func_id: int,
    db: Session = Depends(get_db),
    user_role: str = Cookie(None),
):
    if user_role != "gestor":
        return RedirectResponse(url="/login")

    func = db.query(Usuario).filter(Usuario.id == func_id).first()
    filiais = db.query(Filial).order_by(Filial.nome).all()
    return templates.TemplateResponse(
        request=request,
        name="editar_funcionario.html",
        context={"func": func, "filiais": filiais},
    )


@app.post("/processar-funcionario/{func_id}")
async def processar_funcionario(
    func_id: int,
    acao: str = Form(...),
    username: str = Form(None),
    perfil: str = Form(None),
    nova_senha: str = Form(None),
    filial_id: int = Form(None),
    db: Session = Depends(get_db),
):
    func = db.query(Usuario).filter(Usuario.id == func_id).first()
    if func:
        if acao == "excluir":
            # Desvincular entregas antes de excluir (evita erro de chave estrangeira)
            db.query(Entrega).filter(Entrega.entregador_id == func_id).update({"entregador_id": None})
            db.query(Entrega).filter(Entrega.operador_id == func_id).update({"operador_id": None})
            # Desvincular veículos
            db.query(Veiculo).filter(Veiculo.entregador_id == func_id).update({"entregador_id": None})
            db.delete(func)
        else:
            func.username = username
            func.perfil = perfil
            func.filial_id = filial_id or None
            if nova_senha and nova_senha.strip():
                func.senha = pwd_context.hash(nova_senha)
        db.commit()
    return RedirectResponse(url="/gestao-funcionario", status_code=303)


# ---------------------------------------------------------------------------
# GESTÃO DE VEÍCULOS
# ---------------------------------------------------------------------------

@app.get("/gestao-veiculo")
async def pagina_gestao_veiculo(
    request: Request,
    db: Session = Depends(get_db),
    user_role: str = Cookie(None),
):
    if user_role != "gestor":
        return RedirectResponse(url="/login")

    veiculos = db.query(Veiculo).all()
    entregadores = db.query(Usuario).filter(Usuario.perfil == "entregador").all()
    return templates.TemplateResponse(
        request=request,
        name="gestao_veiculos.html",
        context={"veiculos": veiculos, "entregadores": entregadores},
    )


@app.post("/salvar-veiculo")
async def salvar_veiculo(
    placa: str = Form(...),
    modelo: str = Form(...),
    tipo: str = Form(...),
    entregador_id: int = Form(None),
    db: Session = Depends(get_db),
):
    try:
        db.add(Veiculo(placa=placa, modelo=modelo, tipo=tipo, entregador_id=entregador_id))
        db.commit()
    except IntegrityError:
        db.rollback()
    return RedirectResponse(url="/gestao-veiculo", status_code=303)


@app.get("/vincular-veiculo-page/{veiculo_id}")
async def pagina_vincular(
    request: Request,
    veiculo_id: int,
    db: Session = Depends(get_db),
):
    veiculo = db.query(Veiculo).filter(Veiculo.id == veiculo_id).first()
    entregadores = db.query(Usuario).filter(Usuario.perfil == "entregador").all()
    return templates.TemplateResponse(
        request=request,
        name="vincular_veiculo.html",
        context={"veiculo": veiculo, "entregadores": entregadores},
    )


@app.post("/processar-vinculo/{veiculo_id}")
async def processar_vinculo(
    request: Request,
    veiculo_id: int,
    db: Session = Depends(get_db),
):
    form_data = await request.form()
    entregador_id = form_data.get("entregador_id")
    veiculo = db.query(Veiculo).filter(Veiculo.id == veiculo_id).first()
    if veiculo:
        veiculo.entregador_id = (
            int(entregador_id) if entregador_id and str(entregador_id).isdigit() else None
        )
        db.commit()
    return RedirectResponse(url="/gestao-veiculo", status_code=303)


@app.get("/editar-veiculo/{veiculo_id}")
async def pagina_editar_veiculo(
    request: Request,
    veiculo_id: int,
    db: Session = Depends(get_db),
):
    veiculo = db.query(Veiculo).filter(Veiculo.id == veiculo_id).first()
    entregadores = db.query(Usuario).filter(Usuario.perfil == "entregador").all()
    return templates.TemplateResponse(
        request=request,
        name="editar_veiculo.html",
        context={"veiculo": veiculo, "entregadores": entregadores},
    )


@app.post("/processar-veiculo/{veiculo_id}")
async def processar_veiculo(
    veiculo_id: int,
    acao: str = Form(...),
    placa: str = Form(None),
    modelo: str = Form(None),
    tipo: str = Form(None),
    entregador_id: str = Form(None),
    db: Session = Depends(get_db),
):
    veiculo = db.query(Veiculo).filter(Veiculo.id == veiculo_id).first()
    if veiculo:
        if acao == "excluir":
            db.delete(veiculo)
        else:
            veiculo.placa = placa
            veiculo.modelo = modelo
            veiculo.tipo = tipo
            veiculo.entregador_id = (
                int(entregador_id) if entregador_id and entregador_id.isdigit() else None
            )
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
    return RedirectResponse(url="/gestao-veiculo", status_code=303)


# ---------------------------------------------------------------------------
# API — usada pelo PDV desktop
# ---------------------------------------------------------------------------

@app.get("/clientes/{documento}")
async def api_buscar_cliente(documento: str, db: Session = Depends(get_db)):
    cliente = db.query(Cliente).filter(Cliente.documento == documento).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente não encontrado")
    return {
        "id": cliente.id,
        "nome": cliente.nome,
        "telefone": cliente.telefone or "",
        "rua": cliente.rua,
        "numero": cliente.numero,
        "bairro": cliente.bairro,
        "municipio": cliente.municipio or "",
        "estado": cliente.estado or "",
    }


@app.put("/clientes/{documento}")
async def api_atualizar_cliente(documento: str, dados: dict, db: Session = Depends(get_db)):
    cliente = db.query(Cliente).filter(Cliente.documento == documento).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente não encontrado")
    for campo in ("nome", "telefone", "rua", "numero", "bairro"):
        if campo in dados:
            setattr(cliente, campo, dados[campo])
    db.commit()
    return {"status": "ok"}


@app.post("/clientes/")
async def api_cadastrar_cliente(dados: dict, db: Session = Depends(get_db)):
    novo = Cliente(
        nome=dados.get("nome"),
        documento=dados.get("documento"),
        telefone=dados.get("telefone"),
        rua=dados.get("rua"),
        numero=dados.get("numero"),
        bairro=dados.get("bairro"),
        municipio=dados.get("municipio") or None,
        estado=(dados.get("estado") or "").upper() or None,
    )
    db.add(novo)
    try:
        db.commit()
        db.refresh(novo)
        return {"status": "ok", "id": novo.id}
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Documento já cadastrado")


@app.post("/entregas/")
async def api_lancar_entrega(dados: dict, db: Session = Depends(get_db)):
    nova = Entrega(
        cupom_fiscal=dados.get("cupom_fiscal"),
        cliente_id=dados.get("cliente_id"),
        filial_id=dados.get("filial_id", 1),
        operador_id=dados.get("operador_id"),
        rua=dados.get("rua"),
        numero=dados.get("numero"),
        bairro=dados.get("bairro"),
        municipio=dados.get("municipio"),
        uf=dados.get("uf"),
        cep=dados.get("cep"),
        observacao=dados.get("observacao"),
        # IDs de rastreabilidade do Consinco
        nro_checkout=dados.get("nro_checkout"),
        seq_docto=dados.get("seq_docto"),
        seq_pessoa=dados.get("seq_pessoa"),
        status="pendente",
    )
    db.add(nova)
    try:
        db.commit()
        db.refresh(nova)
        return {"status": "ok", "id": nova.id}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


# ---------------------------------------------------------------------------
# GESTÃO DE CLIENTES (CRUD web)
# ---------------------------------------------------------------------------

@app.get("/gestao-clientes")
async def listar_clientes(
    request: Request,
    q: str = None,
    msg: str = None,
    db: Session = Depends(get_db),
    user_role: str = Cookie(None),
):
    if user_role not in ("gestor", "operador"):
        return RedirectResponse(url="/login")

    query = db.query(Cliente)
    if q and q.strip():
        termo = f"%{q.strip()}%"
        query = query.filter(
            or_(
                Cliente.nome.ilike(termo),
                Cliente.telefone.ilike(termo),
                Cliente.documento.ilike(termo),
            )
        )
    clientes = query.order_by(Cliente.nome).all()
    return templates.TemplateResponse(
        request=request,
        name="gestao_clientes.html",
        context={"clientes": clientes, "q": q or "", "msg": msg},
    )


@app.post("/gestao-clientes/novo")
async def criar_cliente_web(
    nome: str = Form(...),
    documento: str = Form(...),
    telefone: str = Form(default=""),
    rua: str = Form(default=""),
    numero: str = Form(default=""),
    bairro: str = Form(default=""),
    municipio: str = Form(default=""),
    estado: str = Form(default=""),
    ponto_referencia: str = Form(default=""),
    db: Session = Depends(get_db),
    user_role: str = Cookie(None),
):
    if user_role not in ("gestor", "operador"):
        return RedirectResponse(url="/login")

    novo = Cliente(
        nome=nome.strip(),
        documento=documento.strip(),
        telefone=telefone.strip() or None,
        rua=rua.strip() or None,
        numero=numero.strip() or None,
        bairro=bairro.strip() or None,
        municipio=municipio.strip() or None,
        estado=estado.strip().upper() or None,
        ponto_referencia=ponto_referencia.strip() or None,
    )
    db.add(novo)
    try:
        db.commit()
        db.refresh(novo)
        return RedirectResponse(url=f"/gestao-clientes/{novo.id}?msg=criado", status_code=303)
    except IntegrityError:
        db.rollback()
        return RedirectResponse(url="/gestao-clientes?msg=doc_duplicado", status_code=303)


@app.get("/gestao-clientes/{cliente_id}")
async def detalhe_cliente_web(
    request: Request,
    cliente_id: int,
    msg: str = None,
    db: Session = Depends(get_db),
    user_role: str = Cookie(None),
):
    if user_role not in ("gestor", "operador"):
        return RedirectResponse(url="/login")

    cliente = db.query(Cliente).filter(Cliente.id == cliente_id).first()
    if not cliente:
        return RedirectResponse(url="/gestao-clientes")

    return templates.TemplateResponse(
        request=request,
        name="detalhe_cliente.html",
        context={"cliente": cliente, "msg": msg},
    )


@app.post("/gestao-clientes/{cliente_id}/salvar")
async def salvar_cliente_web(
    cliente_id: int,
    nome: str = Form(...),
    documento: str = Form(...),
    telefone: str = Form(default=""),
    rua: str = Form(default=""),
    numero: str = Form(default=""),
    bairro: str = Form(default=""),
    municipio: str = Form(default=""),
    estado: str = Form(default=""),
    ponto_referencia: str = Form(default=""),
    db: Session = Depends(get_db),
    user_role: str = Cookie(None),
):
    if user_role not in ("gestor", "operador"):
        return RedirectResponse(url="/login")

    cliente = db.query(Cliente).filter(Cliente.id == cliente_id).first()
    if not cliente:
        return RedirectResponse(url="/gestao-clientes")

    cliente.nome = nome.strip()
    cliente.documento = documento.strip()
    cliente.telefone = telefone.strip() or None
    cliente.rua = rua.strip() or None
    cliente.numero = numero.strip() or None
    cliente.bairro = bairro.strip() or None
    cliente.municipio = municipio.strip() or None
    cliente.estado = estado.strip().upper() or None
    cliente.ponto_referencia = ponto_referencia.strip() or None

    try:
        db.commit()
        return RedirectResponse(url=f"/gestao-clientes/{cliente_id}?msg=atualizado", status_code=303)
    except IntegrityError:
        db.rollback()
        return RedirectResponse(url=f"/gestao-clientes/{cliente_id}?msg=doc_duplicado", status_code=303)


@app.post("/gestao-clientes/{cliente_id}/excluir")
async def excluir_cliente_web(
    cliente_id: int,
    db: Session = Depends(get_db),
    user_role: str = Cookie(None),
):
    if user_role not in ("gestor", "operador"):
        return RedirectResponse(url="/login")

    cliente = db.query(Cliente).filter(Cliente.id == cliente_id).first()
    if cliente:
        try:
            db.delete(cliente)
            db.commit()
        except Exception:
            db.rollback()

    return RedirectResponse(url="/gestao-clientes?msg=excluido", status_code=303)


# ---------------------------------------------------------------------------
# GESTÃO DE FILIAIS
# ---------------------------------------------------------------------------

@app.get("/gestao-filial")
async def pagina_gestao_filial(
    request: Request,
    db: Session = Depends(get_db),
    user_role: str = Cookie(None),
):
    if user_role != "gestor":
        return RedirectResponse(url="/login")

    filiais = db.query(Filial).order_by(Filial.nome).all()

    # Para cada filial, carrega os usuários PDV (operadores) vinculados
    operadores_por_filial = {}
    for f in filiais:
        operadores_por_filial[f.id] = (
            db.query(Usuario)
            .filter(Usuario.filial_id == f.id, Usuario.perfil == "operador")
            .all()
        )

    return templates.TemplateResponse(
        request=request,
        name="gestao_filiais.html",
        context={"filiais": filiais, "operadores_por_filial": operadores_por_filial},
    )


@app.post("/salvar-filial")
async def salvar_filial(
    nome: str = Form(...),
    cidade: str = Form(""),
    db: Session = Depends(get_db),
    user_role: str = Cookie(None),
):
    if user_role != "gestor":
        return RedirectResponse(url="/login")

    db.add(Filial(nome=nome, cidade=cidade))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
    return RedirectResponse(url="/gestao-filial", status_code=303)


@app.post("/processar-filial/{filial_id}")
async def processar_filial(
    filial_id: int,
    acao: str = Form(...),
    nome: str = Form(None),
    cidade: str = Form(None),
    db: Session = Depends(get_db),
    user_role: str = Cookie(None),
):
    if user_role != "gestor":
        return RedirectResponse(url="/login")

    filial = db.query(Filial).filter(Filial.id == filial_id).first()
    if filial:
        if acao == "excluir":
            try:
                db.delete(filial)
                db.commit()
            except IntegrityError:
                db.rollback()
        else:
            filial.nome = nome
            filial.cidade = cidade
            db.commit()
    return RedirectResponse(url="/gestao-filial", status_code=303)
