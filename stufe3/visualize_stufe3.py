"""
visualize_stufe3.py – Visualisierungen für Cybersyn 2.0 Stufe 3
"""
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import matplotlib.patches as mpatches
import json, warnings
warnings.filterwarnings('ignore')

plt.rcParams.update({
    'font.family': 'DejaVu Sans',
    'font.size': 10,
    'axes.titlesize': 12,
    'axes.labelsize': 10,
    'figure.facecolor': '#0d1117',
    'axes.facecolor': '#161b22',
    'axes.edgecolor': '#30363d',
    'axes.labelcolor': '#c9d1d9',
    'text.color': '#c9d1d9',
    'xtick.color': '#8b949e',
    'ytick.color': '#8b949e',
    'grid.color': '#21262d',
    'grid.linewidth': 0.5,
    'legend.facecolor': '#161b22',
    'legend.edgecolor': '#30363d',
})

CS_COLOR  = '#58a6ff'
MK_COLOR  = '#f85149'
HT_COLOR  = '#3fb950'
EV_COLOR  = '#d2a8ff'
WARN_COLOR = '#e3b341'

df = pd.read_csv('/home/ubuntu/cybersyn2/stufe3/simulation_results_s3.csv')
df['datetime'] = pd.to_datetime(df['datetime'])
df = df.set_index('datetime')

with open('/home/ubuntu/cybersyn2/stufe3/metrics_s3.json') as f:
    m = json.load(f)

# Wöchentliche Rollmittel
df['cs_elec_sr_7d'] = df['cs_elec_sr'].rolling(168).mean()
df['mk_elec_sr_7d'] = df['mk_elec_sr'].rolling(168).mean()
df['cs_heat_sr_7d'] = df['cs_heat_sr'].rolling(168).mean()
df['mk_heat_sr_7d'] = df['mk_heat_sr'].rolling(168).mean()

# ─── Plot 1: Hauptübersicht ────────────────────────────────────────────────────
fig = plt.figure(figsize=(18, 14))
fig.suptitle('Cybersyn 2.0 – Stufe 3: Sektorkopplung Hamburg 2022–2023\n'
             'MPC-Regler (72h Vorausschau) + Algedonic Channel vs. Marktmechanismus',
             fontsize=14, fontweight='bold', color='#e6edf3', y=0.98)
gs = gridspec.GridSpec(3, 2, figure=fig, hspace=0.45, wspace=0.3)

# 1a: Strom-Versorgungsrate (7-Tage-Mittel)
ax1 = fig.add_subplot(gs[0, :])
ax1.plot(df.index, df['cs_elec_sr_7d'] * 100, color=CS_COLOR, lw=1.5,
         label=f'Cybersyn MPC ({m["cs_elec_sr"]:.1f}%)')
ax1.plot(df.index, df['mk_elec_sr_7d'] * 100, color=MK_COLOR, lw=1.5,
         label=f'Markt ({m["mk_elec_sr"]:.1f}%)')
# Kältewelle markieren
cw_mask = df['is_cold_wave'] == 1
if cw_mask.any():
    cw_start = df.index[cw_mask][0]
    cw_end   = df.index[cw_mask][-1]
    ax1.axvspan(cw_start, cw_end, alpha=0.25, color=WARN_COLOR, label='Kältewelle (-15°C, 72h)')
ax1.axhline(100, color='#30363d', lw=0.5, ls='--')
ax1.set_ylabel('Strom-Versorgungsrate (%)')
ax1.set_title('Strom-Versorgungsrate (7-Tage-Rollmittel)')
ax1.legend(loc='lower left', fontsize=9)
ax1.set_ylim(40, 105)
ax1.grid(True, alpha=0.3)

