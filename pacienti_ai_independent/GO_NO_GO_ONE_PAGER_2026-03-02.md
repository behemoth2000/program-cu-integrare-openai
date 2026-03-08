# GO / NO-GO One-Pager - Manual2 + Live Hybrid (2026-03-04)

## Context

- Release: Manual2 inchis + integrare live SIUI/DRG + MEDIS (REST JSON, hybrid direct + outbox retry)
- Scop: rollout pe toate statiile dupa validare sandbox si semnaturi reale
- Fereastra propusa rollout: 2026-03-07 (Europe/Bucharest)

## Criterii obligatorii (GO gates)

- [x] Validare tehnica finala incheiata
  - `python -m py_compile pacienti_ai_independent/pacienti_ai_app.py` = `EXIT:0`
  - `python -m unittest discover -s tests -p "test_*.py"` = `EXIT:0` (`Ran 30 tests`)
  - Evidente: `exports/uat_evidence_2026-03-04/preflight_*`
- [x] Manual2 core inchis functional
  - `15/15 TC PASS` (`TC-FIN-*`, `TC-SIUI-*`, `TC-DRG-*`, `TC-MEDIS-*`, `TC-CASE-*`, `TC-REG-*`)
  - Evidente: `exports/uat_evidence_2026-03-04/TC_*_PASS.json`
- [x] Mecanism live hybrid implementat
  - module `integrations/*`
  - `integration_outbox` + retry/backoff/idempotency
  - feature flags `SIUI_DRG_LIVE_ENABLED`, `MEDIS_LIVE_ENABLED`
- [x] Precheck live local (mocked) complet
  - `TC_LIVE_*_PRECHECK_PASS.json`
- [ ] Executie sandbox reala completa pentru `TC-LIVE-*`
- [ ] Checklist operational completat si semnat (`QA_CHECKLIST_*`, `QA_SIGNOFF.md`)
- [ ] Semnaturi reale QA / Owner operational / Tech owner
- [ ] Owner operational confirma fereastra de rollout

## Evaluare risc

- Risc tehnic: Mediu (integrare externa live + retry queue)
- Risc operational: Mediu
- Impact utilizator: Pozitiv (automatizare submit/pull + fallback local pastrat)

## Decizie curenta

- [ ] GO
- [x] NO-GO

## Motive decizie (obligatoriu)

- Rularea sandbox reala pentru scenariile `TC-LIVE-*` nu este inca executata/completata.
- Semnaturile reale QA/Owner/Tech lipsesc la acest moment.
- Fara aceste 2 conditii, gate-ul de productie ramane blocat conform planului.

## Actiuni pentru trecere la GO

1. Executa `TC-LIVE-SIUI-01`, `TC-LIVE-DRG-01`, `TC-LIVE-SIUI-02`, `TC-LIVE-MEDIS-01/02/03` pe sandbox.
2. Completeaza `QA_CHECKLIST_5MIN_RO.md` + `QA_CHECKLIST_MANUAL2_EXTINS_RO.md`.
3. Completeaza semnaturi reale in `QA_SIGNOFF.md`.
4. Revalideaza preflight rapid in ziua rollout.

## Aprobari

- QA lead: TBD  Data: __________
- Owner operational: TBD  Data: __________
- Tech owner: TBD  Data: __________
