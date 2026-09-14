from __future__ import annotations

from pathlib import Path
from typing import Any, List, Optional

from .reply_resolver import ReplyPayload


class AstrBotAdapter:
    """The only module that builds AstrBot message chains or reads Reply components."""

    def __init__(self, context: Any):
        self.context = context

    async def send_vote_message(self, umo: str, text: str, image_path: Path) -> Optional[str]:
        try:
            from astrbot.api.event import MessageChain

            chain = MessageChain().message(text).file_image(str(image_path))
        except (ImportError, AttributeError):
            from astrbot.api.message_components import Image, Plain

            chain = self._message_chain([Plain(text), Image.fromFileSystem(str(image_path))])
        result = await self.context.send_message(umo, chain)
        if result is False:
            raise RuntimeError("AstrBot could not resolve unified message origin")
        return None

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
