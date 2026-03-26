"""
meta_controller.py – Fraktaler VSM Meta-Controller für Norddeutschland
======================================================================
Koordiniert drei regionale Knoten (Hamburg, Schleswig-Holstein, Niedersachsen)
nach Stafford Beers Viable System Model:

  System 1: Knoten (Hamburg, SH, NDS) – autonome operative Einheiten
  System 2: Koordination (Überschuss-/Defizit-Ausgleich zwischen Knoten)
  System 3: Steuerung (Meta-MPC mit 168h Vorausschau)
  System 4: Intelligenz (Wetterprognosen, saisonale Planung)
  System 5: Normative Ebene (Politische Ziele: Solidaritätsindex, CO2)

Übertragungskapazitäten (Bundesnetzagentur):
  Hamburg ↔ SH:  3.5 GWh/h
  Hamburg ↔ NDS: 2.8 GWh/h
  SH ↔ NDS:      1.2 GWh/h
"""

import numpy as np
from collections import deque

# Übertragungskapazitäten (GWh/h)
CAPACITY = {
    ('HH', 'SH'):  3.5,
    ('SH', 'HH'):  3.5,
    ('HH', 'NDS'): 2.8,
    ('NDS', 'HH'): 2.8,
    ('SH', 'NDS'): 1.2,
    ('NDS', 'SH'): 1.2,
}

NODES = ['HH', 'SH', 'NDS']


class MetaAlgedonicChannel:
    """
    Meta-Algedonic Channel: Wenn ein Knoten > 3 Stunden in Krise,
    sind Nachbar-Knoten zur Solidaritäts-Abgabe verpflichtet.
    """
    def __init__(self):
        self.crisis_counters = {n: 0 for n in NODES}
        self.solidarity_active = {n: False for n in NODES}
        self.events = []

    def update(self, timestamp, node_crisis: dict):
        """
        Aktualisiert Krisenstatus aller Knoten.
        Gibt zurück: Dict {node: True wenn Solidarität erforderlich}.
        """
        for node, in_crisis in node_crisis.items():
            if in_crisis:
                self.crisis_counters[node] += 1
            else:
                self.crisis_counters[node] = 0

            was_active = self.solidarity_active[node]
            self.solidarity_active[node] = self.crisis_counters[node] >= 3

            if self.solidarity_active[node] and not was_active:
                self.events.append({
                    'time': str(timestamp),
                    'node_in_crisis': node,
                    'crisis_hours': self.crisis_counters[node],
                })

        return dict(self.solidarity_active)


class CybersynMetaController:
    """
    Kybernetischer Meta-Controller (Cybersyn-Modus).
    Transfers sind bedarfsbasiert; Solidaritätspflicht bei Krise.
    """
    def __init__(self):
        self.meta_alg         = MetaAlgedonicChannel()
        self.mandatory_transfers = []  # Für Solidaritätsindex
        self.total_transfers     = []

    def coordinate(self, timestamp, node_results: dict):
        """
        Koordiniert Transfers zwischen Knoten.
        node_results: {node_name: step_result_dict}
        Gibt zurück: {node_name: {'transfer_in_elec': x, 'transfer_in_heat': x}}
        """
        # Krisenstatus abfragen
        node_crisis = {n: node_results[n]['in_crisis'] for n in NODES}
        solidarity_required = self.meta_alg.update(timestamp, node_crisis)

        # Surplus / Deficit für jeden Knoten
        elec_surplus = {n: node_results[n]['elec_surplus'] for n in NODES}
        elec_deficit = {n: node_results[n]['elec_deficit'] for n in NODES}
        heat_surplus = {n: node_results[n]['heat_surplus'] for n in NODES}
        heat_deficit = {n: node_results[n]['heat_deficit'] for n in NODES}

        transfers = {n: {'elec': 0.0, 'heat': 0.0, 'is_mandatory': False}
                     for n in NODES}
        line_load = {k: 0.0 for k in CAPACITY}

        # ── Runde 1: Pflicht-Solidarität (Krisenpflichtig) ──────────────────
        for deficit_node in NODES:
            if not solidarity_required[deficit_node]:
                continue
            ed = elec_deficit[deficit_node]
            hd = heat_deficit[deficit_node]
            if ed <= 0.001 and hd <= 0.001:
                continue

            for surplus_node in NODES:
                if surplus_node == deficit_node:
                    continue
                cap_key = (surplus_node, deficit_node)
                if cap_key not in CAPACITY:
                    continue
                remaining_cap = CAPACITY[cap_key] - line_load.get(cap_key, 0.0)
                if remaining_cap <= 0.001:
                    continue

                # Obligatorischer Transfer: bis zu 80% des Surplus abgeben
                elec_share = min(elec_surplus[surplus_node] * 0.80, ed, remaining_cap)
                heat_share = min(heat_surplus[surplus_node] * 0.80, hd,
                                 remaining_cap - elec_share)

                if elec_share > 0.001 or heat_share > 0.001:
                    transfers[deficit_node]['elec']         += elec_share
                    transfers[deficit_node]['heat']         += heat_share
                    transfers[deficit_node]['is_mandatory']  = True
                    elec_surplus[surplus_node] -= elec_share
                    heat_surplus[surplus_node] -= heat_share
                    line_load[cap_key]         += elec_share + heat_share
                    ed -= elec_share
                    hd -= heat_share

                    self.mandatory_transfers.append(elec_share + heat_share)
                    self.total_transfers.append(elec_share + heat_share)

        # ── Runde 2: Freiwillige Bedarfs-Transfers (kein Krisenstatus nötig) ─
        for deficit_node in NODES:
            ed = max(0.0, elec_deficit[deficit_node] - transfers[deficit_node]['elec'])
            hd = max(0.0, heat_deficit[deficit_node] - transfers[deficit_node]['heat'])
            if ed <= 0.001 and hd <= 0.001:
                continue

            for surplus_node in sorted(NODES,
                                       key=lambda n: elec_surplus[n] + heat_surplus[n],
                                       reverse=True):
                if surplus_node == deficit_node:
                    continue
                cap_key = (surplus_node, deficit_node)
                if cap_key not in CAPACITY:
                    continue
                remaining_cap = CAPACITY[cap_key] - line_load.get(cap_key, 0.0)
                if remaining_cap <= 0.001:
                    continue

                elec_share = min(elec_surplus[surplus_node] * 0.50, ed, remaining_cap)
                heat_share = min(heat_surplus[surplus_node] * 0.50, hd,
                                 remaining_cap - elec_share)

                if elec_share > 0.001 or heat_share > 0.001:
                    transfers[deficit_node]['elec'] += elec_share
                    transfers[deficit_node]['heat'] += heat_share
                    elec_surplus[surplus_node] -= elec_share
                    heat_surplus[surplus_node] -= heat_share
                    line_load[cap_key]         += elec_share + heat_share
                    ed -= elec_share
                    hd -= heat_share
                    self.total_transfers.append(elec_share + heat_share)

        return {n: {'transfer_in_elec': transfers[n]['elec'],
                    'transfer_in_heat': transfers[n]['heat']}
                for n in NODES}, line_load

    @property
    def solidarity_index(self):
        """Anteil Pflicht-Transfers an Gesamt-Transfers (nur Cybersyn)."""
        total = sum(self.total_transfers)
        if total < 0.001:
            return 0.0
        return sum(self.mandatory_transfers) / total


