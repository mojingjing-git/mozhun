# v4.1.5 主页 UI 重构 + D 方案 incremental Diff (Plan v2)

> 基于 v4.1.4 完成后实施, 综合 verifier 反馈的 5 致命 + 5 重要
> 状态: 待 v4.1.4 (流式 33ms + 导出 YYMMDD) 完成后派 worker 实施

---

## 1. 设计目标

1. **进度作为子页面放在文件栏底部** (不再占中央独立栏)
2. **对比改成两栏**: 原文字 (左) + 修改文字 (右), 同时显示
3. **修改文字流式直出** (实时打字机效果, 30 FPS)
4. **实时展示 diff** (新增字符高亮, 用 D 方案 incremental 增量算法)

## 2. Verifier 反馈整合

### 5 个 🔴 致命 → 全部修

| # | 致命问题 | 修复方案 |
|---|---------|----------|
| 1 | 左栏原文字数据源缺失 (`t.original` 只在 onTaskComplete 后赋值) | **C 方案**: 修改后端 `on_file_start` 回调, 带 `original` 字段; 前端 `markFileRunning` 同步设 `t.original` |
| 2 | D 算法 `partial.length < state.lastPartialLen` 倒退保护缺失 | 加 `if (partial.length < state.lastPartialLen) { state.lastPartialLen=0; state.renderedHTML=''; state.renderedOriginalLen=0; }` 保护 |
| 3 | HTML ID 兼容未列 (旧 JS 静默失效) | **强制列被删 ID 清单** + **新 ID 清单** + 旧 JS 调用同步更新 |
| 4 | `.home-grid` CSS 未声明 (fallback 到 3 栏) | CSS 显式 `.content-grid.home-grid { grid-template-columns: 1fr 1.5fr; }` |
| 5 | renderState 内存泄漏 (清理时机未定义) | **renderState 生命周期**: 何时初始化 (startProofread) / 何时清理 (removeFile + clearFiles) / retry 是否 reset (见 D 算法增强) |

### 5 个 🟠 重要 → 全部修

| # | 重要问题 | 修复方案 |
|---|---------|----------|
| 6 | 流式 → 全量 diff 切换 UX 未定 | **B 方案**: 流式用 D 算法 (打字机 + ins 高亮), 完成后加 "查看完整 diff" 按钮, 主动点才切到 `diff_main` 全量 (带 `<del>`) |
| 7 | 前端 setInterval 50ms 是天花板 | 改 `setInterval(..., 16)` (60 FPS), 用 RAF 拉 eventQueue |
| 8 | 复制按钮流式时 enabled | `const hasResult = t && t.corrected && !this.isProcessing` (流式完成才 enabled) |
| 9 | 错误态右栏无 fallback | `renderCompare` 加 `if (t.error) { rightPane.innerHTML = '<div class="error-mark">校对失败: ' + escapeHtml(t.error) + '</div>'; return; }` |
| 10 | 跨 chunk 边界 partial 跳跃 | D 算法跨 chunk 不特殊处理, **接受** 边界处新字符全标 `<ins>` (合理视觉: 段间新内容); lastPartialLen 自动重置 (新字符大于上次 partial 长度时照常推进) |

---

## 3. D 方案 incremental 增强版 (核心算法)

### 3.1 状态机

```js
// 每个 fileKey 一份
// 🟡 33: mode 显式默认 'streaming', 避免 || 兜底混乱
const renderState = {
  [fileKey]: {
    lastPartialLen: 0,         // 上次 render 时的 partial 长度
    renderedHTML: '',          // 累积 render 出来的 HTML
    renderedOriginalLen: 0,    // 已渲染的 original 字符数
    rafScheduled: false,       // 防止同帧多次 schedule
    mode: 'streaming',         // 'streaming' (D 算法) / 'full' (diff_main 全量) — 按钮切换
  }
}

// 初始化 helper (显式)
function initRenderState(fileKey) {
  if (!this.renderState[fileKey]) {
    this.renderState[fileKey] = {
      lastPartialLen: 0, renderedHTML: '', renderedOriginalLen: 0,
      rafScheduled: false, mode: 'streaming',
    };
  }
  return this.renderState[fileKey];
}
```

