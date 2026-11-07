"""Persistência de estado operacional e reconciliação com o MetaTrader 5 (L-07).

Garante que o motor possa ser reiniciado sem perder o controle de pernas ativas,
zonas já consumidas e posições abertas na corretora.
"""

import json
import logging
from pathlib import Path
from typing import Any

import pandas as pd

from smc_trader.execution.mt5_interface import BaseMT5Client
from smc_trader.execution.types import LivePosition

logger = logging.getLogger("smc.state_store")


def make_cmd_id(symbol: str, action: str, bar_time: pd.Timestamp) -> str:
    """Gera um ID determinístico e idempotente para evitar ordens duplicadas em retries."""
    ts_str = bar_time.strftime("%Y%m%d%H%M")
    return f"{symbol[:6]}_{action[:3].upper()}_{ts_str}"


class StateStore:
    """Gerenciador de persistência JSON do estado de execução ao vivo."""

    def __init__(self, file_path: Path = Path("data/live_state.json")) -> None:
        self.file_path = file_path
        self.file_path.parent.mkdir(parents=True, exist_ok=True)

    def save(self, data: dict[str, Any]) -> None:
        """Salva o dicionário de estado em disco atomicamente."""
        tmp_path = self.file_path.with_suffix(".tmp")
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            tmp_path.replace(self.file_path)
        except Exception as exc:
            logger.error(f"Erro ao salvar estado operacional em {self.file_path}: {exc}")

    def load(self) -> dict[str, Any]:
        """Carrega o estado salvo ou retorna dict vazio se não existir."""
        if not self.file_path.exists():
            return {}
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as exc:
            logger.error(f"Erro ao ler estado de {self.file_path}: {exc}")
            return {}

    def reconcile_with_broker(
        self,
        client: BaseMT5Client,
        symbol: str,
        magic: int,
        persisted_pos_ticket: int | None = None,
    ) -> LivePosition | None:
        """Reconcilia posições conhecidas pelo motor com posições abertas reais na corretora."""
        try:
            open_positions = client.get_open_positions(symbol=symbol, magic=magic)
        except Exception as exc:
            logger.error(f"[{symbol}] Erro ao consultar posições do MT5 na inicialização: {exc}")
            return None

        if open_positions:
            pos = open_positions[0]
            logger.info(
                f"🔄 [{symbol}] Posição aberta #{pos.ticket} encontrada no MT5 ({pos.direction.upper()} "
                f"{pos.volume} lotes @ {pos.open_price}). Reconciliando monitoramento ativo."
            )
            return pos

        if persisted_pos_ticket is not None:
            logger.info(
                f"ℹ️ [{symbol}] Posição #{persisted_pos_ticket} constava em disco, mas já foi encerrada no MT5."
            )

        return None
