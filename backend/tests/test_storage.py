"""
Tests for the file storage backend.
"""

import sys
import os

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.storage import LocalStorage


@pytest.fixture
def storage(tmp_path):
    """LocalStorage backed by a temporary directory."""
    return LocalStorage(base_path=str(tmp_path))


class TestLocalStorage:
    @pytest.mark.asyncio
    async def test_save_and_get(self, storage):
        data = b"Hello, PropAI!"
        path = await storage.save("deal-123", data, "test.pdf")

        assert path.startswith("deal-123/")
        assert path.endswith(".pdf")

        retrieved = await storage.get(path)
        assert retrieved == data

    @pytest.mark.asyncio
    async def test_save_creates_subdirectory(self, storage):
        await storage.save("new-deal", b"content", "doc.txt")
        assert (storage.base_path / "new-deal").is_dir()

    @pytest.mark.asyncio
    async def test_save_uses_file_extension(self, storage):
        path = await storage.save("d", b"x", "report.xlsx")
        assert path.endswith(".xlsx")

    @pytest.mark.asyncio
    async def test_save_defaults_to_bin_extension(self, storage):
        path = await storage.save("d", b"x", "noext")
        assert path.endswith(".bin")

    @pytest.mark.asyncio
    async def test_get_nonexistent_raises(self, storage):
        with pytest.raises(FileNotFoundError):
            await storage.get("does/not/exist.pdf")

    @pytest.mark.asyncio
    async def test_delete_removes_file(self, storage):
        path = await storage.save("d", b"data", "f.pdf")
        await storage.delete(path)

        with pytest.raises(FileNotFoundError):
            await storage.get(path)

    @pytest.mark.asyncio
    async def test_delete_nonexistent_is_silent(self, storage):
        await storage.delete("does/not/exist.pdf")  # should not raise

    @pytest.mark.asyncio
    async def test_path_traversal_blocked_on_get(self, storage):
        with pytest.raises(ValueError, match="Invalid storage path"):
            await storage.get("../../etc/passwd")

    @pytest.mark.asyncio
    async def test_path_traversal_blocked_on_delete(self, storage):
        with pytest.raises(ValueError, match="Invalid storage path"):
            await storage.delete("../../../etc/passwd")

    @pytest.mark.asyncio
    async def test_unique_filenames_per_save(self, storage):
        path1 = await storage.save("d", b"a", "same.pdf")
        path2 = await storage.save("d", b"b", "same.pdf")
        assert path1 != path2
