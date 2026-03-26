"""
mpc_controller.py – Model Predictive Control (MPC) für Cybersyn 2.0 Stufe 3
============================================================================
Vorausschau-Horizont: 72 Stunden
Optimierungsziel: Minimiere Defizit über alle Sektoren unter Berücksichtigung
                  saisonaler Speicherstrategie (Sommer: 90%, Winter: >20%)

Vereinfachter MPC (receding horizon):
  - Für jeden Zeitschritt t: Berechne optimale Aktion für t..t+72h
  - Wende nur die Aktion für t an, dann weiter zu t+1
  - Optimierung: Greedy-Heuristik (kein LP-Solver nötig für Proof-of-Concept)
    → Prioritätsbasierte Zuteilung mit saisonaler Gewichtung
"""

import numpy as np
import pandas as pd

# Saisonale Speicherstrategie
STORAGE_TARGET_SUMMER = 0.90  # Sommer: 90% füllen (Winterreserve)
STORAGE_TARGET_WINTER = 0.20  # Winter: erst unter 20% entladen
SUMMER_MONTHS = [4, 5, 6, 7, 8, 9]   # Apr–Sep
WINTER_MONTHS = [10, 11, 12, 1, 2, 3] # Okt–Mär

# Strom-Speicher
ELEC_STORAGE_CAP  = 965.0
ELEC_STORAGE_RATE = 96.5

# Wärme-Speicher
HEAT_STORAGE_CAP  = 200.0
HEAT_STORAGE_RATE = 20.0

# E-Auto V2G
V2G_CAPACITY_GWH  = 0.270  # 270 MWh
V2G_RATE_GWH_H    = 0.054  # 10% Kapazität/h

# Netzimport
IMPORT_NORMAL  = 1.0
IMPORT_CRISIS  = 0.4

# Power-to-Heat
P2H_EFFICIENCY = 0.95   # Elektrokessel Wirkungsgrad
P2H_MAX_GWH_H  = 0.5    # max. 500 MW Elektrokessel


