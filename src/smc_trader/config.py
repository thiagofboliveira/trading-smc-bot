from pathlib import Path
from typing import Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class DataConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    root: Path = Path("data")
    server_ny_offset_hours: int | None = 7
    server_timezone: str | None = None

    @model_validator(mode="after")
    def _exactly_one_server_time_rule(self) -> Self:
        if (self.server_ny_offset_hours is None) == (self.server_timezone is None):
            raise ValueError(
                "defina exatamente um entre server_ny_offset_hours e server_timezone"
            )
        return self


class StructureConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pivot_k_htf: int = Field(3, ge=1)
    pivot_k_ltf: int = Field(2, ge=1)


class ZoneConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    require_discount: bool = True
    require_imbalance: bool = False
    use_body: bool = False
    fvg_min_size: float = Field(0.0, ge=0)
    blocks_filter: list[Literal["OB", "FVOB", "BB"]] = Field(
        default_factory=lambda: ["OB", "FVOB", "BB"]
    )
    breaker_require_imbalance: bool = True
    breaker_require_choch: bool = False
    breaker_max_age: int | None = Field(96, ge=1)

    @field_validator("blocks_filter")
    @classmethod
    def _blocks_filter_non_empty_canonical(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("blocks_filter não pode ser vazio")
        return [k for k in ("OB", "FVOB", "BB") if k in v]


class DukascopyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instruments: dict[str, str]
    offer_side: Literal["bid", "ask"] = "bid"


class CostsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    spread_pips: dict[str, float] = Field(default_factory=dict)
    commission_per_lot: float = Field(0.0, ge=0.0)
    slippage_points: float = Field(0.0, ge=0.0)


class ContractSpec(BaseModel):
    """Especificação e custos de um ativo, na unidade de preço do próprio ativo."""

    model_config = ConfigDict(extra="forbid")

    spread: float = Field(gt=0.0)  # spread típico em preço; dados bid => custo de entrada e de saída
    tick_size: float | None = Field(default=None, gt=0.0)
    point_value: float | None = Field(default=None, gt=0.0)  # moeda por ponto, por contrato/lote
    commission_per_unit: float = Field(0.0, ge=0.0)
    slippage: float = Field(0.0, ge=0.0)
    note: str = ""


class SessionWindow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    start: str
    end: str


class SessionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    windows: list[SessionWindow] = Field(
        default_factory=lambda: [
            SessionWindow(name="london", start="07:00", end="15:30"),
            SessionWindow(name="ny", start="13:00", end="20:00"),
        ]
    )
    force_close_time: str | None = Field(default="21:00")


class LimitsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    max_trades_per_day: int = Field(3, ge=1)
    max_stops_per_day: int = Field(2, ge=1)
    max_gains_per_day: int = Field(1, ge=1)


class ConfluenceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    use_ema80: bool = False
    use_sma200: bool = False
    use_fib618: bool = False
    use_fib790: bool = False
    ma_timeframe: Literal["M1", "M5", "M15"] = "M1"
    tolerance: float = Field(0.0, ge=0.0)
    min_rules: int = Field(1, ge=1)


class TrailingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["none", "ema", "bos"] = "none"
    ema_period: int = Field(20, ge=1)
    timeframe: Literal["M1", "M5", "M15"] = "M1"
    activation: Literal["either", "r_multiple", "on_new_bos"] = "either"
    r_threshold: float = Field(1.0, gt=0.0)


class BacktestConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entry_mode: Literal["touch", "confirmation", "hybrid"] = "confirmation"
    stop_mode: Literal["ob", "swing", "m1_swing"] = "ob"
    target_mode: Literal["fixed_r", "none"] = "fixed_r"
    target_r: float = Field(3.0, gt=0.0)
    max_open_per_symbol: int = Field(1, ge=1)
    confirmation_timeout_minutes: int | None = Field(default=None, ge=1)
    costs: CostsConfig = Field(default_factory=CostsConfig)
    session: SessionConfig = Field(default_factory=SessionConfig)
    limits: LimitsConfig = Field(default_factory=LimitsConfig)
    confluence: ConfluenceConfig = Field(default_factory=ConfluenceConfig)
    trailing: TrailingConfig = Field(default_factory=TrailingConfig)


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: DataConfig
    symbols: list[str]
    dukascopy: DukascopyConfig
    structure: StructureConfig
    zones: ZoneConfig
    backtest: BacktestConfig = Field(default_factory=BacktestConfig)
    contracts: dict[str, ContractSpec] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _symbols_have_dukascopy_instrument(self) -> Self:
        missing = [s for s in self.symbols if s not in self.dukascopy.instruments]
        if missing:
            raise ValueError(
                f"símbolos sem mapeamento em dukascopy.instruments: {', '.join(missing)}"
            )
        return self


def load_config(path: Path = Path("config/default.yaml")) -> Config:
    with open(path, encoding="utf-8") as f:
        return Config.model_validate(yaml.safe_load(f))
