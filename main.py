from pathlib import Path

import docker
from wii_arena.dolphin import DolphinEnvironment
from wii_arena.dolphin_docker_nvidia import NvidiaDockerDolphin

from environment.arena import Arena, Player
from environment.record import Recorder
from environment.scenario.models import RaceConfiguration
from environment.scenario.services import MarioKartWiiRace

DOCKER_IMAGE = docker.from_env().images.get("ghcr.io/betarixm/wii-arena-dolphin:latest")
ISO_FILE: Path = ...
VIDEO_FILE: Path = ...
CONFIGURATION: RaceConfiguration = ...
PLAYERS: list[Player] = ...

assert len(PLAYERS) == len(CONFIGURATION.racers)

with Recorder(video_file=VIDEO_FILE) as recorder:
    recorder.record(
        Arena(
            environment=DolphinEnvironment(
                scenario=MarioKartWiiRace(
                    configuration=CONFIGURATION,
                    dolphin=NvidiaDockerDolphin(
                        docker_image=DOCKER_IMAGE, wii_iso_file=ISO_FILE
                    ),
                )
            ),
            players=PLAYERS,
        ).stream()
    )
