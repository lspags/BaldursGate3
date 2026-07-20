# BG3 Character Builder

Install the dependency and run the Dash development server:

```powershell
python -m pip install -r requirements.txt
python app.py
```

Open `http://127.0.0.1:8050` in a browser. The app reads `races.csv` and
`backgrounds.csv` at startup, so regenerated CSV data is reflected after a restart.
