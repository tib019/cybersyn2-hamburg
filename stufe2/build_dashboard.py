"""
Cybersyn 2.0 – Stufe 2: Interaktives HTML-Dashboard
Plotly-basiert, vollständig offline-fähig (CDN-Einbindung)
"""
import pandas as pd
import numpy as np
import json
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import plotly.io as pio

# ─── Daten laden ──────────────────────────────────────────────────────────────
df = pd.read_csv('simulation_results.csv')
df['datetime'] = pd.to_datetime(df['datetime'], utc=True)
df = df.set_index('datetime')

with open('metrics.json') as f:
    m = json.load(f)

cs_m = m['cybersyn']
mk_m = m['markt']

# Wöchentliche Aggregation
df_w = df.resample('W').mean()

# Krisenmonate
mask_crisis = df['is_crisis'].astype(bool)

# Kumulatives Defizit
cs_cum = np.cumsum(df['cs_deficit'].values)
mk_cum = np.cumsum(df['mk_deficit'].values)

# Algedonic Events
alged_events = m.get('algedonic_event_list', [])
if alged_events:
    ev_times    = pd.to_datetime([e['time'] for e in alged_events], utc=True)
    ev_deficits = [e['deficit_ratio'] * 100 for e in alged_events]
else:
    ev_times, ev_deficits = [], []

# Farben
C_CYAN   = '#58a6ff'
C_ORANGE = '#f78166'
C_GREEN  = '#3fb950'
C_YELLOW = '#d29922'
C_RED    = '#ff7b72'
C_BG     = '#0d1117'
C_PLOT   = '#161b22'
C_GRID   = '#21262d'
C_TEXT   = '#e6edf3'
C_MUTED  = '#8b949e'

# ─── Layout-Vorlage ───────────────────────────────────────────────────────────
LAYOUT_BASE = dict(
    paper_bgcolor=C_BG,
    plot_bgcolor=C_PLOT,
    font=dict(family='system-ui, -apple-system, sans-serif', color=C_TEXT, size=12),
    xaxis=dict(gridcolor=C_GRID, zerolinecolor=C_GRID, tickfont=dict(color=C_MUTED)),
    yaxis=dict(gridcolor=C_GRID, zerolinecolor=C_GRID, tickfont=dict(color=C_MUTED)),
    legend=dict(bgcolor='rgba(22,27,34,0.9)', bordercolor=C_GRID, borderwidth=1),
    margin=dict(l=60, r=20, t=50, b=50),
    hovermode='x unified',
)

# ══════════════════════════════════════════════════════════════════════════════
# Krisenband-Shapes
# ══════════════════════════════════════════════════════════════════════════════
def crisis_shapes(df_ref):
    shapes = []
    in_crisis = False
    start = None
    for t, c in zip(df_ref.index, df_ref['is_crisis']):
        if c and not in_crisis:
            in_crisis = True
            start = t
        elif not c and in_crisis:
            in_crisis = False
            shapes.append(dict(
                type='rect', xref='x', yref='paper',
                x0=str(start), x1=str(t),
                y0=0, y1=1,
                fillcolor='rgba(255,123,114,0.08)',
                line=dict(width=0),
                layer='below'
            ))
    if in_crisis:
        shapes.append(dict(
            type='rect', xref='x', yref='paper',
            x0=str(start), x1=str(df_ref.index[-1]),
            y0=0, y1=1,
            fillcolor='rgba(255,123,114,0.08)',
            line=dict(width=0),
            layer='below'
        ))
    return shapes


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1: Übersicht
# ══════════════════════════════════════════════════════════════════════════════

fig1 = make_subplots(
    rows=2, cols=2,
    subplot_titles=[
        'Wöchentliche Versorgungsrate (%)',
        'Kumulatives Versorgungsdefizit (GWh)',
        'Speicherfüllstand (GWh)',
        'Stündliche Versorgungsvolatilität (7-Tage-Std, %)',
    ],
    vertical_spacing=0.12,
    horizontal_spacing=0.08,
)

# Versorgungsrate
fig1.add_trace(go.Scatter(
    x=df_w.index, y=df_w['cs_supply_rate'] * 100,
    name='Cybersyn', line=dict(color=C_CYAN, width=2),
    hovertemplate='%{y:.2f}%<extra>Cybersyn</extra>'
), row=1, col=1)
fig1.add_trace(go.Scatter(
    x=df_w.index, y=df_w['mk_supply_rate'] * 100,
    name='Markt', line=dict(color=C_ORANGE, width=2, dash='dash'),
    hovertemplate='%{y:.2f}%<extra>Markt</extra>'
), row=1, col=1)
fig1.add_hline(y=100, line=dict(color=C_GRID, dash='dot', width=1), row=1, col=1)

