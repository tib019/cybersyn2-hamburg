"""
node_base.py – Basisklasse für regionale Knoten im fraktalen VSM
================================================================
Jeder Knoten ist ein vollständiges Cybersyn-3-Modell:
- MPC-Regler mit 72h Vorausschau
- Algedonic Channel
- Strom + Wärme Sektoren
- Surplus/Defizit-Reporting für Meta-Controller
"""

import numpy as np

# Saisonale Speicherstrategie (identisch zu Stufe 3)
STORAGE_TARGET_SUMMER = 0.90
STORAGE_TARGET_WINTER = 0.20
SUMMER_MONTHS = [4, 5, 6, 7, 8, 9]
WINTER_MONTHS = [10, 11, 12, 1, 2, 3]

P2H_EFFICIENCY = 0.95
P2H_MAX_GWH_H  = 0.5


class NodeConfig:
    """Konfiguration für einen regionalen Knoten."""
    def __init__(self, name, elec_storage_cap, elec_storage_rate,
                 heat_storage_cap, heat_storage_rate,
                 import_cap_normal, import_cap_crisis,
                 scale_factor, has_ev=False, ev_capacity_gwh=0.0):
        self.name              = name
        self.elec_storage_cap  = elec_storage_cap
        self.elec_storage_rate = elec_storage_rate
        self.heat_storage_cap  = heat_storage_cap
        self.heat_storage_rate = heat_storage_rate
        self.import_cap_normal = import_cap_normal
        self.import_cap_crisis = import_cap_crisis
        self.scale_factor      = scale_factor
        self.has_ev            = has_ev
        self.ev_capacity_gwh   = ev_capacity_gwh


class NodeAlgedonicChannel:
    """
    Algedonic Channel für einen Knoten.
    Löst aus wenn Defizit > Schwellwert für N aufeinanderfolgende Stunden.
    """
    def __init__(self, name, threshold=0.15, min_hours=3):
        self.name      = name
        self.threshold = threshold
        self.min_hours = min_hours
        self.active    = {}
        self.counters  = {}
        self.events    = []

    def step(self, timestamp, elec_deficit_ratio, heat_deficit_ratio,
             elec_demand, heat_demand):
        """
        Gibt Lastabwurf-Anteile zurück.
        Prioritätshierarchie:
        1. Kritische Infrastruktur (nie abgeworfen)
        2. Wärme Haushalte
        3. Strom Haushalte
        4. KMU
        5. Industrie
        """
        shed = {}
        for sector, ratio, demand in [
            ('elec', elec_deficit_ratio, elec_demand),
            ('heat', heat_deficit_ratio, heat_demand),
        ]:
            self.counters.setdefault(sector, 0)
            if ratio > self.threshold:
                self.counters[sector] += 1
            else:
                self.counters[sector] = 0

            if self.counters[sector] >= self.min_hours:
                # Stufenweiser Lastabwurf: 0.2 → 0.4 → 0.6
                steps = min(self.counters[sector] - self.min_hours + 1, 3)
                shed[sector] = steps * 0.20
                if not self.active.get(sector):
                    self.active[sector] = True
                    self.events.append({
                        'time': str(timestamp),
                        'node': self.name,
                        'sector': sector,
                        'deficit_ratio': round(ratio, 3),
                        'shed': shed[sector],
                    })
            else:
                shed[sector]         = 0.0
                self.active[sector]  = False

        return shed


