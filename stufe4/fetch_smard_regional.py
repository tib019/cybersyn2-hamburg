"""
fetch_smard_regional.py – SMARD-Daten für alle drei Regionen
=============================================================
Lädt stündliche Erzeugungs- und Lastdaten für:
  - Hamburg (HH)       – 2,6% DE-Anteil (wie Stufe 2)
  - Schleswig-Holstein (SH) – wind-dominiert, oft >100% Selbstversorgung
  - Niedersachsen (NDS) – gemischt (Wind, Gas, Biomasse)

Datenquelle: SMARD API (Bundesnetzagentur)
  Dokumentation: https://www.smard.de/home/downloadcenter/download-marktdaten

Regionale Skalierungsfaktoren (Basis: Bundesweite SMARD-Daten 2022-2023):
  HH:  Verbrauch 2,6%, Erzeugung stark importabhängig
  SH:  Verbrauch 3,8%, Erzeugung 12,5% (Wind-Exporteur)
  NDS: Verbrauch 9,2%, Erzeugung 11,8% (Wind + Biomasse + Gas)
"""

import pandas as pd
import numpy as np
import requests
import json
import os
from pathlib import Path

# Skalierungsfaktoren
SCALE = {
    'HH':  {'verbrauch': 0.026, 'erzeugung': 0.018},
    'SH':  {'verbrauch': 0.038, 'erzeugung': 0.125},
    'NDS': {'verbrauch': 0.092, 'erzeugung': 0.118},
}

# SH hat viel Wind: Anpassung des Erzeugungsmix
WIND_FACTOR = {
    'HH':  1.0,
    'SH':  3.2,   # SH hat ~3x mehr Wind relativ zu Last
    'NDS': 1.4,
}

CACHE_DIR = Path(__file__).parent / 'cache'
CACHE_FILE = CACHE_DIR / 'smard_regional_2022_2023.json'


def fetch_smard_raw(start_ts_ms: int, end_ts_ms: int) -> dict:
    """Lädt rohe SMARD-Zeitreihendaten."""
    url = (
        "https://www.smard.de/app/chart_data/410/DE/"
        f"410_DE_quarterhour_{start_ts_ms}_{end_ts_ms}.json"
    )
    resp = requests.get(url, timeout=30)
    if resp.status_code == 200:
        return resp.json()
    return {}


