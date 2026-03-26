"""
SMARD Daten-Download v2 – Cybersyn 2.0 Stufe 2
Korrekte Filter und Einheiten:
- SMARD gibt MWh pro Viertelstunde (Energie, nicht Leistung)
- Stundenwert = Summe von 4 Viertelstunden = MWh/h
- GWh = MWh / 1000

Korrekte Filter-IDs:
- 410  = Realisierter Stromverbrauch (Netzlast gesamt) [MWh/15min]
- 1223 = Biomasse                                      [MWh/15min]
- 1224 = Wasserkraft                                   [MWh/15min]
- 1225 = Wind Offshore                                 [MWh/15min]
- 1226 = Wind Onshore                                  [MWh/15min]
- 1227 = Photovoltaik                                  [MWh/15min]
- 1228 = Sonstige Erneuerbare                          [MWh/15min]
- 1229 = Kernenergie                                   [MWh/15min]
- 1230 = Braunkohle                                    [MWh/15min]
- 1231 = Steinkohle                                    [MWh/15min]
- 1232 = Erdgas                                        [MWh/15min]
- 1233 = Pumpspeicher                                  [MWh/15min]
- 1234 = Sonstige Konventionelle                       [MWh/15min]
"""

import requests
import json
import pandas as pd
import numpy as np
import datetime
import time
import os

BASE_URL = "https://www.smard.de/app/chart_data"

FILTERS = {
    'last':           410,    # Netzlast gesamt
    'biomasse':       1223,
    'wasserkraft':    1224,
    'wind_offshore':  1225,
    'wind_onshore':   1226,
    'solar':          1227,
    'sonstige_ee':    1228,
    'kernenergie':    1229,
    'braunkohle':     1230,
    'steinkohle':     1231,
    'erdgas':         1232,
    'pumpspeicher':   1233,
    'sonstige_kw':    1234,
}

CACHE_DIR = 'smard_cache_v2'
os.makedirs(CACHE_DIR, exist_ok=True)


def get_timestamps_2022_2023():
    url = f"{BASE_URL}/410/DE/index_quarterhour.json"
    r = requests.get(url, timeout=30)
    ts_list = r.json()['timestamps']
    ts_2022_start = int(datetime.datetime(2022, 1, 1, 0, 0, 0).timestamp() * 1000)
    ts_2024_start = int(datetime.datetime(2024, 1, 1, 0, 0, 0).timestamp() * 1000)
    return [t for t in ts_list if ts_2022_start <= t < ts_2024_start]


def fetch_week(filter_id, filter_name, timestamp):
    cache_file = os.path.join(CACHE_DIR, f"{filter_name}_{timestamp}.json")
    if os.path.exists(cache_file):
        with open(cache_file) as f:
            return json.load(f)
    url = f"{BASE_URL}/{filter_id}/DE/{filter_id}_DE_quarterhour_{timestamp}.json"
    try:
        r = requests.get(url, timeout=30)
        if r.status_code == 200 and r.text.strip():
            data = r.json()
            with open(cache_file, 'w') as f:
                json.dump(data, f)
            return data
    except Exception as e:
        print(f"    Fehler {filter_name} {timestamp}: {e}")
    return None


def series_to_series(series_data):
    """Konvertiert [[ts, val], ...] zu pandas Series mit DatetimeIndex."""
    if not series_data:
        return pd.Series(dtype=float)
    rows = {ts: val for ts, val in series_data if val is not None}
    s = pd.Series(rows)
    s.index = pd.to_datetime(s.index, unit='ms', utc=True)
    return s


def download_all(timestamps):
    """Lädt alle Filter für alle Wochen."""
    all_series = {name: [] for name in FILTERS}
    total = len(timestamps) * len(FILTERS)
    done = 0

    for i, ts in enumerate(timestamps):
        dt = datetime.datetime.fromtimestamp(ts / 1000)
        print(f"  Woche {i+1}/{len(timestamps)}: {dt.strftime('%Y-%m-%d')} ...", end='', flush=True)
        for name, fid in FILTERS.items():
            data = fetch_week(fid, name, ts)
            if data and 'series' in data:
                s = series_to_series(data['series'])
                all_series[name].append(s)
            done += 1
        print(f" OK")
        time.sleep(0.03)

    merged = {}
    for name, series_list in all_series.items():
        if series_list:
            merged[name] = pd.concat(series_list).sort_index()
    return merged


