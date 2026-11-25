"""Team ratings (Release 2 Phase E)."""

from __future__ import annotations

import math
import random

import pytest

from uclfa.model.ratings import Evidence, RatingSettings, fit_ratings

S = RatingSettings(odds_weight=3.0, result_weight=1.0, shrinkage=0.0, half_life_matchdays=100)
TRUE_ATT = {"A": 0.5, "B": 0.2, "C": -0.1, "D": -0.6}
TRUE_DEF = {"A": 0.3, "B": 0.0, "C": -0.2, "D": -0.1}


def true_rates(h: str, a: str) -> tuple[float, float]:
    return (
        math.exp(0.1 + 0.25 + TRUE_ATT[h] - TRUE_DEF[a]),
        math.exp(0.1 + TRUE_ATT[a] - TRUE_DEF[h]),
    )


def pairs():
    return [(h, a) for h in TRUE_ATT for a in TRUE_ATT if h != a]


def test_market_rates_are_reproduced_exactly():
    """Fed only market rates from a true model, the fit returns those rates."""
    ev = [Evidence(h, a, *true_rates(h, a), "odds", 5) for h, a in pairs()]
    r = fit_ratings(ev, S, latest_matchday=5)
    for h, a in pairs():
        assert r.rates(h, a) == pytest.approx(true_rates(h, a), rel=1e-4)
    assert r.home_advantage == pytest.approx(0.25, abs=1e-3)


def _poisson(rng: random.Random, lam: float) -> int:
    n, p, limit = 0, 1.0, math.exp(-lam)
    while True:
        p *= rng.random()
        if p <= limit:
            return n
        n += 1


def test_results_recover_strength_order():
    rng = random.Random(3)
    ev = []
    for md in range(1, 401):  # enough matches that sampling noise stays under 10%
        for h, a in pairs():
            lh, la = true_rates(h, a)
            ev.append(Evidence(h, a, _poisson(rng, lh), _poisson(rng, la), "result", md))
    r = fit_ratings(ev, S, latest_matchday=400)
    assert sorted(r.attack, key=r.attack.get) == ["D", "C", "B", "A"]
    for h, a in pairs():
        assert r.rates(h, a) == pytest.approx(true_rates(h, a), rel=0.10)


def test_shrinkage_pulls_towards_average_and_unknown_clubs_raise():
    ev = [Evidence("A", "B", 6, 0, "result", 1), Evidence("B", "A", 0, 5, "result", 1)]
    loose = fit_ratings(ev, S, 1)
    tight = fit_ratings(ev, S.model_copy(update={"shrinkage": 5.0}), 1)
    assert abs(tight.attack["A"]) < abs(loose.attack["A"])
    with pytest.raises(KeyError):
        loose.rates("A", "Z")
    with pytest.raises(ValueError):
        fit_ratings([], S, 1)


def test_blowout_results_are_capped_but_market_rates_are_not():
    ev = [Evidence("A", "B", 9, 1, "result", 1), Evidence("B", "A", 1, 1, "result", 1)]
    capped = fit_ratings(ev, S.model_copy(update={"max_goals_counted": 3}), 1)
    same = [Evidence("A", "B", 3, 1, "result", 1), Evidence("B", "A", 1, 1, "result", 1)]
    assert capped.rates("A", "B") == pytest.approx(fit_ratings(same, S, 1).rates("A", "B"))
    # Rates the model can reproduce exactly: each team scores 3x as much at home.
    market = [Evidence("A", "B", 4.5, 1.0, "odds", 1), Evidence("B", "A", 3.0, 1.5, "odds", 1)]
    r = fit_ratings(market, S.model_copy(update={"max_goals_counted": 3}), 1)
    assert r.rates("A", "B")[0] == pytest.approx(4.5, rel=1e-3)