### 3.2 核心算法 (带全部保护)

```js
function commonPrefixLength(a, b) {
  let i = 0;
  const min = Math.min(a.length, b.length);
  while (i < min && a[i] === b[i]) i++;
  return i;
}

function renderCompare(fileKey) {
  const t = this.tasks.find(t => t.path === fileKey);
  if (!t) return;
  const original = t.original || '';        // 🔴 修复 1: t.original 在 onFileStart 时已设
  const partial  = this.streamingContent[fileKey] || '';
  const state    = this.renderState[fileKey] || (this.renderState[fileKey] = {
    lastPartialLen: 0, renderedHTML: '', renderedOriginalLen: 0, rafScheduled: false, mode: 'streaming',
  });

  // 🔴 修复 9: 错误态 fallback
  if (t.error) {
    rightPane.innerHTML = `<div class="error-mark">校对失败: ${escapeHtml(t.error)}</div>`;
    return;
  }

  // 🟠 修复 6: 完成后切到全量 diff_main
  if (state.mode === 'full') {
    if (!this.dmp) { rightPane.textContent = partial; return; }
    const diff = this.dmp.diff_main(original, partial);
    this.dmp.diff_cleanupSemantic(diff);
    rightPane.innerHTML = diff.map(([op, text]) => {
      const safe = escapeHtml(text);
      if (op === 1)  return `<ins>${safe}</ins>`;
      if (op === -1) return `<del>${safe}</del>`;
      return `<span>${safe}</span>`;
    }).join('');
    return;
  }

  // 空状态
  if (!partial) {
    rightPane.textContent = '';
    state.lastPartialLen = 0;
    return;
  }

  // 🔴 修复 2: partial 倒退保护 (retry / cancel / resume)
  if (partial.length < state.lastPartialLen) {
    state.lastPartialLen = 0;
    state.renderedHTML = '';
    state.renderedOriginalLen = 0;
  }

  if (partial.length === state.lastPartialLen) return;  // 无新内容

  // 增量算法
  const newChars = partial.slice(state.lastPartialLen);
  const prevRenderedOriginal = state.renderedOriginalLen;
  const newOriginalSlice = original.slice(prevRenderedOriginal, prevRenderedOriginal + newChars.length);

  const matches = commonPrefixLength(newOriginalSlice, newChars);
  const inserted = newChars.slice(matches);

  if (matches > 0) {
    state.renderedHTML += `<span>${escapeHtml(newOriginalSlice.slice(0, matches))}</span>`;
  }
  if (inserted) {
    state.renderedHTML += `<ins>${escapeHtml(inserted)}</ins>`;
  }

  rightPane.innerHTML = state.renderedHTML;
  state.lastPartialLen = partial.length;
  state.renderedOriginalLen = prevRenderedOriginal + newOriginalSlice.length;
}

function scheduleRender(fileKey) {
  const state = this.renderState[fileKey] || (this.renderState[fileKey] = {
    lastPartialLen: 0, renderedHTML: '', renderedOriginalLen: 0, rafScheduled: false, mode: 'streaming',
  });
  if (state.rafScheduled) return;
  state.rafScheduled = true;
  requestAnimationFrame(() => {
    state.rafScheduled = false;
    this.renderCompare(fileKey);
  });
}
```

### 3.3 onStream 调度

```js
// app.js 替换现有 updateStream
updateStream(fileKey, partial) {
  this.streamingContent[fileKey] = partial;
  // 🔴 修复 1: t.original 在 markFileRunning 时已设
  this.scheduleRender(fileKey);
}
```

### 3.4 切回全量 diff 按钮

