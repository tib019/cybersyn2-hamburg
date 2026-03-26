"""
Cybersyn 2.0 – Hamburg Stromversorgung
Kybernetische Regelschleife: Produktion → Verteilung → Verbrauch → Feedback → Anpassung
Datenquelle: Eurostat nrg_bal_c (Deutschland, E7000 = Strom, GWh, jährlich)
Hamburg-Anteil: ~2.6% des deutschen Stromverbrauchs (Bevölkerungsanteil + Industriestruktur)

Modellarchitektur (Kybernetik nach Stafford Beer / Viable System Model):
  - Regler (Algedonic Channel): Vergleicht Ist-Kapazität mit Soll-Bedarf
  - Stellgröße: Kapazitätsanpassung (Speicher, Laststeuerung, Einspeiseregelung)
  - Feedback-Schleife: Abweichung → Korrekturimpuls → neue Produktionsplanung
  - Kein Preismechanismus: nur physikalische Größen (GWh)
"""

import json
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.gridspec import GridSpec
import requests
import os

# ─────────────────────────────────────────────────────────────────────────────
# 1. DATEN LADEN (Eurostat)
# ─────────────────────────────────────────────────────────────────────────────

def load_eurostat_electricity(cache_file='eurostat_elec_DE.json'):
    """Lädt Eurostat-Energiebilanzdaten für Deutschland (E7000 = Strom)."""
    if not os.path.exists(cache_file):
        url = ("https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/"
               "nrg_bal_c?format=JSON&geo=DE&siec=E7000&unit=GWH&freq=A&lang=en")
        r = requests.get(url, timeout=30)
        with open(cache_file, 'w') as f:
            f.write(r.text)

    with open(cache_file) as f:
        d = json.load(f)

    nrg_idx   = d['dimension']['nrg_bal']['category']['index']
    time_idx  = d['dimension']['time']['category']['index']
    values    = d['value']
    nrg_codes = {v: k for k, v in nrg_idx.items()}
    time_codes= {v: k for k, v in time_idx.items()}
    n_time    = len(time_idx)
    n_nrg     = len(nrg_idx)

    rows = []
    for idx_str, val in values.items():
        idx    = int(idx_str)
        t_i    = idx % n_time
        nrg_i  = idx // n_time
        rows.append({
            'nrg_bal': nrg_codes.get(nrg_i, '?'),
            'year':    int(time_codes.get(t_i, 0)),
            'GWh':     float(val) if val is not None else np.nan
        })

    df = pd.DataFrame(rows)
    return df


def build_germany_timeseries(df):
    """Erstellt eine saubere Zeitreihe für Deutschland: Erzeugung, Verbrauch, Import, Export."""
    pivot = df.pivot_table(index='year', columns='nrg_bal', values='GWh', aggfunc='first')

    ts = pd.DataFrame(index=pivot.index)
    # Brutto-Stromerzeugung (Transformation Output Electricity & Heat Generation)
    ts['production_GWh']    = pivot.get('TO_EHG', np.nan)
    # Verfügbar für Endverbrauch
    ts['available_GWh']     = pivot.get('AFC', np.nan)
    # Importe / Exporte
    ts['imports_GWh']       = pivot.get('IMP', np.nan)
    ts['exports_GWh']       = pivot.get('EXP', np.nan)
    # Haushaltsverbrauch
    ts['household_GWh']     = pivot.get('FC_OTH_HH_E', np.nan)
    # Industrieverbrauch
    ts['industry_GWh']      = pivot.get('FC_IND_E', np.nan)

    # Netto-Inlandsverbrauch = Erzeugung + Import - Export
    ts['net_consumption_GWh'] = ts['production_GWh'] + ts['imports_GWh'] - ts['exports_GWh']

    ts = ts.dropna(subset=['production_GWh', 'available_GWh'])
    return ts.sort_index()


def scale_to_hamburg(ts_de, hh_share=0.026):
    """
    Skaliert Deutschland-Daten auf Hamburg.
    Hamburg-Anteil: ~2.6% (Bevölkerung 1.85M / 83M = 2.23%; 
    Korrektur nach oben wegen Industriedichte +0.37% → 2.6%)
    Quelle: Statistisches Amt für Hamburg und Schleswig-Holstein,
            Eurostat regional energy data (nuts2: DE60)
    """
    ts_hh = ts_de.copy() * hh_share
    ts_hh.index = ts_de.index
    return ts_hh


