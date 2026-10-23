"""Streamlit dashboard. Reads only from outputs/; refits only when the user presses "Aggiorna"."""
import json
import subprocess
import sys
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from forecast1x2.auto import last_update_time, load_kickoffs, next_update
from forecast1x2.data import LEAGUES
from forecast1x2.evaluation import SOURCES, calibration_table, outcome_index, probs, rps

ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = ROOT / "outputs"
STALE_DAYS = 3
RISK_LABELS = {1: "🟢 1 · basso", 2: "🟡 2 · medio", 3: "🔴 3 · alto"}
DISCLAIMER = ("Le previsioni non sono consigli di scommessa. Nel backtest 2024-26 il modello non batte le quote "
              "di mercato, e puntare dove «vede valore» avrebbe perso tra il 13% e il 22% di quanto puntato "
              "(dettagli nella pagina Backtest). Il gioco può causare dipendenza.")
AGENT_PLIST = Path.home() / "Library" / "LaunchAgents" / "com.forecast1x2.auto.plist"
TZ = "Europe/Rome"
LEAGUE_NAMES = {d: v[0] for d, v in LEAGUES.items()}
SEASON_NAMES = {"2425": "2024/25", "2526": "2025/26", "tutte": "Tutte"}
DAYS = ["lun", "mar", "mer", "gio", "ven", "sab", "dom"]
STATUS = {"giornata": "", "recupero": "recupero", "rinviata": "rinviata, data da definire"}

CHART_SOURCES = ["model", "market_open", "market", "baseline"]
COLOR = alt.Color("Fonte", scale=alt.Scale(domain=[SOURCES[s] for s in CHART_SOURCES],
                                           range=["#e4572e", "#8e44ad", "#2e86de", "#9e9e9e"]))

st.set_page_config(page_title="Forecast 1X2", layout="wide")


@st.cache_data
def read_csv(name, **kw):
    path = OUTPUTS / name
    return pd.read_csv(path, **kw) if path.exists() else None


def read_meta():
    path = OUTPUTS / "meta.json"
    return json.loads(path.read_text()) if path.exists() else {}


def fmt_time(iso):
    return pd.Timestamp(iso).tz_convert(TZ).strftime("%d/%m/%Y %H:%M")


def sidebar_update(meta):
    """Runs update-data + predict in a separate process on demand (a few seconds to ~1 minute)."""
    st.sidebar.divider()
    if meta.get("data_updated_at"):
        st.sidebar.caption(f"Dati aggiornati il {fmt_time(meta['data_updated_at'])}")
    if AGENT_PLIST.exists():
        nxt = next_update(pd.Timestamp.now(tz="UTC"), load_kickoffs(), last_update_time())
        st.sidebar.caption(f"Aggiornamento automatico attivo · prossimo verso il {nxt.tz_convert(TZ):%d/%m %H:%M}")
    else:
        st.sidebar.caption("Aggiornamento automatico non attivo (vedi README)")
    if st.sidebar.button("Aggiorna dati e previsioni", width="stretch"):
        with st.spinner("Scarico risultati, quote e calendari e rifaccio le previsioni..."):
            try:
                r = subprocess.run([sys.executable, "-W", "ignore", "-m", "forecast1x2", "aggiorna"], cwd=ROOT,
                                   capture_output=True, text=True, timeout=1800)
                ok, log = r.returncode == 0, r.stdout + r.stderr
            except subprocess.TimeoutExpired:
                ok, log = False, "Tempo scaduto (30 minuti)."
        st.session_state["update_result"] = (ok, log)
        st.cache_data.clear()
        st.rerun()
    if "update_result" in st.session_state:
        ok, log = st.session_state["update_result"]
        (st.sidebar.success if ok else st.sidebar.error)(
            "Aggiornamento completato." if ok else "Aggiornamento fallito: dettagli qui sotto.")
        with st.sidebar.expander("Dettagli aggiornamento", expanded=not ok):
            st.code(log or "(nessun output)", language=None)


