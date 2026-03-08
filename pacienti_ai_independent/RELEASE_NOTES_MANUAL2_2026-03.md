# RELEASE NOTES - Manual2 + Integrari Live Hybrid (2026-03)

Data: 2026-03-04  
Versiune: Manual2 closure + live integrations (SIUI/DRG, MEDIS)

## 1) Ce include aceasta versiune

### A) Manual2 core inchis

- Raportare institutionala SIUI/DRG in tab-ul `Internari`
  - `Genereaza + valideaza`
  - `Marcheaza transmis`
  - `Export payload JSON`
- MEDIS cap-coada in tab-ul `Ordine`
  - trimitere ordin
  - inregistrare rezultat
  - fallback manual functional
- Facturare/plati/inchidere economica caz
  - facturi `proforma/final/storno`
  - plati partiale/integrale
  - reconciliere status automat (`issued`/`paid`)
- Validari extinse finalizare caz
  - `CASE_REQUIRE_SIUI_DRG_SUBMISSION`
  - `CASE_REQUIRE_FINANCIAL_CLOSURE`
  - `DISCHARGE_REQUIRE_FINAL_DECONT`

### B) Integrare live SIUI/DRG (REST JSON)

- Module noi:
  - `integrations/contracts.py`
  - `integrations/http_client.py`
  - `integrations/siui_drg_client.py`
  - `integrations/dispatcher.py`
- Submit live la `Marcheaza transmis` cand `SIUI_DRG_LIVE_ENABLED=1`
- Strategie hybrid:
  - direct submit la succes
  - fallback `integration_outbox` la timeout/5xx/network
  - 4xx permanente fara retry automat
- Idempotency key per submit + retry backoff.

### C) Integrare live MEDIS (REST JSON)

- Module noi:
  - `integrations/medis_client.py`
  - `integrations/dispatcher.py`
- `Trimite ordin selectat`:
  - succes live -> `sent`
  - esec tranzitoriu -> `queued` + outbox
  - esec permanent -> `send_failed`
- Pull rezultate live MEDIS:
  - periodic (configurabil)
  - manual din UI (`Pull rezultate live`)
  - dedup pe `external_result_id`
- Fallback manual `Inregistreaza rezultat` pastrat.

### D) Schema DB extinsa

- Tabel nou: `integration_outbox`
  - retry status, attempt count, lease, idempotency, payload, erori HTTP.
- Coloane noi in `institutional_reports`:
  - `transport_state`, `transport_attempts`, `transport_last_error`, `transport_http_code`, `transport_last_attempt_at`
- Coloane noi in `medis_investigations`:
  - `transport_state`, `transport_attempts`, `transport_last_error`, `transport_http_code`, `transport_last_attempt_at`, `external_result_id`

### E) Setari runtime + operare

- Setari noi in tab-ul `Setari`:
  - enable flags, endpoint-uri, auth type, retry/timeout.
- Secrete din ENV (nu DB):
  - `SIUI_DRG_CLIENT_SECRET`, `SIUI_DRG_API_KEY`, `SIUI_DRG_BEARER_TOKEN`
  - `MEDIS_CLIENT_SECRET`, `MEDIS_API_KEY`, `MEDIS_BEARER_TOKEN`
- Actiuni operationale noi:
  - `Proceseaza queue acum`
  - `Vezi erori integrare`

## 2) Validare curenta

- `python -m py_compile ...` -> `EXIT:0`
- `python -m unittest discover ...` -> `EXIT:0` (`Ran 30 tests`)
- Manual2 core: `15/15 PASS` (evidente `TC_*_PASS.json`)
- Live: precheck local automat (`TC_LIVE_*_PRECHECK_PASS.json`)

## 3) Limitari cunoscute

- Pentru GO productie lipsesc inca executiile sandbox reale `TC-LIVE-*`.
- GO este blocat pana la semnaturi reale QA/Owner/Tech.
- Integrarea live depinde de endpoint-uri si secrete corect configurate pe fiecare statie.

## 4) Rollout / rollback

- Rollout doar dupa:
  - sandbox PASS
  - semnaturi reale
  - checklist-uri completate
- Rollback rapid prin feature flags:
  - `SIUI_DRG_LIVE_ENABLED=0`
  - `MEDIS_LIVE_ENABLED=0`
- Restore DB doar in caz de coruptie date.

## 5) Documente de operare

- `QA_CHECKLIST_5MIN_RO.md`
- `QA_CHECKLIST_MANUAL2_EXTINS_RO.md`
- `QA_SIGNOFF.md`
- `ROLLOUT_RUNBOOK_MANUAL2_2026-03.md`
- `GO_NO_GO_ONE_PAGER_2026-03-02.md`

## 6) Evidente tehnice

- `exports/uat_evidence_2026-03-04/preflight_py_compile.log`
- `exports/uat_evidence_2026-03-04/preflight_unittest.log`
- `exports/uat_evidence_2026-03-04/preflight_unittest_exit.log`
- `exports/uat_evidence_2026-03-04/TC_*_PASS.json`
- `exports/uat_evidence_2026-03-04/TC_LIVE_*_PRECHECK_PASS.json`
