"""
File storage backends for document uploads.

Supports local filesystem (development) and S3-compatible (production).
Configurable via STORAGE_BACKEND environment variable.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Protocol

from config import settings


class StorageBackend(Protocol):
    """Interface for file storage backends."""

    async def save(self, deal_id: str, data: bytes, filename: str) -> str:
        """Save file and return storage path/key."""
        ...

    async def get(self, path: str) -> bytes:
        """Retrieve file contents by storage path."""
        ...

    async def delete(self, path: str) -> None:
        """Delete a file by storage path."""
        ...


class LocalStorage:
    """Store files on the local filesystem. For development and small deployments."""

    def __init__(self, base_path: str | None = None):
        self.base_path = Path(base_path or settings.storage_local_path).resolve()

    def _safe_path(self, path: str) -> Path:
        """Resolve path and verify it stays within base_path (prevents traversal)."""
        full = (self.base_path / path).resolve()
        if not full.is_relative_to(self.base_path):
            raise ValueError("Invalid storage path")
        return full

    async def save(self, deal_id: str, data: bytes, filename: str) -> str:
        ext = Path(filename).suffix or ".bin"
        file_id = uuid.uuid4().hex[:12]
        relative_path = f"{deal_id}/{file_id}{ext}"
        full_path = self._safe_path(relative_path)

        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_bytes(data)

        return relative_path

    async def get(self, path: str) -> bytes:
        try:
            return self._safe_path(path).read_bytes()
        except FileNotFoundError:
            raise FileNotFoundError(f"File not found: {path}")

    async def delete(self, path: str) -> None:
        try:
            self._safe_path(path).unlink()
        except FileNotFoundError:
            pass


_storage_instance: StorageBackend | None = None


def get_storage() -> StorageBackend:
    """Return the configured storage backend (singleton)."""
    global _storage_instance
    if _storage_instance is None:
        backend = settings.storage_backend
        if backend == "local":
            _storage_instance = LocalStorage()
        else:
            raise ValueError(f"Unknown storage backend: {backend}")
    return _storage_instance
