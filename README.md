# forecast1x2

Previsioni 1X2 con un modello Dixon-Coles per Serie A, Premier League, Liga, Bundesliga e Ligue 1.
Include un backtest walk-forward contro le quote di chiusura e una dashboard Streamlit.

## Uso rapido (macOS)

1. **Prima volta:** doppio clic su `installa.command`. Crea l'ambiente Python, scarica i dati e calcola le previsioni; ci vuole qualche minuto.
2. **Ogni volta:** doppio clic su `Avvia dashboard.command`. Si apre il browser su http://localhost:8501; chiudi la finestra del Terminale per fermare la dashboard.
3. **Prima di ogni giornata:** nella dashboard premi **«Aggiorna dati e previsioni»** nella barra a sinistra, oppure da terminale lancia `.venv/bin/python -m forecast1x2 aggiorna`.
   - Il momento migliore è venerdì pomeriggio, quando football-data pubblica le quote pre-partita.
   - La dashboard avvisa se i dati hanno più di 3 giorni o se le partite sono già iniziate.

### Aggiornamento automatico in base alle partite

**Su GitHub (in uso da ottobre 2026).** Il workflow `.github/workflows/aggiorna.yml` lancia `python -m forecast1x2 auto` ogni ora e salva nel repository i dati, le previsioni e il registro dei consigli aggiornati; la dashboard su Streamlit Cloud si aggiorna da sola. Gira senza Sportmonks, quindi le previsioni usano solo i gol (vedi la sezione xG). Si può lanciare a mano dalla scheda Actions → «Aggiornamento automatico» → Run workflow. Se lo usi, non tenere attivo anche l'aggiornamento sul Mac.

**Sul Mac (alternativa).** Doppio clic su `attiva aggiornamento automatico.command`. Da quel momento macOS lancia `python -m forecast1x2 auto` ogni 30 minuti.

**Quando aggiorna davvero:** il comando scarica e ricalcola solo se, dall'ultimo aggiornamento, è passato uno di questi momenti:

- 24 ore prima di una partita;
- 3 ore prima di una partita;
- 3 ore dopo una partita;
- 24 ore dopo una partita;
- in ogni caso, se l'ultimo aggiornamento ha più di 24 ore.

Negli altri controlli esce subito, senza accedere alla rete.

**Se qualcosa va storto:**

- un aggiornamento fallito (per esempio perché sei offline) viene ritentato al controllo successivo;
- si esegue un solo aggiornamento alla volta: se ne parte un secondo, per esempio dal pulsante della dashboard mentre è in corso quello automatico, viene rifiutato con un messaggio;
- le fonti facoltative non bloccano mai l'aggiornamento: xG, quote pre-partita e calendario di riserva. Se mancano si usano gli ultimi dati disponibili, e la dashboard mostra un avviso giallo;
- le quote pre-partita si usano solo se la data coincide con quella della partita e sono state scaricate da meno di 7 giorni;
- un file di una stagione chiusa a cui mancano più di 2 partite blocca l'aggiornamento: va riscaricato con `update-data --force`;
- non si fanno previsioni per squadre senza dati storici: quasi sempre è un errore di mappatura dei nomi.
- il registro delle operazioni è in `logs/auto.log`;
- la dashboard mostra nella barra a sinistra se l'aggiornamento automatico è attivo e quando è previsto il prossimo.

**Note:**

- Funziona solo quando il Mac è acceso e hai effettuato l'accesso. I controlli saltati durante lo stop vengono recuperati al risveglio.
- Per spegnerlo: doppio clic su `disattiva aggiornamento automatico.command`.
- Se sposti la cartella del progetto, rilancia lo script di attivazione.

Se macOS blocca i file `.command` alla prima apertura: tasto destro sul file → Apri → Apri.

