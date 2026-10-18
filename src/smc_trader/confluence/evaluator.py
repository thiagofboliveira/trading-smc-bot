import math
from smc_trader.config import ConfluenceConfig
from smc_trader.confluence.fibonacci import calculate_fib_level
from smc_trader.zones.orderblock import Zone


class ConfluenceEvaluator:
    """Avaliador de regras de confluência técnica para POIs SMC."""

    def __init__(self, config: ConfluenceConfig) -> None:
        self.config = config

    def has_confluence(
        self,
        zone: Zone,
        touch_price: float,
        last_closed_ema80: float | None = None,
        last_closed_sma200: float | None = None,
    ) -> bool:
        """Verifica se a zona atende ao número mínimo de regras de confluência ativas."""
        active_matches = 0
        tol = self.config.tolerance
        z_low = zone.low - tol
        z_high = zone.high + tol

        # 1. EMA 80
        if self.config.use_ema80:
            if last_closed_ema80 is not None and not math.isnan(last_closed_ema80):
                if z_low <= last_closed_ema80 <= z_high:
                    active_matches += 1

        # 2. SMA 200
        if self.config.use_sma200:
            if last_closed_sma200 is not None and not math.isnan(last_closed_sma200):
                if z_low <= last_closed_sma200 <= z_high:
                    active_matches += 1

        # 3. Fibonacci 61.8%
        if self.config.use_fib618:
            fib618 = calculate_fib_level(
                zone.direction, zone.range_low, zone.range_high, level=0.618
            )
            if z_low <= fib618 <= z_high:
                active_matches += 1

        # 4. Fibonacci 79.0%
        if self.config.use_fib790:
            fib790 = calculate_fib_level(
                zone.direction, zone.range_low, zone.range_high, level=0.790
            )
            if z_low <= fib790 <= z_high:
                active_matches += 1

        return active_matches >= self.config.min_rules and active_matches > 0
