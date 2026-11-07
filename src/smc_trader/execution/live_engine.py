"""Motor de Execução Autônoma em Tempo Real (Live Trading Engine) para MetaTrader 5."""

import logging
from dataclasses import dataclass, field
from typing import Any, Callable
import pandas as pd

from smc_trader.analysis import analyze
from smc_trader.backtest.limits import DailyLimitsTracker
from smc_trader.backtest.session import SessionManager
from smc_trader.backtest.trailing import TrailingManager
from smc_trader.config import BacktestConfig, ZoneConfig
from smc_trader.data.resample import resample_ohlc
from smc_trader.execution.mt5_interface import BaseMT5Client
from smc_trader.execution.sizing import calculate_lot_size
from smc_trader.execution.types import LivePosition, OrderRequest, OrderResult
from smc_trader.structure.market_structure import detect_structure
from smc_trader.structure.pivots import find_pivots
from smc_trader.zones.orderblock import Zone

logger = logging.getLogger("smc.live")


@dataclass
class SymbolRuntimeState:
    symbol: str
    config: BacktestConfig
    magic: int
    model_name: str = "SMC-DayFlow"
    macro_tf: str = "M15"
    require_sweep: bool = False
    blocks_filter: list[str] = field(default_factory=lambda: ["OB"])
    active_zones: list[Zone] = field(default_factory=list)
    zone_states: dict[tuple[pd.Timestamp, pd.Timestamp], dict[str, Any]] = field(
        default_factory=dict
    )
    trailing_mgr: TrailingManager | None = None
    current_position: LivePosition | None = None
    last_processed_m1_time: pd.Timestamp | None = None