def model_vs_market(p: pd.DataFrame) -> list:
    """Largest gap (percentage points) where the model is above the margin-free market, e.g. '+6 su 2'."""
    out = []
    for r in p.itertuples():
        if pd.isna(r.market_1):
            out.append("")
            continue
        gaps = {o: 100 * (getattr(r, mp) - getattr(r, mk)) for o, mp, mk in
                [("1", "p1", "market_1"), ("X", "px", "market_X"), ("2", "p2", "market_2")]}
        o = max(gaps, key=gaps.get)
        out.append(f"+{gaps[o]:.0f} pp su {o}" if gaps[o] >= 1 else "allineato")
    return out


def source_in_use(meta, available) -> str:
    """The forecast shown on the predictions page: ensemble, with xG if they are active."""
    available = set(available)
    return "ensemble_xg" if meta.get("xg_weight") and "ensemble_xg" in available else "ensemble"


def reliability_panel(meta):
    rel = read_csv("reliability.csv")
    if rel is None:
        return
    r = rel.set_index("source")
    src = source_in_use(meta, r.index)
    if src not in r.index or "market" not in r.index:
        return
    m, k = r.loc[src], r.loc["market"]
    st.markdown("**Affidabilità del modello** (backtest 2024/25 e 2025/26, 3.504 partite)")
    c1, c2, c3 = st.columns(3)
    c1.metric("Esito più probabile indovinato", f"{m.accuracy_pct:.0f}%",
              f"{m.accuracy_pct - k.accuracy_pct:+.1f} punti rispetto al mercato", delta_color="off")
    c2.metric("Errore medio delle probabilità", f"±{m.calib_error_pp:.1f} punti %",
              help="Quando il modello dice 40%, l'esito si verifica in media tra il 40 − x e il 40 + x %.")
    c3.metric("Capacità predittiva rispetto al mercato", f"{m.market_share_pct:.0f}%",
              help="100% = prevede bene quanto le quote di chiusura; 0% = come le sole frequenze storiche 1/X/2.")
    st.caption(f"Per confronto, le quote di chiusura indovinano l'esito più probabile il {k.accuracy_pct:.0f}% "
               "delle volte. Nel calcio anche il miglior pronostico sbaglia quasi una partita su due.")


def risk_legend(meta):
    """How often the favourite actually won in each risk level (backtest of the model in use)."""
    rt = read_csv("risk_tiers.csv")
    if rt is None:
        return
    source = source_in_use(meta, rt.source)
    rt = rt[rt.source == source].set_index("level")
    st.caption("Rischio = quanto è netto il pronostico (probabilità dell'esito più probabile: "
               "≥ 60% basso, 45–60% medio, < 45% alto). Nel backtest 2024-26 il favorito ha vinto: "
               + " · ".join(f"{RISK_LABELS[l]} {100 * rt.loc[l, 'fav_win_rate']:.0f}% delle volte"
                            for l in rt.index) + ".")


