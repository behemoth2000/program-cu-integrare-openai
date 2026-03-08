# QA Checklist Manual2 Extins - UAT + Rollout

Data start UAT: 2026-03-05  
Data actualizare: 2026-03-04  
Fereastra rollout propusa: 2026-03-07

Referinte:
- Checklist smoke: `QA_CHECKLIST_5MIN_RO.md`
- Sign-off: `QA_SIGNOFF.md`
- GO/NO-GO: `GO_NO_GO_ONE_PAGER_2026-03-02.md`
- Runbook rollout: `ROLLOUT_RUNBOOK_MANUAL2_2026-03.md`
- Evidente tehnice: `exports/uat_evidence_2026-03-04/`

## 1) Preconditii UAT

- Build porneste fara erori.
- Preflight tehnic este verde (`py_compile`, `unittest`, app start/import smoke).
- Setari runtime disponibile in tab-ul `Setari`:
  - `CASE_REQUIRE_SIUI_DRG_SUBMISSION`
  - `CASE_REQUIRE_FINANCIAL_CLOSURE`
  - `DISCHARGE_REQUIRE_FINAL_DECONT`
  - `SIUI_DRG_LIVE_ENABLED`
  - `MEDIS_LIVE_ENABLED`
- Dataset UAT dedicat disponibil:
  - `uat_manual2_dataset.db`
  - `uat_dataset_summary.json`

## 2) Reguli de executie

- Pentru fiecare TC se completeaza `Actual`, `Status` si `Evidenta`.
- Statusuri utilizate:
  - `PASS`/`FAIL` pentru Manual2 core
  - `PRECHECK_PASS` pentru teste automate live pe mock local
  - `PENDING_SANDBOX` pentru scenarii care cer endpoint live sandbox
- La `FAIL`, se adauga ID defect + severitate (`Low/Medium/High/Critical`).

## 3) Matrice scenarii UAT Manual2 (core)

| ID | Scenariu | Pasi minimali | Rezultat asteptat | Actual | Status | Evidenta | Defect/Severitate |
|---|---|---|---|---|---|---|---|
| TC-FIN-01 | Emitere factura proforma | Selecteaza internare activa -> tip `proforma` -> `Emite factura` | Factura apare in lista cu status `issued` | Validat automat (`unittest`) | PASS | `exports/uat_evidence_2026-03-04/TC_FIN_01_PASS.json` |  |
| TC-FIN-02 | Emitere factura finala dupa externare | Selecteaza internare externata -> tip `final` -> `Emite factura` | Factura finala este emisa; pe internare neexternata este blocata | Validat automat (`unittest`) | PASS | `exports/uat_evidence_2026-03-04/TC_FIN_02_PASS.json` |  |
| TC-FIN-03 | Plati partiale | Selecteaza factura `issued` -> inregistreaza plata sub total | Status factura ramane `issued` | Validat automat (`unittest`) | PASS | `exports/uat_evidence_2026-03-04/TC_FIN_03_PASS.json` |  |
| TC-FIN-04 | Achitare integrala | Inregistreaza plata pentru sold ramas | Status factura devine `paid` | Validat automat (`unittest`) | PASS | `exports/uat_evidence_2026-03-04/TC_FIN_04_PASS.json` |  |
| TC-FIN-05 | Inchidere economica caz | Verifica caz cu factura finala + plata integrala vs caz cu plata partiala | `is_case_financially_closed=true` doar la inchidere completa | Validat automat (`unittest`) | PASS | `exports/uat_evidence_2026-03-04/TC_FIN_05_PASS.json` |  |
| TC-SIUI-01 | Payload SIUI valid | Selecteaza caz externat complet -> `Genereaza + valideaza` tip `siui` | Raport salvat cu status `validated` si fara erori | Validat automat (`unittest`) | PASS | `exports/uat_evidence_2026-03-04/TC_SIUI_01_PASS.json` |  |
| TC-SIUI-02 | Submit SIUI | Selecteaza raport SIUI valid -> completeaza ref externa -> `Marcheaza transmis` | Raport status `submitted` + ref externa salvata | Validat automat (`unittest`) | PASS | `exports/uat_evidence_2026-03-04/TC_SIUI_02_PASS.json` |  |
| TC-DRG-01 | Payload DRG valid | Selecteaza caz externat complet -> `Genereaza + valideaza` tip `drg` | Raport salvat cu status `validated` si fara erori | Validat automat (`unittest`) | PASS | `exports/uat_evidence_2026-03-04/TC_DRG_01_PASS.json` |  |
| TC-DRG-02 | Submit DRG | Selecteaza raport DRG valid -> completeaza ref externa -> `Marcheaza transmis` | Raport status `submitted` + ref externa salvata | Validat automat (`unittest`) | PASS | `exports/uat_evidence_2026-03-04/TC_DRG_02_PASS.json` |  |
| TC-MEDIS-01 | Trimitere ordin la MEDIS | Selecteaza ordin medical -> completeaza request -> `Trimite ordin selectat` | Cerere MEDIS creata; ordin trece in `in_progress` | Validat automat (`unittest`) | PASS | `exports/uat_evidence_2026-03-04/TC_MEDIS_01_PASS.json` |  |
| TC-MEDIS-02 | Rezultat MEDIS | Selecteaza cerere MEDIS -> completeaza rezultat -> `Inregistreaza rezultat` | Cerere MEDIS `result_received`; ordin `done` | Validat automat (`unittest`) | PASS | `exports/uat_evidence_2026-03-04/TC_MEDIS_02_PASS.json` |  |
| TC-CASE-01 | Finalizare caz cu reguli ON | Activeaza ambele reguli (`SIUI/DRG` + `financial closure`) -> incearca finalizare cu/ fara prerechizite | Blocare corecta fara prerechizite; finalizare reusita cand totul este complet | Validat automat (`unittest`) | PASS | `exports/uat_evidence_2026-03-04/TC_CASE_01_PASS.json` |  |
| TC-CASE-02 | Finalizare caz cu reguli OFF | Dezactiveaza reguli noi -> ruleaza validare/finalizare pe caz compatibil legacy | Comportament backward-compatible (fara regresii) | Validat automat (`unittest`) | PASS | `exports/uat_evidence_2026-03-04/TC_CASE_02_PASS.json` |  |
| TC-REG-01 | Regresie internare/externalizare | Flux internare din booking + externare cu reguli existente | Tranzitii corecte + jurnal transferuri | Validat automat (`unittest`) | PASS | `exports/uat_evidence_2026-03-04/TC_REG_01_PASS.json` |  |
| TC-REG-02 | Regresie exporturi FO/checklist | Export `Raport internare PDF` + `Bilet externare PDF` | Exporturi se genereaza fara erori | Validat automat (`unittest`) | PASS | `exports/uat_evidence_2026-03-04/TC_REG_02_PASS.json` |  |

