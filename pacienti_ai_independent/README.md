# Sistem Pacienti AI (rang spital)

Aplicatie desktop pentru flux clinic de spital:
- introducere pacienti (CRUD),
- note clinice pe pacient,
- internari (MRN, triage, sectie/salon/pat, externare),
- ordine medicale (lab/imaging/medicatie/procedura + status),
- semne vitale seriale,
- dashboard operational de sectie (internari active, ordine urgente, alerte vitale),
- dashboard cu evidentiere vizuala (triage critic/urgent, ordine stat, alerte vitale),
- notificari automate pentru alerte vitale critice (polling periodic + pop-up),
- confirmare (ACK) alerta vitala in dashboard + marcare vizuala,
- escaladare automata pentru alerte critice neconfirmate,
- tab statistici (zilnic/saptamanal, KPI, export CSV),
- backup automat baza de date + backup manual + restore din backup,
- lockout temporar la autentificare dupa incercari repetate esuate,
- autentificare pe rol (admin, medic, asistent, receptie),
- administrare utilizatori (admin): creare user, rol/status, reset parola,
- tab audit (admin/medic): filtre + export CSV + jump la pacient,
- tab Setari (admin): configurare notificari/escaladare, backup automat, lockout login,
- tab Setari (admin): configurare AI (model, cheie, temperatura, timeout, tokeni, roluri permise, template-uri),
- tab Setari (admin): export/import JSON pentru setari aplicatie,
- schimbare parola pentru utilizatorul curent,
- audit intern al actiunilor,
- export PDF (fisa pacient + raport internare/bilet externare + raport garda din dashboard),
- semnatura digitala simpla pe PDF (utilizator + timestamp + hash SHA-256),
- chat AI pe contextul pacientului selectat.
- AI cu output structurat (situatie/risc/recomandare/monitorizare), safety disclaimer si template-uri rapide.
- fisa extinsa (asigurare, contact urgenta, grupa sanguina, inaltime/greutate, istoric familial etc.).

Datele sunt locale in SQLite: `%USERPROFILE%\PacientiAIIndependent\pacienti_ai.db`.

## 1) Instalare

```powershell
cd "d:\Programe VSCODE\PacientiApp\pacienti_ai_independent"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 2) Configurare OpenAI

```powershell
$env:OPENAI_API_KEY="cheia_ta_openai"
$env:OPENAI_MODEL="gpt-5"   # optional
```

## 2.1) Configurare notificari externe (optional)

```powershell
$env:ALERT_NOTIFY_ENABLED="1"
$env:ALERT_NOTIFY_COOLDOWN_SECONDS="120"
$env:ALERT_POLL_SECONDS="45"
$env:ALERT_ESCALATION_MINUTES="10"
$env:ALERT_ESCALATION_COOLDOWN_SECONDS="600"
```

Lockout autentificare (optional):

```powershell
$env:LOGIN_LOCK_MAX_ATTEMPTS="5"
$env:LOGIN_LOCK_MINUTES="10"
```

Backup automat (optional):

```powershell
$env:AUTO_BACKUP_ENABLED="1"
$env:AUTO_BACKUP_INTERVAL_MINUTES="360"
$env:AUTO_BACKUP_RETENTION_DAYS="14"
```

Telegram:

```powershell
$env:ALERT_TELEGRAM_BOT_TOKEN="123456:ABC..."
$env:ALERT_TELEGRAM_CHAT_ID="-1001234567890"
```

Webhook:

```powershell
$env:ALERT_WEBHOOK_URL="https://exemplu.ro/alerts"
```

Email SMTP:

```powershell
$env:ALERT_SMTP_HOST="smtp.exemplu.ro"
$env:ALERT_SMTP_PORT="587"
$env:ALERT_SMTP_USER="user"
$env:ALERT_SMTP_PASS="parola"
$env:ALERT_EMAIL_FROM="alerts@exemplu.ro"
$env:ALERT_EMAIL_TO="garda1@spital.ro,garda2@spital.ro"
```

## 3) Rulare

```powershell
python pacienti_ai_app.py
```

## Conturi initiale

- La prima rulare se creeaza utilizatorii: `admin`, `medic`, `asistent`, `receptie`.
- Parolele nu mai sunt hardcodate in aplicatie.
- Le poti seta explicit din mediu:

```powershell
$env:PACIENTI_SEED_PASS_ADMIN="ParolaSigura1!"
$env:PACIENTI_SEED_PASS_MEDIC="ParolaSigura2!"
$env:PACIENTI_SEED_PASS_ASISTENT="ParolaSigura3!"
$env:PACIENTI_SEED_PASS_RECEPTIE="ParolaSigura4!"
```

- Daca variabilele lipsesc, aplicatia genereaza parole random si le scrie in:
	`%USERPROFILE%\PacientiAIIndependent\initial_credentials.txt`

## Teste regresie

Din radacina workspace-ului (`PacientiApp`):

```powershell
& "d:/Programe VSCODE/PacientiApp/.venv/Scripts/python.exe" -m unittest discover -s tests -p "test_pacienti_ai_regressions.py"
```

Testul verifica:
- migrarea automata de la hash legacy la PBKDF2 la autentificare,
- `create_patient` (insert SQL corect),
- KPI `urgent_orders` filtrat corect pe sectie.

## Observatii

- Aplicatia este independenta de codul vechi (`pacienti_desktop.py` etc.).
- Are validari la salvare (CNP 13 cifre, email, data `YYYY-MM-DD`, inaltime/greutate numerice).
- Pentru export PDF este necesar `reportlab` (inclus in `requirements.txt`).
- Optional: `ALERT_POLL_SECONDS` pentru intervalul de verificare al alertelor (default 45 sec).
- Debounce UI configurabil din tab-ul `Setari` (sau prin import/export setari):
	- `DASHBOARD_REFRESH_DEBOUNCE_SECONDS` (default `0.8`)
	- `EXPORT_DEBOUNCE_SECONDS` (default `0.9`)
	- `QUICK_EXPORT_DEBOUNCE_SECONDS` (default `1.2`)
	- preseturi rapide: `Conservator`, `Echilibrat`, `Rapid`
- Pentru notificari externe configurezi una sau mai multe canale: Telegram, Webhook, SMTP.
- Din header ai buton `Test notificari` pentru validare canale.
- Daca lipseste cheia API sau pachetul `openai`, aplicatia porneste, dar asistentul AI nu va raspunde.
- Evita trimiterea datelor sensibile inutile catre API-ul AI.

## Comunicare update

- Index complet materiale comunicare: [COMMS_INDEX.md](COMMS_INDEX.md)
- Shortcut din root workspace: [../README_COMMS.md](../README_COMMS.md)
