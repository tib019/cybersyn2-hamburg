"""
cybersyn_hamburg_s3.py – Cybersyn 2.0 Stufe 3: Sektorkopplung
==============================================================
Strom + Wärme + Verkehr (E-Mobilität)
MPC-Regler mit 72h Vorausschau + Algedonic Channel (erweitert)
Vergleich: Cybersyn MPC vs. reaktiver Markt
Stresstest: Kältewelle -15°C für 72h (Jan 2023)
"""

import pandas as pd
import numpy as np
import json
import sys
import warnings
warnings.filterwarnings('ignore')

sys.path.insert(0, '/home/ubuntu/cybersyn2/stufe3')
from weather_api import load_or_fetch_weather, compute_sector_data
from mpc_controller import (
    MPCController, ELEC_STORAGE_CAP, ELEC_STORAGE_RATE,
    HEAT_STORAGE_CAP, HEAT_STORAGE_RATE,
    V2G_CAPACITY_GWH, IMPORT_NORMAL, IMPORT_CRISIS
)
from sector_coupling import ExtendedAlgedonicChannel, MarketModel3Sector


# ─── Daten laden ──────────────────────────────────────────────────────────────
def load_all_data():
    # Wetter + Sektordaten
    weather = load_or_fetch_weather()
    sector  = compute_sector_data(weather)

    # Strom-Daten aus Stufe 2
    elec = pd.read_csv('/home/ubuntu/cybersyn2/stufe2/hamburg_hourly_v2.csv',
                       index_col=0)
    elec.index = pd.to_datetime(elec.index, utc=True)

    # Auf 2022-2023 beschränken und alignieren
    start = pd.Timestamp('2022-01-01', tz='UTC')
    end   = pd.Timestamp('2023-12-31 23:00', tz='UTC')
    elec   = elec.loc[start:end]
    sector = sector.loc[start:end]

    # Gemeinsamer Index
    idx = elec.index.intersection(sector.index)
    elec   = elec.loc[idx]
    sector = sector.loc[idx]
    # Sicherstellen dass beide gleiche Länge haben
    n_min = min(len(elec), len(sector))
    elec   = elec.iloc[:n_min]
    sector = sector.iloc[:n_min]
    idx    = idx[:n_min]

    # Import-Kapazität (Krise = Nov–Feb)
    mask_crisis = (
        ((idx.month >= 11)) | (idx.month <= 2)
    )
    import_cap = np.where(mask_crisis, IMPORT_CRISIS, IMPORT_NORMAL)

    return elec, sector, idx, import_cap, mask_crisis


# ─── Kältewelle-Stresstest ────────────────────────────────────────────────────
def apply_cold_wave(sector_df, elec_df, start='2023-01-15', duration_h=72,
                    temp_delta=-15.0):
    """
    Simuliere Kältewelle: Temperatur -15°C für 72h
    → Heizbedarf +40%, E-Auto Reichweite -20% (mehr Laden)
    """
    s = sector_df.copy()
    e = elec_df.copy()
    cw_start = pd.Timestamp(start, tz='UTC')
    cw_end   = cw_start + pd.Timedelta(hours=duration_h)
    # Separate Masken für jeden DataFrame (unterschiedliche Längen möglich)
    mask_s = (s.index >= cw_start) & (s.index < cw_end)
    mask_e = (e.index >= cw_start) & (e.index < cw_end)
    # Gemeinsame Maske auf Basis des gemeinsamen Index
    common_idx = s.index  # beide haben gleichen Index nach load_all_data
    mask = mask_s

    # Temperatur absenken
    s.loc[mask_s, 'temp_c'] = s.loc[mask_s, 'temp_c'] + temp_delta
    # Heizbedarf +40%
    s.loc[mask_s, 'heat_demand'] = s.loc[mask_s, 'heat_demand'] * 1.40
    # E-Auto: 20% mehr Laden
    s.loc[mask_s, 'ev_base_demand'] = s.loc[mask_s, 'ev_base_demand'] * 1.20
    # Strom-Last leicht erhöht (Heizlüfter etc.)
    e.loc[mask_e, 'last'] = e.loc[mask_e, 'last'] * 1.05

    return s, e, mask