La dashboard è raggiungibile solo da questo computer (`localhost`).

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/pip install -e .
```

Testato con Python 3.9.6, l'unico disponibile su questa macchina. Con Python ≥ 3.10 funzionano anche versioni più recenti delle librerie.

## Comandi

```bash
.venv/bin/python -m forecast1x2 aggiorna             # update-data + predict, il comando di tutti i giorni
.venv/bin/python -m forecast1x2 update-data          # scarica e normalizza dati e calendari
.venv/bin/python -m forecast1x2 update-data --force  # riscarica anche le stagioni chiuse
.venv/bin/python -m forecast1x2 backtest             # calibra ξ, λ e w (2022/23 + 2023/24), backtest su 2024/25 e 2025/26 (~4 min)
.venv/bin/python -m forecast1x2 predict              # previsioni della prossima giornata
.venv/bin/python -m forecast1x2 consigli-backtest    # verifica storica della regola dei consigli in prova
.venv/bin/streamlit run app/dashboard.py --server.address localhost   # dashboard su http://localhost:8501
.venv/bin/python -m pytest                           # test
```

Uso tipico durante la stagione: `update-data`, poi `predict`, poi aggiornare la dashboard.
Se `outputs/hyperparams.json` non esiste, `predict` calibra prima gli iperparametri.
Le quote pre-partita (`fixtures.csv` di football-data) escono pochi giorni prima di ogni giornata, di solito il venerdì: conviene rilanciare `update-data` e `predict` a ridosso del weekend.

## Dati

| Fonte | Uso |
|---|---|
| football-data.co.uk `mmz4281/{SSSS}/{DIV}.csv`, dal 2020/21 al 2026/27 | risultati, quote di apertura e di chiusura (prima divisione) |
| football-data.co.uk, stesse stagioni, I2/E1/SP2/D2/F2 | risultati di seconda divisione, per stimare le neopromosse |
| football-data.co.uk `fixtures.csv` | quote pre-partita delle prossime partite (solo come quote, non come calendario) |
| fixturedownload.com `feed/json/{slug}-2026` | calendario (fonte primaria) |
| openfootball `2026-27/{it.1,…}.json` | calendario (fallback) |

- **Download:** un file viene sovrascritto solo se la risposta è HTTP 200, l'intestazione è quella attesa e c'è almeno una riga. Le stagioni chiuse non si riscaricano, salvo con `--force`.
- **Quote di chiusura:** media di mercato (`AvgCH/CD/CA`), con `B365CH/CD/CA` come fallback riga per riga. La colonna `odds_source` indica quale è stata usata.
- **Quote di apertura:** media di mercato (`AvgH/D/A`), con `B365H/D/A` come fallback. football-data le raccoglie il venerdì (o il martedì per le partite infrasettimanali), quindi prima della partita: si possono usare senza leakage.
- **Risultati mancanti:** se manca in prima divisione, la pipeline si ferma. In seconda divisione la riga viene scartata e segnalata; a ottobre 2026 succede per Bastia–Red Star, Ligue 2 2025/26.
- **Nomi delle squadre:** `data/team_names.csv` mappa i nomi dei calendari sui nomi di football-data, separatamente per campionato e per fonte. Se una squadra non è mappata, la pipeline si ferma con un errore.
- **Validazione del calendario:** un calendario deve contenere tutte le coppie casa/trasferta senza ripetizioni, e ogni squadra deve giocare n−1 partite in casa e n−1 in trasferta. Se la fonte primaria non supera il controllo, si usa openfootball e viene stampato un avviso. A ottobre 2026 succede per la Ligue 1: fixturedownload riporta Rennes–PSG due volte e non ha PSG–Rennes.
- **Partite giocate:** una partita del calendario conta come giocata quando compare nei risultati di football-data, oppure quando il calendario stesso riporta già il punteggio (football-data può arrivare con uno o due giorni di ritardo).
- **Prossima giornata:** è il `RoundNumber` più basso con almeno metà delle partite ancora da giocare. Le partite non giocate di giornate precedenti vengono mostrate con un'etichetta:
  - *recupero*, se hanno una data futura;
  - *rinviata*, se la data è già passata senza risultato.

## Modello

Il modello è un Dixon-Coles stimato separatamente per ogni campionato. La stima usa sia le partite di prima divisione sia quelle della seconda divisione corrispondente. Il tasso di gol della squadra di casa è

log λ = μ + δ·[seconda divisione] + casa + attacco_casa + difesa_trasferta + κ·(neo_trasf − neo_casa)

e per la squadra in trasferta vale lo stesso, senza il termine casa e con il segno di κ invertito.

- **Seconda divisione:** le squadre che salgono o scendono collegano le due scale, così una neopromossa parte da un rating basato sui dati e non dalla media del campionato. δ è il diverso livello di gol in seconda divisione.
- **κ:** misura quanto rende di meno una squadra nella prima stagione dopo la promozione rispetto a quanto direbbe il suo rating. Serve perché la forza non resta costante quando si cambia divisione. Viene stimato dai dati: a ottobre 2026 vale tra 0,03 e 0,13 a seconda del campionato.
- **Correzione dei punteggi bassi:** τ corregge 0-0, 1-0, 0-1 e 1-1, con il parametro ρ limitato all'intervallo [−0.2, 0.2].
- **Identificabilità:** Σattacco = Σdifesa = 0, imposta tramite la parametrizzazione.
- **Pesi e penalità:** ogni partita pesa exp(−ξ·giorni), con una penalità L2 di peso λ su attacco e difesa.
- **Stima:** L-BFGS-B con gradiente analitico, verificato numericamente nei test.
- **Probabilità:** dalla matrice dei punteggi 0–10 rinormalizzata si ricavano 1/X/2, i gol attesi e il risultato più probabile.

### Iperparametri (`outputs/hyperparams.json`)

- **ξ e λ:** sono comuni a tutti i campionati e scelti su una griglia, minimizzando la log-loss walk-forward sul 2022/23 e sul 2023/24, quindi prima del backtest. Ho provato anche a sceglierli per campionato, ma è overfitting: scegliendoli sul 2022/23 e valutandoli sul 2023/24, la log-loss era 0,9857 per campionato contro 0,9751 con valori comuni.
- **w:** è il peso del modello nel pool logaritmico con le quote di apertura senza margine, P ∝ P_modello^w · P_mercato^(1−w). È calibrato sulle stesse stagioni e oggi vale **0**: il modello non aggiunge informazione alle quote di apertura.

## Valutazione

- **Walk-forward:** il backtest procede per settimane di calendario (da lunedì). Ogni settimana si ristima il modello usando solo le partite con data anteriore al lunedì.
- **Confronti, sulle stesse partite:**
  - modello + quote di apertura (pool con peso w);
  - quote di apertura senza margine;
  - quote di chiusura senza margine, il riferimento principale (normalizzazione proporzionale; il metodo di Shin come confronto);
  - frequenze storiche 1/X/2 del campionato, calcolate solo sul passato.
- **Metriche:** log-loss, Brier multiclasse e RPS, per campionato, per stagione e in totale.
- **Intervallo di confidenza:** IC 95% bootstrap sulla differenza tra ciascuna fonte e il mercato di chiusura. Si ricampionano settimane intere, perché le partite della stessa settimana non sono indipendenti.

## File in outputs/

| File | Contenuto |
|---|---|
| `predictions.csv` | previsioni della prossima giornata, con recuperi e partite rinviate; quando le quote pre-partita sono disponibili, anche le probabilità di mercato (`market_*`) e il pool (`comb_*`) |
| `ratings.csv` | attacco e difesa stimati per le squadre della stagione in corso, con l'indicazione delle neopromosse; κ non è incluso |
| `meta.json` | data dell'aggiornamento dei dati, ξ, vantaggio casa e ρ per campionato |
| `hyperparams.json` | ξ, λ, w e le griglie di calibrazione |
| `backtest_matches.csv` | probabilità per partita di tutte le fonti, con `train_max_date` per il controllo del leakage |
| `backtest_metrics.csv` | metriche aggregate |
| `backtest_bootstrap.csv` | IC bootstrap della differenza modello − mercato |
| `calibration.csv` | dati per la calibrazione |

La dashboard legge solo da questi file e non rifà le stime.

## Ensemble Dixon-Coles + Elo e affidabilità

**Storico.** Si parte dalla stagione 2015/16, per prima e seconda divisione. Le stagioni 2019/20 di Ligue 1 e Ligue 2, interrotte per il COVID, sono un'eccezione dichiarata nel controllo di completezza. Nel Dixon-Coles le partite con peso sotto 0,001 sono escluse dalla stima, perché non contano nulla e la rallentano.

**Calibrazione.** Gli iperparametri si scelgono sulle stagioni 2021/22, 2022/23 e 2023/24, tutte precedenti al backtest. Valori attuali:
- Dixon-Coles: ξ = 0,002 (emivita circa 347 giorni), λ = 0,25.
- Elo: K = 15, regressione verso la media tra le stagioni 0,1.
- Ensemble: 0,6 Dixon-Coles + 0,4 Elo.
- Peso degli xG: 0,5.

**Il secondo modello.** Accanto al Dixon-Coles c'è un modello diverso (`src/forecast1x2/elo.py`): rating Elo aggiornati partita per partita, con un moltiplicatore per la differenza reti, più una regressione logistica ordinale che trasforma la differenza di rating in P(1), P(X), P(2). Le neopromosse partono dalla media delle squadre retrocesse. La regressione ordinale usa solo le settimane precedenti.

**L'OLS** (regressione lineare con minimi quadrati) è incluso solo come confronto: è il peggiore dei modelli testati.

**Risultati** su 3.504 partite (2024/25 e 2025/26):

| Fonte | Log-loss | Esito più probabile indovinato | Errore medio delle probabilità | Capacità vs mercato |
|---|---|---|---|---|
| **Ensemble + xG (in uso)** | **0,9857** | 52% | ±1,4 pp | **84%** |
| Ensemble senza xG | 0,9872 | 53% | ±1,4 pp | 83% |
| Dixon-Coles | 0,9888 | 52% | ±1,7 pp | 81% |
| Elo | 0,9890 | 52% | ±1,4 pp | 81% |
| OLS | 0,9977 | 52% | ±1,7 pp | 73% |
| Mercato di chiusura | 0,9691 | 54% | ±1,3 pp | 100% |
| Baseline (frequenze 1/X/2) | 1,0748 | 43% | ±0,8 pp | 0% |

- Lo storico dal 2015 ha migliorato tutti i modelli rispetto a quello dal 2020: ensemble −0,0017, Elo −0,0029.
- Rispetto al solo Dixon-Coles, l'ensemble con xG migliora la log-loss di −0,0031, con IC 95% da −0,0053 a −0,0012: un miglioramento significativo.
- Il distacco dal mercato di chiusura resta significativo (+0,017).

**Candidati provati e scartati.** Sono stati valutati solo sulle stagioni di calibrazione, con la regola fissata prima: si tiene un candidato solo se migliora la log-loss dell'ensemble di almeno 0,0005. I pesi scelti sugli stessi dati sono stati misurati lasciando fuori una stagione a rotazione.

| Candidato | Guadagno | Esito |
|---|---|---|
| Correzione dei pareggi | +0,00001 | scartato |
| Pi-ratings (rating dinamici) come terzo modello | +0,00037 | scartato, sotto soglia |
| Vantaggio casa per squadra | da −0,0006 a −0,0009 | scartato, peggiora |
| Giorni di riposo, solo dalle partite di campionato | −0,00004 | scartato |
| Coppe europee e calendario fitto | — | non provato: su openfootball c'è solo la Champions 2024/25 |

## Livelli di rischio e simulazione scommesse

**Le previsioni non sono consigli di scommessa.** La dashboard lo ricorda in ogni pagina delle previsioni.

**Livelli di rischio.** Ogni partita ha un livello, in base alla probabilità dell'esito più probabile:

| Livello | Probabilità del favorito | Partite (backtest 2024-26) | Il favorito ha vinto (modello + xG) |
|---|---|---|---|
| 🟢 1, basso | ≥ 60% | 23% | 72% |
| 🟡 2, medio | 45–60% | 43% | 51% |
| 🔴 3, alto | < 45% | 35% | 40% |

Le percentuali si aggiornano a ogni backtest (`outputs/risk_tiers.csv`). La colonna «Modello − mercato» mostra dove il modello dà a un esito più probabilità delle quote pre-partita: è un'informazione, non un suggerimento.

**Simulazione scommesse** (`outputs/betting_sim.csv`, pagina Backtest). Sono state simulate giocate da 1 unità a partita, alle quote medie pre-partita, sul 2024/25 e sul 2025/26:

| Strategia | Rendimento | IC 95% |
|---|---|---|
| Gioca dove il modello «vede valore» (soglie 0%, 5%, 10%) | da −17% a −22% | sempre sotto zero |
| Gioca sempre il favorito del mercato (riferimento) | −3,4% | circa il margine del bookmaker |

Le cifre valgono sia per il modello sui soli gol sia per quello con xG. Il modello «vede valore» soprattutto dove sbaglia rispetto al mercato.

## Consigli in prova: over/under 2.5

Un registro di giocate **simulate** (1 unità, nessun soldo vero) per verificare in avanti l'unica idea che nello storico ha mostrato un segnale. Codice in `src/forecast1x2/tips.py`, pagina «Consigli in prova» nella dashboard.

**Ricerca (ottobre 2026).** Sullo stesso storico 2015-2026 dei 10 campionati sono state provate le strategie con un fondamento nella letteratura. Le soglie sono state scelte sul 2015/16-2023/24 e verificate sul 2024/25-2025/26. Nessuna batte il mercato in modo affidabile:

| Strategia (quota migliore disponibile) | Verifica 2024-26 |
|---|---|
| Modello del progetto contro la quota migliore | da −5% a −18% |
| 1X2 con la quota migliore molto sopra la media (Kaunitz et al., 2017) | −28% |
| Sempre gli sfavoriti (probabilità < 20%) | −15% |
| Sempre il pareggio (quota ≥ 2,62) / sempre i favoriti forti | circa 0% |
| **Over/under 2.5 con la quota migliore molto sopra la media** | **segnale, ma su pochi casi** |

**Regola `ou25-v1`, congelata il 23/10/2026.** Con le quote del venerdì di football-data (`fixtures.csv`):
- probabilità «giusta» = quote medie over/under senza margine;
- vantaggio = quota migliore × probabilità giusta − 1, sul lato migliore;
- consiglio se il vantaggio supera il 2%, in prima e seconda divisione.

La soglia è stata scelta sul periodo di calibrazione (`python -m forecast1x2 consigli-backtest`, risultati in `outputs/tips_backtest.csv`):

| Periodo | Giocate | Rendimento | IC 95% |
|---|---|---|---|
| Calibrazione 2015-24, tutte | 1.197 | +3,8% | da −3,4% a +11,4% |
| di cui seconda divisione | 385 | +16,0% | da +3,9% a +28,4% |
| Verifica 2024-26, tutte | 105 | +5,1% | da −18,9% a +30,6% |
| di cui seconda divisione | 42 | +32,4% | da −5,4% a +68,0% |

Il segnale c'è solo in seconda divisione, con circa 100 casi a stagione in tutto: per questo è una prova e non un consiglio.

**Come funziona il registro** (`data/tips/ou_register.csv`):
- si aggiorna da solo a ogni `update-data`/`aggiorna`/`auto`; un errore del registro non blocca mai le previsioni;
- una partita entra una volta sola, almeno un'ora prima dell'inizio, con le quote di quel momento, e non viene più modificata;
- dopo la partita la giocata diventa «vinta» o «persa»; se dopo 7 giorni manca il risultato (partita rinviata) diventa «annullata».

**Limiti.**
- La quota migliore è la più alta tra i bookmaker raccolti da football-data, che non dice quale. Spesso coincide con Betfair Exchange, dove sulle vincite si paga una commissione.
- Chi vince con regolarità viene limitato dai bookmaker: è successo anche agli autori dello studio del 2017.
- Prima di qualsiasi conclusione serve almeno una stagione intera di prova.

## xG (expected goals): disattivati da ottobre 2026

**Decisione (23/10/2026).** Sportmonks è stato tolto dall'aggiornamento automatico su GitHub. Il guadagno degli xG è piccolo e non statisticamente certo: ensemble 0,9857 con xG contro 0,9872 senza; sul solo Dixon-Coles −0,0012 di log-loss, con IC 95% da −0,0035 a +0,0011. In pratica le previsioni cambiano di pochi decimi di punto percentuale. Senza xG le previsioni usano automaticamente il peso xG 0 e la dashboard mostra le statistiche dell'ensemble senza xG. Il registro dei consigli non usa gli xG.

Il codice è rimasto: con la chiave Sportmonks (file o variabile qui sotto) gli xG tornano attivi, ad esempio lanciando gli aggiornamenti dal Mac. Quanto segue descrive come funzionavano.

Gli xG per partita arrivano da Sportmonks (piano Starter + add-on xG).
La chiave si legge da `~/.config/forecast1x2/sportmonks_token`, un file fuori dal progetto e leggibile solo dall'utente; in alternativa dalla variabile `SPORTMONKS_API_TOKEN`.

- **Copertura:** sul nostro abbonamento gli xG partono dal **2024/25** (controllato a ottobre 2026). Le stagioni precedenti non restituiscono partite.
- **Test incrociato:** il 2024/25 viene previsto con il peso degli xG scelto sul 2025/26 (0,5), e il 2025/26 con quello scelto sul 2024/25 (0,75). Le stime del modello usano sempre solo partite passate; l'unica scelta che attraversa le stagioni è il peso. Risultati dell'ottobre 2026 su 3.504 partite:

  | Fonte | Log-loss |
  |---|---|
  | Modello, solo gol | 0,9902 |
  | Modello + xG | 0,9873 |
  | Mercato di chiusura | 0,9691 |

  - Rispetto al modello sui soli gol, gli xG migliorano di −0,0029 (IC 95% da −0,0058 a +0,0002): l'effetto va nella stessa direzione in entrambe le stagioni ed è quasi significativo.
  - Il distacco dal mercato resta significativo: +0,018.
- **Previsioni:** usano il peso scelto sulle due stagioni insieme, 0,75.
- **Dove si vede:** il backtest principale resta sui soli gol, per essere confrontabile con i risultati precedenti. Il test xG è in `outputs/xg_metrics.csv` e `outputs/xg_bootstrap.csv`, e nella dashboard (pagina Backtest).
- **Nomi delle squadre:** 121 nomi di Sportmonks mappati in `data/team_names.csv` (`source = sportmonks`). La mappatura è stata ricavata confrontando le partite con football-data e ritrova il 100% delle partite giocate.

Fonti gratuite scartate:

| Fonte | Motivo |
|---|---|
| Understat | `robots.txt` con `Disallow: /` |
| FBref | risponde 403 alle richieste automatiche |
| Sofascore | risponde 403 alle richieste automatiche |
| FotMob | vieta `/api/` nel `robots.txt` |
| xgscore.io | i termini d'uso vietano di copiare i dati |
