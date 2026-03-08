# QA Sign-off - Manual2 extins + Integrari live

Data: 2026-03-04  
Versiune: manual2-live-hybrid-uat

## 1) Checklist acceptanta tehnica

- [x] `python -m py_compile pacienti_ai_independent/pacienti_ai_app.py` = `EXIT:0`
- [x] `python -m unittest discover -s tests -p "test_*.py"` = `EXIT:0` (`Ran 30 tests`)
- [x] Aplicatia porneste/importa fara traceback la deschidere (smoke local)
- [x] Dataset UAT dedicat creat in `exports/uat_evidence_2026-03-04`

## 2) Checklist acceptanta functionala Manual2 (core)

- [x] TC-FIN-01 Factura proforma emisa si listata
- [x] TC-FIN-02 Factura finala emisa dupa externare
- [x] TC-FIN-03 Plati partiale pastreaza status factura `issued`
- [x] TC-FIN-04 Achitare integrala seteaza status factura `paid`
- [x] TC-FIN-05 `is_case_financially_closed` devine `true` doar la inchidere completa
- [x] TC-SIUI-01 Payload SIUI valid
- [x] TC-SIUI-02 SIUI marcat `submitted` cu referinta externa
- [x] TC-DRG-01 Payload DRG valid
- [x] TC-DRG-02 DRG marcat `submitted` cu referinta externa
- [x] TC-MEDIS-01 Ordin trimis MEDIS, status ordin `in_progress`
- [x] TC-MEDIS-02 Rezultat MEDIS inregistrat, status ordin `done`
- [x] TC-CASE-01 Finalizare caz cu reguli ON (SIUI+DRG + inchidere economica)
- [x] TC-CASE-02 Finalizare caz cu reguli OFF (backward-compatible)
- [x] TC-REG-01 Flux internare/externalizare fara regresii
- [x] TC-REG-02 Exporturi FO/checklist existente functionale

Evidenta automata: `exports/uat_evidence_2026-03-04/TC_*_PASS.json`.

## 2.1) Checklist integrare live (sandbox)

- [x] Precheck local `TC-LIVE-SIUI-01` (mocked)
- [x] Precheck local `TC-LIVE-DRG-01` (mocked)
- [x] Precheck local `TC-LIVE-SIUI-02` retry queue (mocked dispatcher/outbox)
- [x] Precheck local `TC-LIVE-MEDIS-01` submit order (mocked)
- [x] Precheck local `TC-LIVE-MEDIS-02` pull rezultat (mocked)
- [x] Precheck local `TC-LIVE-MEDIS-03` fallback manual
- [ ] Executie sandbox reala `TC-LIVE-SIUI-01`
- [ ] Executie sandbox reala `TC-LIVE-DRG-01`
- [ ] Executie sandbox reala `TC-LIVE-SIUI-02`
- [ ] Executie sandbox reala `TC-LIVE-MEDIS-01`
- [ ] Executie sandbox reala `TC-LIVE-MEDIS-02`
- [ ] Executie sandbox reala `TC-LIVE-MEDIS-03`

## 3) Criterii critice GO

- [x] 100% PASS pe scenarii critice Manual2 core
- [x] Minim 95% PASS total pe Manual2 core
- [x] 0 defecte High/Critical deschise (pe executia automata)
- [ ] 100% PASS pe TC critice live in sandbox real

## 4) Rezultat curent

- [ ] ACCEPTAT pentru productie (GO)
- [ ] ACCEPTAT conditionat (GO cu observatii)
- [x] RESPINS (NO-GO)

Observatii:
- Manual2 core este inchis tehnic (`15/15 PASS`).
- Integrarea live este pregatita tehnic si acoperita prin precheck automat local.
- Decizia ramane `NO-GO` pana la rularea sandbox real + semnaturi reale.

## 5) Semnaturi reale obligatorii

- QA lead: TBD  Data: __________
- Owner operational: TBD  Data: __________
- Tech owner: TBD  Data: __________