# ─── Cybersyn MPC Simulation ──────────────────────────────────────────────────
def run_cybersyn_mpc(elec_df, sector_df, import_cap, cold_wave_mask=None):
    n   = len(elec_df)
    mpc = MPCController(horizon=72)
    alg = ExtendedAlgedonicChannel()

    # Arrays
    cs_elec_supply  = np.zeros(n); cs_elec_storage = np.zeros(n)
    cs_elec_deficit = np.zeros(n); cs_elec_curtail  = np.zeros(n)
    cs_elec_import  = np.zeros(n)
    cs_heat_supply  = np.zeros(n); cs_heat_storage  = np.zeros(n)
    cs_heat_deficit = np.zeros(n); cs_heat_curtail  = np.zeros(n)
    cs_ev_demand    = np.zeros(n); cs_v2g_used      = np.zeros(n)
    cs_p2h          = np.zeros(n); cs_alg_elec      = np.zeros(n, dtype=bool)
    cs_alg_heat     = np.zeros(n, dtype=bool)
    cs_flex_used    = np.zeros(n)  # sektorübergreifende Flexibilität

    elec_storage = ELEC_STORAGE_CAP * 0.50
    heat_storage = HEAT_STORAGE_CAP * 0.50
    v2g_soc      = V2G_CAPACITY_GWH * 0.50

    elec_demand_arr = elec_df['last'].values.copy()
    elec_prod_arr   = elec_df['erzeugung_gesamt'].values.copy()
    heat_demand_arr = sector_df['heat_demand'].values[:n].copy()
    heat_supply_arr = (sector_df['kwk_heat'].values[:n] +
                       sector_df['solar_gen'].values[:n] * 0.1).copy()
    ev_demand_arr   = sector_df['ev_base_demand'].values[:n].copy()

    for t in range(n):
        month = elec_df.index[t].month
        hour  = elec_df.index[t].hour

        # Algedonic Channel: Defizit NACH Produktion + vollem Import
        # Nur auslösen wenn selbst mit maximalem Import nicht gedeckt
        max_possible_supply = elec_prod_arr[t] * 1.20 + import_cap[t] + elec_storage * 0.1
        elec_deficit_ratio = max(0.0, (elec_demand_arr[t] - max_possible_supply) /
                                 max(elec_demand_arr[t], 0.001))
        heat_max_supply = heat_supply_arr[t] + heat_storage * 0.1
        heat_deficit_ratio = max(0.0, (heat_demand_arr[t] - heat_max_supply) /
                                 max(heat_demand_arr[t], 0.001))
        alg_shed = alg.step(
            elec_df.index[t],
            elec_deficit_ratio,
            heat_deficit_ratio,
            elec_demand_arr[t], heat_demand_arr[t]
        )
        elec_d = elec_demand_arr[t] * (1.0 - alg_shed.get('elec', 0.0))
        heat_d = heat_demand_arr[t] * (1.0 - alg_shed.get('heat', 0.0))

        # MPC-Schritt
        er, hr, evr, actions = mpc.step(
            t, month, hour,
            elec_prod_arr[t], elec_d, elec_storage, import_cap[t],
            heat_supply_arr[t], heat_d, heat_storage,
            ev_demand_arr[t], v2g_soc
        )

        # Zustand aktualisieren
        elec_storage = er['storage']
        heat_storage = hr['storage']
        v2g_soc      = evr['v2g_soc']

        cs_elec_supply[t]  = er['supply']
        cs_elec_storage[t] = er['storage']
        cs_elec_deficit[t] = er['deficit']
        cs_elec_curtail[t] = er['curtail']
        cs_elec_import[t]  = er['import']
        cs_heat_supply[t]  = hr['supply']
        cs_heat_storage[t] = hr['storage']
        cs_heat_deficit[t] = hr['deficit']
        cs_heat_curtail[t] = hr['curtail']
        cs_ev_demand[t]    = evr['demand_adj']
        cs_v2g_used[t]     = evr['v2g_used']
        cs_p2h[t]          = actions.get('p2h', 0.0)
        cs_alg_elec[t]     = alg.active.get('elec', False)
        cs_alg_heat[t]     = alg.active.get('heat', False)
        cs_flex_used[t]    = (actions.get('p2h', 0.0) +
                               evr['v2g_used'] +
                               actions.get('ev_load_shift', 0.0))

    elec_sr = np.where(elec_demand_arr > 0,
                       np.minimum(cs_elec_supply, elec_demand_arr) / elec_demand_arr, 1.0)
    heat_sr = np.where(heat_demand_arr > 0,
                       np.minimum(cs_heat_supply, heat_demand_arr) / heat_demand_arr, 1.0)

    return {
        'elec_demand': elec_demand_arr, 'elec_supply': cs_elec_supply,
        'elec_storage': cs_elec_storage, 'elec_deficit': cs_elec_deficit,
        'elec_curtail': cs_elec_curtail, 'elec_import': cs_elec_import,
        'elec_sr': elec_sr,
        'heat_demand': heat_demand_arr, 'heat_supply': cs_heat_supply,
        'heat_storage': cs_heat_storage, 'heat_deficit': cs_heat_deficit,
        'heat_curtail': cs_heat_curtail, 'heat_sr': heat_sr,
        'ev_demand': cs_ev_demand, 'v2g_used': cs_v2g_used,
        'p2h': cs_p2h, 'flex_used': cs_flex_used,
        'alg_elec': cs_alg_elec, 'alg_heat': cs_alg_heat,
        'alg_events': alg.events,
    }


