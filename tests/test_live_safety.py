"""Proteções do live: fuso do MT5, kill switch, travas diárias reais, status do modelo,
trava de lucro sem afrouxar stop e entrada a mercado com sinal vencido."""

import time
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from smc_trader.config import (
    BridgeConfig,
    ContractSpec,
    FiboModelConfig,
    KillSwitchConfig,
    ProductionConfig,
    ProductionSymbolConfig,
    ProfitLockConfig,
    TradingProductionConfig,
)
from smc_trader.execution.daily_limits import ConsecutiveLossCounter, ModelDailyLimits
from smc_trader.execution.fibo_live import FiboLiveAction, FiboLiveEvaluator
from smc_trader.execution.kill_switch import KillSwitch
from smc_trader.execution.live_engine import (
    MODEL_FIELDS_NOT_IN_STRATEGY,
    LiveTradingEngine,
    fibo_config_from_model,
)
from smc_trader.execution.mt5_interface import MockMT5Client, NativeMT5Client
from smc_trader.execution.types import ClosedTradeInfo, LivePosition, OrderRequest
from smc_trader.strategies.fibo_ote import FiboOTEConfig

KW = dict(fibo_entry=0.705, fibo_stop=0.790, target_mode="0_percent", pivot_k=2, trailing_exit_ma=None)


def _engine(tmp_path, client, status="approved", **model_kw):
    prod = ProductionConfig(
        trading=TradingProductionConfig(risk_pct_per_trade=1.0, max_open_trades_total=4, magic_base=777000),
        bridge=BridgeConfig(),
        kill_switch=KillSwitchConfig(),
        models={
            "m": FiboModelConfig(
                name="m", strategy="fibo_ote", timeframe="M5", status=status, **{**KW, **model_kw}
            )
        },
        symbols={"XAUUSD": ProductionSymbolConfig(model="m", macro_tf="M5", order_type="limit")},
    )
    return LiveTradingEngine(
        client=client,
        production_config=prod,
        notification_callback=lambda m: None,
        state_file=tmp_path / "s.json",
        journal_file=tmp_path / "j.jsonl",
        contracts={"XAUUSD": ContractSpec(spread=0.2)},
    )


def _client():
    c = MockMT5Client(initial_balance=10_000.0)
    c.connect()
    return c


# --------------------------------------------------------------------------- fuso MT5
class _FakeMT5:
    """Imita o pacote MetaTrader5: horários em segundos no fuso do servidor."""

    TIMEFRAME_M1, TIMEFRAME_M5, TIMEFRAME_M15, TIMEFRAME_H1 = 1, 5, 15, 60
    ORDER_TYPE_BUY, ORDER_TYPE_SELL, ORDER_TYPE_BUY_LIMIT, ORDER_TYPE_SELL_LIMIT = 0, 1, 2, 3
    TRADE_ACTION_DEAL, TRADE_ACTION_PENDING, TRADE_ACTION_SLTP, TRADE_ACTION_REMOVE = 1, 5, 6, 8
    ORDER_TIME_GTC = 0
    ORDER_FILLING_FOK, ORDER_FILLING_IOC, ORDER_FILLING_RETURN = 0, 1, 2
    TRADE_RETCODE_DONE = 10009

    def __init__(self, offset_s: int, tick_age_s: float = 1.0, filling_mode: int = 1):
        self.offset_s = offset_s
        self.tick_age_s = tick_age_s
        self.filling_mode = filling_mode
        self.sent: list[dict] = []
        self.frozen = False  # True: o tick não muda (mercado fechado)
        self.n = 0

    def symbol_info_tick(self, symbol):
        self.n += 0 if self.frozen else 1
        t = int(time.time() + self.offset_s - self.tick_age_s) + self.n
        return SimpleNamespace(time=t if not self.frozen else 1_700_000_000, bid=100.0, ask=100.2)

    def symbol_info(self, symbol):
        return SimpleNamespace(filling_mode=self.filling_mode)

    def copy_rates_from_pos(self, symbol, tf, start, count):
        t0 = 1_800_000_000  # segundos "do servidor"
        rows = [(t0 + 60 * i, 1.0, 2.0, 0.5, 1.5, 10) for i in range(3)]
        return np.array(
            rows,
            dtype=[("time", "i8"), ("open", "f8"), ("high", "f8"), ("low", "f8"), ("close", "f8"), ("tick_volume", "i8")],
        )

    def order_send(self, req):
        self.sent.append(req)
        return SimpleNamespace(retcode=self.TRADE_RETCODE_DONE, order=1, price=req["price"], volume=req["volume"], comment="ok")