# 1b: Strom-Speicher
ax2 = fig.add_subplot(gs[1, 0])
ax2.fill_between(df.index, df['cs_elec_storage'], alpha=0.4, color=CS_COLOR)
ax2.plot(df.index, df['cs_elec_storage'], color=CS_COLOR, lw=1, label='Cybersyn')
ax2.fill_between(df.index, df['mk_elec_storage'], alpha=0.2, color=MK_COLOR)
ax2.plot(df.index, df['mk_elec_storage'], color=MK_COLOR, lw=1, label='Markt')
ax2.axhline(965 * 0.9, color=CS_COLOR, lw=0.8, ls='--', alpha=0.6, label='Sommer-Ziel 90%')
ax2.axhline(965 * 0.2, color=WARN_COLOR, lw=0.8, ls='--', alpha=0.6, label='Winter-Minimum 20%')
ax2.set_ylabel('Strom-Speicher (GWh)')
ax2.set_title('Strom-Speicher (saisonale Strategie)')
ax2.legend(fontsize=8)
ax2.grid(True, alpha=0.3)

# 1c: Wärme-Versorgungsrate
ax3 = fig.add_subplot(gs[1, 1])
ax3.plot(df.index, df['cs_heat_sr_7d'] * 100, color=HT_COLOR, lw=1.5,
         label=f'Cybersyn ({m["cs_heat_sr"]:.1f}%)')
ax3.plot(df.index, df['mk_heat_sr_7d'] * 100, color=MK_COLOR, lw=1.5,
         label=f'Markt ({m["mk_heat_sr"]:.1f}%)')
if cw_mask.any():
    ax3.axvspan(cw_start, cw_end, alpha=0.25, color=WARN_COLOR)
ax3.set_ylabel('Wärme-Versorgungsrate (%)')
ax3.set_title('Wärme-Versorgungsrate (7-Tage-Rollmittel)')
ax3.legend(fontsize=9)
ax3.set_ylim(85, 105)
ax3.grid(True, alpha=0.3)

# 1d: Metriken-Vergleich (Balkendiagramm)
ax4 = fig.add_subplot(gs[2, 0])
categories = ['Strom-SR\n(%)', 'Wärme-SR\n(%)', 'Gesamt-SR\n(%)']
cs_vals = [m['cs_elec_sr'], m['cs_heat_sr'], m['cs_total_sr']]
mk_vals = [m['mk_elec_sr'], m['mk_heat_sr'], m['mk_total_sr']]
x = np.arange(len(categories))
w = 0.35
bars1 = ax4.bar(x - w/2, cs_vals, w, color=CS_COLOR, alpha=0.85, label='Cybersyn MPC')
bars2 = ax4.bar(x + w/2, mk_vals, w, color=MK_COLOR, alpha=0.85, label='Markt')
for bar, val in zip(bars1, cs_vals):
    ax4.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.3,
             f'{val:.1f}%', ha='center', va='bottom', fontsize=8, color=CS_COLOR)
for bar, val in zip(bars2, mk_vals):
    ax4.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.3,
             f'{val:.1f}%', ha='center', va='bottom', fontsize=8, color=MK_COLOR)
ax4.set_ylabel('Versorgungsrate (%)')
ax4.set_title('Versorgungsraten-Vergleich')
ax4.set_xticks(x); ax4.set_xticklabels(categories)
ax4.legend(fontsize=9)
ax4.set_ylim(85, 102)
ax4.grid(True, alpha=0.3, axis='y')

# 1e: Defizit-Vergleich
ax5 = fig.add_subplot(gs[2, 1])
deficit_cats = ['Strom-Defizit\n(GWh)', 'Wärme-Defizit\n(GWh)']
cs_def = [m['cs_elec_deficit'], m['cs_heat_deficit']]
mk_def = [m['mk_elec_deficit'], m['mk_heat_deficit']]
x2 = np.arange(len(deficit_cats))
bars3 = ax5.bar(x2 - w/2, cs_def, w, color=CS_COLOR, alpha=0.85, label='Cybersyn MPC')
bars4 = ax5.bar(x2 + w/2, mk_def, w, color=MK_COLOR, alpha=0.85, label='Markt')
for bar, val in zip(bars3, cs_def):
    ax5.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 5,
             f'{val:.0f}', ha='center', va='bottom', fontsize=9, color=CS_COLOR)
for bar, val in zip(bars4, mk_def):
    ax5.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 5,
             f'{val:.0f}', ha='center', va='bottom', fontsize=9, color=MK_COLOR)
