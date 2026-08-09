# BG3 Character Builder

Install the dependencies and run the Dash development server:

```powershell
python -m pip install -r requirements.txt
python app_local.py
```

Open `http://127.0.0.1:8050` in a browser. The app reads `races.csv` and
`backgrounds.csv` at startup, so regenerated CSV data is reflected after a restart.

## Rule and data checks

Core calculations live in `bg3_rules.py` rather than tooltip text. Run the
standard-library test suite after changing rules or scraped data:

```powershell
python -m unittest discover -s tests -v
```

The suite covers ability modifiers, point buy, proficiency, prepared spells,
weapon ability selection, reference builds, and basic CSV integrity.

## Posit deployment

Publish the project directory with `app.py` as the entrypoint. It exposes both
the Dash application as `app` and its Flask server as `server`; it does not
start a local development server when imported by Posit Connect.

The published entrypoint enables optional email/password accounts and saved
builds. Configure these encrypted environment variables in Posit Connect:

- `DATABASE_URL`: a PostgreSQL connection URL for the application's own database.
- `SECRET_KEY`: a long random value used to sign login sessions.

The application uses a local `bg3_published_local.db` SQLite file only when
`DATABASE_URL` is absent. The local `app_local.py` launcher disables accounts
entirely and preserves the original session-only development workflow.
