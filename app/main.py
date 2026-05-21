import uuid
import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from fastapi import FastAPI, Request, Depends, Form, Response, HTTPException
import csv
import io
from fastapi.responses import RedirectResponse, JSONResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, func
from sqlalchemy.orm import joinedload
from pathlib import Path

from app.api.routes import oportunidades, mensagens, canais, tarefas, auth
from app.api.webhooks import whatsapp as webhook_whatsapp
from app.core.config import get_settings
from app.core.dependencies import get_db, get_current_tenant_id, get_current_user_id, require_admin
from app.core.database import init_db
from app.core.cache import get_cache, kanban_cache_key, invalidar_kanban
from app.models import Oportunidade, Lead, Mensagem, Tarefa_FollowUp, RemetenteRole, Usuario, TipoMensagem
from app.workers.imap_worker import imap_polling_loop

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    
    settings = get_settings()
    imap_task = None
    
    if not settings.DISABLE_BACKGROUND_WORKERS:
        imap_task = asyncio.create_task(imap_polling_loop())
        logger.info("Worker IMAP agendado.")
    else:
        logger.warning("Workers em background DESABILITADOS via env.")
    
    yield
    
    if imap_task:
        imap_task.cancel()
        try:
            await imap_task
        except asyncio.CancelledError:
            pass
    
    await get_cache().close()


app = FastAPI(
    title="LeadPulse",
    description="SaaS CRM com IA para PMEs",
    version="0.3.0",
    lifespan=lifespan,
)

# Rotas de API REST
app.include_router(oportunidades.router, prefix="/api")
app.include_router(mensagens.router, prefix="/api")
app.include_router(tarefas.router)
app.include_router(auth.router, prefix="/api")

# Rotas de UI (HTMX)
app.include_router(canais.router)

# Webhooks externos
app.include_router(webhook_whatsapp.router)

BASE_DIR = Path(__file__).resolve().parent

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# Servir arquivos estáticos (logo, imagens, etc)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


@app.exception_handler(StarletteHTTPException)
async def custom_http_exception_handler(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 401:
        if request.url.path.startswith("/api") or request.url.path.startswith("/webhooks"):
            return JSONResponse({"detail": exc.detail}, status_code=401)
        return RedirectResponse(url="/login")
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)


@app.get("/login")
async def login_view(request: Request):
    return templates.TemplateResponse(request, "login.html")


# ─── Rota de informação do link admin (carregada via HTMX na sidebar) ─────────

@app.get("/api/me/admin-link")
async def me_admin_link(
    db: AsyncSession = Depends(get_db),
    user_id: uuid.UUID = Depends(get_current_user_id),
):
    result = await db.execute(select(Usuario).where(Usuario.id == user_id))
    user = result.scalars().first()
    role_val = (user.role if isinstance(user.role, str) else user.role.value) if user else ""
    if role_val != "ADMIN":
        return HTMLResponse("")
    return HTMLResponse(
        '<a href="/admin" target="_blank" class="nav-link" style="color:var(--accent-500);">'
        '<svg fill="none" viewBox="0 0 24 24" stroke="currentColor">'
        '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" '
        'd="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 '
        '2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 '
        '2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 '
        '0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-'
        '1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.'
        '996.608 2.296.07 2.572-1.065z"/>'
        '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/>'
        '</svg>Administração</a>'
    )


# ─── Tarefas ──────────────────────────────────────────────────────────────────

@app.get("/tarefas")
async def tarefas_view(
    request: Request,
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID = Depends(get_current_tenant_id),
):
    """Página de tarefas de follow-up."""
    stmt = (
        select(Tarefa_FollowUp)
        .where(Tarefa_FollowUp.tenant_id == tenant_id)
        .options(joinedload(Tarefa_FollowUp.oportunidade).joinedload(Oportunidade.lead))
        .order_by(Tarefa_FollowUp.data_limite)
    )
    result = await db.execute(stmt)
    tarefas = result.scalars().all()
    now = datetime.now(timezone.utc)
    return templates.TemplateResponse(
        request, "tarefas.html",
        {"tenant_id": str(tenant_id), "tarefas": tarefas, "now": now},
    )


# ─── Admin ────────────────────────────────────────────────────────────────────

