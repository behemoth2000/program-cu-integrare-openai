# UAT Smoke UI Manual1 (Charisma GAP) - 2026-03-05

Scop: rulare manuala in UI pentru fluxul nou Manual1 (parteneri + centre cost + numerotare + export HTML).

Referinte:
- Evidenta automata precheck: `exports/manual1_smoke_2026-03-05/MANUAL1_SMOKE_RESULT.json`
- DB smoke dedicat: `exports/manual1_smoke_2026-03-05/manual1_smoke.db`
- Export HTML rezultat: `exports/manual1_smoke_2026-03-05/manual1_case_invoices_smoke.html`

## 1) Preconditii

1. Aplicatia porneste fara erori.
2. In `Setari` sunt active:
   - `DOCNUM_ENABLE_AUTO=1`
   - `ENABLE_COST_CENTER_ENFORCEMENT=1`
   - `ENABLE_HTML_EXPORTS_FINANCIAL=1`
3. Exista cel putin o internare activa pentru pacientul de test.

## 2) Smoke UI pas-cu-pas

### TC-M1-UI-01 Partener nou + contact + cont bancar
1. Tab `Parteneri` -> `Partener nou`.
2. Completeaza `Cod`, `Denumire`, `Tip` si `Salveaza partener`.
3. In subpanel `Contacte partener`, adauga un contact principal.
4. In subpanel `Conturi bancare partener`, adauga un IBAN implicit.

Rezultat asteptat:
- partenerul apare in lista;
- contactul si contul bancar apar in listele dedicate.

### TC-M1-UI-02 Centru de cost nou
1. In tab `Parteneri`, zona `Centre de cost / profit`, adauga centru root.
2. Adauga centru copil cu root ca `Parinte`.

Rezultat asteptat:
- ambele centre apar in lista;
- copilul afiseaza parintele corect.

### TC-M1-UI-03 Consum cu partener + centru cost
1. Selecteaza pacient + internare.
2. In `Internari` -> `Consumuri caz`, completeaza articolul.
3. Selecteaza `Partener` si `Centru cost`.
4. `Adauga consum`.

Rezultat asteptat:
- consumul este salvat;
- in tabel se vad `Partener` si `Centru cost`.

### TC-M1-UI-04 Factura cu numerotare automata
1. In `Internari` -> `Facturare`, lasa `Serie` si `Numar` goale.
2. Selecteaza `Partener` si `Centru cost`.
3. `Emite factura`.

Rezultat asteptat:
- factura este emisa cu `Serie/Numar` auto (ex: `M1/00001`);
- partenerul si centrul de cost sunt vizibile in tabel.

### TC-M1-UI-05 Export facturi HTML
1. In `Internari` -> `Facturare`, click `Export facturi HTML`.
2. Salveaza fisierul in folderul de evidenta UAT.

Rezultat asteptat:
- fisier `.html` creat;
- contine antet si randurile facturilor filtrate pe internarea curenta.

## 3) Evidenta recomandata

Pentru fiecare TC:
1. screenshot tab inainte/dupa
2. fisier text scurt cu pasii (`TC_M1_UI_<ID>_PASS.txt`)
3. exporturi rezultate (`.html` pentru TC-M1-UI-05)

Locatie recomandata:
- `exports/manual1_smoke_2026-03-05/ui_manual/`

## 4) Criteriu PASS

1. `TC-M1-UI-01..05` = `PASS`
2. 0 erori runtime/traceback in timpul smoke
3. semnatura QA pe checklist

