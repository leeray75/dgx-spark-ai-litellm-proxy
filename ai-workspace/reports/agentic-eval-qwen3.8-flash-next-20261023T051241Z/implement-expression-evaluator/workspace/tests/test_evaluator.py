import pytest

from calc.evaluator import evaluate


def test_simple():
    assert evaluate("1 + 2 * 3") == 7.0


def test_parentheses():
    assert evaluate("(1 + 2) * 3") == 9.0


def test_empty_is_error():
    with pytest.raises(ValueError):
        evaluate("")


# --------------------------------------------------------------------------
# numbers, whitespace, return type
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "expr, expected",
    [
        ("7", 7.0),
        ("0", 0.0),
        ("0.25", 0.25),
        ("12.5", 12.5),
        ("007", 7.0),
        ("3.0", 3.0),
    ],
)
def test_numbers(expr, expected):
    assert evaluate(expr) == expected


def test_returns_float():
    assert isinstance(evaluate("1 + 1"), float)
    assert isinstance(evaluate("4 / 2"), float)


def test_whitespace_between_tokens():
    assert evaluate("  1\t+\t2  ") == 3.0
    assert evaluate("( 1 + 2 ) * ( 3 - 1 )") == 6.0
    assert evaluate("2 ^ 3 ^ 2") == 512.0


@pytest.mark.parametrize("expr", [".5", "5.", "1.2.", "1e3", "0x10", "1_000", "+", "\u00a0 1"])
def test_malformed_numbers_and_unknown_characters(expr):
    with pytest.raises(ValueError):
        evaluate(expr)


# --------------------------------------------------------------------------
# operators and precedence
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "expr, expected",
    [
        ("1 + 2", 3.0),
        ("5 - 8", -3.0),
        ("3 * 4", 12.0),
        ("7 / 2", 3.5),
        ("2 + 3 * 4", 14.0),
        ("2 * 3 + 4", 10.0),
        ("10 - 4 - 3", 3.0),          # '-' left-associative
        ("100 / 5 / 2", 10.0),        # '/' left-associative
        ("2 + 3 * 4 - 6 / 3", 12.0),
        ("(2 + 3) * (4 - 6)", -10.0),
        ("((1 + 2) * (3 + 4)) / 7", 3.0),
    ],
)
def test_binary_operators_and_precedence(expr, expected):
    assert evaluate(expr) == pytest.approx(expected)


@pytest.mark.parametrize(
    "expr, expected",
    [
        ("2 ^ 3", 8.0),
        ("2 ^ 0", 1.0),
        ("9 ^ 0.5", 3.0),
        ("2 ^ -1", 0.5),              # exponent may be unary minus
        ("2 ^ 3 ^ 2", 512.0),         # '^' right-associative
        ("(2 ^ 3) ^ 2", 64.0),
        ("-2 ^ 2", -4.0),             # unary minus binds looser than '^'
        ("(-2) ^ 2", 4.0),
        ("2 * 3 ^ 2", 18.0),          # '^' binds tighter than '*'
        ("2 ^ 2 * 3", 12.0),
        ("-(2 ^ 2)", -4.0),
        ("1 - 2 ^ 2", -3.0),
    ],
)
def test_power(expr, expected):
    assert evaluate(expr) == pytest.approx(expected)


@pytest.mark.parametrize(
    "expr, expected",
    [
        ("-2", -2.0),
        ("--2", 2.0),
        ("---2", -2.0),
        ("- 2", -2.0),
        ("2 * -3", -6.0),
        ("-2 * -3", 6.0),
        ("-6 / -3", 2.0),
        ("2 - -3", 5.0),
        ("2 + -3", -1.0),
        ("-(3 + 4)", -7.0),
        ("2 ^ 3 * -2", -16.0),
    ],
)
def test_unary_minus(expr, expected):
    assert evaluate(expr) == pytest.approx(expected)


