"""Learning from results (Release 2 Phase F)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from uclfa.model.calibration import (
    CalibrationSettings,
    blend_inputs,
    matchday_actuals,
    parse_ucl_stats,
    review,
)
from uclfa.model.player import PlayerInputs, TeamContext, expected_points, load_player_settings
from uclfa.service import freeze_predictions, review_view

MD5 = Path(__file__).parent / "data" / "md5"
CAL = CalibrationSettings(
    prior_minutes=360, bonus_positions=["MID", "FWD"], sixty_if_average_at_least=75
)


def ucl_file(tmp_path: Path, name: str, lines: str) -> Path:
    path = tmp_path / name
    path.write_text(lines, encoding="utf-8")
    return path


def test_parse_ucl_stats_and_actuals(tmp_path):
    path = ucl_file(
        tmp_path,
        "ffscout-ucl-2026-11-26.txt",
        "# test\n@FC Barcelona;5\nRaphinha;MID;9.6;45;5;305;5;1\n"
        "@Arsenal FC;5\nX;DEF;4.0;10;3;270;0;0\n",
    )
    rows = parse_ucl_stats(path)
    assert rows[("Raphinha", "FC Barcelona")]["goals"] == 5
    actual = matchday_actuals({("Raphinha", "FC Barcelona"): 33, ("X", "Arsenal FC"): 10}, rows)
    assert actual[("Raphinha", "FC Barcelona")] == {"points": 12, "played": True}
    assert actual[("X", "Arsenal FC")] == {"points": 0, "played": False}
    with pytest.raises(ValueError, match="line 1"):
        parse_ucl_stats(ucl_file(tmp_path, "bad.txt", "Raphinha;MID\n"))


def test_review_sums_by_hand():
    preds = [
        {
            "name": "A",
            "source_name": "A",
            "source_club": "C",
            "position": "MID",
            "expected_points": 6.0,
            "in_squad": True,
        },
        {
            "name": "B",
            "source_name": "B",
            "source_club": "C",
            "position": "MID",
            "expected_points": 2.0,
        },
        {
            "name": "D",
            "source_name": "D",
            "source_club": "C",
            "position": "FWD",
            "expected_points": 4.0,
        },
        {
            "name": "None",
            "source_name": "None",
            "source_club": "C",
            "position": "FWD",
            "expected_points": None,
        },
    ]
    actual = {("A", "C"): {"points": 10}, ("B", "C"): {"points": 1}, ("D", "C"): {"points": 4}}
    r = review(preds, actual)
    o = r["overall"]
    assert o["players"] == 3 and o["predicted_mean"] == 4.0 and o["actual_mean"] == 5.0
    assert o["bias"] == 1.0 and o["mean_abs_error"] == pytest.approx((4 + 1 + 0) / 3, abs=0.01)
    # Flat guess: everyone 5.0, misses 5, 4, 1.
    assert o["mean_abs_error_flat_guess"] == pytest.approx(10 / 3, abs=0.01)
    assert r["squad"]["players"] == 1 and r["by_position"]["GK"] == {"players": 0}
    assert r["rows"][0]["name"] == "A"  # biggest miss first


BASE = {"start_prob": 0.5, "minutes_if_start": 80.0, "goal_share": 0.1, "assist_share": 0.1}


def test_blending_moves_towards_ucl_by_the_weight_and_never_past(rules):
    """[scoring] The residual uses the scoring table: 1 per appearance, 1 per 60 minutes,
    5 per midfield goal, 3 per assist."""
    ucl = {"position": "MID", "ucl_points": 40, "apps": 4, "minutes": 360, "goals": 3, "assists": 1}
    out = blend_inputs(dict(BASE), ucl, team_matches=4, team_goals=10, scoring=rules.scoring, s=CAL)
    w = 360 / (360 + 360)
    starts = min(4, 360 / 80) / 4  # 4.5 capped at 4 appearances -> 1.0
    assert out["start_prob"] == pytest.approx((1 - w) * 0.5 + w * min(1.0, starts), abs=1e-3)
    assert 0.5 < out["start_prob"] <= 1.0
    share = 3 / 10 * (90 * 4 / 360)
    assert out["goal_share"] == pytest.approx((1 - w) * 0.1 + w * share, abs=1e-3)
    explained = 4 * 1 + 4 * 1 + 3 * 5 + 1 * 3
    assert out["bonus_p90_ucl"] == pytest.approx((40 - explained) / 360 * 90, abs=0.01)
    assert out["bonus_weight"] == pytest.approx(w, abs=1e-3)


def test_no_ucl_minutes_keeps_the_baseline_and_defenders_get_no_bonus(rules):
    none = {"position": "MID", "ucl_points": 0, "apps": 0, "minutes": 0, "goals": 0, "assists": 0}
    assert blend_inputs(dict(BASE), none, 4, 10, rules.scoring, CAL) == {}
    dfn = {"position": "DEF", "ucl_points": 20, "apps": 4, "minutes": 360, "goals": 0, "assists": 0}
    out = blend_inputs(dict(BASE), dfn, 4, 10, rules.scoring, CAL)
    assert "bonus_p90_ucl" not in out and "start_prob" in out


def test_bonus_replaces_recoveries_and_midfield_clean_sheet_without_double_counting(rules):
    s = load_player_settings()
    team = TeamContext(goals_for=2.0, goals_against=1.0, clean_sheet=0.36)
    base = dict(
        name="M",
        club="C",
        position="MID",
        start_prob=1.0,
        p60_if_start=1.0,
        minutes_if_start=90,
        goal_share=0.0,
        assist_share=0.0,
        recoveries_p90=6.0,
    )
    plain = expected_points(PlayerInputs(**base), team, rules, s)
    full = expected_points(
        PlayerInputs(**base, bonus_p90_ucl=2.5, bonus_weight=1.0), team, rules, s
    )
    assert full.components["balls_recovered"] == 0 and full.components["clean_sheet"] == 0
    assert full.components["bonus_ucl"] == pytest.approx(2.5)
    half = PlayerInputs(**base, bonus_p90_ucl=2.5, bonus_weight=0.5, baseline={"start_prob": 1})
    assert half.as_baseline().bonus_p90_ucl is None
    mixed = expected_points(half, team, rules, s)
    assert mixed.expected == pytest.approx((plain.expected + full.expected) / 2)


# -- freezing and reviewing on real files --------------------------------------------


POOL = """
as_of: "2026-11-15"
players:
  - {name: "Complete Defender", source_name: "C. Def", club: "Arsenal", position: DEF,
     price: 5.0, price_tag: third_party, start_prob: 0.9, p60_if_start: 0.95,
     minutes_if_start: 88, goal_share: 0.03, assist_share: 0.04, recoveries_p90: 6}
