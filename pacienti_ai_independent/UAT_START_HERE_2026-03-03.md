# UAT Start Here (Sprint 1)

Data: 2026-03-03
Status curent: CODE COMPLETE, pending UAT/QA sign-off

Acest document este punctul unic de pornire pentru sesiunea UAT.

## Pasii in ordine (15-30 minute)

1. Ruleaza verificarea tehnica minima:
   - py -3 -m py_compile pacienti_ai_independent/pacienti_ai_app.py
   - python _tmp_initdb_test.py

2. Ruleaza scenariile UAT complete folosind:
   - UAT_RUNBOOK_SPRINT1_2026-03-03.md

3. Inregistreaza fiecare rezultat in:
   - UAT_EXECUTION_LOG_SPRINT1_2026-03-03.md

4. Executa checklist-ul scurt (sanity + sprint checks):
   - QA_CHECKLIST_5MIN_RO.md

5. Completeaza acceptanta formala:
   - QA_SIGNOFF.md

6. Actualizeaza decizia de rollout:
   - GO_NO_GO_ONE_PAGER_2026-03-02.md
   - RELEASE_CLOSURE_STATUS_2026-03-02.md

## Criteriu de inchidere UAT

- GO UAT: toate scenariile critice PASS, fara blocker/critical.
- NO-GO UAT: orice blocker pe tranzitii internare/externare sau conflict handling programari.

## Evidente minime obligatorii

- Log UAT completat (PASS/FAIL pe scenariu)
- Capturi/evidente pentru scenariile FAIL
- Semnaturi QA + owner operational

## Contacte (de completat)

- QA lead: __________________
- Owner operational: __________________
- Tech owner: __________________