def _native(fake, offset_hours=None):
    c = NativeMT5Client(server_utc_offset_hours=offset_hours)
    c._mt5 = fake
    c._connected = True
    return c


def test_estimativa_do_fuso_do_servidor():
    now = 1_800_000_000.0
    assert NativeMT5Client.estimate_offset_seconds(now + 7200 - 3, now) == 7200
    assert NativeMT5Client.estimate_offset_seconds(now + 10800 - 30, now) == 10800
    # tick velho (mercado fechado) não serve para estimar
    assert NativeMT5Client.estimate_offset_seconds(now + 7200 - 900, now) is None


def test_candles_do_mt5_sao_convertidos_para_utc():
    c = _native(_FakeMT5(offset_s=7200))
    assert c.get_candles("XAUUSD", "M1", 3).empty  # 1ª leitura: ainda sem saber se o tick anda
    df = c.get_candles("XAUUSD", "M1", 3)
    assert df.index[0] == pd.Timestamp(1_800_000_000 - 7200, unit="s", tz="UTC")


def test_offset_fixo_vence_a_estimativa():
    c = _native(_FakeMT5(offset_s=7200), offset_hours=3)
    df = c.get_candles("XAUUSD", "M1", 3)
    assert df.index[0] == pd.Timestamp(1_800_000_000 - 10800, unit="s", tz="UTC")


def test_sem_fuso_conhecido_nao_entrega_candles():
    fake = _FakeMT5(offset_s=7200)
    fake.frozen = True  # mercado fechado: o tick não anda
    c = _native(fake)
    for _ in range(3):
        assert c.get_candles("XAUUSD", "M1", 3).empty


def test_tick_parado_ha_uma_hora_nao_vira_fuso():
    """Idade de 1h exata parece fuso de +1h; sem o tick andar, não pode ser aceito."""
    fake = _FakeMT5(offset_s=7200, tick_age_s=3600)
    fake.frozen = True
    c = _native(fake)
    c.get_candles("XAUUSD", "M1", 3)
    assert c.server_utc_offset_seconds("XAUUSD") is None


def test_latencia_volta_a_funcionar_com_horario_utc():
    """Com horário do servidor rotulado como UTC, o atraso dava negativo e nunca bloqueava."""
    ks = KillSwitch(KillSwitchConfig(max_data_delay_seconds=180))
    now = pd.Timestamp("2026-11-23 15:00", tz="UTC")
    candle_utc = now - pd.Timedelta(minutes=10)
    assert ks.check_data_delay(candle_utc, now)[0] is True
    candle_server_as_utc = candle_utc + pd.Timedelta(hours=2)
    assert ks.check_data_delay(candle_server_as_utc, now)[0] is False  # o bug antigo


def test_ordens_nativas_usam_preco_do_tick_e_preenchimento_do_simbolo():
    fake = _FakeMT5(offset_s=0, filling_mode=2)  # só IOC
    c = _native(fake, offset_hours=0)
    c.send_order(OrderRequest("XAUUSD", "long", 0.1, "market", price=90.0, stop_loss=95.0, take_profit=110.0))
    assert fake.sent[-1]["price"] == 100.2  # ask, não o close da barra
    assert fake.sent[-1]["type_filling"] == fake.ORDER_FILLING_IOC
    c.send_order(OrderRequest("XAUUSD", "short", 0.1, "market", price=90.0, stop_loss=105.0, take_profit=90.0))
    assert fake.sent[-1]["price"] == 100.0  # bid
    c.send_order(OrderRequest("XAUUSD", "long", 0.1, "limit", price=99.0, stop_loss=95.0, take_profit=110.0))
    assert fake.sent[-1]["price"] == 99.0
    assert fake.sent[-1]["type_filling"] == fake.ORDER_FILLING_RETURN


