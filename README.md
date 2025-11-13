# Desert Storm Roster Optimizer

Ein Python-Tool, das aus Event-CSV-Dateien die Anwesenheitswahrscheinlichkeit pro Spieler schätzt
und daraus eine optimale Aufstellung (A/B) für das Desert Storm Event berechnet.

## Gruppen-Präferenzen

Die Datei `data/alliance.csv` kann optionale Präferenzspalten enthalten, um Gruppenwünsche zu
berücksichtigen:

```
PlayerName,Active,PrefGroup,PrefMode,PrefBoost
itsH4K1,1,A,hard,
Cupra290,1,B,soft,0.08
Mahaja,1,,,
```

- `PrefGroup` wählt die Wunschgruppe (`A` oder `B`).
- `PrefMode = hard` erzwingt die Zuteilung in die Wunschgruppe, außer andernfalls bliebe eine
  Gruppe dauerhaft unterbesetzt.
- `PrefMode = soft` bevorzugt die Wunschgruppe, erlaubt aber Wechsel bei Kapazitätskonflikten.
- `PrefBoost` erhöht den Score nur in der Wunschgruppe (Standard: `0.05`, wenn leer).

## Admin: Events hochladen (Tabellen-UI)

Für Eventdaten steht unter `docs/admin/events.html` eine eigenständige Tabellenoberfläche bereit:

- Öffne die Seite direkt im Browser (kein Build erforderlich).
- CSVs können via Drag & Drop oder aus der Zwischenablage importiert werden; Event-IDs werden bei passenden Dateinamen automatisch erkannt.
- Die Tabelle erzwingt das Schema `EventID,Slot,PlayerName,RoleAtRegistration,Teilgenommen,Punkte,Warnungen`.
- Event-IDs müssen dem Format `DS-YYYY-MM-DD-A/B` entsprechen; Slots (1–30), Rollen (`Start`/`Ersatz`), Teilnahmen (0/1) und Punkte (≥0) werden live validiert.
- Wähle den Ziel-Branch (`main`, `ops/events` oder einen Custom-Branch) und die Commit-Strategie (`replace`, `merge`, `abort-if-exists`).
- Speichern erfolgt über den Worker-Endpunkt (Standard `/write-file`) mittels Commit `data/<EventID>.csv`; bei `main` löst der bestehende Workflow automatisch Builds aus.
- Der Button „Roster neu bauen“ triggert optional `/dispatch` (workflow_dispatch) und verlinkt den Actions-Run.
