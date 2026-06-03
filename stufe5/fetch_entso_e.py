"""
fetch_entso_e.py – ENTSO-E Transparency Platform Datenabruf für Stufe 5
=======================================================================
Benelux-Knoten: NL, BE, LU
Datenquelle: ENTSO-E Transparency Platform (entsoe-py)

Bidding zones:
  NL  → 10YNL----------L
  BE  → 10YBE----------2
  LU  → 10YLU-CEGEDEL-NQ

Falls kein ENTSO-E API Key vorhanden:
  → synthetische Profile auf Basis realer Jahresstatistiken (Fallback)

Nutzung:
  python fetch_entso_e.py
  → erzeugt data/benelux_hourly.csv
"""

import os
import sys
import warnings
warnings.filterwarnings('ignore')
from pathlib import Path
from datetime import datetime, timezone

import numpy as np
import pandas as pd

# ENTSO-E Bidding Zone Keys
ZONE_KEYS = {
    'NL': '10YNL----------L',
    'BE': '10YBE----------2',
    'LU': '10YLU-CEGEDEL-NQ',
}

# Reale Jahreswerte aus ENTSO-E Statistical Factsheet 2023 (TWh/yr)
ANNUAL_STATS = {
    'NL': {'consumption': 118.3, 'wind': 28.1, 'solar': 19.2,
           'gas': 38.7, 'nuclear': 0.0, 'other': 5.1,
           'offshore_wind_share': 0.62},
    'BE': {'consumption': 84.1,  'wind': 14.3, 'solar': 10.1,
           'gas': 22.4, 'nuclear': 26.1, 'other': 7.2,
           'offshore_wind_share': 0.58},
    'LU': {'consumption':  6.4,  'wind':  0.8, 'solar':  0.6,
           'gas':  0.3, 'nuclear':  0.0, 'other':  1.1,
           'offshore_wind_share': 0.0},
}

SUMMER_MONTHS = [4, 5, 6, 7, 8, 9]


def _synthetic_profile(node: str, idx: pd.DatetimeIndex) -> pd.DataFrame:
    """
    Erzeugt synthetisches stündliches Profil auf Basis realer Jahresstatistiken.
    Methodik identisch zu stufe4/fetch_smard_regional.py:
      - Windprofil: Weibull-Zufallsprozess mit saisonaler Modulation
      - Lastprofil: sinusförmige Tages- und Jahresschwingung
      - Solarprofil: Tagesgangkurve × saisonaler Faktor
    """
    rng = np.random.default_rng(seed=abs(hash(node)) % 2**31)
    stats = ANNUAL_STATS[node]
    n = len(idx)

    hours_per_year = 8760
    annual_demand_gwh = stats['consumption'] * 1e3  # TWh → GWh
    avg_demand = annual_demand_gwh / hours_per_year  # GWh/h

    months = idx.month.values
    hours  = idx.hour.values

    # Last: Jahres- + Tageszyklus
    seasonal = 1.0 + 0.18 * np.cos(2 * np.pi * (months - 1) / 12)
    daily    = 1.0 + 0.12 * np.cos(2 * np.pi * (hours - 14) / 24)
    noise    = 1.0 + rng.normal(0, 0.03, n)
    load     = avg_demand * seasonal * daily * noise
    load     = np.clip(load, avg_demand * 0.4, avg_demand * 1.9)

    # Windproduktion: Weibull, saisonal stärker im Winter
    wind_annual_gwh = (stats['wind'] + stats.get('offshore_wind_frac', 0)) * 1e3
    wind_avg = wind_annual_gwh / hours_per_year
    wind_seasonal = 1.0 + 0.35 * np.cos(2 * np.pi * (months - 1) / 12 + np.pi)
    wind_shape = rng.weibull(2.0, n)
    wind = wind_avg * wind_seasonal * wind_shape
    wind = np.clip(wind, 0, wind_avg * 5)

    # Solar: nur tagsüber, saisonal
    solar_annual_gwh = stats['solar'] * 1e3
    solar_avg = solar_annual_gwh / hours_per_year
    solar_hour = np.clip(np.sin(np.pi * (hours - 6) / 12), 0, 1)
    solar_season = np.where(np.isin(months, SUMMER_MONTHS), 1.6, 0.4)
    solar_noise  = rng.uniform(0.7, 1.3, n)
    solar = solar_avg * solar_hour * solar_season * solar_noise * 2.8
    solar = np.clip(solar, 0, solar_avg * 6)

    # Grundlast: Gas + Nuklear (BE hat Nuklear)
    gas_gwh   = stats['gas'] * 1e3 / hours_per_year
    nuke_gwh  = stats['nuclear'] * 1e3 / hours_per_year
    # Nuklear: konstant mit gelegentlichen Wartungsausfällen
    nuke_avail = rng.choice([1.0, 0.0], size=n, p=[0.92, 0.08])  # 8% Ausfallrate
    nuke_prod  = nuke_gwh * nuke_avail
    gas_var    = 1.0 + rng.normal(0, 0.05, n)
    gas_prod   = np.clip(gas_gwh * gas_var, 0, gas_gwh * 1.5)

    total_prod = wind + solar + nuke_prod + gas_prod

    # Wärmebedarf: stark saisonal (Fernwärme + Industrie)
    heat_annual_gwh = annual_demand_gwh * 0.30  # 30% der Gesamtenergie als Wärme
    heat_avg = heat_annual_gwh / hours_per_year
    heat_seasonal = 1.0 + 0.55 * np.cos(2 * np.pi * (months - 1) / 12)
    heat_noise    = 1.0 + rng.normal(0, 0.04, n)
    heat_demand   = heat_avg * heat_seasonal * heat_noise
    heat_supply   = heat_demand * (0.85 + rng.uniform(0, 0.1, n))

    return pd.DataFrame({
        'last':             load,
        'erzeugung_gesamt': total_prod,
        'wind':             wind,
        'solar':            solar,
        'nuclear':          nuke_prod,
        'gas':              gas_prod,
        'heat_demand':      heat_demand,
        'heat_supply':      heat_supply,
    }, index=idx)


