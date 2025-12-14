# Desert Storm Roster Optimizer

Ein Python-Tool, das Event-Historien der Allianz im „Desert Storm“-Event analysiert, Empirical-Bayes-No-Show-
Schätzungen berechnet und daraus deterministische Aufstellungen (A/B, Start/Ersatz) ableitet.

## Kurzüberblick

- **Zweck**: Verlässliche Aufstellungen und Risiko-Metriken für das MMO-Event „Last War – Desert Storm“
  inkl. Präferenzen, Abwesenheiten und Alias-Auflösung.
- **Technik**: Python-CLI (`src/main.py`) produziert strukturierte JSON/CSV-Exports, GitHub Actions
  hält `out/latest.*` aktuell und GitHub Pages (`docs/`) visualisiert die Ergebnisse.

## Build & Outputs

- **Lokal bauen**
  1. Dependencies installieren: `pip install -r requirements.txt`
  2. Builder starten: `python -m src.main`
  3. Die CLI liest alle CSVs aus `data/` (Events, `alliance.csv`, `aliases.csv`, `absences.csv`, …)
     und schreibt neue Artefakte nach `out/`.
- **CI**: `.github/workflows/roster.yml` führt denselben Schritt auf `main` aus, sobald sich Daten
  ändern. Weitere Workflows räumen alte Artefakte auf oder validieren `latest.json`.
  - Der Commit-Step rebased automatische Builds vor dem Push auf den aktuellen Stand von `main`
    und versucht den Push bei Bedarf bis zu drei Mal – so bleiben die generierten Artefakte
    push-bar, selbst wenn parallel noch andere Commits auflaufen.
  - **How to verify**: Zwei schnelle Änderungen an den Event-Zusagen (jeweils „Roster neu bauen“
    aus dem Admin-Tab anstoßen) erzeugen zwei Actions-Runs, die beide grün durchlaufen sollten.
    Nach jedem Run zeigt `docs/out/latest.json`/`latest.csv` den aktuellen Stand auf GitHub Pages.
- **Wichtige Artefakte (`out/`)**
  - `latest.json` – Quelle der Web-UIs (Roster, Dashboard)
  - `latest.csv` / `roster.csv` – tabellarischer Export je Spieler/Slot
  - `alias_suggestions.csv`, `missing_noshow_report.csv` – Diagnose für Datenpflege
  - `name_warnings.json` – Hinweise für unaufgelöste oder mehrdeutige Namen

### Next-Event-Signups und harte Zusagen (`data/event_signups_next.csv`)

- Wird in `src/main.py` über `_load_event_signups()` eingelesen. Spalten:
  `PlayerName,Group,Role,Commitment,Source,Note` (Commitment default `none`).
- `Commitment = hard` kennzeichnet verbindliche Zusagen: Spieler werden – sofern aktiv,
  in der Allianz und nicht abwesend – **vor** dem Optimizer in den Roster gesetzt.
  `Commitment = none` bedeutet „keine Zusage/Overlay“.
- `Source` dokumentiert den Kanal der Zusage (z. B. `ingame`, `dm`, `manual`,
  `callup-confirmed`) und kann in der Admin-UI bearbeitet werden.
- Standard-Modus: `HARD_SIGNUPS_ONLY: true` (Default in `roster.yml`, per Env-Var
  `HARD_SIGNUPS_ONLY=1` überschreibbar) lässt den Optimizer nur noch mit harten
  Zusagen starten. Slots ohne Zusage bleiben leer; kein automatisches Auffüllen
  aus Allianz-/Callup-Pool.
- Überbuchungen werden nicht heimlich verworfen: `overbooked_forced_signups` in
  `out/latest.json` dokumentiert, wenn mehr harte Zusagen existieren als Slots.
- Einträge ohne `Commitment = hard` bleiben Overlays/Badges (`event_signup`) oder tauchen als
  `extra_signups` unterhalb der Gruppen auf.
