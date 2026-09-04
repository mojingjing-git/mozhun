"""
pywebview 后端 Bridge API (v4.0 Phase 3 完整版).

借鉴自 https://pywebview.flowrl.com/ (BSD-3-Clause)
借鉴内容: Bridge 模式 + evaluate_js 流式推送范式
借鉴方式: 思路借鉴,代码自写
Copyright (c) 2014-2024 Roman Yurchak
"""
import asyncio
import json
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
    CHUNKING_PRESETS,
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


# v4.1.5 (🔴 修复 1): onFileStart 推送 original 字段的字符数阈值.
# 超过这个大小不推 original, 前端 fallback 调 read_file(path) 读.
# 50K 字 ≈ 100KB UTF-8, JSON 序列化 + evaluate_js 单次 payload ~150KB,
# 仍可接受 (>50K 后切前端 read_file 路径, 避免大 payload 卡 evaluate_js).
_ORIGINAL_PUSH_LIMIT = 50000


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
        self._config = load_config()  # v3.0 的配置加载
        self._push_throttle_lock = threading.Lock()
        self._last_push_time = 0.0
        self._push_buffer: list[tuple[str, object]] = []
        self._push_pending = False
        # 后台线程用的 event loop (start_proofread 时初始化)
        self._loop: Optional[asyncio.AbstractEventLoop] = None
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

    def set_config(self, key: str, value) -> None:
        # JS 端做 500ms 防抖, Python 这边只 set
        if not hasattr(self._config, key):
            return
        # 类型转换: 数字字段
        try:
            field_type = self._config.__dataclass_fields__[key].type
            if field_type is float and not isinstance(value, float):
                value = float(value)
            elif field_type is int and not isinstance(value, int):
                value = int(value)
        except (AttributeError, KeyError, TypeError, ValueError):
            pass
        if key == "api_key":
            # v4.1.8.1 (审计修复 H2): 拒绝把混淆串当明文写回 (旧版前端残留 /
            # 用户误粘贴 obf: 值). 只接受真正的明文新 key.
            if isinstance(value, str) and value.startswith("obf:"):
                logger.warning("set_config 忽略 obf: 前缀的 api_key (疑似混淆串回写)")
                return
            if value == "":
                # 空串 = 用户清空 key (允许), 仅在有旧值且前端误传空时需小心;
                # 此处按语义允许显式清空.
                pass
        setattr(self._config, key, value)

    def save_config(self) -> dict:
        """保存配置到磁盘, 返回结果 (前端可读)."""
        try:
            save_config(self._config)
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def get_prompt_modes(self) -> list[dict]:
        return [{"key": k, "label": v["label"]} for k, v in PROMPT_MODES.items()]

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

    def read_file(self, path: str) -> str:
        """同步读文件 (用于前端预览小文件, 大文件通过 stream 走)."""
        try:
            return read_file_text(Path(path))
        except Exception as e:
            return f"[读取错误] {e}"

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
        """window.events.loaded 触发: 等 DOM 就绪, 给 #drop-zone 绑 drop 监听.

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
        except Exception as e:
            logger.error(f"init_drag_drop 异常: {type(e).__name__}: {e}")

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
            data_transfer = event.get("dataTransfer", {}) if isinstance(event, dict) else {}
            files = data_transfer.get("files", []) or []
            paths = []
            for f in files:
                if isinstance(f, dict):
                    p = f.get("pywebviewFullPath")
                    if p:
                        paths.append(p)
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

            # 1. OpenClipboard (失败时重试一次, 避免和其他 app 抢剪贴板)
            for attempt in range(2):
                if user32.OpenClipboard(0):
                    break
                if attempt == 0:
                    time.sleep(0.05)  # 50ms 后重试
            else:
                return {"ok": False, "error": "OpenClipboard 失败 (其他应用占用?)"}

            try:
                user32.EmptyClipboard()
                # 2. GlobalAlloc + lstrcpy 写入 Unicode
                text_bytes = (text + "\0").encode("utf-16-le")
                h = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(text_bytes))
                if not h:
                    return {"ok": False, "error": "GlobalAlloc 失败"}
                try:
                    ptr = kernel32.GlobalLock(h)
                    if not ptr:
                        return {"ok": False, "error": "GlobalLock 失败"}
                    try:
                        ctypes.memmove(ptr, text_bytes, len(text_bytes))
                    finally:
                        kernel32.GlobalUnlock(h)
                    if not user32.SetClipboardData(CF_UNICODETEXT, h):
                        return {"ok": False, "error": "SetClipboardData 失败"}
                    # 成功: SetClipboardData 后 h 归系统, 不能 GlobalFree
                    h = None
                finally:
                    if h:
                        kernel32.GlobalFree(h)
            finally:
                user32.CloseClipboard()
            return {"ok": True, "length": len(text)}
        except Exception as e:
            logger.error(f"copy_to_clipboard 异常: {type(e).__name__}: {e}")
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    # ==================== 校对任务 API ====================

    def start_proofread(self, file_paths: list[str], mode_key: str,
                        custom_prompt: str = "",
                        chunking_preset: str = "balanced") -> dict:
        """启动校对任务 (后台线程), 立即返回 task_id.

        v4.1.8.1 (审计修复 H1): 并发重入保护.
        旧实现每次调用都无条件重建 engine + 起新线程, 不检查上一任务是否在跑:
          - 重复 start -> 旧引擎线程仍在跑, 其回调闭包读动态 self._engine.tasks[k]
            (已被新 engine 替换) -> KeyError -> 被当普通错误反复整文件重试误标 FAILED;
          - 更糟时两个线程 run_until_complete 同一 engine, 交叉写断点.
        修复: 若上一任务线程仍存活, 先 cancel 并 join 等它退出 (最多 5s),
        再启动新任务; 若旧线程迟迟不退则拒绝启动并返回错误.
        """
        # --- 并发重入保护: 先清理上一任务 (若有) ---
        prev_thread = self._current_task_thread
        if prev_thread is not None and prev_thread.is_alive():
            logger.warning("start_proofread: 上一任务仍在运行, 先取消并等待退出")
            if self._engine is not None:
                self._engine.cancel()
            prev_thread.join(timeout=5.0)
            if prev_thread.is_alive():
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
        self._current_task_id = task_id

        # 准备任务
        engine = ProcessingEngine(self._config)
        engine.prepare_tasks([Path(p) for p in file_paths])
        self._engine = engine  # 供 pause/cancel/resume/_collect_results 引用

        # 回调注册: 把事件转 evaluate_js 推送.
        # v4.1.8.1 (H1): 回调闭包一律捕获局部 engine 引用 (默认参数绑定),
        # 不再运行时读动态 self._engine — 否则上一任务线程跑回调时若
        # self._engine 已被新任务替换, tasks[k] 直接 KeyError.
        engine.on_log = lambda msg: self._push("onLog", msg)
        engine.on_stream = lambda k, t: self._push("onStream", {
            "file_key": k, "partial": t,
        })
        # v4.1.5 (🔴 修复 1): onFileStart 带 original 字段, 让前端左栏原文字
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
        engine.on_file_done = lambda k: self._push("onFileDone", k)
        engine.on_file_completed = lambda k: self._push("onFileCompleted", k)
        engine.on_stats_update = lambda s: self._push("onStatsUpdate", {
            "total_files": s.total_files,
            "completed_files": s.completed_files,
            "total_tokens": s.total_tokens,
            "elapsed": s.elapsed,
            "speed": s.speed,
            "eta": s.eta,
        })

        # 后台线程跑 (避免阻塞 pywebview 主线程)
        def run(_eng: ProcessingEngine = engine):
            # v4.1 (I6): 顶层 try/except 兜底, 防止 run_async 抛未预期异常
            # 导致前端 isProcessing 永远卡在 true.
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._loop = loop
            try:
                try:
                    loop.run_until_complete(_eng.run_async())
                except Exception as e:
                    logger.error(f"run_async 未预期异常: {e}")
                    self._push("onTaskComplete", {"error": str(e)})
                    return
                finally:
                    loop.close()
                    self._loop = None
            except Exception as e:
                # 兜底: loop 创建/关闭异常
                logger.error(f"start_proofread run() 异常: {e}")
                self._push("onTaskComplete", {"error": str(e)})
                return
            # 跑完推送给前端 (collect 用 engine 局部引用, 不受 self._engine 后续变化影响)
            self._push("onTaskComplete", self._collect_results(_eng))

        self._current_task_thread = threading.Thread(target=run, daemon=True)
        self._current_task_thread.start()

        return {"task_id": task_id, "total_files": len(file_paths)}

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
        if fmt == "md":
            ext = "md"
        elif file_path:
            ext = Path(file_path).suffix.lstrip(".") or "txt"
        else:
            ext = "txt"

        # YYMMDD-HHMMSS 时间戳 (12位)
        timestamp = datetime.now().strftime("%y%m%d-%H%M%S")
        default_name = f"{stem}-{timestamp}.{ext}"

        try:
            result = self._window.create_file_dialog(
                webview.FileDialog.SAVE,
                directory=src_dir,
                save_filename=default_name,
                file_types=(f"{ext.upper()} files (*.{ext})", "All files (*.*)"),
            )
        except Exception as e:
            logger.error(f"export_result 弹保存对话框失败: {type(e).__name__}: {e}")
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
            logger.error(f"export_result 写文件失败: {type(e).__name__}: {e}")
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

    def deai_step3_audit(self, rewritten: str, style_card_slug: str = "") -> str:
        """Step 3: 三维评分 1-10 + (可选) 8 轴自评.

        v4.1.7: 加 style_card_slug, 走 V5 audit prompt (3 维 + 8 轴自评).
        借鉴自 https://github.com/jianshuo/claude-skills (MIT License) 思路,
        思路借鉴, 无代码复制.
        """
        return self._deai_start("audit", rewritten, sample="", style_card_slug=style_card_slug)

    def _deai_start(self, step: str, text: str, sample: str = "", style_card_slug: str = "") -> str:
        """启动一个 deai 后台线程, 立即返回 task_id."""
        task_id = f"deai_{step}_{uuid.uuid4().hex[:8]}"
        with self._deai_lock:
            self._deai_tasks[task_id] = {
                "step": step,
                "started": time.time(),
                "style_card_slug": style_card_slug,
            }

        def run():
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    loop.run_until_complete(self._deai_run(task_id, step, text, sample, style_card_slug))
                finally:
                    loop.close()
            except Exception as e:
                # v4.1.3 (F3): 只推 onDeaiError, 不推 onDeaiComplete.
                # 之前同时推两个, _flush 合并逻辑 dict 同名覆盖, onDeaiComplete 覆盖 onDeaiError,
                # 前端 handleDeaiComplete 把 status 设为 'done' 完全没看 error -> 用户看到空 output + '已完成'.
                logger.error(f"deai {step} task={task_id} 顶层异常: {type(e).__name__}: {e}")
                self._push("onDeaiError", {"task_id": task_id, "error": str(e)})

        threading.Thread(target=run, daemon=True, name=f"deai-{step}").start()
        return task_id

    async def _deai_run(self, task_id: str, step: str, text: str, sample: str, style_card_slug: str = "") -> None:
        """deai 后台主循环: 调 LLM, 流式推 partial, 完成推 complete."""
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

        # 选 system prompt (v4.1.7: 走 V5 路径, 带 9 轴风格卡注入)
        system_prompt = self._build_deai_prompt(step, sample, style_card_slug)
        user_prompt = self._build_deai_user_prompt(step, text, style_card_slug)

        partial = ""
        # v4.1 (I1): try/finally 保证 client.close() 一定被调用, 避免 httpx 连接泄漏
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
            async for event in stream:
                if not event.choices:
                    continue
                delta = event.choices[0].delta
                content = getattr(delta, "content", None) if delta else None
                if content:
                    partial += content
                    # 流式推 partial (前端 throttle 50ms 后再渲染)
                    self._push("onDeaiStream", {
                        "task_id": task_id,
                        "step": step,
                        "partial": partial,
                    })
        except Exception as e:
            # v4.1.3 (F3): 只推 onDeaiError, 不推 onDeaiComplete
            # 避免 _flush 合并时 onDeaiComplete 覆盖 onDeaiError, 让前端看不到错误.
            logger.error(f"deai {task_id} LLM 流式调用异常: {type(e).__name__}: {e}")
            self._push("onDeaiError", {"task_id": task_id, "error": str(e), "partial": partial})
            return
        finally:
            # I1: 关闭 httpx 连接池, 否则长跑会泄漏 socket
            try:
                await client.close()
            except Exception:
                pass

        # 完成
        self._push("onDeaiComplete", {"task_id": task_id, "step": step, "result": partial})
        with self._deai_lock:
            self._deai_tasks.pop(task_id, None)

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
        task_id = f"distill_{slug}_{uuid.uuid4().hex[:8]}"
        with self._deai_lock:
            self._deai_tasks[task_id] = {
                "step": "distill",
                "slug": slug,
                "started": time.time(),
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

        threading.Thread(target=run, daemon=True, name=f"deai-distill-{slug}").start()
        return task_id

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
                if not event.choices:
                    continue
                delta = event.choices[0].delta
                content = getattr(delta, "content", None) if delta else None
                if content:
                    partial += content
                    self._push("onDeaiStream", {
                        "task_id": task_id,
                        "step": "distill",
                        "partial": partial,
                    })
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

        # 4. 落盘 style-card.md
        try:
            r = self._style_loader.save_style_card(slug, partial)
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
            now = time.time()
            elapsed = now - self._last_push_time
            if self._push_pending:
                return
            if elapsed >= 0.033 and self._last_push_time > 0:
                # 距上次 flush 已过 33ms, 立即同步 flush
                self._flush()
            else:
                # 33ms 内合并推送
                self._push_pending = True
                self._last_push_time = now
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
        MULTI_ALLOWED = {
            "onFileStart", "onFileDone", "onFileCompleted",
            "onTaskComplete", "onDeaiComplete", "onDeaiError",
            "onDeaiStream", "onFilesDropped",
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
