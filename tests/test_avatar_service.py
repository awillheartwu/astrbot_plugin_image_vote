import asyncio
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from src.avatar_service import AvatarService

try:
    from PIL import Image
except ImportError:
    Image = None


class AvatarTest(unittest.TestCase):
    def test_non_qq_identity_never_fetches_and_download_failure_is_optional(self):
        async def run(root):
            service = AvatarService(root)
            with patch.object(service, '_prepare', side_effect=RuntimeError('offline')) as prepare:
                self.assertIsNone(await service.get('../secret'))
                prepare.assert_not_called()
                self.assertIsNone(await service.get('123456789'))
                prepare.assert_called_once()
        with tempfile.TemporaryDirectory() as d:
            asyncio.run(run(Path(d)))

    @unittest.skipIf(Image is None, 'Pillow unavailable in this interpreter')
    def test_avatar_is_derived_cached_and_does_not_expose_identity_in_filenames(self):
        async def run(root):
            service = AvatarService(root)
            raw = io.BytesIO()
            Image.new('RGB', (256, 256), 'blue').save(raw, 'PNG')
            with patch.object(service, '_fetch', return_value=raw.getvalue()) as fetch:
                first = await service.get('123456789')
                second = await service.get('123456789')
                self.assertEqual(first, second)
                self.assertEqual(fetch.call_count, 1)
                with Image.open(io.BytesIO(first)) as image:
                    self.assertEqual(image.format, 'WEBP')
                    self.assertLessEqual(image.width, 128)
            self.assertNotIn('123456789', ' '.join(p.name for p in root.iterdir()))
        with tempfile.TemporaryDirectory() as d:
            asyncio.run(run(Path(d)))
