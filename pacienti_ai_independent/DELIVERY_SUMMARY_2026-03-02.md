# Rezumat livrare (5 puncte)

1. Dashboard & Watchlist
- Persistenta filtre Dashboard (sectie + data), reset simplu si reset combinat Dashboard+Istoric.
- Istoric Watchlist extins (trend/snapshot), export CSV/PDF si export rapid CSV+PDF.

2. Debounce operational
- Protectie anti dublu-click pe refresh si pe export/import in zonele critice (Dashboard, Statistici, Audit, Fisa pacient, Internari, Setari).
- Feedback UX cu timp ramas real pana la urmatorul click permis.

3. Setari noi admin
- Debounce configurabil din Setari: refresh/export/quick export.
- Preseturi: Conservator / Echilibrat / Rapid + indicator preset activ (inclusiv Custom).

4. Stabilitate & mentenanta
- Refactor pentru consistenta (helper-e comune, eliminare duplicari, preseturi debounce centralizate).
- Curatare erori statice (date/parse_iso_date/import dinamic openai) fara impact negativ in runtime.

5. Comunicare completa
- Pachet complet de comunicare livrat: changelog tehnic, release notes, mesaje tura/email/management, poster intern, index central si shortcut din root.

## Addendum 2026-03-03 (Sprint 1 Manual 2 GAP)

6. Receptie & statusuri pacient
- Statusuri receptie complete in lista pacienti: programat internare, internat, programat externare, externat fara decont, externat.
- Filtre status/persistenta/reset livrate, cu refresh consistent.

7. Programari internare/operatie (control conflict)
- Programarile de internare/operație sunt validate pe conflict de interval/resursa (pat/sala/medic) si capacitate.
- La creare internare, programarea de internare din ziua curenta este inchisa automat (`scheduled` -> `completed`) cand exista.
- In UI internari: previzualizare live ocupare operatie, highlight randuri conflictuale, filtru rapid „Doar conflicte operatie” + contor conflicte afisate.

8. Externare controlata + reguli configurabile
- Tranzitie controlata `active -> scheduled_discharge -> discharged` cu audit.
- Externarea finala poate fi blocata prin reguli configurabile: decont final obligatoriu si/sau rezumat externare obligatoriu.
- Indicator „Reguli externare” cu stare colorata (OK/partial/lipsa) in tab-ul de internari.

9. Status inchidere
- Implementarea tehnica Sprint 1 (S1-E1..S1-E4) este livrata in build-ul curent.
- Pentru inchidere formala DoD raman: executie UAT si semnare QA conform checklist/signoff.
