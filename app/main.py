from fastapi import FastAPI, Request, Form, Depends, Cookie, HTTPException, Response
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy import func, case as sql_case, or_
from passlib.context import CryptContext
from pydantic import BaseModel
from typing import Optional, List
from datetime import date, datetime, timedelta
from app.utils import agora
from collections import defaultdict
import re
import os
import hmac
import hashlib
import secrets

from app.database import get_db
from app.models import (
    Entrega, Usuario, Veiculo, Cliente, Filial,
    Checklist, TurnoEntrega, Abastecimento, Manutencao, PneuControle, MotoristaScore,
    Oficina, PecaCatalogo, PontoRota,
)
from app.utils import gerar_link_rota

app = FastAPI()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

class PontoRotaIn(BaseModel):
    lat: float
    lng: float
    tipo: str = "rota"


# ---------------------------------------------------------------------------
# SEGURANÇA DE SESSÃO — cookies de autenticação assinados (HMAC-SHA256)
# ---------------------------------------------------------------------------
# Os cookies user_role / user_id / user_filial_id definem a identidade e o
# nível de acesso. Para impedir que sejam forjados pelo navegador (ex.: abrir
# o DevTools e definir user_role=gestor), o login grava também um cookie
# auth_sig com a assinatura HMAC dos três valores. Um middleware valida essa
# assinatura em toda requisição e descarta cookies adulterados.
SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    # Fallback efêmero: mantém o app funcional, mas as sessões expiram a cada
    # reinício do processo. Defina SECRET_KEY no .env para produção.
    SECRET_KEY = secrets.token_hex(32)

# Cookies só trafegam por HTTPS quando COOKIE_SECURE=true (produção atrás de
# TLS, como na Railway). Em desenvolvimento local (http://localhost) deixe a
# variável ausente/false, senão o navegador não envia os cookies.
_COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() == "true"
_AUTH_COOKIES = ("user_role", "user_id", "user_filial_id", "auth_sig")


def _assinar_sessao(role: str, uid: str, filial: str) -> str:
    """Assinatura HMAC-SHA256 dos três valores de identidade da sessão."""
    msg = f"{role}|{uid}|{filial}".encode("utf-8")
    return hmac.new(SECRET_KEY.encode("utf-8"), msg, hashlib.sha256).hexdigest()


def _set_cookies_sessao(res: Response, role: str, uid: str, filial: str) -> None:
    """Grava os cookies de sessão já assinados e com flags de segurança."""
    sig = _assinar_sessao(role, uid, filial)
    opts = dict(httponly=True, samesite="lax", secure=_COOKIE_SECURE)
    res.set_cookie("user_role", role, **opts)
    res.set_cookie("user_id", uid, **opts)
    res.set_cookie("user_filial_id", filial, **opts)
    res.set_cookie("auth_sig", sig, **opts)


def _exigir_perfil(user_id: Optional[str], db: Session, perfis: tuple) -> Usuario:
    """
    Valida a sessão e exige que o perfil do usuário (do banco, não do cookie)
    esteja em `perfis`. Lança 401 se não autenticado, 403 se sem permissão.
    """
    usuario = _resolver_usuario(user_id, db)
    if usuario.perfil not in perfis:
        raise HTTPException(status_code=403, detail="Acesso restrito")
    return usuario


@app.middleware("http")
async def _validar_assinatura_sessao(request: Request, call_next):
    """
    Rejeita cookies de autenticação adulterados/forjados.

    Se user_role ou user_id estão presentes mas a assinatura auth_sig não
    confere, os cookies de auth são removidos do header Cookie no escopo da
    requisição (compartilhado com o handler). O handler então enxerga a
    requisição como anônima e aplica seu próprio redirecionamento para /login.
    Isso impede escalonamento de privilégio via edição manual de cookies.
    """
    cookies = request.cookies
    role   = cookies.get("user_role")
    uid    = cookies.get("user_id")
    filial = cookies.get("user_filial_id") or ""
    sig    = cookies.get("auth_sig")

    if role is not None or uid is not None:
        esperado = _assinar_sessao(role or "", uid or "", filial)
        if not sig or not hmac.compare_digest(sig, esperado):
            restantes = {k: v for k, v in cookies.items() if k not in _AUTH_COOKIES}
            novos_headers = [
                (k, v) for (k, v) in request.scope["headers"] if k != b"cookie"
            ]
            if restantes:
                cookie_str = "; ".join(f"{k}={v}" for k, v in restantes.items())
                novos_headers.append((b"cookie", cookie_str.encode("latin-1")))
            request.scope["headers"] = novos_headers

    return await call_next(request)


@app.on_event("startup")
async def _startup_migrations():
    """
    Adiciona colunas novas à tabela manutencoes sem recriar a tabela.
    Cada ALTER TABLE é executado individualmente; erros de 'Duplicate column'
    são silenciados — idempotente em qualquer estado do banco.
    """
    from sqlalchemy import text
    from app.database import engine

    _ddl = [
        "ALTER TABLE manutencoes ADD COLUMN status ENUM('pendente','aprovada','rejeitada') NOT NULL DEFAULT 'aprovada'",
        "ALTER TABLE manutencoes ADD COLUMN motorista_id INT NULL",
        "ALTER TABLE manutencoes ADD COLUMN descricao_problema VARCHAR(500) NULL",
        "ALTER TABLE manutencoes ADD COLUMN observacao_gestor  VARCHAR(500) NULL",
        """CREATE TABLE IF NOT EXISTS oficinas (
            id       INT          NOT NULL AUTO_INCREMENT PRIMARY KEY,
            nome     VARCHAR(100) NOT NULL,
            telefone VARCHAR(20),
            endereco VARCHAR(200),
            ativo    TINYINT(1)   NOT NULL DEFAULT 1
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
        """CREATE TABLE IF NOT EXISTS pecas_catalogo (
            id        INT          NOT NULL AUTO_INCREMENT PRIMARY KEY,
            nome      VARCHAR(100) NOT NULL,
            categoria VARCHAR(50),
            unidade   VARCHAR(20)  DEFAULT 'un',
            ativo     TINYINT(1)   NOT NULL DEFAULT 1
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    ]
    with engine.connect() as conn:
        for sql in _ddl:
            try:
                conn.execute(text(sql))
                conn.commit()
            except OperationalError:
                pass  # coluna/tabela já existe — ignora

        # Seed — insere dados iniciais apenas se as tabelas estiverem vazias
        try:
            qtd_of = conn.execute(text("SELECT COUNT(*) FROM oficinas")).scalar()
            if qtd_of == 0:
                conn.execute(text("""
                    INSERT INTO oficinas (nome, telefone, endereco) VALUES
                    ('Auto Center Boa Vista',  '(95) 3224-1100', 'Av. Ville Roy, 4567 — Boa Vista/RR'),
                    ('Mecânica do Zé',          '(95) 99812-3344', 'Rua Araguaia, 210 — São Francisco'),
                    ('Oficina Gavião Express',  '(95) 98700-5566', 'Av. Cap. Ene Garcez, 890 — Gavião')
                """))
                conn.commit()
        except Exception:
            pass

        try:
            qtd_pc = conn.execute(text("SELECT COUNT(*) FROM pecas_catalogo")).scalar()
            if qtd_pc == 0:
                conn.execute(text("""
                    INSERT INTO pecas_catalogo (nome, categoria, unidade) VALUES
                    ('Óleo Motor 5W30',           'motor',   'L'),
                    ('Filtro de Óleo',            'motor',   'un'),
                    ('Pastilha de Freio Dianteira','freios',  'par'),
                    ('Pneu Traseiro',              'pneus',   'un'),
                    ('Corrente de Transmissão',    'transmissao', 'un')
                """))
                conn.commit()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Paths absolutos de static/templates (robusto no Railway)
# ---------------------------------------------------------------------------
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_static_dir = os.path.join(_BASE_DIR, "static")
if os.path.isdir(_static_dir):
    app.mount("/static", StaticFiles(directory=_static_dir), name="static")
templates = Jinja2Templates(directory=os.path.join(_BASE_DIR, "templates"))


# ---------------------------------------------------------------------------
# Constantes de módulo
# ---------------------------------------------------------------------------
_PER_PAGE = 20

# Gradientes de cor por posição no ranking de desempenho (top → demais)
_PERF_GRADIENTS = [
    {"header": "linear-gradient(135deg,#7c3aed,#4f46e5)", "avatar": "linear-gradient(135deg,#f59e0b,#b45309)", "ring": "#7c3aed"},
    {"header": "linear-gradient(135deg,#1e40af,#3b82f6)", "avatar": "linear-gradient(135deg,#374151,#111827)", "ring": "#3b82f6"},
    {"header": "linear-gradient(135deg,#c2410c,#f97316)", "avatar": "linear-gradient(135deg,#f97316,#c2410c)", "ring": "#f97316"},
    {"header": "linear-gradient(135deg,#5b21b6,#7c3aed)", "avatar": "linear-gradient(135deg,#6366f1,#4338ca)", "ring": "#6366f1"},
    {"header": "linear-gradient(135deg,#065f46,#16a34a)", "avatar": "linear-gradient(135deg,#16a34a,#065f46)", "ring": "#16a34a"},
    {"header": "linear-gradient(135deg,#9f1239,#e11d48)", "avatar": "linear-gradient(135deg,#e11d48,#9f1239)", "ring": "#e11d48"},
]

_DIAS_PT = ['SEG', 'TER', 'QUA', 'QUI', 'SEX', 'SÁB', 'DOM']

_ITENS_CRITICOS = ('freio', 'pneu', 'farol')


# ---------------------------------------------------------------------------
# Modelos Pydantic (payloads JSON do módulo Frota)
# ---------------------------------------------------------------------------
class VeiculoCreatePayload(BaseModel):
    placa: str
    modelo: str
    tipo: str
    entregador_id: Optional[int] = None
    odometro_inicial: Optional[int] = None


class VeiculoUpdatePayload(BaseModel):
    placa: Optional[str] = None
    modelo: Optional[str] = None
    tipo: Optional[str] = None
    entregador_id: Optional[int] = None


class ChecklistPayload(BaseModel):
    veiculo_id: int
    tipo: str
    odometro_registrado: int
    itens_reprovados: Optional[List[dict]] = None


class AbastecimentoPayload(BaseModel):
    veiculo_id: int
    odometro: int
    litros: float
    valor_total: float


class ManutencaoPayload(BaseModel):
    veiculo_id: int
    data: Optional[date]
    odometro: Optional[int] = None
    categoria: str
    itens_trocados: Optional[List[dict]] = None
    valor_pecas: Optional[float] = None
    valor_mao_obra: Optional[float] = None
    oficina: Optional[str] = None


class SolicitacaoManutencaoPayload(BaseModel):
    """Payload enviado pelo MOTORISTA para solicitar uma manutenção."""
    veiculo_id: int
    categoria: str
    odometro: int
    descricao_problema: str
    oficina: Optional[str] = None
    pecas: Optional[List[dict]] = None
    valor_pecas: Optional[float] = None
    valor_mao_obra: Optional[float] = None


class AprovarManutencaoPayload(BaseModel):
    """Payload enviado pelo GESTOR ao aprovar uma solicitação."""
    oficina: Optional[str] = None
    valor_pecas: Optional[float] = None
    valor_mao_obra: Optional[float] = None
    itens_trocados: Optional[List[dict]] = None
    observacao_gestor: Optional[str] = None


class CriarOficinaPayload(BaseModel):
    nome: str
    telefone: Optional[str] = None
    endereco: Optional[str] = None


class CriarPecaPayload(BaseModel):
    nome: str
    categoria: Optional[str] = None
    unidade: str = 'un'


class PneuInstalarPayload(BaseModel):
    veiculo_id: int
    posicao: str
    marca: Optional[str] = None
    data_instalacao: date
    km_instalacao: int


class PneuDescartePayload(BaseModel):
    km_descarte: int
    data_descarte: date


# ---------------------------------------------------------------------------
# Helpers compartilhados
# ---------------------------------------------------------------------------
def _resolver_usuario(user_id: Optional[str], db: Session) -> Usuario:
    """
    Lê o user_id do cookie, valida e retorna o objeto Usuario.
    Lança HTTPException 401 se não autenticado ou usuário inexistente.
    """
    uid = int(user_id) if user_id and user_id.isdigit() else None
    if not uid:
        raise HTTPException(status_code=401, detail="Não autenticado")
    usuario = db.query(Usuario).filter(Usuario.id == uid).first()
    if not usuario:
        raise HTTPException(status_code=401, detail="Usuário não encontrado")
    return usuario


def _turno_aberto_hoje(db: Session, motorista_id: int) -> Optional[TurnoEntrega]:
    """Retorna o TurnoEntrega aberto do motorista na data atual (UTC-4), ou None."""
    return (
        db.query(TurnoEntrega)
        .filter(
            TurnoEntrega.motorista_id == motorista_id,
            TurnoEntrega.data == agora().date(),
            TurnoEntrega.status == "aberto",
        )
        .first()
    )


def _turno_aberto_veiculo_hoje(db: Session, veiculo_id: int) -> Optional[TurnoEntrega]:
    """Retorna o TurnoEntrega aberto do veículo na data atual, ou None."""
    return (
        db.query(TurnoEntrega)
        .filter(
            TurnoEntrega.veiculo_id == veiculo_id,
            TurnoEntrega.data == agora().date(),
            TurnoEntrega.status == "aberto",
        )
        .first()
    )


def _tem_item_critico(itens) -> bool:
    """
    Verifica se algum item da lista toca nos radicais críticos
    (freio, pneu, farol) — comparação case-insensitive por substring.
    """
    for item_obj in (itens or []):
        nome = item_obj.get("item", "").lower()
        if any(critico in nome for critico in _ITENS_CRITICOS):
            return True
    return False


def _extrair_erro_trigger(e) -> Optional[str]:
    """
    Extrai a mensagem do SIGNAL SQLSTATE '45000' disparado por trigger MySQL.
    Retorna a mensagem se o código for 1644, None caso contrário.
    """
    orig = getattr(e, "orig", None)
    if orig and hasattr(orig, "args") and orig.args:
        if len(orig.args) >= 2 and orig.args[0] == 1644:
            return str(orig.args[1])
        return "Erro de validação no banco"
    return None


# ---------------------------------------------------------------------------
# AUTENTICAÇÃO
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
    _set_cookies_sessao(res, user.perfil, str(user.id), str(user.filial_id or ""))
    return res


@app.get("/logout")
async def logout():
    res = RedirectResponse(url="/login")
    for c in _AUTH_COOKIES:
        res.delete_cookie(c)
    return res
@app.get("/gestor")
async def dashboard_gestor(request: Request, data: str = None, db: Session = Depends(get_db), user_role: str = Cookie(None)):
    """gestor"""
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
        Entrega.status == "finalizado"
    ).count()

    entregas_loja = db.query(Entrega).filter(
        func.date(Entrega.data_criacao) == filtro,
        Entrega.status == "pendente"
    ).all()

    entregas_rota = db.query(Entrega).filter(Entrega.status == "em_rota").all()

    entregas_erro = db.query(Entrega).filter(Entrega.status == "erro_entrega").all()

    stats_filiais = db.query(
        Filial.id,
        Filial.nome,
        Filial.cidade,
        func.count(Entrega.id).label("total"),
        func.sum(sql_case((Entrega.status == "pendente", 1), else_=0)).label("pendentes"),
        func.sum(sql_case((Entrega.status == "em_rota", 1), else_=0)).label("em_rota"),
        func.sum(sql_case((Entrega.status == "finalizado", 1), else_=0)).label("finalizadas"),
    ).outerjoin(
        Entrega,
        (Entrega.filial_id == Filial.id) & (func.date(Entrega.data_criacao) == filtro)
    ).group_by(Filial.id, Filial.nome, Filial.cidade).all()

    filiais_map = {f.id: f.nome for f in db.query(Filial).all()}

    import calendar as cal_mod
    cal_ano = filtro.year
    cal_mes = filtro.month
    cal_ini = date(cal_ano, cal_mes, 1)
    cal_fim = date(cal_ano, cal_mes, cal_mod.monthrange(cal_ano, cal_mes)[1])

    contagens_raw = db.query(
        func.date(Entrega.data_criacao), func.count(Entrega.id)
    ).filter(
        func.date(Entrega.data_criacao) >= cal_ini,
        func.date(Entrega.data_criacao) <= cal_fim
    ).group_by(func.date(Entrega.data_criacao)).all()

    cal_contagens = {str(row[0]): row[1] for row in contagens_raw}
    cal_max = max(cal_contagens.values(), default=1)
    cal_total = sum(cal_contagens.values())

    cal_semanas = cal_mod.monthcalendar(cal_ano, cal_mes)

    if cal_mes == 1:
        mes_ant = date(cal_ano - 1, 12, 1)
    else:
        mes_ant = date(cal_ano, cal_mes - 1, 1)
    if cal_mes == 12:
        mes_prox = date(cal_ano + 1, 1, 1)
    else:
        mes_prox = date(cal_ano, cal_mes + 1, 1)

    _MESES_PT = ['', 'Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho', 'Julho', 'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro']

    _KM_ALERTA_GES = 9000
    _KM_CRITICO_GES = 10000
    veiculos_ges = db.query(Veiculo).all()

    mnts_ges = db.query(Manutencao).filter(
        Manutencao.categoria == "preventiva",
        Manutencao.odometro.isnot(None)
    ).order_by(Manutencao.veiculo_id, Manutencao.odometro.desc()).all()

    _mnt_map = defaultdict(list)
    for _m in mnts_ges:
        _mnt_map[_m.veiculo_id].append(_m)

    frota_alertas_total = 0
    frota_alertas_critico = 0
    frota_turnos_abertos = db.query(TurnoEntrega).filter(
        TurnoEntrega.data == filtro,
        TurnoEntrega.status == "aberto"
    ).count()

    for _v in veiculos_ges:
        _ultima_km = None
        for _m in _mnt_map[_v.id]:
            _itens = _m.itens_trocados or []
            if any("oleo" in (i.get("item") or "").lower() for i in _itens if isinstance(i, dict)):
                _ultima_km = _m.odometro
                break
        if _ultima_km is None:
            frota_alertas_total += 1
            continue
        if not _v.odometro_atual:
            continue
        if _v.odometro_atual - _ultima_km >= _KM_ALERTA_GES:
            frota_alertas_total += 1
            if _v.odometro_atual - _ultima_km >= _KM_CRITICO_GES:
                frota_alertas_critico += 1

    return templates.TemplateResponse(request=request, name="gestor.html", context={
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
        "cal_semanas": cal_semanas,
        "cal_contagens": cal_contagens,
        "cal_max": cal_max,
        "cal_total": cal_total,
        "cal_ano": cal_ano,
        "cal_mes": cal_mes,
        "cal_mes_nome": _MESES_PT[cal_mes],
        "mes_ant": mes_ant.isoformat(),
        "mes_prox": mes_prox.isoformat(),
        "hoje": date.today().isoformat(),
        "frota_alertas_total": frota_alertas_total,
        "frota_alertas_critico": frota_alertas_critico,
        "frota_turnos_abertos": frota_turnos_abertos,
        "frota_total_veiculos": len(veiculos_ges),
    })


