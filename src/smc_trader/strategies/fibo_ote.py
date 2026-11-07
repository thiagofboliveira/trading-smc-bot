"""Estratégia SMC Fibonacci OTE (Optimal Trade Entry) em M5.

Um impulso que quebra a estrutura (BOS) define uma perna. Quando o preço retrai até o
nível de Fibonacci de entrada, abre-se a posição, com stop no nível de invalidação.

Modelo de execução (dados são candles BID; ask = bid + spread):

* Long compra no ask e vende no bid. Entra quando a mínima (bid) toca o nível, a
  `nível + spread`. Stop e alvo são comparados com a bid.
* Short vende no bid e recompra no ask. Entra quando a máxima (bid) toca o nível, ao
  próprio nível. Stop, alvo, trava e saída por MME são comparados com o ask
  (`bid + spread`), então o short também paga o spread, na saída.

Regras anti-viés (cada uma tem teste em `tests/test_fibo_ote.py`):

* F-01: o BOS só é conhecido no fechamento da barra que o confirma. A perna gera
  entrada a partir da barra seguinte.
* F-03: o stop vale como estava no início da barra. Uma trava 2:1 acionada na barra
  `i` só protege a partir de `i+1`.
* F-04: o toque é testado contra os níveis calculados até a barra `i-1`. A máxima/mínima
  de `i` só expande a perna depois.
* Dentro da mesma barra, a ordem entre eventos é desconhecida: vale o caso conservador
  (stop antes de alvo; a barra de entrada só pode ser estopada, nunca alvejada).

Também tratados: gap além do stop (F-05), saída por MME na abertura seguinte (F-06),
posição aberta no fim dos dados e limite de tempo, que sai na abertura da barra (F-07),
sessão e fim de semana (F-08), comissão e slippage (F-10) e rolagem de contrato, que
encerra a posição na última barra do contrato antigo (D-02).
"""

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd


@dataclass
class FiboOTEConfig:
    timeframe: str = "5min"
    fibo_entry: float = 0.705  # Nível Sweet Spot Institucional (70.5%)
    fibo_stop: float = 0.790  # Nível de Invalidação (79.0% ou 1.000 estrutural)
    fibo_rejection_max: float | None = (
        None  # Limite máximo da zona p/ rejeição (ex: 0.790 com fibo_entry=0.500)
    )
    entry_mode: Literal["limit", "m5_close_rejection"] = "limit"
    stop_mode: Literal["fibo", "rejection_candle"] = "fibo"
    rejection_min_wick_ratio: float = 0.0
    target_mode: Literal["3R", "0_percent", "proj_618", "trailing_only"] = "0_percent"
    target_r: float = 3.0
    pivot_k: int = 2  # Delay fractal (2 barras para confirmação sem lookahead)
    max_holding_candles: int = 60  # Barras (após o BOS) em que a perna segue válida
    enable_reentry_79: bool = False  # Não implementado
    min_leg_spread_mult: float = 10.0
    trailing_exit_ma: str | None = "ema8"  # 'ema8', 'sma20', 'sma9', 'ema80' ou None
    trailing_profit_only: bool = (
        True  # Exige fechamento no lucro para encerrar por trailing
    )
    trailing_exit_on_next_open: bool = (
        False  # F-06: executa saída por MME no open da barra i+1
    )
    use_lock_2to1: bool = (
        False  # Trava 2:1 (Perfil Blindado: ao atingir +2R, sobe stop para +1R)
    )
    lock_trigger_r: float = 2.0
    lock_guarantee_r: float = 1.0
    profit_lock_trigger_r: float | None = (
        None  # Gatilho genérico de lock/breakeven em R (ex: 1.0, 1.5, 2.0)
    )
    profit_lock_guarantee_r: float = (
        0.0  # Novo stop garantido em R (0.0 = breakeven, 1.0 = lock)
    )
    bos_swing_trailing: bool = (
        False  # Condução estrutural: a cada BOS a favor, move stop p/ o swing confirmado (F-01/F-03)
    )
    partial_exit_trigger_r: float | None = (
        None  # Gatilho de realização parcial em R (ex: 1.0, 1.5, 2.0)
    )
    partial_exit_pct: float = (
        0.0  # Fração da mão encerrada na parcial (ex: 0.5 para 50%)
    )
    trend_filter_80_200: bool = (
        False  # Long só se EMA80 > SMA200, Short só se EMA80 < SMA200
    )
    trend_ma: str | None = (
        None  # Filtro de regime de tendência por média móvel ('sma20', 'sma50', 'sma200', 'ema80', 'ema20')
    )
    trend_ma_slope: bool = (
        False  # Exige que a média móvel esteja inclinada a favor do trade (subindo p/ Long, descendo p/ Short)
    )
    trend_ma_min_slope: float = (
        0.0  # Inclinação mínima exigida da média móvel por barra
    )
    confluence_ma: str | None = (
        None  # Exige toque na média móvel na entrada ('ema8', 'ema20', 'sma20', 'sma50', 'ema80', 'sma200')
    )
    check_intrabar_sl: bool = True  # A barra de entrada também pode estopar a posição
    max_position_candles: int = 0  # F-07: tempo máximo de posição (0 = sem limite)
    session_filter: bool = False  # F-08: filtro de horário de entrada
    session_windows: list[tuple[str, str]] | None = (
        None  # F-08: janelas permitidas [("07:00", "15:30")]
    )
    force_close_time: str | None = None  # F-08: horário diário de zeragem forçada
    close_on_friday: bool = False  # F-08: zeragem na sexta-feira antes do fim de semana
    friday_close_time: str = "20:45"  # F-08: horário de zeragem na sexta
    slippage: float = 0.0  # F-10: slippage por execução em pontos de preço
    commission_per_unit: float = (
        0.0  # F-10: comissão total por trade em pontos de preço
    )


