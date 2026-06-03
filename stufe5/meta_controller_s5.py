"""
meta_controller_s5.py – Zweistufiger fraktaler VSM Meta-Controller
===================================================================
Stufe 5: Benelux + Norddeutschland (6 Knoten)

Hierarchie (Beer's VSM fraktal):

  Ebene 1 – Knotenebene (System 1):
    HH, SH, NDS  → Norddeutschland-Cluster
    NL, BE, LU   → Benelux-Cluster

  Ebene 2 – Cluster-Meta-Controller (System 2/3):
    DE_META  → koordiniert HH/SH/NDS (identisch zu stufe4/meta_controller.py)
    BNL_META → koordiniert NL/BE/LU

  Ebene 3 – Super-Meta-Controller (System 4/5):
    SUPER_META → koordiniert DE_META ↔ BNL_META
    Inter-Cluster-Transfers nur über Schlüssel-Leitungen:
      NDS ↔ NL: 3.8 GWh/h  (bestehend + NordLink-Erweiterung)
      SH  ↔ NL: 1.4 GWh/h  (DolWin/BorWin Offshore-Kabel)

Übertragungskapazitäten Benelux (ENTSO-E NTC 2023, GWh/h):
  NL ↔ BE:  3.5
  NL ↔ LU:  0.3
  BE ↔ LU:  0.5
  Inter-Cluster:
  NDS ↔ NL: 3.8
  SH  ↔ NL: 1.4
"""

import numpy as np
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'stufe4'))
from meta_controller import (
    CybersynMetaController as DE_CybersynMeta,
    MarketMetaController   as DE_MarketMeta,
    NODES as DE_NODES,
    CAPACITY as DE_CAPACITY,
)

BNL_NODES = ['NL', 'BE', 'LU']
ALL_NODES = ['HH', 'SH', 'NDS', 'NL', 'BE', 'LU']

# Intra-Benelux Kapazitäten (GWh/h)
BNL_CAPACITY = {
    ('NL', 'BE'): 3.5, ('BE', 'NL'): 3.5,
    ('NL', 'LU'): 0.3, ('LU', 'NL'): 0.3,
    ('BE', 'LU'): 0.5, ('LU', 'BE'): 0.5,
}

# Inter-Cluster Kapazitäten (GWh/h)
INTER_CAPACITY = {
    ('NDS', 'NL'): 3.8, ('NL', 'NDS'): 3.8,
    ('SH',  'NL'): 1.4, ('NL', 'SH'):  1.4,
}


class BeneluxAlgedonicChannel:
    """Algedonic Channel für das Benelux-Cluster."""
    def __init__(self):
        self.crisis_counters   = {n: 0 for n in BNL_NODES}
        self.solidarity_active = {n: False for n in BNL_NODES}
        self.events = []

    def update(self, timestamp, node_crisis: dict):
        for node, in_crisis in node_crisis.items():
            self.crisis_counters[node] = self.crisis_counters[node] + 1 if in_crisis else 0
            was = self.solidarity_active[node]
            self.solidarity_active[node] = self.crisis_counters[node] >= 3
            if self.solidarity_active[node] and not was:
                self.events.append({'time': str(timestamp), 'node': node,
                                    'hours': self.crisis_counters[node]})
        return dict(self.solidarity_active)