# ─────────────────────────────────────────────────────────────────────────────
# 2. KYBERNETISCHES REGELSCHLEIFENMODELL
# ─────────────────────────────────────────────────────────────────────────────

class CybersynController:
    """
    Kybernetischer Regler nach dem Viable System Model (VSM) von Stafford Beer.
    
    Regelschleife:
      Produktion (P) → Verteilung (V) → Verbrauch (C) → Feedback (e) → Anpassung (ΔP)
    
    Regler-Logik (Proportional-Integral = PI-Regler):
      e(t)  = C(t) - P(t)          # Abweichung: Bedarf minus Kapazität
      ΔP(t) = Kp * e(t) + Ki * ∫e  # Korrekturimpuls
      P(t+1)= P(t) + ΔP(t)         # Neue Produktionsplanung
    
    Kein Preissignal. Nur physikalische Bilanz.
    """

    def __init__(self, Kp=0.6, Ki=0.15, storage_capacity_frac=0.08):
        self.Kp = Kp                              # Proportionalverstärkung
        self.Ki = Ki                              # Integralverstärkung
        self.storage_cap_frac = storage_capacity_frac  # Speicher als Anteil des Jahresbedarfs
        self.integral_error = 0.0
        self.storage_level  = 0.0                # aktueller Speicherstand (GWh)

    def reset(self):
        self.integral_error = 0.0
        self.storage_level  = 0.0

    def step(self, demand, planned_production, storage_max):
        """
        Führt einen Regelschritt durch.
        
        Parameter:
          demand             – tatsächlicher Verbrauch (GWh)
          planned_production – geplante Erzeugung (GWh)
          storage_max        – maximale Speicherkapazität (GWh)
        
        Rückgabe:
          actual_supply      – tatsächlich gelieferter Strom (GWh)
          new_plan           – neue Produktionsplanung für nächste Periode
          storage_level      – Speicherstand nach diesem Schritt
          error              – Abweichung (GWh)
          curtailment        – abgeregelter Überschuss (GWh)
          deficit            – nicht gedeckter Bedarf (GWh)
        """
        # Schritt 1: Produktion trifft auf Bedarf
        surplus = planned_production - demand

        curtailment = 0.0
        deficit     = 0.0

        if surplus >= 0:
            # Überschuss: erst Speicher laden
            charge = min(surplus, storage_max - self.storage_level)
            self.storage_level += charge
            curtailment = surplus - charge          # nicht speicherbarer Rest
            actual_supply = demand
        else:
            # Defizit: erst Speicher entladen
            discharge = min(-surplus, self.storage_level)
            self.storage_level -= discharge
            deficit = -surplus - discharge          # nicht gedeckter Rest
            actual_supply = demand - deficit

        # Schritt 2: Feedback – Fehler berechnen
        error = demand - planned_production         # positiv = Unterversorgung
        self.integral_error += error

        # Schritt 3: PI-Regler → neue Produktionsplanung
        correction = self.Kp * error + self.Ki * self.integral_error
        new_plan   = planned_production + correction

        # Produktionsplanung darf nicht negativ werden
        new_plan = max(new_plan, 0.0)

        return {
            'actual_supply':  actual_supply,
            'new_plan':       new_plan,
            'storage_level':  self.storage_level,
            'error':          error,
            'curtailment':    curtailment,
            'deficit':        deficit,
        }