```js
// 复制 export 按钮旁加 "查看完整 diff" 按钮
toggleDiffMode() {
  const state = this.renderState[this.selectedFileKey];
  if (!state) return;
  state.mode = (state.mode === 'streaming') ? 'full' : 'streaming';
  if (state.mode === 'full') {
    // 切到全量: 重置 streaming 状态, 用 diff_main 重渲染
    // 不需要 reset state, renderCompare mode==='full' 走独立分支
  } else {
    // 切回流式: 重置累积, 重新从 partial 增量
    state.lastPartialLen = 0;
    state.renderedHTML = '';
    state.renderedOriginalLen = 0;
  }
  this.renderCompare(this.selectedFileKey);
}
```

---

## 4. 左栏原文字数据源 (修复 🔴 1)

### 4.1 后端改动: `app/web_backend.py`

```python
# 在 start_proofread (line 169 范围) 中
# 🔴 修复 1: 带 original, 但大文件 (> 50K 字) 不推, 改用 read_file fallback
_ORIGINAL_PUSH_LIMIT = 50000  # 50K 字阈值, 超过不推 (JSON 序列化开销)

self._engine.on_file_start = lambda k: self._push("onFileStart", {
    "file_key": k,
    "original": self._engine.tasks[k].original_text if len(self._engine.tasks[k].original_text) <= _ORIGINAL_PUSH_LIMIT else None,
    "original_truncated": len(self._engine.tasks[k].original_text) > _ORIGINAL_PUSH_LIMIT,
})
# 前端拿不到 original 时, 调 window.pywebview.api.read_file(path) 读
```

### 4.2 前端改动: `app.js markFileRunning`

```js
markFileRunning(fileKey) {
  const t = this.tasks.find(t => t.path === fileKey);
  if (t) {
    t.status = 'running';
    // 🔴 修复 1: 从 data.original 同步设 t.original
    if (this._lastFileStartData?.file_key === fileKey) {
      t.original = this._lastFileStartData.original || '';
    }
    this.renderFileList();
  }
}
```

或者更干净: dispatch 直接处理 `onFileStart` 时设 `t.original`, `markFileRunning` 只设 status。

```js
// dispatch
case 'onFileStart':
  this.handleFileStart(data);
  this.markFileRunning(data.file_key);
  break;

handleFileStart(data) {
  const t = this.tasks.find(t => t.path === data.file_key);
  if (t) {
    t.original = data.original || '';  // 🔴 修复 1
    t.status = 'running';
  }
}
```

---

## 5. HTML 结构 (修复 🔴 3)

### 5.1 新结构

```html
<main id="view-home" class="view active">
  <div class="page-header">
    <h1>校对</h1>
    <div class="actions">
      <button id="btn-add-files">添加文件</button>
      <button id="btn-clear-files">清空</button>
      <button id="btn-start">开始</button>
      <button id="btn-pause">暂停</button>
      <button id="btn-resume">恢复</button>
      <button id="btn-cancel">取消</button>
    </div>
  </div>

  <div class="content-grid home-grid">  <!-- 🔴 修复 4: 加 home-grid class -->
    <!-- 左: 文件 + 进度子页面 -->
    <section class="card file-list-card">
      <div class="drop-zone" id="drop-zone">拖拽文件</div>
      <ul class="file-list" id="file-list"></ul>

      <div class="progress-subpanel">  <!-- 🔴 新增: 进度子页面 -->
        <div class="progress-bar">
          <div id="progress-fill" class="progress-fill" style="width:0%"></div>
        </div>
        <div id="progress-stats" class="stats">就绪</div>
        <div id="progress-eta" class="stats-secondary"></div>
        <div id="home-chunking-display" class="chunking-label">分块: --</div>
        <pre id="log-output" class="log"></pre>  <!-- 🟡 加 max-height -->
      </div>
    </section>

    <!-- 右: 对比 2 子栏 -->
    <section class="card compare-card">
      <div class="compare-header">
        <h2>对比</h2>
        <div class="actions">
          <button id="btn-toggle-diff-mode">查看完整 diff</button>
          <button id="btn-copy-result">复制</button>
          <button id="btn-export-result">导出</button>
        </div>
      </div>
      <div class="compare-grid">
        <div class="compare-original" id="compare-original">
          <div class="compare-empty">选择文件查看原文</div>
        </div>
        <div class="compare-revised" id="compare-revised">
          <div class="compare-empty">流式输出将显示在这里</div>
        </div>
      </div>
    </section>
  </div>
</main>
```

