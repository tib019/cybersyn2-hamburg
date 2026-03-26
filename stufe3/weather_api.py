"""
weather_api.py – Open-Meteo Wetterdaten für Hamburg
Ableitung von: Heizgradtagen, Solarertrag, Windertrag
"""
import pandas as pd
import numpy as np
import json
import requests

HAMBURG_LAT = 53.55
HAMBURG_LON = 10.0
BASE_TEMP   = 15.0   # Heizgradtag-Basis (°C)

# Hamburg Sektordaten (Näherungswerte)
HEAT_PER_HDD_GWH  = 1.8 / 24   # GWh pro Gradtag → pro Stunde
SOLAR_CAPACITY_GW = 0.35        # Hamburg installierte PV-Leistung 2022 (~350 MW)
WIND_CAPACITY_GW  = 0.12        # Hamburg Onshore-Wind (~120 MW)

EV_COUNT          = 45_000      # E-Autos Hamburg 2023
EV_BATTERY_KWH    = 60.0        # Ø Batteriekapazität
EV_V2G_FRACTION   = 0.20        # 20% V2G-fähig
EV_CHARGE_POWER_KW = 11.0       # Ø Ladeleistung kW
EV_DAILY_DEMAND_KWH = 12.0      # Ø täglicher Verbrauch kWh/Fahrzeug

# Wärmespeicher
HEAT_STORAGE_GWH  = 200.0
HEAT_STORAGE_RATE = 20.0        # GWh/h max

# KWK-Kapazität Hamburg
KWK_CAPACITY_GW   = 1.5         # ~1.5 GW thermisch


def load_or_fetch_weather():
    """Wetterdaten laden oder von Open-Meteo abrufen."""
    try:
        with open('weather_raw.json') as f:
            d = json.load(f)
        print("  Wetterdaten aus Cache geladen.")
    except FileNotFoundError:
        print("  Lade Wetterdaten von Open-Meteo...")
        url = "https://archive-api.open-meteo.com/v1/archive"
        params = {
            "latitude": HAMBURG_LAT, "longitude": HAMBURG_LON,
            "start_date": "2022-01-01", "end_date": "2023-12-31",
            "hourly": "temperature_2m,shortwave_radiation,windspeed_10m",
            "timezone": "Europe/Berlin",
        }
        r = requests.get(url, params=params, timeout=60)
        d = r.json()
        with open('weather_raw.json', 'w') as f:
            json.dump(d, f)

    df = pd.DataFrame({
        'datetime':    pd.to_datetime(d['hourly']['time']),
        'temp_c':      d['hourly']['temperature_2m'],
        'solar_wm2':   d['hourly']['shortwave_radiation'],
        'wind_ms':     d['hourly']['windspeed_10m'],
    })
    df['datetime'] = df['datetime'].dt.tz_localize('Europe/Berlin', ambiguous='NaT',
                                                    nonexistent='shift_forward')
    df['datetime'] = df['datetime'].dt.tz_convert('UTC')
    df = df.dropna(subset=['datetime']).set_index('datetime').sort_index()
    return df


