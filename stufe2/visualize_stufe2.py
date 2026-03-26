"""
Cybersyn 2.0 – Stufe 2: Visualisierungen
"""
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.patches as mpatches
from matplotlib.gridspec import GridSpec
import json, warnings
warnings.filterwarnings('ignore')

plt.rcParams.update({
    'font.family':     'DejaVu Sans',
    'axes.unicode_minus': False,
    'figure.facecolor': '#0d1117',
    'axes.facecolor':   '#161b22',
    'axes.edgecolor':   '#30363d',
    'axes.labelcolor':  '#e6edf3',
    'xtick.color':      '#8b949e',
    'ytick.color':      '#8b949e',
    'text.color':       '#e6edf3',
    'grid.color':       '#21262d',
    'grid.linewidth':   0.5,
    'legend.facecolor': '#161b22',
    'legend.edgecolor': '#30363d',
})

CYAN   = '#58a6ff'
ORANGE = '#f78166'
GREEN  = '#3fb950'
YELLOW = '#d29922'
PURPLE = '#bc8cff'
RED    = '#ff7b72'

# ─── Daten laden ──────────────────────────────────────────────────────────────
df = pd.read_csv('simulation_results.csv')
df['datetime'] = pd.to_datetime(df['datetime'], utc=True)
df = df.set_index('datetime')

with open('metrics.json') as f:
    m = json.load(f)

cs_m = m['cybersyn']
mk_m = m['markt']
mask_crisis = df['is_crisis'].astype(bool)

# Wöchentliche Aggregation für Übersichtsplots
df_weekly = df.resample('W').mean()


# ══════════════════════════════════════════════════════════════════════════════
# PLOT 1: Hauptübersicht (4 Panels)
# ══════════════════════════════════════════════════════════════════════════════

fig = plt.figure(figsize=(20, 16))
fig.suptitle('Cybersyn 2.0 – Stufe 2: Hamburg Stromversorgung 2022–2023\n'
             'Stündliche Regelschleife | SMARD-Daten | PI-Regler + Algedonic Channel',
             fontsize=16, fontweight='bold', color='#e6edf3', y=0.98)

gs = GridSpec(4, 2, figure=fig, hspace=0.45, wspace=0.3,
              left=0.07, right=0.97, top=0.93, bottom=0.06)

# ── Panel 1: Versorgungsrate (wöchentlich) ────────────────────────────────────
ax1 = fig.add_subplot(gs[0, :])
ax1.plot(df_weekly.index, df_weekly['cs_supply_rate'] * 100,
         color=CYAN, lw=1.5, label='Cybersyn', alpha=0.9)
ax1.plot(df_weekly.index, df_weekly['mk_supply_rate'] * 100,
         color=ORANGE, lw=1.5, label='Markt', alpha=0.9, linestyle='--')
# Krisenzonen markieren
crisis_start = None
for i, (t, c) in enumerate(zip(df.index, df['is_crisis'])):
    if c and crisis_start is None:
        crisis_start = t
    elif not c and crisis_start is not None:
        ax1.axvspan(crisis_start, t, alpha=0.15, color=RED, zorder=0)
        crisis_start = None
if crisis_start is not None:
    ax1.axvspan(crisis_start, df.index[-1], alpha=0.15, color=RED, zorder=0)
ax1.axhline(100, color='#30363d', lw=0.8, linestyle=':')
ax1.set_ylabel('Versorgungsrate (%)', fontsize=10)
ax1.set_title('Wöchentliche Versorgungsrate (rot = Krisenmonate Nov–Feb)',
              fontsize=10, pad=6)
ax1.legend(loc='lower left', fontsize=9)
ax1.set_ylim(50, 105)
ax1.xaxis.set_major_formatter(mdates.DateFormatter('%b %Y'))
ax1.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
ax1.grid(True, alpha=0.4)

# ── Panel 2: Speicherfüllstand ────────────────────────────────────────────────
ax2 = fig.add_subplot(gs[1, 0])
ax2.fill_between(df_weekly.index, df_weekly['cs_storage'],
                 alpha=0.4, color=CYAN, label='Cybersyn')
