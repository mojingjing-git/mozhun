// 新时代校对大师 v4.1.8 前端逻辑 (Win11 Fluent 2 完整重构, 业务逻辑保留 v4.1.5)
//
// 借鉴自 https://pywebview.flowrl.com/ (BSD-3-Clause) - Bridge 模式
// 借鉴自 https://github.com/google/diff-match-patch (Apache-2.0) - diff 算法
// 借鉴自 https://fluent2.microsoft.design/ (MIT) - 设计令牌
// 借鉴自 https://learn.microsoft.com/zh-cn/windows/apps/design/ (Microsoft Terms of Use) - Win11 设计原则
//
// 事件流模型 (PLAN-pywebview.md §6.1 / §7.3, PLAN-v4.1.5-ui-redesign.md §3):
// - Python 端 33ms 节流后 evaluate_js 调 window.app.handleEventBatch([[name, data], ...])
//   (v4.1.4: 100ms -> 33ms, 30 FPS 流式更流畅)
// - v4.1.5: 前端用 setInterval 16ms (60 FPS) 拉 eventQueue, 配合 RAF 让 D 算法
//   在下一帧渲染, 实现 30 FPS 打字机效果
// - 流式: handleEvent('onStream') -> updateStream(fileKey, partial) -> scheduleRender
//   -> renderCompare 用 D 方案增量计算 (commonPrefixLength), 只追加新字符
// - DeAI 流式: handleEvent('onDeaiStream') -> 按 task_id 路由到对应 step 输出框
//
// v4.1.5 主页 2 栏布局: [Files+进度子页面 | Compare(原文字+修改文字)]
// 渲染状态按 fileKey 独立缓存, 切回文件恢复渲染. 模式 streaming/full 切换走 RAF.

