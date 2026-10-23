import math

import pytest

from calc.evaluator import evaluate

CASES = [
    ("1 + 2 * 3", 7), ("(1 + 2) * 3", 9), ("10 - 4 - 3", 3), ("100 / 10 / 5", 2),
    ("2^3^2", 512), ("(2^3)^2", 64), ("-2^2", -4), ("(-2)^2", 4), ("2^-1", 0.5),
    ("2*-3", -6), ("--2", 2), ("-(-(3))", 3), ("2 ^ - - 2", 4), ("-3 - -3", 0),
    ("0.25 * 8", 2), ("12.5", 12.5), ("  1 +\t2 ", 3), ("7", 7), ("((((5))))", 5),
    ("1 - 2 * 3 + 4 / 2", -3), ("2 * 3 ^ 2", 18), ("-2 * -2 ^ 2", 8), ("9 / 3 * 3", 9),
    ("1.5 + 2.25", 3.75), ("2 ^ 0.5 ^ 2", 2 ** 0.25), ("10/4", 2.5),
]


@pytest.mark.parametrize("expr,expected", CASES)
def test_values(expr, expected):
    result = evaluate(expr)
    assert isinstance(result, float)
    assert math.isclose(result, expected, rel_tol=1e-12, abs_tol=1e-12), (expr, result)


@pytest.mark.parametrize("expr", [
    "", "   ", "2 +", "+ 2", "(1", "1)", ")(", "1 2", "1 + * 2", "2..3", ".5", "5.", "1e3",
    "abc", "3 $ 4", "()", "2 ^", "^2", "(1 + 2", "1 + (2 * 3))", "- ", "2 3 +", "4 // 2", "1,5",
])
def test_malformed(expr):
    with pytest.raises(ValueError):
        evaluate(expr)


def test_division_by_zero():
    with pytest.raises(ZeroDivisionError):
        evaluate("1 / 0")
    with pytest.raises(ZeroDivisionError):
        evaluate("1 / (2 - 2)")


def test_error_message_is_helpful():
    with pytest.raises(ValueError) as info:
        evaluate("1 + (2 * 3")
    assert str(info.value).strip()


def test_deep_nesting():
    assert evaluate("(" * 100 + "1" + ")" * 100) == 1.0
    assert evaluate("-" * 100 + "1") == 1.0


def test_no_eval_or_parsing_shortcuts():
    import io
    import tokenize
    import calc.evaluator as mod
    with open(mod.__file__) as f:
        toks = [t for t in tokenize.generate_tokens(io.StringIO(f.read()).readline)
                if t.type in (tokenize.NAME, tokenize.OP)]
    for prev, tok in zip([None] + toks, toks):
        if tok.type != tokenize.NAME:
            continue
        attribute = prev is not None and prev.string == "."
        if tok.string in ("eval", "exec", "compile") and not attribute:
            raise AssertionError(f"uses builtin {tok.string} (line {tok.start[0]})")
        if tok.string == "ast" and prev is not None and prev.string in ("import", "from"):
            raise AssertionError(f"imports ast (line {tok.start[0]})")
