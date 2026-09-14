from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any, List, Optional, Tuple

from .logging_utils import PLUGIN_LOGGER_NAME as PLUGIN_NAME, get_logger

logger = get_logger()

ASTRBOT_AVAILABLE = False
FILTER_SOURCE: Optional[str] = None
EVENT_MESSAGE_TYPE_SOURCE: Optional[str] = None
DATA_DIR_SOURCE: Optional[str] = None
IMPORT_ATTEMPTS: List[str] = []


class _NoopFilter:
    """本地没有 AstrBot 时使用，保证核心模块仍可导入和跑单元测试。"""

    def command(self, *args, **kwargs):
        return lambda function: function

    def event_message_type(self, *args, **kwargs):
        return lambda function: function


class _FallbackEventMessageType:
    GROUP_MESSAGE = "GROUP_MESSAGE"
    ALL = "ALL"


def _record(label: str, exc: BaseException) -> str:
    message = "%s -> %s: %s" % (label, type(exc).__name__, exc)
    IMPORT_ATTEMPTS.append(message)
    return message


def _load_filter() -> Tuple[Optional[Any], Optional[str]]:
    """按 4.x 的几种真实布局依次尝试，返回 (filter 对象, 来源描述)。"""
    candidates = (
        ("astrbot.api.event", "filter"),
        ("astrbot.api.event.filter", None),
        ("astrbot.api.filter", "filter"),
        ("astrbot.core.star.filter", "filter"),
    )
    for module_name, attribute in candidates:
        label = module_name if attribute is None else "%s.%s" % (module_name, attribute)
        try:
            module = importlib.import_module(module_name)
            value = module if attribute is None else getattr(module, attribute)
        except Exception as exc:
            _record(label, exc)
            continue
        if value is not None:
            return value, label
    return None, None


def _load_event_message_type(filter_object: Any) -> Tuple[Optional[Any], Optional[str]]:
    candidates = []
    if filter_object is not None:
        candidates.append((getattr(filter_object, "EventMessageType", None), "filter.EventMessageType"))
    for module_name in (
        "astrbot.api.event",
        "astrbot.api.event.filter",
        "astrbot.core.star.filter.event_message_type",
        "astrbot.core.star.filter",
        "astrbot.core.star.filter.event_type",
    ):
        try:
            module = importlib.import_module(module_name)
        except Exception as exc:
            _record(module_name, exc)
            continue
        for attribute in ("EventMessageType", "EventType"):
            candidates.append((getattr(module, attribute, None), "%s.%s" % (module_name, attribute)))
    for value, label in candidates:
        if value is not None:
            return value, label
    return None, None


def _load_star() -> Tuple[Optional[Any], Optional[Any]]:
    try:
        star_module = importlib.import_module("astrbot.api.star")
    except Exception as exc:
        _record("astrbot.api.star", exc)
        return None, None
    star_class = getattr(star_module, "Star", None)
    register = getattr(star_module, "register", None)
    if register is None:
        register = lambda *args, **kwargs: (lambda plugin_class: plugin_class)
    return star_class, register


_FILTER_OBJECT, FILTER_SOURCE = _load_filter()

if _FILTER_OBJECT is not None:
    _STAR_CLASS, register = _load_star()
    if _STAR_CLASS is not None:
        ASTRBOT_AVAILABLE = True
        Star = _STAR_CLASS
    else:
        class Star:
            def __init__(self, context: Any = None, config: Any = None):
                self.context = context

    EventMessageType, EVENT_MESSAGE_TYPE_SOURCE = _load_event_message_type(_FILTER_OBJECT)
    filter = _FILTER_OBJECT
    if EventMessageType is None:
        EventMessageType = _FallbackEventMessageType()
else:
    Star = type("Star", (object,), {"__init__": lambda self, *args, **kwargs: None})
    register = lambda *args, **kwargs: (lambda plugin_class: plugin_class)
    filter = _NoopFilter()
    EventMessageType = _FallbackEventMessageType()


def compat_report() -> str:
    parts = [
        "astrbot=%s" % ("yes" if ASTRBOT_AVAILABLE else "no"),
        "filter=%s" % (FILTER_SOURCE or "missing"),
        "event_message_type=%s" % (EVENT_MESSAGE_TYPE_SOURCE or "missing"),
        "data_dir=%s" % (DATA_DIR_SOURCE or "pending"),
    ]
    return ", ".join(parts)


