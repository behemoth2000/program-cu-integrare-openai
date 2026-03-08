# GO/NO-GO Checklist Val 3A

Data: 2026-03-08

## Gate tehnic
- [ ] `python -m py_compile pacienti_ai_independent/pacienti_ai_app.py pacienti_ai_independent/api/app.py pacienti_ai_independent/api/client.py pacienti_ai_independent/data_backend/backends.py` este verde.
- [ ] `python -m unittest discover -s tests -p "test_*.py"` este verde.
- [ ] Teste noi trecute:
  - [ ] `tests/test_integration_dry_run_ops_api.py`
  - [ ] `tests/test_shadow_processor_unified_path.py`

## Gate functional
- [ ] Endpoint `GET /api/v1/ops/integration-dry-run-logs` returneaza payload normalizat.
- [ ] Endpoint-ul dry-run logs este admin-only (RBAC).
- [ ] `Vezi loguri dry-run` functioneaza in tab `Setari`.
- [ ] Shadow sync ruleaza prin calea comuna (API + desktop local fallback).

## Gate operational
- [ ] `Runbook Val 3A` publicat.
- [ ] Echipa ops cunoaste procedura de auto-stop/incident.
- [ ] Pragul `API_INTERNAL_POSTGRES_SHADOW_STOP_ON_ERROR_RATE` validat pentru mediu.

## Smoke minim
- [ ] Shadow ON + Postgres indisponibil: write principal ramane OK.
- [ ] `Proceseaza shadow sync acum`: backlog scade dupa revenire Postgres.
- [ ] Dry-run SIUI/DRG + MEDIS: loguri apar, fara schimbare status business.

## Decizie
- [ ] GO
- [ ] NO-GO

Motivatie:

Semnaturi:
- QA Lead: ____________________
- Owner operational: ___________
- Tech owner: _________________