def page_predictions():
    st.title("Previsioni")
    st.info(DISCLAIMER)
    reliability_panel(read_meta())
    preds, meta = read_csv("predictions.csv"), read_meta()
    if preds is None:
        st.error("Nessuna previsione ancora. Premi «Aggiorna dati e previsioni» nella barra a sinistra.")
        return
    now = pd.Timestamp.now(tz="UTC")
    age = now - pd.Timestamp(meta["data_updated_at"])
    if age > pd.Timedelta(days=STALE_DAYS):
        st.warning(f"Dati aggiornati {age.days} giorni fa: premi «Aggiorna dati e previsioni» prima di usarle.")
    for w in meta.get("warnings", []):   # fallback sources, stale calendar/odds/xG from the last update
        st.warning(w)
    div = st.selectbox("Campionato", list(LEAGUE_NAMES), format_func=LEAGUE_NAMES.get)
    p = preds[preds.league == div]
    if p.empty:
        st.info("Nessuna partita in programma per questo campionato.")
        return
    st.subheader(f"Giornata {p.loc[p.status == 'giornata', 'round'].max()}")

    kickoff_utc = pd.to_datetime(p.kickoff_utc, utc=True)
    kickoff = kickoff_utc.dt.tz_convert(TZ)
    started = (kickoff_utc <= now) & (p.status != "rinviata")
    note = [" · ".join(x for x in [STATUS[s] + (f" (giornata {r})" if s != "giornata" else ""),
                                   "già iniziata" if st_ else ""] if x)
            for s, r, st_ in zip(p.status, p["round"], started)]
    if started.all():
        st.warning("Tutte le partite di questa giornata sono già iniziate: aggiorna per passare alla prossima.")
    table = pd.DataFrame({
        "Data e ora (Roma)": kickoff.dt.dayofweek.map(dict(enumerate(DAYS))) + " " + kickoff.dt.strftime("%d/%m %H:%M"),
        "Partita": p.home + " – " + p.away,
        "1 %": (100 * p.p1).round(1),
        "X %": (100 * p.px).round(1),
        "2 %": (100 * p.p2).round(1),
        "Gol attesi casa": p.xg_home.round(2),
        "Gol attesi trasf.": p.xg_away.round(2),
        "Risultato più probabile": p.top_score + "  (" + (100 * p.top_score_prob).round(1).astype(str) + "%)",
        "Rischio": p.risk_level.map(RISK_LABELS),
        "Favorito": p.fav,
        "Mercato 1 %": (100 * p.market_1).round(1),
        "Mercato X %": (100 * p.market_X).round(1),
        "Mercato 2 %": (100 * p.market_2).round(1),
        "Modello − mercato": model_vs_market(p),
        "Note": note,
    })
    st.dataframe(table, hide_index=True, width="stretch")
    if (p.status != "giornata").any():
        st.caption("Recupero/rinviata: partite di giornate precedenti non ancora giocate.")
    risk_legend(meta)
    if p.market_1.isna().all():
        st.caption("Quote pre-partita non ancora disponibili: football-data le pubblica pochi giorni prima della giornata.")
    else:
        st.caption("Mercato = quote medie pre-partita (football-data) senza margine. "
                   f"Peso del modello nella combinazione calibrato sul passato: w = {meta.get('w')}"
                   + (" (il modello non aggiunge informazione alle quote)." if meta.get("w") == 0 else "."))

    m = meta.get("model", {}).get(div, {})
    st.caption(
        f"Ultimo aggiornamento dati: {fmt_time(meta['data_updated_at'])} · "
        f"ultima partita nei dati: {meta['last_match_date'][div]} · "
        f"previsioni generate: {fmt_time(meta['predictions_generated_at'])} · "
        f"vantaggio casa {m.get('home', float('nan')):.3f}, ρ {m.get('rho', float('nan')):.3f}, "
        f"κ neopromosse {m.get('kappa', float('nan')):.3f}, ξ {meta.get('xi')}, λ {meta.get('l2')}"
    )


