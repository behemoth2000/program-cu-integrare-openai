# Program cu integrare OpenAI

Acest repository contine aplicatia `PacientiAIIndependent`, mutata din proiectul mare in repo dedicat, cu dependintele necesare pentru rulare locala.

## Structura principala
- `pacienti_ai_independent/` - codul aplicatiei (UI, API intern, servicii, integrari)
- `tests/` - testele automate
- `requirements.txt` - dependinte Python
- `icd10.csv`, `ro_localities.csv` - date suport pentru diagnostice/adrese
- `run_pacienti_ai_independent.ps1` / `.bat` - scripturi locale de start

## Rulare
1. Creeaza mediu virtual:
   - `python -m venv .venv`
   - `.\.venv\Scripts\Activate.ps1` (PowerShell)
2. Instaleaza dependinte:
   - `pip install -r requirements.txt`
3. Ruleaza aplicatia:
   - `python -m pacienti_ai_independent.pacienti_ai_app`

## Teste
- `python -m unittest discover -s tests -p "test_*.py"`

## Note
- Baza de date implicita este in profilul utilizatorului (`%USERPROFILE%\PacientiAIIndependent`).
- Fisierele de export/log/cache sunt ignorate prin `.gitignore`.