- `out/latest.json.signup_pool` enthält zusätzlich zu den Legacy-Zählern nun ein Feld
  `stats` (u. a. `file_entries_total`, `hard_commit_total`, `forced_in_roster`,
  `forced_out_of_roster`) sowie die Listen `forced_signups`,
  `invalid_forced_signups`, `overbooked_forced_signups` und `file_entries`
  (Diagnose aller CSV-Zeilen inkl. Status `forced` / `info_only` / `invalid`).
- Änderungen an `data/event_signups_next.csv` landen nach dem nächsten Build (`python -m src.main`
  lokal oder GitHub Actions auf `main`/`feat/**`) in `out/latest.json`. Der „Roster neu bauen“-Button
  im Admin-Tab „Events erfassen“ triggert optional denselben Workflow-Dispatch.
- Der Admin-Tab „Event-Zusagen“ zeigt zusätzlich den Sync-Status (CSV vs. `latest.json`) und enthält
  einen Button „Roster neu bauen (nächstes Event)“. So lässt sich direkt aus dem Pool-Editor
  derselbe Workflow-Dispatch starten, sobald neue Zusagen übernommen werden sollen.

#### How to verify (Gruppenwechsel)

1. Vorhandene Zusage in `docs/admin/event-assignments.html` öffnen, die aktuell in Gruppe B steht.
2. Gruppe auf A umstellen und speichern.
3. Roster-Build anstoßen/warten.
4. Admin-Tab neu laden: Die Zusage erscheint jetzt mit Gruppe A, ohne dass alte Roster-Daten die Auswahl überschreiben.

### Roster-Build aus der Admin-UI auslösen

- Sowohl der Button „Roster neu bauen“ im Events-Tab als auch „Roster neu bauen (nächstes Event)“
  im Zusagen-Editor sprechen den Cloudflare-Worker
  `https://ds-commit.hak1.workers.dev/dispatch` per `POST` an. Der Request enthält `ref` (Branch),
  einen `reason`-String und denselben Admin-Key wie der Schreib-Endpunkt (`X-Admin-Key`). Der Worker
  ruft anschließend den GitHub-API-Endpunkt `workflow_dispatch` für `Build Rosters` auf und liefert
  die Actions-URL zurück.
- Änderungen an `data/event_signups_next.csv` werden dadurch erst nach Abschluss des Workflows in
  `out/latest.json` sichtbar; die Admin-Seite weist solange auf ausstehende Builds hin.
- Alternativ lässt sich der Build jederzeit manuell via GitHub Actions starten: Repository öffnen,
  Tab **Actions** → Workflow **Build Rosters** → **Run workflow** klicken und den Ziel-Branch wählen.

## UIs & Admin-Tools

Alle Oberflächen liegen statisch im Ordner `docs/` und können entweder über GitHub Pages
(`https://its-h4k1.github.io/desert-storm-roster-optimizer/…`) oder lokal per
`python -m http.server 4173 --directory docs` geöffnet werden (danach `http://localhost:4173`).
Jede Seite lädt die Daten direkt aus dem Repo (`out/latest.json`, `data/*.csv`) und benötigt daher
keinen Build-Schritt.

> Mehr Details zu Layout und Erweiterungsregeln stehen in [`docs/ADMIN-UI.md`](docs/ADMIN-UI.md).

### Haupt-Roster-Ansicht (`docs/index.html`)

- Zeigt die aktuellen Start- und Ersatzaufstellungen für Gruppen A/B inkl. No-Show-Metriken.
- Lädt `out/latest.json` (Standard-Branch `main`, per `?branch=<name>` überschreibbar) von
  `raw.githubusercontent.com` und rendert vollständig clientseitig.
- Lokal: `http://localhost:4173/index.html` (Server siehe oben).

### Callup-Logik & CSV-Export

