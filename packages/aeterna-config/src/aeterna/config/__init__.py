# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Alberto Ochoa

"""Public layered-configuration API."""

from .core import (
    Configuration,
    ConfigurationBinder,
    ConfigurationBuilder,
    ConfigurationLimits,
    ConfigurationProvider,
    EnvironmentProvider,
    MappingProvider,
)
from .errors import BindingError, ConfigurationError, MergeError, MissingValueError, ProviderError

__all__ = [
    "BindingError",
    "Configuration",
    "ConfigurationBinder",
    "ConfigurationBuilder",
    "ConfigurationError",
    "ConfigurationLimits",
    "ConfigurationProvider",
    "EnvironmentProvider",
    "MappingProvider",
    "MergeError",
    "MissingValueError",
    "ProviderError",
]