# --------------------------------------------------------------------------
# errors
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "expr",
    [
        "",
        "   ",
        "\t",
        "1 +",            # missing right operand
        "1 -",
        "1 *",
        "1 /",
        "1 ^",
        "+",              # '+' is not unary
        "* 3",
        "/ 3",
        "^ 3",
        "()",             # empty parentheses
        "(",
        ")",
        "(1 + 2",         # unclosed
        "1 + 2)",         # trailing token
        "((1 + 2)",
        "(1 + 2))",
        "1 2",            # two numbers in a row
        "1 + + 2",        # '+' is not unary
        "1 + * 2",
        "2 ** 3",
        "1 + 2 +",
        "3 % 2",          # unknown operator
        "1..2",
        "2 ^ ^ 3",
        "- -",
        "abc",
        "1 + abc",
        "pi",
        "1 + ",
    ],
)
def test_syntax_errors_raise_value_error(expr):
    with pytest.raises(ValueError):
        evaluate(expr)


def test_error_messages_mention_the_problem():
    for expr, needle in [
        ("", "empty"),
        ("1 +", "unexpected"),
        ("(1 + 2", "parenthes"),
        ("1 + 2)", "unexpected"),
        ("5.", "number"),
        (".5", "number"),
        ("3 % 2", "character"),
    ]:
        with pytest.raises(ValueError) as excinfo:
            evaluate(expr)
        assert needle in str(excinfo.value).lower()


def test_error_reports_position():
    with pytest.raises(ValueError) as excinfo:
        evaluate("1 + 2 # 3")
    assert "6" in str(excinfo.value)  # offset of the offending '#'


@pytest.mark.parametrize("expr", ["1 / 0", "1 / (2 - 2)", "0 / 0", "1 / 0.0", "5 / -0"])
def test_division_by_zero(expr):
    with pytest.raises(ZeroDivisionError):
        evaluate(expr)


def test_small_divisors_are_not_zero_division():
    assert evaluate("1 / 0.5") == 2.0
    assert evaluate("1 / 0.0000001") == pytest.approx(1e7)


def test_negative_base_with_fractional_exponent_is_error():
    with pytest.raises(ValueError):
        evaluate("(-8) ^ 0.5")


def test_negative_base_with_integral_exponent_is_fine():
    assert evaluate("(-2) ^ 3") == -8.0
    assert evaluate("(-2) ^ 2.0") == 4.0


def test_zero_to_negative_power_is_zero_division():
    with pytest.raises(ZeroDivisionError):
        evaluate("0 ^ -1")


def test_overflow_is_reported_as_value_error():
    with pytest.raises(ValueError):
        evaluate("10 ^ 400")


def test_non_string_input_is_type_error():
    with pytest.raises(TypeError):
        evaluate(1 + 2)  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# bigger expressions / stress
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "expr, expected",
    [
        ("1 + 2 * 3 - 4 / 2", 5.0),
        ("(((((1)))) )", 1.0),
        ("2 ^ 2 ^ 3", 256.0),
        ("-(-(-3))", -3.0),
        ("(1 + 2) * 3 ^ 2 - 10 / 5", 25.0),
        ("10 * (1 + 2 * (3 + 4) - 5) / 2", 50.0),
        ("2 ^ -2 + 3 ^ -1", 0.5833333333333334),
        ("-" + "0.5" + " ^ 2", -0.25),
    ],
)
def test_compound_expressions(expr, expected):
    assert evaluate(expr) == pytest.approx(expected)


def test_long_left_associative_chain():
    assert evaluate(" + ".join(["1"] * 100)) == 100.0
    assert evaluate("1" + " - 1" * 50) == -49.0


def test_moderately_nested_input_still_works():
    assert evaluate("(" * 20 + "1 + 1" + ")" * 20) == 2.0
    assert evaluate("-" * 21 + "1") == -1.0
    assert evaluate("-" * 20 + "1") == 1.0


@pytest.mark.parametrize(
    "expr",
    ["(" * 400 + "1" + ")" * 400, "-" * 400 + "1", "2" + " ^ 2" * 400],
)
def test_runaway_nesting_is_a_value_error_not_a_crash(expr):
    # Recursive descent must not blow the interpreter stack.
    with pytest.raises(ValueError):
        evaluate(expr)
