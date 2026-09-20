# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Alberto Ochoa

"""Framework-owned standalone hosting."""

from __future__ import annotations

import asyncio
import signal

from .application import ApplicationBuilder, ApplicationMain


def run[T](builder: ApplicationBuilder, main: ApplicationMain[T] | None = None) -> T | None:
    """Build and run an application with a framework-owned event loop.

    :param builder: Mutable application composition to build before running.
    :param main: Optional sync or async callback to execute while the application is running.
    :return: The result, or `None` when unavailable.
    :rtype: T | None
    """
    return asyncio.run(_run_with_signals(builder, main))


async def _run_with_signals[T](
    builder: ApplicationBuilder, main: ApplicationMain[T] | None
) -> T | None:
    """Build and run an application while temporarily handling termination signals.

    :param builder: Mutable application composition to build.
    :param main: Optional sync or async callback to execute after application startup.
    :return: The result, or `None` when unavailable.
    :rtype: T | None
    """
    application = await builder.build()
    loop = asyncio.get_running_loop()
    installed: list[signal.Signals] = []
    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signum, application.context.cancellation.cancel)
            installed.append(signum)
        except NotImplementedError:
            pass
    try:
        return await application.run(main)
    finally:
        for signum in installed:
            loop.remove_signal_handler(signum)


def exit_code(error: Exception | asyncio.CancelledError | KeyboardInterrupt | None) -> int:
    """Map standalone completion to a conservative process exit code.

    :param error: Completion error to convert, or ``None`` for successful completion.
    :return: The resulting integer.
    :rtype: int
    """
    if error is None:
        return 0
    if isinstance(error, (KeyboardInterrupt, asyncio.CancelledError)):
        return 130
    return 1
