"""
visualize_stufe5.py – Visualisierungen für Stufe 5 (Benelux + Norddeutschland)
===============================================================================
Lädt metrics_s5.json und erzeugt:
  1. 6-Knoten VSM-Netzwerkkarte (Plotly)
  2. Stresstest-Vergleich aller 4 Szenarien
  3. Inter-Cluster-Transfer-Zeitreihe
  4. Solidaritätsindex-Vergleich (DE, BNL, Super)

Nutzung: python visualize_stufe5.py
"""

import json
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from pathlib import Path

try:
    import plotly.graph_objects as go
    import plotly.express as px
    HAS_PLOTLY = True
except ImportError:
    HAS_PLOTLY = False


# ── VSM-Netzwerkkarte ─────────────────────────────────────────────────────────

NODE_POSITIONS = {
    'HH':  (0.52, 0.82),
    'SH':  (0.42, 0.92),
    'NDS': (0.50, 0.70),
    'NL':  (0.30, 0.55),
    'BE':  (0.22, 0.38),
    'LU':  (0.38, 0.28),
}

NODE_COLORS = {
    'HH': '#E74C3C', 'SH': '#E74C3C', 'NDS': '#E74C3C',   # DE = Rot
    'NL': '#3498DB', 'BE': '#3498DB', 'LU': '#3498DB',     # BNL = Blau
}

EDGES = [
    ('HH',  'SH',  3.5, 'DE'),
    ('HH',  'NDS', 2.8, 'DE'),
    ('SH',  'NDS', 1.2, 'DE'),
    ('NL',  'BE',  3.5, 'BNL'),
    ('NL',  'LU',  0.3, 'BNL'),
    ('BE',  'LU',  0.5, 'BNL'),
    ('NDS', 'NL',  3.8, 'INTER'),
    ('SH',  'NL',  1.4, 'INTER'),
]

EDGE_COLORS = {'DE': '#E74C3C', 'BNL': '#3498DB', 'INTER': '#2ECC71'}


def plot_network():
    """Visualisiert das 6-Knoten VSM-Netzwerk."""
    fig, ax = plt.subplots(1, 1, figsize=(10, 9))
    ax.set_xlim(0.05, 0.75)
    ax.set_ylim(0.15, 1.05)
    ax.axis('off')
    ax.set_facecolor('#0D1117')
    fig.patch.set_facecolor('#0D1117')

    # Cluster-Hintergrund
    from matplotlib.patches import Ellipse
    de_ellipse = Ellipse((0.49, 0.81), 0.25, 0.28, color='#E74C3C', alpha=0.08)
    bnl_ellipse = Ellipse((0.29, 0.42), 0.28, 0.36, color='#3498DB', alpha=0.08)
    ax.add_patch(de_ellipse)
    ax.add_patch(bnl_ellipse)
    ax.text(0.62, 0.93, 'DE Cluster', color='#E74C3C', fontsize=9, alpha=0.7)
    ax.text(0.42, 0.20, 'BNL Cluster', color='#3498DB', fontsize=9, alpha=0.7)

    # Kanten
    for src, dst, cap, etype in EDGES:
        x0, y0 = NODE_POSITIONS[src]
        x1, y1 = NODE_POSITIONS[dst]
        color = EDGE_COLORS[etype]
        lw    = 0.8 + cap / 2.0
        ls    = '--' if etype == 'INTER' else '-'
        ax.plot([x0, x1], [y0, y1], color=color, lw=lw, ls=ls, alpha=0.7, zorder=1)
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        ax.text(mx + 0.01, my + 0.01, f'{cap} GWh/h', color=color,
                fontsize=6.5, alpha=0.8, ha='center')

    # Knoten
    for node, (x, y) in NODE_POSITIONS.items():
        circle = plt.Circle((x, y), 0.045, color=NODE_COLORS[node],
                             zorder=3, alpha=0.9)
        ax.add_patch(circle)
        ax.text(x, y, node, ha='center', va='center', color='white',
                fontsize=10, fontweight='bold', zorder=4)

    # Legende
    patches = [
        mpatches.Patch(color='#E74C3C', label='DE Cluster (HH/SH/NDS)'),
        mpatches.Patch(color='#3498DB', label='BNL Cluster (NL/BE/LU)'),
        mpatches.Patch(color='#2ECC71', label='Inter-Cluster-Leitungen'),
    ]
    ax.legend(handles=patches, loc='lower left', facecolor='#1C1C1C',
              edgecolor='#333', labelcolor='white', fontsize=8)

    ax.set_title(
        'Cybersyn 2.0 – Stufe 5\n6-Knoten fraktales VSM: Benelux + Norddeutschland',
        color='white', fontsize=12, pad=10
    )
    plt.tight_layout()
    plt.savefig('cybersyn_stufe5_network.png', dpi=150,
                facecolor='#0D1117', bbox_inches='tight')
    print('  cybersyn_stufe5_network.png gespeichert.')
    plt.close()