class MarketController:
    """
    Marktmechanismus als Vergleichsmodell.
    
    Logik: Produktion folgt dem Preis. Bei Unterversorgung steigt der Preis,
    bei Überversorgung fällt er. Die Anpassung ist träger und reagiert auf
    Preissignale statt auf physikalischen Bedarf.
    
    Vereinfachtes Modell: Preiselastizität der Angebotsmenge.
    """

    def __init__(self, price_elasticity=0.4, reaction_lag=2):
        self.elasticity  = price_elasticity
        self.lag         = reaction_lag          # Jahre Reaktionsverzögerung
        self.price       = 50.0                  # €/MWh Startpreis
        self.backlog     = []                    # Produktionspläne in der Pipeline

    def reset(self):
        self.price   = 50.0
        self.backlog = []

    def step(self, demand, planned_production, storage_max):
        """Marktschritt: Preis → Produktionsanpassung mit Verzögerung."""
        # Preisbildung: Angebot-Nachfrage-Verhältnis
        ratio = planned_production / max(demand, 1)
        if ratio < 0.95:
            self.price *= (1 + (1 - ratio) * 0.3)   # Preis steigt bei Knappheit
        elif ratio > 1.05:
            self.price *= (1 - (ratio - 1) * 0.2)   # Preis fällt bei Überschuss
        self.price = max(10.0, min(self.price, 500.0))

        # Produktionsanpassung mit Verzögerung
        target = demand * (1 + self.elasticity * (self.price - 50) / 50)
        self.backlog.append(target)

        if len(self.backlog) > self.lag:
            new_plan = self.backlog.pop(0)
        else:
            new_plan = planned_production

        # Einfache Bilanz (kein Speicher im Marktmodell – Speicher ist Ware)
        surplus = new_plan - demand
        deficit     = max(0, -surplus)
        curtailment = max(0, surplus)
        actual_supply = demand - deficit

        error = demand - planned_production

        return {
            'actual_supply':  actual_supply,
            'new_plan':       new_plan,
            'storage_level':  0.0,
            'error':          error,
            'curtailment':    curtailment,
            'deficit':        deficit,
            'price':          self.price,
        }


# ─────────────────────────────────────────────────────────────────────────────
# 3. SIMULATION
# ─────────────────────────────────────────────────────────────────────────────

def run_simulation(ts_hamburg, controller, initial_plan_offset=0.0):
    """
    Führt die Simulation über alle Jahre durch.
    
    ts_hamburg: DataFrame mit Hamburg-Daten (GWh)
    controller: CybersynController oder MarketController
    initial_plan_offset: Startwert-Abweichung vom Bedarf (Stress-Test)
    """
    controller.reset()
    years   = ts_hamburg.index.tolist()
    results = []

    # Startplanung: Bedarf + Offset (simuliert schlechte Anfangsplanung)
    demand_0    = ts_hamburg['available_GWh'].iloc[0]
    planned     = demand_0 * (1 + initial_plan_offset)
    storage_max = demand_0 * controller.storage_cap_frac if hasattr(controller, 'storage_cap_frac') else 0

    for year in years:
        demand = ts_hamburg.loc[year, 'available_GWh']

        # Realistisches Nachfragewachstum: leichte jährliche Schwankung ±3%
        np.random.seed(year)  # reproduzierbar
        demand_actual = demand * (1 + np.random.uniform(-0.03, 0.03))

        result = controller.step(demand_actual, planned, storage_max)
        result['year']   = year
        result['demand'] = demand_actual
        result['planned']= planned
        results.append(result)

        planned = result['new_plan']

    return pd.DataFrame(results).set_index('year')


# ─────────────────────────────────────────────────────────────────────────────
# 4. METRIKEN
# ─────────────────────────────────────────────────────────────────────────────

def compute_metrics(sim_df):
    """Berechnet Stabilitäts- und Effizienzmetriken."""
    total_demand   = sim_df['demand'].sum()
    total_deficit  = sim_df['deficit'].sum()
    total_curtail  = sim_df['curtailment'].sum()
    supply_rate    = (total_demand - total_deficit) / total_demand * 100
    waste_rate     = total_curtail / total_demand * 100
    rmse_error     = np.sqrt((sim_df['error']**2).mean())
    max_deficit    = sim_df['deficit'].max()
    convergence_yr = None

    # Konvergenzjahr: ab wann bleibt |error| < 2% des Bedarfs dauerhaft
    threshold = sim_df['demand'].mean() * 0.02
    stable_mask = (sim_df['error'].abs() < threshold)
    # Finde erstes Fenster von 5 aufeinanderfolgenden stabilen Jahren
    for i in range(len(stable_mask) - 4):
        if stable_mask.iloc[i:i+5].all():
            convergence_yr = sim_df.index[i]
            break

    return {
        'supply_rate_%':    round(supply_rate, 2),
        'waste_rate_%':     round(waste_rate, 2),
        'rmse_GWh':         round(rmse_error, 1),
        'max_deficit_GWh':  round(max_deficit, 1),
        'convergence_year': convergence_yr,
        'total_deficit_GWh':round(total_deficit, 1),
        'total_curtail_GWh':round(total_curtail, 1),
    }


# ─────────────────────────────────────────────────────────────────────────────
# 5. VISUALISIERUNG
# ─────────────────────────────────────────────────────────────────────────────

