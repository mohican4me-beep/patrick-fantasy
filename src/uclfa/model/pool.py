"""Build the player pool from a saved public stats file (Release 2 Phase C).

Input: data/players/ffscout-<date>.txt, public columns copied from a fantasy stats site.
Output: data/players/pool.yaml. Prices are tagged third_party unless an override marks them
entered. The model inputs are baselines derived from league minutes, goals and assists by
the rules in model/settings.yaml (pool_baseline); they are analyst estimates.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict

from uclfa.model.match import DEFAULT_SETTINGS_PATH


class NewsSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    predicted_start_prob: float
    doubtful_start_prob: float
    not_in_xi_start_prob: float
    not_in_xi_sub_prob: float


def load_news_settings(path: Path = DEFAULT_SETTINGS_PATH) -> NewsSettings:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return NewsSettings.model_validate(data["news"])


def apply_news(players: list[dict[str, Any]], news: dict[str, Any], s: NewsSettings) -> None:
    """Set starting chances from team news. Raises on a name not in the pool."""
    by_name = {p["name"]: p for p in players}
    lists = {k: news.get(k) or [] for k in ("out", "doubtful", "not_in_xi", "predicted_xi")}
    unknown = sorted({n for names in lists.values() for n in names} - set(by_name))
    if unknown:
        raise ValueError(f"News names players not in the stats file: {unknown}")
    seen: dict[str, str] = {}
    for kind, names in lists.items():
        for name in names:
            if name in seen:
                raise ValueError(f"{name} is in both {seen[name]} and {kind}")
            seen[name] = kind
            p = by_name[name]
            if "start_prob" not in p:
                continue  # no baseline: news alone gives no number
            if kind == "out":
                p["start_prob"], p["sub_prob"] = 0.0, 0.0
            elif kind == "doubtful":
                p["start_prob"] = min(p["start_prob"], s.doubtful_start_prob)
            elif kind == "not_in_xi":
                p["start_prob"] = min(p["start_prob"], s.not_in_xi_start_prob)
                p["sub_prob"] = s.not_in_xi_sub_prob
            else:
                p["start_prob"] = max(p["start_prob"], s.predicted_start_prob)
            p["sources"].append(f"news MD{news['matchday']} ({news['read_on']}): {kind}")


class PoolBaseline(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    minutes_per_start: float
    max_start_prob: float
    p60_by_minutes: dict[int, float]
    sub_prob: float
    minutes_if_sub: float
    max_goal_share: float
    max_assist_share: float
    recoveries_p90: dict[str, float]
    saves_p90: float


def load_baseline(path: Path = DEFAULT_SETTINGS_PATH) -> PoolBaseline:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return PoolBaseline.model_validate(data["pool_baseline"])


def _count_and_rate(text: str) -> tuple[int, float]:
    """The source shows a count and a rate run together: '151.66' is 15 and 1.66."""
    text = text.strip()
    return int(text[:-4]), float(text[-4:])


def parse_stats_file(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    club: dict[str, Any] | None = None
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(";")
        try:
            if line.startswith("@"):
                _, per_match = _count_and_rate(parts[2])
                club = {"club": parts[0][1:], "played": int(parts[1]), "goals_pm": per_match}
                continue
            if club is None or len(parts) != 8:
                raise ValueError("unexpected layout")
            goals, g90 = _count_and_rate(parts[6])
            rows.append(
                {
                    **club,
                    "name": parts[0],
                    "position": parts[1],
                    "price": float(parts[2]),
                    "ucl_points": int(parts[3]),
                    "apps": int(parts[4]),
                    "minutes": int(parts[5].replace(",", "")),
                    "goals": goals,
                    "g90": g90,
                    "a90": float(parts[7]),
                }
            )
        except (ValueError, IndexError) as exc:
            raise ValueError(f"{path.name} line {number}: {exc}: {raw!r}") from exc
    return rows


def baseline_inputs(row: dict[str, Any], b: PoolBaseline) -> dict[str, Any]:
    """Model inputs from one stats row; empty when he has not played."""
    if row["apps"] == 0 or row["minutes"] == 0 or row["played"] == 0:
        return {}
    starts = min(row["apps"], row["minutes"] / b.minutes_per_start)
    minutes_if_start = min(90.0, max(60.0, row["minutes"] / starts))
    p60 = next(
        v for k, v in sorted(b.p60_by_minutes.items(), reverse=True) if minutes_if_start >= k
    )
    out: dict[str, Any] = {
        "start_prob": round(min(b.max_start_prob, starts / row["played"]), 2),
        "p60_if_start": p60,
        "minutes_if_start": round(minutes_if_start, 1),
        "sub_prob": b.sub_prob,
        "minutes_if_sub": b.minutes_if_sub,
        "goal_share": round(min(b.max_goal_share, row["g90"] / row["goals_pm"]), 3),
        "assist_share": round(min(b.max_assist_share, row["a90"] / row["goals_pm"]), 3),
        "recoveries_p90": b.recoveries_p90[row["position"]],
    }
    if row["position"] == "GK":
        out["saves_p90"] = b.saves_p90
    return out


def build_pool(
    stats_path: Path,
    overrides_path: Path | None,
    b: PoolBaseline,
    news: dict[str, Any] | None = None,
    news_settings: NewsSettings | None = None,
) -> dict[str, Any]:
    date = stats_path.stem.split("-", 1)[1]
    source = f"data/players/{stats_path.name}"
    data = {}
    if overrides_path is not None and overrides_path.exists():
        data = yaml.safe_load(overrides_path.read_text(encoding="utf-8")) or {}
    overrides: dict[str, dict[str, Any]] = dict(data.get("overrides") or {})
    players: list[dict[str, Any]] = []
    rows = parse_stats_file(stats_path)
    base = [
        {
            "name": row["name"],
            "club": row["club"],
            "position": row["position"],
            "price": row["price"],
            "price_tag": "third_party",
            "price_source": source,
            "price_date": date,
            **baseline_inputs(row, b),
            "sources": [
                f"{source}: {row['apps']} league apps, {row['minutes']} min, {row['goals']} goals, "
                f"{row['a90']} assists/90; baseline rules in model/settings.yaml"
            ],
        }
        for row in rows
    ]
    if news is not None:
        apply_news(base, news, news_settings or load_news_settings())
    for player in base:
        change = dict(overrides.pop(player["name"], {}))
        why = change.pop("why", None)
        if change.get("price_tag") == "entered":
            change.setdefault("price_source", "Patrick, from the game")
        if why:
            player["sources"].append(f"override: {why}")
        player.update(change)
        players.append(player)
    if overrides:
        raise ValueError(f"Overrides name players not in the stats file: {sorted(overrides)}")
    players.extend(data.get("extra") or [])
    return {"as_of": date, "built_from": source, "players": players}
