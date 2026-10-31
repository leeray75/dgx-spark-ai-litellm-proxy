import pytest

from calc.evaluator import evaluate


def test_simple():
    assert evaluate("1 + 2 * 3") == 7.0


def test_parentheses():
    assert evaluate("(1 + 2) * 3") == 9.0


def test_empty_is_error():
    with pytest.raises(ValueError):
        evaluate("")


# --- basics ---------------------------------------------------------------

@pytest.mark.parametrize(
    "expr, expected",
    [
        ("7", 7.0),
        ("0.25", 0.25),
        ("12.5", 12.5),
        ("1 + 2", 3.0),
        ("5 - 8", -3.0),
        ("3 * 4", 12.0),
        ("10 / 4", 2.5),
        ("2 / 8", 0.25),
    ],
)
def test_atoms_and_binary_ops(expr, expected):
    assert evaluate(expr) == expected


def test_returns_float():
    value = evaluate("1 + 1")
    assert isinstance(value, float)
    assert value == 2.0


# --- precedence and associativity ------------------------------------------

@pytest.mark.parametrize(
    "expr, expected",
    [
        ("2 + 3 * 4", 14.0),          # * binds tighter than +
        ("2 * 3 + 4", 10.0),
        ("10 - 2 - 3", 5.0),          # - is left-associative
        ("100 / 10 / 2", 5.0),        # / is left-associative
        ("2 - 3 * 4 + 5", -5.0),
        ("(2 + 3) * (4 - 1)", 15.0),
        ("2 ^ 3 ^ 2", 512.0),         # ^ is right-associative
        ("(2 ^ 3) ^ 2", 64.0),
        ("2 ^ 2 ^ 3", 256.0),
        ("3 * 2 ^ 2", 12.0),          # ^ binds tighter than *
        ("1 + 2 ^ 3", 9.0),
    ],
)
def test_precedence_and_associativity(expr, expected):
    assert evaluate(expr) == expected


# --- unary minus and powers --------------------------------------------------

@pytest.mark.parametrize(
    "expr, expected",
    [
        ("-2^2", -4.0),               # unary minus applies after ^
        ("2^-1", 0.5),                # exponent may be unary-negated
        ("2*-3", -6.0),
        ("--2", 2.0),
        ("---2", -2.0),
        ("-(3)", -3.0),
        ("(-3)^2", 9.0),
    ],
)
def test_unary(expr, expected):
    assert evaluate(expr) == expected


def test_minus_chain():
    assert evaluate("-" * 100 + "1") == 1.0
    assert evaluate("-" * 101 + "1") == -1.0


# --- whitespace ---------------------------------------------------------------

@pytest.mark.parametrize(
    "expr, expected",
    [
        ("  1+2  ", 3.0),
        ("\t1\t+\t2\t", 3.0),
        (" ( 1 + 2 ) * 3 ", 9.0),
        ("2 ^ - 1", 0.5),
    ],
)
def test_whitespace_between_tokens(expr, expected):
    assert evaluate(expr) == expected


# --- nesting -------------------------------------------------------------------

def test_nested_parentheses_100_levels():
    assert evaluate("(" * 100 + "1 + 1" + ")" * 100) == 2.0


def test_deeply_nested_mixed():
    assert evaluate("2 * (" + "(" * 49 + "3" + ")" * 49 + ")") == 6.0


# --- errors ----------------------------------------------------------------------

@pytest.mark.parametrize(
    "expr",
    [
        "",                    # empty
        "   ",                 # whitespace only
        "\n",                  # newlines are not whitespace here
        "1e3",                 # no exponent notation
        ".5",                  # must start with a digit
        "5.",                  # must end with a digit
        "1..2",
        "1.2.3",
        "2 $ 3",               # unknown character
        "a + 1",               # unknown character
        "1 +",                 # missing right operand
        "* 3",                 # missing left operand
        "1 * + ",
        "(1 + 2",              # unclosed parenthesis
        "1 + 2)",              # trailing token
        "1 2",                 # trailing token
        "()",                  # empty parens
        "(+1)",                # '+' is not a unary operator
        "1 + (2 * )",
        "2 ^",                 # missing exponent
        "1,,",
    ],
)
def test_invalid_raises_value_error(expr):
    with pytest.raises(ValueError):
        evaluate(expr)


@pytest.mark.parametrize(
    "expr",
    ["1 / 0", "1 / (3 - 3)", "1.5 / 0.0", "(1 + 1) / (2 - 2)"],
)
def test_division_by_zero(expr):
    with pytest.raises(ZeroDivisionError):
        evaluate(expr)


def test_zero_to_negative_power():
    with pytest.raises(ZeroDivisionError):
        evaluate("0^-1")


def test_negative_base_fractional_power_is_error():
    with pytest.raises(ValueError):
        evaluate("(-8)^(1/2)")


def test_error_messages_mention_problem():
    with pytest.raises(ValueError, match="parenthes"):
        evaluate("(1 + 2")
    with pytest.raises(ValueError, match="unknown character"):
        evaluate("2 $ 3")
    with pytest.raises(ValueError, match="malformed number"):
        evaluate("5.")