ax2.fill_between(df_weekly.index, df_weekly['mk_storage'],
                 alpha=0.4, color=ORANGE, label='Markt')
ax2.plot(df_weekly.index, df_weekly['cs_storage'], color=CYAN, lw=1.2)
ax2.plot(df_weekly.index, df_weekly['mk_storage'], color=ORANGE, lw=1.2, linestyle='--')
ax2.axhline(965, color='#30363d', lw=0.8, linestyle=':', label='Kapazität (965 GWh)')
ax2.set_ylabel('Speicherfüllstand (GWh)', fontsize=10)
ax2.set_title('Speicherdynamik', fontsize=10, pad=6)
ax2.legend(fontsize=8)
ax2.xaxis.set_major_formatter(mdates.DateFormatter('%b %Y'))
ax2.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
ax2.grid(True, alpha=0.4)

# ── Panel 3: Kumulatives Defizit ──────────────────────────────────────────────
ax3 = fig.add_subplot(gs[1, 1])
cs_cum = np.cumsum(df['cs_deficit'].values)
mk_cum = np.cumsum(df['mk_deficit'].values)
ax3.fill_between(df.index, mk_cum, alpha=0.3, color=ORANGE)
ax3.fill_between(df.index, cs_cum, alpha=0.3, color=CYAN)
ax3.plot(df.index, mk_cum, color=ORANGE, lw=1.5, label=f'Markt ({mk_m["gesamtdefizit"]:.0f} GWh)')
ax3.plot(df.index, cs_cum, color=CYAN,   lw=1.5, label=f'Cybersyn ({cs_m["gesamtdefizit"]:.0f} GWh)')
ax3.set_ylabel('Kumulatives Defizit (GWh)', fontsize=10)
ax3.set_title('Kumulatives Versorgungsdefizit', fontsize=10, pad=6)
ax3.legend(fontsize=9)
ax3.xaxis.set_major_formatter(mdates.DateFormatter('%b %Y'))
ax3.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
ax3.grid(True, alpha=0.4)

# ── Panel 4: Algedonic-Ereignisse ─────────────────────────────────────────────
ax4 = fig.add_subplot(gs[2, 0])
alged_events = m.get('algedonic_event_list', [])
if alged_events:
    event_times = pd.to_datetime([e['time'] for e in alged_events], utc=True)
    event_deficits = [e['deficit_ratio'] * 100 for e in alged_events]
    ax4.scatter(event_times, event_deficits, color=RED, s=15, alpha=0.7, zorder=5)
    ax4.axhline(10, color=YELLOW, lw=1, linestyle='--', label='Schwelle (10%)')
ax4.set_ylabel('Defizit bei Aktivierung (%)', fontsize=10)
ax4.set_title(f'Algedonic-Ereignisse (n={len(alged_events)})', fontsize=10, pad=6)
ax4.legend(fontsize=8)
ax4.xaxis.set_major_formatter(mdates.DateFormatter('%b %Y'))
ax4.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
ax4.grid(True, alpha=0.4)

# ── Panel 5: Stündliche Volatilität ──────────────────────────────────────────
ax5 = fig.add_subplot(gs[2, 1])
cs_vol = pd.Series(df['cs_supply_rate'].values).rolling(168).std() * 100  # 7-Tage-Std
mk_vol = pd.Series(df['mk_supply_rate'].values).rolling(168).std() * 100
ax5.plot(df.index, cs_vol.values, color=CYAN,   lw=1.2, label='Cybersyn', alpha=0.8)
ax5.plot(df.index, mk_vol.values, color=ORANGE, lw=1.2, label='Markt',    alpha=0.8, linestyle='--')
ax5.set_ylabel('Volatilität (7-Tage-Std, %)', fontsize=10)
ax5.set_title('Stündliche Versorgungsvolatilität', fontsize=10, pad=6)
ax5.legend(fontsize=8)
ax5.xaxis.set_major_formatter(mdates.DateFormatter('%b %Y'))
ax5.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
ax5.grid(True, alpha=0.4)

