from abc import ABC, abstractmethod
from utils.models import PhotoRecord


class StorageScanner(ABC):
    """Abstract base class for all storage connectors."""

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Unique identifier: 'pc', 'google_photos', or 'mobile'."""
        ...

    @abstractmethod
    def scan(self) -> list[PhotoRecord]:
        """
        Scan this storage and return a list of PhotoRecords.
        Must be read-only — never modify any files here.
        """
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if this storage is currently accessible."""
        ...
