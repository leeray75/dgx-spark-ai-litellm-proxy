"""Arithmetic expression evaluator.

Grammar (whitespace — spaces and tabs — is allowed between any two tokens)::

    expr    := term (('+' | '-') term)*          left-associative
    term    := unary (('*' | '/') unary)*        left-associative
    unary   := '-' unary | power
    power   := primary ('^' unary)?              so ^ is right-associative
    primary := NUMBER | '(' expr ')'
    NUMBER  := DIGITS ('.' DIGITS)?              e.g. 7, 0.25, 12.5 (not .5, 5., 1e3)

Consequences: ``-2^2 == -4``, ``2^-1 == 0.5``, ``2^3^2 == 512``, ``2*-3 == -6``, ``--2 == 2``.

``evaluate(expr)`` returns the value as a ``float``. It raises:

* ``ValueError`` (with a message saying what is wrong) for anything that does not match the
  grammar: empty input, unknown characters, missing operands, unbalanced parentheses,
  trailing tokens, malformed numbers;
* ``ZeroDivisionError`` for division by zero.
"""

import sys

__all__ = ["evaluate"]

_DIGITS = "0123456789"
_OPERATORS = "+-*/^"
_WHITESPACE = " \t"

# Token kinds.
_NUMBER = "number"
_OPERATOR = "operator"
_LPAREN = "lparen"
_RPAREN = "rparen"