def plot_results(ts_hamburg, sim_cyber, sim_market, metrics_cyber, metrics_market,
                 output_file='cybersyn_hamburg_results.png'):
    """Erstellt eine umfassende Visualisierung der Simulationsergebnisse."""

    plt.rcParams.update({
        'font.family': 'DejaVu Sans',
        'font.size': 11,
        'axes.titlesize': 13,
        'axes.labelsize': 11,
        'figure.facecolor': '#0d1117',
        'axes.facecolor': '#161b22',
        'axes.edgecolor': '#30363d',
        'axes.labelcolor': '#e6edf3',
        'xtick.color': '#8b949e',
        'ytick.color': '#8b949e',
        'text.color': '#e6edf3',
        'grid.color': '#21262d',
        'grid.linewidth': 0.8,
        'legend.facecolor': '#161b22',
        'legend.edgecolor': '#30363d',
    })

    CYBER_COLOR  = '#58a6ff'   # Blau – kybernetisch
    MARKET_COLOR = '#f78166'   # Rot/Orange – Markt
    DEMAND_COLOR = '#3fb950'   # Grün – Bedarf
    STORAGE_COLOR= '#d2a8ff'   # Lila – Speicher
    ERROR_COLOR  = '#ffa657'   # Orange – Fehler

    fig = plt.figure(figsize=(18, 14))
    fig.suptitle('Cybersyn 2.0 – Hamburg Stromsystem\nKybernetische Regelschleife vs. Marktmechanismus',
                 fontsize=16, fontweight='bold', y=0.98, color='#e6edf3')

    gs = GridSpec(3, 3, figure=fig, hspace=0.45, wspace=0.35,
                  top=0.93, bottom=0.07, left=0.07, right=0.97)

    years = sim_cyber.index

    # ── Panel 1: Bedarf vs. Planung (Cybersyn) ────────────────────────────
    ax1 = fig.add_subplot(gs[0, :2])
    ax1.fill_between(years, sim_cyber['demand'], alpha=0.15, color=DEMAND_COLOR)
    ax1.plot(years, sim_cyber['demand'],  color=DEMAND_COLOR,  lw=2,   label='Tatsächlicher Bedarf')
    ax1.plot(years, sim_cyber['planned'], color=CYBER_COLOR,   lw=2,   label='Kybernetische Planung', ls='--')
    ax1.plot(years, sim_market['planned'],color=MARKET_COLOR,  lw=1.5, label='Marktplanung', ls=':')
    ax1.set_title('Produktionsplanung vs. Bedarf (Hamburg, GWh/Jahr)')
    ax1.set_ylabel('GWh')
    ax1.legend(loc='upper right', fontsize=9)
    ax1.grid(True, alpha=0.4)
    ax1.set_xlim(years[0], years[-1])

    # ── Panel 2: Regelabweichung (Error) ──────────────────────────────────
    ax2 = fig.add_subplot(gs[0, 2])
    ax2.axhline(0, color='#8b949e', lw=0.8, ls='--')
    ax2.fill_between(years, sim_cyber['error'],  alpha=0.3, color=CYBER_COLOR)
    ax2.fill_between(years, sim_market['error'], alpha=0.3, color=MARKET_COLOR)
    ax2.plot(years, sim_cyber['error'],  color=CYBER_COLOR,  lw=1.5, label=f'Cybersyn (RMSE={metrics_cyber["rmse_GWh"]:.0f})')
    ax2.plot(years, sim_market['error'], color=MARKET_COLOR, lw=1.5, label=f'Markt (RMSE={metrics_market["rmse_GWh"]:.0f})')
    ax2.set_title('Regelabweichung (GWh)')
    ax2.set_ylabel('Fehler (GWh)')
    ax2.legend(fontsize=9)
    ax2.grid(True, alpha=0.4)

    # ── Panel 3: Defizit im Zeitverlauf ───────────────────────────────────
    ax3 = fig.add_subplot(gs[1, :2])
    ax3.fill_between(years, sim_cyber['deficit'],  alpha=0.5, color=CYBER_COLOR,  label='Cybersyn Defizit')
    ax3.fill_between(years, sim_market['deficit'], alpha=0.5, color=MARKET_COLOR, label='Markt Defizit')
    ax3.set_title('Versorgungsdefizit (GWh/Jahr) – niedriger ist besser')
    ax3.set_ylabel('Defizit (GWh)')
    ax3.legend(fontsize=9)
    ax3.grid(True, alpha=0.4)
    ax3.set_xlim(years[0], years[-1])

    # ── Panel 4: Speicherstand Cybersyn ───────────────────────────────────
    ax4 = fig.add_subplot(gs[1, 2])
    ax4.fill_between(years, sim_cyber['storage_level'], alpha=0.4, color=STORAGE_COLOR)
    ax4.plot(years, sim_cyber['storage_level'], color=STORAGE_COLOR, lw=2)
    ax4.set_title('Speicherstand Cybersyn (GWh)')
    ax4.set_ylabel('GWh')
    ax4.grid(True, alpha=0.4)

    # ── Panel 5: Kumulativer Vergleich ────────────────────────────────────
    ax5 = fig.add_subplot(gs[2, :2])
    cum_deficit_cyber  = sim_cyber['deficit'].cumsum()
    cum_deficit_market = sim_market['deficit'].cumsum()
    ax5.fill_between(years, cum_deficit_market, cum_deficit_cyber,
                     where=(cum_deficit_market >= cum_deficit_cyber),
                     alpha=0.3, color=CYBER_COLOR, label='Cybersyn-Vorteil')
    ax5.plot(years, cum_deficit_cyber,  color=CYBER_COLOR,  lw=2, label='Cybersyn kumulativ')
    ax5.plot(years, cum_deficit_market, color=MARKET_COLOR, lw=2, label='Markt kumulativ')
    ax5.set_title('Kumulatives Defizit (GWh) – Gesamtversorgungslücke')
    ax5.set_ylabel('Kumulatives Defizit (GWh)')
    ax5.set_xlabel('Jahr')
    ax5.legend(fontsize=9)
    ax5.grid(True, alpha=0.4)
    ax5.set_xlim(years[0], years[-1])

    # ── Panel 6: Metriken-Scorecard ───────────────────────────────────────
    ax6 = fig.add_subplot(gs[2, 2])
    ax6.axis('off')

    scorecard_data = [
        ['Metrik', 'Cybersyn', 'Markt'],
        ['Versorgungsrate', f"{metrics_cyber['supply_rate_%']:.1f}%", f"{metrics_market['supply_rate_%']:.1f}%"],
        ['Verlustrate', f"{metrics_cyber['waste_rate_%']:.1f}%", f"{metrics_market['waste_rate_%']:.1f}%"],
        ['RMSE (GWh)', f"{metrics_cyber['rmse_GWh']:.0f}", f"{metrics_market['rmse_GWh']:.0f}"],
        ['Max. Defizit', f"{metrics_cyber['max_deficit_GWh']:.0f} GWh", f"{metrics_market['max_deficit_GWh']:.0f} GWh"],
        ['Ges. Defizit', f"{metrics_cyber['total_deficit_GWh']:.0f} GWh", f"{metrics_market['total_deficit_GWh']:.0f} GWh"],
        ['Konvergenz', str(metrics_cyber['convergence_year'] or 'n/a'),
                       str(metrics_market['convergence_year'] or 'n/a')],
    ]

    table = ax6.table(
        cellText=scorecard_data[1:],
        colLabels=scorecard_data[0],
        cellLoc='center',
        loc='center',
        bbox=[0, 0.1, 1, 0.85]
    )
    table.auto_set_font_size(False)
    table.set_fontsize(9.5)

    for (row, col), cell in table.get_celld().items():
        cell.set_facecolor('#161b22')
        cell.set_edgecolor('#30363d')
        cell.set_text_props(color='#e6edf3')
        if row == 0:
            cell.set_facecolor('#21262d')
            cell.set_text_props(fontweight='bold', color='#e6edf3')
        elif col == 1:
            cell.set_text_props(color=CYBER_COLOR, fontweight='bold')
        elif col == 2:
            cell.set_text_props(color=MARKET_COLOR)

    ax6.set_title('Leistungsvergleich', pad=8)

    # Legende für Regelschleife
    fig.text(0.5, 0.01,
             'Regelschleife: Produktion → Verteilung → Verbrauch → Feedback → Anpassung  |  '
             'Kein Preismechanismus – nur Bedarf und Kapazität  |  '
             'Daten: Eurostat nrg_bal_c (DE, 1990–2024), Hamburg-Anteil 2.6%',
             ha='center', fontsize=8, color='#8b949e', style='italic')

    plt.savefig(output_file, dpi=150, bbox_inches='tight',
                facecolor=fig.get_facecolor())
    plt.close()
    print(f"  → Visualisierung gespeichert: {output_file}")


