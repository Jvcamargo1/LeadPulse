import asyncio
import uuid
from datetime import datetime, timezone, timedelta
from sqlalchemy import delete
from app.core.database import AsyncSessionLocal
from app.models import Tenant, Usuario, UserRole, Lead, Oportunidade, Mensagem, RemetenteRole, TipoMensagem
from app.core.security import get_password_hash

MOCK_TENANT_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")

async def seed_db():
    print("Iniciando a população do banco de dados...")
    
    async with AsyncSessionLocal() as db:
        # 0. Limpa os dados de teste antigos para evitar erro de duplicidade
        await db.execute(delete(Tenant).where(Tenant.id == MOCK_TENANT_ID))
        await db.commit()
        
        # 1. Cria a Empresa (Tenant) com o MOCK_TENANT_ID que já usamos no código
        tenant = Tenant(
            id=MOCK_TENANT_ID,
            nome_empresa="TechCorp SaaS"
        )
        db.add(tenant)
        
        # 2a. Cria o Administrador
        admin = Usuario(
            id=uuid.uuid4(),
            tenant_id=MOCK_TENANT_ID,
            nome="Admin LeadPulse",
            email="admin@leadpulse.com",
            hashed_password=get_password_hash("123456"),
            role=UserRole.ADMIN
        )
        db.add(admin)

        # 2b. Cria um Usuário Vendedor
        vendedor_id = uuid.uuid4()
        vendedor = Usuario(
            id=vendedor_id,
            tenant_id=MOCK_TENANT_ID,
            nome="João Vendedor",
            email="joao@techcorp.com",
            hashed_password=get_password_hash("123456"),
            role=UserRole.SALES
        )
        db.add(vendedor)
        
        # 3. Cria alguns Leads
        lead_1 = Lead(tenant_id=MOCK_TENANT_ID, nome="Maria Silva", telefone="11999999999", origem="Google Ads")
        lead_2 = Lead(tenant_id=MOCK_TENANT_ID, nome="Carlos Oliveira", telefone="11888888888", origem="Indicação")
        lead_3 = Lead(tenant_id=MOCK_TENANT_ID, nome="Ana Costa", telefone="11777777777", origem="LinkedIn")
        db.add_all([lead_1, lead_2, lead_3])
        
        # Precisamos fazer um flush para gerar os IDs dos leads
        await db.flush()
        
        # 4. Cria as Oportunidades em estágios diferentes para o Kanban
        agora = datetime.now(timezone.utc)
        
        op_1 = Oportunidade(
            tenant_id=MOCK_TENANT_ID,
            vendedor_id=vendedor_id,
            lead_id=lead_1.id,
            valor=5500.00,
            estagio_funil="Prospecção",
            temperatura_ia="Frio",
            status_conversa_ia="Aguardando retorno do primeiro contato.",
            ultima_interacao=agora - timedelta(days=2)
        )
        
        op_2 = Oportunidade(
            tenant_id=MOCK_TENANT_ID,
            vendedor_id=vendedor_id,
            lead_id=lead_2.id,
            valor=12400.50,
            estagio_funil="Proposta",
            temperatura_ia="Quente",
            status_conversa_ia="Proposta enviada, lead com dúvidas sobre prazo.",
            ultima_interacao=agora - timedelta(hours=5)
        )
        
        op_3 = Oportunidade(
            tenant_id=MOCK_TENANT_ID,
            vendedor_id=vendedor_id,
            lead_id=lead_3.id,
            valor=3200.00,
            estagio_funil="Negociação",
            temperatura_ia="Morno",
            status_conversa_ia="Pediu desconto de 10% para fechar hoje.",
            ultima_interacao=agora - timedelta(minutes=30)
        )
        
        db.add_all([op_1, op_2, op_3])
        await db.flush() # Importante: gerar o ID das Oportunidades
        
        # 5. Cria algumas mensagens para a oportunidade 2 (Carlos Oliveira)
        msg_1 = Mensagem(tenant_id=MOCK_TENANT_ID, oportunidade_id=op_2.id, remetente=RemetenteRole.VENDEDOR, tipo=TipoMensagem.WHATSAPP, conteudo_texto="Olá Carlos, tudo bem? Conseguiu dar uma olhada na proposta?", data_envio=agora - timedelta(hours=6))
        msg_2 = Mensagem(tenant_id=MOCK_TENANT_ID, oportunidade_id=op_2.id, remetente=RemetenteRole.LEAD, tipo=TipoMensagem.WHATSAPP, conteudo_texto="Oi João! Vi sim. Achei legal, mas o prazo de entrega ficou um pouco apertado pra nós.", data_envio=agora - timedelta(hours=5, minutes=30))
        msg_3 = Mensagem(tenant_id=MOCK_TENANT_ID, oportunidade_id=op_2.id, remetente=RemetenteRole.VENDEDOR, tipo=TipoMensagem.WHATSAPP, conteudo_texto="Entendo perfeitamente. Se eu conseguir adiantar a entrega em 5 dias, fechamos negócio?", data_envio=agora - timedelta(hours=5))
        
        db.add_all([msg_1, msg_2, msg_3])
        
        # Salva tudo no banco
        await db.commit()
        print("Banco de dados populado com sucesso! Atualize seu Kanban.")

if __name__ == "__main__":
    asyncio.run(seed_db())