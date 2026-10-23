import pytest

from calc.evaluator import evaluate


@pytest.mark.parametrize("depth", [20, 40, 60, 80, 100, 120, 150, 200, 400])
def test_parens_depth(depth):
    print("PARENS", depth, evaluate("(" * depth + "1" + ")" * depth))


@pytest.mark.parametrize("depth", [20, 40, 60, 80, 100, 120, 150, 200, 400])
def test_unary_depth(depth):
    print("UNARY", depth, evaluate("-" * depth + "1"))


@pytest.mark.parametrize("depth", [20, 40, 60, 80, 100, 120, 150, 200, 400])
def test_power_depth(depth):
    print("POWER", depth, evaluate("1" + " ^ 1" * depth))
