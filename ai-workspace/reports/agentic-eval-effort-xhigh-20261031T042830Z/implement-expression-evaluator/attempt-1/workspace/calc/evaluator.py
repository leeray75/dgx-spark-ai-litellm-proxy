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

There is no nesting limit beyond Python's own: at least 100 levels of nested parentheses (and long
chains such as ``-`` repeated 100 times) must evaluate normally.
"""

import sys

__all__ = ["evaluate"]

_DIGITS = "0123456789"
_SPACES = " \t"
_OPERATORS = frozenset("+-*/^()")


class _Token:
    """A single lexical token: ``kind`` is ``"num"`` or ``"op"``."""

    __slots__ = ("kind", "value", "text", "pos")

    def __init__(self, kind, value, text, pos):
        self.kind = kind
        self.value = value
        self.text = text
        self.pos = pos

    def __repr__(self):  # pragma: no cover - debugging helper
        return f"_Token({self.kind!r}, {self.text!r}, pos={self.pos})"


def _tokenize(expr):
    """Split ``expr`` into tokens, raising ``ValueError`` for anything unrecognised."""
    tokens = []
    i, n = 0, len(expr)
    while i < n:
        ch = expr[i]
        if ch in _SPACES:
            i += 1
            continue
        if ch in _DIGITS:
            start = i
            while i < n and expr[i] in _DIGITS:
                i += 1
            if i < n and expr[i] == ".":
                i += 1
                if i >= n or expr[i] not in _DIGITS:
                    raise ValueError(
                        f"malformed number {expr[start:i]!r} at position {start}: "
                        f"missing digits after '.'"
                    )
                while i < n and expr[i] in _DIGITS:
                    i += 1
            text = expr[start:i]
            tokens.append(_Token("num", float(text), text, start))
            continue
        if ch == ".":
            raise ValueError(
                f"unexpected character '.' at position {i}: a number needs digits "
                f"before the decimal point (write 0.5, not .5)"
            )
        if ch in _OPERATORS:
            tokens.append(_Token("op", ch, ch, i))
            i += 1
            continue
        raise ValueError(f"unexpected character {ch!r} at position {i}")
    return tokens


class _Parser:
    """Recursive-descent parser mirroring the grammar in the module docstring."""

    def __init__(self, tokens):
        self._tokens = tokens
        self._index = 0

    # -- entry point ---------------------------------------------------------
    def parse(self):
        if not self._tokens:
            raise ValueError("empty expression")
        value = self._expr()
        leftover = self._peek()
        if leftover is not None:
            raise ValueError(
                f"unexpected {self._describe(leftover)} at position {leftover.pos}: "
                f"trailing tokens after a complete expression "
                f"(unbalanced parenthesis?)"
            )
        return value

    # -- helpers -------------------------------------------------------------
    def _peek(self):
        if self._index < len(self._tokens):
            return self._tokens[self._index]
        return None

    def _describe(self, token):
        if token.kind == "num":
            return f"number {token.text}"
        if token.value == ")":
            return "unbalanced ')'"
        if token.value == "(":
            return "'('"
        return f"operator {token.value!r}"

    # -- grammar rules -------------------------------------------------------
    def _expr(self):
        """expr := term (('+' | '-') term)*"""
        value = self._term()
        while True:
            token = self._peek()
            if token is None or token.kind != "op" or token.value not in "+-":
                return value
            self._index += 1
            rhs = self._term()
            value = value + rhs if token.value == "+" else value - rhs

    def _term(self):
        """term := unary (('*' | '/') unary)*"""
        value = self._unary()
        while True:
            token = self._peek()
            if token is None or token.kind != "op" or token.value not in "*/":
                return value
            self._index += 1
            rhs = self._unary()
            if token.value == "*":
                value = value * rhs
            else:
                try:
                    value = value / rhs
                except ZeroDivisionError:
                    raise ZeroDivisionError("division by zero") from None

    def _unary(self):
        """unary := '-' unary | power  (iterated instead of recursed: ``--2 == 2``)"""
        negatives = 0
        while True:
            token = self._peek()
            if token is None or token.kind != "op" or token.value != "-":
                break
            self._index += 1
            negatives += 1
        value = self._power()
        return -value if negatives % 2 else value

    def _power(self):
        """power := primary ('^' unary)?  — right-associative via the call to unary"""
        base = self._primary()
        token = self._peek()
        if token is not None and token.kind == "op" and token.value == "^":
            self._index += 1
            exponent = self._unary()
            try:
                result = base ** exponent
            except ZeroDivisionError:
                raise ZeroDivisionError("division by zero (0 raised to a negative power)") from None
            except OverflowError:
                raise ValueError(
                    f"overflow: {base!r} ** {exponent!r} is too large to represent"
                ) from None
            if isinstance(result, complex):
                raise ValueError(
                    f"complex result: {base!r} ** {exponent!r} is not a real number"
                )
            return float(result)
        return base

    def _primary(self):
        """primary := NUMBER | '(' expr ')'"""
        token = self._peek()
        if token is None:
            raise ValueError(
                "unexpected end of expression: expected a number, '(' or a unary '-'"
            )
        if token.kind == "num":
            self._index += 1
            return token.value
        if token.value == "(":
            self._index += 1
            value = self._expr()
            closer = self._peek()
            if closer is None:
                raise ValueError(
                    f"unbalanced parenthesis: missing ')' to match the '(' at "
                    f"position {token.pos}"
                )
            if closer.kind != "op" or closer.value != ")":
                raise ValueError(
                    f"expected ')' to close the '(' at position {token.pos} but found "
                    f"{self._describe(closer)} at position {closer.pos}"
                )
            self._index += 1
            return value
        raise ValueError(
            f"expected a number or '(' but found {self._describe(token)} at position {token.pos}"
        )


_MAX_RECURSION_LIMIT = 20_000  # keep the bump sane; deeper input raises RecursionError


def _required_recursion_limit(expr):
    """Rough upper bound on the interpreter stack depth needed for ``expr``.

    ``(`` and ``-`` nest recursively (a run of ``-`` is iterative, but a run of ``-`` nested
    inside parentheses is not), and so does ``^`` (right-associativity recurses through
    ``_power`` -> ``_unary``).
    """
    nesting = expr.count("(") + expr.count("-") + expr.count("^") + 4
    return min(8 * nesting + 200, _MAX_RECURSION_LIMIT)


def evaluate(expr: str) -> float:
    """Evaluate an arithmetic expression and return its value as a ``float``."""
    if not isinstance(expr, str):
        raise ValueError(f"expression must be a string, not {type(expr).__name__}")

    tokens = _tokenize(expr)

    needed = _required_recursion_limit(expr)
    old_limit = sys.getrecursionlimit()
    bumped = needed > old_limit
    if bumped:
        sys.setrecursionlimit(needed)
    try:
        value = _Parser(tokens).parse()
    finally:
        if bumped:
            sys.setrecursionlimit(old_limit)
    return float(value)
