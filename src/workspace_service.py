"""Application-facing services for the authenticated Plugin Pages workspace."""
import asyncio
import base64
import copy
import hashlib
import inspect
import json
import os
import tempfile
import zipfile
from dataclasses import asdict
from pathlib import Path

from .ai_summary_service import build_statistics_prompt, build_summary_statistics
from .config import VoteConfig
from .logging_utils import get_logger
from .models import SessionStatus
from .path_guard import PathGuard
from .report_generator import REPORT_MARKER, PLUGIN_NAME
from .statistics_service import calculate_statistics


logger = get_logger()

class ConfigConflict(ValueError):
    pass


class WorkspaceService:
    def __init__(self, plugin):
        self.plugin = plugin
        self.lock = asyncio.Lock()
        self.group_cache = []
        self._groups_at = 0
        self.schema = json.loads((Path(__file__).resolve().parents[1] / '_conf_schema.json').read_text())

    def reading(self, session_id):
        """报告读取期间的互斥由应用层守卫持有：网页与群命令共用同一份状态。"""
        return self.app.report_activity.reading(session_id)

    @property
    def app(self):
        return self.plugin.application

    def config_snapshot(self):
        self.plugin._ensure_config()
        values = asdict(self.plugin.settings)
        revision = hashlib.sha256(json.dumps(values, sort_keys=True, default=list).encode()).hexdigest()
        return {'values': values, 'revision': revision, 'schema': self.schema}

    async def save_config(self, body):
        async with self.lock:
            snapshot = self.config_snapshot()
            if body.get('revision') != snapshot['revision']:
                raise ConfigConflict('配置已在其他页面更新，请重新读取后合并修改')
            changes = body.get('values')
            if not isinstance(changes, dict) or set(changes) - set(snapshot['values']):
                raise ValueError('配置包含未知字段')
            candidate = dict(snapshot['values'])
            candidate.update(changes)
            # Check JSON types before dataclass validation, especially bool vs int.
            for key, value in candidate.items():
                old = snapshot['values'][key]
                if isinstance(old, bool) and not isinstance(value, bool):
                    raise ValueError('%s 应为布尔值' % key)
                if isinstance(old, int) and not isinstance(old, bool) and (not isinstance(value, int) or isinstance(value, bool)):
                    raise ValueError('%s 应为整数' % key)
                if isinstance(old, str) and not isinstance(value, str):
                    raise ValueError('%s 应为文本' % key)
                if isinstance(old, (list, tuple)) and (not isinstance(value, (list, tuple)) or any(not isinstance(x, str) for x in value)):
                    raise ValueError('%s 应为文本列表' % key)
            VoteConfig.from_mapping(candidate)
            config_object = getattr(self.plugin, '_page_config_object', None)
            if config_object is None or not callable(getattr(config_object, 'save_config', None)):
                raise RuntimeError('当前实例未提供可写的 AstrBotConfig，请从 AstrBot 内置配置页保存')
            previous = copy.deepcopy(dict(config_object))
            config_path = getattr(config_object, 'config_path', None)
            before = None
            if config_path:
                try:
                    before = Path(config_path).read_bytes()
                except OSError:
                    before = None
            grouped = copy.deepcopy(previous)
            for name, group in self.schema.items():
                grouped.setdefault(name, {})
                if not isinstance(grouped[name], dict):
                    grouped[name] = {}
                for key in group['items']:
                    grouped.pop(key, None)
                    grouped[name][key] = candidate[key]
            conflicted = False
            try:
                config_object.clear()
                config_object.update(copy.deepcopy(grouped))
                saver = getattr(config_object, 'save_config_async', None)
                if callable(saver):
                    committed = await saver(grouped)
                    if committed is False:
                        conflicted = True
                        raise ConfigConflict('配置保存被更新的版本取代，请重新读取')
                else:
                    await asyncio.to_thread(config_object.save_config, grouped)
            except Exception:
                config_object.clear()
                config_object.update(previous)
                # 保存可能已经写过磁盘；既然接口报失败，磁盘必须回到保存前的状态，
                # 否则后续 _ensure_config 会把这份「没保存成功」的配置加载进来。
                if not conflicted and config_path:
                    self._restore_config_file(config_path, before)
                raise
            self.plugin._apply_config(grouped, source='插件工作区')
            return self.config_snapshot()

    @staticmethod
    def _restore_config_file(config_path, before):
        try:
            target = Path(config_path)
            current = target.read_bytes() if target.is_file() else None
            if current == before:
                return
            if before is None:
                target.unlink(missing_ok=True)
            else:
                temp = target.with_name(target.name + '.rollback')
                temp.write_bytes(before)
                os.replace(str(temp), str(target))
            logger.warning("配置保存失败，已回滚磁盘配置：%s", target)
        except OSError as exc:
            logger.error("配置保存失败且无法回滚磁盘配置：%s（%s）", config_path, exc)

    def projects(self):
        registry = self.plugin.project_registry.entries()
        names = sorted(set(self.plugin.project_service.list_projects()) | set(registry))
        result = []
        for name in names:
            try:
                path = self.plugin.project_service.resolve_project_path(name)
                error = None
            except (OSError, ValueError) as exc:
                path, error = None, str(exc)
            result.append({'name': name, 'path': str(path) if path else registry.get(name, {}).get('path'),
                           'source': 'registered' if name in registry else 'directory',
                           'settings': self.plugin.project_service.resolve_options(name), 'error': error})
        return result

    async def preview(self, name):
        settings = self.plugin.project_service.resolve_options(name)
        snapshot = await asyncio.to_thread(self.plugin.project_service.inspect, name, settings.get('recursive', self.plugin.settings.recursive_scan))
        interval = settings.get('interval_seconds', self.plugin.settings.default_interval_seconds)
        root = Path(self.plugin.settings.output_root).expanduser()
        parent = root
        while not parent.exists() and parent != parent.parent:
            parent = parent.parent
        return {'name': snapshot.project_name, 'count': len(snapshot.candidates), 'total_size': snapshot.total_size,
                'sort_mode': snapshot.sort_mode, 'warnings': list(snapshot.warnings),
                'invalid_files': list(snapshot.invalid_files),
                'first': [asdict(c) for c in snapshot.candidates[:6]],
                'last': [c.source_filename for c in snapshot.candidates[-5:]],
                'interval_seconds': interval, 'interval_source': 'project' if 'interval_seconds' in settings else 'default',
                'score_min': self.plugin.settings.score_min, 'score_max': self.plugin.settings.score_max,
                'estimated_seconds': max(0, len(snapshot.candidates) - 1) * interval + max(interval, self.plugin.settings.effective_final_grace_seconds),
                'output_writable': parent.is_dir() and os.access(parent, os.W_OK)}

    def browse(self, root=None, relative=''):
        settings = self.plugin.settings
        roots = {str(Path(p).expanduser().resolve()) for p in (settings.input_root, *settings.web_browse_roots)}
        roots.update(str(Path(v['path']).expanduser().resolve()) for v in self.plugin.project_registry.entries().values() if isinstance(v.get('path'), str))
        roots = sorted(p for p in roots if Path(p).is_dir())
        if root is None:
            return {'roots': roots, 'directories': []}
        if root not in roots:
            raise PermissionError('目录不在允许浏览的根目录中')
        guard = PathGuard(Path(root))
        path = guard.resolve_child(relative or '.', allow_root=True)
        children = []
        for item in sorted(path.iterdir(), key=lambda x: x.name.casefold()):
            if item.is_dir() and not item.is_symlink() and not item.name.startswith('.'):
                children.append({'name': item.name, 'relative': str(item.relative_to(Path(root)))})
            if len(children) >= 500:
                break
        return {'roots': roots, 'root': root, 'relative': str(path.relative_to(Path(root))),
                'path': str(path), 'directories': children}

    async def register(self, body):
        async with self.lock:
            name = str(body.get('name', '')).strip()
            old_name = body.get('old_name')
            if old_name is not None and not isinstance(old_name, str):
                raise ValueError('原项目名应为文本')
            if old_name != name and name in self.plugin.project_registry.names():
                raise ValueError('项目名已登记')
            interval, recursive = body.get('interval_seconds'), body.get('recursive')
            if interval is not None and (not isinstance(interval, int) or isinstance(interval, bool) or interval < 1):
                raise ValueError('项目发送间隔应为正整数')
            if recursive is not None and not isinstance(recursive, bool):
                raise ValueError('递归选项应为布尔值')
            self.plugin.project_registry.register(name, Path(str(body.get('path', ''))), interval, recursive,
                                                  str(body.get('description', '')), drop_name=old_name)
            return self.projects()

    async def groups(self, refresh=False):
        now = asyncio.get_running_loop().time()
        if not refresh and now - self._groups_at < 60:
            return self.group_cache
        groups = []
        manager = getattr(self.plugin.context, 'platform_manager', None)
        instances = manager.get_insts() if manager and hasattr(manager, 'get_insts') else []
        for platform in instances:
            meta = platform.meta()
            if meta.name != 'aiocqhttp':
                continue
            client = platform.get_client()
            try:
                response = await asyncio.wait_for(client.call_action('get_group_list'), timeout=10)
                for item in response:
                    group_id = str(item['group_id'])
                    if self.plugin.settings.allowed_group_ids and group_id not in self.plugin.settings.allowed_group_ids:
                        continue
                    groups.append({'id': group_id, 'name': str(item.get('group_name') or group_id),
                                   'platform': meta.id, 'umo': '%s:GroupMessage:%s' % (meta.id, group_id)})
            except Exception:
                continue
        self.group_cache, self._groups_at = groups, now
        return groups

    async def sessions(self, limit=50, offset=0, group_id=None, active=False):
        if active:
            incomplete = await self.plugin.store.list_incomplete_sessions()
            result = {'total':len(incomplete), 'sessions':incomplete}
        else:
            result = await self.plugin.store.list_sessions(limit, offset, group_id)
        output = []
        for session in result['sessions']:
            row = asdict(session)
            row.pop('project_path', None)
            row.pop('umo', None)
            row.pop('output_path', None)
            candidates = await self.plugin.store.list_candidates(session.id)
            votes = await self.plugin.store.list_votes(session.id)
            row['sent_count'] = sum(c.send_status.value == 'sent' for c in candidates)
            row['vote_count'] = len(votes)
            row['participant_count'] = len({v.voter_id for v in votes})
            managed = await self.plugin.session_manager.active_for_group(session.group_id)
            row['seconds_until_next'] = managed.control.remaining_seconds() if managed and managed.session.id == session.id else None
            available = bool(session.output_path and (Path(session.output_path)/'index.html').is_file())
            error = None
            if session.error_message and session.error_message.startswith('report generation failed:'):
                error = session.error_message
            row['report_available'] = available
            row['report_state'] = ('generating' if self.app.report_activity.exporting(session.id)
                                   or (managed and session.status == SessionStatus.COMPLETED)
                                   else 'failed' if error else 'ready' if available else 'missing')
            row['report_error'] = error
            row['active_candidate'] = next(({'id': c.id, 'name': c.display_title, 'index': c.display_index} for c in candidates if c.id == session.active_candidate_id), None)
            output.append(row)
        return {'total': result['total'], 'sessions': output}

    async def start(self, body):
        async with self.lock:
            groups = await self.groups()
            group = next((g for g in groups if g['umo'] == body.get('umo')), None)
            if group is None:
                raise PermissionError('请选择当前机器人可访问且已允许的群')
            previous = await self.plugin.store.latest_session_for_group(group['id'])
            if previous and previous.status in {SessionStatus.PREPARING, SessionStatus.RUNNING, SessionStatus.PAUSED, SessionStatus.FINALIZING}:
                raise ValueError('这个群已有未结束的投票，请先继续、结束或取消')
            session = await self.app.start_session(group['id'], group['umo'], str(body.get('project', '')))
            return {'session_id': session.id}

    async def control(self, body):
        async with self.lock:
            session = await self.plugin.store.get_session(str(body.get('session_id', '')))
            action = body.get('action')
            if session is None or action not in {'pause', 'resume', 'finish', 'stop'}:
                raise ValueError('无效会话或动作')
            managed = await self.plugin.session_manager.active_for_group(session.group_id)
            if managed and managed.session.id != session.id:
                raise ValueError('该群当前已运行另一场投票，请刷新')
            if managed is None:
                latest = await self.plugin.store.latest_session_for_group(session.group_id)
                if latest is None or latest.id != session.id:
                    raise ValueError('该场次已不是当前群的最新会话，请刷新')
            if self.plugin.settings.allowed_group_ids and session.group_id not in self.plugin.settings.allowed_group_ids:
                raise PermissionError('当前群不在白名单内')
            if session.status not in {SessionStatus.RUNNING, SessionStatus.PAUSED}:
                raise ValueError('当前状态不能执行此操作')
            await getattr(self.app, action)(session.group_id)
            return {'session_id': session.id}

    async def export(self, session_id, regenerate_ai=False):
        await self.app.start_report_export(session_id, regenerate_ai=regenerate_ai)
        return {'session_id': session_id, 'state': 'generating'}

    async def report_directory(self, session_id):
        session = await self.plugin.store.get_session(session_id)
        if session is None or not session.output_path:
            raise FileNotFoundError('该场次尚未生成报告')
        path = PathGuard(Path(self.plugin.settings.output_root)).ensure_report_directory(Path(session.output_path), REPORT_MARKER, PLUGIN_NAME)
        marker = json.loads((path/REPORT_MARKER).read_text())
        if marker.get('session_id') != session_id:
            raise PermissionError('报告与场次不匹配')
        return path

    async def shutdown(self):
        await self.app.report_activity.shutdown()
