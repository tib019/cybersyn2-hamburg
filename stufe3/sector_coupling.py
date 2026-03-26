"""
sector_coupling.py – Sektorkopplung und erweiterter Algedonic Channel
======================================================================
Prioritätshierarchie (Beer 1972, erweitert):
  1. Kritische Infrastruktur Strom  (nie abgeworfen)
  2. Wärme Haushalte               (Winterschutz)
  3. Strom Haushalte
  4. E-Auto Laden                  (erste Lastreduktion)
  5. Wärme KMU
  6. Strom KMU
  7. Wärme Industrie
  8. Strom Industrie
"""

import numpy as np

# Sektoranteile
ELEC_SHARES = {
    'kritisch':  0.10,
    'haushalte': 0.30,
    'kmu':       0.25,
    'industrie': 0.35,
}
HEAT_SHARES = {
    'haushalte': 0.45,
    'kmu':       0.30,
    'industrie': 0.25,
}

ALGEDONIC_THRESHOLD   = 0.15   # 15% Defizit (Hamburg ist strukturell Nettoimporteur)
ALGEDONIC_CONSECUTIVE = 3


class ExtendedAlgedonicChannel:
    """
    Erweiterter Algedonic Channel für drei Sektoren.
    Aktivierung: Defizit > 10% für ≥ 3 h in einem beliebigen Sektor.
    """
    def __init__(self):
        self.counters = {'elec': 0, 'heat': 0}
        self.active   = {'elec': False, 'heat': False}
        self.events   = []

    def step(self, t, elec_deficit_ratio, heat_deficit_ratio,
             elec_demand, heat_demand):
        results = {}

        for sector, ratio, demand in [
            ('elec', elec_deficit_ratio, elec_demand),
            ('heat', heat_deficit_ratio, heat_demand),
        ]:
            if ratio > ALGEDONIC_THRESHOLD:
                self.counters[sector] += 1
            else:
                self.counters[sector] = 0
                self.active[sector]   = False

            if (self.counters[sector] >= ALGEDONIC_CONSECUTIVE
                    and not self.active[sector]):
                self.active[sector] = True
                self.events.append({
                    'time': str(t), 'sector': sector,
                    'deficit_ratio': float(ratio), 'demand': float(demand),
                })

            shed = 0.0
            if self.active[sector]:
                needed = min(ratio * 1.2, 0.60)
                shed   = min(needed, 0.60)
            results[sector] = shed

        return results  # {'elec': shed_fraction, 'heat': shed_fraction}


class MarketModel3Sector:
    """
    Marktmodell für drei Sektoren:
    - Strom: Preissignal 6h verzögert, Speicher als Ware
    - Wärme: Preis proportional zu Kälte (Heizöl-Äquivalent)
    - E-Auto: Laden zu Niedrigtarif (Nacht), kein V2G
    """
    def __init__(self, price_delay_h=6):
        self.price_delay = price_delay_h
        self.supply_history = []
        self.demand_history = []
        self.base_price = 100.0

    def step(self, t_idx, month, hour,
             elec_prod, elec_demand, elec_storage, elec_import_cap,
             heat_supply, heat_demand, heat_storage,
             ev_demand):
        from mpc_controller import (
            ELEC_STORAGE_CAP, ELEC_STORAGE_RATE,
            HEAT_STORAGE_CAP, HEAT_STORAGE_RATE,
            P2H_EFFICIENCY, P2H_MAX_GWH_H,
            IMPORT_NORMAL, IMPORT_CRISIS
        )

        # ── Strom-Preis ──────────────────────────────────────────────────────
        t_d = max(0, t_idx - self.price_delay)
        if len(self.supply_history) > t_d:
            ps = self.supply_history[t_d]
            pd_ = self.demand_history[t_d]
        else:
            ps, pd_ = elec_prod, elec_demand
        price = np.clip(self.base_price * (pd_ / max(ps, 0.001)), 20.0, 500.0)
        pr = price / self.base_price

        # Produktionsanpassung
        p_adj = np.clip(elec_prod * (1.0 + 0.3 * (pr - 1.0)),
                        elec_prod * 0.70, elec_prod * 1.30)

        # Import (preisabhängig)
        raw_deficit = max(0.0, elec_demand + ev_demand - p_adj)
        import_factor = max(0.3, 1.0 - (pr - 1.0) * 0.5)
        elec_import = min(raw_deficit * import_factor, elec_import_cap)
        avail = p_adj + elec_import

        # Kein P2H im Marktmodell (kein Anreiz ohne Preissignal)
        p2h = 0.0

        # Strom-Speicher: nur bei Preis-Spread
        elec_balance = avail - elec_demand - ev_demand
        if elec_balance >= 0:
            if price < self.base_price * 0.95:
                charge = min(elec_balance, ELEC_STORAGE_RATE,
                             ELEC_STORAGE_CAP - elec_storage)
                elec_storage_new = elec_storage + charge
                elec_curtail = elec_balance - charge
            else:
                elec_curtail = elec_balance
                elec_storage_new = elec_storage
            elec_supply = elec_demand + ev_demand
        else:
            if price > self.base_price * 1.05:
                discharge = min(-elec_balance, ELEC_STORAGE_RATE, elec_storage)
                elec_storage_new = elec_storage - discharge
            else:
                discharge = 0.0
                elec_storage_new = elec_storage
            elec_supply = avail + (elec_storage - elec_storage_new)
            elec_curtail = 0.0

        elec_storage_new = np.clip(elec_storage_new, 0.0, ELEC_STORAGE_CAP)
        elec_supply = np.clip(elec_supply, 0.0, (elec_demand + ev_demand) * 1.001)

        # ── Wärme ────────────────────────────────────────────────────────────
        # Markt: Wärme wird direkt aus KWK gedeckt, kein P2H
        heat_balance = heat_supply - heat_demand
        if heat_balance >= 0:
            heat_charge = min(heat_balance, HEAT_STORAGE_RATE,
                              HEAT_STORAGE_CAP - heat_storage)
            heat_storage_new = heat_storage + heat_charge
            heat_curtail = heat_balance - heat_charge
            heat_supply_out = heat_demand
        else:
            heat_discharge = min(-heat_balance, HEAT_STORAGE_RATE, heat_storage)
            heat_storage_new = heat_storage - heat_discharge
            heat_supply_out = heat_supply + heat_discharge
            heat_curtail = 0.0

        heat_storage_new = np.clip(heat_storage_new, 0.0, HEAT_STORAGE_CAP)
        heat_supply_out  = np.clip(heat_supply_out, 0.0, heat_demand * 1.001)

        # ── E-Auto: Markt lädt nur nachts (Niedrigtarif), kein V2G ──────────
        ev_demand_adj = ev_demand * (1.2 if (hour >= 22 or hour < 6) else 0.3)
        ev_demand_adj = min(ev_demand_adj, ev_demand * 1.5)

        self.supply_history.append(float(elec_supply))
        self.demand_history.append(float(elec_demand))

        elec_result = {
            'supply':   elec_supply,
            'storage':  elec_storage_new,
            'deficit':  max(0.0, elec_demand + ev_demand - elec_supply),
            'curtail':  elec_curtail,
            'import':   elec_import,
            'price':    price,
        }
        heat_result = {
            'supply':   heat_supply_out,
            'storage':  heat_storage_new,
            'deficit':  max(0.0, heat_demand - heat_supply_out),
            'curtail':  heat_curtail,
        }
        ev_result = {
            'demand_adj': ev_demand_adj,
            'v2g_used':   0.0,
        }
        return elec_result, heat_result, ev_result
