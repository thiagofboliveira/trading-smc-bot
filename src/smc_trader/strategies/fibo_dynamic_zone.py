"""Estratégia Fibo Dynamic Zone (M5).

Confluência de Range Fibo (61.8% a 79.0%) dentro do Range de Médias Dinâmicas (MME 80 e MMA 200).
Inclinação mínima de 30° das médias, alvo mínimo 1:3 de risco/retorno, stop em 82% (ou no topo/fundo),
risco fixo de 2% sobre a banca (alvo de 6% por operação) e travas diárias estritas (máx 2 stops,
1 gain encerra o dia, máx 3 operações por dia).

Regras de causalidade estritas de acordo com AGENTS.md e STANDARDS.md:
- Filtros de médias, inclinação e confluência de range calculados estritamente na barra i-1.
- Ordem limite executada no toque intrabar na barra i.
- A barra de entrada só pode ser estopada intrabar, nunca alvejada.
- Stop loss com gap executado no open com slippage realista.
"""

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

from smc_trader.data.candles import TF_MINUTES


@dataclass
class FiboDynamicZoneConfig:
    timeframe: str = "M5"
    pivot_k: int = 2
    fibo_entry: float = 0.618
    fibo_zone_shallow: float = 0.618
    fibo_zone_deep: float = 0.790
    fibo_stop: float = 0.820
    stop_mode: Literal["fibo_82", "swing_extreme"] = "fibo_82"
    entry_mode: Literal["limit", "rejection"] = "limit"
    rejection_min_wick_ratio: float = 0.25
    rejection_require_directional_body: bool = True
    target_rr: float = 3.0
    target_mode: Literal[
        "fixed_rr", "structural_0", "partial_0_runner_3r", "runner_ma"
    ] = "fixed_rr"
    trailing_ma_period: int = 20
    ema_fast_period: int = 80
    sma_slow_period: int = 200
    min_slope_degrees: float = 20.0
    slope_lookback: int = 50
    zone_confluence_mode: Literal[
        "fibo_within_ma", "overlap", "ema80_in_fibo", "fibo_above_sma200"
    ] = "fibo_within_ma"
    max_holding_candles: int = 72
    slippage: float = 1.0
    commission_per_unit: float = 0.0
    account_balance: float = 10000.0
    risk_pct_per_trade: float = 0.02
    max_stops_per_day: int = 2
    max_gains_per_day: int = 1
    max_trades_per_day: int = 3
    min_leg_spread_mult: float = 3.0
    require_leg_fvg: bool = False
    require_inducement: bool = False
    session_filter: bool = False
    session_windows: tuple[tuple[str, str], ...] = (
        ("07:00", "10:30"),
        ("12:30", "16:30"),
    )
    profit_lock_trigger_r: float = 0.0
    profit_lock_lock_r: float = 0.0
    breakeven_trigger_r: float = 0.0
    breakeven_lock_r: float = 0.0
    partial_trigger_r: float = 0.0
    partial_pct: float = 0.0
    bos_swing_trailing: bool = False
    require_h1_trend_alignment: bool = False
    min_channel_atr: float = 0.0
    max_channel_atr: float = 0.0
    min_adx: float = 0.0
    max_adx: float = 0.0


@dataclass
class DynamicZoneTrade:
    symbol: str
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    direction: Literal["long", "short"]
    entry_price: float
    stop_loss: float
    take_profit: float
    risk_points: float
    pnl_points: float
    r_multiple: float
    pnl_usd: float
    win: bool
    exit_reason: str


@dataclass
class _Leg:
    d: int  # +1 para alta (compra), -1 para baixa (venda)
    origin: float  # fundo no long, topo no short
    extreme: float  # topo no long, fundo no short
    bos_idx: int
    candles: int = 0
    touched: bool = False
    idm_level: float | None = None
    idm_swept: bool = False

    def level(self, ratio: float) -> float:
        span = self.d * (self.extreme - self.origin)
        return self.extreme - self.d * ratio * span


@dataclass
class _Position:
    d: int
    entry_idx: int
    entry_price: float
    stop: float
    target: float
    risk: float
    realized_r: float = 0.0
    locked: bool = False
    be_activated: bool = False
    partial_taken: bool = False
    bos_ref: float = 0.0
    pending_ma_exit: bool = False


