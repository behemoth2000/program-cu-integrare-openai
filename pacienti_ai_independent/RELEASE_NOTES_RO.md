# Note de release (utilizatori)

Data: 2026-03-02
Versiune: update operational Dashboard + Watchlist

## Noutati principale

- Dashboard mai stabil si mai predictibil:
  - filtrele de sectie si data operationala se pastreaza intre sesiuni;
  - reset rapid pentru filtre (`Reset filtre`);
  - reset combinat pentru Dashboard + Istoric (`Reset dashboard+istoric`).

- Istoric Watchlist extins:
  - vizualizare snapshot + trend risc;
  - export CSV/PDF pentru istoric;
  - `Export rapid CSV+PDF` cu un singur mesaj final.

- Statistici performanta export rapid:
  - KPI si detaliu zilnic pentru exporturile rapide de istoric watchlist;
  - export CSV/PDF si export rapid pentru aceasta zona.

## Imbunatatiri de experienta (anti dublu-click)

- Protectie debounce pe actiuni sensibile:
  - refresh Dashboard;
  - exporturi Dashboard, Statistici, Audit, Fisa pacient, Internare/Externare;
  - export/import setari JSON.

- Daca apesi prea repede, aplicatia afiseaza mesaj discret cu timpul ramas pana la urmatorul click permis.

## Setari noi (admin)

In tab-ul `Setari` poti ajusta:

- `Dashboard refresh debounce (sec)`
- `Export debounce standard (sec)`
- `Export debounce rapid (sec)`

Preseturi rapide disponibile:

- `Conservator`
- `Echilibrat`
- `Rapid`

Indicatorul `Preset activ` arata daca valorile curente corespund unui preset sau sunt `Custom`.

## Ce trebuie sa faci

- Pentru utilizare normala: nimic obligatoriu, update-ul functioneaza direct.
- Pentru ajustare debounce: intra in `Setari` (admin), aplica preset sau valori manuale, apoi `Salveaza setari`.

## Compatibilitate

- Nu necesita migrare manuala.
- Datele existente raman compatibile.