def get_event_text(event: Any) -> str:
    value = getattr(event, "message_str", None)
    if isinstance(value, str):
        return value
    return str(getattr(event, "message", "") or "")


def get_sender_id(event: Any) -> str:
    for name in ("get_sender_id",):
        method = getattr(event, name, None)
        if callable(method):
            try:
                value = method()
            except Exception:
                value = None
            if value:
                return str(value)
    sender = getattr(getattr(event, "message_obj", None), "sender", None)
    value = getattr(sender, "user_id", None) or getattr(sender, "sender_id", None) or sender
    return str(value or "")


def get_sender_name(event: Any) -> str:
    for name in ("get_sender_name", "sender_name"):
        attribute = getattr(event, name, None)
        if callable(attribute):
            try:
                value = attribute()
            except Exception:
                value = None
        else:
            value = attribute
        if value:
            return str(value)
    sender = getattr(getattr(event, "message_obj", None), "sender", None)
    return str(getattr(sender, "nickname", None) or getattr(sender, "card", None) or "")


def get_message_id(event: Any) -> str:
    message_obj = getattr(event, "message_obj", None)
    value = getattr(message_obj, "message_id", None) or getattr(event, "message_id", None)
    return str(value or "")


def get_sender_display_name(event: Any) -> str:
    """投票人显示名：优先 QQ 昵称，其次群名片。

    AstrBot 的转换层用的是 card or nickname（群名片优先），而群里同一人常把名片设成
    符号而昵称才是常用名，所以这里反过来读原始事件的 nickname。
    """
    raw = getattr(getattr(event, "message_obj", None), "raw_message", None)
    sender = None
    if isinstance(raw, dict):
        sender = raw.get("sender")
    elif raw is not None and hasattr(raw, "get"):
        try:
            sender = raw.get("sender")
        except Exception:
            sender = None
    if isinstance(sender, dict):
        for key in ("nickname", "card"):
            value = sender.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return get_sender_name(event)


def get_self_id(event: Any) -> str:
    message_obj = getattr(event, "message_obj", None)
    value = getattr(message_obj, "self_id", None) or getattr(event, "self_id", None)
    return str(value or "")


def _sender_role(event: Any) -> str:
    for name in ("is_admin", "is_admin_user"):
        method = getattr(event, name, None)
        if callable(method):
            try:
                return "admin" if method() else "member"
            except Exception:
                continue
    sender = getattr(getattr(event, "message_obj", None), "sender", None)
    return str(getattr(sender, "role", "") or "").lower()


def is_admin_event(event: Any) -> bool:
    role = _sender_role(event)
    return role in {"admin", "owner", "root"}


def get_group_id(event: Any) -> str:
    for name in ("get_group_id", "group_id"):
        value = getattr(event, name, None)
        if callable(value):
            try:
                value = value()
            except Exception:
                continue
        if value is not None:
            return str(value)
    message_obj = getattr(event, "message_obj", None)
    return str(getattr(message_obj, "group_id", "") or "")


def get_unified_message_origin(event: Any) -> str:
    for name in ("unified_msg_origin", "session_id"):
        value = getattr(event, name, None)
        if value:
            return str(value)
    return ""


def get_plugin_data_dir(context: Any, fallback_root: Path) -> Path:
    """优先使用框架提供的 StarTools.get_data_dir(plugin_name)。"""
    global DATA_DIR_SOURCE
    try:
        star_module = importlib.import_module("astrbot.api.star")
    except Exception:
        star_module = None
    if star_module is not None:
        tools = getattr(star_module, "StarTools", None)
        getter = getattr(tools, "get_data_dir", None) if tools is not None else None
        if callable(getter):
            for args in ((PLUGIN_NAME,), ()):
                try:
                    value = getter(*args)
                except Exception as exc:
                    _record("StarTools.get_data_dir%r" % (args,), exc)
                    continue
                if value:
                    DATA_DIR_SOURCE = "StarTools.get_data_dir"
                    return Path(value)
    for name in ("get_plugin_data_dir", "get_data_dir"):
        method = getattr(context, name, None)
        if not callable(method):
            continue
        try:
            value = method(PLUGIN_NAME)
        except TypeError:
            try:
                value = method()
            except Exception:
                continue
        except Exception:
            continue
        if value:
            DATA_DIR_SOURCE = "context.%s" % name
            return Path(value)
    DATA_DIR_SOURCE = "fallback"
    return fallback_root / "plugin_data" / PLUGIN_NAME
