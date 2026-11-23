"""Limites diários do live com a mesma regra da `FiboOTEStrategy` (F-16).

O backtest trava o dia por: trades encerrados no dia, stops SEGUIDOS no dia (um gain zera a
sequência) e gains no dia. Um trade conta como gain se R > +0.05, como stop se R < -0.05;
entre os dois (zero a zero) só conta como trade. O dia é a data UTC do fechamento.

No live, esta classe é alimentada pelos negócios reais da corretora, com o R calculado pelo
risco inicial persistido. Antes, o live usava `DailyLimitsTracker` desligado por padrão e
recebia R = 0.0 de todo negócio, então as travas do modelo nunca disparavam com trades reais.
"""

from dataclasses import dataclass, field

import pandas as pd

R_EPS = 0.05


@dataclass
class _DayStats:
    trades: int = 0
    consec_stops: int = 0
    gains: int = 0


@dataclass
class ModelDailyLimits:
    max_trades_per_day: int = 0  # 0 = sem limite
    max_stops_per_day: int = 0  # stops seguidos no dia; 0 = sem limite
    max_gains_per_day: int = 0  # 0 = sem limite
    _days: dict = field(default_factory=dict)

    def record_trade(self, close_time: pd.Timestamp, r_multiple: float) -> None:
        st = self._days.setdefault(_day_key(close_time), _DayStats())
        st.trades += 1
        if r_multiple > R_EPS:
            st.gains += 1
            st.consec_stops = 0
        elif r_multiple < -R_EPS:
            st.consec_stops += 1

    def is_locked(self, t: pd.Timestamp) -> bool:
        st = self._days.get(_day_key(t))
        if st is None:
            return False
        if self.max_trades_per_day > 0 and st.trades >= self.max_trades_per_day:
            return True
        if self.max_stops_per_day > 0 and st.consec_stops >= self.max_stops_per_day:
            return True
        if self.max_gains_per_day > 0 and st.gains >= self.max_gains_per_day:
            return True
        return False

    def can_trade(self, t: pd.Timestamp) -> bool:
        return not self.is_locked(t)


@dataclass
class ConsecutiveLossCounter:
    """Stops seguidos da conta inteira no dia UTC (kill switch `max_consecutive_losses`)."""

    _day: object = None
    count: int = 0

    def record_trade(self, close_time: pd.Timestamp, r_multiple: float) -> None:
        day = _day_key(close_time)
        if day != self._day:
            self._day = day
            self.count = 0
        if r_multiple > R_EPS:
            self.count = 0
        elif r_multiple < -R_EPS:
            self.count += 1

    def current(self, t: pd.Timestamp) -> int:
        return self.count if _day_key(t) == self._day else 0


def _day_key(t: pd.Timestamp):
    ts = pd.Timestamp(t)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    return ts.tz_convert("UTC").date()


def r_multiple_from_prices(
    direction: str, open_price: float, close_price: float, initial_risk: float
) -> float | None:
    """R em preço (sem custos de comissão/swap). None se faltar dado."""
    if initial_risk <= 0 or open_price <= 0 or close_price <= 0:
        return None
    sign = 1.0 if direction == "long" else -1.0
    return sign * (close_price - open_price) / initial_risk
