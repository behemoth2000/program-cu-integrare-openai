# QA checklist manual (5 minute) - Manual1 medical-relevant

Data: 2026-03-05  
Scop: smoke rapid pentru extensiile Manual1 (parteneri, numerotare, cost center, export HTML).

Folder evidenta:
- `exports/manual1_smoke_2026-03-05/`

## A) Preflight tehnic

- [x] `python -m py_compile pacienti_ai_independent/pacienti_ai_app.py` = `EXIT:0`
- [x] `python -m unittest discover -s tests -p "test_*.py"` = `EXIT:0` (`Ran 41 tests`)
- [x] `python -m unittest discover -s tests -p "test_manual1_*.py"` = `EXIT:0` (`Ran 10 tests`)
- [x] Smoke automat Manual1 (script DB/API end-to-end) = `PASS`
  - Evidenta: `MANUAL1_SMOKE_RESULT.json`, `MANUAL1_SMOKE_RESULT.txt`

## B) Smoke functional UI (manual)

1. Tab `Parteneri`: creare partener + contact + cont bancar.
- [ ] PASS
- [ ] FAIL
Artefact:

2. Tab `Parteneri`: creare centru cost root + copil.
- [ ] PASS
- [ ] FAIL
Artefact:

3. `Internari` -> `Consumuri`: adauga consum cu partener + centru cost.
- [ ] PASS
- [ ] FAIL
Artefact:

4. `Internari` -> `Facturare`: emite factura cu `Serie` + `Numar` goale (auto-numbering ON).
- [ ] PASS
- [ ] FAIL
Artefact:

5. `Internari` -> `Facturare`: export `Export facturi HTML`.
- [ ] PASS
- [ ] FAIL
Artefact:

## C) Rezultat smoke

- [ ] Smoke ACCEPTAT
- [ ] Smoke ACCEPTAT cu observatii
- [ ] Smoke RESPINS

Observatii:
- 
- 

Semnaturi:
- QA / Tester: ____________________  Data: __________
- Owner operational: ______________  Data: __________

