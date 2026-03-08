# Update rapid Pacienti AI (2026-03-02)

## Ce e nou (pe scurt)

- Dashboard: filtrele (sectie + data) se salveaza intre sesiuni.
- Reset rapid:
  - `Reset filtre`
  - `Reset dashboard+istoric`
- Istoric Watchlist: export CSV/PDF + `Export rapid CSV+PDF`.
- Statistici: monitorizare performanta pentru exporturile rapide watchlist.
- Protectie anti dublu-click (debounce) pe refresh/export/import setari.

## Pentru admin (optional)

In `Setari` poti ajusta debounce:
- `Dashboard refresh debounce (sec)`
- `Export debounce standard (sec)`
- `Export debounce rapid (sec)`

Preseturi: `Conservator`, `Echilibrat`, `Rapid`.

## Impact

- Mai putine click-uri duplicate accidentale.
- Exporturi mai curate (fara batch-uri dublate).
- Flux de dashboard mai stabil in tura.

Detalii complete: `RELEASE_NOTES_RO.md`.