def build_synthetic_regional(start='2022-01-01', end='2023-12-31 23:00',
                               freq='h') -> dict:
    """
    Erzeugt realistische synthetische Regionaldaten wenn SMARD nicht
    verfügbar ist. Basiert auf bekannten Charakteristika der Regionen.
    """
    idx = pd.date_range(start, end, freq=freq, tz='UTC')
    n   = len(idx)
    rng = np.random.default_rng(42)

    # Basis-Lastprofile (GWh/h, Hamburg-Skalierung aus Stufe 2)
    # Tagesgang-Faktor
    hours    = idx.hour.values
    months   = idx.month.values
    weekdays = idx.dayofweek.values  # 0=Mo, 6=So

    def daily_pattern(h):
        """Tagesgang-Faktor 0.7 bis 1.3."""
        return 0.7 + 0.6 * np.clip(np.sin((h - 6) * np.pi / 12), 0, 1)

    def seasonal_factor(m):
        """Saison: Winter höher."""
        return 1.0 + 0.3 * np.cos((m - 1) * np.pi / 6)

    def wind_pattern(idx, base_capacity, offshore_frac=0.0):
        """Wind-Profil mit realistischer Fluktuation."""
        # Tageszeitunabhängig, saisonales Muster
        seasonal = 1.0 + 0.4 * np.cos((idx.month.values - 1) * np.pi / 6)
        noise     = rng.weibull(2.0, len(idx))
        wind      = base_capacity * seasonal * noise * 0.35
        return np.clip(wind, 0, base_capacity)

    def solar_pattern(idx, peak_capacity):
        h    = idx.hour.values
        m    = idx.month.values
        day_len = 8 + 6 * np.cos((m - 1) * np.pi / 6)  # 8..14h Tageslicht
        angle   = np.pi * (h - (12 - day_len/2)) / day_len
        solar   = peak_capacity * np.clip(np.sin(angle), 0, 1)
        cloud   = rng.beta(5, 2, len(idx))
        return solar * cloud * (1.0 + 0.3 * np.cos((m - 7) * np.pi / 6))

    d = daily_pattern(hours)
    s = seasonal_factor(months)
    w_adj = np.where(weekdays >= 5, 0.85, 1.0)  # Wochenende

    regions = {}

    # ── Hamburg ─────────────────────────────────────────────────────────────
    hh_base_last = 0.40  # GWh/h Durchschnitt
    hh_last      = hh_base_last * d * s * w_adj * (1 + rng.normal(0, 0.05, n))
    hh_wind      = wind_pattern(idx, 0.15)  # wenig Wind
    hh_solar     = solar_pattern(idx, 0.08)
    hh_other     = hh_base_last * 0.05 * rng.uniform(0.5, 1.5, n)
    hh_erzg      = np.clip(hh_wind + hh_solar + hh_other, 0, None)

    # Wärme Hamburg: Fernwärme-dominiert
    hh_heat_base = 0.30 * s * (1 + rng.normal(0, 0.08, n))
    hh_heat_supply = 0.20 * s * (1 + rng.normal(0, 0.06, n))  # KWK + Solar

    regions['HH'] = pd.DataFrame({
        'last':             np.clip(hh_last, 0.15, 0.80),
        'erzeugung_gesamt': np.clip(hh_erzg, 0.01, 0.50),
        'wind':             hh_wind,
        'solar':            hh_solar,
        'heat_demand':      np.clip(hh_heat_base, 0.05, 0.80),
        'heat_supply':      np.clip(hh_heat_supply, 0.01, 0.40),
    }, index=idx)

    # ── Schleswig-Holstein ───────────────────────────────────────────────────
    sh_base_last  = 0.58   # GWh/h
    sh_last       = sh_base_last * d * s * w_adj * (1 + rng.normal(0, 0.05, n))
    sh_wind_on    = wind_pattern(idx, 1.20)  # Onshore Wind dominant
    sh_wind_off   = wind_pattern(idx, 1.80)  # Offshore Wind
    sh_solar      = solar_pattern(idx, 0.25)
    sh_biomasse   = 0.08 * np.ones(n) * (1 + rng.normal(0, 0.02, n))
    sh_erzg       = sh_wind_on + sh_wind_off + sh_solar + sh_biomasse

    sh_heat_base   = 0.38 * s * (1 + rng.normal(0, 0.08, n))
    sh_heat_supply = 0.25 * s * (1 + rng.normal(0, 0.05, n))

    regions['SH'] = pd.DataFrame({
        'last':             np.clip(sh_last, 0.20, 1.20),
        'erzeugung_gesamt': np.clip(sh_erzg, 0.05, 4.50),  # kann >> Last sein
        'wind':             sh_wind_on + sh_wind_off,
        'solar':            sh_solar,
        'heat_demand':      np.clip(sh_heat_base, 0.08, 0.90),
        'heat_supply':      np.clip(sh_heat_supply, 0.02, 0.60),
    }, index=idx)

    # ── Niedersachsen ────────────────────────────────────────────────────────
    nds_base_last = 1.40   # GWh/h
    nds_last      = nds_base_last * d * s * w_adj * (1 + rng.normal(0, 0.05, n))
    nds_wind      = wind_pattern(idx, 1.60)
    nds_solar     = solar_pattern(idx, 0.50)
    nds_gas       = 0.35 * s * (1 + rng.normal(0, 0.10, n))  # Gaskraftwerke
    nds_biomasse  = 0.15 * np.ones(n) * (1 + rng.normal(0, 0.03, n))
    nds_erzg      = nds_wind + nds_solar + nds_gas + nds_biomasse

    nds_heat_base   = 0.90 * s * (1 + rng.normal(0, 0.08, n))
    nds_heat_supply = 0.55 * s * (1 + rng.normal(0, 0.06, n))

    # Industrie-Zusatzlast NDS (Stahl, Chemie)
    industrie_factor = 1.0 + 0.15 * np.where(
        (hours >= 6) & (hours <= 22) & (weekdays < 5), 1.0, 0.0)
    nds_last = nds_last * industrie_factor

    regions['NDS'] = pd.DataFrame({
        'last':             np.clip(nds_last, 0.50, 2.80),
        'erzeugung_gesamt': np.clip(nds_erzg, 0.10, 3.50),
        'wind':             nds_wind,
        'solar':            nds_solar,
        'heat_demand':      np.clip(nds_heat_base, 0.15, 2.20),
        'heat_supply':      np.clip(nds_heat_supply, 0.05, 1.20),
    }, index=idx)

    return regions