## 4) Criterii de acceptanta Manual2 core

- 100% PASS pe scenarii critice:
  - `TC-FIN-02`, `TC-FIN-05`, `TC-SIUI-02`, `TC-DRG-02`, `TC-MEDIS-02`, `TC-CASE-01`
- Minim 95% PASS total pe matrice.
- 0 defecte `High/Critical` deschise la momentul deciziei.

Status curent Manual2 core:
- `15/15 PASS`
- `0 FAIL`
- `0 defecte High/Critical`

## 5) Matrice extensie LIVE (sandbox + precheck)

| ID | Scenariu | Rezultat asteptat | Actual | Status | Evidenta |
|---|---|---|---|---|---|
| TC-LIVE-SIUI-01 | Submit live SIUI sandbox | Submit live 2xx, raport `submitted`, transport `submitted` | Precheck automat local (mocked) validat | PRECHECK_PASS | `exports/uat_evidence_2026-03-04/TC_LIVE_SIUI_01_PRECHECK_PASS.json` |
| TC-LIVE-DRG-01 | Submit live DRG sandbox | Submit live 2xx, raport `submitted`, transport `submitted` | Precheck automat local (mocked) validat | PRECHECK_PASS | `exports/uat_evidence_2026-03-04/TC_LIVE_DRG_01_PRECHECK_PASS.json` |
| TC-LIVE-SIUI-02 | Timeout SIUI -> queue -> retry -> submitted | Job trece `retry` -> `done`, raport `submitted` | Precheck automat local (mocked dispatcher+outbox) validat | PRECHECK_PASS | `exports/uat_evidence_2026-03-04/TC_LIVE_SIUI_02_PRECHECK_PASS.json` |
| TC-LIVE-MEDIS-01 | Send order sandbox | Cerere `sent` sau `queued` cu retry valid | Precheck automat local (mocked) validat | PRECHECK_PASS | `exports/uat_evidence_2026-03-04/TC_LIVE_MEDIS_01_PRECHECK_PASS.json` |
| TC-LIVE-MEDIS-02 | Pull rezultat sandbox | `result_received`, ordin `done` | Precheck automat local (mocked pull+apply) validat | PRECHECK_PASS | `exports/uat_evidence_2026-03-04/TC_LIVE_MEDIS_02_PRECHECK_PASS.json` |
| TC-LIVE-MEDIS-03 | Fallback manual rezultat | Flux manual ramane functional | Flux manual confirmat automat | PRECHECK_PASS | `exports/uat_evidence_2026-03-04/TC_LIVE_MEDIS_03_PRECHECK_PASS.json` |

Nota:
- Scenariile LIVE raman `PENDING_SANDBOX` pentru acceptanta finala pana la rularea cu endpoint-uri sandbox reale.

## 6) Rezumat executie

- Preflight tehnic: `PASS` (`py_compile EXIT:0`, `unittest EXIT:0`, `Ran 30 tests`)
- Total TC Manual2 core: `15`
- PASS core: `15`
- FAIL core: `0`
- Total TC live precheck: `6`
- PRECHECK_PASS live: `6`
- Defecte High/Critical deschise: `0`
- Recomandare UAT curenta: `[ ] GO UAT  [x] NO-GO UAT`

Motive NO-GO curent:
- Lipsesc executiile sandbox reale pentru scenariile live (`TC-LIVE-*`).
- Lipsesc semnaturile reale QA/Owner/Tech.

Semnaturi:
- QA Tester: TBD  Data: __________
- Owner operational: TBD  Data: __________
- Tech owner: TBD  Data: __________