def compute_sector_data(weather_df):
    """Leite Sektor-Zeitreihen aus Wetterdaten ab."""
    df = weather_df.copy()

    # ── Heizgradtage & Wärmebedarf ──────────────────────────────────────────
    df['hdd_h'] = np.maximum(0, BASE_TEMP - df['temp_c']) / 24.0
    # Wärmebedarf: Heizgradtage × Faktor + Warmwasser-Grundlast
    warmwater_base = 0.8 * HEAT_PER_HDD_GWH  # Warmwasser unabhängig von Temp
    df['heat_demand'] = df['hdd_h'] * HEAT_PER_HDD_GWH * 24 + warmwater_base
    # Tagesgang-Profil (Heizung: morgens und abends)
    hour = df.index.hour
    day_profile = 1.0 + 0.3 * np.sin((hour - 6) * np.pi / 12)
    df['heat_demand'] = df['heat_demand'] * day_profile

    # ── Solarertrag ──────────────────────────────────────────────────────────
    # Wirkungsgrad ~18%, Systemverluste ~15%
    df['solar_gen'] = df['solar_wm2'] * SOLAR_CAPACITY_GW * 0.18 * 0.85 / 1000.0

    # ── Windertrag ───────────────────────────────────────────────────────────
    # Vereinfachte Windkurve: P ~ v³, cut-in 3 m/s, rated 12 m/s, cut-out 25 m/s
    v = df['wind_ms'].values
    p_wind = np.where(v < 3, 0,
             np.where(v < 12, WIND_CAPACITY_GW * ((v - 3) / 9) ** 3,
             np.where(v < 25, WIND_CAPACITY_GW, 0)))
    df['wind_gen'] = p_wind

    # ── KWK-Erzeugung ────────────────────────────────────────────────────────
    # KWK läuft wärmegeführt: mehr im Winter
    kwk_factor = np.clip(df['hdd_h'] * 24 / 10.0, 0.3, 1.0)
    df['kwk_heat'] = kwk_factor * KWK_CAPACITY_GW
    df['kwk_power'] = df['kwk_heat'] * 0.5  # Strom-Wärme-Verhältnis 1:2

    # ── E-Mobilität ──────────────────────────────────────────────────────────
    # Ladeprofile: Hauptladezeit 18-22 Uhr, Nacht-Laden 22-6 Uhr
    hour_arr = df.index.hour
    charge_profile = np.where(
        (hour_arr >= 18) & (hour_arr < 22), 0.35,
        np.where((hour_arr >= 22) | (hour_arr < 6), 0.25,
        np.where((hour_arr >= 7) & (hour_arr < 9), 0.20, 0.05))
    )
    # Gesamtladeenergie täglich: 45000 × 12 kWh × Anteil täglich laden (60%)
    daily_charge_gwh = EV_COUNT * EV_DAILY_DEMAND_KWH * 0.60 / 1e6
    df['ev_base_demand'] = charge_profile * daily_charge_gwh / charge_profile.sum() * 24

    # V2G-Kapazität: 20% × 45000 × 60 kWh × 50% SOC verfügbar
    v2g_capacity_gwh = EV_COUNT * EV_V2G_FRACTION * EV_BATTERY_KWH * 0.5 / 1e6
    df['v2g_capacity'] = v2g_capacity_gwh  # konstant verfügbar

    # Kältewelle-Effekt: Reichweite -20% → mehr Laden nötig
    cold_factor = np.where(df['temp_c'] < -5, 1.20, 1.0)
    df['ev_base_demand'] = df['ev_base_demand'] * cold_factor

    return df


if __name__ == '__main__':
    print("[weather_api] Lade und verarbeite Wetterdaten...")
    weather = load_or_fetch_weather()
    sector  = compute_sector_data(weather)
    sector.to_csv('sector_data.csv')
    print(f"  Stunden: {len(sector)}")
    print(f"  Zeitraum: {sector.index[0].date()} – {sector.index[-1].date()}")
    print(f"  Ø Wärmebedarf:  {sector['heat_demand'].mean():.3f} GWh/h")
    print(f"  Ø Solarertrag:  {sector['solar_gen'].mean():.4f} GWh/h")
    print(f"  Ø Windertrag:   {sector['wind_gen'].mean():.4f} GWh/h")
    print(f"  Ø KWK-Wärme:    {sector['kwk_heat'].mean():.3f} GWh/h")
    print(f"  Ø E-Auto-Last:  {sector['ev_base_demand'].mean():.4f} GWh/h")
    print(f"  V2G-Kapazität:  {sector['v2g_capacity'].iloc[0]*1000:.1f} MWh")
    print("  Gespeichert: sector_data.csv")