# --------------------------------------------------------------------------- kill switch
def test_kill_switch_persiste_saldo_base_apos_reinicio(tmp_path):
    f = tmp_path / "ks.json"
    now = pd.Timestamp("2026-11-23 10:00", tz="UTC")
    ks = KillSwitch(KillSwitchConfig(max_daily_loss_pct=3.0), state_file=f)
    ks.reset_daily_equity_if_new_day(10_000.0, now)
    # processo reinicia depois de perder 2.5%
    ks2 = KillSwitch(KillSwitchConfig(max_daily_loss_pct=3.0), state_file=f)
    ks2.reset_daily_equity_if_new_day(9_750.0, now + pd.Timedelta(hours=1))
    assert ks2.starting_equity_day == 10_000.0
    assert ks2.check_daily_loss(9_650.0)[0] is True
    # dia seguinte: novo saldo base
    ks2.reset_daily_equity_if_new_day(9_650.0, now + pd.Timedelta(days=1))
    assert ks2.starting_equity_day == 9_650.0


def test_kill_switch_persiste_parada_ativa(tmp_path):
    f = tmp_path / "ks.json"
    now = pd.Timestamp("2026-11-23 10:00", tz="UTC")
    ks = KillSwitch(state_file=f)
    ks.reset_daily_equity_if_new_day(1000.0, now)
    ks.execute_emergency_shutdown(_client())
    ks2 = KillSwitch(state_file=f)
    ks2.reset_daily_equity_if_new_day(1000.0, now + pd.Timedelta(minutes=5))
    assert ks2.is_active is True


def test_parada_cancela_pendentes_e_preserva_posicoes_de_terceiros():
    c = _client()
    c.send_order(OrderRequest("XAUUSD", "long", 0.01, "market", 2650.0, 2640.0, 2680.0, magic=777001))
    c.send_order(OrderRequest("XAUUSD", "long", 0.01, "market", 2650.0, 2640.0, 2680.0, magic=12345))
    c.send_order(OrderRequest("XAUUSD", "long", 0.01, "limit", 2600.0, 2590.0, 2700.0, magic=777001))
    c.send_order(OrderRequest("XAUUSD", "long", 0.01, "limit", 2600.0, 2590.0, 2700.0, magic=12345))
    ks = KillSwitch()
    ks.execute_emergency_shutdown(c, magics={777001})
    assert [p.magic for p in c.get_open_positions()] == [12345]
    assert [o.magic for o in c.orders.values()] == [12345]


def test_engine_parada_cancela_a_pendente_conhecida(tmp_path):
    c = _client()
    eng = _engine(tmp_path, c)
    st = eng.runtimes["XAUUSD"]
    res = c.send_order(OrderRequest("XAUUSD", "long", 0.01, "limit", 2600.0, 2590.0, 2700.0, magic=st.magic))
    st.pending_order_ticket = res.ticket
    eng._emergency_shutdown("XAUUSD", "teste")
    assert c.orders == {}
    assert st.pending_order_ticket is None
    assert eng.kill_switch.is_active is True


# --------------------------------------------------------------------------- travas diárias
def test_model_daily_limits_segue_a_regra_do_backtest():
    t = pd.Timestamp("2026-11-23 10:00", tz="UTC")
    lim = ModelDailyLimits(max_trades_per_day=3, max_stops_per_day=2, max_gains_per_day=1)
    lim.record_trade(t, -1.0)
    lim.record_trade(t, 0.0)  # zero a zero não zera nem soma a sequência
    assert lim.can_trade(t)
    lim.record_trade(t, -1.0)  # 2 stops seguidos
    assert not lim.can_trade(t)
    assert lim.can_trade(t + pd.Timedelta(days=1))
    lim2 = ModelDailyLimits(max_stops_per_day=2)
    lim2.record_trade(t, -1.0)
    lim2.record_trade(t, 1.2)  # gain zera a sequência
    lim2.record_trade(t, -1.0)
    assert lim2.can_trade(t)


