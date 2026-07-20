# BG3 Character Builder

Install the dependencies and run the Dash development server:

```powershell
python -m pip install -r requirements.txt
python app_local.py
```

Open `http://127.0.0.1:8050` in a browser. The app reads `races.csv` and
`backgrounds.csv` at startup, so regenerated CSV data is reflected after a restart.

## Posit deployment

Publish the project directory with `app.py` as the entrypoint. It exposes both
the Dash application as `app` and its Flask server as `server`; it does not
start a local development server when imported by Posit Connect.
