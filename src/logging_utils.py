from __future__ import annotations

import importlib
import logging
from typing import Optional


PLUGIN_LOGGER_NAME = "astrbot_plugin_image_vote"


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """取插件专用 logger，让日志进 AstrBot 面板并按插件名加前缀。

    AstrBot 4.27+ 的 astrbot.api.logger 是按调用方动态解析的代理对象，不是 logging.Logger；
    插件专用 logger 由 LogManager.get_plugin_logger 提供，它同时挂着面板的日志队列 handler。
    取不到时退回普通 logger，保证本地测试可用。
    """
    logger_name = name or PLUGIN_LOGGER_NAME
    try:
        log_module = importlib.import_module("astrbot.core.log")
        manager = getattr(log_module, "LogManager", None)
        resolver = getattr(manager, "get_plugin_logger", None)
        if callable(resolver):
            resolved = resolver(logger_name)
            if isinstance(resolved, logging.Logger):
                return resolved
    except Exception:
        pass
    try:
        api = importlib.import_module("astrbot.api")
        upstream = getattr(api, "logger", None)
    except Exception:
        upstream = None
    if isinstance(upstream, logging.Logger):
        return upstream.getChild(logger_name)
    return logging.getLogger(logger_name)
