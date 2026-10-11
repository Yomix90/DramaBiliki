"""
Parallel MTProto upload: sends the 512 KB parts of a file over several concurrent
requests instead of one at a time, which makes large uploads several times faster.
Returns an InputFile/InputFileBig ready for client.send_file().
"""
import asyncio
import hashlib
import logging
from pathlib import Path
from typing import Callable, Optional, Union

from telethon import errors, helpers
from telethon.tl import functions, types

logger = logging.getLogger("bridge.telegram.upload")

PART_SIZE = 512 * 1024
BIG_FILE_THRESHOLD = 10 * 1024 * 1024


async def fast_upload_file(
    client,
    path: Path,
    file_name: Optional[str] = None,
    workers: int = 8,
    progress: Optional[Callable[[int, int], None]] = None,
) -> Union[types.InputFile, types.InputFileBig]:
    size = path.stat().st_size
    if size == 0:
        raise ValueError("Fichier vide")
    is_big = size > BIG_FILE_THRESHOLD
    part_count = (size + PART_SIZE - 1) // PART_SIZE
    file_id = helpers.generate_random_long()
    queue: asyncio.Queue = asyncio.Queue()
    for index in range(part_count):
        queue.put_nowait(index)

    sent_bytes = 0
    md5_parts = {} if not is_big else None

    with open(path, "rb") as fh:
        read_lock = asyncio.Lock()

        async def read_part(index: int) -> bytes:
            async with read_lock:
                def _read():
                    fh.seek(index * PART_SIZE)
                    return fh.read(PART_SIZE)
                return await asyncio.to_thread(_read)

        async def worker():
            nonlocal sent_bytes
            while True:
                try:
                    index = queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
                data = await read_part(index)
                if md5_parts is not None:
                    md5_parts[index] = data
                request = (
                    functions.upload.SaveBigFilePartRequest(file_id, index, part_count, data)
                    if is_big
                    else functions.upload.SaveFilePartRequest(file_id, index, data)
                )
                for attempt in range(5):
                    try:
                        if await client(request):
                            break
                    except errors.FloodWaitError as e:
                        logger.warning(f"FloodWait {e.seconds}s on part {index}")
                        await asyncio.sleep(min(e.seconds, 60))
                    except Exception as e:
                        if attempt == 4:
                            raise RuntimeError(f"Échec de l'envoi du morceau {index}/{part_count}: {e}") from e
                        await asyncio.sleep(0.5 * (attempt + 1))
                else:
                    raise RuntimeError(f"Échec de l'envoi du morceau {index}/{part_count}")
                sent_bytes += len(data)
                if progress:
                    progress(sent_bytes, size)

        await asyncio.gather(*(worker() for _ in range(max(1, min(workers, part_count)))))

    name = file_name or path.name
    if is_big:
        return types.InputFileBig(id=file_id, parts=part_count, name=name)
    md5 = hashlib.md5()
    for index in range(part_count):
        md5.update(md5_parts[index])
    return types.InputFile(id=file_id, parts=part_count, name=name, md5_checksum=md5.hexdigest())
