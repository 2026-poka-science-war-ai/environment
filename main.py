"""Runs the competition: three VS races, each recorded to its own video."""

import argparse
import logging
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Final

import docker
from docker.models.images import Image
from wii_arena.dolphin import Dolphin
from wii_arena.dolphin_docker_nvidia import NvidiaDockerDolphin

from environment.competition.functions import (
    competition_racer_count,
    load_competition_configuration,
)
from environment.competition.services import (
    MemoryVsPointsReader,
    TotalPointsMetric,
    run_competition,
)
from environment.record import (
    audio_dump_volume,
    cuda_pinned_gpu,
    dolphin_audio_dump_arguments,
)

_LOGGER = logging.getLogger(__name__)

DOCKER_IMAGE_NAME = "ghcr.io/betarixm/wii-arena-dolphin:latest"
SEAT_SCREEN_CAPTURE: Final[Mapping[str, str]] = {"FRAME_CAPTURE_OBSERVATION": "1"}


class NvidiaDockerDolphinFactory:
    def __init__(
        self,
        docker_image: Image,
        writable_memory: bool = False,
        internal_resolution: int | None = None,
    ) -> None:
        self._docker_image = docker_image
        self._writable_memory = writable_memory
        self._internal_resolution = internal_resolution
        self._gpu = cuda_pinned_gpu()

    def _dolphin_arguments(self) -> list[str]:
        arguments = dolphin_audio_dump_arguments()
        if self._internal_resolution is not None:
            arguments.append(
                "--config=Graphics.Settings.InternalResolution="
                f"{self._internal_resolution}"
            )
        return arguments

    def create(self, wii_iso_file: Path, audio_dump_directory: Path) -> Dolphin:
        return NvidiaDockerDolphin(
            docker_image=self._docker_image,
            wii_iso_file=wii_iso_file,
            extra_volumes=audio_dump_volume(audio_dump_directory),
            extra_dolphin_arguments=self._dolphin_arguments(),
            extra_environment=dict(SEAT_SCREEN_CAPTURE),
            gpu=self._gpu,
            writable_memory=self._writable_memory,
        )


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--configuration",
        type=Path,
        default=Path("competition.toml"),
        help="the competition configuration file",
    )
    parser.add_argument(
        "--video-directory",
        type=Path,
        default=Path("recordings"),
        help="where the three recordings are written",
    )
    parser.add_argument(
        "--internal-resolution",
        type=int,
        help=(
            "render at this multiple of the console's own resolution. Leave it "
            "alone for a competition: it is what the models see. Lowering it "
            "makes a verification run far cheaper to capture and encode."
        ),
    )
    parser.add_argument(
        "--writable-memory",
        action="store_true",
        help=(
            "let models write to the game's memory. Off for a real competition: "
            "a model that can write can drive itself round the course."
        ),
    )
    return parser.parse_args()


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )
    arguments = parse_arguments()

    configuration = load_competition_configuration(arguments.configuration)
    video_directory: Path = arguments.video_directory
    video_directory.mkdir(parents=True, exist_ok=True)

    outcome = run_competition(
        configuration=configuration,
        dolphin_factory=NvidiaDockerDolphinFactory(
            docker_image=docker.from_env().images.get(DOCKER_IMAGE_NAME),
            writable_memory=arguments.writable_memory,
            internal_resolution=arguments.internal_resolution,
        ),
        points_reader=MemoryVsPointsReader(competition_racer_count(configuration)),
        metric=TotalPointsMetric(),
        video_directory=video_directory,
    )

    for index, session in enumerate(outcome.sessions, start=1):
        _LOGGER.info(
            "VS race %d on %s: %s %d - %d %s, won by %s (attempt %d), recorded to %s",
            index,
            session.cup,
            configuration.team("a").name,
            session.scores.points_by_team["a"],
            session.scores.points_by_team["b"],
            configuration.team("b").name,
            configuration.team(session.winner).name,
            session.attempt,
            session.video_file,
        )
    _LOGGER.info("Competition won by %s", configuration.team(outcome.winner).name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