def test_contador_de_stops_seguidos_da_conta():
    t = pd.Timestamp("2026-11-23 10:00", tz="UTC")
    c = ConsecutiveLossCounter()
    for _ in range(3):
        c.record_trade(t, -1.0)
    assert c.current(t) == 3
    assert c.current(t + pd.Timedelta(days=1)) == 0


def _deal(ticket, magic, close_price, pnl=0.0, r=0.0, pos_id=None, t="2026-11-23 10:00"):
    return ClosedTradeInfo(
        ticket=ticket, symbol="XAUUSD", direction="long", volume=0.1, open_price=0.0,
        close_price=close_price, open_time=pd.Timestamp(t, tz="UTC"),
        close_time=pd.Timestamp(t, tz="UTC"), pnl=pnl, r_multiple=r, magic=magic,
        position_id=pos_id if pos_id is not None else ticket,
    )


def test_negocios_reais_travam_o_dia_com_r_calculado(tmp_path):
    c = _client()
    eng = _engine(tmp_path, c, max_stops_per_day=2)
    st = eng.runtimes["XAUUSD"]
    now = pd.Timestamp("2026-11-23 11:00", tz="UTC")
    for pid in (1, 2):
        st.position_risk[str(pid)] = {"direction": "long", "open_price": 2000.0, "initial_risk": 10.0}
    # o cliente informa R = 0 (como o MT5 nativo): o motor calcula pelo risco persistido
    c.closed_deals = [
        _deal(11, st.magic, 1990.0, pnl=-10, pos_id=1),
        _deal(12, st.magic, 1990.0, pnl=-10, pos_id=2),
        _deal(13, 99999, 1980.0, pnl=-20),  # outro robô: ignorado
    ]
    eng._sync_deals_and_limits("XAUUSD", now)
    assert not st.model_limits.can_trade(now)
    assert eng.consecutive_losses.current(now) == 2
    assert 13 not in st.processed_deal_tickets


def test_negocio_de_outro_robo_nao_trava(tmp_path):
    c = _client()
    eng = _engine(tmp_path, c, max_stops_per_day=1)
    st = eng.runtimes["XAUUSD"]
    now = pd.Timestamp("2026-11-23 11:00", tz="UTC")
    c.closed_deals = [_deal(21, 424242, 1990.0, pnl=-10)]
    eng._sync_deals_and_limits("XAUUSD", now)
    assert st.model_limits.can_trade(now)


# --------------------------------------------------------------------------- status e entrada
def _act(kind="PLACE_LIMIT", direction="long", stop=90.0, tp=120.0):
    return FiboLiveAction(action_type=kind, direction=direction, price=100.0, stop_loss=stop, take_profit=tp)


