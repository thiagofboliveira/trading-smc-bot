import pandas as pd
import plotly.graph_objects as go

from smc_trader.analysis import Analysis

_UP = "#2e9e5b"
_DOWN = "#d6453d"
_FVG_FILL = "rgba(70, 130, 220, 0.18)"
_ZONE_FILL = {"long": "rgba(46, 158, 91, 0.25)", "short": "rgba(214, 69, 61, 0.25)"}
_ZONE_LINE = {"long": _UP, "short": _DOWN}
_BREAKER_FILL = {
    "long": "rgba(139, 92, 246, 0.22)",
    "short": "rgba(245, 158, 11, 0.22)",
}
_BREAKER_LINE = {"long": "#8b5cf6", "short": "#f59e0b"}


def build_chart(candles: pd.DataFrame, analysis: Analysis, title: str) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(
        go.Candlestick(
            x=candles.index,
            open=candles["open"],
            high=candles["high"],
            low=candles["low"],
            close=candles["close"],
            name="Preço",
            increasing_line_color=_UP,
            decreasing_line_color=_DOWN,
        )
    )

    pivots = analysis.pivots
    for kind, symbol, color, label in (
        ("high", "triangle-down", _DOWN, "Pivô alto"),
        ("low", "triangle-up", _UP, "Pivô baixo"),
    ):
        sel = pivots[pivots["kind"] == kind]
        fig.add_trace(
            go.Scatter(
                x=sel["time"],
                y=sel["price"],
                mode="markers",
                marker=dict(symbol=symbol, size=7, color=color),
                name=label,
            )
        )

    for e in analysis.events:
        color = _UP if e.direction == "up" else _DOWN
        fig.add_trace(
            go.Scatter(
                x=[e.level_time, e.time],
                y=[e.level, e.level],
                mode="lines",
                line=dict(color=color, width=1, dash="dot"),
                showlegend=False,
                hoverinfo="skip",
            )
        )
        fig.add_annotation(
            x=e.time,
            y=e.level,
            text=f"{e.kind} {'↑' if e.direction == 'up' else '↓'}",
            showarrow=False,
            yshift=10 if e.direction == "up" else -10,
            font=dict(size=11, color=color),
        )

    for f in analysis.fvgs:
        fig.add_shape(
            type="rect",
            xref="x",
            yref="y",
            x0=f.start_time,
            x1=f.formed_at,
            y0=f.low,
            y1=f.high,
            fillcolor=_FVG_FILL,
            line=dict(width=0),
            layer="below",
        )

    last_close = candles["close_time"].iloc[-1] if len(candles) else None

    def draw_zone(z, fill, color, label, dash=None):
        fig.add_shape(
            type="rect",
            xref="x",
            yref="y",
            x0=z.created_at,
            x1=z.end_time if z.end_time is not None else last_close,
            y0=z.low,
            y1=z.high,
            fillcolor=fill,
            line=dict(color=color, width=1, **({"dash": dash} if dash else {})),
            layer="below",
        )
        fig.add_annotation(
            x=z.created_at,
            y=z.high,
            text=label + (" sweep" if z.swept_liquidity else ""),
            showarrow=False,
            xanchor="left",
            yanchor="bottom",
            font=dict(size=10, color=color),
        )

    for z in analysis.zones:
        draw_zone(z, _ZONE_FILL[z.direction], _ZONE_LINE[z.direction], z.kind)
    for z in analysis.breakers:
        draw_zone(
            z, _BREAKER_FILL[z.direction], _BREAKER_LINE[z.direction], "BB", "dash"
        )

    fig.update_layout(
        title=title,
        xaxis_rangeslider_visible=False,
        xaxis=dict(rangebreaks=[dict(bounds=["sat", "sun"])]),
        legend=dict(orientation="h"),
    )
    return fig
