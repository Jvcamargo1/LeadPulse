"""
Serviço de integração com Z-API (WhatsApp não oficial via QR Code).
Documentação: https://developer.z-api.io/

ATENÇÃO: Z-API conecta o WhatsApp via QR Code, igual o WhatsApp Web.
O Meta pode banir o número a qualquer momento. Use apenas para MVP/POC.
"""
import logging
from typing import Optional, Dict, Any
import httpx

from app.core.crypto import get_cipher
from app.models import CanalComunicacao
from app.services.routing import normalizar_whatsapp

logger = logging.getLogger(__name__)

ZAPI_BASE_URL = "https://api.z-api.io"


def _extrair_credenciais(canal: CanalComunicacao) -> Dict[str, str]:
    """
    Decifra e valida as credenciais do canal Z-API.
    Espera um dict com: {"instance_id": "...", "token": "...", "client_token": "..."}
    O client_token é opcional (algumas contas exigem).
    """
    creds = get_cipher().decrypt(canal.credenciais_cifradas)
    if "instance_id" not in creds or "token" not in creds:
        raise ValueError("Credenciais Z-API inválidas: faltam 'instance_id' ou 'token'.")
    return creds


def _build_url(creds: Dict[str, str], endpoint: str) -> str:
    return f"{ZAPI_BASE_URL}/instances/{creds['instance_id']}/token/{creds['token']}/{endpoint}"


def _build_headers(creds: Dict[str, str]) -> Dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if "client_token" in creds and creds["client_token"]:
        headers["Client-Token"] = creds["client_token"]
    return headers


async def enviar_mensagem_texto(
    canal: CanalComunicacao,
    numero_destino: str,
    texto: str,
) -> Dict[str, Any]:
    """
    Envia uma mensagem de texto via Z-API.
    
    Args:
        canal: Registro do CanalComunicacao com credenciais cifradas
        numero_destino: Número do destinatário (será normalizado para E.164 sem '+')
        texto: Conteúdo da mensagem
    
    Returns:
        Resposta da Z-API (geralmente contém messageId)
    """
    creds = _extrair_credenciais(canal)
    url = _build_url(creds, "send-text")
    
    payload = {
        "phone": normalizar_whatsapp(numero_destino),
        "message": texto,
    }
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(url, json=payload, headers=_build_headers(creds))
        
        if response.status_code >= 400:
            logger.error(f"Z-API erro {response.status_code}: {response.text}")
            response.raise_for_status()
        
        data = response.json()
        logger.info(f"WhatsApp enviado para {payload['phone']}: messageId={data.get('messageId')}")
        return data


async def verificar_status_conexao(canal: CanalComunicacao) -> Dict[str, Any]:
    """
    Verifica se a instância Z-API está conectada ao WhatsApp.
    Útil para diagnóstico — se 'connected' for False, o cliente precisa escanear o QR Code novamente.
    """
    creds = _extrair_credenciais(canal)
    url = _build_url(creds, "status")
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(url, headers=_build_headers(creds))
        response.raise_for_status()
        return response.json()


def parse_webhook_payload(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Normaliza o payload do webhook da Z-API para o formato interno do LeadPulse.
    
    A Z-API envia eventos de diversos tipos (ReceivedCallback, MessageStatusCallback, etc).
    Aqui filtramos APENAS mensagens recebidas (inbound) de texto.
    
    Retorna None se o payload não for uma mensagem de texto recebida válida.
    """
    # Eventos de mensagem recebida têm type=ReceivedCallback e fromMe=false
    if payload.get("type") != "ReceivedCallback":
        return None
    
    if payload.get("fromMe") is True:
        # Mensagem enviada por nós, não pelo lead — ignora
        return None
    
    # Estrutura: {"phone": "5511...", "senderName": "...", "text": {"message": "..."}, "messageId": "..."}
    text_block = payload.get("text") or {}
    conteudo = text_block.get("message")
    
    if not conteudo:
        # Não é mensagem de texto (pode ser imagem, áudio, etc) — fora do escopo do MVP
        logger.info("Webhook Z-API ignorado: mensagem não-textual")
        return None
    
    return {
        "whatsapp_id": payload.get("phone"),
        "nome_remetente": payload.get("senderName"),
        "conteudo": conteudo,
        "id_externo": payload.get("messageId"),
    }
