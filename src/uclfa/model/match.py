"""Match model: from bookmaker odds to team goal expectations and scoreline chances.

Method (docs/model.md):
1. Remove the bookmaker margin from the median match-result odds and from the over/under
   odds of the main half-goal line.
2. Find one goal rate per team so that a Poisson scoreline grid, with the Dixon-Coles
   low-score correction, reproduces those market probabilities as closely as possible.
3. Read expected goals, clean-sheet and scoring chances off the grid.

No database, file or network access here: the caller supplies odds and settings. Every
number this module produces is an analyst estimate.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from uclfa.rules.model import REPO_ROOT

DEFAULT_SETTINGS_PATH = REPO_ROOT / "model" / "settings.yaml"


class MatchModelSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    margin_method: Literal["power"]
    low_score_correction: float = Field(ge=-0.3, le=0.3)
    max_goals: int = Field(ge=6, le=20)
    min_rate: float = Field(gt=0)
    max_rate: float = Field(gt=0)
    fit_tolerance: float = Field(gt=0, lt=0.1)
    min_result_bookmakers: int = Field(ge=1)
    min_goals_bookmakers: int = Field(ge=1)


def load_settings(path: Path = DEFAULT_SETTINGS_PATH) -> MatchModelSettings:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return MatchModelSettings.model_validate(data["match_model"])


# -- margin removal ------------------------------------------------------------------


def remove_margin(odds: list[float]) -> list[float]:
    """Power method: p_i = (1/o_i)^k with k chosen so the p_i sum to 1.

    A book without margin comes back unchanged (k = 1). Raises ValueError on odds that are
    not decimal prices above 1.
    """
    if len(odds) < 2 or any(not (o > 1.0) for o in odds):
        raise ValueError(f"Need two or more decimal odds above 1, got {odds}")
    implied = [1.0 / o for o in odds]

    def total(k: float) -> float:
        return sum(q**k for q in implied)

    lo, hi = 0.01, 50.0  # total() falls as k rises, since every q < 1
    if not (total(lo) >= 1.0 >= total(hi)):
        raise ValueError(f"Cannot remove the margin from {odds}")
    for _ in range(200):
        mid = (lo + hi) / 2
        if total(mid) > 1.0:
            lo = mid
        else:
            hi = mid
    k = (lo + hi) / 2
    probs = [q**k for q in implied]
    s = sum(probs)
    return [p / s for p in probs]


def margin(odds: list[float]) -> float:
    """Bookmaker margin: sum of implied probabilities minus one."""
    return sum(1.0 / o for o in odds) - 1.0


def is_half_line(line: float | None) -> bool:
    return line is not None and math.isclose(line % 1, 0.5)


# -- scoreline grid ------------------------------------------------------------------


def _poisson(rate: float, n: int) -> list[float]:
    out = [math.exp(-rate)]
    for k in range(1, n + 1):
        out.append(out[-1] * rate / k)
    return out


@dataclass(frozen=True)
class Grid:
    """P(home goals = i, away goals = j), truncated at max_goals and renormalised."""

    cells: tuple[tuple[float, ...], ...]
    truncated_mass: float

    def prob(self, test) -> float:  # noqa: ANN001 - small internal helper
        return sum(p for i, row in enumerate(self.cells) for j, p in enumerate(row) if test(i, j))

    @property
    def home_win(self) -> float:
        return self.prob(lambda i, j: i > j)

    @property
    def draw(self) -> float:
        return self.prob(lambda i, j: i == j)

    @property
    def away_win(self) -> float:
        return self.prob(lambda i, j: i < j)

    def over(self, line: float) -> float:
        return self.prob(lambda i, j: i + j > line)

    @property
    def home_clean_sheet(self) -> float:
        return sum(row[0] for row in self.cells)

    @property
    def away_clean_sheet(self) -> float:
        return sum(self.cells[0])

    @property
    def expected_home_goals(self) -> float:
        return sum(i * p for i, row in enumerate(self.cells) for p in row)

    @property
    def expected_away_goals(self) -> float:
        return sum(j * p for row in self.cells for j, p in enumerate(row))

    def top_scorelines(self, n: int = 3) -> list[tuple[str, float]]:
        flat = [(f"{i}-{j}", p) for i, row in enumerate(self.cells) for j, p in enumerate(row)]
        return sorted(flat, key=lambda x: -x[1])[:n]


def scoreline_grid(home_rate: float, away_rate: float, rho: float, max_goals: int) -> Grid:
    """Independent Poisson goals with the Dixon-Coles correction on 0-0, 1-0, 0-1, 1-1."""
    ph, pa = _poisson(home_rate, max_goals), _poisson(away_rate, max_goals)
    cells = [[ph[i] * pa[j] for j in range(max_goals + 1)] for i in range(max_goals + 1)]
    lam, mu = home_rate, away_rate
    cells[0][0] *= max(0.0, 1 - lam * mu * rho)
    cells[0][1] *= max(0.0, 1 + lam * rho)
    cells[1][0] *= max(0.0, 1 + mu * rho)
    cells[1][1] *= max(0.0, 1 - rho)
    total = sum(map(sum, cells))
    return Grid(tuple(tuple(p / total for p in row) for row in cells), max(0.0, 1 - total))


# -- fitting -------------------------------------------------------------------------


def _nelder_mead(f, start: list[float], step: float = 0.3, iters: int = 600) -> list[float]:  # noqa: ANN001
    """Minimise f over two variables. Small, dependency-free and deterministic."""
    pts = [list(start), [start[0] + step, start[1]], [start[0], start[1] + step]]
    vals = [f(p) for p in pts]
    for _ in range(iters):
        order = sorted(range(3), key=vals.__getitem__)
        pts, vals = [pts[i] for i in order], [vals[i] for i in order]
        if vals[2] - vals[0] < 1e-16 and max(abs(pts[2][k] - pts[0][k]) for k in range(2)) < 1e-10:
            break
        centre = [(pts[0][k] + pts[1][k]) / 2 for k in range(2)]
        refl = [centre[k] + (centre[k] - pts[2][k]) for k in range(2)]
        fr = f(refl)
        if fr < vals[0]:
            exp = [centre[k] + 2 * (centre[k] - pts[2][k]) for k in range(2)]
            fe = f(exp)
            pts[2], vals[2] = (exp, fe) if fe < fr else (refl, fr)
        elif fr < vals[1]:
            pts[2], vals[2] = refl, fr
        else:
            con = [centre[k] + 0.5 * (pts[2][k] - centre[k]) for k in range(2)]
            fc = f(con)
            if fc < vals[2]:
                pts[2], vals[2] = con, fc
            else:
                for i in (1, 2):
                    pts[i] = [pts[0][k] + 0.5 * (pts[i][k] - pts[0][k]) for k in range(2)]
                    vals[i] = f(pts[i])
    return pts[min(range(3), key=vals.__getitem__)]


@dataclass(frozen=True)
class MarketInput:
    """Median odds for one match, as stored in an odds snapshot."""

    home_price: float
    draw_price: float
    away_price: float
    result_bookmakers: int
    total_line: float | None = None
    over_price: float | None = None
    under_price: float | None = None
    goals_bookmakers: int = 0


@dataclass
class MatchFit:
    home_rate: float
    away_rate: float
    grid: Grid
    market: dict[str, float]
    model: dict[str, float]
    max_error: float
    margins: dict[str, float]
    goals_line: float | None
    confidence: Literal["normal", "low"]
    reasons: list[str] = field(default_factory=list)


def fit_match(m: MarketInput, s: MatchModelSettings) -> MatchFit:
    """Fit goal rates to the market. Raises ValueError if the result odds are unusable."""
    p_home, p_draw, p_away = remove_margin([m.home_price, m.draw_price, m.away_price])
    market = {"home_win": p_home, "draw": p_draw, "away_win": p_away}
    margins = {"result": margin([m.home_price, m.draw_price, m.away_price])}
    reasons: list[str] = []

    line: float | None = None
    if m.over_price and m.under_price and is_half_line(m.total_line):
        line = m.total_line
        market[f"over_{line}"] = remove_margin([m.over_price, m.under_price])[0]
        margins["goals"] = margin([m.over_price, m.under_price])
        if m.goals_bookmakers < s.min_goals_bookmakers:
            reasons.append(
                f"goals line {line} quoted by {m.goals_bookmakers} bookmakers "
                f"(minimum {s.min_goals_bookmakers})"
            )
    elif m.total_line is not None:
        reasons.append(
            f"main goals line {m.total_line} is not a half-goal line; fitted from the "
            "match result only"
        )
    else:
        reasons.append("no goals line; fitted from the match result only")
    if m.result_bookmakers < s.min_result_bookmakers:
        reasons.append(
            f"match result quoted by {m.result_bookmakers} bookmakers "
            f"(minimum {s.min_result_bookmakers})"
        )

    lo, hi = math.log(s.min_rate), math.log(s.max_rate)

    def probs(grid: Grid) -> dict[str, float]:
        out = {"home_win": grid.home_win, "draw": grid.draw, "away_win": grid.away_win}
        if line is not None:
            out[f"over_{line}"] = grid.over(line)
        return out

    def loss(x: list[float]) -> float:
        a, b = (min(max(v, lo), hi) for v in x)
        penalty = sum((v - min(max(v, lo), hi)) ** 2 for v in x)
        g = scoreline_grid(math.exp(a), math.exp(b), s.low_score_correction, s.max_goals)
        p = probs(g)
        return sum((p[k] - market[k]) ** 2 for k in market) + penalty

    best = _nelder_mead(loss, [math.log(1.4), math.log(1.1)])
    home_rate, away_rate = (math.exp(min(max(v, lo), hi)) for v in best)
    grid = scoreline_grid(home_rate, away_rate, s.low_score_correction, s.max_goals)
    model = probs(grid)
    max_error = max(abs(model[k] - market[k]) for k in market)
    if max_error > s.fit_tolerance:
        reasons.append(
            f"model misses a market probability by {max_error * 100:.1f} points "
            f"(tolerance {s.fit_tolerance * 100:.1f})"
        )
    for name, rate in (("home", home_rate), ("away", away_rate)):
        if math.isclose(rate, s.min_rate, rel_tol=1e-6) or math.isclose(
            rate, s.max_rate, rel_tol=1e-6
        ):
            reasons.append(f"{name} goal rate hit its bound ({rate:.2f})")
    return MatchFit(
        home_rate=home_rate,
        away_rate=away_rate,
        grid=grid,
        market=market,
        model=model,
        max_error=max_error,
        margins=margins,
        goals_line=line,
        confidence="low" if reasons else "normal",
        reasons=reasons,
    )


def main_half_line(record: dict) -> tuple[float | None, float | None, float | None, int, str]:
    """Pick the half-goal line most bookmakers quote from an odds snapshot record.

    Returns (line, over_price, under_price, bookmakers, note). Records written before the
    per-line change (13 November 2026) only have the single stored line.
    """
    totals = record.get("totals")
    if totals is None:
        line = record.get("total_line")
        if is_half_line(line):
            return (
                line,
                record.get("over_price"),
                record.get("under_price"),
                0,
                ("old snapshot format: goals bookmaker count unknown"),
            )
        return line, None, None, 0, ""
    half = [t for t in totals if is_half_line(t["line"])]
    if not half:
        main = record.get("total_line")
        return main, None, None, 0, ""
    best = max(half, key=lambda t: (t["bookmakers"], -t["line"]))
    note = ""
    if record.get("total_line") is not None and best["line"] != record["total_line"]:
        note = (
            f"most quoted line {record['total_line']} is not a half-goal line; "
            f"used {best['line']} ({best['bookmakers']} bookmakers)"
        )
    return best["line"], best["over_price"], best["under_price"], best["bookmakers"], note
