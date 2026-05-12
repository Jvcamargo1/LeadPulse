import json
import logging
from typing import Dict, Any
from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings

logger = logging.getLogger(__name__)

class CredentialCipher:
    """
    Cifra e decifra credenciais de canais (Z-API, Gmail, etc) usando Fernet (AES-128-CBC + HMAC).
    A chave deve estar em FERNET_KEY no .env. Em produção, use um cofre (AWS Secrets Manager, Vault).
    """
    
    def __init__(self):
        settings = get_settings()
        if not settings.FERNET_KEY:
            raise RuntimeError(
                "FERNET_KEY não configurada. Gere uma com: "
                "python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
            )
        self._fernet = Fernet(settings.FERNET_KEY.encode())
    
    def encrypt(self, data: Dict[str, Any]) -> str:
        """Cifra um dicionário Python e retorna uma string base64."""
        plain = json.dumps(data).encode("utf-8")
        return self._fernet.encrypt(plain).decode("utf-8")
    
    def decrypt(self, token: str) -> Dict[str, Any]:
        """Decifra uma string base64 de volta para um dicionário Python."""
        try:
            plain = self._fernet.decrypt(token.encode("utf-8"))
            return json.loads(plain.decode("utf-8"))
        except InvalidToken:
            logger.error("Token Fernet inválido — credenciais corrompidas ou chave trocada.")
            raise


# Singleton lazy
_cipher_instance: CredentialCipher | None = None

def get_cipher() -> CredentialCipher:
    global _cipher_instance
    if _cipher_instance is None:
        _cipher_instance = CredentialCipher()
    return _cipher_instance
