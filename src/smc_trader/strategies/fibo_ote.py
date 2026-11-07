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

Suposições ainda NÃO tratadas (ver docs/BACKLOG_CORRECOES.md): gap além do stop (F-05),
saída por MME no próprio fechamento (F-06), posição aberta no fim dos dados e limite de
tempo de posição (F-07), sessão e fim de semana (F-08), custos de comissão/slippage (F-10).
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
    partial_exit_trigger_r: float | None = (
        None  # Gatilho de realização parcial em R (ex: 1.0, 1.5, 2.0)
    )
    partial_exit_pct: float = (
        0.0  # Fração da mão encerrada na parcial (ex: 0.5 para 50%)
    )
    trend_filter_80_200: bool = (
        False  # Long só se EMA80 > SMA200, Short só se EMA80 < SMA200
    )
    confluence_ma: str | None = (
        None  # Exige toque na média móvel na entrada ('ema8', 'sma20', etc.)
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


def _fractal_swings(
    highs: np.ndarray, lows: np.ndarray, k: int
) -> tuple[np.ndarray, np.ndarray]:
    """Marca o fractal no índice central (janela de 2k+1). Só é conhecido k barras depois."""
    n = len(highs)
    sh = np.zeros(n, dtype=bool)
    sl = np.zeros(n, dtype=bool)
    if n < 2 * k + 1:
        return sh, sl
    win = 2 * k + 1
    sh[k : n - k] = highs[k : n - k] == np.lib.stride_tricks.sliding_window_view(
        highs, win
    ).max(axis=1)
    sl[k : n - k] = lows[k : n - k] == np.lib.stride_tricks.sliding_window_view(
        lows, win
    ).min(axis=1)
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

        return df_res

    def run_backtest(
        self, df_m1: pd.DataFrame, symbol: str, spread: float
    ) -> list[FiboTrade]:
        """Simulação cronológica barra a barra. Ver o docstring do módulo para o modelo."""
        df = self.resample_data(df_m1)
        cfg = self.config
        k = cfg.pivot_k
        n = len(df)

        opens = df["open"].to_numpy()
        highs = df["high"].to_numpy()
        lows = df["low"].to_numpy()
        closes = df["close"].to_numpy()
        ts = df.index
        mas = df["trailing_ma"].to_numpy() if "trailing_ma" in df.columns else None
        emas80 = df["ema80"].to_numpy() if "ema80" in df.columns else None
        smas200 = df["sma200"].to_numpy() if "sma200" in df.columns else None
        conf_mas = (
            df["confluence_ma"].to_numpy() if "confluence_ma" in df.columns else None
        )
        swing_h, swing_l = _fractal_swings(highs, lows, k)

        def ask_adj(d: int) -> float:
            """Short recompra no ask: seus preços de saída são `bid + spread`."""
            return spread if d == -1 else 0.0

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
            adverse = lows[i] if pos.d == 1 else highs[i] + spread
            return pos.d * (pos.stop - adverse) >= 0

        def get_stop_exit_price(pos: _Position, i: int) -> float:
            # F-05: gap além do stop preenche no open (ou pior com slippage)
            if pos.d == 1:
                return min(opens[i], pos.stop) - cfg.slippage
            else:
                return max(opens[i] + spread, pos.stop) + cfg.slippage

        def get_target_exit_price(pos: _Position, i: int) -> float:
            if pos.d == 1:
                return max(opens[i], pos.target) - cfg.slippage
            else:
                return min(opens[i] + spread, pos.target) + cfg.slippage

        def open_position(leg: _Leg, i: int) -> _Position | None:
            d = leg.d
            level = leg.level(cfg.fibo_entry)
            stop = leg.level(cfg.fibo_stop)
            slip = cfg.slippage if d == 1 else -cfg.slippage
            entry = level + (spread if d == 1 else 0.0) + slip
            risk = d * (entry - stop)
            if risk <= spread * 1.5:
                return None
            if cfg.target_mode == "3R":
                target = entry + d * risk * cfg.target_r
            elif cfg.target_mode == "proj_618":
                target = leg.extreme + 0.618 * (leg.extreme - level)
            else:  # "0_percent" e "trailing_only" (neste, o alvo não é usado)
                target = leg.extreme
            return _Position(
                d=d, entry_idx=i, entry_price=entry, stop=stop, target=target, risk=risk
            )

        trades: list[FiboTrade] = []
        last_sh_price = last_sl_price = None
        last_sh_idx = last_sl_idx = None
        pos: _Position | None = None
        leg: _Leg | None = None

        for i in range(k + 1, n):
            # 1. Swings confirmados com atraso de k barras
            chk = i - k
            if swing_h[chk]:
                last_sh_price, last_sh_idx = highs[chk], chk
            if swing_l[chk]:
                last_sl_price, last_sl_idx = lows[chk], chk

            # 2. Gerenciamento da posição aberta (barras posteriores à entrada)
            if pos is not None:
                d = pos.d
                adj = ask_adj(d)

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
                            pos, i, closes[i] + adj + slip_exit, "TIME_EXPIRATION"
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
                            pos.stop = pos.entry_price + d * pos.risk * guar_r
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
            if leg.touched:
                continue

            # F-08: filtro de sessão para novas entradas
            if cfg.session_filter and cfg.session_windows:
                cur_ts = ts[i]
                t_str = cur_ts.strftime("%H:%M")
                if not any(
                    w_start <= t_str < w_end for w_start, w_end in cfg.session_windows
                ):
                    continue

            # F-04: toque contra o nível calculado até a barra i-1
            d = leg.d
            level = leg.level(cfg.fibo_entry)
            touch = lows[i] if d == 1 else highs[i]
            if d * (level - touch) >= 0:
                # Checa filtros adicionais de tendência e confluência
                if (
                    cfg.trend_filter_80_200
                    and emas80 is not None
                    and smas200 is not None
                ):
                    if d == 1 and emas80[i] <= smas200[i]:
                        continue
                    if d == -1 and emas80[i] >= smas200[i]:
                        continue
                if cfg.confluence_ma and conf_mas is not None:
                    c_ma = conf_mas[i]
                    if not (lows[i] <= c_ma <= highs[i]):
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
        # F-07: posição ainda aberta no fim dos dados é encerrada no último fechamento,
        # em vez de sumir da conta (viés de sobrevivência).
        if pos is not None:
            slip_exit = -cfg.slippage if pos.d == 1 else cfg.slippage
            trades.append(
                close_trade(
                    pos,
                    n - 1,
                    closes[n - 1] + ask_adj(pos.d) + slip_exit,
                    "END_OF_DATA",
                )
            )

        return trades

    # Alias canônico
    run = run_backtest