# ── Panel 6: Metriken-Vergleich (Bar) ─────────────────────────────────────────
ax6 = fig.add_subplot(gs[3, :])
categories = [
    'Versorgungsrate\n(%)',
    'Gesamtdefizit\n(GWh / 100)',
    'RMSE\n(GWh × 10)',
    'Volatilität\n(%)',
    'Winter-\nVersorgungsrate (%)',
    'Netzimport\n(GWh / 1000)',
]
cs_vals = [
    cs_m['versorgungsrate'],
    cs_m['gesamtdefizit'] / 100,
    cs_m['rmse'] * 10,
    cs_m['volatilitaet'],
    m['winter_cybersyn']['versorgungsrate'],
    cs_m['total_import'] / 1000,
]
mk_vals = [
    mk_m['versorgungsrate'],
    mk_m['gesamtdefizit'] / 100,
    mk_m['rmse'] * 10,
    mk_m['volatilitaet'],
    m['winter_markt']['versorgungsrate'],
    mk_m['total_import'] / 1000,
]

x = np.arange(len(categories))
w = 0.35
bars_cs = ax6.bar(x - w/2, cs_vals, w, color=CYAN,   alpha=0.85, label='Cybersyn', zorder=3)
bars_mk = ax6.bar(x + w/2, mk_vals, w, color=ORANGE, alpha=0.85, label='Markt',    zorder=3)
ax6.set_xticks(x)
ax6.set_xticklabels(categories, fontsize=9)
ax6.set_title('Metriken-Vergleich (normalisiert)', fontsize=10, pad=6)
ax6.legend(fontsize=9)
ax6.grid(True, alpha=0.3, axis='y')
# Werte annotieren
for bar in bars_cs:
    ax6.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.3,
             f'{bar.get_height():.1f}', ha='center', va='bottom', fontsize=7, color=CYAN)
for bar in bars_mk:
    ax6.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.3,
             f'{bar.get_height():.1f}', ha='center', va='bottom', fontsize=7, color=ORANGE)

plt.savefig('cybersyn_stufe2_main.png', dpi=150, bbox_inches='tight',
            facecolor='#0d1117')
plt.close()
print("  Gespeichert: cybersyn_stufe2_main.png")


# ══════════════════════════════════════════════════════════════════════════════
# PLOT 2: Winter-Krise Detail (Dez 2022 – Feb 2023)
# ══════════════════════════════════════════════════════════════════════════════

mask_detail = (
    (df.index >= pd.Timestamp('2022-12-01', tz='UTC')) &
    (df.index <= pd.Timestamp('2023-02-28', tz='UTC'))
)
df_d = df[mask_detail].copy()

fig2, axes = plt.subplots(3, 1, figsize=(18, 12), sharex=True)
fig2.suptitle('Winter-Energiekrise 2022/23 – Stündliche Auflösung\n'
              'Hamburg | Dez 2022 – Feb 2023 | Import-Kapazität: 0.4 GWh/h',
              fontsize=14, fontweight='bold', color='#e6edf3')
fig2.patch.set_facecolor('#0d1117')

# Versorgungsrate stündlich
ax = axes[0]
ax.set_facecolor('#161b22')
ax.plot(df_d.index, df_d['cs_supply_rate'] * 100, color=CYAN,   lw=0.8,
        label='Cybersyn', alpha=0.9)
ax.plot(df_d.index, df_d['mk_supply_rate'] * 100, color=ORANGE, lw=0.8,
        label='Markt', alpha=0.9, linestyle='--')
ax.axhline(100, color='#30363d', lw=0.6, linestyle=':')
# Algedonic-Ereignisse markieren
alged_mask = df_d['cs_algedonic'].astype(bool)
ax.fill_between(df_d.index, 0, 100, where=alged_mask,
                alpha=0.2, color=RED, label='Algedonic aktiv')
ax.set_ylabel('Versorgungsrate (%)', fontsize=10)
ax.set_title('Stündliche Versorgungsrate', fontsize=10, pad=4)
ax.legend(fontsize=8, loc='lower right')
ax.set_ylim(40, 105)
ax.grid(True, alpha=0.3)

