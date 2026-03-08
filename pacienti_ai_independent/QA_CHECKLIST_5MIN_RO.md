# QA checklist manual (5 minute) - Manual2 + Live Hybrid

Data: 2026-03-04  
Scop: smoke UAT rapid pentru Manual2 core + verificari operationale pentru integrarea live hibrida.

Folder evidenta: `pacienti_ai_independent/exports/uat_evidence_2026-03-04`

## A) Preflight tehnic

- [x] `python -m py_compile pacienti_ai_independent/pacienti_ai_app.py` = `EXIT:0`  
  Evidenta: `preflight_py_compile.log`
- [x] `python -m unittest discover -s tests -p "test_*.py"` = `EXIT:0` (`Ran 30 tests`)  
  Evidenta: `preflight_unittest.log`, `preflight_unittest_exit.log`
- [x] Start/import aplicatie fara crash la deschidere  
  Evidenta: `preflight_app_start.log`
- [x] Chei runtime prezente:
  - `CASE_REQUIRE_SIUI_DRG_SUBMISSION`
  - `CASE_REQUIRE_FINANCIAL_CLOSURE`
  - `DISCHARGE_REQUIRE_FINAL_DECONT`
  - `SIUI_DRG_LIVE_ENABLED`
  - `MEDIS_LIVE_ENABLED`
- [x] Dataset UAT dedicat creat  
  Evidenta: `uat_manual2_dataset.db`, `uat_dataset_summary.json`

## B) Smoke functional rapid

1. Login + deschidere pacient din dataset UAT.
- [ ] PASS
- [ ] FAIL
Artefact:

2. Internari: `Genereaza + valideaza` raport institutional (`siui`).
- [ ] PASS
- [ ] FAIL
Artefact:

3. Internari: `Genereaza + valideaza` raport institutional (`drg`).
- [ ] PASS
- [ ] FAIL
Artefact:

4. Internari: emitere factura `proforma`.
- [ ] PASS
- [ ] FAIL
Artefact:

5. Internari: inregistrare plata pe factura.
- [ ] PASS
- [ ] FAIL
Artefact:

6. Ordine: `Trimite ordin selectat` + status ordin.
- [ ] PASS
- [ ] FAIL
Artefact:

7. Ordine: `Inregistreaza rezultat` fallback manual + status ordin `done`.
- [ ] PASS
- [ ] FAIL
Artefact:

8. Internari: export `Raport internare PDF` + `Bilet externare PDF`.
- [ ] PASS
- [ ] FAIL
Artefact:

## C) Smoke live operations (cand live flags sunt ON)

1. Setari: `SIUI_DRG_LIVE_ENABLED=1`, `MEDIS_LIVE_ENABLED=1`.
- [ ] PASS
- [ ] FAIL
Artefact:

2. Actiune operationala: `Proceseaza queue acum`.
- [ ] PASS
- [ ] FAIL
Artefact:

3. Actiune operationala: `Vezi erori integrare` (fara erori permanente blocante).
- [ ] PASS
- [ ] FAIL
Artefact:

4. Actiune MEDIS: `Pull rezultate live`.
- [ ] PASS
- [ ] FAIL
Artefact:

## D) Rezultat smoke

- [ ] Smoke ACCEPTAT
- [ ] Smoke ACCEPTAT cu observatii
- [ ] Smoke RESPINS

Observatii:
- 
- 

Semnaturi:
- QA / Tester: TBD  Data: __________
- Owner operational: TBD  Data: __________
