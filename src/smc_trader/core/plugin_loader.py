"""Carregador de plugins e registro unificado de estratégias (SDK - E2-7, E8-2).

Permite que usuários criem suas próprias estratégias na pasta `plugins/`
sem modificar o código-fonte da plataforma, respeitando a interface `BaseStrategy`.
"""

import importlib.util
import inspect
from pathlib import Path

import pandas as pd

from smc_trader.broker.sim_broker import BrokerTrade, SimBroker
from smc_trader.core.strategy import BaseStrategy


def discover_plugins(plugins_dir: Path | str = "plugins") -> dict[str, type[BaseStrategy]]:
    """Varre o diretório de plugins e retorna dicionário {nome_identificador: ClasseEstrategia}."""
    discovered: dict[str, type[BaseStrategy]] = {}
    p_dir = Path(plugins_dir)
    if not p_dir.exists():
        return discovered

    for file_path in p_dir.glob("*.py"):
        if file_path.name.startswith("__"):
            continue

        module_name = f"smc_trader_plugin_{file_path.stem}"
        try:
            spec = importlib.util.spec_from_file_location(module_name, file_path)
            if spec is None or spec.loader is None:
                continue
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            for _, obj in inspect.getmembers(module, inspect.isclass):
                if issubclass(obj, BaseStrategy) and obj is not BaseStrategy:
                    # Instancia temporariamente se possível para pegar o nome
                    try:
                        inst = obj()
                        strat_name = inst.name
                    except Exception:
                        strat_name = obj.__name__.lower()
                    discovered[strat_name] = obj
                    discovered[file_path.stem] = obj
        except Exception as e:
            print(f"⚠️ Erro ao carregar plugin de {file_path}: {e}")

    return discovered


def load_strategy_from_file(file_path: Path | str) -> type[BaseStrategy] | None:
    """Carrega dinamicamente a primeira classe que herda de BaseStrategy em um arquivo."""
    p = Path(file_path)
    if not p.exists() or not p.is_file():
        return None

    module_name = f"smc_dyn_plugin_{p.stem}"
    spec = importlib.util.spec_from_file_location(module_name, p)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    for _, obj in inspect.getmembers(module, inspect.isclass):
        if issubclass(obj, BaseStrategy) and obj is not BaseStrategy:
            return obj

    return None


def run_strategy_simulation(
    strategy: BaseStrategy,
    df: pd.DataFrame,
    symbol: str = "ASSET",
    spread: float = 1.0,
    slippage: float = 0.5,
    commission: float = 0.0,
) -> list[BrokerTrade]:
    """Executa simulação de uma BaseStrategy com o SimBroker causal."""
    broker = SimBroker(spread=spread, slippage=slippage, commission=commission)
    warmup = strategy.get_warmup_bars()
    if len(df) <= warmup:
        return []

    for i in range(warmup, len(df)):
        sub_df = df.iloc[:i]  # Apenas barras fechadas até i-1
        open_pos = {
            "symbol": broker.positions[0].symbol,
            "direction": broker.positions[0].direction,
            "entry_price": broker.positions[0].entry_price,
            "stop_loss": broker.positions[0].stop_loss,
            "take_profit": broker.positions[0].take_profit,
        } if broker.positions else None

        # Avaliação da estratégia
        intents = strategy.evaluate(sub_df, open_position=open_pos)
        for intent in intents:
            broker.submit_order(intent, bar_idx=i)

        # Processa a barra atual i
        curr_bar = df.iloc[i]
        ts = df.index[i]
        broker.process_bar(
            bar_idx=i,
            timestamp=ts if isinstance(ts, pd.Timestamp) else pd.Timestamp(ts),
            open_=float(curr_bar["open"]),
            high=float(curr_bar["high"]),
            low=float(curr_bar["low"]),
            close=float(curr_bar["close"]),
            symbol=symbol,
        )

    return broker.closed_trades
