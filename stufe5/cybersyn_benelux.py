"""
cybersyn_benelux.py – Cybersyn 2.0 Stufe 5: Benelux + Norddeutschland
======================================================================
6-Knoten fraktales Viable System Model:
  Cluster DE:  Hamburg (HH) + Schleswig-Holstein (SH) + Niedersachsen (NDS)
  Cluster BNL: Niederlande (NL) + Belgien (BE) + Luxemburg (LU)

Datenquellen:
  DE-Cluster:  SMARD API (Bundesnetzagentur) – identisch zu Stufe 4
  BNL-Cluster: ENTSO-E Transparency Platform (oder synthetische Profile)

Stresstests:
  A – Belgischer Atomausfall: Alle AKW offline, 3 Wochen (Mär 2023)
  B – Niederländische Gasdisruption: Groningen-Abschaltung, 5 Tage (Jan 2023)
  C – Nordsee-Sturm: Offshore-Wind 350%, Last +15% (Feb 2023)
  D – Dunkelflaute + Atomausfall kombiniert (worst case)

Neue Metriken:
  - Cluster-Solidaritätsindex (DE ↔ BNL)
  - Inter-Cluster-Transfers (GWh)
  - Zwei-Ebenen-Resilienz (Cluster-Ebene + Super-Meta-Ebene)
  - Atomausfall-Absorptionsfähigkeit
"""

import sys
import json
import warnings
warnings.filterwarnings('ignore')
from pathlib import Path

import numpy as np
import pandas as pd

# Stufe 4 Module
sys.path.insert(0, str(Path(__file__).parent.parent / 'stufe4'))
from node_base import RegionalNode, NodeConfig
from meta_controller import NODES as DE_NODES, CAPACITY as DE_CAPACITY
from fetch_smard_regional import load_regional_data as load_de_data

# Stufe 5 Module
from fetch_entso_e import (
    load_benelux_data,
    apply_nuclear_phase_out,
    apply_gas_disruption,
    apply_nordsee_sturm,
)
from meta_controller_s5 import (
    BeneluxCybersynMeta, BeneluxMarketMeta,
    DE_CybersynMeta, DE_MarketMeta,
    SuperMetaController,
    BNL_NODES, ALL_NODES,
    BNL_CAPACITY, INTER_CAPACITY,
)


# ── Knotenkonfigurationen ─────────────────────────────────────────────────────

def make_de_nodes():
    """Norddeutschland-Knoten (identisch zu Stufe 4)."""
    return {
        'HH': RegionalNode(NodeConfig(
            name='Hamburg',
            elec_storage_cap=965.0,   elec_storage_rate=96.5,
            heat_storage_cap=200.0,   heat_storage_rate=20.0,
            import_cap_normal=1.0,    import_cap_crisis=0.4,
            scale_factor=0.026,       has_ev=True, ev_capacity_gwh=0.270,
        )),
        'SH': RegionalNode(NodeConfig(
            name='Schleswig-Holstein',
            elec_storage_cap=1200.0,  elec_storage_rate=120.0,
            heat_storage_cap=280.0,   heat_storage_rate=28.0,
            import_cap_normal=0.8,    import_cap_crisis=0.3,
            scale_factor=0.125,
        )),
        'NDS': RegionalNode(NodeConfig(
            name='Niedersachsen',
            elec_storage_cap=2000.0,  elec_storage_rate=200.0,
            heat_storage_cap=450.0,   heat_storage_rate=45.0,
            import_cap_normal=1.5,    import_cap_crisis=0.6,
            scale_factor=0.118,
        )),
    }


