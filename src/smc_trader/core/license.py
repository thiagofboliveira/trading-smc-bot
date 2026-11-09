"""Sistema de Licenciamento Offline (SPEC_PRODUTO.md E8-7).

Garante verificação de licença com chave assinada criptograficamente (HMAC-SHA256),
sem envio de dados do usuário para servidores externos (offline-first).
"""

import base64
import hashlib
import hmac
import json
from datetime import datetime, timezone
from typing import Any

# Chave secreta de validação offline padrão da plataforma
_DEFAULT_PLATFORM_SECRET = b"smc_trader_platform_sovereign_offline_key_2026"


def generate_license_key(
    customer_id: str,
    tier: str = "pro",
    valid_until: str = "2027-12-31",
    secret: bytes = _DEFAULT_PLATFORM_SECRET,
) -> str:
    """Gera chave de licença offline assinada no formato <payload_b64>.<sig_hex>."""
    payload = {
        "customer_id": customer_id,
        "tier": tier,
        "valid_until": valid_until,
        "issued_at": datetime.now(timezone.utc).isoformat(),
    }
    raw_json = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    b64_payload = base64.urlsafe_b64encode(raw_json).decode("ascii")

    sig = hmac.new(secret, b64_payload.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{b64_payload}.{sig}"


def verify_license_key(
    key: str,
    secret: bytes = _DEFAULT_PLATFORM_SECRET,
) -> tuple[bool, str, dict[str, Any] | None]:
    """Valida a chave de licença offline.

    Retorna (válido, mensagem_status, dados_payload).
    """
    if not key or "." not in key:
        return False, "Formato de chave inválido", None

    parts = key.strip().split(".")
    if len(parts) != 2:
        return False, "Estrutura de chave incorreta", None

    b64_payload, signature = parts[0], parts[1]

    # Verifica assinatura HMAC
    expected_sig = hmac.new(secret, b64_payload.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected_sig):
        return False, "Assinatura digital da licença inválida ou corrompida", None

    try:
        raw_json = base64.urlsafe_b64decode(b64_payload.encode("ascii")).decode("utf-8")
        payload = json.loads(raw_json)
    except Exception as e:
        return False, f"Falha na decodificação do payload: {e}", None

    valid_until_str = payload.get("valid_until", "")
    try:
        valid_until_dt = datetime.fromisoformat(valid_until_str.replace("Z", "+00:00"))
        if valid_until_dt.tzinfo is None:
            valid_until_dt = valid_until_dt.replace(tzinfo=timezone.utc)
        now_dt = datetime.now(timezone.utc)
        if now_dt > valid_until_dt:
            return False, f"Licença expirada em {valid_until_str}", payload
    except Exception:
        # Se for formato YYYY-MM-DD
        try:
            valid_until_dt = datetime.strptime(valid_until_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            now_dt = datetime.now(timezone.utc)
            if now_dt > valid_until_dt:
                return False, f"Licença expirada em {valid_until_str}", payload
        except Exception as e:
            return False, f"Formato de data de expiração inválido: {e}", payload

    return True, f"Licença ativa ({payload.get('tier', 'standard').upper()}) válida até {valid_until_str}", payload
