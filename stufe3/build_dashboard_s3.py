"""
build_dashboard_s3.py – Interaktives HTML-Dashboard für Cybersyn 2.0 Stufe 3
"""
import pandas as pd
import numpy as np
import json
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import plotly.io as pio

df = pd.read_csv('/home/ubuntu/cybersyn2/stufe3/simulation_results_s3.csv')
df['datetime'] = pd.to_datetime(df['datetime'])
df = df.set_index('datetime')

with open('/home/ubuntu/cybersyn2/stufe3/metrics_s3.json') as f:
    m = json.load(f)

# Wöchentliche Rollmittel
df['cs_elec_sr_7d'] = df['cs_elec_sr'].rolling(168).mean() * 100
df['mk_elec_sr_7d'] = df['mk_elec_sr'].rolling(168).mean() * 100
df['cs_heat_sr_7d'] = df['cs_heat_sr'].rolling(168).mean() * 100
df['mk_heat_sr_7d'] = df['mk_heat_sr'].rolling(168).mean() * 100

CS_COLOR = '#58a6ff'
MK_COLOR = '#f85149'
HT_COLOR = '#3fb950'
WARN_COLOR = '#e3b341'

LAYOUT = dict(
    template='plotly_dark',
    paper_bgcolor='#0d1117',
    plot_bgcolor='#161b22',
    font=dict(family='monospace', color='#c9d1d9'),
    margin=dict(l=60, r=30, t=60, b=40),
)

cw_start = df.index[df['is_cold_wave'] == 1][0] if (df['is_cold_wave'] == 1).any() else None
cw_end   = df.index[df['is_cold_wave'] == 1][-1] if (df['is_cold_wave'] == 1).any() else None

# ─── Tab 1: Übersicht ──────────────────────────────────────────────────────────
fig1 = make_subplots(
    rows=3, cols=2,
    subplot_titles=[
        'Strom-Versorgungsrate (7-Tage-Rollmittel)',
        'Wärme-Versorgungsrate (7-Tage-Rollmittel)',
        'Strom-Speicher (saisonale Strategie)',
        'Wärme-Speicher',
        'Strom-Defizit kumuliert (GWh)',
        'Netzimport monatlich (GWh)',
    ],
    vertical_spacing=0.12, horizontal_spacing=0.08,
)

# Strom-SR
fig1.add_trace(go.Scatter(x=df.index, y=df['cs_elec_sr_7d'],
    name='Cybersyn MPC', line=dict(color=CS_COLOR, width=1.5)), row=1, col=1)
fig1.add_trace(go.Scatter(x=df.index, y=df['mk_elec_sr_7d'],
    name='Markt', line=dict(color=MK_COLOR, width=1.5)), row=1, col=1)
if cw_start:
    fig1.add_vrect(x0=cw_start, x1=cw_end, fillcolor=WARN_COLOR, opacity=0.15,
                   line_width=0, row=1, col=1)

# Wärme-SR
fig1.add_trace(go.Scatter(x=df.index, y=df['cs_heat_sr_7d'],
    name='Cybersyn Wärme', line=dict(color=HT_COLOR, width=1.5),
    showlegend=True), row=1, col=2)
fig1.add_trace(go.Scatter(x=df.index, y=df['mk_heat_sr_7d'],
    name='Markt Wärme', line=dict(color=MK_COLOR, width=1.5, dash='dot'),
    showlegend=True), row=1, col=2)

# Strom-Speicher
fig1.add_trace(go.Scatter(x=df.index, y=df['cs_elec_storage'],
    name='CS Strom-Speicher', fill='tozeroy', fillcolor='rgba(88,166,255,0.15)',
    line=dict(color=CS_COLOR, width=1)), row=2, col=1)
fig1.add_trace(go.Scatter(x=df.index, y=df['mk_elec_storage'],
    name='MK Strom-Speicher', fill='tozeroy', fillcolor='rgba(248,81,73,0.1)',
    line=dict(color=MK_COLOR, width=1)), row=2, col=1)
fig1.add_hline(y=965*0.9, line_dash='dash', line_color=CS_COLOR,
               opacity=0.5, annotation_text='Sommer-Ziel 90%', row=2, col=1)
fig1.add_hline(y=965*0.2, line_dash='dash', line_color=WARN_COLOR,
               opacity=0.5, annotation_text='Winter-Min 20%', row=2, col=1)