@app.get("/entregador")
async def dashboard_entregador(request: Request, db: Session = Depends(get_db), user_role: str = Cookie(None), user_id: str = Cookie(None), user_filial_id: str = Cookie(None), erro: str = None):
    """entregador"""
    if user_role != "entregador":
        return RedirectResponse(url="/login")

    uid = int(user_id) if user_id and user_id.isdigit() else None

    usuario_logado = db.query(Usuario).filter(Usuario.id == uid).first() if uid else None

    disponiveis = db.query(Entrega).filter(Entrega.status == "pendente").all()

    em_rota = db.query(Entrega).filter(
        Entrega.status == "em_rota",
        Entrega.entregador_id == uid
    ).all() if uid else []

    hoje_inicio = datetime.combine(date.today(), datetime.min.time())

    finalizadas_hoje = db.query(Entrega).filter(
        Entrega.entregador_id == uid,
        Entrega.status == "finalizado",
        Entrega.data_finalizacao >= hoje_inicio
    ).order_by(Entrega.data_finalizacao.desc()).all() if uid else []

    fid = int(user_filial_id) if user_filial_id and user_filial_id.isdigit() else None

    filial = db.query(Filial).filter(Filial.id == fid).first() if fid else None

    cidade_filial = filial.cidade.strip() if filial and filial.cidade else ""

    link_rota = gerar_link_rota(em_rota, cidade=cidade_filial)

    filiais_map = {f.id: f for f in db.query(Filial).all()}

    turno_ativo = _turno_aberto_hoje(db, uid) if uid else None

    veiculo_motorista = None
    if turno_ativo:
        veiculo_motorista = db.query(Veiculo).filter(Veiculo.id == turno_ativo.veiculo_id).first()
    if not veiculo_motorista and uid:
        veiculo_motorista = db.query(Veiculo).filter(Veiculo.entregador_id == uid).first()

    abastecimentos_hoje = []
    if uid and veiculo_motorista:
        _abt_inicio = datetime.combine(date.today(), datetime.min.time())

        _abts = db.query(Abastecimento).filter(
            Abastecimento.motorista_id == uid,
            Abastecimento.data >= _abt_inicio
        ).order_by(Abastecimento.data.desc()).all()

        for a in _abts:
            abastecimentos_hoje.append({
                "id": a.id,
                "hora": a.data.strftime("%H:%M"),
                "odometro": a.odometro,
                "litros": float(a.litros or 0),
                "valor_total": float(a.valor_total or 0),
                "preco_l": round(float(a.valor_total or 0) / float(a.litros or 1), 3),
            })

    total_combustivel_hoje = sum(a["valor_total"] for a in abastecimentos_hoje)

    return templates.TemplateResponse(request=request, name="dashboard_entregador.html", context={
        "disponiveis": disponiveis,
        "em_rota": em_rota,
        "link_rota": link_rota,
        "filiais_map": filiais_map,
        "entregador_nome": usuario_logado.username if usuario_logado else "Entregador",
        "finalizadas_hoje": finalizadas_hoje,
        "turno_ativo": turno_ativo,
        "veiculo_motorista": veiculo_motorista,
        "abastecimentos_hoje": abastecimentos_hoje,
        "total_combustivel_hoje": total_combustivel_hoje,
        "erro": erro,
    })


@app.post("/entregador/aceitar/{entrega_id}")
async def aceitar_entrega(
    entrega_id: int,
    lat: str = Form(None),
    lng: str = Form(None),
    db: Session = Depends(get_db),
    user_id: str = Cookie(None),
    user_role: str = Cookie(None),
):
    """entregador"""
    if user_role != "entregador":
        return RedirectResponse(url="/login")

    uid = int(user_id) if user_id and user_id.isdigit() else None

    turno_check = _turno_aberto_hoje(db, uid) if uid else None
    if not turno_check:
        return RedirectResponse(url="/entregador?erro=sem_turno", status_code=303)

    entrega = db.query(Entrega).filter(Entrega.id == entrega_id).first()
    if entrega and entrega.status == "pendente" and uid:
        entrega.status = "em_rota"
        entrega.entregador_id = uid
        entrega.data_aceite = agora()
        try:
            if lat and lng:
                db.add(PontoRota(entrega_id=entrega_id, latitude=float(lat), longitude=float(lng), tipo="inicio"))
        except (ValueError, TypeError):
            pass
        db.commit()

    return RedirectResponse(url="/entregador?aba=emrota", status_code=303)


@app.get("/entregador/entrega/{entrega_id}")
async def detalhe_entrega(request: Request, entrega_id: int, db: Session = Depends(get_db), user_role: str = Cookie(None), user_id: str = Cookie(None)):
    """entregador"""
    if user_role != "entregador":
        return RedirectResponse(url="/login")

    uid = int(user_id) if user_id and user_id.isdigit() else None

    entrega = db.query(Entrega).filter(
        Entrega.id == entrega_id,
        Entrega.entregador_id == uid,
        Entrega.status == "em_rota"
    ).first()

    if not entrega:
        return RedirectResponse(url="/entregador")

    cliente = db.query(Cliente).filter(Cliente.id == entrega.cliente_id).first()

    telefone_raw = (cliente.telefone or "") if cliente else ""
    telefone_wa = re.sub("\\D", "", telefone_raw)
    if telefone_wa and not telefone_wa.startswith("55"):
        telefone_wa = "55" + telefone_wa

    municipio_cliente = entrega.municipio or (cliente.municipio if cliente else "") or ""
    estado_cliente = entrega.uf or (cliente.estado if cliente else "") or ""

    partes_maps = [f"{entrega.rua or ''}, {entrega.numero or ''}".strip(", "), entrega.bairro]
    if municipio_cliente:
        partes_maps.append(municipio_cliente)
    if estado_cliente:
        partes_maps.append(estado_cliente)
    partes_maps.append("Brasil")
    endereco_maps = ", ".join(p for p in partes_maps if p)

    return templates.TemplateResponse(request=request, name="detalhe_entrega.html", context={
        "entrega": entrega,
        "telefone": telefone_raw,
        "telefone_wa": telefone_wa,
        "endereco_maps": endereco_maps,
        "nome_cliente": cliente.nome if cliente else "",
        "municipio_cliente": municipio_cliente,
        "estado_cliente": estado_cliente,
    })


@app.post("/entregador/finalizar/{entrega_id}")
async def finalizar_entrega(
    entrega_id: int,
    lat: str = Form(None),
    lng: str = Form(None),
    db: Session = Depends(get_db),
    user_id: str = Cookie(None),
    user_role: str = Cookie(None),
):
    """entregador"""
    if user_role != "entregador":
        return RedirectResponse(url="/login")

    uid = int(user_id) if user_id and user_id.isdigit() else None

    entrega = db.query(Entrega).filter(Entrega.id == entrega_id).first()
    if entrega and entrega.status == "em_rota" and entrega.entregador_id == uid:
        entrega.status = "finalizado"
        entrega.data_finalizacao = agora()
        try:
            if lat and lng:
                db.add(PontoRota(entrega_id=entrega_id, latitude=float(lat), longitude=float(lng), tipo="fim"))
        except (ValueError, TypeError):
            pass
        db.commit()

    return RedirectResponse(url="/entregador", status_code=303)


@app.post("/entregador/rastrear/{entrega_id}")
async def rastrear_entrega(
    entrega_id: int,
    body: PontoRotaIn,
    db: Session = Depends(get_db),
    user_id: str = Cookie(None),
    user_role: str = Cookie(None),
):
    """entregador — recebe ponto GPS periódico durante a rota"""
    if user_role != "entregador":
        return JSONResponse({"ok": False}, status_code=401)

    uid = int(user_id) if user_id and user_id.isdigit() else None
    entrega = db.query(Entrega).filter(
        Entrega.id == entrega_id,
        Entrega.entregador_id == uid,
        Entrega.status == "em_rota",
    ).first()
    if entrega:
        db.add(PontoRota(entrega_id=entrega_id, latitude=body.lat, longitude=body.lng, tipo="rota"))
        db.commit()
    return JSONResponse({"ok": True})


@app.post("/entregas/{entrega_id}/reportar-erro")
async def reportar_erro(entrega_id: int, motivo: str = Form(...), db: Session = Depends(get_db), user_role: str = Cookie(None), user_id: str = Cookie(None)):
    """entregador"""
    if user_role != "entregador":
        return RedirectResponse(url="/login")

    uid = int(user_id) if user_id and user_id.isdigit() else None

    entrega = db.query(Entrega).filter(
        Entrega.id == entrega_id,
        Entrega.entregador_id == uid,
        Entrega.status == "em_rota"
    ).first()

    if entrega:
        entrega.status = "erro_entrega"
        entrega.motivo_erro = motivo
        db.commit()

    return RedirectResponse(url="/entregador", status_code=303)


@app.post("/entregas/{entrega_id}/reiniciar")
async def reiniciar_entrega(entrega_id: int, rua: str = Form(None), numero: str = Form(None), bairro: str = Form(None), db: Session = Depends(get_db), user_role: str = Cookie(None)):
    """gestor"""
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


@app.get("/gestor/ajustar-entrega/{entrega_id}")
async def pagina_ajustar_entrega(request: Request, entrega_id: int, db: Session = Depends(get_db), user_role: str = Cookie(None)):
    """gestor"""
    if user_role not in ("gestor", "operador"):
        return RedirectResponse(url="/login")

    entrega = db.query(Entrega).filter(
        Entrega.id == entrega_id,
        Entrega.status == "erro_entrega"
    ).first()

    if not entrega:
        return RedirectResponse(url="/gestor")

    cliente = db.query(Cliente).filter(Cliente.id == entrega.cliente_id).first()

    return templates.TemplateResponse(request=request, name="ajustar_entrega.html", context={
        "entrega": entrega,
        "cliente": cliente,
    })


