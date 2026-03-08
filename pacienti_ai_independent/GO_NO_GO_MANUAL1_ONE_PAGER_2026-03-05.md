# GO / NO-GO One-Pager - Manual1 medical-relevant (2026-03-05)

## Context

- Release scope: GAP Manual1 (Charisma) -> implementare medical-relevant
- Include:
  - registru parteneri + contacte + conturi bancare
  - centre de cost
  - numerotare documente centralizata
  - asociere partener/centru cost in consumuri/facturi/deconturi
  - export HTML facturi (feature-flag)

## GO Gates

- [x] Validare tehnica finala
  - `python -m py_compile ...` = `EXIT:0`
  - `python -m unittest discover -s tests -p "test_*.py"` = `EXIT:0` (`Ran 41 tests`)
- [x] Teste Manual1 dedicate
  - `python -m unittest discover -s tests -p "test_manual1_*.py"` = `EXIT:0` (`Ran 10 tests`)
- [x] Smoke automat end-to-end Manual1
  - `MANUAL1_SMOKE_RESULT.json` = `PASS`
- [ ] Smoke UI manual complet (`TC-M1-UI-01..05`)
- [ ] Checklist Manual1 semnat (`QA_CHECKLIST_5MIN_MANUAL1_RO.md`, `QA_CHECKLIST_MANUAL1_EXTINS_RO.md`)
- [ ] Semnaturi reale QA / Owner operational / Tech owner

## Evaluare risc

- Risc tehnic: Mediu (extindere schema + validari noi pe fluxuri financiare)
- Risc operational: Mediu (schimbare UX in tab-uri noi/actualizate)
- Fallback disponibil: Da
  - `DOCNUM_ENABLE_AUTO=0`
  - `ENABLE_COST_CENTER_ENFORCEMENT=0`
  - `ENABLE_HTML_EXPORTS_FINANCIAL=0`

## Decizie curenta

- [ ] GO
- [x] NO-GO (temporar)

## Motive NO-GO curent

1. Smoke UI manual nu este inca executat si semnat.
2. Lipsesc semnaturile reale QA/Owner/Tech.

## Actiuni pentru trecere la GO

1. Ruleaza `UAT_SMOKE_UI_MANUAL1_2026-03-05.md` cap-coada.
2. Completeaza `QA_CHECKLIST_5MIN_MANUAL1_RO.md` si `QA_CHECKLIST_MANUAL1_EXTINS_RO.md`.
3. Completeaza semnaturi reale.
4. Reconfirma preflight in ziua rollout.

## Aprobari

- QA lead: TBD  Data: __________
- Owner operational: TBD  Data: __________
- Tech owner: TBD  Data: __________

