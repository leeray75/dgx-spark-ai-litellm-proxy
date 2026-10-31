import pytest

from calc.evaluator import evaluate


def test_simple():
    assert evaluate("1 + 2 * 3") == 7.0


def test_parentheses():
    assert evaluate("(1 + 2) * 3") == 9.0


def test_empty_is_error():
    with pytest.raises(ValueError):
        evaluate("")


# --- return type -------------------------------------------------------------


def test_result_is_a_float():
    result = evaluate("1 + 1")
    assert isinstance(result, float)
    assert result == 2.0


def test_result_is_float_even_for_exact_integers():
    assert isinstance(evaluate("10 / 2"), float)


# --- numbers -----------------------------------------------------------------


@pytest.mark.parametrize(
    "expr, expected",
    [
        ("0", 0.0),
        ("7", 7.0),
        ("42", 42.0),
        ("007", 7.0),
        ("0.25", 0.25),
        ("12.5", 12.5),
        ("3.0", 3.0),
        ("123456789", 123456789.0),
    ],
)
def test_numbers(expr, expected):
    assert evaluate(expr) == expected


@pytest.mark.parametrize("expr", [".5", "5.", "1..2", "1.2.3", "1e3", "1E3", "0x10", "1_000"])
def test_malformed_numbers_are_errors(expr):
    with pytest.raises(ValueError):
        evaluate(expr)


# --- whitespace --------------------------------------------------------------


@pytest.mark.parametrize(
    "expr, expected",
    [
        ("1+2*3", 7.0),
        ("  1  +  2  ", 3.0),
        ("( 1 + 2 ) * 3", 9.0),
        ("\t4\t", 4.0),
        ("2 ^ 3", 8.0),
        ("- 5", -5.0),
        ("(  ( 1 ) )", 1.0),
    ],
)
def test_whitespace_between_tokens(expr, expected):
    assert evaluate(expr) == expected


@pytest.mark.parametrize("expr", ["   ", "\t", "\t \n"])
def test_whitespace_only_is_error(expr):
    with pytest.raises(ValueError):
        evaluate(expr)


# --- precedence and associativity -------------------------------------------


@pytest.mark.parametrize(
    "expr, expected",
    [
        ("1 + 2 * 3", 7.0),
        ("(1 + 2) * 3", 9.0),
        ("2 * 3 + 4", 10.0),
        ("2 + 3 * 4 - 6 / 2", 11.0),
        ("100 / 10 / 2", 5.0),      # / is left-associative
        ("100 / (10 / 2)", 20.0),
        ("2 - 3 - 4", -5.0),        # - is left-associative
        ("2 - (3 - 4)", 3.0),
        ("8 / 2 * 4", 16.0),        # * and / share a level, left to right
        ("2 ^ 3 * 2", 16.0),        # ^ binds tighter than *
        ("2 * 3 ^ 2", 18.0),
        ("1 + 2 ^ 3", 9.0),
    ],
)
def test_precedence_and_associativity(expr, expected):
    assert evaluate(expr) == expected


# --- power -------------------------------------------------------------------


@pytest.mark.parametrize(
    "expr, expected",
    [
        ("2 ^ 3", 8.0),
        ("2 ^ 0", 1.0),
        ("2 ^ 0.5", 2 ** 0.5),
        ("2 ^ -1", 0.5),
        ("2 ^ 3 ^ 2", 512.0),       # right-associative
        ("(2 ^ 3) ^ 2", 64.0),
        ("2 ^ - 1", 0.5),
        ("4 ^ 0.5", 2.0),
        ("10 ^ -2", 0.01),
        ("1.5 ^ 2", 2.25),
    ],
)
def test_power(expr, expected):
    assert evaluate(expr) == expected


def test_unary_minus_binds_looser_than_power():
    assert evaluate("-2^2") == -4.0
    assert evaluate("(-2)^2") == 4.0


def test_power_of_parenthesised_negative():
    assert evaluate("(-3) ^ 3") == -27.0


def test_negative_base_with_fractional_exponent_is_an_error():
    with pytest.raises(ValueError):
        evaluate("(-2) ^ 0.5")


# --- unary minus -------------------------------------------------------------


@pytest.mark.parametrize(
    "expr, expected",
    [
        ("-1", -1.0),
        ("--2", 2.0),
        ("---2", -2.0),
        ("- - 2", 2.0),
        ("2 * -3", -6.0),
        ("2 - -3", 5.0),
        ("2 + -3", -1.0),
        ("-2 * -3", 6.0),
        ("-(2 + 3)", -5.0),
        ("-0.5 + 1", 0.5),
        ("6 / -3", -2.0),
        ("-2 ^ 2 ^ 2", -16.0),
    ],
)
def test_unary_minus(expr, expected):
    assert evaluate(expr) == expected


def test_many_unary_minuses():
    assert evaluate("-" * 100 + "1") == 1.0
    assert evaluate("-" * 101 + "1") == -1.0


# --- parentheses -------------------------------------------------------------


@pytest.mark.parametrize(
    "expr, expected",
    [
        ("((((1 + 2)))) * 3", 9.0),
        ("(1 + 2) * (3 + 4)", 21.0),
        ("((2))", 2.0),
        ("(1 + (2 * (3 + (4 - 1))))", 13.0),
    ],
)
def test_nested_parentheses(expr, expected):
    assert evaluate(expr) == expected


def test_deep_parentheses_without_recursion_errors():
    depth = 100
    assert evaluate("(" * depth + "7" + ")" * depth) == 7.0
    depth = 300
    assert evaluate("(" * depth + "-1 + 1" + ")" * depth) == 0.0


