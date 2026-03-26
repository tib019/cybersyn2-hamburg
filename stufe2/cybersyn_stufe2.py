"""
Cybersyn 2.0 – Stufe 2: Stündliche Regelschleife
=================================================
Stafford Beer, "Brain of the Firm" (1972)
SMARD API Bundesnetzagentur / Eurostat nrg_bal_c

Modellarchitektur:
  Versorgung = Lokale Erzeugung + Speicher + Netzimport (begrenzt)

  Hamburg Kontext (2022):
  - Eigenversorgungsgrad: 38.7% (Nettoimporteur)
  - Netzimport: 1.0 GWh/h normal | 0.4 GWh/h Krise (Nov–Feb)
  - Speicher: 965 GWh, max. Rate: 96.5 GWh/h

  Cybersyn vs. Markt – Unterschied:
  - Cybersyn: Speicher nach Bedarfspriorität + Algedonic Channel
  - Markt: Speicher nach Preis-Spread + 6h Preissignal-Verzögerung

  Algedonic Channel (Beer 1972):
  - Aktivierung: Defizit > 10% für ≥ 3 h
  - Lastabwurf: Industrie → KMU → Haushalte (kritische Infra: nie)
"""

import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.gridspec import GridSpec
import warnings, json
warnings.filterwarnings('ignore')

plt.rcParams['font.family'] = 'DejaVu Sans'
plt.rcParams['axes.unicode_minus'] = False

# ─── Konstanten ───────────────────────────────────────────────────────────────
STORAGE_CAPACITY_GWH   = 965.0
STORAGE_MAX_RATE       = 96.5          # GWh/h (10% Kapazität)
STORAGE_INIT_RATIO     = 0.50
IMPORT_NORMAL_GWH_H    = 1.0           # Normalbetrieb
IMPORT_CRISIS_GWH_H    = 0.4           # Krise (Nov–Feb)

ALGEDONIC_THRESHOLD    = 0.10
ALGEDONIC_CONSECUTIVE  = 3

KP = 0.8
KI = 0.10


# ═══════════════════════════════════════════════════════════════════════════════
# DATEN
# ═══════════════════════════════════════════════════════════════════════════════

def load_data():
    df = pd.read_csv('hamburg_hourly_v2.csv', index_col=0)
    df.index = pd.to_datetime(df.index, utc=True)
    df = df.sort_index()
    df = df.interpolate(method='time', limit=3)
    df = df.fillna(method='ffill', limit=6).fillna(method='bfill', limit=6)

    # Import-Kapazität: Krise = Nov–Feb
    mask_crisis = (
        ((df.index.year == 2022) & (df.index.month >= 11)) |
        ((df.index.year == 2023) & (df.index.month <= 2))
    )
    df['import_cap'] = np.where(mask_crisis, IMPORT_CRISIS_GWH_H, IMPORT_NORMAL_GWH_H)
    df['is_crisis']  = mask_crisis
    return df


# ═══════════════════════════════════════════════════════════════════════════════
# ALGEDONIC CHANNEL
# ═══════════════════════════════════════════════════════════════════════════════

class AlgedonicChannel:
    def __init__(self):
        self.counter = 0
        self.active  = False
        self.events  = []

    def step(self, t, demand, supply, deficit_ratio):
        if deficit_ratio > ALGEDONIC_THRESHOLD:
            self.counter += 1
        else:
            self.counter = 0
            self.active  = False

        if self.counter >= ALGEDONIC_CONSECUTIVE and not self.active:
            self.active = True
            self.events.append({
                'time': str(t), 'deficit_ratio': float(deficit_ratio),
                'demand': float(demand), 'supply': float(supply)
            })

        shed = 0.0
        if self.active:
            # Lastabwurf: Industrie (35%) zuerst, dann KMU (25%)
            needed = min(deficit_ratio * 1.2, 0.60)
            shed   = min(needed, 0.60)

        return demand * (1.0 - shed), shed


# ═══════════════════════════════════════════════════════════════════════════════
# CYBERSYN MODELL
# ═══════════════════════════════════════════════════════════════════════════════

