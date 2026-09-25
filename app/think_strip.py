# 借鉴自 https://github.com/commonmark/commonmark-spec (CC-BY-SA 4.0, spec 文本)
# 借鉴内容: 围栏代码块语义 (行首最多 3 空格 / 字符与长度配对 / 闭围栏长度不小于开围栏)
# 借鉴方式: 规范语义引用,无代码复制
# Copyright (c) John MacFarlane, CommonMark contributors

"""think_strip — 模型输出思维链 (inline think block) 剥离引擎 (零 LLM 纯规则).

背景 (PLAN §0): 部分端点把思维链内联进 content (`<think>…</think>`), 会整段进入
corrected → 字符级 diff / 复制 / 导出 / 断点 / 本地评分 / DeAI 全链路污染.
本模块是唯一剥离单点: processor 整篇流式 + web_backend DeAI 三处共用同一语义.

语义 (PLAN §3, v2.1 两轮审计后口径):
1. 只剥白名单标签 (THINK_TAGS) 的成对块; 开标签必须位于**行首**且围栏外.
   行首 = 已剥离可见文本中, 该 `<` 之前同一行内只有空白 (已剥除区段视为不存在;
   头部级联块同口径递归).
2. 未闭合块 (围栏外) → 从开标签起整段丢弃; 头部块连块前空白一并丢.
   裸半截标签 (如 "<thi") 按字面保留 — 不静默删内容.
3. 围栏代码块 (```/~~~) 内一切原样保留 (围栏只"保护"从不"删除"); 围栏行判定
   走可见文本坐标, 行尾先 rstrip("\r") — CRLF 文本的围栏必须能闭合 (审计 V2).
   块内不感知围栏: 块配对只数同名标签 (深度计数).
4. 头部块剥除时, 连"块前空白 + 块后连续空行"一并清 (保留第一个非空行行首缩进).

流式契约 (ThinkFilter; PLAN §3.3, 测试逐条锁定):
- feed(delta) 只追加; take() 推进扫描并返回新增可显示文本; flush() 收尾, 幂等;
- 任意时刻累计 take 是最终结果的前缀延长 (永不回溯);
- "".join(take 序列) + flush() == strip_thinking(raw);
- 结果与切分方式无关 (全切点 property 测试).

实现: 单个可续扫 (resumable) 前向扫描器 —— 每次 take 只处理新增文本, 但对外
语义与"全量重算 + 安全前缀"完全等价 (property 测试锁定). 悬置点 (半截标签 /
未闭合块 / 头部未定 / 围栏行未定) 一律不产出, 等后续输入或 flush 再判定.
调用方负责空结果兜底: 剥后为空 → 走既有空输出失败/重试语义.
"""
import re

# 白名单标签 (小写); 大小写不敏感匹配
THINK_TAGS = ("think", "thinking", "reasoning", "thought")

# 闭围栏: 行首最多 3 空格 + run + 仅尾随空白 (与 md_strip 同口径; 判定前 rstrip("\r"))
_FENCE_CLOSE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})[ \t]*$")


def _advance_line_state(ws_only: bool, spaces: int, s: str) -> tuple[bool, int]:
    """推进"当前可见行"状态: ws_only = 该行可见前缀是否只有空白;
    spaces = 可见前缀连续空格数 (-1 表示前缀已含非空格字符, 已不是纯空格前缀)."""
    for c in s:
        if c == "\n":
            ws_only, spaces = True, 0
        elif not ws_only:
            continue
        elif c == " ":
            if spaces >= 0:
                spaces += 1
        elif c.isspace():
            spaces = -1
        else:
            ws_only, spaces = False, -1
    return ws_only, spaces


def _run_len(raw: str, i: int, ch: str) -> int:
    j = i
    n = len(raw)
    while j < n and raw[j] == ch:
        j += 1
    return j - i