def test_recursion_limit_is_restored():
    import sys

    before = sys.getrecursionlimit()
    evaluate("(" * 200 + "1" + ")" * 200)
    assert sys.getrecursionlimit() == before
    with pytest.raises(ValueError):
        evaluate("(" * 200 + "1")
    assert sys.getrecursionlimit() == before


# --- errors ------------------------------------------------------------------


@pytest.mark.parametrize(
    "expr",
    [
        "",                     # empty
        "1 +",                  # missing right operand
        "1 -",
        "1 *",
        "1 /",
        "1 ^",
        "+",                    # operator with no operand
        "*",
        "-",
        "* 3",                  # missing left operand
        "*3",
        "/ 3",
        "^ 3",
        "1 + * 2",              # two operators in a row
        "1 ** 2",
        "1 +",
        "()",                   # empty parentheses
        "(1 + )",
        "( * 2 )",
        "1 2",                  # trailing tokens
        "1 2 + 3",
        "2 (3)",                # missing operator
        "(1 + 2))",             # unbalanced parentheses
        "((1 + 2)",
        "(",
        ")",
        "((",
        "1 + (2 * 3))",
        "1 + 2)",
        "3 @ 4",                # unknown character
        "1 $ 2",
        "a",
        "1 + b",
        "2 & 3",
        "1,5",
        "1 +\n2",               # newline is not whitespace in this grammar
        "½ + 1",
    ],
)
def test_syntax_errors_raise_value_error(expr):
    with pytest.raises(ValueError):
        evaluate(expr)


@pytest.mark.parametrize(
    "expr, message_part",
    [
        ("", "empty"),
        ("3 @ 4", "@"),
        ("1 2", "2"),
        ("(1", ")"),
        ("1)", ")"),
        ("1 +", "end"),
    ],
)
def test_error_messages_are_informative(expr, message_part):
    with pytest.raises(ValueError) as excinfo:
        evaluate(expr)
    assert message_part in str(excinfo.value)


def test_value_error_is_not_a_subclass_confusion():
    with pytest.raises(ValueError):
        evaluate("nope")


# --- division ----------------------------------------------------------------


@pytest.mark.parametrize("expr", ["1 / 0", "0 / 0", "1 / (2 - 2)", "1 / 0.0", "1 + 5 / (3 - 3)"])
def test_division_by_zero(expr):
    with pytest.raises(ZeroDivisionError):
        evaluate(expr)


def test_division_by_zero_is_not_a_value_error():
    # A caller catching only ValueError must not swallow division by zero.
    with pytest.raises(ZeroDivisionError):
        evaluate("1 / 0")
    try:
        evaluate("1 / 0")
    except ZeroDivisionError:
        pass
    except ValueError:  # pragma: no cover - would be a bug
        pytest.fail("division by zero must raise ZeroDivisionError, not ValueError")


def test_division_produces_fraction():
    assert evaluate("1 / 3") == pytest.approx(0.3333333333333333)
    assert evaluate("7 / 2") == 3.5


def test_zero_to_a_negative_power_is_division_by_zero():
    with pytest.raises(ZeroDivisionError):
        evaluate("0 ^ -1")


# --- larger expressions ------------------------------------------------------


@pytest.mark.parametrize(
    "expr, expected",
    [
        ("2 + 3 * 4 - 6 / 2 + (1 + 1) ^ 3", 19.0),
        ("-(3 + 4) * 2 ^ 2 / (1 + 3)", -7.0),
        ("10 - 2 * 3 ^ 2", -8.0),
        ("(1 + 2 * 3 - 4) ^ 2 / 4", 2.25),
        ("100 / (2 + 3) / (7 - 5)", 10.0),
        ("-1 - -1 - -1", 1.0),
    ],
)
def test_larger_expressions(expr, expected):
    assert evaluate(expr) == pytest.approx(expected)


def test_matches_python_semantics_for_long_random_expression():
    expr = "3 * (2 + 5) ^ 2 - 4 / 2 + -6 * 1.5"
    assert evaluate(expr) == pytest.approx(3 * (2 + 5) ** 2 - 4 / 2 + -6 * 1.5)


def test_long_operator_chains():
    assert evaluate("1" + "+1" * 20000) == 20001.0
    assert evaluate("1" + "-1" * 20000) == -19999.0
    assert evaluate("2" + "*2" * 100) == 2.0 ** 101


def test_long_right_associative_power_chain():
    assert evaluate("1^" * 1000 + "1") == 1.0


def test_overflow_is_a_value_error():
    with pytest.raises(ValueError):
        evaluate("10 ^ 400")


def test_minuses_nested_in_parentheses():
    assert evaluate("(" * 100 + "-" * 100 + "1" + ")" * 100) == 1.0
    assert evaluate("(" * 100 + "-" * 101 + "1" + ")" * 100) == -1.0


# --- input validation --------------------------------------------------------


@pytest.mark.parametrize("expr", [None, 3, 1.5, ["1 + 1"], object(), b"1 + 1"])
def test_non_string_input_is_a_value_error(expr):
    with pytest.raises(ValueError):
        evaluate(expr)


# --- the evaluator must not use dynamic evaluation --------------------------


def test_no_dynamic_evaluation_primitives():
    import inspect

    from calc import evaluator

    source = inspect.getsource(evaluator)
    for forbidden in ("eval(", "exec(", "compile(", "import ast", "from ast"):
        assert forbidden not in source, f"evaluator must not use {forbidden}"