def run_cybersyn(df):
    n          = len(df)
    demand_raw = df['last'].values.copy()
    prod_local = df['erzeugung_gesamt'].values.copy()
    imp_cap    = df['import_cap'].values.copy()

    supply_arr  = np.zeros(n)
    storage_arr = np.zeros(n)
    deficit_arr = np.zeros(n)
    curtail_arr = np.zeros(n)
    import_arr  = np.zeros(n)
    alged_arr   = np.zeros(n, dtype=bool)
    shed_arr    = np.zeros(n)
    eff_demand  = demand_raw.copy()

    storage  = STORAGE_CAPACITY_GWH * STORAGE_INIT_RATIO
    integral = 0.0
    alged    = AlgedonicChannel()

    for t in range(n):
        d   = eff_demand[t]
        p   = prod_local[t]
        cap = imp_cap[t]

        # PI-Regler: schätzt benötigten Ausgleich
        prev = supply_arr[t-1] if t > 0 else p
        err  = d - prev
        integral = np.clip(integral + err, -d * 200, d * 200)
        adj  = KP * err + KI * integral

        # Lokale Produktion ±20%
        p_adj = np.clip(p + adj * 0.2, p * 0.80, p * 1.20)

        # Import (Cybersyn: volle Kapazität, Priorität nach Bedarf)
        raw_deficit = max(0.0, d - p_adj)
        grid_import = min(raw_deficit, cap)
        avail = p_adj + grid_import

        # Speicher
        balance = avail - d
        if balance >= 0:
            charge  = min(balance, STORAGE_MAX_RATE, STORAGE_CAPACITY_GWH - storage)
            storage += charge
            curtail  = balance - charge
            supply   = d
        else:
            discharge = min(-balance, STORAGE_MAX_RATE, storage)
            storage  -= discharge
            supply    = avail + discharge
            curtail   = 0.0

        storage = np.clip(storage, 0.0, STORAGE_CAPACITY_GWH)
        supply  = np.clip(supply,  0.0, d * 1.001)

        # Algedonic Channel
        def_ratio = max(0.0, (d - supply) / d) if d > 0 else 0.0
        d_eff, shed = alged.step(df.index[t], d, supply, def_ratio)
        eff_demand[t] = d_eff
        shed_arr[t]   = shed

        supply_arr[t]  = supply
        storage_arr[t] = storage
        deficit_arr[t] = max(0.0, d_eff - supply)
        curtail_arr[t] = curtail
        import_arr[t]  = grid_import
        alged_arr[t]   = alged.active

    sr = np.where(demand_raw > 0,
                  np.minimum(supply_arr, demand_raw) / demand_raw, 1.0)
    return {
        'demand': demand_raw, 'supply': supply_arr, 'storage': storage_arr,
        'deficit': deficit_arr, 'curtailment': curtail_arr,
        'grid_import': import_arr, 'algedonic_active': alged_arr,
        'shed': shed_arr, 'supply_rate': sr,
        'production_local': prod_local, 'algedonic_events': alged.events,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# MARKTMODELL
# ═══════════════════════════════════════════════════════════════════════════════

def run_market(df, price_delay_h=6):
    n          = len(df)
    demand_raw = df['last'].values.copy()
    prod_local = df['erzeugung_gesamt'].values.copy()
    imp_cap    = df['import_cap'].values.copy()

    supply_arr  = np.zeros(n)
    storage_arr = np.zeros(n)
    deficit_arr = np.zeros(n)
    curtail_arr = np.zeros(n)
    import_arr  = np.zeros(n)
    price_arr   = np.zeros(n)

    storage    = STORAGE_CAPACITY_GWH * STORAGE_INIT_RATIO
    base_price = 100.0

    for t in range(n):
        d   = demand_raw[t]
        p   = prod_local[t]
        cap = imp_cap[t]

        # Verzögertes Preissignal
        t_d   = max(0, t - price_delay_h)
        ps    = supply_arr[t_d] if t_d > 0 else p
        pd_   = demand_raw[t_d]
        price = np.clip(base_price * (pd_ / max(ps, 0.001)), 20.0, 500.0)
        price_arr[t] = price
        pr    = price / base_price

        # Produktionsanpassung
        p_adj = np.clip(p * (1.0 + 0.3 * (pr - 1.0)), p * 0.70, p * 1.30)

        # Import: Markt importiert weniger wenn Preis hoch
        raw_deficit = max(0.0, d - p_adj)
        import_factor = max(0.3, 1.0 - (pr - 1.0) * 0.5)
        grid_import = min(raw_deficit * import_factor, cap)
        avail = p_adj + grid_import

        balance = avail - d
        if balance >= 0:
            # Speicher laden nur wenn Preis günstig
            if price < base_price * 0.95:
                charge  = min(balance, STORAGE_MAX_RATE, STORAGE_CAPACITY_GWH - storage)
                storage += charge
                curtail  = balance - charge
            else:
                curtail  = balance
            supply = d
        else:
            # Speicher entladen nur wenn Preis hoch
            if price > base_price * 1.05:
                discharge = min(-balance, STORAGE_MAX_RATE, storage)
                storage  -= discharge
            else:
                discharge = 0.0
            supply  = avail + discharge
            curtail = 0.0

        storage = np.clip(storage, 0.0, STORAGE_CAPACITY_GWH)
        supply  = np.clip(supply,  0.0, d * 1.001)

        supply_arr[t]  = supply
        storage_arr[t] = storage
        deficit_arr[t] = max(0.0, d - supply)
        curtail_arr[t] = curtail
        import_arr[t]  = grid_import

    sr = np.where(demand_raw > 0,
                  np.minimum(supply_arr, demand_raw) / demand_raw, 1.0)
    return {
        'demand': demand_raw, 'supply': supply_arr, 'storage': storage_arr,
        'deficit': deficit_arr, 'curtailment': curtail_arr,
        'grid_import': import_arr, 'price': price_arr, 'supply_rate': sr,
        'production_local': prod_local,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# METRIKEN
# ═══════════════════════════════════════════════════════════════════════════════

def metrics(r, label=''):
    d, s = r['demand'], r['supply']
    sr   = r['supply_rate']
    return {
        'label':           label,
        'versorgungsrate': float(sr.mean() * 100),
        'gesamtdefizit':   float(r['deficit'].sum()),
        'curtailment_pct': float(r['curtailment'].sum() / d.sum() * 100),
        'rmse':            float(np.sqrt(np.mean((d - np.minimum(s, d))**2))),
        'volatilitaet':    float(sr.std() * 100),
        'total_demand':    float(d.sum()),
        'total_import':    float(r.get('grid_import', np.zeros_like(d)).sum()),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# HAUPTPROGRAMM
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    print("=" * 65)
    print("  Cybersyn 2.0 – Stufe 2: Stündliche Simulation")
    print("  Import: 1.0 GWh/h normal | 0.4 GWh/h Krise (Nov–Feb)")
    print("=" * 65)

    print("\n[1] Daten laden...")
    df = load_data()
    n  = len(df)
    mask22 = df.index.year == 2022
    print(f"    {n} Stunden | {df.index[0].date()} – {df.index[-1].date()}")
    print(f"    Verbrauch 2022:        {df.loc[mask22,'last'].sum():.0f} GWh")
    print(f"    Eigenversorgung 2022:  {df.loc[mask22,'erzeugung_gesamt'].sum()/df.loc[mask22,'last'].sum()*100:.1f}%")
    print(f"    Krisenstunden:         {df['is_crisis'].sum()} h")

    print("\n[2] Cybersyn (PI-Regler + Algedonic Channel)...")
    cs   = run_cybersyn(df)
    cs_m = metrics(cs, 'Cybersyn')
    print(f"    Versorgungsrate:  {cs_m['versorgungsrate']:.2f}%")
    print(f"    Gesamtdefizit:    {cs_m['gesamtdefizit']:.1f} GWh")
    print(f"    Curtailment:      {cs_m['curtailment_pct']:.2f}%")
    print(f"    RMSE:             {cs_m['rmse']:.4f} GWh")
    print(f"    Volatilität:      {cs_m['volatilitaet']:.4f}%")
    print(f"    Netzimport:       {cs_m['total_import']:.0f} GWh")
    print(f"    Algedonic Events: {len(cs['algedonic_events'])}")

    print("\n[3] Marktmodell (6h Preisverzögerung)...")
    mk   = run_market(df, price_delay_h=6)
    mk_m = metrics(mk, 'Markt')
    print(f"    Versorgungsrate:  {mk_m['versorgungsrate']:.2f}%")
    print(f"    Gesamtdefizit:    {mk_m['gesamtdefizit']:.1f} GWh")
    print(f"    Curtailment:      {mk_m['curtailment_pct']:.2f}%")
    print(f"    RMSE:             {mk_m['rmse']:.4f} GWh")
    print(f"    Volatilität:      {mk_m['volatilitaet']:.4f}%")
    print(f"    Netzimport:       {mk_m['total_import']:.0f} GWh")

    print("\n[4] Winter-Energiekrise 2022 (Nov 2022 – Feb 2023)...")
    mask_w = df['is_crisis'].values
    cs_wr  = np.minimum(cs['supply'][mask_w], cs['demand'][mask_w]) / cs['demand'][mask_w]
    mk_wr  = np.minimum(mk['supply'][mask_w], mk['demand'][mask_w]) / mk['demand'][mask_w]
    print(f"    Cybersyn Versorgungsrate: {cs_wr.mean()*100:.2f}%")
    print(f"    Markt   Versorgungsrate:  {mk_wr.mean()*100:.2f}%")
    print(f"    Cybersyn Defizit:         {cs['deficit'][mask_w].sum():.1f} GWh")
    print(f"    Markt   Defizit:          {mk['deficit'][mask_w].sum():.1f} GWh")

    # ─── Speichern ────────────────────────────────────────────────────────────
    pd.DataFrame({
        'datetime':       df.index.astype(str),
        'demand':         cs['demand'],
        'is_crisis':      df['is_crisis'].values.astype(int),
        'import_cap':     df['import_cap'].values,
        'cs_supply':      cs['supply'],
        'cs_storage':     cs['storage'],
        'cs_deficit':     cs['deficit'],
        'cs_curtailment': cs['curtailment'],
        'cs_import':      cs['grid_import'],
        'cs_supply_rate': cs['supply_rate'],
        'cs_algedonic':   cs['algedonic_active'].astype(int),
        'mk_supply':      mk['supply'],
        'mk_storage':     mk['storage'],
        'mk_deficit':     mk['deficit'],
        'mk_curtailment': mk['curtailment'],
        'mk_import':      mk['grid_import'],
        'mk_supply_rate': mk['supply_rate'],
        'mk_price':       mk['price'],
    }).to_csv('simulation_results.csv', index=False)

    with open('metrics.json', 'w') as f:
        json.dump({
            'cybersyn': cs_m, 'markt': mk_m,
            'winter_cybersyn': {
                'versorgungsrate': float(cs_wr.mean() * 100),
                'gesamtdefizit':   float(cs['deficit'][mask_w].sum()),
            },
            'winter_markt': {
                'versorgungsrate': float(mk_wr.mean() * 100),
                'gesamtdefizit':   float(mk['deficit'][mask_w].sum()),
            },
            'algedonic_events':    len(cs['algedonic_events']),
            'algedonic_event_list': cs['algedonic_events'],
            'n_hours': n,
            'eigenversorgungsgrad_2022': float(
                df.loc[mask22,'erzeugung_gesamt'].sum() /
                df.loc[mask22,'last'].sum() * 100),
            'import_normal_gwh_h': IMPORT_NORMAL_GWH_H,
            'import_crisis_gwh_h': IMPORT_CRISIS_GWH_H,
        }, f, indent=2, default=str)

    # ─── Zusammenfassung ──────────────────────────────────────────────────────
    print("\n" + "=" * 65)
    print("  ERGEBNISSE – CYBERSYN vs. MARKT")
    print("=" * 65)
    print(f"  {'Metrik':<38} {'Cybersyn':>10} {'Markt':>10} {'Delta':>10}")
    print("  " + "-" * 70)
    def row(lbl, cv, mv, fmt='.2f'):
        d = cv - mv
        print(f"  {lbl:<38} {cv:>10{fmt}} {mv:>10{fmt}} {'+' if d>=0 else ''}{d:>{10}{fmt}}")
    row('Versorgungsrate (%)',        cs_m['versorgungsrate'],  mk_m['versorgungsrate'])
    row('Gesamtdefizit (GWh)',        cs_m['gesamtdefizit'],    mk_m['gesamtdefizit'],  '.1f')
    row('Curtailment (%)',            cs_m['curtailment_pct'],  mk_m['curtailment_pct'])
    row('RMSE (GWh)',                 cs_m['rmse'],             mk_m['rmse'],           '.4f')
    row('Volatilitaet (%)',           cs_m['volatilitaet'],     mk_m['volatilitaet'],   '.4f')
    row('Winter-Versorgungsrate (%)', cs_wr.mean()*100,         mk_wr.mean()*100)
    row('Netzimport gesamt (GWh)',    cs_m['total_import'],     mk_m['total_import'],   '.0f')
    print(f"  {'Algedonic-Ereignisse':<38} {len(cs['algedonic_events']):>10}")
    print("\n  Fertig. Dateien: simulation_results.csv | metrics.json")