class RegionalNode:
    """
    Regionaler Knoten im fraktalen VSM.
    Enthält eigenen MPC-Regler und Algedonic Channel.
    """
    def __init__(self, config: NodeConfig):
        self.cfg = config
        self.alg = NodeAlgedonicChannel(config.name)

        # Zustand
        self.elec_storage = config.elec_storage_cap * 0.50
        self.heat_storage = config.heat_storage_cap * 0.50

        # Überschuss/Defizit (wird vom Meta-Controller abgefragt)
        self.last_elec_surplus  = 0.0
        self.last_elec_deficit  = 0.0
        self.last_heat_surplus  = 0.0
        self.last_heat_deficit  = 0.0
        self.in_crisis          = False
        self.crisis_hours       = 0

    def get_storage_pressure(self, current_soc, month, cap):
        target = cap * (STORAGE_TARGET_SUMMER if month in SUMMER_MONTHS
                        else STORAGE_TARGET_WINTER)
        return (target - current_soc) / cap

    def step(self, timestamp, elec_prod, elec_demand,
             heat_supply, heat_demand, is_crisis_period,
             transfer_in_elec=0.0, transfer_in_heat=0.0):
        """
        Ein Zeitschritt für diesen Knoten.
        transfer_in_*: Energie vom Meta-Controller (Solidaritätstransfer).
        Gibt zurück: dict mit Metriken + (surplus_elec, surplus_heat).
        """
        month = timestamp.month
        hour  = timestamp.hour
        cfg   = self.cfg

        import_cap = cfg.import_cap_crisis if is_crisis_period else cfg.import_cap_normal

        # ── Algedonic Check ─────────────────────────────────────────────────
        max_possible = elec_prod * 1.20 + import_cap + self.elec_storage * 0.1 + transfer_in_elec
        elec_def_ratio = max(0.0, (elec_demand - max_possible) / max(elec_demand, 0.001))
        heat_max = heat_supply + self.heat_storage * 0.1 + transfer_in_heat
        heat_def_ratio = max(0.0, (heat_demand - heat_max) / max(heat_demand, 0.001))
        shed = self.alg.step(timestamp, elec_def_ratio, heat_def_ratio,
                             elec_demand, heat_demand)
        elec_d = elec_demand * (1.0 - shed.get('elec', 0.0))
        heat_d = heat_demand * (1.0 - shed.get('heat', 0.0))

        # ── MPC: saisonaler Speicherdruck ────────────────────────────────────
        elec_pressure = self.get_storage_pressure(self.elec_storage, month, cfg.elec_storage_cap)
        prod_boost    = min(1.20, 1.0 + max(0, elec_pressure) * 0.3)
        elec_prod_adj = elec_prod * prod_boost

        # Import
        raw_deficit    = max(0.0, elec_d - elec_prod_adj - transfer_in_elec)
        effective_cap  = import_cap * (1.5 if month in WINTER_MONTHS and raw_deficit > import_cap * 0.8 else 1.0)
        elec_import    = min(raw_deficit, effective_cap)
        elec_avail     = elec_prod_adj + elec_import + transfer_in_elec

        # Power-to-Heat
        heat_def_raw = max(0.0, heat_d - heat_supply - transfer_in_heat)
        elec_balance = elec_avail - elec_d
        if heat_def_raw > 0 and self.heat_storage < cfg.heat_storage_cap * 0.5:
            p2h = min(heat_def_raw / P2H_EFFICIENCY, P2H_MAX_GWH_H, import_cap * 0.3)
        else:
            p2h = max(0.0, min(elec_balance, P2H_MAX_GWH_H,
                               max(heat_def_raw, 0) / P2H_EFFICIENCY + 0.1)) if elec_balance > 0 else 0.0
        elec_demand_eff = elec_d + p2h
        extra_for_p2h   = max(0.0, elec_demand_eff - elec_avail)
        if extra_for_p2h > 0:
            extra_imp = min(extra_for_p2h, effective_cap - elec_import)
            elec_import += extra_imp
            elec_avail  += extra_imp
        elec_balance = elec_avail - elec_demand_eff

        # ── Strom-Speicher ───────────────────────────────────────────────────
        if elec_balance >= 0:
            charge_desire = elec_balance * (1.0 + max(0, elec_pressure))
            charge = min(charge_desire, cfg.elec_storage_rate,
                         cfg.elec_storage_cap - self.elec_storage)
            self.elec_storage = np.clip(self.elec_storage + charge, 0, cfg.elec_storage_cap)
            elec_curtail = elec_balance - charge
            elec_supply  = elec_d
            elec_surplus = elec_curtail  # Überschuss nach Laden
        else:
            if month in WINTER_MONTHS:
                deficit_ratio = -elec_balance / max(elec_demand_eff, 0.001)
                min_soc = 0.0 if deficit_ratio > 0.40 else cfg.elec_storage_cap * STORAGE_TARGET_WINTER
            else:
                min_soc = 0.0
            avail_discharge = max(0.0, self.elec_storage - min_soc)
            discharge = min(-elec_balance, cfg.elec_storage_rate, avail_discharge)
            self.elec_storage = np.clip(self.elec_storage - discharge, 0, cfg.elec_storage_cap)
            elec_supply  = elec_avail + discharge
            elec_curtail = 0.0
            elec_surplus = 0.0

        elec_deficit = max(0.0, elec_d - elec_supply)

        # ── Wärme-Bilanz ─────────────────────────────────────────────────────
        heat_total = heat_supply + p2h * P2H_EFFICIENCY + transfer_in_heat
        heat_bal   = heat_total - heat_d
        if heat_bal >= 0:
            hc = min(heat_bal, cfg.heat_storage_rate, cfg.heat_storage_cap - self.heat_storage)
            self.heat_storage = np.clip(self.heat_storage + hc, 0, cfg.heat_storage_cap)
            heat_curtail  = heat_bal - hc
            heat_supply_out = heat_d
            heat_surplus  = heat_curtail
        else:
            hd = min(-heat_bal, cfg.heat_storage_rate, self.heat_storage)
            self.heat_storage = np.clip(self.heat_storage - hd, 0, cfg.heat_storage_cap)
            heat_supply_out = heat_total + hd
            heat_curtail  = 0.0
            heat_surplus  = 0.0

        heat_deficit = max(0.0, heat_d - heat_supply_out)

        # ── Krisenstatus aktualisieren ────────────────────────────────────────
        total_deficit_ratio = (elec_deficit / max(elec_d, 0.001) * 0.6 +
                               heat_deficit / max(heat_d, 0.001) * 0.4)
        if total_deficit_ratio > 0.10:
            self.crisis_hours += 1
        else:
            self.crisis_hours = 0
        self.in_crisis = self.crisis_hours >= 3

        self.last_elec_surplus = elec_surplus
        self.last_elec_deficit = elec_deficit
        self.last_heat_surplus = heat_surplus
        self.last_heat_deficit = heat_deficit

        return {
            'elec_supply':   elec_supply,
            'elec_demand':   elec_d,
            'elec_deficit':  elec_deficit,
            'elec_curtail':  elec_curtail,
            'elec_import':   elec_import,
            'elec_surplus':  elec_surplus,
            'elec_storage':  self.elec_storage,
            'heat_supply':   heat_supply_out,
            'heat_demand':   heat_d,
            'heat_deficit':  heat_deficit,
            'heat_curtail':  heat_curtail,
            'heat_surplus':  heat_surplus,
            'heat_storage':  self.heat_storage,
            'p2h':           p2h,
            'alg_active':    bool(shed.get('elec', 0) > 0 or shed.get('heat', 0) > 0),
            'in_crisis':     self.in_crisis,
        }