def load_benelux_data(start='2022-01-01', end='2024-01-01',
                      api_key: str = None,
                      cache_path: str = None) -> dict:
    """
    Lädt Benelux-Stundendaten.
    Versucht zuerst ENTSO-E API (wenn api_key gesetzt),
    fällt auf synthetische Profile zurück.

    Returns: {'NL': DataFrame, 'BE': DataFrame, 'LU': DataFrame}
    """
    if cache_path is None:
        cache_path = Path(__file__).parent.parent / 'data' / 'benelux_hourly.parquet'

    cache_path = Path(cache_path)
    if cache_path.exists():
        print(f'    [Cache] Lade {cache_path}')
        combined = pd.read_parquet(cache_path)
        return {node: combined[combined['node'] == node].drop(columns='node')
                for node in ['NL', 'BE', 'LU']}

    # Zeitindex 2022–2023 (UTC, stündlich)
    idx = pd.date_range(start, end, freq='h', tz='UTC')[:-1]

    api_key = api_key or os.environ.get('ENTSOE_API_KEY')
    data = {}

    if api_key:
        try:
            from entsoe import EntsoePandasClient
            client = EntsoePandasClient(api_key=api_key)
            start_ts = pd.Timestamp(start, tz='UTC')
            end_ts   = pd.Timestamp(end,   tz='UTC')

            for node, zone in ZONE_KEYS.items():
                print(f'    [ENTSO-E] Lade {node} ({zone})...')
                try:
                    load_raw = client.query_load(zone, start=start_ts, end=end_ts)
                    gen_raw  = client.query_generation(zone, start=start_ts, end=end_ts)
                    load_h   = load_raw.resample('h').mean() / 1000  # MW → GWh/h
                    gen_h    = gen_raw.resample('h').sum(axis=1) / 1000
                    load_h   = load_h.reindex(idx).interpolate()
                    gen_h    = gen_h.reindex(idx).fillna(method='ffill')
                    # Wärme synthetisch (ENTSO-E liefert keine Wärmedaten)
                    synth = _synthetic_profile(node, idx)
                    df = pd.DataFrame({
                        'last':             load_h.values,
                        'erzeugung_gesamt': gen_h.values,
                        'heat_demand':      synth['heat_demand'].values,
                        'heat_supply':      synth['heat_supply'].values,
                    }, index=idx)
                    data[node] = df
                    print(f'    [ENTSO-E] {node}: {len(df)} Stunden geladen.')
                except Exception as e:
                    print(f'    [ENTSO-E] {node} Fehler: {e} → Fallback auf Synthese')
                    data[node] = _synthetic_profile(node, idx)
        except ImportError:
            print('    [ENTSO-E] entsoe-py nicht installiert → synthetische Profile')
            for node in ZONE_KEYS:
                data[node] = _synthetic_profile(node, idx)
    else:
        print('    [Info] Kein ENTSO-E API Key → synthetische Profile')
        print('    [Info] API Key setzen: export ENTSOE_API_KEY=<key>')
        print('    [Info] Kostenlos registrieren: transparency.entsoe.eu')
        for node in ZONE_KEYS:
            print(f'    Generiere {node}...')
            data[node] = _synthetic_profile(node, idx)

    # Cache speichern
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    combined = pd.concat(
        [df.assign(node=node) for node, df in data.items()]
    )
    combined.to_parquet(cache_path)
    print(f'    [Cache] Gespeichert: {cache_path}')

    return data