@dataclass
class FiboTrade:
    symbol: str
    stage: int  # 1 = entrada primária, 2 = reentrada
    direction: Literal["long", "short"]
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    entry_price: float
    stop_loss: float
    take_profit: float
    risk_points: float
    pnl_points: float
    r_multiple: float
    win: bool
    exit_reason: str


@dataclass
class PendingSetup:
    """Entrada que o backtest executaria na PRÓXIMA barra, se o preço tocar o nível.

    No live vira uma ordem limite armada: `entry_price` já inclui o spread do long (compra no ask).
    """

    direction: Literal["long", "short"]
    entry_price: float
    stop_loss: float
    take_profit: float
    risk: float
    bos_time: pd.Timestamp
    candles_left: int  # barras restantes de validade da perna


@dataclass
class _Leg:
    """Perna de impulsão. `d` = +1 (BOS de alta, entrada comprada) ou -1 (BOS de baixa)."""

    d: int
    origin: float  # início da perna: fundo (d=+1) ou topo (d=-1)
    extreme: float  # ponta da perna: topo (d=+1) ou fundo (d=-1), expande até o toque
    bos_idx: int  # barra que confirmou o BOS
    candles: int = 0  # barras decorridas desde o BOS
    touched: bool = False

    def level(self, ratio: float) -> float:
        span = self.d * (self.extreme - self.origin)
        return self.extreme - self.d * ratio * span


@dataclass
class _PendingOpenEntry:
    d: int
    stop: float
    level: float
    extreme: float
    risk_ref: float
    bos_idx: int
    rej_extreme: float = 0.0


@dataclass
class _Position:
    d: int
    entry_idx: int
    entry_price: float
    stop: float
    target: float
    risk: float
    locked: bool = False
    pending_ma_exit: bool = False
    partial_taken: bool = False
    realized_r: float = 0.0
    bos_ref: float = 0.0
    rej_extreme: float = 0.0


def _fractal_swings(
    highs: np.ndarray, lows: np.ndarray, k: int, strict_tie_break: bool = True
) -> tuple[np.ndarray, np.ndarray]:
    """Marca o fractal no índice central (janela de 2k+1). F-11: desempata na 1ª ocorrência."""
    n = len(highs)
    sh = np.zeros(n, dtype=bool)
    sl = np.zeros(n, dtype=bool)
    if n < 2 * k + 1:
        return sh, sl
    if not strict_tie_break:
        win = 2 * k + 1
        sh[k : n - k] = highs[k : n - k] == np.lib.stride_tricks.sliding_window_view(
            highs, win
        ).max(axis=1)
        sl[k : n - k] = lows[k : n - k] == np.lib.stride_tricks.sliding_window_view(
            lows, win
        ).min(axis=1)
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


