import json

import pandas as pd
import pytest

from forecast1x2 import oddspapi as op
from forecast1x2.data import DataError

NOW = pd.Timestamp("2026-10-23 12:00", tz="UTC")
KICK = int(pd.Timestamp("2026-10-24 14:00", tz="UTC").timestamp())

TOURNAMENTS = [
    {"tournamentId": 17, "tournamentName": "Serie A", "categoryName": "Italy"},
    {"tournamentId": 18, "tournamentName": "Serie A Women", "categoryName": "Italy"},
    {"tournamentId": 35, "tournamentName": "Bundesliga", "categoryName": "Germany"},
    {"tournamentId": 44, "tournamentName": "2. Bundesliga", "categoryName": "Germany"},
    {"tournamentId": 8, "tournamentName": "LaLiga", "categoryName": "Spain"},
    {"tournamentId": 99, "tournamentName": "Bundesliga", "categoryName": "Austria"},
]
MARKETS = [
    {"marketId": 101, "marketType": "1x2", "period": "fulltime", "handicap": 0.0, "playerProp": False,
     "outcomes": [{"outcomeId": 101, "outcomeName": "1"}, {"outcomeId": 102, "outcomeName": "X"},
                  {"outcomeId": 103, "outcomeName": "2"}]},
    {"marketId": 104, "marketType": "bothteamsscore", "period": "fulltime", "handicap": 0.0, "playerProp": False,
     "outcomes": [{"outcomeId": 104, "outcomeName": "Yes"}, {"outcomeId": 105, "outcomeName": "No"}]},
    {"marketId": 1010, "marketType": "totals", "period": "fulltime", "handicap": 2.5, "playerProp": False,
     "outcomes": [{"outcomeId": 1010, "outcomeName": "Over"}, {"outcomeId": 1011, "outcomeName": "Under"}]},
    {"marketId": 1012, "marketType": "totals", "period": "fulltime", "handicap": 2.25, "playerProp": False,
     "outcomes": [{"outcomeId": 1012, "outcomeName": "Over"}, {"outcomeId": 1013, "outcomeName": "Under"}]},
    {"marketId": 10208, "marketType": "1x2", "period": "p1", "handicap": 0.0, "playerProp": False,
     "outcomes": [{"outcomeId": 10208, "outcomeName": "1"}, {"outcomeId": 10209, "outcomeName": "X"},
                  {"outcomeId": 10210, "outcomeName": "2"}]},
    {"marketId": 10224, "marketType": "teamtotals-team1", "period": "fulltime", "handicap": 0.5, "playerProp": False,
     "outcomes": [{"outcomeId": 10224, "outcomeName": "Over"}, {"outcomeId": 10225, "outcomeName": "Under"}]},
    {"marketId": 1500, "marketType": "anytimegoalscorer", "period": "fulltime", "handicap": 0.0, "playerProp": True,
     "outcomes": [{"outcomeId": 1500, "outcomeName": "Yes"}]},
]


def fixture(fid, tid, home, away, start=KICK, prices=None):
    odds = {f"{fid}:{op.BOOKMAKER}:{oid}:0": {"outcomeId": oid, "price": p, "active": True, "marketActive": True}
            for oid, p in (prices or {}).items()}
    return {"fixtureId": fid, "tournament": {"tournamentId": tid}, "startTime": start,
            "participants": {"participant1Name": home, "participant2Name": away},
            "odds": {op.BOOKMAKER: odds} if prices else {}}


FIXTURES = [fixture("idA", 8, "Real Madrid CF", "Valencia CF"),
            fixture("idB", 8, "Atletico Madrid", "Sevilla FC"),
            fixture("idC", 17, "Inter Milano", "AC Milan", KICK + 3600),
            fixture("idX", 18, "Inter Women", "Milan Women")]
PRICES = {"idA": {101: 1.5, 102: 4.2, 103: 6.5, 1010: 1.7, 1011: 2.15, 1012: 1.8, 10208: 2.1, 999: 3.0},
          "idB": {101: 1.9, 104: 1.95}, "idC": {101: 2.3, 10224: 1.25}}