const App = {
  config: {},
  promptModes: [],
  apiTemplates: [],
  chunkingPresets: [],
  tasks: [],                  // [{path, status, original, corrected, error}]
  streamingContent: {},       // {file_key: latest_partial_text}
  selectedFileKey: null,
  eventQueue: [],
  dmp: null,                  // diff_match_patch instance (lazy)
  isProcessing: false,
  // 500ms 防抖保存 config
  configSaveTimer: null,
  configDirty: false,
  // URL 校验
  urlValid: true,
  // DeAI 状态
  deai: {
    step1TaskId: null,
    step2TaskId: null,
    step3TaskId: null,
    step1Done: false,
    step2Done: false,
    step3Done: false,
    lastResult: '',
    // v4.1.7: 风格 Profile 状态
    styleCardSlug: '',  // 当前选定的 profile (空 = 不选)
    styleProfiles: { builtin: [], custom: [] },
    distillTaskId: null,  // 当前蒸馏 task
  },
  // v4.1.5: 每文件渲染状态 (D 方案 incremental)
  // 详细见 PLAN-v4.1.5-ui-redesign.md §3.1 / §7
  renderState: {},            // {file_key: {lastPartialLen, renderedHTML, renderedOriginalLen, rafScheduled, mode}}

  // ====== 初始化 ======
  async init() {
    // 创建 diff_match_patch 实例 (从 lib/diff-match-patch.js 加载到 window.diff_match_patch)
    if (typeof window.diff_match_patch === 'function') {
      this.dmp = new window.diff_match_patch();
    }

    // 加载配置
    try {
      this.config = await window.pywebview.api.get_config();
    } catch (e) {
      console.error('get_config 失败:', e);
      this.config = {};
    }

    // 加载 prompt 模式列表
    try {
      this.promptModes = await window.pywebview.api.get_prompt_modes();
    } catch (e) {
      console.error('get_prompt_modes 失败:', e);
      this.promptModes = [];
    }

    // 加载 API 模板
    try {
      this.apiTemplates = await window.pywebview.api.get_api_templates();
    } catch (e) {
      console.error('get_api_templates 失败:', e);
      this.apiTemplates = [];
    }

    // 加载 chunking 预设
    try {
      this.chunkingPresets = await window.pywebview.api.get_chunking_presets();
    } catch (e) {
      console.error('get_chunking_presets 失败:', e);
      this.chunkingPresets = [];
    }

    this.renderSidebar();
    this.renderHome();
    this.renderSettings();
    this.bindEvents();
    this.startEventLoop();
    this.setView('home');
    this.appendLog('[就绪] v4.0 pywebview 前端已加载');
    // v4.1.7: 加载风格 profile 列表 (异步, 不阻塞 init)
    this.loadStyleProfiles();
  },

  // ====== 视图切换 ======
  setView(viewName) {
    document.querySelectorAll('.view').forEach(el => el.classList.remove('active'));
    document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));
    const view = document.getElementById('view-' + viewName);
    const nav = document.querySelector(`.nav-item[data-view="${viewName}"]`);
    if (view) view.classList.add('active');
    if (nav) nav.classList.add('active');
  },

  // ====== 事件循环 ======
  startEventLoop() {
    // v4.1.5 (🟠 修复 7): 50ms -> 16ms (60 FPS 拉取), 让 D 算法高频渲染
    // (30 FPS 流式打字机) 不被前端 setInterval 截流. 跟后端 _push 33ms 节流
    // 仍兼容 (前端只关心不丢事件, 16ms 间隔低于 33ms flush 频率, 每次拉都拿到最新)
    setInterval(() => {
      while (this.eventQueue.length > 0) {
        const [event, data] = this.eventQueue.shift();
        this.handleEvent(event, data);
      }
    }, 16);
  },

  // 批量事件入口 (后端 _flush 推送)
  handleEventBatch(events) {
    if (!Array.isArray(events)) return;
    for (const [event, data] of events) {
      this.eventQueue.push([event, data]);
    }
  },

  handleEvent(event, data) {
    this.dispatch(event, data);
  },

  dispatch(event, data) {
    switch (event) {
      case 'onLog':            this.appendLog(data); break;
      case 'onStream':         this.updateStream(data.file_key, data.partial); break;
      // v4.1.5 (🔴 修复 1): onFileStart 改为 dict {file_key, original, original_truncated}
      // 先 handleFileStart 同步设 t.original (左栏原文字数据源),
      // 再 markFileRunning 设 status='running'
      case 'onFileStart':      this.handleFileStart(data); this.markFileRunning(data.file_key); break;
      case 'onFileDone':       this.markFileDone(data); break;
      case 'onFileCompleted':  this.markFileDone(data); break;
      case 'onStatsUpdate':    this.updateStats(data); break;
      case 'onTaskComplete':   this.onTaskComplete(data); break;
      // v4.1.7: 风格 profile 蒸馏 (step='distill') 也复用 onDeaiStream 事件
      case 'onDeaiStream':     this.handleDeaiStreamOrDistill(data); break;
      case 'onDeaiComplete':   this.handleDeaiComplete(data); break;
      case 'onDeaiError':      this.handleDeaiError(data); break;
      // v4.1 (I3): fetch_models / test_connection 异步完成事件
      case 'onFetchModelsComplete': this.handleFetchModelsComplete(data); break;
      // v4.1.3 (F2): 后端 Python DOM 监听到 drop 后, 推送 onFilesDropped (含 pywebviewFullPath)
      case 'onFilesDropped':   this.handleFilesDropped(data); break;
      default: console.warn('未知事件:', event, data);
    }
  },

  // ====== 侧边栏 ======
  renderSidebar() {
    document.querySelectorAll('.nav-item').forEach(btn => {
      btn.addEventListener('click', () => this.setView(btn.dataset.view));
    });
  },

  // ====== 主页渲染 ======
  renderHome() {
    // v4.1 (I5): chunking 预设下拉挪到设置页, 主页只显示只读 label
    this.renderChunkingDisplay();
    this.updateFileCount();
  },

  // v4.1 (I5): 渲染主页只读 chunking 标签, 读 this.config.chunking_preset
  renderChunkingDisplay() {
    const el = document.getElementById('home-chunking-display');
    if (!el) return;
    const preset = this.config.chunking_preset || 'balanced';
    const found = this.chunkingPresets.find(p => p.key === preset);
    const label = found ? found.label : preset;
    el.textContent = `分块: ${label}`;
  },

  updateFileCount() {
    const el = document.getElementById('file-count');
    if (el) el.textContent = this.tasks.length;
    const clearBtn = document.getElementById('btn-clear-files');
    if (clearBtn) clearBtn.disabled = this.tasks.length === 0 || this.isProcessing;
    const startBtn = document.getElementById('btn-start');
    if (startBtn) {
      const hasPending = this.tasks.some(t => t.status === 'pending' || t.status === 'failed');
      startBtn.disabled = this.isProcessing || !hasPending;
    }
  },

  // ====== 设置页渲染 ======
  renderSettings() {
    // 填充 prompt 模式
    this.fillSelect('cfg-prompt-mode', this.promptModes, this.config.prompt_mode);

    // 填充 API 模板
    const tplSel = document.getElementById('cfg-template');
    if (tplSel) {
      tplSel.innerHTML = '<option value="">-- 选择 API 模板 --</option>';
      for (const t of this.apiTemplates) {
        const opt = document.createElement('option');
        opt.value = t.name;
        opt.textContent = t.name + ' (' + (t.model || '?') + ')';
        tplSel.appendChild(opt);
      }
    }

    // 填充 chunking 预设
    this.fillSelect('cfg-chunking-preset', this.chunkingPresets, this.config.chunking_preset);

    // 填充字段
    this.setVal('cfg-api-base', this.config.api_base);
    this.setVal('cfg-api-key', this.config.api_key);
    this.setVal('cfg-model', this.config.model);
    this.setVal('cfg-temperature', this.config.temperature);
    this.setVal('cfg-concurrency', this.config.concurrency);
    this.setVal('cfg-max-retries', this.config.max_retries);
    this.setVal('cfg-timeout', this.config.timeout);
    this.setVal('cfg-context-max-chars', this.config.context_max_chars);
    this.setVal('cfg-context-max-chunks', this.config.context_max_chunks);
    this.setVal('cfg-custom-prompt', this.config.custom_prompt);

    // 初始 URL 校验
    this.validateApiBase();
  },

  fillSelect(id, items, currentVal) {
    const sel = document.getElementById(id);
    if (!sel) return;
    sel.innerHTML = '';
    for (const it of items) {
      const opt = document.createElement('option');
      opt.value = it.key;
      opt.textContent = it.label;
      // v4.1.8.1: tooltip 兜底 (动态填充的 option 也显示 label 当 title)
      // 后端可传 it.tooltip 覆盖 (更具体的描述优先)
      opt.title = it.tooltip || it.label;
      if (it.key === currentVal) opt.selected = true;
      sel.appendChild(opt);
    }
  },

  setVal(id, val) {
    const el = document.getElementById(id);
    if (el && val !== undefined && val !== null) el.value = val;
  },

  getVal(id) {
    const el = document.getElementById(id);
    return el ? el.value : '';
  },

  // ====== 事件绑定 ======
  bindEvents() {
    // 主页
    const addBtn = document.getElementById('btn-add-files');
    if (addBtn) addBtn.addEventListener('click', () => this.addFiles());

    const clearBtn = document.getElementById('btn-clear-files');
    if (clearBtn) clearBtn.addEventListener('click', () => this.clearFiles());

    const startBtn = document.getElementById('btn-start');
    if (startBtn) startBtn.addEventListener('click', () => this.startProofread());

    const pauseBtn = document.getElementById('btn-pause');
    if (pauseBtn) pauseBtn.addEventListener('click', () => this.pauseProofread());

    const resumeBtn = document.getElementById('btn-resume');
    if (resumeBtn) resumeBtn.addEventListener('click', () => this.resumeProofread());

    const cancelBtn = document.getElementById('btn-cancel');
    if (cancelBtn) cancelBtn.addEventListener('click', () => this.cancelProofread());

    // diff 操作
    const copyBtn = document.getElementById('btn-copy-result');
    if (copyBtn) copyBtn.addEventListener('click', () => this.copyResult());

    const exportBtn = document.getElementById('btn-export-result');
    if (exportBtn) exportBtn.addEventListener('click', () => this.exportResult());

    // v4.1.5: 流式/全量 diff 模式切换按钮
    const toggleDiffBtn = document.getElementById('btn-toggle-diff-mode');
    if (toggleDiffBtn) toggleDiffBtn.addEventListener('click', () => this.toggleDiffMode());

    // 拖拽
    this.bindDragDrop();

    // 设置
    const saveBtn = document.getElementById('btn-save-config');
    if (saveBtn) saveBtn.addEventListener('click', () => this.saveConfigNow());

    const testConnBtn = document.getElementById('btn-test-connection');
    if (testConnBtn) testConnBtn.addEventListener('click', () => this.testConnection());

    const toggleKeyBtn = document.getElementById('btn-toggle-key');
    if (toggleKeyBtn) toggleKeyBtn.addEventListener('click', () => this.toggleKeyVisibility());

    const fetchBtn = document.getElementById('btn-fetch-models');
    if (fetchBtn) fetchBtn.addEventListener('click', () => this.fetchModels());

    // API 模板选择
    const tplSel = document.getElementById('cfg-template');
    if (tplSel) tplSel.addEventListener('change', () => this.applyTemplate(tplSel.value));

    // v4.1.8: 主题切换 (Win11 §3.1.1 暗色模式 + §2.3 个人原则)
    this.bindThemeSwitcher();

    // URL 校验 + 防抖
    const urlInput = document.getElementById('cfg-api-base');
    if (urlInput) {
      urlInput.addEventListener('input', () => {
        this.validateApiBase();
        this.markConfigDirty();
      });
    }
    // 所有 cfg-* 字段防抖
    document.querySelectorAll('#view-settings input, #view-settings select, #view-settings textarea').forEach(el => {
      if (el.id === 'cfg-template' || el.id === 'cfg-api-base') return; // 单独处理
      el.addEventListener('input', () => this.markConfigDirty());
      el.addEventListener('change', () => this.markConfigDirty());
    });

    // DeAI
    const step1 = document.getElementById('btn-deai-step1');
    if (step1) step1.addEventListener('click', () => this.deaiStep1());
    const step2 = document.getElementById('btn-deai-step2');
    if (step2) step2.addEventListener('click', () => this.deaiStep2());
    const step3 = document.getElementById('btn-deai-step3');
    if (step3) step3.addEventListener('click', () => this.deaiStep3());

    // v4.1.7: DeAI Step 0 风格 Profile 按钮
    const profileSel = document.getElementById('deai-style-profile');
    if (profileSel) profileSel.addEventListener('change', () => this.selectStyleProfile(profileSel.value));
    const btnCreate = document.getElementById('btn-deai-create-profile');
    if (btnCreate) btnCreate.addEventListener('click', () => this.createStyleProfile());
    const btnAddSample = document.getElementById('btn-deai-add-sample');
    if (btnAddSample) btnAddSample.addEventListener('click', () => this.addSampleToProfile());
    const btnDistill = document.getElementById('btn-deai-distill');
    if (btnDistill) btnDistill.addEventListener('click', () => this.distillStyleProfile());

    // DeAI 复制按钮
    for (let i = 1; i <= 3; i++) {
      const btn = document.getElementById('btn-deai-copy-' + i);
      if (btn) btn.addEventListener('click', () => this.copyDeaiOutput(i));
    }
    const deaiExport = document.getElementById('btn-deai-export');
    if (deaiExport) deaiExport.addEventListener('click', () => this.exportDeaiResult());

    // v4.1.6 (P3): 关窗兜底保存. 之前若用户改了 cfg 后 500ms 内关窗,
    // 防抖还没触发, 改动全丢. 这里在 beforeunload 同步 fire-and-forget 一次.
    // 注意: beforeunload 不能 await, 所以用 try/catch 串行调 (不依赖 Promise.all).
    // 11 个 set_config + 1 个 save_config 都在 webview 销毁前能塞进 IPC 队列.
    window.addEventListener('beforeunload', () => {
      if (!this.configDirty) return;
      try {
        const updates = this._collectAllConfig();
        for (const [k, v] of Object.entries(updates)) {
          try { window.pywebview.api.set_config(k, v); } catch (_) { /* swallow */ }
        }
        try { window.pywebview.api.save_config(); } catch (_) { /* swallow */ }
      } catch (_) { /* swallow */ }
    });
  },

  // ====== 拖拽 (Drag & Drop) ======
  // v4.1.3 (F2): 重写 - 前端不再 addEventListener('drop'), 全部走 Python DOM API.
  // 原因: pywebview 6.x 的 drop 文件路径注入机制 (pywebviewFullPath) 只在
  // window.dom.get_element(selector).on('drop', callback) 注册时生效
  // (element.py:412-413 自增 _dnd_state['num_listeners'], 否则 C# 端 FilesDropped 消息直接 return).
  // 前端 addEventListener('drop') 拿不到 pywebviewFullPath, 因此完全不绑 drop 处理,
  // 只保留 dragover/dragleave 视觉 class 切换.
  bindDragDrop() {
    const dropZone = document.getElementById('drop-zone');
    if (!dropZone) return;
    // 阻止默认行为 (避免浏览器打开文件), 整页也禁掉
    ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
      dropZone.addEventListener(eventName, (e) => {
        e.preventDefault();
        e.stopPropagation();
      });
      document.body.addEventListener(eventName, (e) => {
        e.preventDefault();
        e.stopPropagation();
      });
    });
    // 视觉 class 切换: dragover 显示高亮
    dropZone.addEventListener('dragenter', () => dropZone.classList.add('drag-over'));
    dropZone.addEventListener('dragover', () => dropZone.classList.add('drag-over'));
    dropZone.addEventListener('dragleave', () => dropZone.classList.remove('drag-over'));
    // drop 触发后清掉高亮 (实际处理走 Python 后端推 onFilesDropped 事件)
    dropZone.addEventListener('drop', () => dropZone.classList.remove('drag-over'));
  },

  // v4.1.3 (F2): 接收 Python DOM API 推过来的文件路径 (含 pywebviewFullPath)
  handleFilesDropped(data) {
    if (!data || !Array.isArray(data.paths) || data.paths.length === 0) {
      this.appendLog('[拖拽] 未拿到有效文件路径');
      return;
    }
    // 用 drag_drop_files 桥接方法校验 (避免不存在路径混进列表)
    const paths = data.paths;
    let added = 0;
    for (const p of paths) {
      if (!this.tasks.find(t => t.path === p)) {
        this.tasks.push({path: p, status: 'pending', original: '', corrected: '', error: ''});
        added++;
      }
    }
    this.renderFileList();
    this.updateFileCount();
    this.appendLog(`[拖拽] 添加 ${added} 个文件, 总计 ${this.tasks.length}`);
  },

  // v4.1.8: 主题切换 (auto/light/dark) — 设置 document.documentElement.dataset.theme
  //         auto 模式: 删除 data-theme, 让 @media (prefers-color-scheme) 生效
  bindThemeSwitcher() {
    const switcher = document.getElementById('theme-switcher');
    if (!switcher) return;
    const buttons = switcher.querySelectorAll('button[data-theme-value]');
    buttons.forEach(btn => {
      btn.addEventListener('click', () => {
        const value = btn.dataset.themeValue;  // auto / light / dark
        if (value === 'auto') {
          delete document.documentElement.dataset.theme;
        } else {
          document.documentElement.dataset.theme = value;
        }
        // 更新 active 样式 + aria-selected
        buttons.forEach(b => {
          const isActive = b === btn;
          b.classList.toggle('active', isActive);
          b.setAttribute('aria-selected', isActive ? 'true' : 'false');
        });
        this.appendLog(`[主题] 已切换到: ${value}`);
      });
    });
  },

  // ====== 文件操作 ======
  addTaskPath(p) {
    if (!this.tasks.find(t => t.path === p)) {
      this.tasks.push({path: p, status: 'pending', original: '', corrected: '', error: ''});
    }
  },

  async addFiles() {
    try {
      const paths = await window.pywebview.api.choose_files();
      if (!paths || paths.length === 0) {
        this.appendLog('[取消] 用户未选择文件');
        return;
      }
      let added = 0;
      for (const p of paths) {
        if (!this.tasks.find(t => t.path === p)) {
          this.tasks.push({path: p, status: 'pending', original: '', corrected: '', error: ''});
          added++;
        }
      }
      this.renderFileList();
      this.updateFileCount();
      this.appendLog(`[添加] 新增 ${added} 个文件, 总计 ${this.tasks.length}`);
    } catch (e) {
      this.appendLog('[错误] choose_files 失败: ' + e);
    }
  },

  async clearFiles() {
    if (this.isProcessing) {
      this.appendLog('[提示] 处理中, 请先取消');
      return;
    }
    if (this.tasks.length === 0) return;
    if (!confirm(`确认清空 ${this.tasks.length} 个文件?`)) return;
    try {
      await window.pywebview.api.clear_files();
    } catch (e) { /* ignore */ }
    this.tasks = [];
    this.selectedFileKey = null;
    this.streamingContent = {};
    // v4.1.5 (🔴 修复 5): 清空所有 renderState, 避免内存泄漏
    this.renderState = {};
    this.renderFileList();
    this.renderCompare(null);
    this.updateFileCount();
    this.appendLog('[清空] 文件列表已清空');
  },

  async removeFile(path) {
    if (this.isProcessing) return;
    try {
      await window.pywebview.api.remove_file(path);
    } catch (e) { /* ignore */ }
    this.tasks = this.tasks.filter(t => t.path !== path);
    delete this.streamingContent[path];
    // v4.1.5 (🔴 修复 5): 删 renderState 防止内存泄漏
    delete this.renderState[path];
    if (this.selectedFileKey === path) this.selectedFileKey = null;
    this.renderFileList();
    this.renderCompare(this.selectedFileKey);
    this.updateFileCount();
  },

  renderFileList() {
    const ul = document.getElementById('file-list');
    if (!ul) return;
    if (this.tasks.length === 0) {
      ul.innerHTML = '<li class="file-list-empty">尚未添加文件</li>';
      this.updateFileCount();
      return;
    }
    ul.innerHTML = '';
    for (const t of this.tasks) {
      const li = document.createElement('li');
      const name = t.path.split(/[\\/]/).pop();
      const statusText = {
        pending: '待处理', running: '处理中', paused: '已暂停', completed: '完成', failed: '失败', cancelled: '已取消',
      }[t.status] || t.status;
      li.innerHTML = `<span class="file-name" title="${this.escapeHtml(t.path)}">${this.escapeHtml(name)}</span>
                      <span class="file-status ${t.status}">${statusText}</span>
                      <button class="file-remove" data-path="${this.escapeHtml(t.path)}" title="删除" type="button">×</button>`;
      li.addEventListener('click', (e) => {
        if (e.target.classList.contains('file-remove')) return;
        this.selectFile(t.path);
      });
      if (t.path === this.selectedFileKey) li.classList.add('selected');
      ul.appendChild(li);
    }
    // 绑定删除按钮
    ul.querySelectorAll('.file-remove').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        this.removeFile(btn.dataset.path);
      });
    });
    this.updateFileCount();
  },

  selectFile(path) {
    this.selectedFileKey = path;
    this.renderFileList();
    this.renderCompare(path);
    // v4.1.5 (🟠 修复 8): 复制/导出按钮仅在"校对完成 + 非处理中"时 enabled.
    // 流式时 disabled, 避免用户复制到一半的 partial.
    const copyBtn = document.getElementById('btn-copy-result');
    const exportBtn = document.getElementById('btn-export-result');
    const toggleDiffBtn = document.getElementById('btn-toggle-diff-mode');
    const t = this.tasks.find(t => t.path === path);
    const hasResult = !!(t && t.corrected && !this.isProcessing);
    if (copyBtn) copyBtn.disabled = !hasResult;
    if (exportBtn) exportBtn.disabled = !hasResult;
    // toggle 按钮: 仅在已校对完成时 enabled (流式时 disabled, 切到 full 也得有完整结果)
    if (toggleDiffBtn) toggleDiffBtn.disabled = !(t && t.corrected);
  },

  // ====== 校对流程 ======
  async startProofread() {
    const paths = this.tasks.filter(t => t.status === 'pending' || t.status === 'failed')
                            .map(t => t.path);
    if (paths.length === 0) {
      this.appendLog('[提示] 没有待处理文件');
      return;
    }
    // v4.1 (I5): 主页不再有 chunking select, 直接读 config (从设置页同步过来)
    const preset = this.config.chunking_preset || 'balanced';
    this.isProcessing = true;
    // v4.1.5: 为每个待处理文件显式初始化 renderState (避免 scheduleRender
    // 第一次跑时还要 init, 不严格必要但语义清晰, 跟 plan v2 §7 一致)
    for (const p of paths) {
      this._initRenderState(p);
    }
    // v4.1 (I6): 60 秒 watchdog, 防止后端异常时 isProcessing 永远卡 true.
    // 取消时 watchdog 也清掉.
    this._clearProofreadWatchdog();
    this._proofreadWatchdog = setTimeout(() => {
      if (this.isProcessing) {
        this.isProcessing = false;
        this.setProcessingButtons(false);
        this.appendLog('[警告] 60秒无响应, 自动复位 (可能后端异常)');
        this.renderFileList();
      }
    }, 60000);
    for (const p of paths) {
      const t = this.tasks.find(t => t.path === p);
      if (t) t.status = 'running';
    }
    this.renderFileList();
    this.updateFileCount();
    this.setProcessingButtons(true);
    this.appendLog(`[启动] ${paths.length} 个文件, 模式=${this.config.prompt_mode || 'strict'}, 分块=${preset}`);
    try {
      const result = await window.pywebview.api.start_proofread(
        paths,
        this.config.prompt_mode || 'strict',
        this.config.custom_prompt || '',
        preset
      );
      this.appendLog(`[Task] ${JSON.stringify(result)}`);
    } catch (e) {
      this.appendLog('[错误] start_proofread 失败: ' + e);
      this._clearProofreadWatchdog();
      this.isProcessing = false;
      this.setProcessingButtons(false);
      this.renderFileList();
    }
  },

  // v4.1 (I6): watchdog 清理
  _clearProofreadWatchdog() {
    if (this._proofreadWatchdog) {
      clearTimeout(this._proofreadWatchdog);
      this._proofreadWatchdog = null;
    }
  },

  async pauseProofread() {
    try {
      const r = await window.pywebview.api.pause_proofread();
      this.appendLog(`[${r.action || 'pause'}] ${r.ok ? '已暂停' : '失败'}`);
      if (r.ok) this.setProcessingButtons(true, true); // paused
    } catch (e) {
      this.appendLog('[错误] pause 失败: ' + e);
    }
  },

  async resumeProofread() {
    try {
      const r = await window.pywebview.api.resume_proofread();
      this.appendLog(`[${r.action || 'resume'}] ${r.ok ? '已恢复' : '失败'}`);
      if (r.ok) this.setProcessingButtons(true, false);
    } catch (e) {
      this.appendLog('[错误] resume 失败: ' + e);
    }
  },

  async cancelProofread() {
    try {
      const r = await window.pywebview.api.cancel_proofread();
      this.appendLog(`[${r.action || 'cancel'}] ${r.ok ? '已取消' : '失败'}`);
    } catch (e) {
      this.appendLog('[错误] cancel 失败: ' + e);
    }
  },

  setProcessingButtons(processing, paused = false) {
    const start = document.getElementById('btn-start');
    const pause = document.getElementById('btn-pause');
    const resume = document.getElementById('btn-resume');
    const cancel = document.getElementById('btn-cancel');
    const addBtn = document.getElementById('btn-add-files');
    const clearBtn = document.getElementById('btn-clear-files');
    if (start) start.disabled = processing;
    if (addBtn) addBtn.disabled = processing;
    if (clearBtn) clearBtn.disabled = processing || this.tasks.length === 0;
    if (pause) pause.disabled = !processing || paused;
    if (resume) resume.disabled = !processing || !paused;
    if (cancel) cancel.disabled = !processing;
  },

  // ====== 流式回调 ======
  // v4.1.5: 流式 partial 用 scheduleRender (RAF) 合并, 避免每 token 都触发 innerHTML 重排.
  // 跟 v4.1.3 RAF 节流思路一致, 但语义不同 — v4.1.3 是节流, v4.1.5 是 D 算法增量入口.
  updateStream(fileKey, partial) {
    this.streamingContent[fileKey] = partial;
    const t = this.tasks.find(t => t.path === fileKey);
    if (t) t.corrected = partial;
    // 无论是否选中, 都更新 renderState (切回时能从 lastPartialLen 续)
    this.scheduleRender(fileKey);
  },

  markFileRunning(fileKey) {
    const t = this.tasks.find(t => t.path === fileKey);
    if (t) {
      t.status = 'running';
      this.renderFileList();
      // v4.1.5: handleFileStart 已在 dispatch 阶段同步设了 t.original
      // 如果当前选中的就是这个文件, 重渲染 compare (左栏立刻显示原文)
      if (this.selectedFileKey === fileKey) {
        this.renderCompare(fileKey);
      }
    }
  },

  markFileDone(fileKey) {
    const t = this.tasks.find(t => t.path === fileKey);
    if (t) {
      t.status = 'completed';
      this.renderFileList();
      // v4.1.5: 文件完成, 启用复制/导出/toggle 按钮
      if (this.selectedFileKey === fileKey) {
        this.renderCompare(fileKey);
        this.selectFile(fileKey);
      }
    }
  },

  updateStats(stats) {
    const el = document.getElementById('progress-stats');
    if (!el) return;
    const pct = stats.total_files > 0
      ? Math.round((stats.completed_files / stats.total_files) * 100)
      : 0;
    const etaText = stats.eta > 0 ? ` | 剩余 ~${stats.eta.toFixed(0)}s` : '';
    el.textContent = `${pct}% | ${stats.completed_files}/${stats.total_files} 文件 | ${stats.total_tokens} tokens | ${stats.speed.toFixed(1)} t/s${etaText}`;
    const fill = document.getElementById('progress-fill');
    if (fill) fill.style.width = pct + '%';
    // ETA
    const etaEl = document.getElementById('progress-eta');
    if (etaEl) {
      etaEl.textContent = stats.eta > 0 ? `预计剩余: ${stats.eta.toFixed(0)} 秒` : '';
    }
  },

  onTaskComplete(results) {
    this._clearProofreadWatchdog();
    this.isProcessing = false;
    this.setProcessingButtons(false);
    // v4.1 (I6): 后端异常时 (run() 顶层 try/except) 会推 {"error": "..."}
    if (results && results.error) {
      this.appendLog('[错误] 后端任务异常: ' + results.error);
      this.renderFileList();
      return;
    }
    this.appendLog('[完成] ' + JSON.stringify(Object.keys(results || {})));
    if (results) {
      for (const [key, info] of Object.entries(results)) {
        const t = this.tasks.find(t => t.path === key);
        if (t && info.result) {
          t.original = info.result.original || '';
          t.corrected = info.result.corrected || '';
          t.status = info.status || 'completed';
          if (info.result.error) t.error = info.result.error;
        }
      }
      this.renderFileList();
    }
  },

  // ====== Diff 渲染 (v4.1.5: D 方案 incremental) ======
  // 详细: PLAN-v4.1.5-ui-redesign.md §3 / §7
  //
  // renderState 生命周期:
  // - 初始化: startProofread (initRenderState) + updateStream (隐式 init)
  // - 清理: removeFile (delete this.renderState[path])
  // - 重置: clearFiles (this.renderState = {})
  // - 模式切: toggleDiffMode (state.mode='full'/'streaming')
  // - 错误态: renderCompare 检查 t.error, 显示 error-mark
  //
  // D 算法: 纯前缀匹配 commonPrefixLength, 不用 diff_main
  // - 增量: partial 增量 = partial.slice(state.lastPartialLen)
  // - 倒退保护: if (partial.length < state.lastPartialLen) reset
  // - 跨 chunk 边界: 接受为 ins 接缝 (新字符全标 ins)

  // 工具: 计算 a, b 前缀相同字符数 (从 0 开始)
  _commonPrefixLength(a, b) {
    let i = 0;
    const min = Math.min(a.length, b.length);
    while (i < min && a[i] === b[i]) i++;
    return i;
  },

  // 显式初始化 renderState (按 plan v2 §3.1)
  _initRenderState(fileKey) {
    if (!this.renderState[fileKey]) {
      this.renderState[fileKey] = {
        lastPartialLen: 0,
        renderedHTML: '',
        renderedOriginalLen: 0,
        rafScheduled: false,
        mode: 'streaming',  // 显式默认 'streaming', 避免 || 兜底混乱
      };
    }
    return this.renderState[fileKey];
  },

  // RAF 调度: 多次 updateStream 合并到下一帧, 避免每 token 都触发 innerHTML
  scheduleRender(fileKey) {
    const state = this._initRenderState(fileKey);
    if (state.rafScheduled) return;
    state.rafScheduled = true;
    requestAnimationFrame(() => {
      state.rafScheduled = false;
      this.renderCompare(fileKey);
    });
  },

  // 核心渲染: 左 compare-original (静态原文字), 右 compare-revised (流式/全量)
  renderCompare(fileKey) {
    const originalEl = document.getElementById('compare-original');
    const revisedEl = document.getElementById('compare-revised');
    if (!originalEl || !revisedEl) return;

    // 1. 未选文件: 显示空状态
    if (!fileKey) {
      originalEl.innerHTML = '<div class="type-emptystate">选择文件查看原文</div>';
      revisedEl.innerHTML = '<div class="type-emptystate">流式输出将显示在这里</div>';
      return;
    }

    const t = this.tasks.find(t => t.path === fileKey);
    if (!t) {
      originalEl.innerHTML = '<div class="type-emptystate">选择文件查看原文</div>';
      revisedEl.innerHTML = '<div class="type-emptystate">流式输出将显示在这里</div>';
      return;
    }

    // 2. (🟠 修复 9): 错误态 fallback — 右栏显示 error-mark
    if (t.error) {
      originalEl.textContent = t.original || '';
      revisedEl.innerHTML = `<div class="error-mark">校对失败: ${this.escapeHtml(t.error)}</div>`;
      return;
    }

    // 3. 左栏原文字: t.original 在 handleFileStart / onTaskComplete 时已设
    //    大文件 original_truncated 场景: t.original 为空, 异步调 read_file 读
    if (t.original) {
      originalEl.textContent = t.original;
    } else if (t._originalTruncated) {
      // 大文件未推 original: 异步 read_file 补上
      originalEl.innerHTML = '<div class="type-emptystate">原文较大, 正在加载...</div>';
      this._loadOriginalFallback(fileKey);
    } else {
      originalEl.innerHTML = '<div class="type-emptystate">流式开始时显示原文</div>';
    }

    // 4. 右栏: D 方案 (流式) 或 diff_main (全量)
    const state = this._initRenderState(fileKey);
    const partial = this.streamingContent[fileKey] || t.corrected || '';

    // 4a. 全量模式: 用户点"查看完整 diff"后, 用 diff_main 重渲染
    if (state.mode === 'full') {
      if (!this.dmp || !t.original) {
        revisedEl.textContent = partial;
        return;
      }
      const diff = this.dmp.diff_main(t.original, partial);
      this.dmp.diff_cleanupSemantic(diff);
      revisedEl.innerHTML = diff.map(([op, text]) => {
        const safe = this.escapeHtml(text);
        if (op === 1)  return `<ins>${safe}</ins>`;
        if (op === -1) return `<del>${safe}</del>`;
        return `<span>${safe}</span>`;
      }).join('');
      return;
    }

    // 4b. 流式模式: D 方案 incremental
    // 空 partial: 重置 lastPartialLen
    if (!partial) {
      revisedEl.textContent = '';
      state.lastPartialLen = 0;
      return;
    }

    // (🔴 修复 2): partial 倒退保护 (retry / cancel / resume 场景)
    if (partial.length < state.lastPartialLen) {
      state.lastPartialLen = 0;
      state.renderedHTML = '';
      state.renderedOriginalLen = 0;
    }
    // 无新内容
    if (partial.length === state.lastPartialLen) return;

    // 增量: 只算新字符
    const newChars = partial.slice(state.lastPartialLen);
    const prevRenderedOriginal = state.renderedOriginalLen;
    const newOriginalSlice = (t.original || '').slice(
      prevRenderedOriginal,
      prevRenderedOriginal + newChars.length
    );
    const matches = this._commonPrefixLength(newOriginalSlice, newChars);
    const inserted = newChars.slice(matches);

    if (matches > 0) {
      state.renderedHTML += `<span>${this.escapeHtml(newOriginalSlice.slice(0, matches))}</span>`;
    }
    if (inserted) {
      state.renderedHTML += `<ins>${this.escapeHtml(inserted)}</ins>`;
    }

    revisedEl.innerHTML = state.renderedHTML;
    state.lastPartialLen = partial.length;
    state.renderedOriginalLen = prevRenderedOriginal + newOriginalSlice.length;
  },

  // 大文件 fallback: onFileStart 没推 original 时, 异步调 read_file 补
  async _loadOriginalFallback(fileKey) {
    const t = this.tasks.find(t => t.path === fileKey);
    if (!t || t.original || !t._originalTruncated) return;
    // 防止重复请求
    if (t._loadingOriginal) return;
    t._loadingOriginal = true;
    try {
      const text = await window.pywebview.api.read_file(fileKey);
      t._loadingOriginal = false;
      if (t.path === this.selectedFileKey && !t.original) {
        t.original = text || '';
        this.renderCompare(fileKey);
      }
    } catch (e) {
      t._loadingOriginal = false;
      this.appendLog('[提示] 加载原文字失败: ' + e);
    }
  },

  // v4.1.5: 切换流式 / 全量 diff 模式
  toggleDiffMode() {
    const key = this.selectedFileKey;
    if (!key) return;
    const state = this._initRenderState(key);
    const t = this.tasks.find(t => t.path === key);
    if (!t || !t.corrected) return;  // 没结果不让切
    const btn = document.getElementById('btn-toggle-diff-mode');
    if (state.mode === 'streaming') {
      state.mode = 'full';
      if (btn) btn.textContent = '查看流式 diff';
    } else {
      state.mode = 'streaming';
      // 切回流式: 重置累积, 重新从 partial 增量
      state.lastPartialLen = 0;
      state.renderedHTML = '';
      state.renderedOriginalLen = 0;
      if (btn) btn.textContent = '查看完整 diff';
    }
    this.renderCompare(key);
  },

  // v4.1.5 (🔴 修复 1): 后端 onFileStart 推送 {file_key, original, original_truncated}
  // 同步设 t.original, 让左栏原文字在流式开始就有数据
  handleFileStart(data) {
    if (!data || !data.file_key) return;
    const t = this.tasks.find(t => t.path === data.file_key);
    if (!t) return;
    // original 可能是 null (大文件) 或 string
    t.original = data.original || '';
    t._originalTruncated = !!data.original_truncated;
  },

  // ====== Diff 操作 ======
  async copyResult() {
    if (!this.selectedFileKey) return;
    const t = this.tasks.find(t => t.path === this.selectedFileKey);
    const text = t ? (t.corrected || this.streamingContent[this.selectedFileKey] || '') : '';
    if (!text) return;
    // v4.1.3 (I1): 优先用 Python Win32 剪贴板 (WebView2 里成功率 100%),
    // 失败再 fallback 到 navigator.clipboard.writeText
    if (window.pywebview && window.pywebview.api && window.pywebview.api.copy_to_clipboard) {
      try {
        const r = await window.pywebview.api.copy_to_clipboard(text);
        if (r && r.ok) {
          this.appendLog(`[复制] 已复制到剪贴板 (${r.length} 字符)`);
          return;
        }
        this.appendLog(`[提示] 系统剪贴板失败 (${r && r.error}), 尝试浏览器 API`);
      } catch (e) {
        this.appendLog('[提示] 桥接复制异常, 尝试浏览器 API: ' + e);
      }
    }
    // fallback: navigator.clipboard.writeText
    try {
      await navigator.clipboard.writeText(text);
      this.appendLog('[复制] 已复制到剪贴板 (浏览器 API)');
    } catch (e) {
      this.appendLog('[错误] 复制失败: ' + e);
    }
  },

  async exportResult() {
    if (!this.selectedFileKey) return;
    const t = this.tasks.find(t => t.path === this.selectedFileKey);
    if (!t) return;
    const text = t.corrected || this.streamingContent[this.selectedFileKey] || '';
    if (!text) return;
    try {
      // v4.1.4: 弹原生保存对话框 (默认位置=源文件目录, 默认文件名=<stem>-<YYMMDD>-<HHMMSS>.<ext>)
      const r = await window.pywebview.api.export_result(this.selectedFileKey, text, 'txt');
      if (r.ok) {
        this.appendLog(`[导出] 已保存: ${r.path}`);
      } else if (r.cancelled) {
        this.appendLog('[导出] 用户取消保存');
      } else {
        this.appendLog(`[错误] 导出失败: ${r.error}`);
      }
    } catch (e) {
      this.appendLog('[错误] 导出失败: ' + e);
    }
  },

  // ====== 日志 ======
  appendLog(msg) {
    const el = document.getElementById('log-output');
    if (!el) return;
    const time = new Date().toLocaleTimeString('zh-CN', {hour12: false});
    el.textContent += `[${time}] ${msg}\n`;
    el.scrollTop = el.scrollHeight;
  },

  // ====== 设置: 防抖保存 + URL 校验 ======
  validateApiBase() {
    const url = this.getVal('cfg-api-base');
    const input = document.getElementById('cfg-api-base');
    const hint = document.getElementById('hint-api-base');
    const valid = url === '' || /^https?:\/\/[^\s]+$/.test(url);
    this.urlValid = valid;
    if (input) {
      input.classList.toggle('input-invalid', !valid);
    }
    if (hint) {
      hint.textContent = valid ? '需为 http:// 或 https:// 开头' : 'URL 格式无效';
      hint.classList.toggle('hint-invalid', !valid);
    }
    this.updateSaveButton();
  },

  updateSaveButton() {
    const btn = document.getElementById('btn-save-config');
    if (btn) btn.disabled = !this.urlValid;
  },

  markConfigDirty() {
    this.configDirty = true;
    if (this.configSaveTimer) clearTimeout(this.configSaveTimer);
    this.configSaveTimer = setTimeout(() => {
      this.autoSaveConfig();
    }, 500);
  },

  async autoSaveConfig() {
    if (!this.configDirty) return;
    this.configDirty = false;
    await this.saveConfig({silent: true});
  },

  async saveConfigNow() {
    if (!this.urlValid) {
      this.appendLog('[错误] URL 格式无效,无法保存');
      return;
    }
    this.configDirty = false;
    if (this.configSaveTimer) clearTimeout(this.configSaveTimer);
    await this.saveConfig({silent: false});
    // v4.1.6 (P4): 显式保存按钮文案变 "✓ 已保存" 2 秒, 给用户一个明确视觉反馈.
    const btn = document.getElementById('btn-save-config');
    if (btn && !btn.disabled) {
      const orig = btn.dataset.origLabel || btn.textContent;
      if (!btn.dataset.origLabel) btn.dataset.origLabel = orig;
      btn.textContent = '✓ 已保存';
      btn.disabled = true;
      if (btn._savedTimer) clearTimeout(btn._savedTimer);
      btn._savedTimer = setTimeout(() => {
        btn.textContent = btn.dataset.origLabel;
        btn.disabled = false;
      }, 2000);
    }
  },

  // v4.1.6 (P1+P2): 抽 helper, 11 字段从 DOM 一次性收集.
  // 复用场景: saveConfig (异步) + beforeunload (同步 fire-and-forget).
  _collectAllConfig() {
    return {
      api_base:           this.getVal('cfg-api-base'),
      api_key:            this.getVal('cfg-api-key'),
      model:              this.getVal('cfg-model'),
      prompt_mode:        this.getVal('cfg-prompt-mode'),
      temperature:        parseFloat(this.getVal('cfg-temperature') || '0.1'),
      concurrency:        parseInt(this.getVal('cfg-concurrency') || '2', 10),
      max_retries:        parseInt(this.getVal('cfg-max-retries') || '3', 10),
      timeout:            parseInt(this.getVal('cfg-timeout') || '120', 10),
      chunking_preset:    this.getVal('cfg-chunking-preset'),
      context_max_chars:  parseInt(this.getVal('cfg-context-max-chars') || '800', 10),
      context_max_chunks: parseInt(this.getVal('cfg-context-max-chunks') || '2', 10),
      custom_prompt:      this.getVal('cfg-custom-prompt'),
    };
  },

  async saveConfig(opts = {}) {
    const updates = this._collectAllConfig();
    const entries = Object.entries(updates);
    // v4.1.6 (P1): 串行 await 11 次 bridge 累积延迟可能错过 500ms 防抖,
    // 改 Promise.all 并行, 11 个 set_config 并发飞过去. 任何 reject 立即 log.
    const setResults = await Promise.all(entries.map(([k, v]) =>
      window.pywebview.api.set_config(k, v)
        .then(() => null)
        .catch(e => `${k}=${e}`)
    ));
    const setFails = setResults.filter(Boolean);
    if (setFails.length) {
      this.appendLog(`[错误] set_config 失败 (${setFails.length}/${entries.length}): ${setFails.join(', ')}`);
    }
    try {
      // v4.1.6 (P3): save_config 返回 {ok, error}, 失败时不静默吞错.
      const r = await window.pywebview.api.save_config();
      if (!r || !r.ok) {
        this.appendLog(`[错误] save_config: ${(r && r.error) || '返回无 ok 字段'}`);
        return;
      }
      this.config = await window.pywebview.api.get_config();
      // v4.1 (I5): config 变了, 主页 chunking 只读 label 也要同步刷新
      this.renderChunkingDisplay();
      // v4.1.6 (P5): 始终显示保存反馈 (silent 模式也打, 用户知道后台已经落了盘).
      this.appendLog(`[设置] 已保存 (${entries.length} 字段)`);
    } catch (e) {
      this.appendLog('[错误] save_config 异常: ' + e);
    }
  },

  toggleKeyVisibility() {
    const input = document.getElementById('cfg-api-key');
    if (input) input.type = input.type === 'password' ? 'text' : 'password';
  },

  async fetchModels() {
    const base = this.getVal('cfg-api-base');
    const key = this.getVal('cfg-api-key');
    this.appendLog('[测试] 拉取模型列表...');
    // v4.1 (I3): 改异步, 立即拿 task_id, 后端跑 requests.get, 完成推 onFetchModelsComplete
    try {
      const r = await window.pywebview.api.fetch_models(base, key);
      if (r && r.ok) {
        this._pendingFetchTaskId = r.task_id;
        this.appendLog(`[测试] 后台拉取中 (task_id=${r.task_id})...`);
      } else {
        this.appendLog(`[错误] 启动拉取失败: ${r.error || '未知'}`);
      }
    } catch (e) {
      this.appendLog('[错误] fetch_models 失败: ' + e);
    }
  },

  // v4.1 (I3): fetch_models / test_connection 完成后回调
  handleFetchModelsComplete(data) {
    if (!data) return;
    // 仅处理最新一次拉取 (防止旧 task 完成覆盖新结果)
    if (this._pendingFetchTaskId && data.task_id !== this._pendingFetchTaskId) {
      // 但 test_connection 也要走同一通道, 记录 taskId 路由
    }
    const isTest = this._pendingTestTaskId === data.task_id;
    if (isTest) this._pendingTestTaskId = null;
    else if (this._pendingFetchTaskId === data.task_id) this._pendingFetchTaskId = null;
    if (data.ok) {
      if (isTest) {
        this.appendLog(`[测试] 连接成功, 发现 ${data.count} 个模型`);
        return;
      }
      const sel = document.getElementById('cfg-model-list');
      if (sel) {
        sel.innerHTML = '<option value="">-- 选择模型 --</option>';
        for (const m of (data.models || [])) {
          const opt = document.createElement('option');
          opt.value = m;
          opt.textContent = m;
          sel.appendChild(opt);
        }
        sel.style.display = 'block';
        sel.onchange = () => {
          if (sel.value) {
            this.setVal('cfg-model', sel.value);
            this.markConfigDirty();
          }
        };
      }
      this.appendLog(`[测试] 成功, 发现 ${data.count} 个模型`);
    } else {
      this.appendLog(`[${isTest ? '测试' : '错误'}] 失败: ${data.error}`);
    }
  },

  async testConnection() {
    const base = this.getVal('cfg-api-base');
    const key = this.getVal('cfg-api-key');
    this.appendLog('[测试] 测试连接...');
    // v4.1 (I3): 也走异步, 通过 onFetchModelsComplete 拿到结果
    try {
      const r = await window.pywebview.api.test_connection(base, key);
      if (r && r.ok) {
        this._pendingTestTaskId = r.task_id;
        this.appendLog(`[测试] 后台测试中 (task_id=${r.task_id})...`);
      } else {
        this.appendLog(`[测试] 失败: ${r.error || '未知'}`);
      }
    } catch (e) {
      this.appendLog('[错误] test_connection 失败: ' + e);
    }
  },

  applyTemplate(name) {
    if (!name) return;
    const tpl = this.apiTemplates.find(t => t.name === name);
    if (!tpl) return;
    this.setVal('cfg-api-base', tpl.api_base);
    this.setVal('cfg-model', tpl.model);
    if (tpl.api_key !== undefined) this.setVal('cfg-api-key', tpl.api_key);
    this.validateApiBase();
    this.markConfigDirty();
    this.appendLog(`[模板] 已应用: ${name}`);
  },

  // ====== DeAI 3 步 ======
  async deaiStep1() {
    const text = this.getVal('deai-input');
    if (!text) { this.appendLog('[DeAI] 请先输入文本'); return; }
    this.setDeaiStepUI(1, 'running', '调用 LLM 中...');
    try {
      // v4.1.7: 传 styleCardSlug (可选)
      const taskId = await window.pywebview.api.deai_step1_detect(text, this.deai.styleCardSlug);
      this.deai.step1TaskId = taskId;
    } catch (e) {
      this.setDeaiStepUI(1, 'error', String(e));
    }
  },

  async deaiStep2() {
    const text = this.getVal('deai-input');
    const sample = this.getVal('deai-sample');
    if (!text) return;
    this.setDeaiStepUI(2, 'running', '调用 LLM 中...');
    try {
      // v4.1.7: 传 styleCardSlug (可选), 走 V5 rewrite (9 轴 + 事实骨架)
      const taskId = await window.pywebview.api.deai_step2_rewrite(
        text, sample, this.deai.styleCardSlug
      );
      this.deai.step2TaskId = taskId;
    } catch (e) {
      this.setDeaiStepUI(2, 'error', String(e));
    }
  },

  async deaiStep3() {
    const rewritten = this.getDeaiOutput(2);
    if (!rewritten) return;
    this.setDeaiStepUI(3, 'running', '调用 LLM 中...');
    try {
      // v4.1.7: 传 styleCardSlug (可选), 走 V5 audit (3 维 + 8 轴自评)
      const taskId = await window.pywebview.api.deai_step3_audit(
        rewritten, this.deai.styleCardSlug
      );
      this.deai.step3TaskId = taskId;
    } catch (e) {
      this.setDeaiStepUI(3, 'error', String(e));
    }
  },

  setDeaiStepUI(step, state, statusText) {
    const statusEl = document.getElementById('deai-status-' + step);
    if (statusEl) {
      statusEl.textContent = statusText;
      statusEl.className = 'deai-step-status status-' + state;
    }
    const outEl = document.getElementById('deai-output-' + step);
    if (outEl && state === 'running' && !outEl.textContent) {
      outEl.textContent = '...';
    }
    // 按钮联动
    const btn1 = document.getElementById('btn-deai-step1');
    const btn2 = document.getElementById('btn-deai-step2');
    const btn3 = document.getElementById('btn-deai-step3');
    if (step === 1) {
      if (btn1) btn1.disabled = (state === 'running');
    } else if (step === 2) {
      if (btn1) btn1.disabled = (state === 'running');
      if (btn2) btn2.disabled = (state === 'running');
    } else if (step === 3) {
      if (btn1) btn1.disabled = (state === 'running');
      if (btn2) btn2.disabled = (state === 'running');
      if (btn3) btn3.disabled = (state === 'running');
    }
  },

  handleDeaiStream(data) {
    if (!data || !data.task_id) return;
    // 路由到对应 step 输出框
    if (data.task_id === this.deai.step1TaskId) {
      this.setDeaiOutput(1, data.partial);
      this.setDeaiStepUI(1, 'running', '生成中...');
    } else if (data.task_id === this.deai.step2TaskId) {
      this.setDeaiOutput(2, data.partial);
      this.setDeaiStepUI(2, 'running', '生成中...');
    } else if (data.task_id === this.deai.step3TaskId) {
      this.setDeaiOutput(3, data.partial);
      this.setDeaiStepUI(3, 'running', '生成中...');
    }
  },

  // v4.1.7: 复用 onDeaiStream 路由, 如果 step='distill' 转给 distill handler
  handleDeaiStreamOrDistill(data) {
    if (data && data.step === 'distill') {
      this.handleDeaiDistillStream(data);
    } else {
      this.handleDeaiStream(data);
    }
  },

  // v4.1.7: 蒸馏流式 partial 实时显示 (只显示字符数 + 状态)
  handleDeaiDistillStream(data) {
    const status = document.getElementById('deai-distill-status');
    if (status) {
      status.textContent = `蒸馏中... 已生成 ${data.partial.length} 字符`;
    }
  },

  handleDeaiComplete(data) {
    if (!data || !data.task_id) return;
    // v4.1.7: 蒸馏完成 (step='distill')
    if (data.step === 'distill') {
      const status = document.getElementById('deai-distill-status');
      if (status) {
        status.textContent = `蒸馏完成: ${data.card_chars} 字符 (${data.distilled_at})`;
      }
      const btn = document.getElementById('btn-deai-distill');
      if (btn) btn.disabled = false;
      this.appendLog(`[DeAI] 蒸馏完成: ${data.slug} (${data.card_chars} 字符)`);
      return;
    }
    if (data.task_id === this.deai.step1TaskId) {
      this.deai.step1Done = true;
      this.setDeaiOutput(1, data.result || '');
      this.setDeaiStepUI(1, 'done', '已完成');
      const copyBtn = document.getElementById('btn-deai-copy-1');
      if (copyBtn) copyBtn.disabled = false;
      // 解锁 step 2
      const btn2 = document.getElementById('btn-deai-step2');
      if (btn2) btn2.disabled = false;
      const status2 = document.getElementById('deai-status-2');
      if (status2) { status2.textContent = '可运行'; status2.className = 'deai-step-status status-ready'; }
    } else if (data.task_id === this.deai.step2TaskId) {
      this.deai.step2Done = true;
      this.deai.lastResult = data.result || '';
      this.setDeaiOutput(2, data.result || '');
      this.setDeaiStepUI(2, 'done', '已完成');
      const copyBtn = document.getElementById('btn-deai-copy-2');
      if (copyBtn) copyBtn.disabled = false;
      // 解锁 step 3
      const btn3 = document.getElementById('btn-deai-step3');
      if (btn3) btn3.disabled = false;
      const status3 = document.getElementById('deai-status-3');
      if (status3) { status3.textContent = '可运行'; status3.className = 'deai-step-status status-ready'; }
      // 解锁 export
      const exportBtn = document.getElementById('btn-deai-export');
      if (exportBtn) exportBtn.disabled = false;
    } else if (data.task_id === this.deai.step3TaskId) {
      this.deai.step3Done = true;
      this.setDeaiOutput(3, data.result || '');
      this.setDeaiStepUI(3, 'done', '已完成');
      const copyBtn = document.getElementById('btn-deai-copy-3');
      if (copyBtn) copyBtn.disabled = false;
    }
  },

  handleDeaiError(data) {
    if (!data || !data.task_id) return;
    this.appendLog(`[DeAI 错误] ${data.error}`);
    // v4.1.7: 蒸馏失败
    if (data.step === 'distill') {
      const status = document.getElementById('deai-distill-status');
      if (status) status.textContent = `蒸馏失败: ${data.error}`;
      const btn = document.getElementById('btn-deai-distill');
      if (btn) btn.disabled = false;
      return;
    }
    if (data.task_id === this.deai.step1TaskId) {
      this.setDeaiStepUI(1, 'error', '错误: ' + data.error);
    } else if (data.task_id === this.deai.step2TaskId) {
      this.setDeaiStepUI(2, 'error', '错误: ' + data.error);
    } else if (data.task_id === this.deai.step3TaskId) {
      this.setDeaiStepUI(3, 'error', '错误: ' + data.error);
    }
  },

  setDeaiOutput(step, text) {
    const el = document.getElementById('deai-output-' + step);
    if (el) el.textContent = text;
  },

  getDeaiOutput(step) {
    const el = document.getElementById('deai-output-' + step);
    return el ? el.textContent : '';
  },

  async copyDeaiOutput(step) {
    const text = this.getDeaiOutput(step);
    if (!text) return;
    // v4.1.3 (I1): 同样优先 Python Win32 剪贴板, 失败 fallback
    if (window.pywebview && window.pywebview.api && window.pywebview.api.copy_to_clipboard) {
      try {
        const r = await window.pywebview.api.copy_to_clipboard(text);
        if (r && r.ok) {
          this.appendLog(`[DeAI] 已复制 Step ${step} 结果 (${r.length} 字符)`);
          return;
        }
        this.appendLog(`[提示] 系统剪贴板失败 (${r && r.error}), 尝试浏览器 API`);
      } catch (e) {
        this.appendLog('[提示] 桥接复制异常, 尝试浏览器 API: ' + e);
      }
    }
    try {
      await navigator.clipboard.writeText(text);
      this.appendLog(`[DeAI] 已复制 Step ${step} 结果 (浏览器 API)`);
    } catch (e) {
      this.appendLog('[错误] 复制失败: ' + e);
    }
  },

  async exportDeaiResult() {
    const text = this.deai.lastResult || this.getDeaiOutput(2);
    if (!text) return;
    const fmt = this.getVal('deai-export-fmt') || 'txt';
    try {
      // v4.1.4: 传空 file_path, 后端 export_result 走 DeAI fallback 路径
      // (默认位置 = home/Documents, 默认文件名 = deai_result-YYMMDD-HHMMSS.<ext>)
      // 之前用 'deai_result.xxx' hack 路径会让默认位置指向 cwd, 用户体验差
      const r = await window.pywebview.api.export_result('', text, fmt);
      if (r.ok) {
        this.appendLog(`[DeAI] 已导出: ${r.path}`);
      } else if (r.cancelled) {
        this.appendLog('[DeAI] 用户取消保存');
      } else {
        this.appendLog(`[DeAI 错误] 导出失败: ${r.error}`);
      }
    } catch (e) {
      this.appendLog('[错误] 导出失败: ' + e);
    }
  },

  // ====== v4.1.7 DeAI Step 0 风格 Profile ======
  // 借鉴自 https://github.com/jianshuo/claude-skills (MIT License) 9 轴蒸馏思路
  // 借鉴方式: 思路借鉴, 无代码复制, UI / 文案 / 交互全部项目语言重写
  // Copyright (c) 2026 Jianshuo Wang

  async loadStyleProfiles() {
    try {
      const r = await window.pywebview.api.list_style_profiles();
      this.deai.styleProfiles = r;
      this.renderStyleProfileSelect();
    } catch (e) {
      this.appendLog('[DeAI 错误] 加载风格 profile 失败: ' + e);
    }
  },

  renderStyleProfileSelect() {
    const sel = document.getElementById('deai-style-profile');
    if (!sel) return;
    sel.innerHTML = '<option value="">-- 不选, 用默认 --</option>';
    const optgroupBuiltin = document.createElement('optgroup');
    optgroupBuiltin.label = '预置 (3 套)';
    for (const p of (this.deai.styleProfiles.builtin || [])) {
      const opt = document.createElement('option');
      opt.value = p.key;
      opt.textContent = `${p.name} — ${p.summary}`;
      optgroupBuiltin.appendChild(opt);
    }
    sel.appendChild(optgroupBuiltin);
    if (this.deai.styleProfiles.custom && this.deai.styleProfiles.custom.length > 0) {
      const optgroupCustom = document.createElement('optgroup');
      optgroupCustom.label = '自定义 (蒸馏)';
      for (const p of this.deai.styleProfiles.custom) {
        const opt = document.createElement('option');
        opt.value = p.key;
        const distilled = p.distilled_at ? '已蒸馏' : '未蒸馏';
        opt.textContent = `${p.name} (${p.samples_count} 篇, ${distilled})`;
        optgroupCustom.appendChild(opt);
      }
      sel.appendChild(optgroupCustom);
    }
  },

  async selectStyleProfile(slug) {
    this.deai.styleCardSlug = slug || '';
    const info = document.getElementById('deai-profile-info');
    const btnAdd = document.getElementById('btn-deai-add-sample');
    const btnDistill = document.getElementById('btn-deai-distill');
    if (!slug) {
      if (info) info.textContent = '未选 profile (用默认 V5 prompt)';
      if (btnAdd) btnAdd.disabled = true;
      if (btnDistill) btnDistill.disabled = true;
      return;
    }
    // 找 profile 元信息
    const all = [
      ...(this.deai.styleProfiles.builtin || []),
      ...(this.deai.styleProfiles.custom || []),
    ];
    const p = all.find(x => x.key === slug);
    if (p) {
      if (info) {
        if (p.abstract) {
          info.textContent = `已选: ${p.name} (预置, ${p.summary})`;
        } else {
          const distilled = p.distilled_at ? '已蒸馏' : '未蒸馏';
          info.textContent = `已选: ${p.name} (${p.samples_count} 篇, ${distilled})`;
        }
      }
    }
    // builtin 不允许加样本/蒸馏
    const isBuiltin = (this.deai.styleProfiles.builtin || []).some(x => x.key === slug);
    if (isBuiltin) {
      if (btnAdd) btnAdd.disabled = true;
      if (btnDistill) btnDistill.disabled = true;
    } else {
      if (btnAdd) btnAdd.disabled = false;
      // 蒸馏条件: samples >= 3 (后端强制, 前端做提示)
      if (btnDistill) {
        const samples = p ? (p.samples_count || 0) : 0;
        btnDistill.disabled = samples < 3;
        if (samples < 3) {
          if (info) info.textContent += ` (还需 ${3 - samples} 篇才能蒸馏)`;
        }
      }
    }
  },

  async createStyleProfile() {
    const slug = this.getVal('deai-new-profile-slug').trim();
    const name = this.getVal('deai-new-profile-name').trim();
    if (!slug) { this.appendLog('[DeAI] 请输入 slug'); return; }
    if (!name) { this.appendLog('[DeAI] 请输入显示名'); return; }
    try {
      const r = await window.pywebview.api.create_style_profile(slug, name, '');
      if (r.ok) {
        this.appendLog(`[DeAI] 已创建 profile: ${slug}`);
        this.setVal('deai-new-profile-slug', '');
        this.setVal('deai-new-profile-name', '');
        await this.loadStyleProfiles();
        // 自动选上
        const sel = document.getElementById('deai-style-profile');
        if (sel) { sel.value = slug; this.selectStyleProfile(slug); }
      } else {
        this.appendLog(`[DeAI 错误] 创建失败: ${r.error}`);
      }
    } catch (e) {
      this.appendLog('[DeAI 错误] create_style_profile: ' + e);
    }
  },

  async addSampleToProfile() {
    const slug = this.deai.styleCardSlug;
    if (!slug) { this.appendLog('[DeAI] 请先选定 custom profile'); return; }
    const content = this.getVal('deai-sample-content').trim();
    if (!content) { this.appendLog('[DeAI] 范文内容不能为空'); return; }
    try {
      const r = await window.pywebview.api.add_sample_to_profile(slug, content, '');
      if (r.ok) {
        this.appendLog(`[DeAI] 已加范文 (${slug}): ${r.filename} (累计 ${r.samples_count} 篇)`);
        this.setVal('deai-sample-content', '');
        await this.loadStyleProfiles();
        await this.selectStyleProfile(slug);
      } else {
        this.appendLog(`[DeAI 错误] 加范文失败: ${r.error}`);
      }
    } catch (e) {
      this.appendLog('[DeAI 错误] add_sample_to_profile: ' + e);
    }
  },

  async distillStyleProfile() {
    const slug = this.deai.styleCardSlug;
    if (!slug) { this.appendLog('[DeAI] 请先选定 custom profile'); return; }
    const status = document.getElementById('deai-distill-status');
    const btn = document.getElementById('btn-deai-distill');
    if (status) status.textContent = '蒸馏中...';
    if (btn) btn.disabled = true;
    try {
      const taskId = await window.pywebview.api.distill_style_profile(slug);
      this.deai.distillTaskId = taskId;
      this.appendLog(`[DeAI] 蒸馏任务启动: ${taskId}`);
    } catch (e) {
      this.appendLog('[DeAI 错误] distill_style_profile: ' + e);
      if (status) status.textContent = '蒸馏启动失败: ' + e;
      if (btn) btn.disabled = false;
    }
  },

  // ====== 工具 ======
  escapeHtml(s) {
    if (s === undefined || s === null) return '';
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  },
};

