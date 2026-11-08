import chess
import pytest


@pytest.fixture(autouse=True)
def training_wording():
    """Every test starts from the prompt wording our demos used; a live game in one test must not change the next."""
    from dreamchess import where

    where.PROMPT_STYLE, where.ROBOT_SIDE = "squares", chess.BLACK
    yield
    where.PROMPT_STYLE, where.ROBOT_SIDE = "squares", chess.BLACK
