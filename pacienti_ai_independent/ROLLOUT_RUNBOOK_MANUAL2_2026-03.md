# ROLLOUT RUNBOOK - Manual2 + Integrari Live (2026-03)

Data: 2026-03-04  
Scope rollout: Manual2 core + integrare live SIUI/DRG + MEDIS (REST JSON, hybrid direct + queue retry).

## 1) Roluri si ownership

- Release coordinator: TBD
- QA lead: TBD
- Owner operational: TBD
- Tech owner: TBD

## 2) Fereastra rollout

- T0 propus: 2026-03-07 09:00 (Europe/Bucharest)
- Durata rollout tehnic: 45-60 min
- Monitorizare intensiva: primele 24h dupa T0

## 3) Pre-rollout checklist (obligatoriu)

1. Preflight tehnic verde:
- `python -m py_compile pacienti_ai_independent/pacienti_ai_app.py`
- `python -m unittest discover -s tests -p "test_*.py"`

2. Manual2 core complet:
- `QA_CHECKLIST_MANUAL2_EXTINS_RO.md` (`15/15 PASS`)
- `QA_CHECKLIST_5MIN_RO.md` completat
- `QA_SIGNOFF.md` pregatit pentru semnaturi reale

3. Live sandbox complet:
- `TC-LIVE-SIUI-01`
- `TC-LIVE-DRG-01`
- `TC-LIVE-SIUI-02`
- `TC-LIVE-MEDIS-01`
- `TC-LIVE-MEDIS-02`
- `TC-LIVE-MEDIS-03`

4. Config runtime si secrete:
- Feature flags:
  - `SIUI_DRG_LIVE_ENABLED`
  - `MEDIS_LIVE_ENABLED`
- Endpoint-uri:
  - `SIUI_DRG_BASE_URL`, `SIUI_DRG_ENDPOINT_SIUI_SUBMIT`, `SIUI_DRG_ENDPOINT_DRG_SUBMIT`
  - `MEDIS_BASE_URL`, `MEDIS_ENDPOINT_ORDER_SUBMIT`, `MEDIS_ENDPOINT_RESULTS_PULL`
- Secrete ENV disponibile pe statii:
  - `SIUI_DRG_CLIENT_SECRET` / `SIUI_DRG_API_KEY` / `SIUI_DRG_BEARER_TOKEN`
  - `MEDIS_CLIENT_SECRET` / `MEDIS_API_KEY` / `MEDIS_BEARER_TOKEN`

5. Backup DB + setari:

```powershell
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$appDir = Join-Path $env:USERPROFILE "PacientiAIIndependent"
$srcDb = Join-Path $appDir "pacienti_ai.db"
$dstDir = "pacienti_ai_independent/exports/uat_evidence_2026-03-04"
New-Item -ItemType Directory -Force -Path $dstDir | Out-Null
Copy-Item $srcDb (Join-Path $dstDir ("backup_pacienti_ai_" + $stamp + ".db")) -Force
```

- Export setari din UI (`Setari` -> `Export setari JSON`) in acelasi folder.

## 4) Pasii rollout (fereastra controlata)

1. Confirma semnaturi QA/Owner/Tech.
2. Ruleaza din nou preflight tehnic.
3. Anunta inceputul ferestrei in canalul operational.
4. Activeaza feature flags live pe toate statiile:
   - `SIUI_DRG_LIVE_ENABLED=1`
   - `MEDIS_LIVE_ENABLED=1`
5. Smoke post-deploy pe statie pilot:
   - login
   - selectie pacient + internare
   - `Genereaza + valideaza` SIUI/DRG
   - `Marcheaza transmis` SIUI/DRG (live)
   - `Trimite ordin selectat` MEDIS (live)
   - `Pull rezultate live`
   - `Proceseaza queue acum` si `Vezi erori integrare`
6. Daca smoke pilot este PASS, continua pe toate statiile.

## 5) Criterii GO imediat post-rollout

- Smoke post-deploy: 100% PASS.
- Niciun crash la pornire sau pe flux critic.
- Nicio eroare blocanta la finalizare caz valid.
- `integration_outbox` fara crestere necontrolata (`failed`/`retry`).

## 6) Monitorizare 24h

Urmarire minima:
- erori runtime (traceback)
- blocaje pe finalizare caz
- anomalii status facturi/plati
- inconsistente status SIUI/DRG (`validated/submitted/transport_state`)
- inconsistente status MEDIS (`queued/sent/result_received/send_failed`)
- backlog `integration_outbox` (retry/failed)
- duplicate/idempotency anomalies

Logare evidenta:
- folder: `exports/uat_evidence_2026-03-04/monitoring_24h/`
- fisier sumar: `monitoring_summary_2026-03-07.md`

## 7) Trigger rollback

Rollback imediat daca apare oricare:
1. Crash repetitiv pe flux critic.
2. Coruptie date facturi/plati.
3. Imposibilitate finalizare caz pe scenariu valid.
4. Eroare sistemica integrare live (SIUI/DRG/MEDIS) fara fallback functional.

## 8) Procedura rollback

1. Oprire utilizare flux live nou (anunt operational imediat).
2. Dezactivare feature flags live:
   - `SIUI_DRG_LIVE_ENABLED=0`
   - `MEDIS_LIVE_ENABLED=0`
3. `Proceseaza queue acum` doar pentru inchidere jobs necritice (sau stop worker).
4. Revenire setari la profil anterior din JSON exportat.
5. Restaurare backup DB doar daca exista coruptie de date.
6. Retest smoke minim dupa restore.
7. Comunicare incident + ETA remediere.

## 9) Mesaj de inchidere fereastra

- Daca GO: "Rollout Manual2 + Integrari live finalizat, monitorizare 24h activa."
- Daca NO-GO: "Rollout oprit, rollback executat, urmeaza remediere conform plan incident."
