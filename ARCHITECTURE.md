# Architekturüberblick

Das Projekt "Desert Storm Roster Optimizer" automatisiert die Einsatzplanung für die Allianz im MMO-Eventzyklus "Last War Desert Storm". Aus unterschiedlichen CSV-Quellen erzeugt das Tool deterministische Start- und Ersatzaufstellungen, die zuverlässig mit Historie, Präferenzen und Risiko-Metriken abgeglichen werden. So lassen sich wiederkehrende Event-Rosters für mehrere Gruppen konsistent pflegen.

Ziel ist eine reproduzierbare Pipeline, die vorhandene Event-Historien, Abwesenheiten und Spielerpräferenzen in strukturierte JSON- und CSV-Outputs übersetzt. Diese Outputs treiben sowohl die interaktive Webansicht als auch analytische Auswertungen und können per GitHub Actions vollautomatisch neu generiert werden.

## Ordnerstruktur & Hauptmodule

- `src/` – Python-Code für Rosterbau, Statistiken und Hilfsfunktionen.
  - `src/main.py` orchestriert den CLI-Einstieg: Argument-Parsing, Laden der CSV-Quellen, Aufruf von Statistik- und Builder-Komponenten sowie Schreiben der Ergebnisse.
  - `src/stats.py` bündelt Metrik-Berechnung (No-Show-Raten, Empirical-Bayes-Schätzung) und Historienaufbereitung für Spieler und Teams.
  - `src/utils.py` enthält den deterministischen Roster-Builder inklusive Slot-Optimierung, Präferenzauswertung, Alias-Mapping und Score-Berechnung.
  - `src/config.py` stellt die konfigurierbaren Parameter wie Gruppen, Slots, Prior-Settings und Filtern bereit.
  - `src/debug_missing_metrics.py` dient zur Diagnose: Es prüft Event-Dateien und markiert Spieler mit fehlenden oder inkonsistenten Metriken.
  - `src/alias_utils.py` bündelt die zentrale Alias-Logik (Normalisierung, Konfliktprüfung, Laden von Alias-Tabellen).
- `data/` – Eingabedateien (Allianzdaten, Alias-Definitionen, Event-Historien, Präferenzen, Abwesenheiten) als CSV.
- `out/` – Generierte Ergebnisse (`latest.csv`, `latest.json` und historische Snapshots).
- `docs/` – GitHub-Pages-Frontend, das den aktuellen Roster-Export rendert.
- `.github/workflows/` – CI-Automatisierungen (Roster-Build, Aufräumen der Outputs, Validierungen).

## Datenfluss

1. CSV-Quellen in `data/` (Event-Logs, alliance.csv, aliases.csv, absences.csv, preferences.csv) werden durch `src/main.py` geladen und normalisiert.
2. `src/stats.py` berechnet No-Show-Metriken, Team-Priors und Empirical-Bayes-Korrekturen, die `src/utils.py` anschließend in die Roster-Optimierung einspeist.
3. Der Builder erzeugt deterministische Zuweisungen für Start- und Ersatzslots je Gruppe. Ergebnisse werden als `out/latest.csv` und `out/latest.json` persistiert.
4. Die Weboberfläche `docs/index.html` lädt `out/latest.json` (über `fetch` von `raw.githubusercontent.com`), rendert Tabellen pro Gruppe und zeigt No-Show-Trends, Tooltipps und Farblegenden an. GitHub Pages hostet diese statische Seite direkt aus dem `docs/`-Ordner.

## Metriken & No-Show/EB-Logik (High-Level)

- **NoShowOverall**: Langfristige Fehlzeitenquote aus der kompletten Historie, gewichtet nach Event-Recency. Liefert robuste Grundwahrscheinlichkeiten.
- **NoShowRolling**: Kurzfristige Sicht auf aktuelle Abweichungen, mit stärkerem Gewicht auf den letzten Einsätzen. Reagiert schneller auf Trendwechsel.
- **Team-Prior**: Allianzweiter Basiswert, der für Spieler mit wenig Historie als Startpunkt dient und in die Empirical-Bayes-Schätzung einfließt.
- **Empirical-Bayes-Risiko**: Kombination aus Prior und beobachteter No-Show-Historie; reduziert Ausreißer durch Shrinkage und liefert stabilere Risikoscores für den Builder.

## Metriken im Export (latest.json / latest.csv)

Jeder Spieler im Export hat ein Set an Kernmetriken, die für Auswertung und UI verwendet werden:

- `NoShowOverall`  
  Langfristige No-Show-Rate über alle berücksichtigten Events.  
  - Basis: alle vergangenen Einsätze (Start/Ersatz), mit historischer Gewichtung.  
  - Interpretation: „Wie oft ist dieser Spieler typischerweise *nicht* erschienen?“  
  - Wertbereich: 0.0–1.0 (0 = immer da, 1 = immer fehlend).

- `NoShowRolling`  
  „Frischere“ No-Show-Rate mit stärkerem Fokus auf die letzten Events.  
  - Basis: dieselben Events wie bei `NoShowOverall`, aber mit stärkerem Gewicht auf jüngeren Events
    (exponentieller Zerfall).  
  - Interpretation: „Wie verhält sich der Spieler *aktuell* in letzter Zeit?“  
  - Wertbereich: 0.0–1.0 (wie oben), kann sich schneller ändern als `NoShowOverall`.

- `risk_penalty`  
  Risikozuschlag, der vom Builder intern genutzt wird, um riskantere Spieler zu benachteiligen.  
  - Basis: Empirical-Bayes-Schätzung der No-Show-Wahrscheinlichkeit (inkl. Prior), kombiniert mit der
    Verlässlichkeit der Daten (Sample Size, Rolling vs. Overall).  
  - Interpretation: „Wie viel Risiko bringt dieser Spieler relativ zum Team-Durchschnitt?“  
  - Wertbereich: typischerweise 0.0–~0.4  
    - 0.0 ≈ kein zusätzlicher Risikostrafpunkt  
    - höherer Wert = Spieler wird im Roster leicht nach hinten priorisiert  
  - Verwendung: fließt als **Penalty** in die Score-Berechnung des Roster-Builders ein  
    (höherer `risk_penalty` → geringere Chance auf Startplatz bei knappen Slots).

Diese Felder sind ausschließlich als **Risikomodelle** gedacht und sollen nicht „eins zu eins“ als Skill- oder Leistungsindikator interpretiert werden. Der Builder nutzt sie, um bei knappen Plätzen die Kombination aus Zuverlässigkeit und Präferenzen möglichst fair und deterministisch zu optimieren.

## Automatisierung & GitHub Pages

- **Build Rosters** (`.github/workflows/roster.yml`): Baut den Roster auf GitHub Actions, installiert Dependencies, führt `python -m src.main` aus und pusht aktualisierte `out/`-Artefakte zurück auf `main`.
- **purge-out** (`.github/workflows/purge-out.yml`): Bereinigt historische Outputs in `out/`, sodass nur die aktuellen `latest.*`-Dateien versioniert bleiben.
- **validate_latest**: Skriptgestützte Prüfung (Workflow/Manual Run) des Exports, das die Struktur von `out/latest.json` und `out/latest.csv` verifiziert, bevor Deployments erfolgen.
- **GitHub Pages**: Aktiviert über „Deploy from branch“ und verweist auf den `docs/`-Ordner; die Seite holt bei jedem Laden die aktuellen JSON-Daten vom Repository und visualisiert sie ohne Build-Schritt.