# ─── Markt-Simulation ─────────────────────────────────────────────────────────
def run_market_3sector(elec_df, sector_df, import_cap):
    n      = len(elec_df)
    market = MarketModel3Sector(price_delay_h=6)

    mk_elec_supply  = np.zeros(n); mk_elec_storage = np.zeros(n)
    mk_elec_deficit = np.zeros(n); mk_elec_curtail  = np.zeros(n)
    mk_elec_import  = np.zeros(n); mk_price         = np.zeros(n)
    mk_heat_supply  = np.zeros(n); mk_heat_storage  = np.zeros(n)
    mk_heat_deficit = np.zeros(n); mk_heat_curtail  = np.zeros(n)
    mk_ev_demand    = np.zeros(n)

    elec_storage = ELEC_STORAGE_CAP * 0.50
    heat_storage = HEAT_STORAGE_CAP * 0.50

    elec_demand_arr = elec_df['last'].values.copy()
    elec_prod_arr   = elec_df['erzeugung_gesamt'].values.copy()
    heat_demand_arr = sector_df['heat_demand'].values[:n].copy()
    heat_supply_arr = (sector_df['kwk_heat'].values[:n] +
                       sector_df['solar_gen'].values[:n] * 0.1).copy()
    ev_demand_arr   = sector_df['ev_base_demand'].values[:n].copy()

    for t in range(n):
        month = elec_df.index[t].month
        hour  = elec_df.index[t].hour

        er, hr, evr = market.step(
            t, month, hour,
            elec_prod_arr[t], elec_demand_arr[t], elec_storage, import_cap[t],
            heat_supply_arr[t], heat_demand_arr[t], heat_storage,
            ev_demand_arr[t]
        )
        elec_storage = er['storage']
        heat_storage = hr['storage']

        mk_elec_supply[t]  = er['supply']
        mk_elec_storage[t] = er['storage']
        mk_elec_deficit[t] = er['deficit']
        mk_elec_curtail[t] = er['curtail']
        mk_elec_import[t]  = er['import']
        mk_price[t]        = er['price']
        mk_heat_supply[t]  = hr['supply']
        mk_heat_storage[t] = hr['storage']
        mk_heat_deficit[t] = hr['deficit']
        mk_heat_curtail[t] = hr['curtail']
        mk_ev_demand[t]    = evr['demand_adj']

    elec_sr = np.where(elec_demand_arr > 0,
                       np.minimum(mk_elec_supply, elec_demand_arr) / elec_demand_arr, 1.0)
    heat_sr = np.where(heat_demand_arr > 0,
                       np.minimum(mk_heat_supply, heat_demand_arr) / heat_demand_arr, 1.0)

    return {
        'elec_demand': elec_demand_arr, 'elec_supply': mk_elec_supply,
        'elec_storage': mk_elec_storage, 'elec_deficit': mk_elec_deficit,
        'elec_curtail': mk_elec_curtail, 'elec_import': mk_elec_import,
        'elec_sr': elec_sr, 'price': mk_price,
        'heat_demand': heat_demand_arr, 'heat_supply': mk_heat_supply,
        'heat_storage': mk_heat_storage, 'heat_deficit': mk_heat_deficit,
        'heat_curtail': mk_heat_curtail, 'heat_sr': heat_sr,
        'ev_demand': mk_ev_demand,
    }