// 暴露给 Python 端 evaluate_js 调用
window.app = App;

// v4.1 (AB1): pywebview 6.x 在 pywebviewready 事件才注入 window.pywebview.api。
// 之前的 DOMContentLoaded 会早于 pywebviewready, 调 get_config 必定报 undefined。
// 修法: 检测 window.pywebview 是否已注入, 已注入直接 init; 否则监听 pywebviewready。
function _bootstrap_app() {
  if (window.pywebview && window.pywebview.api) {
    App.init();
  } else {
    // 一次监听, pywebviewready 触发后立即 init
    window.addEventListener('pywebviewready', () => App.init(), { once: true });
    // 兜底: 5 秒后还没就绪, 提示用户 (避免白屏)
    setTimeout(() => {
      if (!window.pywebview || !window.pywebview.api) {
        const log = document.getElementById('log-output');
        if (log) {
          log.textContent += '[错误] pywebview API 5 秒内未就绪, 请检查 WebView2 Runtime 是否安装\n';
        }
        console.error('pywebviewready 5s timeout, window.pywebview.api is undefined');
      }
    }, 5000);
  }
}

// DOMContentLoaded 仍然比 pywebviewready 早, 先把 bootstrap 注册好。
// pywebviewready 触发时 DOM 通常已就绪, 上面 _bootstrap_app 自己处理。
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', _bootstrap_app);
} else {
  _bootstrap_app();
}
