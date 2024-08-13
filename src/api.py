from typing import Literal

import aiohttp
import pydantic


class OpenTriviaQuestion(pydantic.BaseModel):
    type: str
    category: str
    question: str
    correct_answer: str
    incorrect_answers: list[str]


class OpenTriviaResponse(pydantic.BaseModel):
    response_code: int
    results: list[OpenTriviaQuestion]


class OpenTriviaDB:
    encoding: Literal["default", "legacy", "url", "base64"] = "default"
    diff_map = {"easy": 0, "medium": 1, "hard": 2}

    def __init__(
        self,
        base_url: str,
        api_path: str,
        encoding: Literal["default", "legacy", "url", "base64"] = "default",
    ) -> None:
        self.encoding = encoding
        self.base_url = base_url
        self.api_path = api_path

        self.session = aiohttp.ClientSession(base_url=self.base_url)

    async def get(
        self,
        amount: int,
        category: int | None = None,
        difficulty: Literal["easy", "medium", "hard"] | None = None,
    ) -> list[OpenTriviaQuestion]:
        params = {"amount": amount}

        if category is not None:
            params["category"] = category

        if difficulty is not None:
            params["difficulty"] = self.diff_map[difficulty]

        response = await self.session.get(self.api_path, params=params)
        response.raise_for_status()

        raw = await response.read()
        body = OpenTriviaResponse.model_validate_json(raw)

        return body.results


_DB = OpenTriviaDB(
    base_url="https://opentdb.com",
    api_path="/api.php",
    encoding="default",
)


async def get_open_trivia_db() -> OpenTriviaDB:
    return _DB
