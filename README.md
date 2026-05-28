<div align="center">

# 👾<br>Environment

The Official AI Competition Environment for the 2026 KAIST–POSTECH Science War

</div>

## Overview

Participants implement an `Agent` that follows `wii_arena.core.agent.protocols.Agent`. The submitted agent will compete across multiple scenarios.

The goal of this environment is to provide a standardized interface for participants to develop and test their AI agents.
Providing a trainable environment to participants is not a goal.

## Quickstart

### Docker Environment with NVIDIA Support

```bash
docker pull ghcr.io/betarixm/wii-arena-dolphin:latest
```

```bash
uv add "environment[nvidia-docker]@git+https://github.com/2026-poka-science-war-ai/environment.git"
```

```python
from pathlib import Path

import docker
from wii_arena.core.agent.protocols import Agent
from wii_arena.core.environment.types import Terminated, Truncated
from wii_arena.dolphin import DolphinEnvironment
from wii_arena.dolphin_docker_nvidia import NvidiaDockerDolphin

from environment.scenario.services import MarioKartWiiGrandPrixScenario

DOCKER_IMAGE = docker.from_env().images.get("ghcr.io/betarixm/wii-arena-dolphin:latest")
ISO_FILE: Path = ...
AGENT: Agent = ...

with DolphinEnvironment(
    scenario=MarioKartWiiGrandPrixScenario(
        dolphin=NvidiaDockerDolphin(docker_image=DOCKER_IMAGE, wii_iso_file=ISO_FILE)
    )
).session() as environment:
    observation, context = environment.reset()
    terminated, truncated = Terminated(False), Truncated(False)

    while not (terminated or truncated):
        action = AGENT.act(observation)
        observation, terminated, truncated, context = environment.step(action=action)
```

### Local Environment with NVIDIA Support

```bash
apt update
apt install libbluetooth3 libhidapi-hidraw0 libspng0 libpugixml1v5 libqt6core6t64 libqt6dbus6t64
```

```bash
wget "https://.../wii-arena-dolphin-linux-x86_64.zip" # Download from GitHub Actions Artifacts (betarixm/wii-arena)
wget "https://.../wii-arena-vulkan-layer-linux-x86_64.zip"  # Download from GitHub Actions Artifacts (betarixm/wii-arena)
unzip ...
```

```bash
uv add "environment[nvidia-local]@git+https://github.com/2026-poka-science-war-ai/environment.git"
```

```python
from wii_arena.core.agent.protocols import Agent
from wii_arena.core.environment.types import Terminated, Truncated
from wii_arena.cuda_driver import CudaDriver
from wii_arena.dolphin import DolphinEnvironment
from wii_arena.dolphin_local import LocalDolphin

from environment.scenario.services import MarioKartWiiGrandPrixScenario

AGENT: Agent = ...

with DolphinEnvironment(
    scenario=MarioKartWiiGrandPrixScenario(
        dolphin=LocalDolphin(
            executable_path=DOLPHIN_EXECUTABLE,
            vulcan_layer_path=VULKAN_LAYER_LIBRARY,
            vulkan_layer_configuration_path=VULKAN_LAYER_CONFIG,
            wii_iso_file=ISO_FILE,
            driver=CudaDriver(),
        )
    )
).session() as environment:
    observation, context = environment.reset()
    terminated, truncated = Terminated(False), Truncated(False)

    while not (terminated or truncated):
        action = AGENT.act(observation)
        observation, terminated, truncated, context = environment.step(action=action)
```

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