# Wärme-Speicher
fig1.add_trace(go.Scatter(x=df.index, y=df['cs_heat_storage'],
    name='CS Wärme-Speicher', fill='tozeroy', fillcolor='rgba(63,185,80,0.15)',
    line=dict(color=HT_COLOR, width=1)), row=2, col=2)
fig1.add_trace(go.Scatter(x=df.index, y=df['mk_heat_storage'],
    name='MK Wärme-Speicher', fill='tozeroy', fillcolor='rgba(248,81,73,0.1)',
    line=dict(color=MK_COLOR, width=1)), row=2, col=2)

# Kumuliertes Defizit
cs_cum = df['cs_elec_deficit'].cumsum()
mk_cum = df['mk_elec_deficit'].cumsum()
fig1.add_trace(go.Scatter(x=df.index, y=cs_cum,
    name='CS Defizit kum.', line=dict(color=CS_COLOR, width=2)), row=3, col=1)
fig1.add_trace(go.Scatter(x=df.index, y=mk_cum,
    name='MK Defizit kum.', line=dict(color=MK_COLOR, width=2)), row=3, col=1)

# Monatlicher Import
monthly_cs = df['cs_elec_import'].resample('ME').sum()
monthly_mk = df['mk_elec_import'].resample('ME').sum()
fig1.add_trace(go.Bar(x=monthly_cs.index, y=monthly_cs.values,
    name='CS Import', marker_color=CS_COLOR, opacity=0.8), row=3, col=2)
fig1.add_trace(go.Bar(x=monthly_mk.index, y=monthly_mk.values,
    name='MK Import', marker_color=MK_COLOR, opacity=0.8), row=3, col=2)

fig1.update_layout(**LAYOUT,
    title=dict(text='Cybersyn 2.0 Stufe 3 – Übersicht Hamburg 2022–2023',
               font=dict(size=16, color='#e6edf3')),
    height=900,
)
fig1.update_yaxes(title_text='SR (%)', row=1, col=1)
fig1.update_yaxes(title_text='SR (%)', row=1, col=2)
fig1.update_yaxes(title_text='GWh', row=2, col=1)
fig1.update_yaxes(title_text='GWh', row=2, col=2)
fig1.update_yaxes(title_text='GWh kum.', row=3, col=1)
fig1.update_yaxes(title_text='GWh/Monat', row=3, col=2)

# ─── Tab 2: Kältewelle ────────────────────────────────────────────────────────
win_start = cw_start - pd.Timedelta(days=5) if cw_start else df.index[0]
win_end   = cw_end   + pd.Timedelta(days=5) if cw_end else df.index[-1]
win = df.loc[win_start:win_end]

fig2 = make_subplots(rows=3, cols=1,
    subplot_titles=[
        f'Strom: Cybersyn {m["cs_cold_elec_sr"]:.1f}% vs. Markt {m["mk_cold_elec_sr"]:.1f}% (+{m["cs_cold_elec_sr"]-m["mk_cold_elec_sr"]:.1f}%)',
        f'Wärme: Cybersyn {m["cs_cold_heat_sr"]:.1f}% vs. Markt {m["mk_cold_heat_sr"]:.1f}%',
        'Temperatur & Strom-Speicher',
    ],
    vertical_spacing=0.12,
)
fig2.add_trace(go.Scatter(x=win.index, y=win['cs_elec_sr']*100,
    name='Cybersyn Strom', line=dict(color=CS_COLOR, width=1.5)), row=1, col=1)
fig2.add_trace(go.Scatter(x=win.index, y=win['mk_elec_sr']*100,
    name='Markt Strom', line=dict(color=MK_COLOR, width=1.5)), row=1, col=1)
if cw_start:
    for r in [1, 2, 3]:
        fig2.add_vrect(x0=cw_start, x1=cw_end, fillcolor=WARN_COLOR,
                       opacity=0.12, line_width=0, row=r, col=1)

fig2.add_trace(go.Scatter(x=win.index, y=win['cs_heat_sr']*100,
    name='Cybersyn Wärme', line=dict(color=HT_COLOR, width=1.5)), row=2, col=1)
fig2.add_trace(go.Scatter(x=win.index, y=win['mk_heat_sr']*100,
    name='Markt Wärme', line=dict(color=MK_COLOR, width=1.5, dash='dot')), row=2, col=1)

fig2.add_trace(go.Scatter(x=win.index, y=win['temp_c'],
    name='Temperatur (°C)', line=dict(color=WARN_COLOR, width=2)), row=3, col=1)
