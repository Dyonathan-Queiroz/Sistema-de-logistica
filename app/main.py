from fastapi import FastAPI, Request, Form, Depends, Cookie, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from sqlalchemy import func, case as sql_case, or_
from passlib.context import CryptContext
from datetime import date, datetime
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

    return templates.TemplateResponse(
        request=request,
        name="dashboard_entregador.html",
        context={
            "disponiveis": disponiveis,
            "em_rota": em_rota,
            "link_rota": link_rota,
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
        entrega.data_aceite = datetime.utcnow()
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

    municipio_cliente = (cliente.municipio or "") if cliente else ""
    estado_cliente = (cliente.estado or "") if cliente else ""

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
        entrega.data_finalizacao = datetime.utcnow()
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
        observacao=dados.get("observacao"),
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