ax5.set_ylabel('Defizit (GWh)')
ax5.set_title(f'Gesamtdefizit\n(Cybersyn -{(1-m["cs_elec_deficit"]/m["mk_elec_deficit"])*100:.0f}% weniger Strom-Defizit)')
ax5.set_xticks(x2); ax5.set_xticklabels(deficit_cats)
ax5.legend(fontsize=9)
ax5.grid(True, alpha=0.3, axis='y')

plt.savefig('cybersyn_stufe3_main.png', dpi=150, bbox_inches='tight',
            facecolor=fig.get_facecolor())
plt.close()
print("  Gespeichert: cybersyn_stufe3_main.png")


# ─── Plot 2: Kältewelle-Detail ────────────────────────────────────────────────
cw_df = df[df['is_cold_wave'] == 1].copy()
# 5 Tage vor und nach Kältewelle
cw_start_ts = cw_df.index[0]
cw_end_ts   = cw_df.index[-1]
window_start = cw_start_ts - pd.Timedelta(days=5)
window_end   = cw_end_ts   + pd.Timedelta(days=5)
win = df.loc[window_start:window_end]

fig2, axes = plt.subplots(3, 1, figsize=(16, 12))
fig2.patch.set_facecolor('#0d1117')
fig2.suptitle('Kältewelle-Stresstest: -15°C für 72h (15. Jan 2023)\n'
              'Cybersyn MPC vs. Markt – Sektorübergreifende Reaktion',
              fontsize=13, fontweight='bold', color='#e6edf3')

# Strom
ax = axes[0]
ax.set_facecolor('#161b22')
ax.plot(win.index, win['cs_elec_sr'] * 100, color=CS_COLOR, lw=1.2, alpha=0.8,
        label=f'Cybersyn Strom-SR')
ax.plot(win.index, win['mk_elec_sr'] * 100, color=MK_COLOR, lw=1.2, alpha=0.8,
        label=f'Markt Strom-SR')
ax.axvspan(cw_start_ts, cw_end_ts, alpha=0.2, color=WARN_COLOR, label='Kältewelle')
ax.axhline(100, color='#30363d', lw=0.5, ls='--')
ax.set_ylabel('Strom-SR (%)')
ax.set_title(f'Strom: Cybersyn {m["cs_cold_elec_sr"]:.1f}% vs. Markt {m["mk_cold_elec_sr"]:.1f}% '
             f'(+{m["cs_cold_elec_sr"]-m["mk_cold_elec_sr"]:.1f}%)')
ax.legend(fontsize=9, loc='lower left')
ax.set_ylim(30, 110)
ax.grid(True, alpha=0.3, color='#21262d')
for spine in ax.spines.values(): spine.set_edgecolor('#30363d')
ax.tick_params(colors='#8b949e')

# Wärme
ax = axes[1]
ax.set_facecolor('#161b22')
ax.plot(win.index, win['cs_heat_sr'] * 100, color=HT_COLOR, lw=1.2, alpha=0.8,
        label=f'Cybersyn Wärme-SR')
ax.plot(win.index, win['mk_heat_sr'] * 100, color=MK_COLOR, lw=1.2, alpha=0.8,
        label=f'Markt Wärme-SR')
ax.axvspan(cw_start_ts, cw_end_ts, alpha=0.2, color=WARN_COLOR)
ax.axhline(100, color='#30363d', lw=0.5, ls='--')
ax.set_ylabel('Wärme-SR (%)')
ax.set_title(f'Wärme: Cybersyn {m["cs_cold_heat_sr"]:.1f}% vs. Markt {m["mk_cold_heat_sr"]:.1f}%')
ax.legend(fontsize=9, loc='lower left')
ax.set_ylim(85, 105)
ax.grid(True, alpha=0.3, color='#21262d')
for spine in ax.spines.values(): spine.set_edgecolor('#30363d')
ax.tick_params(colors='#8b949e')

# Temperatur + Speicher
ax = axes[2]
ax.set_facecolor('#161b22')
ax2b = ax.twinx()
ax.plot(win.index, win['temp_c'], color=WARN_COLOR, lw=1.5, label='Temperatur (°C)')
ax.axhline(0, color='#30363d', lw=0.5, ls='--')
ax.axvspan(cw_start_ts, cw_end_ts, alpha=0.2, color=WARN_COLOR)
ax2b.plot(win.index, win['cs_elec_storage'], color=CS_COLOR, lw=1.2, ls='--',
          alpha=0.7, label='CS Strom-Speicher (GWh)')
