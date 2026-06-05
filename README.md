# Reversal List (Cursor AI / Dupe)

Stock Reversal Point Analysis Web App (MA3 reversal detection).

**Deployment (this repo):** [https://reversal.up.railway.app](https://reversal.up.railway.app)  
This is a duplicate of the production repo; the domain above is used to avoid confusion with the main production site.

## Run locally

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
export FLASK_APP=app.py && .venv/bin/flask run
```

Open http://127.0.0.1:5000

## Google Sheets storage

This app now uses Google Sheets for the tracked symbol list and SIM positions.

- Default sheet id: `1Rq-qt_rg6JiGX63xOcr2pvR-HWoILhL2fqeOrrO37Og`
- Override it with `GOOGLE_SHEET_ID`
- Public sheet sharing is enough for reads
- Shared writes can use either a Google service account or a Google Apps Script web app
- If neither shared write mode is configured, the app still supports local add/remove overrides in the current runtime

### Required tabs

- `symbols`
  - `symbol`, `active`, `added_at`, `notes`
- `sim_positions`
  - `symbol`, `shares`, `cost`, `buy_date`, `active`, `updated_at`
- `audit_log`
  - `timestamp`, `action`, `table_name`, `symbol`, `old_value`, `new_value`, `actor`, `notes`

### Enable shared writes with Apps Script

This is the easiest way to avoid embedding Google credentials in the app runtime.

1. Open [script.google.com](https://script.google.com) and create a new Apps Script project.
2. Paste in the contents of [google_sheet_bridge.gs](/Users/rolandtalkonmini/Documents/Debug%20Reversal/google_sheet_bridge.gs).
3. In `Project Settings`, add a script property named `SHARED_SECRET` if you want to protect the endpoint.
4. Deploy the script as a `Web app`:
   - Execute as: `Me`
   - Who has access: `Anyone`
5. Set these environment variables in the app:

```bash
export GOOGLE_SHEET_ID=1Rq-qt_rg6JiGX63xOcr2pvR-HWoILhL2fqeOrrO37Og
export GOOGLE_APPS_SCRIPT_WEB_APP_URL='https://script.google.com/macros/s/.../exec'
export GOOGLE_APPS_SCRIPT_SHARED_SECRET='your-shared-secret'
```

### Enable shared writes with a service account

1. Create a Google service account with Sheets API access.
2. Share the spreadsheet with that service account email as an editor.
3. Set one of these environment variables:

```bash
export GOOGLE_SHEET_ID=1Rq-qt_rg6JiGX63xOcr2pvR-HWoILhL2fqeOrrO37Og
export GOOGLE_SERVICE_ACCOUNT_JSON='{"type":"service_account", ... }'
```

Or:

```bash
export GOOGLE_SERVICE_ACCOUNT_FILE=/absolute/path/to/service-account.json
```

## Override base URL

To use a different public URL (e.g. for another deployment):

```bash
export APP_BASE_URL=https://your-domain.example.com
```

Default is `https://reversal.up.railway.app`.