@app.get("/admin")
async def admin_view(
    request: Request,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_admin),
    tenant_id: uuid.UUID = Depends(get_current_tenant_id),
):
    result = await db.execute(
        select(Usuario).where(Usuario.tenant_id == tenant_id).order_by(Usuario.nome)
    )
    usuarios = result.scalars().all()
    return templates.TemplateResponse(
        request, "admin.html",
        {"tenant_id": str(tenant_id), "usuarios": usuarios},
    )


@app.get("/ui/admin/modal-novo-usuario")
async def ui_modal_novo_usuario(request: Request, _admin=Depends(require_admin)):
    return templates.TemplateResponse(request, "modal_novo_usuario.html")


@app.post("/admin/usuarios")
async def admin_criar_usuario(
    nome: str = Form(...),
    email: str = Form(...),
    senha: str = Form(...),
    role: str = Form("SALES"),
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_admin),
    tenant_id: uuid.UUID = Depends(get_current_tenant_id),
):
    from app.core.security import get_password_hash
    email_norm = email.strip().lower()
    existing = (await db.execute(select(Usuario).where(Usuario.email == email_norm))).scalars().first()
    if existing:
        raise HTTPException(status_code=400, detail="E-mail já cadastrado no sistema")
    novo = Usuario(
        tenant_id=tenant_id,
        nome=nome.strip(),
        email=email_norm,
        hashed_password=get_password_hash(senha),
        role=role,
    )
    db.add(novo)
    await db.commit()
    return Response(status_code=204, headers={"HX-Refresh": "true"})


@app.delete("/admin/usuarios/{usuario_id}")
async def admin_deletar_usuario(
    usuario_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_admin),
    tenant_id: uuid.UUID = Depends(get_current_tenant_id),
):
    result = await db.execute(
        select(Usuario).where(Usuario.id == usuario_id, Usuario.tenant_id == tenant_id)
    )
    usuario = result.scalars().first()
    if usuario:
        await db.delete(usuario)
        await db.commit()
    return Response(status_code=204, headers={"HX-Refresh": "true"})


# ─── Converter Lead em Cliente ────────────────────────────────────────────────

@app.get("/ui/leads/{lead_id}/modal-converter")
async def ui_modal_converter_lead(
    lead_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID = Depends(get_current_tenant_id),
):
    result = await db.execute(select(Lead).where(Lead.id == lead_id, Lead.tenant_id == tenant_id))
    lead = result.scalars().first()
    if not lead:
        raise HTTPException(404, "Lead não encontrado")
    return templates.TemplateResponse(request, "modal_converter_lead.html", {"lead": lead})


@app.post("/ui/leads/{lead_id}/converter")
async def ui_converter_lead(
    lead_id: uuid.UUID,
    nome_completo: str = Form(...),
    cpf_cnpj: str = Form(""),
    cidade: str = Form(""),
    telefone: str = Form(""),
    email: str = Form(""),
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID = Depends(get_current_tenant_id),
):
    result = await db.execute(select(Lead).where(Lead.id == lead_id, Lead.tenant_id == tenant_id))
    lead = result.scalars().first()
    if not lead:
        raise HTTPException(404, "Lead não encontrado")
    lead.is_cliente = True
    lead.nome_completo = nome_completo.strip()
    lead.cpf_cnpj = cpf_cnpj.strip() or None
    lead.cidade = cidade.strip() or None
    if telefone.strip():
        tel = telefone.strip()
        lead.telefone = tel
        lead.whatsapp_id = tel.replace("+", "").replace(" ", "").replace("-", "") or None
    if email.strip():
        lead.email_principal = email.strip()
    lead.data_conversao = datetime.now(timezone.utc)
    await db.commit()
    return Response(status_code=204, headers={"HX-Refresh": "true"})


# ─── Editar Lead ──────────────────────────────────────────────────────────────

@app.get("/ui/leads/{lead_id}/modal-editar")
async def ui_modal_editar_lead(
    lead_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID = Depends(get_current_tenant_id),
):
    result = await db.execute(select(Lead).where(Lead.id == lead_id, Lead.tenant_id == tenant_id))
    lead = result.scalars().first()
    if not lead:
        raise HTTPException(404, "Lead não encontrado")
    return templates.TemplateResponse(request, "modal_editar_lead.html", {"lead": lead})