# Speicherfüllstand
ax = axes[1]
ax.set_facecolor('#161b22')
ax.fill_between(df_d.index, df_d['cs_storage'], alpha=0.3, color=CYAN)
ax.fill_between(df_d.index, df_d['mk_storage'], alpha=0.3, color=ORANGE)
ax.plot(df_d.index, df_d['cs_storage'], color=CYAN,   lw=1.0, label='Cybersyn')
ax.plot(df_d.index, df_d['mk_storage'], color=ORANGE, lw=1.0, label='Markt', linestyle='--')
ax.axhline(965, color='#30363d', lw=0.6, linestyle=':', label='Kapazität')
ax.set_ylabel('Speicher (GWh)', fontsize=10)
ax.set_title('Speicherfüllstand', fontsize=10, pad=4)
ax.legend(fontsize=8)
ax.grid(True, alpha=0.3)

# Defizit
ax = axes[2]
ax.set_facecolor('#161b22')
ax.fill_between(df_d.index, df_d['cs_deficit'], alpha=0.5, color=CYAN,   label='Cybersyn')
ax.fill_between(df_d.index, df_d['mk_deficit'], alpha=0.5, color=ORANGE, label='Markt')
ax.set_ylabel('Defizit (GWh/h)', fontsize=10)
ax.set_title('Stündliches Versorgungsdefizit', fontsize=10, pad=4)
ax.legend(fontsize=8)
ax.xaxis.set_major_formatter(mdates.DateFormatter('%d.%m'))
ax.xaxis.set_major_locator(mdates.WeekdayLocator(byweekday=0))
ax.grid(True, alpha=0.3)
plt.setp(ax.xaxis.get_majorticklabels(), rotation=30, ha='right')

plt.tight_layout(rect=[0, 0, 1, 0.95])
plt.savefig('cybersyn_stufe2_winter.png', dpi=150, bbox_inches='tight',
            facecolor='#0d1117')
plt.close()
print("  Gespeichert: cybersyn_stufe2_winter.png")


# ══════════════════════════════════════════════════════════════════════════════
# PLOT 3: Algedonic Channel Diagramm
# ══════════════════════════════════════════════════════════════════════════════

fig3, ax = plt.subplots(figsize=(14, 8))
fig3.patch.set_facecolor('#0d1117')
ax.set_facecolor('#161b22')

# Prioritätshierarchie visualisieren
priorities = ['Kritische\nInfrastruktur\n(10%)', 'Haushalte\n(30%)',
              'KMU\n(25%)', 'Industrie\n(35%)']
colors_p = [GREEN, CYAN, YELLOW, ORANGE]
shares   = [0.10, 0.30, 0.25, 0.35]
bottoms  = [0, 0.10, 0.40, 0.65]

for i, (p, c, s, b) in enumerate(zip(priorities, colors_p, shares, bottoms)):
    ax.barh(0, s, left=b, color=c, alpha=0.85, height=0.4,
            label=f'{p.replace(chr(10), " ")} – Priorität {i+1}')
    ax.text(b + s/2, 0, f'{int(s*100)}%', ha='center', va='center',
            fontsize=11, fontweight='bold', color='#0d1117')

ax.set_xlim(0, 1)
ax.set_ylim(-0.8, 1.5)
ax.set_yticks([])
ax.set_xticks([0, 0.10, 0.40, 0.65, 1.0])
ax.set_xticklabels(['0%', '10%', '40%', '65%', '100%'], fontsize=10)

# Lastabwurf-Pfeile
ax.annotate('', xy=(1.0, -0.3), xytext=(0.65, -0.3),
            arrowprops=dict(arrowstyle='<->', color=ORANGE, lw=2))
ax.text(0.825, -0.45, 'Stufe 1: Industrie\n(bei Defizit > 10%)',
        ha='center', fontsize=9, color=ORANGE)

ax.annotate('', xy=(1.0, -0.6), xytext=(0.40, -0.6),
            arrowprops=dict(arrowstyle='<->', color=YELLOW, lw=2))
