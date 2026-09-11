from __future__ import annotations

import importlib
import logging
from typing import Optional


PLUGIN_LOGGER_NAME = "astrbot_plugin_image_vote"


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """AstrBot 会按 logger 名字在日志里加 [插件名] 前缀，这里统一用一个名字。"""
    logger_name = name or PLUGIN_LOGGER_NAME
    try:
        api = importlib.import_module("astrbot.api")
        upstream = getattr(api, "logger", None)
    except Exception:
        upstream = None
    if isinstance(upstream, logging.Logger):
        return upstream.getChild(logger_name)
    return logging.getLogger(logger_name)
