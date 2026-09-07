import asyncio
import base64
import os
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


def _deobf_until_plain(s: str) -> str:
    """循环解混淆直到不再带 obf: 前缀。

    v4.1.8.1 (审计修复 H2): 修复历史 api_key 双重混淆污染数据.
    旧版链路缺陷 (web_backend.get_config 回显混淆串 -> 用户保存 -> set_config 把
    obf:xxx 当明文写回 -> 磁盘 obf(obf(key)) 永久损坏) 已产生的损坏配置,
    用本函数在加载时解到底, 自动恢复为明文.
    """
    if not s or not s.startswith("obf:"):
        return s
    seen = 0
    while s.startswith("obf:") and seen < 8:  # 8 层上限, 防死循环
        nxt = _deobf(s)
        if nxt == s:  # 解不动 (损坏数据), 停止
            break
        s = nxt
        seen += 1
    return s


def compute_prompt_hash(
    prompt_mode: str,
    model: str,
    custom_prompt: str,
    chunking_preset: str = "",
    context_max_chars: int = 0,
    context_max_chunks: int = 0,
    temperature: float | None = None,
    api_base: str = "",
    punct_fix: bool = True,
    punct_quote_style: str = "curly",
    punct_fullwidth_alnum: bool = True,
    punct_repeat_compress: bool = False,
    punct_dash_tilde: bool = True,
    md_strip: bool = False,
    harness_enabled: bool = True,
) -> str:
    """计算 prompt/生成配置指纹 — 断点缓存随配置变化而失效。

    v4.1.8.1 (审计修复 C2): 旧版仅纳入 prompt_mode/model/custom_prompt, 改
    chunking_preset / context_max_chars / context_max_chunks / temperature
    会改变生成结果但 hash 不变 -> 静默复用旧断点, 返回与当前档位不符的结果.
    现全部纳入; hash 算法变更使历史断点一次性失效 (配合 C5 语义, 属预期).

    v4.1.8.2 (审计 E16): 补纳 api_base — 同 model 名换端点 (官方 <-> 代理/本地
    网关) 时产出不同, 旧指纹不变会静默复用旧端点的断点.

    v5.1.0: 补纳 harness_enabled — harness 开关改变 LLM 的输出形态
    (整篇全文 vs edit_text 工具调用), 开关切换后旧断点必须失效。
    """
    raw = (
        f"{prompt_mode}|{model}|{custom_prompt}"
        f"|chunk={chunking_preset}|ctxc={context_max_chars}"
        f"|ctxn={context_max_chunks}|temp={temperature}"
        f"|base={api_base}|punct={punct_fix}"
        f"|pq={punct_quote_style}|pa={punct_fullwidth_alnum}"
        f"|pr={punct_repeat_compress}|pd={punct_dash_tilde}"
        # v4.4.2: md_strip 开关无条件纳入 — 全部旧断点一次性失效 (C2/E16 同语义,
        # 评审 P2-9: 与其零失效而漏纳, 不如一次失效保证缓存正确)
        f"|ms={md_strip}"
        # v5.1.0: harness 开关纳入 (输出形态改变; 与 md_strip 同失效语义)
        f"|he={harness_enabled}"
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


def compute_prompt_hash_for_config(cfg: "ProjectConfig") -> str:
    """v5.0.1 (审计 I-3): 从 ProjectConfig 一把算断点指纹.

    生产调用方 (processor) 与测试统一走这里 — 字段集与 compute_prompt_hash
    严格同步且相邻可见, 杜绝"部分传参靠默认值碰巧匹配"的缓存屏障虚标
    (旧 3 处测试只传 8/14 字段, 任何默认值漂移都会静默破坏屏障)."""
    return compute_prompt_hash(
        cfg.prompt_mode, cfg.model, cfg.custom_prompt,
        chunking_preset=cfg.chunking_preset,
        context_max_chars=cfg.context_max_chars,
        context_max_chunks=cfg.context_max_chunks,
        temperature=cfg.temperature,
        api_base=cfg.api_base,
        punct_fix=cfg.punct_fix,
        punct_quote_style=cfg.punct_quote_style,
        punct_fullwidth_alnum=cfg.punct_fullwidth_alnum,
        punct_repeat_compress=cfg.punct_repeat_compress,
        punct_dash_tilde=cfg.punct_dash_tilde,
        md_strip=cfg.md_strip_before_llm,
        harness_enabled=cfg.harness_enabled,
    )


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
    # v5.1.0: harness 部分成功标记 (边界 12) — 存在未生效的编辑建议/整轮级
    # 告警时置位, UI 显示"完成（部分建议未采纳）"。不新增 TaskStatus 枚举。
    warnings: bool = False

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
            "warnings": self.warnings,
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
            warnings=bool(d.get("warnings", False)),
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
    # v4.1.8.2 (审计 E2): 读文件失败占位标记 — 这类 task 不再进 pending 重打 API
    # (旧逻辑空文本会发给 LLM, 轻则 400 覆盖真实错误, 重则产出垃圾"成功"结果).
    # 仅内存态, 不写入断点 (to_dict 不含该字段).
    skip: bool = False

    @property
    def is_done(self) -> bool:
        return self.result is not None and not self.result.error

    def to_dict(self) -> dict:
        return {
            "file_path": str(self.file_path),
            "status": self.status.value,
            "original_text": self.original_text,
            "result": self.result.to_dict() if self.result else None,
            # v4.1.8.2 (审计 E9): 补齐 task 级时间/错误字段, 断点加载后不再丢
            "start_time": self.start_time,
            "end_time": self.end_time,
            "error_message": self.error_message,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "FileTask":
        task = cls(
            file_path=Path(d["file_path"]),
            status=TaskStatus(d["status"]),
            original_text=d.get("original_text", ""),
            start_time=d.get("start_time", 0.0),
            end_time=d.get("end_time", 0.0),
            error_message=d.get("error_message", ""),
        )
        if d.get("result"):
            task.result = FileResult.from_dict(d["result"])
        return task


# v5.0.0 (Phase A4): 模式精简 — 3 个已砍模式静默归一.
# 语义: from_dict 时 in-memory 生效; 磁盘旧值保留到下次防抖写回 (下次启动再归一,
# 行为等价, 审计时勿据磁盘值误判未生效). 对 punct_local/md_local 零影响.
_LEGACY_MODE_MAP = {
    "deep_polish": "polish",     # 重润色 → 改走去 AI 味视图, 常规需求落在轻润色
    "anti_rambling": "polish",   # 去流水账 → 同上
    "long_sentence": "polish",   # 长句拆分 → 已并入 polish 处理规则 4
}


def _normalize_legacy_mode(mode: str) -> str:
    """旧配置的已砍模式归一为保留模式 (未命中原样返回)."""
    return _LEGACY_MODE_MAP.get(mode, mode)


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
    schema_version: int = 3  # v3.0+ 配置 schema 版本号; v5.0.0: 2→3 (模式精简+归一化)
    context_max_chars: int = 800   # NEW (v3.0+): 跨段上下文最大字符数
    context_max_chunks: int = 2    # NEW (v3.0+): 跨段上下文取最近几个 chunk
    ui_theme: str = "auto"  # NEW (v4.1.9): 主题三态 (auto/light/dark), Win11 §2.3 个人原则 — 主题持久化
    ui_skin: str = "ink"  # NEW (v4.4.0): 界面皮肤 (fluent=Win11 Fluent 2 / ink=水墨宣纸); v4.4.1 起默认 ink
    md_strip_before_llm: bool = False  # NEW (v4.4.2): 送 LLM 前先剥离 Markdown 标记 (app/md_strip.py, 零成本)
    punct_fix: bool = True  # NEW (v4.3.3): 发送 LLM 前先本地修复半角标点 (app/punct_fix.py, 零成本)
    # v4.3.4: 标点修复 v2 规则选项 (默认值与 app/punct_fix.py::_DEFAULT_OPTIONS 严格一致)
    punct_quote_style: str = "curly"    # 引号风格: curly=弯“” (推荐) / rect=直角「」 (指北争议项)
    punct_fullwidth_alnum: bool = True   # 全角字母/数字归一化 (ＡＢＣ１２３→ABC123; 指北 B4)
    punct_repeat_compress: bool = False  # 重复标点压缩 ！！！→！ (指北 B1, 默认关)
    punct_dash_tilde: bool = True        # 破折号——/波浪～ 补齐 (GB/T 15834)
    # v5.0.2: DeAI rewrite 步后置三开关 — 只影响去 AI 味视图, **不进 compute_prompt_hash**
    # (裁定见 AGENTS.md §35: DeAI 无断点缓存体系, 塞进校对断点指纹只会让校对断点无谓失效)
    deai_strip_after: bool = True   # rewrite 完整输出后剥离 Markdown 标记 (app/md_strip.py, 空结果兜底)
    deai_ai_score: bool = True      # rewrite 完成后跑客户端 0-100 AI 味评分 (app/ai_score_local.py, 零 LLM)
    deai_revise: bool = False       # 评分 >= REVISE_THRESHOLD 时以出戏句反馈追加一轮改写 (额外 1 次 LLM, <=2 万字)
    # v5.1.0: 校对 harness 化总开关 (用户逃生口)。生效条件 = 本开关为 True 且
    # prompt_mode ∈ {strict, polish} (白名单双决策, 见 AGENTS.md §36)。
    # True 时 strict/polish 走 Edit 工具链 (LLM 返回编辑建议, 客户端 apply),
    # 纳入 compute_prompt_hash (|he=) — 切换开关会使旧断点一次性失效。
    harness_enabled: bool = True

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
            "ui_theme": self.ui_theme,
            "ui_skin": self.ui_skin,
            "md_strip_before_llm": self.md_strip_before_llm,
            "punct_fix": self.punct_fix,
            "punct_quote_style": self.punct_quote_style,
            "punct_fullwidth_alnum": self.punct_fullwidth_alnum,
            "punct_repeat_compress": self.punct_repeat_compress,
            "punct_dash_tilde": self.punct_dash_tilde,
            "deai_strip_after": self.deai_strip_after,
            "deai_ai_score": self.deai_ai_score,
            "deai_revise": self.deai_revise,
            "harness_enabled": self.harness_enabled,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ProjectConfig":
        return cls(
            api_base=d.get("api_base", ""),
            api_key=_deobf_until_plain(d.get("api_key", "")),
            model=d.get("model", ""),
            timeout=d.get("timeout", 120),
            max_retries=d.get("max_retries", 3),
            concurrency=d.get("concurrency", 2),
            output_format=d.get("output_format", "txt"),
            prompt_mode=_normalize_legacy_mode(d.get("prompt_mode") or "strict"),
            custom_prompt=d.get("custom_prompt", ""),
            temperature=d.get("temperature", 0.1),
            output_dir=d.get("output_dir", ""),
            chunking_preset=d.get("chunking_preset") or "balanced",
            schema_version=3,  # v5.0.0: 旧文件 (值 2) 加载即升级, to_dict 落盘 3
            context_max_chars=d.get("context_max_chars", 800),
            context_max_chunks=d.get("context_max_chunks", 2),
            ui_theme=d.get("ui_theme") or "auto",
            ui_skin=d.get("ui_skin") or "ink",
            md_strip_before_llm=bool(d.get("md_strip_before_llm", False)),
            punct_fix=bool(d.get("punct_fix", True)),
            punct_quote_style=d.get("punct_quote_style") or "curly",
            punct_fullwidth_alnum=bool(d.get("punct_fullwidth_alnum", True)),
            punct_repeat_compress=bool(d.get("punct_repeat_compress", False)),
            punct_dash_tilde=bool(d.get("punct_dash_tilde", True)),
            deai_strip_after=bool(d.get("deai_strip_after", True)),
            deai_ai_score=bool(d.get("deai_ai_score", True)),
            deai_revise=bool(d.get("deai_revise", False)),
            harness_enabled=bool(d.get("harness_enabled", True)),
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
    """多编码兜底读文本.

    v4.1.8.2 (审计 E4): 旧实现按 utf-8 -> gbk -> gb2312 -> gb18030 依次试解码,
    但 UTF-16 文件的字节流大概率能被 GBK "成功"解码成乱码 (不抛异常), 乱码会被
    静默送 LLM 校对 (数据损坏型). 现改为: 先 BOM 嗅探 (utf-8-sig / utf-16),
    再 utf-8, 再 gb18030 (gbk/gb2312 的超集, 单独覆盖两者), 全失败才 replace 兜底;
    顺带修复带 BOM 文件的 \\ufeff 混入 prompt 的问题.
    """
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig")
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    for encoding in ("utf-8", "gb18030"):
        try:
            return raw.decode(encoding)
        except (UnicodeDecodeError, UnicodeError):
            continue
    return raw.decode("utf-8", errors="replace")


async def save_checkpoint_async(file_path: Path, task: FileTask) -> None:
    """save_checkpoint 的异步包装。"""
    await asyncio.to_thread(save_checkpoint, file_path, task)


def _atomic_write_text(path: Path, text: str) -> None:
    """原子写文本: 先写临时文件再 os.replace, 避免写中途崩溃留下半截 JSON.

    v4.1.8.2 (审计 E15): 配置/断点原来直接 write_text 截断+写, 崩溃/断电后
    last_config.json 损坏 -> load_config 返回默认配置, 用户 API key 静默丢失.
    """
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


# 配置/断点根目录.
# 支持环境变量 PROOFREADER_HOME 覆盖 (v4.1.8.1 审计修复 H10):
# 测试套件用它指向临时目录, 杜绝污染用户真实 ~/.proofreader.
def _default_config_dir() -> Path:
    override = os.environ.get("PROOFREADER_HOME")
    if override:
        return Path(override)
    return Path.home() / ".proofreader"


CONFIG_DIR = _default_config_dir()
CHECKPOINT_DIR = CONFIG_DIR / "checkpoints"
try:
    # v4.1.8.2 (审计 E10): 补 parents=True + 异常兜底 — PROOFREADER_HOME 指向
    # 多级不存在路径时, 旧版在 import 期抛 FileNotFoundError 让应用启动即崩.
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
except OSError as e:
    logger.error(f"数据目录创建失败 (配置/断点将不可用): {CONFIG_DIR} — {e}")
CONFIG_FILE = CONFIG_DIR / "last_config.json"


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


def save_config(config: ProjectConfig) -> bool:
    """落盘配置. 返回是否成功.

    v4.1.8.2 (审计 B4): 旧版内部吞异常恒返回 None, bridge 层的 except 永远
    不可达 -> 磁盘满/只读时前端仍显示"已保存", 重启后配置静默丢失.
    现返回 bool, 由 bridge 层透传给前端.
    """
    try:
        _atomic_write_text(
            CONFIG_FILE,
            json.dumps(config.to_dict(), ensure_ascii=False, indent=2),
        )
        return True
    except Exception as e:
        logger.error(f"保存配置失败: {e}")
        return False


def load_config() -> ProjectConfig:
    try:
        if CONFIG_FILE.exists():
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            return ProjectConfig.from_dict(data)
    except Exception as e:
        logger.error(f"加载配置失败: {e}")
    return ProjectConfig()


def _checkpoint_file(file_path: Path) -> Path:
    """文件路径 -> 断点文件路径.

    v4.1.8.2 (审计 E3): 旧映射 (: / \\ -> _) 会把 `a_b.txt` 与 `a\\b.txt` 映射到
    同一断点文件, 后处理的文件直接复用前者的校对结果 (交叉污染), 且断点校验
    不核对归属路径. 改用归一化绝对路径的 sha256 命名, 无碰撞; 旧命名断点一次性
    失效 (属预期, 配合 load_checkpoint 的归属校验双保险).
    """
    norm = os.path.normcase(os.path.abspath(str(file_path)))
    digest = hashlib.sha256(norm.encode("utf-8")).hexdigest()[:24]
    return CHECKPOINT_DIR / f"cp_{digest}.json"


def split_text(text: str, max_chars: int, preset: str = "balanced") -> list[str]:
    """按段落/句号边界切分文本, 每块不超过 max_chars 字符。

    v4.3.0: 从 processor._split_text 平移到 utils — 校对引擎与 DeAI 分块共用
    一个实现 (DeAI 长文本分块复用), processor 保留同名静态方法委托到这里,
    兼容既有测试与外部调用。

    优先级: \\n\\n (段落) > \\n (行) > 。！？ (句号) > 强制切分。
    切分点保留在段尾 (即不丢标点), 保证拼接时语义完整。
    overlap=0 (校对场景硬约束): 重叠区会被改两次, 结果冲突。

    preset 参数仅在 ``whole_file`` / ``max_chars == 0`` 时生效, 直接返回
    ``[text]`` (整文件不分块)。
    """
    # 整文件预设
    if preset == "whole_file" or max_chars == 0:
        return [text]

    if len(text) <= max_chars:
        return [text]
    chunks: list[str] = []
    remaining = text
    while len(remaining) > max_chars:
        # 尝试在 max_chars 范围内找最佳切分点
        window = remaining[:max_chars]
        cut = -1
        for sep in ("\n\n", "\n", "。", "！", "？", ".", "!", "?"):
            idx = window.rfind(sep)
            if idx > max_chars // 2:  # 至少切在前半段, 避免小块
                # v4.1.8.2 (审计 E8): ASCII 句点切分校验 — "3.14"/"U.S."/
                # "v2.5" 会被旧逻辑拦腰切开, 两块独立送模型后拼接语义损坏.
                # 句点后紧跟字母/数字, 或两侧均为字母数字时不在此切.
                if sep == ".":
                    pos = idx + 1
                    nxt = remaining[pos] if pos < len(remaining) else ""
                    prv = remaining[idx - 1] if idx > 0 else ""
                    if (nxt and (nxt.isdigit() or nxt.isalpha())) or (
                        prv.isalnum() and nxt.isalnum()
                    ):
                        continue
                cut = idx + len(sep)
                break
        if cut <= 0:
            cut = max_chars  # 实在没合适切分点, 硬切
        chunks.append(remaining[:cut])
        remaining = remaining[cut:]
    if remaining:
        chunks.append(remaining)
    return chunks


def save_checkpoint(file_path: Path, task: FileTask) -> None:
    try:
        cp_file = _checkpoint_file(file_path)
        _atomic_write_text(
            cp_file,
            json.dumps(task.to_dict(), ensure_ascii=False, indent=2),
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

    v4.1.8.2 (审计 E3): 增加归属校验 — 断点内 file_path 必须与请求路径一致
    (Windows 下不区分大小写), 防 checkpoint 文件串用. 同时兼容读旧命名断点
    (一次迁移期): 旧命名有碰撞风险, 但归属校验会把不属于当前文件的缓存拒掉.
    """
    candidates = [_checkpoint_file(file_path)]
    legacy = CHECKPOINT_DIR / (
        str(file_path).replace(":", "_").replace("/", "_").replace("\\", "_") + ".json"
    )
    if legacy not in candidates:
        candidates.append(legacy)
    for cp_file in candidates:
        try:
            if not cp_file.exists():
                continue
            data = json.loads(cp_file.read_text(encoding="utf-8"))
            task = FileTask.from_dict(data)
            # v4.1.8.2 (审计 E3): 归属校验
            if os.path.normcase(str(task.file_path)) != os.path.normcase(str(file_path)):
                logger.info(
                    f"[断点] 路径不匹配,忽略缓存: {task.file_path} != {file_path}"
                )
                continue
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
    return None