@app.put("/ui/leads/{lead_id}")
async def ui_atualizar_lead(
    lead_id: uuid.UUID,
    nome: str = Form(...),
    telefone: str = Form(""),
    email: str = Form(""),
    origem: str = Form(""),
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID = Depends(get_current_tenant_id),
):
    result = await db.execute(select(Lead).where(Lead.id == lead_id, Lead.tenant_id == tenant_id))
    lead = result.scalars().first()
    if not lead:
        raise HTTPException(404, "Lead não encontrado")
    tel = telefone.strip()
    lead.nome = nome.strip()
    lead.telefone = tel or None
    lead.whatsapp_id = tel.replace("+", "").replace(" ", "").replace("-", "") or None
    lead.email_principal = email.strip() or None
    lead.origem = origem.strip() or None
    await db.commit()
    return Response(status_code=204, headers={"HX-Refresh": "true"})


# ─── Simular mensagem recebida (demo) ─────────────────────────────────────────

@app.post("/ui/oportunidades/{oportunidade_id}/simular-mensagem")
async def ui_simular_mensagem(
    oportunidade_id: uuid.UUID,
    request: Request,
    conteudo: str = Form(...),
    canal: str = Form("WHATSAPP"),
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID = Depends(get_current_tenant_id),
):
    """Cria uma mensagem simulada do lead (sem canal real) para fins de demonstração."""
    stmt = select(Oportunidade).where(
        Oportunidade.id == oportunidade_id, Oportunidade.tenant_id == tenant_id
    )
    op = (await db.execute(stmt)).scalars().first()
    if not op:
        raise HTTPException(404, "Oportunidade não encontrada")
    tipo = TipoMensagem.WHATSAPP if canal == "WHATSAPP" else TipoMensagem.EMAIL
    nova_msg = Mensagem(
        tenant_id=tenant_id,
        oportunidade_id=oportunidade_id,
        remetente=RemetenteRole.LEAD,
        tipo=tipo,
        conteudo_texto=conteudo.strip(),
    )
    db.add(nova_msg)
    op.ultima_interacao = datetime.now(timezone.utc)
    await db.commit()
    await invalidar_kanban(tenant_id)
    return await _render_painel_oportunidade(oportunidade_id, request, db, tenant_id)


# ─── Notas rápidas na oportunidade ───────────────────────────────────────────

@app.put("/ui/oportunidades/{oportunidade_id}/notas")
async def ui_salvar_notas(
    oportunidade_id: uuid.UUID,
    notas: str = Form(""),
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID = Depends(get_current_tenant_id),
):
    result = await db.execute(
        select(Oportunidade).where(
            Oportunidade.id == oportunidade_id, Oportunidade.tenant_id == tenant_id
        )
    )
    op = result.scalars().first()
    if op:
        op.notas = notas.strip() or None
        await db.commit()
    return HTMLResponse(
        '<span style="font-size:11px;color:#3F8B5E;font-weight:600;">✓ Salvo</span>'
    )


# ─── Export CSV ───────────────────────────────────────────────────────────────

@app.get("/leads/export.csv")
async def export_leads_csv(
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID = Depends(get_current_tenant_id),
):
    result = await db.execute(
        select(Lead).where(Lead.tenant_id == tenant_id).order_by(Lead.nome)
    )
    leads = result.scalars().all()

    output = io.StringIO()
    w = csv.writer(output)
    w.writerow(["Nome", "Telefone", "WhatsApp ID", "Email", "Origem"])
    for lead in leads:
        w.writerow([lead.nome, lead.telefone or "", lead.whatsapp_id or "",
                    lead.email_principal or "", lead.origem or ""])
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue().encode("utf-8-sig")]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=leads.csv"},
    )


@app.get("/oportunidades/export.csv")
async def export_oportunidades_csv(
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID = Depends(get_current_tenant_id),
):
    result = await db.execute(
        select(Oportunidade)
        .where(Oportunidade.tenant_id == tenant_id)
        .options(joinedload(Oportunidade.lead))
        .order_by(Oportunidade.estagio_funil)
    )
    ops = result.scalars().all()

    output = io.StringIO()
    w = csv.writer(output)
    w.writerow(["Lead", "Estágio", "Valor (R$)", "Temperatura IA", "Status IA", "Última Interação"])
    for op in ops:
        lead_nome = op.lead.nome if op.lead else ""
        ultima = op.ultima_interacao.strftime("%d/%m/%Y %H:%M") if op.ultima_interacao else ""
        w.writerow([
            lead_nome, op.estagio_funil,
            f"{op.valor:.2f}" if op.valor else "0.00",
            op.temperatura_ia or "", op.status_conversa_ia or "", ultima,
        ])
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue().encode("utf-8-sig")]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=oportunidades.csv"},
    )


