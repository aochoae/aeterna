# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Alberto Ochoa

"""Application lifecycle errors."""


class ApplicationError(Exception):
    """Base class for runtime failures."""


class ApplicationCancellationError(ApplicationError):
    """Application cleanup could not complete normally after cancellation."""


class InvalidStateError(ApplicationError):
    """A lifecycle operation is invalid in the current state."""


class StartupError(ApplicationError):
    """Application startup failed."""

    def __init__(self, cause: Exception):
        """Create an error that wraps a startup failure.

        :param cause: Exception raised while starting hooks or hosted services.
        """
        super().__init__(f"Application startup failed: {cause}")
        self.__cause__ = cause


class HostedServiceError(ApplicationError):
    """A hosted service stopped before application shutdown."""

    def __init__(self, service: object, cause: Exception | None = None):
        """Create an error for a hosted service that stopped unexpectedly.

        :param service: Hosted service that returned or failed before shutdown.
        :param cause: Optional exception raised by the hosted service task.
        :return: None.
        :rtype: None
        """
        message = f"Hosted service {type(service).__qualname__} stopped unexpectedly"
        if cause is not None:
            message = f"{message}: {cause}"
        super().__init__(message)
        self.service = service
        self.__cause__ = cause


class ShutdownTimeoutError(ApplicationError):
    """Graceful shutdown exceeded its configured deadline."""
