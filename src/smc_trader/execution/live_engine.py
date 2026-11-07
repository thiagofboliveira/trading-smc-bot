"""Motor de Execução Autônoma em Tempo Real (Live Trading Engine) para MetaTrader 5.

Implementa conformidade integral com os requisitos de produção:
- L-01: Integração com cliente MT5 nativo ou Bridge EA (fail-closed contra mock não autorizado)
- L-02: Execução fiel da estratégia SMC Fibo OTE (ou zonas institucionais)
- L-03: Decisões tomadas estritamente em barras fechadas (descarta barra em formação)
- L-04: Sizing com tick_size correto e recusa (0.0) se min_lot exceder o risco tolerado
- L-05: Limites diários alimentados por histórico de deals reais e limite global de posições
- L-06: Suporte a ordens pendentes limite no nível Fibo OTE
- L-07: Persistência de estado JSON e reconciliação com a corretora na inicialização
- L-08: Autenticação por token e verificação de retcodes na ponte HTTP
- L-09: Saída por Trailing EMA8 / médias móveis no live
- L-10: Kill Switch (perda diária máxima %, stops consecutivos, pico de spread, latência de dados)
- L-11: Observabilidade com diário de trades estruturado em JSONL
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from smc_trader.analysis import analyze
from smc_trader.backtest.limits import DailyLimitsTracker
from smc_trader.backtest.session import SessionManager
from smc_trader.backtest.trailing import TrailingManager
from smc_trader.config import (
    BacktestConfig,
    ProductionConfig,
    ZoneConfig,
)
from smc_trader.data.resample import resample_ohlc
from smc_trader.execution.fibo_live import FiboLiveAction, FiboLiveEvaluator
from smc_trader.execution.journal import TradeJournal
from smc_trader.execution.kill_switch import KillSwitch
from smc_trader.execution.mt5_interface import BaseMT5Client
from smc_trader.execution.sizing import calculate_lot_size
from smc_trader.execution.state_store import StateStore, make_cmd_id
from smc_trader.execution.types import LivePosition, OrderRequest, OrderResult
from smc_trader.strategies.fibo_ote import FiboOTEConfig
from smc_trader.structure.market_structure import detect_structure
from smc_trader.structure.pivots import find_pivots
from smc_trader.zones.orderblock import Zone

logger = logging.getLogger("smc.live")


@dataclass
class SymbolRuntimeState:
    symbol: str
    config: BacktestConfig
    magic: int
    strategy_type: str = "fibo_ote"  # 'fibo_ote' ou 'zones'
    model_name: str = "SMC-Fibo-Trailing"
    macro_tf: str = "M5"
    order_type: str = "limit"  # 'limit' ou 'market'
    require_sweep: bool = False
    blocks_filter: list[str] = field(default_factory=lambda: ["OB"])
    active_zones: list[Zone] = field(default_factory=list)
    zone_states: dict[tuple[pd.Timestamp, pd.Timestamp], dict[str, Any]] = field(
        default_factory=dict
    )
    trailing_mgr: TrailingManager | None = None
    current_position: LivePosition | None = None
    pending_order_ticket: int | None = None
    pending_order_price: float | None = None
    last_processed_m1_time: pd.Timestamp | None = None
    processed_deal_tickets: set[int] = field(default_factory=set)


class LiveTradingEngine:
    """Motor autônomo de execução com suporte a Fibo OTE e Zonas Institucionais."""

    def __init__(
        self,
        client: BaseMT5Client,
        symbol_configs: dict[str, BacktestConfig] | None = None,
        production_config: ProductionConfig | None = None,
        symbol_blocks: dict[str, list[str]] | None = None,
        symbol_models: dict[str, str] | None = None,
        symbol_macro_tfs: dict[str, str] | None = None,
        symbol_sweeps: dict[str, bool] | None = None,
        risk_pct: float = 1.0,
        pivot_k_htf: int = 3,
        notification_callback: Callable[[str], None] | None = None,
        state_file: Path = Path("data/live_state.json"),
        journal_file: Path = Path("logs/live_trade_journal.jsonl"),
        contracts: dict[str, Any] | None = None,
    ) -> None:
        self.client = client
        self.notify = notification_callback or (lambda msg: logger.info(msg))
        self.state_store = StateStore(state_file)
        self.journal = TradeJournal(journal_file)
        self.kill_switch = KillSwitch(
            production_config.kill_switch if production_config else None
        )

        self.runtimes: dict[str, SymbolRuntimeState] = {}
        self.session_mgrs: dict[str, SessionManager] = {}
        self.limits_trackers: dict[str, DailyLimitsTracker] = {}
        self.fibo_evaluators: dict[str, FiboLiveEvaluator] = {}

        self.production_config = production_config
        if contracts is not None:
            self.contracts = contracts
        else:
            try:
                from smc_trader.config import load_config
                self.contracts = load_config().contracts
            except Exception:
                self.contracts = {}

        if production_config is not None:
            self.risk_pct = production_config.trading.risk_pct_per_trade
            self.max_open_trades_total = (
                production_config.trading.max_open_trades_total
            )
            magic_base = production_config.trading.magic_base
            for idx, (sym, sym_cfg) in enumerate(
                production_config.symbols.items(), start=1
            ):
                if not getattr(sym_cfg, "enabled", True):
                    logger.info(
                        "⏭️ [%s] Símbolo desativado em production.yaml (aguardando calibração OOS).",
                        sym,
                    )
                    continue
                magic = magic_base + idx
                model_def = production_config.models.get(sym_cfg.model)
                strategy_type = model_def.strategy if model_def else "fibo_ote"
                model_name = model_def.name if model_def else sym_cfg.model

                fibo_cfg = FiboOTEConfig(
                    timeframe=sym_cfg.macro_tf,
                    fibo_entry=model_def.fibo_entry if model_def else 0.705,
                    fibo_stop=model_def.fibo_stop if model_def else 0.790,
                    fibo_rejection_max=(
                        model_def.fibo_rejection_max if model_def else None
                    ),
                    entry_mode=(
                        model_def.entry_mode
                        if (model_def and model_def.entry_mode in ("limit", "m5_close_rejection"))
                        else "limit"
                    ),
                    stop_mode=(
                        model_def.stop_mode
                        if (model_def and model_def.stop_mode in ("fibo", "rejection_candle"))
                        else "fibo"
                    ),
                    rejection_min_wick_ratio=(
                        model_def.rejection_min_wick_ratio if model_def else 0.0
                    ),
                    target_mode=model_def.target_mode if model_def else "0_percent",
                    target_r=model_def.target_r if model_def else 3.0,
                    pivot_k=model_def.pivot_k if model_def else 3,
                    trailing_exit_ma=(
                        model_def.trailing_exit_ma if model_def else "ema8"
                    ),
                    profit_lock_trigger_r=(
                        model_def.profit_lock.trigger_r
                        if (model_def and model_def.profit_lock)
                        else None
                    ),
                    profit_lock_guarantee_r=(
                        model_def.profit_lock.lock_r
                        if (model_def and model_def.profit_lock)
                        else 0.0
                    ),
                    session_filter=(
                        model_def.session_filter if model_def else False
                    ),
                    session_windows=(
                        list(model_def.session_windows)
                        if (model_def and model_def.session_windows)
                        else None
                    ),
                    force_close_time=(
                        model_def.force_close_time if model_def else None
                    ),
                    trend_ma=(
                        model_def.trend_ma if model_def else None
                    ),
                    trend_ma_slope=(
                        model_def.trend_ma_slope if model_def else False
                    ),
                    confluence_ma=(
                        model_def.confluence_ma if model_def else None
                    ),
                )
                self.fibo_evaluators[sym] = FiboLiveEvaluator(fibo_cfg)

                bt_cfg = BacktestConfig()
                self.runtimes[sym] = SymbolRuntimeState(
                    symbol=sym,
                    config=bt_cfg,
                    magic=magic,
                    strategy_type=strategy_type,
                    model_name=model_name,
                    macro_tf=sym_cfg.macro_tf,
                    order_type=sym_cfg.order_type,
                )
                self.session_mgrs[sym] = SessionManager(bt_cfg.session)
                self.limits_trackers[sym] = DailyLimitsTracker(bt_cfg.limits)
        else:
            # Compatibilidade com configuração legada
            self.risk_pct = risk_pct
            self.max_open_trades_total = 4
            sym_configs = symbol_configs or {}
            blocks_map = symbol_blocks or {}
            models_map = symbol_models or {}
            tfs_map = symbol_macro_tfs or {}
            sweeps_map = symbol_sweeps or {}
            magic_base = 888100
            for idx, (sym, cfg) in enumerate(sym_configs.items(), start=1):
                magic = magic_base + idx
                model_name = models_map.get(sym, "SMC-DayFlow")
                macro_tf = tfs_map.get(sym, "M15")
                strategy_type = (
                    "fibo_ote"
                    if "fibo" in model_name.lower()
                    else "zones"
                )
                self.runtimes[sym] = SymbolRuntimeState(
                    symbol=sym,
                    config=cfg,
                    magic=magic,
                    strategy_type=strategy_type,
                    model_name=model_name,
                    macro_tf=macro_tf,
                    require_sweep=sweeps_map.get(sym, False),
                    blocks_filter=blocks_map.get(sym, ["OB"]),
                )
                if strategy_type == "fibo_ote":
                    self.fibo_evaluators[sym] = FiboLiveEvaluator(
                        FiboOTEConfig(timeframe=macro_tf)
                    )
                self.session_mgrs[sym] = SessionManager(cfg.session)
                self.limits_trackers[sym] = DailyLimitsTracker(cfg.limits)

        # L-07: Reconciliação na inicialização com posições abertas na corretora
        self.reconcile_startup_state()

    def reconcile_startup_state(self) -> None:
        """Reconcilia o estado do motor com o estado real do MT5 na inicialização (L-07)."""
        persisted = self.state_store.load()
        for sym, state in self.runtimes.items():
            sym_persisted = persisted.get(sym, {})
            pos_ticket = sym_persisted.get("current_position_ticket")
            reconciled_pos = self.state_store.reconcile_with_broker(
                self.client, sym, state.magic, pos_ticket
            )
            state.current_position = reconciled_pos
            if reconciled_pos:
                state.pending_order_ticket = None
                state.pending_order_price = None
                self.notify(
                    f"🔄 [{sym}] Monitorando posição reconciliada #{reconciled_pos.ticket} ({reconciled_pos.direction.upper()})"
                )
            else:
                state.pending_order_ticket = sym_persisted.get("pending_order_ticket")
                state.pending_order_price = sym_persisted.get("pending_order_price")

    def _sync_deals_and_limits(self, symbol: str, now: pd.Timestamp) -> None:
        """Sincroniza histórico de negócios do broker e alimenta o DailyLimitsTracker (L-05)."""
        state = self.runtimes[symbol]
        tracker = self.limits_trackers[symbol]
        deals = self.client.get_closed_deals(symbol=symbol, days=1)
        for deal in deals:
            if deal.ticket not in state.processed_deal_tickets:
                state.processed_deal_tickets.add(deal.ticket)
                r_mult = deal.r_multiple
                tracker.record_trade(deal.close_time, r_multiple=r_mult)
                self.journal.log_trade_close(
                    symbol=symbol,
                    ticket=deal.ticket,
                    close_price=deal.close_price,
                    pnl=deal.pnl,
                    r_multiple=r_mult,
                    reason=deal.comment or "BROKER_EXECUTION",
                )
                self.notify(
                    f"📊 [{symbol}] Trade fechado no MT5 #{deal.ticket}: PnL ${deal.pnl:.2f} ({r_mult:+.2f}R)"
                )

    def process_symbol_tick(
        self, symbol: str, now_utc: pd.Timestamp | None = None
    ) -> None:
        """Executa um ciclo completo de análise e decisão para um ativo."""
        if symbol not in self.runtimes:
            return

        state = self.runtimes[symbol]

        # 1. Obtém dados de conta e verifica Kill Switch (L-10)
        try:
            acc_info = self.client.get_account_info()
        except Exception:
            return

        now = now_utc or pd.Timestamp.now(tz="UTC")
        self.kill_switch.reset_daily_equity_if_new_day(acc_info.equity, now)

        loss_hit, loss_msg = self.kill_switch.check_daily_loss(acc_info.equity)
        if loss_hit:
            self.kill_switch.trigger_reason = loss_msg
            self.kill_switch.execute_emergency_shutdown(self.client)
            self.journal.log_block(symbol, "KILL_SWITCH_EMERGENCY_SHUTDOWN", {"reason": loss_msg})
            self.notify(f"🚨 [{symbol}] {loss_msg}")
            return

        if self.kill_switch.is_active:
            return

        # 2. Sincroniza histórico de deals com os limites diários (L-05)
        self._sync_deals_and_limits(symbol, now)

        # 3. Obtém candles M1 da corretora
        # a perna vale até max_holding_candles barras e o fractal precisa de contexto antes dela
        candles_count = 3600 if state.macro_tf in ("M15", "H1") else 1500
        candles_m1_raw = self.client.get_candles(
            symbol, timeframe="M1", count=candles_count
        )
        if candles_m1_raw.empty or len(candles_m1_raw) < 50:
            return

        # L-03: Descartar a barra corrente em formação e agir só em barras M1 fechadas
        closed_candles = candles_m1_raw.iloc[:-1]
        if closed_candles.empty or len(closed_candles) < 49:
            return

        last_closed_time = closed_candles.index[-1]
        if state.last_processed_m1_time == last_closed_time:
            return
        state.last_processed_m1_time = last_closed_time

        candles_m1 = closed_candles

        # L-10: Verificação de latência de dados (atraso > tolerância)
        delay_hit, delay_msg = self.kill_switch.check_data_delay(last_closed_time, now)
        if delay_hit:
            self.journal.log_block(symbol, "DATA_LATENCY_EXCEEDED", {"details": delay_msg})
            return

        # L-10: Verificação de anomalia de spread (pico de notícias / baixa liquidez)
        sym_info = self.client.get_symbol_info(symbol)
        contract_spec = self.contracts.get(symbol) if hasattr(self, "contracts") else None
        if contract_spec is not None and contract_spec.spread > 0:
            typical_spread = contract_spec.spread
        elif sym_info.spread > 0:
            typical_spread = sym_info.spread
        else:
            typical_spread = sym_info.point * 10 if sym_info.point > 0 else 0.0001
        current_spread = sym_info.ask - sym_info.bid
        spread_hit, spread_msg = self.kill_switch.check_spread(current_spread, typical_spread)
        if spread_hit:
            self.journal.log_block(symbol, "SPREAD_SPIKE_BLOCKED", {"details": spread_msg})
            return

        # 4. Sincroniza posição aberta local com MT5
        open_positions = self.client.get_open_positions(
            symbol=symbol, magic=state.magic
        )
        if open_positions:
            state.current_position = open_positions[0]
        else:
            state.current_position = None
            state.trailing_mgr = None

        # 5. EXECUÇÃO ESPECÍFICA POR ESTRATÉGIA (L-02)
        if state.strategy_type == "fibo_ote":
            self._process_fibo_strategy(symbol, candles_m1, sym_info, now)
        else:
            self._process_zones_strategy(symbol, candles_m1, sym_info, now)

        # L-07: Persiste estado no final do ciclo
        self._save_state(symbol)

    def _process_fibo_strategy(
        self,
        symbol: str,
        candles_m1: pd.DataFrame,
        sym_info: Any,
        now: pd.Timestamp,
    ) -> None:
        """Executa a estratégia oficial SMC Fibo OTE no live (L-02, L-06, L-09)."""
        state = self.runtimes[symbol]
        evaluator = self.fibo_evaluators.get(symbol)
        if evaluator is None:
            return

        # Estabiliza o spread com o spread contratual/típico para evitar cancelamento e rearme
        # desnecessário de ordens limites por ruído de sub-pips nos ticks
        contract_spec = self.contracts.get(symbol) if hasattr(self, "contracts") else None
        if contract_spec is not None and contract_spec.spread > 0:
            evaluator.spread = contract_spec.spread
        elif sym_info.spread > 0:
            evaluator.spread = sym_info.spread
        else:
            evaluator.spread = sym_info.point * 10 if sym_info.point > 0 else 0.0001
        df_m5 = resample_ohlc(candles_m1, state.macro_tf)
        if len(df_m5) < 5:
            return

        is_pos = state.current_position is not None
        pos_dir = state.current_position.direction if is_pos else None
        pos_entry = state.current_position.open_price if is_pos else 0.0
        pos_sl = state.current_position.stop_loss if is_pos else 0.0
        pos_ticket = state.current_position.ticket if is_pos else 0

        actions = evaluator.process_closed_m5(
            df_m5=df_m5,
            is_positioned=is_pos,
            current_pos_direction=pos_dir,
            current_pos_open_price=pos_entry,
            current_pos_stop_loss=pos_sl,
            current_pos_ticket=pos_ticket,
            current_pos_open_time=(
                state.current_position.open_time if is_pos and state.current_position else None
            ),
        )

        # L-06: a ordem limite armada acompanha o setup. Com posição, a pendente já foi
        # executada. Setup novo ou alterado: cancela e rearma. Setup extinto: só cancela.
        if is_pos:
            state.pending_order_ticket = None
            state.pending_order_price = None
        elif state.pending_order_ticket and evaluator.evaluated:
            desired = next((a for a in actions if a.action_type == "PLACE_LIMIT"), None)
            same = desired is not None and state.pending_order_price == round(
                desired.price, sym_info.digits
            )
            if same:
                actions = [a for a in actions if a.action_type != "PLACE_LIMIT"]
            else:
                actions = [
                    FiboLiveAction(
                        action_type="CANCEL_ORDER",
                        ticket=state.pending_order_ticket,
                        reason="SETUP_CHANGED" if desired else "SETUP_EXPIRED",
                    ),
                    *actions,
                ]

        for act in actions:
            if act.action_type in ("MARKET_ENTRY", "PLACE_LIMIT"):
                # L-05: Checa teto global de posições abertas na carteira
                total_open = sum(
                    1 for rt in self.runtimes.values() if rt.current_position is not None
                )
                if total_open >= self.max_open_trades_total:
                    self.journal.log_block(
                        symbol,
                        "MAX_OPEN_TRADES_TOTAL_REACHED",
                        {"total_open": total_open, "limit": self.max_open_trades_total},
                    )
                    return

                # Checa limites diários e sessão
                if not self.limits_trackers[symbol].can_trade(now):
                    self.journal.log_block(symbol, "DAILY_LIMIT_REACHED")
                    return

                acc_info = self.client.get_account_info()
                entry_p = round(act.price, sym_info.digits)
                sl_p = round(act.stop_loss, sym_info.digits)
                tp_p = round(act.take_profit, sym_info.digits)

                # L-04: Sizing com proteção de blowout
                lot = calculate_lot_size(
                    equity=acc_info.equity,
                    risk_pct=self.risk_pct,
                    entry_price=entry_p,
                    stop_loss=sl_p,
                    symbol_info=sym_info,
                )
                if lot <= 0.0:
                    self.journal.log_block(
                        symbol,
                        "SIZING_REJECTED",
                        {"reason": "min_lot exceeds risk or equity <= 0"},
                    )
                    return

                # L-07: cmd_id idempotente
                cmd_id = make_cmd_id(symbol, act.action_type, df_m5.index[-1])
                is_limit = (
                    act.action_type == "PLACE_LIMIT"
                    or state.order_type == "limit"
                )
                order_req = OrderRequest(
                    symbol=symbol,
                    direction=act.direction or "long",
                    volume=lot,
                    order_type="limit" if is_limit else "market",
                    price=entry_p,
                    stop_loss=sl_p,
                    take_profit=tp_p,
                    magic=state.magic,
                    comment=f"{state.model_name[:12]}",
                    cmd_id=cmd_id,
                )

                self.journal.log_signal(
                    symbol=symbol,
                    strategy="fibo_ote",
                    direction=order_req.direction,
                    entry_price=entry_p,
                    stop_loss=sl_p,
                    take_profit=tp_p,
                    details={"action": act.action_type, "lot": lot},
                )
                self.journal.log_order_dispatch(
                    symbol=symbol,
                    order_type=order_req.order_type,
                    direction=order_req.direction,
                    volume=lot,
                    price=entry_p,
                    stop_loss=sl_p,
                    take_profit=tp_p,
                    magic=state.magic,
                    cmd_id=cmd_id,
                )

                self.notify(
                    f"🚀 [{symbol}] [{state.model_name}] Enviando ordem {order_req.order_type.upper()} "
                    f"{order_req.direction.upper()}: Lote {lot} @ {entry_p} | SL: {sl_p} | TP: {tp_p}"
                )
                res = self.client.send_order(order_req)
                if res.success:
                    if is_limit:
                        state.pending_order_ticket = res.ticket
                        state.pending_order_price = entry_p
                    self.journal.log_order_fill(
                        symbol=symbol,
                        ticket=res.ticket,
                        requested_price=entry_p,
                        filled_price=res.price,
                        volume=lot,
                        cmd_id=cmd_id,
                    )
                    self.notify(f"✅ [{symbol}] Ordem aceita! Ticket #{res.ticket}")
                else:
                    self.journal.log_block(
                        symbol,
                        "ORDER_REJECTED_BY_BROKER",
                        {"error": res.comment, "code": res.error_code},
                    )
                    self.notify(f"❌ [{symbol}] Ordem rejeitada: {res.comment}")

            elif act.action_type == "MODIFY_STOP":
                new_sl = round(act.stop_loss, sym_info.digits)
                if is_pos and state.current_position:
                    success = self.client.modify_position(
                        act.ticket, stop_loss=new_sl, take_profit=state.current_position.take_profit
                    )
                    if success:
                        self.notify(f"🛡️ [{symbol}] Stop Loss atualizado para {new_sl} ({act.reason})")
                        state.current_position.stop_loss = new_sl

            elif act.action_type == "CLOSE_POSITION":
                self.notify(f"🚪 [{symbol}] Encerrando posição #{act.ticket} ({act.reason})")
                self.client.close_position(act.ticket)
                state.current_position = None

            elif act.action_type == "CANCEL_ORDER":
                self.notify(f"🚫 [{symbol}] Cancelando ordem pendente #{act.ticket} ({act.reason})")
                self.client.cancel_order(act.ticket)
                if act.ticket == state.pending_order_ticket:
                    state.pending_order_ticket = None
                    state.pending_order_price = None

    def _process_zones_strategy(
        self,
        symbol: str,
        candles_m1: pd.DataFrame,
        sym_info: Any,
        now: pd.Timestamp,
    ) -> None:
        """Executa a estratégia de zonas SMC (OB/CHoCH)."""
        state = self.runtimes[symbol]
        cfg = state.config
        session_mgr = self.session_mgrs[symbol]
        limits_tracker = self.limits_trackers[symbol]

        if state.current_position is not None:
            pos = state.current_position
            if session_mgr.should_force_close(now):
                self.notify(f"⏰ [{symbol}] Fechamento de sessão às {now.strftime('%H:%M')}")
                self.client.close_position(pos.ticket)
                limits_tracker.record_trade(now, r_multiple=0.0)
                state.current_position = None
                return

            if cfg.trailing.mode == "bos":
                pivots_m1 = find_pivots(candles_m1, k=2)
                events_m1 = detect_structure(candles_m1, pivots_m1)
                needed_dir = "up" if pos.direction == "long" else "down"
                curr_bos = next(
                    (e for e in reversed(events_m1) if e.kind == "BOS" and e.direction == needed_dir),
                    None,
                )
                if state.trailing_mgr is None:
                    state.trailing_mgr = TrailingManager(cfg.trailing, pos.stop_loss)
                c_curr = candles_m1.iloc[-1]
                should_exit, new_sl, reason = state.trailing_mgr.check_and_update(
                    pos, c_curr["open"], c_curr["high"], c_curr["low"], c_curr["close"], now, current_bos=curr_bos
                )
                if state.trailing_mgr.current_stop != pos.stop_loss and state.trailing_mgr.current_stop is not None:
                    updated_sl = round(state.trailing_mgr.current_stop, sym_info.digits)
                    if updated_sl != pos.stop_loss:
                        if self.client.modify_position(pos.ticket, stop_loss=updated_sl, take_profit=pos.take_profit):
                            pos.stop_loss = updated_sl
            return

        if not (session_mgr.is_trade_allowed(now) and limits_tracker.can_trade(now)):
            return

        candles_macro = resample_ohlc(candles_m1, state.macro_tf)
        if len(candles_macro) < 15:
            return

        zcfg = ZoneConfig(blocks_filter=state.blocks_filter or ["OB"], breaker_require_imbalance=True)
        analysis = analyze(candles_macro, pivot_k=3, config=zcfg)
        all_zones = analysis.zones + analysis.breakers
        if state.require_sweep:
            all_zones = [z for z in all_zones if z.swept_liquidity]

        c_last = candles_m1.iloc[-1]
        c_high, c_low, c_close = float(c_last["high"]), float(c_last["low"]), float(c_last["close"])
        for zone in all_zones:
            k = (zone.candle_time, zone.created_at)
            if k not in state.zone_states:
                state.zone_states[k] = {"state": "UNTOUCHED"}
            z_info = state.zone_states[k]
            if z_info["state"] == "CONSUMED":
                continue
            long = zone.direction == "long"
            if z_info["state"] == "UNTOUCHED":
                touched = (c_low <= zone.high) if long else (c_high >= zone.low)
                if touched:
                    z_info["state"] = "CONSUMED"
                    self._trigger_zone_entry(symbol, zone, c_close, now)
                    return

    def _trigger_zone_entry(
        self, symbol: str, zone: Zone, entry_price: float, t: pd.Timestamp
    ) -> OrderResult | None:
        state = self.runtimes[symbol]
        long = zone.direction == "long"
        sym_info = self.client.get_symbol_info(symbol)
        stop_loss = zone.range_low if long else zone.range_high
        risk = abs(entry_price - stop_loss)
        target_r = state.config.target_r if state.config.target_r > 0 else 3.0
        take_profit = entry_price + (target_r * risk) if long else entry_price - (target_r * risk)

        entry_price = round(entry_price, sym_info.digits)
        stop_loss = round(stop_loss, sym_info.digits)
        take_profit = round(take_profit, sym_info.digits)

        acc = self.client.get_account_info()
        lot = calculate_lot_size(acc.equity, self.risk_pct, entry_price, stop_loss, sym_info)
        if lot <= 0.0:
            return None

        cmd_id = make_cmd_id(symbol, "ZON", t)
        req = OrderRequest(
            symbol=symbol,
            direction=zone.direction,
            volume=lot,
            order_type="market",
            price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            magic=state.magic,
            comment=f"{state.model_name[:12]}",
            cmd_id=cmd_id,
        )
        return self.client.send_order(req)

    def _save_state(self, symbol: str) -> None:
        """Persiste estado operacional em disco (L-07)."""
        data = self.state_store.load()
        state = self.runtimes[symbol]
        data[symbol] = {
            "current_position_ticket": (
                state.current_position.ticket if state.current_position else None
            ),
            "pending_order_ticket": state.pending_order_ticket,
            "pending_order_price": state.pending_order_price,
            "last_processed_m1_time": (
                state.last_processed_m1_time.isoformat()
                if state.last_processed_m1_time
                else None
            ),
        }
        self.state_store.save(data)
