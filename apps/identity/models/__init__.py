"""Identity app models."""

from apps.identity.models.identity_signal import IdentitySignal

__all__ = ["IdentitySignal"]


def register_models() -> None:
    return None