"""


def setup_dir(tmp_path: Path) -> Path:
    data = tmp_path / "data"
    shutil.copytree(MD5, data)
    (data / "players").mkdir()
    (data / "players" / "pool.yaml").write_text(POOL, encoding="utf-8")
    return data


def test_freeze_uses_only_snapshots_up_to_the_date(rules, tmp_path):
    data = setup_dir(tmp_path)
    frozen = freeze_predictions(5, "2026-11-15", rules, data_dir=data)
    (row,) = frozen["players"]
    assert row["expected_points"] is not None and row["source_name"] == "C. Def"
    early = freeze_predictions(5, "2026-11-01", rules, data_dir=data)
    assert early["players"] == [] or early["players"][0]["expected_points"] is None


def test_review_end_to_end(rules, tmp_path):
    data = setup_dir(tmp_path)
    (data / "predictions").mkdir()
    frozen = freeze_predictions(5, "2026-11-15", rules, data_dir=data)
    (data / "predictions" / "md05.json").write_text(json.dumps(frozen), encoding="utf-8")
    # Mark matchday 5 finished in the fixtures snapshot.
    fx = next((data / "snapshots" / "fixtures").glob("*.json"))
    snap = json.loads(fx.read_text("utf-8"))
    for r in snap["records"]:
        if r["matchday"] == 5:
            r["status"] = "FINISHED"
    fx.write_text(json.dumps(snap), "utf-8")
    assert review_view(5, data_dir=data)["tag"] == "unavailable"  # no stats files yet
    ucl_file(
        data / "players",
        "ffscout-2026-11-15.txt",
        "@Arsenal;10;151.50\nC. Def;DEF;5.0;10;10;900;00.00;0.00\n",
    )
    ucl_file(
        data / "players", "ffscout-ucl-2026-11-26.txt", "@Arsenal;5\nC. Def;DEF;5.0;18;5;450;0;0\n"
    )
    view = review_view(5, data_dir=data)
    assert view["tag"] == "analyst_estimate"
    assert view["overall"]["players"] == 1 and view["rows"][0]["actual"] == 8
    assert view["actual_from"] == ["ffscout-2026-11-15.txt", "ffscout-ucl-2026-11-26.txt"]


def test_review_without_frozen_predictions():
    assert review_view(9, data_dir=MD5)["tag"] == "unavailable"