def _read_open_tag(raw: str, i: int) -> tuple[str, object, object]:
    """尝试在 i 处读一个开标签 (`<name ...>`; 属性值内的 > / < / 引号跳过).

    返回:
      ("tag", end, name)          完整标签 (end = '>' 之后; name 小写)
      ("partial", could_be, None) 输入在半截标签处耗尽
                                  (could_be = 仍可能长成白名单开标签)
      ("none", None, None)        确定不是开标签
    """
    n = len(raw)
    j = i + 1
    if j >= n:
        return ("partial", True, None)  # 单个 "<": 可能是任何标签开头
    if not (raw[j].isascii() and raw[j].isalpha()):
        return ("none", None, None)
    st = j
    while j < n and raw[j].isascii() and (raw[j].isalnum() or raw[j] == "-"):
        j += 1
    name = raw[st:j].lower()
    if j >= n:
        # 名字尚未被任何字符终止 → 仍可能继续增长成白名单名
        return ("partial", any(t.startswith(name) for t in THINK_TAGS), None)
    c = raw[j]
    if c == "/":
        return ("none", None, None)  # <think/> 自闭合, 不构成块
    if c not in " \t\r\n>":
        return ("none", None, None)  # 名字后跟非法字符 → 不是标签
    quote = None
    while j < n:
        c = raw[j]
        if quote is not None:
            if c == quote:
                quote = None
        elif c in "\"'":
            quote = c
        elif c == ">":
            return ("tag", j + 1, name)
        elif c == "<":
            return ("none", None, None)
        j += 1
    # 属性区耗尽: 名字已定 → 是否可能长成白名单开标签
    return ("partial", name in THINK_TAGS, None)


def _read_close_tag(raw: str, i: int, name: str) -> tuple[str, object]:
    """i 处是否是完整的同名闭标签 `</name ... >` (大小写不敏感)."""
    n = len(raw)
    if not raw.startswith("</", i):
        return ("none", None)
    j = i + 2
    st = j
    while j < n and raw[j].isascii() and (raw[j].isalnum() or raw[j] == "-"):
        j += 1
    partial_name = raw[st:j].lower()
    if j >= n:
        # 名字未终止: 仍可能长成 name
        return ("partial", None) if name.startswith(partial_name) else ("none", None)
    if partial_name != name:
        return ("none", None)
    while j < n and raw[j] in " \t\r\n":
        j += 1
    if j >= n:
        return ("partial", None)  # 等 '>' 或更多空白
    if raw[j] == ">":
        return ("close", j + 1)
    return ("none", None)


def _next_block_tag(raw: str, pos: int, name: str) -> tuple[object, object, int]:
    """块内搜索下一个同名开/闭标签 (深度配对用; 只数同名, 不感知围栏).

    返回 (kind, end, resume):
      ("open"/"close", end, end)  命中, 下一次从 end 继续搜
      (None, None, resume)        未命中: resume = 下次继续搜索的起点
                                  (半截同名标签处原地重试, 否则推进到输入尾)
    """
    n = len(raw)
    k = pos
    while True:
        j = raw.find("<", k)
        if j < 0:
            return (None, None, n)
        if raw.startswith("</", j):
            kind, end = _read_close_tag(raw, j, name)
            if kind == "close":
                return ("close", end, end)
            if kind == "partial":
                return (None, None, j)
        else:
            kind, a, b = _read_open_tag(raw, j)
            if kind == "tag" and b == name:
                return ("open", a, a)
            if kind == "partial":
                return (None, None, j)   # 半截标签: 原地重试 (不跳过)
        k = j + 1


