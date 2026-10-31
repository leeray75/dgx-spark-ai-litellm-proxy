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


class _Tokenizer:
    """Splits the input into NUMBER / operator / parenthesis tokens.

    Only spaces and tabs are treated as whitespace; any other unexpected character
    (including newlines) is reported as an unknown character.
    """

    _SINGLE = set("+-*/^().")

    def __init__(self, text: str):
        self._text = text
        self._i = 0
        self.peek: str | None = None  # next token, or None at end of input
        self._advance()

    def _advance(self) -> None:
        text, n = self._text, len(self._text)
        i = self._i
        while i < n and text[i] in " \t":
            i += 1
        self._i = i
        if i >= n:
            self.peek = None
        elif text[i].isdigit():
            j = i
            while j < n and text[j].isdigit():
                j += 1
            if j < n and text[j] == ".":
                j += 1
                if j >= n or not text[j].isdigit():
                    raise ValueError(
                        f"malformed number at position {i}: digits are required after '.'"
                    )
                while j < n and text[j].isdigit():
                    j += 1
            self.peek = text[i:j]
            self._i = j
        elif text[i] in self._SINGLE:
            self.peek = text[i]
            self._i = i + 1
        else:
            raise ValueError(f"unknown character {text[i]!r} at position {i}")

    def position(self) -> int:
        """Character offset of the current (unconsumed) token."""
        return self._i

    def next(self) -> str:
        """Consume and return the current token; raises at end of input."""
        if self.peek is None:
            raise ValueError(f"unexpected end of input at position {len(self._text)}")
        token = self.peek
        self._advance()
        return token

    def expect(self, token: str) -> None:
        if self.peek != token:
            if self.peek is None:
                raise ValueError(
                    f"expected {token!r} but reached end of input at position {len(self._text)}"
                )
            raise ValueError(
                f"expected {token!r} but found {self.peek!r} at position {self.position()}"
            )
        self._advance()


def _apply_power(base: float, exponent: float) -> float:
    try:
        value = base ** exponent
    except ZeroDivisionError:
        raise ZeroDivisionError("0 cannot be raised to a negative power") from None
    except OverflowError:
        raise ValueError("numeric overflow while evaluating '^'") from None
    except ValueError:
        raise ValueError(
            f"negative base {base} raised to fractional power {exponent} is not a real number"
        ) from None
    if isinstance(value, complex):
        raise ValueError(
            f"negative base {base} raised to fractional power {exponent} is not a real number"
        ) from None
    return float(value)


class _Parser:
    """Recursive descent parser following the module docstring's grammar."""

    def __init__(self, text: str):
        self._tok = _Tokenizer(text)

    def parse(self) -> float:
        value = self._expr()
        if self._tok.peek is not None:
            raise ValueError(f"unexpected trailing token {self._tok.peek!r}")
        return value

    def _expr(self) -> float:
        value = self._term()
        while self._tok.peek in ("+", "-"):
            op = self._tok.next()
            rhs = self._term()
            value = value + rhs if op == "+" else value - rhs
        return value

    def _term(self) -> float:
        value = self._unary()
        while self._tok.peek in ("*", "/"):
            op = self._tok.next()
            rhs = self._unary()
            if op == "*":
                value = value * rhs
            else:
                if rhs == 0.0:
                    raise ZeroDivisionError("division by zero")
                value = value / rhs
        return value

    def _unary(self) -> float:
        if self._tok.peek == "-":
            self._tok.next()
            return -self._unary()
        return self._power()

    def _power(self) -> float:
        base = self._primary()
        if self._tok.peek == "^":
            self._tok.next()
            return _apply_power(base, self._unary())  # right-associative
        return base

    def _primary(self) -> float:
        token = self._tok.peek
        if token is None:
            raise ValueError(
                f"unexpected end of input at position {self._tok.position()}; "
                "expected a number or '('"
            )
        if token == "(":
            self._tok.next()
            value = self._expr()
            if self._tok.peek is None:
                raise ValueError("unbalanced parentheses: missing ')'")
            self._tok.expect(")")
            return value
        if token[0].isdigit():
            self._tok.next()
            return float(token)
        raise ValueError(f"expected a number or '(' but found {token!r}")


def evaluate(expr: str) -> float:
    if not isinstance(expr, str):
        raise TypeError(f"expected a string expression, got {type(expr).__name__}")
    return _Parser(expr).parse()
