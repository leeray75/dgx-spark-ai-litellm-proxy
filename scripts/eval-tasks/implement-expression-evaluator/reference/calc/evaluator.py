"""Arithmetic expression evaluator (reference solution, recursive descent)."""
import re

_TOKEN = re.compile(r"\s*(?:(\d+(?:\.\d+)?)(?![\d.])|([-+*/^()]))")


def _tokenize(expr):
    tokens, pos = [], 0
    while pos < len(expr):
        if expr[pos] in " \t":
            pos += 1
            continue
        m = _TOKEN.match(expr, pos)
        if not m:
            raise ValueError(f"unexpected character {expr[pos]!r} at position {pos}")
        tokens.append(("num", float(m.group(1))) if m.group(1) else ("op", m.group(2)))
        pos = m.end()
    return tokens


def evaluate(expr: str) -> float:
    tokens = _tokenize(expr)
    pos = 0

    def peek():
        return tokens[pos] if pos < len(tokens) else (None, None)

    def take(op):
        nonlocal pos
        if peek() == ("op", op):
            pos += 1
            return True
        return False

    def expr_():
        value = term()
        while True:
            if take("+"):
                value += term()
            elif take("-"):
                value -= term()
            else:
                return value

    def term():
        value = unary()
        while True:
            if take("*"):
                value *= unary()
            elif take("/"):
                value /= unary()
            else:
                return value

    def unary():
        if take("-"):
            return -unary()
        return power()

    def power():
        base = primary()
        if take("^"):
            return base ** unary()
        return base

    def primary():
        nonlocal pos
        kind, value = peek()
        if kind == "num":
            pos += 1
            return value
        if take("("):
            inner = expr_()
            if not take(")"):
                raise ValueError("missing closing parenthesis")
            return inner
        raise ValueError("expected a number or '('" + ("" if kind else " but the expression ended"))

    import sys
    sys.setrecursionlimit(max(sys.getrecursionlimit(), 10000))
    result = expr_()
    if pos != len(tokens):
        raise ValueError(f"unexpected token {tokens[pos][1]!r}")
    return float(result)
