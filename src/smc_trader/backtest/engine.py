from typing import Any, Callable, Literal
import numpy as np
import pandas as pd

from smc_trader.backtest.costs import ExecutionCostsCalculator
from smc_trader.backtest.limits import DailyLimitsTracker
from smc_trader.backtest.metrics import calculate_metrics
from smc_trader.backtest.session import SessionManager
from smc_trader.backtest.types import BacktestResult, Position, Trade
from smc_trader.config import BacktestConfig
from smc_trader.structure.market_structure import detect_structure
from smc_trader.structure.pivots import find_pivots
from smc_trader.zones.orderblock import Zone


class BacktestEngine:
    """Motor de eventos orientado a candles M1 com suporte a OB, FVOB e Breakers."""

    def __init__(self, config: BacktestConfig) -> None:
        self.config = config
        self.costs_calc = ExecutionCostsCalculator(config.costs)
        self.session_mgr = SessionManager(config.session)
        self.limits_tracker = DailyLimitsTracker(config.limits)

    def run(
        self,
        candles_m1: pd.DataFrame,
        zones: list[Zone],
        symbol: str = "XAUUSD",
        confluence_fn: Callable[[Zone, pd.Timestamp, pd.Series], bool] | None = None,
    ) -> BacktestResult:
        """Executa a simulação cronológica sobre candles M1."""
        if candles_m1.empty:
            return BacktestResult(trades=[], metrics=calculate_metrics([]), config=self.config)

        # Pré-computa CHoCH M1 se o modo de entrada envolver confirmação
        m1_chochs: dict[tuple[str, pd.Timestamp], Any] = {}
        if self.config.entry_mode in ("confirmation", "hybrid"):
            pivots_m1 = find_pivots(candles_m1, k=2)
            events_m1 = detect_structure(candles_m1, pivots_m1)
            for e in events_m1:
                if e.kind == "CHoCH":
                    m1_chochs[(e.direction, e.time)] = e

        closed_trades: list[Trade] = []
        current_pos: Position | None = None
        trade_counter = 0

        # Estado de rastreamento de cada zona
        # key: (zone.candle_time, zone.created_at) -> dict com state, touch_time
        zone_states: dict[tuple[pd.Timestamp, pd.Timestamp], dict[str, Any]] = {
            (z.candle_time, z.created_at): {"state": "UNTOUCHED", "touch_time": None}
            for z in zones
        }

        # Arrays numpy para iteração rápida
        index = candles_m1.index
        open_ = candles_m1["open"].to_numpy()
        high = candles_m1["high"].to_numpy()
        low = candles_m1["low"].to_numpy()
        close = candles_m1["close"].to_numpy()
        n = len(candles_m1)

        for i in range(n):
            t = index[i]
            c_open = float(open_[i])
            c_high = float(high[i])
            c_low = float(low[i])
            c_close = float(close[i])

            # 1. Gerenciamento de posição aberta
            if current_pos is not None:
                # Verifica fechamento forçado de sessão
                if self.session_mgr.should_force_close(t):
                    exit_price, exit_cost = self.costs_calc.get_exit_price(
                        current_pos.direction, c_close, symbol
                    )
                    trade = self._create_closed_trade(
                        current_pos, t, exit_price, "session_close", exit_cost, trade_counter
                    )
                    trade_counter += 1
                    closed_trades.append(trade)
                    self.limits_tracker.record_trade(t, trade.r_multiple)
                    current_pos = None
                else:
                    # Avalia Stop Loss e Take Profit
                    long = current_pos.direction == "long"
                    sl = current_pos.stop_loss
                    tp = current_pos.take_profit

                    if long:
                        hit_sl = c_low <= sl
                        hit_tp = (tp is not None) and (c_high >= tp)
                    else:
                        hit_sl = c_high >= sl
                        hit_tp = (tp is not None) and (c_low <= tp)

                    # Regra de ambiguidade intrabar: se ambos atingidos no mesmo candle M1, assume STOP
                    if hit_sl and hit_tp:
                        exit_price, exit_cost = self.costs_calc.get_exit_price(
                            current_pos.direction, sl, symbol
                        )
                        trade = self._create_closed_trade(
                            current_pos, t, exit_price, "sl", exit_cost, trade_counter
                        )
                        trade_counter += 1
                        closed_trades.append(trade)
                        self.limits_tracker.record_trade(t, trade.r_multiple)
                        current_pos = None
                    elif hit_sl:
                        exit_price, exit_cost = self.costs_calc.get_exit_price(
                            current_pos.direction, sl, symbol
                        )
                        trade = self._create_closed_trade(
                            current_pos, t, exit_price, "sl", exit_cost, trade_counter
                        )
                        trade_counter += 1
                        closed_trades.append(trade)
                        self.limits_tracker.record_trade(t, trade.r_multiple)
                        current_pos = None
                    elif hit_tp:
                        assert tp is not None
                        exit_price, exit_cost = self.costs_calc.get_exit_price(
                            current_pos.direction, tp, symbol
                        )
                        trade = self._create_closed_trade(
                            current_pos, t, exit_price, "tp", exit_cost, trade_counter
                        )
                        trade_counter += 1
                        closed_trades.append(trade)
                        self.limits_tracker.record_trade(t, trade.r_multiple)
                        current_pos = None

            # 2. Avaliação de novas entradas (se não houver posição aberta)
            if current_pos is None:
                allowed_session = self.session_mgr.is_trade_allowed(t)
                allowed_limits = self.limits_tracker.can_trade(t)

                for zone in zones:
                    if zone.created_at > t:
                        continue

                    z_key = (zone.candle_time, zone.created_at)
                    z_info = zone_states[z_key]
                    if z_info["state"] == "CONSUMED":
                        continue

                    # Verifica invalidação no M15
                    if zone.end_reason == "invalidated" and zone.end_time is not None:
                        if t >= zone.end_time:
                            z_info["state"] = "CONSUMED"
                            continue

                    long = zone.direction == "long"

                    # Toque inicial
                    if z_info["state"] == "UNTOUCHED":
                        touched = (c_low <= zone.high) if long else (c_high >= zone.low)
                        if touched:
                            z_info["touch_time"] = t
                            if self.config.entry_mode == "touch":
                                # Breaker não aceita toque puro
                                if zone.kind == "BREAKER":
                                    z_info["state"] = "CONSUMED"
                                    continue
                                z_info["state"] = "CONSUMED"
                                if allowed_session and allowed_limits:
                                    nominal_entry = (
                                        min(c_open, zone.high) if long else max(c_open, zone.low)
                                    )
                                    current_pos = self._open_position(
                                        zone, nominal_entry, t, symbol, "touch"
                                    )
                                    break
                            elif self.config.entry_mode == "hybrid":
                                # Confluência no momento do toque
                                has_confluence = False
                                if confluence_fn is not None:
                                    has_confluence = confluence_fn(zone, t, candles_m1.iloc[i])
                                if has_confluence:
                                    z_info["state"] = "CONSUMED"
                                    if allowed_session and allowed_limits:
                                        nominal_entry = (
                                            min(c_open, zone.high)
                                            if long
                                            else max(c_open, zone.low)
                                        )
                                        current_pos = self._open_position(
                                            zone, nominal_entry, t, symbol, "hybrid"
                                        )
                                        break
                                else:
                                    z_info["state"] = "ARMED"
                            else:
                                # Modo confirmation
                                z_info["state"] = "ARMED"

                    # Confirmação após o toque
                    elif z_info["state"] == "ARMED":
                        # Timeout
                        if self.config.confirmation_timeout_minutes is not None:
                            elapsed = (t - z_info["touch_time"]).total_seconds() / 60.0
                            if elapsed > self.config.confirmation_timeout_minutes:
                                z_info["state"] = "CONSUMED"
                                continue

                        # Checa CHoCH M1
                        needed_dir = "up" if long else "down"
                        choch_event = m1_chochs.get((needed_dir, t))
                        if choch_event is not None:
                            # Fechamento do candle do CHoCH deve estar dentro de [zone.low, zone.high]
                            if zone.low <= c_close <= zone.high:
                                z_info["state"] = "CONSUMED"
                                if allowed_session and allowed_limits:
                                    m1_swing = choch_event.range_low if long else choch_event.range_high
                                    current_pos = self._open_position(
                                        zone,
                                        c_close,
                                        t,
                                        symbol,
                                        "confirmation",
                                        m1_swing=m1_swing,
                                    )
                                    break

        # Ao final do loop, fecha posição residual se houver
        if current_pos is not None:
            t_last = index[-1]
            last_close = float(close[-1])
            exit_price, exit_cost = self.costs_calc.get_exit_price(
                current_pos.direction, last_close, symbol
            )
            trade = self._create_closed_trade(
                current_pos, t_last, exit_price, "session_close", exit_cost, trade_counter
            )
            closed_trades.append(trade)

        metrics = calculate_metrics(closed_trades)
        return BacktestResult(trades=closed_trades, metrics=metrics, config=self.config)

    def _open_position(
        self,
        zone: Zone,
        nominal_entry: float,
        t: pd.Timestamp,
        symbol: str,
        entry_mode: Literal["touch", "confirmation", "hybrid"],
        m1_swing: float | None = None,
    ) -> Position:
        long = zone.direction == "long"
        entry_price, _ = self.costs_calc.get_entry_price(zone.direction, nominal_entry, symbol)

        # Stop loss
        if self.config.stop_mode == "m1_swing" and m1_swing is not None:
            stop_loss = m1_swing
        elif self.config.stop_mode == "swing":
            stop_loss = zone.range_low if long else zone.range_high
        else:
            stop_loss = zone.low if long else zone.high

        risk = abs(entry_price - stop_loss)
        if risk == 0:
            risk = 0.0001  # proteção contra divisão por zero

        if self.config.target_mode == "fixed_r":
            take_profit = (
                entry_price + self.config.target_r * risk
                if long
                else entry_price - self.config.target_r * risk
            )
        else:
            take_profit = None

        return Position(
            symbol=symbol,
            direction=zone.direction,
            zone_kind=zone.kind,
            entry_mode=entry_mode,
            entry_time=t,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            initial_risk=risk,
            zone_created_at=zone.created_at,
        )

    def _create_closed_trade(
        self,
        pos: Position,
        exit_time: pd.Timestamp,
        exit_price: float,
        reason: Literal["tp", "sl", "session_close", "trailing"],
        exit_cost: float,
        trade_num: int,
    ) -> Trade:
        long = pos.direction == "long"
        if long:
            pnl = exit_price - pos.entry_price
        else:
            pnl = pos.entry_price - exit_price

        r_multiple = pnl / pos.initial_risk if pos.initial_risk > 0 else 0.0

        return Trade(
            id=f"trade-{trade_num+1}",
            symbol=pos.symbol,
            direction=pos.direction,
            zone_kind=pos.zone_kind,
            entry_mode=pos.entry_mode,
            entry_time=pos.entry_time,
            entry_price=pos.entry_price,
            stop_loss=pos.stop_loss,
            take_profit=pos.take_profit,
            exit_time=exit_time,
            exit_price=exit_price,
            exit_reason=reason,
            r_multiple=round(r_multiple, 3),
            pnl=round(pnl, 4),
            costs=round(exit_cost, 4),
            zone_created_at=pos.zone_created_at,
        )