def _fractal_swings(highs: np.ndarray, lows: np.ndarray, k: int) -> tuple[np.ndarray, np.ndarray]:
    n = len(highs)
    sh = np.zeros(n, dtype=bool)
    sl = np.zeros(n, dtype=bool)
    if n < 2 * k + 1:
        return sh, sl

    mid_h = highs[k : n - k]
    left_h = np.lib.stride_tricks.sliding_window_view(highs[: n - k - 1], k).max(axis=1)
    right_h = np.lib.stride_tricks.sliding_window_view(highs[k + 1 :], k).max(axis=1)
    sh[k : n - k] = (mid_h > left_h) & (mid_h >= right_h)

    mid_l = lows[k : n - k]
    left_l = np.lib.stride_tricks.sliding_window_view(lows[: n - k - 1], k).min(axis=1)
    right_l = np.lib.stride_tricks.sliding_window_view(lows[k + 1 :], k).min(axis=1)
    sl[k : n - k] = (mid_l < left_l) & (mid_l <= right_l)

    return sh, sl


class FiboDynamicZoneStrategy:
    """Implementação da estratégia Fibo Dynamic Zone (M5)."""

    def __init__(self, config: FiboDynamicZoneConfig | None = None) -> None:
        self.config = config or FiboDynamicZoneConfig()

    def resample_data(self, df_m1: pd.DataFrame) -> pd.DataFrame:
        """Resampleia de M1 para o timeframe operacional (ex: M5) e calcula indicadores."""
        rule = (
            f"{TF_MINUTES[self.config.timeframe]}min"
            if self.config.timeframe in TF_MINUTES
            else self.config.timeframe
        )
        agg_dict = {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
        }
        if "volume" in df_m1.columns:
            agg_dict["volume"] = "sum"
        if "roll" in df_m1.columns:
            agg_dict["roll"] = "max"

        df_res = df_m1.resample(rule).agg(agg_dict).dropna()

        # ATR 14 para normalização causal de inclinação
        high = df_res["high"]
        low = df_res["low"]
        close = df_res["close"]
        prev_close = close.shift(1)
        tr1 = high - low
        tr2 = (high - prev_close).abs()
        tr3 = (low - prev_close).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        df_res["atr"] = tr.rolling(window=14).mean()

        # MME 80, MMA 200, MME 960 (equivalente causal à MME 80 do H1 no M5) e MME de condução
        df_res["ema80"] = close.ewm(span=self.config.ema_fast_period, adjust=False).mean()
        df_res["sma200"] = close.rolling(window=self.config.sma_slow_period).mean()
        df_res["ema960"] = close.ewm(span=self.config.ema_fast_period * 12, adjust=False).mean()
        df_res["trailing_ma"] = close.ewm(span=self.config.trailing_ma_period, adjust=False).mean()

        # ADX(14) causal
        up_move = high - high.shift(1)
        down_move = low.shift(1) - low
        plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
        tr_s = tr.rolling(window=14).sum().replace(0, np.nan)
        plus_di = 100.0 * (pd.Series(plus_dm, index=df_res.index).rolling(window=14).sum() / tr_s)
        minus_di = 100.0 * (pd.Series(minus_dm, index=df_res.index).rolling(window=14).sum() / tr_s)
        dx = 100.0 * ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan))
        df_res["adx14"] = dx.rolling(window=14).mean()

        # Inclinação em graus na janela de N candles (caixa visual do range de candles):
        # Traça a reta da média ao longo do range de N candles normalizado pela amplitude (MaxHigh - MinLow) da janela.
        n_lookback = self.config.slope_lookback
        win_range = (
            high.rolling(window=n_lookback).max() - low.rolling(window=n_lookback).min()
        ).replace(0, np.nan)
        slope_norm = (df_res["ema80"] - df_res["ema80"].shift(n_lookback)) / win_range
        df_res["slope_deg"] = np.degrees(np.arctan(slope_norm.fillna(0).to_numpy()))

        return df_res

    def run_backtest(
        self,
        df_m1: pd.DataFrame,
        symbol: str,
        spread: float,
        df_ask_m1: pd.DataFrame | None = None,
    ) -> list[DynamicZoneTrade]:
        """Execução causal cronológica barra a barra."""
        df = self.resample_data(df_m1)
        cfg = self.config
        k = cfg.pivot_k
        n = len(df)

        opens = df["open"].to_numpy()
        highs = df["high"].to_numpy()
        lows = df["low"].to_numpy()
        closes = df["close"].to_numpy()
        ts = df.index
        emas80 = df["ema80"].to_numpy()
        smas200 = df["sma200"].to_numpy()
        emas960 = df["ema960"].to_numpy()
        trailing_mas = df["trailing_ma"].to_numpy()
        atrs = df["atr"].to_numpy()
        adxs14 = df["adx14"].to_numpy()
        slope_deg = df["slope_deg"].to_numpy()
        swing_h, swing_l = _fractal_swings(highs, lows, k)

        df_ask = (
            self.resample_data(df_ask_m1).reindex(df.index)
            if df_ask_m1 is not None
            else None
        )
        ask_opens = df_ask["open"].to_numpy() if df_ask is not None else None
        ask_highs = df_ask["high"].to_numpy() if df_ask is not None else None

        day_trades: dict[object, int] = {}
        day_stops: dict[object, int] = {}
        day_gains: dict[object, int] = {}

        def is_day_locked(d_key: object) -> bool:
            if cfg.max_trades_per_day > 0 and day_trades.get(d_key, 0) >= cfg.max_trades_per_day:
                return True
            if cfg.max_stops_per_day > 0 and day_stops.get(d_key, 0) >= cfg.max_stops_per_day:
                return True
            if cfg.max_gains_per_day > 0 and day_gains.get(d_key, 0) >= cfg.max_gains_per_day:
                return True
            return False

        def close_trade(pos: _Position, i: int, exit_px: float, reason: str) -> DynamicZoneTrade:
            unscaled_pnl = pos.d * (exit_px - pos.entry_price) - cfg.commission_per_unit
            unscaled_r = unscaled_pnl / pos.risk
            part_frac = (
                0.5
                if cfg.target_mode == "partial_0_runner_3r"
                else cfg.partial_pct
            )
            rem_frac = 1.0 - (part_frac if pos.partial_taken else 0.0)
            r = pos.realized_r + rem_frac * unscaled_r
            # Risco monetário de 2% sobre o capital: 1R = 2% do capital
            usd_risk = cfg.account_balance * cfg.risk_pct_per_trade
            pnl_usd = r * usd_risk

            d_key = ts[i].date()
            day_trades[d_key] = day_trades.get(d_key, 0) + 1
            if r > 0.05:
                day_gains[d_key] = day_gains.get(d_key, 0) + 1
            elif r < -0.05:
                day_stops[d_key] = day_stops.get(d_key, 0) + 1

            return DynamicZoneTrade(
                symbol=symbol,
                entry_time=ts[pos.entry_idx],
                exit_time=ts[i],
                direction="long" if pos.d == 1 else "short",
                entry_price=pos.entry_price,
                stop_loss=pos.stop,
                take_profit=pos.target,
                risk_points=pos.risk,
                pnl_points=r * pos.risk,
                r_multiple=r,
                pnl_usd=pnl_usd,
                win=r > 0,
                exit_reason=reason,
            )

        def stop_hit(pos: _Position, i: int) -> bool:
            adverse = (
                lows[i]
                if pos.d == 1
                else (
                    ask_highs[i]
                    if (ask_highs is not None and i < len(ask_highs) and not np.isnan(ask_highs[i]))
                    else highs[i] + spread
                )
            )
            return pos.d * (pos.stop - adverse) >= 0

        def get_stop_exit_price(pos: _Position, i: int) -> float:
            if pos.d == 1:
                return min(opens[i], pos.stop) - cfg.slippage
            else:
                open_ask = (
                    ask_opens[i]
                    if (ask_opens is not None and i < len(ask_opens) and not np.isnan(ask_opens[i]))
                    else opens[i] + spread
                )
                return max(open_ask, pos.stop) + cfg.slippage

        def get_target_exit_price(pos: _Position, i: int) -> float:
            if pos.d == 1:
                return max(opens[i], pos.target) - cfg.slippage
            else:
                open_ask = (
                    ask_opens[i]
                    if (ask_opens is not None and i < len(ask_opens) and not np.isnan(ask_opens[i]))
                    else opens[i] + spread
                )
                return min(open_ask, pos.target) + cfg.slippage

        def ask_adj(d: int, i: int) -> float:
            if d != -1:
                return 0.0
            if ask_opens is not None and i < len(ask_opens) and not np.isnan(ask_opens[i]):
                return float(ask_opens[i] - opens[i])
            return spread

        def open_position(leg: _Leg, i: int) -> _Position | None:
            d = leg.d
            level = leg.level(cfg.fibo_entry)
            if cfg.stop_mode == "fibo_82":
                stop = leg.level(cfg.fibo_stop)
            else:  # "swing_extreme"
                stop = leg.origin

            slip = cfg.slippage if d == 1 else -cfg.slippage
            curr_spread = (
                (ask_opens[i] - opens[i])
                if (ask_opens is not None and i < len(ask_opens) and not np.isnan(ask_opens[i]))
                else spread
            )
            # Se a barra abriu com gap além do nível limite (opens[i] < level no Long ou opens[i] > level no Short),
            # uma ordem limite apregoada em i-1 preenche no open da barra i.
            fill_base = min(opens[i], level) if d == 1 else max(opens[i], level)
            entry = fill_base + (curr_spread if d == 1 else 0.0) + slip
            risk = d * (entry - stop)
            if risk <= curr_spread * 1.5:
                return None

            target = (
                0.0
                if cfg.target_mode == "runner_ma"
                else (
                    leg.extreme
                    if cfg.target_mode == "structural_0"
                    else entry + d * risk * cfg.target_rr
                )
            )
            if cfg.target_mode != "runner_ma" and d * (target - entry) <= 0:
                return None
            return _Position(
                d=d,
                entry_idx=i,
                entry_price=entry,
                stop=stop,
                target=target,
                risk=risk,
                bos_ref=leg.extreme,
            )

        def check_range_confluence(d: int, leg: _Leg, idx_eval: int) -> bool:
            """Verifica se o range Fibo [fibo_zone_shallow, fibo_zone_deep] está confluente com o canal [MMA200, MME80].

            Calculado na barra i-1 antes da execução intrabar.
            """
            fibo_shallow_px = leg.level(cfg.fibo_zone_shallow)
            fibo_deep_px = leg.level(cfg.fibo_zone_deep)
            ema = emas80[idx_eval]
            sma = smas200[idx_eval]

            if np.isnan(ema) or np.isnan(sma):
                return False

            # Filtro de alinhamento com tendência Macro H1 (MME 80 vs MME 960) avaliado em idx_eval (i-1)
            if cfg.require_h1_trend_alignment:
                ema_h1 = emas960[idx_eval]
                if np.isnan(ema_h1):
                    return False
                if d == 1 and ema <= ema_h1:
                    return False
                if d == -1 and ema >= ema_h1:
                    return False

            # Filtro de largura do canal [MMA200, MME80] em múltiplos de ATR(14) (evita exaustão ou embolamento)
            if cfg.min_channel_atr > 0 or cfg.max_channel_atr > 0:
                atr_val = atrs[idx_eval]
                if np.isnan(atr_val) or atr_val <= 0:
                    return False
                chan_width_atr = abs(ema - sma) / atr_val
                if cfg.min_channel_atr > 0 and chan_width_atr < cfg.min_channel_atr:
                    return False
                if cfg.max_channel_atr > 0 and chan_width_atr > cfg.max_channel_atr:
                    return False

            # Filtro de ADX(14) avaliado em idx_eval (i-1)
            if cfg.min_adx > 0 or cfg.max_adx > 0:
                adx_val = adxs14[idx_eval]
                if np.isnan(adx_val):
                    return False
                if cfg.min_adx > 0 and adx_val < cfg.min_adx:
                    return False
                if cfg.max_adx > 0 and adx_val > cfg.max_adx:
                    return False

            if d == 1:
                # Long: Tendência de alta exige MME 80 > MMA 200
                if ema <= sma:
                    return False
                # Inclinação mínima de 30°
                if slope_deg[idx_eval] < cfg.min_slope_degrees:
                    return False

                # Range de Fibo de compra: [fibo_deep_px, fibo_shallow_px] onde deep < shallow
                f_low = min(fibo_shallow_px, fibo_deep_px)
                f_high = max(fibo_shallow_px, fibo_deep_px)
                # Canal de Médias: [MMA200, MME80]
                ma_low = sma
                ma_high = ema

                if cfg.zone_confluence_mode == "fibo_within_ma":
                    # Range Fibo inteiramente dentro ou contido no canal de médias
                    return f_high <= ma_high and f_low >= ma_low
                elif cfg.zone_confluence_mode == "ema80_in_fibo":
                    # MME 80 passa exatamente dentro da zona Fibo [79.0%, 61.8%] e zona está acima da MMA 200
                    return (f_low <= ema <= f_high) and (f_low >= sma)
                elif cfg.zone_confluence_mode == "fibo_above_sma200":
                    # Zona Fibo tem a MMA 200 como piso abaixo de 79% e conflui com a MME 80 (dentro ou no canal)
                    return (f_low >= sma) and (ema >= f_low)
                else:  # "overlap"
                    return max(f_low, ma_low) <= min(f_high, ma_high)
            else:
                # Short: Tendência de baixa exige MME 80 < MMA 200
                if ema >= sma:
                    return False
                # Inclinação mínima de -30° (para baixo)
                if slope_deg[idx_eval] > -cfg.min_slope_degrees:
                    return False

                # Range de Fibo de venda: [fibo_shallow_px, fibo_deep_px] onde shallow < deep
                f_low = min(fibo_shallow_px, fibo_deep_px)
                f_high = max(fibo_shallow_px, fibo_deep_px)
                # Canal de Médias: [MME80, MMA200]
                ma_low = ema
                ma_high = sma

                if cfg.zone_confluence_mode == "fibo_within_ma":
                    # Range Fibo inteiramente dentro ou contido no canal de médias
                    return f_low >= ma_low and f_high <= ma_high
                elif cfg.zone_confluence_mode == "ema80_in_fibo":
                    # MME 80 passa exatamente dentro da zona Fibo [61.8%, 79.0%] e zona está abaixo da MMA 200
                    return (f_low <= ema <= f_high) and (f_high <= sma)
                elif cfg.zone_confluence_mode == "fibo_above_sma200":
                    # Zona Fibo tem a MMA 200 como teto acima de 79% e conflui com a MME 80 (dentro ou no canal)
                    return (f_high <= sma) and (ema <= f_high)
                else:  # "overlap"
                    return max(f_low, ma_low) <= min(f_high, ma_high)

        pos: _Position | None = None
        leg: _Leg | None = None
        pending_rej: tuple[int, float] | None = None
        last_sh_price: float | None = None
        last_sh_idx: int | None = None
        last_sl_price: float | None = None
        last_sl_idx: int | None = None
        trades: list[DynamicZoneTrade] = []

        start_bar = max(cfg.sma_slow_period + 10, 2 * k + 1)

        for i in range(start_bar, n):
            # 1. Atualiza pivôs fractais causais confirmados na barra i
            piv_idx = i - k
            if piv_idx >= 0:
                if swing_h[piv_idx]:
                    last_sh_price = highs[piv_idx]
                    last_sh_idx = piv_idx
                if swing_l[piv_idx]:
                    last_sl_price = lows[piv_idx]
                    last_sl_idx = piv_idx

            # 1b. Execução de entrada pendente no open da barra i (após candle de rejeição em i-1)
            if pos is None and pending_rej is not None:
                p_d, p_stop = pending_rej
                pending_rej = None
                if not is_day_locked(ts[i].date()):
                    slip = cfg.slippage if p_d == 1 else -cfg.slippage
                    curr_spread = (
                        (ask_opens[i] - opens[i])
                        if (ask_opens is not None and i < len(ask_opens) and not np.isnan(ask_opens[i]))
                        else spread
                    )
                    entry = opens[i] + (curr_spread if p_d == 1 else 0.0) + slip
                    risk = p_d * (entry - p_stop)
                    if risk > curr_spread * 1.5:
                        target = (
                            0.0
                            if cfg.target_mode == "runner_ma"
                            else entry + p_d * risk * cfg.target_rr
                        )
                        pos = _Position(
                            d=p_d,
                            entry_idx=i,
                            entry_price=entry,
                            stop=p_stop,
                            target=target,
                            risk=risk,
                        )
                        if stop_hit(pos, i):
                            exit_px = get_stop_exit_price(pos, i)
                            trades.append(
                                close_trade(pos, i, exit_px, "INTRABAR_STOP_LOSS")
                            )
                            pos = None
                        else:
                            continue

            # 2. Gerenciamento de posição aberta
            if pos is not None:
                # 2a. Saída pendente a mercado no open da barra i (acionada no fechamento da barra i-1 contra a trailing MA)
                if pos.pending_ma_exit:
                    exit_px = (
                        opens[i] - cfg.slippage
                        if pos.d == 1
                        else opens[i] + ask_adj(pos.d, i) + cfg.slippage
                    )
                    trades.append(close_trade(pos, i, exit_px, "TRAILING_MA"))
                    pos = None
                    leg = None
                    continue

                # Checa stop loss na abertura (gap) ou no intraday da barra i
                if stop_hit(pos, i):
                    exit_px = get_stop_exit_price(pos, i)
                    reason = (
                        "PROFIT_LOCK"
                        if pos.locked
                        else ("BREAKEVEN" if pos.be_activated else "STOP_LOSS")
                    )
                    trades.append(close_trade(pos, i, exit_px, reason))
                    pos = None
                    leg = None
                    continue

                # Checa take profit (F-02: short sai pelo ask = low + ask_adj)
                favorable = highs[i] if pos.d == 1 else lows[i] + ask_adj(pos.d, i)
                eff_part_pct = (
                    0.5
                    if cfg.target_mode == "partial_0_runner_3r"
                    else cfg.partial_pct
                )
                eff_part_trig_r = (
                    (pos.d * (pos.bos_ref - pos.entry_price) / pos.risk)
                    if (cfg.target_mode == "partial_0_runner_3r" and pos.bos_ref > 0)
                    else cfg.partial_trigger_r
                )
                target_hit = (
                    cfg.target_mode != "runner_ma"
                    and pos.d * (favorable - pos.target) >= 0
                )
                if target_hit:
                    # Se havia parcial armada antes do alvo final e ainda não executada, ela cruzou primeiro
                    if (
                        eff_part_trig_r > 0
                        and eff_part_pct > 0
                        and not pos.partial_taken
                        and i > pos.entry_idx
                    ):
                        pos.realized_r += eff_part_pct * eff_part_trig_r
                        pos.partial_taken = True
                    exit_px = get_target_exit_price(pos, i)
                    trades.append(close_trade(pos, i, exit_px, "TAKE_PROFIT"))
                    pos = None
                    leg = None
                    continue

                # Realização parcial causal (apenas em barras posteriores à entrada)
                if (
                    eff_part_trig_r > 0
                    and eff_part_pct > 0
                    and not pos.partial_taken
                    and i > pos.entry_idx
                ):
                    part_px = pos.entry_price + pos.d * pos.risk * eff_part_trig_r
                    if pos.d * (favorable - part_px) >= 0:
                        pos.realized_r += eff_part_pct * eff_part_trig_r
                        pos.partial_taken = True
                        if cfg.target_mode == "partial_0_runner_3r":
                            be_stop = pos.entry_price + pos.d * pos.risk * max(cfg.breakeven_lock_r, 0.1)
                            if pos.d * (be_stop - pos.stop) > 0:
                                pos.stop = be_stop
                                pos.be_activated = True

                # Estágio 1: Breakeven causal (ex: ao atingir +1.0R ou +1.25R, move stop p/ 0.0R ou +0.1R a partir de i+1)
                if not pos.be_activated and not pos.locked and cfg.breakeven_trigger_r > 0:
                    be_trig_px = pos.entry_price + pos.d * pos.risk * cfg.breakeven_trigger_r
                    if pos.d * (favorable - be_trig_px) >= 0:
                        be_stop = pos.entry_price + pos.d * pos.risk * cfg.breakeven_lock_r
                        if pos.d * (be_stop - pos.stop) > 0:
                            pos.stop = be_stop
                            pos.be_activated = True

                # Estágio 2: Trava de proteção de lucro (profit_lock) causal:
                # Se a barra i atingiu o gatilho (ex: +1.618R ou +2.0R) sem estopar, move o stop para +1.0R a partir de i+1
                if not pos.locked and cfg.profit_lock_trigger_r > 0:
                    trig_px = pos.entry_price + pos.d * pos.risk * cfg.profit_lock_trigger_r
                    if pos.d * (favorable - trig_px) >= 0:
                        new_stop = pos.entry_price + pos.d * pos.risk * cfg.profit_lock_lock_r
                        if pos.d * (new_stop - pos.stop) > 0:
                            pos.stop = new_stop
                            pos.locked = True

                # Condução estrutural BOS a BOS causal (move stop para o último swing confirmado k barras atrás)
                if cfg.bos_swing_trailing:
                    if (
                        pos.d == 1
                        and last_sh_idx is not None
                        and last_sh_idx >= pos.entry_idx
                        and last_sh_price is not None
                        and last_sh_price > pos.bos_ref
                    ):
                        pos.bos_ref = last_sh_price
                    elif (
                        pos.d == -1
                        and last_sl_idx is not None
                        and last_sl_idx >= pos.entry_idx
                        and last_sl_price is not None
                        and last_sl_price < pos.bos_ref
                    ):
                        pos.bos_ref = last_sl_price

                    if pos.bos_ref > 0 and pos.d * (closes[i] - pos.bos_ref) > 0:
                        pos.bos_ref = highs[i] if pos.d == 1 else lows[i]
                        swing_stop = None
                        if (
                            pos.d == 1
                            and last_sl_price is not None
                            and last_sl_idx is not None
                            and last_sl_idx >= pos.entry_idx - k
                        ):
                            swing_stop = last_sl_price
                        elif (
                            pos.d == -1
                            and last_sh_price is not None
                            and last_sh_idx is not None
                            and last_sh_idx >= pos.entry_idx - k
                        ):
                            swing_stop = last_sh_price + ask_adj(pos.d, i)
                        if swing_stop is not None and pos.d * (swing_stop - pos.stop) > 0:
                            pos.stop = swing_stop
                            pos.locked = True

                # Condução Runner por Média Móvel (causal):
                # Quando profit_lock_trigger_r > 0, ativa apenas após o Profit Lock;
                # caso contrário, ativa a partir de qualquer barra posterior à entrada.
                # Se o candle fechar contra a trailing MA, agenda saída a mercado no open[i+1].
                runner_active = pos.locked if cfg.profit_lock_trigger_r > 0 else (i > pos.entry_idx)
                if cfg.target_mode == "runner_ma" and runner_active:
                    t_ma = trailing_mas[i]
                    if not np.isnan(t_ma) and pos.d * (closes[i] - t_ma) < 0:
                        pos.pending_ma_exit = True

                continue

            # 3. Detecta novo BOS causal no fechamento da barra i
            if leg is None and last_sh_price is not None and last_sl_price is not None:
                origin_idx = None
                if last_sh_idx > last_sl_idx and closes[i] > last_sh_price:
                    cand = _Leg(d=1, origin=last_sl_price, extreme=highs[i], bos_idx=i)
                    origin_idx = last_sl_idx
                elif last_sl_idx > last_sh_idx and closes[i] < last_sl_price:
                    cand = _Leg(d=-1, origin=last_sh_price, extreme=lows[i], bos_idx=i)
                    origin_idx = last_sh_idx
                else:
                    cand = None

                if cand is not None and abs(cand.extreme - cand.origin) > spread * cfg.min_leg_spread_mult:
                    has_fvg = True
                    if cfg.require_leg_fvg and origin_idx is not None:
                        if i - origin_idx < 2:
                            has_fvg = False
                        elif cand.d == 1:
                            has_fvg = bool(
                                np.any(lows[origin_idx + 2 : i + 1] > highs[origin_idx : i - 1])
                            )
                        else:
                            has_fvg = bool(
                                np.any(highs[origin_idx + 2 : i + 1] < lows[origin_idx : i - 1])
                            )
                    if has_fvg:
                        leg = cand

            # 4. Perna ativa: regra de ouro F-01 (só opera a partir da barra seguinte ao BOS)
            if leg is None or leg.bos_idx >= i:
                continue

            leg.candles += 1
            if leg.candles > cfg.max_holding_candles:
                leg = None
                continue

            if leg.touched and cfg.entry_mode == "limit":
                continue

            d = leg.d
            level_entry = leg.level(cfg.fibo_entry)
            level_deep = leg.level(cfg.fibo_zone_deep)
            level_invalidation = leg.level(cfg.fibo_stop) if cfg.stop_mode == "fibo_82" else leg.origin

            touch = lows[i] if d == 1 else highs[i]

            # Rastreamento causal de Inducement (IDM) formado até a barra i-1
            if leg.idm_level is None and not leg.touched and i > leg.bos_idx + 1:
                span_leg = leg.d * (leg.extreme - leg.origin)
                if leg.d == 1:
                    sub_l = lows[leg.bos_idx + 1 : i]
                    sub_h = highs[leg.bos_idx + 1 : i]
                    min_idx = int(np.argmin(sub_l))
                    min_sub = float(sub_l[min_idx])
                    if (
                        min_sub > level_entry
                        and min_idx < len(sub_h) - 1
                        and np.any(sub_h[min_idx + 1 :] > min_sub + 0.10 * span_leg)
                    ):
                        leg.idm_level = min_sub
                else:
                    sub_h = highs[leg.bos_idx + 1 : i]
                    sub_l = lows[leg.bos_idx + 1 : i]
                    max_idx = int(np.argmax(sub_h))
                    max_sub = float(sub_h[max_idx])
                    if (
                        max_sub < level_entry
                        and max_idx < len(sub_l) - 1
                        and np.any(sub_l[max_idx + 1 :] < max_sub - 0.10 * span_leg)
                    ):
                        leg.idm_level = max_sub

            if leg.idm_level is not None and not leg.idm_swept:
                if leg.d == 1 and lows[i] < leg.idm_level:
                    leg.idm_swept = True
                elif leg.d == -1 and highs[i] > leg.idm_level:
                    leg.idm_swept = True

            # Invalidação prematura: preço rompeu o stop antes de tocar na entrada
            if d * (level_invalidation - touch) >= 0:
                leg = None
                continue

            in_session = True
            if cfg.session_filter and cfg.session_windows:
                t_str = ts[i].strftime("%H:%M")
                in_session = any(w_start <= t_str < w_end for w_start, w_end in cfg.session_windows)

            if cfg.entry_mode == "rejection":
                # Modo Rejeição: espera a barra i tocar a zona [61.8%, 79.0%] e FECHAR rejeitando com pavio.
                # A ordem será executada somente no open da barra i+1 (sem look-ahead!).
                if d * (level_entry - touch) >= 0:
                    leg.touched = True
                    idm_ok = (not cfg.require_inducement) or leg.idm_swept
                    # Verifica confluência de range na barra i (já fechada no momento da decisão)
                    if (
                        in_session
                        and (not is_day_locked(ts[i].date()))
                        and idm_ok
                        and check_range_confluence(d, leg, i)
                        and d * (closes[i] - level_deep) > 0
                    ):
                        rng_b = highs[i] - lows[i]
                        wick = (
                            (min(opens[i], closes[i]) - lows[i])
                            if d == 1
                            else (highs[i] - max(opens[i], closes[i]))
                        )
                        wick_ok = rng_b > 0 and (wick >= cfg.rejection_min_wick_ratio * rng_b)
                        body_ok = (not cfg.rejection_require_directional_body) or (
                            d * (closes[i] - opens[i]) >= 0
                        )
                        if wick_ok and body_ok:
                            pending_rej = (d, level_invalidation)
                            leg = None
                    elif d * (closes[i] - level_deep) <= 0:
                        # Fechou além do limite de 79% da zona sem rejeitar: invalida a perna
                        leg = None
                else:
                    ext = highs[i] if d == 1 else lows[i]
                    if not leg.touched and d * (ext - leg.extreme) > 0:
                        leg.extreme = ext
                        leg.idm_level = None
                        leg.idm_swept = False
                continue

            # Checa toque intrabar no nível de entrada 61.8% (modo limit)
            if d * (level_entry - touch) >= 0:
                # O primeiro toque consome a ordem limite (mesmo que os filtros em i-1 ou a sessão bloqueiem a entrada).
                # Além disso, em i-1 o fechamento deve estar do lado de aproximação (acima de 61.8% p/ Long, abaixo p/ Short).
                leg.touched = True
                idm_ok = (not cfg.require_inducement) or leg.idm_swept
                approaching_from_outside = d * (closes[i - 1] - level_entry) > 0
                if (
                    (not in_session)
                    or is_day_locked(ts[i].date())
                    or (not approaching_from_outside)
                    or (not idm_ok)
                    or (not check_range_confluence(d, leg, i - 1))
                ):
                    leg = None
                    continue

                pos = open_position(leg, i)
                if pos is not None:
                    # Regra anti-viés: na barra de entrada i, testa IMEDIATAMENTE se o stop foi violado
                    if stop_hit(pos, i):
                        exit_px = get_stop_exit_price(pos, i)
                        trades.append(
                            close_trade(pos, i, exit_px, "INTRABAR_STOP_LOSS")
                        )
                        pos = None
                        leg = None
            else:
                # Expansão da perna se fizer nova máxima/mínima sem tocar a entrada
                ext = highs[i] if d == 1 else lows[i]
                if d * (ext - leg.extreme) > 0:
                    leg.extreme = ext
                    leg.idm_level = None
                    leg.idm_swept = False

        return trades
