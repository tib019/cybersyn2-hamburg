"""
cybersyn_nordde.py – Cybersyn 2.0 Stufe 4: Regionale Vernetzung
================================================================
Norddeutschland: Hamburg + Schleswig-Holstein + Niedersachsen

Drei regionale Knoten bilden ein fraktales Viable System Model (Beer, 1972).
Jeder Knoten ist ein vollständiges Cybersyn-3-Modell (MPC + Algedonic).
Meta-Controller koordiniert Transfers zwischen Knoten.

Stresstests:
  A – Dunkelflaute: 14 Tage, Wind -80%, Solar -90% (Nov 2022)
  B – Knotenausfall: SH fällt 48h komplett aus (Aug 2022)
  C – Sturmproduktion: SH produziert 300% (Feb 2023)

Neue Metriken:
  - Solidaritätsindex (nur Cybersyn)
  - Systemresilienz (Erholungszeit nach Schock in Stunden)
  - Netzauslastung (%)
  - Inter-Knoten-Transfers (GWh gesamt + pro Linie)
"""

import pandas as pd
import numpy as np
import json
import warnings
warnings.filterwarnings('ignore')

from node_base import RegionalNode, NodeConfig, NODES
from meta_controller import (CybersynMetaController, MarketMetaController,
                               CAPACITY)
from fetch_smard_regional import (load_regional_data,
                                   apply_dunkelflaute,
                                   apply_node_collapse,
                                   apply_sturmproduktion)


# ─── Knotenkonfigurationen ────────────────────────────────────────────────────
def make_nodes():
    """Erzeugt die drei regionalen Knoten."""
    hh = RegionalNode(NodeConfig(
        name='Hamburg',
        elec_storage_cap=965.0,   elec_storage_rate=96.5,
        heat_storage_cap=200.0,   heat_storage_rate=20.0,
        import_cap_normal=1.0,    import_cap_crisis=0.4,
        scale_factor=0.026,
        has_ev=True,              ev_capacity_gwh=0.270,
    ))
    sh = RegionalNode(NodeConfig(
        name='Schleswig-Holstein',
        elec_storage_cap=1200.0,  elec_storage_rate=120.0,
        heat_storage_cap=280.0,   heat_storage_rate=28.0,
        import_cap_normal=0.8,    import_cap_crisis=0.3,
        scale_factor=0.125,
    ))
    nds = RegionalNode(NodeConfig(
        name='Niedersachsen',
        elec_storage_cap=2000.0,  elec_storage_rate=200.0,
        heat_storage_cap=450.0,   heat_storage_rate=45.0,
        import_cap_normal=1.5,    import_cap_crisis=0.6,
        scale_factor=0.118,
    ))
    return {'HH': hh, 'SH': sh, 'NDS': nds}


def is_crisis_period(ts):
    """Winter = Krisenperiode für Import-Kapazität."""
    return ts.month in [11, 12, 1, 2]


# ─── Hauptsimulation ─────────────────────────────────────────────────────────
def run_simulation(regions: dict, mode='cybersyn', label='') -> dict:
    """
    Führt die Simulation für alle Knoten + Meta-Controller durch.
    mode: 'cybersyn' oder 'market'
    """
    nodes   = make_nodes()
    meta    = CybersynMetaController() if mode == 'cybersyn' else MarketMetaController()

    idx     = regions['HH'].index
    n       = len(idx)
    results = {node: [] for node in NODES}
    line_loads_all = []

    # Transfers aus dem vorherigen Schritt (Cybersyn kennt Transfers im Voraus)
    pending_transfers = {node: {'transfer_in_elec': 0.0, 'transfer_in_heat': 0.0}
                         for node in NODES}

    for t in range(n):
        ts = idx[t]
        crisis = is_crisis_period(ts)

        # Schritt 1: Jeder Knoten läuft mit den Transfers des vorherigen Schritts
        step_results = {}
        for node in NODES:
            df       = regions[node]
            ep       = float(df['erzeugung_gesamt'].iloc[t])
            ed       = float(df['last'].iloc[t])
            hs       = float(df['heat_supply'].iloc[t])
            hd       = float(df['heat_demand'].iloc[t])
            t_elec   = pending_transfers[node]['transfer_in_elec']
            t_heat   = pending_transfers[node]['transfer_in_heat']
            result   = nodes[node].step(ts, ep, ed, hs, hd, crisis, t_elec, t_heat)
            result['elec_surplus'] = nodes[node].last_elec_surplus
            result['elec_deficit'] = nodes[node].last_elec_deficit
            result['heat_surplus'] = nodes[node].last_heat_surplus
            result['heat_deficit'] = nodes[node].last_heat_deficit
            step_results[node]     = result
            results[node].append(result)

        # Schritt 2: Meta-Controller koordiniert für nächsten Schritt
        pending_transfers, line_load = meta.coordinate(ts, step_results)
        line_loads_all.append(line_load)

    # ── Ergebnisse aggregieren ────────────────────────────────────────────────
    agg = {}
    for node in NODES:
        df = pd.DataFrame(results[node], index=idx)
        agg[node] = df

    # Netzauslastung
    line_df = pd.DataFrame(line_loads_all, index=idx)

    return {
        'nodes':      agg,
        'line_loads': line_df,
        'meta':       meta,
        'idx':        idx,
    }


