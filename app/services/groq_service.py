import os
import json
import logging
from typing import List, Dict, Any, Optional

try:
    from groq import AsyncGroq
except ImportError:
    # Fallback/Mock caso a biblioteca groq não esteja instalada no ambiente ainda
    AsyncGroq = None

logger = logging.getLogger(__name__)

# Configuração da API Key (Idealmente vindo de app.core.config no futuro)
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

async def analisar_interacao_lead(historico_mensagens: List[Dict[str, str]]) -> Optional[Dict[str, Any]]:
    """
    Analisa o histórico de mensagens de uma oportunidade utilizando o Llama 3 via Groq API.
    
    Args:
        historico_mensagens: Lista de dicionários no formato [{"role": "user"|"assistant", "content": "..."}]
                             representando a conversa entre o Lead ("user") e o Vendedor ("assistant").
                             
    Returns:
        Um dicionário contendo a 'temperatura' (Quente, Morno, Frio), 
        um 'status_conversa_ia' (resumo curto) e um 'rascunho_sugerido_ia'.
        Retorna None se houver falha na API.
    """
    if not GROQ_API_KEY:
        logger.warning("GROQ_API_KEY não configurada. Usando mock do serviço de IA.")
        return _mock_analise_ia(historico_mensagens)

    if AsyncGroq is None:
        logger.warning("Biblioteca 'groq' não instalada. Usando mock do serviço de IA. Instale com: pip install groq")
        return _mock_analise_ia(historico_mensagens)

    client = AsyncGroq(api_key=GROQ_API_KEY)
    
    # Prompt de Sistema (System Prompt) definindo a persona e as regras de saída
    system_prompt = """
    Você é um assistente de vendas especialista e estrategista de CRM.
    Sua tarefa é analisar o histórico de conversa entre um Lead (cliente potencial) e um Vendedor.
    
    Baseado na interação, você deve determinar:
    1. A 'temperatura' do Lead: Escolha EXATAMENTE entre 'Quente' (pronto para comprar/muito interessado), 'Morno' (interessado mas com dúvidas) ou 'Frio' (sem interesse no momento/não responde adequadamente).
    2. O 'status_conversa': Uma frase curta (máx 10 palavras) resumindo o momento atual da negociação.
    3. Um 'rascunho_sugerido': Uma sugestão de próxima mensagem que o Vendedor deve enviar para avançar no funil de vendas. Seja persuasivo, empático e direto.
    
    Você DEVE retornar APENAS um objeto JSON válido. Nenhuma outra palavra fora do JSON.
    Formato esperado:
    {
        "temperatura": "Quente" | "Morno" | "Frio",
        "status_conversa": "string",
        "rascunho_sugerido": "string"
    }
    """

    # Montamos as mensagens para a API
    messages = [{"role": "system", "content": system_prompt}]
    
    # Adicionamos o histórico garantindo que apenas 'user' ou 'assistant' sejam passados
    # No nosso contexto do BD (remetente), mapearemos Lead -> user, Vendedor -> assistant antes de chamar o serviço.
    messages.extend(historico_mensagens)

    try:
        response = await client.chat.completions.create(
            messages=messages,
            model="llama3-8b-8192", # Modelo otimizado para tarefas rápidas e JSON
            response_format={"type": "json_object"}, # Força o retorno em JSON nativamente
            temperature=0.3, # Temperatura baixa para respostas mais determinísticas e consistentes com JSON
            max_tokens=500
        )
        
        resultado_str = response.choices[0].message.content
        resultado_json = json.loads(resultado_str)
        
        return resultado_json
        
    except json.JSONDecodeError as e:
        logger.error(f"Erro ao decodificar JSON da Groq API: {str(e)}\nResposta original: {resultado_str}")
        return None
    except Exception as e:
        logger.error(f"Erro na comunicação com a Groq API: {str(e)}")
        return None

def _mock_analise_ia(historico_mensagens: List[Dict[str, str]]) -> Dict[str, Any]:
    """Retorno simulado para ambientes de desenvolvimento sem API Key."""
    return {
        "temperatura": "Morno",
        "status_conversa": "Lead aguardando proposta formal.",
        "rascunho_sugerido": "Olá! Conforme conversamos, segue a nossa proposta detalhada. Podemos agendar uma call rápida amanhã às 14h para repassarmos os detalhes?"
    }