# Kumulatives Defizit
fig1.add_trace(go.Scatter(
    x=df.index, y=mk_cum,
    name='Markt kum.', line=dict(color=C_ORANGE, width=1.5),
    fill='tozeroy', fillcolor='rgba(247,129,102,0.15)',
    hovertemplate='%{y:.0f} GWh<extra>Markt kumulativ</extra>'
), row=1, col=2)
fig1.add_trace(go.Scatter(
    x=df.index, y=cs_cum,
    name='Cybersyn kum.', line=dict(color=C_CYAN, width=1.5),
    fill='tozeroy', fillcolor='rgba(88,166,255,0.15)',
    hovertemplate='%{y:.0f} GWh<extra>Cybersyn kumulativ</extra>'
), row=1, col=2)

# Speicher
fig1.add_trace(go.Scatter(
    x=df_w.index, y=df_w['cs_storage'],
    name='Cybersyn Speicher', line=dict(color=C_CYAN, width=1.5),
    fill='tozeroy', fillcolor='rgba(88,166,255,0.1)',
    hovertemplate='%{y:.0f} GWh<extra>Cybersyn Speicher</extra>'
), row=2, col=1)
fig1.add_trace(go.Scatter(
    x=df_w.index, y=df_w['mk_storage'],
    name='Markt Speicher', line=dict(color=C_ORANGE, width=1.5, dash='dash'),
    hovertemplate='%{y:.0f} GWh<extra>Markt Speicher</extra>'
), row=2, col=1)
fig1.add_hline(y=965, line=dict(color=C_MUTED, dash='dot', width=1), row=2, col=1)

# Volatilität
cs_vol = pd.Series(df['cs_supply_rate'].values).rolling(168).std() * 100
mk_vol = pd.Series(df['mk_supply_rate'].values).rolling(168).std() * 100
fig1.add_trace(go.Scatter(
    x=df.index, y=cs_vol.values,
    name='Cybersyn Volatilität', line=dict(color=C_CYAN, width=1),
    hovertemplate='%{y:.3f}%<extra>Cybersyn Volatilität</extra>'
), row=2, col=2)
fig1.add_trace(go.Scatter(
    x=df.index, y=mk_vol.values,
    name='Markt Volatilität', line=dict(color=C_ORANGE, width=1, dash='dash'),
    hovertemplate='%{y:.3f}%<extra>Markt Volatilität</extra>'
), row=2, col=2)

fig1.update_layout(
    **LAYOUT_BASE,
    title=dict(
        text='Cybersyn 2.0 – Stufe 2: Übersicht 2022–2023',
        font=dict(size=16, color=C_TEXT), x=0.5
    ),
    height=700,
    showlegend=True,
    shapes=crisis_shapes(df),
)
for ax in ['xaxis', 'xaxis2', 'xaxis3', 'xaxis4']:
    fig1.update_layout(**{ax: dict(gridcolor=C_GRID, tickfont=dict(color=C_MUTED))})
for ax in ['yaxis', 'yaxis2', 'yaxis3', 'yaxis4']:
    fig1.update_layout(**{ax: dict(gridcolor=C_GRID, tickfont=dict(color=C_MUTED))})


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2: Winter-Krise Detail
# ══════════════════════════════════════════════════════════════════════════════

mask_w = (
    (df.index >= pd.Timestamp('2022-12-01', tz='UTC')) &
    (df.index <= pd.Timestamp('2023-02-28', tz='UTC'))
)
df_w2 = df[mask_w].copy()

fig2 = make_subplots(
    rows=3, cols=1,
    subplot_titles=[
        'Stündliche Versorgungsrate (%) – Algedonic aktiv = rot markiert',
        'Speicherfüllstand (GWh)',
        'Stündliches Versorgungsdefizit (GWh/h)',
    ],
    vertical_spacing=0.10,
    shared_xaxes=True,
)

# Algedonic-Bereiche
alged_shapes = []
in_alged = False
alged_start = None
for t, a in zip(df_w2.index, df_w2['cs_algedonic']):
    if a and not in_alged:
        in_alged = True
        alged_start = t
    elif not a and in_alged:
        in_alged = False
        alged_shapes.append(dict(
            type='rect', xref='x', yref='paper',
            x0=str(alged_start), x1=str(t),
            y0=0, y1=1,
            fillcolor='rgba(255,123,114,0.15)',
            line=dict(width=0), layer='below'
        ))