class LiveTradingEngine:
    """Motor autônomo que monitora o mercado em tempo real e opera diretamente no MetaTrader 5."""

    def __init__(
        self,
        client: BaseMT5Client,
        symbol_configs: dict[str, BacktestConfig],
        symbol_blocks: dict[str, list[str]] | None = None,
        symbol_models: dict[str, str] | None = None,
        symbol_macro_tfs: dict[str, str] | None = None,
        symbol_sweeps: dict[str, bool] | None = None,
        risk_pct: float = 1.0,
        pivot_k_htf: int = 3,
        notification_callback: Callable[[str], None] | None = None,
    ) -> None:
        self.client = client
        self.symbol_configs = symbol_configs
        self.risk_pct = risk_pct
        self.pivot_k_htf = pivot_k_htf
        self.notify = notification_callback or (lambda msg: logger.info(msg))

        self.runtimes: dict[str, SymbolRuntimeState] = {}
        self.session_mgrs: dict[str, SessionManager] = {}
        self.limits_trackers: dict[str, DailyLimitsTracker] = {}
        self.running = False

        blocks_map = symbol_blocks or {}
        models_map = symbol_models or {}
        tfs_map = symbol_macro_tfs or {}
        sweeps_map = symbol_sweeps or {}
        magic_base = 888100
        for idx, (sym, cfg) in enumerate(symbol_configs.items(), start=1):
            magic = magic_base + idx
            bf = blocks_map.get(sym, ["OB"])
            model_name = models_map.get(sym, "SMC-DayFlow")
            macro_tf = tfs_map.get(sym, "M15")
            req_sweep = sweeps_map.get(sym, False)
            self.runtimes[sym] = SymbolRuntimeState(
                symbol=sym,
                config=cfg,
                magic=magic,
                model_name=model_name,
                macro_tf=macro_tf,
                require_sweep=req_sweep,
                blocks_filter=bf,
            )
            self.session_mgrs[sym] = SessionManager(cfg.session)
            self.limits_trackers[sym] = DailyLimitsTracker(cfg.limits)

    def process_symbol_tick(
        self, symbol: str, now_utc: pd.Timestamp | None = None
    ) -> None:
        """Executa um ciclo completo de análise e decisão para um ativo."""
        if symbol not in self.runtimes:
            return

        state = self.runtimes[symbol]
        cfg = state.config
        session_mgr = self.session_mgrs[symbol]
        limits_tracker = self.limits_trackers[symbol]

        # 1. Obtém candles recentes de M1 (suficientes para cálculo de H1/M15 e médias)
        candles_count = 2000 if state.macro_tf in ("H1", "H4") else 450
        candles_m1_raw = self.client.get_candles(
            symbol, timeframe="M1", count=candles_count
        )
        if candles_m1_raw.empty or len(candles_m1_raw) < 50:
            return

        # L-03: Descartar a barra corrente em formação (ainda aberta) e operar apenas em barras fechadas
        closed_candles = candles_m1_raw.iloc[:-1]
        if closed_candles.empty or len(closed_candles) < 49:
            return

        last_closed_time = closed_candles.index[-1]
        if state.last_processed_m1_time == last_closed_time:
            # Barra fechada já processada; aguarda fechamento da próxima barra M1
            return
        state.last_processed_m1_time = last_closed_time

        candles_m1 = closed_candles
        now = now_utc or last_closed_time

        # 2. Sincroniza posições abertas no MT5 com o estado interno
        open_positions = self.client.get_open_positions(
            symbol=symbol, magic=state.magic
        )
        if open_positions:
            state.current_position = open_positions[0]
        else:
            state.current_position = None
            state.trailing_mgr = None

        # 3. Gerenciamento de posição aberta (Trailing Stop e Fechamento de Sessão)
        if state.current_position is not None:
            pos = state.current_position

            # A. Fechamento forçado de fim de sessão (ex: 21:00 UTC)
            if session_mgr.should_force_close(now):
                self.notify(
                    f"⏰ [{symbol}] Fechamento forçado de sessão às {now.strftime('%H:%M UTC')}. Encerrando posição #{pos.ticket}."
                )
                self.client.close_position(pos.ticket)
                limits_tracker.record_trade(now, r_multiple=0.0)
                state.current_position = None
                return

            # B. Trailing Stop dinâmico (Trailing BOS M1 ou EMA)
            if cfg.trailing.mode == "bos":
                pivots_m1 = find_pivots(candles_m1, k=2)
                events_m1 = detect_structure(candles_m1, pivots_m1)
                needed_dir = "up" if pos.direction == "long" else "down"
                curr_bos = next(
                    (
                        e
                        for e in reversed(events_m1)
                        if e.kind == "BOS" and e.direction == needed_dir
                    ),
                    None,
                )

                if state.trailing_mgr is None:
                    state.trailing_mgr = TrailingManager(cfg.trailing, pos.stop_loss)

                c_curr = candles_m1.iloc[-1]
                should_exit, new_sl_price, reason = state.trailing_mgr.check_and_update(
                    pos,
                    c_curr["open"],
                    c_curr["high"],
                    c_curr["low"],
                    c_curr["close"],
                    now,
                    current_bos=curr_bos,
                )

                # Se o trailing gerou um novo nível de stop loss protetor, atualiza no MT5!
                if (
                    state.trailing_mgr.current_stop != pos.stop_loss
                    and state.trailing_mgr.current_stop is not None
                ):
                    updated_sl = state.trailing_mgr.current_stop
                    sym_info = self.client.get_symbol_info(symbol)
                    updated_sl = round(updated_sl, sym_info.digits)
                    if updated_sl != pos.stop_loss:
                        success = self.client.modify_position(
                            pos.ticket,
                            stop_loss=updated_sl,
                            take_profit=pos.take_profit,
                        )
                        if success:
                            self.notify(
                                f"🛡️ [{symbol}] Trailing Stop atualizado para {updated_sl} (Ticket #{pos.ticket})"
                            )
                            pos.stop_loss = updated_sl

            return

        # 4. Avaliação de novas entradas (se não houver posição aberta)
        allowed_session = session_mgr.is_trade_allowed(now)
        allowed_limits = limits_tracker.can_trade(now)
        if not (allowed_session and allowed_limits):
            return

        # A. Constrói Timeframe Macro do Modelo e analisa zonas institucionais
        candles_macro = resample_ohlc(candles_m1, state.macro_tf)
        if len(candles_macro) < 15:
            return

        allowed_blocks = state.blocks_filter or ["OB"]
        zcfg = ZoneConfig(blocks_filter=allowed_blocks, breaker_require_imbalance=True)
        analysis = analyze(candles_macro, pivot_k=self.pivot_k_htf, config=zcfg)
        all_zones = analysis.zones + analysis.breakers

        # Se o modelo exigir varredura prévia de liquidez (Wyckoff Spring/UTAD)
        if state.require_sweep:
            all_zones = [z for z in all_zones if z.swept_liquidity]

        # Atualiza dicionário de estados de zonas
        for z in all_zones:
            k = (z.candle_time, z.created_at)
            if k not in state.zone_states:
                state.zone_states[k] = {"state": "UNTOUCHED", "touch_time": None}

        # B. Avalia toque e gatilho no candle M1 atual
        c_last = candles_m1.iloc[-1]
        _, c_high, c_low, c_close = (
            float(c_last["open"]),
            float(c_last["high"]),
            float(c_last["low"]),
            float(c_last["close"]),
        )

        pivots_m1 = find_pivots(candles_m1, k=2)
        events_m1 = detect_structure(candles_m1, pivots_m1)
        m1_chochs = {(e.direction, e.time): e for e in events_m1 if e.kind == "CHoCH"}

        for zone in all_zones:
            k = (zone.candle_time, zone.created_at)
            z_info = state.zone_states[k]
            if z_info["state"] == "CONSUMED":
                continue

            long = zone.direction == "long"

            # 1. Detecção do Primeiro Toque
            if z_info["state"] == "UNTOUCHED":
                touched = (c_low <= zone.high) if long else (c_high >= zone.low)
                if touched:
                    z_info["touch_time"] = now
                    if cfg.entry_mode == "touch":
                        # Entrada imediata a mercado no toque
                        z_info["state"] = "CONSUMED"
                        self._trigger_entry(
                            symbol, zone, c_close, now, entry_mode="touch"
                        )
                        return
                    else:
                        # Arma a zona para confirmação M1 (CHoCH)
                        z_info["state"] = "ARMED"
                        self.notify(
                            f"🎯 [{symbol}] Zona {zone.kind} {zone.direction.upper()} armada no toque ({zone.low} - {zone.high}). Aguardando confirmação M1..."
                        )

            # 2. Confirmação por Micro-CHoCH M1
            elif z_info["state"] == "ARMED":
                needed_dir = "up" if long else "down"
                choch = m1_chochs.get((needed_dir, last_time))
                if choch is not None and (zone.low <= c_close <= zone.high):
                    z_info["state"] = "CONSUMED"
                    m1_swing = choch.range_low if long else choch.range_high
                    self._trigger_entry(
                        symbol,
                        zone,
                        c_close,
                        now,
                        entry_mode="confirmation",
                        m1_swing=m1_swing,
                    )
                    return

    def _trigger_entry(
        self,
        symbol: str,
        zone: Zone,
        entry_price: float,
        t: pd.Timestamp,
        entry_mode: str,
        m1_swing: float | None = None,
    ) -> OrderResult | None:
        """Calcula lote, posiciona Stop Loss e Take Profit e despacha ordem ao MetaTrader 5."""
        state = self.runtimes[symbol]
        cfg = state.config
        long = zone.direction == "long"
        sym_info = self.client.get_symbol_info(symbol)

        # 1. Posicionamento do Stop Loss
        if cfg.stop_mode == "m1_swing" and m1_swing is not None:
            stop_loss = m1_swing
        elif cfg.stop_mode == "swing":
            stop_loss = zone.range_low if long else zone.range_high
        else:
            stop_loss = zone.low if long else zone.high

        # Verificação de sanidade
        if (long and entry_price <= stop_loss) or (
            not long and entry_price >= stop_loss
        ):
            logger.warning(
                f"[{symbol}] Entrada inválida: preço {entry_price} além do stop {stop_loss}"
            )
            return None

        # 2. Posicionamento do Take Profit (Fixo 1:3 R:R)
        risk = abs(entry_price - stop_loss)
        target_r = cfg.target_r if cfg.target_r > 0 else 3.0
        take_profit = (
            entry_price + (target_r * risk) if long else entry_price - (target_r * risk)
        )

        # Formata preços conforme dígitos do ativo
        entry_price = round(entry_price, sym_info.digits)
        stop_loss = round(stop_loss, sym_info.digits)
        take_profit = round(take_profit, sym_info.digits)

        # 3. Dimensionamento de Lote (Position Sizing)
        acc_info = self.client.get_account_info()
        lot = calculate_lot_size(
            equity=acc_info.equity,
            risk_pct=self.risk_pct,
            entry_price=entry_price,
            stop_loss=stop_loss,
            symbol_info=sym_info,
        )

        order_req = OrderRequest(
            symbol=symbol,
            direction=zone.direction,
            volume=lot,
            order_type="market",
            price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            magic=state.magic,
            comment=f"{state.model_name[:12]}",
        )

        self.notify(
            f"🚀 [{symbol}] [{state.model_name}] DISPARANDO ORDEM {zone.direction.upper()}: "
            f"Lote: {lot} | Entrada: {entry_price} | SL: {stop_loss} | TP: {take_profit} (R:R 1:{target_r:.0f})"
        )

        result = self.client.send_order(order_req)
        if result.success:
            self.notify(
                f"✅ [{symbol}] Ordem executada com sucesso! Ticket: #{result.ticket} @ {result.price}"
            )
            state.trailing_mgr = TrailingManager(cfg.trailing, stop_loss)
        else:
            self.notify(
                f"❌ [{symbol}] Falha ao executar ordem: {result.comment} (Código: {result.error_code})"
            )

        return result
