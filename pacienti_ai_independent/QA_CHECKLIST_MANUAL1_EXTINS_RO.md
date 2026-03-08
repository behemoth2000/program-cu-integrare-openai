# QA Checklist Manual1 Extins - Charisma GAP (medical-relevant)

Data start UAT: 2026-03-05  
Data actualizare: 2026-03-05  
Scope: implementare Manual1 in `PacientiAIIndependent` (fara ERP contabil complet).

Referinte:
- Checklist rapid: `QA_CHECKLIST_5MIN_MANUAL1_RO.md`
- Smoke UI ghidat: `UAT_SMOKE_UI_MANUAL1_2026-03-05.md`
- GO/NO-GO: `GO_NO_GO_MANUAL1_ONE_PAGER_2026-03-05.md`
- Evidenta automata: `exports/manual1_smoke_2026-03-05/`

## 1) Preconditii UAT

- Build porneste fara erori.
- Preflight tehnic verde (`py_compile`, `unittest`).
- Setari runtime disponibile in `Setari`:
  - `DOCNUM_ENABLE_AUTO`
  - `ENABLE_COST_CENTER_ENFORCEMENT`
  - `ENABLE_HTML_EXPORTS_FINANCIAL`
  - `ORG_DEFAULT_CURRENCY`
  - `ORG_DEFAULT_LOCATION`
- Dataset UAT dedicat disponibil.

## 2) Matrice scenarii Manual1

| ID | Scenariu | Rezultat asteptat | Actual | Status | Evidenta | Defect/Severitate |
|---|---|---|---|---|---|---|
| TC-M1-TECH-01 | Compile | `py_compile` fara erori | `EXIT:0` | PASS | rulare shell 2026-03-05 |  |
| TC-M1-TECH-02 | Teste complete | `test_*.py` verde | `Ran 41 tests` | PASS | rulare shell 2026-03-05 |  |
| TC-M1-TECH-03 | Teste Manual1 | `test_manual1_*.py` verde | `Ran 10 tests` | PASS | rulare shell 2026-03-05 |  |
| TC-M1-AUTO-01 | Smoke automat end-to-end | partener + CC + consum + factura auto + export HTML | rezultat `PASS` | PASS | `exports/manual1_smoke_2026-03-05/MANUAL1_SMOKE_RESULT.json` |  |
| TC-M1-UI-01 | UI parteneri | CRUD partener + contact + cont bancar | Neexecutat manual | PENDING_UI | `UAT_SMOKE_UI_MANUAL1_2026-03-05.md` |  |
| TC-M1-UI-02 | UI cost centers | root + child + parinte vizibil | Neexecutat manual | PENDING_UI | `UAT_SMOKE_UI_MANUAL1_2026-03-05.md` |  |
| TC-M1-UI-03 | UI consumuri | consum salvat cu partener + cost center | Neexecutat manual | PENDING_UI | `UAT_SMOKE_UI_MANUAL1_2026-03-05.md` |  |
| TC-M1-UI-04 | UI facturare auto numar | serie/numar auto cand campurile sunt goale | Neexecutat manual | PENDING_UI | `UAT_SMOKE_UI_MANUAL1_2026-03-05.md` |  |
| TC-M1-UI-05 | UI export HTML | fisier HTML generat corect | Neexecutat manual | PENDING_UI | `UAT_SMOKE_UI_MANUAL1_2026-03-05.md` |  |

## 3) Criterii de acceptanta Manual1

1. 100% PASS pe `TC-M1-TECH-*` si `TC-M1-AUTO-*`.
2. 100% PASS pe scenariile UI `TC-M1-UI-*`.
3. 0 defecte `High/Critical` deschise.
4. Semnaturi QA + owner operational + tech owner.

Status curent:
- `4 PASS`
- `5 PENDING_UI`
- `0 FAIL`
- `0 defecte High/Critical` raportate

## 4) Concluzie UAT curenta

- [ ] GO UAT
- [x] NO-GO UAT (temporar)

Motive:
1. Pasii UI manuali (`TC-M1-UI-01..05`) nu sunt inca executati/semnati.

Semnaturi:
- QA lead: TBD  Data: __________
- Owner operational: TBD  Data: __________
- Tech owner: TBD  Data: __________

