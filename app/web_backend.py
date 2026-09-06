"""
pywebview 后端 Bridge API (v4.0 Phase 3 完整版).

借鉴自 https://pywebview.flowrl.com/ (BSD-3-Clause)
借鉴内容: Bridge 模式 + evaluate_js 流式推送范式
借鉴方式: 思路借鉴,代码自写
Copyright (c) 2014-2024 Roman Yurchak
"""
import asyncio
import json
import re
import sys
import threading
import time
import uuid
import webview
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

from openai import AsyncOpenAI

from app.logger import setup_logging
from app.processor import ProcessingEngine
from app.utils import (
    ProjectConfig,
    load_config,
    save_config,
    read_file_text,
    split_text,
    _atomic_write_text,
    CONFIG_DIR,
    CHUNKING_PRESETS,
    CHUNKING_PRESETS_MAP,
    DEFAULT_CHUNK_PRESET,
)
from app.templates import (
    PROMPT_MODES,
    API_TEMPLATES,
    SYSTEM_PROMPT_DEAI,
    SYSTEM_PROMPT_DISTILL_STYLE,
    SYSTEM_PROMPT_DEAI_DETECT_V5,
    SYSTEM_PROMPT_DEAI_REWRITE_V5,
    SYSTEM_PROMPT_DEAI_AUDIT_V5,
)
from app.style_profiles.loader import StyleProfileLoader, MIN_SAMPLES_FOR_DISTILL

logger = setup_logging()


# v4.1.5 (修复 1): onFileStart 推送 original 字段的字符数阈值.
# 超过这个大小不推 original, 前端 fallback 调 read_file(path) 读.
# 50K 字 ≈ 100KB UTF-8, JSON 序列化 + evaluate_js 单次 payload ~150KB,
# 仍可接受 (>50K 后切前端 read_file 路径, 避免大 payload 卡 evaluate_js).
_ORIGINAL_PUSH_LIMIT = 50000

# v4.3.0: DeAI 长文本支持常量
# - 推送降级阈值: partial 超过它不再推全量 (对齐 _ORIGINAL_PUSH_LIMIT, 评审#1:
#   30 万字书改写收尾单帧 ~1MB x 30FPS 会拖死 WebView), 完整结果落盘走文件
_DEAI_PUSH_LIMIT = 50000
# - whole_file 预设兜底 (评审#6): 超过它强制回退 large(6000) 分块,
#   否则整本书 = 单次 LLM 调用必然超模型上下文
_DEAI_WHOLE_FILE_LIMIT = 20000
# - Few-shot 范文截断 (评审#6): 范文用途是学风格, 超长部分无增益还爆上下文
_DEAI_SAMPLE_LIMIT = 20000


# 异步模型 (PLAN-pywebview.md §2.2):
# - 校对任务用 threading.Thread + asyncio.run 在后台线程跑, 不阻塞 pywebview 主线程
# - pywebview 主线程不跑 asyncio loop, callback 通过 evaluate_js 推送到前端
# - pause/cancel 事件用 threading.Event (processor.py 已修订, §13.1 验收)
#
# 流式推送节流 (PLAN §6.1):
# - 后端 callback 高频触发 (每个 token 节流后), 累积到 self._push_buffer
# - 每 33ms flush 一次, 把 buffer 合并成单个 evaluate_js 调用, 避免卡 webview
# - 33ms (30 FPS) 比 50ms (20 FPS) / 100ms (10 FPS) 流畅, 跟前端 RAF 对齐
#   (v4.1.4 修订, 见 _push 方法注释)
#
# DeAI 3 步工作流 (Phase 3):
# - 独立 LLM 调用, 不依赖 start_proofread
# - 每步起独立后台线程 + 临时 AsyncOpenAI 客户端
# - 流式 partial 推 onDeaiStream, 完成推 onDeaiComplete
# - 用 uuid 区分 step 任务, 避免多步并发串台


# Chunking 档位单点定义在 app/utils.py:CHUNKING_PRESETS (v4.1 M2 提取)。
# 借鉴来源沿用 utils.py 顶部注释 (tianhm/ollama-batch-processor MIT)。
# 业务层 + 前端层统一从 utils 导入, 避免 label/max_chars 漂移。


