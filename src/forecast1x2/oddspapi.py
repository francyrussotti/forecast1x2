"""Quote Planetwin365 da OddsPapi (https://docs.oddspapi.io), confrontate con le quote giuste di markets.py.

Facoltativo: senza chiave (variabile ODDSPAPI_API_KEY o file KEY_FILE, fuori dal progetto) non fa nulla.
Pochi request: al primo uso (e ogni 30 giorni) scarica i riferimenti (bookmaker, campionati, codici dei mercati)
in REFERENCE; poi, al massimo ogni MIN_INTERVAL, 1 request per l'elenco delle partite e 1 ogni 100 partite per
le quote. Il contatore mensile in STATE si ferma a MONTHLY_CAP (il piano gratuito dichiara 250 al mese).

Le partite di OddsPapi si abbinano alle nostre per campionato, orario (±3 ore) e somiglianza dei nomi.
"""
import json
import os
import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from .data import ROOT, DataError, write_atomic, write_csv_atomic

BASE_URL = "https://v5.oddspapi.io/en"
BOOKMAKER = "planetwin365.it"
BOOKMAKER_NAME = "Planetwin365"
SOCCER = 10
KEY_ENV = "ODDSPAPI_API_KEY"
KEY_FILE = Path.home() / ".config" / "forecast1x2" / "oddspapi_key"
REFERENCE = ROOT / "data" / "oddspapi_reference.json"
STATE = ROOT / "data" / "oddspapi_state.json"
OUT = ROOT / "outputs" / "bookmaker_odds.csv"
MIN_INTERVAL = pd.Timedelta(hours=12)
MONTHLY_CAP = 200
HORIZON = pd.Timedelta(days=5)
REFERENCE_MAX_AGE = pd.Timedelta(days=30)
MAX_KICKOFF_GAP = pd.Timedelta(hours=3)
MIN_NAME_SCORE = 0.45
OUT_COLS = ["league", "kickoff_utc", "home", "away", "bookmaker", "group", "market", "odds", "fetched_at"]

# our league code -> (OddsPapi categoryName, accepted tournamentName values)
TOURNAMENTS = {
    "I1": ("Italy", ["Serie A"]), "I2": ("Italy", ["Serie B"]),
    "E0": ("England", ["Premier League"]), "E1": ("England", ["Championship"]),
    "SP1": ("Spain", ["LaLiga", "La Liga", "Primera Division", "LaLiga EA Sports"]),
    "SP2": ("Spain", ["LaLiga 2", "La Liga 2", "LaLiga Hypermotion", "Segunda Division", "Segunda División"]),
    "D1": ("Germany", ["Bundesliga"]), "D2": ("Germany", ["2. Bundesliga", "2nd Bundesliga"]),
    "F1": ("France", ["Ligue 1"]), "F2": ("France", ["Ligue 2"]),
}


# ------------------------------------------------------------------ helpers

def get_key():
    key = os.environ.get(KEY_ENV, "").strip()
    if not key and KEY_FILE.exists():
        lines = KEY_FILE.read_text().strip().splitlines()
        key = lines[0].strip() if lines else ""
    return key or None


def _norm(s: str) -> str:
    """Lowercase ASCII name without punctuation, for loose comparisons."""
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9 ]+", " ", s).strip()


_DROP = {"fc", "ac", "as", "ssc", "sc", "cf", "ud", "rc", "sd", "cd", "afc", "us", "calcio", "club", "sv", "vfb",
         "vfl", "tsg", "bsc", "fk", "ss", "rcd", "sco", "ogc", "aj", "stade", "olympique", "1", "05", "04", "1899",
         "1846", "1907", "1910", "1913", "1919", "1929", "hsc", "ca", "real", "de", "la", "el"}
_EXPAND = {"man": "manchester", "utd": "united", "ath": "athletic", "ein": "eintracht", "nott m": "nottingham",
           "m gladbach": "monchengladbach", "st": "saint", "sp": "sporting", "wolves": "wolverhampton",
           "qpr": "queens park rangers", "psg": "paris saint germain", "paris sg": "paris saint germain",
           "sheff": "sheffield", "wed": "wednesday", "inter": "internazionale", "verona": "hellas verona"}


