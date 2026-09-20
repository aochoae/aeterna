# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Alberto Ochoa

"""Configuration error types."""


class ConfigurationError(Exception):
    """Base class for configuration failures."""


class ProviderError(ConfigurationError):
    """A configuration provider failed without exposing its original error details."""

    def __init__(self, provider: str):
        """Create a sanitized provider failure.

        :param provider: Identity of the provider that failed to load.
        """
        super().__init__(f"Configuration provider {provider!r} failed")
        self.provider = provider


class MergeError(ConfigurationError):
    """Provider data cannot be represented as a configuration tree."""


class MissingValueError(ConfigurationError, KeyError):
    """A requested configuration path does not exist."""

    def __init__(self, path: str):
        """Create an error for an absent configuration path.

        :param path: Fully qualified path that could not be found.
        """
        super().__init__(f"Configuration value {path!r} is missing")
        self.path = path


class BindingError(ConfigurationError):
    """A configuration value cannot be converted to the requested type."""

    def __init__(self, path: str, target: object, reason: str):
        """Create an error that describes a failed type conversion.

        :param path: Fully qualified path of the value being bound.
        :param target: Requested runtime type or annotation.
        :param reason: Safe explanation of why conversion failed.
        """
        super().__init__(f"Cannot bind configuration {path or '<root>'!r} to {target!r}: {reason}")
        self.path = path
        self.target = target
