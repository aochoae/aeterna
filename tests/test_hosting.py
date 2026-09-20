# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Alberto Ochoa

from __future__ import annotations

import asyncio

import pytest
from aeterna.runtime import ApplicationBuilder, exit_code, run


def test_exit_code_none_returns_zero() -> None:
    assert exit_code(None) == 0


def test_exit_code_keyboard_interrupt_returns_130() -> None:
    assert exit_code(KeyboardInterrupt()) == 130


def test_exit_code_cancelled_error_returns_130() -> None:
    assert exit_code(asyncio.CancelledError()) == 130


def test_exit_code_generic_error_returns_one() -> None:
    assert exit_code(RuntimeError("boom")) == 1


def test_run_builds_and_executes_application() -> None:
    result = run(ApplicationBuilder(), lambda _: "hello")
    assert result == "hello"


def test_run_without_main_completes_cleanly() -> None:
    result = run(ApplicationBuilder())
    assert result is None


def test_run_handles_platforms_without_signal_handlers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Windows event loops raise NotImplementedError from add_signal_handler."""

    def raise_not_implemented(*args: object, **kwargs: object) -> None:
        raise NotImplementedError

    loop = asyncio.new_event_loop()
    loop_type = type(loop)
    loop.close()
    monkeypatch.setattr(loop_type, "add_signal_handler", raise_not_implemented)

    # Driven through the public run(), so the loop that asyncio.run creates is the
    # one exercised rather than a hand-built call to a private coroutine.
    assert run(ApplicationBuilder(), lambda _: "ok") == "ok"
