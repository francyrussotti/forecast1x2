"""Consigliere: la giocata più probabile di ogni partita e le schedine, con regole tratte dallo storico.

Regole (verifica 2024/25-2025/26 alle quote Bet365, vedi README «Schedina consigliata»):
  - la giocata più probabile di ogni partita perde in media solo il margine del bookmaker (−3,6%),
    quasi nulla con quote basse (1,01-1,30: +0,1%);
  - ogni partita in più in una multipla costa altri 3-4 punti (doppia −4%, tripla −10%, cinquina −16%);
  - il «valore» contro il consenso su un singolo bookmaker non ha retto (−50% sulla verifica).
Quindi: giocata più probabile, nei mercati dove il bookmaker trattiene meno, in singola o al massimo in doppia.
Per lo stesso incontro il regolamento prevede i mercati Combo: due esiti della stessa partita non vanno in multipla.
"""
from itertools import combinations, product

import numpy as np
import pandas as pd

MIN_ODDS = 1.20        # sotto, la vincita non ripaga il rischio di sbagliare
MAX_ODDS = 2.50        # sopra, il margine del bookmaker cresce (fascia 3-5: −12%, oltre 5: −29%)
MAX_COST = 0.06        # rendimento atteso non peggiore di −6% (il margine tipico dei mercati principali)
EXCLUDED_GROUPS = {"Draw no bet"}   # probabilità condizionata al non pareggio: non confrontabile con le altre
EXOTIC_GROUPS = ["Multigoal", "Combo DC + U/O", "Combo DC + Multigoal", "Combo 1X2 + U/O", "Combo DC + GG/NG"]
POOL = 15              # le schedine si cercano tra le migliori POOL giocate


MIN_PROB_CHEAP = 0.60  # la giocata «più conveniente» deve comunque essere probabile
KEYS = ["league", "home", "away"]


def candidates(vt: pd.DataFrame, min_odds: float = MIN_ODDS, max_odds: float = MAX_ODDS) -> pd.DataFrame:
    """Bookmaker prices worth considering: sensible odds, not much worse than fair, no suspicious quotes."""
    if vt.empty:
        return vt
    c = vt[(vt.odds >= min_odds) & (vt.odds <= max_odds) & (vt.value >= -MAX_COST)
           & (vt.verdict != "quota sospetta") & ~vt.group.isin(EXCLUDED_GROUPS)]
    return c.copy()


def best_picks(vt: pd.DataFrame, min_odds: float = MIN_ODDS, max_odds: float = MAX_ODDS) -> pd.DataFrame:
    """One pick per match: the most probable candidate (ties: higher value)."""
    c = candidates(vt, min_odds, max_odds)
    if c.empty:
        return c
    c = c.sort_values(["prob", "value"], ascending=False)
    return c.drop_duplicates(KEYS).sort_values("prob", ascending=False).reset_index(drop=True)


def cheapest_picks(vt: pd.DataFrame, min_prob: float = MIN_PROB_CHEAP) -> pd.DataFrame:
    """One pick per match: the candidate with the smallest bookmaker margin among those with prob >= min_prob."""
    c = candidates(vt)
    c = c[c.prob >= min_prob] if not c.empty else c
    if c.empty:
        return c
    c = c.sort_values(["value", "prob"], ascending=False)
    return c.drop_duplicates(KEYS).sort_values("value", ascending=False).reset_index(drop=True)


def exotic_suggestions(fair: pd.DataFrame, lo: float = 1.30, hi: float = 2.50) -> pd.DataFrame:
    """Per match, the most probable Combo/Multigoal with fair odds in [lo, hi]: odds to ask the bookmaker for.

    fair: rows of markets.fair_odds_for for one match (group, market, prob, fair_odds)."""
    f = fair[fair.group.isin(EXOTIC_GROUPS) & fair.fair_odds.between(lo, hi)]
    return f.sort_values("prob", ascending=False).drop_duplicates("group").reset_index(drop=True)


def pareto_options(c: pd.DataFrame) -> list:
    """Per match, the candidates not beaten on both probability and odds (sorted by probability)."""
    out = []
    for _, g in c.sort_values(["prob", "odds"], ascending=False).groupby(KEYS, sort=False):
        keep, best_odds = [], 0.0
        for _, r in g.iterrows():
            if r.odds > best_odds:   # higher odds than every more probable option
                keep.append(r)
                best_odds = r.odds
        out.append(pd.DataFrame(keep))
    return sorted(out, key=lambda d: -d.prob.iloc[0])


def best_multiple(vt: pd.DataFrame, k: int, target_odds: float = 1.0):
    """Most likely k-fold (different matches, one option each) with total odds >= target_odds.

    Exact search over the Pareto options of the POOL matches with the most probable picks.
    Returns a dict (legs, odds, prob, value) or None."""
    options = pareto_options(candidates(vt))[:POOL]
    best = None
    for idx in combinations(range(len(options)), k):
        for rows in product(*(options[i].itertuples(index=False) for i in idx)):
            q = float(np.prod([r.odds for r in rows]))
            p = float(np.prod([r.prob for r in rows]))
            if q >= target_odds and (best is None or p > best[2] + 1e-12):
                best = (rows, q, p)
    if best is None:
        return None
    rows, q, p = best
    legs = pd.DataFrame(rows, columns=vt.columns).sort_values("kickoff_utc").reset_index(drop=True)
    return {"legs": legs, "odds": q, "prob": p, "value": p * q - 1}


def expected_outcome(prob: float, odds: float, stake: float = 10.0) -> dict:
    """What a bet means in money: win chance, payout if it wins, average result over many bets."""
    return {"stake": stake, "win_pct": 100 * prob, "payout": stake * odds, "avg_result": stake * (prob * odds - 1)}