ax.text(0.70, -0.75, 'Stufe 2: Industrie + KMU\n(bei Defizit > 35%)',
        ha='center', fontsize=9, color=YELLOW)

ax.set_title('Algedonic Channel – Lastabwurf-Prioritätshierarchie\n'
             f'Aktivierungen in 2022–2023: {m["algedonic_events"]} Ereignisse',
             fontsize=13, fontweight='bold', pad=15)
ax.legend(loc='upper center', bbox_to_anchor=(0.5, 1.22), ncol=2, fontsize=9)
ax.grid(True, alpha=0.2, axis='x')

plt.tight_layout()
plt.savefig('cybersyn_stufe2_algedonic.png', dpi=150, bbox_inches='tight',
            facecolor='#0d1117')
plt.close()
print("  Gespeichert: cybersyn_stufe2_algedonic.png")


# ══════════════════════════════════════════════════════════════════════════════
# PLOT 4: Stufe 1 vs. Stufe 2 Vergleich
# ══════════════════════════════════════════════════════════════════════════════

fig4, axes4 = plt.subplots(1, 2, figsize=(16, 7))
fig4.suptitle('Cybersyn 2.0 – Stufe 1 (Jahresdaten) vs. Stufe 2 (Stundendaten)\n'
              'Vergleich der Systemleistung', fontsize=14, fontweight='bold',
              color='#e6edf3')
fig4.patch.set_facecolor('#0d1117')

# Stufe 1 Daten (aus Bericht)
s1_cs = {'Versorgungsrate': 99.4, 'Defizit (GWh/100)': 25.6, 'Curtailment': 0.7, 'RMSE×10': 5.61}
s1_mk = {'Versorgungsrate': 98.6, 'Defizit (GWh/100)': 64.1, 'Curtailment': 3.2, 'RMSE×10': 8.26}
s2_cs = {'Versorgungsrate': cs_m['versorgungsrate'],
         'Defizit (GWh/100)': cs_m['gesamtdefizit']/100,
         'Curtailment': cs_m['curtailment_pct'],
         'RMSE×10': cs_m['rmse']*10}
s2_mk = {'Versorgungsrate': mk_m['versorgungsrate'],
         'Defizit (GWh/100)': mk_m['gesamtdefizit']/100,
         'Curtailment': mk_m['curtailment_pct'],
         'RMSE×10': mk_m['rmse']*10}

cats = list(s1_cs.keys())
x    = np.arange(len(cats))
w    = 0.2

for ax_i, (title, s1c, s1m, s2c, s2m) in enumerate([
    ('Cybersyn', s1_cs, None, s2_cs, None),
    ('Markt',    None, s1_mk, None, s2_mk),
]):
    ax = axes4[ax_i]
    ax.set_facecolor('#161b22')
    if ax_i == 0:
        ax.bar(x - w/2, list(s1c.values()), w, color=CYAN,   alpha=0.6, label='Stufe 1 (Jahresdaten)')
        ax.bar(x + w/2, list(s2c.values()), w, color=CYAN,   alpha=1.0, label='Stufe 2 (Stundendaten)')
    else:
        ax.bar(x - w/2, list(s1_mk.values()), w, color=ORANGE, alpha=0.6, label='Stufe 1 (Jahresdaten)')
        ax.bar(x + w/2, list(s2_mk.values()), w, color=ORANGE, alpha=1.0, label='Stufe 2 (Stundendaten)')
    ax.set_xticks(x)
    ax.set_xticklabels(cats, fontsize=9)
    ax.set_title(f'{title}: Stufe 1 vs. Stufe 2', fontsize=11, pad=6)
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3, axis='y')

plt.tight_layout(rect=[0, 0, 1, 0.93])
plt.savefig('cybersyn_stufe2_vs_stufe1.png', dpi=150, bbox_inches='tight',
            facecolor='#0d1117')
plt.close()
print("  Gespeichert: cybersyn_stufe2_vs_stufe1.png")

print("\n  Alle Visualisierungen erstellt.")
