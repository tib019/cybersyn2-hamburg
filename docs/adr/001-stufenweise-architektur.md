# ADR-001: Stufenweise Systemarchitektur (Stufen 1-4)

**Status:** Accepted  
**Datum:** 2025

## Kontext
Cybersyn2-Hamburg ist ein Konzeptprojekt inspiriert vom chilenischen Cybersyn-System der 1970er. Die Entwicklung soll schrittweise erfolgen, von einfacher Datenerfassung bis zu kybernetischer Steuerung.

## Entscheidung
Vierstufige Architektur: Stufe 1 (Datenerfassung) → Stufe 2 (Analyse) → Stufe 3 (Simulation) → Stufe 4 (Steuerung).

## Abgewogene Alternativen
- **Monolithisches System:** Einfacher zu entwickeln, aber schwerer erweiterbar
- **Microservices von Anfang an:** Zu komplex für Forschungsprojekt-Phase

## Konsequenzen
**Positiv:**
- Klare Entwicklungsphasen und Meilensteine
- Jede Stufe ist unabhängig nutzbar
- Schrittweise Komplexitätssteigerung

**Negativ:**
- Interfaces zwischen Stufen müssen frühzeitig definiert werden