fig2.add_trace(go.Scatter(x=win.index, y=win['cs_elec_storage'],
    name='CS Speicher (GWh)', line=dict(color=CS_COLOR, width=1.5, dash='dash'),
    yaxis='y6'), row=3, col=1)

fig2.update_layout(**LAYOUT,
    title=dict(text='Kältewelle-Stresstest: -15°C für 72h (15. Jan 2023)',
               font=dict(size=15, color='#e6edf3')),
    height=750,
)

# ─── Tab 3: Metriken-Vergleich ────────────────────────────────────────────────
fig3 = go.Figure()
metrics_labels = ['Strom-SR (%)', 'Wärme-SR (%)', 'Gesamt-SR (%)',
                  'Kältewelle Strom-SR (%)', 'Kältewelle Wärme-SR (%)']
cs_vals = [m['cs_elec_sr'], m['cs_heat_sr'], m['cs_total_sr'],
           m['cs_cold_elec_sr'], m['cs_cold_heat_sr']]
mk_vals = [m['mk_elec_sr'], m['mk_heat_sr'], m['mk_total_sr'],
           m['mk_cold_elec_sr'], m['mk_cold_heat_sr']]

fig3.add_trace(go.Bar(name='Cybersyn MPC', x=metrics_labels, y=cs_vals,
    marker_color=CS_COLOR, opacity=0.85,
    text=[f'{v:.1f}%' for v in cs_vals], textposition='outside'))
fig3.add_trace(go.Bar(name='Markt', x=metrics_labels, y=mk_vals,
    marker_color=MK_COLOR, opacity=0.85,
    text=[f'{v:.1f}%' for v in mk_vals], textposition='outside'))

fig3.update_layout(**LAYOUT,
    title=dict(text='Metriken-Vergleich: Cybersyn MPC vs. Markt',
               font=dict(size=15, color='#e6edf3')),
    barmode='group', yaxis_range=[40, 105],
    yaxis_title='Versorgungsrate (%)',
    height=500,
)

# ─── Tab 4: Skalierungspfad ───────────────────────────────────────────────────
fig4 = make_subplots(rows=1, cols=3,
    subplot_titles=['Strom-Versorgungsrate', 'Strom-Gesamtdefizit (GWh)', 'Schock-Resilienz (%)'])

stufen = ['Stufe 1<br>(Jahreswerte)', 'Stufe 2<br>(Stundenwerte)', 'Stufe 3<br>(Sektorkopplung)']
cs_sr_all = [99.4, 95.48, 95.96]
mk_sr_all = [98.6, 93.77, 89.01]
cs_def_all = [2563, 200, 482]
mk_def_all = [6411, 1705, 2958]
cs_shock_all = [97.2, 76.0, 86.17]
mk_shock_all = [94.1, 53.0, 63.84]

for col, (cs_v, mk_v, ylabel) in enumerate([
    (cs_sr_all, mk_sr_all, 'SR (%)'),
    (cs_def_all, mk_def_all, 'GWh'),
    (cs_shock_all, mk_shock_all, 'SR (%)'),
], 1):
    fig4.add_trace(go.Bar(name='Cybersyn', x=stufen, y=cs_v,
        marker_color=CS_COLOR, opacity=0.85,
        text=[f'{v:.1f}' for v in cs_v], textposition='outside',
        showlegend=(col == 1)), row=1, col=col)
    fig4.add_trace(go.Bar(name='Markt', x=stufen, y=mk_v,
        marker_color=MK_COLOR, opacity=0.85,
        text=[f'{v:.1f}' for v in mk_v], textposition='outside',
        showlegend=(col == 1)), row=1, col=col)

fig4.update_layout(**LAYOUT,
    title=dict(text='Cybersyn 2.0 – Skalierungspfad Stufe 1 → 2 → 3',
               font=dict(size=15, color='#e6edf3')),
    barmode='group', height=500,
)

