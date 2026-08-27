import logging
from collections.abc import Mapping
from functools import partial
from pathlib import Path
from random import Random
from tempfile import TemporaryDirectory
from typing import Final, Protocol

from wii_arena.core.environment.types import Terminated, Truncated
from wii_arena.dolphin import (
    Dolphin,
    DolphinAction,
    DolphinEnvironment,
    DolphinObservation,
)

from ..arena import Player, PlayerAgent
from ..record import Recorder, find_audio_dumps, mux
from ..scenario.functions import kart_of_seat
from ..scenario.services import (
    MarioKartWiiRace,
    VsSessionLifecycle,
    idle_action,
)
from ..scenario.types import Cup, PlayerSeat
from ..telemetry.functions import read_vs_points
from ..telemetry.services import GuestMemory
from ..telemetry.types import KartIndex, RaceCompletion, RacerCount, VsPoints
from .functions import (
    first_picking_team,
    load_model,
    race_configuration_for,
    select_cups,
    select_opening_team,
    select_seat_assignment,
    series_is_decided,
)
from .models import (
    SEATS_IN_ORDER,
    TEAM_IDENTIFIERS,
    CompetitionConfiguration,
    CompetitionOutcome,
    TeamScores,
    VsSessionOutcome,
)
from .types import SeatsByTeam, TeamIdentifier, VsSessionVerdict

_LOGGER = logging.getLogger(__name__)

_PROGRESS_LOG_EVERY_FRAMES: Final[int] = 600

MAX_SESSION_ATTEMPTS: Final[int] = 5


class VsPointsUnavailableError(RuntimeError): ...


class ObservationScreensMissingError(RuntimeError): ...


class TiedSessionUnresolvedError(RuntimeError): ...


class DolphinFactory(Protocol):
    def create(self, wii_iso_file: Path, audio_dump_directory: Path) -> Dolphin: ...


class VsPointsReader(Protocol):
    def read(self, memory: GuestMemory) -> Mapping[KartIndex, VsPoints] | None: ...


class TeamOutcomeMetric(Protocol):
    def decide(
        self,
        points_by_seat: Mapping[PlayerSeat, VsPoints],
        seats_by_team: SeatsByTeam,
    ) -> TeamScores: ...


class MemoryVsPointsReader:
    def __init__(self, racer_count: RacerCount) -> None:
        self._racer_count = racer_count

    def read(self, memory: GuestMemory) -> Mapping[KartIndex, VsPoints] | None:
        return read_vs_points(memory, self._racer_count)


class TotalPointsMetric:
    def decide(
        self,
        points_by_seat: Mapping[PlayerSeat, VsPoints],
        seats_by_team: SeatsByTeam,
    ) -> TeamScores:
        points_by_team: Mapping[TeamIdentifier, VsPoints] = {
            identifier: VsPoints(
                sum(points_by_seat[seat] for seat in seats_by_team[identifier])
            )
            for identifier in TEAM_IDENTIFIERS
        }
        verdict: VsSessionVerdict
        if points_by_team["a"] == points_by_team["b"]:
            verdict = "tie"
        elif points_by_team["a"] > points_by_team["b"]:
            verdict = "a"
        else:
            verdict = "b"
        return TeamScores(points_by_team=points_by_team, verdict=verdict)


def _occupation(lifecycle: VsSessionLifecycle) -> str:
    if lifecycle.is_racing:
        return "racing"
    if lifecycle.is_counting_down:
        return "counting down"
    if lifecycle.is_session_complete:
        return "closing the session"
    if lifecycle.should_advance_menu:
        return "advancing the menus"
    return "waiting"


def _rounded(completion: RaceCompletion | None) -> float | None:
    return None if completion is None else round(completion, 2)


def _log_progress(cup: Cup, frame: int, lifecycle: VsSessionLifecycle) -> None:
    progress = lifecycle.latest_progress
    seats = (
        None
        if progress is None
        else {
            seat: _rounded(progress.completions.get(kart_of_seat(seat)))
            for seat in SEATS_IN_ORDER
        }
    )
    _LOGGER.info(
        "%s frame %d: %s, %d of %d races credited, stage %s, seats %s, %s home",
        cup,
        frame,
        _occupation(lifecycle),
        lifecycle.completed_race_count,
        lifecycle.race_count,
        lifecycle.stage,
        seats,
        "?" if progress is None else progress.finished_kart_count,
    )


def build_seat_agents(
    configuration: CompetitionConfiguration, seats_by_team: SeatsByTeam
) -> Mapping[PlayerSeat, PlayerAgent]:
    """Binds each team's models, in the order submitted, to its drawn seats."""
    return {
        seat: PlayerAgent(
            Player(
                name=f"{configuration.team(identifier).name} seat {seat}",
                model=load_model(model_file, seat, seats),
            ),
            seat,
        )
        for identifier, seats in seats_by_team.items()
        for seat, model_file in zip(seats, configuration.team(identifier).models)
    }


def _actions(
    agents: Mapping[PlayerSeat, PlayerAgent],
    observation: DolphinObservation,
    lifecycle: VsSessionLifecycle,
) -> DolphinAction:
    if not (lifecycle.is_racing or lifecycle.is_counting_down):
        return idle_action()

    _, screens = observation
    required_screens = len(SEATS_IN_ORDER) + 1
    if len(screens) < required_screens:
        if lifecycle.is_counting_down:
            return idle_action()
        raise ObservationScreensMissingError(
            f"a race is live but only {len(screens)} screens were captured, "
            f"{required_screens} are needed for seats {list(SEATS_IN_ORDER)}"
        )
    return [agents[seat].act(observation) for seat in SEATS_IN_ORDER]


