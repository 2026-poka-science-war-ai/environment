from wii_arena.dolphin import DolphinGameCubeControllerInput, DolphinObservation

from environment.scenario.types import PlayerSeat


class Model:
    def __init__(self, player: PlayerSeat, team_players: list[PlayerSeat]) -> None:
        self._player = player
        self._team_players = team_players

    def act(self, observation: DolphinObservation) -> DolphinGameCubeControllerInput:
        _memory, screens = observation
        _own_view = screens[self._player]
        return DolphinGameCubeControllerInput(a=True)
