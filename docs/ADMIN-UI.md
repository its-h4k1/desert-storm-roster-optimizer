# Admin UI Leitplanken

## 1. Ziele
- Einheitliches Erscheinungsbild und Layout für alle Admin-Seiten (CSV-Konsole, Events, Spieler/Aliase, No-Show Analyse).
- Gemeinsame Navigations-Shell als klarer Einstiegspunkt mit Links zu allen Bereichen.
- Gute Lesbarkeit auf Desktop & Tablet, inkl. Sticky-Header und responsiver Navigation.
- Gemeinsame Grund-Styles (Buttons, Panels, Tabellen), damit neue Tools schnell eingebettet werden können.

## 2. Struktur
- **Header**: Oben fixiert, enthält das Branding „ELT Admin“, optionale Status-Pills (z. B. Environment/Login) und einen Link zurück zur Haupt-Roster-Ansicht (`../index.html`).
- **Navigation** (`.admin-nav`): Linke Sidebar (bei kleinen Screens als horizontale Liste) mit Links zu:
  - „CSV & Datei-Tools“ (`index.html`)
  - „Events erfassen“ (`events.html`)
  - „Spieler & Aliase“ (`players.html`)
  - „No-Show Analyse“ (`noshow-dashboard.html`)
- **Content** (`.admin-content`): rechter Bereich mit Seiten-spezifischem Inhalt. Panels nutzen `.admin-section` oder `.panel` sowie `card-grid` für Kennzahlen.

## 3. Design-Richtlinien
- **Typografie**: `Inter`/System-UI, helle Schrift auf dunklem Hintergrund. Überschriften nutzen `h1/h2` innerhalb der Content-Fläche.
- **Buttons**: Grundklasse `.btn`, Varianten `.pri`, `.ok`, `.err`, `.ghost` (optional). Buttons sind leicht abgerundet und reagieren beim Hover.
- **Panels/Cards**: `.admin-section`, `.panel`, `.card` teilen sich Border-Radius (≥16px), dunklen Hintergrund, dezente Ränder und Schatten.
- **Tabellen**: innerhalb `.table-wrapper`, Kopfzeile uppercase + dezente Linien. Zebra-Streifen + Hover-Highlight.
- **Spacing**: Content erhält `clamp(1rem,4vw,2.5rem)` Padding. Grid/Row-Helfer (`.row`, `.two`, `.card-grid`) strukturieren Eingabeformulare.

## 4. Technik
- **CSS**: `docs/admin/admin.css` enthält alle globalen Styles (Layout, Buttons, Panels, Tabellen, Typografie). Seite-spezifische Styles verbleiben inline oder in eigenen Dateien, greifen aber auf die Basis-Klassen zurück.
- **JavaScript**: `docs/admin/admin.js` markiert automatisch den aktiven Menüpunkt anhand des aktuellen Pfades und kann künftig weitere Shell-Helfer beherbergen.
- **Einbindung**: Jede Admin-Seite lädt `admin.css` und `admin.js` und rendert die gemeinsame Shell-Struktur (`.admin-shell` → `.admin-header` + `.admin-layout`).

## 5. Aktueller UI-Bestand

| Seite | Zweck | Datenquellen |
| --- | --- | --- |
| `docs/index.html` | Öffentliche Roster-Ansicht für Gruppen A/B, inklusive No-Show-Trends, Player-Meta-Toggle und Links zu Admin-Tools. | Lädt `out/latest.json` (Standard `main`, optional `?branch=`) von `raw.githubusercontent.com`.
| `docs/admin/index.html` | Shell-Einstieg, Tab-Tools für Allianz-, Alias-, Event- und Abwesenheits-Dateien. Dient als Fallback, falls spezialisierte Admin-UIs nicht genügen. | Liest/Schreibt direkt `data/alliance.csv`, `data/aliases.csv`, `data/absences.csv` und Event-CSVs via Worker-API.
| `docs/admin/events.html` | Tabellenbasiertes Erfassen/Validieren von Events, inkl. Alias-Resolver, Auto-Vervollständigung und Commit-Flow. | Liest `data/alliance.csv`, `data/aliases.csv` (lokal oder Raw-URLs) und speichert `data/<EventID>.csv`.
| `docs/admin/players.html` | Pflege von Spielerstatus, Aliases und Abwesenheiten mit Detailpanelen und Modal-Editoren. | Verwaltet `data/alliance.csv`, `data/aliases.csv`, `data/absences.csv`.
| `docs/admin/noshow-dashboard.html` | Analytisches Dashboard mit Filtern, Histogrammen und Rolling-vs-Overall KPIs. | Lädt `out/latest.json` (aktuellster Build).

> Wenn neue Admin- oder Analyse-Seiten entstehen, bitte hier kurz Zweck & Datenquellen ergänzen und in der README verlinken.
