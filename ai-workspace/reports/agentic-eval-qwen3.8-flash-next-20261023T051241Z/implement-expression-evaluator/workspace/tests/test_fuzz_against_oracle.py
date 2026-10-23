"""Cross-check ``evaluate`` against an independently written shunting-yard oracle.

Random token soup is generated, fed to both implementations and compared.  Anything the oracle
cannot judge (it rejects a different set of malformed strings) is skipped; error handling itself
is covered by the table-driven cases in ``test_evaluator.py``.
"""
import random

import pytest

from calc.evaluator import evaluate

PREC = {"+": 1, "-": 1, "*": 2, "/": 2, "^": 3, "u": 3}
RIGHT = {"^", "u"}  # neither pops an operand of equal precedence


def _tokens(s):
    out, i = [], 0
    while i < len(s):
        c = s[i]
        if c.isspace():
            i += 1
        elif c.isdigit():
            j = i
            while j < len(s) and s[j].isdigit():
                j += 1
            if j < len(s) and s[j] == ".":
                j += 1
                if j >= len(s) or not s[j].isdigit():
                    raise ValueError("malformed number")  # '5.'
                while j < len(s) and s[j].isdigit():
                    j += 1
                if j < len(s) and s[j] == ".":
                    raise ValueError("malformed number")  # '1.2.3'
            out.append(("num", float(s[i:j])))
            i = j
        elif c == ".":
            raise ValueError("malformed number")  # '.5'
        elif c in "+-*/^()":
            out.append(("op", c))
            i += 1
        else:
            raise ValueError(f"bad character {c!r}")
    return out


def oracle(s):
    """Shunting-yard evaluation; raises on anything it cannot parse."""
    out, ops, prev = [], [], None
    for kind, val in _tokens(s):
        if kind == "num":
            if prev == "num":
                raise ValueError("two numbers in a row")
            out.append(val)
        elif val == "-" and prev in (None, "op"):
            val = "u"  # unary minus: same precedence as ^ but right-associative
            ops.append(val)
        elif val == "(":
            ops.append(val)
        elif val == ")":
            while ops and ops[-1] != "(":
                out.append(ops.pop())
            if not ops:
                raise ValueError("unbalanced parentheses")
            ops.pop()  # discard the '('
            if prev != "num":
                raise ValueError("empty parentheses")
        else:
            while ops and ops[-1] != "(" and _should_pop(ops[-1], val):
                out.append(ops.pop())
            ops.append(val)
        prev = "num" if kind == "num" else "op"
    while ops:
        top = ops.pop()
        if top in ("(", ")"):
            raise ValueError("unbalanced parentheses")
        out.append(top)

    stack = []
    for item in out:
        if isinstance(item, float):
            stack.append(item)
        elif item == "u":
            if not stack:
                raise ValueError("missing operand")
            stack.append(-stack.pop())
        else:
            if len(stack) < 2:
                raise ValueError("missing operand")
            b, a = stack.pop(), stack.pop()
            if item == "+":
                stack.append(a + b)
            elif item == "-":
                stack.append(a - b)
            elif item == "*":
                stack.append(a * b)
            elif item == "/":
                stack.append(a / b)  # ZeroDivisionError propagates
            else:
                result = a ** b
                if isinstance(result, complex):
                    raise ValueError("no real value")
                stack.append(float(result))
    if len(stack) != 1:
        raise ValueError("malformed expression")
    return stack[0]


def _should_pop(top, cur):
    if PREC[top] > PREC[cur]:
        return True
    return PREC[top] == PREC[cur] and cur not in RIGHT


ALPHABET = ["0", "1", "2", "3", "0.5", "2.5", "+", "-", "*", "/", "^", "(", ")"]


@pytest.mark.parametrize("seed", range(400))
def test_matches_oracle(seed):
    expr = _expression(seed)
    try:
        expected = oracle(expr)
    except ZeroDivisionError:
        with pytest.raises((ZeroDivisionError, ValueError)):
            evaluate(expr)
        return
    except (ValueError, SyntaxError, IndexError, RecursionError, OverflowError, TypeError):
        return  # oracle disagrees about validity of this shape; skip it
    assert evaluate(expr) == pytest.approx(expected), expr


@pytest.mark.parametrize("seed", range(400))
def test_rejects_what_the_oracle_rejects(seed):
    """The two lexers agree on the generated alphabet, so validity must agree too."""
    expr = _expression(seed)
    try:
        oracle(expr)
    except ZeroDivisionError:
        with pytest.raises((ZeroDivisionError, ValueError)):
            evaluate(expr)
    except (ValueError, SyntaxError, IndexError, RecursionError, OverflowError, TypeError):
        with pytest.raises(ValueError):
            evaluate(expr)
    else:
        evaluate(expr)  # must not raise


def _expression(seed):
    rng = random.Random(seed)
    parts = [rng.choice(ALPHABET) for _ in range(rng.randint(1, 9))]
    # sprinkle in optional whitespace, including around numbers (never inside one)
    return "".join(
        p if rng.random() < 0.6 else rng.choice([" ", "\t", " ", "  "]) + p + " " for p in parts
    )