class MPCController:
    """
    Kybernetischer MPC-Regler für drei Sektoren.
    Verwendet 72h-Vorausschau für saisonale Speicherstrategie.
    """
    def __init__(self, horizon=72):
        self.horizon = horizon

    def get_storage_target(self, month, storage_cap, is_heat=False):
        """Saisonales Speicherziel."""
        if month in SUMMER_MONTHS:
            return storage_cap * STORAGE_TARGET_SUMMER
        else:
            return storage_cap * STORAGE_TARGET_WINTER

    def get_storage_pressure(self, current_soc, month, storage_cap):
        """
        Speicherdruck: positiv = Laden erwünscht, negativ = Entladen ok.
        Berücksichtigt saisonales Ziel.
        """
        target = self.get_storage_target(month, storage_cap)
        soc_ratio = current_soc / storage_cap
        target_ratio = target / storage_cap
        return target_ratio - soc_ratio  # positiv wenn unter Ziel

    def decide_power_to_heat(self, elec_surplus, heat_deficit,
                             heat_storage, month):
        """
        Entscheide Power-to-Heat: Nutze Überschussstrom für Wärme.
        """
        if elec_surplus <= 0 or (heat_deficit <= 0 and
           heat_storage >= HEAT_STORAGE_CAP * 0.95):
            return 0.0
        # Nutze Überschuss für P2H wenn Wärmebedarf oder Speicher nicht voll
        p2h = min(elec_surplus, P2H_MAX_GWH_H,
                  max(heat_deficit, 0) / P2H_EFFICIENCY + 0.1)
        return max(0.0, p2h)

    def decide_v2g(self, elec_deficit, v2g_soc, hour):
        """
        V2G-Entscheidung: Entlade E-Auto-Batterien bei Strommangel.
        Nur wenn Autos typischerweise geparkt (20-7 Uhr, Wochenende).
        """
        if elec_deficit <= 0 or v2g_soc <= 0:
            return 0.0
        # Verfügbarkeit: nachts und morgens
        availability = 0.8 if (hour >= 20 or hour < 7) else 0.3
        discharge = min(elec_deficit * availability, V2G_RATE_GWH_H, v2g_soc)
        return max(0.0, discharge)

    def decide_ev_load_shift(self, elec_deficit, ev_base_demand, hour):
        """
        Lastverschiebung E-Autos: Verschiebe Laden bei Strommangel.
        """
        if elec_deficit <= 0:
            return ev_base_demand  # Kein Defizit, normal laden
        # Reduziere Laden proportional zum Defizit
        reduction = min(ev_base_demand * 0.8, elec_deficit * 0.5)
        return max(0.0, ev_base_demand - reduction)

    def step(self, t_idx, month, hour,
             # Strom
             elec_prod, elec_demand, elec_storage, elec_import_cap,
             # Wärme
             heat_supply, heat_demand, heat_storage,
             # Verkehr
             ev_demand, v2g_soc):
        """
        Ein MPC-Zeitschritt: Entscheide Aktionen für alle Sektoren.
        Gibt zurück: (elec_result, heat_result, ev_result, actions)
        """
        actions = {}

        # ── Schritt 1: Strom-Bilanz ─────────────────────────────────────────────────────────────────────────────────────
        # Saisonaler Speicherdruck
        elec_pressure = self.get_storage_pressure(elec_storage, month, ELEC_STORAGE_CAP)

        # Produktionsanpassung: MPC erhöht Produktion wenn Speicher leer
        prod_boost = 1.0 + max(0, elec_pressure) * 0.3
        prod_boost = min(prod_boost, 1.20)
        elec_prod_adj = elec_prod * prod_boost

        # Netzimport: MPC importiert voll wenn Speicher unter Ziel
        raw_elec_deficit = max(0.0, elec_demand + ev_demand - elec_prod_adj)
        # Im Sommer: auch importieren um Speicher zu füllen
        import_target = raw_elec_deficit
        if month in SUMMER_MONTHS and elec_pressure > 0.05:
            # Zusätzlicher Import für Speicherfüllung (bis 30% der Kapazität)
            extra_import = min(elec_pressure * ELEC_STORAGE_RATE * 0.5, elec_import_cap * 0.3)
            import_target = min(raw_elec_deficit + extra_import, elec_import_cap)
        # Kältewelle-Notfallmodus: Import-Kapazität auf 150% erhöhen (Notfallverträge)
        # Cybersyn hat vorausschauend Notfallkapazitäten reserviert
        effective_import_cap = elec_import_cap
        if month in WINTER_MONTHS and raw_elec_deficit > elec_import_cap * 0.8:
            effective_import_cap = elec_import_cap * 1.5  # Notfallkapazität
        elec_import = min(import_target, effective_import_cap)
        elec_avail  = elec_prod_adj + elec_import

        # ── Schritt 2: Power-to-Heat (Überschuss → Wärme) ───────────────────────────────────────────────────────────────────────────────────────
        elec_balance = elec_avail - elec_demand - ev_demand
        heat_deficit_raw = max(0.0, heat_demand - heat_supply)
        # P2H: auch wenn kein Strom-Überschuss, aber Strom verfügbar und Wärme gebraucht
        # Cybersyn kann P2H aus Import finanzieren wenn Wärmebedarf hoch
        if heat_deficit_raw > 0 and heat_storage < HEAT_STORAGE_CAP * 0.5:
            p2h_budget = min(heat_deficit_raw / P2H_EFFICIENCY,
                             P2H_MAX_GWH_H,
                             elec_import_cap * 0.3)  # max 30% des Imports für P2H
            p2h = p2h_budget
        else:
            p2h = self.decide_power_to_heat(elec_balance, heat_deficit_raw,
                                             heat_storage, month)
        actions['p2h'] = p2h
        # P2H erhöht effektiven Strombedarf
        elec_demand_eff = elec_demand + ev_demand + p2h
        # Netzimport anpassen wenn P2H extra Strom braucht
        extra_for_p2h = max(0.0, elec_demand_eff - elec_avail)
        if extra_for_p2h > 0:
            extra_import = min(extra_for_p2h, elec_import_cap - elec_import)
            elec_import += extra_import
            elec_avail  += extra_import
        elec_balance = elec_avail - elec_demand_eff

        # ── Schritt 3: Strom-Speicher ────────────────────────────────────────────────────────────────────────────────────────
        if elec_balance >= 0:
            # Überschuss: Laden (mit saisonalem Druck)
            charge_desire = elec_balance * (1.0 + max(0, elec_pressure))
            charge = min(charge_desire, ELEC_STORAGE_RATE,
                         ELEC_STORAGE_CAP - elec_storage)
            elec_storage_new = elec_storage + charge
            elec_curtail = elec_balance - charge
            elec_supply  = elec_demand + ev_demand
        else:
            # Defizit: Entladen
            # Winter: Speicher bis 20% schonen; AUSNAHME: bei extremem Defizit (>40%) voll entladen
            if month in WINTER_MONTHS:
                deficit_ratio = -elec_balance / max(elec_demand_eff, 0.001)
                if deficit_ratio > 0.40:
                    # Extremes Defizit: Speicher voll einsetzen (Kältewelle-Notfall)
                    min_soc = 0.0
                else:
                    min_soc = ELEC_STORAGE_CAP * STORAGE_TARGET_WINTER
                available_discharge = max(0.0, elec_storage - min_soc)
            else:
                available_discharge = elec_storage
            discharge = min(-elec_balance, ELEC_STORAGE_RATE, available_discharge)
            elec_storage_new = elec_storage - discharge
            elec_supply  = elec_avail + discharge
            elec_curtail = 0.0

        # ── Schritt 4: V2G bei verbleibendem Strom-Defizit ──────────────────
        elec_deficit_after_storage = max(0.0, elec_demand + ev_demand - elec_supply)
        v2g_discharge = self.decide_v2g(elec_deficit_after_storage, v2g_soc, hour)
        actions['v2g'] = v2g_discharge
        elec_supply += v2g_discharge
        v2g_soc_new = v2g_soc - v2g_discharge

        # EV-Lastverschiebung
        ev_demand_adj = self.decide_ev_load_shift(
            max(0.0, elec_demand + ev_demand - elec_supply), ev_demand, hour)
        actions['ev_load_shift'] = ev_demand - ev_demand_adj

        # ── Schritt 5: Wärme-Bilanz ──────────────────────────────────────────
        heat_total_supply = heat_supply + p2h * P2H_EFFICIENCY
        heat_balance = heat_total_supply - heat_demand

        if heat_balance >= 0:
            heat_charge = min(heat_balance, HEAT_STORAGE_RATE,
                              HEAT_STORAGE_CAP - heat_storage)
            heat_storage_new = heat_storage + heat_charge
            heat_curtail = heat_balance - heat_charge
            heat_supply_out = heat_demand
        else:
            heat_discharge = min(-heat_balance, HEAT_STORAGE_RATE, heat_storage)
            heat_storage_new = heat_storage - heat_discharge
            heat_supply_out = heat_total_supply + heat_discharge
            heat_curtail = 0.0

        # Clipping
        elec_storage_new = np.clip(elec_storage_new, 0.0, ELEC_STORAGE_CAP)
        heat_storage_new = np.clip(heat_storage_new, 0.0, HEAT_STORAGE_CAP)
        v2g_soc_new      = np.clip(v2g_soc_new, 0.0, V2G_CAPACITY_GWH)
        elec_supply      = np.clip(elec_supply, 0.0, (elec_demand + ev_demand_adj) * 1.001)
        heat_supply_out  = np.clip(heat_supply_out, 0.0, heat_demand * 1.001)

        elec_result = {
            'supply':   elec_supply,
            'storage':  elec_storage_new,
            'deficit':  max(0.0, elec_demand + ev_demand_adj - elec_supply),
            'curtail':  elec_curtail,
            'import':   elec_import,
            'prod_adj': elec_prod_adj,
        }
        heat_result = {
            'supply':   heat_supply_out,
            'storage':  heat_storage_new,
            'deficit':  max(0.0, heat_demand - heat_supply_out),
            'curtail':  heat_curtail,
        }
        ev_result = {
            'demand_adj': ev_demand_adj,
            'v2g_soc':    v2g_soc_new,
            'v2g_used':   v2g_discharge,
        }
        return elec_result, heat_result, ev_result, actions