# ─── Metriken ─────────────────────────────────────────────────────────────────
def compute_metrics(sim_result: dict, stress_mask: pd.Series,
                     label: str) -> dict:
    nodes   = sim_result['nodes']
    ll      = sim_result['line_loads']
    meta    = sim_result['meta']
    m       = {}

    # Netzweite Metriken
    total_elec_demand  = sum(nodes[n]['elec_demand'].sum()  for n in NODES)
    total_elec_deficit = sum(nodes[n]['elec_deficit'].sum() for n in NODES)
    total_heat_demand  = sum(nodes[n]['heat_demand'].sum()  for n in NODES)
    total_heat_deficit = sum(nodes[n]['heat_deficit'].sum() for n in NODES)
    total_curtail      = sum(nodes[n]['elec_curtail'].sum() + nodes[n]['heat_curtail'].sum()
                             for n in NODES)

    m[f'{label}_net_elec_sr']      = (1 - total_elec_deficit / max(total_elec_demand, 1)) * 100
    m[f'{label}_net_heat_sr']      = (1 - total_heat_deficit / max(total_heat_demand, 1)) * 100
    m[f'{label}_total_sr']         = (m[f'{label}_net_elec_sr'] * 0.6 +
                                       m[f'{label}_net_heat_sr'] * 0.4)
    m[f'{label}_elec_deficit_gwh'] = total_elec_deficit
    m[f'{label}_heat_deficit_gwh'] = total_heat_deficit
    m[f'{label}_curtail_gwh']      = total_curtail

    # Knotenweise Versorgungsraten
    for node in NODES:
        ed  = nodes[node]['elec_demand']
        hd  = nodes[node]['heat_demand']
        esr = (1 - nodes[node]['elec_deficit'] / ed.replace(0, np.nan)).fillna(1.0)
        hsr = (1 - nodes[node]['heat_deficit'] / hd.replace(0, np.nan)).fillna(1.0)
        m[f'{label}_{node}_elec_sr'] = esr.mean() * 100
        m[f'{label}_{node}_heat_sr'] = hsr.mean() * 100

    # Stresstest-Periode
    if stress_mask.any():
        s_elec_def = sum(nodes[n]['elec_deficit'][stress_mask].sum() for n in NODES)
        s_elec_dem = sum(nodes[n]['elec_demand'][stress_mask].sum()  for n in NODES)
        s_heat_def = sum(nodes[n]['heat_deficit'][stress_mask].sum() for n in NODES)
        s_heat_dem = sum(nodes[n]['heat_demand'][stress_mask].sum()  for n in NODES)
        m[f'{label}_stress_elec_sr'] = (1 - s_elec_def / max(s_elec_dem, 1)) * 100
        m[f'{label}_stress_heat_sr'] = (1 - s_heat_def / max(s_heat_dem, 1)) * 100

    # Systemresilienz: Stunden bis Versorgungsrate > 95% nach Stresstest
    if stress_mask.any():
        post_stress_start = stress_mask.index[stress_mask][-1]
        post = sim_result['idx'] > post_stress_start
        recovery_h = 0
        for node in NODES:
            esr = (1 - nodes[node]['elec_deficit'] / nodes[node]['elec_demand'].replace(0, np.nan)).fillna(1.0)
            post_esr = esr[post]
            if len(post_esr) > 0:
                below = (post_esr < 0.95)
                recovery_h = max(recovery_h, int(below.cumsum().max()))
        m[f'{label}_recovery_hours'] = recovery_h

    # Netzauslastung
    if len(ll.columns) > 0:
        line_util = {}
        for col in ll.columns:
            cap = CAPACITY.get(col, 1.0)
            line_util[str(col)] = float((ll[col] / cap).mean() * 100)
        m[f'{label}_avg_line_utilization'] = np.mean(list(line_util.values()))
        m[f'{label}_line_utilization']     = line_util

    # Transfers
    total_transfers = sum(sim_result['meta'].total_transfers)
    m[f'{label}_transfers_gwh'] = total_transfers

    # Solidaritätsindex (nur Cybersyn)
    if hasattr(meta, 'solidarity_index'):
        m[f'{label}_solidarity_index'] = meta.solidarity_index
        m[f'{label}_mandatory_crisis_events'] = len(meta.meta_alg.events)

    # CO2-Vermeidung durch Netz-Solidarität
    # Vermiedene lokale Erzeugung aus Importen durch Netzausgleich
    total_import = sum(nodes[n]['elec_import'].sum() for n in NODES)
    m[f'{label}_elec_import_gwh'] = total_import
    m[f'{label}_co2_avoided_t']   = total_transfers * 400  # 400 t CO2/GWh

    return m


