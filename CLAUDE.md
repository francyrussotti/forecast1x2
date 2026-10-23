# forecast1x2 — note per Claude Code

Previsioni 1X2 (Dixon-Coles + Elo + xG) per Serie A, Premier, Liga, Bundesliga, Ligue 1, con backtest walk-forward e dashboard Streamlit. Dettagli completi su modello, dati e risultati in `README.md`.

## Ambiente
- Python 3.9.6 in `.venv` (l'unico disponibile sul Mac): usa sempre `.venv/bin/python`, mai `python3` di sistema.
- Pacchetto installato in modalità editable da `src/forecast1x2` (`pip install -e .`).
- Dipendenze in `requirements.txt` (versioni bloccate per la compatibilità con 3.9).

## Comandi
```bash
.venv/bin/python -m pytest                       # test (~2 s)
.venv/bin/python -m forecast1x2 aggiorna         # update-data + predict
.venv/bin/python -m forecast1x2 backtest         # ~4 min
.venv/bin/streamlit run app/dashboard.py --server.address localhost
```
Per l'anteprima nel browser integrato c'è la configurazione `dashboard-progetto` in `.claude/launch.json` (porta 8502).

## Struttura
- `src/forecast1x2/`: `data.py` (download e normalizzazione), `model.py` (Dixon-Coles), `elo.py`, `xg.py`, `evaluation.py` (backtest), `auto.py` (aggiornamento automatico), `__main__.py` (CLI).
- `app/dashboard.py`: legge solo da `outputs/`, non rifà le stime.
- `data/raw/`: CSV football-data e JSON di calendari/xG scaricati. `data/team_names.csv`: mappatura dei nomi delle squadre per fonte.
- `outputs/`: previsioni, rating, iperparametri e risultati del backtest.
- File `.command`: launcher con doppio clic per l'utente (installazione, dashboard, launchd ogni 30 min con etichetta `com.forecast1x2.auto`).

## Regole
- Il token Sportmonks sta in `~/.config/forecast1x2/sportmonks_token` (o `SPORTMONKS_API_TOKEN`): non copiarlo mai nel progetto.
- Niente leakage: nel backtest si stima solo con partite anteriori alla settimana prevista.
- Un candidato nuovo per il modello si tiene solo se migliora la log-loss dell'ensemble di almeno 0,0005 sulle stagioni di calibrazione.
- Le previsioni non sono consigli di scommessa: l'avviso nella dashboard resta.
- Documentazione e messaggi all'utente in italiano.
