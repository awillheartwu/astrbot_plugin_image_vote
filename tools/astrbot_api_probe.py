"""在现场 AstrBot 环境运行本脚本，一次性收集兼容性事实。

用法（在 AstrBot 容器内执行）：

    python3 <插件目录>/tools/astrbot_api_probe.py

脚本只读取和打印信息：不发送消息、不写文件、不修改配置、不联网。
本地没有安装 AstrBot 时所有导入都会失败，这是预期结果。
"""

from __future__ import annotations

import dataclasses
import importlib
import inspect
import re
import sys
import traceback
from pathlib import Path


NEEDLES = (
    "_conf_schema.json",
    "get_data_dir",
    "plugin_data",
    "class StarTools",
    "config=config",
    "stop_event",
    "def send_message",
    "file_image",
)

EXPECTED_EVENT_API = (
    "message_str",
    "message_obj",
    "unified_msg_origin",
    "message_id",
    "is_admin",
    "is_admin_user",
    "get_sender_id",
    "get_sender_name",
    "get_group_id",
    "group_id",
    "plain_result",
    "stop_event",
    "send",
    "role",
)


def section(title: str) -> None:
    print("\n" + "=" * 74)
    print("## " + title)
    print("=" * 74)


def step(name: str, func) -> None:
    section(name)
    try:
        func()
    except Exception:
        print("!! 本节失败，继续下一节：")
        traceback.print_exc()


def describe(label: str, value) -> None:
    print("%-42s %r" % (label + ":", value))


def signature(label: str, value) -> None:
    try:
        print("%-42s %s" % (label + ":", inspect.signature(value)))
    except (TypeError, ValueError) as exc:
        print("%-42s <无法获取签名: %s>" % (label + ":", exc))


def probe_version() -> None:
    astrbot = importlib.import_module("astrbot")
    describe("astrbot module file", getattr(astrbot, "__file__", None))
    describe("astrbot __version__", getattr(astrbot, "__version__", None))
    try:
        from importlib.metadata import version

        describe("package metadata version", version("astrbot"))
    except Exception as exc:
        describe("package metadata version", "<不可用: %s>" % exc)


def probe_event_api() -> None:
    module = importlib.import_module("astrbot.api.event")
    print("astrbot.api.event 导出：%s" % ", ".join(sorted(n for n in dir(module) if not n.startswith("_"))))
    event_cls = getattr(module, "AstrMessageEvent", None)
    if event_cls is None:
        print("!! 找不到 AstrMessageEvent")
        return
    describe("AstrMessageEvent", event_cls)
    signature("AstrMessageEvent.__init__", event_cls.__init__)
    fields = []
    if dataclasses.is_dataclass(event_cls):
        fields = [item.name for item in dataclasses.fields(event_cls)]
        print("dataclass 字段：%s" % ", ".join(fields))
    missing = [name for name in EXPECTED_EVENT_API if not hasattr(event_cls, name) and name not in fields]
    print("插件依赖但缺失的属性/方法：%s" % (", ".join(missing) if missing else "无"))
    filter_obj = getattr(module, "filter", None)
    if filter_obj is not None:
        signature("filter.command", getattr(filter_obj, "command", None))
        signature("filter.event_message_type", getattr(filter_obj, "event_message_type", None))
        event_type = getattr(filter_obj, "EventMessageType", None)
        if event_type is not None:
            describe("filter.EventMessageType.GROUP_MESSAGE", getattr(event_type, "GROUP_MESSAGE", None))


def probe_message_chain() -> None:
    event_module = importlib.import_module("astrbot.api.event")
    chain_cls = getattr(event_module, "MessageChain", None)
    describe("astrbot.api.event.MessageChain", chain_cls)
    if chain_cls is not None:
        signature("MessageChain.message", getattr(chain_cls, "message", None))
        signature("MessageChain.file_image", getattr(chain_cls, "file_image", None))
        signature("MessageChain.image", getattr(chain_cls, "image", None))
    try:
        components = importlib.import_module("astrbot.api.message_components")
    except ImportError as exc:
        describe("astrbot.api.message_components", "<导入失败: %s>" % exc)
        return
    print("组件类：%s" % ", ".join(sorted(n for n in dir(components) if n[:1].isupper())))
    image_cls = getattr(components, "Image", None)
    if image_cls is not None:
        signature("Image.__init__", image_cls.__init__)
        for name in ("fromFileSystem", "fromURL", "fromBytes", "fromBase64"):
            if hasattr(image_cls, name):
                signature("Image.%s" % name, getattr(image_cls, name))
    reply_cls = getattr(components, "Reply", None)
    describe("Reply 类", reply_cls)
    if reply_cls is not None:
        describe("Reply __module__", getattr(reply_cls, "__module__", None))
        signature("Reply.__init__", reply_cls.__init__)
        if dataclasses.is_dataclass(reply_cls):
            print("Reply dataclass 字段：%s" % ", ".join(item.name for item in dataclasses.fields(reply_cls)))