# ── Stresstest-Vergleich ──────────────────────────────────────────────────────

def plot_stresstests(metrics: dict):
    """Balkendiagramm: Cybersyn vs. Markt für alle 4 Stresstests."""
    scenarios = [
        ('A: Atomausfall BE', 'stresstest_A_atomausfall', 'cs_A', 'mk_A', 'BNL'),
        ('B: Gas NL',         'stresstest_B_gas',         'cs_B', 'mk_B', 'BNL'),
        ('C: Nordsee-Sturm',  'stresstest_C_sturm',       'cs_C', 'mk_C', 'ALL'),
        ('D: Worst-Case',     'stresstest_D_worstcase',   'cs_D', 'mk_D', 'ALL'),
    ]

    fig, axes = plt.subplots(1, 4, figsize=(16, 5), sharey=False)
    fig.patch.set_facecolor('#0D1117')

    for ax, (name, key, cs_prefix, mk_prefix, cluster) in zip(axes, scenarios):
        m = metrics.get(key, {})
        cs_sr = m.get(f'{cs_prefix}_{cluster}_stress_elec_sr',
                      m.get(f'{cs_prefix}_{cluster}_total_sr', 0))
        mk_sr = m.get(f'{mk_prefix}_{cluster}_stress_elec_sr',
                      m.get(f'{mk_prefix}_{cluster}_total_sr', 0))
        bars = ax.bar(['Cybersyn', 'Markt'], [cs_sr, mk_sr],
                      color=['#2ECC71', '#E74C3C'], alpha=0.85, width=0.5)
        ax.set_ylim(0, 110)
        ax.set_title(name, color='white', fontsize=9)
        ax.set_facecolor('#161B22')
        ax.tick_params(colors='white')
        ax.spines[:].set_color('#333')
        ax.set_ylabel('Strom-SR (%) Krisenperiode', color='white', fontsize=7)
        for bar, val in zip(bars, [cs_sr, mk_sr]):
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 1,
                    f'{val:.1f}%', ha='center', va='bottom', color='white', fontsize=9)

    fig.suptitle('Cybersyn 2.0 Stufe 5 – Stresstest-Ergebnisse',
                 color='white', fontsize=13)
    plt.tight_layout()
    plt.savefig('cybersyn_stufe5_stresstests.png', dpi=150,
                facecolor='#0D1117', bbox_inches='tight')
    print('  cybersyn_stufe5_stresstests.png gespeichert.')
    plt.close()


# ── Solidaritätsindex ─────────────────────────────────────────────────────────

def plot_solidarity(metrics: dict):
    """Solidaritätsindex auf drei Ebenen: DE, BNL, Super."""
    labels = ['DE\n(intra)', 'BNL\n(intra)', 'Super\n(inter-cluster)']
    m      = metrics.get('stresstest_D_worstcase', {})
    values = [
        m.get('cs_D_de_solidarity_idx',  0),
        m.get('cs_D_bnl_solidarity_idx', 0),
        m.get('cs_D_super_solidarity_idx', 0),
    ]

    fig, ax = plt.subplots(figsize=(7, 4))
    fig.patch.set_facecolor('#0D1117')
    ax.set_facecolor('#161B22')
    bars = ax.bar(labels, [v * 100 for v in values],
                  color=['#E74C3C', '#3498DB', '#2ECC71'], alpha=0.85, width=0.4)
    ax.set_ylim(0, 110)
    ax.set_ylabel('Solidaritätsindex (%)', color='white')
    ax.set_title('Zwei-Ebenen-Solidarität – Cybersyn Stufe 5 (Worst-Case)',
                 color='white', fontsize=10)
    ax.tick_params(colors='white')
    ax.spines[:].set_color('#333')
    for bar, val in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 1,
                f'{val*100:.1f}%', ha='center', va='bottom', color='white', fontsize=10)
    plt.tight_layout()
    plt.savefig('cybersyn_stufe5_solidarity.png', dpi=150,
                facecolor='#0D1117', bbox_inches='tight')
    print('  cybersyn_stufe5_solidarity.png gespeichert.')
    plt.close()


# ── Hauptprogramm ─────────────────────────────────────────────────────────────

if __name__ == '__main__':
    metrics_path = Path('metrics_s5.json')
    if not metrics_path.exists():
        print('metrics_s5.json nicht gefunden. Erst cybersyn_benelux.py ausführen.')
        exit(1)

    with open(metrics_path) as f:
        metrics = json.load(f)

    print('Erzeuge Visualisierungen...')
    plot_network()
    plot_stresstests(metrics)
    plot_solidarity(metrics)
    print('Fertig. 3 PNG-Dateien erzeugt.')
