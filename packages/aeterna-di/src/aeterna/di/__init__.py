# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Alberto Ochoa

"""Public dependency-injection API."""

from .container import (
    ServiceCollection,
    ServiceDescriptor,
    ServiceLifetime,
    ServiceProvider,
    ServiceResolver,
    ServiceScope,
)
from .errors import (
    ActivationError,
    AmbiguousRegistrationError,
    CaptiveDependencyError,
    CircularDependencyError,
    MissingRegistrationError,
    RegistrationError,
    ResolutionError,
    ScopeClosedError,
    ServiceCancellationError,
)

__all__ = [
    "ActivationError",
    "AmbiguousRegistrationError",
    "CaptiveDependencyError",
    "CircularDependencyError",
    "MissingRegistrationError",
    "RegistrationError",
    "ResolutionError",
    "ScopeClosedError",
    "ServiceCollection",
    "ServiceCancellationError",
    "ServiceDescriptor",
    "ServiceLifetime",
    "ServiceProvider",
    "ServiceResolver",
    "ServiceScope",
]