def xg_section(league, season):
    """Cross-season test of the xG model (2024/25 and 2025/26), if the backtest produced it."""
    xm, xb = read_csv("xg_metrics.csv", dtype={"season": str}), read_csv("xg_bootstrap.csv", dtype={"season": str})
    if xm is None or xb is None:
        return
    meta = read_meta()
    st.subheader("Test degli xG (2024/25 e 2025/26)")
    st.caption("Test incrociato: ogni stagione è prevista con il peso degli xG scelto sull'altra stagione, "
               "sulle stesse partite del mercato. Le previsioni usano il peso scelto su entrambe: "
               f"{meta.get('xg_weight')}.")
    sel = xm[(xm.league == league) & (xm.season == season)].set_index("source")
    sel = sel.loc[[s for s in SOURCES if s in sel.index]]
    st.dataframe(pd.DataFrame({
        "Fonte": [SOURCES[s] for s in sel.index], "Partite": sel.n.to_numpy(),
        "Log-loss": sel.log_loss.round(4).to_numpy(), "Brier": sel.brier.round(4).to_numpy(),
        "RPS": sel.rps.round(4).to_numpy(),
    }), hide_index=True, width="stretch")
    b = xb[(xb.league == league) & (xb.season == season)]
    st.dataframe(pd.DataFrame({
        "Confronto": ["Modello + xG − " + {"model": "Modello (solo gol)", "market": "Mercato chiusura"}[a]
                      for a in b.against],
        "Metrica": b.metric.to_numpy(), "Differenza media": b.mean_diff.round(4).to_numpy(),
        "IC 95%": [f"{lo:+.4f} … {hi:+.4f}" for lo, hi in zip(b.ci_low, b.ci_high)],
    }), hide_index=True, width="stretch")
    st.caption("Valori negativi = Modello + xG migliore.")


def betting_section():
    """Historical simulation of betting on the model's 'value' picks at pre-match odds."""
    sim = read_csv("betting_sim.csv")
    if sim is None:
        return
    st.subheader("Simulazione scommesse (2024/25 e 2025/26)")
    st.caption("1 unità per partita, quote medie pre-partita, al massimo una giocata per partita. "
               "«Valore»: si gioca l'esito con valore atteso (probabilità × quota − 1) sopra la soglia. "
               "«Favorito del mercato»: si gioca sempre il favorito delle quote, come riferimento.")
    names = {k: v for k, v in SOURCES.items()}
    st.dataframe(pd.DataFrame({
        "Modello": sim.source.map(names).to_numpy(),
        "Strategia": ["Favorito del mercato" if s == "favorito" else f"Valore > {100 * t:.0f}%"
                      for s, t in zip(sim.strategy, sim.threshold)],
        "Giocate": sim.bets.to_numpy(), "Vinte": sim.wins.to_numpy(),
        "Guadagno (unità)": sim.profit.round(1).to_numpy(),
        "Rendimento": [f"{100 * r:+.1f}%" for r in sim.roi],
        "IC 95%": [f"{100 * lo:+.1f}% … {100 * hi:+.1f}%" for lo, hi in zip(sim.ci_low, sim.ci_high)],
    }), hide_index=True, width="stretch")
    st.caption("Rendimento negativo = perdita per unità giocata. Tutte le strategie del modello perdono più "
               "del margine del bookmaker: il modello «vede valore» soprattutto dove sbaglia.")


