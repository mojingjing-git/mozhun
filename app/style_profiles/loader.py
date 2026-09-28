"""v4.1.7 风格 Profile 加载器 (CRUD + 蒸馏入口).

借鉴自 https://github.com/jianshuo/claude-skills (MIT License)
借鉴内容: Style Card 存储路径 `~/code/style-cards/<author-slug>/` + 9 轴指纹 +
         蒸馏流程 (样本入库 → 9 轴拆解 → 锚点原句 → 写出 style-card.md)
借鉴方式: 思路借鉴, 无代码复制, 存储路径改 `~/.proofreader/styles/<slug>/`
         (项目统一走 ~/.proofreader, 不引入新 home 子目录)
Copyright (c) 2026 Jianshuo Wang
"""
from __future__ import annotations

import json
import os
import re
import shutil
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.logger import setup_logging

logger = setup_logging()


# === 借鉴自 jianshuo/claude-skills 的 style-card 目录结构 (思路借鉴) ===
# 原项目: ~/code/style-cards/<author-slug>/{samples, style-card.md, rewrites}
# 本项目: ~/.proofreader/styles/<slug>/{samples, style-card.md, meta.json}
# 改点: 路径跟项目现有 CONFIG_DIR/CHECKPOINT_DIR 一致 (app/utils.py:291-295)
# v4.1.8.1 (审计修复 H10): 支持 PROOFREADER_HOME 环境变量覆盖 (测试隔离用),
# 与 app/utils.py 的 CONFIG_DIR 指向同一根目录.
def _styles_dir() -> Path:
    override = os.environ.get("PROOFREADER_HOME")
    if override:
        return Path(override) / "styles"
    return Path.home() / ".proofreader" / "styles"


STYLES_DIR = _styles_dir()


# === 借鉴自 jianshuo/claude-skills 的 '9 轴 schema' 思路 (字段名全自定) ===
# 9 轴: 句子节奏 / 段落长度 / 词汇 / 语气腔调 / 论证结构 / 比喻运用 / 情绪强度 / 开头与收尾 / 雷区
# 每轴 3 件事: 观察 (observe) / 可执行规则 (rule) / 锚点原句 (anchor_examples)
AXIS_KEYS = [
    "1_sentence_rhythm", "2_paragraph_length", "3_vocabulary", "4_tone_register",
    "5_argument_structure", "6_metaphor_use", "7_emotion_intensity",
    "8_opening_closing", "9_avoid",
]


# 借鉴自 jianshuo/claude-skills 的 'AI 6 处易露馅' (思路借鉴, 项目语言重写)
# 原 6 处: 缺真实专名 / 结尾太圆 / 推进太顺 / 鸡汤教科书化 / 批次指纹 / 文章原型不匹配
AI_TELLS = [
    "缺真实专名 (用真实 API/库名/版本号替代占位符)",
    "结尾太圆 ('希望对您有帮助' / '总之' / '综上所述' 一律删)",
    "推进太顺 (允许 '但有个例外' / '坑:' 转折, 不允许一气呵成)",
    "鸡汤教科书化 ('站在更高的视角看' / '底层逻辑是' 一律删)",
    "批次指纹 (一段不同时塞 3+ 个短句/破折号/反问/口头禅)",
    "文章原型不匹配 (论点型不冒充叙事型, 叙事型不冒充段子型)",
]


# 借鉴自 jianshuo/claude-skills 的 '建议 3-6 篇样本' (思路借鉴)
MIN_SAMPLES_FOR_DISTILL = 3
MAX_SAMPLE_BYTES = 200_000  # 单样本 200K 字节上限 (防单篇喂爆 prompt)