class BeneluxCybersynMeta:
    """
    Kybernetischer Meta-Controller für den Benelux-Cluster.
    Gleiche Logik wie CybersynMetaController aus stufe4,
    angepasst auf BNL_NODES und BNL_CAPACITY.
    """
    def __init__(self):
        self.alg                 = BeneluxAlgedonicChannel()
        self.mandatory_transfers = []
        self.total_transfers     = []

    def coordinate(self, timestamp, node_results: dict):
        node_crisis   = {n: node_results[n]['in_crisis'] for n in BNL_NODES}
        solidarity_req = self.alg.update(timestamp, node_crisis)

        elec_surplus = {n: node_results[n]['elec_surplus'] for n in BNL_NODES}
        elec_deficit = {n: node_results[n]['elec_deficit'] for n in BNL_NODES}
        heat_surplus = {n: node_results[n]['heat_surplus'] for n in BNL_NODES}
        heat_deficit = {n: node_results[n]['heat_deficit'] for n in BNL_NODES}

        transfers = {n: {'elec': 0.0, 'heat': 0.0} for n in BNL_NODES}
        line_load = {k: 0.0 for k in BNL_CAPACITY}

        # Runde 1: Pflicht-Solidarität
        for deficit_node in BNL_NODES:
            if not solidarity_req[deficit_node]:
                continue
            ed, hd = elec_deficit[deficit_node], heat_deficit[deficit_node]
            for surplus_node in BNL_NODES:
                if surplus_node == deficit_node:
                    continue
                cap_key = (surplus_node, deficit_node)
                if cap_key not in BNL_CAPACITY:
                    continue
                rem = BNL_CAPACITY[cap_key] - line_load.get(cap_key, 0.0)
                if rem <= 0.001:
                    continue
                e_share = min(elec_surplus[surplus_node] * 0.80, ed, rem)
                h_share = min(heat_surplus[surplus_node] * 0.80, hd, rem - e_share)
                if e_share > 0.001 or h_share > 0.001:
                    transfers[deficit_node]['elec'] += e_share
                    transfers[deficit_node]['heat'] += h_share
                    elec_surplus[surplus_node] -= e_share
                    heat_surplus[surplus_node] -= h_share
                    line_load[cap_key]         += e_share + h_share
                    ed -= e_share; hd -= h_share
                    self.mandatory_transfers.append(e_share + h_share)
                    self.total_transfers.append(e_share + h_share)

        # Runde 2: Freiwillige Transfers
        for deficit_node in BNL_NODES:
            ed = max(0.0, elec_deficit[deficit_node] - transfers[deficit_node]['elec'])
            hd = max(0.0, heat_deficit[deficit_node] - transfers[deficit_node]['heat'])
            if ed <= 0.001 and hd <= 0.001:
                continue
            for surplus_node in sorted(BNL_NODES,
                                       key=lambda n: elec_surplus[n], reverse=True):
                if surplus_node == deficit_node:
                    continue
                cap_key = (surplus_node, deficit_node)
                if cap_key not in BNL_CAPACITY:
                    continue
                rem = BNL_CAPACITY[cap_key] - line_load.get(cap_key, 0.0)
                if rem <= 0.001:
                    continue
                e_share = min(elec_surplus[surplus_node] * 0.50, ed, rem)
                h_share = min(heat_surplus[surplus_node] * 0.50, hd, rem - e_share)
                if e_share > 0.001 or h_share > 0.001:
                    transfers[deficit_node]['elec'] += e_share
                    transfers[deficit_node]['heat'] += h_share
                    elec_surplus[surplus_node] -= e_share
                    heat_surplus[surplus_node] -= h_share
                    line_load[cap_key]         += e_share + h_share
                    ed -= e_share; hd -= h_share
                    self.total_transfers.append(e_share + h_share)

        return (
            {n: {'transfer_in_elec': transfers[n]['elec'],
                 'transfer_in_heat': transfers[n]['heat']} for n in BNL_NODES},
            line_load
        )

    @property
    def solidarity_index(self):
        total = sum(self.total_transfers)
        return sum(self.mandatory_transfers) / total if total > 0.001 else 0.0


class BeneluxMarketMeta:
    """Markt-Koordinator für Benelux (kein Solidaritätszwang)."""
    def __init__(self, spread_threshold=0.01):
        self.spread_threshold = spread_threshold
        self.total_transfers  = []

    def coordinate(self, timestamp, node_results: dict):
        elec_surplus = {n: node_results[n]['elec_surplus'] for n in BNL_NODES}
        elec_deficit = {n: node_results[n]['elec_deficit'] for n in BNL_NODES}
        heat_surplus = {n: node_results[n]['heat_surplus'] for n in BNL_NODES}
        heat_deficit = {n: node_results[n]['heat_deficit'] for n in BNL_NODES}
        transfers = {n: {'elec': 0.0, 'heat': 0.0} for n in BNL_NODES}
        line_load = {k: 0.0 for k in BNL_CAPACITY}

        for deficit_node in BNL_NODES:
            ed, hd = elec_deficit[deficit_node], heat_deficit[deficit_node]
            if ed <= self.spread_threshold and hd <= self.spread_threshold:
                continue
            for surplus_node in BNL_NODES:
                if surplus_node == deficit_node:
                    continue
                cap_key = (surplus_node, deficit_node)
                if cap_key not in BNL_CAPACITY:
                    continue
                rem = BNL_CAPACITY[cap_key] - line_load.get(cap_key, 0.0)
                if rem <= 0.001:
                    continue
                e_share = min(elec_surplus[surplus_node] * 0.40, ed, rem)
                h_share = min(heat_surplus[surplus_node] * 0.40, hd, rem - e_share)
                if e_share > 0.001 or h_share > 0.001:
                    transfers[deficit_node]['elec'] += e_share
                    transfers[deficit_node]['heat'] += h_share
                    elec_surplus[surplus_node] -= e_share
                    heat_surplus[surplus_node] -= h_share
                    line_load[cap_key]         += e_share + h_share
                    ed -= e_share; hd -= h_share
                    self.total_transfers.append(e_share + h_share)

        return (
            {n: {'transfer_in_elec': transfers[n]['elec'],
                 'transfer_in_heat': transfers[n]['heat']} for n in BNL_NODES},
            line_load
        )