def page_backtest():
    st.title("Backtest walk-forward")
    metrics = read_csv("backtest_metrics.csv", dtype={"season": str})
    boot = read_csv("backtest_bootstrap.csv", dtype={"season": str})
    matches = read_csv("backtest_matches.csv", parse_dates=["date", "week_start"], dtype={"season": str})
    if metrics is None or boot is None or matches is None:
        st.error("Nessun backtest in outputs/. Lancia `python -m forecast1x2 backtest`.")
        return

    c1, c2 = st.columns(2)
    league = c1.selectbox("Campionato", ["tutti"] + list(LEAGUE_NAMES),
                          format_func=lambda d: "Tutti" if d == "tutti" else LEAGUE_NAMES[d])
    season = c2.selectbox("Stagione", ["tutte", "2425", "2526"], format_func=SEASON_NAMES.get)

    sel = metrics[(metrics.league == league) & (metrics.season == season)].set_index("source")
    sel = sel.loc[[s for s in SOURCES if s in sel.index]]
    st.dataframe(pd.DataFrame({
        "Fonte": [SOURCES[s] for s in sel.index], "Partite": sel.n.to_numpy(),
        "Log-loss": sel.log_loss.round(4).to_numpy(), "Brier": sel.brier.round(4).to_numpy(),
        "RPS": sel.rps.round(4).to_numpy(),
    }), hide_index=True, width="stretch")

    st.caption("Differenze rispetto al mercato di chiusura (IC 95% bootstrap per settimane). "
               "Valori positivi = peggiore del mercato di chiusura.")
    b = boot[(boot.league == league) & (boot.season == season)]
    st.dataframe(pd.DataFrame({
        "Fonte": b.source.map(SOURCES).to_numpy(), "Metrica": b.metric.to_numpy(),
        "Differenza media": b.mean_diff.round(4).to_numpy(),
        "IC 95%": [f"{lo:+.4f} … {hi:+.4f}" for lo, hi in zip(b.ci_low, b.ci_high)],
    }), hide_index=True, width="stretch")

    df = matches
    if league != "tutti":
        df = df[df.league == league]
    if season != "tutte":
        df = df[df.season == season]
    df = df.sort_values("date").reset_index(drop=True)

    xg_section(league, season)
    betting_section()
    rel = read_csv("reliability.csv")
    if rel is not None:
        st.subheader("Affidabilità di tutti i modelli (2024/25 e 2025/26)")
        rel = rel.set_index("source").loc[[s for s in SOURCES if s in set(rel.source)]]
        st.dataframe(pd.DataFrame({
            "Fonte": [SOURCES[s] for s in rel.index],
            "Esito più probabile indovinato": [f"{v:.1f}%" for v in rel.accuracy_pct],
            "Errore medio probabilità": [f"±{v:.1f} pp" for v in rel.calib_error_pp],
            "Miglioramento sulla baseline": [f"{v:.1f}%" for v in rel.skill_vs_baseline_pct],
            "Capacità vs mercato": [f"{v:.0f}%" for v in rel.market_share_pct],
            "Log-loss": rel.log_loss.round(4).to_numpy(),
        }), hide_index=True, width="stretch")
        st.caption("«Capacità vs mercato»: quanta parte del vantaggio delle quote di chiusura sulla baseline "
                   "il modello riesce a ottenere (100% = come il mercato).")

    st.subheader("Calibrazione")
    outcome = st.radio("Esito", ["1", "X", "2"], horizontal=True)
    cal = calibration_table(df)
    cal = cal[(cal.outcome == outcome) & cal.source.isin(CHART_SOURCES)].copy()
    cal["Fonte"] = cal.source.map(SOURCES)
    diag = alt.Chart(pd.DataFrame({"x": [0, 1], "y": [0, 1]})).mark_line(
        strokeDash=[4, 4], color="gray").encode(x="x", y="y")
    pts = alt.Chart(cal).mark_line(point=True).encode(
        x=alt.X("mean_pred", title="Probabilità prevista", scale=alt.Scale(domain=[0, 1])),
        y=alt.Y("obs_freq", title="Frequenza osservata", scale=alt.Scale(domain=[0, 1])),
        color=COLOR, tooltip=["Fonte", alt.Tooltip("mean_pred", format=".3f"),
                                alt.Tooltip("obs_freq", format=".3f"), "n"])
    st.altair_chart(diag + pts, use_container_width=True)

    st.subheader("RPS medio cumulato")
    y = outcome_index(df)
    long = [pd.DataFrame({"Data": df.date, "Fonte": SOURCES[s],
                          "RPS cumulato": pd.Series(rps(probs(df, s), y)).expanding().mean()})
            for s in CHART_SOURCES]
    line = alt.Chart(pd.concat(long)).mark_line().encode(
        x="Data:T", y=alt.Y("RPS cumulato", scale=alt.Scale(zero=False)), color=COLOR)
    st.altair_chart(line, use_container_width=True)


page = st.sidebar.radio("Pagina", ["Previsioni", "Backtest"])
sidebar_update(read_meta())
if page == "Previsioni":
    page_predictions()
else:
    page_backtest()