### 5.2 被删 ID / 类名清单 (修复 🔴 3 必填)

| 被删 | 替代 |
|------|------|
| `<section class="card progress-card">` (整个中央栏) | 移到 `<div class="progress-subpanel">` |
| `<div class="diff-tabs" id="diff-tabs">` | 删除 (单文件 selectedFileKey) |
| `<div class="diff-content" id="diff-content">` | 拆成 `<div id="compare-original">` + `<div id="compare-revised">` |

### 5.3 新 ID / 类名清单

| 新增 | 用途 |
|------|------|
| `<div class="content-grid home-grid">` | 🔴 修复 4 显式 2 栏 |
| `<div class="progress-subpanel">` | 文件栏底部进度区 |
| `<div id="home-chunking-display">` | 保留 (现已在 progress-subpanel) |
| `<section class="card compare-card">` | 右栏卡片 |
| `<div class="compare-grid">` | 2 子栏 grid |
| `<div id="compare-original">` | 左: 原文字 |
| `<div id="compare-revised">` | 右: 流式修改 + ins 高亮 |
| `<button id="btn-toggle-diff-mode">` | 切换流式/全量 diff 模式 |
| `<div class="compare-empty">` | 空状态 |
| `<div class="error-mark">` | 错误态 |

### 5.4 旧 JS 调用必须更新 (修复 🔴 3)

| 旧调用 | 新调用 |
|--------|--------|
| `getElementById('diff-tabs')` | 删除 (renderDiffTabs 整个删) |
| `getElementById('diff-content')` | 删除 (renderDiffForFile 整个改 renderCompare) |
| `getElementById('diff-empty')` | 改成 `getElementById('compare-original').querySelector('.compare-empty')` |
| `getElementById('home-chunking-display')` | **保留** (已挪位置, ID 不变) |
| `getElementById('progress-fill')` `progress-stats` `progress-eta` `log-output` | **保留** (已挪位置) |
| `getElementById('btn-copy-result')` `btn-export-result` | **保留** (已挪位置到 compare-card) |

---

## 6. CSS 改动 (修复 🔴 4)

```css
/* 🔴 修复 4: 显式 2 栏 (overrides .content-grid 默认 3 栏) */
.content-grid.home-grid {
  grid-template-columns: 1fr 1.5fr;  /* 左文件 1fr, 右对比 1.5fr */
  gap: var(--space-4);
}

/* 进度子页面 */
.progress-subpanel {
  margin-top: auto;  /* 推到文件栏底部 */
  padding-top: var(--space-3);
  border-top: 1px solid var(--color-border-subtle);
}

/* 🟡 14: 限制 log-output 高度 */
.progress-subpanel .log {
  max-height: 120px;
  overflow-y: auto;
  margin-top: var(--space-2);
}

/* 对比 2 子栏 */
.compare-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1px;
  background: var(--color-border);
  flex: 1;  /* 🟡 32: 用 flex 撑满, 不要 calc(100vh - 240px) 硬编码 */
  min-height: 0;
  overflow: hidden;
}

/* main / content-grid 用 flex 撑满剩余高度 (不硬编码 vh) */
.view { display: flex; flex-direction: column; }
.content-grid { flex: 1; min-height: 0; }

.compare-original,
.compare-revised {
  background: var(--color-card);
  font-family: var(--font-mono), var(--font-family);  /* 🟡 13: 中文回退 */
  font-size: 13px;
  line-height: 1.6;
  white-space: pre-wrap;
  overflow-y: auto;
  padding: var(--space-3);
}

.compare-revised ins {
  background: var(--color-diff-add-bg);
  color: var(--color-diff-add);
  text-decoration: none;
  border-radius: 2px;
  padding: 0 1px;
}

.compare-revised del {
  background: var(--color-diff-del-bg);
  color: var(--color-diff-del);
  text-decoration: line-through;
}

.compare-empty {
  color: var(--color-text-tertiary);
  text-align: center;
  padding: var(--space-6);
}

.error-mark {
  background: var(--color-error-light);
  color: var(--color-error);
  padding: var(--space-3);
  border-radius: var(--radius-md);
  font-family: var(--font-family);
}

/* 文件栏 flex 布局 (让 progress-subpanel 推到底部) */
.file-list-card {
  display: flex;
  flex-direction: column;
}

.file-list-card .file-list {
  flex: 1;  /* 文件列表占中间空间 */
  overflow-y: auto;
  max-height: 300px;  /* 限制文件列表最大高度 */
}
```