class SuperMetaController:
    """
    System 4/5 des fraktalen VSM.
    Koordiniert Inter-Cluster-Transfers zwischen DE_CLUSTER und BNL_CLUSTER.
    Entscheidet ob und wie viel Energie zwischen Norddeutschland und Benelux
    über NDS↔NL und SH↔NL fließt.
    """
    def __init__(self, mode='cybersyn'):
        self.mode             = mode
        self.inter_transfers  = []
        self.inter_mandatory  = []
        # Inter-Cluster Leitungsauslastung
        self.inter_line_load  = {k: 0.0 for k in INTER_CAPACITY}

    def coordinate_inter(
        self, timestamp,
        de_cluster_surplus: dict,   # {'elec': float, 'heat': float}
        bnl_cluster_surplus: dict,
        de_cluster_crisis: bool,
        bnl_cluster_crisis: bool,
    ) -> tuple:
        """
        Entscheidet über Inter-Cluster-Transfers.
        Gibt zurück: (de_export_gwh, bnl_import_gwh)
        """
        # Verfügbare Inter-Cluster-Kapazität
        cap_nds_nl = INTER_CAPACITY[('NDS', 'NL')]
        cap_sh_nl  = INTER_CAPACITY[('SH',  'NL')]
        total_inter_cap = cap_nds_nl + cap_sh_nl

        de_export = 0.0
        bnl_export = 0.0

        if self.mode == 'cybersyn':
            # Pflicht-Solidarität bei Clusterkrise
            if bnl_cluster_crisis and de_cluster_surplus['elec'] > 0.5:
                transfer = min(
                    de_cluster_surplus['elec'] * 0.70,
                    total_inter_cap
                )
                de_export = transfer
                self.inter_mandatory.append(transfer)
                self.inter_transfers.append(transfer)
            elif de_cluster_crisis and bnl_cluster_surplus['elec'] > 0.5:
                transfer = min(
                    bnl_cluster_surplus['elec'] * 0.70,
                    total_inter_cap
                )
                bnl_export = transfer
                self.inter_mandatory.append(transfer)
                self.inter_transfers.append(transfer)
            else:
                # Freiwilliger Ausgleich
                net_surplus_de  = de_cluster_surplus['elec']
                net_surplus_bnl = bnl_cluster_surplus['elec']
                if net_surplus_de > net_surplus_bnl + 0.5:
                    transfer = min((net_surplus_de - net_surplus_bnl) * 0.30, total_inter_cap)
                    de_export = transfer
                    self.inter_transfers.append(transfer)
                elif net_surplus_bnl > net_surplus_de + 0.5:
                    transfer = min((net_surplus_bnl - net_surplus_de) * 0.30, total_inter_cap)
                    bnl_export = transfer
                    self.inter_transfers.append(transfer)
        else:  # market
            # Nur bei starkem Preisspreiz
            net_de  = de_cluster_surplus['elec']
            net_bnl = bnl_cluster_surplus['elec']
            spread  = abs(net_de - net_bnl)
            if spread > 1.0:  # min. 1 GWh/h Differenz
                if net_de > net_bnl:
                    de_export = min(net_de * 0.25, total_inter_cap)
                else:
                    bnl_export = min(net_bnl * 0.25, total_inter_cap)
                self.inter_transfers.append(max(de_export, bnl_export))

        return de_export, bnl_export

    @property
    def solidarity_index(self):
        total = sum(self.inter_transfers)
        return sum(self.inter_mandatory) / total if total > 0.001 else 0.0
