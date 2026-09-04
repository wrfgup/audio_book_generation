"""Public exception types used by the command-line interface."""

from __future__ import annotations


class AudiobookError(Exception):
    """Base class for errors that are safe to report to a user."""


class InputError(AudiobookError):
    """Invalid local input, path, or configuration (exit code 2)."""


class BuildError(AudiobookError):
    """A network, API, or audio build failure (exit code 1)."""


class APIConfigurationError(InputError):
    """An API setting is missing or unsafe."""


class APIRequestError(BuildError):
    """A remote API request failed without exposing request contents."""


class RecoverableAPIError(APIRequestError):
    """A transient or malformed optional inference result may be downgraded."""


class SourceError(BuildError):
    """An authorized web source could not be fetched safely."""