ax2b.plot(win.index, win['mk_elec_storage'], color=MK_COLOR, lw=1.2, ls='--',
          alpha=0.7, label='MK Strom-Speicher (GWh)')
ax.set_ylabel('Temperatur (°C)', color=WARN_COLOR)
ax2b.set_ylabel('Strom-Speicher (GWh)', color=CS_COLOR)
ax.set_title('Temperatur & Speicher-Einsatz während Kältewelle')
lines1, labels1 = ax.get_legend_handles_labels()
lines2, labels2 = ax2b.get_legend_handles_labels()
ax.legend(lines1 + lines2, labels1 + labels2, fontsize=9, loc='lower left')
ax.grid(True, alpha=0.3, color='#21262d')
for spine in ax.spines.values(): spine.set_edgecolor('#30363d')
ax.tick_params(colors='#8b949e')

plt.tight_layout()
plt.savefig('cybersyn_stufe3_coldwave.png', dpi=150, bbox_inches='tight',
            facecolor='#0d1117')
plt.close()
print("  Gespeichert: cybersyn_stufe3_coldwave.png")


# ─── Plot 3: Stufe 1 → 2 → 3 Vergleich ───────────────────────────────────────
fig3, axes3 = plt.subplots(1, 3, figsize=(18, 7))
fig3.patch.set_facecolor('#0d1117')
fig3.suptitle('Cybersyn 2.0 – Skalierungspfad: Stufe 1 → 2 → 3\n'
              'Proof of Concept: Kybernetische Steuerung übertrifft Markt auf jeder Ebene',
              fontsize=13, fontweight='bold', color='#e6edf3')

stufen = ['Stufe 1\n(Jahreswerte\nEurostat)', 'Stufe 2\n(Stundenwerte\nSMARD)', 'Stufe 3\n(Sektorkopplung\nMPC+Algedonic)']
cs_sr  = [99.4, 95.48, 95.96]
mk_sr  = [98.6, 93.77, 89.01]
cs_def = [2563, 200, 482]
mk_def = [6411, 1705, 2958]
cs_cw  = [None, 76.0, 86.17]  # Stufe 1 hat keine Kältewelle
mk_cw  = [None, 53.0, 63.84]

x = np.arange(3)
w = 0.35

# Versorgungsrate
ax = axes3[0]
ax.set_facecolor('#161b22')
b1 = ax.bar(x - w/2, cs_sr, w, color=CS_COLOR, alpha=0.85, label='Cybersyn')
b2 = ax.bar(x + w/2, mk_sr, w, color=MK_COLOR, alpha=0.85, label='Markt')
for bar, val in zip(b1, cs_sr):
    ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.1,
            f'{val:.1f}%', ha='center', va='bottom', fontsize=8, color=CS_COLOR, fontweight='bold')
for bar, val in zip(b2, mk_sr):
    ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.1,
            f'{val:.1f}%', ha='center', va='bottom', fontsize=8, color=MK_COLOR, fontweight='bold')
ax.set_ylabel('Versorgungsrate (%)')
ax.set_title('Strom-Versorgungsrate')
ax.set_xticks(x); ax.set_xticklabels(stufen, fontsize=8)
ax.legend(fontsize=9)
ax.set_ylim(85, 102)
ax.grid(True, alpha=0.3, axis='y', color='#21262d')
for spine in ax.spines.values(): spine.set_edgecolor('#30363d')
ax.tick_params(colors='#8b949e')

# Defizit
ax = axes3[1]
ax.set_facecolor('#161b22')
b3 = ax.bar(x - w/2, cs_def, w, color=CS_COLOR, alpha=0.85, label='Cybersyn')
b4 = ax.bar(x + w/2, mk_def, w, color=MK_COLOR, alpha=0.85, label='Markt')
for bar, val in zip(b3, cs_def):
    ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 30,
            f'{val:.0f}', ha='center', va='bottom', fontsize=8, color=CS_COLOR, fontweight='bold')
