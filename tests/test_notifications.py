"""Testes dos alertas e integração com Telegram (E4)."""

from pathlib import Path

import pandas as pd

from smc_trader.core.types import Employee, EmployeeStage, SignalRecord
from smc_trader.notifications.signal_card import render_signal_card
from smc_trader.notifications.telegram_bot import TelegramAlertManager, TelegramConfig
from smc_trader.store.database import Database
from smc_trader.store.repository import StoreRepository


def test_render_signal_card(tmp_path: Path):
    """Testa renderização gráfica de card de sinal."""
    # Cria candles
    dt_idx = pd.date_range("2024-01-01 14:00:00", periods=40, freq="15min", tz="UTC")
    df = pd.DataFrame(
        {
            "open": 18000.0,
            "high": 18020.0,
            "low": 17980.0,
            "close": 18010.0,
            "volume": 100.0,
        },
        index=dt_idx,
    )

    out_file = tmp_path / "card_test.png"
    p = render_signal_card(
        df_candles=df,
        entry_price=18010.0,
        stop_loss=17950.0,
        take_profit=18150.0,
        direction="long",
        title="Arthur NAS100",
        out_path=out_file,
    )

    assert p.exists()
    assert p.stat().st_size > 1000  # Imagem PNG gerada com sucesso


def test_telegram_message_and_decision_flow(tmp_path: Path):
    """Testa formatação de texto e idempotência de decisão humana."""
    db = Database(":memory:")
    repo = StoreRepository(db)

    emp = Employee(
        id="arthur-d1-rev",
        name="Arthur (D1 Reversion)",
        strategy_id="d1_mean_reversion",
        symbol="NAS100",
        timeframe="D1",
        stage=EmployeeStage.HIRED,
        avatar="👔",
    )
    repo.add_employee(emp)

    sig = SignalRecord(
        id="sig_test_10",
        employee_id="arthur-d1-rev",
        timestamp="2026-11-09T14:30:00Z",
        direction="long",
        entry_price=18500.0,
        stop_loss=18400.0,
        take_profit=18700.0,
        valid_until="2026-11-09T17:00:00Z",
    )
    repo.record_signal(sig)

    config = TelegramConfig(authorized_chat_ids=[123456], enabled=True)
    mgr = TelegramAlertManager(repo, config)

    # Formatação de mensagem
    msg = mgr.format_signal_message(emp, sig, risk_money=150.0)
    assert "Arthur" in msg
    assert "18,500.00" in msg
    assert "1:2.0" in msg
    assert "COMPRA" in msg

    # Decisão de usuário não autorizado (bloqueado)
    ok_unauth, reason_unauth = mgr.handle_user_decision(
        signal_id="sig_test_10",
        user_id=999999,
        action="enter",
    )
    assert ok_unauth is False
    assert "não autorizado" in reason_unauth

    # Decisão de usuário autorizado
    ok_auth, msg_auth = mgr.handle_user_decision(
        signal_id="sig_test_10",
        user_id=123456,
        action="enter",
    )
    assert ok_auth is True
    assert "confirmada" in msg_auth

    # Idempotência: clique repetido não duplica ordem
    ok_dup, msg_dup = mgr.handle_user_decision(
        signal_id="sig_test_10",
        user_id=123456,
        action="enter",
    )
    assert ok_dup is False
    assert "já registrada" in msg_dup