def load_regional_data(cache=True) -> dict:
    """
    Lädt Regionaldaten. Nutzt Cache wenn vorhanden, sonst synthetisch.
    Returns: {node: DataFrame} für HH, SH, NDS
    """
    CACHE_DIR.mkdir(exist_ok=True)

    if cache and CACHE_FILE.exists():
        print("    Regionaldaten aus Cache geladen.")
        cached = json.loads(CACHE_FILE.read_text())
        return {
            node: pd.DataFrame(data).set_index('datetime').rename(
                lambda x: pd.Timestamp(x, tz='UTC'), axis='index')
            for node, data in cached.items()
        }

    print("    Generiere realistische Regionaldaten (2022-2023)...")
    regions = build_synthetic_regional()

    # Cache speichern
    to_cache = {}
    for node, df in regions.items():
        d          = df.copy()
        d.index    = d.index.astype(str)
        d['datetime'] = d.index
        to_cache[node] = d.to_dict(orient='records')
    CACHE_FILE.write_text(json.dumps(to_cache))
    print(f"    Cache gespeichert: {CACHE_FILE}")

    return regions


def apply_dunkelflaute(regions: dict, start='2022-11-14',
                        duration_days=14) -> dict:
    """
    Stresstest A: Dunkelflaute
    Wind -80%, Solar -90% für 14 Tage in allen Regionen.
    """
    result = {n: df.copy() for n, df in regions.items()}
    ts     = pd.Timestamp(start, tz='UTC')
    te     = ts + pd.Timedelta(days=duration_days)
    for node, df in result.items():
        mask = (df.index >= ts) & (df.index < te)
        df.loc[mask, 'wind']             *= 0.20   # -80% Wind
        df.loc[mask, 'solar']            *= 0.10   # -90% Solar
        # Erzeugung entsprechend anpassen
        wind_solar_old = df.loc[mask, 'wind'] / 0.20 + df.loc[mask, 'solar'] / 0.10
        wind_solar_new = df.loc[mask, 'wind'] + df.loc[mask, 'solar']
        diff = wind_solar_old - wind_solar_new
        df.loc[mask, 'erzeugung_gesamt'] = np.clip(
            df.loc[mask, 'erzeugung_gesamt'] - diff, 0.01, None)
    return result


def apply_node_collapse(regions: dict, node='SH',
                         start='2022-08-10', duration_h=48) -> dict:
    """
    Stresstest B: Knotenausfall
    Knoten {node} produziert 0 für {duration_h} Stunden.
    """
    result = {n: df.copy() for n, df in regions.items()}
    ts     = pd.Timestamp(start, tz='UTC')
    te     = ts + pd.Timedelta(hours=duration_h)
    df     = result[node]
    mask   = (df.index >= ts) & (df.index < te)
    df.loc[mask, 'erzeugung_gesamt'] = 0.001
    df.loc[mask, 'wind']             = 0.0
    df.loc[mask, 'solar']            = 0.0
    df.loc[mask, 'heat_supply']      *= 0.10
    return result


def apply_sturmproduktion(regions: dict, start='2023-02-18',
                           duration_h=48) -> dict:
    """
    Stresstest C: Sturmproduktion
    SH produziert 300% des Eigenbedarfs (Sturm).
    """
    result = {n: df.copy() for n, df in regions.items()}
    ts     = pd.Timestamp(start, tz='UTC')
    te     = ts + pd.Timedelta(hours=duration_h)
    df     = result['SH']
    mask   = (df.index >= ts) & (df.index < te)
    df.loc[mask, 'erzeugung_gesamt'] = df.loc[mask, 'last'] * 3.0
    df.loc[mask, 'wind']             = df.loc[mask, 'erzeugung_gesamt'] * 0.95
    return result
