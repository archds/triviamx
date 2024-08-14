import datetime
import random
import uuid
import pydantic
from api import OpenTriviaDB
import utils


class GameAnswerEntry(pydantic.BaseModel):
    text: str
    button_class: str


class GameQuestion(pydantic.BaseModel):
    text: str
    correct_answer: str
    incorrect_answers: list[str]
    guess: str | None = None
    get_at: datetime.datetime = pydantic.Field(default_factory=datetime.datetime.now)

    @pydantic.computed_field
    def answers(self) -> list[GameAnswerEntry]:
        rnd = random.Random(self.text)
        answ = self.incorrect_answers + [self.correct_answer]
        rnd.shuffle(answ)
        return [
            GameAnswerEntry(text=ans, button_class=self.get_button_class(ans))
            for ans in answ
        ]

    def get_button_class(self, button_text: str) -> str:
        default_class = "button"

        if button_text == self.correct_answer and self.guess == self.correct_answer:
            return default_class + " success bounce"
        if button_text == self.correct_answer and self.guess:
            return default_class + " success"
        if button_text != self.correct_answer and button_text == self.guess:
            return default_class + " error shake"
        if button_text != self.correct_answer and self.guess:
            return default_class + " error"

        return default_class


class GameState(pydantic.BaseModel):
    question: GameQuestion
    get_at: datetime.datetime = pydantic.Field(default_factory=datetime.datetime.now)
    answers_url: str = "/answers"
    avatar: utils.Avatar


class Player(pydantic.BaseModel):
    session_id: str
    nickname: str
    avatar: utils.Avatar

    @classmethod
    def new(cls, session_id: str) -> "Player":
        avatar = utils.get_avatar(session_id)
        return cls(session_id=session_id, nickname=avatar.name, avatar=avatar)


class GameSession(pydantic.BaseModel):
    id: uuid.UUID = pydantic.Field(default_factory=uuid.uuid4)
    current_question: GameQuestion
    question_pool: list[GameQuestion]
    started: datetime.datetime = pydantic.Field(default_factory=datetime.datetime.now)
    answers_url: str = "/answers"
    players: list[Player]


class GameSessionManager:
    def __init__(self, trivia_db: OpenTriviaDB) -> None:
        self.game_sessions: dict[uuid.UUID, GameSession] = {}
        self.db = trivia_db

    async def open_session(self, player_session_id: str) -> GameSession:
        questions = await self.db.get(amount=10)
        current_question = questions.pop(0)
        player = Player.new(player_session_id)

        session = GameSession(
            current_question=GameQuestion(
                text=current_question.text,
                correct_answer=current_question.correct_answer,
                incorrect_answers=current_question.incorrect_answers,
            ),
            question_pool=[
                GameQuestion(
                    text=question.text,
                    correct_answer=question.correct_answer,
                    incorrect_answers=question.incorrect_answers,
                )
                for question in questions
            ],
            players=[player],
        )

        self.game_sessions[session.id] = session

        return session

    async def get_session(self, session_id: uuid.UUID) -> GameSession:
        return self.game_sessions[session_id]

    async def join_session(
        self, session_id: uuid.UUID, player_session_id: str
    ) -> GameSession:
        session = await self.get_session(session_id)
        player = Player.new(player_session_id)
        session.players.append(player)
        return session

    async def next_question(self, session_id: uuid.UUID) -> GameSession:
        session = await self.get_session(session_id)
        session.current_question = session.question_pool.pop(0)
        return session


_Manager = None


async def get_game_session_manager(trivia_db: OpenTriviaDB) -> GameSessionManager:
    global _Manager
    if not _Manager:
        _Manager = GameSessionManager(trivia_db)

    return _Manager