for bar, val in zip(b4, mk_def):
    ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 30,
            f'{val:.0f}', ha='center', va='bottom', fontsize=8, color=MK_COLOR, fontweight='bold')
# Reduktions-Pfeile
for i in range(3):
    reduction = (1 - cs_def[i]/mk_def[i]) * 100
    ax.annotate(f'–{reduction:.0f}%', xy=(x[i], max(cs_def[i], mk_def[i]) + 200),
                ha='center', fontsize=9, color='#3fb950', fontweight='bold')
ax.set_ylabel('Gesamtdefizit (GWh)')
ax.set_title('Strom-Gesamtdefizit')
ax.set_xticks(x); ax.set_xticklabels(stufen, fontsize=8)
ax.legend(fontsize=9)
ax.grid(True, alpha=0.3, axis='y', color='#21262d')
for spine in ax.spines.values(): spine.set_edgecolor('#30363d')
ax.tick_params(colors='#8b949e')

# Schock-Resilienz (Kältewelle / Extremereignis)
ax = axes3[2]
ax.set_facecolor('#161b22')
# Stufe 1: kein Kältewellen-Test, zeige Schock-Resilienz aus Stabilitätsanalyse
cs_shock = [97.2, 76.0, 86.17]  # Stufe 1: aus Stabilitätsanalyse
mk_shock = [94.1, 53.0, 63.84]
b5 = ax.bar(x - w/2, cs_shock, w, color=CS_COLOR, alpha=0.85, label='Cybersyn')
b6 = ax.bar(x + w/2, mk_shock, w, color=MK_COLOR, alpha=0.85, label='Markt')
for bar, val in zip(b5, cs_shock):
    ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.3,
            f'{val:.1f}%', ha='center', va='bottom', fontsize=8, color=CS_COLOR, fontweight='bold')
for bar, val in zip(b6, mk_shock):
    ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.3,
            f'{val:.1f}%', ha='center', va='bottom', fontsize=8, color=MK_COLOR, fontweight='bold')
ax.set_ylabel('Versorgungsrate bei Schock (%)')
ax.set_title('Schock-Resilienz\n(Extremereignis / Kältewelle)')
ax.set_xticks(x); ax.set_xticklabels(stufen, fontsize=8)
ax.legend(fontsize=9)
ax.set_ylim(40, 105)
ax.grid(True, alpha=0.3, axis='y', color='#21262d')
for spine in ax.spines.values(): spine.set_edgecolor('#30363d')
ax.tick_params(colors='#8b949e')

plt.tight_layout()
plt.savefig('cybersyn_stufe3_skalierung.png', dpi=150, bbox_inches='tight',
            facecolor='#0d1117')
plt.close()
print("  Gespeichert: cybersyn_stufe3_skalierung.png")


# ─── Plot 4: Sektorkopplung & Algedonic Channel ───────────────────────────────
fig4, axes4 = plt.subplots(2, 2, figsize=(16, 10))
fig4.patch.set_facecolor('#0d1117')
fig4.suptitle('Cybersyn 2.0 Stufe 3 – Sektorkopplung & Algedonic Channel\n'
              'Drei gekoppelte Subsysteme unter kybernetischer Steuerung',
              fontsize=13, fontweight='bold', color='#e6edf3')

# Wärme-Speicher saisonal
ax = axes4[0, 0]
ax.set_facecolor('#161b22')
ax.fill_between(df.index, df['cs_heat_storage'], alpha=0.4, color=HT_COLOR)
ax.plot(df.index, df['cs_heat_storage'], color=HT_COLOR, lw=1, label='Cybersyn')
ax.fill_between(df.index, df['mk_heat_storage'], alpha=0.2, color=MK_COLOR)
ax.plot(df.index, df['mk_heat_storage'], color=MK_COLOR, lw=1, label='Markt')
ax.set_ylabel('Wärme-Speicher (GWh)')
ax.set_title('Wärme-Speicher (saisonal)')
ax.legend(fontsize=9)
ax.grid(True, alpha=0.3, color='#21262d')
for spine in ax.spines.values(): spine.set_edgecolor('#30363d')
ax.tick_params(colors='#8b949e')