---

## 7. renderState 生命周期 (修复 🔴 5)

| 时机 | 动作 |
|------|------|
| `startProofread` 开始 | 为每个 fileKey 初始化 `renderState[fileKey]` |
| `updateStream(fileKey, partial)` | 调用 `scheduleRender(fileKey)` (RAF 合并) |
| `removeFile(path)` | `delete renderState[path]` |
| `clearFiles()` | `renderState = {}` |
| `selectFile(path)` | **不删** (切回要恢复) |
| 流式完成 + 用户点 "查看完整 diff" | `state.mode = 'full'`, renderCompare 走全量分支 |
| 切回 "流式 diff" 按钮 | `state.lastPartialLen=0; renderedHTML=''; renderedOriginalLen=0; mode='streaming'`, 重新增量 |
| 校对 retry | `state.lastPartialLen=0; renderedHTML=''; renderedOriginalLen=0` (partial 重置到 0, D 算法保护已覆盖) |
| 关闭窗口 | 浏览器回收, 无需处理 |

---

## 8. setInterval 50ms → 16ms (修复 🟠 7)

```js
// app.js startEventLoop 改
startEventLoop() {
  // 50ms → 16ms (60 FPS), D 算法高频渲染需要快速拉取
  setInterval(() => {
    while (this.eventQueue.length > 0) {
      const [event, data] = this.eventQueue.shift();
      this.dispatch(event, data);
    }
  }, 16);
}
```

---

## 9. 复制/导出按钮流式中禁用 (修复 🟠 8)

```js
selectFile(path) {
  this.selectedFileKey = path;
  this.renderFileList();
  this.renderCompare(path);  // 改 renderDiffForFile
  // 🟠 修复 8: 流式时禁用复制/导出
  const t = this.tasks.find(t => t.path === path);
  const hasResult = t && t.corrected && !this.isProcessing;
  if (copyBtn) copyBtn.disabled = !hasResult;
  if (exportBtn) exportBtn.disabled = !hasResult;
  if (toggleDiffBtn) toggleDiffBtn.disabled = !t?.corrected;
}
```

---

## 10. 实施步骤 (调整顺序)

### Phase 1: 后端事件协议 (修复 🔴 1)
- 修改 `app/web_backend.py` `start_proofread` 中 `on_file_start` 回调, 带 `original` 字段
- 测试: 加 mock 测试验证 onFileStart data 含 original

### Phase 2: HTML 结构 (修复 🔴 3)
- 修改 `web/index.html`: 删 `.progress-card` 和 `.diff-card` 内的旧结构
- 新增 `.progress-subpanel` 在 `.file-list-card` 底部
- 新增 `.compare-card` 替换 `.diff-card`
- 加 `<button id="btn-toggle-diff-mode">`

### Phase 3: CSS (修复 🔴 4)
- 加 `.content-grid.home-grid { grid-template-columns: 1fr 1.5fr; }` 显式声明
- 加 `.progress-subpanel` / `.compare-grid` / `.compare-original` / `.compare-revised` 样式
- 加 `.compare-revised ins/del` 高亮
- 加 `.compare-empty` / `.error-mark` 状态
- log-output max-height: 120px