fig2.add_trace(go.Scatter(
    x=df_w2.index, y=df_w2['cs_supply_rate'] * 100,
    name='Cybersyn', line=dict(color=C_CYAN, width=1),
    hovertemplate='%{y:.1f}%<extra>Cybersyn</extra>'
), row=1, col=1)
fig2.add_trace(go.Scatter(
    x=df_w2.index, y=df_w2['mk_supply_rate'] * 100,
    name='Markt', line=dict(color=C_ORANGE, width=1, dash='dash'),
    hovertemplate='%{y:.1f}%<extra>Markt</extra>'
), row=1, col=1)

fig2.add_trace(go.Scatter(
    x=df_w2.index, y=df_w2['cs_storage'],
    name='Cybersyn Speicher', line=dict(color=C_CYAN, width=1.2),
    fill='tozeroy', fillcolor='rgba(88,166,255,0.1)',
), row=2, col=1)
fig2.add_trace(go.Scatter(
    x=df_w2.index, y=df_w2['mk_storage'],
    name='Markt Speicher', line=dict(color=C_ORANGE, width=1.2, dash='dash'),
), row=2, col=1)

fig2.add_trace(go.Bar(
    x=df_w2.index, y=df_w2['cs_deficit'],
    name='Cybersyn Defizit', marker_color=C_CYAN, opacity=0.7,
), row=3, col=1)
fig2.add_trace(go.Bar(
    x=df_w2.index, y=df_w2['mk_deficit'],
    name='Markt Defizit', marker_color=C_ORANGE, opacity=0.5,
), row=3, col=1)

fig2.update_layout(
    **LAYOUT_BASE,
    title=dict(
        text='Winter-Energiekrise 2022/23 – Stündliche Auflösung<br>'
             '<sub>Hamburg | Import-Kapazität: 0.4 GWh/h | Rot = Algedonic aktiv</sub>',
        font=dict(size=15, color=C_TEXT), x=0.5
    ),
    height=750,
    shapes=alged_shapes,
    barmode='overlay',
)
for ax in ['xaxis', 'xaxis2', 'xaxis3']:
    fig2.update_layout(**{ax: dict(gridcolor=C_GRID, tickfont=dict(color=C_MUTED))})
for ax in ['yaxis', 'yaxis2', 'yaxis3']:
    fig2.update_layout(**{ax: dict(gridcolor=C_GRID, tickfont=dict(color=C_MUTED))})


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3: Metriken-Vergleich
# ══════════════════════════════════════════════════════════════════════════════

fig3 = make_subplots(
    rows=2, cols=3,
    subplot_titles=[
        'Versorgungsrate (%)',
        'Gesamtdefizit (GWh)',
        'RMSE (GWh)',
        'Volatilität (%)',
        'Winter-Versorgungsrate (%)',
        'Netzimport gesamt (GWh)',
    ],
    vertical_spacing=0.18,
    horizontal_spacing=0.1,
)

metrics_data = [
    (cs_m['versorgungsrate'],         mk_m['versorgungsrate'],         1, 1),
    (cs_m['gesamtdefizit'],           mk_m['gesamtdefizit'],           1, 2),
    (cs_m['rmse'],                    mk_m['rmse'],                    1, 3),
    (cs_m['volatilitaet'],            mk_m['volatilitaet'],            2, 1),
    (m['winter_cybersyn']['versorgungsrate'], m['winter_markt']['versorgungsrate'], 2, 2),
    (cs_m['total_import'],            mk_m['total_import'],            2, 3),
]

for cs_val, mk_val, row, col in metrics_data:
    fig3.add_trace(go.Bar(
        x=['Cybersyn', 'Markt'],
        y=[cs_val, mk_val],
        marker_color=[C_CYAN, C_ORANGE],
        text=[f'{cs_val:.2f}', f'{mk_val:.2f}'],
        textposition='outside',
        showlegend=False,
    ), row=row, col=col)

fig3.update_layout(
    **LAYOUT_BASE,
    title=dict(
        text='Cybersyn vs. Markt – Metriken-Vergleich',
        font=dict(size=16, color=C_TEXT), x=0.5
    ),
    height=600,
)
for i in range(1, 7):
    ax = f'yaxis{i}' if i > 1 else 'yaxis'
    xax = f'xaxis{i}' if i > 1 else 'xaxis'
    fig3.update_layout(**{
        ax:  dict(gridcolor=C_GRID, tickfont=dict(color=C_MUTED)),
        xax: dict(gridcolor=C_GRID, tickfont=dict(color=C_MUTED)),
    })