def plot_feedback_loop(output_file='cybersyn_feedback_loop.png'):
    """Visualisiert die kybernetische Regelschleife als Diagramm."""
    plt.rcParams.update({
        'font.family': 'DejaVu Sans',
        'figure.facecolor': '#0d1117',
        'text.color': '#e6edf3',
    })

    fig, ax = plt.subplots(figsize=(14, 7))
    fig.patch.set_facecolor('#0d1117')
    ax.set_facecolor('#0d1117')
    ax.set_xlim(0, 14)
    ax.set_ylim(0, 7)
    ax.axis('off')

    ax.set_title('Cybersyn 2.0 – Kybernetische Regelschleife (Hamburg Stromsystem)',
                 fontsize=14, fontweight='bold', pad=15, color='#e6edf3')

    # Knoten definieren
    nodes = {
        'Produktion':   (1.5, 3.5),
        'Verteilung':   (4.5, 3.5),
        'Verbrauch':    (7.5, 3.5),
        'Feedback':     (7.5, 1.5),
        'Regler':       (4.5, 1.5),
        'Anpassung':    (1.5, 1.5),
    }
    node_colors = {
        'Produktion':   '#1f6feb',
        'Verteilung':   '#388bfd',
        'Verbrauch':    '#3fb950',
        'Feedback':     '#f78166',
        'Regler':       '#d2a8ff',
        'Anpassung':    '#ffa657',
    }
    node_labels = {
        'Produktion':   'PRODUKTION\n(Wind, Solar,\nKraftwerke)',
        'Verteilung':   'VERTEILUNG\n(Netz Hamburg\n110kV/10kV)',
        'Verbrauch':    'VERBRAUCH\n(Haushalte,\nIndustrie)',
        'Feedback':     'FEEDBACK\n(Ist-Bedarf\nmessen)',
        'Regler':       'REGLER\n(PI-Algorithmus\nKp=0.6, Ki=0.15)',
        'Anpassung':    'ANPASSUNG\n(Speicher,\nLaststeuerung)',
    }

    box_w, box_h = 2.2, 1.4
    for name, (cx, cy) in nodes.items():
        rect = mpatches.FancyBboxPatch(
            (cx - box_w/2, cy - box_h/2), box_w, box_h,
            boxstyle='round,pad=0.1',
            facecolor=node_colors[name], edgecolor='#e6edf3',
            linewidth=1.5, alpha=0.85, zorder=3
        )
        ax.add_patch(rect)
        ax.text(cx, cy, node_labels[name], ha='center', va='center',
                fontsize=8.5, fontweight='bold', color='white', zorder=4,
                multialignment='center')

    # Pfeile (Vorwärtspfade oben, Rückwärtspfade unten)
    arrow_style = dict(arrowstyle='->', color='#58a6ff', lw=2,
                       connectionstyle='arc3,rad=0')
    feedback_style = dict(arrowstyle='->', color='#f78166', lw=2,
                          connectionstyle='arc3,rad=0')

    def arrow(ax, start, end, style, label='', label_offset=(0, 0.25)):
        ax.annotate('', xy=end, xytext=start,
                    arrowprops=dict(**style, shrinkA=8, shrinkB=8), zorder=2)
        if label:
            mx = (start[0] + end[0]) / 2 + label_offset[0]
            my = (start[1] + end[1]) / 2 + label_offset[1]
            ax.text(mx, my, label, ha='center', va='bottom',
                    fontsize=8, color='#8b949e', style='italic')

    # Vorwärtspfade (oben)
    arrow(ax, (2.6, 3.5), (3.4, 3.5), arrow_style, 'GWh erzeugt')
    arrow(ax, (5.6, 3.5), (6.4, 3.5), arrow_style, 'GWh verteilt')

    # Feedback-Pfad (rechts runter)
    arrow(ax, (7.5, 2.8), (7.5, 2.2), feedback_style, 'Abweichung\ne(t) = C-P', (0.7, 0))

    # Rückwärtspfade (unten)
    arrow(ax, (6.4, 1.5), (5.6, 1.5), feedback_style, 'Korrekturimpuls')
    arrow(ax, (3.4, 1.5), (2.6, 1.5), feedback_style, 'ΔP(t)')

    # Anpassung → Produktion (links hoch)
    arrow(ax, (1.5, 2.2), (1.5, 2.8), arrow_style, 'neue\nPlanung', (0.7, 0))

    # Eurostat-Daten-Label
    ax.text(7, 5.5, 'Datenquelle:\nEurostat nrg_bal_c\n(DE, 1990–2024)\nHamburg-Anteil: 2.6%',
            ha='center', va='center', fontsize=9, color='#8b949e',
            bbox=dict(boxstyle='round', facecolor='#161b22', edgecolor='#30363d', alpha=0.8))

    # Kein-Preis-Label
    ax.text(7, 0.5, 'Kein Preismechanismus – nur physikalische Bilanz (GWh)',
            ha='center', va='center', fontsize=9, color='#ffa657', style='italic')

    plt.tight_layout()
    plt.savefig(output_file, dpi=150, bbox_inches='tight',
                facecolor=fig.get_facecolor())
    plt.close()
    print(f"  → Regelschleife-Diagramm gespeichert: {output_file}")


