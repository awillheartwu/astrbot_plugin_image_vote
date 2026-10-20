import asyncio
import base64
import itertools
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from main import ImageVotePlugin
from src.application import VoteApplication
from src.astrbot_adapter import AstrBotAdapter
from src.config import VoteConfig
from src.models import Candidate, MessageStamp, SendReceipt, SendStatus, Session, SessionStatus, Vote, VoteSource, VoteWindow
from src.persistence import SQLiteStore
from src.project_service import ProjectService
from src.reply_resolver import ReplyPayload
from src.session_manager import SessionManager
from src.vote_collector import VoteRouter
from src.vote_timing import event_stamp, timestamp


def moment(second):
    return "2026-10-20T10:00:%02d+00:00" % second


class VoteTimingTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.store = SQLiteStore(self.root / "vote.db")
        await self.store.initialize()
        self.config = VoteConfig.from_mapping({
            "input_root": str(self.root), "output_root": str(self.root / "reports"),
            "score_min": 0, "score_max": 10,
        })
        self.app = VoteApplication(
            self.config, ProjectService(self.root), self.store, SessionManager(), VoteRouter(),
        )
        self.session = Session(
            "s1", "ABCD", "g1", "umo", "demo", str(self.root), SessionStatus.RUNNING,
            started_at=moment(0), score_min=0, score_max=10, time_routing=True, vote_policy="last_wins",
            active_character="B", active_candidate_id="b",
        )
        self.candidates = [
            Candidate("a", "s1", 1, "a.png", "a.png", "A-1", None, 1, character="A",
                      send_status=SendStatus.SENT, sent_at=moment(11), message_time=moment(10), message_sequence="100"),
            Candidate("a2", "s1", 2, "a2.png", "a2.png", "A-2", None, 1, character="A",
                      send_status=SendStatus.SENT, sent_at=moment(16), message_time=moment(15), message_sequence="150"),
            Candidate("b", "s1", 3, "b.png", "b.png", "B", None, 1, character="B",
                      send_status=SendStatus.SENT, sent_at=moment(27), message_time=moment(25), message_sequence="250"),
        ]
        await self.store.save_session(self.session)
        await self.store.save_candidates(self.candidates)
        await self.store.open_vote_window(VoteWindow("s1", "a", moment(11)))
        await self.store.close_vote_windows("s1", moment(20))
        await self.store.open_vote_window(VoteWindow("s1", "b", moment(27)))

    async def asyncTearDown(self):
        await self.store.close()
        self.temporary.cleanup()

    async def cast(self, second, seq, score="10", reply=None, voter="u1"):
        return await self.app.record_vote(
            self.session, self.candidates, score, voter, "voter", self.candidates[-1],
            reply=reply, message_id="m%s" % seq,
            stamp=MessageStamp(moment(second), moment(second), str(seq)),
        )

    async def test_delayed_votes_respect_windows_gaps_and_outside_window_replies(self):
        self.assertIsNone(await self.app.record_vote(
            self.session, self.candidates, "3", "old", "voter", self.candidates[-1],
            stamp=MessageStamp("2026-10-19T10:00:00+00:00"),
        ))
        # This event is processed with B active, but arrived before A's send acknowledgement.
        decision = await self.cast(10, 110)
        self.assertEqual((decision.character, decision.candidate_id), ("A", "a"))
        decision = await self.cast(17, 170, "6", voter="u2")
        self.assertEqual((decision.character, decision.candidate_id), ("A", "a2"))
        self.assertIsNone(await self.cast(22, 220))  # Explicitly closed, next image not sent.
        decision = await self.cast(26, 260, voter="u3")
        self.assertEqual(decision.character, "B")  # B displayed before its API acknowledgement.
        reply = ReplyPayload(message_str="[投票 001/003 · ABCD]")
        decision = await self.cast(30, 300, "3", reply=reply)
        self.assertEqual(decision.character, "A")
        self.session.status = SessionStatus.PAUSED
        self.assertEqual((await self.cast(31, 310, "4", reply=reply, voter="paused")).character, "A")
        self.session.status = SessionStatus.RUNNING
        self.assertIsNone(await self.cast(12, 120, "9", reply=reply))  # Older change cannot win.
        self.assertIsNone(await self.cast(31, 310, reply=ReplyPayload(message_str="[投票 001/003 · OTHER]")))
        self.assertIsNone(await self.cast(5, 50, reply=reply))  # Cannot quote an unsent image.
        self.session.status = SessionStatus.FINALIZING
        self.session.finished_at = moment(40)
        decision = await self.cast(35, 350, "2", reply=reply)
        self.assertEqual(decision.character, "A")
        self.assertIsNone(await self.cast(40, 400, reply=reply))
        votes = {(v.character, v.voter_id): v for v in await self.store.list_votes("s1")}
        self.assertEqual(votes["A", "u1"].score, 2)
        self.assertEqual(votes["A", "u2"].candidate_id, "a2")
        await self.app.vote_activity.seal(self.session)
        self.assertIsNone(await self.cast(36, 360, reply=reply))
        # Migration is additive, and reopening keeps windows, policy and message order intact.
        await self.store.close()
        await self.store.initialize()
        loaded = await self.store.get_session("s1")
        self.assertTrue(loaded.time_routing)
        self.assertEqual(loaded.vote_policy, "last_wins")
        self.assertEqual(len(await self.store.list_vote_windows("s1")), 2)
        self.assertEqual((await self.store.list_candidates("s1"))[0].message_sequence, "100")
        self.assertEqual({(v.character, v.voter_id): v.score for v in await self.store.list_votes("s1")},
                         {key: value.score for key, value in votes.items()})

    async def test_policies_choose_the_same_final_vote_for_every_arrival_order(self):
        scores = [9, 2, 6]
        for policy, winner in [("last_wins", 2), ("first_wins", 0), ("max_score", 0), ("min_score", 1)]:
            for case, order in enumerate(itertools.permutations(range(3))):
                voter = "%s-%s" % (policy, case)
                for index in order:
                    await self.store.apply_vote(Vote(
                        None, "s1", "a" if index == 0 else "a2", voter, "voter", scores[index],
                        VoteSource.CURRENT_WINDOW if index == 0 else VoteSource.QUOTED_REPLY,
                        message_id="m%s" % index, character="A", message_time=moment(12),
                        message_sequence=str(index + 101), received_at=moment(index + 12),
                    ), policy)
                vote = next(v for v in await self.store.list_votes("s1") if v.voter_id == voter)
                self.assertEqual((vote.score, vote.message_sequence), (scores[winner], str(winner + 101)))
                self.assertEqual(vote.candidate_id, "a" if winner == 0 else "a2")
                duplicate = await self.store.apply_vote(vote, policy)
                self.assertFalse(duplicate.accepted)

    async def test_cancelled_sqlite_write_finishes_before_final_snapshot(self):
        entered, release = threading.Event(), threading.Event()
        original = self.store._upsert_vote_sync

        def blocked_write(*args):
            entered.set()
            if not release.wait(2):
                raise TimeoutError("test did not release the disposable SQLite write")
            return original(*args)

        self.store._upsert_vote_sync = blocked_write
        task = asyncio.create_task(self.cast(12, 120))
        seal = None
        try:
            self.assertTrue(await asyncio.to_thread(entered.wait, 2))
            task.cancel()
            seal = asyncio.create_task(self.app.vote_activity.seal(self.session))
            await asyncio.sleep(0)
            self.assertFalse(seal.done())
            release.set()
            with self.assertRaises(asyncio.CancelledError):
                await task
            await asyncio.wait_for(seal, 2)
            self.assertEqual(len(await self.store.list_votes("s1")), 1)
        finally:
            release.set()
            await asyncio.gather(task, *([seal] if seal is not None else []), return_exceptions=True)

    async def test_progress_and_new_window_roll_back_together_on_write_failure(self):
        await self.store.close_vote_windows("s1", moment(30))
        original = self.store._save_session_sync

        def fail_session(*args, **kwargs):
            raise RuntimeError("disposable database write failure")

        candidate = Candidate("c", "s1", 4, "c.png", "c.png", "C", None, 1,
                              send_status=SendStatus.SENT, sent_at=moment(35))
        self.store._save_session_sync = fail_session
        try:
            with self.assertRaises(RuntimeError):
                await self.store.save_send_progress(
                    self.session, [candidate], VoteWindow("s1", "c", moment(35)),
                )
            self.assertEqual(len(await self.store.list_candidates("s1")), 3)
            self.assertEqual(len(await self.store.list_vote_windows("s1")), 2)
        finally:
            self.store._save_session_sync = original


