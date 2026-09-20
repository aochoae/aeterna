# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Alberto Ochoa

"""Dependency-injection error types."""

from __future__ import annotations

from collections.abc import Sequence


def _format_path(path: Sequence[type[object]]) -> str:
    """Format a resolution path for diagnostics.

    :param path: Ordered service types participating in resolution.
    :return: The resulting string.
    :rtype: str
    """
    return " -> ".join(item.__qualname__ for item in path)


class ResolutionError(Exception):
    """Base class for service-resolution failures."""


class RegistrationError(ResolutionError):
    """A service registration is invalid."""


class MissingRegistrationError(ResolutionError):
    """A required service has no registration."""

    def __init__(self, key: type[object], path: Sequence[type[object]] = ()):
        """Create an error for a missing registration.

        :param key: Service type that has no registration.
        :param path: Resolution path that led to ``key``.
        """
        suffix = f" while resolving {_format_path(path)}" if path else ""
        super().__init__(f"No service is registered for {key!r}{suffix}")
        self.key = key
        self.path = tuple(path)


class AmbiguousRegistrationError(RegistrationError):
    """More than one registration exists for a service key."""

    def __init__(self, key: type[object]):
        """Create an error for duplicate registrations.

        :param key: Service type that was registered more than once.
        """
        super().__init__(f"Multiple services are registered for {key!r}")
        self.key = key


class CircularDependencyError(ResolutionError):
    """The resolution graph contains a dependency cycle."""

    def __init__(self, path: Sequence[type[object]]):
        """Create an error for a circular resolution path.

        :param path: Ordered service types in the detected cycle.
        """
        super().__init__(f"Circular dependency: {_format_path(path)}")
        self.path = tuple(path)


class CaptiveDependencyError(ResolutionError):
    """A singleton depends on a service with a shorter lifetime."""

    def __init__(self, key: type[object], path: Sequence[type[object]]):
        """Create an error for a singleton graph capturing a scoped service.

        :param key: Scoped service captured by the singleton dependency graph.
        :param path: Resolution path demonstrating the lifetime violation.
        """
        super().__init__(
            f"Singleton dependency graph cannot capture scoped service {key!r}: "
            f"{_format_path(path)}"
        )
        self.key = key
        self.path = tuple(path)


class ActivationError(ResolutionError):
    """A registered service could not be created."""

    def __init__(self, key: type[object], path: Sequence[type[object]], cause: Exception):
        """Create an error that wraps a service activation failure.

        :param key: Registered service type that failed to activate.
        :param path: Resolution path at the point of activation.
        :param cause: Original exception raised while creating the service.
        """
        super().__init__(f"Failed to activate {key!r} at {_format_path(path)}: {cause}")
        self.key = key
        self.path = tuple(path)
        self.__cause__ = cause


class ScopeClosedError(ResolutionError):
    """A resolver was used after its ownership boundary closed."""


class ServiceCancellationError(ResolutionError):
    """Service cleanup could not complete normally after cancellation."""