@app.get("/")
async def kanban_view(
    request: Request,
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID = Depends(get_current_tenant_id),
):
    """Kanban com cache-aside no Redis."""
    settings = get_settings()
    cache = get_cache()
    cache_key = kanban_cache_key(tenant_id)
    
    estagios_padrao = [
        "Prospecção",
        "Qualificação",
        "Proposta",
        "Negociação",
        "Fechado Ganho",
        "Fechado Perdido",
    ]
    
    # Tenta cache primeiro
    cached = await cache.get_json(cache_key)
    if cached is not None:
        return templates.TemplateResponse(
            request, "kanban.html",
            {"estagios": cached, "tenant_id": str(tenant_id), "from_cache": True},
        )
    
    # Cache miss — busca no banco
    stmt = (
        select(Oportunidade)
        .where(Oportunidade.tenant_id == tenant_id)
        .options(joinedload(Oportunidade.lead))
    )
    result = await db.execute(stmt)
    oportunidades_db = result.scalars().all()
    
    # Serializa para algo que cabe no JSON do Redis
    estagios_dict = {estagio: [] for estagio in estagios_padrao}
    for op in oportunidades_db:
        item = {
            "id": str(op.id),
            "valor": op.valor,
            "estagio_funil": op.estagio_funil,
            "temperatura_ia": op.temperatura_ia,
            "status_conversa_ia": op.status_conversa_ia,
            "lead_nome": op.lead.nome if op.lead else "Desconhecido",
        }
        estagios_dict.setdefault(op.estagio_funil, []).append(item)
    
    await cache.set_json(cache_key, estagios_dict, ttl=settings.CACHE_TTL_KANBAN_SECONDS)
    
    return templates.TemplateResponse(
        request, "kanban.html",
        {"estagios": estagios_dict, "tenant_id": str(tenant_id), "from_cache": False},
    )


@app.get("/ui/oportunidades/modal-nova")
async def ui_modal_nova_oportunidade(
    request: Request,
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID = Depends(get_current_tenant_id),
):
    stmt = select(Lead).where(Lead.tenant_id == tenant_id)
    result = await db.execute(stmt)
    leads = result.scalars().all()
    return templates.TemplateResponse(
        request, "modal_nova_oportunidade.html", {"leads": leads}
    )


@app.post("/ui/oportunidades")
async def ui_criar_oportunidade(
    lead_id: uuid.UUID = Form(...),
    valor: float = Form(0.0),
    estagio_funil: str = Form("Prospecção"),
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID = Depends(get_current_tenant_id),
):
    nova_op = Oportunidade(
        tenant_id=tenant_id, lead_id=lead_id, valor=valor, estagio_funil=estagio_funil
    )
    db.add(nova_op)
    await db.commit()
    
    # Invalida cache do Kanban deste tenant
    await invalidar_kanban(tenant_id)
    
    return Response(status_code=204, headers={"HX-Refresh": "true"})


@app.put("/ui/oportunidades/{oportunidade_id}/estagio")
async def ui_atualizar_estagio_oportunidade(
    oportunidade_id: uuid.UUID,
    estagio_funil: str = Form(...),
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID = Depends(get_current_tenant_id),
):
    stmt = select(Oportunidade).where(
        Oportunidade.id == oportunidade_id, Oportunidade.tenant_id == tenant_id
    )
    result = await db.execute(stmt)
    op = result.scalars().first()
    if op:
        op.estagio_funil = estagio_funil
        await db.commit()
        await invalidar_kanban(tenant_id)
    return Response(status_code=204)

