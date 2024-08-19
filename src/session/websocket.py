import asyncio
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


ClientSessionMessage = dict[str, str]

PlayerJoinedEvent = "player-joined"
PlayerLeftEvent = "player-left"
PlayerGuessSetEvent = "guess-set"
PlayerGuessUnsetEvent = "guess-unset"
RevealAnswers = "reveal-answers"
NextQuestion = "next-question"


@litestar.events.listener(PlayerJoinedEvent, PlayerLeftEvent)
async def update_players_after_join(game_session: state.GameSession, **kwargs):
    await GameWebsocketListener.broadcast_template("players.html", game_session)


@litestar.events.listener(PlayerGuessSetEvent, PlayerGuessUnsetEvent)
async def update_player_status_after_guess(game_session: state.GameSession, **kwargs):
    await GameWebsocketListener.broadcast_template("players.html", game_session)


@litestar.events.listener(RevealAnswers)
async def reveal_answers(game_session: state.GameSession, **kwargs):
    await GameWebsocketListener.broadcast_template("revealed-answers.html", game_session)


@litestar.events.listener(NextQuestion)
async def next_question(
    game_session: state.GameSession,
    session_manager: state.GameSessionManager,
    **kwargs,
):
    game_session = await session_manager.next_question(game_session.id)

    tasks = [
        GameWebsocketListener.broadcast_template("question.html", game_session),
        GameWebsocketListener.broadcast_template("players.html", game_session),
    ]

    await asyncio.gather(*tasks)


@litestar.events.listener(PlayerGuessSetEvent, PlayerGuessUnsetEvent)
async def update_answers_after_guess(game_session: state.GameSession, **kwargs):
    await GameWebsocketListener.broadcast_template("answers.html", game_session)


LISTENERS = [
    update_players_after_join,
    update_player_status_after_guess,
    update_answers_after_guess,
    reveal_answers,
    next_question,
]


class GameWebsocketListener(litestar.handlers.WebsocketListener):
    path = "/game-session"
    sockets: dict[uuid.UUID, list[GameWebsocket]] = defaultdict(list)
    reveal_answers_tasks = {}
    next_question_tasks = {}

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
                    session_manager=session_manager,
                )

                if session.all_guessed:
                    self.next_question_tasks[game_session_id] = asyncio.create_task(
                        utils.chain_awaitables(
                            asyncio.sleep(5),
                            utils.sync_to_async(socket.app.emit)(
                                RevealAnswers,
                                game_session=session,
                                session_manager=session_manager,
                            ),
                            asyncio.sleep(5),
                            utils.sync_to_async(socket.app.emit)(
                                NextQuestion,
                                game_session=session,
                                session_manager=session_manager,
                            ),
                        )
                    )
            case "UnsetGuess":
                session = await session_manager.unset_player_guess(
                    session_id=game_session_id,
                    player_session_id=player_session_id,
                )

                socket.app.emit(
                    PlayerGuessUnsetEvent,
                    game_session=session,
                    session_manager=session_manager,
                )
                next_question_task = self.next_question_tasks.pop(game_session_id, None)

                if next_question_task:
                    next_question_task.cancel()

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

    @classmethod
    async def broadcast_template(cls, template_name: str, session: state.GameSession) -> None:
        for socket in cls.sockets[session.id]:
            data = await cls.get_client_data_from_socket(session, socket)
            await socket.send_template(template_name, data)

    @staticmethod
    def create_emit_after_task(
        socket: GameWebsocket,
        event_type: str,
        game_session: state.GameSession,
        session_manager: state.GameSessionManager,
        delay: int,
    ) -> asyncio.Task:
        async def _emit():
            socket.app.emit(
                event_type,
                game_session=game_session,
                session_manager=session_manager,
            )

        return utils.create_delayed_task(_emit(), delay)
