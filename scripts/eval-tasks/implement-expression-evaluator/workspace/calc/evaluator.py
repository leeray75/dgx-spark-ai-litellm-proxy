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


def evaluate(expr: str) -> float:
    raise NotImplementedError
