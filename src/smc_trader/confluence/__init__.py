"""Módulo de confluências técnicas (Médias Móveis e Fibonacci)."""

from smc_trader.confluence.evaluator import ConfluenceEvaluator
from smc_trader.confluence.fibonacci import calculate_fib_level
from smc_trader.confluence.indicators import calculate_ema, calculate_sma

__all__ = [
    "calculate_ema",
    "calculate_sma",
    "calculate_fib_level",
    "ConfluenceEvaluator",
]
