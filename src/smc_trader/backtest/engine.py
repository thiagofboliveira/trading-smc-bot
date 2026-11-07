from typing import Any, Callable, Literal
import numpy as np
import pandas as pd

from smc_trader.backtest.costs import ExecutionCostsCalculator
from smc_trader.backtest.limits import DailyLimitsTracker
from smc_trader.backtest.metrics import calculate_metrics
from smc_trader.backtest.session import SessionManager
from smc_trader.backtest.trailing import TrailingManager
from smc_trader.backtest.types import BacktestResult, Position, Trade
from smc_trader.config import BacktestConfig
from smc_trader.confluence.evaluator import ConfluenceEvaluator
from smc_trader.confluence.indicators import calculate_ema, calculate_sma
from smc_trader.data.resample import resample_ohlc
from smc_trader.structure.market_structure import detect_structure
from smc_trader.structure.pivots import find_pivots
from smc_trader.zones.orderblock import Zone


class BacktestEngine:
    """Motor de eventos orientado a candles M1 com suporte a OB, FVOB, Breakers, confluências e trailing stop."""

    def __init__(self, config: BacktestConfig) -> None:
        self.config = config
        self.costs_calc = ExecutionCostsCalculator(config.costs)
        self.session_mgr = SessionManager(config.session)
        self.limits_tracker = DailyLimitsTracker(config.limits)
        self.confluence_eval = ConfluenceEvaluator(config.confluence)

    def _prepare_ma_series(
        self, candles_m1: pd.DataFrame, tf: str, kind: str, period: int
    ) -> np.ndarray:
        if tf == "M1":
            s = candles_m1["close"]
            ma = calculate_ema(s, period) if kind == "ema" else calculate_sma(s, period)
            return ma.shift(1).to_numpy()
        else:
            agg = resample_ohlc(candles_m1, tf)
            s = agg["close"]
            ma = calculate_ema(s, period) if kind == "ema" else calculate_sma(s, period)
            # Z-01: o fechamento do bucket só existe após o encerramento do bucket.
            # Aplicar shift(1) na série agregada ANTES do ffill para M1!
            ma_shifted = ma.shift(1).reindex(candles_m1.index, method="ffill")
            return ma_shifted.to_numpy()

    def run(
        self,
        candles_m1: pd.DataFrame,
        zones: list[Zone],
        symbol: str = "XAUUSD",
        confluence_fn: Callable[[Zone, pd.Timestamp, pd.Series], bool] | None = None,
        precomputed_m1: dict[str, Any] | None = None,
    ) -> BacktestResult:
        """Executa a simulação cronológica sobre candles M1."""
        if candles_m1.empty:
            return BacktestResult(
                trades=[], metrics=calculate_metrics([]), config=self.config
            )

        # Z-10: recria limits_tracker a cada execução para não vazar estado entre chamadas
        self.limits_tracker = DailyLimitsTracker(self.config.limits)

        # 1. Estrutura M1 (para confirmação e trailing BOS)
        if precomputed_m1 is not None and "events" in precomputed_m1:
            events_m1 = precomputed_m1["events"]
            m1_chochs = precomputed_m1["chochs"]
            m1_bos = precomputed_m1.get(
                "bos", {(e.direction, e.time): e for e in events_m1 if e.kind == "BOS"}
            )
        else:
            pivots_m1 = find_pivots(candles_m1, k=2)
            events_m1 = detect_structure(candles_m1, pivots_m1)
            m1_chochs = {
                (e.direction, e.time): e for e in events_m1 if e.kind == "CHoCH"
            }
            m1_bos = {(e.direction, e.time): e for e in events_m1 if e.kind == "BOS"}

        # 2. Indicadores de confluência
        c_cfg = self.config.confluence
        if precomputed_m1 is not None and "ema80" in precomputed_m1:
            ema80_vals = precomputed_m1["ema80"] if c_cfg.use_ema80 else None
            sma200_vals = precomputed_m1["sma200"] if c_cfg.use_sma200 else None
        else:
            ema80_vals = (
                self._prepare_ma_series(candles_m1, c_cfg.ma_timeframe, "ema", 80)
                if c_cfg.use_ema80
                else None
            )
            sma200_vals = (
                self._prepare_ma_series(candles_m1, c_cfg.ma_timeframe, "sma", 200)
                if c_cfg.use_sma200
                else None
            )

        # 3. Indicadores de trailing stop
        t_cfg = self.config.trailing
        trailing_ema_vals = (
            self._prepare_ma_series(
                candles_m1, t_cfg.timeframe, "ema", t_cfg.ema_period
            )
            if t_cfg.mode == "ema"
            else None
        )

        closed_trades: list[Trade] = []
        current_pos: Position | None = None
        trailing_mgr: TrailingManager | None = None
        trade_counter = 0

        # Estado de rastreamento de cada zona.
        # Zonas cuja vida terminou (mitigada/invalidada no M15) antes do início da
        # janela simulada já nascem CONSUMED: sem isso, ao simular um recorte
        # (OOS / walk-forward) com zonas detectadas no período inteiro, zonas
        # já mitigadas seriam "tocadas" no 1º candle com o preço além do stop.
        window_start = candles_m1.index[0] if len(candles_m1) else None
        zone_states: dict[tuple[pd.Timestamp, pd.Timestamp], dict[str, Any]] = {
            (z.candle_time, z.created_at): {
                "state": (
                    "CONSUMED"
                    if window_start is not None
                    and z.end_time is not None
                    and z.end_time <= window_start
                    else "UNTOUCHED"
                ),
                "touch_time": None,
            }
            for z in zones
        }
        zones_sorted = sorted(zones, key=lambda z: z.created_at)
        zone_cursor = 0
        active_zones: list[Zone] = []

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

            # Adiciona zonas que nasceram até o momento t
            while (
                zone_cursor < len(zones_sorted)
                and zones_sorted[zone_cursor].created_at <= t
            ):
                active_zones.append(zones_sorted[zone_cursor])
                zone_cursor += 1

            just_closed = False

            # 1. Gerenciamento de posição aberta
            if current_pos is not None:
                long = current_pos.direction == "long"
                sl = current_pos.stop_loss
                tp = current_pos.take_profit

                if long:
                    hit_sl = c_low <= sl
                    hit_tp = (tp is not None) and (c_high >= tp)
                else:
                    hit_sl = c_high >= sl
                    hit_tp = (tp is not None) and (c_low <= tp)

                # Z-04: Stop loss tem prioridade absoluta sobre trailing e sessão
                # Z-03: Gap além do stop sai no c_open
                if hit_sl:
                    nominal_sl = min(c_open, sl) if long else max(c_open, sl)
                    exit_price, exit_cost = self.costs_calc.get_exit_price(
                        current_pos.direction, nominal_sl, symbol
                    )
                    trade = self._create_closed_trade(
                        current_pos, t, exit_price, "sl", exit_cost, trade_counter
                    )
                    trade_counter += 1
                    closed_trades.append(trade)
                    self.limits_tracker.record_trade(t, trade.r_multiple)
                    current_pos = None
                    trailing_mgr = None
                    just_closed = True
                elif hit_tp:
                    assert tp is not None
                    nominal_tp = max(c_open, tp) if long else min(c_open, tp)
                    exit_price, exit_cost = self.costs_calc.get_exit_price(
                        current_pos.direction, nominal_tp, symbol
                    )
                    trade = self._create_closed_trade(
                        current_pos, t, exit_price, "tp", exit_cost, trade_counter
                    )
                    trade_counter += 1
                    closed_trades.append(trade)
                    self.limits_tracker.record_trade(t, trade.r_multiple)
                    current_pos = None
                    trailing_mgr = None
                    just_closed = True
                else:
                    # Avalia trailing stop se ativo
                    trailing_exit = False
                    if trailing_mgr is not None:
                        tr_ema = (
                            trailing_ema_vals[i]
                            if trailing_ema_vals is not None
                            else None
                        )
                        curr_bos = m1_bos.get(
                            ("up" if current_pos.direction == "long" else "down", t)
                        )
                        should_tr_exit, tr_price, tr_reason = (
                            trailing_mgr.check_and_update(
                                current_pos,
                                c_open,
                                c_high,
                                c_low,
                                c_close,
                                t,
                                tr_ema,
                                current_bos=curr_bos,
                            )
                        )
                        if should_tr_exit:
                            trailing_exit = True
                            exit_price, exit_cost = self.costs_calc.get_exit_price(
                                current_pos.direction, tr_price, symbol
                            )
                            trade = self._create_closed_trade(
                                current_pos,
                                t,
                                exit_price,
                                tr_reason or "trailing",
                                exit_cost,
                                trade_counter,
                            )
                            trade_counter += 1
                            closed_trades.append(trade)
                            self.limits_tracker.record_trade(t, trade.r_multiple)
                            current_pos = None
                            trailing_mgr = None
                            just_closed = True

                    # Se não saiu por trailing, verifica fechamento forçado de sessão
                    if not trailing_exit and current_pos is not None:
                        if self.session_mgr.should_force_close(t):
                            exit_price, exit_cost = self.costs_calc.get_exit_price(
                                current_pos.direction, c_close, symbol
                            )
                            trade = self._create_closed_trade(
                                current_pos,
                                t,
                                exit_price,
                                "session_close",
                                exit_cost,
                                trade_counter,
                            )
                            trade_counter += 1
                            closed_trades.append(trade)
                            self.limits_tracker.record_trade(t, trade.r_multiple)
                            current_pos = None
                            trailing_mgr = None
                            just_closed = True

            # 2. Avaliação de novas entradas (se não houver posição aberta e NÃO acabou de fechar uma no mesmo candle - Z-05)
            if current_pos is None and not just_closed:
                allowed_session = self.session_mgr.is_trade_allowed(t)
                allowed_limits = self.limits_tracker.can_trade(t)

                remaining_active: list[Zone] = []
                entered = False

                for zone in active_zones:
                    if entered:
                        remaining_active.append(zone)
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
                                        min(c_open, zone.high)
                                        if long
                                        else max(c_open, zone.low)
                                    )
                                    current_pos = self._open_position(
                                        zone, nominal_entry, t, symbol, "touch"
                                    )
                                    if current_pos is not None:
                                        entered = True
                                        # Z-02: checar stop no candle de entrada
                                        hit_sl_entry = (
                                            (c_low <= current_pos.stop_loss)
                                            if long
                                            else (c_high >= current_pos.stop_loss)
                                        )
                                        if hit_sl_entry:
                                            exit_price, exit_cost = (
                                                self.costs_calc.get_exit_price(
                                                    current_pos.direction,
                                                    current_pos.stop_loss,
                                                    symbol,
                                                )
                                            )
                                            trade = self._create_closed_trade(
                                                current_pos,
                                                t,
                                                exit_price,
                                                "sl",
                                                exit_cost,
                                                trade_counter,
                                            )
                                            trade_counter += 1
                                            closed_trades.append(trade)
                                            self.limits_tracker.record_trade(
                                                t, trade.r_multiple
                                            )
                                            current_pos = None
                                            trailing_mgr = None
                                            just_closed = True
                                        else:
                                            trailing_mgr = TrailingManager(
                                                self.config.trailing,
                                                current_pos.stop_loss,
                                            )
                            elif self.config.entry_mode == "hybrid":
                                # Confluência técnica no momento do toque
                                touch_p = (
                                    min(c_open, zone.high)
                                    if long
                                    else max(c_open, zone.low)
                                )
                                ema80_v = (
                                    ema80_vals[i] if ema80_vals is not None else None
                                )
                                sma200_v = (
                                    sma200_vals[i] if sma200_vals is not None else None
                                )
                                has_confluence = self.confluence_eval.has_confluence(
                                    zone,
                                    touch_price=touch_p,
                                    last_closed_ema80=ema80_v,
                                    last_closed_sma200=sma200_v,
                                )
                                if confluence_fn is not None:
                                    has_confluence = has_confluence or confluence_fn(
                                        zone, t, candles_m1.iloc[i]
                                    )
                                if has_confluence:
                                    z_info["state"] = "CONSUMED"
                                    if allowed_session and allowed_limits:
                                        current_pos = self._open_position(
                                            zone, touch_p, t, symbol, "hybrid"
                                        )
                                        if current_pos is not None:
                                            entered = True
                                            # Z-02: checar stop no candle de entrada
                                            hit_sl_entry = (
                                                (c_low <= current_pos.stop_loss)
                                                if long
                                                else (c_high >= current_pos.stop_loss)
                                            )
                                            if hit_sl_entry:
                                                exit_price, exit_cost = (
                                                    self.costs_calc.get_exit_price(
                                                        current_pos.direction,
                                                        current_pos.stop_loss,
                                                        symbol,
                                                    )
                                                )
                                                trade = self._create_closed_trade(
                                                    current_pos,
                                                    t,
                                                    exit_price,
                                                    "sl",
                                                    exit_cost,
                                                    trade_counter,
                                                )
                                                trade_counter += 1
                                                closed_trades.append(trade)
                                                self.limits_tracker.record_trade(
                                                    t, trade.r_multiple
                                                )
                                                current_pos = None
                                                trailing_mgr = None
                                                just_closed = True
                                            else:
                                                trailing_mgr = TrailingManager(
                                                    self.config.trailing,
                                                    current_pos.stop_loss,
                                                )
                                else:
                                    z_info["state"] = "ARMED"
                                    remaining_active.append(zone)
                            else:
                                # Modo confirmation
                                z_info["state"] = "ARMED"
                                remaining_active.append(zone)
                        else:
                            remaining_active.append(zone)

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
                                    m1_swing = (
                                        choch_event.range_low
                                        if long
                                        else choch_event.range_high
                                    )
                                    current_pos = self._open_position(
                                        zone,
                                        c_close,
                                        t,
                                        symbol,
                                        "confirmation",
                                        m1_swing=m1_swing,
                                    )
                                    if current_pos is not None:
                                        trailing_mgr = TrailingManager(
                                            self.config.trailing, current_pos.stop_loss
                                        )
                                        entered = True
                            else:
                                remaining_active.append(zone)
                        else:
                            remaining_active.append(zone)

                active_zones = remaining_active

        # Ao final do loop, fecha posição residual se houver
        if current_pos is not None:
            t_last = index[-1]
            last_close = float(close[-1])
            exit_price, exit_cost = self.costs_calc.get_exit_price(
                current_pos.direction, last_close, symbol
            )
            trade = self._create_closed_trade(
                current_pos,
                t_last,
                exit_price,
                "session_close",
                exit_cost,
                trade_counter,
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
    ) -> Position | None:
        long = zone.direction == "long"
        entry_price, _ = self.costs_calc.get_entry_price(
            zone.direction, nominal_entry, symbol
        )

        # Stop loss
        if self.config.stop_mode == "m1_swing" and m1_swing is not None:
            stop_loss = m1_swing
        elif self.config.stop_mode == "swing":
            stop_loss = zone.range_low if long else zone.range_high
        else:
            stop_loss = zone.low if long else zone.high

        # Sanidade: preço de execução já além do stop (gap através da zona) não é
        # um setup válido — o stop seria "atingido" com lucro no mesmo candle.
        if (long and entry_price <= stop_loss) or (
            not long and entry_price >= stop_loss
        ):
            return None

        # Z-07: Risco mínimo. Rejeita setups com risco degenerado
        risk = abs(entry_price - stop_loss)
        spread = self.costs_calc.get_spread(symbol)
        min_risk = max(spread * 1.5, 1e-4)
        if risk < min_risk:
            return None

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

        # Z-06: Desconta comissão por lote configurada
        comm = self.config.costs.commission_per_lot
        pnl = pnl - comm
        total_costs = exit_cost + comm

        r_multiple = pnl / pos.initial_risk if pos.initial_risk > 0 else 0.0

        return Trade(
            id=f"trade-{trade_num + 1}",
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
            costs=round(total_costs, 4),
            zone_created_at=pos.zone_created_at,
        )