# 借鉴自 jianshuo/claude-skills 的 slug 校验 (思路借鉴)
# 拒绝: 空 / 路径分隔符 / .. / 隐藏文件 (.) / 特殊字符
_SAFE_SLUG = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_\-]{0,63}$")
# v4.1.8.2 (审计 L3): Windows 保留设备名 — 旧正则放行 CON/NUL/AUX 等,
# mkdir 时抛 WinError 被上层兜成生硬系统报错
_WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def _validate_slug(slug: str) -> None:
    """slug 必须是 [a-zA-Z0-9][a-zA-Z0-9_-]{0,63}, 拒绝 ../ 或空.

    v4.1.8.2 (审计 L3): re.match + $ 会放行尾随换行 ("abc\\n"), 改 fullmatch;
    拒绝 Windows 保留设备名.
    """
    if not isinstance(slug, str) or not slug:
        raise ValueError("slug 不能为空")
    if not _SAFE_SLUG.fullmatch(slug):
        raise ValueError(
            f"slug 非法: {slug!r}. "
            f"必须匹配 {chr(94)}[a-zA-Z0-9][a-zA-Z0-9_-]{{0,63}}$ (字母/数字/下划线/连字符, 首位字母数字, 1-64 字符)"
        )
    if slug.upper() in _WINDOWS_RESERVED:
        raise ValueError(f"slug 不能使用 Windows 保留设备名: {slug!r}")


def _profile_dir(slug: str) -> Path:
    """取得 profile 根目录 (不创建)."""
    _validate_slug(slug)
    return STYLES_DIR / slug


def _meta_path(slug: str) -> Path:
    return _profile_dir(slug) / "meta.json"


def _style_card_path(slug: str) -> Path:
    return _profile_dir(slug) / "style-card.md"


def _samples_dir(slug: str) -> Path:
    return _profile_dir(slug) / "samples"


def _now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def _atomic_write_text(path: Path, text: str) -> None:
    """原子写文本 (写临时文件 + os.replace).

    v4.1.8.2 (审计 L4): meta.json 旧版 write_text 截断+写, 蒸馏线程落盘瞬间
    前端刷新列表会读到半截 JSON, profile 从下拉框闪失. Windows 下 os.replace
    目标被占用会 PermissionError, 加短重试.
    """
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    for i in range(3):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if i == 2:
                raise
            time.sleep(0.05)