class VoteFinalizationTest(unittest.IsolatedAsyncioTestCase):
    async def test_cutoff_waits_for_admitted_handlers_and_cancelled_handlers_release_guard(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "projects" / "demo"
            project.mkdir(parents=True)
            (project / "one.png").write_bytes(b"disposable fixture")
            context = SimpleNamespace(get_plugin_data_dir=lambda _: root / "state")
            plugin = ImageVotePlugin(context, {
                "input_root": str(root / "projects"), "output_root": str(root / "reports"),
                "auto_report_on_finish": False, "ai_summary_enabled": False,
            })
            await plugin.store.initialize()
            window_ready, cutoff_seen, entered, release = [asyncio.Event() for _ in range(4)]
            notices = []

            async def sender(*_):
                return SendReceipt(timestamp(time.time()))

            async def notify(umo, text):
                notices.append(text)
                if "⏹" in text:
                    cutoff_seen.set()

            app = plugin.application
            app.sender, app.notifier = sender, notify
            session = await app.prepare_session("g1", "umo", "demo")
            session.interval_seconds = session.final_grace_seconds = 60
            candidates = await plugin.store.list_candidates(session.id)

            async def runner(current, control):
                original_wait = control.wait_for_interval

                async def wait(seconds):
                    window_ready.set()
                    await original_wait(seconds)

                control.wait_for_interval = wait
                await app.run_session(current, candidates, control)

            tasks = []
            try:
                await app.sessions.start(session, runner)
                managed = await app.sessions.active_for_group("g1")
                await asyncio.wait_for(window_ready.wait(), 2)
                original_attention = plugin._group_needs_attention

                async def blocked_attention(group_id):
                    entered.set()
                    await release.wait()
                    return await original_attention(group_id)

                plugin._group_needs_attention = blocked_attention
                event = SimpleNamespace(
                    message_str="3", created_at=time.time(),
                    message_obj=SimpleNamespace(group_id="g1", self_id="bot", message_id="m1",
                                                sender=SimpleNamespace(user_id="u1", nickname="voter")),
                )
                tasks.append(asyncio.create_task(plugin.on_group_message(event)))
                await asyncio.wait_for(entered.wait(), 2)
                cancelled = asyncio.create_task(plugin.on_group_message(event))
                tasks.append(cancelled)
                await asyncio.sleep(0)
                cancelled.cancel()
                await asyncio.gather(cancelled, return_exceptions=True)
                await app.finish("g1")
                await asyncio.wait_for(cutoff_seen.wait(), 2)
                self.assertFalse(managed.task.done())
                self.assertEqual(session.status, SessionStatus.FINALIZING)
                release.set()
                await asyncio.wait_for(tasks[0], 2)
                await asyncio.wait_for(managed.task, 2)
                self.assertEqual(session.status, SessionStatus.COMPLETED)
                self.assertEqual(len(await plugin.store.list_votes(session.id)), 1)
                self.assertTrue(any("有效票：1" in notice for notice in notices))
            finally:
                release.set()
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                await plugin.terminate()


class VoteSendReceiptTest(unittest.IsolatedAsyncioTestCase):
    async def test_send_receipt_uses_real_sequence_and_metadata_failure_does_not_resend(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "one.png"
            path.write_bytes(b"image fixture")
            calls = []
            fail_lookup = None

            async def call_action(action, **params):
                calls.append((action, params))
                if action == "send_group_msg":
                    self.assertEqual(params["group_id"], 123)
                    image = params["message"][1]["data"]["file"].removeprefix("base64://")
                    self.assertEqual(base64.b64decode(image), path.read_bytes())
                    return {"message_id": 456}
                if fail_lookup == "error":
                    raise RuntimeError("metadata unavailable")
                if fail_lookup == "invalid":
                    return {"data": None}
                return {"time": 1792491600, "real_seq": "999", "message_seq": 456}

            platform = SimpleNamespace(meta=lambda: SimpleNamespace(name="aiocqhttp"),
                                       bot=SimpleNamespace(call_action=call_action))
            adapter = AstrBotAdapter(SimpleNamespace(get_platform_inst=lambda _: platform))
            receipt = await adapter.send_vote_message("qq:GroupMessage:123", "vote", [path])
            self.assertEqual((receipt.message_id, receipt.sequence), ("456", "999"))
            for fail_lookup in ["error", "invalid"]:
                adapter = AstrBotAdapter(SimpleNamespace(get_platform_inst=lambda _: platform))
                with self.assertLogs("astrbot_plugin_image_vote", level="WARNING"):
                    fallback = await adapter.send_vote_message("qq:GroupMessage:123", "vote", [path])
                self.assertIsNone(fallback.sequence)
            self.assertEqual([a for a, _ in calls], ["send_group_msg", "get_msg"] * 3)
            stamp = event_stamp(SimpleNamespace(created_at=1792491600.5, message_obj=SimpleNamespace(
                raw_message={"time": 1792491600, "real_seq": "999", "message_seq": 456},
            )))
            self.assertEqual(stamp.sequence, "999")
            self.assertIsNone(event_stamp(SimpleNamespace(created_at=float("nan"))))