def _add_sound(
    silent_video: Path, audio_dump_directory: Path, video_file: Path
) -> None:
    dumps = find_audio_dumps(audio_dump_directory)
    if not dumps:
        _LOGGER.warning(
            "No audio dump appeared in %s, so %s is silent",
            audio_dump_directory,
            video_file,
        )
        silent_video.replace(video_file)
        return
    mux(silent_video, dumps, video_file)
    silent_video.unlink()


def run_vs_session(
    configuration: CompetitionConfiguration,
    cup: Cup,
    picking_first: TeamIdentifier,
    seats_by_team: SeatsByTeam,
    dolphin_factory: DolphinFactory,
    points_reader: VsPointsReader,
    metric: TeamOutcomeMetric,
    video_file: Path,
    attempt: int,
) -> VsSessionOutcome:
    race_configuration = race_configuration_for(
        configuration, cup, picking_first, seats_by_team
    )
    agents = build_seat_agents(configuration, seats_by_team)

    _LOGGER.info(
        "Starting %s (attempt %d), %s picks first, recording to %s",
        cup,
        attempt,
        configuration.team(picking_first).name,
        video_file,
    )

    latest_points: Mapping[KartIndex, VsPoints] | None = None
    silent_video = video_file.with_suffix(".silent.mp4")

    with TemporaryDirectory() as audio_directory:
        audio_dump_directory = Path(audio_directory)
        with Recorder(video_file=silent_video) as recorder:
            scenario = MarioKartWiiRace(
                configuration=race_configuration,
                dolphin=dolphin_factory.create(
                    configuration.wii_iso_file, audio_dump_directory
                ),
                observe_frame=recorder.submit,
            )
            with DolphinEnvironment(scenario=scenario).session() as session:
                observation, _context = session.reset()
                lifecycle = scenario.lifecycle
                terminated, truncated = Terminated(False), Truncated(False)
                frame = 0

                while not (terminated or truncated):
                    observation, terminated, truncated, _context = session.step(
                        scenario.control(_actions(agents, observation, lifecycle))
                    )
                    recorder.submit(observation[1][0])
                    frame += 1
                    if frame % _PROGRESS_LOG_EVERY_FRAMES == 0:
                        _log_progress(cup, frame, lifecycle)

                    if lifecycle.is_session_complete:
                        sampled = points_reader.read(GuestMemory(observation[0]))
                        if sampled is not None:
                            latest_points = sampled

        _add_sound(silent_video, audio_dump_directory, video_file)

    if latest_points is None:
        raise VsPointsUnavailableError(
            f"the {cup} session ended without a readable point total"
        )

    points_by_seat: Mapping[PlayerSeat, VsPoints] = {
        seat: latest_points[kart_of_seat(seat)] for seat in SEATS_IN_ORDER
    }
    scores = metric.decide(points_by_seat, seats_by_team)
    _LOGGER.info(
        "%s finished: %s, verdict %s",
        cup,
        dict(scores.points_by_team),
        scores.verdict,
    )
    return VsSessionOutcome(
        cup=cup,
        first_picking_team=picking_first,
        points_by_seat=points_by_seat,
        scores=scores,
        attempt=attempt,
        video_file=video_file,
    )


class VsSessionAttempt(Protocol):
    def __call__(self, *, attempt: int) -> VsSessionOutcome: ...


def decide_vs_session(
    cup: Cup,
    video_file: Path,
    run_attempt: VsSessionAttempt,
    max_attempts: int = MAX_SESSION_ATTEMPTS,
) -> VsSessionOutcome:
    for attempt in range(1, max_attempts + 1):
        video_file.unlink(missing_ok=True)
        outcome = run_attempt(attempt=attempt)
        if outcome.scores.verdict != "tie":
            return outcome
        _LOGGER.warning(
            "%s ended level at %d points each; replaying it",
            cup,
            outcome.scores.points_by_team["a"],
        )

    raise TiedSessionUnresolvedError(
        f"{cup} was still level after {max_attempts} attempts"
    )


def run_competition(
    configuration: CompetitionConfiguration,
    dolphin_factory: DolphinFactory,
    points_reader: VsPointsReader,
    metric: TeamOutcomeMetric,
    video_directory: Path,
    random: Random | None = None,
    max_attempts: int = MAX_SESSION_ATTEMPTS,
) -> CompetitionOutcome:
    generator = Random() if random is None else random
    cups = select_cups(generator)
    opening_team = select_opening_team(generator)

    winners: list[TeamIdentifier] = []
    sessions: list[VsSessionOutcome] = []
    for session_index, cup in enumerate(cups):
        picking_first = first_picking_team(session_index, opening_team, winners)
        seats_by_team = select_seat_assignment(generator)
        outcome = decide_vs_session(
            cup=cup,
            video_file=video_directory / f"vs-race-{session_index + 1}.mp4",
            run_attempt=partial(
                run_vs_session,
                configuration=configuration,
                cup=cup,
                picking_first=picking_first,
                seats_by_team=seats_by_team,
                dolphin_factory=dolphin_factory,
                points_reader=points_reader,
                metric=metric,
                video_file=video_directory / f"vs-race-{session_index + 1}.mp4",
            ),
            max_attempts=max_attempts,
        )
        sessions.append(outcome)
        winners.append(outcome.winner)
        if series_is_decided(winners) and len(sessions) < len(cups):
            _LOGGER.info(
                "%s has taken the series %d-%d, so the remaining VS races are not run",
                configuration.team(outcome.winner).name,
                winners.count(outcome.winner),
                len(winners) - winners.count(outcome.winner),
            )
            break

    return CompetitionOutcome(sessions=sessions)
