# UAT Execution Log Sprint 1

Data executie: __________________
Build testat: __________________
Tester: __________________
Owner operational: __________________

## Rezumat

- Total scenarii: 12
- PASS: ____
- FAIL: ____
- BLOCKER: ____
- Recomandare UAT: [ ] GO  [ ] NO-GO

## Log detaliat scenarii

| ID | Epic | Scenariu | Rezultat (PASS/FAIL) | Severitate defect (daca FAIL) | Evidenta (screenshot/export) | Observatii scurte |
|---|---|---|---|---|---|---|
| S1-E1-01 | S1-E1 | Filtru Programati la internare afiseaza corect pacientii |  |  |  |  |
| S1-E1-02 | S1-E1 | Filtru Pacienti internati afiseaza corect pacientii |  |  |  |  |
| S1-E1-03 | S1-E1 | Filtru Programati la externare afiseaza corect pacientii |  |  |  |  |
| S1-E1-04 | S1-E1 | Filtru Externati fara decont final afiseaza corect pacientii |  |  |  |  |
| S1-E1-05 | S1-E1 | Persistenta + reset filtre status receptie functioneaza |  |  |  |  |
| S1-E2-01 | S1-E2 | Programare internare valida se salveaza corect |  |  |  |  |
| S1-E2-02 | S1-E2 | Conflict internare (resursa/interval) este blocat cu mesaj explicit |  |  |  |  |
| S1-E2-03 | S1-E2 | La creare internare, booking-ul din zi curenta trece in completed |  |  |  |  |
| S1-E3-01 | S1-E3 | Conflict operatie sala/medic este detectat |  |  |  |  |
| S1-E3-02 | S1-E3 | Previzualizare ocupare + highlight + filtru Doar conflicte functioneaza |  |  |  |  |
| S1-E4-01 | S1-E4 | Externare blocata cand lipseste regula activa (decont/rezumat) |  |  |  |  |
| S1-E4-02 | S1-E4 | Externare reusita pe tranzitia valida si audit prezent |  |  |  |  |

## Log audit verificat

| Eveniment audit asteptat | Gasit (DA/NU) | Detalii |
|---|---|---|
| create_admission cu transition=scheduled_admission->active sau direct->active |  |  |
| discharge_admission cu transition=active->scheduled_discharge->discharged |  |  |
| create_booking / update_booking_status pentru cazurile testate |  |  |

## Defecte deschise

| ID defect | Severitate | Descriere | Owner | ETA |
|---|---|---|---|---|
|  |  |  |  |  |
|  |  |  |  |  |

## Decizie finala UAT

- [ ] GO UAT
- [ ] NO-GO UAT

Motive decizie:
- 
- 
- 

Semnaturi:
- QA Tester: __________________  Data: __________
- Owner operational: __________  Data: __________
- Tech owner: __________________ Data: __________
