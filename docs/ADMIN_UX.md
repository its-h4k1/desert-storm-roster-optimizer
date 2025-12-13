# Admin UX Pattern (SSOT)

## Ziel
- Gemeinsamer Admin-Header mit Navigation und nur sichtbaren Betriebsinformationen: Statuspill(en), Login/Logout-Actions und Routen-Link.
- Infrastruktur-Details (Worker-URL, Branch-Override, Admin-Key) bleiben standardmäßig verborgen und werden erst bei Bedarf in den Einstellungen gezeigt.

## Verhalten
- Der zentrale Gatekeeper (`initAdminKeyGate`) prüft den gespeicherten Admin-Key aus dem Shared-Storage.
- Fehlt ein Key, wird der Hinweisbanner eingeblendet **und** der Einstellungen-Bereich automatisch geöffnet, damit der Key sofort nachgetragen werden kann.
- Sobald ein Key vorliegt, bleibt die Infrastruktur-Sektion zu und die Seite arbeitet nur mit Status-/Action-Elementen im Header.

## Nutzung für neue Admin-Seiten
- Binde `docs/shared.js` und `docs/admin/admin.js` ein, damit Navigation & Layout (`initAdminLayout`) sowie die zentrale Key-Synchronisierung (`applyAdminKeyInput`) automatisch greifen.【F:docs/admin/admin.js†L1-L28】【F:docs/shared.js†L252-L375】【F:docs/shared.js†L461-L489】
- Verwende den Admin-Key-Gatekeeper aus `dsroShared.initAdminKeyGate` für Status-Label, Fallback-Input und Settings-Toggle; der Gatekeeper öffnet die Settings selbst, falls kein Key gefunden wird.【F:docs/shared.js†L273-L375】
- Für API-/Worker-Calls immer `dsroShared.buildAdminHeaders` nutzen, damit der gespeicherte Admin-Key (oder Fallback) automatisch als `X-Admin-Key` angehängt wird.【F:docs/shared.js†L378-L387】

## Smoke-Tests (manuell)
1) Mit gesetztem Admin-Key: Seite laden → Statuspill zeigt „gesetzt“, Einstellungen bleiben zu, Aktionen bleiben erreichbar.
2) Ohne Admin-Key: Seite laden → Statuspill zeigt Warnung, Settings-Panel öffnet automatisch und Fallback-Eingabe ist sichtbar.
3) Ohne Admin-Key, Key im Fallback eingeben + übernehmen → Status wechselt auf „geprüft/gesetzt“, Panel darf wieder manuell zugeklappt werden.
4) Mit Admin-Key einen Worker-/Dispatch-Call auslösen, wobei der Request `X-Admin-Key` trägt (über `buildAdminHeaders` oder `triggerRosterBuild`).