# ─────────────────────────────────────────────────────────────────────────────
# 6. HAUPTPROGRAMM
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    print("=" * 60)
    print("  Cybersyn 2.0 – Hamburg Stromsystem")
    print("  Kybernetische Regelschleife")
    print("=" * 60)

    # Daten laden
    print("\n[1] Lade Eurostat-Daten...")
    df_raw = load_eurostat_electricity()
    ts_de  = build_germany_timeseries(df_raw)
    ts_hh  = scale_to_hamburg(ts_de, hh_share=0.026)

    print(f"    Datenpunkte: {len(ts_hh)} Jahre ({ts_hh.index[0]}–{ts_hh.index[-1]})")
    print(f"    Hamburg Verbrauch 2023: {ts_hh.loc[2023, 'available_GWh']:.0f} GWh")
    print(f"    Hamburg Erzeugung 2023: {ts_hh.loc[2023, 'production_GWh']:.0f} GWh")

    # Simulation
    print("\n[2] Starte Simulationen...")

    # Cybersyn: PI-Regler mit Speicher
    cyber_ctrl  = CybersynController(Kp=0.6, Ki=0.15, storage_capacity_frac=0.08)
    # Stress-Test: Startplanung 15% unter Bedarf
    sim_cyber   = run_simulation(ts_hh, cyber_ctrl, initial_plan_offset=-0.15)

    # Markt: Preiselastizität mit 2-Jahres-Verzögerung
    market_ctrl = MarketController(price_elasticity=0.4, reaction_lag=2)
    sim_market  = run_simulation(ts_hh, market_ctrl, initial_plan_offset=-0.15)

    # Metriken
    print("\n[3] Berechne Metriken...")
    m_cyber  = compute_metrics(sim_cyber)
    m_market = compute_metrics(sim_market)

    print("\n  ┌─────────────────────────────────────────────────────┐")
    print("  │              LEISTUNGSVERGLEICH                     │")
    print("  ├──────────────────────┬──────────────┬──────────────┤")
    print("  │ Metrik               │  Cybersyn    │    Markt     │")
    print("  ├──────────────────────┼──────────────┼──────────────┤")
    for key in m_cyber:
        v_c = str(m_cyber[key])
        v_m = str(m_market[key])
        print(f"  │ {key:<20} │ {v_c:>12} │ {v_m:>12} │")
    print("  └──────────────────────┴──────────────┴──────────────┘")

    # Visualisierungen
    print("\n[4] Erstelle Visualisierungen...")
    plot_results(ts_hh, sim_cyber, sim_market, m_cyber, m_market)
    plot_feedback_loop()

    # Daten exportieren
    print("\n[5] Exportiere Daten...")
    ts_hh.to_csv('hamburg_electricity_data.csv')
    sim_cyber.to_csv('simulation_cybersyn.csv')
    sim_market.to_csv('simulation_market.csv')

    print("\n[6] Fertig! Dateien:")
    print("    - cybersyn_hamburg_results.png   (Hauptvisualisierung)")
    print("    - cybersyn_feedback_loop.png     (Regelschleife-Diagramm)")
    print("    - hamburg_electricity_data.csv   (Rohdaten Hamburg)")
    print("    - simulation_cybersyn.csv        (Simulationsergebnisse Cybersyn)")
    print("    - simulation_market.csv          (Simulationsergebnisse Markt)")
    print("=" * 60)
