"""Montagem de séries contínuas para contratos futuros da B3 (WIN/WDO) com controle de rolagem (D-02).

Evita que o salto de preço entre vencimentos consecutivos (ex: WINV26 -> WINZ26)
seja interpretado como quebra de estrutura (BOS) ou violação de Stop Loss.
Adiciona a coluna booleana 'roll' na barra de transição de contrato.
"""

from typing import Literal

import pandas as pd


def stitch_contracts_series(
    contracts: dict[str, pd.DataFrame],
    rollover_dates: dict[str, pd.Timestamp] | None = None,
    rule: Literal["volume_flip", "fixed_date"] = "volume_flip",
) -> pd.DataFrame:
    """Combina múltiplos vencimentos de contratos futuros em uma série contínua não ajustada.

    contracts: dicionário ordenado {código_contrato: df_ohlc_m1_utc}
    rollover_dates: opcional, data/hora exata da virada para cada contrato
    """
    if not contracts:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume", "roll"])

    sorted_keys = list(contracts.keys())
    if len(sorted_keys) == 1:
        single_df = contracts[sorted_keys[0]].copy()
        if "roll" not in single_df.columns:
            single_df["roll"] = False
        return single_df

    stitched_chunks: list[pd.DataFrame] = []

    for idx in range(len(sorted_keys)):
        curr_key = sorted_keys[idx]
        curr_df = contracts[curr_key].sort_index().copy()

        if idx < len(sorted_keys) - 1:
            next_key = sorted_keys[idx + 1]
            next_df = contracts[next_key].sort_index()

            # Determina o momento do rollover
            if rollover_dates and curr_key in rollover_dates:
                roll_ts = rollover_dates[curr_key]
            else:
                # Regra de volume_flip: encontra a primeira data onde volume diário do próximo supera o atual
                overlap_start = max(curr_df.index[0], next_df.index[0])
                overlap_end = min(curr_df.index[-1], next_df.index[-1])
                if overlap_start < overlap_end:
                    curr_sub = curr_df.loc[overlap_start:overlap_end]
                    next_sub = next_df.loc[overlap_start:overlap_end]
                    # Agrupa por dia
                    daily_curr = curr_sub["volume"].resample("1D").sum()
                    daily_next = next_sub["volume"].resample("1D").sum()
                    flip_days = daily_next[daily_next > daily_curr].index
                    if len(flip_days) > 0:
                        roll_ts = curr_df.loc[curr_df.index >= flip_days[0]].index[0]
                    else:
                        roll_ts = overlap_end
                else:
                    roll_ts = curr_df.index[-1]

            chunk = curr_df.loc[curr_df.index <= roll_ts].copy()
            chunk["roll"] = False
            # Marca a última barra antes da troca com roll = True
            if not chunk.empty:
                chunk.iloc[-1, chunk.columns.get_loc("roll")] = True
            stitched_chunks.append(chunk)
        else:
            # Último contrato
            prev_chunk_last_ts = stitched_chunks[-1].index[-1] if stitched_chunks else None
            if prev_chunk_last_ts:
                chunk = curr_df.loc[curr_df.index > prev_chunk_last_ts].copy()
            else:
                chunk = curr_df.copy()
            chunk["roll"] = False
            stitched_chunks.append(chunk)

    full_series = pd.concat(stitched_chunks)
    full_series = full_series[~full_series.index.duplicated(keep="first")].sort_index()
    if "spread" not in full_series.columns:
        full_series["spread"] = 0.0
    return full_series
