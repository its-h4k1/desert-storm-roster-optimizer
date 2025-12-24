# Admin-Workflow: Event-Ergebnisse und Zusage-Pool Reset

## 1) Zweck
Wann Admins den Button **„Event abschließen & Zusage-Pool leeren“** klicken, damit der Wochenrhythmus sauber bleibt.

## 2) Was zählt als letztes Event?
- Der Eintrag **DS-YYYY-MM-DD** vom vergangenen Freitag ist das letzte Event.
- **DS-NEXT** ist nur die Vorschau auf das kommende Event und zählt nicht als Ergebnis.

## 3) Wochenablauf (Fr → Mo 03:00 → Do 03:00)
- **Freitag:** Event findet statt.
- **Nach dem Event:** Ergebnisse als **DS-YYYY-MM-DD** speichern.
- **Montag 03:00 (Europe/Zurich):** Zusagefenster öffnet.
- **Donnerstag 03:00 (Europe/Zurich):** Zusagefenster schließt (Sommerzeit beachten; im Zweifel den UI-Fensterstatus checken).

## 4) Ergebnisse sichtbar machen
- „Sichtbar“ heißt: Die gespeicherten Ergebnisse sind auf der Website unter der passenden Event-Ansicht zu sehen.
- Schneller Check: Event-Seite öffnen oder neu laden und prüfen, ob der Eintrag **DS-YYYY-MM-DD** mit den Ergebnissen erscheint.

## 5) Schritt-für-Schritt
1) Ergebnisse des letzten Events speichern (**DS-YYYY-MM-DD**, nicht **DS-NEXT**).
2) Kurz prüfen, ob sie auf der Website sichtbar sind (siehe oben).
3) Zwischen **Mo 03:00 und Do 03:00** den Button **„Event abschließen & Zusage-Pool leeren“** klicken.
4) Danach laufen neue Zusagen bis **Do 03:00** ein.

## 6) Mini-FAQ
- **Warum ist der Button deaktiviert?** Entweder die Ergebnisse sind nicht sichtbar, oder das Zeitfenster **Mo 03:00–Do 03:00 (Europe/Zurich)** ist gerade geschlossen.
- **Ergebnisse gespeichert, Button trotzdem aus – was tun?** Seite neu laden und bestätigen, dass **DS-YYYY-MM-DD** angezeigt wird. Falls ja, aber das Fenster laut UI zu ist: bis zum nächsten Öffnen **Mo 03:00** warten.

## 7) Betroffene Daten
- **Bleibt bestehen:** Event-Ergebnisse.
- **Wird geleert:** Zusagen/Responses im Zusage-Pool.

## 8) Nützliche Links
- [Event-Ergebnisse verwalten](./event-results.html)
- [Zuweisungen & Zusagen](./event-assignments.html)

## Kurzcheckliste vor dem Reset
- Ergebnisse eingetragen und unter **DS-YYYY-MM-DD** gespeichert.
- Ergebnisse sind auf der Website sichtbar.
- Aktuell im Zeitfenster **Mo 03:00 bis Do 03:00** (Europe/Zurich); UI zeigt „Fenster offen“.
- Seite aktualisiert und auf den richtigen Event gewechselt.
- Bereit, den Button **„Event abschließen & Zusage-Pool leeren“** zu klicken.
