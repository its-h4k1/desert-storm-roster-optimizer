# Admin Reset-Guard Analyse

## Beobachtungen
- `resolveLastEventId` versucht zuerst `data/event_results/index.json` (Mirror und Raw), fällt danach auf `event_signups`-Meta oder `event`-Infos aus `latest.json` zurück; bei fehlender Index-Datei landet dadurch `state.eventInfo.id` (`DS-NEXT`) als letztes Event.
- `loadRoster` setzt `state.eventInfo` aus `latest.json`/`roster.json`; aktuelles `out/latest.json` enthält nur `event.id = "DS-NEXT"` und keine `event_signups`-Metadaten, sodass der Fallback ausschließlich die Planungs-ID liefert.
- Der Mirror-Check prüft bei `lastEventId = DS-NEXT` die URL `${SITE_ROOT}data/event_results/DS-NEXT.json`, die erwartungsgemäß 404 liefert und den Reset-Button sperrt.
- In `docs/data/event_results/` liegen nur echte Event-Dateien (z.B. `DS-2025-12-12.json`), aber keine `index.json`, wodurch der vorgesehene Primärpfad nie greift.

## Ableitungen
- Verfügbare Datenquellen: `out/latest.json` (Event = DS-NEXT, `event_signups` leer), `out/roster.json` (Fallback), Mirror-Dateien unter `docs/data/event_results/DS-YYYY-MM-DD.json`.
- Aktuell genutzt: `resolveLastEventId` zieht mangels Index/Meta den `event.id`-Wert (`DS-NEXT`) aus `state.eventInfo`, der aus `latest.json` stammt.

## Fix-Idee (ohne Umsetzung)
- Entweder `resolveLastEventId` so anpassen, dass `DS-NEXT` als Fallback ausgeschlossen wird, oder einen robusteren Pick aus `event_results/index.json`/`event_signups`-Meta erzwingen (z.B. letzter Eintrag oder `latest.json`-Meta statt `event.id`).
- Sicherstellen, dass der Mirror-Check auf eine reale Result-Datei (letzter Freitag/letztes Ergebnis) zeigt, nicht auf die Planungs-ID.
- Optional: `docs/data/event_results/index.json` bereitstellen, damit der Primärpfad nie auf `event.id` zurückfällt.