# ══════════════════════════════════════════════════════════════════════════════
# TAB 4: Algedonic Channel
# ══════════════════════════════════════════════════════════════════════════════

fig4 = make_subplots(
    rows=1, cols=2,
    subplot_titles=[
        f'Algedonic-Ereignisse über Zeit (n={len(alged_events)})',
        'Monatliche Häufigkeit der Algedonic-Aktivierungen',
    ],
    horizontal_spacing=0.1,
)

if ev_times is not None and len(ev_times) > 0:
    fig4.add_trace(go.Scatter(
        x=list(ev_times),
        y=ev_deficits,
        mode='markers',
        marker=dict(color=C_RED, size=6, opacity=0.7),
        name='Algedonic-Ereignis',
        hovertemplate='%{x|%d.%m.%Y %H:%M}<br>Defizit: %{y:.1f}%<extra></extra>'
    ), row=1, col=1)
    fig4.add_hline(y=10, line=dict(color=C_YELLOW, dash='dash', width=1),
                   annotation_text='Schwelle 10%', row=1, col=1)

    # Monatliche Häufigkeit
    ev_df = pd.DataFrame({'time': ev_times, 'deficit': ev_deficits})
    ev_df['month'] = ev_df['time'].dt.to_period('M').astype(str)
    monthly = ev_df.groupby('month').size().reset_index(name='count')
    fig4.add_trace(go.Bar(
        x=monthly['month'],
        y=monthly['count'],
        marker_color=C_RED,
        opacity=0.8,
        name='Ereignisse/Monat',
        hovertemplate='%{x}: %{y} Ereignisse<extra></extra>'
    ), row=1, col=2)

fig4.update_layout(
    **LAYOUT_BASE,
    title=dict(
        text='Algedonic Channel – Notfallprotokoll nach Stafford Beer (1972)',
        font=dict(size=15, color=C_TEXT), x=0.5
    ),
    height=450,
)
for ax in ['xaxis', 'xaxis2', 'yaxis', 'yaxis2']:
    fig4.update_layout(**{ax: dict(gridcolor=C_GRID, tickfont=dict(color=C_MUTED))})


# ══════════════════════════════════════════════════════════════════════════════
# HTML zusammenbauen
# ══════════════════════════════════════════════════════════════════════════════

html_tab1 = pio.to_html(fig1, include_plotlyjs=False, full_html=False, div_id='tab1')
html_tab2 = pio.to_html(fig2, include_plotlyjs=False, full_html=False, div_id='tab2')
html_tab3 = pio.to_html(fig3, include_plotlyjs=False, full_html=False, div_id='tab3')
html_tab4 = pio.to_html(fig4, include_plotlyjs=False, full_html=False, div_id='tab4')

# Metriken-Karten
def delta_badge(cs_val, mk_val, higher_is_better=True, fmt='.2f'):
    delta = cs_val - mk_val
    pct   = (delta / abs(mk_val) * 100) if mk_val != 0 else 0
    good  = (delta > 0) == higher_is_better
    color = '#3fb950' if good else '#f78166'
    sign  = '+' if delta >= 0 else ''
    return f'<span style="color:{color};font-weight:600">{sign}{delta:{fmt}} ({sign}{pct:.1f}%)</span>'