def build_hourly_df(merged):
    """
    Aggregiert 15-Min-Daten (MWh/15min) auf Stundenwerte (MWh/h = GWh/h * 1000).
    Stundenwert = Summe der 4 Viertelstunden (MWh/h)
    GWh/h = MWh/h / 1000
    """
    # Erstelle DataFrame aus allen Serien
    df = pd.DataFrame(merged)
    df.index.name = 'datetime'

    # Stündliche Aggregation: Summe der 4 Viertelstunden = MWh/h
    df_hourly = df.resample('1h').sum(min_count=1)

    # MWh/h → GWh/h
    df_hourly_gwh = df_hourly / 1000.0

    # Erzeugung gesamt (alle Quellen außer Last)
    erzeugungs_cols = [c for c in df_hourly_gwh.columns if c != 'last']
    df_hourly_gwh['erzeugung_gesamt'] = df_hourly_gwh[erzeugungs_cols].sum(axis=1, min_count=1)

    # Erneuerbare Erzeugung
    ee_cols = ['biomasse', 'wasserkraft', 'wind_offshore', 'wind_onshore', 'solar', 'sonstige_ee']
    df_hourly_gwh['erzeugung_ee'] = df_hourly_gwh[[c for c in ee_cols if c in df_hourly_gwh.columns]].sum(axis=1, min_count=1)

    # Konventionelle Erzeugung
    konv_cols = ['kernenergie', 'braunkohle', 'steinkohle', 'erdgas', 'pumpspeicher', 'sonstige_kw']
    df_hourly_gwh['erzeugung_konv'] = df_hourly_gwh[[c for c in konv_cols if c in df_hourly_gwh.columns]].sum(axis=1, min_count=1)

    # Nur 2022-2023
    df_hourly_gwh = df_hourly_gwh[
        (df_hourly_gwh.index >= pd.Timestamp('2022-01-01', tz='UTC')) &
        (df_hourly_gwh.index < pd.Timestamp('2024-01-01', tz='UTC'))
    ]

    return df_hourly_gwh


def scale_to_hamburg(df, share=0.026):
    """Skaliert auf Hamburg (2,6%)."""
    return df * share


if __name__ == '__main__':
    print("=" * 60)
    print("  SMARD v2 – Korrekte Filter & Einheiten")
    print("=" * 60)

    cache_de = 'germany_hourly_v2.csv'
    cache_hh = 'hamburg_hourly_v2.csv'

    if os.path.exists(cache_hh):
        print(f"\n  Cache gefunden: {cache_hh}")
        df_hh = pd.read_csv(cache_hh, index_col=0)
        df_hh.index = pd.to_datetime(df_hh.index, utc=True)
    else:
        print("\n[1] Timestamps laden...")
        timestamps = get_timestamps_2022_2023()
        print(f"    {len(timestamps)} Wochen")

        print("\n[2] Daten herunterladen...")
        merged = download_all(timestamps)

        print("\n[3] Stündliche Aggregation...")
        df_de = build_hourly_df(merged)
        df_de.to_csv(cache_de)

        print("\n[4] Hamburg-Skalierung (2,6%)...")
        df_hh = scale_to_hamburg(df_de, 0.026)
        df_hh.to_csv(cache_hh)

    # Validierung
    mask22 = df_hh.index.year == 2022
    mask23 = df_hh.index.year == 2023
    print(f"\n  Datenpunkte: {len(df_hh)}")
    print(f"  Zeitraum: {df_hh.index[0]} bis {df_hh.index[-1]}")
    print(f"  Hamburg Verbrauch 2022: {df_hh.loc[mask22, 'last'].sum():.0f} GWh")
    print(f"  Hamburg Verbrauch 2023: {df_hh.loc[mask23, 'last'].sum():.0f} GWh")
    print(f"  Hamburg Erzeugung 2022: {df_hh.loc[mask22, 'erzeugung_gesamt'].sum():.0f} GWh")
    print(f"  Hamburg Erzeugung 2023: {df_hh.loc[mask23, 'erzeugung_gesamt'].sum():.0f} GWh")
    print(f"  Max. Stundenlast: {df_hh['last'].max():.3f} GWh/h")
    print(f"  Min. Stundenlast: {df_hh['last'].min():.3f} GWh/h")
    print(f"  Mittlere Stundenlast: {df_hh['last'].mean():.3f} GWh/h")
    print(f"  NaN-Anteil Last: {df_hh['last'].isna().mean()*100:.1f}%")
    print(f"  Spalten: {list(df_hh.columns)}")
    print("\n  Fertig!")