async def _render_painel_oportunidade(
    oportunidade_id: uuid.UUID,
    request: Request,
    db: AsyncSession,
    tenant_id: uuid.UUID,
):
    """Helper compartilhado: busca tudo de uma oportunidade e renderiza o painel lateral."""
    stmt = (
        select(Oportunidade)
        .where(Oportunidade.id == oportunidade_id, Oportunidade.tenant_id == tenant_id)
        .options(
            joinedload(Oportunidade.lead),
            joinedload(Oportunidade.mensagens),
            joinedload(Oportunidade.tarefas)
        )
    )
    result = await db.execute(stmt)
    op = result.unique().scalars().first()
    
    if not op:
        raise HTTPException(status_code=404, detail="Oportunidade não encontrada")
        
    mensagens = sorted(op.mensagens, key=lambda m: m.data_envio)
    tarefa_pendente = next((t for t in op.tarefas if t.status == "PENDENTE"), None)
    return templates.TemplateResponse(
        request, "painel_oportunidade.html",
        {"op": op, "mensagens": mensagens, "tarefa": tarefa_pendente},
    )


@app.get("/ui/oportunidades/{oportunidade_id}")
async def ui_painel_oportunidade(
    oportunidade_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID = Depends(get_current_tenant_id),
):
    """Abre o Painel Lateral com histórico de conversa e insights da IA."""
    return await _render_painel_oportunidade(oportunidade_id, request, db, tenant_id)


@app.get("/api/me/info")
async def me_info(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user_id: uuid.UUID = Depends(get_current_user_id),
):
    """Retorna fragmento HTML com informações do usuário logado (para sidebar)."""
    result = await db.execute(select(Usuario).where(Usuario.id == user_id))
    user = result.scalars().first()
    if not user:
        return HTMLResponse('<div class="user-name">Usuário</div><div class="user-role">—</div>')
    initials = "".join(p[0] for p in user.nome.split()[:2]).upper()
    role_label = {"ADMIN": "Administrador", "MANAGER": "Gerente", "SALES": "Vendedor"}.get(
        user.role if isinstance(user.role, str) else user.role.value, "Vendedor"
    )
    return HTMLResponse(
        f'<div class="user-avatar">{initials}</div>'
        f'<div style="flex:1;min-width:0">'
        f'<div class="user-name">{user.nome}</div>'
        f'<div class="user-role">{role_label}</div>'
        f'</div>'
    )


@app.get("/api/tarefas/pendentes/count")
async def tarefas_pendentes_count(
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID = Depends(get_current_tenant_id),
):
    """Retorna contagem de tarefas pendentes (para badge na sidebar)."""
    count = (await db.execute(
        select(func.count(Tarefa_FollowUp.id)).where(
            Tarefa_FollowUp.tenant_id == tenant_id,
            Tarefa_FollowUp.status == "PENDENTE",
        )
    )).scalar() or 0
    if count == 0:
        return HTMLResponse("")
    return HTMLResponse(
        f'<span class="badge badge-quente" style="margin-left:auto;font-size:10px;">{count}</span>'
    )


