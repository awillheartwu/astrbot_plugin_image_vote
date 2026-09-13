"""Bounded, fixed-host QQ avatar retrieval; only derived files enter reports."""
import asyncio
import hashlib
import io
import os
import re
import time
import uuid
from pathlib import Path
from urllib.request import HTTPRedirectHandler, Request, build_opener


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class AvatarService:
    def __init__(self, cache_root: Path):
        self.cache_root = Path(cache_root)
        self._semaphore = asyncio.Semaphore(4)

    def _fetch(self, voter_id: str) -> bytes:
        request = Request('https://q1.qlogo.cn/g?b=qq&nk=%s&s=100' % voter_id,
                          headers={'User-Agent': 'AstrBot-Image-Vote/1.0'})
        with build_opener(_NoRedirect()).open(request, timeout=5) as response:
            if not response.headers.get('Content-Type', '').lower().startswith('image/'):
                raise ValueError('avatar endpoint did not return an image')
            content = response.read(2 * 1024 * 1024 + 1)
            if len(content) > 2 * 1024 * 1024:
                raise ValueError('avatar image exceeds size limit')
            return content

    def _prepare(self, voter_id: str) -> bytes:
        from PIL import Image, ImageOps
        self.cache_root.mkdir(parents=True, exist_ok=True)
        cache = self.cache_root / (hashlib.sha256(voter_id.encode()).hexdigest() + '.webp')
        if cache.is_file() and not cache.is_symlink() and time.time() - cache.stat().st_mtime < 30 * 86400:
            return cache.read_bytes()
        raw = self._fetch(voter_id)
        with Image.open(io.BytesIO(raw)) as source:
            if source.width * source.height > 4_000_000:
                raise ValueError('avatar dimensions exceed limit')
            image = ImageOps.exif_transpose(source).convert('RGB')
            image.thumbnail((128, 128))
            output = io.BytesIO()
            image.save(output, 'WEBP', quality=80)
        content = output.getvalue()
        temporary = cache.with_name('.' + uuid.uuid4().hex + '.tmp')
        try:
            temporary.write_bytes(content)
            os.replace(temporary, cache)
        finally:
            temporary.unlink(missing_ok=True)
        return content

    async def get(self, voter_id: str):
        if not re.fullmatch(r'[1-9][0-9]{4,14}', voter_id):
            return None
        async with self._semaphore:
            # The worker only touches the cache, never a cancellable staging directory.
            try:
                return await asyncio.to_thread(self._prepare, voter_id)
            except Exception:
                return None
