# Cybersyn 2.0 – Kybernetisches Energiesteuerungsmodell Hamburg

> *"Informatik ist das Werkzeug zur Konstruktion einer klassenlosen Gesellschaft."*  
> Inspiriert von Stafford Beer, *Brain of the Firm* (1972)

Ein laufendes kybernetisches Modell, das beweist: **Bedarf + Kapazität schlagen Preis + Profit** – auf jeder Skalierungsebene.

---

## Das Argument

| Stufe | Daten | Methode | Cybersyn Defizit | Markt Defizit | Reduktion |
|---|---|---|---|---|---|
| **1** | Eurostat Jahreswerte 1990–2024 | PI-Regler | 2.563 GWh | 6.411 GWh | **–60%** |
| **2** | SMARD Stundenwerte 2022–2023 | PI + Algedonic Channel | 200 GWh | 1.705 GWh | **–88%** |
| **3** | SMARD + Open-Meteo 2022–2023 | MPC 72h + Sektorkopplung | 482 GWh | 2.958 GWh | **–84%** |

Kältewelle-Stresstest (-15°C, 72h): **Cybersyn 86,2% vs. Markt 63,8%** Versorgungsrate.

---

## Projektstruktur

```
cybersyn2-hamburg/
├── stufe1/              # Jahreswerte, PI-Regler, Stabilitätsanalyse
│   ├── cybersyn_hamburg.py
│   ├── stability_analysis.py
│   └── BERICHT_STUFE1.pdf
├── stufe2/              # Stundenwerte, Algedonic Channel
│   ├── cybersyn_stufe2.py
│   ├── fetch_smard_v2.py
│   ├── visualize_stufe2.py
│   └── BERICHT_STUFE2.pdf
├── stufe3/              # Sektorkopplung: Strom + Wärme + Verkehr
│   ├── cybersyn_hamburg_s3.py   # Hauptsimulation
│   ├── mpc_controller.py        # MPC-Regler (72h Vorausschau)
│   ├── sector_coupling.py       # Algedonic Channel + Marktmodell
│   ├── weather_api.py           # Open-Meteo Wetterdaten
│   ├── visualize_stufe3.py      # Visualisierungen
│   └── BERICHT_STUFE3.pdf
└── data/
    ├── hamburg_electricity_data.csv   # Eurostat (Stufe 1)
    ├── stufe2/hamburg_hourly_v2.csv   # SMARD stündlich (Stufe 2+3)
    └── stufe3/sector_data.csv         # Wetter + Sektordaten
```

---

## Schnellstart

```bash
# Abhängigkeiten
pip install pandas numpy matplotlib plotly requests

# Stufe 1 ausführen
python stufe1/cybersyn_hamburg.py

# Stufe 2: SMARD-Daten laden (dauert ~5 Min)
python stufe2/fetch_smard_v2.py
python stufe2/cybersyn_stufe2.py

# Stufe 3: Vollständige Simulation
python stufe3/cybersyn_hamburg_s3.py
python stufe3/visualize_stufe3.py
```

---

## Theoretische Grundlage

Das Modell basiert auf Stafford Beers **Viable System Model (VSM)** und dem **Algedonic Channel** – einem Notfallsignal, das bei kritischem Systemversagen eine Prioritätshierarchie aktiviert:

1. Kritische Infrastruktur (Strom) → nie abgeworfen
2. Wärme Haushalte → Winterschutz
3. Strom Haushalte
4. E-Auto Laden → erste Lastreduktion
5. Wärme KMU → Wärme Industrie → Strom Industrie

---

## Skalierungspfad

```
Stufe 1: Hamburg, Strom, Jahreswerte          ✅
Stufe 2: Hamburg, Strom, Stundenwerte         ✅
         + Algedonic Channel
Stufe 3: Hamburg, Sektorkopplung              ✅
         (Strom + Wärme + Verkehr) + MPC 72h
Stufe 4: Norddeutschland (in Entwicklung)     🔄
         Viable System Model: Hamburg + SH + NDS
```

---

## Datenquellen

- **Eurostat** `nrg_bal_c` – Energiebilanz Deutschland 1990–2024
- **SMARD API** (Bundesnetzagentur) – Stündliche Erzeugung & Last 2022–2023
- **Open-Meteo Historical API** – Stündliche Wetterdaten Hamburg 2022–2023

---

## Referenzen

- Beer, S. (1972). *Brain of the Firm*. Herder and Herder.
- Beer, S. (1979). *The Heart of Enterprise*. Wiley.
- Medina, E. (2011). *Cybernetic Revolutionaries*. MIT Press.
