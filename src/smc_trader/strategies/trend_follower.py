"""Estratégia de Super Tendência Intraday com Gatilhos Modulares nos Índices.

Arquitetura Modular:
1. Filtro Macro Causal em i-1:
   - Alinhamento de MME 80 e MME 200 (Long: close > MME80 > MME200; Short: close < MME80 < MME200)
   - Força direcional com ADX(14) >= 25
   - Inclinação angular normalizada da MME 80 por ATR(14) em 10 barras
2. Filtro de Sessão:
   - Foco no miolo de liquidez de Nova York (13:00 - 17:30 UTC)
3. Gatilhos Modulares Selecionáveis:
   - "trap": Falso rompimento da barra anterior na MME 8
   - "force_bar": Barra de Força / Ponto Contínuo com fechamento no terço extremo
   - "engulfing": Engolfo na zona da média
   - "inside_bar": Inside bar na zona da média
4. Modos de Execução:
   - "independent": cada gatilho opera uma posição independente
   - "single_position": apenas 1 trade ativo por ativo por vez
5. Condução:
   - Saída causal por fechamento além da média (MME 20 ou MME 8) executada no open da barra seguinte
   - Stop loss fixo no extremo do candle de sinal
"""

from dataclasses import dataclass
from typing import Any, Literal
import numpy as np
import pandas as pd


@dataclass
class TrendFollowerConfig:
    timeframe: str = "15min"
    triggers: list[Literal["trap", "force_bar", "engulfing", "inside_bar"]] = (
        None  # default: ["trap", "force_bar", "engulfing"]
    )
    execution_mode: Literal["independent", "single_position"] = "independent"
    conduction_ma: Literal["mme20", "mme8", "mma9"] = "mme20"
    session_start_utc: str = "13:00"
    session_end_utc: str = "17:30"
    use_session_filter: bool = True
    adx_period: int = 14
    adx_min: float = 25.0
    ema_fast: int = 80
    ema_slow: int = 200
    slope_min: float = 0.10
    slope_max: float = 1.00
    slippage_pts: float = 0.0  # Slippage em pontos para ordens stop (rompimento e stop loss)

    def __post_init__(self):
        if self.triggers is None:
            self.triggers = ["trap", "force_bar", "engulfing"]


@dataclass
class TrendTrade:
    symbol: str
    setup_name: str
    direction: Literal["long", "short"]
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    entry_price: float
    stop_price: float
    exit_price: float
    exit_reason: str
    r_multiple: float
    win: bool


