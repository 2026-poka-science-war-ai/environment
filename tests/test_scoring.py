from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Literal

import pytest

from environment.competition.models import (
    TeamScores,
    UndecidedSessionError,
    VsSessionOutcome,
)
from environment.competition.services import (
    TiedSessionUnresolvedError,
    TotalPointsMetric,
    VsPointsUnavailableError,
    decide_vs_session,
)
from environment.competition.types import SeatsByTeam, VsSessionVerdict
from environment.scenario.functions import DriftPageUnrecognisedError
from environment.scenario.types import PlayerSeat
from environment.telemetry.types import VsPoints

_SEATS: SeatsByTeam = {"a": (1, 3), "b": (2, 4)}


def _points(p1: int, p2: int, p3: int, p4: int) -> Mapping[PlayerSeat, VsPoints]:
    return {1: VsPoints(p1), 2: VsPoints(p2), 3: VsPoints(p3), 4: VsPoints(p4)}


def test_the_team_with_more_points_takes_the_session() -> None:
    scores = TotalPointsMetric().decide(_points(p1=15, p3=10, p2=12, p4=8), _SEATS)

    assert scores.points_by_team == {"a": 25, "b": 20}
    assert scores.verdict == "a"


def test_the_other_team_takes_the_session_when_it_scores_more() -> None:
    scores = TotalPointsMetric().decide(_points(p1=3, p3=2, p2=15, p4=12), _SEATS)

    assert scores.verdict == "b"


def test_a_level_score_is_a_tie_rather_than_a_winner() -> None:
    scores = TotalPointsMetric().decide(_points(p1=15, p3=8, p2=12, p4=11), _SEATS)

    assert scores.points_by_team == {"a": 23, "b": 23}
    assert scores.verdict == "tie"


def _outcome(verdict: VsSessionVerdict, attempt: int) -> VsSessionOutcome:
    return VsSessionOutcome(
        cup="Mushroom Cup",
        first_picking_team="a",
        points_by_seat=_points(p1=15, p2=12, p3=8, p4=11),
        scores=TeamScores(
            points_by_team={"a": VsPoints(23), "b": VsPoints(23)}, verdict=verdict
        ),
        attempt=attempt,
        video_file=Path("vs-race-1.mp4"),
    )


def test_a_tied_session_refuses_to_name_a_winner() -> None:
    with pytest.raises(UndecidedSessionError):
        _ = _outcome("tie", attempt=1).winner


class _RecordedAttempts:
    def __init__(
        self,
        verdicts: Sequence[VsSessionVerdict | Literal["no result", "menus lost"]],
        video_file: Path,
    ) -> None:
        self._verdicts = verdicts
        self._video_file = video_file
        self.leftover_recordings: list[bool] = []

    def __call__(self, *, attempt: int) -> VsSessionOutcome:
        self.leftover_recordings.append(self._video_file.exists())
        self._video_file.write_bytes(b"recording")
        verdict = self._verdicts[attempt - 1]
        if verdict == "no result":
            raise VsPointsUnavailableError("the session was truncated")
        if verdict == "menus lost":
            raise DriftPageUnrecognisedError("the drift page was not one of the two")
        return _outcome(verdict, attempt)


def test_a_replay_replaces_the_recording_of_the_attempt_it_supersedes(
    tmp_path: Path,
) -> None:
    video_file = tmp_path / "vs-race-1.mp4"
    attempts = _RecordedAttempts(["tie", "tie", "b"], video_file)

    decided = decide_vs_session(
        cup="Mushroom Cup", video_file=video_file, run_attempt=attempts
    )

    assert attempts.leftover_recordings == [False, False, False]
    assert decided.attempt == 3
    assert decided.winner == "b"


def test_a_cup_that_will_not_separate_the_teams_is_a_fault(tmp_path: Path) -> None:
    video_file = tmp_path / "vs-race-1.mp4"
    attempts = _RecordedAttempts(["tie", "tie"], video_file)

    with pytest.raises(TiedSessionUnresolvedError):
        decide_vs_session(
            cup="Mushroom Cup",
            video_file=video_file,
            run_attempt=attempts,
            max_attempts=2,
        )


def test_a_session_that_reaches_no_result_is_replayed(tmp_path: Path) -> None:
    video_file = tmp_path / "vs-race-1.mp4"
    attempts = _RecordedAttempts(["no result", "a"], video_file)

    decided = decide_vs_session(
        cup="Mushroom Cup", video_file=video_file, run_attempt=attempts
    )

    assert attempts.leftover_recordings == [False, False]
    assert (decided.attempt, decided.winner) == (2, "a")


def test_a_session_whose_menus_lose_their_way_is_replayed(tmp_path: Path) -> None:
    video_file = tmp_path / "vs-race-1.mp4"
    attempts = _RecordedAttempts(["menus lost", "a"], video_file)

    decided = decide_vs_session(
        cup="Mushroom Cup", video_file=video_file, run_attempt=attempts
    )

    assert attempts.leftover_recordings == [False, False]
    assert (decided.attempt, decided.winner) == (2, "a")


def test_a_session_that_never_reaches_a_result_is_a_fault(tmp_path: Path) -> None:
    video_file = tmp_path / "vs-race-1.mp4"
    attempts = _RecordedAttempts(["no result", "no result"], video_file)

    with pytest.raises(VsPointsUnavailableError):
        decide_vs_session(
            cup="Mushroom Cup",
            video_file=video_file,
            run_attempt=attempts,
            max_attempts=2,
        )

    assert attempts.leftover_recordings == [False, False]