def compute_skalierung_tabelle(metrics_all: list) -> pd.DataFrame:
    """Skalierungspfad-Tabelle über alle Stufen."""
    rows = [
        {'Stufe': 1, 'Beschreibung': 'Jahreswerte, Eurostat',
         'Cybersyn SR (%)': 99.4, 'Markt SR (%)': 98.6, 'Defizit-Reduktion (%)': 60},
        {'Stufe': 2, 'Beschreibung': 'Stundenwerte, SMARD',
         'Cybersyn SR (%)': 95.5, 'Markt SR (%)': 93.8, 'Defizit-Reduktion (%)': 88},
        {'Stufe': 3, 'Beschreibung': 'Sektorkopplung + MPC',
         'Cybersyn SR (%)': 84.0, 'Markt SR (%)': 63.8, 'Defizit-Reduktion (%)': 84},
    ]
    for entry in metrics_all:
        rows.append(entry)
    return pd.DataFrame(rows)


# ─── Hauptprogramm ────────────────────────────────────────────────────────────
if __name__ == '__main__':
    import sys
    sys.path.insert(0, str(__import__('pathlib').Path(__file__).parent))

    print("=" * 70)
    print("  Cybersyn 2.0 – Stufe 4: Regionale Vernetzung")
    print("  Hamburg + Schleswig-Holstein + Niedersachsen | Fraktales VSM")
    print("=" * 70)

    print("\n[1] Regionaldaten laden (2022–2023)...")
    regions_base = load_regional_data()
    idx = regions_base['HH'].index
    n   = len(idx)
    print(f"    {n} Stunden | {idx[0].date()} – {idx[-1].date()}")
    for node in NODES:
        df = regions_base[node]
        print(f"    {node}: Last Ø {df['last'].mean():.3f} GWh/h | "
              f"Erzg Ø {df['erzeugung_gesamt'].mean():.3f} GWh/h | "
              f"Selbstvers. {df['erzeugung_gesamt'].mean()/df['last'].mean()*100:.0f}%")

    # ── Stresstest A: Dunkelflaute ────────────────────────────────────────────
    print("\n[2] Stresstest A: Dunkelflaute (14 Nov–28 Nov 2022, Wind -80%, Solar -90%)")
    regions_dk  = apply_dunkelflaute(regions_base)
    ts_dk_start = pd.Timestamp('2022-11-14', tz='UTC')
    ts_dk_end   = pd.Timestamp('2022-11-28', tz='UTC')
    mask_dk     = pd.Series((idx >= ts_dk_start) & (idx < ts_dk_end), index=idx)

    print("    Cybersyn-Simulation...")
    cs_dk = run_simulation(regions_dk, mode='cybersyn', label='cs_dk')
    print("    Markt-Simulation...")
    mk_dk = run_simulation(regions_dk, mode='market',   label='mk_dk')
    m_cs_dk = compute_metrics(cs_dk, mask_dk, 'cs_dk')
    m_mk_dk = compute_metrics(mk_dk, mask_dk, 'mk_dk')

    print(f"    Cybersyn Gesamt-SR: {m_cs_dk['cs_dk_total_sr']:.2f}% | "
          f"Dunkelflaute Strom: {m_cs_dk.get('cs_dk_stress_elec_sr', 0):.2f}%")
    print(f"    Markt    Gesamt-SR: {m_mk_dk['mk_dk_total_sr']:.2f}% | "
          f"Dunkelflaute Strom: {m_mk_dk.get('mk_dk_stress_elec_sr', 0):.2f}%")
    print(f"    Solidaritätsindex: {m_cs_dk.get('cs_dk_solidarity_index', 0):.3f}")

    # ── Stresstest B: Knotenausfall SH ───────────────────────────────────────
    print("\n[3] Stresstest B: SH-Knotenausfall (10–12 Aug 2022, 48h)")
    regions_ko  = apply_node_collapse(regions_base, node='SH')
    ts_ko_start = pd.Timestamp('2022-08-10', tz='UTC')
    ts_ko_end   = pd.Timestamp('2022-08-12', tz='UTC')
    mask_ko     = pd.Series((idx >= ts_ko_start) & (idx < ts_ko_end), index=idx)

    print("    Cybersyn-Simulation...")
    cs_ko = run_simulation(regions_ko, mode='cybersyn', label='cs_ko')
    print("    Markt-Simulation...")
    mk_ko = run_simulation(regions_ko, mode='market',   label='mk_ko')
    m_cs_ko = compute_metrics(cs_ko, mask_ko, 'cs_ko')
    m_mk_ko = compute_metrics(mk_ko, mask_ko, 'mk_ko')

    print(f"    Cybersyn Ausfall-SR: {m_cs_ko.get('cs_ko_stress_elec_sr', 0):.2f}% | "
          f"Erholung: {m_cs_ko.get('cs_ko_recovery_hours', 0)}h")
    print(f"    Markt    Ausfall-SR: {m_mk_ko.get('mk_ko_stress_elec_sr', 0):.2f}% | "
          f"Erholung: {m_mk_ko.get('mk_ko_recovery_hours', 0)}h")

    # ── Stresstest C: Sturmproduktion ─────────────────────────────────────────
    print("\n[4] Stresstest C: Sturmproduktion SH (18–20 Feb 2023, 300% Eigenbedarf)")
    regions_st  = apply_sturmproduktion(regions_base)
    ts_st_start = pd.Timestamp('2023-02-18', tz='UTC')
    ts_st_end   = pd.Timestamp('2023-02-20', tz='UTC')
    mask_st     = pd.Series((idx >= ts_st_start) & (idx < ts_st_end), index=idx)

    print("    Cybersyn-Simulation...")
    cs_st = run_simulation(regions_st, mode='cybersyn', label='cs_st')
    print("    Markt-Simulation...")
    mk_st = run_simulation(regions_st, mode='market',   label='mk_st')
    m_cs_st = compute_metrics(cs_st, mask_st, 'cs_st')
    m_mk_st = compute_metrics(mk_st, mask_st, 'mk_st')

    cs_st_curtail = sum(cs_st['nodes'][n]['elec_curtail'].sum() for n in NODES)
    mk_st_curtail = sum(mk_st['nodes'][n]['elec_curtail'].sum() for n in NODES)
    print(f"    Cybersyn Curtailment: {cs_st_curtail:.1f} GWh | "
          f"Transfers genutzt: {m_cs_st['cs_st_transfers_gwh']:.1f} GWh")
    print(f"    Markt    Curtailment: {mk_st_curtail:.1f} GWh | "
          f"Transfers genutzt: {m_mk_st['mk_st_transfers_gwh']:.1f} GWh")

    # ── Skalierungstabelle ────────────────────────────────────────────────────
    print("\n[5] Skalierungspfad Stufe 1 → 4")
    stufe4_row = {
        'Stufe':                 4,
        'Beschreibung':          'Regionale Vernetzung (3 Knoten)',
        'Cybersyn SR (%)':       m_cs_dk['cs_dk_total_sr'],
        'Markt SR (%)':          m_mk_dk['mk_dk_total_sr'],
        'Defizit-Reduktion (%)': round((1 - m_cs_dk['cs_dk_elec_deficit_gwh'] /
                                        max(m_mk_dk['mk_dk_elec_deficit_gwh'], 0.001)) * 100, 1),
    }
    skalierung = compute_skalierung_tabelle([stufe4_row])

    # ── Zusammenfassung ───────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("  ERGEBNISSE STUFE 4 – DUNKELFLAUTE (HAUPTSZENARIO)")
    print("=" * 70)
    print(f"  {'Metrik':<45} {'Cybersyn':>10} {'Markt':>10}")
    print("  " + "-" * 67)

    def row(lbl, cv, mv, fmt='.2f'):
        d = cv - mv
        print(f"  {lbl:<45} {cv:>10{fmt}} {mv:>10{fmt}}  ({'+' if d>=0 else ''}{d:{fmt}})")

    row('Gesamt-Versorgungsrate (%)',          m_cs_dk['cs_dk_total_sr'],         m_mk_dk['mk_dk_total_sr'])
    row('Strom-Versorgungsrate (%)',            m_cs_dk['cs_dk_net_elec_sr'],      m_mk_dk['mk_dk_net_elec_sr'])
    row('Wärme-Versorgungsrate (%)',            m_cs_dk['cs_dk_net_heat_sr'],      m_mk_dk['mk_dk_net_heat_sr'])
    row('Dunkelflaute Strom-SR (%)',            m_cs_dk.get('cs_dk_stress_elec_sr', 0), m_mk_dk.get('mk_dk_stress_elec_sr', 0))
    row('Strom-Defizit gesamt (GWh)',           m_cs_dk['cs_dk_elec_deficit_gwh'], m_mk_dk['mk_dk_elec_deficit_gwh'], '.1f')
    row('Netzimport gesamt (GWh)',              m_cs_dk['cs_dk_elec_import_gwh'],  m_mk_dk['mk_dk_elec_import_gwh'],  '.1f')
    row('Ø Leitungsauslastung (%)',             m_cs_dk.get('cs_dk_avg_line_utilization', 0),
                                               m_mk_dk.get('mk_dk_avg_line_utilization', 0))
    print(f"  {'Solidaritätsindex':<45} {m_cs_dk.get('cs_dk_solidarity_index', 0):>10.3f}")
    print(f"  {'Pflicht-Krisenereignisse':<45} {m_cs_dk.get('cs_dk_mandatory_crisis_events', 0):>10}")
    print(f"  {'CO2 vermieden (t)':<45} {m_cs_dk.get('cs_dk_co2_avoided_t', 0):>10.0f}")

    print("\n  KNOTENAUSFALL SH (48h)")
    row('SH Ausfall Strom-SR (%)',       m_cs_ko.get('cs_ko_stress_elec_sr', 0), m_mk_ko.get('mk_ko_stress_elec_sr', 0))
    print(f"  {'Erholungszeit (h)':<45} {'CS: ' + str(m_cs_ko.get('cs_ko_recovery_hours', 0)):>10} "
          f"{'Mk: ' + str(m_mk_ko.get('mk_ko_recovery_hours', 0)):>10}")

    print("\n  STURMPRODUKTION SH")
    row('Curtailment SH-Sturm (GWh)',    cs_st_curtail, mk_st_curtail, '.1f')
    row('Netz-Transfers genutzt (GWh)',  m_cs_st['cs_st_transfers_gwh'], m_mk_st['mk_st_transfers_gwh'], '.1f')

    print("\n  SKALIERUNGSPFAD")
    print("  " + skalierung.to_string(index=False))

    # ── Ergebnisse speichern ──────────────────────────────────────────────────
    all_metrics = {
        'dunkelflaute': {**m_cs_dk, **m_mk_dk},
        'knotenausfall': {**m_cs_ko, **m_mk_ko},
        'sturmproduktion': {**m_cs_st, **m_mk_st},
        'skalierung': skalierung.to_dict(orient='records'),
    }
    with open('metrics_s4.json', 'w') as f:
        json.dump(all_metrics, f, indent=2, default=str)

    # Stunden-Daten für Dashboard
    for scenario, sim_cs, sim_mk in [
        ('dunkelflaute', cs_dk, mk_dk),
        ('knotenausfall', cs_ko, mk_ko),
        ('sturmproduktion', cs_st, mk_st),
    ]:
        rows = []
        for node in NODES:
            df_cs = sim_cs['nodes'][node].copy()
            df_mk = sim_mk['nodes'][node].copy()
            df_cs.columns = [f'cs_{c}' for c in df_cs.columns]
            df_mk.columns = [f'mk_{c}' for c in df_mk.columns]
            df_combined = pd.concat([df_cs, df_mk], axis=1)
            df_combined['node'] = node
            rows.append(df_combined)
        pd.concat(rows).to_csv(f'results_s4_{scenario}.csv')

    print(f"\n  Fertig. Dateien: metrics_s4.json | results_s4_*.csv")
