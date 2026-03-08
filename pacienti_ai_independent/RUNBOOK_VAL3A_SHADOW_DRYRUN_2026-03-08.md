# Runbook Val 3A - Shadow Sync + Dry-Run

Data: 2026-03-08

## Scop
Acest runbook descrie operarea in productie/pilot pentru:
- shadow sync SQLite -> Postgres (fara cutover),
- dry-run SIUI/DRG + MEDIS (fara efect business).

## Setari runtime relevante
- `API_INTERNAL_POSTGRES_SHADOW_ENABLED` (0/1)
- `API_INTERNAL_POSTGRES_SHADOW_MAX_RETRIES`
- `API_INTERNAL_POSTGRES_SHADOW_BATCH_SIZE`
- `API_INTERNAL_POSTGRES_SHADOW_INTERVAL_SECONDS`
- `API_INTERNAL_POSTGRES_SHADOW_STOP_ON_ERROR_RATE`
- `SIUI_DRG_DRY_RUN` (0/1)
- `MEDIS_DRY_RUN` (0/1)

## Operare zilnica (Ops)
1. Verifica `Testeaza health API`.
2. Verifica `Vezi status shadow sync`:
   - `shadow_backlog_pending`
   - `shadow_error_rate_24h`
   - `attempted_24h` / `failed_24h`
3. Verifica `Vezi erori shadow sync` pentru ultimele joburi failed/retry.
4. Verifica `Vezi loguri dry-run` pentru transport SIUI/DRG + MEDIS.
5. Daca backlog-ul e ridicat, ruleaza `Proceseaza shadow sync acum`.

## Reguli de protectie
- Daca `shadow_error_rate_24h` depaseste `API_INTERNAL_POSTGRES_SHADOW_STOP_ON_ERROR_RATE`, shadow se auto-opreste.
- Auto-stop nu blocheaza write-ul principal (SQLite).
- Dry-run nu modifica statusurile clinice/financiare.

## Incident response
1. Simptome: backlog mare, multe failed, latenta mare dry-run, erori conexiune Postgres.
2. Actiuni:
   - verifica DSN (`PACIENTI_POSTGRES_DSN`) si conectivitatea Postgres,
   - analizeaza erorile din `Vezi erori shadow sync`,
   - daca este nevoie, mentine shadow OFF (`API_INTERNAL_POSTGRES_SHADOW_ENABLED=0`) pana la remediere,
   - reruleaza procesarea manuala dupa fix.
3. Confirmare remediere:
   - backlog in scadere,
   - error rate sub prag,
   - fara erori noi repetitive.

## Rollback operational
1. Seteaza `API_INTERNAL_POSTGRES_SHADOW_ENABLED=0`.
2. Pastreaza API intern activ pe SQLite.
3. Continua operarea normala; incidentul ramane non-blocking pentru fluxurile clinice/economice.

## Audit/trasabilitate
- Audit keys principale:
  - `shadow_sync_manual_process`
  - `shadow_sync_auto_stop`
  - `integration_dry_run_manual`
  - `integration_dry_run_logs_view`
- Correlation ID este inclus in logurile dry-run si in executiile joburilor.
