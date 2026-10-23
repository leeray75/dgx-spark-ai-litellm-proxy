"""Smoke tests for the command-line front end (``python -m calc.cli``)."""
import runpy
import sys

import pytest


def _run(monkeypatch, capsys, *argv):
    monkeypatch.setattr(sys, "argv", ["calc.cli", *argv])
    return runpy.run_module("calc.cli", run_name="__main__")


def test_prints_the_result(monkeypatch, capsys):
    _run(monkeypatch, capsys, "1 + 2 * 3")
    assert capsys.readouterr().out == "7.0\n"


def test_joins_argv(monkeypatch, capsys):
    _run(monkeypatch, capsys, "(1", "+", "2)", "*", "3")
    assert capsys.readouterr().out == "9.0\n"


def test_reports_errors_on_stderr_and_exits(monkeypatch, capsys):
    with pytest.raises(SystemExit) as excinfo:
        _run(monkeypatch, capsys, "1 / 0")
    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("error:")
    assert "division by zero" in captured.err


def test_reports_syntax_errors(monkeypatch, capsys):
    with pytest.raises(SystemExit) as excinfo:
        _run(monkeypatch, capsys, "1 +")
    assert excinfo.value.code == 1
    assert "error:" in capsys.readouterr().err