def apply_nuclear_phase_out(data: dict, node='BE') -> dict:
    """Stresstest: Alle Atomkraftwerke in BE gleichzeitig offline."""
    out = {k: df.copy() for k, df in data.items()}
    mask = (
        (out[node].index >= pd.Timestamp('2023-03-01', tz='UTC')) &
        (out[node].index <  pd.Timestamp('2023-03-22', tz='UTC'))  # 3 Wochen
    )
    out[node].loc[mask, 'nuclear']          = 0.0
    out[node].loc[mask, 'erzeugung_gesamt'] -= out[node].loc[mask, 'nuclear'].shift(1).fillna(0)
    out[node].loc[mask, 'erzeugung_gesamt'] = np.clip(
        out[node].loc[mask, 'erzeugung_gesamt'], 0, None
    )
    return out


def apply_gas_disruption(data: dict, node='NL') -> dict:
    """Stresstest: Gasnetz-Unterbrechung in NL (Groningen-Szenario), 5 Tage."""
    out = {k: df.copy() for k, df in data.items()}
    mask = (
        (out[node].index >= pd.Timestamp('2023-01-15', tz='UTC')) &
        (out[node].index <  pd.Timestamp('2023-01-20', tz='UTC'))
    )
    out[node].loc[mask, 'gas']              *= 0.1
    out[node].loc[mask, 'erzeugung_gesamt'] *= 0.55
    return out


def apply_nordsee_sturm(data: dict) -> dict:
    """Stresstest: Nordsee-Sturm → Offshore-Wind NL+BE 350%, aber Last +15% (Kälte)."""
    out = {k: df.copy() for k, df in data.items()}
    for node in ['NL', 'BE']:
        mask = (
            (out[node].index >= pd.Timestamp('2023-02-10', tz='UTC')) &
            (out[node].index <  pd.Timestamp('2023-02-13', tz='UTC'))
        )
        out[node].loc[mask, 'wind']             *= 3.5
        out[node].loc[mask, 'erzeugung_gesamt'] *= 2.8
        out[node].loc[mask, 'last']             *= 1.15
        out[node].loc[mask, 'heat_demand']      *= 1.20
    return out


if __name__ == '__main__':
    print('Lade Benelux-Daten 2022–2023...')
    data = load_benelux_data()
    for node, df in data.items():
        stats = ANNUAL_STATS[node]
        sr = df['erzeugung_gesamt'].mean() / df['last'].mean() * 100
        print(f'  {node}: {len(df)} Stunden | '
              f'Last Ø {df["last"].mean():.3f} GWh/h | '
              f'Erzg Ø {df["erzeugung_gesamt"].mean():.3f} GWh/h | '
              f'Selbstvers. {sr:.0f}%')
    print('Fertig.')