def _tokens(name: str) -> set:
    s = _norm(name)
    for k, v in _EXPAND.items():
        s = re.sub(rf"\b{k}\b", v, s)
    return {t for t in s.split() if t and t not in _DROP}


def name_score(a: str, b: str) -> float:
    """Similarity 0-1 between two team names written differently (e.g. 'Man City' / 'Manchester City')."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return SequenceMatcher(None, _norm(a), _norm(b)).ratio()
    common = len(ta & tb)   # extra words on one side lower the score: 'Real Madrid' beats 'Atletico Madrid'
    overlap = 0.7 * common / min(len(ta), len(tb)) + 0.3 * common / max(len(ta), len(tb))
    seq = SequenceMatcher(None, " ".join(sorted(ta)), " ".join(sorted(tb))).ratio()
    return max(overlap, seq)


# ------------------------------------------------------------------ client

class Client:
    """Counts every request in the state dict and refuses to go over MONTHLY_CAP."""

    def __init__(self, key: str, state: dict, now: pd.Timestamp, get=requests.get):
        self.key, self.state, self.get_fn = key, state, get
        month = now.strftime("%Y-%m")
        if state.get("month") != month:
            state.update(month=month, requests=0)

    def get(self, path: str, **params):
        if self.state["requests"] >= MONTHLY_CAP:
            raise DataError(f"OddsPapi: raggiunto il limite di {MONTHLY_CAP} richieste per questo mese")
        self.state["requests"] += 1
        try:
            r = self.get_fn(BASE_URL + path, params={**params, "apiKey": self.key}, timeout=60)
        except requests.RequestException as e:
            raise DataError(f"OddsPapi {path}: richiesta fallita ({type(e).__name__})")
        if r.status_code != 200:   # message without the URL, which contains the key
            raise DataError(f"OddsPapi {path}: HTTP {r.status_code} {r.text[:200]}")
        return r.json()


def load_json(path: Path, default):
    return json.loads(path.read_text()) if path.exists() else default


# --------------------------------------------------------------- reference

def resolve_tournaments(rows: list) -> dict:
    """Our league code -> OddsPapi tournamentId, matching country and exact (normalised) league name."""
    out = {}
    for div, (country, names) in TOURNAMENTS.items():
        want = {_norm(n) for n in names}
        hits = [r for r in rows if _norm(r.get("categoryName", "")) == _norm(country)
                and _norm(r.get("tournamentName", "")) in want]
        if hits:
            out[div] = int(hits[0]["tournamentId"])
    return out


def market_key(market_type: str, period: str, handicap: float, outcome: str):
    """(group, market) of markets.MARKETS for an OddsPapi outcome, or None if we do not price it."""
    h, o = f"{float(handicap):g}", str(outcome).strip()
    full = period in ("fulltime", "result")
    if market_type == "1x2" and float(handicap) == 0 and o in ("1", "X", "2"):
        if full:
            return ("1X2", o)
        return {"p1": ("Primo tempo", f"1X2 1T: {o}"), "p2": ("Secondo tempo", f"1X2 2T: {o}")}.get(period)
    if market_type == "totals" and o in ("Over", "Under"):
        if full:
            return ("Under/Over", f"{o} {h}")
        return {"p1": ("Primo tempo", f"{o} {h} 1T"), "p2": ("Secondo tempo", f"{o} {h} 2T")}.get(period)
    if market_type == "bothteamsscore" and o in ("Yes", "No"):
        if full:
            return ("Goal/No goal", "Goal" if o == "Yes" else "No goal")
        return ("Primo tempo", "Goal 1T") if period == "p1" and o == "Yes" else None
    if not full:
        return None
    if market_type == "drawnobet" and o in ("1", "2"):
        return ("Draw no bet", f"{o} (rimborso se X)")
    if market_type == "oddeven" and o in ("Odd", "Even"):
        return ("Pari/Dispari", "Dispari" if o == "Odd" else "Pari")
    if market_type in ("teamtotals-team1", "teamtotals-team2") and o in ("Over", "Under"):
        return ("Under/Over squadra", f"{o} {h} {'casa' if market_type.endswith('1') else 'ospite'}")
    if market_type == "doublechance":
        dc = o.replace("/", "").replace(" ", "").upper()
        return ("Doppia chance", dc) if dc in ("1X", "X2", "12") else None
    return None


def outcome_map(markets: list) -> dict:
    """outcomeId -> [group, market] for the OddsPapi soccer markets we can price."""
    from .markets import MARKETS
    known = {(g, m) for g, m, _, _ in MARKETS}
    out = {}
    for mk in markets:
        if mk.get("playerProp"):
            continue
        for oc in mk.get("outcomes", []):
            k = market_key(mk.get("marketType", ""), mk.get("period", ""), mk.get("handicap", 0), oc.get("outcomeName", ""))
            if k in known:
                out[str(oc["outcomeId"])] = list(k)
    return out


def refresh_reference(client: Client, now: pd.Timestamp, path: Path = REFERENCE) -> dict:
    books = client.get("/bookmakers", bookmakers=BOOKMAKER)
    if not any(b.get("slug") == BOOKMAKER for b in books):
        raise DataError(f"OddsPapi: il bookmaker '{BOOKMAKER}' non risulta disponibile per questa chiave")
    tournaments = resolve_tournaments(client.get("/tournaments", sportId=SOCCER))
    missing = sorted(set(TOURNAMENTS) - set(tournaments))
    outcomes = outcome_map(client.get("/markets", sportId=SOCCER))
    ref = {"bookmaker": BOOKMAKER, "tournaments": tournaments, "missing_tournaments": missing,
           "outcomes": outcomes, "fetched_at": now.isoformat(timespec="seconds")}
    write_atomic(path, json.dumps(ref, indent=1))
    return ref


# -------------------------------------------------------------- matching

def match_fixtures(ours: pd.DataFrame, fixtures: list, tournaments: dict) -> list:
    """Pairs (index in ours, OddsPapi fixture): same league, kickoff within MAX_KICKOFF_GAP, best names.

    One-to-one, best pairs first; a pair needs both team names to be reasonably similar."""
    league_of = {v: k for k, v in tournaments.items()}
    cands = []
    for fx in fixtures:
        div = league_of.get(int(fx.get("tournament", {}).get("tournamentId", -1)))
        if div is None:
            continue
        start = pd.Timestamp(int(fx["startTime"]), unit="s", tz="UTC")
        p = fx.get("participants", {})
        names1 = [n for n in (p.get("participant1Name"), p.get("participant1ShortName")) if n]
        names2 = [n for n in (p.get("participant2Name"), p.get("participant2ShortName")) if n]
        if not names1 or not names2:
            continue
        for i, r in ours[ours.league == div].iterrows():
            gap = abs(pd.Timestamp(r.kickoff_utc) - start)
            if gap > MAX_KICKOFF_GAP:
                continue
            s1 = max(name_score(r.home, n) for n in names1)
            s2 = max(name_score(r.away, n) for n in names2)
            if min(s1, s2) < MIN_NAME_SCORE:
                continue
            cands.append((s1 + s2 - gap / pd.Timedelta(hours=12), i, fx["fixtureId"], fx))
    pairs, used_i, used_f = [], set(), set()
    for score, i, fid, fx in sorted(cands, key=lambda c: -c[0]):
        if i not in used_i and fid not in used_f:
            pairs.append((i, fx))
            used_i.add(i)
            used_f.add(fid)
    return pairs


def extract_odds(fx: dict, outcomes: dict, bookmaker: str = BOOKMAKER) -> list:
    """[(group, market, price)] of active prices of one bookmaker in one fixture."""
    out = []
    for o in ((fx.get("odds") or {}).get(bookmaker) or {}).values():
        k = outcomes.get(str(o.get("outcomeId")))
        price = o.get("price")
        if k and o.get("active", True) and o.get("marketActive", True) and price and float(price) > 1:
            out.append((k[0], k[1], float(price)))
    return out


# ------------------------------------------------------------------ update

def update_bookmaker_odds(now: pd.Timestamp = None, get=requests.get, fair_path: Path = None,
                          state_path: Path = STATE, reference_path: Path = REFERENCE, out: Path = OUT) -> list:
    """Download Planetwin365 odds for the upcoming matches in outputs/fair_odds.csv. Returns warnings."""
    from .markets import FAIR_ODDS_OUT
    now = now if now is not None else pd.Timestamp.now(tz="UTC")
    key = get_key()
    if not key:
        print(f"quote {BOOKMAKER_NAME} disattivate: nessuna chiave ({KEY_ENV} o {KEY_FILE})")
        return []
    state = load_json(state_path, {})
    last = state.get("last_fetch")
    if last and now - pd.Timestamp(last) < MIN_INTERVAL:
        print(f"quote {BOOKMAKER_NAME}: ultimo download {last}, il prossimo almeno {MIN_INTERVAL} dopo")
        return []
    fair_path = fair_path or FAIR_ODDS_OUT
    ours = pd.read_csv(fair_path) if fair_path.exists() else pd.DataFrame()
    if ours.empty:
        return []
    ours["kickoff_utc"] = pd.to_datetime(ours.kickoff_utc, utc=True)
    client = Client(key, state, now, get)
    try:
        ref = load_json(reference_path, {})
        if not ref.get("fetched_at") or now - pd.Timestamp(ref["fetched_at"]) > REFERENCE_MAX_AGE:
            ref = refresh_reference(client, now, reference_path)
        fixtures = client.get("/fixtures", sportId=SOCCER, bookmakers=BOOKMAKER,
                              startTimeFrom=int(now.timestamp()), startTimeTo=int((now + HORIZON).timestamp()))
        wanted = set(ref["tournaments"].values())
        mine = [f for f in fixtures if int(f.get("tournament", {}).get("tournamentId", -1)) in wanted]
        pairs = match_fixtures(ours, mine, ref["tournaments"])
        ids = [fx["fixtureId"] for _, fx in pairs]
        priced = {}
        for k in range(0, len(ids), 100):
            for fx in client.get("/fixtures/odds/main", fixtureIds=",".join(ids[k:k + 100]), bookmakers=BOOKMAKER):
                priced[fx["fixtureId"]] = fx
    finally:
        write_atomic(state_path, json.dumps(state, indent=1))   # count requests even when something fails
    rows = []
    for i, fx in pairs:
        r = ours.loc[i]
        for group, market, price in extract_odds(priced.get(fx["fixtureId"], {}), ref["outcomes"]):
            rows.append({"league": r.league, "kickoff_utc": r.kickoff_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
                         "home": r.home, "away": r.away, "bookmaker": BOOKMAKER, "group": group, "market": market,
                         "odds": price, "fetched_at": now.isoformat(timespec="seconds")})
    state["last_fetch"] = now.isoformat(timespec="seconds")
    write_atomic(state_path, json.dumps(state, indent=1))
    write_csv_atomic(pd.DataFrame(rows, columns=OUT_COLS), out)
    print(f"quote {BOOKMAKER_NAME}: {len(rows)} quote su {len(pairs)} partite "
          f"({len(ours) - len(pairs)} senza abbinamento); richieste questo mese: {state['requests']}/{MONTHLY_CAP}")
    if ref.get("missing_tournaments"):
        return [f"{BOOKMAKER_NAME}: campionati non trovati su OddsPapi: {', '.join(ref['missing_tournaments'])}"]
    return []


# ----------------------------------------------------------------- values

def value_table(upcoming: pd.DataFrame, bk: pd.DataFrame, params: dict, err: dict) -> pd.DataFrame:
    """Every bookmaker price next to its fair odds: value, quarter-Kelly stake (max 5%), and a verdict."""
    from .markets import fair_odds_for
    rows = []
    for _, r in upcoming.iterrows():
        b = bk[(bk.league == r.league) & (bk.home == r.home) & (bk.away == r.away)]
        if b.empty:
            continue
        fo = fair_odds_for(r, params).merge(b[["group", "market", "odds"]], on=["group", "market"])
        for f in fo.itertuples():
            value = f.odds * f.prob - 1
            e = abs(err.get((f.group, f.market), 0.0)) / 100 * f.odds
            suspicious = f.odds > 2 * f.fair_odds
            stake = 0.0 if suspicious else float(np.clip(0.25 * value / (f.odds - 1), 0, 0.05))
            verdict = ("quota sospetta" if suspicious else "nessun valore" if value <= 0
                       else "valore entro l'errore" if value <= e else "valore")
            rows.append({"league": r.league, "kickoff_utc": r.kickoff_utc, "home": r.home, "away": r.away,
                         "group": f.group, "market": f.market, "prob": f.prob, "fair_odds": f.fair_odds,
                         "odds": f.odds, "value": value, "stake": stake, "verdict": verdict})
    return pd.DataFrame(rows)