@app.get("/dashboard")
async def dashboard_view(
    request: Request,
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID = Depends(get_current_tenant_id),
):
    """Dashboard analítico do CRM."""
    total_leads = (await db.execute(
        select(func.count(Lead.id)).where(Lead.tenant_id == tenant_id)
    )).scalar() or 0

    ops_result = await db.execute(
        select(Oportunidade)
        .where(Oportunidade.tenant_id == tenant_id)
        .options(joinedload(Oportunidade.lead))
    )
    todas_ops = ops_result.scalars().all()

    estagios_padrao = ["Prospecção", "Qualificação", "Proposta", "Negociação", "Fechado Ganho", "Fechado Perdido"]
    por_estagio = {e: {"count": 0, "valor": 0.0} for e in estagios_padrao}
    por_temperatura = {"Quente": 0, "Morno": 0, "Frio": 0, "Sem análise": 0}
    valor_pipeline = 0.0

    for op in todas_ops:
        if op.estagio_funil in por_estagio:
            por_estagio[op.estagio_funil]["count"] += 1
            if op.valor:
                por_estagio[op.estagio_funil]["valor"] += op.valor
        if op.estagio_funil not in ["Fechado Ganho", "Fechado Perdido"] and op.valor:
            valor_pipeline += op.valor
        temp = (op.temperatura_ia or "Sem análise").strip().capitalize()
        if temp not in por_temperatura:
            temp = "Sem análise"
        por_temperatura[temp] += 1

    tarefas_result = await db.execute(
        select(Tarefa_FollowUp)
        .where(Tarefa_FollowUp.tenant_id == tenant_id, Tarefa_FollowUp.status == "PENDENTE")
        .options(joinedload(Tarefa_FollowUp.oportunidade).joinedload(Oportunidade.lead))
        .order_by(Tarefa_FollowUp.data_limite)
        .limit(5)
    )
    tarefas_pendentes = tarefas_result.scalars().all()

    total_mensagens = (await db.execute(
        select(func.count(Mensagem.id)).where(Mensagem.tenant_id == tenant_id)
    )).scalar() or 0

    atividade_result = await db.execute(
        select(Mensagem)
        .where(Mensagem.tenant_id == tenant_id)
        .options(joinedload(Mensagem.oportunidade).joinedload(Oportunidade.lead))
        .order_by(Mensagem.data_envio.desc())
        .limit(8)
    )
    atividade_recente = atividade_result.scalars().all()

    fechado_ganho = por_estagio["Fechado Ganho"]["count"]
    total_ops = len(todas_ops)
    taxa_conversao = round(fechado_ganho / total_ops * 100, 1) if total_ops > 0 else 0.0
    ops_ativas = total_ops - por_estagio["Fechado Ganho"]["count"] - por_estagio["Fechado Perdido"]["count"]
    max_count = max((v["count"] for v in por_estagio.values()), default=1) or 1

    return templates.TemplateResponse(
        request, "dashboard.html",
        {
            "tenant_id": str(tenant_id),
            "total_leads": total_leads,
            "total_ops": total_ops,
            "ops_ativas": ops_ativas,
            "valor_pipeline": valor_pipeline,
            "taxa_conversao": taxa_conversao,
            "por_estagio": por_estagio,
            "por_temperatura": por_temperatura,
            "tarefas_pendentes": tarefas_pendentes,
            "atividade_recente": atividade_recente,
            "total_mensagens": total_mensagens,
            "max_count": max_count,
        },
    )


@app.get("/leads")
async def leads_view(
    request: Request,
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID = Depends(get_current_tenant_id),
):
    """Listagem de todos os leads do tenant."""
    stmt = (
        select(Lead)
        .where(Lead.tenant_id == tenant_id)
        .options(joinedload(Lead.oportunidades))
        .order_by(Lead.nome)
    )
    result = await db.execute(stmt)
    leads = result.unique().scalars().all()
    return templates.TemplateResponse(
        request, "leads.html", {"leads": leads, "tenant_id": str(tenant_id)},
    )


@app.get("/ui/leads/modal-novo")
async def ui_modal_novo_lead(request: Request):
    return templates.TemplateResponse(request, "modal_novo_lead.html")


@app.post("/ui/leads")
async def ui_criar_lead(
    nome: str = Form(...),
    telefone: str = Form(""),
    email: str = Form(""),
    origem: str = Form(""),
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID = Depends(get_current_tenant_id),
):
    telefone_limpo = telefone.strip().replace(" ", "").replace("-", "").replace("+", "") if telefone else None
    novo_lead = Lead(
        tenant_id=tenant_id,
        nome=nome.strip(),
        telefone=telefone.strip() or None,
        email_principal=email.strip() or None,
        whatsapp_id=telefone_limpo or None,
        origem=origem.strip() or None,
    )
    db.add(novo_lead)
    await db.commit()
    return Response(status_code=204, headers={"HX-Refresh": "true"})


@app.delete("/ui/leads/{lead_id}")
async def ui_deletar_lead(
    lead_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID = Depends(get_current_tenant_id),
):
    result = await db.execute(
        select(Lead).where(Lead.id == lead_id, Lead.tenant_id == tenant_id)
    )
    lead = result.scalars().first()
    if lead:
        await db.delete(lead)
        await db.commit()
        await invalidar_kanban(tenant_id)
    return Response(status_code=204, headers={"HX-Refresh": "true"})