class MarketMetaController:
    """
    Markt-Koordinator.
    Transfers nur bei positivem Preisspreiz (> 10 EUR/MWh Schwelle).
    Keine Solidaritätspflicht.
    """
    def __init__(self, spread_threshold=0.01):
        """spread_threshold in GWh-Äquivalent (0.01 = 10 EUR/MWh)."""
        self.spread_threshold = spread_threshold
        self.total_transfers  = []

    def coordinate(self, timestamp, node_results: dict):
        """
        Koordiniert marktbasierte Transfers.
        Kein Zwang – nur wenn Preisspreiz vorhanden und Surplus verfügbar.
        """
        elec_surplus = {n: node_results[n]['elec_surplus'] for n in NODES}
        elec_deficit = {n: node_results[n]['elec_deficit'] for n in NODES}
        heat_surplus = {n: node_results[n]['heat_surplus'] for n in NODES}
        heat_deficit = {n: node_results[n]['heat_deficit'] for n in NODES}

        transfers = {n: {'elec': 0.0, 'heat': 0.0} for n in NODES}
        line_load = {k: 0.0 for k in CAPACITY}

        for deficit_node in NODES:
            ed = elec_deficit[deficit_node]
            hd = heat_deficit[deficit_node]
            if ed <= self.spread_threshold and hd <= self.spread_threshold:
                continue  # Kein signifikanter Bedarf → kein Marktanreiz

            for surplus_node in NODES:
                if surplus_node == deficit_node:
                    continue
                cap_key = (surplus_node, deficit_node)
                if cap_key not in CAPACITY:
                    continue
                remaining_cap = CAPACITY[cap_key] - line_load.get(cap_key, 0.0)
                if remaining_cap <= 0.001:
                    continue

                # Markt: max 40% des Surplus (Rest für eigene Preisoptimierung)
                elec_share = min(elec_surplus[surplus_node] * 0.40, ed, remaining_cap)
                heat_share = min(heat_surplus[surplus_node] * 0.40, hd,
                                 remaining_cap - elec_share)

                if elec_share > 0.001 or heat_share > 0.001:
                    transfers[deficit_node]['elec'] += elec_share
                    transfers[deficit_node]['heat'] += heat_share
                    elec_surplus[surplus_node] -= elec_share
                    heat_surplus[surplus_node] -= heat_share
                    line_load[cap_key]         += elec_share + heat_share
                    ed -= elec_share
                    hd -= heat_share
                    self.total_transfers.append(elec_share + heat_share)

        return {n: {'transfer_in_elec': transfers[n]['elec'],
                    'transfer_in_heat': transfers[n]['heat']}
                for n in NODES}, line_load