- Die Callup-Regeln liegen versioniert in `data/callup_config.yml` (YAML/JSON). Felder (Defaults entsprechen der bisherigen
  Logik):
  - `min_events = 3` (ab hier werden Rolling/Overall-Raten ernst genommen)
  - `low_n_max_events = 2` (≤2 Events werden vorsorglich als Callup markiert)
  - `high_overall_threshold = 0.40` (overall ≥40 % löst Callup aus)
  - `high_rolling_threshold = 0.50` (rolling ≥50 % löst Callup aus)
  - `rolling_uptick_min = 0.25` + `rolling_uptick_delta = 0.10` (rolling mindestens 25 % und ≥10 pp über overall)
- Die Werte lassen sich vollständig im Admin-Tab „Callup-Assistent“ pflegen (Bereich „Callup-Regeln“). Dort können die Schwellen
  geladen, angepasst, auf Standardwerte zurückgesetzt und direkt in `data/callup_config.yml` geschrieben werden.
- Der Builder lädt die Datei beim Start. Fehlende Datei oder Felder → Defaults + Warnung, Build läuft weiter. Die genutzte
  Konfiguration landet als Snapshot in `callup_stats.config_snapshot` (inkl. `config_source` für Metadaten), sodass UIs die
  Schwellen anzeigen können.
- Rolling wird stärker gewichtet: Sowohl „high rolling“ als auch „rolling uptick“ können eine Empfehlung auslösen,
  auch wenn overall noch unterhalb der 40 %-Schwelle liegt. `callup_reason` codiert u. a. `high_rolling`,
  `rolling_uptick`, `high_overall` und `low_n`; `callup_stats.reasons` zählt diese Gründe.
- Callup-Empfehlungen sind rein informativ und beeinflussen den Roster-Build nicht; die Aufstellung basiert auf
  `event_signups_next.csv` (Commitment = hard).
- In der Roster-UI steht ein Button „Callup-Kandidaten als CSV exportieren“:
  - Exportiert alle empfohlenen Spieler (laut `latest.json`) direkt aus dem geladenen Payload als CSV.
  - Spaltenreihenfolge: `PlayerName,Group,Role,EventsSeen,NoShowsTotal,NoShowOverall,NoShowRolling,CallupReason,LastSeenDate,LastNoShowDate`.
  - Nützlich, um Callup-Listen in anderen Tools weiterzugeben oder separat zu filtern.

### Admin Startseite & CSV-Tools (`docs/admin/index.html`)

- Gemeinsame Shell mit Navigation, direktem Zugriff auf `data/alliance.csv`, `data/aliases.csv`,
  `data/absences.csv` sowie einem Event-Upload.
- Unterstützt schnelles Editieren/Committen über den Cloudflare-Worker `ds-commit.hak1.workers.dev`.
- Lokal: `http://localhost:4173/admin/index.html` (setzt denselben Worker voraus wie die anderen
  Admin-Seiten).

### Events erfassen (`docs/admin/events.html`)

- Tabellen-UI für Event-Dateien (`data/<EventID>.csv`). Import via Drag & Drop oder Zwischenablage,
  Schema-Prüfung und Validierung von Slot, Rolle und Teilnahme.
- Nutzt `data/alliance.csv` und `data/aliases.csv` (lokal oder via Raw-GitHub), um Spieler zuzuordnen
  bzw. neue Aliase/Spieler vorzuschlagen. Exportiert bestätigte Events als CSV-Commits.
- Lokal: `http://localhost:4173/admin/events.html` – identisch zur GitHub-Pages-Version, solange der
  Worker-Endpunkt erreichbar ist.

### Spieler, Aliase & Absenzen (`docs/admin/players.html`)

- Verwalten von `data/alliance.csv`, `data/aliases.csv` und `data/absences.csv` inkl. Statusfeldern,
  Such-/Filterfunktionen und Abwesenheitsformularen.
- Lädt bestehende Datensätze (lokal oder via Raw-URL), erlaubt Alias-Merge, Spielerstatus-Updates und
  schreibt Änderungen zurück über denselben Worker-Commit-Flow.
- Lokal: `http://localhost:4173/admin/players.html`.

