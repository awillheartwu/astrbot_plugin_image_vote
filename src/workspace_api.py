"""AstrBot 4.27.5 PageBridge adapter. No unauthenticated standalone routes."""
import asyncio
import base64
import json
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import quote

from .path_guard import PathGuard
from .report_generator import PLUGIN_NAME, REPORT_MARKER
from .workspace_service import ConfigConflict, WorkspaceService


class WorkspaceAPI:
    def __init__(self, plugin, web=None):
        self.plugin = plugin
        self.service = WorkspaceService(plugin)
        self.ready = False
        self.handlers = []
        if web is None:
            try:
                from astrbot.api import web
            except ImportError:
                web = None
        self.web = web

    def authorize(self):
        username = self.web.request.username
        # v4.27.5 authenticates extensions upstream but also permits scoped API keys.
        # This human administration surface requires the current Dashboard account.
        expected = self.plugin.context.get_config().get('dashboard', {}).get('username')
        if not username or not expected or username != expected:
            raise PermissionError('需要使用当前 AstrBot 管理员账户登录')
        if not self.ready:
            raise RuntimeError('插件尚未就绪或已经卸载')

    def register(self):
        if self.web is None or not hasattr(self.plugin.context, 'register_web_api'):
            return False
        for endpoint, method in [('config','GET'),('config','POST'),('projects','GET'),('projects/register','POST'),
                                 ('projects/unregister','POST'),('projects/preview','GET'),('browse','GET'),
                                 ('groups','GET'),('providers','GET'),('sessions','GET'),('sessions/start','POST'),
                                 ('sessions/control','POST'),('reports/export','POST'),('reports/cleanup','POST'),
                                 ('sessions/purge','POST'),
                                 ('reports/download','GET'),('thumbnail','GET'),('prompt/preview','POST')]:
            async def handler(_endpoint=endpoint, _method=method):
                try:
                    self.authorize()
                    self.plugin._ensure_config()
                    body = await self.web.request.json() if _method == 'POST' else {}
                    if not isinstance(body, dict) or len(json.dumps(body)) > 1024 * 1024:
                        raise ValueError('请求内容过大或格式无效')
                    response = await self.dispatch(_endpoint, _method, body)
                    return self.web.json_response({'status':'ok', 'data':response}) if isinstance(response, (dict,list)) else response
                except PermissionError as exc:
                    return self.web.error_response(str(exc), status_code=403)
                except ConfigConflict as exc:
                    return self.web.error_response(str(exc), status_code=409)
                except (ValueError, FileNotFoundError) as exc:
                    return self.web.error_response(str(exc), status_code=400)
                except Exception as exc:
                    return self.web.error_response(str(exc), status_code=503)
            path = '/' + PLUGIN_NAME + '/' + endpoint
            self.plugin.context.register_web_api(path, handler, [method], 'Image Vote workspace')
            self.handlers.append(handler)
        return True

    async def dispatch(self, endpoint, method, body):
        query = self.web.request.query
        service = self.service
        if endpoint == 'config':
            return service.config_snapshot() if method == 'GET' else await service.save_config(body)
        if endpoint == 'projects':
            return service.projects()
        if endpoint == 'projects/register':
            return await service.register(body)
        if endpoint == 'projects/unregister':
            if body.get('confirmed') is not True:
                raise ValueError('请确认取消项目登记；原图不会删除')
            async with service.lock:
                self.plugin.project_registry.unregister(str(body.get('name','')))
            return service.projects()
        if endpoint == 'projects/preview':
            return await service.preview(query.get('name',''))
        if endpoint == 'browse':
            return await asyncio.to_thread(service.browse, query.get('root'), query.get('relative',''))
        if endpoint == 'groups':
            return await service.groups(refresh=query.get('refresh') == 'true')
        if endpoint == 'providers':
            getter = getattr(self.plugin.context, 'get_all_providers', None)
            return [{'id': p.meta().id, 'name': p.meta().id} for p in getter()] if callable(getter) else []
        if endpoint == 'sessions':
            return await service.sessions(int(query.get('limit',50)), int(query.get('offset',0)), query.get('group_id'),
                                          active=query.get('active') == 'true')
        if endpoint == 'sessions/start':
            return await service.start(body)
        if endpoint == 'sessions/control':
            if body.get('action') in {'finish','stop'} and body.get('confirmed') is not True:
                raise ValueError('结束或取消需要确认')
            return await service.control(body)
        if endpoint == 'reports/export':
            if not isinstance(body.get('regenerate_ai', False), bool):
                raise ValueError('regenerate_ai 必须为布尔值')
            return await service.export(str(body.get('session_id','')), body.get('regenerate_ai',False))
        if endpoint == 'reports/cleanup':
            if body.get('confirmed') is not True:
                raise ValueError('清理报告需要确认')
            session_id = str(body.get('session_id',''))
            async with service.lock:
                session = await self.plugin.store.get_session(session_id)
                if session is not None:
                    managed = await self.plugin.session_manager.active_for_group(session.group_id)
                    if managed and managed.session.id == session.id:
                        raise ValueError('该场次仍在运行或收尾，暂不能清理报告')
                await service.report_directory(session_id)
                # 生成与读取的互斥由应用层守卫裁决，群命令走同一条路径。
                result = self.plugin.application.cleanup_reports(session_id)
            return {'removed': result.removed, 'skipped': result.skipped}
        if endpoint == 'reports/download':
            session_id = query.get('session_id','')
            # 读取期间禁止清理删除目录；单文件下载还会先打开文件句柄。
            with service.reading(session_id):
                path = await service.report_directory(session_id)
                return await self.download(path)
        if endpoint == 'sessions/purge':
            if body.get('confirmed') is not True:
                raise ValueError('彻底删除需要确认')
            async with service.lock:
                result = await self.plugin.application.purge_session(str(body.get('session_id','')), confirm=True)
            return {
                'session_id': result.session_id,
                'short_id': result.short_id,
                'reports': result.reports,
                'votes': result.votes,
                'candidates': result.candidates,
            }
        if endpoint == 'thumbnail':
            return await self.thumbnail(query)
        if endpoint == 'prompt/preview':
            from .ai_summary_service import build_statistics_prompt
            return {'prompt': build_statistics_prompt({'project':'示例项目','score_min':self.plugin.settings.score_min,
                        'score_max':self.plugin.settings.score_max,'top_n':self.plugin.settings.ai_top_n,
                        'bottom_n':self.plugin.settings.ai_bottom_n,'total_valid_votes':0}, str(body.get('template','')))}
        raise ValueError('未知接口')

    async def thumbnail(self, query):
        session_id = query.get('session_id')
        if session_id:
            session = await self.plugin.store.get_session(session_id)
            if session is None:
                raise FileNotFoundError('会话不存在')
            candidates = await self.plugin.store.list_candidates(session_id)
            source_root = Path(session.project_path)
            candidate = next((c for c in candidates if c.id == query.get('candidate_id')), None)
        else:
            name = query.get('project','')
            options = self.plugin.project_service.resolve_options(name)
            snapshot = await service._inspect(name, options.get('recursive', self.plugin.settings.recursive_scan))
            source_root = Path(snapshot.project_path)
            index = int(query.get('index',1))
            candidate = next((c for c in snapshot.candidates if c.display_index == index), None)
        if candidate is None:
            raise FileNotFoundError('图片不存在')
        source = PathGuard(source_root).ensure_within(source_root/candidate.source_relative_path, allow_root=False)
        return {'image': await asyncio.to_thread(service.thumbnail_data_uri, source)}

    async def download(self, path):
        payload = json.loads((path/'data.json').read_text())
        if payload.get('report_mode') == 'single_html':
            target = PathGuard(path).resolve_child('index.html')
            handle = await asyncio.to_thread(target.open, 'rb')
            async def stream_file():
                try:
                    while True:
                        chunk = await asyncio.to_thread(handle.read, 256 * 1024)
                        if not chunk:
                            break
                        yield chunk
                finally:
                    await asyncio.to_thread(handle.close)
            return self.web.stream_response(stream_file(), content_type='text/html', headers={
                'Content-Disposition': "attachment; filename*=UTF-8''"+quote(path.name+'.html')})
        temporary = tempfile.TemporaryDirectory(prefix='image-vote-download-')
        archive = Path(temporary.name)/'report.zip'
        def pack():
            guard = PathGuard(path)
            with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED) as output:
                for file in path.rglob('*'):
                    if file.is_file() and not file.is_symlink() and not file.name.startswith('.'):
                        safe = guard.ensure_within(file, allow_root=False)
                        output.write(safe, str(file.relative_to(path)))
        try:
            await asyncio.to_thread(pack)
        except BaseException:
            temporary.cleanup()
            raise
        async def stream():
            try:
                with archive.open('rb') as file:
                    while True:
                        chunk = await asyncio.to_thread(file.read, 256 * 1024)
                        if not chunk:
                            break
                        yield chunk
            finally:
                temporary.cleanup()
        return self.web.stream_response(stream(), content_type='application/zip', headers={
            'Content-Disposition': "attachment; filename*=UTF-8''"+quote(path.name+'.zip')})

    async def close(self):
        self.ready = False
        await self.service.shutdown()
        # v4.27.5 has no public unregister method. Remove only this instance's handlers.
        registered = getattr(self.plugin.context, 'registered_web_apis', None)
        if isinstance(registered, list):
            registered[:] = [entry for entry in registered if entry[1] not in self.handlers]
