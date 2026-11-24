"""Team ratings (Release 2 Phase E): attack, defence and home advantage for every club.

Expected goals are log-linear: log(home rate) = base + home + attack[home] - defence[away],
log(away rate) = base + attack[away] - defence[home]. Ratings are fitted by maximising a
weighted Poisson likelihood over two kinds of evidence:

- played results, where the observation is the number of goals scored;
- bookmaker-priced matches, where the observation is the market-implied goal rate (the
  Poisson log-likelihood is maximised exactly at that rate, so it acts as a soft target).

A ridge penalty pulls ratings towards average. Used only for matches the bookmakers have not
priced; priced matches always use their own odds. All outputs are analyst estimates.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import yaml
from pydantic import BaseModel, ConfigDict, Field
from scipy.optimize import minimize

from uclfa.model.match import DEFAULT_SETTINGS_PATH


class RatingSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    odds_weight: float = Field(gt=0)
    result_weight: float = Field(gt=0)
    shrinkage: float = Field(ge=0)
    half_life_matchdays: float = Field(gt=0)
    max_goals_counted: int = Field(default=99, ge=1)


def load_rating_settings(path: Path = DEFAULT_SETTINGS_PATH) -> RatingSettings:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return RatingSettings.model_validate(data["ratings"])


@dataclass(frozen=True)
class Evidence:
    """One match. `home_obs`/`away_obs` are goals (result) or market rates (odds)."""

    home: str
    away: str
    home_obs: float
    away_obs: float
    kind: str  # "result" or "odds"
    matchday: int


@dataclass(frozen=True)
class Ratings:
    base: float
    home_advantage: float
    attack: dict[str, float]
    defence: dict[str, float]
    matches_used: int

    def rates(self, home: str, away: str) -> tuple[float, float]:
        """Expected goals (home, away). Raises KeyError for a club with no evidence."""
        h = math.exp(self.base + self.home_advantage + self.attack[home] - self.defence[away])
        a = math.exp(self.base + self.attack[away] - self.defence[home])
        return h, a


def fit_ratings(evidence: list[Evidence], s: RatingSettings, latest_matchday: int) -> Ratings:
    if not evidence:
        raise ValueError("No matches to fit ratings from")
    teams = sorted({e.home for e in evidence} | {e.away for e in evidence})
    idx = {t: i for i, t in enumerate(teams)}
    n = len(teams)
    hi = np.array([idx[e.home] for e in evidence])
    ai = np.array([idx[e.away] for e in evidence])
    cap = s.max_goals_counted

    def counted(e: Evidence, obs: float) -> float:
        return min(obs, cap) if e.kind == "result" else obs

    yh = np.array([counted(e, e.home_obs) for e in evidence])
    ya = np.array([counted(e, e.away_obs) for e in evidence])
    kind_w = np.array([s.odds_weight if e.kind == "odds" else s.result_weight for e in evidence])
    age = np.array([max(0, latest_matchday - e.matchday) for e in evidence])
    w = kind_w * 0.5 ** (age / s.half_life_matchdays)

    def unpack(x: np.ndarray) -> tuple[float, float, np.ndarray, np.ndarray]:
        return x[0], x[1], x[2 : 2 + n], x[2 + n :]

    def nll(x: np.ndarray) -> tuple[float, np.ndarray]:
        base, home, att, dfn = unpack(x)
        lh = base + home + att[hi] - dfn[ai]
        la = base + att[ai] - dfn[hi]
        mh, ma = np.exp(lh), np.exp(la)
        value = -np.sum(w * (yh * lh - mh + ya * la - ma))
        value += s.shrinkage * (np.sum(att**2) + np.sum(dfn**2))
        rh, ra = w * (mh - yh), w * (ma - ya)  # d(-loglik)/d(log rate)
        grad = np.zeros_like(x)
        grad[0] = rh.sum() + ra.sum()
        grad[1] = rh.sum()
        g_att = np.bincount(hi, rh, n) + np.bincount(ai, ra, n)
        g_def = -np.bincount(ai, rh, n) - np.bincount(hi, ra, n)
        grad[2 : 2 + n] = g_att + 2 * s.shrinkage * att
        grad[2 + n :] = g_def + 2 * s.shrinkage * dfn
        return value, grad

    start = np.zeros(2 + 2 * n)
    start[0] = math.log(max(0.1, float(np.average(np.concatenate([yh, ya])))))
    res = minimize(
        nll,
        start,
        jac=True,
        method="L-BFGS-B",
        options={"maxiter": 5000, "ftol": 1e-14, "gtol": 1e-9},
    )
    if not res.success:
        raise ValueError(f"Rating fit did not converge: {res.message}")
    base, home, att, dfn = unpack(res.x)
    return Ratings(
        base=float(base),
        home_advantage=float(home),
        attack={t: float(att[i]) for t, i in idx.items()},
        defence={t: float(dfn[i]) for t, i in idx.items()},
        matches_used=len(evidence),
    )
