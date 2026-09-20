# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Alberto Ochoa

"""Public aeterna runtime API."""

from .application import (
    Application,
    ApplicationBuilder,
    ApplicationContext,
    ApplicationState,
    CancellationToken,
    HostedService,
    LifecycleHook,
)
from .errors import (
    ApplicationCancellationError,
    ApplicationError,
    HostedServiceError,
    InvalidStateError,
    ShutdownTimeoutError,
    StartupError,
)
from .hosting import exit_code, run

__all__ = [
    "Application",
    "ApplicationBuilder",
    "ApplicationCancellationError",
    "ApplicationContext",
    "ApplicationError",
    "ApplicationState",
    "CancellationToken",
    "HostedService",
    "HostedServiceError",
    "InvalidStateError",
    "LifecycleHook",
    "ShutdownTimeoutError",
    "StartupError",
    "exit_code",
    "run",
]