# Algedonic Channel Aktivierungen
ax = axes4[0, 1]
ax.set_facecolor('#161b22')
alg_elec = df['cs_alg_elec'].rolling(24).sum()
alg_heat = df['cs_alg_heat'].rolling(24).sum()
ax.fill_between(df.index, alg_elec, alpha=0.6, color=CS_COLOR, label='Strom-Algedonic (24h-Summe)')
ax.fill_between(df.index, alg_heat, alpha=0.6, color=HT_COLOR, label='Wärme-Algedonic (24h-Summe)')
if cw_mask.any():
    ax.axvspan(cw_start_ts, cw_end_ts, alpha=0.2, color=WARN_COLOR, label='Kältewelle')
ax.set_ylabel('Algedonic-Aktivierungen (24h)')
ax.set_title(f'Algedonic Channel ({m["cs_alg_events"]} Gesamtereignisse)')
ax.legend(fontsize=9)
ax.grid(True, alpha=0.3, color='#21262d')
for spine in ax.spines.values(): spine.set_edgecolor('#30363d')
ax.tick_params(colors='#8b949e')

# Prioritätshierarchie (Infografik)
ax = axes4[1, 0]
ax.set_facecolor('#161b22')
ax.set_xlim(0, 10); ax.set_ylim(0, 9)
ax.axis('off')
ax.set_title('Algedonic Channel – Prioritätshierarchie', color='#e6edf3')
priorities = [
    ('1. Kritische Infrastruktur (Strom)', '#f85149', '→ NIE abgeworfen'),
    ('2. Wärme Haushalte', '#e3b341', '→ Winterschutz'),
    ('3. Strom Haushalte', '#58a6ff', '→ Geschützt'),
    ('4. E-Auto Laden', '#d2a8ff', '→ Erste Reduktion'),
    ('5. Wärme KMU', '#3fb950', '→ Reduziert'),
    ('6. Strom KMU', '#58a6ff', '→ Reduziert'),
    ('7. Wärme Industrie', '#e3b341', '→ Abgeworfen'),
    ('8. Strom Industrie', '#f85149', '→ Zuerst abgeworfen'),
]
for i, (label, color, note) in enumerate(priorities):
    y = 8.2 - i * 0.9
    ax.add_patch(mpatches.FancyBboxPatch((0.2, y-0.35), 9.6, 0.65,
                 boxstyle='round,pad=0.05', facecolor=color, alpha=0.2,
                 edgecolor=color, linewidth=1))
    ax.text(0.5, y, label, va='center', fontsize=9, color=color, fontweight='bold')
    ax.text(7.5, y, note, va='center', fontsize=8, color='#8b949e')

# Netzimport-Vergleich monatlich
ax = axes4[1, 1]
ax.set_facecolor('#161b22')
monthly_cs = df['cs_elec_import'].resample('ME').sum()
monthly_mk = df['mk_elec_import'].resample('ME').sum()
months = range(len(monthly_cs))
ax.bar([m - 0.2 for m in months], monthly_cs.values, 0.4,
       color=CS_COLOR, alpha=0.8, label='Cybersyn')
ax.bar([m + 0.2 for m in months], monthly_mk.values, 0.4,
       color=MK_COLOR, alpha=0.8, label='Markt')
ax.set_xticks(list(months))
ax.set_xticklabels([d.strftime('%b\n%y') for d in monthly_cs.index], fontsize=7)
ax.set_ylabel('Netzimport (GWh/Monat)')
ax.set_title(f'Monatlicher Netzimport\n(CS gesamt: {m["cs_elec_import"]:.0f} GWh, '
             f'MK: {m["mk_elec_import"]:.0f} GWh)')
ax.legend(fontsize=9)
ax.grid(True, alpha=0.3, axis='y', color='#21262d')
for spine in ax.spines.values(): spine.set_edgecolor('#30363d')
ax.tick_params(colors='#8b949e')

plt.tight_layout()
plt.savefig('cybersyn_stufe3_sektoren.png', dpi=150, bbox_inches='tight',
            facecolor='#0d1117')
plt.close()
print("  Gespeichert: cybersyn_stufe3_sektoren.png")
print("\nAlle Visualisierungen erstellt.")
