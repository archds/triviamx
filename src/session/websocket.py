import asyncio
import typing
import uuid
from collections import defaultdict

import config
import litestar.channels
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


class ChannelMessage(pydantic.BaseModel):
    event_type: str
    client_data: ClientData


ClientSessionCommand = typing.Literal["SetGuess"]
ClientSessionValue = str
ClientSessionMessage = dict[str, str]

PlayerJoinedEvent = "player-joined"
PlayerLeftEvent = "player-left"
PlayerGuessSetEvent = "guess-set"
PlayerGuessUnsetEvent = "guess-unset"
NextQuestion = "next-question"
RevealAnswers = "reveal-answers"


async def publish_to_channel(
    channels: litestar.channels.ChannelsPlugin,
    message: ChannelMessage,
) -> None:
    channels.publish(message.model_dump_json(), str(message.client_data.game_session.id))


async def reveal_answers_if_all_guessed(
    game_session_id: uuid.UUID,
    session_manager: state.GameSessionManager,
    channels: litestar.channels.ChannelsPlugin,
    player_session_id: str,
):
    game_session = await session_manager.get_session(game_session_id)

    if not game_session.all_guessed:
        return

    message = ChannelMessage(
        event_type=RevealAnswers,
        client_data=ClientData(
            player_session_id=player_session_id,
            game_session=game_session,
        ),
    )
    await publish_to_channel(channels, message)


async def handle_channel_message(
    socket: GameWebsocket,
    channels: litestar.channels.ChannelsPlugin,
    game_session_id: uuid.UUID,
    session_manager: state.GameSessionManager,
    player_session_id: str,
) -> None:
    reveal_answer_task = None

    async with channels.start_subscription(str(game_session_id)) as subscription:
        async for message in subscription.iter_events():
            message = ChannelMessage.model_validate_json(message)
            tasks = []

            if message.event_type in [PlayerJoinedEvent, PlayerLeftEvent]:
                tasks.append(socket.send_template("players.html", message.client_data))

            if message.event_type in [PlayerGuessSetEvent, PlayerGuessUnsetEvent]:
                tasks.append(socket.send_template("players.html", message.client_data))
                tasks.append(socket.send_template("answers.html", message.client_data))

            if message.event_type == PlayerGuessSetEvent:
                reveal_answer_task = utils.create_delayed_task(
                    reveal_answers_if_all_guessed(
                        game_session_id=game_session_id,
                        session_manager=session_manager,
                        channels=channels,
                        player_session_id=player_session_id,
                    ),
                    delay=5,
                )

            if message.event_type == PlayerGuessUnsetEvent and reveal_answer_task:
                reveal_answer_task.cancel()

            if message.event_type == RevealAnswers:
                new_message = ChannelMessage(
                    event_type=NextQuestion,
                    client_data=message.client_data,
                )
                tasks.append(
                    socket.send_template("answers-revealed.html", new_message.client_data)
                )
                tasks.append(
                    utils.create_delayed_task(publish_to_channel(channels, new_message), delay=5)
                )

            if message.event_type == NextQuestion:
                session = await session_manager.next_question(game_session_id)
                client_data = ClientData(
                    player_session_id=player_session_id,
                    game_session=session,
                )

                tasks.append(socket.send_template("question.html", client_data))
                tasks.append(socket.send_template("players.html", client_data))

            await asyncio.gather(*tasks)


class GameWebsocketListener(litestar.handlers.WebsocketListener):
    path = "/game-session/{game_session_id:str}"
    sockets: dict[uuid.UUID, list[GameWebsocket]] = defaultdict(list)
    next_question_timer_tasks = {}
    channel_handlers = {}

    async def on_accept(
        self,
        socket: GameWebsocket,
        game_session_id: uuid.UUID,
        player_session_id: str,
        session_manager: state.GameSessionManager,
        channels: litestar.channels.ChannelsPlugin,
    ) -> None:
        self.sockets[game_session_id].append(socket)
        self.channel_handlers[player_session_id] = asyncio.create_task(
            handle_channel_message(
                socket,
                channels,
                game_session_id,
                session_manager,
                player_session_id,
            )
        )

        session = await session_manager.join_session(
            session_id=game_session_id,
            player_session_id=player_session_id,
        )
        message = ChannelMessage(
            event_type=PlayerJoinedEvent,
            client_data=ClientData(
                player_session_id=player_session_id,
                game_session=session,
            ),
        )
        channels.publish(message.model_dump_json(), str(game_session_id))

    async def on_disconnect(
        self,
        socket: GameWebsocket,
        game_session_id: uuid.UUID,
        player_session_id: str,
        session_manager: state.GameSessionManager,
        channels: litestar.channels.ChannelsPlugin,
    ) -> None:
        self.sockets[game_session_id].remove(socket)
        self.channel_handlers[player_session_id].cancel()
        session = await session_manager.leave_session(
            session_id=game_session_id,
            player_session_id=player_session_id,
        )
        message = ChannelMessage(
            event_type=PlayerLeftEvent,
            client_data=ClientData(
                player_session_id=player_session_id,
                game_session=session,
            ),
        )
        channels.publish(message.model_dump_json(), str(game_session_id))

    async def on_receive(
        self,
        data: ClientSessionMessage,
        socket: GameWebsocket,
        game_session_id: uuid.UUID,
        player_session_id: str,
        session_manager: state.GameSessionManager,
        channels: litestar.channels.ChannelsPlugin,
    ) -> str:
        match data["Command"]:
            case "SetGuess":
                session = await session_manager.set_player_guess(
                    session_id=game_session_id,
                    player_session_id=player_session_id,
                    guess=data["Value"],
                )

                message = ChannelMessage(
                    event_type=PlayerGuessSetEvent,
                    client_data=ClientData(
                        player_session_id=player_session_id,
                        game_session=session,
                    ),
                )

                channels.publish(message.model_dump_json(), str(game_session_id))

            case "UnsetGuess":
                session = await session_manager.unset_player_guess(
                    session_id=game_session_id,
                    player_session_id=player_session_id,
                )

                message = ChannelMessage(
                    event_type=PlayerGuessUnsetEvent,
                    client_data=ClientData(
                        player_session_id=player_session_id,
                        game_session=session,
                    ),
                )

                channels.publish(message.model_dump_json(), str(game_session_id))

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
