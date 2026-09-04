import asyncio
import base64
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import hashlib
import json
import time
from pathlib import Path

from app.logger import setup_logging

logger = setup_logging()


# === API key 简单伪装 ===
# 注意：这不是真正的加密，只是为了避免明文落盘到 ~/.proofreader/last_config.json。
# 真正保密应使用系统 keyring。这里仅防意外泄露。
_CONFIG_OBFUSCATE_KEY = b"ProofreaderConfigObf2026"


def _obf(s: str) -> str:
    """XOR + base64 伪装 api_key (前缀 obf: 标识)。"""
    if not s:
        return ""
    raw = s.encode("utf-8")
    xored = bytes(
        b ^ _CONFIG_OBFUSCATE_KEY[i % len(_CONFIG_OBFUSCATE_KEY)]
        for i, b in enumerate(raw)
    )
    return "obf:" + base64.b64encode(xored).decode("ascii")


def _deobf(s: str) -> str:
    """_obf 逆运算; 非 obf: 前缀视为明文 (兼容旧版)。"""
    if not s:
        return ""
    if not s.startswith("obf:"):
        return s
    try:
        xored = base64.b64decode(s[4:])
        return bytes(
            b ^ _CONFIG_OBFUSCATE_KEY[i % len(_CONFIG_OBFUSCATE_KEY)]
            for i, b in enumerate(xored)
        ).decode("utf-8")
    except Exception:
        return ""