@app.post("/gestor/ajustar-entrega/{entrega_id}")
async def salvar_ajuste_entrega(entrega_id: int, rua: str = Form(...), numero: str = Form(...), bairro: str = Form(...), observacao: str = Form(default=""), db: Session = Depends(get_db), user_role: str = Cookie(None)):
    """gestor"""
    if user_role not in ("gestor", "operador"):
        return RedirectResponse(url="/login")

    entrega = db.query(Entrega).filter(
        Entrega.id == entrega_id,
        Entrega.status == "erro_entrega"
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
@app.get("/gestor/desempenho")
async def desempenho_gestor(request: Request, db: Session = Depends(get_db), user_role: str = Cookie(None), inicio: str = None, fim: str = None, entregador_id: str = None, filial_id: str = None):
    """gestor"""
    if user_role not in ("gestor", "operador"):
        return RedirectResponse(url="/login")

    hoje = agora().date()
    inicio_str = inicio or hoje.replace(day=1).strftime("%Y-%m-%d")
    fim_str = fim or hoje.strftime("%Y-%m-%d")

    try:
        inicio_dt = datetime.strptime(inicio_str, "%Y-%m-%d")
        fim_dt = datetime.strptime(fim_str, "%Y-%m-%d") + timedelta(days=1)
    except ValueError:
        inicio_dt = datetime.combine(hoje.replace(day=1), datetime.min.time())
        fim_dt = datetime.combine(hoje + timedelta(days=1), datetime.min.time())

    filiais_map = {f.id: f for f in db.query(Filial).all()}

    todos_entregadores = db.query(Usuario).filter(Usuario.perfil == "entregador").order_by(Usuario.username).all()

    entregas_periodo = db.query(Entrega).filter(
        Entrega.data_criacao >= inicio_dt,
        Entrega.data_criacao < fim_dt,
    ).all()

    sete_atras = datetime.combine(hoje - timedelta(days=6), datetime.min.time())
    entregas_7d = db.query(Entrega).filter(Entrega.data_criacao >= sete_atras).all()

    em_rota_ids = {e.entregador_id for e in db.query(Entrega).filter(Entrega.status == "em_rota").all() if e.entregador_id}

    dias_labels = [_DIAS_PT[(hoje - timedelta(days=i)).weekday()] for i in range(6, -1, -1)]

    ranking = []
    for u in todos_entregadores:
        minhas = [e for e in entregas_periodo if e.entregador_id == u.id]
        total = len(minhas)
        finalizadas = sum(1 for e in minhas if e.status == "finalizado")
        erros = sum(1 for e in minhas if e.status == "erro_entrega")
        concluidas = finalizadas + erros
        taxa_sucesso = round(finalizadas / concluidas * 100) if concluidas > 0 else None

        tr, te, tt = [], [], []
        for e in minhas:
            if e.status == "finalizado" and e.data_aceite and e.data_finalizacao:
                r = (e.data_aceite - e.data_criacao).total_seconds() / 60
                en = (e.data_finalizacao - e.data_aceite).total_seconds() / 60
                tot = (e.data_finalizacao - e.data_criacao).total_seconds() / 60
                if 0 < r < 180:
                    tr.append(r)
                if 0 < en < 300:
                    te.append(en)
                if 0 < tot < 480:
                    tt.append(tot)

        t_reacao = round(sum(tr) / len(tr)) if tr else None
        t_entrega = round(sum(te) / len(te)) if te else None
        t_total = round(sum(tt) / len(tt)) if tt else None

        if u.id in em_rota_ids:
            status_atual = "em_rota"
        elif total > 0:
            status_atual = "disponivel"
        else:
            status_atual = "inativo"

        spark_counts = []
        for i in range(6, -1, -1):
            dia = hoje - timedelta(days=i)
            spark_counts.append(sum(1 for e in entregas_7d if e.entregador_id == u.id and e.data_criacao.date() == dia))

        spark_max = max(spark_counts) if any(c > 0 for c in spark_counts) else 1
        spark_avg = round(sum(spark_counts) / 7, 1)

        spark_bars = [{
            "pct": max(int(c / spark_max * 100), 4) if c > 0 else 4,
            "opacity": round(0.3 + c / spark_max * 0.7, 2) if c > 0 else 0.15,
            "label": dias_labels[i],
        } for i, c in enumerate(spark_counts)]

        filial = filiais_map.get(u.filial_id)
        ring_offset = round(263.9 * (1 - (taxa_sucesso or 0) / 100), 1)

        ranking.append({
            "usuario": u,
            "filial_nome": filial.nome if filial else "—",
            "total": total,
            "finalizadas": finalizadas,
            "erros": erros,
            "taxa_sucesso": taxa_sucesso,
            "ring_offset": ring_offset,
            "t_reacao": t_reacao,
            "t_entrega": t_entrega,
            "t_total": t_total,
            "status_atual": status_atual,
            "spark_bars": spark_bars,
            "spark_avg": spark_avg,
        })

    ranking.sort(key=lambda x: (x["finalizadas"], x["total"]), reverse=True)
    for idx, item in enumerate(ranking):
        item["colors"] = _PERF_GRADIENTS[idx % len(_PERF_GRADIENTS)]
        item["rank"] = idx + 1

    lista_filtrada = ranking[:]
    if entregador_id and entregador_id.isdigit():
        lista_filtrada = [r for r in ranking if r["usuario"].id == int(entregador_id)]
    if filial_id and filial_id.isdigit():
        lista_filtrada = [r for r in lista_filtrada if r["usuario"].filial_id == int(filial_id)]

    ativos = sum(1 for r in ranking if r["total"] > 0)
    em_rota_cnt = sum(1 for r in ranking if r["status_atual"] == "em_rota")
    total_ent = sum(r["total"] for r in ranking)
    total_fin = sum(r["finalizadas"] for r in ranking)
    total_err = sum(r["erros"] for r in ranking)
    conc_geral = total_fin + total_err
    taxa_media = round(total_fin / conc_geral * 100) if conc_geral > 0 else None
    tempos_g = [r["t_total"] for r in ranking if r["t_total"] is not None]
    tempo_medio = round(sum(tempos_g) / len(tempos_g)) if tempos_g else None
    destaque = ranking[0] if ranking else None
    top3 = ranking[:3]
    filiais = db.query(Filial).order_by(Filial.nome).all()

    return templates.TemplateResponse(request=request, name="gestao_desempenho.html", context={
        "ranking": lista_filtrada,
        "top3": top3,
        "destaque": destaque,
        "ativos": ativos,
        "em_rota_cnt": em_rota_cnt,
        "total_entregas": total_ent,
        "taxa_media": taxa_media,
        "tempo_medio": tempo_medio,
        "entregadores": todos_entregadores,
        "filiais": filiais,
        "filtros": {
            "inicio": inicio_str,
            "fim": fim_str,
            "entregador_id": entregador_id or "",
            "filial_id": filial_id or "",
        },
    })


@app.get("/gestor/entregador/{entregador_id}")
async def historico_entregador(request: Request, entregador_id: int, db: Session = Depends(get_db), user_role: str = Cookie(None), status: str = None, inicio: str = None, fim: str = None, page: int = 1):
    """gestor"""
    if user_role not in ("gestor", "operador"):
        return RedirectResponse(url="/login")

    entregador = db.query(Usuario).filter(Usuario.id == entregador_id, Usuario.perfil == "entregador").first()
    if not entregador:
        return RedirectResponse(url="/gestor/desempenho")

    hoje = agora().date()
    inicio_dt = datetime.strptime(inicio, "%Y-%m-%d") if inicio else datetime.combine(hoje.replace(day=1), datetime.min.time())
    fim_dt = (datetime.strptime(fim, "%Y-%m-%d") + timedelta(days=1)) if fim else datetime.combine(hoje + timedelta(days=1), datetime.min.time())
    inicio_str = inicio or hoje.replace(day=1).strftime("%Y-%m-%d")
    fim_str = fim or hoje.strftime("%Y-%m-%d")

    query = db.query(Entrega).filter(
        Entrega.entregador_id == entregador_id,
        Entrega.data_criacao >= inicio_dt,
        Entrega.data_criacao < fim_dt,
    )
    if status:
        query = query.filter(Entrega.status == status)

    todas = query.order_by(Entrega.data_criacao.desc()).all()
    total_pag = 30
    total_reg = len(todas)
    total_pags = max(1, (total_reg + total_pag - 1) // total_pag)
    page = max(1, min(page, total_pags))
    entregas = todas[(page - 1) * total_pag:page * total_pag]

    todas_periodo = db.query(Entrega).filter(
        Entrega.entregador_id == entregador_id,
        Entrega.data_criacao >= inicio_dt,
        Entrega.data_criacao < fim_dt,
    ).all()
    total = len(todas_periodo)
    finalizadas = sum(1 for e in todas_periodo if e.status == "finalizado")
    erros = sum(1 for e in todas_periodo if e.status == "erro_entrega")
    em_rota = sum(1 for e in todas_periodo if e.status == "em_rota")
    pendentes = sum(1 for e in todas_periodo if e.status == "pendente")
    concluidas = finalizadas + erros
    taxa_sucesso = round(finalizadas / concluidas * 100) if concluidas > 0 else None

    tr, te, tt = [], [], []
    for e in todas_periodo:
        if e.status == "finalizado" and e.data_aceite and e.data_finalizacao:
            r = (e.data_aceite - e.data_criacao).total_seconds() / 60
            en = (e.data_finalizacao - e.data_aceite).total_seconds() / 60
            tot = (e.data_finalizacao - e.data_criacao).total_seconds() / 60
            if 0 < r < 180:
                tr.append(r)
            if 0 < en < 300:
                te.append(en)
            if 0 < tot < 480:
                tt.append(tot)

    t_reacao = round(sum(tr) / len(tr)) if tr else None
    t_entrega = round(sum(te) / len(te)) if te else None
    t_total = round(sum(tt) / len(tt)) if tt else None

    filiais_map = {f.id: f.nome for f in db.query(Filial).all()}

    return templates.TemplateResponse(request=request, name="historico_entregador.html", context={
        "entregador": entregador,
        "filial_nome": filiais_map.get(entregador.filial_id, "—"),
        "entregas": entregas,
        "filiais_map": filiais_map,
        "total": total,
        "finalizadas": finalizadas,
        "erros": erros,
        "em_rota": em_rota,
        "pendentes": pendentes,
        "taxa_sucesso": taxa_sucesso,
        "t_reacao": t_reacao,
        "t_entrega": t_entrega,
        "t_total": t_total,
        "total_reg": total_reg,
        "page": page,
        "total_pags": total_pags,
        "filtros": {
            "status": status or "",
            "inicio": inicio_str,
            "fim": fim_str,
        },
    })


@app.get("/gestor/log")
async def log_entregas_page(request: Request, db: Session = Depends(get_db), user_role: str = Cookie(None), inicio: str = None, fim: str = None, status: str = None, filial_id: str = None, q: str = None, page: int = 1):
    """gestor"""
    if user_role not in ("gestor", "operador"):
        return RedirectResponse(url="/login")

    hoje = agora().date()
    inicio_str = inicio or (hoje - timedelta(days=30)).strftime("%Y-%m-%d")
    fim_str = fim or hoje.strftime("%Y-%m-%d")

    try:
        inicio_dt = datetime.strptime(inicio_str, "%Y-%m-%d")
        fim_dt = datetime.strptime(fim_str, "%Y-%m-%d") + timedelta(days=1)
    except ValueError:
        inicio_dt = datetime.combine(hoje - timedelta(days=30), datetime.min.time())
        fim_dt = datetime.combine(hoje, datetime.max.time())

    base_q = db.query(Entrega).filter(
        Entrega.data_criacao >= inicio_dt,
        Entrega.data_criacao < fim_dt,
    )

    cnt_total = base_q.count()
    cnt_pendente = base_q.filter(Entrega.status == "pendente").count()
    cnt_em_rota = base_q.filter(Entrega.status == "em_rota").count()
    cnt_finalizado = base_q.filter(Entrega.status == "finalizado").count()
    cnt_erro = base_q.filter(Entrega.status == "erro_entrega").count()

    lista_q = db.query(Entrega).filter(
        Entrega.data_criacao >= inicio_dt,
        Entrega.data_criacao < fim_dt,
    )

    if status:
        lista_q = lista_q.filter(Entrega.status == status)
    if filial_id:
        try:
            lista_q = lista_q.filter(Entrega.filial_id == int(filial_id))
        except ValueError:
            pass
    if q:
        lista_q = lista_q.filter(or_(Entrega.cupom_fiscal.ilike(f"%{q}%")))

    lista_q = lista_q.order_by(Entrega.data_criacao.desc())
    total = lista_q.count()
    total_pages = max(1, (total + _PER_PAGE - 1) // _PER_PAGE)
    page = max(1, min(page, total_pages))

    entregas_raw = lista_q.offset((page - 1) * _PER_PAGE).limit(_PER_PAGE).all()

    ids_pagina = [e.id for e in entregas_raw]
    ids_com_rota = set(
        row.entrega_id for row in db.query(PontoRota.entrega_id)
        .filter(PontoRota.entrega_id.in_(ids_pagina)).distinct().all()
    ) if ids_pagina else set()

    clientes_map = {c.id: c for c in db.query(Cliente).all()}
    filiais_map = {f.id: f for f in db.query(Filial).all()}
    usuarios_map = {u.id: u for u in db.query(Usuario).all()}

    entregas = []
    for e in entregas_raw:
        cli = clientes_map.get(e.cliente_id)
        fil = filiais_map.get(e.filial_id)
        ent = usuarios_map.get(e.entregador_id)
        entregas.append({
            "entrega": e,
            "cliente_nome": cli.nome if cli else "",
            "cliente_doc": cli.documento if cli else "",
            "cliente_tel": cli.telefone if cli else "",
            "filial_nome": fil.nome if fil else "",
            "entregador_nome": ent.username if ent else "",
        })

    params = {}
    if inicio:
        params["inicio"] = inicio
    if fim:
        params["fim"] = fim
    if status:
        params["status"] = status
    if filial_id:
        params["filial_id"] = filial_id
    if q:
        params["q"] = q
    qs = "&".join(f"{k}={v}" for k, v in params.items())

    filiais = db.query(Filial).order_by(Filial.nome).all()

    return templates.TemplateResponse(request=request, name="log_entregas.html", context={
        "entregas": entregas,
        "ids_com_rota": ids_com_rota,
        "total": total,
        "page": page,
        "total_pages": total_pages,
        "qs": qs,
        "filiais": filiais,
        "cnt_total": cnt_total,
        "cnt_pendente": cnt_pendente,
        "cnt_em_rota": cnt_em_rota,
        "cnt_finalizado": cnt_finalizado,
        "cnt_erro": cnt_erro,
        "filtros": {
            "inicio": inicio_str,
            "fim": fim_str,
            "status": status or "",
            "filial_id": filial_id or "",
            "q": q or "",
        },
    })


@app.post("/gestor/log/editar/{entrega_id}")
async def salvar_edicao_log(entrega_id: int, rua: str = Form(...), numero: str = Form(...), bairro: str = Form(...), municipio: str = Form(default=""), uf: str = Form(default=""), cep: str = Form(default=""), observacao: str = Form(default=""), novo_status: str = Form(default=""), motivo_erro: str = Form(default=""), motivo_alteracao: str = Form(default=""), db: Session = Depends(get_db), user_role: str = Cookie(None)):
    """gestor"""
    if user_role not in ("gestor", "operador"):
        return RedirectResponse(url="/login")

    entrega = db.query(Entrega).filter(Entrega.id == entrega_id).first()
    if not entrega:
        return RedirectResponse(url="/gestor/log", status_code=303)

    entrega.rua = rua.strip()
    entrega.numero = numero.strip()
    entrega.bairro = bairro.strip()
    entrega.municipio = municipio.strip() or entrega.municipio
    entrega.uf = uf.strip().upper() or entrega.uf
    entrega.cep = cep.strip() or entrega.cep
    if observacao.strip():
        entrega.observacao = observacao.strip()

    if novo_status in ("pendente", "finalizado", "erro_entrega"):
        entrega.status = novo_status
        if novo_status == "pendente":
            entrega.entregador_id = None
            entrega.data_aceite = None
            entrega.data_finalizacao = None
            entrega.motivo_erro = None
        if novo_status == "finalizado" and not entrega.data_finalizacao:
            entrega.data_finalizacao = agora()

    if motivo_erro.strip():
        entrega.motivo_erro = motivo_erro.strip()

    db.commit()
    return RedirectResponse(url="/gestor/log", status_code=303)


@app.get("/gestor/entrega/{entrega_id}/rota")
async def rota_entrega_gestor(request: Request, entrega_id: int, db: Session = Depends(get_db), user_role: str = Cookie(None)):
    """gestor — mapa de rastreamento GPS de uma entrega"""
    if user_role not in ("gestor", "operador"):
        return RedirectResponse(url="/login")

    entrega = db.query(Entrega).filter(Entrega.id == entrega_id).first()
    if not entrega:
        return RedirectResponse(url="/gestor/log")

    pontos = db.query(PontoRota).filter(PontoRota.entrega_id == entrega_id).order_by(PontoRota.timestamp).all()
    cliente    = db.query(Cliente).filter(Cliente.id == entrega.cliente_id).first()
    entregador = db.query(Usuario).filter(Usuario.id == entrega.entregador_id).first() if entrega.entregador_id else None
    filial     = db.query(Filial).filter(Filial.id == entrega.filial_id).first()

    import json
    pontos_json = json.dumps([
        {
            "lat": p.latitude,
            "lng": p.longitude,
            "tipo": p.tipo,
            "timestamp": p.timestamp.strftime("%d/%m/%Y %H:%M:%S") if p.timestamp else "",
        }
        for p in pontos
    ])

    return templates.TemplateResponse(request=request, name="rota_entrega.html", context={
        "entrega": entrega,
        "pontos": pontos,
        "pontos_json": pontos_json,
        "cliente": cliente,
        "entregador": entregador,
        "filial": filial,
    })


@app.get("/gestao-funcionario")
async def pagina_gestao_funcionario(request: Request, db: Session = Depends(get_db), user_role: str = Cookie(None)):
    """gestor"""
    if user_role != 'gestor':
        return RedirectResponse(url="/login")
    funcionarios = db.query(Usuario).all()
    filiais = db.query(Filial).order_by(Filial.nome).all()
    return templates.TemplateResponse(request=request, name="gestao_funcionarios.html", context={"funcionarios": funcionarios, "filiais": filiais})


@app.post("/salvar-funcionario")
async def salvar_funcionario(username: str = Form(...), perfil: str = Form(...), senha: str = Form(...), filial_id: str = Form(None), db: Session = Depends(get_db)):
    novo = Usuario(username=username, perfil=perfil, senha=pwd_context.hash(senha), filial_id=filial_id if filial_id else None)
    db.add(novo)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
    return RedirectResponse(url="/gestao-funcionario", status_code=303)


@app.get("/editar-funcionario/{func_id}")
async def pagina_editar_funcionario(request: Request, func_id: int, db: Session = Depends(get_db), user_role: str = Cookie(None)):
    """gestor"""
    if user_role != 'gestor':
        return RedirectResponse(url="/login")
    func = db.query(Usuario).filter(Usuario.id == func_id).first()
    filiais = db.query(Filial).order_by(Filial.nome).all()
    return templates.TemplateResponse(request=request, name="editar_funcionario.html", context={"func": func, "filiais": filiais})


@app.post("/processar-funcionario/{func_id}")
async def processar_funcionario(func_id: int, acao: str = Form(...), username: str = Form(None), perfil: str = Form(None), nova_senha: str = Form(None), filial_id: str = Form(None), db: Session = Depends(get_db)):
    """excluir"""
    func = db.query(Usuario).filter(Usuario.id == func_id).first()
    if func:
        if acao == 'excluir':
            db.query(Entrega).filter(Entrega.entregador_id == func_id).update({"entregador_id": None})
            db.query(Entrega).filter(Entrega.operador_id == func_id).update({"operador_id": None})
            db.query(Veiculo).filter(Veiculo.entregador_id == func_id).update({"entregador_id": None})
            db.delete(func)
        else:
            func.username = username
            func.perfil = perfil
            func.filial_id = filial_id if filial_id else None
            if nova_senha and nova_senha.strip():
                func.senha = pwd_context.hash(nova_senha)
        db.commit()
    return RedirectResponse(url="/gestao-funcionario", status_code=303)


@app.get("/gestao-veiculo")
async def pagina_gestao_veiculo(request: Request, db: Session = Depends(get_db), user_role: str = Cookie(None)):
    """gestor"""
    if user_role != 'gestor':
        return RedirectResponse(url="/login")
    veiculos = db.query(Veiculo).all()
    entregadores = db.query(Usuario).filter(Usuario.perfil == 'entregador').all()
    return templates.TemplateResponse(request=request, name="gestao_veiculos.html", context={"veiculos": veiculos, "entregadores": entregadores})


@app.post("/salvar-veiculo")
async def salvar_veiculo(placa: str = Form(...), modelo: str = Form(...), tipo: str = Form(...), entregador_id: str = Form(None), db: Session = Depends(get_db)):
    try:
        db.add(Veiculo(placa=placa, modelo=modelo, tipo=tipo, entregador_id=entregador_id))
        db.commit()
    except IntegrityError:
        db.rollback()
    return RedirectResponse(url="/gestao-veiculo", status_code=303)


@app.get("/vincular-veiculo-page/{veiculo_id}")
async def pagina_vincular(request: Request, veiculo_id: int, db: Session = Depends(get_db)):
    """entregador"""
    veiculo = db.query(Veiculo).filter(Veiculo.id == veiculo_id).first()
    entregadores = db.query(Usuario).filter(Usuario.perfil == 'entregador').all()
    return templates.TemplateResponse(request=request, name="vincular_veiculo.html", context={"veiculo": veiculo, "entregadores": entregadores})


@app.post("/processar-vinculo/{veiculo_id}")
async def processar_vinculo(request: Request, veiculo_id: int, db: Session = Depends(get_db)):
    form_data = await request.form()
    entregador_id = form_data.get("entregador_id")
    veiculo = db.query(Veiculo).filter(Veiculo.id == veiculo_id).first()
    if veiculo:
        veiculo.entregador_id = int(entregador_id) if entregador_id and str(entregador_id).isdigit() else None
        db.commit()
    return RedirectResponse(url="/gestao-veiculo", status_code=303)


@app.get("/editar-veiculo/{veiculo_id}")
async def pagina_editar_veiculo(request: Request, veiculo_id: int, db: Session = Depends(get_db)):
    """entregador"""
    veiculo = db.query(Veiculo).filter(Veiculo.id == veiculo_id).first()
    entregadores = db.query(Usuario).filter(Usuario.perfil == 'entregador').all()
    return templates.TemplateResponse(request=request, name="editar_veiculo.html", context={"veiculo": veiculo, "entregadores": entregadores})


@app.post("/processar-veiculo/{veiculo_id}")
async def processar_veiculo(veiculo_id: int, acao: str = Form(...), placa: str = Form(None), modelo: str = Form(None), tipo: str = Form(None), entregador_id: str = Form(None), db: Session = Depends(get_db)):
    """excluir"""
    veiculo = db.query(Veiculo).filter(Veiculo.id == veiculo_id).first()
    if veiculo:
        if acao == 'excluir':
            db.delete(veiculo)
        else:
            veiculo.placa = placa
            veiculo.modelo = modelo
            veiculo.tipo = tipo
            veiculo.entregador_id = int(entregador_id) if entregador_id and entregador_id.isdigit() else None
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
    return RedirectResponse(url="/gestao-veiculo", status_code=303)
@app.get("/clientes/{documento}")
async def api_buscar_cliente(documento: str, db: Session = Depends(get_db), user_id: str = Cookie(None)):
    _resolver_usuario(user_id, db)  # exige sessão autenticada válida
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
async def api_atualizar_cliente(documento: str, dados: dict, db: Session = Depends(get_db), user_id: str = Cookie(None)):
    _resolver_usuario(user_id, db)  # exige sessão autenticada válida
    cliente = db.query(Cliente).filter(Cliente.documento == documento).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente não encontrado")
    for campo in ("nome", "telefone", "rua", "numero", "bairro"):
        if campo in dados:
            setattr(cliente, campo, dados[campo])
    db.commit()
    return {"status": "ok"}


@app.post("/clientes/")
async def api_cadastrar_cliente(dados: dict, db: Session = Depends(get_db), user_id: str = Cookie(None)):
    _resolver_usuario(user_id, db)  # exige sessão autenticada válida
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
async def api_lancar_entrega(dados: dict, db: Session = Depends(get_db), user_id: str = Cookie(None)):
    _resolver_usuario(user_id, db)  # exige sessão autenticada válida
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


@app.get("/gestao-clientes")
async def listar_clientes(request: Request, q: str = None, msg: str = None, db: Session = Depends(get_db), user_role: str = Cookie(None)):
    if user_role not in ("gestor", "operador"):
        return RedirectResponse(url="/login")
    query = db.query(Cliente)
    if q and q.strip():
        termo = f"%{q.strip()}%"
        query = query.filter(or_(
            Cliente.nome.ilike(termo),
            Cliente.telefone.ilike(termo),
            Cliente.documento.ilike(termo),
        ))
    clientes = query.order_by(Cliente.nome).all()
    return templates.TemplateResponse(request=request, name="gestao_clientes.html", context={"clientes": clientes, "q": q or "", "msg": msg})


@app.post("/gestao-clientes/novo")
async def criar_cliente_web(nome: str = Form(...), documento: str = Form(...), telefone: str = Form(default=""), rua: str = Form(default=""), numero: str = Form(default=""), bairro: str = Form(default=""), municipio: str = Form(default=""), estado: str = Form(default=""), ponto_referencia: str = Form(default=""), db: Session = Depends(get_db), user_role: str = Cookie(None)):
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
async def detalhe_cliente_web(request: Request, cliente_id: int, msg: str = None, db: Session = Depends(get_db), user_role: str = Cookie(None)):
    if user_role not in ("gestor", "operador"):
        return RedirectResponse(url="/login")
    cliente = db.query(Cliente).filter(Cliente.id == cliente_id).first()
    if not cliente:
        return RedirectResponse(url="/gestao-clientes")
    return templates.TemplateResponse(request=request, name="detalhe_cliente.html", context={"cliente": cliente, "msg": msg})


@app.post("/gestao-clientes/{cliente_id}/salvar")
async def salvar_cliente_web(cliente_id: int, nome: str = Form(...), documento: str = Form(...), telefone: str = Form(default=""), rua: str = Form(default=""), numero: str = Form(default=""), bairro: str = Form(default=""), municipio: str = Form(default=""), estado: str = Form(default=""), ponto_referencia: str = Form(default=""), db: Session = Depends(get_db), user_role: str = Cookie(None)):
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
async def excluir_cliente_web(cliente_id: int, db: Session = Depends(get_db), user_role: str = Cookie(None)):
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


@app.get("/gestao-filial")
async def pagina_gestao_filial(request: Request, db: Session = Depends(get_db), user_role: str = Cookie(None)):
    if user_role != "gestor":
        return RedirectResponse(url="/login")
    filiais = db.query(Filial).order_by(Filial.nome).all()
    operadores_por_filial = {}
    for f in filiais:
        operadores_por_filial[f.id] = db.query(Usuario).filter(Usuario.filial_id == f.id, Usuario.perfil == "operador").all()
    return templates.TemplateResponse(request=request, name="gestao_filiais.html", context={"filiais": filiais, "operadores_por_filial": operadores_por_filial})


@app.post("/salvar-filial")
async def salvar_filial(nome: str = Form(...), cidade: str = Form(""), db: Session = Depends(get_db), user_role: str = Cookie(None)):
    if user_role != "gestor":
        return RedirectResponse(url="/login")
    db.add(Filial(nome=nome, cidade=cidade))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
    return RedirectResponse(url="/gestao-filial", status_code=303)


@app.post("/processar-filial/{filial_id}")
async def processar_filial(filial_id: int, acao: str = Form(...), nome: str = Form(None), cidade: str = Form(None), db: Session = Depends(get_db), user_role: str = Cookie(None)):
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
@app.get("/frota/veiculos")
async def frota_listar_veiculos(user_id: str = Cookie(default=None), db: Session = Depends(get_db)):
    """id"""
    _resolver_usuario(user_id, db)
    veiculos = db.query(Veiculo).order_by(Veiculo.placa).all()
    return [
        {
            "id": v.id,
            "placa": v.placa,
            "modelo": v.modelo,
            "tipo": v.tipo,
            "entregador_id": v.entregador_id,
            "odometro_atual": v.odometro_atual,
            "custo_acumulado_manutencao": float(v.custo_acumulado_manutencao or 0),
        }
        for v in veiculos
    ]


@app.get("/frota/veiculos/{veiculo_id}")
async def frota_detalhe_veiculo(veiculo_id: int, user_id: str = Cookie(default=None), db: Session = Depends(get_db)):
    _resolver_usuario(user_id, db)
    v = db.query(Veiculo).filter(Veiculo.id == veiculo_id).first()
    if not v:
        raise HTTPException(status_code=404, detail="Veículo não encontrado")
    return {
        "id": v.id,
        "placa": v.placa,
        "modelo": v.modelo,
        "tipo": v.tipo,
        "entregador_id": v.entregador_id,
        "odometro_atual": v.odometro_atual,
        "custo_acumulado_manutencao": float(v.custo_acumulado_manutencao or 0),
    }


@app.post("/frota/veiculos", status_code=201)
async def frota_criar_veiculo(payload: VeiculoCreatePayload, user_id: str = Cookie(default=None), db: Session = Depends(get_db)):
    _exigir_perfil(user_id, db, ("gestor",))
    novo = Veiculo(
        placa=payload.placa.upper().strip(),
        modelo=payload.modelo.strip(),
        tipo=payload.tipo,
        entregador_id=payload.entregador_id,
        odometro_atual=payload.odometro_inicial,
    )
    db.add(novo)
    try:
        db.commit()
        db.refresh(novo)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Placa já cadastrada")
    return {"id": novo.id, "placa": novo.placa, "mensagem": "Veículo criado"}


@app.put("/frota/veiculos/{veiculo_id}")
async def frota_atualizar_veiculo(veiculo_id: int, payload: VeiculoUpdatePayload, user_id: str = Cookie(default=None), db: Session = Depends(get_db)):
    _exigir_perfil(user_id, db, ("gestor",))
    v = db.query(Veiculo).filter(Veiculo.id == veiculo_id).first()
    if not v:
        raise HTTPException(status_code=404, detail="Veículo não encontrado")
    if payload.placa is not None:
        v.placa = payload.placa.upper().strip()
    if payload.modelo is not None:
        v.modelo = payload.modelo.strip()
    if payload.tipo is not None:
        v.tipo = payload.tipo
    if payload.entregador_id is not None:
        v.entregador_id = payload.entregador_id
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Placa já em uso por outro veículo")
    return {"mensagem": "Veículo atualizado", "id": v.id}


@app.delete("/frota/veiculos/{veiculo_id}", status_code=204)
async def frota_deletar_veiculo(veiculo_id: int, user_id: str = Cookie(default=None), db: Session = Depends(get_db)):
    _exigir_perfil(user_id, db, ("gestor",))
    v = db.query(Veiculo).filter(Veiculo.id == veiculo_id).first()
    if not v:
        raise HTTPException(status_code=404, detail="Veículo não encontrado")
    db.delete(v)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Veículo possui registros vinculados (checklists, turnos ou pneus) e não pode ser excluído",
        )
    return Response(status_code=204)


@app.post("/frota/checklist", status_code=201)
async def frota_registrar_checklist(payload: ChecklistPayload, user_id: str = Cookie(default=None), user_role: str = Cookie(default=None), db: Session = Depends(get_db)):
    """
    Registra um checklist e orquestra abertura/encerramento do turno.

    tipo='inicio':
      1. Bloqueia se já houver turno aberto hoje.
      2. Salva com aprovado=False e retorna 400 se itens críticos encontrados
         (freios, pneus, faróis) — turno NÃO é criado.
      3. O trigger BEFORE INSERT valida KM regressivo (SIGNAL 45000).
      4. Cria TurnoEntrega com status='aberto'.

    tipo='fim' — Fechamento Inteligente (Parte 4):
      1. Valida que payload.veiculo_id == turno_hoje.veiculo_id.
      2. Calcula km_rodada = odometro_fim − odometro_inicio.
      3. db.expire_all() → força leitura fresca pós-trigger.
      4. Calcula consumo_medio (mesma lógica de /frota/analise/consumo/).
      5. Calcula CPK de manutenção (mesma lógica de /frota/analise/cpk/).
      6. custo_combustivel = max(trigger_acumulado, km/consumo * R$5,80)
         custo_manutencao  = max(trigger_acumulado, km * cpk)
         Estratégia max(): preserva dados reais (triggers) quando existem;
         usa estimativa km-based como fallback quando não há registros.
      7. Persiste status='encerrado', checklist_fim_id, custos consolidados.
      8. db.refresh() lê total_cupons_dia atualizado pelos triggers.
      9. Retorna JSON completo de auditoria operacional.

    IMPORTANTE — campos gerenciados por triggers (nunca atualize manualmente):
      veiculos.odometro_atual, veiculos.custo_acumulado_manutencao,
      turnos_entrega.total_cupons_dia, motorista_scores.total_entregas
    """
    if user_role not in ("entregador",):
        raise HTTPException(status_code=403, detail="Acesso restrito a entregadores")

    usuario = _resolver_usuario(user_id, db)

    if payload.tipo not in ("inicio", "fim"):
        raise HTTPException(status_code=400, detail="tipo deve ser 'inicio' ou 'fim'")

    turno_hoje = _turno_aberto_hoje(db, usuario.id)

    if payload.tipo == "inicio" and turno_hoje:
        raise HTTPException(status_code=400, detail=f"Motorista já possui turno aberto hoje (turno_id={turno_hoje.id})")

    if payload.tipo == "fim" and not turno_hoje:
        raise HTTPException(status_code=400, detail="Nenhum turno aberto encontrado para encerrar hoje")

    tem_critico = _tem_item_critico(payload.itens_reprovados) if payload.tipo == "inicio" else False

    checklist = Checklist(
        veiculo_id=payload.veiculo_id,
        motorista_id=usuario.id,
        tipo=payload.tipo,
        data_hora=agora(),
        aprovado=not tem_critico,
        itens_reprovados=payload.itens_reprovados,
        odometro_registrado=payload.odometro_registrado,
    )
    db.add(checklist)

    try:
        db.flush()
    except OperationalError as e:
        db.rollback()
        msg = _extrair_erro_trigger(e)
        if msg:
            raise HTTPException(status_code=400, detail=msg)
        raise HTTPException(status_code=500, detail="Erro inesperado no banco de dados")

    if tem_critico:
        db.commit()
        raise HTTPException(
            status_code=400,
            detail="Checklist reprovado: itens críticos encontrados (freios, pneus ou faróis). Turno bloqueado até resolução.",
        )

    if payload.tipo == "inicio":
        turno = TurnoEntrega(
            veiculo_id=payload.veiculo_id,
            motorista_id=usuario.id,
            checklist_inicio_id=checklist.id,
            status="aberto",
            data=agora().date(),
        )
        db.add(turno)
        db.commit()
        db.refresh(turno)
        return {
            "mensagem": "Turno iniciado com sucesso",
            "turno_id": turno.id,
            "checklist_id": checklist.id,
            "data": turno.data.isoformat(),
        }

    if payload.veiculo_id != turno_hoje.veiculo_id:
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail=f"Veículo do checklist (id={payload.veiculo_id}) não corresponde ao veículo do turno ativo (id={turno_hoje.veiculo_id})",
        )

    chk_inicio_id = turno_hoje.checklist_inicio_id
    veiculo_id_trn = turno_hoje.veiculo_id

    chk_inicio = db.query(Checklist).filter(Checklist.id == chk_inicio_id).first()
    odometro_inicio = chk_inicio.odometro_registrado if chk_inicio else 0
    odometro_fim = payload.odometro_registrado
    km_rodada = max(0, odometro_fim - odometro_inicio)

    db.expire_all()

    veiculo = db.query(Veiculo).filter(Veiculo.id == veiculo_id_trn).first()

    _PRECO_LITRO = 5.8
    consumo_padrao = 35.0 if (veiculo and veiculo.tipo == "Moto") else 12.0

    abts = (
        db.query(Abastecimento)
        .filter(Abastecimento.veiculo_id == veiculo_id_trn)
        .order_by(Abastecimento.data.desc())
        .limit(2)
        .all()
    )

    if len(abts) >= 2:
        _km_diff = abts[0].odometro - abts[1].odometro
        _litros = float(abts[0].litros or 0)
        if _litros > 0 and _km_diff > 0:
            consumo_medio = round(_km_diff / _litros, 2)
        else:
            consumo_medio = consumo_padrao
    else:
        consumo_medio = consumo_padrao

    primeiro_chk_vida = (
        db.query(Checklist)
        .filter(Checklist.veiculo_id == veiculo_id_trn)
        .order_by(Checklist.odometro_registrado.asc())
        .first()
    )

    custo_acum = float(veiculo.custo_acumulado_manutencao or 0) if veiculo else 0.0
    km_inicio_ref = primeiro_chk_vida.odometro_registrado if primeiro_chk_vida else None
    km_total_vida = (odometro_fim - km_inicio_ref) if km_inicio_ref is not None else 0
    cpk = round(custo_acum / km_total_vida, 4) if km_total_vida > 0 else 0.0

    custo_comb_calc = round(km_rodada / consumo_medio * _PRECO_LITRO, 2) if (consumo_medio > 0 and km_rodada > 0) else 0.0
    custo_mnt_calc = round(km_rodada * cpk, 2)

    custo_comb_final = max(float(turno_hoje.custo_combustivel_total or 0), custo_comb_calc)
    custo_mnt_final = max(float(turno_hoje.custo_manutencao_total or 0), custo_mnt_calc)

    turno_hoje.status = "encerrado"
    turno_hoje.checklist_fim_id = checklist.id
    turno_hoje.custo_combustivel_total = custo_comb_final
    turno_hoje.custo_manutencao_total = custo_mnt_final
    db.commit()

    db.refresh(turno_hoje)

    custo_total = round(custo_comb_final + custo_mnt_final, 2)
    cupons = turno_hoje.total_cupons_dia or 0
    cpe = round(custo_total / cupons, 4) if cupons > 0 else 0.0

    return {
        "mensagem": "Turno encerrado com sucesso",
        "turno_id": turno_hoje.id,
        "checklist_fim_id": checklist.id,
        "data": turno_hoje.data.isoformat(),
        "motorista_id": turno_hoje.motorista_id,
        "veiculo_id": veiculo_id_trn,
        "km_inicio": odometro_inicio,
        "km_fim": odometro_fim,
        "km_rodada_turno": km_rodada,
        "consumo_medio_km_l": consumo_medio,
        "cpk_manutencao": cpk,
        "preco_litro_referencia": _PRECO_LITRO,
        "custo_combustivel": custo_comb_final,
        "custo_manutencao": custo_mnt_final,
        "custo_total": custo_total,
        "total_cupons_dia": cupons,
        "custo_por_entrega": cpe,
    }


@app.post("/frota/abastecimento", status_code=201)
async def frota_registrar_abastecimento(payload: AbastecimentoPayload, user_id: str = Cookie(default=None), db: Session = Depends(get_db)):
    """
    Registra um abastecimento.
    Se o motorista tiver turno aberto hoje, associa automaticamente o turno_id.
    O trigger trg_abt_after_odometro_custo cuida do restante:
      - Atualiza veiculos.odometro_atual (se KM maior)
      - Acumula custo_combustivel_total no turno
    """
    usuario = _resolver_usuario(user_id, db)

    turno = _turno_aberto_hoje(db, usuario.id)

    abastecimento = Abastecimento(
        veiculo_id=payload.veiculo_id,
        motorista_id=usuario.id,
        turno_id=turno.id if turno else None,
        data=agora(),
        odometro=payload.odometro,
        litros=payload.litros,
        valor_total=payload.valor_total,
    )
    db.add(abastecimento)
    db.commit()
    db.refresh(abastecimento)
    return {
        "mensagem": "Abastecimento registrado",
        "id": abastecimento.id,
        "turno_id": abastecimento.turno_id,
        "odometro": abastecimento.odometro,
        "valor_total": float(abastecimento.valor_total),
    }


@app.get("/frota/abastecimento/historico/{veiculo_id}")
async def frota_historico_abastecimento(veiculo_id: int, user_id: str = Cookie(default=None), db: Session = Depends(get_db)):
    """id"""
    _resolver_usuario(user_id, db)
    registros = (
        db.query(Abastecimento)
        .filter(Abastecimento.veiculo_id == veiculo_id)
        .order_by(Abastecimento.data.desc())
        .all()
    )
    return [
        {
            "id": r.id,
            "data": r.data.isoformat(),
            "motorista_id": r.motorista_id,
            "turno_id": r.turno_id,
            "odometro": r.odometro,
            "litros": float(r.litros),
            "valor_total": float(r.valor_total),
        }
        for r in registros
    ]


@app.post("/frota/manutencao", status_code=201)
async def frota_registrar_manutencao(payload: ManutencaoPayload, user_id: str = Cookie(default=None), db: Session = Depends(get_db)):
    """
    Registra uma manutenção.
    Associa ao turno aberto do veículo (se houver) para imputar custo no turno.
    O trigger trg_mnt_after_odometro_custo cuida do restante:
      - Atualiza veiculos.odometro_atual (se KM informado e maior)
      - Acumula em veiculos.custo_acumulado_manutencao
      - Acumula custo_manutencao_total no turno
    """
    _resolver_usuario(user_id, db)

    turno = _turno_aberto_veiculo_hoje(db, payload.veiculo_id)

    manutencao = Manutencao(
        veiculo_id=payload.veiculo_id,
        turno_id=turno.id if turno else None,
        data=payload.data,
        odometro=payload.odometro,
        categoria=payload.categoria,
        itens_trocados=payload.itens_trocados,
        valor_pecas=payload.valor_pecas,
        valor_mao_obra=payload.valor_mao_obra,
        oficina=payload.oficina,
    )
    db.add(manutencao)
    db.commit()
    db.refresh(manutencao)
    return {
        "mensagem": "Manutenção registrada",
        "id": manutencao.id,
        "turno_id": manutencao.turno_id,
        "custo_total": float((payload.valor_pecas or 0) + (payload.valor_mao_obra or 0)),
    }


@app.post("/frota/manutencao/solicitar", status_code=201)
async def frota_solicitar_manutencao(payload: SolicitacaoManutencaoPayload, user_id: str = Cookie(default=None), user_role: str = Cookie(default=None), db: Session = Depends(get_db)):
    """
    Motorista solicita uma manutenção.
    Criada com status='pendente' — aguarda aprovação do gestor.
    """
    if user_role not in ("entregador",):
        raise HTTPException(status_code=403, detail="Acesso restrito a entregadores")

    usuario = _resolver_usuario(user_id, db)

    if payload.categoria not in ("preventiva", "corretiva"):
        raise HTTPException(status_code=400, detail="categoria deve ser 'preventiva' ou 'corretiva'")

    veiculo = db.query(Veiculo).filter(Veiculo.id == payload.veiculo_id).first()
    if not veiculo:
        raise HTTPException(status_code=404, detail="Veículo não encontrado")

    if veiculo.odometro_atual and payload.odometro < veiculo.odometro_atual:
        raise HTTPException(
            status_code=400,
            detail=f"KM informado ({payload.odometro}) não pode ser menor que o registrado ({veiculo.odometro_atual})",
        )

    turno = _turno_aberto_hoje(db, usuario.id)

    manutencao = Manutencao(
        veiculo_id=payload.veiculo_id,
        motorista_id=usuario.id,
        turno_id=turno.id if turno else None,
        data=agora().date(),
        odometro=payload.odometro,
        categoria=payload.categoria,
        descricao_problema=payload.descricao_problema,
        oficina=payload.oficina,
        itens_trocados=payload.pecas or [],
        valor_pecas=payload.valor_pecas,
        valor_mao_obra=payload.valor_mao_obra,
        status="pendente",
    )
    db.add(manutencao)
    db.commit()
    db.refresh(manutencao)
    return {
        "mensagem": "Solicitação enviada ao gestor",
        "id": manutencao.id,
        "status": manutencao.status,
    }


@app.post("/frota/manutencao/{manutencao_id}/aprovar", status_code=200)
async def frota_aprovar_manutencao(manutencao_id: int, payload: AprovarManutencaoPayload, user_id: str = Cookie(default=None), user_role: str = Cookie(default=None), db: Session = Depends(get_db)):
    """
    Gestor aprova a solicitação de manutenção, opcionalmente complementando
    dados de oficina, custos e itens trocados.
    """
    if user_role not in ("gestor", "operador"):
        raise HTTPException(status_code=403, detail="Acesso restrito a gestores")

    mnt = db.query(Manutencao).filter(Manutencao.id == manutencao_id).first()
    if not mnt:
        raise HTTPException(status_code=404, detail="Manutenção não encontrada")

    if mnt.status != "pendente":
        raise HTTPException(status_code=400, detail=f"Manutenção já está '{mnt.status}'")

    mnt.status = "aprovada"
    mnt.oficina = payload.oficina or mnt.oficina
    mnt.valor_pecas = payload.valor_pecas
    mnt.valor_mao_obra = payload.valor_mao_obra
    mnt.itens_trocados = payload.itens_trocados or mnt.itens_trocados
    mnt.observacao_gestor = payload.observacao_gestor
    db.commit()
    return {"mensagem": "Manutenção aprovada", "id": mnt.id}


@app.post("/frota/manutencao/{manutencao_id}/rejeitar", status_code=200)
async def frota_rejeitar_manutencao(manutencao_id: int, user_id: str = Cookie(default=None), user_role: str = Cookie(default=None), observacao: str = None, db: Session = Depends(get_db)):
    """Gestor rejeita a solicitação de manutenção."""
    if user_role not in ("gestor", "operador"):
        raise HTTPException(status_code=403, detail="Acesso restrito a gestores")

    mnt = db.query(Manutencao).filter(Manutencao.id == manutencao_id).first()
    if not mnt:
        raise HTTPException(status_code=404, detail="Manutenção não encontrada")

    if mnt.status != "pendente":
        raise HTTPException(status_code=400, detail=f"Manutenção já está '{mnt.status}'")

    mnt.status = "rejeitada"
    mnt.observacao_gestor = observacao
    db.commit()
    return {"mensagem": "Manutenção rejeitada", "id": mnt.id}


@app.get("/frota/manutencao/historico/{veiculo_id}")
async def frota_historico_manutencao(veiculo_id: int, user_id: str = Cookie(default=None), db: Session = Depends(get_db)):
    """id"""
    _resolver_usuario(user_id, db)
    registros = (
        db.query(Manutencao)
        .filter(Manutencao.veiculo_id == veiculo_id)
        .order_by(Manutencao.data.desc())
        .all()
    )
    return [
        {
            "id": r.id,
            "data": r.data.isoformat(),
            "turno_id": r.turno_id,
            "odometro": r.odometro,
            "categoria": r.categoria,
            "itens_trocados": r.itens_trocados,
            "valor_pecas": float(r.valor_pecas or 0),
            "valor_mao_obra": float(r.valor_mao_obra or 0),
            "custo_total": float((r.valor_pecas or 0) + (r.valor_mao_obra or 0)),
            "oficina": r.oficina,
        }
        for r in registros
    ]
@app.post("/frota/pneus", status_code=201)
async def frota_instalar_pneu(payload: PneuInstalarPayload, user_id: str = Cookie(default=None), db: Session = Depends(get_db)):
    """
    Instala um pneu novo em uma posição do veículo.
    Antes do INSERT, descarta automaticamente qualquer pneu ativo
    naquela posição (mesmo veiculo_id + posicao).
    """
    _resolver_usuario(user_id, db)

    hoje = agora().date()

    db.query(PneuControle).filter(
        PneuControle.veiculo_id == payload.veiculo_id,
        PneuControle.posicao == payload.posicao,
        PneuControle.status == "ativo",
    ).update({
        "status": "descartado",
        "km_descarte": payload.km_instalacao,
        "data_descarte": hoje,
    }, synchronize_session=False)

    novo = PneuControle(
        veiculo_id=payload.veiculo_id,
        posicao=payload.posicao,
        marca=payload.marca,
        data_instalacao=payload.data_instalacao,
        km_instalacao=payload.km_instalacao,
        status="ativo",
    )
    db.add(novo)
    db.commit()
    db.refresh(novo)

    return {
        "mensagem": "Pneu instalado",
        "id": novo.id,
        "posicao": novo.posicao,
        "km_instalacao": novo.km_instalacao,
    }


@app.patch("/frota/pneus/{pneu_id}/descarte")
async def frota_descartar_pneu(pneu_id: int, payload: PneuDescartePayload, user_id: str = Cookie(default=None), db: Session = Depends(get_db)):
    _resolver_usuario(user_id, db)
    pneu = db.query(PneuControle).filter(PneuControle.id == pneu_id).first()
    if not pneu:
        raise HTTPException(status_code=404, detail="Pneu não encontrado")
    if pneu.status == "descartado":
        raise HTTPException(status_code=409, detail="Pneu já está descartado")

    pneu.status = "descartado"
    pneu.km_descarte = payload.km_descarte
    pneu.data_descarte = payload.data_descarte
    db.commit()

    km_rodados = payload.km_descarte - pneu.km_instalacao if pneu.km_instalacao else None

    return {
        "mensagem": "Pneu descartado",
        "id": pneu.id,
        "km_rodados": km_rodados,
    }


@app.get("/frota/pneus/ativos/{veiculo_id}")
async def frota_pneus_ativos(veiculo_id: int, user_id: str = Cookie(default=None), db: Session = Depends(get_db)):
    _resolver_usuario(user_id, db)
    km_atual = db.query(Veiculo.odometro_atual).filter(Veiculo.id == veiculo_id).scalar()

    pneus = db.query(PneuControle).filter(
        PneuControle.veiculo_id == veiculo_id,
        PneuControle.status == "ativo",
    ).order_by(PneuControle.posicao).all()

    return [
        {
            "id": p.id,
            "posicao": p.posicao,
            "marca": p.marca,
            "data_instalacao": p.data_instalacao.isoformat(),
            "km_instalacao": p.km_instalacao,
            "km_atual_veiculo": km_atual,
        }
        for p in pneus
    ]


@app.get("/frota/oficinas/lista")
async def frota_lista_oficinas(db: Session = Depends(get_db)):
    """Retorna lista de oficinas ativas para o formulário do entregador."""
    oficinas = db.query(Oficina).filter(Oficina.ativo == True).order_by(Oficina.nome).all()
    return [
        {"id": o.id, "nome": o.nome, "telefone": o.telefone}
        for o in oficinas
    ]


@app.post("/frota/oficinas", status_code=201)
async def frota_criar_oficina(payload: CriarOficinaPayload, user_role: str = Cookie(default=None), db: Session = Depends(get_db)):
    if user_role not in ("gestor", "operador"):
        raise HTTPException(status_code=403, detail="Acesso restrito a gestores")
    o = Oficina(nome=payload.nome.strip(), telefone=payload.telefone, endereco=payload.endereco)
    db.add(o)
    db.commit()
    db.refresh(o)
    return {"id": o.id, "nome": o.nome}


@app.delete("/frota/oficinas/{oficina_id}", status_code=204)
async def frota_desativar_oficina(oficina_id: int, user_role: str = Cookie(default=None), db: Session = Depends(get_db)):
    if user_role not in ("gestor", "operador"):
        raise HTTPException(status_code=403, detail="Acesso restrito a gestores")
    o = db.query(Oficina).filter(Oficina.id == oficina_id).first()
    if not o:
        raise HTTPException(status_code=404, detail="Oficina não encontrada")
    o.ativo = False
    db.commit()
    return None


@app.get("/frota/pecas/lista")
async def frota_lista_pecas(db: Session = Depends(get_db)):
    """Retorna catálogo de peças ativas para o formulário do entregador."""
    pecas = db.query(PecaCatalogo).filter(PecaCatalogo.ativo == True).order_by(PecaCatalogo.categoria, PecaCatalogo.nome).all()
    return [
        {"id": p.id, "nome": p.nome, "categoria": p.categoria, "unidade": p.unidade}
        for p in pecas
    ]


@app.post("/frota/pecas", status_code=201)
async def frota_criar_peca(payload: CriarPecaPayload, user_role: str = Cookie(default=None), db: Session = Depends(get_db)):
    if user_role not in ("gestor", "operador"):
        raise HTTPException(status_code=403, detail="Acesso restrito a gestores")
    p = PecaCatalogo(nome=payload.nome.strip(), categoria=payload.categoria, unidade=payload.unidade or "un")
    db.add(p)
    db.commit()
    db.refresh(p)
    return {"id": p.id, "nome": p.nome}


@app.delete("/frota/pecas/{peca_id}", status_code=204)
async def frota_desativar_peca(peca_id: int, user_role: str = Cookie(default=None), db: Session = Depends(get_db)):
    if user_role not in ("gestor", "operador"):
        raise HTTPException(status_code=403, detail="Acesso restrito a gestores")
    p = db.query(PecaCatalogo).filter(PecaCatalogo.id == peca_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Peça não encontrada")
    p.ativo = False
    db.commit()
    return None


@app.get("/frota/configuracoes")
async def frota_configuracoes_page(request: Request, user_id: str = Cookie(default=None), user_role: str = Cookie(default=None), db: Session = Depends(get_db)):
    if user_role not in ("gestor", "operador"):
        return RedirectResponse(url="/frota/dashboard")
    usuario = _resolver_usuario(user_id, db)
    oficinas = db.query(Oficina).filter(Oficina.ativo == True).order_by(Oficina.nome).all()
    pecas = db.query(PecaCatalogo).filter(PecaCatalogo.ativo == True).order_by(PecaCatalogo.categoria, PecaCatalogo.nome).all()
    return templates.TemplateResponse(request=request, name="frota_configuracoes.html", context={"usuario": usuario, "oficinas": oficinas, "pecas": pecas})
@app.get("/frota/score/ranking")
async def frota_score_ranking(user_id: str = Cookie(default=None), db: Session = Depends(get_db)):
    """
    Ranking de motoristas ordenado por score_atual (desc).
    total_entregas é mantido automaticamente pelo trigger trg_entrega_finalizada.
    """
    _exigir_perfil(user_id, db, ('gestor', 'operador'))

    scores = db.query(MotoristaScore).order_by(
        MotoristaScore.score_atual.desc(),
        MotoristaScore.total_entregas.desc(),
    ).all()

    usuarios_map = {u.id: u.username for u in db.query(Usuario).all()}

    return [
        {
            "posicao": idx + 1,
            "motorista_id": s.motorista_id,
            "username": usuarios_map.get(s.motorista_id, "—"),
            "score_atual": s.score_atual,
            "total_entregas": s.total_entregas,
            "updated_at": s.updated_at.isoformat() if s.updated_at else None,
        }
        for idx, s in enumerate(scores)
    ]


@app.get("/frota/dashboard/consolidado-turno/{turno_id}")
async def frota_consolidado_turno(turno_id, user_id: str = Cookie(default=None), db: Session = Depends(get_db)):
    """
    Consolidado do turno — todos os campos de custo e contagem
    são lidos diretamente do banco (mantidos por triggers, nunca calculados aqui).
    """
    _exigir_perfil(user_id, db, ('gestor', 'operador'))

    turno = db.query(TurnoEntrega).filter(TurnoEntrega.id == turno_id).first()
    if not turno:
        raise HTTPException(status_code=404, detail="Turno não encontrado")

    custo_comb = float(turno.custo_combustivel_total or 0)
    custo_mnt = float(turno.custo_manutencao_total or 0)

    chk_inicio = db.query(Checklist).filter(Checklist.id == turno.checklist_inicio_id).first()
    chk_fim = db.query(Checklist).filter(Checklist.id == turno.checklist_fim_id).first() if turno.checklist_fim_id else None

    km_percorrido = (chk_fim.odometro_registrado - chk_inicio.odometro_registrado) if (chk_inicio and chk_fim) else None

    return {
        "turno_id": turno.id,
        "data": turno.data.isoformat(),
        "status": turno.status,
        "motorista_id": turno.motorista_id,
        "veiculo_id": turno.veiculo_id,
        "total_cupons_dia": turno.total_cupons_dia,
        "custo_combustivel_total": custo_comb,
        "custo_manutencao_total": custo_mnt,
        "custo_total_dia": round(custo_comb + custo_mnt, 2),
        "km_inicio": chk_inicio.odometro_registrado if chk_inicio else None,
        "km_fim": chk_fim.odometro_registrado if chk_fim else None,
        "km_percorrido": km_percorrido,
    }


@app.get("/frota/analise/consumo/{veiculo_id}")
async def frota_analise_consumo(veiculo_id, user_id: str = Cookie(default=None), db: Session = Depends(get_db)):
    """
    Consumo médio de combustível em km/L para o veículo.

    Fórmula: (odometro_ultimo - odometro_penultimo) / litros_ultimo
    Requer ao menos 2 abastecimentos. Sem dados suficientes, retorna
    o padrão do tipo de veículo: Moto=35.0 km/L, Carro/Caminhão=12.0 km/L.

    Proteções:
      - litros <= 0  → retorna padrão (divisão por zero)
      - km_diff <= 0 → retorna padrão (odômetros inconsistentes)
    """
    _exigir_perfil(user_id, db, ('gestor', 'operador'))

    veiculo = db.query(Veiculo).filter(Veiculo.id == veiculo_id).first()
    if not veiculo:
        raise HTTPException(status_code=404, detail="Veículo não encontrado")

    consumo_padrao = 35.0 if veiculo.tipo == "Moto" else 12.0

    abts = db.query(Abastecimento).filter(
        Abastecimento.veiculo_id == veiculo_id
    ).order_by(
        Abastecimento.data.desc()
    ).limit(2).all()

    if len(abts) < 2:
        return {
            "veiculo_id": veiculo_id,
            "placa": veiculo.placa,
            "tipo": veiculo.tipo,
            "consumo_km_l": consumo_padrao,
            "fonte": "padrao",
            "total_abastecimentos": len(abts),
        }

    ultimo, penultimo = abts[0], abts[1]
    km_diff = ultimo.odometro - penultimo.odometro
    litros = float(ultimo.litros or 0)

    if litros <= 0 or km_diff <= 0:
        return {
            "veiculo_id": veiculo_id,
            "placa": veiculo.placa,
            "tipo": veiculo.tipo,
            "consumo_km_l": consumo_padrao,
            "fonte": "padrao",
            "aviso": "Dados insuficientes (km ou litros inválidos) — valor padrão retornado",
            "total_abastecimentos": len(abts),
        }

    consumo = round(km_diff / litros, 2)

    return {
        "veiculo_id": veiculo_id,
        "placa": veiculo.placa,
        "tipo": veiculo.tipo,
        "consumo_km_l": consumo,
        "fonte": "calculado",
        "km_percorrido": km_diff,
        "litros_ultimo": litros,
        "total_abastecimentos": len(abts),
    }


@app.get("/frota/analise/cpk/{veiculo_id}")
async def frota_analise_cpk(veiculo_id, user_id: str = Cookie(default=None), db: Session = Depends(get_db)):
    """
    Custo Por Quilômetro (CPK) de manutenção acumulado para o veículo.

    Fórmula: custo_acumulado_manutencao / km_total_rodado
      - custo_acumulado_manutencao: mantido pelo trigger trg_mnt_after_odometro_custo
      - km_total_rodado: odometro_atual − odometro do primeiro checklist registrado

    Retorna cpk=0.0 quando:
      - Veículo não tem checklist registrado (sem KM de referência inicial), ou
      - km_total_rodado <= 0 (veículo novo ou sem variação de KM)
    """
    _exigir_perfil(user_id, db, ('gestor', 'operador'))

    veiculo = db.query(Veiculo).filter(Veiculo.id == veiculo_id).first()
    if not veiculo:
        raise HTTPException(status_code=404, detail="Veículo não encontrado")

    primeiro_chk = db.query(Checklist).filter(
        Checklist.veiculo_id == veiculo_id
    ).order_by(
        Checklist.odometro_registrado.asc()
    ).first()

    custo = float(veiculo.custo_acumulado_manutencao or 0)
    km_atual = veiculo.odometro_atual or 0
    km_inicio = primeiro_chk.odometro_registrado if primeiro_chk else None
    km_total = (km_atual - km_inicio) if km_inicio is not None else 0

    if km_total <= 0:
        return {
            "veiculo_id": veiculo_id,
            "placa": veiculo.placa,
            "custo_acumulado_manutencao": custo,
            "km_total_rodado": km_total,
            "cpk_reais_por_km": 0.0,
            "km_inicial_referencia": km_inicio,
            "km_atual": km_atual,
            "aviso": "KM total insuficiente para calcular CPK",
        }

    cpk = round(custo / km_total, 4)

    return {
        "veiculo_id": veiculo_id,
        "placa": veiculo.placa,
        "custo_acumulado_manutencao": custo,
        "km_total_rodado": km_total,
        "cpk_reais_por_km": cpk,
        "km_inicial_referencia": km_inicio,
        "km_atual": km_atual,
    }


@app.get("/frota/analise/alertas")
async def frota_analise_alertas(user_id: str = Cookie(default=None), db: Session = Depends(get_db)):
    """
    Alertas preditivos de troca de óleo para toda a frota.

    Critério de alerta (threshold = 9000 km):
      - "sem_registro": veículo nunca teve troca de óleo registrada (risco desconhecido)
      - "atencao":      km_desde_troca >= 9000 e < 10000
      - "critico":      km_desde_troca >= 10000

    Apenas veículos com ao menos 1 alerta são retornados na lista.

    A busca por óleo usa filtro Python no JSON array (itens_trocados).
    Somente manutenções preventivas COM odômetro registrado são consideradas
    (odometro nullable — manutenções sem KM não servem como referência de KM).

    itens_trocados esperado: [{"item": "oleo_motor", ...}, ...]
    """
    _exigir_perfil(user_id, db, ('gestor', 'operador'))

    _KM_ALERTA = 9000
    _KM_CRITICO = 10000

    veiculos = db.query(Veiculo).all()

    todas_mnt = db.query(Manutencao).filter(
        Manutencao.categoria == "preventiva",
        Manutencao.odometro.isnot(None),
    ).order_by(
        Manutencao.veiculo_id,
        Manutencao.odometro.desc(),
    ).all()

    mnt_por_veiculo = defaultdict(list)
    for m in todas_mnt:
        mnt_por_veiculo[m.veiculo_id].append(m)

    alertas = []

    for v in veiculos:
        km_atual = v.odometro_atual

        ultima_troca_km = None
        for m in mnt_por_veiculo[v.id]:
            itens = m.itens_trocados or []
            tem_oleo = any(
                "oleo" in (item.get("nome") or item.get("item") or "").lower()
                for item in itens
                if isinstance(item, dict)
            )
            if tem_oleo:
                ultima_troca_km = m.odometro
                break

        if ultima_troca_km is None:
            alertas.append({
                "veiculo_id": v.id,
                "placa": v.placa,
                "tipo": v.tipo,
                "km_atual": km_atual,
                "ultima_troca_km": None,
                "km_desde_troca": None,
                "nivel_alerta": "sem_registro",
                "mensagem": "Nenhuma troca de óleo registrada no sistema",
            })
            continue

        if km_atual is None:
            continue

        km_desde = km_atual - ultima_troca_km
        if km_desde >= _KM_ALERTA:
            alertas.append({
                "veiculo_id": v.id,
                "placa": v.placa,
                "tipo": v.tipo,
                "km_atual": km_atual,
                "ultima_troca_km": ultima_troca_km,
                "km_desde_troca": km_desde,
                "nivel_alerta": "critico" if km_desde >= _KM_CRITICO else "atencao",
                "mensagem": f"Troca de óleo necessária — {km_desde} km desde a última troca",
            })

    return {
        "total_alertas": len(alertas),
        "km_limite": _KM_ALERTA,
        "alertas": alertas,
    }


@app.get("/frota/alertas")
async def frota_alertas_page(request: Request, user_id: str = Cookie(default=None), db: Session = Depends(get_db)):
    """Página de alertas de manutenção para o gestor."""
    usuario = _resolver_usuario(user_id, db)

    _KM_ALERTA = 9000
    _KM_CRITICO = 10000

    veiculos = db.query(Veiculo).all()

    todas_mnt = db.query(Manutencao).filter(
        Manutencao.categoria == "preventiva",
        Manutencao.odometro.isnot(None),
    ).order_by(
        Manutencao.veiculo_id,
        Manutencao.odometro.desc(),
    ).all()

    mnt_por_veiculo = defaultdict(list)
    for m in todas_mnt:
        mnt_por_veiculo[m.veiculo_id].append(m)

    alertas = []
    veiculos_ok = 0
    total_critico = 0
    total_atencao = 0
    total_sem_reg = 0

    for v in veiculos:
        km_atual = v.odometro_atual

        ultima_troca_km = None
        for m in mnt_por_veiculo[v.id]:
            itens = m.itens_trocados or []
            if any(
                "oleo" in (i.get("item") or "").lower()
                for i in itens
                if isinstance(i, dict)
            ):
                ultima_troca_km = m.odometro
                break

        if ultima_troca_km is None:
            total_sem_reg += 1
            alertas.append({
                "nivel_alerta": "sem_registro",
                "veiculo_id": v.id,
                "placa": v.placa,
                "modelo": v.modelo or "—",
                "mensagem": "Nenhuma troca de óleo registrada no sistema",
            })
            continue

        if km_atual is not None and km_atual - ultima_troca_km >= _KM_ALERTA:
            km_desde = km_atual - ultima_troca_km
            nivel = "critico" if km_desde >= _KM_CRITICO else "atencao"
            if nivel == "critico":
                total_critico += 1
            else:
                total_atencao += 1
            alertas.append({
                "nivel_alerta": nivel,
                "veiculo_id": v.id,
                "placa": v.placa,
                "modelo": v.modelo or "—",
                "km_desde_troca": km_desde,
                "km_ultima_troca": ultima_troca_km,
                "km_atual": km_atual,
                "mensagem": f"{km_desde:,} km desde a última troca de óleo".replace(",", "."),
            })
        else:
            veiculos_ok += 1

    ordem = {"critico": 0, "atencao": 1, "sem_registro": 2}
    alertas.sort(key=lambda a: ordem.get(a["nivel_alerta"], 9))

    return templates.TemplateResponse(
        request=request,
        name="frota_alertas.html",
        context={
            "usuario": usuario,
            "alertas": alertas,
            "total_critico": total_critico,
            "total_atencao": total_atencao,
            "total_sem_reg": total_sem_reg,
            "veiculos_ok": veiculos_ok,
            "km_limite": _KM_ALERTA,
            "km_critico": _KM_CRITICO,
        },
    )


@app.get("/frota/manutencao")
async def frota_manutencao_page(request: Request, veiculo_id: int = None, user_id: str = Cookie(default=None), db: Session = Depends(get_db)):
    """
    Histórico de manutenções para o gestor.
    Sem veiculo_id: mostra todos os veículos.
    Com veiculo_id: filtra por veículo.
    """
    usuario = _resolver_usuario(user_id, db)
    veiculos = db.query(Veiculo).order_by(Veiculo.placa).all()

    veiculo_selecionado = None
    if veiculo_id:
        veiculo_selecionado = db.query(Veiculo).filter(Veiculo.id == veiculo_id).first()
        if not veiculo_selecionado:
            raise HTTPException(status_code=404, detail="Veículo não encontrado")

    placa_map = {v.id: v.placa for v in veiculos}
    modelo_map = {v.id: v.modelo for v in veiculos}
    motorista_map = {u.id: u.username for u in db.query(Usuario).all()}

    pendentes_raw = db.query(Manutencao).filter(
        Manutencao.status == "pendente"
    ).order_by(Manutencao.data.desc()).all()

    catalogo_nomes = {
        p.nome.lower().strip()
        for p in db.query(PecaCatalogo).filter(PecaCatalogo.ativo == True).all()
    }

    pendentes = []
    for p in pendentes_raw:
        itens = p.itens_trocados or []
        itens_nomes = ", ".join(
            (i.get("nome") or i.get("item", "")).replace("_", " ").title()
            for i in itens
            if isinstance(i, dict) and (i.get("nome") or i.get("item"))
        ) or None

        pecas_sem_cadastro = [
            (i.get("nome") or i.get("item", "")).strip()
            for i in itens
            if isinstance(i, dict)
            and (i.get("nome") or i.get("item", "")).strip()
            and (i.get("nome") or i.get("item", "")).lower().strip() not in catalogo_nomes
        ]

        pendentes.append({
            "id": p.id,
            "placa": placa_map.get(p.veiculo_id, "—"),
            "modelo": modelo_map.get(p.veiculo_id, "—"),
            "veiculo_id": p.veiculo_id,
            "categoria": p.categoria,
            "data": p.data.strftime("%d/%m/%Y") if p.data else "—",
            "odometro": p.odometro,
            "descricao_problema": p.descricao_problema or "—",
            "motorista": motorista_map.get(p.motorista_id, "—") if p.motorista_id else "—",
            "oficina": p.oficina or "",
            "pecas_str": itens_nomes or "",
            "valor_pecas": float(p.valor_pecas or 0),
            "valor_mao_obra": float(p.valor_mao_obra or 0),
            "pecas_sem_cadastro": pecas_sem_cadastro,
        })

    query = db.query(Manutencao).filter(
        Manutencao.status == "aprovada"
    ).order_by(Manutencao.data.desc())

    if veiculo_id:
        query = query.filter(Manutencao.veiculo_id == veiculo_id)

    registros = query.limit(200).all()

    custo_total = 0.0
    total_preventiva = 0
    total_corretiva = 0

    manutencoes = []
    for r in registros:
        pecas = float(r.valor_pecas or 0)
        mao_obra = float(r.valor_mao_obra or 0)
        custo = round(pecas + mao_obra, 2)
        custo_total += custo

        if r.categoria == "preventiva":
            total_preventiva += 1
        else:
            total_corretiva += 1

        itens = r.itens_trocados or []
        itens_str = ", ".join(
            (i.get("nome") or i.get("item", "")).replace("_", " ").title()
            for i in itens
            if isinstance(i, dict) and (i.get("nome") or i.get("item"))
        ) or None

        manutencoes.append({
            "id": r.id,
            "veiculo_id": r.veiculo_id,
            "placa": placa_map.get(r.veiculo_id, "—"),
            "modelo": modelo_map.get(r.veiculo_id, "—"),
            "data": r.data.strftime("%d/%m/%Y") if r.data else "—",
            "categoria": r.categoria,
            "oficina": r.oficina,
            "odometro": r.odometro,
            "valor_pecas": pecas,
            "valor_mao_obra": mao_obra,
            "custo_total": custo,
            "itens_trocados": itens,
            "itens_str": itens_str,
        })

    return templates.TemplateResponse(
        request=request,
        name="frota_manutencao.html",
        context={
            "usuario": usuario,
            "veiculos": veiculos,
            "veiculo_id": veiculo_id,
            "veiculo_selecionado": veiculo_selecionado,
            "pendentes": pendentes,
            "manutencoes": manutencoes,
            "custo_total": round(custo_total, 2),
            "total_preventiva": total_preventiva,
            "total_corretiva": total_corretiva,
        },
    )


@app.get("/frota/ranking")
async def frota_ranking_page(request: Request, user_id: str = Cookie(default=None), db: Session = Depends(get_db)):
    """Ranking de scores dos motoristas — visão HTML para o gestor."""
    usuario = _resolver_usuario(user_id, db)

    scores_raw = db.query(MotoristaScore).order_by(
        MotoristaScore.score_atual.desc(),
        MotoristaScore.total_entregas.desc(),
    ).all()

    usuarios_map = {u.id: u.username for u in db.query(Usuario).all()}

    def _nivel(score: int) -> str:
        if score >= 90:
            return "ouro"
        if score >= 70:
            return "prata"
        if score >= 50:
            return "bronze"
        return "normal"

    scores = [
        {
            "posicao": idx + 1,
            "motorista_id": s.motorista_id,
            "username": usuarios_map.get(s.motorista_id, f"#{s.motorista_id}"),
            "score_atual": s.score_atual,
            "total_entregas": s.total_entregas,
            "nivel": _nivel(s.score_atual),
            "updated_at_fmt": s.updated_at.strftime("%d/%m %H:%M") if s.updated_at else None,
        }
        for idx, s in enumerate(scores_raw)
    ]

    return templates.TemplateResponse(
        request=request,
        name="frota_ranking.html",
        context={
            "usuario": usuario,
            "scores": scores,
        },
    )
@app.get("/frota/dashboard")
async def frota_dashboard_page(request: Request, user_id: str = Cookie(default=None), user_role: str = Cookie(default=None), db: Session = Depends(get_db)):
    """Painel principal do gestor de frota."""
    usuario = _resolver_usuario(user_id, db)
    hoje = agora().date()

    veiculos = db.query(Veiculo).all()

    turnos_hoje = db.query(TurnoEntrega).filter(
        TurnoEntrega.data == hoje
    ).all()

    total_turnos_ativos = sum(1 for t in turnos_hoje if t.status == 'aberto')
    total_cupons_hoje = sum((t.total_cupons_dia or 0) for t in turnos_hoje)
    custo_total_hoje = round(sum(
        float(t.custo_combustivel_total or 0) + float(t.custo_manutencao_total or 0)
        for t in turnos_hoje
    ), 2)

    scores_raw = db.query(MotoristaScore).join(
        MotoristaScore.motorista
    ).order_by(
        MotoristaScore.score_atual.desc()
    ).limit(10).all()

    scores = [
        {
            'motorista_nome': s.motorista.username if s.motorista else f"#{s.motorista_id}",
            'score_atual': s.score_atual,
            'total_entregas': s.total_entregas,
            'updated_at': s.updated_at.strftime('%d/%m %H:%M') if s.updated_at else '—',
        }
        for s in scores_raw
    ]

    _KM_ALERTA = 9000
    _KM_CRITICO = 10000

    todas_mnt = db.query(Manutencao).filter(
        Manutencao.categoria == 'preventiva',
        Manutencao.odometro.isnot(None)
    ).order_by(Manutencao.veiculo_id, Manutencao.odometro.desc()).all()

    mnt_por_veiculo = defaultdict(list)
    for m in todas_mnt:
        mnt_por_veiculo[m.veiculo_id].append(m)

    alertas = []
    for v in veiculos:
        km_atual = v.odometro_atual
        ultima_troca_km = None
        for m in mnt_por_veiculo[v.id]:
            itens = m.itens_trocados or []
            tem_oleo = any(
                'oleo' in (item.get('nome') or item.get('item') or '').lower()
                for item in itens
                if isinstance(item, dict)
            )
            if tem_oleo:
                ultima_troca_km = m.odometro
                break

        if ultima_troca_km is None:
            alertas.append({
                'nivel_alerta': 'sem_registro',
                'veiculo_id': v.id,
                'placa': v.placa,
                'modelo': v.modelo,
                'mensagem': 'Nenhuma troca de óleo registrada',
            })
            continue

        if km_atual is None:
            continue

        if km_atual - ultima_troca_km >= _KM_ALERTA:
            km_desde = km_atual - ultima_troca_km
            alertas.append({
                'nivel_alerta': 'critico' if km_desde >= _KM_CRITICO else 'atencao',
                'veiculo_id': v.id,
                'placa': v.placa,
                'modelo': v.modelo,
                'km_desde_troca': km_desde,
                'km_ultima_troca': ultima_troca_km,
                'km_atual': km_atual,
                'mensagem': f"{km_desde} km desde a última troca de óleo",
            })

    return templates.TemplateResponse(request=request, name="frota_dashboard.html", context={
        'usuario': usuario,
        'veiculos': veiculos,
        'scores': scores,
        'alertas': alertas,
        'alertas_count': len(alertas),
        'total_turnos_ativos': total_turnos_ativos,
        'total_cupons_hoje': total_cupons_hoje,
        'custo_total_hoje': custo_total_hoje,
        'data_hoje': hoje.strftime('%d/%m/%Y'),
    })


@app.get("/frota/turno")
async def frota_turno_page(request: Request, user_id: str = Cookie(default=None), user_role: str = Cookie(default=None), db: Session = Depends(get_db)):
    """
    Interface do motorista — acompanha o turno em tempo real.
    EXCLUSIVO PARA ENTREGADORES: gestores são redirecionados para o painel.
    """
    if user_role not in ('entregador',):
        return RedirectResponse(url='/frota/dashboard')

    usuario = _resolver_usuario(user_id, db)
    turno = _turno_aberto_hoje(db, usuario.id)

    veiculo = None
    if turno:
        veiculo = db.query(Veiculo).filter(Veiculo.id == turno.veiculo_id).first()
    if not veiculo:
        veiculo = db.query(Veiculo).filter(Veiculo.entregador_id == usuario.id).first()

    _MESES = ['Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho', 'Julho', 'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro']

    _DIAS = ['Segunda-feira', 'Terça-feira', 'Quarta-feira', 'Quinta-feira', 'Sexta-feira', 'Sábado', 'Domingo']

    _hoje = agora().date()

    data_hoje_fmt = f"{_DIAS[_hoje.weekday()]}, {_hoje.day:02d} de {_MESES[_hoje.month - 1]} de {_hoje.year}"

    return templates.TemplateResponse(request=request, name="frota_turno.html", context={
        'usuario': usuario,
        'turno': turno,
        'veiculo': veiculo,
        'data_hoje': data_hoje_fmt,
    })


@app.get("/frota/checklist")
async def frota_checklist_page(request: Request, veiculo_id: str = None, tipo: str = 'inicio', user_id: str = Cookie(default=None), user_role: str = Cookie(default=None), db: Session = Depends(get_db)):
    """
    Formulário de inspeção veicular — EXCLUSIVO PARA ENTREGADORES.
    Gestores e operadores são redirecionados para o painel de frota.

    Query params:
      veiculo_id — ID do veículo a inspecionar
      tipo       — 'inicio' (padrão) | 'fim'
    """
    if user_role not in ('entregador',):
        return RedirectResponse(url='/frota/dashboard')

    usuario = _resolver_usuario(user_id, db)

    if not veiculo_id:
        return RedirectResponse(url='/frota/turno')

    veiculo = db.query(Veiculo).filter(Veiculo.id == veiculo_id).first()
    if not veiculo:
        raise HTTPException(status_code=404, detail='Veículo não encontrado')

    if tipo not in ('inicio', 'fim'):
        tipo = 'inicio'

    turno = _turno_aberto_hoje(db, usuario.id)

    return templates.TemplateResponse(request=request, name="frota_checklist.html", context={
        'usuario': usuario,
        'veiculo': veiculo,
        'tipo': tipo,
        'turno': turno,
        'odometro_sugerido': veiculo.odometro_atual or 0,
    })


@app.get("/frota/historico-geral")
async def frota_historico_geral_page(request: Request, veiculo_id: str = None, user_id: str = Cookie(default=None), db: Session = Depends(get_db)):
    """aprovada"""
    usuario = _resolver_usuario(user_id, db)
    veiculos = db.query(Veiculo).order_by(Veiculo.placa).all()
    placa_map = {v.id: v.placa for v in veiculos}
    modelo_map = {v.id: v.modelo for v in veiculos}

    mnt_q = db.query(Manutencao).filter(Manutencao.status == 'aprovada')
    abt_q = db.query(Abastecimento)
    chk_q = db.query(Checklist)

    if veiculo_id:
        mnt_q = mnt_q.filter(Manutencao.veiculo_id == veiculo_id)
        abt_q = abt_q.filter(Abastecimento.veiculo_id == veiculo_id)
        chk_q = chk_q.filter(Checklist.veiculo_id == veiculo_id)

    manutencoes = mnt_q.order_by(Manutencao.data.desc()).limit(300).all()
    abastecimentos = abt_q.order_by(Abastecimento.data.desc()).limit(300).all()
    checklists = chk_q.order_by(Checklist.data_hora.desc()).limit(300).all()

    custo_mnt = sum(float(m.valor_pecas or 0) + float(m.valor_mao_obra or 0) for m in manutencoes)
    custo_abt = sum(float(a.valor_total or 0) for a in abastecimentos)
    chk_ok = sum(1 for c in checklists if c.aprovado)
    chk_nok = len(checklists) - chk_ok

    rows_mnt = []
    for m in manutencoes:
        itens = m.itens_trocados or []
        itens_str = ', '.join(
            i.get('nome', i.get('item', '')).replace('_', ' ').title()
            for i in itens
            if isinstance(i, dict) and (i.get('nome') or i.get('item'))
        ) or '—'
        rows_mnt.append({
            'id': m.id,
            'placa': placa_map.get(m.veiculo_id, '—'),
            'modelo': modelo_map.get(m.veiculo_id, '—'),
            'data': m.data.strftime('%d/%m/%Y') if m.data else '—',
            'categoria': m.categoria,
            'oficina': m.oficina or '—',
            'itens_str': itens_str,
            'odometro': m.odometro,
            'valor_pecas': float(m.valor_pecas or 0),
            'valor_mao': float(m.valor_mao_obra or 0),
            'total': round(float(m.valor_pecas or 0) + float(m.valor_mao_obra or 0), 2),
        })

    rows_abt = []
    for a in abastecimentos:
        litros = float(a.litros or 0)
        total = float(a.valor_total or 0)
        preco = round(total / litros, 3) if litros > 0 else None
        rows_abt.append({
            'placa': placa_map.get(a.veiculo_id, '—'),
            'modelo': modelo_map.get(a.veiculo_id, '—'),
            'data': a.data.strftime('%d/%m/%Y') if a.data else '—',
            'litros': litros,
            'preco_l': preco,
            'total': total,
            'odometro': a.odometro,
        })

    rows_chk = []
    for c in checklists:
        reprovados = c.itens_reprovados or []
        rep_str = ', '.join(
            r.get('item', '').replace('_', ' ').title()
            for r in reprovados
            if isinstance(r, dict)
        ) or None
        rows_chk.append({
            'placa': placa_map.get(c.veiculo_id, '—'),
            'modelo': modelo_map.get(c.veiculo_id, '—'),
            'data': c.data_hora.strftime('%d/%m/%Y %H:%M') if c.data_hora else '—',
            'tipo': c.tipo,
            'aprovado': c.aprovado,
            'odometro': c.odometro_registrado,
            'rep_str': rep_str,
        })

    return templates.TemplateResponse(request=request, name="frota_historico_geral.html", context={
        'usuario': usuario,
        'veiculos': veiculos,
        'veiculo_id': veiculo_id,
        'rows_mnt': rows_mnt,
        'rows_abt': rows_abt,
        'rows_chk': rows_chk,
        'custo_mnt': custo_mnt,
        'custo_abt': custo_abt,
        'chk_ok': chk_ok,
        'chk_nok': chk_nok,
        'total_mnt': len(rows_mnt),
        'total_abt': len(rows_abt),
        'total_chk': len(rows_chk),
    })


@app.get("/frota/historico/{veiculo_id}")
async def frota_historico_page(veiculo_id: str, request: Request, user_id: str = Cookie(default=None), db: Session = Depends(get_db)):
    """
    Timeline unificada de eventos de um veículo:
    abastecimentos, manutenções, checklists e trocas de pneus.
    """
    usuario = _resolver_usuario(user_id, db)

    veiculo = db.query(Veiculo).filter(Veiculo.id == veiculo_id).first()
    if not veiculo:
        raise HTTPException(status_code=404, detail='Veículo não encontrado')

    veiculos = db.query(Veiculo).order_by(Veiculo.placa).all()

    abastecimentos = db.query(Abastecimento).filter(
        Abastecimento.veiculo_id == veiculo_id
    ).order_by(Abastecimento.data.desc()).limit(100).all()

    manutencoes = db.query(Manutencao).filter(
        Manutencao.veiculo_id == veiculo_id
    ).order_by(Manutencao.data.desc()).limit(100).all()

    checklists = db.query(Checklist).filter(
        Checklist.veiculo_id == veiculo_id
    ).order_by(Checklist.data_hora.desc()).limit(100).all()

    pneus = db.query(PneuControle).filter(
        PneuControle.veiculo_id == veiculo_id
    ).order_by(PneuControle.data_instalacao.desc()).all()

    eventos = []

    for a in abastecimentos:
        litros = float(a.litros or 0)
        valor = float(a.valor_total or 0)
        preco_l = round(valor / litros, 3) if litros > 0 else None
        eventos.append({
            'tipo': 'abastecimento',
            'data': a.data.isoformat() if a.data else '',
            '_sort_key': a.data,
            'titulo': f"Abastecimento — {litros:.1f} L",
            'subtitulo': f"{a.odometro:,} km · {('R$ ' + format(preco_l, '.3f') + '/L') if preco_l else ''}".replace(',', '.'),
            'valor': valor if valor > 0 else None,
            'icone': 'fuel',
            'detalhes': {
                'Litros': f"{litros:.2f} L",
                'Odômetro': f"{a.odometro:,} km".replace(',', '.'),
                'Preço/L': f"R$ {preco_l:.3f}" if preco_l else '—',
                'Total': f"R$ {valor:.2f}",
            },
        })

    for m in manutencoes:
        pecas = float(m.valor_pecas or 0)
        mao_ob = float(m.valor_mao_obra or 0)
        total = round(pecas + mao_ob, 2)
        itens = m.itens_trocados or []
        itens_str = ', '.join(
            i.get('item', '').replace('_', ' ').title()
            for i in itens
            if isinstance(i, dict)
        ) or '—'
        eventos.append({
            'tipo': 'manutencao',
            'data': m.data.isoformat() if m.data else '',
            '_sort_key': datetime.combine(m.data, datetime.min.time()) if m.data else datetime.min,
            'titulo': f"Manutenção {m.categoria.capitalize()} — {itens_str[:40]}",
            'subtitulo': f"{m.oficina or 'Sem oficina informada'}" + (f" · {m.odometro:,} km".replace(',', '.') if m.odometro else ''),
            'valor': total if total > 0 else None,
            'icone': 'wrench',
            'detalhes': {
                'Categoria': m.categoria.capitalize(),
                'Peças': f"R$ {pecas:.2f}",
                'Mão de obra': f"R$ {mao_ob:.2f}",
                'Oficina': m.oficina or '—',
                'Odômetro': f"{m.odometro:,} km".replace(',', '.') if m.odometro else '—',
                'Itens': itens_str,
            },
        })

    for c in checklists:
        reprovados = c.itens_reprovados or []
        rep_str = ', '.join(
            r.get('item', '').replace('_', ' ').title()
            for r in reprovados
            if isinstance(r, dict)
        ) or None
        eventos.append({
            'tipo': 'checklist',
            'data': c.data_hora.isoformat() if c.data_hora else '',
            '_sort_key': c.data_hora,
            'titulo': f"Checklist de {'Início' if c.tipo == 'inicio' else 'Fim'} — {'Aprovado' if c.aprovado else 'Reprovado'}",
            'subtitulo': f"{c.odometro_registrado:,} km".replace(',', '.') + (f" · Reprovado: {rep_str}" if rep_str else ''),
            'valor': None,
            'icone': 'clipboard-check' if c.aprovado else 'clipboard-x',
            'detalhes': {
                'Tipo': c.tipo.capitalize(),
                'Situação': 'Aprovado' if c.aprovado else 'Reprovado',
                'Odômetro': f"{c.odometro_registrado:,} km".replace(',', '.'),
                'Reprovados': rep_str or 'Nenhum',
            },
        })

    for p in pneus:
        km_vida = p.km_descarte - p.km_instalacao if p.km_descarte else None
        eventos.append({
            'tipo': 'pneu',
            'data': p.data_instalacao.isoformat() if p.data_instalacao else '',
            '_sort_key': datetime.combine(p.data_instalacao, datetime.min.time()) if p.data_instalacao else datetime.min,
            'titulo': f"Pneu {p.posicao.replace('_', ' ').title()} instalado",
            'subtitulo': f"{p.marca or 'Sem marca'} · {p.km_instalacao:,} km".replace(',', '.') + (f" · Descartado em {p.km_descarte:,} km".replace(',', '.') if p.km_descarte else ''),
            'valor': None,
            'icone': 'circle-dot',
            'detalhes': {
                'Posição': p.posicao.replace('_', ' ').title(),
                'Marca': p.marca or '—',
                'Instalação': f"{p.km_instalacao:,} km".replace(',', '.'),
                'Descarte': f"{p.km_descarte:,} km".replace(',', '.') if p.km_descarte else 'Em uso',
                'Vida útil': f"{km_vida:,} km".replace(',', '.') if km_vida else '—',
                'Status': p.status.capitalize(),
            },
        })

    eventos.sort(key=lambda e: e['_sort_key'] or datetime.min, reverse=True)

    for e in eventos:
        e.pop('_sort_key', None)

    consumo = None

    abts_consumo = db.query(Abastecimento).filter(
        Abastecimento.veiculo_id == veiculo_id
    ).order_by(Abastecimento.data.desc()).limit(2).all()

    consumo_padrao = 35.0 if veiculo.tipo == 'Moto' else 12.0

    if len(abts_consumo) >= 2:
        _km_diff = abts_consumo[0].odometro - abts_consumo[1].odometro
        _litros = float(abts_consumo[0].litros or 0)
        if _litros > 0 and _km_diff > 0:
            consumo = {
                'consumo_km_l': round(_km_diff / _litros, 2),
                'fonte': 'calculado',
                'total_abastecimentos': len(abts_consumo),
            }

    if not consumo:
        consumo = {
            'consumo_km_l': consumo_padrao,
            'fonte': 'padrao',
            'total_abastecimentos': len(abts_consumo),
        }

    cpk = None

    primeiro_chk = db.query(Checklist).filter(
        Checklist.veiculo_id == veiculo_id
    ).order_by(Checklist.odometro_registrado.asc()).first()

    custo_acum = float(veiculo.custo_acumulado_manutencao or 0)
    km_inicio = primeiro_chk.odometro_registrado if primeiro_chk else None
    km_total = (veiculo.odometro_atual or 0) - km_inicio if km_inicio is not None else 0

    if km_total > 0:
        cpk = {
            'cpk_reais_por_km': round(custo_acum / km_total, 4),
            'km_total_rodado': km_total,
            'custo_acumulado': custo_acum,
        }

    pneus_ativos = [p for p in pneus if p.status == 'ativo']

    pneus_ctx = [
        {
            'posicao': p.posicao,
            'marca': p.marca,
            'data_troca': p.data_instalacao.isoformat() if p.data_instalacao else None,
            'km_troca': p.km_instalacao,
            'custo': None,
        }
        for p in pneus_ativos
    ]

    return templates.TemplateResponse(request=request, name="frota_historico.html", context={
        'usuario': usuario,
        'veiculo': veiculo,
        'veiculos': veiculos,
        'eventos': eventos,
        'consumo': consumo,
        'cpk': cpk,
        'pneus': pneus_ctx,
    })


@app.get("/frota/analise/eficiencia-turno/{turno_id}")
async def frota_analise_eficiencia_turno(turno_id: str, user_id: str = Cookie(default=None), db: Session = Depends(get_db)):
    """
    Eficiência financeira do turno: custo total por entrega realizada.

    Fórmula: (custo_combustivel_total + custo_manutencao_total) / total_cupons_dia

    Todos os campos são mantidos por triggers MySQL — nunca calculados aqui.
    Retorna custo_por_entrega=0.0 quando total_cupons_dia=0 (sem entregas
    no turno ainda, ou turno recém-aberto) para evitar divisão por zero.
    """
    _exigir_perfil(user_id, db, ('gestor', 'operador'))

    turno = db.query(TurnoEntrega).filter(TurnoEntrega.id == turno_id).first()
    if not turno:
        raise HTTPException(status_code=404, detail='Turno não encontrado')

    custo_comb = float(turno.custo_combustivel_total or 0)
    custo_mnt = float(turno.custo_manutencao_total or 0)
    custo_total = round(custo_comb + custo_mnt, 2)
    total_cupons = turno.total_cupons_dia or 0

    custo_por_entrega = round(custo_total / total_cupons, 4) if total_cupons > 0 else 0.0

    return {
        'turno_id': turno.id,
        'data': turno.data.isoformat(),
        'status': turno.status,
        'motorista_id': turno.motorista_id,
        'veiculo_id': turno.veiculo_id,
        'total_cupons_dia': total_cupons,
        'custo_combustivel': custo_comb,
        'custo_manutencao': custo_mnt,
        'custo_total': custo_total,
        'custo_por_entrega': custo_por_entrega,
        'aviso': 'Turno sem entregas — CPE indisponível' if total_cupons == 0 else None,
    }