### No-Show Analyse / Dashboard (`docs/admin/noshow-dashboard.html`)

- Chart-basierte Analyse von Rolling/Overall-No-Show-Raten, Histogrammen und Gruppenvergleichen zur
  Bewertung des Empirical-Bayes-Rosters.
- Liest ausschließlich `out/latest.json` und bietet Filter nach Gruppe, Rolle, Historie etc.
- Lokal: `http://localhost:4173/admin/noshow-dashboard.html`.

## Admin-Flow (High Level)

1. Event-Rohdaten erfassen (z. B. via Screenshot→OCR→CSV); Vorlage und Schema stehen in `docs/admin/events.html`.
2. In der Events-UI CSV importieren, Namen auflösen (Alias anlegen oder Spieler hinzufügen) und das
   Event nach `data/DS-YYYY-MM-DD-<Group>.csv` committen.
3. Optional: Spieler-/Alias-/Abwesenheitsdaten in `docs/admin/players.html` pflegen.
4. Builder läuft lokal oder via GitHub Actions → neue `out/latest.*`. Ergebnis in `docs/index.html`
   (Roster) und `docs/admin/noshow-dashboard.html` (Analytics) prüfen.

## Allianz-Stammdaten

Die Datei `data/alliance.csv` hält nur noch die Kernspalten `PlayerName`, `InAlliance` und
optional `Note` bereit.

- `InAlliance` kennzeichnet die Allianz-Mitgliedschaft: `1` = Spieler ist aktuell Teil der
  Allianz (wird beim Roster berücksichtigt), `0` = Spieler ist ausgetreten bzw. entfernt
  (taucht in Berechnungen nicht mehr auf). Ältere CSVs mit `Active` werden weiter eingelesen,
  es erscheint jedoch eine Warnung mit dem Hinweis auf die neue Spalte. Das Skript
  `scripts/migrate_active_flag.py data/alliance.csv --backup` benennt alte Dateien auf Wunsch
  automatisch um.

## Admin: Events hochladen (Tabellen-UI)

Für Eventdaten steht unter `docs/admin/events.html` eine eigenständige Tabellenoberfläche bereit:

- Öffne die Seite direkt im Browser (kein Build erforderlich).
- CSVs können via Drag & Drop oder aus der Zwischenablage importiert werden; Event-IDs werden bei passenden Dateinamen automatisch erkannt.
- Die Tabelle erzwingt das Schema `EventID,Slot,PlayerName,RoleAtRegistration,Teilgenommen,Punkte,Warnungen`.
- Event-IDs müssen dem Format `DS-YYYY-MM-DD-A/B` entsprechen; Slots (1–30), Rollen (`Start`/`Ersatz`), Teilnahmen (0/1) und Punkte (≥0) werden live validiert.
- Beim Import werden Spielernamen gegen `data/alliance.csv` und `data/aliases.csv` geprüft. Unbekannte Namen lassen sich per Klick einem bekannten Spieler zuordnen, als Alias vormerken oder als neuer Spieler hinterlegen; die Seite schreibt die entsprechenden Ergänzungen bei Bedarf automatisch in `data/aliases.csv` bzw. `data/alliance.csv`.
- Vor dem Speichern erscheint eine Zusammenfassung der geplanten Änderungen (neue Aliase, neue Spieler und – sofern explizit zugelassen – offen bleibende Namen). Gespeichert werden Events erst, wenn alle Namen entschieden oder bewusst übersteuert wurden.
- Wähle den Ziel-Branch (`main`, `ops/events` oder einen Custom-Branch) und die Commit-Strategie (`replace`, `merge`, `abort-if-exists`).
- Speichern erfolgt über den Worker-Endpunkt (Standard `/write-file`) mittels Commit `data/<EventID>.csv`; bei `main` löst der bestehende Workflow automatisch Builds aus.
- Der Button „Roster neu bauen“ triggert optional `/dispatch` (workflow_dispatch) und verlinkt den Actions-Run.
