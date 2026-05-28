"""Strategy filter tests, run offline against the fixture universe."""
from __future__ import annotations

from strategies import earnings, momentum, post_earnings_drift, squeeze

REQUIRED_COLUMNS = {"strategy", "match", "signal", "symbol"}


def _symbols(df) -> set[str]:
    return set(df["symbol"].tolist())


def _tag(df, symbol: str) -> str:
    return df.loc[df["symbol"] == symbol, "match"].iloc[0]


def test_momentum_tight(universe):
    hits = momentum.run(universe, "tight")
    assert _symbols(hits) == {"MOMO"}
    assert REQUIRED_COLUMNS <= set(hits.columns)
    assert (hits["match"] == "tight").all()
    assert (hits["strategy"] == "Momentum").all()


def test_momentum_loose_distinguishes_tags(universe):
    hits = momentum.run(universe, "loose")
    assert _symbols(hits) == {"MOMO", "MOLO"}
    assert _tag(hits, "MOMO") == "tight"
    assert _tag(hits, "MOLO") == "loose"


def test_earnings_tight(universe):
    hits = earnings.run(universe, "tight")
    assert _symbols(hits) == {"EARN"}
    assert _tag(hits, "EARN") == "tight"


def test_post_earnings_drift_tight(universe):
    hits = post_earnings_drift.run(universe, "tight")
    assert _symbols(hits) == {"PEAD"}


def test_squeeze_tight(universe):
    hits = squeeze.run(universe, "tight")
    assert _symbols(hits) == {"SQZ"}


def test_squeeze_loose_adds_loose_candidate(universe):
    hits = squeeze.run(universe, "loose")
    assert _symbols(hits) == {"SQZ", "SQLO"}
    assert _tag(hits, "SQZ") == "tight"
    assert _tag(hits, "SQLO") == "loose"


def test_dud_never_matches(universe):
    for strat in (momentum, earnings, post_earnings_drift, squeeze):
        for mode in ("tight", "loose"):
            assert "DUD" not in _symbols(strat.run(universe, mode))