def make_bnl_nodes():
    """
    Benelux-Knoten.
    Kapazitäten basieren auf ENTSO-E Statistical Factsheet 2023
    und nationalen Netzentwicklungsplänen.
    """
    return {
        # NL: Großer Offshore-Wind-Überschuss, hoher Gasanteil historisch
        'NL': RegionalNode(NodeConfig(
            name='Niederlande',
            elec_storage_cap=3800.0,  elec_storage_rate=380.0,  # Pumpspeicher + Batterien
            heat_storage_cap=800.0,   heat_storage_rate=80.0,
            import_cap_normal=3.5,    import_cap_crisis=2.0,    # Hohe Importkapazität
            scale_factor=0.230,
        )),
        # BE: Nuklear-Grundlast (Doel + Tihange), strukturell Exporteur
        'BE': RegionalNode(NodeConfig(
            name='Belgien',
            elec_storage_cap=2200.0,  elec_storage_rate=220.0,
            heat_storage_cap=500.0,   heat_storage_rate=50.0,
            import_cap_normal=2.8,    import_cap_crisis=1.5,
            scale_factor=0.160,
        )),
        # LU: Klein, hochvernetzt, hauptsächlich Importeur
        'LU': RegionalNode(NodeConfig(
            name='Luxemburg',
            elec_storage_cap=180.0,   elec_storage_rate=18.0,
            heat_storage_cap=40.0,    heat_storage_rate=4.0,
            import_cap_normal=0.5,    import_cap_crisis=0.2,
            scale_factor=0.012,
        )),
    }


def is_crisis_period(ts):
    return ts.month in [11, 12, 1, 2]


# ── Simulation ────────────────────────────────────────────────────────────────

def run_simulation(de_regions: dict, bnl_regions: dict,
                   mode='cybersyn', label='') -> dict:
    """
    Zweistufige VSM-Simulation für alle 6 Knoten.

    Architektur:
      1. Jeder Knoten läuft autonom (RegionalNode.step)
      2. DE-Cluster-Meta koordiniert HH/SH/NDS
      3. BNL-Cluster-Meta koordiniert NL/BE/LU
      4. Super-Meta koordiniert Inter-Cluster-Transfers
    """
    de_nodes  = make_de_nodes()
    bnl_nodes = make_bnl_nodes()

    if mode == 'cybersyn':
        de_meta   = DE_CybersynMeta()
        bnl_meta  = BeneluxCybersynMeta()
        super_meta = SuperMetaController(mode='cybersyn')
    else:
        de_meta   = DE_MarketMeta()
        bnl_meta  = BeneluxMarketMeta()
        super_meta = SuperMetaController(mode='market')

    idx = de_regions['HH'].index
    n   = len(idx)

    results = {node: [] for node in ALL_NODES}
    de_line_loads  = []
    bnl_line_loads = []
    inter_transfers_log = []

    de_pending  = {node: {'transfer_in_elec': 0.0, 'transfer_in_heat': 0.0}
                   for node in DE_NODES}
    bnl_pending = {node: {'transfer_in_elec': 0.0, 'transfer_in_heat': 0.0}
                   for node in BNL_NODES}

    for t in range(n):
        ts     = idx[t]
        crisis = is_crisis_period(ts)

        # ── DE-Cluster Schritt ────────────────────────────────────────────
        de_step = {}
        for node in DE_NODES:
            df  = de_regions[node]
            res = de_nodes[node].step(
                ts,
                float(df['erzeugung_gesamt'].iloc[t]),
                float(df['last'].iloc[t]),
                float(df['heat_supply'].iloc[t]),
                float(df['heat_demand'].iloc[t]),
                crisis,
                de_pending[node]['transfer_in_elec'],
                de_pending[node]['transfer_in_heat'],
            )
            res['elec_surplus'] = de_nodes[node].last_elec_surplus
            res['elec_deficit'] = de_nodes[node].last_elec_deficit
            res['heat_surplus'] = de_nodes[node].last_heat_surplus
            res['heat_deficit'] = de_nodes[node].last_heat_deficit
            de_step[node] = res
            results[node].append(res)

        # ── BNL-Cluster Schritt ───────────────────────────────────────────
        bnl_step = {}
        for node in BNL_NODES:
            df  = bnl_regions[node]
            res = bnl_nodes[node].step(
                ts,
                float(df['erzeugung_gesamt'].iloc[t]),
                float(df['last'].iloc[t]),
                float(df['heat_supply'].iloc[t]),
                float(df['heat_demand'].iloc[t]),
                crisis,
                bnl_pending[node]['transfer_in_elec'],
                bnl_pending[node]['transfer_in_heat'],
            )
            res['elec_surplus'] = bnl_nodes[node].last_elec_surplus
            res['elec_deficit'] = bnl_nodes[node].last_elec_deficit
            res['heat_surplus'] = bnl_nodes[node].last_heat_surplus
            res['heat_deficit'] = bnl_nodes[node].last_heat_deficit
            bnl_step[node] = res
            results[node].append(res)

        # ── Intra-Cluster Meta-Koordination ───────────────────────────────
        de_pending,  de_ll  = de_meta.coordinate(ts, de_step)
        bnl_pending, bnl_ll = bnl_meta.coordinate(ts, bnl_step)
        de_line_loads.append(de_ll)
        bnl_line_loads.append(bnl_ll)

        # ── Inter-Cluster Super-Meta ──────────────────────────────────────
        de_net_surplus  = sum(de_step[n]['elec_surplus']  - de_step[n]['elec_deficit']
                              for n in DE_NODES)
        bnl_net_surplus = sum(bnl_step[n]['elec_surplus'] - bnl_step[n]['elec_deficit']
                              for n in BNL_NODES)
        de_crisis_cluster  = any(de_step[n]['in_crisis']  for n in DE_NODES)
        bnl_crisis_cluster = any(bnl_step[n]['in_crisis'] for n in BNL_NODES)

        de_export, bnl_export = super_meta.coordinate_inter(
            ts,
            {'elec': max(0, de_net_surplus),  'heat': 0.0},
            {'elec': max(0, bnl_net_surplus), 'heat': 0.0},
            de_crisis_cluster,
            bnl_crisis_cluster,
        )

        # Inter-Cluster-Transfer auf Grenzknoten buchen
        # DE → BNL: NDS und SH exportieren nach NL
        if de_export > 0:
            cap_nds = INTER_CAPACITY[('NDS', 'NL')]
            cap_sh  = INTER_CAPACITY[('SH',  'NL')]
            total   = cap_nds + cap_sh
            nds_share = de_export * cap_nds / total
            sh_share  = de_export * cap_sh  / total
            bnl_pending['NL']['transfer_in_elec'] = (
                bnl_pending['NL']['transfer_in_elec'] + nds_share + sh_share
            )
        if bnl_export > 0:
            cap_nl_nds = INTER_CAPACITY[('NL', 'NDS')]
            cap_nl_sh  = INTER_CAPACITY[('NL', 'SH')]
            total      = cap_nl_nds + cap_nl_sh
            de_pending['NDS']['transfer_in_elec'] = (
                de_pending['NDS']['transfer_in_elec'] + bnl_export * cap_nl_nds / total
            )
            de_pending['SH']['transfer_in_elec'] = (
                de_pending['SH']['transfer_in_elec'] + bnl_export * cap_nl_sh / total
            )

        inter_transfers_log.append({'de_export': de_export, 'bnl_export': bnl_export})

    agg = {node: pd.DataFrame(results[node], index=idx) for node in ALL_NODES}

    return {
        'nodes':          agg,
        'de_line_loads':  pd.DataFrame(de_line_loads,  index=idx),
        'bnl_line_loads': pd.DataFrame(bnl_line_loads, index=idx),
        'inter_log':      pd.DataFrame(inter_transfers_log, index=idx),
        'de_meta':        de_meta,
        'bnl_meta':       bnl_meta,
        'super_meta':     super_meta,
        'idx':            idx,
    }