class Resp:
    def __init__(self, data, status=200):
        self.data, self.status_code, self.text = data, status, json.dumps(data)

    def json(self):
        return self.data


class FakeApi:
    """Answers like OddsPapi v5 (shapes from the official OpenAPI examples)."""

    def __init__(self, fail=None):
        self.calls, self.fail = [], fail

    def __call__(self, url, params, timeout):
        path = url.replace(op.BASE_URL, "")
        self.calls.append((path, params))
        if self.fail == path:
            return Resp({"error": 401, "message": "bad key"}, 401)
        if path == "/bookmakers":
            return Resp([{"slug": op.BOOKMAKER, "bookmakerName": "Planetwin365"}])
        if path == "/tournaments":
            return Resp(TOURNAMENTS)
        if path == "/markets":
            return Resp(MARKETS)
        if path == "/fixtures":
            return Resp(FIXTURES)
        if path == "/fixtures/odds/main":
            ids = params["fixtureIds"].split(",")
            return Resp([fixture(i, 0, "", "", prices=PRICES[i]) for i in ids if i in PRICES])
        raise AssertionError(path)


def ours():
    k = pd.Timestamp(KICK, unit="s", tz="UTC")
    return pd.DataFrame({"league": ["SP1", "SP1", "I1"], "kickoff_utc": [k, k, k + pd.Timedelta(hours=1)],
                         "home": ["Real Madrid", "Ath Madrid", "Inter"], "away": ["Valencia", "Sevilla", "Milan"]})


def test_tournaments_need_country_and_exact_name():
    assert op.resolve_tournaments(TOURNAMENTS) == {"I1": 17, "D1": 35, "D2": 44, "SP1": 8}   # no women, no Austria


def test_outcome_map_keeps_only_markets_we_price():
    m = op.outcome_map(MARKETS)
    assert m["101"] == ["1X2", "1"] and m["105"] == ["Goal/No goal", "No goal"]
    assert m["1011"] == ["Under/Over", "Under 2.5"] and m["10209"] == ["Primo tempo", "1X2 1T: X"]
    assert m["10224"] == ["Under/Over squadra", "Over 0.5 casa"]
    assert "1012" not in m and "1500" not in m   # quarter line and player prop


def test_matching_by_league_time_and_names():
    pairs = op.match_fixtures(ours(), FIXTURES, op.resolve_tournaments(TOURNAMENTS))
    got = {ours().loc[i, "home"]: fx["fixtureId"] for i, fx in pairs}
    assert got == {"Real Madrid": "idA", "Ath Madrid": "idB", "Inter": "idC"}


def test_matching_rejects_far_kickoff_and_wrong_teams():
    t = op.resolve_tournaments(TOURNAMENTS)
    assert op.match_fixtures(ours(), [fixture("idA", 8, "Real Madrid CF", "Valencia CF", KICK + 5 * 3600)], t) == []
    assert op.match_fixtures(ours(), [fixture("idZ", 8, "Getafe CF", "Girona FC")], t) == []


@pytest.fixture
def paths(tmp_path, monkeypatch):
    monkeypatch.setenv(op.KEY_ENV, "SECRETKEY")
    fair = tmp_path / "fair_odds.csv"
    o = ours()
    o.assign(kickoff_utc=o.kickoff_utc.dt.strftime("%Y-%m-%dT%H:%M:%SZ")).to_csv(fair, index=False)
    return {"fair_path": fair, "state_path": tmp_path / "state.json",
            "reference_path": tmp_path / "ref.json", "out": tmp_path / "bk.csv"}


