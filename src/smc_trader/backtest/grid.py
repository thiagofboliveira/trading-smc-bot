import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Literal

from smc_trader.config import (
    BacktestConfig,
    ConfluenceConfig,
    TrailingConfig,
)

BlocksFilterType = tuple[str, ...]
EntryModeType = Literal["touch", "confirmation", "hybrid"]
StopModeType = Literal["ob", "swing", "m1_swing"]
TrailingModeType = Literal["none", "ema", "bos"]
ConfluenceProfileType = Literal["all_active", "ema_only", "sma_only", "fib_only", "none"]


@dataclass(frozen=True)
class GridVariant:
    """Representação de uma variante discreta da grade de parâmetros."""

    blocks_filter: tuple[str, ...]
    entry_mode: EntryModeType
    stop_mode: StopModeType
    trailing_mode: TrailingModeType
    confluence_profile: ConfluenceProfileType
    config_hash: str

    @classmethod
    def create(
        cls,
        blocks_filter: tuple[str, ...],
        entry_mode: EntryModeType,
        stop_mode: StopModeType,
        trailing_mode: TrailingModeType,
        confluence_profile: ConfluenceProfileType,
        base_config: BacktestConfig | None = None,
    ) -> "GridVariant":
        canonical_blocks = tuple(sorted(list(set(blocks_filter))))
        payload = {
            "blocks_filter": list(canonical_blocks),
            "entry_mode": entry_mode,
            "stop_mode": stop_mode,
            "trailing_mode": trailing_mode,
            "confluence_profile": confluence_profile,
        }
        if base_config is not None:
            payload["costs"] = base_config.costs.model_dump()
            payload["target_mode"] = base_config.target_mode
            payload["target_r"] = base_config.target_r
            payload["session"] = base_config.session.model_dump()

        raw_json = json.dumps(payload, sort_keys=True)
        h = hashlib.sha256(raw_json.encode("utf-8")).hexdigest()[:16]
        return cls(
            blocks_filter=canonical_blocks,
            entry_mode=entry_mode,
            stop_mode=stop_mode,
            trailing_mode=trailing_mode,
            confluence_profile=confluence_profile,
            config_hash=h,
        )

    def to_backtest_config(self, base_config: BacktestConfig) -> BacktestConfig:
        """Converte a variante em uma instância concreta de BacktestConfig."""
        # Configurar confluência conforme o perfil
        confluence_dict = base_config.confluence.model_dump()
        if self.confluence_profile == "all_active":
            confluence_dict.update({"use_ema80": True, "use_sma200": True, "use_fib618": True, "use_fib790": True, "min_rules": 1})
        elif self.confluence_profile == "ema_only":
            confluence_dict.update({"use_ema80": True, "use_sma200": False, "use_fib618": False, "use_fib790": False, "min_rules": 1})
        elif self.confluence_profile == "sma_only":
            confluence_dict.update({"use_ema80": False, "use_sma200": True, "use_fib618": False, "use_fib790": False, "min_rules": 1})
        elif self.confluence_profile == "fib_only":
            confluence_dict.update({"use_ema80": False, "use_sma200": False, "use_fib618": True, "use_fib790": True, "min_rules": 1})
        elif self.confluence_profile == "none":
            confluence_dict.update({"use_ema80": False, "use_sma200": False, "use_fib618": False, "use_fib790": False, "min_rules": 1})

        # Configurar trailing
        trailing_dict = base_config.trailing.model_dump()
        trailing_dict["mode"] = self.trailing_mode

        # Desligar travas no backtest de exploração por padrão (conforme spec)
        limits_dict = base_config.limits.model_dump()
        limits_dict["enabled"] = False

        return BacktestConfig(
            entry_mode=self.entry_mode,
            stop_mode=self.stop_mode,
            target_mode=base_config.target_mode,
            target_r=base_config.target_r,
            max_open_per_symbol=base_config.max_open_per_symbol,
            confirmation_timeout_minutes=base_config.confirmation_timeout_minutes,
            costs=base_config.costs,
            session=base_config.session,
            limits=limits_dict,
            confluence=confluence_dict,
            trailing=trailing_dict,
        )


def generate_grid_variants(base_config: BacktestConfig) -> list[GridVariant]:
    """Gera todas as combinações válidas da grade de parâmetros SMC."""
    blocks_candidates: list[tuple[str, ...]] = [
        ("OB",),
        ("FVOB",),
        ("BB",),
        ("OB", "FVOB", "BB"),
    ]
    entry_candidates: list[EntryModeType] = ["touch", "confirmation", "hybrid"]
    stop_candidates: list[StopModeType] = ["ob", "swing", "m1_swing"]
    trailing_candidates: list[TrailingModeType] = ["none", "ema", "bos"]
    confluence_candidates: list[ConfluenceProfileType] = [
        "all_active",
        "ema_only",
        "sma_only",
        "fib_only",
        "none",
    ]

    variants: list[GridVariant] = []

    for blocks in blocks_candidates:
        for entry in entry_candidates:
            # Regra da spec: Breaker não aceita toque puro
            if blocks == ("BB",) and entry == "touch":
                continue

            for stop in stop_candidates:
                # Regra: m1_swing exige confirmação M1 (não faz sentido em toque puro)
                if stop == "m1_swing" and entry == "touch":
                    continue

                for trailing in trailing_candidates:
                    # Se entry for touch ou confirmation pura, variações de confluência
                    # não alteram a execução. Fixamos em 'none' para não gerar combinações redundantes.
                    profiles = confluence_candidates if entry == "hybrid" else ["none"]

                    for conf in profiles:
                        variant = GridVariant.create(
                            blocks_filter=blocks,
                            entry_mode=entry,
                            stop_mode=stop,
                            trailing_mode=trailing,
                            confluence_profile=conf,  # type: ignore[arg-type]
                            base_config=base_config,
                        )
                        variants.append(variant)

    return variants
