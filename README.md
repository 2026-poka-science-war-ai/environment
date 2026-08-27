<div align="center">

# 👾<br>Environment

The Official AI Competition Environment for the 2026 KAIST–POSTECH Science War

</div>

## Overview

Participants submit a model, one Python file per seat, which competes across multiple scenarios.

The goal of this environment is to provide a standardized interface for participants to develop and test their AI agents.
Providing a trainable environment to participants is not a goal.

## Quickstart

### Docker Environment with NVIDIA Support

```bash
docker pull ghcr.io/betarixm/wii-arena-dolphin:latest
```

```bash
apt update
apt install ffmpeg
```

```bash
uv add "environment[nvidia-docker]@git+https://github.com/2026-poka-science-war-ai/environment.git"
```


### Local Environment with NVIDIA Support

```bash
apt update
apt install libbluetooth3 libhidapi-hidraw0 libspng0 libpugixml1v5 libqt6core6t64 libqt6dbus6t64 ffmpeg
```

```bash
wget "https://.../wii-arena-dolphin-linux-x86_64.zip" # Download from GitHub Actions Artifacts (betarixm/wii-arena)
wget "https://.../wii-arena-vulkan-layer-linux-x86_64.zip"  # Download from GitHub Actions Artifacts (betarixm/wii-arena)
unzip ...
```

```bash
uv add "environment[nvidia-local]@git+https://github.com/2026-poka-science-war-ai/environment.git"
```


## Submitting a Model

A submission is a single Python file exposing a class named `Model`. It is
constructed with the seat it drives and the seats its whole team drives, and is
asked for one controller input per frame while a race is live.

```python
from wii_arena.dolphin import DolphinGameCubeControllerInput, DolphinObservation

from environment.scenario.types import PlayerSeat


class Model:
    def __init__(self, player: PlayerSeat, team_players: list[PlayerSeat]) -> None:
        self._player = player
        self._team_players = team_players

    def act(self, observation: DolphinObservation) -> DolphinGameCubeControllerInput:
        memory, screens = observation
        own_view = screens[self._player]
        return DolphinGameCubeControllerInput(a=True)
```

`PlayerSeat` is `Literal[1, 2, 3, 4]`, so a seat that is not one of the four
controller ports is a type error rather than a runtime surprise.

`screens[0]` is the composited split screen with the on-screen overlay drawn
on it. `screens[1]` through `screens[4]` are the four seats' own views,
rendered without any overlay, which is why a model is told which seat it is.

Models are asked to act through the countdown and the race, so a rocket start is
part of the race. The menus between races are walked by the environment, and
models are not asked to act there.

## Environment Behavior

### Execution Model

The environment runs synchronously. It waits for the agent to return an action before advancing to the next step.

### Observation Semantics

The environment returns a memory view, not a memory copy. Therefore, agents must not mutate the observation returned by the environment. The environment does not enforce immutability at the type or runtime level. However, because execution is synchronous, participants may treat observations as immutable within each step.

## Limitations

### CUDA Support

Running the environment with `DockerDolphin` and `ghcr.io/betarixm/wii-arena-dolphin` is supported only on Linux with CUDA.

## Contributing

To contribute core logic, please contribute to <https://github.com/betarixm/wii-arena>.

To contribute competition scenarios, please contribute to this repository. This includes scenarios for specific games, streaming renderers, and related components.

## Disclaimer

The maintainers of this repository are not affiliated with Nintendo in any way. This project is an independent initiative to create an environment for AI competitions based on Nintendo's Wii console.

We do not endorse or promote any unauthorized use of Nintendo's intellectual property. Participants are responsible for ensuring that their actions comply with all applicable laws and regulations regarding the use of copyrighted materials.

We do not provide Wii disc image files. Participants are expected to obtain any required files through legal means.