class FiboOTEStrategy:
    """Estratégia baseada em impulsão com BOS e retração OTE de Fibonacci."""

    def __init__(self, config: FiboOTEConfig | None = None) -> None:
        self.config = config or FiboOTEConfig()

    def resample_data(self, df_m1: pd.DataFrame) -> pd.DataFrame:
        """Resampleia candles M1 para o timeframe operacional (padrão M5)."""
        if not isinstance(df_m1.index, pd.DatetimeIndex):
            if "time" in df_m1.columns:
                df_m1 = df_m1.copy()
                df_m1["time"] = pd.to_datetime(df_m1["time"])
                df_m1.set_index("time", inplace=True)
            elif "timestamp" in df_m1.columns:
                df_m1 = df_m1.copy()
                df_m1["timestamp"] = pd.to_datetime(df_m1["timestamp"])
                df_m1.set_index("timestamp", inplace=True)

        rule = (
            "5min"
            if self.config.timeframe in ("M5", "5min", "5m")
            else (
                "15min"
                if self.config.timeframe in ("M15", "15min", "15m")
                else self.config.timeframe
            )
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

        if self.config.trailing_exit_ma:
            ma = self.config.trailing_exit_ma.lower()
            if ma == "ema8":
                df_res["trailing_ma"] = df_res["close"].ewm(span=8, adjust=False).mean()
            elif ma == "sma20":
                df_res["trailing_ma"] = df_res["close"].rolling(20).mean()
            elif ma == "sma9":
                df_res["trailing_ma"] = df_res["close"].rolling(9).mean()
            elif ma == "sma50":
                df_res["trailing_ma"] = df_res["close"].rolling(50).mean()
            elif ma == "ema80":
                df_res["trailing_ma"] = (
                    df_res["close"].ewm(span=80, adjust=False).mean()
                )
            elif ma == "sma200":
                df_res["trailing_ma"] = df_res["close"].rolling(200).mean()
            else:
                df_res["trailing_ma"] = df_res["close"].ewm(span=8, adjust=False).mean()

        if self.config.trend_filter_80_200:
            df_res["ema80"] = df_res["close"].ewm(span=80, adjust=False).mean()
            df_res["sma200"] = df_res["close"].rolling(200).mean()

        if self.config.confluence_ma:
            cma = self.config.confluence_ma.lower()
            if cma == "ema8":
                df_res["confluence_ma"] = (
                    df_res["close"].ewm(span=8, adjust=False).mean()
                )
            elif cma == "ema20":
                df_res["confluence_ma"] = (
                    df_res["close"].ewm(span=20, adjust=False).mean()
                )
            elif cma == "sma20":
                df_res["confluence_ma"] = df_res["close"].rolling(20).mean()
            elif cma == "sma50":
                df_res["confluence_ma"] = df_res["close"].rolling(50).mean()
            elif cma == "ema80":
                df_res["confluence_ma"] = (
                    df_res["close"].ewm(span=80, adjust=False).mean()
                )
            elif cma == "sma200":
                df_res["confluence_ma"] = df_res["close"].rolling(200).mean()

        if self.config.trend_ma:
            tma = self.config.trend_ma.lower()
            if tma == "ema8":
                df_res["trend_ma"] = df_res["close"].ewm(span=8, adjust=False).mean()
            elif tma == "ema20":
                df_res["trend_ma"] = df_res["close"].ewm(span=20, adjust=False).mean()
            elif tma == "sma20":
                df_res["trend_ma"] = df_res["close"].rolling(20).mean()
            elif tma == "sma50":
                df_res["trend_ma"] = df_res["close"].rolling(50).mean()
            elif tma == "ema80":
                df_res["trend_ma"] = df_res["close"].ewm(span=80, adjust=False).mean()
            elif tma == "sma200":
                df_res["trend_ma"] = df_res["close"].rolling(200).mean()

        return df_res

    def run_backtest(
        self,
        df_m1: pd.DataFrame,
        symbol: str,
        spread: float,
        df_ask_m1: pd.DataFrame | None = None,
    ) -> list[FiboTrade]:
        """Simulação cronológica barra a barra. Ver o docstring do módulo para o modelo."""
        result = self._run(df_m1, symbol, spread, df_ask_m1, live=False)
        assert isinstance(result, list)
        return result

    def pending_setup(
        self, df_m1: pd.DataFrame, spread: float, symbol: str = "LIVE"
    ) -> PendingSetup | None:
        """Mesma simulação do backtest, parada na última barra FECHADA da janela.

        Devolve a entrada que valeria para a barra seguinte (perna ativa, ainda sem toque,
        sem posição simulada) ou None. É a ponte usada pelo live: a decisão vem do mesmo
        código do backtest e depende só dos timestamps da janela, não de índices guardados.
        """
        result = self._run(df_m1, symbol, spread, None, live=True)
        assert result is None or isinstance(result, PendingSetup)
        return result

    def _run(
        self,
        df_m1: pd.DataFrame,
        symbol: str,
        spread: float,
        df_ask_m1: pd.DataFrame | None,
        live: bool,
    ) -> "list[FiboTrade] | PendingSetup | None":
        df = self.resample_data(df_m1)
        cfg = self.config
        k = cfg.pivot_k
        n = len(df)

        opens = df["open"].to_numpy()
        highs = df["high"].to_numpy()
        lows = df["low"].to_numpy()
        closes = df["close"].to_numpy()
        rolls = df["roll"].to_numpy() if "roll" in df.columns else None
        ts = df.index
        mas = df["trailing_ma"].to_numpy() if "trailing_ma" in df.columns else None
        emas80 = df["ema80"].to_numpy() if "ema80" in df.columns else None
        smas200 = df["sma200"].to_numpy() if "sma200" in df.columns else None
        conf_mas = (
            df["confluence_ma"].to_numpy() if "confluence_ma" in df.columns else None
        )
        trend_mas = (
            df["trend_ma"].to_numpy() if "trend_ma" in df.columns else None
        )
        swing_h, swing_l = _fractal_swings(highs, lows, k)

        # M-07: Resample de candles Ask reais se disponíveis
        df_ask = self.resample_data(df_ask_m1) if df_ask_m1 is not None else None
        ask_opens = df_ask["open"].to_numpy() if df_ask is not None else None
        ask_highs = df_ask["high"].to_numpy() if df_ask is not None else None

        def ask_adj(d: int, i: int) -> float:
            """Short recompra no ask: seus preços de saída são ask_open ou bid + spread."""
            if d != -1:
                return 0.0
            if ask_opens is not None and i < len(ask_opens):
                return float(ask_opens[i] - opens[i])
            return spread

        def close_trade(pos: _Position, i: int, price: float, reason: str) -> FiboTrade:
            unscaled_pnl = pos.d * (price - pos.entry_price) - cfg.commission_per_unit
            unscaled_r = unscaled_pnl / pos.risk
            remaining_frac = 1.0 - (cfg.partial_exit_pct if pos.partial_taken else 0.0)
            r = pos.realized_r + remaining_frac * unscaled_r
            pnl = r * pos.risk
            return FiboTrade(
                symbol=symbol,
                stage=1,
                direction="long" if pos.d == 1 else "short",
                entry_time=ts[pos.entry_idx],
                exit_time=ts[i],
                entry_price=pos.entry_price,
                stop_loss=pos.stop,
                take_profit=pos.target,
                risk_points=pos.risk,
                pnl_points=pnl,
                r_multiple=r,
                win=r > 0,
                exit_reason=reason,
            )

        def stop_hit(pos: _Position, i: int) -> bool:
            adverse = (
                lows[i]
                if pos.d == 1
                else (
                    ask_highs[i]
                    if (ask_highs is not None and i < len(ask_highs))
                    else highs[i] + spread
                )
            )
            return pos.d * (pos.stop - adverse) >= 0

        def get_stop_exit_price(pos: _Position, i: int) -> float:
            # F-05: gap além do stop preenche no open (ou pior com slippage)
            if pos.d == 1:
                return min(opens[i], pos.stop) - cfg.slippage
            else:
                open_ask = (
                    ask_opens[i]
                    if (ask_opens is not None and i < len(ask_opens))
                    else opens[i] + spread
                )
                return max(open_ask, pos.stop) + cfg.slippage

        def get_target_exit_price(pos: _Position, i: int) -> float:
            if pos.d == 1:
                return max(opens[i], pos.target) - cfg.slippage
            else:
                open_ask = (
                    ask_opens[i]
                    if (ask_opens is not None and i < len(ask_opens))
                    else opens[i] + spread
                )
                return min(open_ask, pos.target) + cfg.slippage

        def open_position(leg: _Leg, i: int) -> _Position | None:
            d = leg.d
            level = leg.level(cfg.fibo_entry)
            stop = leg.level(cfg.fibo_stop)
            slip = cfg.slippage if d == 1 else -cfg.slippage
            curr_spread = (
                (ask_opens[i] - opens[i])
                if (ask_opens is not None and i < len(ask_opens))
                else spread
            )
            entry = level + (curr_spread if d == 1 else 0.0) + slip
            risk = d * (entry - stop)
            if risk <= curr_spread * 1.5:
                return None
            if cfg.target_mode == "trailing_only":
                target = 0.0
            elif cfg.target_mode == "3R":
                target = entry + d * risk * cfg.target_r
            elif cfg.target_mode == "proj_618":
                target = leg.extreme + 0.618 * (leg.extreme - level)
            else:  # "0_percent"
                target = leg.extreme
            return _Position(
                d=d,
                entry_idx=i,
                entry_price=entry,
                stop=stop,
                target=target,
                risk=risk,
                bos_ref=leg.extreme,
                rej_extreme=(
                    (
                        lows[i]
                        if d == 1
                        else (
                            ask_highs[i]
                            if (ask_highs is not None and i < len(ask_highs))
                            else highs[i] + spread
                        )
                    )
                    if i < n
                    else 0.0
                ),
            )

        trades: list[FiboTrade] = []
        last_sh_price = last_sl_price = None
        last_sh_idx = last_sl_idx = None
        pos: _Position | None = None
        leg: _Leg | None = None
        pending_open: _PendingOpenEntry | None = None
        last_roll_idx = -1

        for i in range(k + 1, n):
            # D-02: Transição de contrato futuro com rolagem: invalida perna ativa
            if rolls is not None and rolls[i]:
                if pos is not None:
                    # a barra marcada é a última do contrato antigo: encerra nela, sem o salto
                    slip_exit = -cfg.slippage if pos.d == 1 else cfg.slippage
                    trades.append(
                        close_trade(
                            pos, i, closes[i] + ask_adj(pos.d, i) + slip_exit, "ROLLOVER"
                        )
                    )
                    pos = None
                leg = None
                pending_open = None
                last_sh_price = last_sl_price = None
                last_sh_idx = last_sl_idx = None
                last_roll_idx = i
                continue

            # 1. Swings confirmados com atraso de k barras
            chk = i - k
            # D-02: janela do fractal que cruza a rolagem mistura dois contratos
            if chk - k <= last_roll_idx:
                swing_ok = False
            else:
                swing_ok = True
            if swing_ok and swing_h[chk]:
                last_sh_price, last_sh_idx = highs[chk], chk
            if swing_ok and swing_l[chk]:
                last_sl_price, last_sl_idx = lows[chk], chk

            # 1b. Ordem a mercado armada no fechamento da barra i-1 (entry_mode="m5_close_rejection"):
            # executa no open desta barra (i), antes do gerenciamento da posição.
            if pending_open is not None and pos is None:
                po = pending_open
                pending_open = None
                d_po = po.d
                curr_spread = (
                    (ask_opens[i] - opens[i])
                    if (ask_opens is not None and i < len(ask_opens))
                    else spread
                )
                slip = cfg.slippage if d_po == 1 else -cfg.slippage
                entry_px = opens[i] + (curr_spread if d_po == 1 else 0.0) + slip
                risk_px = d_po * (entry_px - po.stop)
                if risk_px <= 0:
                    # Gap na abertura já além do stop: executa e encerra imediatamente no open
                    pos_gap = _Position(
                        d=d_po,
                        entry_idx=i,
                        entry_price=entry_px + d_po * po.risk_ref,
                        stop=po.stop,
                        target=po.extreme,
                        risk=po.risk_ref,
                    )
                    trades.append(
                        close_trade(
                            pos_gap,
                            i,
                            get_stop_exit_price(pos_gap, i),
                            "STOP_LOSS",
                        )
                    )
                    leg = None
                    continue
                if risk_px > curr_spread * 1.5:
                    if cfg.target_mode == "trailing_only":
                        target_px = 0.0
                    elif cfg.target_mode == "3R":
                        target_px = entry_px + d_po * risk_px * cfg.target_r
                    elif cfg.target_mode == "proj_618":
                        target_px = po.extreme + 0.618 * (po.extreme - po.level)
                    else:
                        target_px = po.extreme
                    if (
                        cfg.target_mode in ("trailing_only", "3R")
                        or d_po * (target_px - entry_px) > 0
                    ):
                        pos = _Position(
                            d=d_po,
                            entry_idx=i,
                            entry_price=entry_px,
                            stop=po.stop,
                            target=target_px,
                            risk=risk_px,
                            bos_ref=po.extreme,
                            rej_extreme=po.rej_extreme,
                        )

            # 2. Gerenciamento da posição aberta (barras posteriores à entrada)
            if pos is not None:
                d = pos.d
                adj = ask_adj(d, i)

                # F-06: saída por MME engatilhada na barra anterior executa no open desta barra
                if pos.pending_ma_exit:
                    slip_exit = -cfg.slippage if d == 1 else cfg.slippage
                    trades.append(
                        close_trade(pos, i, opens[i] + adj + slip_exit, "TRAILING_MA")
                    )
                    pos = None
                    leg = None
                    continue

                # F-08: controle de sessão / fim de semana
                if cfg.session_filter:
                    cur_ts = ts[i]
                    is_friday = cur_ts.weekday() == 4
                    t_str = cur_ts.strftime("%H:%M")
                    force_close = False
                    if (
                        is_friday
                        and cfg.close_on_friday
                        and t_str >= cfg.friday_close_time
                    ) or cfg.force_close_time and t_str >= cfg.force_close_time:
                        force_close = True
                    if force_close:
                        slip_exit = -cfg.slippage if d == 1 else cfg.slippage
                        trades.append(
                            close_trade(
                                pos, i, opens[i] + adj + slip_exit, "SESSION_CLOSE"
                            )
                        )
                        pos = None
                        leg = None
                        continue

                # F-07: tempo máximo de posição
                if (
                    cfg.max_position_candles > 0
                    and (i - pos.entry_idx) >= cfg.max_position_candles
                ):
                    slip_exit = -cfg.slippage if d == 1 else cfg.slippage
                    trades.append(
                        close_trade(
                            pos, i, opens[i] + adj + slip_exit, "TIME_EXPIRATION"
                        )
                    )
                    pos = None
                    leg = None
                    continue

                # F-03 & F-05: stop vigente no início da barra decide primeiro
                favorable = highs[i] if d == 1 else lows[i] + adj
                close_eff = closes[i] + adj

                exit_trade = None
                if stop_hit(pos, i):
                    stop_px = get_stop_exit_price(pos, i)
                    exit_trade = close_trade(
                        pos, i, stop_px, "LOCK_PROFIT_SL" if pos.locked else "STOP_LOSS"
                    )
                else:
                    trailing = False
                    if (
                        mas is not None
                        and i > pos.entry_idx
                        and d * (closes[i] - mas[i]) < 0
                    ):
                        trailing = (not cfg.trailing_profit_only) or d * (
                            close_eff - pos.entry_price
                        ) > 0
                    if trailing:
                        if cfg.trailing_exit_on_next_open and i < n - 1:
                            pos.pending_ma_exit = True
                        else:
                            slip_exit = -cfg.slippage if d == 1 else cfg.slippage
                            exit_trade = close_trade(
                                pos, i, close_eff + slip_exit, "TRAILING_MA"
                            )
                    elif (
                        cfg.target_mode != "trailing_only"
                        and d * (favorable - pos.target) >= 0
                    ):
                        tp_px = get_target_exit_price(pos, i)
                        exit_trade = close_trade(pos, i, tp_px, "TAKE_PROFIT")

                if exit_trade is not None:
                    trades.append(exit_trade)
                    pos = None
                    leg = None
                else:
                    # Checa realização parcial intrabar
                    if cfg.partial_exit_trigger_r is not None and not pos.partial_taken:
                        if (
                            d
                            * (
                                favorable
                                - (
                                    pos.entry_price
                                    + d * pos.risk * cfg.partial_exit_trigger_r
                                )
                            )
                            >= 0
                        ):
                            pos.realized_r += (
                                cfg.partial_exit_pct * cfg.partial_exit_trigger_r
                            )
                            pos.partial_taken = True

                    # Checa trava 2:1 ou breakeven (a trava só protege a partir da próxima barra)
                    use_lock = cfg.use_lock_2to1 or (
                        cfg.profit_lock_trigger_r is not None
                    )
                    if use_lock and not pos.locked:
                        trig_r = (
                            cfg.profit_lock_trigger_r
                            if cfg.profit_lock_trigger_r is not None
                            else cfg.lock_trigger_r
                        )
                        guar_r = (
                            cfg.profit_lock_guarantee_r
                            if cfg.profit_lock_trigger_r is not None
                            else cfg.lock_guarantee_r
                        )
                        if (
                            d * (favorable - (pos.entry_price + d * pos.risk * trig_r))
                            >= 0
                        ):
                            new_lock_stop = pos.entry_price + d * pos.risk * guar_r
                            if d * (new_lock_stop - pos.stop) > 0:
                                pos.stop = new_lock_stop
                            pos.locked = True

                    # Condução estrutural BOS a BOS (F-01 e F-03: swing confirmado com atraso k;
                    # stop atualizado no fechamento de i só passa a valer em i+1).
                    if cfg.bos_swing_trailing:
                        if (
                            d == 1
                            and last_sh_idx is not None
                            and last_sh_idx >= pos.entry_idx
                            and last_sh_price is not None
                            and last_sh_price > pos.bos_ref
                        ):
                            pos.bos_ref = last_sh_price
                        elif (
                            d == -1
                            and last_sl_idx is not None
                            and last_sl_idx >= pos.entry_idx
                            and last_sl_price is not None
                            and last_sl_price < pos.bos_ref
                        ):
                            pos.bos_ref = last_sl_price

                        if pos.bos_ref > 0 and d * (closes[i] - pos.bos_ref) > 0:
                            pos.bos_ref = highs[i] if d == 1 else lows[i]
                            swing_stop = None
                            if (
                                d == 1
                                and last_sl_price is not None
                                and last_sl_idx is not None
                                and last_sl_idx >= pos.entry_idx - k
                            ):
                                swing_stop = last_sl_price
                            elif (
                                d == -1
                                and last_sh_price is not None
                                and last_sh_idx is not None
                                and last_sh_idx >= pos.entry_idx - k
                            ):
                                swing_stop = last_sh_price + spread
                            cand_stop = (
                                swing_stop
                                if swing_stop is not None
                                else (
                                    pos.rej_extreme if pos.rej_extreme > 0 else pos.stop
                                )
                            )
                            if d * (cand_stop - pos.stop) > 0:
                                pos.stop = cand_stop
                                pos.locked = True
                continue

            # 3. Nova perna por quebra de estrutura (BOS), confirmada no fechamento de i
            if leg is None and last_sh_price is not None and last_sl_price is not None:
                if last_sh_idx > last_sl_idx and closes[i] > last_sh_price:
                    cand = _Leg(d=1, origin=last_sl_price, extreme=highs[i], bos_idx=i)
                elif last_sl_idx > last_sh_idx and closes[i] < last_sl_price:
                    cand = _Leg(d=-1, origin=last_sh_price, extreme=lows[i], bos_idx=i)
                else:
                    cand = None
                if (
                    cand is not None
                    and abs(cand.extreme - cand.origin)
                    > spread * cfg.min_leg_spread_mult
                ):
                    leg = cand

            # 4. Perna ativa: F-01 só opera a partir da barra seguinte ao BOS
            if leg is None or leg.bos_idx >= i:
                continue
            leg.candles += 1
            if leg.candles > cfg.max_holding_candles:
                leg = None
                continue
            if leg.touched and cfg.entry_mode == "limit":
                continue

            d = leg.d
            level = leg.level(cfg.fibo_entry)
            touch = lows[i] if d == 1 else highs[i]

            if cfg.entry_mode == "m5_close_rejection":
                # Se rompeu a origem estrutural (1.000), invalida a perna imediatamente
                if d * (leg.origin - touch) >= 0:
                    leg = None
                    continue
                in_zone = d * (level - touch) >= 0
                if in_zone:
                    leg.touched = True
                ma_touched = (
                    (lows[i] <= conf_mas[i] <= highs[i])
                    if (cfg.confluence_ma and conf_mas is not None)
                    else True
                )
                if in_zone and ma_touched:
                    # Espera o fechamento da barra i; a entrada só ocorre no open de i+1.
                    # Por isso, os dados da barra i (close[i], high[i], low[i], médias[i])
                    # já estão fechados no momento em que a ordem para i+1 é decidida.
                    in_session = True
                    if cfg.session_filter and cfg.session_windows:
                        t_str = ts[i].strftime("%H:%M")
                        in_session = any(
                            w_start <= t_str < w_end
                            for w_start, w_end in cfg.session_windows
                        )
                    rej_bound = (
                        leg.level(cfg.fibo_rejection_max)
                        if cfg.fibo_rejection_max is not None
                        else level
                    )
                    inv_level = leg.level(cfg.fibo_stop)
                    cond = (
                        in_session
                        and (d * (closes[i] - rej_bound) > 0)
                        and (d * (closes[i] - inv_level) > 0)
                    )
                    if cond and cfg.rejection_min_wick_ratio > 0:
                        rng_b = highs[i] - lows[i]
                        wick_len = (
                            (min(opens[i], closes[i]) - lows[i])
                            if d == 1
                            else (highs[i] - max(opens[i], closes[i]))
                        )
                        cond = rng_b > 0 and (
                            wick_len >= cfg.rejection_min_wick_ratio * rng_b
                        )
                    if (
                        cond
                        and cfg.trend_filter_80_200
                        and emas80 is not None
                        and smas200 is not None
                    ):
                        if d == 1 and emas80[i] <= smas200[i]:
                            cond = False
                        if d == -1 and emas80[i] >= smas200[i]:
                            cond = False
                    if cond and cfg.trend_ma and trend_mas is not None:
                        t_ma = trend_mas[i]
                        if d == 1 and closes[i] <= t_ma:
                            cond = False
                        if d == -1 and closes[i] >= t_ma:
                            cond = False
                        if cond and cfg.trend_ma_slope and i > 0:
                            slope = trend_mas[i] - trend_mas[i - 1]
                            if d == 1 and slope <= cfg.trend_ma_min_slope:
                                cond = False
                            if d == -1 and slope >= -cfg.trend_ma_min_slope:
                                cond = False
                    if cond:
                        curr_spread = (
                            (ask_opens[i] - opens[i])
                            if (ask_opens is not None and i < len(ask_opens))
                            else spread
                        )
                        c_ref = closes[i] + (curr_spread if d == 1 else 0.0)
                        if cfg.stop_mode == "rejection_candle":
                            stop_px = (
                                lows[i]
                                if d == 1
                                else (
                                    ask_highs[i]
                                    if (ask_highs is not None and i < len(ask_highs))
                                    else highs[i] + spread
                                )
                            )
                        else:
                            stop_px = inv_level
                        risk_ref = d * (c_ref - stop_px)
                        if risk_ref > curr_spread * 1.5 and (
                            cfg.target_mode in ("trailing_only", "3R")
                            or d * (leg.extreme - c_ref) > 0
                        ):
                            rej_ext = (
                                lows[i]
                                if d == 1
                                else (
                                    ask_highs[i]
                                    if (ask_highs is not None and i < len(ask_highs))
                                    else highs[i] + spread
                                )
                            )
                            pending_open = _PendingOpenEntry(
                                d=d,
                                stop=stop_px,
                                level=level,
                                extreme=leg.extreme,
                                risk_ref=risk_ref,
                                bos_idx=leg.bos_idx,
                                rej_extreme=rej_ext,
                            )
                    leg = None
                    continue
                if not leg.touched:
                    ext = highs[i] if d == 1 else lows[i]
                    if d * (ext - leg.extreme) > 0:
                        leg.extreme = ext
                continue

            # F-08: filtro de sessão para novas entradas (modo limit)
            if cfg.session_filter and cfg.session_windows:
                cur_ts = ts[i]
                t_str = cur_ts.strftime("%H:%M")
                if not any(
                    w_start <= t_str < w_end for w_start, w_end in cfg.session_windows
                ):
                    continue

            # F-04: toque contra o nível calculado até a barra i-1
            if d * (level - touch) >= 0:
                # Modo "limit": a ordem executa no toque intrabar (close[i] ainda não existe);
                # todo filtro adicional usa estritamente a barra anterior (i-1).
                if (
                    cfg.trend_filter_80_200
                    and emas80 is not None
                    and smas200 is not None
                ):
                    if d == 1 and emas80[i - 1] <= smas200[i - 1]:
                        continue
                    if d == -1 and emas80[i - 1] >= smas200[i - 1]:
                        continue
                if cfg.trend_ma and trend_mas is not None:
                    t_ma = trend_mas[i - 1]
                    if d == 1 and closes[i - 1] <= t_ma:
                        continue
                    if d == -1 and closes[i - 1] >= t_ma:
                        continue
                    if cfg.trend_ma_slope and i > 1:
                        slope = trend_mas[i - 1] - trend_mas[i - 2]
                        if d == 1 and slope <= cfg.trend_ma_min_slope:
                            continue
                        if d == -1 and slope >= -cfg.trend_ma_min_slope:
                            continue
                if cfg.confluence_ma and conf_mas is not None:
                    c_ma = conf_mas[i - 1]
                    if not (lows[i - 1] <= c_ma <= highs[i - 1]):
                        continue

                leg.touched = True
                pos = open_position(leg, i)
                if pos is not None and cfg.check_intrabar_sl and stop_hit(pos, i):
                    slip_exit = -cfg.slippage if d == 1 else cfg.slippage
                    trades.append(
                        close_trade(pos, i, pos.stop + slip_exit, "INTRABAR_STOP_LOSS")
                    )
                    pos = None
                    leg = None
            else:
                # só agora a barra i pode expandir a perna (vale a partir de i+1)
                ext = highs[i] if d == 1 else lows[i]
                if d * (ext - leg.extreme) > 0:
                    leg.extreme = ext
        if live:
            if cfg.entry_mode == "m5_close_rejection":
                if pos is not None or pending_open is None or n < 1:
                    return None
                po = pending_open
                slip = cfg.slippage if po.d == 1 else -cfg.slippage
                entry_px = closes[n - 1] + (spread if po.d == 1 else 0.0) + slip
                risk_px = po.d * (entry_px - po.stop)
                if risk_px <= spread * 1.5:
                    return None
                if cfg.target_mode == "trailing_only":
                    target_px = 0.0
                elif cfg.target_mode == "3R":
                    target_px = entry_px + po.d * risk_px * cfg.target_r
                elif cfg.target_mode == "proj_618":
                    target_px = po.extreme + 0.618 * (po.extreme - po.level)
                else:
                    target_px = po.extreme
                return PendingSetup(
                    direction="long" if po.d == 1 else "short",
                    entry_price=entry_px,
                    stop_loss=po.stop,
                    take_profit=target_px,
                    risk=risk_px,
                    bos_time=ts[po.bos_idx],
                    candles_left=1,
                )
            if pos is not None or leg is None or leg.touched or n < 1:
                return None
            # F-08: filtro de sessão para novas ordens limite pendentes na barra seguinte (n)
            if cfg.session_filter and cfg.session_windows:
                bar_mins = (
                    15
                    if cfg.timeframe in ("M15", "15min", "15m")
                    else (60 if cfg.timeframe in ("H1", "1h", "60min") else 5)
                )
                next_ts = ts[-1] + pd.Timedelta(minutes=bar_mins)
                t_str = next_ts.strftime("%H:%M")
                if not any(
                    w_start <= t_str < w_end for w_start, w_end in cfg.session_windows
                ):
                    return None
            if (
                cfg.trend_filter_80_200
                and emas80 is not None
                and smas200 is not None
            ):
                if leg.d == 1 and emas80[n - 1] <= smas200[n - 1]:
                    return None
                if leg.d == -1 and emas80[n - 1] >= smas200[n - 1]:
                    return None
            if cfg.trend_ma and trend_mas is not None:
                t_ma = trend_mas[n - 1]
                if leg.d == 1 and closes[n - 1] <= t_ma:
                    return None
                if leg.d == -1 and closes[n - 1] >= t_ma:
                    return None
                if cfg.trend_ma_slope and n > 1:
                    slope = trend_mas[n - 1] - trend_mas[n - 2]
                    if leg.d == 1 and slope <= cfg.trend_ma_min_slope:
                        return None
                    if leg.d == -1 and slope >= -cfg.trend_ma_min_slope:
                        return None
            if cfg.confluence_ma and conf_mas is not None:
                c_ma = conf_mas[n - 1]
                if not (lows[n - 1] <= c_ma <= highs[n - 1]):
                    return None
            # a próxima barra incrementa `candles` antes de testar a validade
            if leg.candles + 1 > cfg.max_holding_candles:
                return None
            nxt = open_position(leg, n)
            if nxt is None:
                return None
            return PendingSetup(
                direction="long" if leg.d == 1 else "short",
                entry_price=nxt.entry_price,
                stop_loss=nxt.stop,
                take_profit=nxt.target,
                risk=nxt.risk,
                bos_time=ts[leg.bos_idx],
                candles_left=cfg.max_holding_candles - leg.candles,
            )
        # F-07: posição ainda aberta no fim dos dados é encerrada no último fechamento,
        # em vez de sumir da conta (viés de sobrevivência).
        if pos is not None:
            slip_exit = -cfg.slippage if pos.d == 1 else cfg.slippage
            trades.append(
                close_trade(
                    pos,
                    n - 1,
                    closes[n - 1] + ask_adj(pos.d, n - 1) + slip_exit,
                    "END_OF_DATA",
                )
            )

        return trades

    # Alias canônico
    run = run_backtest
