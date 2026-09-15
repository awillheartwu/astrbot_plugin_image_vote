import shutil
import asyncio
import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from src.application import VoteApplication
from src.config import VoteConfig
from src.models import Session, SessionStatus
from src.path_guard import PathGuard
from src.persistence import SQLiteStore
from src.project_registry import ProjectRegistry
from src.project_service import ProjectService
from src.report_generator import PLUGIN_NAME, REPORT_MARKER
from src.session_manager import SessionManager
from src.vote_collector import VoteRouter
from src.workspace_api import WorkspaceAPI
from src.workspace_service import ConfigConflict, WorkspaceService


class ConfigObject(dict):
    def save_config(self, changes):
        self.update(copy.deepcopy(changes))
        self.saved = copy.deepcopy(dict(self))


class FailingConfigObject(dict):
    """写入磁盘后再抛错，用于验证保存失败时的磁盘回滚。"""

    def __init__(self, payload, config_path):
        super().__init__(payload)
        self.config_path = str(config_path)

    def save_config(self, changes):
        self.update(copy.deepcopy(changes))
        Path(self.config_path).write_text(json.dumps(dict(self), ensure_ascii=False), encoding="utf-8")
        raise OSError("disk full")


class WorkspaceTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = self.root = Path(self.temp.name)
        (root/'input'/'demo').mkdir(parents=True)
        (root/'input'/'demo'/'one.png').write_bytes(b'fixture')
        self.config = ConfigObject({'paths': {'input_root':str(root/'input'), 'output_root':str(root/'out')}})
        self.store = SQLiteStore(root/'state.db')
        await self.store.initialize()
        self.manager = SessionManager()
        context = SimpleNamespace(get_config=lambda:{'dashboard':{'username':'owner'}}, registered_web_apis=[])
        def register(path, handler, methods, description):
            context.registered_web_apis[:] = [r for r in context.registered_web_apis if (r[0],r[2]) != (path,methods)]
            context.registered_web_apis.append((path,handler,methods,description))
        context.register_web_api = register
        self.plugin = SimpleNamespace(context=context, _page_config_object=self.config, store=self.store,
                         project_registry=ProjectRegistry(root/'projects.json'), session_manager=self.manager)
        def apply(raw, source=None):
            self.plugin.settings=VoteConfig.from_mapping(raw)
            self.plugin.project_service=ProjectService(root/'input', registry=self.plugin.project_registry)
        apply(self.config)
        self.plugin._apply_config=apply
        self.plugin._ensure_config=lambda:None
        self.plugin.application=VoteApplication(self.plugin.settings,self.plugin.project_service,self.store,
                                                self.manager,VoteRouter(),sender=AsyncMock())
        self.service=WorkspaceService(self.plugin)

    def make_report(self, session_id, mode='single_html', name='report-dir', body='<html>report body</html>'):
        output = self.root/'out'/'demo'/name
        output.mkdir(parents=True, exist_ok=True)
        PathGuard.write_report_marker(output, REPORT_MARKER, PLUGIN_NAME, session_id, {'short_id': session_id})
        (output/'index.html').write_text(body, encoding='utf-8')
        (output/'data.json').write_text(json.dumps({'report_mode': mode, 'session': {}, 'statistics': {},
                                                    'candidates': [], 'participants': []}), encoding='utf-8')
        return output

    async def completed_session(self, session_id, output):
        await self.store.save_session(Session(session_id, session_id, 'g', 'umo', 'demo', '/unused',
                                             status=SessionStatus.COMPLETED, output_path=str(output)))

    def configure_reporting(self):
        # 这些用例只验证互斥，不真的生成报告：给应用层一个可用的报告服务占位。
        self.plugin.application.report_generator = object()
        self.plugin.application.image_processor = object()

    def api(self, query=None):
        request = SimpleNamespace(username='owner', query=query or {}, json=AsyncMock(return_value={}))
        web = SimpleNamespace(request=request, json_response=lambda d: d,
                              error_response=lambda message, status_code: {'error': message, 'code': status_code},
                              file_response=lambda target, filename=None, content_type=None: {'file': str(target)},
                              stream_response=lambda content, content_type=None, headers=None: {
                                  'stream': content, 'content_type': content_type, 'headers': headers})
        api = WorkspaceAPI(self.plugin, web=web)
        api.service = self.service
        api.ready = True
        return api

    async def asyncTearDown(self):
        await self.service.shutdown()
        await self.manager.shutdown()
        await self.store.close()
        self.temp.cleanup()

    async def test_config_save_validates_types_conflicts_and_persists_grouped_values(self):
        original=self.service.config_snapshot()
        with self.assertRaises(ConfigConflict):
            await self.service.save_config({'revision':'old','values':{'score_max':10}})
        with self.assertRaises(ValueError):
            await self.service.save_config({'revision':original['revision'],'values':{'score_max':True}})
        with self.assertRaises(ValueError):
            await self.service.save_config({'revision':original['revision'],'values':{'secret_unknown':'x'}})
        result=await self.service.save_config({'revision':original['revision'],'values':{'score_max':10}})
        self.assertEqual(result['values']['score_max'],10)
        self.assertEqual(self.config.saved['voting']['score_max'],10)
        self.assertNotEqual(result['revision'],original['revision'])

    async def test_project_preflight_honors_overrides_and_browse_rejects_traversal(self):
        self.plugin.project_registry.register('registered',self.root/'input'/'demo',interval_seconds=7,recursive=True)
        result=await self.service.preview('registered')
        self.assertEqual(result['count'],1)
        self.assertEqual(result['interval_seconds'],7)
        self.assertEqual(result['interval_source'],'project')
        roots=self.service.browse()['roots']
        self.assertIn(str((self.root/'input').resolve()),roots)
        with self.assertRaises(PermissionError):
            self.service.browse('/')
        with self.assertRaises(ValueError):
            self.service.browse(str((self.root/'input').resolve()),'../')
        self.assertEqual({p['name'] for p in self.service.projects()},{'demo','registered'})

    async def test_recovered_session_finish_does_not_send_remaining_images(self):
        session=await self.plugin.application.prepare_session('g','umo','demo')
        session.status=SessionStatus.PAUSED
        await self.store.save_session(session)
        await self.service.control({'session_id':session.id,'action':'finish'})
        managed=await self.manager.active_for_group('g')
        await managed.task
        self.plugin.application.sender.assert_not_awaited()
        current=await self.store.get_session(session.id)
        self.assertEqual(current.status,SessionStatus.COMPLETED)

    async def test_stale_session_cannot_control_newer_recovered_session(self):
        for name,date in [('old','2026-01-01'),('new','2026-01-02')]:
            await self.store.save_session(Session(name,name,'g','umo','demo',str(self.root/'input'/'demo'),
                                                status=SessionStatus.PAUSED,created_at=date))
        with self.assertRaises(ValueError):
            await self.service.control({'session_id':'old','action':'stop'})
        self.assertEqual((await self.store.get_session('new')).status,SessionStatus.PAUSED)

    async def test_authorization_and_unload_remove_only_own_routes(self):
        request=SimpleNamespace(username=None, query={}, json=AsyncMock(return_value={}))
        web=SimpleNamespace(request=request,json_response=lambda d:d,error_response=lambda message,status_code:{'error':message,'code':status_code})
        api=WorkspaceAPI(self.plugin,web=web)
        self.assertTrue(api.register())
        api.ready=True
        endpoint=next(r[1] for r in self.plugin.context.registered_web_apis if r[0].endswith('/projects') and r[2]==['GET'])
        self.assertEqual((await endpoint())['code'],403)
        request.username='api_key:delegated'
        self.assertEqual((await endpoint())['code'],403)
        request.username='owner'
        self.assertEqual((await endpoint())['status'],'ok')
        new_api=WorkspaceAPI(self.plugin,web=web)
        new_api.register()
        count=len(self.plugin.context.registered_web_apis)
        await api.close()
        self.assertEqual(len(self.plugin.context.registered_web_apis),count)
        await new_api.close()
        self.assertEqual(self.plugin.context.registered_web_apis,[])
        self.assertEqual((await endpoint())['code'],503)

    async def test_active_sessions_are_not_lost_behind_history_pagination(self):
        await self.store.save_session(Session('paused','paused','g','umo','demo','/unused',status=SessionStatus.PAUSED,created_at='2020-01-01'))
        for i in range(5):
            await self.store.save_session(Session(str(i),str(i),'other','umo','demo','/unused',status=SessionStatus.COMPLETED,created_at='2026-01-01'))
        history=await self.service.sessions(limit=2)
        active=await self.service.sessions(active=True)
        self.assertEqual(len(history['sessions']),2)
        self.assertEqual([r['id'] for r in active['sessions']],['paused'])

    async def test_report_failure_is_visible_and_old_report_remains_accessible(self):
        output=self.root/'out'/'saved'
        output.mkdir(parents=True)
        (output/'index.html').write_text('previous report')
        await self.store.save_session(Session('old','old','g','umo','demo','/unused',status=SessionStatus.COMPLETED,
             output_path=str(output),error_message='report generation failed: disk full'))
        result=await self.service.sessions()
        self.assertEqual(result['sessions'][0]['report_state'],'failed')
        self.assertTrue(result['sessions'][0]['report_available'])

    async def test_countdown_decreases_and_pauses(self):
        from src.session_manager import SessionControl
        control=SessionControl()
        task=asyncio.create_task(control.wait_for_interval(1))
        await asyncio.sleep(.02)
        first=control.remaining_seconds()
        await asyncio.sleep(.03)
        self.assertLess(control.remaining_seconds(),first)
        control.pause()
        await asyncio.sleep(.01)
        frozen=control.remaining_seconds()
        await asyncio.sleep(.03)
        self.assertEqual(control.remaining_seconds(),frozen)
        control.request_finish()
        await task
        self.assertIsNone(control.remaining_seconds())

    async def test_concurrent_export_starts_only_one_generation(self):
        self.configure_reporting()
        output = self.make_report('s1')
        await self.completed_session('s1', output)
        original = self.plugin.store.get_session
        async def delayed(session_id):
            await asyncio.sleep(.02)
            return await original(session_id)
        self.plugin.store.get_session = delayed
        self.plugin.application.export_session = AsyncMock()
        results = await asyncio.gather(self.service.export('s1'), self.service.export('s1'), return_exceptions=True)
        self.assertEqual(sum(isinstance(r, ValueError) for r in results), 1)
        self.assertEqual(sum(isinstance(r, dict) for r in results), 1)
        for pending in self.plugin.application.report_activity.pending():
            await pending
        self.plugin.application.export_session.assert_awaited_once()

    async def test_failed_config_save_restores_disk_and_memory(self):
        config_path = self.root/'demo_config.json'
        config_path.write_text(json.dumps({'voting': {'score_max': 4}}, ensure_ascii=False), encoding='utf-8')
        failing = FailingConfigObject(copy.deepcopy(dict(self.config)), config_path)
        self.plugin._page_config_object = failing
        snapshot = self.service.config_snapshot()
        with self.assertRaises(OSError):
            await self.service.save_config({'revision': snapshot['revision'], 'values': {'score_max': 10}})
        self.assertEqual(self.plugin.settings.score_max, 4)
        self.assertEqual(json.loads(config_path.read_text(encoding='utf-8'))['voting']['score_max'], 4)

    async def test_cleanup_refuses_while_report_is_being_read(self):
        output = self.make_report('s1')
        await self.completed_session('s1', output)
        api = self.api({'session_id': 's1'})
        with self.service.reading('s1'):
            with self.assertRaises(ValueError):
                await api.dispatch('reports/cleanup', 'POST', {'session_id': 's1', 'confirmed': True})
            with self.assertRaises(ValueError):
                self.plugin.application.cleanup_reports('s1')
        self.assertTrue(output.is_dir())

    async def test_cleanup_refuses_while_report_is_generating(self):
        self.configure_reporting()
        output = self.make_report('s1')
        await self.completed_session('s1', output)
        started = asyncio.Event()
        async def slow_export(session_id, regenerate_ai=False):
            started.set()
            await asyncio.sleep(.05)
        self.plugin.application.export_session = slow_export
        api = self.api({'session_id': 's1'})
        await self.service.export('s1')
        await started.wait()
        with self.assertRaises(ValueError):
            await api.dispatch('reports/cleanup', 'POST', {'session_id': 's1', 'confirmed': True})
        with self.assertRaises(ValueError):
            self.plugin.application.cleanup_reports('s1')
        for pending in self.plugin.application.report_activity.pending():
            await pending
        self.assertTrue(output.is_dir())

    async def test_export_refuses_while_report_is_being_cleaned(self):
        self.configure_reporting()
        output = self.make_report('s1')
        await self.completed_session('s1', output)
        # 清理占位期间（删除前后都不留空隙）不允许再启动生成。
        with self.plugin.application.report_activity.cleaning('s1'):
            with self.assertRaises(ValueError):
                await self.service.export('s1')
            with self.assertRaises(ValueError):
                with self.service.reading('s1'):
                    pass
        self.assertEqual(self.plugin.application.report_activity.pending(), [])

    async def test_single_file_download_survives_report_cleanup(self):
        output = self.make_report('s1', body='<html>report body</html>')
        await self.completed_session('s1', output)
        api = self.api({'session_id': 's1'})
        response = await api.dispatch('reports/download', 'GET', {})
        shutil.rmtree(output)
        chunks = [chunk async for chunk in response['stream']]
        self.assertEqual(b''.join(chunks), b'<html>report body</html>')

    async def test_rename_replaces_registration_without_partial_state(self):
        self.plugin.project_registry.register('旧名', self.root/'input'/'demo')
        result = await self.service.register({'old_name': '旧名', 'name': '新名',
                                              'path': str(self.root/'input'/'demo')})
        self.assertEqual({p['name'] for p in result}, {'demo', '新名'})
        self.assertEqual(sorted(self.plugin.project_registry.entries()), ['新名'])
        # 目录项目没有登记项可移除：只登记新名，不报错
        result = await self.service.register({'old_name': 'demo', 'name': '别名',
                                              'path': str(self.root/'input'/'demo')})
        self.assertEqual({p['name'] for p in result}, {'demo', '新名', '别名'})
        # 改名参数非法时整体失败，不留半成品
        with self.assertRaises(ValueError):
            await self.service.register({'old_name': 'a/b', 'name': '半成品',
                                         'path': str(self.root/'input'/'demo')})
        self.assertEqual(sorted(self.plugin.project_registry.entries()), ['别名', '新名'])

    async def test_purge_requires_confirmation_and_deletes_records(self):
        output = self.make_report('s1')
        await self.completed_session('s1', output)
        api = self.api({'session_id': 's1'})
        with self.assertRaises(ValueError):
            await api.dispatch('sessions/purge', 'POST', {'session_id': 's1'})
        result = await api.dispatch('sessions/purge', 'POST', {'session_id': 's1', 'confirmed': True})
        self.assertEqual(result['reports'], 1)
        self.assertIsNone(await self.store.get_session('s1'))
        self.assertFalse(output.exists())
