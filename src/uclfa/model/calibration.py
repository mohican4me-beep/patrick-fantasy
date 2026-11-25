"""Learning from results (Release 2 Phase F).

Three jobs, all on public data only:
1. Parse a saved Champions League stats file (price, UCL fantasy points, appearances,
   minutes, goal and assist totals per player).
2. Compare frozen predictions for a matchday with what players actually scored, taken as
   the difference in season UCL points between a stats file saved before the matchday and
   one saved after it.
3. Blend each player's league baseline with his UCL record so far: start chance and
   minutes, goal and assist shares, and for midfielders and forwards a per-player rate of
   points not otherwise modelled (recoveries, cards, player of the match).

Every output is an analyst estimate. A player without UCL data keeps his baseline.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from uclfa.model.match import DEFAULT_SETTINGS_PATH


class CalibrationSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    prior_minutes: float = Field(gt=0)
    bonus_positions: list[str]
    sixty_if_average_at_least: float = Field(ge=60, le=90)


def load_calibration_settings(path: Path = DEFAULT_SETTINGS_PATH) -> CalibrationSettings:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return CalibrationSettings.model_validate(data["calibration"])


# -- stats files ---------------------------------------------------------------------


def parse_ucl_stats(path: Path) -> dict[tuple[str, str], dict[str, Any]]:
    """Rows keyed by (name, club). Line format, under '@club' headers:
    name;position;price;ucl_points;apps;minutes;goals;assists (totals)."""
    rows: dict[tuple[str, str], dict[str, Any]] = {}
    club: str | None = None
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("@"):
            club = line[1:].split(";")[0]
            continue
        parts = line.split(";")
        if club is None or len(parts) != 8:
            raise ValueError(f"{path.name} line {number}: unexpected layout: {raw!r}")
        name, pos, price, pts, apps, mins, goals, assists = parts
        rows[(name, club)] = {
            "name": name,
            "club": club,
            "position": pos,
            "price": float(price),
            "ucl_points": int(pts),
            "apps": int(apps),
            "minutes": int(mins.replace(",", "")),
            "goals": int(goals),
            "assists": int(assists),
        }
    return rows


def matchday_actuals(
    before: dict[tuple[str, str], int], after: dict[tuple[str, str], dict[str, Any]]
) -> dict[tuple[str, str], dict[str, Any]]:
    """Points scored in the matchday: season UCL points after minus before. `before` maps
    (name, club) to season UCL points. Players missing from either side are left out."""
    out = {}
    for key, row in after.items():
        if key in before:
            pts = row["ucl_points"] - before[key]
            out[key] = {"points": pts, "played": pts != 0}
    return out


# -- review --------------------------------------------------------------------------


def review(
    predictions: list[dict[str, Any]], actuals: dict[tuple[str, str], dict[str, Any]]
) -> dict[str, Any]:
    """Predicted against actual for every predicted player with an actual score."""
    rows = []
    for p in predictions:
        if p.get("expected_points") is None:
            continue
        actual = actuals.get((p["source_name"], p["source_club"]))
        if actual is None:
            continue
        rows.append(
            {
                "name": p["name"],
                "position": p["position"],
                "club": p["source_club"],
                "in_squad": p.get("in_squad", False),
                "predicted": p["expected_points"],
                "actual": actual["points"],
                "error": round(actual["points"] - p["expected_points"], 2),
            }
        )

    def summary(group: list[dict[str, Any]]) -> dict[str, Any]:
        if not group:
            return {"players": 0}
        n = len(group)
        pred = sum(r["predicted"] for r in group)
        act = sum(r["actual"] for r in group)
        mae = sum(abs(r["error"]) for r in group) / n
        flat = act / n  # a naive guess: everyone scores the group's average
        mae_flat = sum(abs(r["actual"] - flat) for r in group) / n
        return {
            "players": n,
            "predicted_mean": round(pred / n, 2),
            "actual_mean": round(act / n, 2),
            "bias": round((act - pred) / n, 2),  # positive: the model was too low
            "mean_abs_error": round(mae, 2),
            "mean_abs_error_flat_guess": round(mae_flat, 2),
            "correlation": _correlation(
                [r["predicted"] for r in group], [r["actual"] for r in group]
            ),
        }

    by_pos = {
        pos: summary([r for r in rows if r["position"] == pos])
        for pos in ("GK", "DEF", "MID", "FWD")
    }
    return {
        "tag": "analyst_estimate",
        "overall": summary(rows),
        "by_position": by_pos,
        "squad": summary([r for r in rows if r["in_squad"]]),
        "rows": sorted(rows, key=lambda r: -abs(r["error"])),
        "note": (
            "Actual = change in season UCL points between two saved stats files. The flat "
            "guess gives every player the group's actual average; a useful model should "
            "beat it. One matchday is a small sample."
        ),
    }


def _correlation(x: list[float], y: list[float]) -> float | None:
    n = len(x)
    if n < 3:
        return None
    mx, my = sum(x) / n, sum(y) / n
    sx = math.sqrt(sum((a - mx) ** 2 for a in x))
    sy = math.sqrt(sum((b - my) ** 2 for b in y))
    if sx == 0 or sy == 0:
        return None
    return round(sum((a - mx) * (b - my) for a, b in zip(x, y, strict=True)) / (sx * sy), 3)


# -- blending inputs -----------------------------------------------------------------


def blend_inputs(
    player: dict[str, Any],
    ucl: dict[str, Any],
    team_matches: int,
    team_goals: int,
    scoring: Any,
    s: CalibrationSettings,
) -> dict[str, Any]:
    """Updated model inputs from a player's UCL record so far. Returns only changed
    fields. `team_matches` and `team_goals` are his club's finished UCL matches and goals."""
    if "start_prob" not in player or ucl["minutes"] <= 0 or team_matches <= 0:
        return {}
    w = ucl["minutes"] / (ucl["minutes"] + s.prior_minutes)
    starts_est = min(ucl["apps"], ucl["minutes"] / max(player["minutes_if_start"], 60))
    out: dict[str, Any] = {
        "start_prob": round(
            (1 - w) * player["start_prob"] + w * min(1.0, starts_est / team_matches), 3
        ),
    }
    per_game = ucl["minutes"] / ucl["apps"] if ucl["apps"] else 0.0
    if team_goals > 0:
        share_goals = ucl["goals"] / team_goals * (90 * team_matches / ucl["minutes"])
        share_assists = ucl["assists"] / team_goals * (90 * team_matches / ucl["minutes"])
        out["goal_share"] = round((1 - w) * player["goal_share"] + w * min(0.6, share_goals), 3)
        out["assist_share"] = round(
            (1 - w) * player["assist_share"] + w * min(0.5, share_assists), 3
        )
    if ucl["position"] in s.bonus_positions and ucl["apps"] > 0:
        pos = ucl["position"]
        sixty = ucl["apps"] if per_game >= s.sixty_if_average_at_least else 0
        explained = (
            ucl["apps"] * scoring.appearance
            + sixty * scoring.sixty_minutes
            + ucl["goals"] * scoring.goal[pos]
            + ucl["assists"] * scoring.assist
        )
        residual_p90 = max(0.0, (ucl["ucl_points"] - explained) / ucl["minutes"] * 90)
        out["bonus_p90_ucl"] = round(residual_p90, 2)
        out["bonus_weight"] = round(w, 3)
    return out
