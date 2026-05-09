"""Abstract base for social media publishers."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class PublishResult:
    ok: bool
    external_id: str | None = None
    error: str | None = None
    attempts: int = 0


class Publisher(ABC):
    @abstractmethod
    def publish(self, image_url: str, caption: str) -> PublishResult:
        ...
