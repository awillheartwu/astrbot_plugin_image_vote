"""报告读取、生成与清理的统一互斥，网页工作区与群命令共用同一个实例。

三个状态互斥：正在生成（导出占位或后台任务）、正在读取（下载或预览）、正在清理。
所有状态变更都是同步的，因此在 asyncio 单线程里天然原子；跨入口的竞争
（网页在下载、群命令在清理，或网页在清理、群命令在导出）由同一份状态裁决。
"""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
from typing import Dict, Iterator, List, Optional


class ReportBusyError(ValueError):
    """报告正在生成、下载或清理，当前操作暂不可执行。"""


class ReportActivity:
    def __init__(self) -> None:
        self._tasks: Dict[str, Optional[asyncio.Task]] = {}
        self._readers: Dict[str, int] = {}
        self._cleaning: set = set()

    def exporting(self, session_id) -> bool:
        """是否有导出占位或生成任务（界面用它显示「生成中」）。"""
        return str(session_id) in self._tasks

    def busy(self, session_id) -> bool:
        key = str(session_id)
        return key in self._tasks or bool(self._readers.get(key)) or key in self._cleaning

    def pending(self) -> List[asyncio.Task]:
        return [task for task in self._tasks.values() if isinstance(task, asyncio.Task)]

    def reserve_export(self, session_id) -> None:
        """占位后才可以开始耗时的导出；占位在读库等 await 之前完成。"""
        key = str(session_id)
        if key in self._tasks:
            raise ReportBusyError('该报告正在生成')
        if self._readers.get(key):
            raise ReportBusyError('报告正在下载或预览，请稍后重试')
        if key in self._cleaning:
            raise ReportBusyError('报告正在清理，请稍后重试')
        self._tasks[key] = None

    def attach_task(self, session_id, task: asyncio.Task) -> None:
        self._tasks[str(session_id)] = task

    def release_export(self, session_id) -> None:
        self._tasks.pop(str(session_id), None)

    @contextmanager
    def reading(self, session_id) -> Iterator[None]:
        key = str(session_id)
        if key in self._tasks:
            raise ReportBusyError('报告正在生成，请稍后重试')
        if key in self._cleaning:
            raise ReportBusyError('报告正在清理，请稍后重试')
        self._readers[key] = self._readers.get(key, 0) + 1
        try:
            yield
        finally:
            remaining = self._readers.get(key, 1) - 1
            if remaining > 0:
                self._readers[key] = remaining
            else:
                self._readers.pop(key, None)

    @contextmanager
    def cleaning(self, session_id) -> Iterator[None]:
        key = str(session_id)
        if key in self._tasks:
            raise ReportBusyError('报告正在生成，暂不能清理')
        if self._readers.get(key):
            raise ReportBusyError('报告正在下载或预览，请稍后重试')
        if key in self._cleaning:
            raise ReportBusyError('报告正在清理，请稍后重试')
        self._cleaning.add(key)
        try:
            yield
        finally:
            self._cleaning.discard(key)

    async def shutdown(self) -> None:
        tasks = self.pending()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()
