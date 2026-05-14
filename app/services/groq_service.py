"""
Serviço de análise de conversas via Groq API.

Política de fallback:
- Se GROQ_API_KEY estiver vazia → usa mock (desenvolvimento sem chave)
- Se a API falhar com erro de rede/auth → log claro + mock
- Se a API retornar JSON inválido → log com a resposta original + mock
- Outras exceções inesperadas → propaga para o caller tratar
"""
import os
import json
import logging
from typing import List, Dict, Optional, Any

try:
    from groq import AsyncGroq
except ImportError:
    AsyncGroq = None

from app.core.config import get_settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Você é um assistente de vendas sênior especializado em CRM B2B.
Sua função é analisar conversas entre vendedor e lead e produzir três coisas:

1. **temperatura**: classifique o engajamento do lead. Valores válidos: "Quente", "Morno", "Frio".
   - Quente: demonstra interesse claro, pede preço, pede demo, pergunta sobre prazo de entrega.
   - Morno: responde mas sem urgência, faz perguntas genéricas.
   - Frio: respostas evasivas, demora para responder, ou nunca respondeu.

2. **status_conversa**: um resumo executivo em UMA frase curta (máx 80 caracteres) do estado atual da negociação.

3. **rascunho_sugerido**: a próxima mensagem que o vendedor deveria enviar. Deve ser:
   - Natural, em português brasileiro coloquial mas profissional
   - Direta ao ponto (máx 3 frases)
   - Avançar a negociação (pedir reunião, enviar proposta, etc)
   - Nunca mais formal que o tom do lead

Responda APENAS com um JSON válido, sem markdown, sem explicações adicionais. Exemplo:
{"temperatura": "Quente", "status_conversa": "Lead pediu desconto para fechar hoje.", "rascunho_sugerido": "Oi! Consigo um desconto de 8% se fecharmos até amanhã. Combinado?"}
"""


async def analisar_interacao_lead(
    historico_mensagens: List[Dict[str, str]]
) -> Optional[Dict[str, Any]]:
    """
    Envia o histórico de mensagens para a Groq e retorna uma análise estruturada.
    
    Args:
        historico_mensagens: lista de dicts {"role": "user"|"assistant", "content": "..."}
                             onde "user" = LEAD e "assistant" = VENDEDOR
    
    Returns:
        Dict com keys: temperatura, status_conversa, rascunho_sugerido — ou None se vazio.
    """
    if not historico_mensagens:
        logger.info("Análise IA pulada: histórico vazio.")
        return None
    
    settings = get_settings()
    api_key = settings.GROQ_API_KEY or os.getenv("GROQ_API_KEY")
    
    if not api_key:
        logger.warning("GROQ_API_KEY não configurada — usando mock.")
        return _mock_analise_ia(historico_mensagens)
    
    if AsyncGroq is None:
        logger.warning("Biblioteca 'groq' não instalada — usando mock.")
        return _mock_analise_ia(historico_mensagens)
    
    # Pega só as últimas 10 mensagens para não estourar o contexto
    mensagens_limitadas = historico_mensagens[-10:]
    
    messages_payload = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages_payload.extend(mensagens_limitadas)
    messages_payload.append({
        "role": "user",
        "content": "Com base no histórico acima, retorne o JSON conforme instruído."
    })
    
    try:
        client = AsyncGroq(api_key=api_key)
        completion = await client.chat.completions.create(
            messages=messages_payload,
            model="llama-3.3-70b-versatile",
            temperature=0.3,
            max_tokens=400,
            response_format={"type": "json_object"},
        )
        
        resultado_str = completion.choices[0].message.content
        logger.info(f"Groq retornou {len(resultado_str)} chars.")
        
        try:
            resultado = json.loads(resultado_str)
        except json.JSONDecodeError as e:
            logger.error(f"JSON inválido da Groq: {e}\nResposta: {resultado_str[:200]}")
            return _mock_analise_ia(historico_mensagens)
        
        # Valida que os campos obrigatórios existem
        campos_esperados = {"temperatura", "status_conversa", "rascunho_sugerido"}
        if not campos_esperados.issubset(resultado.keys()):
            logger.error(f"Resposta da Groq sem campos esperados. Recebido: {list(resultado.keys())}")
            return _mock_analise_ia(historico_mensagens)
        
        # Normaliza temperatura (a IA às vezes responde "quente" minúsculo)
        temp = resultado.get("temperatura", "").strip().capitalize()
        if temp not in ("Quente", "Morno", "Frio"):
            temp = "Morno"
        resultado["temperatura"] = temp
        
        return resultado
    
    except Exception as e:
        # Log detalhado para debug
        logger.exception(f"Falha ao chamar Groq API: {type(e).__name__}: {e}")
        # Em dev volta o mock para a interface não quebrar; em prod propaga
        if settings.is_production:
            raise
        logger.warning("Voltando mock da IA em modo desenvolvimento.")
        return _mock_analise_ia(historico_mensagens)


def _mock_analise_ia(historico_mensagens: List[Dict[str, str]]) -> Dict[str, Any]:
    """
    Retorno simulado quando GROQ_API_KEY está ausente ou a API falha (em dev).
    Tenta variar a resposta de forma minimamente inteligente baseada no tamanho do histórico.
    """
    n = len(historico_mensagens)
    
    if n <= 1:
        return {
            "temperatura": "Frio",
            "status_conversa": "Primeiro contato — aguardando resposta do lead.",
            "rascunho_sugerido": "Oi! Tudo bem? Conseguiu dar uma olhada no material que enviei? Posso esclarecer alguma dúvida?",
        }
    elif n <= 3:
        return {
            "temperatura": "Morno",
            "status_conversa": "Lead respondeu mas sem urgência aparente.",
            "rascunho_sugerido": "Bacana! Pra eu te mandar uma proposta certinha, preciso de duas infos rápidas: prazo desejado e volume aproximado. Pode me passar?",
        }
    else:
        return {
            "temperatura": "Quente",
            "status_conversa": "Conversa avançada — lead engajado.",
            "rascunho_sugerido": "Perfeito! Posso te enviar a proposta hoje ainda. Topa uma call amanhã às 14h pra alinharmos os detalhes finais?",
        }
