import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from src.maintenance import (owned_temporary_directory, prune_stale_temp_dirs,
                             prune_avatar_cache, TEMP_MARKER, temp_scan_bases)


class MaintenanceTest(unittest.TestCase):
    def test_only_expired_owned_dead_process_directory_is_removed(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            unmanaged=root/'.image-vote-foreign';unmanaged.mkdir()
            old=time.time()-90000;os.utime(unmanaged,(old,old))
            with owned_temporary_directory(root,'.image-vote-') as tmp:
                target=Path(tmp);os.utime(target,(old,old))
                bases=[(root,('.image-vote-',))]
                self.assertEqual(prune_stale_temp_dirs(bases),0)  # Current process is alive.
                with patch('src.maintenance.os.kill',side_effect=ProcessLookupError):
                    self.assertEqual(prune_stale_temp_dirs(bases),1)
                self.assertTrue(unmanaged.exists())

    def test_unreadable_owner_or_symlink_is_not_removed(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);target=root/'.image-vote-broken';target.mkdir()
            (target/TEMP_MARKER).write_text('{broken')
            os.utime(target,(0,0));link=root/'.image-vote-link';link.symlink_to(target)
            self.assertEqual(prune_stale_temp_dirs([(root,('.image-vote-',))]),0)
            self.assertTrue(target.exists())
            self.assertNotIn(Path(tempfile.gettempdir()),[base for base,_ in temp_scan_bases(root,root/'data')])

    def test_avatar_pruning_is_name_and_root_scoped(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);cache=root/'avatars';cache.mkdir()
            own=cache/('a'*64+'.webp');own.write_bytes(b'cache');os.utime(own,(0,0))
            foreign=cache/'notes.txt';foreign.write_text('keep');os.utime(foreign,(0,0))
            link=root/'alias';link.symlink_to(cache)
            self.assertEqual(prune_avatar_cache(link,30),0)
            self.assertEqual(prune_avatar_cache(cache,30),1)
            self.assertTrue(foreign.exists())


class PeriodicMaintenanceTest(unittest.IsolatedAsyncioTestCase):
    async def test_periodic_maintenance_runs_and_is_cancellable(self):
        import asyncio
        from unittest.mock import AsyncMock, Mock
        from main import ImageVotePlugin
        plugin=object.__new__(ImageVotePlugin)
        plugin._ensure_config=Mock()
        plugin.run_self_maintenance=AsyncMock()
        with patch('main.asyncio.sleep', new=AsyncMock(side_effect=[None,asyncio.CancelledError])):
            with self.assertRaises(asyncio.CancelledError):
                await plugin._maintenance_loop()
        plugin.run_self_maintenance.assert_awaited_once()


class ThumbnailQuotaTest(unittest.TestCase):
    def test_size_cap_removes_oldest_and_retains_unrelated_files(self):
        from src.maintenance import prune_thumbnail_cache
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            old=root/('a'*64+'.webp');new=root/('b'*64+'.webp')
            old.write_bytes(b'a'*700000);new.write_bytes(b'b'*700000)
            stamp=time.time();os.utime(old,(stamp-100,stamp-100))
            unrelated=root/'keep.txt';unrelated.write_text('keep')
            self.assertEqual(prune_thumbnail_cache(root,7,1),1)
            self.assertFalse(old.exists());self.assertTrue(new.exists());self.assertTrue(unrelated.exists())