# ── Metriken ──────────────────────────────────────────────────────────────────

def compute_metrics(sim: dict, stress_mask: pd.Series, label: str) -> dict:
    nodes  = sim['nodes']
    inter  = sim['inter_log']
    m      = {}

    for cluster, cluster_nodes in [('DE', DE_NODES), ('BNL', BNL_NODES),
                                    ('ALL', ALL_NODES)]:
        elec_dem = sum(nodes[n]['elec_demand'].sum()  for n in cluster_nodes)
        elec_def = sum(nodes[n]['elec_deficit'].sum() for n in cluster_nodes)
        heat_dem = sum(nodes[n]['heat_demand'].sum()  for n in cluster_nodes)
        heat_def = sum(nodes[n]['heat_deficit'].sum() for n in cluster_nodes)
        m[f'{label}_{cluster}_elec_sr']      = (1 - elec_def / max(elec_dem, 1)) * 100
        m[f'{label}_{cluster}_heat_sr']      = (1 - heat_def / max(heat_dem, 1)) * 100
        m[f'{label}_{cluster}_total_sr']     = (m[f'{label}_{cluster}_elec_sr'] * 0.6 +
                                                 m[f'{label}_{cluster}_heat_sr'] * 0.4)
        m[f'{label}_{cluster}_elec_def_gwh'] = elec_def

        if stress_mask.any():
            s_ed = sum(nodes[n]['elec_deficit'][stress_mask].sum() for n in cluster_nodes)
            s_em = sum(nodes[n]['elec_demand'][stress_mask].sum()  for n in cluster_nodes)
            m[f'{label}_{cluster}_stress_elec_sr'] = (1 - s_ed / max(s_em, 1)) * 100

    # Inter-Cluster-Transfers
    m[f'{label}_inter_de_export_gwh']  = inter['de_export'].sum()
    m[f'{label}_inter_bnl_export_gwh'] = inter['bnl_export'].sum()
    m[f'{label}_super_solidarity_idx'] = sim['super_meta'].solidarity_index

    # Cluster-Solidaritätsindizes
    if hasattr(sim['de_meta'], 'solidarity_index'):
        m[f'{label}_de_solidarity_idx']  = sim['de_meta'].solidarity_index
    if hasattr(sim['bnl_meta'], 'solidarity_index'):
        m[f'{label}_bnl_solidarity_idx'] = sim['bnl_meta'].solidarity_index

    return m


