from pathlib import Path

import aiofiles
from fastapi import UploadFile


async def save_uploaded_file(
    upload_file: UploadFile,
    path: Path,
    chunk_size: int = 128 * 1024,  # 128KB
) -> Path:
    """Save uploaded file using streaming to handle large files"""
    async with aiofiles.open(path, "wb") as f:
        while chunk := await upload_file.read(chunk_size):
            await f.write(chunk)

    return path
