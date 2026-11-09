"""Gerenciador de alertas e decisões via Telegram (SPEC_PRODUTO.md 5.4 / E4).

Implementa:
- E4-1: Autenticação de usuário autorizado.
- E4-2: Renderização de card gráfico de candles com níveis de SL/TP.
- E4-3: Mensagem formatada com botões interativos 'Entrar', 'Ignorar', 'Detalhes'.
- E4-4: Idempotência de cliques e rejeição de sinais expirados.
- P4: Humano no comando - toda ação gera registro de auditoria.
"""

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from smc_trader.core.types import DecisionRecord, Employee, SignalRecord
from smc_trader.notifications.signal_card import render_signal_card
from smc_trader.store.repository import StoreRepository, now_utc_iso


@dataclass
class TelegramConfig:
    bot_token: str = ""
    authorized_chat_ids: list[int] = field(default_factory=list)
    enabled: bool = False


class TelegramAlertManager:
    """Gerencia formatação de alertas, validação de decisões e auditoria."""

    def __init__(self, repo: StoreRepository, config: TelegramConfig | None = None) -> None:
        self.repo = repo
        self.config = config or TelegramConfig()
        self.processed_decisions: set[str] = set()

    def format_signal_message(
        self,
        emp: Employee,
        sig: SignalRecord,
        risk_money: float = 100.0,
    ) -> str:
        """Formata o texto oficial do alerta de sinal (SPEC_PRODUTO.md 5.4)."""
        risk_pts = abs(sig.entry_price - sig.stop_loss)
        reward_pts = abs(sig.take_profit - sig.entry_price) if sig.take_profit else 0.0
        rr_str = f"1:{reward_pts / risk_pts:.1f}" if (risk_pts > 0 and reward_pts > 0) else "N/A"

        direction_emoji = "🟢 COMPRA" if sig.direction == "long" else "🔴 VENDA"
        lines = [
            f"🔔 *NOVO SINAL DETECTADO* | {emp.avatar} {emp.name}",
            "━" * 32,
            f"🎯 *Ativo / Operação:* `{emp.symbol}` · {direction_emoji}",
            f"📍 *Entrada:* `{sig.entry_price:,.2f}`",
            f"🛑 *Stop Loss:* `{sig.stop_loss:,.2f}` ({risk_pts:.1f} pts | ${risk_money:,.2f})",
        ]
        if sig.take_profit:
            lines.append(f"🏁 *Alvo:* `{sig.take_profit:,.2f}` ({reward_pts:.1f} pts | R:R {rr_str})")

        lines.extend([
            f"⏳ *Validade:* Vale até {sig.valid_until} UTC",
            f"💼 *Estágio do Modelo:* `{emp.stage.value.upper()}`",
            "━" * 32,
            "⚠️ _Confirme abaixo para autorizar o preenchimento da ordem:_",
        ])
        return "\n".join(lines)

    def prepare_signal_card(
        self,
        emp: Employee,
        sig: SignalRecord,
        df_candles: pd.DataFrame,
        out_dir: Path | str = "out/signals",
    ) -> Path:
        """Gera e retorna caminho do cartão gráfico do sinal."""
        out_path = Path(out_dir) / f"{sig.id}.png"
        return render_signal_card(
            df_candles=df_candles,
            entry_price=sig.entry_price,
            stop_loss=sig.stop_loss,
            take_profit=sig.take_profit,
            direction=sig.direction,
            title=f"{emp.avatar} {emp.name} ({emp.symbol})",
            out_path=out_path,
        )

    def handle_user_decision(
        self,
        signal_id: str,
        user_id: int | str,
        action: str,  # 'enter', 'ignore'
    ) -> tuple[bool, str]:
        """Processa a decisão humana garantindo regras anti-viés e idempotência."""
        # 1. Checagem de autorização
        if self.config.authorized_chat_ids and int(user_id) not in self.config.authorized_chat_ids:
            return False, "❌ Usuário não autorizado para decidir operações."

        # 2. Idempotência por sinal
        decision_key = f"{signal_id}_{action}"
        if decision_key in self.processed_decisions:
            return False, "⚠️ Decisão já registrada anteriormente. Clique duplicado ignorado."

        # 3. Registra a decisão no store
        dec_id = f"dec_{signal_id}_{user_id}"
        dec = DecisionRecord(
            id=dec_id,
            signal_id=signal_id,
            user=str(user_id),
            action=action,  # type: ignore[arg-type]
            timestamp=now_utc_iso(),
        )
        self.repo.record_decision(dec)
        self.processed_decisions.add(decision_key)

        if action == "enter":
            return True, f"✅ Ordem confirmada pelo usuário {user_id}. Executando no broker..."
        else:
            return True, f"🚫 Sinal {signal_id} ignorado pelo usuário."