# ── Hauptprogramm ─────────────────────────────────────────────────────────────

if __name__ == '__main__':
    print('=' * 72)
    print('  Cybersyn 2.0 – Stufe 5: Benelux + Norddeutschland')
    print('  6-Knoten fraktales Viable System Model (Beer, 1972)')
    print('=' * 72)

    print('\n[1] Norddeutschland-Daten laden (SMARD 2022–2023)...')
    de_base = load_de_data()
    idx = de_base['HH'].index
    n   = len(idx)
    print(f'    {n} Stunden | {idx[0].date()} – {idx[-1].date()}')
    for node in DE_NODES:
        df = de_base[node]
        sr = df['erzeugung_gesamt'].mean() / df['last'].mean() * 100
        print(f'    {node}: Ø Last {df["last"].mean():.3f} GWh/h | '
              f'Ø Erzg {df["erzeugung_gesamt"].mean():.3f} GWh/h | '
              f'Selbstvers. {sr:.0f}%')

    print('\n[2] Benelux-Daten laden (ENTSO-E / synthetisch)...')
    bnl_base = load_benelux_data(
        start=str(idx[0].date()), end=str(idx[-1].date())
    )
    # Index angleichen
    for node in BNL_NODES:
        bnl_base[node] = bnl_base[node].reindex(idx).interpolate()
    for node in BNL_NODES:
        df = bnl_base[node]
        sr = df['erzeugung_gesamt'].mean() / df['last'].mean() * 100
        print(f'    {node}: Ø Last {df["last"].mean():.3f} GWh/h | '
              f'Ø Erzg {df["erzeugung_gesamt"].mean():.3f} GWh/h | '
              f'Selbstvers. {sr:.0f}%')

    # ── Stresstest A: Belgischer Atomausfall ──────────────────────────────
    print('\n[3] Stresstest A: Belgischer Atomausfall (1–21 Mär 2023, alle AKW)')
    bnl_A = apply_nuclear_phase_out(bnl_base, node='BE')
    mask_A = pd.Series(
        (idx >= pd.Timestamp('2023-03-01', tz='UTC')) &
        (idx <  pd.Timestamp('2023-03-22', tz='UTC')), index=idx
    )
    print('    Cybersyn...'); cs_A = run_simulation(de_base, bnl_A, mode='cybersyn', label='cs_A')
    print('    Markt...');    mk_A = run_simulation(de_base, bnl_A, mode='market',   label='mk_A')
    m_cs_A = compute_metrics(cs_A, mask_A, 'cs_A')
    m_mk_A = compute_metrics(mk_A, mask_A, 'mk_A')
    print(f'    CS BE-Strom-SR (Krise): {m_cs_A.get("cs_A_BNL_stress_elec_sr", 0):.2f}% | '
          f'Markt: {m_mk_A.get("mk_A_BNL_stress_elec_sr", 0):.2f}%')
    print(f'    Inter-Cluster-Transfers DE→BNL: '
          f'CS {m_cs_A["cs_A_inter_de_export_gwh"]:.1f} GWh | '
          f'Markt {m_mk_A["mk_A_inter_de_export_gwh"]:.1f} GWh')

    # ── Stresstest B: Niederländische Gasdisruption ───────────────────────
    print('\n[4] Stresstest B: NL Gasnetz-Disruption (15–20 Jan 2023, -90% Gas)')
    bnl_B = apply_gas_disruption(bnl_base, node='NL')
    mask_B = pd.Series(
        (idx >= pd.Timestamp('2023-01-15', tz='UTC')) &
        (idx <  pd.Timestamp('2023-01-20', tz='UTC')), index=idx
    )
    print('    Cybersyn...'); cs_B = run_simulation(de_base, bnl_B, mode='cybersyn', label='cs_B')
    print('    Markt...');    mk_B = run_simulation(de_base, bnl_B, mode='market',   label='mk_B')
    m_cs_B = compute_metrics(cs_B, mask_B, 'cs_B')
    m_mk_B = compute_metrics(mk_B, mask_B, 'mk_B')
    print(f'    CS NL-Strom-SR (Krise): {m_cs_B.get("cs_B_BNL_stress_elec_sr", 0):.2f}% | '
          f'Markt: {m_mk_B.get("mk_B_BNL_stress_elec_sr", 0):.2f}%')

    # ── Stresstest C: Nordsee-Sturm ───────────────────────────────────────
    print('\n[5] Stresstest C: Nordsee-Sturm (10–13 Feb 2023, Offshore-Wind 350%)')
    bnl_C = apply_nordsee_sturm(bnl_base)
    # SH (DE) ebenfalls betroffen: Sturm-Bonus auf Wind, Last leicht erhöht
    de_C = {k: df.copy() for k, df in de_base.items()}
    mask_sturm = (
        (de_C['SH'].index >= pd.Timestamp('2023-02-10', tz='UTC')) &
        (de_C['SH'].index <  pd.Timestamp('2023-02-13', tz='UTC'))
    )
    de_C['SH'].loc[mask_sturm, 'erzeugung_gesamt'] *= 2.5
    de_C['SH'].loc[mask_sturm, 'last']             *= 1.10
    mask_C = pd.Series(
        (idx >= pd.Timestamp('2023-02-10', tz='UTC')) &
        (idx <  pd.Timestamp('2023-02-13', tz='UTC')), index=idx
    )
    print('    Cybersyn...'); cs_C = run_simulation(de_C, bnl_C, mode='cybersyn', label='cs_C')
    print('    Markt...');    mk_C = run_simulation(de_C, bnl_C, mode='market',   label='mk_C')
    m_cs_C = compute_metrics(cs_C, mask_C, 'cs_C')
    m_mk_C = compute_metrics(mk_C, mask_C, 'mk_C')
    print(f'    CS Curtailment-Vermeidung durch Transfers: '
          f'{m_cs_C["cs_C_inter_bnl_export_gwh"] + m_cs_C["cs_C_inter_de_export_gwh"]:.1f} GWh')

    # ── Stresstest D: Worst-Case Kombination ──────────────────────────────
    print('\n[6] Stresstest D: Worst-Case (Dunkelflaute + Atomausfall gleichzeitig)')
    from fetch_smard_regional import apply_dunkelflaute
    de_D  = apply_dunkelflaute(de_base)
    bnl_D = apply_nuclear_phase_out(bnl_base, node='BE')
    ts_D_start = pd.Timestamp('2022-11-14', tz='UTC')
    ts_D_end   = pd.Timestamp('2022-11-28', tz='UTC')
    mask_D = pd.Series((idx >= ts_D_start) & (idx < ts_D_end), index=idx)
    print('    Cybersyn...'); cs_D = run_simulation(de_D, bnl_D, mode='cybersyn', label='cs_D')
    print('    Markt...');    mk_D = run_simulation(de_D, bnl_D, mode='market',   label='mk_D')
    m_cs_D = compute_metrics(cs_D, mask_D, 'cs_D')
    m_mk_D = compute_metrics(mk_D, mask_D, 'mk_D')

    # ── Zusammenfassung ───────────────────────────────────────────────────
    print('\n' + '=' * 72)
    print('  ERGEBNISSE STUFE 5 – 6-KNOTEN BENELUX + NORDDEUTSCHLAND')
    print('=' * 72)

    def row(lbl, cv, mv, fmt='.2f'):
        d = cv - mv
        print(f'  {lbl:<48} {cv:>8{fmt}} {mv:>8{fmt}}  ({d:+{fmt}})')

    print(f'  {"":48} {"Cybersyn":>8} {"Markt":>8}')
    print('  ' + '-' * 70)
    print('  STRESSTEST A: Atomausfall Belgien')
    row('  Gesamt-SR (%)',             m_cs_A['cs_A_ALL_total_sr'],  m_mk_A['mk_A_ALL_total_sr'])
    row('  BNL Strom-SR Krise (%)',   m_cs_A.get('cs_A_BNL_stress_elec_sr', 0),
                                      m_mk_A.get('mk_A_BNL_stress_elec_sr', 0))
    row('  Inter-DE→BNL (GWh)',       m_cs_A['cs_A_inter_de_export_gwh'],
                                      m_mk_A['mk_A_inter_de_export_gwh'], '.1f')
    print(f'  {"  Super-Solidaritätsindex":<48} '
          f'{m_cs_A["cs_A_super_solidarity_idx"]:>8.3f}')

    print('\n  STRESSTEST B: NL Gasdisruption')
    row('  BNL Strom-SR Krise (%)',   m_cs_B.get('cs_B_BNL_stress_elec_sr', 0),
                                      m_mk_B.get('mk_B_BNL_stress_elec_sr', 0))

    print('\n  STRESSTEST C: Nordsee-Sturm')
    cs_C_inter = m_cs_C['cs_C_inter_bnl_export_gwh'] + m_cs_C['cs_C_inter_de_export_gwh']
    mk_C_inter = m_mk_C['mk_C_inter_bnl_export_gwh'] + m_mk_C['mk_C_inter_de_export_gwh']
    row('  Inter-Cluster Transfers (GWh)', cs_C_inter, mk_C_inter, '.1f')

    print('\n  STRESSTEST D: Worst-Case (Dunkelflaute + Atomausfall)')
    row('  Gesamt-SR (%)',             m_cs_D['cs_D_ALL_total_sr'],  m_mk_D['mk_D_ALL_total_sr'])
    row('  ALL Strom-SR Krise (%)',   m_cs_D.get('cs_D_ALL_stress_elec_sr', 0),
                                      m_mk_D.get('mk_D_ALL_stress_elec_sr', 0))
    row('  Strom-Defizit (GWh)',      m_cs_D['cs_D_ALL_elec_def_gwh'],
                                      m_mk_D['mk_D_ALL_elec_def_gwh'], '.1f')

    print('\n  SKALIERUNGSPFAD STUFE 1 → 5')
    scaling = [
        ('1', 'Jahreswerte, Eurostat (HH)',        '99.4', '98.6', '-60%'),
        ('2', 'Stundenwerte, SMARD (HH)',           '95.5', '93.8', '-88%'),
        ('3', 'Sektorkopplung + MPC (HH)',          '97.6', '93.4', '-84%'),
        ('4', '3 Knoten, Norddeutschland',          '100',  '100',  '-100%'),
        ('5', '6 Knoten, Benelux + Norddeutschland',
         f"{m_cs_D['cs_D_ALL_total_sr']:.1f}",
         f"{m_mk_D['mk_D_ALL_total_sr']:.1f}", 'siehe Stresstests'),
    ]
    print(f'  {"St":<3} {"Beschreibung":<44} {"CS-SR":>6} {"Mk-SR":>6} {"Defizit":>12}')
    print('  ' + '-' * 75)
    for s in scaling:
        print(f'  {s[0]:<3} {s[1]:<44} {s[2]:>6} {s[3]:>6} {s[4]:>12}')

    # ── Speichern ─────────────────────────────────────────────────────────
    all_metrics = {
        'stresstest_A_atomausfall': {**m_cs_A, **m_mk_A},
        'stresstest_B_gas':         {**m_cs_B, **m_mk_B},
        'stresstest_C_sturm':       {**m_cs_C, **m_mk_C},
        'stresstest_D_worstcase':   {**m_cs_D, **m_mk_D},
    }
    with open('metrics_s5.json', 'w') as f:
        json.dump(all_metrics, f, indent=2, default=str)

    print(f'\n  Fertig. metrics_s5.json gespeichert.')
