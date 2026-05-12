"""
Serviço de integração com Gmail via IMAP (leitura) e SMTP (envio).

REQUISITOS DO CLIENTE:
1. Conta Gmail com autenticação em dois fatores ativada
2. Senha de aplicativo gerada em: https://myaccount.google.com/apppasswords
3. IMAP habilitado em: Gmail → Configurações → Encaminhamento e POP/IMAP

Credenciais esperadas (cifradas no banco):
{
    "email": "vendas@empresa.com",
    "app_password": "abcd efgh ijkl mnop"
}
"""
import logging
import email
from email.message import EmailMessage
from email.utils import parseaddr, parsedate_to_datetime
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime

import aioimaplib
import aiosmtplib

from app.core.crypto import get_cipher
from app.models import CanalComunicacao
from app.services.routing import normalizar_email

logger = logging.getLogger(__name__)

IMAP_HOST = "imap.gmail.com"
IMAP_PORT = 993
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587


def _extrair_credenciais(canal: CanalComunicacao) -> Dict[str, str]:
    creds = get_cipher().decrypt(canal.credenciais_cifradas)
    if "email" not in creds or "app_password" not in creds:
        raise ValueError("Credenciais Gmail inválidas: faltam 'email' ou 'app_password'.")
    return creds


# ============================================================
# RECEBIMENTO (IMAP)
# ============================================================

async def buscar_emails_novos(
    canal: CanalComunicacao,
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """
    Conecta ao Gmail via IMAP e busca e-mails novos desde o ultimo_uid_lido do canal.
    
    Returns:
        Tupla (lista_de_emails_normalizados, novo_ultimo_uid).
        Se não houver e-mails novos, retorna ([], None).
    """
    creds = _extrair_credenciais(canal)
    emails_novos: List[Dict[str, Any]] = []
    novo_ultimo_uid: Optional[str] = None
    
    client = aioimaplib.IMAP4_SSL(host=IMAP_HOST, port=IMAP_PORT, timeout=30)
    
    try:
        await client.wait_hello_from_server()
        await client.login(creds["email"], creds["app_password"])
        await client.select("INBOX")
        
        # Busca UIDs em ordem - se já temos um ultimo_uid_lido, busca só os maiores
        if canal.ultimo_uid_lido:
            criterio = f"UID {int(canal.ultimo_uid_lido) + 1}:*"
        else:
            # Primeira execução - busca apenas e-mails não lidos para evitar processar caixa inteira
            criterio = "UNSEEN"
        
        status, data = await client.uid_search(criterio)
        if status != "OK" or not data:
            return [], None
        
        # data[0] é bytes tipo b"1 2 3 4"
        uids_raw = data[0].decode().split() if data[0] else []
        if not uids_raw:
            return [], None
        
        for uid in uids_raw:
            try:
                status, msg_data = await client.uid("fetch", uid, "(RFC822)")
                if status != "OK" or not msg_data or len(msg_data) < 2:
                    continue
                
                raw_email = msg_data[1]
                if isinstance(raw_email, bytes) is False:
                    continue
                
                msg = email.message_from_bytes(raw_email)
                parsed = _parse_email_message(msg, uid)
                if parsed:
                    emails_novos.append(parsed)
                novo_ultimo_uid = uid
            except Exception as e:
                logger.exception(f"Erro processando UID {uid}: {e}")
                continue
        
        await client.logout()
    
    except Exception as e:
        logger.exception(f"Erro IMAP para canal {canal.id}: {e}")
        raise
    
    return emails_novos, novo_ultimo_uid


def _parse_email_message(msg, uid: str) -> Optional[Dict[str, Any]]:
    """
    Extrai os campos relevantes de uma mensagem RFC822.
    Retorna None se a mensagem não tiver corpo de texto.
    """
    from_header = msg.get("From", "")
    nome_remetente, email_remetente = parseaddr(from_header)
    
    if not email_remetente:
        return None
    
    assunto = msg.get("Subject", "(sem assunto)")
    message_id = msg.get("Message-ID", uid)
    
    data_str = msg.get("Date")
    try:
        data_envio = parsedate_to_datetime(data_str) if data_str else None
    except Exception:
        data_envio = None
    
    # Extrai corpo de texto (preferindo text/plain)
    corpo = _extrair_corpo_texto(msg)
    if not corpo:
        return None
    
    return {
        "email_remetente": email_remetente,
        "nome_remetente": nome_remetente or email_remetente.split("@")[0],
        "assunto": assunto,
        "conteudo": corpo,
        "id_externo": message_id,
        "data_envio": data_envio,
        "uid": uid,
    }


def _extrair_corpo_texto(msg) -> Optional[str]:
    """Pega o text/plain da mensagem, ignorando anexos e HTML pesado."""
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition", ""))
            
            if content_type == "text/plain" and "attachment" not in content_disposition:
                try:
                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset() or "utf-8"
                        return payload.decode(charset, errors="replace").strip()
                except Exception:
                    continue
    else:
        if msg.get_content_type() == "text/plain":
            payload = msg.get_payload(decode=True)
            if payload:
                charset = msg.get_content_charset() or "utf-8"
                return payload.decode(charset, errors="replace").strip()
    
    return None


# ============================================================
# ENVIO (SMTP)
# ============================================================

async def enviar_email(
    canal: CanalComunicacao,
    destinatario: str,
    assunto: str,
    corpo_texto: str,
    in_reply_to: Optional[str] = None,
) -> None:
    """
    Envia um e-mail via SMTP do Gmail.
    
    Args:
        canal: CanalComunicacao com credenciais cifradas
        destinatario: e-mail do destinatário
        assunto: assunto da mensagem
        corpo_texto: corpo em texto plano
        in_reply_to: Message-ID original (para manter o thread, opcional)
    """
    creds = _extrair_credenciais(canal)
    
    msg = EmailMessage()
    msg["From"] = creds["email"]
    msg["To"] = normalizar_email(destinatario)
    msg["Subject"] = assunto
    
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = in_reply_to
    
    msg.set_content(corpo_texto)
    
    await aiosmtplib.send(
        msg,
        hostname=SMTP_HOST,
        port=SMTP_PORT,
        start_tls=True,
        username=creds["email"],
        password=creds["app_password"],
        timeout=30,
    )
    
    logger.info(f"E-mail enviado para {destinatario} (assunto: {assunto[:50]})")
