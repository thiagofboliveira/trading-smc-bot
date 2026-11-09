"""Módulo de alertas, notificações e integração Telegram (Fase E4)."""

from smc_trader.notifications.signal_card import render_signal_card
from smc_trader.notifications.telegram_bot import TelegramAlertManager, TelegramConfig

__all__ = ["TelegramAlertManager", "TelegramConfig", "render_signal_card"]