def _bars(last_m1: str):
    m1 = pd.DataFrame(
        {"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1},
        index=pd.date_range(end=pd.Timestamp(last_m1, tz="UTC"), periods=10, freq="1min"),
    )
    m5 = pd.DataFrame(
        {"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0},
        index=pd.DatetimeIndex([pd.Timestamp("2026-11-23 10:00", tz="UTC")]),
    )
    return m1, m5


@pytest.mark.parametrize(
    "status,mode,blocked",
    [
        ("paper_only", "real", True),
        ("paper_only", "unknown", True),
        ("candidate", "real", True),
        ("paper_only", "demo", False),
        ("approved", "real", False),
    ],
)
def test_modelo_nao_aprovado_nao_opera_conta_real(tmp_path, status, mode, blocked):
    c = _client()
    c.account.trade_mode = mode
    eng = _engine(tmp_path, c, status=status)
    m1, m5 = _bars("2026-11-23 10:04")
    sym = c.get_symbol_info("XAUUSD")
    res = eng._entry_block_reason("XAUUSD", _act(), m1, m5, sym, c.account, m1.index[-1])
    assert (res is not None and res[0] == "MODEL_NOT_APPROVED_FOR_REAL_ACCOUNT") is blocked


def test_modelo_reprovado_nao_e_carregado(tmp_path):
    eng = _engine(tmp_path, _client(), status="reproved")
    assert "XAUUSD" not in eng.runtimes


def test_teto_global_conta_ordens_pendentes(tmp_path):
    c = _client()
    eng = _engine(tmp_path, c)
    eng.max_open_trades_total = 1
    other = eng.runtimes["XAUUSD"].__class__(symbol="NAS100", config=eng.runtimes["XAUUSD"].config, magic=1)
    other.pending_order_ticket = 555
    eng.runtimes["NAS100"] = other
    m1, m5 = _bars("2026-11-23 10:04")
    res = eng._entry_block_reason("XAUUSD", _act(), m1, m5, c.get_symbol_info("XAUUSD"), c.account, m1.index[-1])
    assert res is not None and res[0] == "MAX_OPEN_TRADES_TOTAL_REACHED"


def test_entrada_a_mercado_com_sinal_vencido_e_descartada(tmp_path):
    c = _client()
    eng = _engine(tmp_path, c)
    sym = c.get_symbol_info("XAUUSD")  # bid 2650 / ask 2650.2
    act = _act("MARKET_ENTRY", stop=2600.0, tp=2700.0)
    m1, m5 = _bars("2026-11-23 10:04")  # 1º ciclo após o fechamento da barra 10:00
    assert eng._entry_block_reason("XAUUSD", act, m1, m5, sym, c.account, m1.index[-1]) is None
    m1_late, _ = _bars("2026-11-23 10:06")  # dois minutos depois (ciclo anterior bloqueado)
    res = eng._entry_block_reason("XAUUSD", act, m1_late, m5, sym, c.account, m1_late.index[-1])
    assert res is not None and res[0] == "STALE_MARKET_SIGNAL"


def test_entrada_a_mercado_com_preco_alem_do_stop_e_descartada(tmp_path):
    c = _client()
    eng = _engine(tmp_path, c)
    sym = c.get_symbol_info("XAUUSD")
    m1, m5 = _bars("2026-11-23 10:04")
    act = _act("MARKET_ENTRY", stop=2655.0, tp=2700.0)  # bid 2650 já abaixo do stop
    res = eng._entry_block_reason("XAUUSD", act, m1, m5, sym, c.account, m1.index[-1])
    assert res is not None and res[0] == "PRICE_BEYOND_STOP_OR_TARGET"


# --------------------------------------------------------------------------- trava de lucro
def _m5_bar(high):
    times = pd.date_range("2026-11-23 10:00", periods=10, freq="5min", tz="UTC")
    return pd.DataFrame({"open": 2000.0, "high": high, "low": 1999.0, "close": 2004.0, "volume": 1}, index=times)


def test_trava_apos_reinicio_nao_afrouxa_o_stop():
    """Entrada 2000, risco inicial 10, trava 1.618R -> +0.5R já aplicada (stop 2005).

    Após um reinício, inferir o risco do stop atual dava 5, e a trava movia o stop para
    2002.5 (pior). Com o risco inicial persistido, nada é enviado.
    """
    cfg = FiboOTEConfig(**KW, profit_lock_trigger_r=1.618, profit_lock_guarantee_r=0.5)
    df = _m5_bar(high=2017.0)
    kw = dict(
        is_positioned=True, current_pos_direction="long", current_pos_open_price=2000.0,
        current_pos_stop_loss=2005.0, current_pos_ticket=7, current_pos_open_time=df.index[0],
    )
    acts = FiboLiveEvaluator(cfg).process_closed_m5(df, current_pos_initial_risk=10.0, **kw)
    assert not [a for a in acts if a.action_type == "MODIFY_STOP"]
    # mesmo sem o risco persistido, o avaliador não propõe stop pior que o atual
    acts_old = FiboLiveEvaluator(cfg).process_closed_m5(df, **kw)
    assert all(a.stop_loss > 2005.0 for a in acts_old if a.action_type == "MODIFY_STOP")


def test_engine_recusa_modificacao_que_piora_o_stop(tmp_path):
    c = _client()
    eng = _engine(tmp_path, c, profit_lock=ProfitLockConfig(trigger_r=1.0, lock_r=0.0))
    st = eng.runtimes["XAUUSD"]
    res = c.send_order(OrderRequest("XAUUSD", "long", 0.01, "market", 2650.0, 2640.0, 2700.0, magic=st.magic))
    c.positions[res.ticket].stop_loss = 2648.0  # stop vigente; a ação propõe 2645 (pior)
    st.current_position = c.positions[res.ticket]
    worse = FiboLiveAction(action_type="MODIFY_STOP", ticket=res.ticket, stop_loss=2645.0, reason="t")
    eng.fibo_evaluators["XAUUSD"].process_closed_m5 = lambda **k: [worse]
    m1 = pd.DataFrame(
        {"open": 2650.0, "high": 2651.0, "low": 2649.0, "close": 2650.0, "volume": 1},
        index=pd.date_range("2026-11-23 10:00", periods=30, freq="1min", tz="UTC"),
    )
    eng._process_fibo_strategy("XAUUSD", m1, c.get_symbol_info("XAUUSD"), m1.index[-1])
    assert c.positions[res.ticket].stop_loss == 2648.0


def test_risco_inicial_persiste_no_state_store(tmp_path):
    c = _client()
    eng = _engine(tmp_path, c)
    st = eng.runtimes["XAUUSD"]
    pos = LivePosition(
        ticket=42, symbol="XAUUSD", direction="long", volume=0.1, open_price=2000.0,
        current_price=2000.0, stop_loss=1990.0, take_profit=2030.0,
        open_time=pd.Timestamp("2026-11-23 10:00", tz="UTC"), initial_risk=10.0, magic=st.magic,
    )
    eng._remember_position_risk(st, pos, pd.Timestamp("2026-11-23 10:01", tz="UTC"))
    pos.stop_loss = 2005.0  # trava move o stop: o registro não muda
    eng._remember_position_risk(st, pos, pd.Timestamp("2026-11-23 10:30", tz="UTC"))
    eng._save_state("XAUUSD")
    eng2 = _engine(tmp_path, c)
    assert eng2.runtimes["XAUUSD"].position_risk["42"]["initial_risk"] == 10.0


# --------------------------------------------------------------------------- mapeamento
def test_todo_campo_do_modelo_chega_a_estrategia():
    """Nenhum campo do YAML pode ser ignorado em silêncio no live."""
    model = FiboModelConfig(
        name="x",
        fibo_entry=0.618, fibo_stop=0.886, fibo_rejection_max=0.79, rejection_min_wick_ratio=0.5,
        target_mode="3R", target_r=4.0, pivot_k=4, trailing_exit_ma="sma20", trend_ma="ema80",
        trend_ma_slope=True, confluence_ma="ema20", bos_swing_trailing=True,
        entry_mode="m5_close_rejection", stop_mode="rejection_candle", session_filter=True,
        session_windows=[("07:00", "10:30")], force_close_time="20:00", close_on_friday=True,
        friday_close_time="19:00", max_holding_candles=33, trend_ma_min_slope=0.2,
        rejection_require_directional_body=True, max_trades_per_day=3, max_stops_per_day=2,
        max_gains_per_day=1, require_inducement=False, require_leg_fvg=True,
        profit_lock=ProfitLockConfig(trigger_r=1.618, lock_r=1.0),
    )
    cfg = fibo_config_from_model(model, "M5")
    for name in FiboModelConfig.model_fields:
        if name in MODEL_FIELDS_NOT_IN_STRATEGY:
            continue
        expected = getattr(model, name)
        if name == "session_windows":
            expected = [tuple(w) for w in expected]
        assert getattr(cfg, name) == expected, name
    assert cfg.profit_lock_trigger_r == 1.618 and cfg.profit_lock_guarantee_r == 1.0