class _Scanner:
    """可续扫前向扫描器 (语义见模块 docstring; 设计见 PLAN §2 D4)."""

    __slots__ = (
        "raw", "parts", "i", "n", "fence", "ws_only", "spaces", "head",
        "post_nl", "block_name", "depth", "pending_head_block",
        "block_search", "new_parts",
    )

    def __init__(self):
        self.raw = ""
        self.parts: list[str] = []
        self.i = 0
        self.n = 0
        self.fence = None          # (char, len) | None
        self.ws_only = True        # 当前可见行是否只有空白 (已剥块视为不存在)
        self.spaces = 0            # 当前可见行前缀连续空格数 (-1 = 非纯空格前缀)
        self.head = "pending"      # pending(头部未定) | post(头部块后清空白) | done
        self.post_nl = 0           # head=post: 最后一个换行之后的位置
        self.block_name = None     # 块内标签名 (None = 不在块内)
        self.depth = 0
        self.pending_head_block = False
        self.block_search = 0      # 块内标签搜索起点
        self.new_parts: list[str] = []  # 已产出、尚未被 take/flush 取走

    # ---------- 对外 ----------

    def feed(self, delta: str) -> None:
        if delta:
            self.parts.append(delta)

    def drain(self) -> str:
        if not self.new_parts:
            return ""
        out = "".join(self.new_parts)
        self.new_parts.clear()
        return out

    # ---------- 内部 ----------

    def _emit(self, s: str) -> None:
        if not s:
            return
        self.new_parts.append(s)
        self.ws_only, self.spaces = _advance_line_state(self.ws_only, self.spaces, s)

    def _absorb(self) -> None:
        if self.parts:
            self.raw = self.raw + "".join(self.parts)
            self.parts.clear()
            self.n = len(self.raw)

    def _fence_close_verdict(self, i: int, eof: bool) -> str:
        """围栏内"可见行首 run"的闭围栏判定: close / content / hold."""
        ch, flen = self.fence
        r = _run_len(self.raw, i, ch)
        if i + r < self.n:
            nxt = self.raw[i + r]
            if r < flen:
                return "content"      # run 已被不同字符终止, 长度不够
            if nxt not in " \t\r\n":
                return "content"      # run 后已有非空白 → 确定不是闭围栏
            nl = self.raw.find("\n", i)
            if nl < 0:
                return "hold"         # 行未终止: 之后可能出现非空白
            line = self.raw[i:nl]
            return "close" if _FENCE_CLOSE_RE.match(line.rstrip("\r")) else "content"
        # run 抵达输入尾: 可能继续增长 / 可能以 EOF 收尾
        if r < flen:
            return "content" if eof else "hold"
        if not eof:
            return "hold"
        return "close" if _FENCE_CLOSE_RE.match(self.raw[i:].rstrip("\r")) else "content"

    def run(self, eof: bool) -> None:
        """推进扫描 (只处理新增文本); eof=True 按收尾语义解决全部悬置."""
        self._absorb()
        raw = self.raw
        while self.i < self.n:
            ch = raw[self.i]

            # (A) 块内: 同名标签深度配对 (整块丢弃)
            if self.block_name is not None:
                kind, end, resume = _next_block_tag(raw, self.block_search, self.block_name)
                if kind is None:
                    self.block_search = resume
                    if not eof:
                        self.i = resume
                        return
                    # eof: 围栏外未闭合块 → 交给收尾统一丢弃
                    self.i = self.n
                    break
                self.depth += 1 if kind == "open" else -1
                self.block_search = end
                if self.depth == 0:
                    self.block_name = None
                    if self.pending_head_block:
                        # 头部块剥除 → 转"清块后空白"阶段
                        self.head = "post"
                        self.post_nl = end
                        self.pending_head_block = False
                        self.ws_only, self.spaces = True, 0
                    self.i = end
                continue

            # (B) 头部空白吞咽 (pending: 块前空白; post: 块后连续空白)
            if self.head in ("pending", "post") and ch.isspace():
                if self.head == "post" and ch == "\n":
                    self.post_nl = self.i + 1
                self.i += 1
                continue

            # (C) 块开标签判定 (仅: 围栏外 + 可见行首 + '<')
            if ch == "<" and self.ws_only and self.fence is None:
                kind, a, b = _read_open_tag(raw, self.i)
                if kind == "tag" and b in THINK_TAGS:
                    self.block_name = b
                    self.depth = 1
                    self.pending_head_block = self.head in ("pending", "post")
                    self.block_search = a
                    self.i = a
                    continue
                if kind == "partial" and a and not eof:
                    return                       # H3: 行首半截标签 → 悬置 (i 不动)
                # none / 非白名单 / eof 半截 → 落定头部后按普通字符处理

            # (D) 头部落定 (非块): pending 保留前导空白; post 只保留末行缩进
            if self.head == "pending":
                self._emit(raw[0:self.i])
                self.head = "done"
            elif self.head == "post":
                self._emit(raw[self.post_nl:self.i])
                self.head = "done"

            # (E) 普通字符: 换行 / 围栏 / 其他
            if ch == "\n":
                self._emit(ch)
                self.i += 1
                continue
            if self.fence is not None:
                if self.ws_only and 0 <= self.spaces <= 3 and ch in "`~":
                    verdict = self._fence_close_verdict(self.i, eof)
                    if verdict == "hold":
                        return
                    if verdict == "close":
                        self.fence = None
                        self._emit(ch)
                        self.i += 1
                        continue
                self._emit(ch)
                self.i += 1
                continue
            if self.ws_only and 0 <= self.spaces <= 3 and ch in "`~":
                r = _run_len(raw, self.i, ch)
                if r >= 3:
                    self.fence = (ch, r)
                    self._emit(ch)
                    self.i += 1
                    continue
                if self.i + r >= self.n and not eof:
                    return                       # run 可能继续增长成长围栏 → 暂缓
            self._emit(ch)
            self.i += 1

        # 循环结束 / 未进入循环 (i == n)
        if not eof:
            return
        if self.block_name is not None:
            # 围栏外未闭合块 → 从开标签起整段丢弃
            self.block_name = None
            self.i = self.n
            if self.head in ("pending", "post"):
                self.head = "done"   # 头部块前的空白 / 缩进一并丢
            return
        if self.head == "pending":
            # 全文仅空白且无块 → 原样产出 (逐字节不变)
            self._emit(raw[0:self.i])
            self.head = "done"
        elif self.head == "post":
            # EOF: 头部块后的剩余空白不存在"第一个非空行" → 全丢
            self.head = "done"


