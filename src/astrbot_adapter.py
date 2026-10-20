from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional, Sequence

from .logging_utils import get_logger
from .models import SendReceipt
from .reply_resolver import ReplyPayload
from .vote_timing import sequence, timestamp

logger = get_logger()


class AstrBotAdapter:
    """The only module that builds AstrBot message chains or reads Reply components."""

    def __init__(self, context: Any):
        self.context = context
        self._receipt_warning_logged = False

    def _warn_receipt(self, message, *args):
        if not self._receipt_warning_logged:
            logger.warning(message, *args)
            self._receipt_warning_logged = True

    @staticmethod
    def _action_data(response):
        if not isinstance(response, dict):
            return {}
        data = response.get("data")
        return data if isinstance(data, dict) else response

    async def send_vote_message(self, umo: str, text: str, image_paths: Sequence[Path]) -> SendReceipt:
        parts = umo.split(":", 2)
        getter = getattr(self.context, "get_platform_inst", None)
        platform = getter(parts[0]) if len(parts) == 3 and callable(getter) else None
        if (platform is not None and platform.meta().name == "aiocqhttp" and parts[1] == "GroupMessage"
                and callable(getattr(getattr(platform, "bot", None), "call_action", None))):
            group_id = parts[2].split("_")[-1]
            if group_id.isdecimal():
                return await self._send_onebot_vote(platform.bot, int(group_id), text, image_paths)
        try:
            from astrbot.api.event import MessageChain

            chain = MessageChain().message(text)
            for path in image_paths:
                chain = chain.file_image(str(path))
        except (ImportError, AttributeError):
            from astrbot.api.message_components import Image, Plain

            chain = self._message_chain(
                [Plain(text), *[Image.fromFileSystem(str(path)) for path in image_paths]]
            )
        result = await self.context.send_message(umo, chain)
        if result is False:
            raise RuntimeError("AstrBot could not resolve unified message origin")
        self._warn_receipt("当前平台未提供发图消息时间/顺序，使用本机确认时间判断图片边界")
        return SendReceipt(datetime.now(timezone.utc).isoformat())

    async def _send_onebot_vote(self, bot, group_id, text, image_paths) -> SendReceipt:
        """Use the same OneBot image payload, retaining the send API's message identity."""
        def build_segments():
            return [{"type": "text", "data": {"text": text}}] + [
                {"type": "image", "data": {
                    "file": "base64://" + base64.b64encode(Path(path).read_bytes()).decode("ascii")
                }} for path in image_paths
            ]

        segments = await asyncio.to_thread(build_segments)
        response = await bot.call_action("send_group_msg", group_id=group_id, message=segments)
        acknowledged_at = datetime.now(timezone.utc).isoformat()
        if isinstance(response, dict) and (response.get("status") == "failed" or response.get("retcode", 0) != 0):
            raise RuntimeError("OneBot send_group_msg failed")
        response = self._action_data(response)
        message_id = response.get("message_id")
        details = response
        if message_id is not None:
            try:
                details = await asyncio.wait_for(bot.call_action("get_msg", message_id=message_id), timeout=2)
                details = self._action_data(details)
            except Exception as exc:
                # The image was already sent. A metadata lookup failure must never resend it.
                self._warn_receipt("发图成功，但读取消息时间/顺序失败，使用本机确认时间：%s", type(exc).__name__)
                details = response
        else:
            self._warn_receipt("发图成功但未返回消息 ID，使用本机确认时间判断图片边界")
        message_time = timestamp(details.get("time"))
        message_sequence = sequence(details.get("real_seq"))
        if message_time is None or message_sequence is None:
            self._warn_receipt("发图回执缺少有效时间或真实序号，使用本机确认时间保守判断图片边界")
        else:
            self._receipt_warning_logged = False
        return SendReceipt(
            acknowledged_at,
            str(message_id) if message_id is not None else None,
            message_time,
            message_sequence,
        )

    async def send_text(self, umo: str, text: str) -> None:
        """纯文本通知（自动暂停提示等），不附带图片。"""
        try:
            from astrbot.api.event import MessageChain

            chain = MessageChain().message(text)
        except (ImportError, AttributeError):
            from astrbot.api.message_components import Plain

            chain = self._message_chain([Plain(text)])
        result = await self.context.send_message(umo, chain)
        if result is False:
            raise RuntimeError("AstrBot could not resolve unified message origin")

    async def send_file(self, umo: str, path: Path, name: Optional[str] = None) -> None:
        """把文件作为附件发送（单文件报告用），不同 AstrBot 版本的组件名不同，逐层降级。"""
        label = name or path.name
        try:
            from astrbot.api.message_components import File, Plain

            chain = self._message_chain([Plain(label), File(name=label, file=str(path))])
        except (ImportError, AttributeError, TypeError) as exc:
            raise RuntimeError("当前 AstrBot 版本不支持发送文件组件：%s" % exc) from exc
        result = await self.context.send_message(umo, chain)
        if result is False:
            raise RuntimeError("AstrBot could not resolve unified message origin")

    @staticmethod
    def _message_chain(components: List[Any]) -> Any:
        """把组件列表装成 MessageChain。

        直接传 list 会在平台发送路径上炸（没有 .chain 属性），AstrBot 单文件报告发送
        失败就是这个原因。
        """
        from astrbot.api.event import MessageChain

        try:
            return MessageChain(chain=list(components))
        except TypeError:
            chain = MessageChain()
            chain.chain = list(components)
            return chain

    def resolve_reply(self, event: Any) -> Optional[ReplyPayload]:
        message_obj = getattr(event, "message_obj", None)
        components = getattr(message_obj, "message", None) or []
        reply = next((item for item in components if item.__class__.__name__ == "Reply"), None)
        if reply is None:
            return None
        chain_text = self._chain_text(getattr(reply, "chain", None))
        message_str = str(getattr(reply, "message_str", "") or getattr(reply, "text", "") or "")
        return ReplyPayload(
            message_str=message_str,
            chain_text=chain_text,
            message_id=str(getattr(reply, "id", "") or "") or None,
        )

    @staticmethod
    def _chain_text(chain: Any) -> str:
        chain = getattr(chain, "chain", chain)
        if not isinstance(chain, (list, tuple)):
            return ""
        texts: List[str] = []
        for component in chain:
            text = getattr(component, "text", None)
            if isinstance(text, str):
                texts.append(text)
        return "".join(texts)
