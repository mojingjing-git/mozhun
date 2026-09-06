"""跨段上下文构造器。

借鉴自 https://github.com/shreyan241/gpt-proofreader (MIT License)
借鉴内容: 跨段上下文 prefix 思路
借鉴方式: 思路借鉴,无代码复制
Copyright (c) 2024 shreyan241
"""
from app.utils import FileResult


class ContextBuilder:
    """跨段上下文构造器。"""

    def __init__(self, max_chars: int = 800, max_chunks: int = 2):
        self.max_chars = max_chars
        self.max_chunks = max_chunks

    def build(
        self,
        chunks_processed: list[FileResult],
        current_chunk_index: int,
    ) -> str:
        """构造当前 chunk 的前文 prefix。

        规则:
        - 第一段 (index=0) 或无已完成 chunk → 返回 ""
        - 收集前 max_chunks 个 chunk 的 corrected
        - 总字符数不超过 max_chars
        - 超过时截断尾部(保留最近内容)
        """
        if current_chunk_index == 0 or not chunks_processed:
            return ""

        start = max(0, current_chunk_index - self.max_chunks)
        prev = chunks_processed[start:current_chunk_index]

        # v4.1.8.2 (审计 E14): 从最新块往旧块收集 — 旧实现按旧→新遍历, 巨大的
        # 旧块先吃满预算, 紧邻当前块的最近内容反而被整体丢弃, 与"保留最近内容"
        # 的意图相反. 新实现保证最新块完整, 预算耗尽时丢弃更旧的块 (被截断的
        # 旧块保留尾部 = 距当前块最近的部分).
        selected: list[str] = []
        used = 0
        for r in reversed(prev):
            text = r.corrected
            if not text:
                continue
            if used + len(text) > self.max_chars:
                remaining = self.max_chars - used
                if remaining < 50:
                    break
                text = "…" + text[-(remaining - 1):]
            selected.append(text)
            used += len(text)
        parts = list(reversed(selected))

        if not parts:
            return ""

        return (
            "上文(已校对,仅供风格/术语参考,请勿重复输出):\n"
            + "\n---\n".join(parts)
        )
