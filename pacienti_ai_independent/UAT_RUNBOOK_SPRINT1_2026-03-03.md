# UAT Runbook Sprint 1 (Manual 2 GAP)

Data: 2026-03-03
Versiune build: code complete (S1-E1..S1-E4)
Scop: executie UAT structurata pentru fluxurile critice receptie/programari/internare/externare.

## 1) Preconditii

- Aplicatia porneste fara erori.
- Baza are minimum 3 pacienti de test.
- Exista cel putin 1 utilizator cu rol medic sau admin.
- Validari tehnice minime executate:
  - py -3 -m py_compile pacienti_ai_independent/pacienti_ai_app.py -> EXIT:0
  - python _tmp_initdb_test.py -> EXIT:0

## 2) Evidente obligatorii

Pentru fiecare scenariu capturati:
- rezultat: PASS sau FAIL
- screenshot (sau export) pentru ecranul relevant
- timestamp test
- observatii scurte (max 2 randuri)

## 3) Scenarii UAT pe epic

### S1-E1 Receptie / statusuri

1. Deschide lista pacienti si verifica filtrele de status receptie.
2. Ruleaza pe rand filtrele:
   - Programati la internare
   - Pacienti internati
   - Programati la externare
   - Externati fara decont final
   - Pacienti externati
3. Verifica persistenta filtrului dupa refresh si dupa redeschidere aplicatie.
4. Ruleaza reset filtre si verifica revenirea la default.

Criteriu PASS:
- toate cele 5 statusuri sunt afisate corect si filtrarea este consistenta.

### S1-E2 Programare internare

1. Creeaza programare de internare (sectie + salon + interval).
2. Incearca o programare suprapusa pe aceeasi resursa (pat/salon) in acelasi interval.
3. Creeaza internarea efectiva pentru pacientul programat in ziua curenta.

Criteriu PASS:
- conflictul este blocat cu mesaj explicit;
- la creare internare, programarea corespunzatoare se inchide automat (scheduled -> completed).

### S1-E3 Programare operatie

1. Creeaza o operatie valida.
2. Creeaza intentinat conflict pe aceeasi sala sau acelasi medic in interval suprapus.
3. Verifica preview-ul live de ocupare in formular.
4. Verifica highlight randuri conflictuale in tabel.
5. Activeaza filtrul Doar conflicte operatie si confirma contorul Conflicte afisate.

Criteriu PASS:
- conflictul este semnalat in preview, in tabel si prin filtrare rapida.

### S1-E4 Externare controlata

1. Pentru un pacient internat, creeaza programare de externare in ziua curenta.
2. Activeaza/dezactiveaza regulile de externare din Setari:
   - decont final obligatoriu
   - rezumat externare obligatoriu
3. Incearca externarea fara indeplinirea regulilor, apoi cu regulile indeplinite.
4. Verifica indicatorul Reguli externare (culoare + text stare).

Criteriu PASS:
- externarea este blocata corect cand lipsesc prerechizite;
- externarea reuseste doar in tranzitia valida active -> programat externare -> externat.

## 4) Verificare audit (obligatoriu)

Confirmati in audit cel putin urmatoarele evenimente:
- create_admission cu transition=scheduled_admission->active sau direct->active
- discharge_admission cu transition=active->scheduled_discharge->discharged
- create_booking / update_booking_status pentru cazurile testate

## 5) Regula de decizie UAT

- GO UAT: toate scenariile critice PASS, fara defecte blocker/critical.
- NO-GO UAT: orice defect blocker pe tranzitii internare/externare sau pe conflict handling programari.

## 6) Semnaturi

- QA Tester: __________________  Data: __________
- Owner operational: __________  Data: __________
- Tech owner: __________________ Data: __________

## 7) Legaturi utile

- UAT_START_HERE_2026-03-03.md
- QA_CHECKLIST_5MIN_RO.md
- QA_SIGNOFF.md
- UAT_EXECUTION_LOG_SPRINT1_2026-03-03.md
- GO_NO_GO_ONE_PAGER_2026-03-02.md
- RELEASE_CLOSURE_STATUS_2026-03-02.md