class Backend:
    """暴露给 JS 的 Python 方法集合 (window.pywebview.api.xxx)。"""

    def __init__(self, window=None):
        # window 在 main.py 中后置注入: window.js_api = self
        self._window = window
        self._engine: Optional[ProcessingEngine] = None
        self._current_task_thread: Optional[threading.Thread] = None
        # v4.1.8.2 (审计 B13): start_proofread 重入守卫加锁 — pywebview 每个
        # JS 调用独立线程, 旧版 check-then-act 无锁, 理论并发双调可各起一个引擎
        self._task_guard_lock = threading.Lock()
        self._config = load_config()  # v3.0 的配置加载
        self._push_throttle_lock = threading.Lock()
        self._last_push_time = 0.0
        self._push_buffer: list[tuple[str, object]] = []
        self._push_pending = False
        # DeAI 3 步工作流任务跟踪
        self._deai_tasks: dict[str, dict] = {}
        self._deai_lock = threading.Lock()
        # v4.1.7: 风格 Profile 加载器 (借鉴 jianshuo/claude-skills MIT 9 轴指纹思路)
        self._style_loader = StyleProfileLoader()

    # ==================== 配置 API ====================

    def get_config(self) -> dict:
        """返回给前端渲染的配置 (明文 key, 不泄露混淆串).

        v4.1.8.1 (审计修复 H2): 旧实现直接返回 ``to_dict()``, 而 to_dict 对
        api_key 恒 ``_obf`` (磁盘混淆) -> 前端密码框回显混淆串 -> 用户保存时
        set_config 把混淆串当明文写回 -> 磁盘 obf(obf(key)) 永久损坏且 Bearer
        变 obf:xxx 全线 401. 修复: 混淆只发生在"磁盘 <-> 内存"边界 (save_config
        落盘 obf / load_config 读盘 deobf), Bridge 层一律给明文, 前端不再需要
        认识混淆格式.
        """
        cfg = self._config.to_dict()
        cfg["api_key"] = self._config.api_key  # 明文回显 (内存即明文)
        return cfg

    def set_config(self, key: str, value) -> dict:
        """单字段写内存配置. 返回 {ok, error?} 供前端感知失败.

        v4.1.8.2 (审计 B9): 类型转换失败旧版静默吞掉后把原值 (如 "3.5" 字符串)
        直接 setattr 并落盘, 运行期才以 TypeError 爆炸 — 现改为返回错误.
        v4.1.8.2 (审计 E1/E6/F8): 数值范围钳制 — 前端 min/max 挡不住手输
        (concurrency=0 会让引擎 Semaphore(0) 永久死锁), 双端防御.
        """
        # JS 端做 500ms 防抖, Python 这边只 set
        if not hasattr(self._config, key):
            return {"ok": False, "error": f"未知配置项: {key}"}
        # 类型转换: 数字字段
        try:
            field_type = self._config.__dataclass_fields__[key].type
            if field_type is float and not isinstance(value, float):
                value = float(value)
            elif field_type is int and not isinstance(value, int):
                value = int(value)
        except (AttributeError, KeyError, TypeError, ValueError):
            return {"ok": False, "error": f"配置项 {key} 的值 {value!r} 类型转换失败"}
        # 数值范围钳制 (与设置页 min/max 一致)
        clamp_map = {
            "concurrency": (1, 16),
            "max_retries": (0, 10),
            "timeout": (10, 300),
            "temperature": (0.0, 2.0),
            "context_max_chars": (200, 2000),
            "context_max_chunks": (1, 5),
        }
        if key in clamp_map:
            lo, hi = clamp_map[key]
            value = max(lo, min(hi, value))
        if key == "api_key":
            # v4.1.8.1 (审计修复 H2): 拒绝把混淆串当明文写回 (旧版前端残留 /
            # 用户误粘贴 obf: 值). 只接受真正的明文新 key.
            if isinstance(value, str) and value.startswith("obf:"):
                logger.warning("set_config 忽略 obf: 前缀的 api_key (疑似混淆串回写)")
                return {"ok": False, "error": "api_key 不能是混淆串"}
        setattr(self._config, key, value)
        return {"ok": True}

    def save_config(self) -> dict:
        """保存配置到磁盘, 返回结果 (前端可读).

        v4.1.8.2 (审计 B4): utils.save_config 现返回 bool (旧版吞异常恒 None,
        本层 except 永不可达), 据此如实上报, 磁盘满/只读不再误报"已保存".
        """
        ok = save_config(self._config)
        return {"ok": bool(ok)}

    def get_prompt_modes(self) -> list[dict]:
        """返回校对模式下拉选项.

        v4.1.8.2 (审计 C4): 过滤 "deai" — 它是去AI味视图专用的遗留模式
        (复用 v3.1 全量改写 prompt), 出现在校对模式下拉会误导用户把校对
        跑成整篇改写; DeAI 功能走独立视图的 deai_step* API.
        """
        return [
            {"key": k, "label": v["label"]}
            for k, v in PROMPT_MODES.items()
            if k != "deai"
        ]

    def get_api_templates(self) -> list[dict]:
        """返回 API 模板列表 (从 app.templates.API_TEMPLATES).

        与 get_prompt_modes 同质, 给前端下拉用. 不重复实现, 直接透传.
        """
        return list(API_TEMPLATES)

    def get_chunking_presets(self) -> list[dict]:
        """返回 5 档 chunking 预设 (供主页下拉).

        v4.1 (M2): 直接返回 utils.CHUNKING_PRESETS 的副本, 避免双点定义漂移.
        """
        return list(CHUNKING_PRESETS)

    # ==================== 文件 API ====================

    def choose_files(self) -> list[str]:
        """用 pywebview 原生 create_file_dialog, 不用 QFileDialog.

        pywebview 5.x 官方 API, 非阻塞, 支持多选.
        pywebview 6.x 用 webview.FileDialog.OPEN.

        v4.1.3 (F1): file_types 多扩展必须用 ';' 分隔 (pywebview 6.2.1 parse_file_type
        正则 `^([\\w ]+)\\((...)(?:;\\*\\.\\w+)*\\)$` 强制), 旧版 '(*.txt *.md)' 用空格
        会直接抛 ValueError, 之前被双重 except 吞掉, JS 拿到 [] -> "用户未选择文件".

        v4.1.3 (I5): 删掉兼容 fallback (pywebview 6.x 主推 FileDialog.OPEN),
        改成单层 try/except + logger.error 真实异常落地.
        """
        if self._window is None:
            return []
        try:
            result = self._window.create_file_dialog(
                webview.FileDialog.OPEN,
                allow_multiple=True,
                file_types=("文本文件 (*.txt;*.md)", "所有文件 (*.*)"),
            )
        except Exception as e:
            # 单层 try/except: 真实异常落地日志, 不再吞掉, 便于排查.
            logger.error(f"choose_files 失败: {type(e).__name__}: {e}")
            return []
        # result 是 list[str] 或 None
        return list(result) if result else []

    def read_file(self, path: str) -> dict:
        """同步读文件 (用于前端预览小文件, 大文件通过 stream 走).

        v4.1.8.2 (审计 B10): 返回结构化 {ok, content/error} — 旧版失败时返回
        "[读取错误] ..." 文本, 前端把它当原文渲染进对比栏并参与 diff.
        """
        try:
            return {"ok": True, "content": read_file_text(Path(path))}
        except Exception as e:
            logger.error(f"read_file 失败 [{path}]: {e}")
            return {"ok": False, "error": str(e)}

    def drag_drop_files(self, paths: list) -> dict:
        """前端拖拽文件时调用 (兼容性保留, 主路径走 init_drag_drop + onFilesDropped).

        pywebview 6.x 通过 Python DOM API 注册 drop 事件后, 回调会注入
        `pywebviewFullPath` 到 event['dataTransfer']['files'][i], 详见 init_drag_drop.
        返回 {"ok": True, "count": N} 给前端用.
        """
        # 简单校验: 过滤不存在的路径
        valid = [p for p in (paths or []) if isinstance(p, str) and Path(p).exists()]
        return {"ok": True, "count": len(valid), "paths": valid}

    def init_drag_drop(self, window) -> None:
        """v4.1.3 (F2): 注册 drop 事件, 必须用 Python DOM API, 不能用前端 addEventListener.

        原因 (pywebview 6.2.1 源码确凿):
        - 前端 `addEventListener('drop')` 不会触发 `_dnd_state['num_listeners']++`,
          因此 C# 端 on_script_notify 收到 'FilesDropped' 时 _dnd_state['num_listeners']==0,
          直接 return, _dnd_state['paths'] 永远为空, JS 拿不到 pywebviewFullPath.
        - 必须用 `window.dom.get_element(selector).on('drop', callback)` 注册,
          element.py:412-413 才会在 on('drop') 时 _dnd_state['num_listeners'] += 1.
        - 在 callback 收到的 event dict 里, `event['dataTransfer']['files'][i]`
          已经被 util.py:288-300 注入 'pywebviewFullPath' (C# 端 file.Path 解码后).

        调用顺序: 必须等 window.events.loaded 之后 (DOM 已注入 data-pywebview-id 节点),
        否则 get_element 拿不到 selector. 用 events.loaded += callback 注册.
        """
        self._window = window  # 确保引用
        window.events.loaded += self._on_loaded_drag_drop
        logger.info("拖拽 drop 监听注册 (init_drag_drop 已注册 loaded 回调)")

    def _on_loaded_drag_drop(self) -> None:
        """window.events.loaded 触发: 等 DOM 就绪, 绑 drop 监听.

        v4.3.0: 除 #drop-zone (文件路径 -> onFilesDropped) 外, 给去AI味的两个
        textarea (#deai-input/#deai-sample) 也注册 drop — 拖入 .txt/.md 文件时
        拿 pywebviewFullPath 后走 read_file_text (BOM/gb18030 编码兜底),
        绕开 File.text() 恒 UTF-8 导致 GBK 文件乱码的问题 (评审#4).
        此回调运行在 pywebview 主线程, _dnd_state 在 webview.dom._dnd_state
        (全局, 跨函数共享), _dnd_state['num_listeners'] 由 element.on('drop') 自增.
        """
        try:
            drop_zone = self._window.dom.get_element("#drop-zone")
            if drop_zone is None:
                logger.error("init_drag_drop 失败: #drop-zone 元素未找到 (DOM 未就绪?)")
                return
            drop_zone.on("drop", self._on_drag_drop)
            logger.info("#drop-zone drop 监听已绑定 (pywebview DOM API)")
            # v4.3.0: DeAI textarea 文件拖入 (内容读取走 Python 编码兜底)
            for selector, target in (("#deai-input", "deai-input"),
                                     ("#deai-sample", "deai-sample")):
                el = self._window.dom.get_element(selector)
                if el is None:
                    logger.warning(f"textarea drop 注册跳过: {selector} 未找到")
                    continue
                el.on("drop", (lambda tgt: lambda event: self._on_textarea_drop(event, tgt))(target))
            logger.info("DeAI textarea drop 监听已绑定")
        except Exception as e:
            logger.error(f"init_drag_drop 异常: {type(e).__name__}: {e}")

    @staticmethod
    def _extract_drop_paths(event) -> list:
        """从 pywebview DOM drop 事件提取 pywebviewFullPath 列表 (v4.3.0 抽取复用)."""
        data_transfer = event.get("dataTransfer", {}) if isinstance(event, dict) else {}
        files = data_transfer.get("files", []) or []
        paths = []
        for f in files:
            if isinstance(f, dict):
                pp = f.get("pywebviewFullPath")
                if pp:
                    paths.append(pp)
        return paths

    def _on_textarea_drop(self, event, target: str) -> None:
        """DeAI textarea drop: 提取文件路径, 推 onDeaiTextDrop 给前端读内容.

        路径在此只做传递; 内容读取由前端调 read_file bridge (read_file_text
        的 BOM/gb18030 兜底在 Python 侧生效). 纯文本拖放不经过此通道
        (JS 侧 text/plain 直接由浏览器原生插入).
        """
        try:
            paths = self._extract_drop_paths(event)
            if not paths:
                logger.debug(f"textarea drop 无 pywebviewFullPath (target={target})")
                return
            logger.info(f"textarea 拖入 {len(paths)} 个文件 (target={target})")
            self._push("onDeaiTextDrop", {"target": target, "paths": paths})
        except Exception as e:
            logger.error(f"_on_textarea_drop 异常: {type(e).__name__}: {e}")

    def _on_drag_drop(self, event) -> None:
        """pywebview DOM 回调: 接收 drop 事件, 提取 pywebviewFullPath, 推送给前端.

        event 结构 (util.js_bridge_call 已注入 pywebviewFullPath):
        {
            'type': 'drop',
            'dataTransfer': {
                'files': [
                    {'name': 'a.txt', 'pywebviewFullPath': 'C:\\path\\a.txt'},
                    ...
                ]
            },
            ...
        }
        """
        try:
            paths = self._extract_drop_paths(event)
            files = (event.get("dataTransfer", {}) or {}).get("files", []) if isinstance(event, dict) else []
            if not paths:
                # 拖了 0 文件, 或 _dnd_state 注入失败 (非 pywebview 环境)
                logger.warning(f"drop 事件但未拿到 pywebviewFullPath (files={len(files)})")
                return
            logger.info(f"拖拽收到 {len(paths)} 个文件: {paths[:3]}{'...' if len(paths) > 3 else ''}")
            self._push("onFilesDropped", {"paths": paths, "count": len(paths)})
        except Exception as e:
            logger.error(f"_on_drag_drop 异常: {type(e).__name__}: {e}")

    def remove_file(self, path: str) -> dict:
        """前端请求删除某个文件. Python 端无需状态, 只确认."""
        return {"ok": True, "removed": path}

    def clear_files(self) -> dict:
        """前端清空文件列表."""
        return {"ok": True}

    def copy_to_clipboard(self, text: str) -> dict:
        """v4.1.3 (I1): 用 Win32 OpenClipboard API 把文本写入系统剪贴板.

        原因: WebView2 里 navigator.clipboard.writeText 经常失败 (focus 不在 iframe
        或用户拒绝权限), 通过 Python 端调 Win32 API 走 OS 剪贴板, 成功率 100%.

        借鉴自 pywebview 自身 (BSD-3-Clause) - Win32 OpenClipboard API 范式.
        思路借鉴, 代码自写 (pywebview 内部 clipboard 用的是 win32clipboard 第三方库,
        我们不引入新依赖, 用 ctypes 直接调 user32/kernel32).
        """
        if not isinstance(text, str):
            return {"ok": False, "error": "text 必须是 str"}
        if not text:
            return {"ok": False, "error": "text 为空"}
        if sys.platform != "win32":
            # 非 Windows: 退化到当前进程 (基本没意义, 但不崩)
            return {"ok": False, "error": f"copy_to_clipboard 仅支持 Windows, 当前 {sys.platform}"}
        try:
            import ctypes
            from ctypes import wintypes
            CF_UNICODETEXT = 13
            GMEM_MOVEABLE = 0x0002

            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32

            # v4.1.8.2 (审计 B1, P0): 声明完整 argtypes/restype — 旧版全部走
            # ctypes 默认 c_int, 64 位进程下 HGLOBAL/HANDLE 被截断成 32 位:
            # GlobalLock 按无效句柄返回 NULL (复制必失败), 或 memmove 写到截断
            # 地址破坏堆 (实测 GlobalAlloc 返回 0x22272a20018 被截断). 同时把
            # EmptyClipboard 挪到数据准备成功之后, 失败路径不再清空用户剪贴板.
            kernel32.GlobalAlloc.argtypes = (wintypes.UINT, ctypes.c_size_t)
            kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
            kernel32.GlobalLock.argtypes = (wintypes.HGLOBAL,)
            kernel32.GlobalLock.restype = wintypes.LPVOID
            kernel32.GlobalUnlock.argtypes = (wintypes.HGLOBAL,)
            kernel32.GlobalUnlock.restype = wintypes.BOOL
            kernel32.GlobalFree.argtypes = (wintypes.HGLOBAL,)
            kernel32.GlobalFree.restype = wintypes.HGLOBAL
            user32.OpenClipboard.argtypes = (wintypes.HWND,)
            user32.OpenClipboard.restype = wintypes.BOOL
            user32.CloseClipboard.argtypes = []
            user32.CloseClipboard.restype = wintypes.BOOL
            user32.EmptyClipboard.argtypes = []
            user32.EmptyClipboard.restype = wintypes.BOOL
            user32.SetClipboardData.argtypes = (wintypes.UINT, wintypes.HANDLE)
            user32.SetClipboardData.restype = wintypes.HANDLE

            # 1. 先在剪贴板之外准备好数据 (失败时不碰用户剪贴板)
            text_bytes = (text + "\0").encode("utf-16-le")
            h = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(text_bytes))
            if not h:
                return {"ok": False, "error": "GlobalAlloc 失败"}
            ptr = kernel32.GlobalLock(h)
            if not ptr:
                kernel32.GlobalFree(h)
                return {"ok": False, "error": "GlobalLock 失败"}
            try:
                ctypes.memmove(ptr, text_bytes, len(text_bytes))
            finally:
                kernel32.GlobalUnlock(h)

            # 2. OpenClipboard (失败时重试一次, 避免和其他 app 抢剪贴板)
            opened = False
            for attempt in range(2):
                if user32.OpenClipboard(None):
                    opened = True
                    break
                if attempt == 0:
                    time.sleep(0.05)  # 50ms 后重试
            if not opened:
                kernel32.GlobalFree(h)
                return {"ok": False, "error": "OpenClipboard 失败 (其他应用占用?)"}

            try:
                user32.EmptyClipboard()
                if not user32.SetClipboardData(CF_UNICODETEXT, h):
                    # 失败: h 仍归我们, 释放 (数据已备好, 该分支极少见)
                    kernel32.GlobalFree(h)
                    h = None
                    return {"ok": False, "error": "SetClipboardData 失败"}
                # 成功: SetClipboardData 后 h 归系统, 不能 GlobalFree
                h = None
            finally:
                user32.CloseClipboard()
                if h:
                    kernel32.GlobalFree(h)
            return {"ok": True, "length": len(text)}
        except Exception as e:
            logger.error(f"copy_to_clipboard 异常: {type(e).__name__}: {e}")
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    # ==================== 校对任务 API ====================

    def start_proofread(self, file_paths: list[str], mode_key: str,
                        custom_prompt: str = "",
                        chunking_preset: str = "balanced",
                        force_rerun: bool = False) -> dict:
        """启动校对任务 (后台线程), 立即返回 task_id.

        v4.3.1 (UX #7): 末位加 force_rerun (带默认值, pywebview 按位置传参,
        前端不传时行为不变) — True 时 prepare_tasks 跳过断点缓存强制重跑,
        解决"已完成文件删掉重加被缓存秒标完成、前端无重跑通道"的问题;
        返回 dict 新增 cached_files 字段, 前端据此提示哪些文件命中缓存.

        v4.1.8.1 (审计修复 H1): 并发重入保护.
        旧实现每次调用都无条件重建 engine + 起新线程, 不检查上一任务是否在跑:
          - 重复 start -> 旧引擎线程仍在跑, 其回调闭包读动态 self._engine.tasks[k]
            (已被新 engine 替换) -> KeyError -> 被当普通错误反复整文件重试误标 FAILED;
          - 更糟时两个线程 run_until_complete 同一 engine, 交叉写断点.
        修复: 若上一任务线程仍存活, 先 cancel 并 join 等它退出 (最多 5s),
        再启动新任务; 若旧线程迟迟不退则拒绝启动并返回错误.
        """
        # --- 并发重入保护: 先清理上一任务 (若有) ---
        # v4.1.8.2 (审计 B13): 守卫序列套锁, 防 js_api 线程池并发双调
        with self._task_guard_lock:
            prev_thread = self._current_task_thread
            if prev_thread is not None and prev_thread.is_alive():
                logger.warning("start_proofread: 上一任务仍在运行, 先取消并等待退出")
                if self._engine is not None:
                    self._engine.cancel()
                prev_thread.join(timeout=5.0)
                if prev_thread.is_alive():
                    # v4.1.8.2 (审计 B3): 失败返回与成功返回统一 dict 契约,
                    # 前端按 ok 字段处理 (旧版成功无 ok 字段, 前端无法区分)
                    return {
                        "ok": False,
                        "error": "上一个任务未能及时退出, 请稍后重试",
                    }

        # 设置 config
        self._config.prompt_mode = mode_key
        if custom_prompt:
            self._config.custom_prompt = custom_prompt
        if chunking_preset in [p["key"] for p in CHUNKING_PRESETS]:
            self._config.chunking_preset = chunking_preset
        self._config.output_format = "txt"

        # v4.1 (M3): task_id 用 uuid 避免硬编码 "1" (并发/多任务时唯一)
        task_id = f"proof_{uuid.uuid4().hex[:8]}"

        # 准备任务
        # v4.3.1 (UX #7): force_rerun 透传给引擎 (True 跳过断点缓存)
        engine = ProcessingEngine(self._config)
        engine.prepare_tasks([Path(p) for p in file_paths], force_rerun=force_rerun)
        self._engine = engine  # 供 pause/cancel/resume/_collect_results 引用
        # v4.3.4: 标点不平衡报告 — prepare 阶段 _log 未接回调, 在此补推 (评审 E-1)
        for msg in list(engine.punct_reports):
            self._push("onLog", msg)
        engine.punct_reports.clear()

        # 回调注册: 把事件转 evaluate_js 推送.
        # v4.1.8.1 (H1): 回调闭包一律捕获局部 engine 引用 (默认参数绑定),
        # 不再运行时读动态 self._engine — 否则上一任务线程跑回调时若
        # self._engine 已被新任务替换, tasks[k] 直接 KeyError.
        engine.on_log = lambda msg: self._push("onLog", msg)
        engine.on_stream = lambda k, t: self._push("onStream", {
            "file_key": k, "partial": t,
        })
        # v4.1.5 (修复 1): onFileStart 带 original 字段, 让前端左栏原文字
        # 在流式开始就有数据 (不再等 onTaskComplete).
        # 大文件 (> _ORIGINAL_PUSH_LIMIT 字) 不推 original, 前端 fallback
        # 调 read_file(path) 读 — 避免 JSON 序列化开销 + evaluate_js payload 过大.
        def _on_file_start(k: str, _eng: ProcessingEngine = engine) -> None:
            original = _eng.tasks[k].original_text
            self._push("onFileStart", {
                "file_key": k,
                "original": original if len(original) <= _ORIGINAL_PUSH_LIMIT else None,
                "original_truncated": len(original) > _ORIGINAL_PUSH_LIMIT,
            })
        engine.on_file_start = _on_file_start
        # v4.1.8.2 (审计 C2): onFileDone/onFileCompleted 附带 status — 旧版
        # 成功/失败/取消三条路径都推且 payload 无状态, 前端无条件标"完成"
        engine.on_file_done = lambda k, status: self._push("onFileDone", {
            "file_key": k, "status": status,
        })
        engine.on_file_completed = lambda k, status: self._push("onFileCompleted", {
            "file_key": k, "status": status,
        })
        engine.on_stats_update = lambda s: self._push("onStatsUpdate", {
            "total_files": s.total_files,
            "completed_files": s.completed_files,
            "total_tokens": s.total_tokens,
            "elapsed": s.elapsed,
            "speed": s.speed,
            "eta": s.eta,
        })
        # v4.3.1 (UX #7): 块级进度 — 单文件多 chunk 时前端进度条可按块推进,
        # 不再长时间 0% (多 chunk 路径才触发, 单块文件无分块语义不推)
        engine.on_file_progress = lambda k, c, t: self._push("onChunkProgress", {
            "file_key": k, "chunk": c, "total": t,
        })

        # v4.1.8.2 (审计 C2/F4): 缓存命中文件不进 pending, 收不到任何事件,
        # 前端会全程显示"处理中" — 这里补发完成事件让 UI 即刻收敛.
        for k, t in engine.tasks.items():
            if t.is_done:
                self._push("onFileDone", {"file_key": k, "status": t.status.value})
                self._push("onFileCompleted", {"file_key": k, "status": t.status.value})

        # 后台线程跑 (避免阻塞 pywebview 主线程)
        def run(_eng: ProcessingEngine = engine, _task_id: str = task_id):
            # v4.1 (I6): 顶层 try/except 兜底, 防止 run_async 抛未预期异常
            # 导致前端 isProcessing 永远卡在 true.
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                try:
                    loop.run_until_complete(_eng.run_async())
                except Exception as e:
                    logger.error(f"run_async 未预期异常: {e}")
                    # v4.1.8.2 (审计 B7): 附带 task_id, 前端丢弃旧任务的晚到事件
                    self._push("onTaskComplete", {"task_id": _task_id, "error": str(e)})
                    return
                finally:
                    loop.close()
            except Exception as e:
                # 兜底: loop 创建/关闭异常
                logger.error(f"start_proofread run() 异常: {e}")
                self._push("onTaskComplete", {"task_id": _task_id, "error": str(e)})
                return
            # 跑完推送给前端 (collect 用 engine 局部引用, 不受 self._engine 后续变化影响)
            # v4.1.8.2 (审计 B7): 附带 task_id
            payload = self._collect_results(_eng)
            payload["task_id"] = _task_id
            self._push("onTaskComplete", payload)

        self._current_task_thread = threading.Thread(target=run, daemon=True)
        self._current_task_thread.start()

        # v4.1.8.2 (审计 B3): 统一契约, 成功也带 ok 字段
        # v4.3.1 (UX #7): 附 cached_files — 本次命中断点缓存直接复用结果的文件
        # 路径列表 (force_rerun 时恒为空), 前端提示用户"秒完成"实为缓存命中
        return {
            "ok": True,
            "task_id": task_id,
            "total_files": len(file_paths),
            "cached_files": list(engine.cached_files),
        }

    def cancel_proofread(self) -> dict:
        if self._engine:
            self._engine.cancel()
            return {"ok": True, "action": "cancelled"}
        return {"ok": False, "action": "no_engine"}

    def pause_proofread(self) -> dict:
        if self._engine:
            self._engine.pause()
            return {"ok": True, "action": "paused"}
        return {"ok": False, "action": "no_engine"}

    def resume_proofread(self) -> dict:
        if self._engine:
            self._engine.resume()
            return {"ok": True, "action": "resumed"}
        return {"ok": False, "action": "no_engine"}

    # ==================== 模型列表 / 测试连接 ====================

    def fetch_models(self, api_base: str = "", api_key: str = "") -> dict:
        """拉取 OpenAI 兼容 API 的模型列表 (用于测试连接 + 自动填充 model 字段).

        v4.1 (I3): 改异步 — 立即返回 task_id, 后台线程跑 requests.get,
        完成通过 onFetchModelsComplete 推回前端. 原因: 慢服务器 10s timeout
        会卡 pywebview 主线程, 改后台后前端立即拿到 task_id 可以显示 loading.

        返回:
          {"ok": True, "task_id": "fetch_xxxxxxxx", "status": "running"}
        """
        base = api_base or self._config.api_base
        key = api_key or self._config.api_key
        if not base:
            return {"ok": False, "error": "API base URL 为空"}
        task_id = f"fetch_{uuid.uuid4().hex[:8]}"
        threading.Thread(
            target=self._fetch_models_worker,
            args=(task_id, base, key),
            daemon=True,
            name="fetch-models",
        ).start()
        return {"ok": True, "task_id": task_id, "status": "running"}

    def _fetch_models_worker(self, task_id: str, base: str, key: str) -> None:
        """fetch_models 后台线程 worker. 完成推 onFetchModelsComplete."""
        try:
            import requests
            url = base.rstrip("/") + "/models"
            headers = {"Authorization": f"Bearer {key}"} if key else {}
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code != 200:
                self._push("onFetchModelsComplete", {
                    "task_id": task_id,
                    "ok": False,
                    "error": f"HTTP {resp.status_code}: {resp.text[:200]}",
                })
                return
            data = resp.json()
            models = [m.get("id", "") for m in data.get("data", []) if m.get("id")]
            self._push("onFetchModelsComplete", {
                "task_id": task_id,
                "ok": True,
                "models": models,
                "count": len(models),
            })
        except ImportError:
            self._push("onFetchModelsComplete", {
                "task_id": task_id,
                "ok": False,
                "error": "requests 库未安装",
            })
        except Exception as e:
            self._push("onFetchModelsComplete", {
                "task_id": task_id,
                "ok": False,
                "error": str(e),
            })

    def test_connection(self, api_base: str = "", api_key: str = "") -> dict:
        """测试 API 连接.

        v4.1 (I3): 也改异步, 内部走 fetch_models 后台线程.
        立即返回 task_id, 前端等 onFetchModelsComplete 拿到结果.
        """
        return self.fetch_models(api_base, api_key)

    # ==================== 结果导出 ====================

    def export_result(self, file_path: str = "", content: str = "", fmt: str = "txt") -> dict:
        """v4.1.4: 弹原生保存对话框, 默认位置=源文件目录, 默认文件名=<stem>-<YYMMDD>-<HHMMSS>.<ext>.

        改法 (vs v4.1.3):
        - 默认位置: 源文件同目录 (从 file_path 推导; DeAI 导出 或 源文件不存在 用 home/Documents)
        - 默认文件名: <stem>-<YYMMDD>-<HHMMSS>.<ext>
          例: mydoc-260905-014530.txt  (2026-09-05 01:45:30 导出)
          - YYMMDD = datetime.now().strftime("%y%m%d")
          - HHMMSS = datetime.now().strftime("%H%M%S")
        - 弹 create_file_dialog(FileDialog.SAVE, save_filename=default_name, directory=src_dir)
        - 用户取消 -> {"ok": False, "cancelled": True}
        - 用户选位置 -> 写入

        借鉴自 pywebview (BSD-3-Clause) - create_file_dialog SAVE 范式
        Copyright (c) 2014-2024 Roman Yurchak
        """
        if self._window is None:
            return {"ok": False, "error": "window 未注入"}

        # 推导默认值
        if file_path and Path(file_path).exists():
            src = Path(file_path)
            src_dir = str(src.parent)
            stem = src.stem
        else:
            # DeAI 导出 或 源文件不存在: 用 home/Documents
            src_dir = str(Path.home() / "Documents")
            stem = "deai_result"

        # 扩展名: 优先用 fmt (md 走 md, 否则继承源文件后缀, 兜底 txt)
        # v4.1.8.2 (审计 B11): 非 \w 扩展名 (如 "c++"/"tf#") 会让 pywebview
        # parse_file_type 正则抛 ValueError, 保存对话框直接打不开 — 白名单化.
        if fmt == "md":
            ext = "md"
        elif file_path:
            ext = Path(file_path).suffix.lstrip(".") or "txt"
        else:
            ext = "txt"
        ext = re.sub(r"[^0-9A-Za-z]", "", ext) or "txt"

        # v4.3.0: 对话框 + 写盘逻辑抽为 _export_via_dialog, deai_save_result 复用
        return self._export_via_dialog(stem, src_dir, content, ext)

    def _export_via_dialog(self, default_stem: str, src_dir: str, content: str, ext: str) -> dict:
        """弹原生保存对话框并写盘 (v4.3.0: 从 export_result 抽出复用)."""
        # YYMMDD-HHMMSS 时间戳 (12位)
        timestamp = datetime.now().strftime("%y%m%d-%H%M%S")
        default_name = f"{default_stem}-{timestamp}.{ext}"

        try:
            result = self._window.create_file_dialog(
                webview.FileDialog.SAVE,
                directory=src_dir,
                save_filename=default_name,
                file_types=(f"{ext.upper()} files (*.{ext})", "All files (*.*)"),
            )
        except Exception as e:
            logger.error(f"弹保存对话框失败: {type(e).__name__}: {e}")
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

        # result 是 str (选定的完整路径) 或 None (取消) 或 tuple (pywebview 旧版)
        if not result:
            return {"ok": False, "cancelled": True}

        # result 可能是 str (pywebview 6.x) 或 tuple (旧版)
        save_path = Path(result[0]) if isinstance(result, (tuple, list)) else Path(result)

        try:
            save_path.parent.mkdir(parents=True, exist_ok=True)
            save_path.write_text(content, encoding="utf-8")
            return {"ok": True, "path": str(save_path)}
        except Exception as e:
            logger.error(f"写文件失败: {type(e).__name__}: {e}")
            return {"ok": False, "error": f"写入失败: {e}"}

    # ==================== 去 AI 味 API (Phase 3 真实实现) ====================

    def deai_step1_detect(self, text: str, style_card_slug: str = "") -> str:
        """Step 1: 检测 AI 味, 返回 task_id 立即.

        v4.1.7: 加 style_card_slug (可选), 不影响 detect 输出, 留作未来扩展.
        实际 LLM 调用在后台线程跑, 流式通过 onDeaiStream / onDeaiComplete 推送.
        """
        return self._deai_start("detect", text, sample="", style_card_slug=style_card_slug)

    def deai_step2_rewrite(self, text: str, sample: str = "", style_card_slug: str = "") -> str:
        """Step 2: 4 pass 改写 + (可选) 9 轴风格卡注入.

        v4.1.7: 加 style_card_slug, 走 V5 rewrite prompt (9 轴 + 事实骨架 + 范文锚点).
        借鉴自 https://github.com/jianshuo/claude-skills (MIT License) 思路,
        思路借鉴, 无代码复制.
        """
        return self._deai_start("rewrite", text, sample=sample, style_card_slug=style_card_slug)

    def deai_step3_audit(self, rewritten: str, style_card_slug: str = "",
                         source_task_id: str = "") -> str:
        """Step 3: 三维评分 1-10 + (可选) 8 轴自评.

        v4.1.7: 加 style_card_slug, 走 V5 audit prompt (3 维 + 8 轴自评).
        v4.3.0: 加 source_task_id — step2 超长模式下完整改写结果在后端落盘
        (前端只有头部预览), 这里引用 step2 的 task_id 让后端直读, 全文不过 IPC.
        借鉴自 https://github.com/jianshuo/claude-skills (MIT License) 思路,
        思路借鉴, 无代码复制.
        """
        return self._deai_start("audit", rewritten, sample="",
                                style_card_slug=style_card_slug,
                                source_task_id=source_task_id)

    def _deai_start(self, step: str, text: str, sample: str = "",
                    style_card_slug: str = "", source_task_id: str = "") -> str:
        """启动一个 deai 后台线程, 立即返回 task_id.

        v4.3.0: 登记项加 cancel_event — 供 deai_cancel / 前端"运行中按钮变取消".
        """
        task_id = f"deai_{step}_{uuid.uuid4().hex[:8]}"
        with self._deai_lock:
            self._deai_tasks[task_id] = {
                "step": step,
                "started": time.time(),
                "style_card_slug": style_card_slug,
                "cancel_event": threading.Event(),
            }

        def run():
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    loop.run_until_complete(self._deai_run(
                        task_id, step, text, sample, style_card_slug, source_task_id))
                finally:
                    loop.close()
            except Exception as e:
                # v4.1.3 (F3): 只推 onDeaiError, 不推 onDeaiComplete.
                # 之前同时推两个, _flush 合并逻辑 dict 同名覆盖, onDeaiComplete 覆盖 onDeaiError,
                # 前端 handleDeaiComplete 把 status 设为 'done' 完全没看 error -> 用户看到空 output + '已完成'.
                logger.error(f"deai {step} task={task_id} 顶层异常: {type(e).__name__}: {e}")
                self._push("onDeaiError", {"task_id": task_id, "error": str(e)})
            finally:
                # v4.1.8.2 (审计, 任务表泄漏): 旧版只有成功路径 pop, 异常路径条目
                # 永久残留 _deai_tasks — 统一在收尾清理.
                with self._deai_lock:
                    self._deai_tasks.pop(task_id, None)

        threading.Thread(target=run, daemon=True, name=f"deai-{step}").start()
        return task_id

    async def _deai_run(self, task_id: str, step: str, text: str, sample: str,
                        style_card_slug: str = "", source_task_id: str = "") -> None:
        """deai 后台主循环 (v4.3.0: 分块 + 降级推送 + 可取消).

        v4.3.0 设计 (实施前评审结论):
        - 分块: 按 config.chunking_preset 切块逐块调用; rewrite 纯拼接 (块间注入
          前块结尾做衔接, 导出文本干净无分隔符); detect/audit 报告按「第 i/N 块」分节.
        - whole_file 兜底 (评审#6): whole_file 预设且文本 > _DEAI_WHOLE_FILE_LIMIT
          时强制回退 large(6000), 否则整本书 = 单次调用必超模型上下文.
        - 降级推送 (评审#1): partial > _DEAI_PUSH_LIMIT 时 onDeaiStream 只推尾部
          预览 (全量 MB 级 evaluate_js x 30FPS 会拖死 WebView); 完成后完整结果
          落盘 deai_results/<task_id>.txt, onDeaiComplete 带 result_file,
          复制/导出/step3 引用走后端直读, 全文不过 IPC.
        - 取消 (评审#3): 逐 delta + 块间检查 cancel_event; 取消走结构化 payload
          (cancelled: true) 区分"用户取消"与"失败" (F3 语义), 已完成部分以
          partial/result_file 保留. 取消语义与校对一致: 丢弃中间态, 重跑从块 0.
        - 取消生效时机: 下一个流 delta 或块边界; 模型停流时等 timeout — 与校对一致.
        """
        cancel_event = None
        with self._deai_lock:
            info = self._deai_tasks.get(task_id)
            if info:
                cancel_event = info.get("cancel_event")

        # step3 超长模式: 引用 step2 落盘结果, 全文不过 IPC
        if source_task_id:
            src = self._load_deai_result_text(source_task_id)
            if src is None:
                self._push("onDeaiError", {
                    "task_id": task_id, "error": f"引用的结果不存在或已过期: {source_task_id}",
                })
                self._deai_tasks_pop(task_id)
                return
            text = src

        if not text.strip():
            self._push("onDeaiError", {"task_id": task_id, "error": "输入文本为空"})
            self._deai_tasks_pop(task_id)
            return

        # 分块决策 (whole_file 兜底见 docstring)
        preset = self._config.chunking_preset or DEFAULT_CHUNK_PRESET
        preset_info = CHUNKING_PRESETS_MAP.get(preset) or CHUNKING_PRESETS_MAP[DEFAULT_CHUNK_PRESET]
        max_chars = preset_info["max_chars"]
        if max_chars == 0 and len(text) > _DEAI_WHOLE_FILE_LIMIT:
            logger.info(
                f"deai {task_id}: whole_file 预设但文本 {len(text)} 字 > "
                f"{_DEAI_WHOLE_FILE_LIMIT}, 回退 large(6000) 分块"
            )
            max_chars = CHUNKING_PRESETS_MAP["large"]["max_chars"]
        # preset 恒传 balanced: whole_file 分支已在上面兜底处理
        chunks = split_text(text, max_chars, preset="balanced")
        total = len(chunks)

        # 临时 AsyncOpenAI (不共享 engine 的 client, 因为 deai 独立于校对)
        try:
            client = AsyncOpenAI(
                base_url=self._config.api_base,
                api_key=self._config.api_key,
                timeout=self._config.timeout,
                max_retries=0,
            )
        except Exception as e:
            # v4.1.3 (F3): 只推 onDeaiError, 不推 onDeaiComplete
            logger.error(f"deai {task_id} AsyncOpenAI 创建失败: {e}")
            self._push("onDeaiError", {"task_id": task_id, "error": f"客户端创建失败: {e}"})
            return

        system_prompt = self._build_deai_prompt(step, sample, style_card_slug)
        partial = ""          # 完整累积结果 (内存)
        last_push = 0.0       # v4.1.8.2 (B6): 50ms 节流
        cancelled = False
        try:
            for i, chunk in enumerate(chunks):
                if cancel_event is not None and cancel_event.is_set():
                    cancelled = True
                    break
                user_prompt = self._build_deai_user_prompt(step, chunk, style_card_slug)
                if step == "rewrite" and i > 0 and partial:
                    # v4.3.0: 块间衔接 — 前块改写结果尾部做语气参考 (不重复输出)
                    user_prompt = (
                        "以下是前文已改写部分的结尾 (仅供语气/衔接参考, 请勿重复输出):\n"
                        f"{partial[-400:]}\n\n{user_prompt}"
                    )
                if step != "rewrite" and total > 1:
                    partial += f"=== 第 {i + 1}/{total} 块 ===\n\n"
                try:
                    stream = await client.chat.completions.create(
                        model=self._config.model,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                        temperature=self._config.temperature,
                        stream=True,
                    )
                except Exception as e:
                    raise RuntimeError(f"块 {i + 1}/{total} 调用失败: {e}") from e
                chunk_out = ""
                async for event in stream:
                    if cancel_event is not None and cancel_event.is_set():
                        break
                    if not event.choices:
                        continue
                    delta = event.choices[0].delta
                    content = getattr(delta, "content", None) if delta else None
                    if content:
                        chunk_out += content
                        now = time.time()
                        if now - last_push >= 0.05:
                            self._push_deai_stream(task_id, step, partial + chunk_out, i + 1, total)
                            last_push = now
                if cancel_event is not None and cancel_event.is_set():
                    cancelled = True
                    break
                # v4.1.8.2 (B12): 空块报错, 与校对链路 (空流抛 ValueError) 对齐
                if not chunk_out.strip():
                    raise ValueError(f"API 返回空内容 (块 {i + 1}/{total})")
                partial += chunk_out
                if step != "rewrite" and total > 1:
                    partial += "\n\n"
                # 块完成边界推一次进度
                self._push_deai_stream(task_id, step, partial, i + 1, total)
                last_push = 0.0
        except Exception as e:
            # v4.1.3 (F3): 只推 onDeaiError, 不推 onDeaiComplete
            # 避免 _flush 合并时 onDeaiComplete 覆盖 onDeaiError, 让前端看不到错误.
            logger.error(f"deai {task_id} LLM 调用异常: {type(e).__name__}: {e}")
            err_payload = {"task_id": task_id, "error": str(e),
                           "partial": self._deai_preview(partial)}
            if len(partial) > _DEAI_PUSH_LIMIT:
                err_payload["result_file"] = self._save_deai_result(task_id, partial)
                err_payload["total_len"] = len(partial)
            self._push("onDeaiError", err_payload)
            self._deai_tasks_pop(task_id)
            return
        finally:
            # I1: 关闭 httpx 连接池, 否则长跑会泄漏 socket
            try:
                await client.close()
            except Exception:
                pass

        if cancelled:
            # v4.3.0 (评审#3): 结构化取消 — cancelled 标志 + 保留已完成部分
            payload = {
                "task_id": task_id, "step": step, "error": "已取消",
                "cancelled": True, "partial": self._deai_preview(partial),
                "total_len": len(partial),
            }
            if len(partial) > _DEAI_PUSH_LIMIT:
                payload["result_file"] = self._save_deai_result(task_id, partial)
            self._push("onDeaiError", payload)
            self._deai_tasks_pop(task_id)
            return

        # v4.1.8.2 (B12): 空输出报错
        if not partial.strip():
            self._push("onDeaiError", {"task_id": task_id, "error": "API 返回空内容 (stream 无 token)"})
            self._deai_tasks_pop(task_id)
            return

        # 收尾帧 (helper 内部处理降级)
        self._push_deai_stream(task_id, step, partial, total, total)
        # 完成 (v4.3.0 评审#1: 超阈值完整结果落盘, 前端拿头部预览 + result_file)
        if len(partial) > _DEAI_PUSH_LIMIT:
            result_file = self._save_deai_result(task_id, partial)
            self._push("onDeaiComplete", {
                "task_id": task_id, "step": step,
                "result": partial[:2000] + "\n…(内容过长, 完整结果已存盘, 复制/导出将取完整内容)",
                "truncated": True, "total_len": len(partial), "result_file": result_file,
            })
        else:
            self._push("onDeaiComplete", {
                "task_id": task_id, "step": step, "result": partial, "truncated": False,
            })
        self._deai_tasks_pop(task_id)

    # ---------- v4.3.0: 分块/降级/取消 辅助 ----------

    def _deai_preview(self, text: str) -> str:
        """超阈值降级为尾部预览 (评审#1): 全量 MB 级 evaluate_js 会拖死 WebView."""
        if len(text) <= _DEAI_PUSH_LIMIT:
            return text
        return f"…(内容过长, 已生成 {len(text)} 字, 以下为尾部预览)\n" + text[-600:]

    def _push_deai_stream(self, task_id: str, step: str, display: str,
                          chunk_no: int, total: int) -> None:
        """流式推送: 短文本推全量 (兼容旧前端行为), 超阈值推尾部预览 + 进度."""
        self._push("onDeaiStream", {
            "task_id": task_id,
            "step": step,
            "partial": self._deai_preview(display),
            "truncated": len(display) > _DEAI_PUSH_LIMIT,
            "total_len": len(display),
            "progress": {"chunk": min(chunk_no, total), "total": total},
        })

    def _deai_tasks_pop(self, task_id: str) -> None:
        """任务表清理 (v4.3.0): 所有终态路径统一走这里, 防条目泄漏."""
        with self._deai_lock:
            self._deai_tasks.pop(task_id, None)

    def _save_deai_result(self, task_id: str, text: str) -> str:
        """完整结果落盘 deai_results/<task_id>.txt, 供复制/导出/step3 引用."""
        try:
            d = CONFIG_DIR / "deai_results"
            d.mkdir(parents=True, exist_ok=True)
            f = d / f"{task_id}.txt"
            _atomic_write_text(f, text)
            return str(f)
        except Exception as e:
            logger.error(f"deai 结果落盘失败 [{task_id}]: {e}")
            return ""

    def _load_deai_result_text(self, task_id: str):
        """按 task_id 读落盘结果; 不存在/非法 id 返回 None."""
        import re as _re
        if not task_id or not _re.fullmatch(r"[A-Za-z0-9_\-]+", task_id):
            return None
        f = CONFIG_DIR / "deai_results" / f"{task_id}.txt"
        try:
            if not f.exists():
                return None
            return read_file_text(f)
        except Exception as e:
            logger.error(f"deai 结果读取失败 [{task_id}]: {e}")
            return None

    def deai_cancel(self, task_id: str) -> dict:
        """取消一个运行中的 deai/蒸馏任务 (v4.3.0).

        取消语义与校对一致: 丢弃中间态, 重跑从块 0 (AGENTS.md 第 8 条).
        取消生效时机: 下一个流 delta 或块边界; 模型停流时等 timeout.
        """
        with self._deai_lock:
            info = self._deai_tasks.get(task_id)
            if not info:
                return {"ok": False, "error": "任务不存在或已结束"}
            ev = info.get("cancel_event")
            if ev is not None:
                ev.set()
        return {"ok": True, "action": "cancel_requested"}

    def deai_copy_result(self, task_id: str) -> dict:
        """复制超长结果全文 (v4.3.0): 后端直读落盘文件写剪贴板, 全文不过前端."""
        text = self._load_deai_result_text(task_id)
        if text is None:
            return {"ok": False, "error": "结果不存在或已过期"}
        return self.copy_to_clipboard(text)

    def deai_save_result(self, task_id: str, fmt: str = "txt") -> dict:
        """导出超长结果全文 (v4.3.0): 后端直读落盘文件弹保存框, 全文不过前端."""
        text = self._load_deai_result_text(task_id)
        if text is None:
            return {"ok": False, "error": "结果不存在或已过期"}
        ext = "md" if fmt == "md" else "txt"
        return self._export_via_dialog(
            "deai_result", str(Path.home() / "Documents"), text, ext,
        )

    def _build_deai_prompt(self, step: str, sample: str, style_card_slug: str = "") -> str:
        """构造 system prompt. step: detect/rewrite/audit.

        v4.1.7: 走 V5 路径
        - detect: SYSTEM_PROMPT_DEAI_DETECT_V5 (7 大类 + AI 6 处反制)
        - rewrite: SYSTEM_PROMPT_DEAI_REWRITE_V5 (9 轴 + 事实骨架) + 可选 style-card.md 全文注入
        - audit: SYSTEM_PROMPT_DEAI_AUDIT_V5 (3 维 + 8 轴自评) + 可选 style-card.md 全文注入
        借鉴自 jianshuo/claude-skills MIT 思路, 项目语言重写.
        """
        if step == "detect":
            return SYSTEM_PROMPT_DEAI_DETECT_V5
        if step == "rewrite":
            base = SYSTEM_PROMPT_DEAI_REWRITE_V5
            # 范文学习: 旧版 sample 字段 (单篇) + 新版 style_card (9 轴)
            if sample:
                # v4.3.0 (评审#6): 范文截断 — 超长范文原样注入会爆上下文,
                # 范文用途是学风格, 2 万字足够
                if len(sample) > _DEAI_SAMPLE_LIMIT:
                    logger.info(f"deai sample 截断: {len(sample)} -> {_DEAI_SAMPLE_LIMIT}")
                    sample = sample[:_DEAI_SAMPLE_LIMIT] + "\n…(范文超 2 万字, 已截断)"
                base += (
                    f"\n\n# 范文学习 (用户输入)\n学句长、口气、转折、毛边:\n{sample}"
                )
            if style_card_slug:
                card_text = self._load_style_card_text(style_card_slug)
                if card_text:
                    base += (
                        f"\n\n# 9 轴风格指纹卡 (用户选定)\n"
                        f"按下面 9 轴描述的'怎么写'改写, 锚点原句从卡里查:\n\n{card_text}"
                    )
            return base
        if step == "audit":
            base = SYSTEM_PROMPT_DEAI_AUDIT_V5
            if style_card_slug:
                card_text = self._load_style_card_text(style_card_slug)
                if card_text:
                    base += (
                        f"\n\n# 9 轴风格指纹卡 (八轴自评对照基准)\n\n{card_text}"
                    )
            return base
        return SYSTEM_PROMPT_DEAI

    def _build_deai_user_prompt(self, step: str, text: str, style_card_slug: str = "") -> str:
        if step == "detect":
            return f"请检测下面这段文本的 AI 痕迹:\n\n{text}"
        if step == "rewrite":
            return f"请改写下面这段文本,清除 AI 痕迹:\n\n{text}"
        if step == "audit":
            return f"请对下面这段改写后文本评分:\n\n{text}"
        return text

    def _load_style_card_text(self, slug: str) -> str:
        """读 style-card.md 全文, 失败返空串. 借鉴自 jianshuo MIT 思路."""
        if not slug:
            return ""
        try:
            return self._style_loader.get_style_card(slug)
        except Exception as e:
            logger.warning(f"读 style-card {slug} 失败: {e}")
            return ""

    # ==================== v4.1.7 风格 Profile API (借鉴 jianshuo/claude-skills MIT 9 轴思路) ====================
    # 借鉴内容: 9 轴指纹 CRUD + 蒸馏流程 + 事实骨架纪律, 思路借鉴, 无代码复制
    # 6 个 Bridge API 全部以 list_/create_/delete_/add_/distill_/get_ 前缀暴露给 JS
    # 存储路径: ~/.proofreader/styles/<slug>/{samples/,style-card.md,meta.json}
    # 4 段借鉴注释见各方法 docstring

    def list_style_profiles(self) -> dict:
        """列出所有风格 profile: builtin 3 套 + custom N 套 (按 ~/.proofreader/styles/ 扫).

        借鉴自 https://github.com/jianshuo/claude-skills (MIT License)
        借鉴内容: 风格 profile 存储 + 列表化展示 (思路借鉴)
        借鉴方式: 思路借鉴, 无代码复制
        Copyright (c) 2026 Jianshuo Wang
        """
        try:
            return {
                "builtin": self._style_loader.list_builtin(),
                "custom": self._style_loader.list_custom(),
            }
        except Exception as e:
            logger.error(f"list_style_profiles 失败: {e}")
            return {"builtin": [], "custom": [], "error": str(e)}

    def create_style_profile(self, slug: str, name: str, summary: str = "") -> dict:
        """建 custom profile, 建目录 ~/.proofreader/styles/<slug>/.

        借鉴自 https://github.com/jianshuo/claude-skills (MIT License)
        借鉴内容: <author-slug> 目录结构思路 + 9 轴指纹作为卡片存储
        借鉴方式: 思路借鉴, 无代码复制
        Copyright (c) 2026 Jianshuo Wang
        """
        try:
            meta = self._style_loader.create_custom(slug, name, summary)
            return {"ok": True, "profile": meta}
        except (FileExistsError, ValueError) as e:
            return {"ok": False, "error": str(e)}
        except Exception as e:
            logger.error(f"create_style_profile 失败: {e}")
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    def delete_style_profile(self, slug: str) -> dict:
        """删 custom profile (builtin 拒绝删除).

        借鉴自 https://github.com/jianshuo/claude-skills (MIT License)
        借鉴内容: profile 生命周期管理
        借鉴方式: 思路借鉴, 无代码复制
        Copyright (c) 2026 Jianshuo Wang
        """
        try:
            r = self._style_loader.delete_custom(slug)
            return {"ok": True, **r}
        except (FileNotFoundError, PermissionError, ValueError) as e:
            return {"ok": False, "error": str(e)}
        except Exception as e:
            logger.error(f"delete_style_profile 失败: {e}")
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    def add_sample_to_profile(self, slug: str, content: str, filename: str = "") -> dict:
        """加一篇样本到 custom profile 的 samples/ 目录, meta.samples_count 自增.

        借鉴自 https://github.com/jianshuo/claude-skills (MIT License)
        借鉴内容: 样本入库 (蒸馏前准备) + 建议 3-6 篇覆盖
        借鉴方式: 思路借鉴, 无代码复制
        Copyright (c) 2026 Jianshuo Wang
        """
        try:
            r = self._style_loader.add_sample(slug, content, filename)
            return {"ok": True, **r}
        except (FileNotFoundError, ValueError) as e:
            return {"ok": False, "error": str(e)}
        except Exception as e:
            logger.error(f"add_sample_to_profile 失败: {e}")
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    def get_style_card(self, slug: str) -> dict:
        """读 style-card.md 全文 + meta, 返 dict 给前端展示.

        借鉴自 https://github.com/jianshuo/claude-skills (MIT License)
        借鉴内容: 蒸馏后 style-card.md 作为真源 (人可读可手改)
        借鉴方式: 思路借鉴, 无代码复制
        Copyright (c) 2026 Jianshuo Wang
        """
        try:
            meta = self._style_loader.get_custom(slug)
            card_text = self._style_loader.get_style_card(slug)
            return {
                "ok": True,
                "slug": slug,
                "name": meta.get("name", slug),
                "samples_count": meta.get("samples_count", 0),
                "distilled_at": meta.get("distilled_at", ""),
                "card_markdown": card_text,
                "axes": meta.get("axes", {}),
                "ai_tells_counter": meta.get("ai_tells_counter", []),
            }
        except FileNotFoundError as e:
            return {"ok": False, "error": str(e)}
        except Exception as e:
            logger.error(f"get_style_card 失败: {e}")
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    def distill_style_profile(self, slug: str) -> str:
        """启动后台蒸馏: 拼样本 → 调 LLM (流式推 onDeaiStream) → 落盘 style-card.md.

        借鉴自 https://github.com/jianshuo/claude-skills (MIT License)
        借鉴内容: 蒸馏流程 (样本 → 9 轴拆解 → 锚点原句 → 写出 style-card.md) +
                 AI 6 处反制 + 调料校准
        借鉴方式: 思路借鉴, 无代码复制, 实际 LLM 调用走 AsyncOpenAI 流式
        Copyright (c) 2026 Jianshuo Wang

        立即返 task_id, 后台线程跑, 流式 partial 复用 onDeaiStream (slug 当 step 路由).
        完成推 onDeaiComplete + 自动 save_style_card, 失败推 onDeaiError.
        """
        # v4.1.8.2 (审计 L5): 同 slug 去重 — 旧版可并发双蒸馏同一 profile,
        # save_style_card last-writer-wins 随机覆盖
        with self._deai_lock:
            for info in self._deai_tasks.values():
                if info.get("step") == "distill" and info.get("slug") == slug:
                    return {"ok": False, "error": f"profile '{slug}' 正在蒸馏中, 请等待完成"}
        task_id = f"distill_{slug}_{uuid.uuid4().hex[:8]}"
        with self._deai_lock:
            self._deai_tasks[task_id] = {
                "step": "distill",
                "slug": slug,
                "started": time.time(),
                "cancel_event": threading.Event(),  # v4.3.0: 蒸馏也支持取消
            }

        def run():
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    loop.run_until_complete(self._deai_distill_run(task_id, slug))
                finally:
                    loop.close()
            except Exception as e:
                logger.error(f"distill {task_id} 顶层异常: {type(e).__name__}: {e}")
                self._push("onDeaiError", {
                    "task_id": task_id,
                    "step": "distill",
                    "error": f"{type(e).__name__}: {e}",
                })
            finally:
                # v4.1.8.2 (审计, 任务表泄漏): 异常路径也要清理登记
                with self._deai_lock:
                    self._deai_tasks.pop(task_id, None)

        threading.Thread(target=run, daemon=True, name=f"deai-distill-{slug}").start()
        return {"ok": True, "task_id": task_id}

    async def _deai_distill_run(self, task_id: str, slug: str) -> None:
        """distill_style_profile 后台主循环: 跑 LLM 蒸馏, 流式推 partial.

        借鉴自 https://github.com/jianshuo/claude-skills (MIT License)
        借鉴内容: SYSTEM_PROMPT_DISTILL_STYLE (9 轴 schema + 锚点纪律 + AI 6 处反制)
        借鉴方式: 思路借鉴, 无代码复制, prompt 在 templates.py
        Copyright (c) 2026 Jianshuo Wang
        """
        # 1. 准备样本 (loader 内部已校验 samples_count >= 3)
        try:
            sdir = self._style_loader._samples_dir(slug)
            samples = []
            for f in sorted(sdir.glob("*.md")):
                txt = f.read_text(encoding="utf-8", errors="replace")
                samples.append(f"# {f.name}\n\n{txt}")
            if len(samples) < MIN_SAMPLES_FOR_DISTILL:
                raise ValueError(
                    f"样本不足: {len(samples)} 篇, 至少 {MIN_SAMPLES_FOR_DISTILL} 篇"
                )
            samples_concat = "\n\n---\n\n".join(samples)
            # v4.1.8.2 (审计 L2): 样本总量上限 — 旧版只限单篇 200KB, 50 篇拼进
            # 一个 prompt 必被服务端 400 拒绝或产生巨额 token 消耗
            if len(samples_concat) > 600_000:
                raise ValueError(
                    f"样本总量 {len(samples_concat)} 字符超上限 600000, 请删减样本后重试"
                )
        except Exception as e:
            logger.error(f"distill {task_id} 读样本失败: {e}")
            self._push("onDeaiError", {
                "task_id": task_id, "step": "distill", "error": f"读样本失败: {e}",
            })
            return

        # 2. 建临时 AsyncOpenAI
        try:
            client = AsyncOpenAI(
                base_url=self._config.api_base,
                api_key=self._config.api_key,
                timeout=max(self._config.timeout, 60),  # 蒸馏 10-30s, 至少 60s
                max_retries=0,
            )
        except Exception as e:
            logger.error(f"distill {task_id} AsyncOpenAI 创建失败: {e}")
            self._push("onDeaiError", {
                "task_id": task_id, "step": "distill", "error": f"客户端创建失败: {e}",
            })
            return

        # 3. 流式调 LLM
        user_prompt = f"以下是 {len(samples)} 篇样本, 请提炼 9 轴风格指纹:\n\n{samples_concat}"
        partial = ""
        last_push = 0.0  # v4.1.8.2 (审计 B6): 50ms 节流, 同 _deai_run
        cancel_event = None
        with self._deai_lock:
            _info = self._deai_tasks.get(task_id)
            if _info:
                cancel_event = _info.get("cancel_event")
        cancelled = False
        try:
            stream = await client.chat.completions.create(
                model=self._config.model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT_DISTILL_STYLE},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.4,  # 蒸馏要稳定, 低温
                stream=True,
            )
            async for event in stream:
                if cancel_event is not None and cancel_event.is_set():
                    cancelled = True
                    break
                if not event.choices:
                    continue
                delta = event.choices[0].delta
                content = getattr(delta, "content", None) if delta else None
                if content:
                    partial += content
                    now = time.time()
                    if now - last_push >= 0.05:
                        self._push("onDeaiStream", {
                            "task_id": task_id,
                            "step": "distill",
                            "partial": partial,
                        })
                        last_push = now
        except Exception as e:
            logger.error(f"distill {task_id} LLM 异常: {type(e).__name__}: {e}")
            self._push("onDeaiError", {
                "task_id": task_id, "step": "distill",
                "error": f"{type(e).__name__}: {e}", "partial": partial,
            })
            return
        finally:
            try:
                await client.close()
            except Exception:
                pass

        # v4.3.0: 蒸馏取消 — 结构化 payload (同 _deai_run)
        if cancelled:
            self._push("onDeaiError", {
                "task_id": task_id, "step": "distill", "error": "已取消",
                "cancelled": True, "partial": partial,
            })
            return

        # 4. 落盘 style-card.md
        try:
            r = self._style_loader.save_style_card(slug, partial)
            # v4.1.8.2 (审计 B6): 补推一次全量, 保证收尾帧完整
            self._push("onDeaiStream", {"task_id": task_id, "step": "distill", "partial": partial})
            self._push("onDeaiComplete", {
                "task_id": task_id,
                "step": "distill",
                "slug": slug,
                "result": partial,
                "card_chars": r["card_chars"],
                "distilled_at": r["distilled_at"],
            })
        except Exception as e:
            logger.error(f"distill {task_id} 落盘失败: {e}")
            self._push("onDeaiError", {
                "task_id": task_id, "step": "distill",
                "error": f"落盘失败: {e}", "partial": partial,
            })
            return

        with self._deai_lock:
            self._deai_tasks.pop(task_id, None)

    # ==================== 内部 ====================

    def _collect_results(self, engine: Optional[ProcessingEngine] = None) -> dict:
        """遍历 engine.tasks, 返回 {file_key: result_dict}.

        v4.1.8.1 (H1): 支持显式传 engine (start_proofread 的 run() 线程用它
        绑定的局部 engine 调用), 不再无条件读 self._engine — 避免旧任务线程
        收尾时 self._engine 已被新任务替换导致错收新任务的结果.
        """
        eng = engine if engine is not None else self._engine
        if eng is None:
            return {}
        results = {}
        for file_key, task in eng.tasks.items():
            if task.result is not None:
                results[file_key] = {
                    "file_path": str(task.file_path),
                    "status": task.status.value,
                    "result": task.result.to_dict() if task.result else None,
                }
        return results

    def _push(self, event_name: str, data=None):
        """通过 evaluate_js 推送到前端, 33ms 节流避免卡 webview (30 FPS).

        队列化: 高频 push 累积在 self._push_buffer, 33ms 后批量 flush.

        v4.1.4: 节流 100ms -> 33ms. 原因:
        - 100ms (10 FPS) 流式滚字看起来像"刷出来", 用户体验差.
        - 33ms (30 FPS) 流畅, 接近 monitor refresh rate, 跟前端 RAF
          (requestAnimationFrame) 渲染对齐, 滚字无卡顿.
        - 跨线程 evaluate_js 频率从 10/s 提升到 30/s, 仍远低于 UI 主线程负载
          (webview 内部 60 FPS 渲染), 不会卡 WebView.

        版本演进:
        - v4.0/v4.1.0: 50ms (20 FPS)
        - v4.1.1/v4.1.2/v4.1.3 (I2): 100ms (10 FPS) — 用户报告"刷出来"感
        - v4.1.4: 33ms (30 FPS) — 平衡流畅度 + 跨线程 evaluate_js 压力
        """
        with self._push_throttle_lock:
            self._push_buffer.append((event_name, data))
            if self._push_pending:
                return
            # v4.1.8.2 (审计 B5): 删除旧的"距上次 flush 已过 33ms 立即同步 flush"
            # 分支 — 它在当前控制流下不可达 (依赖 _last_push_time 每次清零的脆弱
            # 不变量), 且分支体内持非重入锁调 _flush() 会同线程自死锁. 统一走
            # Timer 延迟 flush, 行为不变, 拆掉死锁地雷.
            self._push_pending = True
            self._last_push_time = time.time()
            threading.Timer(0.033, self._flush).start()

    def _flush(self):
        """批量推送到前端.

        v4.1.3 (F3 / I3 / I4) 合并策略:
        - 大多数事件: 同名覆盖 (后到的赢, 流式 partial 类适用)
        - onLog: 累积拼接 (避免 100ms 内多条日志只留最后一条, 丢中间)
        - onFileStart / onFileDone / onTaskComplete / onDeaiComplete / onDeaiError
          / onDeaiStream / onFilesDropped: 保留所有 (同名不合并),
          因为这些是离散事件点, 合并会丢 file 进度
        - onStatsUpdate: 同名覆盖 (只关心最新统计)
        """
        # 事件分类常量 (在函数外也行, 但放内部便于测试隔离)
        # 累积类: 字符串拼接, 多个同类合成单条
        ACCUMULATE_EVENTS = {"onLog"}
        # 允许多个类: 同名事件不合并, 全部保留
        # v4.1.8.2 (审计 B8/F12): 补 onFetchModelsComplete — 它带 task_id 是
        # 离散事件, 旧版落入"同名覆盖"类, 并发"测试连接 + 拉取模型"落在同一
        # 33ms 窗口时先完成者的结果被覆盖, 前端 pending id 永久悬挂
        MULTI_ALLOWED = {
            "onFileStart", "onFileDone", "onFileCompleted",
            "onTaskComplete", "onDeaiComplete", "onDeaiError",
            "onDeaiStream", "onFilesDropped", "onFetchModelsComplete",
        }
        with self._push_throttle_lock:
            if not self._push_buffer:
                self._push_pending = False
                return
            merged: dict[str, object] = {}  # 覆盖类
            multi: list[tuple[str, object]] = []  # 允许多个类, 顺序保留
            for name, data in self._push_buffer:
                if name in ACCUMULATE_EVENTS:
                    # 累积拼接 (data 通常是 string)
                    prev = merged.get(name)
                    if prev is None:
                        merged[name] = data if isinstance(data, str) else str(data)
                    else:
                        sep = "" if (isinstance(prev, str) and prev.endswith("\n")) else "\n"
                        merged[name] = (
                            (prev if isinstance(prev, str) else str(prev))
                            + sep
                            + (data if isinstance(data, str) else str(data))
                        )
                elif name in MULTI_ALLOWED:
                    # 保留所有同名事件
                    multi.append((name, data))
                else:
                    # 默认同名覆盖 (onStream, onStatsUpdate, onFetchModelsComplete 等)
                    merged[name] = data
            events = list(merged.items()) + multi
            self._push_buffer.clear()
            self._push_pending = False
            self._last_push_time = 0.0
        if self._window is None:
            return
        # 序列化 + 推 (v4.1 M4: 用 _serialize 替代 default=str,
        # 能正确处理 Path / dataclass / Enum 等, 不再退化为 str repr)
        payload = json.dumps(
            events, ensure_ascii=False, default=self._serialize
        )
        # 用 textContent 替代 innerHTML, 防 XSS
        js = f"window.app.handleEventBatch({payload})"
        try:
            self._window.evaluate_js(js)
        except Exception as e:
            # evaluate_js 失败不致命 (比如 webview 关闭中)
            logger.error(f"[push error] {type(e).__name__}: {e}")

    @staticmethod
    def _serialize(obj):
        """v4.1 (M4): json.dumps 的 default 回调, 把 Path/dataclass/Enum 序列化为 JSON 友好类型.

        替代之前的 default=str, 后者把所有对象退化为 str repr, 失去结构 (例如 Path("a/b/c") 变 "'a\\\\b\\\\c'").
        """
        from dataclasses import asdict, is_dataclass
        if isinstance(obj, Path):
            return str(obj)
        if isinstance(obj, Enum):
            return obj.value
        if is_dataclass(obj):
            return asdict(obj)
        if isinstance(obj, (list, tuple)):
            return [Backend._serialize(x) for x in obj]
        if isinstance(obj, dict):
            return {k: Backend._serialize(v) for k, v in obj.items()}
        # 兜底: str (旧行为)
        return str(obj)