# ─── HTML zusammenbauen ───────────────────────────────────────────────────────
html_parts = [
    '<!DOCTYPE html><html><head>',
    '<meta charset="UTF-8">',
    '<title>Cybersyn 2.0 – Stufe 3 Dashboard</title>',
    '<style>',
    'body { background: #0d1117; color: #c9d1d9; font-family: monospace; margin: 0; padding: 20px; }',
    'h1 { color: #58a6ff; text-align: center; font-size: 1.4em; margin-bottom: 5px; }',
    'p.subtitle { text-align: center; color: #8b949e; margin-bottom: 20px; font-size: 0.9em; }',
    '.tabs { display: flex; gap: 5px; margin-bottom: 15px; }',
    '.tab { padding: 8px 18px; background: #161b22; border: 1px solid #30363d; cursor: pointer;',
    '       color: #8b949e; border-radius: 4px; font-family: monospace; }',
    '.tab.active { background: #1f6feb; color: #fff; border-color: #1f6feb; }',
    '.panel { display: none; } .panel.active { display: block; }',
    '.metrics-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 20px; }',
    '.metric-card { background: #161b22; border: 1px solid #30363d; border-radius: 6px;',
    '               padding: 12px; text-align: center; }',
    '.metric-val { font-size: 1.6em; font-weight: bold; }',
    '.metric-lbl { font-size: 0.75em; color: #8b949e; margin-top: 4px; }',
    '.metric-delta { font-size: 0.85em; margin-top: 4px; }',
    '.pos { color: #3fb950; } .neg { color: #f85149; }',
    '</style></head><body>',
    '<h1>&#9889; Cybersyn 2.0 – Stufe 3: Sektorkopplung Hamburg</h1>',
    f'<p class="subtitle">MPC-Regler (72h Vorausschau) + Algedonic Channel | '
    f'SMARD-Daten 2022–2023 | Open-Meteo Wetterdaten</p>',
    # Metriken-Karten
    '<div class="metrics-grid">',
]

cards = [
    ('Strom-SR', f'{m["cs_elec_sr"]:.1f}%', f'+{m["cs_elec_sr"]-m["mk_elec_sr"]:.1f}% vs. Markt', True),
    ('Wärme-SR', f'{m["cs_heat_sr"]:.1f}%', f'+{m["cs_heat_sr"]-m["mk_heat_sr"]:.1f}% vs. Markt', True),
    ('Strom-Defizit', f'{m["cs_elec_deficit"]:.0f} GWh', f'–{(1-m["cs_elec_deficit"]/m["mk_elec_deficit"])*100:.0f}% vs. Markt', True),
    ('Kältewelle Strom', f'{m["cs_cold_elec_sr"]:.1f}%', f'+{m["cs_cold_elec_sr"]-m["mk_cold_elec_sr"]:.1f}% vs. Markt', True),
    ('Gesamt-SR', f'{m["cs_total_sr"]:.1f}%', f'+{m["cs_total_sr"]-m["mk_total_sr"]:.1f}% vs. Markt', True),
    ('Algedonic Events', f'{m["cs_alg_events"]}', 'Notfall-Aktivierungen', None),
    ('V2G genutzt', f'{m["cs_v2g_total"]:.2f} GWh', 'Vehicle-to-Grid', None),
    ('CO₂ vermieden', f'{abs(m["cs_co2_avoided_t"])/1000:.0f} kt', 'durch weniger Import', None),
]
for lbl, val, delta, is_pos in cards:
    delta_cls = 'pos' if is_pos else ('neg' if is_pos is False else '')
    html_parts.append(
        f'<div class="metric-card"><div class="metric-val" style="color: #58a6ff">{val}</div>'
        f'<div class="metric-lbl">{lbl}</div>'
        f'<div class="metric-delta {delta_cls}">{delta}</div></div>'
    )
html_parts.append('</div>')

# Tabs
html_parts += [
    '<div class="tabs">',
    '<button class="tab active" onclick="showTab(0)">Übersicht</button>',
    '<button class="tab" onclick="showTab(1)">Kältewelle</button>',
    '<button class="tab" onclick="showTab(2)">Metriken</button>',
    '<button class="tab" onclick="showTab(3)">Skalierungspfad</button>',
    '</div>',
]

figs = [fig1, fig2, fig3, fig4]
for i, fig in enumerate(figs):
    active = 'active' if i == 0 else ''
    html_parts.append(f'<div class="panel {active}" id="panel-{i}">')
    html_parts.append(fig.to_html(full_html=False, include_plotlyjs=(i == 0)))
    html_parts.append('</div>')

html_parts += [
    '<script>',
    'function showTab(n) {',
    '  document.querySelectorAll(".tab").forEach((t,i) => t.classList.toggle("active", i===n));',
    '  document.querySelectorAll(".panel").forEach((p,i) => p.classList.toggle("active", i===n));',
    '}',
    '</script>',
    '</body></html>',
]

html = '\n'.join(html_parts)
with open('dashboard_stufe3.html', 'w', encoding='utf-8') as f:
    f.write(html)

import os
size_kb = os.path.getsize('dashboard_stufe3.html') // 1024
print(f"  Gespeichert: dashboard_stufe3.html ({size_kb} KB)")
