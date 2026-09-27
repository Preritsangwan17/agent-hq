"""Isolated application email workflow. No Agent HQ database or worker dependency."""

from .core import EmailModule, EmailModuleError

__all__ = ["EmailModule", "EmailModuleError"]
