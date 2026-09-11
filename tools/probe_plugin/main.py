"""现场探针插件：只打印，不回复。

安装：把本目录复制/重命名为 <AstrBot data>/plugins/astrbot_plugin_image_vote_probe
用法：在测试群发一条「引用任意消息 + 4」，然后查看容器日志中的 [IMAGE_VOTE_PROBE] 行。
"""

from __future__ import annotations

from typing import Any

from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register

try:
    EventMessageType = filter.EventMessageType
except AttributeError:  # 旧版本把枚举放在模块级别
    from astrbot.api.event import EventMessageType


TAG = "[IMAGE_VOTE_PROBE]"
_DIR_DUMPED = False


def _dump(label: str, value: Any) -> None:
    try:
        print("%s %s = %r" % (TAG, label, value), flush=True)
    except Exception as exc:  # 任何 repr 异常都不能影响事件处理
        print("%s %s = <repr 失败: %s>" % (TAG, label, exc), flush=True)


def _dump_component(index: int, component: Any) -> None:
    cls = component.__class__
    print(
        "%s   [%d] class=%s module=%s mro=%s"
        % (TAG, index, cls.__name__, getattr(cls, "__module__", "?"), [item.__name__ for item in cls.__mro__[:3]]),
        flush=True,
    )
    try:
        _dump("      vars", vars(component))
    except TypeError:
        _dump("      repr", component)
    for attribute in ("type", "id", "message_str", "text", "chain", "data", "url", "file", "name", "qq", "sender_id"):
        if not hasattr(component, attribute):
            continue
        try:
            _dump("      ." + attribute, getattr(component, attribute))
        except Exception as exc:
            _dump("      ." + attribute, "<读取失败: %s>" % exc)


@register("astrbot_plugin_image_vote_probe", "AstrBot Image Vote", "图片投票 API 探针", "0.0.1")
class ImageVoteProbePlugin(Star):
    def __init__(self, context: Context, config: Any = None):
        super().__init__(context)
        print("%s 插件初始化" % TAG, flush=True)
        _dump("config 类型", type(config))
        _dump("config 值", config)
        _dump("context 类型", type(context))
        _dump("context 成员", sorted(name for name in dir(context) if not name.startswith("_")))

    @filter.event_message_type(EventMessageType.GROUP_MESSAGE)
    async def on_group_message(self, event: AstrMessageEvent):
        global _DIR_DUMPED
        message_obj = getattr(event, "message_obj", None)
        components = getattr(message_obj, "message", None) or []
        if not _DIR_DUMPED:
            _DIR_DUMPED = True
            _dump("event 成员", sorted(name for name in dir(event) if not name.startswith("_")))
            _dump("message_obj 类型", type(message_obj))
            _dump("message_obj 成员", sorted(name for name in dir(message_obj) if not name.startswith("_")))
        if not any(component.__class__.__name__ == "Reply" for component in components):
            return None
        print("%s ---- 收到带引用的群消息 ----" % TAG, flush=True)
        _dump("message_str", getattr(event, "message_str", None))
        _dump("unified_msg_origin", getattr(event, "unified_msg_origin", None))
        _dump("message_id", getattr(message_obj, "message_id", None))
        _dump("group_id", getattr(message_obj, "group_id", None))
        _dump("sender", getattr(message_obj, "sender", None))
        _dump("raw_message", getattr(message_obj, "raw_message", None))
        for index, component in enumerate(components):
            _dump_component(index, component)
        return None