# ─── Metriken ─────────────────────────────────────────────────────────────────
def compute_metrics_3sector(cs, mk, mask_crisis, mask_cold):
    def m(r, prefix):
        ed = r['elec_demand']; hd = r['heat_demand']
        return {
            f'{prefix}_elec_sr':      float(r['elec_sr'].mean() * 100),
            f'{prefix}_elec_deficit': float(r['elec_deficit'].sum()),
            f'{prefix}_elec_curtail': float(r['elec_curtail'].sum() / ed.sum() * 100),
            f'{prefix}_elec_rmse':    float(np.sqrt(np.mean((ed - np.minimum(r['elec_supply'], ed))**2))),
            f'{prefix}_heat_sr':      float(r['heat_sr'].mean() * 100),
            f'{prefix}_heat_deficit': float(r['heat_deficit'].sum()),
            f'{prefix}_heat_curtail': float(r['heat_curtail'].sum() / hd.sum() * 100),
            f'{prefix}_heat_rmse':    float(np.sqrt(np.mean((hd - np.minimum(r['heat_supply'], hd))**2))),
            f'{prefix}_elec_import':  float(r['elec_import'].sum()),
            # Gesamt-Versorgungsrate (gewichtet: Strom 60%, Wärme 40%)
            f'{prefix}_total_sr':     float(r['elec_sr'].mean() * 0.6 * 100 +
                                            r['heat_sr'].mean() * 0.4 * 100),
        }
    cs_m = m(cs, 'cs')
    mk_m = m(mk, 'mk')

    # Kältewelle-Metriken
    if mask_cold.sum() > 0:
        cs_m['cs_cold_elec_sr'] = float(cs['elec_sr'][mask_cold].mean() * 100)
        cs_m['cs_cold_heat_sr'] = float(cs['heat_sr'][mask_cold].mean() * 100)
        mk_m['mk_cold_elec_sr'] = float(mk['elec_sr'][mask_cold].mean() * 100)
        mk_m['mk_cold_heat_sr'] = float(mk['heat_sr'][mask_cold].mean() * 100)

    # Sektorkopplung Flexibilität
    cs_m['cs_flex_total'] = float(cs.get('flex_used', np.zeros(1)).sum())
    cs_m['cs_p2h_total']  = float(cs.get('p2h', np.zeros(1)).sum())
    cs_m['cs_v2g_total']  = float(cs.get('v2g_used', np.zeros(1)).sum())
    cs_m['cs_alg_events'] = len(cs.get('alg_events', []))

    # CO2-Äquivalent vermiedener Importe (0.4 kg CO2/kWh = 400 t/GWh)
    import_diff = mk_m['mk_elec_import'] - cs_m['cs_elec_import']
    cs_m['cs_co2_avoided_t'] = float(import_diff * 400)

    return cs_m, mk_m


