import typing
import uuid

import config
import litestar.events
import litestar.handlers
import pydantic
import utils

import session.state as state


class ClientData(pydantic.BaseModel):
    player_session_id: str
    game_session: state.GameSession

    @pydantic.computed_field
    @property
    def current_player(self) -> state.Player | None:
        try:
            return next(
                player
                for player in self.game_session.players
                if player.session_id == self.player_session_id
            )
        except StopIteration:
            return None


ClientSessionCommand = typing.Literal["SetGuess"]
ClientSessionValue = str
ClientSessionMessage = dict[str, str]

PlayerJoinedEvent = "player-joined"
PlayerLeftEvent = "player-left"
PlayerGuessSetEvent = "guess-set"
PlayerGuessUnsetEvent = "guess-unset"


@litestar.events.listener(PlayerJoinedEvent, PlayerLeftEvent)
async def update_players(game_session: state.GameSession):
    for socket in GameSessionHandler.sockets:
        player_session_id = await utils.get_player_session_id(socket)

        data = ClientData(
            player_session_id=player_session_id,
            game_session=game_session,
        )

        template = config.template_config.engine_instance.get_template("players.html")
        rendered = template.render(**data.model_dump())
        await socket.send_text(rendered)


@litestar.events.listener(PlayerGuessSetEvent, PlayerGuessUnsetEvent)
async def update_player_status(game_session: state.GameSession):
    for socket in GameSessionHandler.sockets:
        player_session_id = await utils.get_player_session_id(socket)

        data = ClientData(
            player_session_id=player_session_id,
            game_session=game_session,
        )

        template = config.template_config.engine_instance.get_template("player-status.html")
        rendered = template.render(player=data.current_player)
        await socket.send_text(rendered)


@litestar.events.listener(
    PlayerGuessSetEvent,
    PlayerGuessUnsetEvent,
    PlayerLeftEvent,
    PlayerJoinedEvent,
)
async def update_answers_box(game_session: state.GameSession):
    for socket in GameSessionHandler.sockets:
        player_session_id = await utils.get_player_session_id(socket)

        data = ClientData(
            player_session_id=player_session_id,
            game_session=game_session,
        )

        template = config.template_config.engine_instance.get_template("answers.html")
        rendered = template.render(**data.model_dump())
        await socket.send_text(rendered)


class GameSessionHandler(litestar.handlers.WebsocketListener):
    path = "/game-session"
    sockets = []

    async def on_accept(
        self,
        socket: litestar.WebSocket,
        game_session_id: uuid.UUID,
        player_session_id: str,
        session_manager: state.GameSessionManager,
    ) -> None:
        session = await session_manager.join_session(
            session_id=game_session_id,
            player_session_id=player_session_id,
        )

        self.sockets.append(socket)
        socket.app.emit(PlayerJoinedEvent, game_session=session)

    async def on_disconnect(
        self,
        socket: litestar.WebSocket,
        game_session_id: uuid.UUID,
        player_session_id: str,
        session_manager: state.GameSessionManager,
    ) -> None:
        session = await session_manager.leave_session(
            session_id=game_session_id,
            player_session_id=player_session_id,
        )
        self.sockets.remove(socket)
        socket.app.emit(PlayerLeftEvent, game_session=session)

    async def on_receive(
        self,
        data: ClientSessionMessage,
        socket: litestar.WebSocket,
        game_session_id: uuid.UUID,
        player_session_id: str,
        session_manager: state.GameSessionManager,
    ) -> str:
        match data["Command"]:
            case "SetGuess":
                session = await session_manager.set_player_guess(
                    session_id=game_session_id,
                    player_session_id=player_session_id,
                    guess=data["Value"],
                )

                socket.app.emit(PlayerGuessSetEvent, game_session=session)

            case "UnsetGuess":
                session = await session_manager.unset_player_guess(
                    session_id=game_session_id,
                    player_session_id=player_session_id,
                )

                socket.app.emit(PlayerGuessUnsetEvent, game_session=session)

        return "Received."