class ThinkFilter:
    """流式增量过滤器 (PLAN §2 D4 / §3.3).

    feed(delta) 只追加; take() 推进扫描并返回"新增可显示文本";
    flush() 按收尾语义 (eof) 结算剩余, 幂等.
    """

    __slots__ = ("_sc", "_done")

    def __init__(self):
        self._sc = _Scanner()
        self._done = False

    def feed(self, delta: str) -> None:
        if not self._done:
            self._sc.feed(delta)

    def take(self) -> str:
        if self._done:
            return ""
        self._sc.run(False)
        return self._sc.drain()

    def flush(self) -> str:
        if self._done:
            return ""
        self._sc.run(True)
        self._done = True
        return self._sc.drain()


def strip_thinking(text: str) -> str:
    """一次性剥离 (非流式路径 / flush 基准 / 测试基准)."""
    if not text:
        return text
    sc = _Scanner()
    sc.feed(text)
    sc.run(True)
    return sc.drain()


def has_think_residue(result) -> bool:
    """D9: 旧断点残留检测 (单点口径 — 直接复用 strip_thinking, 不另写"行首"实现).

    判定 = corrected 会被剥离改写, 且原文本身不会被改写 (原文自带行首块的语料不触发,
    否则 harness 轨 corrected=原文 会永久打不中缓存 — 复审 v2.1 收敛).
    """
    corrected = getattr(result, "corrected_full", None)
    if corrected is None:
        corrected = getattr(result, "corrected", "") or ""
    if not corrected:
        return False
    if strip_thinking(corrected) == corrected:
        return False
    original = getattr(result, "original", "") or ""
    if original and strip_thinking(original) != original:
        return False
    return True