class TrendFollowerStrategy:
    """Implementação causal da estratégia seguidora de tendência."""

    def __init__(self, config: TrendFollowerConfig | None = None) -> None:
        self.config = config or TrendFollowerConfig()

    @staticmethod
    def calculate_indicators(df: pd.DataFrame) -> dict[str, np.ndarray]:
        """Calcula indicadores técnicos necessários em arrays numpy."""
        close = df["close"]
        high = df["high"]
        low = df["low"]

        mme8 = close.ewm(span=8, adjust=False).mean().to_numpy(dtype=float)
        mma9 = close.rolling(window=9).mean().to_numpy(dtype=float)
        mme20 = close.ewm(span=20, adjust=False).mean().to_numpy(dtype=float)
        mme80 = close.ewm(span=80, adjust=False).mean().to_numpy(dtype=float)
        mme200 = close.ewm(span=200, adjust=False).mean().to_numpy(dtype=float)

        # ATR(14)
        tr1 = high - low
        tr2 = (high - close.shift(1)).abs()
        tr3 = (low - close.shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(window=14).mean()

        # ADX(14)
        up_move = high - high.shift(1)
        down_move = low.shift(1) - low
        plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
        tr_s = tr.rolling(window=14).sum()
        plus_di = 100 * (pd.Series(plus_dm, index=df.index).rolling(window=14).sum() / tr_s)
        minus_di = 100 * (pd.Series(minus_dm, index=df.index).rolling(window=14).sum() / tr_s)
        dx = 100 * ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan))
        adx14 = dx.rolling(window=14).mean().fillna(0).to_numpy(dtype=float)

        # Slope normalizado da MME 80 em 10 barras
        slope80 = (
            (close.ewm(span=80, adjust=False).mean() - close.ewm(span=80, adjust=False).mean().shift(10))
            / (10 * atr.replace(0, np.nan))
        ).fillna(0).to_numpy(dtype=float)

        return {
            "mme8": mme8,
            "mma9": mma9,
            "mme20": mme20,
            "mme80": mme80,
            "mme200": mme200,
            "adx14": adx14,
            "slope80": slope80,
        }

    def run_simulation(
        self,
        df: pd.DataFrame,
        symbol: str,
        spread: float,
    ) -> list[TrendTrade]:
        """Executa a simulação em um dataframe OHLC resampleado."""
        n = len(df)
        if n < 220:
            return []

        cfg = self.config
        ind = self.calculate_indicators(df)

        opens = df["open"].to_numpy(dtype=float)
        highs = df["high"].to_numpy(dtype=float)
        lows = df["low"].to_numpy(dtype=float)
        closes = df["close"].to_numpy(dtype=float)
        ts = df.index
        time_vals = (df.index.hour * 60 + df.index.minute).to_numpy(dtype=np.int32)

        mme8 = ind["mme8"]
        mme20 = ind["mme20"]
        mme80 = ind["mme80"]
        mme200 = ind["mme200"]
        adx = ind["adx14"]
        slope80 = ind["slope80"]

        if cfg.conduction_ma == "mme20":
            ma_cond = mme20
        elif cfg.conduction_ma == "mma9":
            ma_cond = ind["mma9"]
        else:
            ma_cond = mme8

        # Janela de sessão
        if cfg.use_session_filter:
            sh, sm = map(int, cfg.session_start_utc.split(":"))
            eh, em = map(int, cfg.session_end_utc.split(":"))
            t_start = sh * 60 + sm
            t_end = eh * 60 + em
        else:
            t_start = 0
            t_end = 24 * 60

        triggers = cfg.triggers
        trades: list[TrendTrade] = []

        if cfg.execution_mode == "independent":
            # Cada gatilho roda de forma isolada
            for setup_id in triggers:
                tr_sub = self._run_single_setup_loop(
                    setup_id=setup_id,
                    opens=opens,
                    highs=highs,
                    lows=lows,
                    closes=closes,
                    time_vals=time_vals,
                    ts=ts,
                    mme8=mme8,
                    mme20=mme20,
                    mme80=mme80,
                    mme200=mme200,
                    adx=adx,
                    slope80=slope80,
                    ma_cond=ma_cond,
                    symbol=symbol,
                    spread=spread,
                    t_start=t_start,
                    t_end=t_end,
                )
                trades.extend(tr_sub)
            trades.sort(key=lambda t: t.exit_time)
            return trades

        else:
            # Modo "single_position" (apenas 1 trade ativo por vez)
            return self._run_unified_single_position(
                triggers=triggers,
                opens=opens,
                highs=highs,
                lows=lows,
                closes=closes,
                time_vals=time_vals,
                ts=ts,
                mme8=mme8,
                mme20=mme20,
                mme80=mme80,
                mme200=mme200,
                adx=adx,
                slope80=slope80,
                ma_cond=ma_cond,
                symbol=symbol,
                spread=spread,
                t_start=t_start,
                t_end=t_end,
            )

    def _run_single_setup_loop(
        self,
        setup_id: str,
        opens: np.ndarray,
        highs: np.ndarray,
        lows: np.ndarray,
        closes: np.ndarray,
        time_vals: np.ndarray,
        ts: pd.DatetimeIndex,
        mme8: np.ndarray,
        mme20: np.ndarray,
        mme80: np.ndarray,
        mme200: np.ndarray,
        adx: np.ndarray,
        slope80: np.ndarray,
        ma_cond: np.ndarray,
        symbol: str,
        spread: float,
        t_start: int,
        t_end: int,
    ) -> list[TrendTrade]:
        n = len(opens)
        trades: list[TrendTrade] = []
        open_pos: dict[str, Any] | None = None
        pending_order: dict[str, Any] | None = None

        for i in range(210, n - 1):
            # 1. Posição Aberta
            if open_pos is not None:
                pos = open_pos
                d = 1 if pos["direction"] == "long" else -1
                hit_sl = False
                exit_by_ma = False

                if d == 1:
                    if lows[i] <= pos["stop_price"]:
                        hit_sl = True
                else:
                    if highs[i] + spread >= pos["stop_price"]:
                        hit_sl = True

                # Saída Causal por Média Móvel
                if i > pos["entry_idx"]:
                    if d == 1 and closes[i] < ma_cond[i]:
                        exit_by_ma = True
                    elif d == -1 and closes[i] > ma_cond[i]:
                        exit_by_ma = True

                if hit_sl:
                    if d == 1:
                        raw_exit = min(pos["stop_price"], opens[i])
                        exit_price = raw_exit - self.config.slippage_pts
                        r = (exit_price - pos["entry_price"]) / pos["initial_risk"]
                    else:
                        raw_exit = max(pos["stop_price"], opens[i] + spread)
                        exit_price = raw_exit + self.config.slippage_pts
                        r = (pos["entry_price"] - exit_price) / pos["initial_risk"]

                    trades.append(
                        TrendTrade(
                            symbol=symbol,
                            setup_name=setup_id.upper(),
                            direction=pos["direction"],
                            entry_time=pos["entry_time"],
                            exit_time=ts[i],
                            entry_price=pos["entry_price"],
                            stop_price=pos["stop_price"],
                            exit_price=exit_price,
                            exit_reason="STOP_LOSS",
                            r_multiple=float(r),
                            win=bool(r > 0),
                        )
                    )
                    open_pos = None
                    pending_order = None
                    continue

                elif exit_by_ma and i < n - 1:
                    exit_price = opens[i + 1] if d == 1 else opens[i + 1] + spread
                    r = (
                        (exit_price - pos["entry_price"]) / pos["initial_risk"]
                        if d == 1
                        else (pos["entry_price"] - exit_price) / pos["initial_risk"]
                    )
                    trades.append(
                        TrendTrade(
                            symbol=symbol,
                            setup_name=setup_id.upper(),
                            direction=pos["direction"],
                            entry_time=pos["entry_time"],
                            exit_time=ts[i + 1],
                            entry_price=pos["entry_price"],
                            stop_price=pos["stop_price"],
                            exit_price=exit_price,
                            exit_reason="TRAILING_MA",
                            r_multiple=float(r),
                            win=bool(r > 0),
                        )
                    )
                    open_pos = None
                    pending_order = None
                    continue

            # 2. Ordem Armada
            if pending_order is not None and open_pos is None:
                po = pending_order
                d = 1 if po["direction"] == "long" else -1
                triggered = False
                exec_price = 0.0

                if d == 1:
                    if highs[i] >= po["trigger_price"]:
                        triggered = True
                        exec_price = max(opens[i], po["trigger_price"]) + spread + self.config.slippage_pts
                else:
                    if lows[i] <= po["trigger_price"]:
                        triggered = True
                        exec_price = min(opens[i], po["trigger_price"]) - self.config.slippage_pts

                if triggered:
                    risk = abs(exec_price - po["stop_price"])
                    if risk > 0:
                        # Checagem obrigatória anti-viés: stop na barra de entrada
                        entry_stopped = False
                        if d == 1:
                            if lows[i] <= po["stop_price"]:
                                entry_stopped = True
                                raw_exit = min(po["stop_price"], opens[i])
                                exit_price = raw_exit - self.config.slippage_pts
                                r = (exit_price - exec_price) / risk
                        else:
                            if highs[i] + spread >= po["stop_price"]:
                                entry_stopped = True
                                raw_exit = max(po["stop_price"], opens[i] + spread)
                                exit_price = raw_exit + self.config.slippage_pts
                                r = (exec_price - exit_price) / risk

                        if entry_stopped:
                            trades.append(
                                TrendTrade(
                                    symbol=symbol,
                                    setup_name=setup_id.upper(),
                                    direction=po["direction"],
                                    entry_time=ts[i],
                                    exit_time=ts[i],
                                    entry_price=exec_price,
                                    stop_price=po["stop_price"],
                                    exit_price=exit_price,
                                    exit_reason="STOP_LOSS_ENTRY_BAR",
                                    r_multiple=float(r),
                                    win=bool(r > 0),
                                )
                            )
                            open_pos = None
                            pending_order = None
                            continue
                        else:
                            open_pos = {
                                "direction": po["direction"],
                                "entry_idx": i,
                                "entry_time": ts[i],
                                "entry_price": exec_price,
                                "stop_price": po["stop_price"],
                                "initial_risk": risk,
                            }
                    pending_order = None
                    continue
                else:
                    pending_order = None

            # 3. Identificar Sinal
            if open_pos is None and pending_order is None:
                if not (t_start <= time_vals[i] <= t_end):
                    continue

                strong_trend = adx[i - 1] >= self.config.adx_min
                bullish_macro = closes[i - 1] > mme80[i - 1] > mme200[i - 1]
                bearish_macro = closes[i - 1] < mme80[i - 1] < mme200[i - 1]
                slope_bullish = self.config.slope_min <= slope80[i - 1] <= self.config.slope_max
                slope_bearish = -self.config.slope_max <= slope80[i - 1] <= -self.config.slope_min

                c_range = highs[i] - lows[i]
                if c_range <= 0 or not strong_trend:
                    continue

                if setup_id == "trap":
                    if bullish_macro and slope_bullish:
                        touched = lows[i] <= mme8[i] * 1.001
                        trap = (lows[i] < lows[i - 1]) and (closes[i] > lows[i - 1]) and (closes[i] > opens[i])
                        if touched and trap:
                            pending_order = {"direction": "long", "trigger_price": highs[i], "stop_price": lows[i]}
                    elif bearish_macro and slope_bearish:
                        touched = highs[i] >= mme8[i] * 0.999
                        trap = (highs[i] > highs[i - 1]) and (closes[i] < highs[i - 1]) and (closes[i] < opens[i])
                        if touched and trap:
                            pending_order = {"direction": "short", "trigger_price": lows[i], "stop_price": highs[i] + spread}

                elif setup_id == "force_bar":
                    if bullish_macro and slope_bullish:
                        touched = lows[i] <= max(mme8[i], mme20[i]) * 1.001
                        force = (closes[i] > opens[i]) and ((closes[i] - lows[i]) / c_range >= 0.70) and (closes[i] > mme8[i])
                        if touched and force:
                            pending_order = {"direction": "long", "trigger_price": highs[i], "stop_price": lows[i]}
                    elif bearish_macro and slope_bearish:
                        touched = highs[i] >= min(mme8[i], mme20[i]) * 0.999
                        force = (closes[i] < opens[i]) and ((highs[i] - closes[i]) / c_range >= 0.70) and (closes[i] < mme8[i])
                        if touched and force:
                            pending_order = {"direction": "short", "trigger_price": lows[i], "stop_price": highs[i] + spread}

                elif setup_id == "engulfing":
                    if bullish_macro and slope_bullish:
                        touched = lows[i] <= max(mme8[i], mme20[i]) * 1.001
                        prev_bear = closes[i - 1] < opens[i - 1]
                        engulf = (closes[i] > opens[i]) and (closes[i] >= opens[i - 1]) and (opens[i] <= closes[i - 1])
                        if touched and prev_bear and engulf:
                            pending_order = {"direction": "long", "trigger_price": highs[i], "stop_price": lows[i]}
                    elif bearish_macro and slope_bearish:
                        touched = highs[i] >= min(mme8[i], mme20[i]) * 0.999
                        prev_bull = closes[i - 1] > opens[i - 1]
                        engulf = (closes[i] < opens[i]) and (closes[i] <= opens[i - 1]) and (opens[i] >= closes[i - 1])
                        if touched and prev_bull and engulf:
                            pending_order = {"direction": "short", "trigger_price": lows[i], "stop_price": highs[i] + spread}

                elif setup_id == "inside_bar":
                    is_inside = (highs[i] <= highs[i - 1]) and (lows[i] >= lows[i - 1])
                    if is_inside:
                        if bullish_macro and slope_bullish:
                            touched = lows[i] <= max(mme8[i], mme20[i]) * 1.001
                            if touched:
                                pending_order = {"direction": "long", "trigger_price": highs[i], "stop_price": lows[i]}
                        elif bearish_macro and slope_bearish:
                            touched = highs[i] >= min(mme8[i], mme20[i]) * 0.999
                            if touched:
                                pending_order = {"direction": "short", "trigger_price": lows[i], "stop_price": highs[i] + spread}

        return trades

    def _run_unified_single_position(
        self,
        triggers: list[str],
        opens: np.ndarray,
        highs: np.ndarray,
        lows: np.ndarray,
        closes: np.ndarray,
        time_vals: np.ndarray,
        ts: pd.DatetimeIndex,
        mme8: np.ndarray,
        mme20: np.ndarray,
        mme80: np.ndarray,
        mme200: np.ndarray,
        adx: np.ndarray,
        slope80: np.ndarray,
        ma_cond: np.ndarray,
        symbol: str,
        spread: float,
        t_start: int,
        t_end: int,
    ) -> list[TrendTrade]:
        n = len(opens)
        trades: list[TrendTrade] = []
        open_pos: dict[str, Any] | None = None
        pending_order: dict[str, Any] | None = None

        for i in range(210, n - 1):
            if open_pos is not None:
                pos = open_pos
                d = 1 if pos["direction"] == "long" else -1
                hit_sl = False
                exit_by_ma = False

                if d == 1:
                    if lows[i] <= pos["stop_price"]:
                        hit_sl = True
                else:
                    if highs[i] + spread >= pos["stop_price"]:
                        hit_sl = True

                if i > pos["entry_idx"]:
                    if d == 1 and closes[i] < ma_cond[i]:
                        exit_by_ma = True
                    elif d == -1 and closes[i] > ma_cond[i]:
                        exit_by_ma = True

                if hit_sl:
                    if d == 1:
                        raw_exit = min(pos["stop_price"], opens[i])
                        exit_price = raw_exit - self.config.slippage_pts
                        r = (exit_price - pos["entry_price"]) / pos["initial_risk"]
                    else:
                        raw_exit = max(pos["stop_price"], opens[i] + spread)
                        exit_price = raw_exit + self.config.slippage_pts
                        r = (pos["entry_price"] - exit_price) / pos["initial_risk"]

                    trades.append(
                        TrendTrade(
                            symbol=symbol,
                            setup_name=pos["setup"],
                            direction=pos["direction"],
                            entry_time=pos["entry_time"],
                            exit_time=ts[i],
                            entry_price=pos["entry_price"],
                            stop_price=pos["stop_price"],
                            exit_price=exit_price,
                            exit_reason="STOP_LOSS",
                            r_multiple=float(r),
                            win=bool(r > 0),
                        )
                    )
                    open_pos = None
                    pending_order = None
                    continue

                elif exit_by_ma and i < n - 1:
                    exit_price = opens[i + 1] if d == 1 else opens[i + 1] + spread
                    r = (
                        (exit_price - pos["entry_price"]) / pos["initial_risk"]
                        if d == 1
                        else (pos["entry_price"] - exit_price) / pos["initial_risk"]
                    )
                    trades.append(
                        TrendTrade(
                            symbol=symbol,
                            setup_name=pos["setup"],
                            direction=pos["direction"],
                            entry_time=pos["entry_time"],
                            exit_time=ts[i + 1],
                            entry_price=pos["entry_price"],
                            stop_price=pos["stop_price"],
                            exit_price=exit_price,
                            exit_reason="TRAILING_MA",
                            r_multiple=float(r),
                            win=bool(r > 0),
                        )
                    )
                    open_pos = None
                    pending_order = None
                    continue

            if pending_order is not None and open_pos is None:
                po = pending_order
                d = 1 if po["direction"] == "long" else -1
                triggered = False
                exec_price = 0.0

                if d == 1:
                    if highs[i] >= po["trigger_price"]:
                        triggered = True
                        exec_price = max(opens[i], po["trigger_price"]) + spread + self.config.slippage_pts
                else:
                    if lows[i] <= po["trigger_price"]:
                        triggered = True
                        exec_price = min(opens[i], po["trigger_price"]) - self.config.slippage_pts

                if triggered:
                    risk = abs(exec_price - po["stop_price"])
                    if risk > 0:
                        entry_stopped = False
                        if d == 1:
                            if lows[i] <= po["stop_price"]:
                                entry_stopped = True
                                raw_exit = min(po["stop_price"], opens[i])
                                exit_price = raw_exit - self.config.slippage_pts
                                r = (exit_price - exec_price) / risk
                        else:
                            if highs[i] + spread >= po["stop_price"]:
                                entry_stopped = True
                                raw_exit = max(po["stop_price"], opens[i] + spread)
                                exit_price = raw_exit + self.config.slippage_pts
                                r = (exec_price - exit_price) / risk

                        if entry_stopped:
                            trades.append(
                                TrendTrade(
                                    symbol=symbol,
                                    setup_name=po["setup"],
                                    direction=po["direction"],
                                    entry_time=ts[i],
                                    exit_time=ts[i],
                                    entry_price=exec_price,
                                    stop_price=po["stop_price"],
                                    exit_price=exit_price,
                                    exit_reason="STOP_LOSS_ENTRY_BAR",
                                    r_multiple=float(r),
                                    win=bool(r > 0),
                                )
                            )
                            open_pos = None
                            pending_order = None
                            continue
                        else:
                            open_pos = {
                                "setup": po["setup"],
                                "direction": po["direction"],
                                "entry_idx": i,
                                "entry_time": ts[i],
                                "entry_price": exec_price,
                                "stop_price": po["stop_price"],
                                "initial_risk": risk,
                            }
                    pending_order = None
                    continue
                else:
                    pending_order = None

            if open_pos is None and pending_order is None:
                if not (t_start <= time_vals[i] <= t_end):
                    continue

                strong_trend = adx[i - 1] >= self.config.adx_min
                bullish_macro = closes[i - 1] > mme80[i - 1] > mme200[i - 1]
                bearish_macro = closes[i - 1] < mme80[i - 1] < mme200[i - 1]
                slope_bullish = self.config.slope_min <= slope80[i - 1] <= self.config.slope_max
                slope_bearish = -self.config.slope_max <= slope80[i - 1] <= -self.config.slope_min

                c_range = highs[i] - lows[i]
                if c_range <= 0 or not strong_trend:
                    continue

                if bullish_macro and slope_bullish:
                    # Avalia gatilhos em ordem de prioridade
                    if "trap" in triggers:
                        touched = lows[i] <= mme8[i] * 1.001
                        trap = (lows[i] < lows[i - 1]) and (closes[i] > lows[i - 1]) and (closes[i] > opens[i])
                        if touched and trap:
                            pending_order = {"setup": "TRAP", "direction": "long", "trigger_price": highs[i], "stop_price": lows[i]}

                    if pending_order is None and "force_bar" in triggers:
                        touched = lows[i] <= max(mme8[i], mme20[i]) * 1.001
                        force = (closes[i] > opens[i]) and ((closes[i] - lows[i]) / c_range >= 0.70) and (closes[i] > mme8[i])
                        if touched and force:
                            pending_order = {"setup": "FORCE_BAR", "direction": "long", "trigger_price": highs[i], "stop_price": lows[i]}

                    if pending_order is None and "engulfing" in triggers:
                        touched = lows[i] <= max(mme8[i], mme20[i]) * 1.001
                        prev_bear = closes[i - 1] < opens[i - 1]
                        engulf = (closes[i] > opens[i]) and (closes[i] >= opens[i - 1]) and (opens[i] <= closes[i - 1])
                        if touched and prev_bear and engulf:
                            pending_order = {"setup": "ENGULFING", "direction": "long", "trigger_price": highs[i], "stop_price": lows[i]}

                    if pending_order is None and "inside_bar" in triggers:
                        is_inside = (highs[i] <= highs[i - 1]) and (lows[i] >= lows[i - 1])
                        touched = lows[i] <= max(mme8[i], mme20[i]) * 1.001
                        if is_inside and touched:
                            pending_order = {"setup": "INSIDE_BAR", "direction": "long", "trigger_price": highs[i], "stop_price": lows[i]}

                elif bearish_macro and slope_bearish:
                    if "trap" in triggers:
                        touched = highs[i] >= mme8[i] * 0.999
                        trap = (highs[i] > highs[i - 1]) and (closes[i] < highs[i - 1]) and (closes[i] < opens[i])
                        if touched and trap:
                            pending_order = {"setup": "TRAP", "direction": "short", "trigger_price": lows[i], "stop_price": highs[i] + spread}

                    if pending_order is None and "force_bar" in triggers:
                        touched = highs[i] >= min(mme8[i], mme20[i]) * 0.999
                        force = (closes[i] < opens[i]) and ((highs[i] - closes[i]) / c_range >= 0.70) and (closes[i] < mme8[i])
                        if touched and force:
                            pending_order = {"setup": "FORCE_BAR", "direction": "short", "trigger_price": lows[i], "stop_price": highs[i] + spread}

                    if pending_order is None and "engulfing" in triggers:
                        touched = highs[i] >= min(mme8[i], mme20[i]) * 0.999
                        prev_bull = closes[i - 1] > opens[i - 1]
                        engulf = (closes[i] < opens[i]) and (closes[i] <= opens[i - 1]) and (opens[i] >= closes[i - 1])
                        if touched and prev_bull and engulf:
                            pending_order = {"setup": "ENGULFING", "direction": "short", "trigger_price": lows[i], "stop_price": highs[i] + spread}

                    if pending_order is None and "inside_bar" in triggers:
                        is_inside = (highs[i] <= highs[i - 1]) and (lows[i] >= lows[i - 1])
                        touched = highs[i] >= min(mme8[i], mme20[i]) * 0.999
                        if is_inside and touched:
                            pending_order = {"setup": "INSIDE_BAR", "direction": "short", "trigger_price": lows[i], "stop_price": highs[i] + spread}

        return trades

    @staticmethod
    def max_drawdown_r(trades: list[TrendTrade]) -> float:
        if not trades:
            return 0.0
        r_curve = np.cumsum([t.r_multiple for t in trades])
        peak = np.maximum.accumulate(r_curve)
        dd = peak - r_curve
        return float(np.max(dd)) if len(dd) > 0 else 0.0

    @classmethod
    def generate_attribution_report(
        cls,
        trades: list[TrendTrade],
        split_dt: pd.Timestamp | None = None,
    ) -> str:
        """Gera relatório markdown granular com atribuição por gatilho e ativo."""
        if not trades:
            return "Nenhum trade realizado."

        if split_dt is None:
            split_dt = pd.Timestamp("2024-11-01", tz="UTC")

        # 1. Atribuição por Gatilho
        setups = sorted(list(set(t.setup_name for t in trades)))
        symbols = sorted(list(set(t.symbol for t in trades)))

        lines = [
            "### Relatório Granular de Atribuição de Desempenho",
            "",
            "#### 1. Desempenho por Gatilho",
            "| Gatilho | Trades | R Total | Taxa Acerto | Profit Factor | Max Drawdown | IS | OOS |",
            "|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|",
        ]

        for s in setups:
            tr_s = [t for t in trades if t.setup_name == s]
            n = len(tr_s)
            r_tot = sum(t.r_multiple for t in tr_s)
            wins = sum(1 for t in tr_s if t.win)
            wr = 100.0 * wins / n if n > 0 else 0.0
            gp = sum(t.r_multiple for t in tr_s if t.r_multiple > 0)
            gl = -sum(t.r_multiple for t in tr_s if t.r_multiple < 0)
            pf = gp / gl if gl > 0 else float("inf")
            dd = cls.max_drawdown_r(tr_s)
            is_r = sum(t.r_multiple for t in tr_s if t.entry_time < split_dt)
            oos_r = sum(t.r_multiple for t in tr_s if t.entry_time >= split_dt)
            lines.append(
                f"| **{s}** | {n} | {r_tot:+.1f}R | {wr:.1f}% | {pf:.2f} | {dd:.1f}R | {is_r:+.1f}R | {oos_r:+.1f}R |"
            )

        # 2. Desempenho por Ativo
        lines.extend([
            "",
            "#### 2. Desempenho por Ativo",
            "| Ativo | Trades | R Total | Taxa Acerto | Profit Factor | Max Drawdown | IS | OOS |",
            "|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|",
        ])

        for sym in symbols:
            tr_sym = [t for t in trades if t.symbol == sym]
            n = len(tr_sym)
            r_tot = sum(t.r_multiple for t in tr_sym)
            wins = sum(1 for t in tr_sym if t.win)
            wr = 100.0 * wins / n if n > 0 else 0.0
            gp = sum(t.r_multiple for t in tr_sym if t.r_multiple > 0)
            gl = -sum(t.r_multiple for t in tr_sym if t.r_multiple < 0)
            pf = gp / gl if gl > 0 else float("inf")
            dd = cls.max_drawdown_r(tr_sym)
            is_r = sum(t.r_multiple for t in tr_sym if t.entry_time < split_dt)
            oos_r = sum(t.r_multiple for t in tr_sym if t.entry_time >= split_dt)
            lines.append(
                f"| **{sym}** | {n} | {r_tot:+.1f}R | {wr:.1f}% | {pf:.2f} | {dd:.1f}R | {is_r:+.1f}R | {oos_r:+.1f}R |"
            )

        # 3. Consolidado da Carteira
        tot_n = len(trades)
        tot_r = sum(t.r_multiple for t in trades)
        tot_wins = sum(1 for t in trades if t.win)
        tot_wr = 100.0 * tot_wins / tot_n if tot_n > 0 else 0.0
        tot_gp = sum(t.r_multiple for t in trades if t.r_multiple > 0)
        tot_gl = -sum(t.r_multiple for t in trades if t.r_multiple < 0)
        tot_pf = tot_gp / tot_gl if tot_gl > 0 else float("inf")
        tot_dd = cls.max_drawdown_r(trades)
        tot_is = sum(t.r_multiple for t in trades if t.entry_time < split_dt)
        tot_oos = sum(t.r_multiple for t in trades if t.entry_time >= split_dt)
        r_per_tr = tot_r / tot_n if tot_n > 0 else 0.0
        se = float(np.std([t.r_multiple for t in trades]) / np.sqrt(tot_n)) if tot_n > 0 else 0.0

        lines.extend([
            "",
            "#### 3. Total Consolidado",
            f"* **Total de Trades:** {tot_n}",
            f"* **Retorno Total:** {tot_r:+.1f}R ({tot_r / 5.0:+.1f}R/ano)",
            f"* **Expectativa (R/trade):** {r_per_tr:+.3f} ± {se:.3f}R",
            f"* **Taxa de Acerto:** {tot_wr:.1f}%",
            f"* **Profit Factor:** {tot_pf:.2f}",
            f"* **Max Drawdown:** {tot_dd:.1f}R",
            f"* **In-Sample (3 anos):** {tot_is:+.1f}R",
            f"* **Out-of-Sample (2 anos):** {tot_oos:+.1f}R",
        ])

        return "\n".join(lines)
