# Changelog recent (Dashboard / Watchlist / Debounce)

Data: 2026-03-02

## Ce s-a adaugat

- Persistenta filtre Dashboard:
  - `DASHBOARD_FILTER_DEPARTMENT`
  - `DASHBOARD_OPERATIONAL_DATE`
- Persistenta preferinte Istoric Watchlist:
  - interval ore, mod trend (`Toate` / `Doar cresteri`), sortare (coloana + directie)
- Exporturi extinse Dashboard:
  - Watchlist istoric CSV/PDF
  - Export rapid CSV+PDF (silent batch + popup final)
- Telemetrie export rapid watchlist in audit:
  - `duration_ms`, `snapshot_runs`, `trend_rows`, `files`
- Statistici performanta export rapid watchlist:
  - agregare zilnica + KPI
  - export CSV/PDF + export rapid
- Persistenta filtre Statistici:
  - `STATS_FILTER_DEPARTMENT`, `STATS_FILTER_DATE_FROM`, `STATS_FILTER_DATE_TO`

## UX / Operabilitate

- Butoane reset:
  - `Reset filtre` (Dashboard)
  - `Reset dashboard+istoric` (Dashboard + Istoric Watchlist)
- Debounce anti dublu-click:
  - `Refresh Dashboard`
  - exporturi Dashboard
  - exporturi Statistici
  - exporturi Audit / Fisa pacient / Internare / Bilet externare
  - export/import setari JSON
- Feedback debounce:
  - mesaj temporar in status
  - timp ramas real pana la urmatorul click
  - precizie sporita sub 1s (2 zecimale)

## Setari noi (admin)

Configurabile in tab-ul `Setari` + import/export JSON:

- `DASHBOARD_REFRESH_DEBOUNCE_SECONDS` (default `0.8`)
- `EXPORT_DEBOUNCE_SECONDS` (default `0.9`)
- `QUICK_EXPORT_DEBOUNCE_SECONDS` (default `1.2`)

Preseturi debounce in UI:

- `Conservator` (`1.2 / 1.5 / 2.0`)
- `Echilibrat` (`0.8 / 0.9 / 1.2`)
- `Rapid` (`0.4 / 0.5 / 0.8`)

Indicator preset activ:

- detectie automata (`Conservator`, `Echilibrat`, `Rapid`, `Custom`)
- culoare verde pentru preset cunoscut
- culoare portocalie pentru `Custom`
- hover-help pentru regula de detectie (toleranta `±0.05s`)

## Refactor / Stabilitate

- Unificare citire filtre Dashboard prin helper comun (`_resolve_dashboard_filters`)
- Eliminare apeluri redundante de refresh in bucle
- Preseturile debounce si toleranta extrase in constante comune:
  - `DEBOUNCE_PRESETS`
  - `DEBOUNCE_PRESET_TOLERANCE`
- Helper comun pentru format debounce (`_format_debounce_seconds`)
- Corectii analiza statica:
  - import `date`
  - helper `parse_iso_date`
  - import dinamic `openai` pentru medii fara stubs

## Validare efectuata

- `get_errors` pe `pacienti_ai_app.py`: fara erori
- `python -m py_compile pacienti_ai_independent/pacienti_ai_app.py`: `EXIT:0`
- `python _tmp_initdb_test.py`: `EXIT:0`

## Fisiere atinse (principal)

- `pacienti_ai_independent/pacienti_ai_app.py`
- `pacienti_ai_independent/README.md`
- `pacienti_ai_independent/CHANGELOG_RECENT.md`

---

## Val 3A closure (Shadow Mode + Dry-Run) - 2026-03-08

### Ce s-a adaugat

- API nou admin-only:
  - `GET /api/v1/ops/integration-dry-run-logs?limit=&provider=&operation=`
- Vizibilitate ops desktop:
  - buton nou `Vezi loguri dry-run` in `Setari`
  - popup cu loguri dry-run normalizate (provider/operation/http/latency/correlation)
- Hardening contract backend shadow:
  - validare target shadow + motiv de fail explicit
  - helper comun `process_shadow_sync_with_backend(...)` folosit unitar pentru procesare shadow

### Stabilitate / non-breaking

- SQLite ramane authoritative.
- Postgres ramane strict shadow, non-blocking.
- Dry-run SIUI/DRG + MEDIS ramane separat de statusurile business.

### Teste adaugate

- `tests/test_integration_dry_run_ops_api.py`
- `tests/test_shadow_processor_unified_path.py`
- extins `tests/test_enterprise_api_client.py` cu ruta noua dry-run ops