# The parser below is recursive-descent, so pathologically nested input (``((((((...`` or
# ``-----...``) could exhaust the interpreter stack and die with a RecursionError instead of
# reporting a problem.  ``_MAX_DEPTH`` bounds how many grammar rules may be active at once; every
# level costs a couple of Python frames, so the budget stays well inside the interpreter's own
# limit (see also the RecursionError safety net in :func:`evaluate`).
_MAX_DEPTH = max(40, min(150, sys.getrecursionlimit() // 5))


class _Token:
    """A lexical token together with its offset in the source string."""

    __slots__ = ("kind", "text", "pos")

    def __init__(self, kind: str, text: str, pos: int) -> None:
        self.kind = kind
        self.text = text
        self.pos = pos

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"_Token({self.kind!r}, {self.text!r}, {self.pos})"


def _tokenize(expr: str) -> list:
    """Split ``expr`` into tokens, raising ``ValueError`` on anything unexpected."""
    tokens: list = []
    i, n = 0, len(expr)
    while i < n:
        char = expr[i]
        if char in _WHITESPACE:
            i += 1
            continue
        if char in _DIGITS:
            start = i
            while i < n and expr[i] in _DIGITS:
                i += 1
            if i < n and expr[i] == ".":
                i += 1  # tentatively consume the '.'
                if i >= n or expr[i] not in _DIGITS:
                    raise ValueError(
                        f"malformed number at position {start}: "
                        "expected at least one digit after '.'"
                    )
                while i < n and expr[i] in _DIGITS:
                    i += 1
            tokens.append(_Token(_NUMBER, expr[start:i], start))
            continue
        if char in _OPERATORS:
            tokens.append(_Token(_OPERATOR, char, i))
            i += 1
            continue
        if char == "(":
            tokens.append(_Token(_LPAREN, char, i))
            i += 1
            continue
        if char == ")":
            tokens.append(_Token(_RPAREN, char, i))
            i += 1
            continue
        if char == ".":
            raise ValueError(
                f"malformed number at position {i}: "
                "a number must have at least one digit before '.'"
            )
        raise ValueError(f"unexpected character {char!r} at position {i}")
    return tokens


class _Parser:
    """Recursive-descent parser over the token list produced by :func:`_tokenize`."""

    def __init__(self, tokens: list) -> None:
        self._tokens = tokens
        self._index = 0
        self._depth = 0

    # -- token helpers ---------------------------------------------------
    def _peek(self):
        """Return the next token without consuming it, or ``None`` at the end."""
        if self._index < len(self._tokens):
            return self._tokens[self._index]
        return None

    def _advance(self) -> _Token:
        token = self._tokens[self._index]
        self._index += 1
        return token

    @staticmethod
    def _is_operator(token, *symbols: str) -> bool:
        return token is not None and token.kind == _OPERATOR and token.text in symbols

    def _call(self, rule):
        """Run a grammar rule one level deeper, guarding against runaway recursion."""
        self._depth += 1
        if self._depth > _MAX_DEPTH:
            token = self._peek()
            where = f"at position {token.pos}" if token is not None else "at the end"
            raise ValueError(f"expression is nested too deeply ({where})")
        try:
            return rule()
        finally:
            self._depth -= 1

    # -- grammar rules ---------------------------------------------------
    def parse(self) -> float:
        if not self._tokens:
            raise ValueError("empty expression")
        value = self._expr()
        leftover = self._peek()
        if leftover is not None:
            raise ValueError(
                f"unexpected {leftover.text!r} at position {leftover.pos}: "
                "trailing input after a complete expression"
            )
        return float(value)

    def _expr(self) -> float:
        """expr := term (('+' | '-') term)*"""
        value = self._call(self._term)
        while True:
            token = self._peek()
            if not self._is_operator(token, "+", "-"):
                return value
            self._advance()
            rhs = self._call(self._term)
            value = value + rhs if token.text == "+" else value - rhs

    def _term(self) -> float:
        """term := unary (('*' | '/') unary)*"""
        value = self._call(self._unary)
        while True:
            token = self._peek()
            if not self._is_operator(token, "*", "/"):
                return value
            self._advance()
            rhs = self._call(self._unary)
            if token.text == "*":
                value = value * rhs
            else:
                if rhs == 0.0:
                    raise ZeroDivisionError("division by zero")
                value = value / rhs

    def _unary(self) -> float:
        """unary := '-' unary | power"""
        token = self._peek()
        if self._is_operator(token, "-"):
            self._advance()
            return -self._call(self._unary)
        return self._call(self._power)

    def _power(self) -> float:
        """power := primary ('^' unary)?  -- the operand is ``unary``, so ^ is right-associative."""
        base = self._call(self._primary)
        token = self._peek()
        if self._is_operator(token, "^"):
            self._advance()
            exponent = self._call(self._unary)
            return _power(base, exponent)
        return base

    def _primary(self) -> float:
        """primary := NUMBER | '(' expr ')'"""
        token = self._peek()
        if token is None:
            raise ValueError(
                "unexpected end of expression: expected a number, '(' or a unary '-'"
            )
        if token.kind == _NUMBER:
            self._advance()
            return float(token.text)
        if token.kind == _LPAREN:
            self._advance()
            value = self._call(self._expr)
            closing = self._peek()
            if closing is None:
                raise ValueError(
                    f"unbalanced parentheses: '(' at position {token.pos} is never closed"
                )
            if closing.kind != _RPAREN:
                raise ValueError(
                    f"expected ')' at position {closing.pos}, got {closing.text!r}"
                )
            self._advance()
            return value
        raise ValueError(f"unexpected {token.text!r} at position {token.pos}")


def _power(base: float, exponent: float) -> float:
    """``base ** exponent`` with messages that say what went wrong."""
    if base < 0.0 and not float(exponent).is_integer():
        raise ValueError(
            f"negative base {base:g} raised to the non-integer power {exponent:g} "
            "is not a real number"
        )
    try:
        return float(base ** exponent)
    except OverflowError:
        raise ValueError(
            f"the result of {base:g} ** {exponent:g} is too large to represent as a float"
        ) from None
    except ZeroDivisionError:
        raise ZeroDivisionError(
            f"{base:g} cannot be raised to the negative power {exponent:g}"
        ) from None


def evaluate(expr: str) -> float:
    """Evaluate an arithmetic expression and return its value as a ``float``."""
    if not isinstance(expr, str):
        raise TypeError(f"expression must be a str, not {type(expr).__name__}")
    try:
        return _Parser(_tokenize(expr)).parse()
    except RecursionError:  # safety net: a runaway expression is a bad expression, not a crash
        raise ValueError("expression is nested too deeply") from None
