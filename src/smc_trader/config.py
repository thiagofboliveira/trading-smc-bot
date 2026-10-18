from pathlib import Path
from typing import Literal, Self

import yaml
from pydantic import BaseModel, Field, model_validator


class DataConfig(BaseModel):
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
    pivot_k_htf: int = Field(3, ge=1)
    pivot_k_ltf: int = Field(2, ge=1)


class ZoneConfig(BaseModel):
    require_discount: bool = True
    require_imbalance: bool = False
    use_body: bool = False
    fvg_min_size: float = Field(0.0, ge=0)


class DukascopyConfig(BaseModel):
    instruments: dict[str, str]
    offer_side: Literal["bid", "ask"] = "bid"


class Config(BaseModel):
    data: DataConfig
    symbols: list[str]
    dukascopy: DukascopyConfig
    structure: StructureConfig
    zones: ZoneConfig


def load_config(path: Path = Path("config/default.yaml")) -> Config:
    with open(path, encoding="utf-8") as f:
        return Config.model_validate(yaml.safe_load(f))