class StyleProfileLoader:
    """风格 Profile 加载器: builtin CRUD + custom CRUD + 蒸馏入口.

    线程安全: 公开方法都用 self._lock 保护, 蒸馏后台线程跟主线程不冲突.

    使用范式:
        loader = StyleProfileLoader()
        profiles = loader.list_builtin() + loader.list_custom()
        loader.add_sample(slug, content, "essay-1.md")
        card = loader.save_style_card(slug, markdown_text)  # 蒸馏结果
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # 蒸馏任务表 (start_distill 组件级入口用; Bridge 走 _deai_tasks)
        self._distill_tasks: dict[str, dict] = {}
        try:
            # v4.1.8.2 (审计 M1): 目录创建失败不再裸崩 — 旧版异常直接逃出
            # Backend() 构造链, 窗口模式下游走不到任何兜底提示
            STYLES_DIR.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.error(f"风格库目录创建失败 (风格 profile 功能不可用): {STYLES_DIR} — {e}")

    # ==================== Builtin profiles ====================

    def list_builtin(self) -> list[dict]:
        """返回 3 个预置 profile 列表 [{key, name, summary}, ...]."""
        result = []
        builtin_dir = Path(__file__).parent / "builtin"
        for f in sorted(builtin_dir.glob("*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                result.append({
                    "key": data.get("key", f.stem),
                    "name": data.get("name", f.stem),
                    "summary": data.get("summary", ""),
                    "abstract": data.get("abstract", True),
                })
            except Exception as e:
                logger.error(f"读 builtin profile 失败 {f.name}: {e}")
        return result

    def get_builtin(self, key: str) -> dict:
        """读单个预置 profile 全文 (key, name, axes 9 维, ai_tells_counter)."""
        builtin_path = Path(__file__).parent / "builtin" / f"{key}.json"
        if not builtin_path.exists():
            raise FileNotFoundError(f"builtin profile 不存在: {key}")
        return json.loads(builtin_path.read_text(encoding="utf-8"))

    # ==================== Custom profiles ====================

    def list_custom(self) -> list[dict]:
        """扫 ~/.proofreader/styles/<slug>/meta.json, 返回 [{key, name, samples_count, distilled_at}, ...]."""
        result = []
        if not STYLES_DIR.exists():
            return result
        for d in sorted(STYLES_DIR.iterdir()):
            if not d.is_dir():
                continue
            meta_file = d / "meta.json"
            if not meta_file.exists():
                continue
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
                result.append({
                    "key": d.name,
                    "name": meta.get("name", d.name),
                    "samples_count": meta.get("samples_count", 0),
                    "distilled_at": meta.get("distilled_at", ""),
                    "created_at": meta.get("created_at", ""),
                    "abstract": False,
                })
            except Exception as e:
                logger.error(f"读 custom profile 失败 {d.name}: {e}")
        return result

    def get_custom(self, slug: str) -> dict:
        """读 custom profile 全文 (含 meta + 9 轴)."""
        _validate_slug(slug)
        meta = self._read_meta(slug)
        # 9 轴存在 style-card.md, 没有蒸馏过的 profile axes 为空
        card_text = self.get_style_card(slug)
        # 解析 style-card.md 提取 9 轴 (粗解析, 不强求)
        axes = self._parse_style_card_axes(card_text) if card_text else {}
        return {
            "key": slug,
            "name": meta.get("name", slug),
            "summary": meta.get("summary", ""),
            "samples_count": meta.get("samples_count", 0),
            "distilled_at": meta.get("distilled_at", ""),
            "created_at": meta.get("created_at", ""),
            "axes": axes,
            "ai_tells_counter": AI_TELLS,
        }

    def create_custom(self, slug: str, name: str, summary: str = "") -> dict:
        """建 custom profile 目录 + meta.json. 存在则抛 FileExistsError."""
        _validate_slug(slug)
        with self._lock:
            pdir = _profile_dir(slug)
            if pdir.exists():
                raise FileExistsError(f"profile 已存在: {slug}")
            pdir.mkdir(parents=True, exist_ok=False)
            _samples_dir(slug).mkdir(parents=True, exist_ok=False)
            meta = {
                "key": slug,
                "name": name or slug,
                "summary": summary or "",
                "samples_count": 0,
                "created_at": _now_iso(),
                "distilled_at": "",
            }
            _atomic_write_text(
                _meta_path(slug),
                json.dumps(meta, ensure_ascii=False, indent=2),
            )
            return meta

    def delete_custom(self, slug: str) -> dict:
        """删 custom profile 整目录. builtin 不能删."""
        _validate_slug(slug)
        # 防止误删 builtin: key 出现在 builtin 列表里就拒
        for b in self.list_builtin():
            if b["key"] == slug:
                raise PermissionError(f"builtin profile 不能删除: {slug}")
        with self._lock:
            pdir = _profile_dir(slug)
            if not pdir.exists():
                raise FileNotFoundError(f"profile 不存在: {slug}")
            shutil.rmtree(pdir)
            return {"ok": True, "deleted": slug}

    def add_sample(self, slug: str, content: str, filename: str = "") -> dict:
        """加一篇样本到 samples/ + 更新 meta.samples_count.

        filename 留空自动 sample-<N>.md.
        """
        _validate_slug(slug)
        if not content or not content.strip():
            raise ValueError("样本内容不能为空")
        if len(content.encode("utf-8")) > MAX_SAMPLE_BYTES:
            raise ValueError(
                f"样本超过 {MAX_SAMPLE_BYTES // 1000}K 字节上限 "
                f"(实际 {len(content.encode('utf-8')) // 1000}K), 请拆成多段"
            )
        with self._lock:
            meta = self._read_meta(slug)  # 触发 FileNotFoundError
            sdir = _samples_dir(slug)
            sdir.mkdir(parents=True, exist_ok=True)
            # 决定 filename
            if not filename:
                filename = f"sample-{meta['samples_count'] + 1:03d}.md"
            # 防 path traversal in filename (二次校验, slug 已校验)
            safe_name = re.sub(r"[^\w.\-]", "_", filename)[:120]
            if not safe_name:
                safe_name = f"sample-{meta['samples_count'] + 1:03d}.md"
            target = sdir / safe_name
            # v4.1.8.2 (审计 L1): 拒绝同名覆盖 — 旧版静默覆盖旧样本但计数照常
            # 自增, 范文永久丢失且样本数虚增, 蒸馏时报"样本不足"无从排查
            if target.exists():
                raise ValueError(
                    f"样本文件名已存在: {safe_name}, 请换一个文件名或先删除旧样本"
                )
            target.write_text(content, encoding="utf-8")
            meta["samples_count"] = meta.get("samples_count", 0) + 1
            meta["last_sample_at"] = _now_iso()
            _atomic_write_text(
                _meta_path(slug),
                json.dumps(meta, ensure_ascii=False, indent=2),
            )
            return {
                "ok": True,
                "slug": slug,
                "filename": safe_name,
                "samples_count": meta["samples_count"],
            }

    def save_style_card(self, slug: str, markdown_content: str) -> dict:
        """把蒸馏生成的 style-card.md 落盘, 触发 meta.distilled_at 更新.

        markdown_content 期望含 '## 1_sentence_rhythm' 等 9 段 (粗解析用).
        """
        _validate_slug(slug)
        if not markdown_content or not markdown_content.strip():
            raise ValueError("style-card 内容不能为空")
        with self._lock:
            meta = self._read_meta(slug)
            _style_card_path(slug).write_text(markdown_content, encoding="utf-8")
            meta["distilled_at"] = _now_iso()
            _atomic_write_text(
                _meta_path(slug),
                json.dumps(meta, ensure_ascii=False, indent=2),
            )
            return {
                "ok": True,
                "slug": slug,
                "card_chars": len(markdown_content),
                "distilled_at": meta["distilled_at"],
            }

    def get_style_card(self, slug: str) -> str:
        """读 style-card.md; 不存在时对 builtin key 回退渲染内置 JSON, 否则空串.

        v4.1.8.1 (审计修复 H9/E1): builtin slug 无落盘 style-card.md (builtin
        只存 axes JSON), 原恒返 "" -> 去 AI 味 step2/3 选中预置 profile 拿不到
        9 轴卡静默 no-op (界面显示"已选", 实际空转). 现对 builtin key 回退把
        内置 JSON 渲染成与蒸馏产物同构的 markdown (兼容 _parse_style_card_axes).
        """
        _validate_slug(slug)
        p = _style_card_path(slug)
        if p.exists():
            return p.read_text(encoding="utf-8")
        # custom 未蒸馏 + slug 命中 builtin key (或 custom 与 builtin 同名但无卡) 时回退
        try:
            return self._render_builtin_card(slug)
        except FileNotFoundError:
            return ""
        except Exception as e:
            logger.error(f"渲染 builtin style card {slug} 失败: {e}")
            return ""

    def _render_builtin_card(self, key: str) -> str:
        """把 builtin JSON 渲染成与蒸馏 style-card.md 同构的 9 轴 markdown.

        v4.1.8.1 (审计修复 H9/E1): builtin 预置 profile 只存 axes JSON, 从未被
        渲染成可注入 markdown. 渲染结构兼容 _parse_style_card_axes (每个 9 轴是
        '## N_axis' 段), 使内置卡与 custom 蒸馏卡同构, step2/3 可同路径注入.
        key 非 builtin 时抛 FileNotFoundError (由 get_style_card 转空串).
        """
        data = self.get_builtin(key)  # FileNotFoundError 上抛
        lines = [
            f"# {data.get('name', key)}",
            "",
            data.get("summary", ""),
            "",
            "> 预置抽象化 profile (abstract=True), 由 builtin JSON 渲染, 非真人作家蒸馏.",
            "",
        ]
        axes = data.get("axes", {}) or {}
        for axis_key in AXIS_KEYS:
            axis = axes.get(axis_key) or {}
            lines.append(f"## {axis_key}")
            if axis.get("observe"):
                lines.append(f"- 观察 (observe): {axis['observe']}")
            if axis.get("rule"):
                lines.append(f"- 可执行规则 (rule): {axis['rule']}")
            anchors = axis.get("anchor_examples") or []
            if anchors:
                lines.append("- 锚点原句:")
                for a in anchors:
                    lines.append(f"  - {a}")
            lines.append("")
        tells = data.get("ai_tells_counter") or []
        if tells:
            lines.append("## ai_tells_counter")
            for t in tells:
                lines.append(f"- {t}")
            lines.append("")
        return "\n".join(lines).strip()

    # ==================== 蒸馏入口 ====================

    def start_distill(self, slug: str, llm_callback) -> str:
        """启动蒸馏 (组件级同步入口, 供测试/库调用; Bridge 走 _deai_distill_run):
        读 samples/, 调 llm_callback(samples_concat, slug) 拿 markdown,
        落盘 style-card.md. 立即返 task_id.

        llm_callback(samples_concat: str, slug: str) -> str:
        由调用方实现 (同步返回 markdown, 线程由调用方控制).
        """
        _validate_slug(slug)
        task_id = f"distill_{uuid.uuid4().hex[:8]}"
        with self._lock:
            meta = self._read_meta(slug)
            samples_count = meta.get("samples_count", 0)
            if samples_count < MIN_SAMPLES_FOR_DISTILL:
                raise ValueError(
                    f"样本不足: 当前 {samples_count} 篇, "
                    f"蒸馏至少需要 {MIN_SAMPLES_FOR_DISTILL} 篇"
                )
            # 拼所有样本
            samples = []
            for f in sorted(_samples_dir(slug).glob("*.md")):
                txt = f.read_text(encoding="utf-8", errors="replace")
                samples.append(f"# {f.name}\n\n{txt}")
            samples_concat = "\n\n---\n\n".join(samples)
            self._distill_tasks[task_id] = {
                "slug": slug,
                "started": time.time(),
                "status": "running",
            }
        # 同步跑 (调用方控制线程), 这里不另起线程
        try:
            markdown = llm_callback(samples_concat, slug)
            if not markdown or not markdown.strip():
                raise RuntimeError("LLM 返回空 markdown, 蒸馏失败")
            self.save_style_card(slug, markdown)
            with self._lock:
                self._distill_tasks[task_id]["status"] = "done"
                self._distill_tasks[task_id]["card_chars"] = len(markdown)
            return task_id
        except Exception as e:
            with self._lock:
                self._distill_tasks[task_id]["status"] = "error"
                self._distill_tasks[task_id]["error"] = str(e)
            raise

    def get_distill_status(self, task_id: str) -> dict:
        with self._lock:
            return dict(self._distill_tasks.get(task_id, {}))

    # ==================== 内部 ====================

    def _read_meta(self, slug: str) -> dict:
        """读 meta.json, 不存在返空 dict (供 list_custom 等)."""
        mp = _meta_path(slug)
        if not mp.exists():
            raise FileNotFoundError(f"profile 不存在: {slug}")
        return json.loads(mp.read_text(encoding="utf-8"))

    def _parse_style_card_axes(self, card_text: str) -> dict:
        """从 style-card.md 粗解析 9 轴 (按 '## N_xxx' 切段)."""
        if not card_text:
            return {}
        axes = {}
        current_axis = None
        current_body: list[str] = []
        for line in card_text.splitlines():
            m = re.match(r"^##\s+(\d+_\w+)\s*(.*)$", line)
            if m:
                if current_axis:
                    axes[current_axis] = "\n".join(current_body).strip()
                current_axis = m.group(1)
                current_body = [m.group(2)] if m.group(2) else []
            else:
                if current_axis:
                    current_body.append(line)
        if current_axis:
            axes[current_axis] = "\n".join(current_body).strip()
        return axes