# ─── Hauptprogramm ────────────────────────────────────────────────────────────
if __name__ == '__main__':
    print("=" * 65)
    print("  Cybersyn 2.0 – Stufe 3: Sektorkopplung")
    print("  Strom + Wärme + Verkehr | MPC 72h | Algedonic Channel")
    print("=" * 65)

    print("\n[1] Daten laden...")
    elec, sector, idx, import_cap, mask_crisis = load_all_data()
    n = len(idx)
    print(f"    {n} Stunden | {idx[0].date()} – {idx[-1].date()}")
    print(f"    Ø Wärmebedarf:  {sector['heat_demand'].mean():.3f} GWh/h")
    print(f"    Ø Solarertrag:  {sector['solar_gen'].mean():.4f} GWh/h")
    print(f"    Ø E-Auto-Last:  {sector['ev_base_demand'].mean():.4f} GWh/h")

    print("\n[2] Kältewelle-Szenario vorbereiten (15. Jan 2023, 72h, -15°C)...")
    sector_cw, elec_cw, mask_cold_raw = apply_cold_wave(sector, elec)
    # mask_cold auf den gemeinsamen Index (elec_cw) ausrichten
    cw_start = pd.Timestamp('2023-01-15', tz='UTC')
    cw_end   = cw_start + pd.Timedelta(hours=72)
    mask_cold = (elec_cw.index >= cw_start) & (elec_cw.index < cw_end)
    mask_cold_s = (sector_cw.index >= cw_start) & (sector_cw.index < cw_end)
    print(f"    Kältewelle-Stunden: {mask_cold.sum()}")
    print(f"    Ø Wärmebedarf Kältewelle: {sector_cw['heat_demand'].values[mask_cold_s].mean():.3f} GWh/h")

    print("\n[3] Cybersyn MPC-Simulation...")
    cs = run_cybersyn_mpc(elec_cw, sector_cw, import_cap, mask_cold)
    print(f"    Strom-Versorgungsrate:  {cs['elec_sr'].mean()*100:.2f}%")
    print(f"    Wärme-Versorgungsrate:  {cs['heat_sr'].mean()*100:.2f}%")
    print(f"    Strom-Defizit:          {cs['elec_deficit'].sum():.1f} GWh")
    print(f"    Wärme-Defizit:          {cs['heat_deficit'].sum():.1f} GWh")
    print(f"    P2H genutzt:            {cs['p2h'].sum():.1f} GWh")
    print(f"    V2G genutzt:            {cs['v2g_used'].sum():.2f} GWh")
    print(f"    Algedonic-Ereignisse:   {len(cs['alg_events'])}")
    print(f"    Kältewelle Strom-SR:    {cs['elec_sr'][mask_cold].mean()*100:.2f}%")
    print(f"    Kältewelle Wärme-SR:    {cs['heat_sr'][mask_cold].mean()*100:.2f}%")

    print("\n[4] Markt-Simulation (3 Sektoren)...")
    mk = run_market_3sector(elec_cw, sector_cw, import_cap)
    print(f"    Strom-Versorgungsrate:  {mk['elec_sr'].mean()*100:.2f}%")
    print(f"    Wärme-Versorgungsrate:  {mk['heat_sr'].mean()*100:.2f}%")
    print(f"    Strom-Defizit:          {mk['elec_deficit'].sum():.1f} GWh")
    print(f"    Wärme-Defizit:          {mk['heat_deficit'].sum():.1f} GWh")
    print(f"    Kältewelle Strom-SR:    {mk['elec_sr'][mask_cold].mean()*100:.2f}%")
    print(f"    Kältewelle Wärme-SR:    {mk['heat_sr'][mask_cold].mean()*100:.2f}%")

    print("\n[5] Metriken berechnen...")
    cs_m, mk_m = compute_metrics_3sector(cs, mk, mask_crisis, mask_cold)

    # Ergebnisse speichern
    results_df = pd.DataFrame({
        'datetime':        idx.astype(str),
        'is_crisis':       mask_crisis.astype(int),
        'is_cold_wave':    mask_cold.astype(int),
        'elec_demand':     cs['elec_demand'],
        'heat_demand':     cs['heat_demand'],
        'cs_elec_supply':  cs['elec_supply'],
        'cs_elec_storage': cs['elec_storage'],
        'cs_elec_deficit': cs['elec_deficit'],
        'cs_elec_import':  cs['elec_import'],
        'cs_elec_sr':      cs['elec_sr'],
        'cs_heat_supply':  cs['heat_supply'],
        'cs_heat_storage': cs['heat_storage'],
        'cs_heat_deficit': cs['heat_deficit'],
        'cs_heat_sr':      cs['heat_sr'],
        'cs_p2h':          cs['p2h'],
        'cs_v2g':          cs['v2g_used'],
        'cs_flex':         cs['flex_used'],
        'cs_alg_elec':     cs['alg_elec'].astype(int),
        'cs_alg_heat':     cs['alg_heat'].astype(int),
        'mk_elec_supply':  mk['elec_supply'],
        'mk_elec_storage': mk['elec_storage'],
        'mk_elec_deficit': mk['elec_deficit'],
        'mk_elec_import':  mk['elec_import'],
        'mk_elec_sr':      mk['elec_sr'],
        'mk_heat_supply':  mk['heat_supply'],
        'mk_heat_storage': mk['heat_storage'],
        'mk_heat_deficit': mk['heat_deficit'],
        'mk_heat_sr':      mk['heat_sr'],
        'mk_price':        mk['price'],
        'temp_c':          sector_cw['temp_c'].values,
    })
    results_df.to_csv('simulation_results_s3.csv', index=False)

    all_metrics = {**cs_m, **mk_m,
                   'alg_event_list': cs['alg_events'],
                   'n_hours': n,
                   'cold_wave_hours': int(mask_cold.sum())}
    with open('metrics_s3.json', 'w') as f:
        json.dump(all_metrics, f, indent=2, default=str)

    # ── Zusammenfassung ───────────────────────────────────────────────────────
    print("\n" + "=" * 65)
    print("  ERGEBNISSE – CYBERSYN MPC vs. MARKT (3 Sektoren)")
    print("=" * 65)
    print(f"  {'Metrik':<40} {'Cybersyn':>10} {'Markt':>10}")
    print("  " + "-" * 62)
    def row(lbl, cv, mv, fmt='.2f'):
        d = cv - mv
        print(f"  {lbl:<40} {cv:>10{fmt}} {mv:>10{fmt}}  ({'+' if d>=0 else ''}{d:{fmt}})")
    row('Strom-Versorgungsrate (%)',   cs_m['cs_elec_sr'],   mk_m['mk_elec_sr'])
    row('Wärme-Versorgungsrate (%)',   cs_m['cs_heat_sr'],   mk_m['mk_heat_sr'])
    row('Gesamt-Versorgungsrate (%)',  cs_m['cs_total_sr'],  mk_m['mk_total_sr'])
    row('Strom-Defizit (GWh)',         cs_m['cs_elec_deficit'], mk_m['mk_elec_deficit'], '.1f')
    row('Wärme-Defizit (GWh)',         cs_m['cs_heat_deficit'], mk_m['mk_heat_deficit'], '.1f')
    row('Strom-RMSE (GWh)',            cs_m['cs_elec_rmse'], mk_m['mk_elec_rmse'], '.4f')
    row('Wärme-RMSE (GWh)',            cs_m['cs_heat_rmse'], mk_m['mk_heat_rmse'], '.4f')
    row('Kältewelle Strom-SR (%)',     cs_m['cs_cold_elec_sr'], mk_m['mk_cold_elec_sr'])
    row('Kältewelle Wärme-SR (%)',     cs_m['cs_cold_heat_sr'], mk_m['mk_cold_heat_sr'])
    row('Netzimport gesamt (GWh)',     cs_m['cs_elec_import'], mk_m['mk_elec_import'], '.0f')
    print(f"  {'P2H genutzt (GWh)':<40} {cs_m['cs_p2h_total']:>10.1f}")
    print(f"  {'V2G genutzt (GWh)':<40} {cs_m['cs_v2g_total']:>10.2f}")
    print(f"  {'CO2 vermieden (t)':<40} {cs_m['cs_co2_avoided_t']:>10.0f}")
    print(f"  {'Algedonic-Ereignisse':<40} {cs_m['cs_alg_events']:>10}")
    print("\n  Fertig. Dateien: simulation_results_s3.csv | metrics_s3.json")
