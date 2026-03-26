"""
visualize_stufe4.py – Visualisierungen für Cybersyn 2.0 Stufe 4
================================================================
Erzeugt PNG-Plots und interaktives HTML-Dashboard.
"""

import pandas as pd
import numpy as np
import json
import warnings
warnings.filterwarnings('ignore')

try:
    import plotly.graph_objects as go
    import plotly.subplots as sp
    HAS_PLOTLY = True
except ImportError:
    HAS_PLOTLY = False
    import matplotlib.pyplot as plt
    import matplotlib.gridspec as gridspec

NODES       = ['HH', 'SH', 'NDS']
NODE_NAMES  = {'HH': 'Hamburg', 'SH': 'Schleswig-Holstein', 'NDS': 'Niedersachsen'}
NODE_COLORS = {'HH': '#e63946', 'SH': '#457b9d', 'NDS': '#2a9d8f'}
CS_COLOR    = '#2a9d8f'
MK_COLOR    = '#e63946'


def load_results():
    try:
        with open('metrics_s4.json') as f:
            metrics = json.load(f)
        return metrics
    except FileNotFoundError:
        return {}


def make_matplotlib_dashboard(scenario='dunkelflaute'):
    """Fallback: matplotlib wenn plotly nicht installiert."""
    try:
        df = pd.read_csv(f'results_s4_{scenario}.csv', index_col=0, parse_dates=True)
    except FileNotFoundError:
        print(f"  Keine Ergebnisdatei für {scenario} gefunden.")
        return

    metrics = load_results()
    fig = plt.figure(figsize=(18, 12))
    fig.suptitle(f'Cybersyn 2.0 – Stufe 4: Regionale Vernetzung ({scenario.title()})',
                 fontsize=14, fontweight='bold')
    gs  = gridspec.GridSpec(3, 3, figure=fig, hspace=0.45, wspace=0.35)

    # Netzweite SR
    ax1 = fig.add_subplot(gs[0, :])
    for node in NODES:
        node_df = df[df['node'] == node] if 'node' in df.columns else df
        if f'cs_elec_supply' in node_df.columns and f'cs_elec_demand' in node_df.columns:
            sr = (node_df['cs_elec_supply'] /
                  node_df['cs_elec_demand'].replace(0, np.nan)).fillna(1.0).clip(0, 1) * 100
            ax1.plot(sr.index, sr.rolling(24).mean(),
                     label=f'CS {NODE_NAMES[node]}', color=NODE_COLORS[node])
    ax1.set_ylabel('Versorgungsrate (%)')
    ax1.set_title('Stündliche Versorgungsrate (24h gleitend)')
    ax1.legend(fontsize=8)
    ax1.set_ylim(50, 105)
    ax1.axhline(100, color='gray', linestyle='--', alpha=0.5)

    # Metriken-Vergleich
    ax2 = fig.add_subplot(gs[1, 0])
    m   = metrics.get(scenario, {})
    prefix = 'cs_' + scenario[:2]  # vereinfacht
    cats = ['Gesamt-SR', 'Strom-SR', 'Wärme-SR', 'Stress-SR']
    try:
        cs_vals = [m.get(f'cs_{scenario}_total_sr', 0),
                   m.get(f'cs_{scenario}_net_elec_sr', 0),
                   m.get(f'cs_{scenario}_net_heat_sr', 0),
                   m.get(f'cs_{scenario}_stress_elec_sr', 0)]
        mk_vals = [m.get(f'mk_{scenario}_total_sr', 0),
                   m.get(f'mk_{scenario}_net_elec_sr', 0),
                   m.get(f'mk_{scenario}_net_heat_sr', 0),
                   m.get(f'mk_{scenario}_stress_elec_sr', 0)]
        x = np.arange(len(cats))
        ax2.bar(x - 0.2, cs_vals, 0.35, label='Cybersyn', color=CS_COLOR, alpha=0.8)
        ax2.bar(x + 0.2, mk_vals, 0.35, label='Markt',    color=MK_COLOR, alpha=0.8)
        ax2.set_xticks(x); ax2.set_xticklabels(cats, fontsize=7, rotation=20)
        ax2.set_ylabel('%'); ax2.set_title('Versorgungsraten')
        ax2.legend(fontsize=8)
    except Exception:
        pass

    plt.savefig(f'cybersyn_stufe4_{scenario}.png', dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  Plot gespeichert: cybersyn_stufe4_{scenario}.png")


def make_plotly_dashboard():
    """Interaktives HTML-Dashboard mit Plotly."""
    metrics = load_results()

    fig = sp.make_subplots(
        rows=4, cols=3,
        subplot_titles=[
            'Dunkelflaute: Gesamt-SR', 'Knotenausfall SH: SR', 'Sturmproduktion: Curtailment',
            'Cybersyn Strom-SR (HH)', 'Cybersyn Strom-SR (SH)', 'Cybersyn Strom-SR (NDS)',
            'Markt Strom-SR (HH)', 'Markt Strom-SR (SH)', 'Markt Strom-SR (NDS)',
            'Solidaritätsindex', 'Skalierungspfad Stufe 1→4', 'Netzauslastung',
        ],
        vertical_spacing=0.10,
        horizontal_spacing=0.08,
    )

    # ── Reihe 1: Stresstest-Vergleiche ───────────────────────────────────────
    # Dunkelflaute
    m_dk = metrics.get('dunkelflaute', {})
    cats = ['Cybersyn', 'Markt']
    for i, (label, key_prefix) in enumerate([('Cybersyn', 'cs_dk'), ('Markt', 'mk_dk')]):
        vals = [
            m_dk.get(f'{key_prefix}_total_sr', 0),
            m_dk.get(f'{key_prefix}_stress_elec_sr', 0),
        ]
        fig.add_trace(go.Bar(name=label, x=['Gesamt', 'Dunkelflaute'],
                             y=vals,
                             marker_color=CS_COLOR if i == 0 else MK_COLOR,
                             showlegend=(i == 0)),
                      row=1, col=1)

    # Knotenausfall
    m_ko = metrics.get('knotenausfall', {})
    for i, (label, kp) in enumerate([('Cybersyn', 'cs_ko'), ('Markt', 'mk_ko')]):
        vals = [m_ko.get(f'{kp}_total_sr', 0), m_ko.get(f'{kp}_stress_elec_sr', 0)]
        fig.add_trace(go.Bar(name=label, x=['Gesamt', 'SH Ausfall'],
                             y=vals,
                             marker_color=CS_COLOR if i == 0 else MK_COLOR,
                             showlegend=False),
                      row=1, col=2)

    # Sturmproduktion
    m_st = metrics.get('sturmproduktion', {})
    fig.add_trace(go.Bar(name='Cybersyn',
                          x=['CS Transfers', 'Mk Transfers'],
                          y=[m_st.get('cs_st_transfers_gwh', 0),
                             m_st.get('mk_st_transfers_gwh', 0)],
                          marker_color=[CS_COLOR, MK_COLOR],
                          showlegend=False),
                  row=1, col=3)

    # ── Reihe 2+3: Zeitreihen aus CSV ────────────────────────────────────────
    for node_i, node in enumerate(NODES):
        try:
            df = pd.read_csv('results_s4_dunkelflaute.csv',
                              index_col=0, parse_dates=True)
            node_df = df[df['node'] == node].copy() if 'node' in df.columns else df

            if 'cs_elec_supply' in node_df.columns:
                sr_cs = (node_df['cs_elec_supply'] /
                          node_df['cs_elec_demand'].replace(0, np.nan)).fillna(1.0).clip(0, 1) * 100
                sr_mk = (node_df['mk_elec_supply'] /
                          node_df['mk_elec_demand'].replace(0, np.nan)).fillna(1.0).clip(0, 1) * 100
                sr_cs_r = sr_cs.rolling(24).mean()
                sr_mk_r = sr_mk.rolling(24).mean()

                fig.add_trace(go.Scatter(x=sr_cs_r.index, y=sr_cs_r.values,
                                          name=f'CS {node}', line=dict(color=CS_COLOR),
                                          showlegend=False),
                               row=2, col=node_i + 1)
                fig.add_trace(go.Scatter(x=sr_mk_r.index, y=sr_mk_r.values,
                                          name=f'Mk {node}', line=dict(color=MK_COLOR),
                                          showlegend=False),
                               row=3, col=node_i + 1)
        except Exception:
            pass

    # ── Reihe 4: Solidaritätsindex + Skalierung + Netzauslastung ─────────────
    # Solidaritätsindex
    si = m_dk.get('cs_dk_solidarity_index', 0)
    fig.add_trace(go.Indicator(
        mode='gauge+number',
        value=si * 100,
        title={'text': 'Solidaritätsindex (%)'},
        gauge={'axis': {'range': [0, 100]},
               'bar': {'color': CS_COLOR}},
    ), row=4, col=1)

    # Skalierungspfad
    skal = metrics.get('skalierung', [])
    if skal:
        stufen = [str(s.get('Stufe', '')) for s in skal]
        cs_srs = [s.get('Cybersyn SR (%)', 0) for s in skal]
        mk_srs = [s.get('Markt SR (%)', 0)    for s in skal]
        fig.add_trace(go.Bar(name='Cybersyn', x=stufen, y=cs_srs,
                              marker_color=CS_COLOR, showlegend=False),
                      row=4, col=2)
        fig.add_trace(go.Bar(name='Markt', x=stufen, y=mk_srs,
                              marker_color=MK_COLOR, showlegend=False),
                      row=4, col=2)

    # Netzauslastung
    line_util = m_dk.get('cs_dk_line_utilization', {})
    if line_util:
        keys = [str(k) for k in line_util]
        vals = list(line_util.values())
        fig.add_trace(go.Bar(x=keys, y=vals,
                              marker_color=CS_COLOR, showlegend=False,
                              name='Auslastung %'),
                      row=4, col=3)

    fig.update_layout(
        title_text='Cybersyn 2.0 – Stufe 4: Regionale Vernetzung Norddeutschland',
        title_x=0.5,
        height=1200,
        template='plotly_dark',
        showlegend=True,
    )

    fig.write_html('cybersyn_stufe4_dashboard.html')
    print("  Dashboard gespeichert: cybersyn_stufe4_dashboard.html")


if __name__ == '__main__':
    print("Erzeuge Visualisierungen für Stufe 4...")

    if HAS_PLOTLY:
        make_plotly_dashboard()
    else:
        for scenario in ['dunkelflaute', 'knotenausfall', 'sturmproduktion']:
            make_matplotlib_dashboard(scenario)

    print("Fertig.")