### Phase 4: app.js D 算法 (核心)
- 加 `renderState` 初始化 (在 init / startProofread)
- 加 `renderCompare(fileKey)` (替换 `renderDiffForFile`)
- 加 `scheduleRender(fileKey)` (RAF 调度)
- 加 `commonPrefixLength` 工具
- 加 `toggleDiffMode()` 按钮 handler
- 加 `handleFileStart(data)` 同步设 `t.original`
- 改 `updateStream` 调 `scheduleRender` (不直接 render)
- 改 `selectFile` 调 `renderCompare` + 复制/导出按钮状态 (修复 🟠 8)
- 改 `removeFile` / `clearFiles` 清理 `renderState` (修复 🔴 5)
- 加 `handleError` 错误态 fallback (修复 🟠 9)
- 改 `startEventLoop` 16ms (修复 🟠 7)

### Phase 5: 删旧 JS (修复 🔴 3 收尾)
- 删 `renderDiffForFile` / `_doRenderDiffForFile` / `renderDiffTabs` / `selectFile` 中相关调用
- 删 `getElementById('diff-tabs')` `getElementById('diff-content')` 所有引用

### Phase 6: 测试
- 现有 416 测试不破
- 新增 5-8 个 D 算法 mock 测试:
  - 增量前缀匹配 (newChars 全部新增 → 全部 ins)
  - 增量前缀匹配 (newChars 全部保留 → 全部 span)
  - 增量前缀匹配 (混合)
  - partial 倒退保护 (retry)
  - renderState 清理 (removeFile / clearFiles)
  - 错误态 fallback
  - 模式切换 (streaming ↔ full)
- 总数 ≥ 423

### Phase 7: CHANGELOG
- 加 v4.1.5 段: UI 重构 + D 方案 incremental + 5 致命 5 重要修复

---

## 11. 风险与验收

### 风险

| 风险 | 缓解 |
|------|------|
| WebView2 高频 innerHTML (30 FPS) 丢帧 | RAF + setInterval 16ms; 测实际帧率 |
| 大文件 (10K+ 字) D 算法 renderedHTML 累积内存 | 接受, 估算 30KB/file |
| 跨 chunk 边界视觉"接缝" | 接受为 `<ins>` (新段落合理视觉) |
| 并行校对 renderState 累积 | 接受, 5 文件 ≈ 150KB |
| 字体回退错位 | 🔴 13 修复, 显式 `font-family: var(--font-mono), var(--font-family)` |

### 验收清单
- [ ] 主页 2 大栏 (Files | Compare)
- [ ] 进度 + 日志 + chunking 在 Files 栏底部 (固定展开)
- [ ] Compare 2 子栏 (Original | Revised) 同时显示
- [ ] 流式输出右栏打字机效果 (30 FPS, 设了 16ms interval)
- [ ] 新增字符 `<ins>` 高亮
- [ ] 左右栏独立滚动
- [ ] 多 chunk 累积显示 (跨 chunk 接受为 ins)
- [ ] 流式完成有 "查看完整 diff" 按钮, 切到带 `<del>` 全量
- [ ] 复制/导出 流式时 disabled, 完成后 enabled
- [ ] 错误态 fallback 显示红色错误块
- [ ] 测试 ≥ 416/0 全过 (新增 ≥ 7 个)
- [ ] 视觉 4K 屏不挤
- [ ] 左栏在流式时就有原文字 (修复 🔴 1)

### 不在本次范围
- 流式撤销/编辑
- 多文件并行 diff (仍按 selectedFileKey 单文件)
- Export 文件名格式 (v4.1.4 修)
- 暗色模式 / 移动端响应式

---

## 12. 时间预估

- Phase 1 后端事件协议: 0.5h
- Phase 2 HTML: 0.5h
- Phase 3 CSS: 1h
- Phase 4 app.js D 算法 + 集成: 2-3h
- Phase 5 删旧 JS: 0.5h
- Phase 6 测试: 0.5-1h
- Phase 7 CHANGELOG: 0.2h
- 合计: **5-7h**

---

## 13. 实施前置条件

- v4.1.4 (流式 33ms + 导出 YYMMDD) 已完成 (worker `bg_78000b12` 跑中)
- v4.1.3 测试 416/0 全过 (已确认)
- 用户已审本 plan v2, 同意开工

实施时派 v4.1.5 worker, prompt 含本 plan v2 全文 + 6 必读文件 + 完整交付格式。
