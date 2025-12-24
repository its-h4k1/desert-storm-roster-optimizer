# Admin-Workflow: Event-Ergebnisse & Zusage-Pool Reset

Dieses Dokument beschreibt den wöchentlichen Admin-Ablauf rund um:
- **Event-Ergebnisse speichern** (`DS-YYYY-MM-DD`)
- **Zusage-/Antwort-Pool leeren** für das kommende Event

Ziel: Der Reset soll **nur dann** möglich sein, wenn
1) die Ergebnisse vom **letzten echten Event** auf der Website sichtbar sind und  
2) das **Anmeldefenster** offen ist (**Mo 03:00–Do 03:00**, Europe/Zurich).

---

## 1) Begriffe (kurz)

- **Echtes Event (Ergebnis-Event):** `DS-YYYY-MM-DD` (immer ein Freitag)
- **DS-NEXT:** Planungs-/Vorschau-ID für das **kommende** Event (kein Ergebnis-Event)

Wichtig:
- **`DS-NEXT` zählt nicht als Ergebnis.**
- Ergebnisse existieren nur für echte `DS-YYYY-MM-DD` Events.

---

## 2) Wochenablauf (Standard)

### Freitag (Event-Tag)
1. Event wird gespielt.
2. Danach: **Event-Ergebnisse speichern** (mit der echten ID `DS-YYYY-MM-DD`).

### Anmeldefenster fürs kommende Event
- **Start:** Montag **03:00**
- **Ende:** Donnerstag **03:00**
- **Zeitzone:** Europe/Zurich

Innerhalb dieses Fensters:
- Zusagen/Responses sammeln für das kommende Freitag-Event.

---

## 3) Schritt-für-Schritt: So läuft es jede Woche

### Schritt A — Ergebnisse erfassen (nach dem Event)
1. Öffne **Event-Ergebnisse**:  
   → [Event-Ergebnisse](./event-results.html)
2. Verwende die Event-ID im Format **`DS-YYYY-MM-DD`**.
3. Trage Anwesenheit & Punkte ein.
4. Speichern, bis das Ergebnis **ladbar** ist.

Hinweis:
- „Ergebnisse sichtbar“ bedeutet: Das Ergebnis kann auf der Website geladen werden (**kein 404 / keine Fehlermeldung**).

---

### Schritt B — Pool leeren (zum Start des Anmeldefensters)
1. Warte bis **Montag 03:00** (Start des Anmeldefensters).
2. Öffne **Event-Zusagen / Pool**:  
   → [Event-Zusagen / Pool](./event-assignments.html)
3. Klicke im Statusblock **Aktualisieren** (der Status entscheidet, ob Reset erlaubt ist).
4. Prüfe:
   - **Letztes Event** ist eine echte `DS-YYYY-MM-DD` ID (nicht `DS-NEXT`)
   - **Ergebnisse sichtbar (Website)** ist ✅
   - **Anmeldefenster** ist ✅ (offen)

5. Klicke **„Event abschließen & Zusage-Pool leeren“**.

Was passiert dabei:
- Es werden nur die Dateien für das **kommende** Event geleert:
  - `event_signups_next.csv`
  - `event_responses_next.csv`
- **Event-Ergebnisse bleiben erhalten.**

---

## 4) Warum der Reset-Button manchmal deaktiviert ist

Der Button ist deaktiviert, wenn mindestens einer dieser Punkte zutrifft:

### A) Ergebnisse sind nicht sichtbar
- Der Status zeigt ❌ bei „Ergebnisse sichtbar (Website)“.

Dann:
- Öffne **Event-Ergebnisse**
- lade/speichere das letzte `DS-YYYY-MM-DD` Event erneut (bis es ladbar ist)
- kehre zurück und klicke **Aktualisieren**

### B) Anmeldefenster ist geschlossen
- Reset ist nur erlaubt von **Mo 03:00 bis Do 03:00**.

Dann:
- Warte bis das Fenster wieder offen ist (**nächster Montag 03:00**).

---

## 5) Troubleshooting (wenn etwas nicht passt)

### „Letztes Event“ zeigt `DS-NEXT`
- `DS-NEXT` ist nur Planung und kein Ergebnis-Event.
- Klicke **Aktualisieren**.
- Stelle sicher, dass die Ergebnisse für das letzte echte `DS-YYYY-MM-DD` gespeichert und ladbar sind.

### Ergebnisse gespeichert, aber „Ergebnisse sichtbar“ bleibt ❌
- Öffne [Event-Ergebnisse](./event-results.html)
- versuche das Event `DS-YYYY-MM-DD` zu laden
- falls es nicht lädt: nochmal speichern (bis es ladbar ist)
- zurück zur Zusagen-Seite → **Aktualisieren**

### Zeit wirkt “komisch” (03:00)
- Zeiten gelten in **Europe/Zurich**.
- Bei Sommerzeit-Wechseln kann es gefühlt abweichen.
- Im Zweifel dem **Fenster-Status in der UI** vertrauen und **Aktualisieren** klicken.

---

## 6) Betroffene Daten (High Level)

Beim Reset werden geleert:
- `event_signups_next.csv` (Zusage-Pool fürs kommende Event)
- `event_responses_next.csv` (Absagen/Responses fürs kommende Event)

Unverändert bleiben:
- alle gespeicherten Event-Ergebnisse (`DS-YYYY-MM-DD`)
- alle Statistiken/History, die aus Ergebnissen berechnet werden

---

## Kurzcheckliste (vor jedem Reset)

- [ ] Einmal **Aktualisieren** klicken
- [ ] Ist jetzt **Mo 03:00–Do 03:00** (Fenster offen)?
- [ ] Zeigt „Letztes Event“ eine echte **`DS-YYYY-MM-DD`** ID (nicht `DS-NEXT`)?
- [ ] Steht „Ergebnisse sichtbar (Website)“ auf ✅?
- [ ] Dann erst: **„Event abschließen & Zusage-Pool leeren“**