@app.get("/api/buscar")
async def buscar_global(
    request: Request,
    q: str = "",
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID = Depends(get_current_tenant_id),
):
    """Busca global por nome de lead. Retorna fragmento HTML para HTMX."""
    if not q or len(q.strip()) < 2:
        return HTMLResponse("")

    padrao = f"%{q.strip()}%"

    leads_result = await db.execute(
        select(Lead)
        .where(Lead.tenant_id == tenant_id, Lead.nome.ilike(padrao))
        .limit(6)
    )
    leads = leads_result.scalars().all()

    ops_result = await db.execute(
        select(Oportunidade)
        .where(Oportunidade.tenant_id == tenant_id)
        .join(Lead, Oportunidade.lead_id == Lead.id)
        .where(Lead.nome.ilike(padrao))
        .options(joinedload(Oportunidade.lead))
        .limit(4)
    )
    ops = ops_result.scalars().all()

    if not leads and not ops:
        return HTMLResponse(
            '<div class="search-empty">Nenhum resultado para <strong>' + q + '</strong></div>'
        )

    items_html = ""
    if leads:
        items_html += '<div class="search-group-label">Leads</div>'
        for lead in leads:
            items_html += (
                f'<a href="/leads" class="search-result-item">'
                f'<svg width="12" height="12" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"/></svg>'
                f'<span>{lead.nome}</span>'
                f'<span class="search-result-meta">{lead.telefone or lead.email_principal or ""}</span>'
                f'</a>'
            )
    if ops:
        items_html += '<div class="search-group-label">Oportunidades</div>'
        for op in ops:
            lead_nome = op.lead.nome if op.lead else "—"
            items_html += (
                f'<div class="search-result-item" '
                f'hx-get="/ui/oportunidades/{op.id}" hx-target="#modal-container" '
                f'style="cursor:pointer;">'
                f'<svg width="12" height="12" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6"/></svg>'
                f'<span>{lead_nome}</span>'
                f'<span class="search-result-meta">{op.estagio_funil}</span>'
                f'</div>'
            )

    return HTMLResponse(f'<div class="search-results">{items_html}</div>')


@app.post("/ui/oportunidades/{oportunidade_id}/analisar-ia")
async def ui_analisar_ia(
    oportunidade_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID = Depends(get_current_tenant_id),
):
    """Processa a IA (Groq) no histórico real e gera rascunho de resposta."""
    stmt = (
        select(Oportunidade)
        .where(Oportunidade.id == oportunidade_id, Oportunidade.tenant_id == tenant_id)
        .options(joinedload(Oportunidade.mensagens))
    )
    op = (await db.execute(stmt)).unique().scalars().first()
    
    if not op:
        raise HTTPException(status_code=404, detail="Oportunidade não encontrada")
    
    # Monta histórico para a IA (lead → user, vendedor → assistant)
    historico = []
    for m in sorted(op.mensagens, key=lambda x: x.data_envio):
        role = "user" if m.remetente == RemetenteRole.LEAD else "assistant"
        historico.append({"role": role, "content": m.conteudo_texto})
    
    if not historico:
        raise HTTPException(
            status_code=400,
            detail="Esta oportunidade ainda não tem mensagens para analisar. Aguarde o lead responder."
        )
    
    from app.services.groq_service import analisar_interacao_lead
    try:
        resultado = await analisar_interacao_lead(historico)
    except Exception as e:
        logger.exception(f"Falha inesperada na análise IA: {e}")
        raise HTTPException(status_code=502, detail=f"Erro ao consultar a IA: {str(e)}")
    
    if resultado:
        op.temperatura_ia = resultado.get("temperatura")
        op.status_conversa_ia = resultado.get("status_conversa")
        
        # Apaga tarefas pendentes antigas e cria a nova
        await db.execute(
            delete(Tarefa_FollowUp).where(
                Tarefa_FollowUp.oportunidade_id == op.id,
                Tarefa_FollowUp.tenant_id == tenant_id,
                Tarefa_FollowUp.status == "PENDENTE",
            )
        )
        
        rascunho = resultado.get("rascunho_sugerido")
        if rascunho:
            nova_tarefa = Tarefa_FollowUp(
                tenant_id=tenant_id,
                oportunidade_id=op.id,
                status="PENDENTE",
                data_limite=datetime.now(timezone.utc) + timedelta(hours=24),
                rascunho_sugerido_ia=rascunho,
            )
            db.add(nova_tarefa)
        
        await db.commit()
        await invalidar_kanban(tenant_id)
    
    # Renderiza o painel atualizado (HTMX vai trocar dentro do #modal-container)
    return await _render_painel_oportunidade(oportunidade_id, request, db, tenant_id)