def probe_star_and_data_dir() -> None:
    star_module = importlib.import_module("astrbot.api.star")
    print("astrbot.api.star 导出：%s" % ", ".join(sorted(n for n in dir(star_module) if not n.startswith("_"))))
    star_cls = getattr(star_module, "Star", None)
    if star_cls is not None:
        signature("Star.__init__", star_cls.__init__)
    tools_cls = getattr(star_module, "StarTools", None)
    describe("StarTools", tools_cls)
    if tools_cls is not None:
        for name in ("get_data_dir", "get_config", "get_plugin_path"):
            if hasattr(tools_cls, name):
                signature("StarTools.%s" % name, getattr(tools_cls, name))
        if hasattr(tools_cls, "get_data_dir"):
            for args in ((), ("astrbot_plugin_image_vote",)):
                try:
                    describe("StarTools.get_data_dir%r" % (args,), tools_cls.get_data_dir(*args))
                except Exception as exc:
                    describe("StarTools.get_data_dir%r" % (args,), "<调用失败: %s>" % exc)


def probe_context() -> None:
    for module_name in ("astrbot.api.star", "astrbot.api.provider", "astrbot.core.star.context"):
        try:
            module = importlib.import_module(module_name)
        except ImportError:
            continue
        context_cls = getattr(module, "Context", None)
        if context_cls is None:
            continue
        describe("Context 来源", module_name)
        print("Context 公开成员：%s" % ", ".join(sorted(n for n in dir(context_cls) if not n.startswith("_"))))
        if hasattr(context_cls, "send_message"):
            signature("Context.send_message", context_cls.send_message)
        return
    print("!! 未找到 Context 类")


def probe_config_class() -> None:
    for module_name in (
        "astrbot.core.config.astrbot_config",
        "astrbot.core.config",
        "astrbot.api.config",
    ):
        try:
            module = importlib.import_module(module_name)
        except ImportError:
            continue
        for name in dir(module):
            value = getattr(module, name)
            if "Config" not in name or not inspect.isclass(value):
                continue
            bases = ", ".join(item.__name__ for item in value.__mro__[1:4])
            print("%s.%s -> %r  基类=%s" % (module_name, name, value, bases))


def probe_source_needles() -> None:
    astrbot = importlib.import_module("astrbot")
    package_root = Path(getattr(astrbot, "__file__", "")).resolve().parent
    describe("扫描目录", package_root)
    files = sorted(item for item in package_root.rglob("*.py") if "__pycache__" not in item.parts)
    print("扫描 %d 个 Python 文件" % len(files))
    for needle in NEEDLES:
        print("\n--- 命中 %r 的前 6 处 ---" % needle)
        hits = 0
        pattern = re.compile(re.escape(needle))
        for path in files:
            try:
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            found = False
            for number, line in enumerate(lines, start=1):
                if not pattern.search(line):
                    continue
                print("%s:%d: %s" % (path.relative_to(package_root), number, line.strip()[:150]))
                hits += 1
                found = True
                break
            if found and hits >= 6:
                break
        if hits == 0:
            print("<无命中>")


def main() -> int:
    print("Python: %s" % sys.version.splitlines()[0])
    steps = (
        ("AstrBot 版本", probe_version),
        ("事件与命令 API", probe_event_api),
        ("消息链与组件", probe_message_chain),
        ("Star / 数据目录", probe_star_and_data_dir),
        ("Context", probe_context),
        ("配置类", probe_config_class),
        ("源码线索扫描", probe_source_needles),
    )
    for name, func in steps:
        step(name, func)
    print("\n探针结束。请把完整输出回传。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