def test_update_downloads_matches_and_counts_requests(paths):
    api = FakeApi()
    warnings = op.update_bookmaker_odds(NOW, api, **paths)
    assert warnings == ["Planetwin365: campionati non trovati su OddsPapi: E0, E1, F1, F2, I2, SP2"]
    assert [c[0] for c in api.calls] == ["/bookmakers", "/tournaments", "/markets", "/fixtures", "/fixtures/odds/main"]
    assert all(c[1]["apiKey"] == "SECRETKEY" for c in api.calls)
    assert api.calls[3][1]["bookmakers"] == op.BOOKMAKER
    bk = pd.read_csv(paths["out"]).set_index(["home", "group", "market"])
    assert bk.loc[("Real Madrid", "1X2", "1"), "odds"] == 1.5
    assert bk.loc[("Real Madrid", "Under/Over", "Under 2.5"), "odds"] == 2.15
    assert bk.loc[("Ath Madrid", "Goal/No goal", "Goal"), "odds"] == 1.95
    assert bk.loc[("Inter", "Under/Over squadra", "Over 0.5 casa"), "odds"] == 1.25
    assert len(bk) == 10   # outcome 999 (unknown) and 1012 (quarter line) dropped
    state = json.loads(paths["state_path"].read_text())
    assert state["requests"] == 5 and state["month"] == "2026-10"

    api2 = FakeApi()   # 6 hours later: nothing is requested
    op.update_bookmaker_odds(NOW + pd.Timedelta(hours=6), api2, **paths)
    assert api2.calls == []
    api3 = FakeApi()   # 13 hours later: reference cached, only fixtures + odds
    op.update_bookmaker_odds(NOW + pd.Timedelta(hours=13), api3, **paths)
    assert [c[0] for c in api3.calls] == ["/fixtures", "/fixtures/odds/main"]
    assert json.loads(paths["state_path"].read_text())["requests"] == 7


def test_monthly_cap_and_errors_without_the_key(paths):
    paths["state_path"].write_text(json.dumps({"month": "2026-10", "requests": op.MONTHLY_CAP}))
    with pytest.raises(DataError, match="limite"):
        op.update_bookmaker_odds(NOW, FakeApi(), **paths)
    paths["state_path"].write_text(json.dumps({"month": "2026-09", "requests": op.MONTHLY_CAP}))   # new month
    with pytest.raises(DataError) as e:
        op.update_bookmaker_odds(NOW, FakeApi(fail="/bookmakers"), **paths)
    assert "401" in str(e.value) and "SECRETKEY" not in str(e.value)
    assert json.loads(paths["state_path"].read_text())["requests"] == 1   # a failed request still counts


def test_no_key_no_requests(paths, monkeypatch):
    monkeypatch.delenv(op.KEY_ENV)
    monkeypatch.setattr(op, "KEY_FILE", paths["out"].parent / "missing")
    api = FakeApi()
    assert op.update_bookmaker_odds(NOW, api, **paths) == [] and api.calls == []


def test_value_table():
    up = pd.DataFrame({"league": ["I1"], "kickoff_utc": ["2026-10-24T14:00:00Z"], "home": ["Roma"], "away": ["Lazio"],
                       "rate_home": [1.4], "rate_away": [1.1]})
    params = {"rho": -0.05, "nu": 1.1, "first_half_share": 0.44}
    from forecast1x2.markets import fair_odds_for
    fair = fair_odds_for(up.iloc[0], params).set_index(["group", "market"]).fair_odds
    bk = pd.DataFrame({"league": ["I1"] * 3, "home": ["Roma"] * 3, "away": ["Lazio"] * 3,
                       "group": ["1X2"] * 3, "market": ["1", "X", "2"],
                       "odds": [fair[("1X2", "1")] * 1.10, fair[("1X2", "X")] * 0.9, fair[("1X2", "2")] * 3]})
    v = op.value_table(up, bk, params, {("1X2", "1"): 1.0}).set_index("market")
    assert v.loc["1", "verdict"] == "valore" and v.loc["1", "value"] == pytest.approx(0.10)
    assert 0 < v.loc["1", "stake"] <= 0.05
    assert v.loc["X", "verdict"] == "nessun valore" and v.loc["X", "stake"] == 0
    assert v.loc["2", "verdict"] == "quota sospetta" and v.loc["2", "stake"] == 0
