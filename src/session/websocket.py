import asyncio
import typing
import uuid
from collections import defaultdict

import config
import litestar.events
import litestar.handlers
import pydantic
import utils

import session.state as state


class GameWebsocket(litestar.WebSocket):
    async def send_template(self, template_name: str, context: dict | pydantic.BaseModel) -> None:
        if isinstance(context, pydantic.BaseModel):
            context = context.model_dump()

        template = config.template_config.engine_instance.get_template(template_name)
        rendered = template.render(context)
        await self.send_text(rendered)


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
async def update_players_after_join(
    game_session: state.GameSession,
    sockets: list[GameWebsocket],
    session_manager: state.GameSessionManager,
):
    for socket in sockets:
        data = await GameWebsocketListener.get_client_data_from_socket(game_session, socket)
        await socket.send_template("players.html", data)


@litestar.events.listener(PlayerGuessSetEvent, PlayerGuessUnsetEvent)
async def update_player_status_after_guess(
    game_session: state.GameSession,
    sockets: list[GameWebsocket],
    session_manager: state.GameSessionManager,
):
    for socket in sockets:
        data = await GameWebsocketListener.get_client_data_from_socket(game_session, socket)
        await socket.send_template("players.html", data)


@litestar.events.listener(PlayerGuessSetEvent)
async def next_question_if_all_guessed(
    game_session: state.GameSession,
    sockets: list[GameWebsocket],
    session_manager: state.GameSessionManager,
):
    if game_session.all_guessed:
        await asyncio.sleep(3)
        game_session = await session_manager.get_session(game_session.id)

        if game_session.all_guessed:
            game_session = await session_manager.next_question(game_session.id)

            for socket in sockets:
                data = await GameWebsocketListener.get_client_data_from_socket(
                    game_session, socket
                )
                await socket.send_template("question.html", data)


@litestar.events.listener(PlayerGuessSetEvent, PlayerGuessUnsetEvent)
async def update_answers_after_guess(
    game_session: state.GameSession,
    sockets: list[GameWebsocket],
    session_manager: state.GameSessionManager,
):
    for socket in sockets:
        data = await GameWebsocketListener.get_client_data_from_socket(game_session, socket)
        await socket.send_template("answers.html", data)


LISTENERS = [
    update_players_after_join,
    update_player_status_after_guess,
    next_question_if_all_guessed,
    update_answers_after_guess,
]


class GameWebsocketListener(litestar.handlers.WebsocketListener):
    path = "/game-session"
    sockets: dict[uuid.UUID, list[GameWebsocket]] = defaultdict(list)
    timer_tasks = {}

    async def on_accept(
        self,
        socket: GameWebsocket,
        game_session_id: uuid.UUID,
        player_session_id: str,
        session_manager: state.GameSessionManager,
    ) -> None:
        session = await session_manager.join_session(
            session_id=game_session_id,
            player_session_id=player_session_id,
        )
        self.sockets[game_session_id].append(socket)
        socket.app.emit(
            PlayerJoinedEvent,
            game_session=session,
            sockets=self.sockets[game_session_id],
            session_manager=session_manager,
        )

    async def on_disconnect(
        self,
        socket: GameWebsocket,
        game_session_id: uuid.UUID,
        player_session_id: str,
        session_manager: state.GameSessionManager,
    ) -> None:
        session = await session_manager.leave_session(
            session_id=game_session_id,
            player_session_id=player_session_id,
        )
        self.sockets[game_session_id].remove(socket)
        socket.app.emit(
            PlayerLeftEvent,
            game_session=session,
            sockets=self.sockets[game_session_id],
            session_manager=session_manager,
        )

    async def on_receive(
        self,
        data: ClientSessionMessage,
        socket: GameWebsocket,
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

                socket.app.emit(
                    PlayerGuessSetEvent,
                    game_session=session,
                    sockets=self.sockets[game_session_id],
                    session_manager=session_manager,
                )

            case "UnsetGuess":
                session = await session_manager.unset_player_guess(
                    session_id=game_session_id,
                    player_session_id=player_session_id,
                )

                socket.app.emit(
                    PlayerGuessUnsetEvent,
                    game_session=session,
                    sockets=self.sockets[game_session_id],
                    session_manager=session_manager,
                )

        return "Received."

    @staticmethod
    async def get_client_data_from_socket(
        game_session: state.GameSession,
        socket: GameWebsocket,
    ) -> ClientData:
        return ClientData(
            player_session_id=await utils.get_player_session_id(socket),
            game_session=game_session,
        )
