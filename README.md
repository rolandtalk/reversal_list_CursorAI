# Reversal List (Cursor AI / Dupe)

Stock Reversal Point Analysis Web App (MA3 reversal detection).

**Deployment (this repo):** [https://reversalX.up.railway.app](https://reversalX.up.railway.app)  
This is a duplicate of the production repo; the domain above is used to avoid confusion with the main production site.

## Run locally

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
export FLASK_APP=app.py && .venv/bin/flask run
```

Open http://127.0.0.1:5000

## Override base URL

To use a different public URL (e.g. for another deployment):

```bash
export APP_BASE_URL=https://your-domain.example.com
```

Default is `https://reversalX.up.railway.app`.