html = f"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Cybersyn 2.0 – Stufe 2 Dashboard</title>
<script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
<style>
  :root {{
    --bg: #0d1117; --surface: #161b22; --border: #30363d;
    --text: #e6edf3; --muted: #8b949e;
    --cyan: #58a6ff; --orange: #f78166; --green: #3fb950;
    --yellow: #d29922; --red: #ff7b72;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: var(--bg); color: var(--text); font-family: system-ui,-apple-system,sans-serif; }}
  header {{
    background: var(--surface); border-bottom: 1px solid var(--border);
    padding: 20px 32px; display: flex; align-items: center; gap: 16px;
  }}
  header h1 {{ font-size: 1.4rem; font-weight: 700; color: var(--cyan); }}
  header p  {{ font-size: 0.85rem; color: var(--muted); margin-top: 4px; }}
  .badge {{
    background: rgba(88,166,255,0.1); border: 1px solid var(--cyan);
    color: var(--cyan); padding: 4px 10px; border-radius: 20px; font-size: 0.75rem;
  }}
  .metrics-grid {{
    display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
    gap: 16px; padding: 24px 32px;
  }}
  .metric-card {{
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 8px; padding: 16px;
  }}
  .metric-card .label {{ font-size: 0.78rem; color: var(--muted); margin-bottom: 8px; }}
  .metric-card .values {{ display: flex; gap: 16px; align-items: baseline; }}
  .metric-card .cs-val {{ font-size: 1.5rem; font-weight: 700; color: var(--cyan); }}
  .metric-card .mk-val {{ font-size: 1.0rem; color: var(--orange); }}
  .metric-card .delta  {{ font-size: 0.82rem; margin-top: 6px; }}
  .tabs {{
    display: flex; gap: 0; border-bottom: 1px solid var(--border);
    padding: 0 32px; background: var(--surface);
  }}
  .tab-btn {{
    padding: 12px 20px; background: none; border: none; color: var(--muted);
    cursor: pointer; font-size: 0.9rem; border-bottom: 2px solid transparent;
    transition: all 0.2s;
  }}
  .tab-btn:hover  {{ color: var(--text); }}
  .tab-btn.active {{ color: var(--cyan); border-bottom-color: var(--cyan); }}
  .tab-content {{ display: none; padding: 24px 32px; }}
  .tab-content.active {{ display: block; }}
  .info-box {{
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 8px; padding: 16px 20px; margin-bottom: 20px;
    font-size: 0.85rem; line-height: 1.6; color: var(--muted);
  }}
  .info-box strong {{ color: var(--text); }}
  .info-box .highlight {{ color: var(--cyan); font-weight: 600; }}
  .info-box .warning  {{ color: var(--yellow); font-weight: 600; }}
  footer {{
    border-top: 1px solid var(--border); padding: 16px 32px;
    font-size: 0.78rem; color: var(--muted); text-align: center;
  }}
</style>
</head>
<body>

<header>
  <div>
    <h1>Cybersyn 2.0 – Stufe 2</h1>
    <p>Hamburg Stromversorgung | Stündliche Regelschleife | SMARD-Daten 2022–2023</p>
  </div>
  <span class="badge">PI-Regler + Algedonic Channel</span>
  <span class="badge">17.473 Stunden</span>
  <span class="badge">Eigenversorgung: {m['eigenversorgungsgrad_2022']:.1f}%</span>
</header>

<div class="metrics-grid">
  <div class="metric-card">
    <div class="label">Versorgungsrate (gesamt)</div>
    <div class="values">
      <span class="cs-val">{cs_m['versorgungsrate']:.2f}%</span>
      <span class="mk-val">{mk_m['versorgungsrate']:.2f}%</span>
    </div>
    <div class="delta">{delta_badge(cs_m['versorgungsrate'], mk_m['versorgungsrate'], True)}</div>
  </div>
  <div class="metric-card">
    <div class="label">Gesamtdefizit (GWh)</div>
    <div class="values">
      <span class="cs-val">{cs_m['gesamtdefizit']:.0f}</span>
      <span class="mk-val">{mk_m['gesamtdefizit']:.0f}</span>
    </div>
    <div class="delta">{delta_badge(cs_m['gesamtdefizit'], mk_m['gesamtdefizit'], False, '.0f')}</div>
  </div>
  <div class="metric-card">
    <div class="label">RMSE (GWh)</div>
    <div class="values">
      <span class="cs-val">{cs_m['rmse']:.4f}</span>
      <span class="mk-val">{mk_m['rmse']:.4f}</span>
    </div>
    <div class="delta">{delta_badge(cs_m['rmse'], mk_m['rmse'], False, '.4f')}</div>
  </div>
  <div class="metric-card">
    <div class="label">Volatilität (%)</div>
    <div class="values">
      <span class="cs-val">{cs_m['volatilitaet']:.2f}%</span>
      <span class="mk-val">{mk_m['volatilitaet']:.2f}%</span>
    </div>
    <div class="delta">{delta_badge(cs_m['volatilitaet'], mk_m['volatilitaet'], False)}</div>
  </div>
  <div class="metric-card">
    <div class="label">Winter-Versorgungsrate (Nov–Feb)</div>
    <div class="values">
      <span class="cs-val">{m['winter_cybersyn']['versorgungsrate']:.2f}%</span>
      <span class="mk-val">{m['winter_markt']['versorgungsrate']:.2f}%</span>
    </div>
    <div class="delta">{delta_badge(m['winter_cybersyn']['versorgungsrate'], m['winter_markt']['versorgungsrate'], True)}</div>
  </div>
  <div class="metric-card">
    <div class="label">Algedonic-Ereignisse</div>
    <div class="values">
      <span class="cs-val">{m['algedonic_events']}</span>
      <span class="mk-val" style="color:var(--muted)">n/a</span>
    </div>
    <div class="delta" style="color:var(--muted);font-size:0.78rem">Notfallprotokoll-Aktivierungen</div>
  </div>
</div>

<div class="tabs">
  <button class="tab-btn active" onclick="showTab('overview', this)">Übersicht</button>
  <button class="tab-btn" onclick="showTab('winter', this)">Winter-Krise</button>
  <button class="tab-btn" onclick="showTab('metrics', this)">Metriken</button>
  <button class="tab-btn" onclick="showTab('algedonic', this)">Algedonic Channel</button>
</div>

<div id="overview" class="tab-content active">
  <div class="info-box">
    <strong>Modell:</strong> Hamburg 2022–2023 | Eigenversorgungsgrad: <span class="highlight">{m['eigenversorgungsgrad_2022']:.1f}%</span> |
    Netzimport: <span class="highlight">1.0 GWh/h</span> normal, <span class="warning">0.4 GWh/h</span> in Krisenmonate (Nov–Feb) |
    Speicher: <span class="highlight">965 GWh</span>, max. Rate 96.5 GWh/h.
    Rote Bereiche = Krisenmonate.
  </div>
  {html_tab1}
</div>

<div id="winter" class="tab-content">
  <div class="info-box">
    <strong>Winter-Energiekrise 2022/23:</strong> Import auf <span class="warning">0.4 GWh/h</span> reduziert (–60% gegenüber Normal).
    Cybersyn-Defizit: <span class="highlight">{m['winter_cybersyn']['gesamtdefizit']:.0f} GWh</span> |
    Markt-Defizit: <span style="color:var(--orange);font-weight:600">{m['winter_markt']['gesamtdefizit']:.0f} GWh</span> |
    Faktor: <span class="highlight">{m['winter_markt']['gesamtdefizit']/max(m['winter_cybersyn']['gesamtdefizit'],0.1):.1f}×</span> weniger Defizit mit Cybersyn.
    Rote Bereiche = Algedonic Channel aktiv.
  </div>
  {html_tab2}
</div>

<div id="metrics" class="tab-content">
  <div class="info-box">
    <strong>Vergleich:</strong> Cybersyn (blau) vs. Markt (orange) über alle Metriken.
    Cybersyn-Gesamtdefizit ist <span class="highlight">{mk_m['gesamtdefizit']/max(cs_m['gesamtdefizit'],0.1):.1f}×</span> kleiner als Markt-Defizit.
    Netzimport: Cybersyn nutzt <span class="highlight">{cs_m['total_import']:.0f} GWh</span> vs. Markt <span style="color:var(--orange)">{mk_m['total_import']:.0f} GWh</span>
    (Cybersyn importiert effizienter).
  </div>
  {html_tab3}
</div>

<div id="algedonic" class="tab-content">
  <div class="info-box">
    <strong>Algedonic Channel</strong> (Stafford Beer, "Brain of the Firm", 1972):
    Aktivierung wenn Defizit &gt; <span class="warning">10%</span> für ≥ 3 aufeinanderfolgende Stunden.
    Lastabwurf-Reihenfolge: Industrie (35%) → KMU (25%) → Haushalte (30%) → Kritische Infrastruktur (10%, nie abgeworfen).
    Gesamt-Aktivierungen 2022–2023: <span class="highlight">{m['algedonic_events']}</span>.
  </div>
  {html_tab4}
</div>

<footer>
  Cybersyn 2.0 – Stufe 2 | Datenquelle: SMARD API (Bundesnetzagentur) + Eurostat nrg_bal_c |
  Modell: Stafford Beer, "Brain of the Firm" (1972) | Hamburg-Skalierung: 2.6% des deutschen Verbrauchs
</footer>

<script>
function showTab(id, btn) {{
  document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
  document.getElementById(id).classList.add('active');
  btn.classList.add('active');
}}
</script>
</body>
</html>"""

with open('dashboard_stufe2.html', 'w', encoding='utf-8') as f:
    f.write(html)

print("  Gespeichert: dashboard_stufe2.html")
print(f"  Dateigröße: {len(html)/1024:.0f} KB")
