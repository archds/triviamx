import datetime
import random
import pydantic
import utils

class GameAnswerEntry(pydantic.BaseModel):
    text: str
    button_class: str


class GameQuestion(pydantic.BaseModel):
    text: str
    correct_answer: str
    incorrect_answers: list[str]
    guess: str | None = None

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
