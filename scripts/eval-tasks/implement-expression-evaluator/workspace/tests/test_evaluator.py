import pytest

from calc.evaluator import evaluate


def test_simple():
    assert evaluate("1 + 2 * 3") == 7.0


def test_parentheses():
    assert evaluate("(1 + 2) * 3") == 9.0


def test_empty_is_error():
    with pytest.raises(ValueError):
        evaluate("")
