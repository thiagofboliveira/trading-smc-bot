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
    FiboModelConfig,
    ProductionConfig,
    ZoneConfig,
)
from smc_trader.data.candles import tf_minutes
from smc_trader.data.resample import resample_ohlc
from smc_trader.execution.daily_limits import (
    ConsecutiveLossCounter,
    ModelDailyLimits,
    r_multiple_from_prices,
)
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

# Campos de FiboModelConfig que não pertencem à FiboOTEConfig (o teste de mapeamento exige
# que todo o resto seja repassado, para nenhum campo do YAML ser ignorado em silêncio no live).
MODEL_FIELDS_NOT_IN_STRATEGY = frozenset(
    {"name", "strategy", "timeframe", "blocks_filter", "require_sweep", "status", "profit_lock"}
)

# Tipos de conta em que modelos não aprovados podem operar
NON_REAL_ACCOUNT_MODES = frozenset({"demo", "contest"})


def fibo_config_from_model(model_def: FiboModelConfig, timeframe: str) -> FiboOTEConfig:
    """Constrói a FiboOTEConfig de um modelo de produção (fonte única para o live)."""
    kwargs = {
        name: getattr(model_def, name)
        for name in FiboModelConfig.model_fields
        if name not in MODEL_FIELDS_NOT_IN_STRATEGY
    }
    if kwargs.get("entry_mode") not in ("limit", "m5_close_rejection"):
        kwargs["entry_mode"] = "limit"
    if kwargs.get("stop_mode") not in ("fibo", "rejection_candle"):
        kwargs["stop_mode"] = "fibo"
    if kwargs.get("session_windows") is not None:
        kwargs["session_windows"] = [tuple(w) for w in kwargs["session_windows"]]
    if model_def.profit_lock is not None:
        kwargs["profit_lock_trigger_r"] = model_def.profit_lock.trigger_r
        kwargs["profit_lock_guarantee_r"] = model_def.profit_lock.lock_r
    return FiboOTEConfig(timeframe=timeframe, **kwargs)


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
    model_status: str = "candidate"
    # Travas diárias do modelo alimentadas pelos negócios reais (mesma regra do backtest)
    model_limits: ModelDailyLimits = field(default_factory=ModelDailyLimits)
    # ticket da posição -> {"direction", "open_price", "initial_risk", "seen_at"}
    position_risk: dict[str, dict[str, Any]] = field(default_factory=dict)
    deals_initialized: bool = False


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
        # Estado do kill switch em disco: reiniciar o processo não zera a perda do dia
        self.kill_switch = KillSwitch(
            production_config.kill_switch if production_config else None,
            state_file=state_file.with_name(f"{state_file.stem}_kill_switch.json"),
        )
        self.consecutive_losses = ConsecutiveLossCounter()

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
                if model_def is None:
                    raise ValueError(
                        f"{sym}: modelo '{sym_cfg.model}' não existe em production.yaml"
                    )
                if model_def.status == "reproved":
                    logger.warning(
                        "⛔ [%s] Modelo '%s' está REPROVADO: símbolo não será operado.",
                        sym,
                        sym_cfg.model,
                    )
                    self.notify(
                        f"⛔ [{sym}] Modelo '{sym_cfg.model}' reprovado: símbolo ignorado."
                    )
                    continue
                strategy_type = model_def.strategy
                model_name = model_def.name

                fibo_cfg = fibo_config_from_model(model_def, sym_cfg.macro_tf)
                if not model_def.force_close_time and not model_def.close_on_friday:
                    self.notify(
                        f"⚠️ [{sym}] Modelo '{sym_cfg.model}' sem zeragem diária nem de sexta: "
                        "posições podem atravessar a noite e o fim de semana."
                    )
                elif not model_def.session_filter:
                    self.notify(
                        f"⚠️ [{sym}] Modelo '{sym_cfg.model}' tem zeragem configurada, mas "
                        "session_filter=false: a zeragem não é aplicada (igual ao backtest)."
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
                    model_status=model_def.status,
                    model_limits=ModelDailyLimits(
                        max_trades_per_day=model_def.max_trades_per_day,
                        max_stops_per_day=model_def.max_stops_per_day,
                        max_gains_per_day=model_def.max_gains_per_day,
                    ),
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
            state.position_risk = dict(sym_persisted.get("position_risk", {}) or {})
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

    def _deal_r_multiple(self, state: SymbolRuntimeState, deal: Any) -> float:
        """R do negócio fechado: pelo risco inicial persistido; senão o R informado pelo
        cliente; senão o sinal do PnL (±1R), conservador para a contagem de stops."""
        rec = state.position_risk.get(str(deal.position_id or deal.ticket))
        if rec is not None:
            r = r_multiple_from_prices(
                rec.get("direction", deal.direction),
                float(deal.open_price or rec.get("open_price", 0.0)),
                float(deal.close_price),
                float(rec.get("initial_risk", 0.0)),
            )
            if r is not None:
                return r
        if deal.r_multiple:
            return float(deal.r_multiple)
        logger.warning(
            "[%s] Negócio #%s sem risco inicial conhecido: R estimado pelo sinal do PnL.",
            state.symbol,
            deal.ticket,
        )
        if deal.pnl < 0:
            return -1.0
        if deal.pnl > 0:
            return 1.0
        return 0.0

    def _sync_deals_and_limits(self, symbol: str, now: pd.Timestamp) -> None:
        """Alimenta as travas diárias com os negócios reais do robô (L-05).

        Só entram negócios com o número mágico do símbolo (ou de posição que o motor
        registrou): trades manuais e de outros robôs não travam o dia. Na primeira
        sincronização após a partida, o histórico das últimas 24h reconstrói os contadores
        sem repetir notificações.
        """
        state = self.runtimes[symbol]
        tracker = self.limits_trackers[symbol]
        deals = self.client.get_closed_deals(symbol=symbol, days=1)
        first_sync = not state.deals_initialized
        state.deals_initialized = True
        for deal in sorted(deals, key=lambda d: pd.Timestamp(d.close_time)):
            if deal.ticket in state.processed_deal_tickets:
                continue
            own = deal.magic == state.magic or str(deal.position_id) in state.position_risk
            if not own:
                continue
            state.processed_deal_tickets.add(deal.ticket)
            r_mult = self._deal_r_multiple(state, deal)
            close_t = pd.Timestamp(deal.close_time)
            tracker.record_trade(close_t, r_multiple=r_mult)
            state.model_limits.record_trade(close_t, r_mult)
            self.consecutive_losses.record_trade(close_t, r_mult)
            if first_sync:
                continue
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

    def _emergency_shutdown(self, symbol: str, reason: str) -> None:
        """Parada de emergência: cancela pendentes e fecha posições SÓ deste robô."""
        self.kill_switch.trigger_reason = reason
        self.kill_switch.execute_emergency_shutdown(
            self.client,
            magics={rt.magic for rt in self.runtimes.values()},
            pending_tickets=[
                rt.pending_order_ticket
                for rt in self.runtimes.values()
                if rt.pending_order_ticket
            ],
        )
        for rt in self.runtimes.values():
            rt.pending_order_ticket = None
            rt.pending_order_price = None
            self._save_state(rt.symbol)
        self.journal.log_block(symbol, "KILL_SWITCH_EMERGENCY_SHUTDOWN", {"reason": reason})
        self.notify(f"🚨 [{symbol}] {reason}")

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
        if loss_hit and not self.kill_switch.is_active:
            self._emergency_shutdown(symbol, loss_msg)
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
            self._remember_position_risk(state, state.current_position, now)
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

    @staticmethod
    def _remember_position_risk(
        state: SymbolRuntimeState, pos: LivePosition, now: pd.Timestamp
    ) -> None:
        """Guarda o risco inicial na primeira vez que a posição é vista.

        Nesse momento o stop ainda é o original (o motor só move o stop de posição já
        observada). O registro vai para o StateStore e sobrevive a reinícios; serve à trava
        de lucro e ao cálculo do R do negócio fechado.
        """
        key = str(pos.ticket)
        if key in state.position_risk:
            return
        risk = abs(pos.open_price - pos.stop_loss) if pos.stop_loss > 0 else 0.0
        state.position_risk[key] = {
            "direction": pos.direction,
            "open_price": pos.open_price,
            "initial_risk": risk,
            "seen_at": pd.Timestamp(now).isoformat(),
        }
        # descarta registros antigos (posições encerradas há mais de 7 dias)
        cutoff = pd.Timestamp(now) - pd.Timedelta(days=7)
        for k in list(state.position_risk):
            seen = state.position_risk[k].get("seen_at")
            try:
                if seen and pd.Timestamp(seen) < cutoff and k != key:
                    del state.position_risk[k]
            except (ValueError, TypeError):
                continue

    def _entry_block_reason(
        self, symbol: str, act: FiboLiveAction, candles_m1: pd.DataFrame,
        df_m5: pd.DataFrame, sym_info: Any, acc_info: Any, now: pd.Timestamp,
    ) -> tuple[str, dict[str, Any]] | None:
        """Motivo para NÃO enviar uma entrada, ou None se pode enviar."""
        state = self.runtimes[symbol]

        # Modelo não aprovado só opera em conta demo/contest (tipo desconhecido = real)
        trade_mode = getattr(acc_info, "trade_mode", "unknown")
        if state.model_status != "approved" and trade_mode not in NON_REAL_ACCOUNT_MODES:
            return "MODEL_NOT_APPROVED_FOR_REAL_ACCOUNT", {
                "status": state.model_status,
                "trade_mode": trade_mode,
            }

        # Teto global: posições abertas + ordens pendentes dos OUTROS símbolos
        total_open = sum(
            1
            for sym, rt in self.runtimes.items()
            if sym != symbol
            and (rt.current_position is not None or rt.pending_order_ticket is not None)
        )
        if total_open >= self.max_open_trades_total:
            return "MAX_OPEN_TRADES_TOTAL_REACHED", {
                "total_open": total_open,
                "limit": self.max_open_trades_total,
            }

        if not self.limits_trackers[symbol].can_trade(now):
            return "DAILY_LIMIT_REACHED", {}
        if not state.model_limits.can_trade(now):
            return "MODEL_DAILY_LIMIT_REACHED", {}

        consec = self.consecutive_losses.current(now)
        hit, msg = self.kill_switch.check_consecutive_losses(consec)
        if hit:
            return "MAX_CONSECUTIVE_LOSSES", {"details": msg}

        if act.action_type == "MARKET_ENTRY":
            # Só entra a mercado no primeiro ciclo após o fechamento da barra do sinal.
            # Se esse ciclo foi bloqueado (spread, latência), o sinal expira em vez de
            # entrar minutos depois com stop/alvo calculados pelo close antigo.
            bar_last_m1 = df_m5.index[-1] + pd.Timedelta(
                minutes=tf_minutes(state.macro_tf) - 1
            )
            if candles_m1.index[-1] != bar_last_m1:
                return "STALE_MARKET_SIGNAL", {
                    "signal_bar": df_m5.index[-1].isoformat(),
                    "last_m1": candles_m1.index[-1].isoformat(),
                }
            # O preço corrente não pode já ter passado do stop ou do alvo
            long = act.direction == "long"
            cur = sym_info.ask if long else sym_info.bid
            exit_side = sym_info.bid if long else sym_info.ask
            d = 1 if long else -1
            if cur > 0 and (
                d * (exit_side - act.stop_loss) <= 0
                or (act.take_profit > 0 and d * (cur - act.take_profit) >= 0)
            ):
                return "PRICE_BEYOND_STOP_OR_TARGET", {
                    "price": cur,
                    "stop": act.stop_loss,
                    "target": act.take_profit,
                }
        return None

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
            current_pos_initial_risk=(
                float(
                    state.position_risk.get(str(pos_ticket), {}).get("initial_risk", 0.0)
                )
                if is_pos
                else 0.0
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
                acc_info = self.client.get_account_info()
                block = self._entry_block_reason(
                    symbol, act, candles_m1, df_m5, sym_info, acc_info, now
                )
                if block is not None:
                    reason, details = block
                    self.journal.log_block(symbol, reason, details)
                    return

                entry_p = round(act.price, sym_info.digits)
                sl_p = round(act.stop_loss, sym_info.digits)
                tp_p = round(act.take_profit, sym_info.digits)

                # L-04: Sizing com proteção de blowout. A mercado, o risco real é medido
                # do preço corrente (ask na compra, bid na venda) até o stop.
                size_ref = entry_p
                if act.action_type == "MARKET_ENTRY":
                    cur = sym_info.ask if act.direction == "long" else sym_info.bid
                    if cur > 0:
                        size_ref = cur
                lot = calculate_lot_size(
                    equity=acc_info.equity,
                    risk_pct=self.risk_pct,
                    entry_price=size_ref,
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
                is_limit = act.action_type == "PLACE_LIMIT" or (
                    act.action_type != "MARKET_ENTRY" and state.order_type == "limit"
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
                    cur_pos = state.current_position
                    d = 1 if cur_pos.direction == "long" else -1
                    if cur_pos.stop_loss > 0 and d * (new_sl - cur_pos.stop_loss) <= 0:
                        # o stop só anda a favor: nunca afrouxa a proteção
                        self.journal.log_block(
                            symbol,
                            "STOP_MODIFY_REJECTED_NOT_BETTER",
                            {"current": cur_pos.stop_loss, "proposed": new_sl, "reason": act.reason},
                        )
                        continue
                    success = self.client.modify_position(
                        act.ticket, stop_loss=new_sl, take_profit=state.current_position.take_profit
                    )
                    if success:
                        self.notify(f"🛡️ [{symbol}] Stop Loss atualizado para {new_sl} ({act.reason})")
                        state.current_position.stop_loss = new_sl

            elif act.action_type == "CLOSE_POSITION":
                self.notify(f"🚪 [{symbol}] Encerrando posição #{act.ticket} ({act.reason})")
                if self.client.close_position(act.ticket):
                    state.current_position = None
                else:
                    # mantém a posição no estado; a saída é reavaliada na próxima barra
                    self.journal.log_block(
                        symbol, "CLOSE_POSITION_FAILED", {"ticket": act.ticket, "reason": act.reason}
                    )
                    self.notify(f"❌ [{symbol}] Falha ao encerrar a posição #{act.ticket}")

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
            "position_risk": state.position_risk,
            "last_processed_m1_time": (
                state.last_processed_m1_time.isoformat()
                if state.last_processed_m1_time
                else None
            ),
        }
        self.state_store.save(data)