def compute_prompt_hash(prompt_mode: str, model: str, custom_prompt: str) -> str:
    """计算 prompt 模式指纹 — 用于让断点缓存跟随 prompt 配置变化而失效。"""
    raw = f"{prompt_mode}|{model}|{custom_prompt}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class FileResult:
    # 现有字段保留（兼容旧断点）
    original: str
    corrected: str = ""
    token_count: int = 0
    elapsed: float = 0.0
    error: Optional[str] = None
    prompt_hash: str = ""
    # NEW (v3.0+): chunk 级别结果数组
    chunks_results: list["FileResult"] = field(default_factory=list)
    failed_chunks: list[int] = field(default_factory=list)  # 失败 chunk index
    schema_version: int = 2

    @property
    def is_chunked(self) -> bool:
        """是否分块处理（多 chunk）。"""
        return len(self.chunks_results) > 0

    @property
    def corrected_full(self) -> str:
        """完整 corrected 文本（chunk 拼接或单字段）。"""
        if self.is_chunked:
            return "".join(r.corrected for r in self.chunks_results)
        return self.corrected

    @property
    def is_done(self) -> bool:
        """所有 chunk 都完成。"""
        if not self.chunks_results:
            return bool(self.corrected) and not self.error
        return all(not r.error for r in self.chunks_results)

    def to_dict(self) -> dict:
        return {
            "original": self.original,
            "corrected": self.corrected,
            "token_count": self.token_count,
            "elapsed": self.elapsed,
            "error": self.error,
            "prompt_hash": self.prompt_hash,
            "chunks_results": [r.to_dict() for r in self.chunks_results],
            "failed_chunks": list(self.failed_chunks),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "FileResult":
        return cls(
            original=d["original"],
            corrected=d.get("corrected", ""),
            token_count=d.get("token_count", 0),
            elapsed=d.get("elapsed", 0.0),
            error=d.get("error"),
            prompt_hash=d.get("prompt_hash", ""),
            chunks_results=[cls.from_dict(c) for c in d.get("chunks_results", [])],
            failed_chunks=list(d.get("failed_chunks", [])),
            schema_version=d.get("schema_version", 2),
        )


@dataclass
class FileTask:
    file_path: Path
    status: TaskStatus = TaskStatus.PENDING
    original_text: str = ""
    result: Optional[FileResult] = None
    start_time: float = 0.0
    end_time: float = 0.0
    error_message: str = ""

    @property
    def is_done(self) -> bool:
        return self.result is not None and not self.result.error

    def to_dict(self) -> dict:
        return {
            "file_path": str(self.file_path),
            "status": self.status.value,
            "original_text": self.original_text,
            "result": self.result.to_dict() if self.result else None,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "FileTask":
        task = cls(
            file_path=Path(d["file_path"]),
            status=TaskStatus(d["status"]),
            original_text=d.get("original_text", ""),
        )
        if d.get("result"):
            task.result = FileResult.from_dict(d["result"])
        return task


@dataclass
class ProjectConfig:
    api_base: str = ""
    api_key: str = ""
    model: str = ""
    timeout: int = 120
    max_retries: int = 3
    concurrency: int = 2
    output_format: str = "txt"
    prompt_mode: str = "strict"
    custom_prompt: str = ""
    temperature: float = 0.1
    output_dir: str = ""
    chunking_preset: str = "balanced"  # NEW (v3.0+): chunking 档位 (fast/balanced/high_context/large/whole_file)
    schema_version: int = 2  # NEW (v3.0+): 配置 schema 版本号 (Phase 3 断点迁移用)
    context_max_chars: int = 800   # NEW (v3.0+): 跨段上下文最大字符数
    context_max_chunks: int = 2    # NEW (v3.0+): 跨段上下文取最近几个 chunk

    def to_dict(self) -> dict:
        return {
            "api_base": self.api_base,
            "api_key": _obf(self.api_key),
            "model": self.model,
            "timeout": self.timeout,
            "max_retries": self.max_retries,
            "concurrency": self.concurrency,
            "output_format": self.output_format,
            "prompt_mode": self.prompt_mode,
            "custom_prompt": self.custom_prompt,
            "temperature": self.temperature,
            "output_dir": self.output_dir,
            "chunking_preset": self.chunking_preset,
            "schema_version": self.schema_version,
            "context_max_chars": self.context_max_chars,
            "context_max_chunks": self.context_max_chunks,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ProjectConfig":
        return cls(
            api_base=d.get("api_base", ""),
            api_key=_deobf(d.get("api_key", "")),
            model=d.get("model", ""),
            timeout=d.get("timeout", 120),
            max_retries=d.get("max_retries", 3),
            concurrency=d.get("concurrency", 2),
            output_format=d.get("output_format", "txt"),
            prompt_mode=d.get("prompt_mode") or "strict",
            custom_prompt=d.get("custom_prompt", ""),
            temperature=d.get("temperature", 0.1),
            output_dir=d.get("output_dir", ""),
            chunking_preset=d.get("chunking_preset") or "balanced",
            schema_version=d.get("schema_version", 2),
            context_max_chars=d.get("context_max_chars", 800),
            context_max_chunks=d.get("context_max_chunks", 2),
        )


@dataclass
class ProcessStats:
    total_files: int = 0
    completed_files: int = 0
    success_files: int = 0
    failed_files: int = 0
    total_tokens: int = 0
    start_time: float = 0.0
    elapsed: float = 0.0

    @property
    def speed(self) -> float:
        if self.elapsed > 0:
            return self.total_tokens / self.elapsed
        return 0.0

    @property
    def eta(self) -> float:
        if self.completed_files > 0 and self.elapsed > 0:
            rate = self.completed_files / self.elapsed
            remaining = self.total_files - self.completed_files
            return remaining / rate if rate > 0 else 0.0
        return 0.0

    @property
    def progress_pct(self) -> float:
        if self.total_files > 0:
            return (self.completed_files / self.total_files) * 100
        return 0.0

    def to_dict(self) -> dict:
        return {
            "total_files": self.total_files,
            "completed_files": self.completed_files,
            "success_files": self.success_files,
            "failed_files": self.failed_files,
            "total_tokens": self.total_tokens,
            "start_time": self.start_time,
            "elapsed": self.elapsed,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ProcessStats":
        return cls(
            total_files=d.get("total_files", 0),
            completed_files=d.get("completed_files", 0),
            success_files=d.get("success_files", 0),
            failed_files=d.get("failed_files", 0),
            total_tokens=d.get("total_tokens", 0),
            start_time=d.get("start_time", 0.0),
            elapsed=d.get("elapsed", 0.0),
        )


def read_file_text(path: Path) -> str:
    for encoding in ["utf-8", "gbk", "gb2312", "gb18030"]:
        try:
            return path.read_text(encoding=encoding)
        except (UnicodeDecodeError, UnicodeError):
            continue
    return path.read_text(encoding="utf-8", errors="replace")


async def read_file_text_async(path: Path) -> str:
    """read_file_text 的异步包装 — 把阻塞 IO 放到线程池,避免事件循环卡顿。"""
    return await asyncio.to_thread(read_file_text, path)


async def save_checkpoint_async(file_path: Path, task: FileTask) -> None:
    """save_checkpoint 的异步包装。"""
    await asyncio.to_thread(save_checkpoint, file_path, task)


CONFIG_DIR = Path.home() / ".proofreader"
CONFIG_DIR.mkdir(exist_ok=True)
CONFIG_FILE = CONFIG_DIR / "last_config.json"
CHECKPOINT_DIR = CONFIG_DIR / "checkpoints"
CHECKPOINT_DIR.mkdir(exist_ok=True)


# v4.1 (M2): 把 chunking 预设从 processor.py + web_backend.py 抽到 utils.py 单点。
# 两边 import 同一个常量, 避免 label/max_chars 漂移。
#
# 借鉴自 https://github.com/tianhm/ollama-batch-processor (MIT License)
# 借鉴内容: chunking preset 分档设计思路
# 借鉴方式: 思路借鉴,无代码复制
# Copyright (c) 2025 tianhm
CHUNKING_PRESETS = [
    {"key": "fast",         "label": "快速 (2000 字)",   "max_chars": 2000},
    {"key": "balanced",     "label": "均衡 (3000 字)",   "max_chars": 3000},
    {"key": "high_context", "label": "高上下文 (4000)",  "max_chars": 4000},
    {"key": "large",        "label": "大块 (6000)",       "max_chars": 6000},
    {"key": "whole_file",   "label": "整文件 (不分块)",  "max_chars": 0},
]
# 字符串 -> dict 索引 (processor 内部用)
CHUNKING_PRESETS_MAP = {p["key"]: p for p in CHUNKING_PRESETS}
DEFAULT_CHUNK_PRESET = "balanced"


def save_config(config: ProjectConfig) -> None:
    try:
        CONFIG_FILE.write_text(
            json.dumps(config.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        logger.error(f"保存配置失败: {e}")


def load_config() -> ProjectConfig:
    try:
        if CONFIG_FILE.exists():
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            return ProjectConfig.from_dict(data)
    except Exception as e:
        logger.error(f"加载配置失败: {e}")
    return ProjectConfig()


def save_checkpoint(file_path: Path, task: FileTask) -> None:
    try:
        safe_name = str(file_path).replace(":", "_").replace("/", "_").replace("\\", "_")
        cp_file = CHECKPOINT_DIR / f"{safe_name}.json"
        cp_file.write_text(
            json.dumps(task.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        logger.error(f"保存断点失败 [{file_path}]: {e}")


def load_checkpoint(file_path: Path, expected_hash: Optional[str] = None) -> FileTask | None:
    """加载断点缓存。
    expected_hash: 若提供,则与缓存中 result.prompt_hash 比对,不匹配视为无缓存
    (返回 None),避免 prompt 改了之后旧缓存无声复用。

    v3.0 schema v2:
    - 自动 v1 → v2 迁移(FileResult.to_dict/from_dict 已兼容旧 dict 缺新字段)
    - CANCELLED 状态返回 None (v0.2 修订: 取消状态强制重跑,不读 chunks_results)
    """
    try:
        safe_name = str(file_path).replace(":", "_").replace("/", "_").replace("\\", "_")
        cp_file = CHECKPOINT_DIR / f"{safe_name}.json"
        if cp_file.exists():
            data = json.loads(cp_file.read_text(encoding="utf-8"))
            task = FileTask.from_dict(data)
            # v0.2 修订: CANCELLED 状态不加载,强制重跑
            if task.status == TaskStatus.CANCELLED:
                logger.info(
                    f"[断点] {file_path.name}: 上次被取消,强制重跑"
                )
                return None
            if expected_hash is not None and task.result is not None:
                if task.result.prompt_hash != expected_hash:
                    logger.info(
                        f"缓存 prompt 不匹配 [{file_path}]: "
                        f"old={task.result.prompt_hash or '(empty)'} "
                        f"new={expected_hash},将重新处理"
                    )
                    return None
            return task
    except Exception as e:
        logger.error(f"加载断点失败 [{file_path}]: {e}")
    return None
