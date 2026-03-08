# Index comunicare update (2026-03-04)

Acest index centralizeaza materialele de comunicare, QA, UAT si rollout pentru Manual2 extins.

Last updated: 2026-03-04
Owner document: Responsabil Aplicatie
Next review: 2026-03-05
Doc status: in review pentru decizia GO/NO-GO

## Change log (ultimele update-uri)

- 2026-03-04: adaugat pachet Manual2 extins (checklist extins, runbook rollout, release notes dedicate).
- 2026-03-04: actualizat `QA_CHECKLIST_5MIN_RO.md` pentru smoke SIUI/DRG, MEDIS, facturare/plati.
- 2026-03-04: actualizat `GO_NO_GO_ONE_PAGER_2026-03-02.md` cu gate-uri Manual2.

## Documente QA/UAT/Rollout (active)

- [QA_CHECKLIST_5MIN_RO.md](QA_CHECKLIST_5MIN_RO.md)
  - Audienta: QA / owner operational
  - Scop: smoke rapid + status preflight

- [QA_CHECKLIST_MANUAL2_EXTINS_RO.md](QA_CHECKLIST_MANUAL2_EXTINS_RO.md)
  - Audienta: QA / owner operational / tech owner
  - Scop: matrice completa TC-FIN/TC-SIUI/TC-DRG/TC-MEDIS/TC-CASE/TC-REG

- [QA_SIGNOFF.md](QA_SIGNOFF.md)
  - Audienta: QA lead / owner operational / tech owner
  - Scop: acceptanta formala

- [GO_NO_GO_ONE_PAGER_2026-03-02.md](GO_NO_GO_ONE_PAGER_2026-03-02.md)
  - Audienta: management / owner operational / QA
  - Scop: decizie formala GO/NO-GO

- [ROLLOUT_RUNBOOK_MANUAL2_2026-03.md](ROLLOUT_RUNBOOK_MANUAL2_2026-03.md)
  - Audienta: release coordinator / ops / QA
  - Scop: pasi rollout, monitorizare, trigger si procedura rollback

- [RELEASE_NOTES_MANUAL2_2026-03.md](RELEASE_NOTES_MANUAL2_2026-03.md)
  - Audienta: utilizatori finali + coordonatori tura
  - Scop: ce s-a schimbat, impact operational, limitari

## Evidente tehnice

- Folder evidenta: `exports/uat_evidence_2026-03-04/`
- Artefacte generate:
  - `preflight_py_compile.log`
  - `preflight_unittest.log`
  - `preflight_unittest_exit.log`
  - `preflight_app_start.log`
  - `preflight_runtime_settings_keys.log`
  - `uat_manual2_dataset.db`
  - `uat_dataset_summary.json`
  - `TC_*_PASS.json|txt` (automat, din suita `tests/test_manual2_reporting_finance_medis.py`)

## Documente istorice (Sprint1)

- [UAT_START_HERE_2026-03-03.md](UAT_START_HERE_2026-03-03.md)
- [UAT_RUNBOOK_SPRINT1_2026-03-03.md](UAT_RUNBOOK_SPRINT1_2026-03-03.md)
- [UAT_EXECUTION_LOG_SPRINT1_2026-03-03.md](UAT_EXECUTION_LOG_SPRINT1_2026-03-03.md)
- [RELEASE_CLOSURE_STATUS_2026-03-02.md](RELEASE_CLOSURE_STATUS_2026-03-02.md)
- [RELEASE_DECISION_PACKET_V1_FILLED_2026-03-02.md](RELEASE_DECISION_PACKET_V1_FILLED_2026-03-02.md)
