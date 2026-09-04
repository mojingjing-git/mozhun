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
STYLES_DIR = Path.home() / ".proofreader" / "styles"


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


# 借鉴自 jianshuo/claude-skills 的 '8 轴自评' (思路借鉴, 项目语言重写)
# 在改写后做 1-5 评分, 替代'独立判官盲测' (本项目单模型场景, 内联自评)
SELF_AUDIT_AXES = [
    "1_句子节奏相似度", "2_段落分布相似度", "3_词汇偏好相似度", "4_语气腔调相似度",
    "5_论证路径相似度", "6_比喻风格相似度", "7_情绪温度相似度", "8_开头与收尾相似度",
]


# 借鉴自 jianshuo/claude-skills 的 '建议 3-6 篇样本' (思路借鉴)
MIN_SAMPLES_FOR_DISTILL = 3
MAX_SAMPLE_BYTES = 200_000  # 单样本 200K 字节上限 (防单篇喂爆 prompt)


# 借鉴自 jianshuo/claude-skills 的 slug 校验 (思路借鉴)
# 拒绝: 空 / 路径分隔符 / .. / 隐藏文件 (.) / 特殊字符
_SAFE_SLUG = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_\-]{0,63}$")


def _validate_slug(slug: str) -> None:
    """slug 必须是 [a-zA-Z0-9][a-zA-Z0-9_-]{0,63}, 拒绝 ../ 或空."""
    if not isinstance(slug, str) or not slug:
        raise ValueError("slug 不能为空")
    if not _SAFE_SLUG.match(slug):
        raise ValueError(
            f"slug 非法: {slug!r}. "
            f"必须匹配 {chr(94)}[a-zA-Z0-9][a-zA-Z0-9_-]{{0,63}}$ (字母/数字/下划线/连字符, 首位字母数字, 1-64 字符)"
        )


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
        # 蒸馏任务: task_id -> {slug, started, status}
        self._distill_tasks: dict[str, dict] = {}
        STYLES_DIR.mkdir(parents=True, exist_ok=True)

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
            _meta_path(slug).write_text(
                json.dumps(meta, ensure_ascii=False, indent=2),
                encoding="utf-8",
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
            target.write_text(content, encoding="utf-8")
            meta["samples_count"] = meta.get("samples_count", 0) + 1
            meta["last_sample_at"] = _now_iso()
            _meta_path(slug).write_text(
                json.dumps(meta, ensure_ascii=False, indent=2),
                encoding="utf-8",
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
            _meta_path(slug).write_text(
                json.dumps(meta, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return {
                "ok": True,
                "slug": slug,
                "card_chars": len(markdown_content),
                "distilled_at": meta["distilled_at"],
            }

    def get_style_card(self, slug: str) -> str:
        """读 style-card.md, 不存在返空串."""
        _validate_slug(slug)
        p = _style_card_path(slug)
        if not p.exists():
            return ""
        return p.read_text(encoding="utf-8")

    # ==================== 蒸馏入口 ====================

    def start_distill(self, slug: str, llm_callback) -> str:
        """启动后台蒸馏: 读 samples/, 调 llm_callback(samples_concat) 拿 markdown,
        落盘 style-card.md. 立即返 task_id.

        llm_callback(prompt: str) -> str: 由调用方实现 (web_backend 调 AsyncOpenAI 流式).
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
