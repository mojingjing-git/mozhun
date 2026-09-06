// 墨准 v4.1.8 前端逻辑 (Win11 Fluent 2 完整重构, 业务逻辑保留 v4.1.5)
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
    running1: false,   // v4.3.0: 步骤运行中 (按钮=取消)
    running2: false,
    running3: false,
    step1File: null,   // v4.3.0: 超长结果落盘路径 (复制/导出走后端直读)
    step2File: null,
    step3File: null,
    lastResult: '',
    // v4.1.7: 风格 Profile 状态
    styleCardSlug: '',  // 当前选定的 profile (空 = 不选)
    styleProfiles: { builtin: [], custom: [] },
    distillTaskId: null,  // 当前蒸馏 task
    distillRunning: false,  // v4.3.1 (UX #13): 蒸馏运行中 (按钮=取消, 同 3 步工作流)
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
    this.appendLog('[就绪] v4.4.0 pywebview 前端已加载');
    // v4.1.7: 加载风格 profile 列表 (异步, 不阻塞 init)
    this.loadStyleProfiles();
    // v4.1.9 (S2.3 个人原则): 恢复持久化主题 (auto/light/dark)
    this.applyTheme(this.config.ui_theme || 'auto');
    // v4.4.0: 恢复持久化界面皮肤 (fluent / ink 水墨) — 与主题轴正交
    this.applySkin(this.config.ui_skin || 'fluent');
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

  // ====== 主题 (v4.1.9: S2.3 个人原则 - 主题持久化到 config) ======
  applyTheme(value) {
    // auto 模式: 删除 data-theme, 让 @media (prefers-color-scheme) 生效
    if (value === 'light' || value === 'dark') {
      document.documentElement.dataset.theme = value;
    } else {
      value = 'auto';
      delete document.documentElement.dataset.theme;
    }
    // 同步设置页三态按钮 active / aria-selected
    const switcher = document.getElementById('theme-switcher');
    if (switcher) {
      const buttons = switcher.querySelectorAll('button[data-theme-value]');
      buttons.forEach(b => {
        const isActive = b.dataset.themeValue === value;
        b.classList.toggle('active', isActive);
        b.setAttribute('aria-selected', isActive ? 'true' : 'false');
      });
    }
  },

  // 持久化主题 (切换时调用): 写 config + 落盘, 重启后恢复
  _persistTheme(value) {
    if (!(window.pywebview && window.pywebview.api)) return;
    try {
      window.pywebview.api.set_config('ui_theme', value)
        .then(() => window.pywebview.api.save_config())
        .catch(e => console.error('主题持久化失败:', e));
    } catch (e) { /* pywebview 未就绪, 静默 */ }
  },

  // ====== 界面皮肤 (v4.4.0: fluent=Win11 Fluent 2 / ink=水墨宣纸) ======
  // 与主题轴 (auto/light/dark) 正交: data-skin 与 data-theme 独立写 documentElement,
  // CSS 层叠见 style.css「水墨皮肤」段的特异性验算注释
  applySkin(value) {
    if (value === 'ink') {
      document.documentElement.dataset.skin = 'ink';
    } else {
      value = 'fluent';
      delete document.documentElement.dataset.skin;
    }
    // 同步设置页按钮 active / aria-selected (与 theme-switcher 同构)
    const switcher = document.getElementById('skin-switcher');
    if (switcher) {
      const buttons = switcher.querySelectorAll('button[data-skin-value]');
      buttons.forEach(b => {
        const isActive = b.dataset.skinValue === value;
        b.classList.toggle('active', isActive);
        b.setAttribute('aria-selected', isActive ? 'true' : 'false');
      });
    }
  },

  // 持久化皮肤 (切换时调用): 写 config + 落盘, 重启后恢复
  _persistSkin(value) {
    if (!(window.pywebview && window.pywebview.api)) return;
    try {
      window.pywebview.api.set_config('ui_skin', value)
        .then(() => window.pywebview.api.save_config())
        .catch(e => console.error('皮肤持久化失败:', e));
    } catch (e) { /* pywebview 未就绪, 静默 */ }
  },

  // ====== ContentDialog (v4.1.9, WinUI 3 S3.4.4: Smoke + ContentDialog) ======
  // 替代原生 confirm() — Promise 化: resolve(true)=主按钮, false=次按钮/Esc/点遮罩
  showConfirmDialog(opts) {
    // v4.3.0: 支持 closeText 第三命令按钮 (WinUI 3 ContentDialog 三命令模式)
    // 返回: true=主按钮, 'close'=第三按钮, false=次按钮/Esc/点遮罩
    const {title, body, primaryText = '确定', secondaryText = '取消',
           closeText = '', icon = 'warning', danger = false} = opts || {};
    const root = document.getElementById('dialog-root');
    if (!root) return Promise.resolve(false);
    const titleEl = document.getElementById('dialog-title-text');
    const bodyEl = document.getElementById('dialog-body-text');
    const iconEl = document.getElementById('dialog-icon');
    const btnP = document.getElementById('dialog-btn-primary');
    const btnS = document.getElementById('dialog-btn-secondary');
    const btnC = document.getElementById('dialog-btn-close');
    if (!titleEl || !btnP || !btnS) return Promise.resolve(false);
    titleEl.textContent = title || '';
    bodyEl.textContent = body || '';
    btnP.textContent = primaryText;
    btnS.textContent = secondaryText;
    if (btnC) {
      btnC.hidden = !closeText;
      btnC.textContent = closeText || '';
    }
    iconEl.dataset.icon = icon;
    iconEl.className = 'nav-icon' + (danger ? ' icon-error' : (icon === 'info' ? ' icon-info' : ''));
    btnP.className = 'dialog-primary' + (danger ? ' dialog-danger' : '');
    root.hidden = false;
    btnP.focus();
    return new Promise((resolve) => {
      const close = (result) => {
        root.hidden = true;
        document.removeEventListener('keydown', onKey, true);
        resolve(result);
      };
      const onKey = (e) => {
        if (e.key === 'Escape') { e.stopPropagation(); close(false); }
        else if (e.key === 'Enter') { e.stopPropagation(); close(true); }
      };
      btnP.onclick = () => close(true);
      btnS.onclick = () => close(false);
      if (btnC) btnC.onclick = () => close('close');
      root.querySelector('.dialog-smoke').onclick = () => close(false);
      document.addEventListener('keydown', onKey, true);
    });
  },

  // ====== 全局 Toast (v4.3.1, UX 审查 #1) ======
  // 背景: 全应用此前只有校对页日志区一个反馈通道, 6/7 页面上的操作没有回音.
  // 语义: 右下角非模态轻提示, 与 ContentDialog (模态确认) 互补 —
  // appendLog 保留日志语义, 跨页操作结果一律补 toast 保证"视线内有回音".
  showToast(msg, type = 'info', duration) {
    const root = document.getElementById('toast-root');
    if (!root) return;
    // 类型守卫: 只接受 success/error/info, 未知类型落 info
    const cls = ['success', 'error', 'info'].includes(type) ? type : 'info';
    // 时长: error 5s (留时间读原因), 其余 3s; 显式 duration 参数优先
    const ms = typeof duration === 'number' ? duration : (cls === 'error' ? 5000 : 3000);
    // 同屏上限 4 条: 超出移除最旧 (FIFO), 长任务连发不糊屏
    while (root.children.length >= 4) {
      root.removeChild(root.firstChild);
    }
    const el = document.createElement('div');
    el.className = 'toast toast-' + cls;
    el.setAttribute('role', 'status');
    el.title = '点击关闭';
    // textContent 赋值 (非 innerHTML), 调用方传入的错误文本天然防注入
    el.textContent = msg;
    const dismiss = () => {
      if (el.parentNode) el.remove();
    };
    el.addEventListener('click', dismiss);  // 可点击立即关闭
    root.appendChild(el);
    if (ms > 0) setTimeout(dismiss, ms);
  },

  // ====== 文件右键菜单 (v4.1.9, S2.4 熟悉原则 + S3.4.2 Acrylic flyout) ======
  _closeFlyout() {
    const existing = document.getElementById('ctx-flyout');
    if (existing) existing.remove();
    document.removeEventListener('click', this._flyoutOutside, true);
    document.removeEventListener('keydown', this._flyoutEsc, true);
    window.removeEventListener('blur', this._flyoutOutside);
  },

  _showFileFlyout(filePath, x, y) {
    this._closeFlyout();
    const menu = document.createElement('div');
    menu.id = 'ctx-flyout';
    menu.className = 'menu-flyout acrylic';
    menu.setAttribute('role', 'menu');
    const mkItem = (label, iconName, danger, fn) => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.setAttribute('role', 'menuitem');
      btn.className = danger ? 'danger' : '';
      const icon = document.createElement('span');
      icon.className = 'nav-icon';
      icon.dataset.icon = iconName;
      btn.appendChild(icon);
      btn.appendChild(document.createTextNode(label));
      btn.addEventListener('click', () => { this._closeFlyout(); fn(); });
      return btn;
    };
    const sep = document.createElement('hr');
    sep.className = 'menu-flyout-separator';
    const sep2 = document.createElement('hr');
    sep2.className = 'menu-flyout-separator';
    menu.appendChild(mkItem('复制路径', 'document', false, () => this._copyFilePath(filePath)));
    menu.appendChild(sep);
    // v4.3.1 (UX #7): 强制重新校对 — 后端 force_rerun 跳过断点缓存重跑该文件
    menu.appendChild(mkItem('重新校对（忽略缓存）', 'play', false, () => this._rerunSingleFile(filePath)));
    menu.appendChild(sep2);
    menu.appendChild(mkItem('移除文件', 'close', true, () => this.removeFile(filePath)));
    document.body.appendChild(menu);
    // 视口钳制: 菜单整体不出屏 (S2.1 毫不费力)
    const rect = menu.getBoundingClientRect();
    menu.style.left = Math.min(x, window.innerWidth - rect.width - 8) + 'px';
    menu.style.top = Math.min(y, window.innerHeight - rect.height - 8) + 'px';
    // 外点/Esc/失焦关闭
    this._flyoutOutside = (e) => {
      if (!menu.contains(e.target)) this._closeFlyout();
    };
    this._flyoutEsc = (e) => { if (e.key === 'Escape') this._closeFlyout(); };
    document.addEventListener('click', this._flyoutOutside, true);
    document.addEventListener('keydown', this._flyoutEsc, true);
    window.addEventListener('blur', this._flyoutOutside);
  },

  async _copyFilePath(filePath) {
    if (window.pywebview && window.pywebview.api && window.pywebview.api.copy_to_clipboard) {
      try {
        const r = await window.pywebview.api.copy_to_clipboard(filePath);
        if (r && r.ok) { this.appendLog('[复制] 已复制文件路径'); return; }
      } catch (e) { /* fallthrough */ }
    }
    try {
      await navigator.clipboard.writeText(filePath);
      this.appendLog('[复制] 已复制文件路径');
    } catch (e) {
      this.appendLog('[错误] 复制路径失败: ' + e);
    }
  },

  // ====== 事件循环 ======
  startEventLoop() {
    // v4.1.5 (🟠 修复 7): 50ms -> 16ms (60 FPS 拉取), 让 D 算法高频渲染
    // (30 FPS 流式打字机) 不被前端 setInterval 截流. 跟后端 _push 33ms 节流
    // 仍兼容 (前端只关心不丢事件, 16ms 间隔低于 33ms flush 频率, 每次拉都拿到最新)
    // v4.1.8.2 (审计 F21): 排空循环套 try/catch — 任一 handler 抛异常旧版会把
    // 该事件静默吞掉且同批剩余事件延迟一拍, 毒事件还会反复打断排空.
    setInterval(() => {
      while (this.eventQueue.length > 0) {
        const [event, data] = this.eventQueue.shift();
        try {
          this.handleEvent(event, data);
        } catch (e) {
          console.error('事件处理失败:', event, data, e);
        }
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
    // v4.1.8.2 (审计 F1/C1): 活动型 watchdog — 校对相关事件到达即续期,
    // 旧版是"距开始固定 60s"的一次性定时器, 长任务中途被强制复位
    // (暂停/取消按钮被禁而后端仍在跑, 重新开始会静默取消旧任务).
    if (this.isProcessing && ['onStream', 'onStatsUpdate', 'onLog',
      'onFileStart', 'onFileDone', 'onFileCompleted',
      'onChunkProgress'].includes(event)) {  // v4.3.1 (UX #18): 块级进度也是活动信号
      this._armProofreadWatchdog();
    }
    switch (event) {
      case 'onLog':            this.appendLog(data); break;
      case 'onStream':         this.updateStream(data.file_key, data.partial); break;
      // v4.3.1 (UX #18): 多块文件每块完成时后端推 {file_key, chunk, total}
      case 'onChunkProgress':  this.handleChunkProgress(data); break;
      // v4.1.5 (🔴 修复 1): onFileStart 改为 dict {file_key, original, original_truncated}
      // 先 handleFileStart 同步设 t.original (左栏原文字数据源),
      // 再 markFileRunning 设 status='running'
      case 'onFileStart':      this.handleFileStart(data); this.markFileRunning(data.file_key); break;
      // v4.1.8.2 (审计 C2): onFileDone/onFileCompleted payload 改为
      // {file_key, status}, 失败/取消不再被误标"完成"
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
      // v4.3.0: DeAI textarea 文件拖入 (Python read_file_text 编码兜底)
      case 'onDeaiTextDrop':   this.handleDeaiTextDrop(data); break;
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

  // v4.3.1 (UX #15): 禁用按钮统一写 title 说明原因 — 用户不再猜"为什么是灰的".
  // 所有置 disabled 的地方都走此 helper, 同步维护 title (启用时移除)
  _setDisabledReason(btn, disabled, reason) {
    if (!btn) return;
    btn.disabled = !!disabled;
    if (disabled && reason) {
      btn.title = reason;
    } else {
      btn.removeAttribute('title');
    }
  },

  updateFileCount() {
    const el = document.getElementById('file-count');
    if (el) el.textContent = this.tasks.length;
    const clearBtn = document.getElementById('btn-clear-files');
    if (clearBtn) {
      // v4.3.1 (UX #15): 禁用原因 title (空列表 / 处理中区分说明)
      if (this.tasks.length === 0) {
        this._setDisabledReason(clearBtn, true, '列表为空');
      } else if (this.isProcessing) {
        this._setDisabledReason(clearBtn, true, '校对进行中，结束后可用');
      } else {
        this._setDisabledReason(clearBtn, false, '');
      }
    }
    const startBtn = document.getElementById('btn-start');
    if (startBtn) {
      // v4.1.8.2 (审计 F5): cancelled 也算可重跑 — 后端断点语义本就强制
      // CANCELLED 重跑, 旧版过滤掉 cancelled 后取消的文件永远无法重新开始
      const hasPending = this.tasks.some(t =>
        t.status === 'pending' || t.status === 'failed' || t.status === 'cancelled');
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
        // v4.3.2: 模型名留空的预设显示"拉取模型"提示, 并把 description 作为悬浮说明
        opt.textContent = t.name + ' (' + (t.model || '拉取模型') + ')';
        if (t.description) opt.title = t.description;
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
    // v4.3.3: 标点修复开关 (checkbox 用 checked 而非 value)
    {
      const cb = document.getElementById('cfg-punct-fix');
      if (cb) cb.checked = this.config.punct_fix !== false;
    }
    // v4.3.4: 标点修复 v2 规则选项
    {
      const qs = document.getElementById('cfg-punct-quote-style');
      if (qs) qs.value = this.config.punct_quote_style || 'curly';
      const setCb = (id, val, dflt) => {
        const cb = document.getElementById(id);
        if (cb) cb.checked = val === undefined ? dflt : !!val;
      };
      setCb('cfg-punct-fullwidth-alnum', this.config.punct_fullwidth_alnum, true);
      setCb('cfg-punct-repeat-compress', this.config.punct_repeat_compress, false);
      setCb('cfg-punct-dash-tilde', this.config.punct_dash_tilde, true);
    }

    // 初始 URL 校验
    this.validateApiBase();
  },

  fillSelect(id, items, currentVal) {
    const sel = document.getElementById(id);
    if (!sel) return;
    sel.innerHTML = '';
    // v4.1.8.2 (审计 F19): config 值不在选项列表时补一个"当前值"项 — 旧版
    // select 显示第一项而真实 config 未变, 用户一触发保存就把显示值写回 config
    const knownKeys = new Set(items.map(it => it.key));
    if (currentVal && !knownKeys.has(currentVal)) {
      const opt = document.createElement('option');
      opt.value = currentVal;
      opt.textContent = `${currentVal} (当前值, 选项列表缺失)`;
      opt.selected = true;
      sel.appendChild(opt);
    }
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

    // v4.3.1 (UX #21): 主页只读分块标签可点 → 前往「校对参数」页修改预设
    const chunkChip = document.getElementById('home-chunking-display');
    if (chunkChip) chunkChip.addEventListener('click', () => this.setView('params'));

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

    // v4.1.9: 文件右键菜单 (Fluent flyout)
    this.bindFileContextMenu();

    // v4.2.0: 参数页的保存按钮 (与 API 页 btn-save-config 同一逻辑)
    // v4.3.1 (UX #9): 把触发按钮传给 saveConfigNow, "✓ 已保存" 反馈落在本按钮
    document.querySelectorAll('.js-save-config').forEach(btn => {
      btn.addEventListener('click', () => this.saveConfigNow(btn));
    });

    // v4.2.0: data-nav 通用跳转 (如去AI味页的「管理风格库」)
    document.querySelectorAll('[data-nav]').forEach(btn => {
      btn.addEventListener('click', () => this.setView(btn.dataset.nav));
    });

    // v4.2.0: 结果对比页文件下拉
    const resultSel = document.getElementById('result-file-select');
    if (resultSel) {
      resultSel.addEventListener('change', () => {
        if (resultSel.value) this.selectFile(resultSel.value);
      });
    }

    // v4.2.0: 风格库页 Profile 下拉 (与去AI味页镜像)
    const stylesSel = document.getElementById('styles-profile-select');
    if (stylesSel) {
      stylesSel.addEventListener('change', () => this.selectStyleProfile(stylesSel.value));
    }

    // 设置
    // v4.3.1 (UX #9): 传入按钮, 保存反馈作用于触发按钮本身
    const saveBtn = document.getElementById('btn-save-config');
    if (saveBtn) saveBtn.addEventListener('click', () => this.saveConfigNow(saveBtn));

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
    this.bindSkinSwitcher();

    // URL 校验 + 防抖
    const urlInput = document.getElementById('cfg-api-base');
    if (urlInput) {
      urlInput.addEventListener('input', () => {
        this.validateApiBase();
        this.markConfigDirty();
      });
    }
    // 所有 cfg-* 字段防抖
    // v4.2.0: cfg-* 字段分布在 API 接口 / 校对参数 / 外观三页
    document.querySelectorAll('#view-api input, #view-api select, #view-api textarea, #view-params input, #view-params select, #view-params textarea, #view-appearance input, #view-appearance select, #view-appearance textarea').forEach(el => {
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

    // v4.3.0: DeAI textarea 拖入 (纯文本原生插入; 文件走 Python 通道)
    this.bindDeaiTextDrop();
    // v4.3.0: 字符计数 + 预计块数
    for (const id of ['deai-input', 'deai-sample']) {
      const el = document.getElementById(id);
      if (el) el.addEventListener('input', () => this._updateDeaiCharCount());
    }

    // DeAI 复制按钮
    for (let i = 1; i <= 3; i++) {
      const btn = document.getElementById('btn-deai-copy-' + i);
      if (btn) btn.addEventListener('click', () => this.copyDeaiOutput(i));
    }
    const deaiExport = document.getElementById('btn-deai-export');
    if (deaiExport) deaiExport.addEventListener('click', () => this.exportDeaiResult());

    // v4.1.8.2 (审计 F14): 补回 README 宣称的快捷键 (v4.0 重写时整层丢失)
    document.addEventListener('keydown', (e) => {
      if (!e.ctrlKey) return;
      const key = e.key.toLowerCase();
      if (key === 'o') {
        e.preventDefault();  // 避免浏览器"打开文件"默认行为
        this.addFiles();
      } else if (key === 'enter') {
        // textarea 内也允许 Ctrl+Enter 开始 (显式组合键, 不冲突)
        if (!this.isProcessing) this.startProofread();
      } else if (key === ',') {
        this.setView('api');  // v4.2.0: 设置拆分后指向 API 接口页
      } else if (key === '.') {
        this.setView('deai');
      }
    });

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
    // v4.1.8.2 (审计 F25): Esc 取消拖拽 / 指针快速拖出窗口时 dragleave 不保证
    // 派发, 高亮框会残留到下次拖拽 — window 级 dragend 兜底清除
    window.addEventListener('dragend', () => dropZone.classList.remove('drag-over'));
    document.body.addEventListener('drop', () => dropZone.classList.remove('drag-over'));
  },

  // v4.1.3 (F2): 接收 Python DOM API 推过来的文件路径 (含 pywebviewFullPath)
  handleFilesDropped(data) {
    if (!data || !Array.isArray(data.paths) || data.paths.length === 0) {
      this.appendLog('[拖拽] 未拿到有效文件路径');
      return;
    }
    // v4.1.8.2 (审计 F24/C7): 修正注释 — 路径来自 OS drop 事件必然存在;
    // 目录/不可读文件由后端 prepare_tasks 读失败建 FAILED 占位兜底
    // (drag_drop_files 只查存在性, 过滤不了目录, 故不在此调用)
    const paths = data.paths;
    let added = 0;
    let skipped = 0;
    for (const p of paths) {
      // v4.3.1 (UX #22): 校对区只收文本文件 — 非文本路径不入列 (与去AI味拖入
      // 同一扩展名白名单); 旧版直接入列, 后端读失败才变 FAILED, 用户无回音
      if (!/\.(txt|md|markdown|text)$/i.test(p)) {
        skipped++;
        continue;
      }
      if (!this.tasks.find(t => t.path === p)) {
        this.tasks.push({path: p, status: 'pending', original: '', corrected: '', error: ''});
        added++;
      }
    }
    this.renderFileList();
    this.updateFileCount();
    if (skipped > 0) {
      this.appendLog(`[拖拽] 跳过 ${skipped} 个不支持的文件 (仅 .txt/.md 等文本)`);
      // v4.3.1 (UX #22): 跳过也要有即时回音
      this.showToast(`已跳过 ${skipped} 个不支持的文件，仅支持 .txt/.md 等文本文件`, 'error');
    }
    this.appendLog(`[拖拽] 添加 ${added} 个文件, 总计 ${this.tasks.length}`);
  },

  // v4.1.8: 主题切换 (auto/light/dark)
  // v4.1.9 (S2.3 个人原则): 切换逻辑抽到 applyTheme, 并持久化到 config
  // (旧版只改 DOM 不落盘, 重启回退 auto)
  bindThemeSwitcher() {
    const switcher = document.getElementById('theme-switcher');
    if (!switcher) return;
    const buttons = switcher.querySelectorAll('button[data-theme-value]');
    buttons.forEach(btn => {
      btn.addEventListener('click', () => {
        const value = btn.dataset.themeValue;  // auto / light / dark
        this.applyTheme(value);
        this._persistTheme(value);
        this.appendLog(`[主题] 已切换到: ${value} (已保存)`);
        // v4.3.1 (UX #2): 外观页无日志区, toast 确认已切换并落盘
        this.showToast('主题已切换并保存', 'info');
      });
    });
  },

  // v4.4.0: 界面皮肤切换 (fluent / ink 水墨) — 模式镜像 bindThemeSwitcher
  bindSkinSwitcher() {
    const switcher = document.getElementById('skin-switcher');
    if (!switcher) return;
    const buttons = switcher.querySelectorAll('button[data-skin-value]');
    buttons.forEach(btn => {
      btn.addEventListener('click', () => {
        const value = btn.dataset.skinValue;  // fluent / ink
        this.applySkin(value);
        this._persistSkin(value);
        this.appendLog(`[风格] 已切换到: ${value === 'ink' ? '水墨宣纸' : 'Win11 Fluent'} (已保存)`);
        // 外观页无日志区, toast 确认已切换并落盘 (同 v4.3.1 UX #2)
        this.showToast('风格已切换并保存', 'info');
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
    // v4.1.9 (S3.4.4): 原生 confirm() -> WinUI 3 ContentDialog (Smoke + 等宽双按钮)
    const confirmed = await this.showConfirmDialog({
      title: '清空所有文件?',
      body: `将移除列表中的 ${this.tasks.length} 个文件 (已完成的校对结果也会被清除)。`,
      primaryText: '清空',
      secondaryText: '取消',
      icon: 'warning',
      danger: true,
    });
    if (!confirmed) return;
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
      li.dataset.path = t.path;  // v4.1.9: 右键菜单定位用
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
        // v4.3.1 (UX #6): 只有完成/失败才跳结果对比页 (看成品/看错误);
        // 待处理/处理中/暂停/已取消仅选中不跳转 — 留在校对页看进度, 保持安静不弹 toast
        if (t.status === 'completed' || t.status === 'failed') {
          this.setView('results');
        }
      });
      // v4.3.1 (UX #5): 失败文件悬停即见人话原因 (不必先跳结果页)
      if (t.status === 'failed' && t.error) {
        li.title = this._humanizeError(t.error);
      }
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
    // v4.2.0: 同步结果对比页的文件下拉
    this.renderResultFileSelect();
  },

  // v4.2.0: 结果对比页的文件下拉 (与文件列表同一数据源)
  renderResultFileSelect() {
    const sel = document.getElementById('result-file-select');
    if (!sel) return;
    const statusText = {
      pending: '待处理', running: '处理中', paused: '已暂停',
      completed: '完成', failed: '失败', cancelled: '已取消',
    };
    sel.innerHTML = '';
    if (this.tasks.length === 0) {
      const opt = document.createElement('option');
      opt.value = '';
      opt.textContent = '尚未添加文件';
      sel.appendChild(opt);
      sel.disabled = true;
      return;
    }
    sel.disabled = false;
    for (const t of this.tasks) {
      const opt = document.createElement('option');
      opt.value = t.path;
      const name = t.path.split(/[\\/]/).pop();
      opt.textContent = `${name} (${statusText[t.status] || t.status})`;
      if (t.path === this.selectedFileKey) opt.selected = true;
      sel.appendChild(opt);
    }
  },

  // 绑定一次: 文件列表右键弹出 Fluent 菜单 (v4.1.9, S2.4 熟悉原则)
  bindFileContextMenu() {
    const ul = document.getElementById('file-list');
    if (!ul || ul.dataset.ctxBound) return;
    ul.dataset.ctxBound = '1';
    ul.addEventListener('contextmenu', (e) => {
      const li = e.target.closest('li');
      if (!li || !li.dataset.path) return;
      e.preventDefault();
      this._showFileFlyout(li.dataset.path, e.clientX, e.clientY);
    });
  },

  selectFile(path) {
    this.selectedFileKey = path;
    this.renderFileList();
    this.renderCompare(path);
    // v4.2.0: 同步结果对比页下拉
    const sel = document.getElementById('result-file-select');
    if (sel && sel.value !== path) sel.value = path;
    // v4.1.5 (🟠 修复 8): 复制/导出按钮仅在"校对完成 + 非处理中"时 enabled.
    // 流式时 disabled, 避免用户复制到一半的 partial.
    // v4.1.8.2 (审计 F7/C3): 增加 status 判据 — 失败/取消文件后端把 corrected
    // 兜底为原文, 只判 corrected 非空会把未校对原文当结果复制/导出
    const copyBtn = document.getElementById('btn-copy-result');
    const exportBtn = document.getElementById('btn-export-result');
    const toggleDiffBtn = document.getElementById('btn-toggle-diff-mode');
    const t = this.tasks.find(t => t.path === path);
    const hasResult = !!(t && t.corrected && t.status === 'completed' && !this.isProcessing);
    // v4.3.1 (UX #15): 禁用原因 title — 处理中与未完成给不同说明
    const opReason = this.isProcessing ? '校对进行中，结束后可用' : '校对完成后可用';
    if (copyBtn) this._setDisabledReason(copyBtn, !hasResult, opReason);
    if (exportBtn) this._setDisabledReason(exportBtn, !hasResult, opReason);
    // toggle 按钮: 仅在已校对完成时 enabled (流式时 disabled, 切到 full 也得有完整结果)
    // v4.1.8.2 (审计 F10): 判据从 t.corrected 改为 status==='completed' —
    // 流式期间 partial 正写入 t.corrected, 旧判据会误启用
    // v4.3.1 (UX #15): 禁用区分"处理中"与"还没有结果"
    if (toggleDiffBtn) {
      if (this.isProcessing) {
        this._setDisabledReason(toggleDiffBtn, true, '校对进行中，结束后可用');
      } else if (!t || t.status !== 'completed') {
        this._setDisabledReason(toggleDiffBtn, true, '该文件还没有校对结果');
      } else {
        this._setDisabledReason(toggleDiffBtn, false, '');
      }
    }
    // v4.1.8.2 (审计 F16): 同步 toggle 按钮文案与所选文件的 mode — 旧版切
    // 文件后文案停在上一文件的 state.mode, 第一次点击表现为"没切换"
    const state = path ? this.renderState[path] : null;
    if (toggleDiffBtn && state) {
      // v4.3.1 (UX #16): 文案与 toggleDiffMode 同步统一
      toggleDiffBtn.textContent = state.mode === 'full' ? '返回逐字对比' : '查看增删标记';
    }
  },

  // ====== 校对流程 ======
  // v4.3.1 (UX #5): 错误人话化 — 常见 LLM API 错误关键字映射为一行行动指引;
  // 未命中规则时原样返回 (不吞信息), 原始错误始终在 error-raw / chip title 可查
  _humanizeError(msg) {
    const s = String(msg || '');
    const rules = [
      [/Authentication|401|Unauthorized|api[_ ]?key/i, 'API Key 无效或未填写，请到「API 接口」页检查'],
      // v4.3.1.1: RateLimit 补带空格写法 (真实报错常为 "Rate limit reached" / "rate limit exceeded")
      [/Rate[ _]?Limit|429/i, '触发 API 限速，请稍后重试或降低并发数'],
      [/timeout|timed out/i, '请求超时（服务器无响应或太慢），可在「校对参数」页调大超时'],
      [/Connection|ConnectionError|ECONNREFUSED|Failed to establish|fetch failed/i, '无法连接 API 服务器，请检查 Base URL 与网络'],
      [/NotFound|404|not found/i, '模型或接口不存在，请检查模型名'],
    ];
    for (const [re, hint] of rules) {
      if (re.test(s)) return hint;
    }
    return s;
  },

  // v4.3.1 (UX #5): 鉴权/连接类错误 — 需要回「API 接口」页改配置 (renderCompare 行动按钮判据)
  _isApiConfigError(msg) {
    return /Authentication|401|Unauthorized|api[_ ]?key|Connection|ConnectionError|ECONNREFUSED|Failed to establish|fetch failed/i
      .test(String(msg || ''));
  },

  // v4.3.1 (UX #4): 开始前统一校验 — Base URL 格式 / API Key / 模型名, 缺什么列什么;
  // 不通过时跳「API 接口」页 + 对话框给行动指引 (可从预设模板一键填入), 返回 false
  _checkStartPrerequisites() {
    // v4.3.3: 「仅标点修复」模式全程本地、不触网 — 跳过 API 配置检查
    if (this.getVal('cfg-prompt-mode') === 'punct_local') return true;
    const missing = [];
    const apiBase = this.getVal('cfg-api-base');
    // v4.1.8.2 (审计 F20): 空/非法 URL 直接拒绝启动 — 旧版空 api_base 能启动,
    // 全部文件走完重试链后 APIConnectionError 失败
    if (!apiBase || !/^https?:\/\/[^\s]+$/.test(apiBase)) {
      missing.push('API Base URL (为空或格式无效)');
    }
    if (!this.getVal('cfg-api-key')) missing.push('API Key');
    if (!this.getVal('cfg-model')) missing.push('模型名 (Model)');
    if (missing.length === 0) return true;
    this.setView('api');
    this.showConfirmDialog({
      title: '还不能开始校对',
      body: `缺少: ${missing.join('、')}。请先在「API 接口」页补全 Base URL / API Key / 模型名 (可从预设模板一键填入)。`,
      primaryText: '知道了',
      secondaryText: '关闭',
      icon: 'info',
    });
    this.appendLog('[错误] API 配置不完整 (' + missing.join(', ') + '), 请先到 API 接口页配置');
    return false;
  },

  // v4.1.8.2 (审计 F5): cancelled 也纳入重跑 (与 hasPending/后端断点语义一致)
  async startProofread() {
    const paths = this.tasks.filter(t =>
        t.status === 'pending' || t.status === 'failed' || t.status === 'cancelled')
                            .map(t => t.path);
    if (paths.length === 0) {
      this.appendLog('[提示] 没有待处理文件');
      return;
    }
    await this._runProofread(paths);
  },

  // v4.3.1 (UX #7): 校对执行主体 — 开始按钮与文件右键"重新校对(忽略缓存)"共用;
  // forceRerun=true 透传后端 start_proofread 第 5 个位置参数 (跳过断点缓存强制重跑)
  async _runProofread(paths, { forceRerun = false } = {}) {
    if (!paths || paths.length === 0) {
      this.appendLog('[提示] 没有待处理文件');
      return;
    }
    // v4.3.1 (UX #4): Base URL / API Key / 模型名三缺一都拦在启动前
    if (!this._checkStartPrerequisites()) return;
    // v4.1.8.2 (审计 C6): 有未落盘的改动先同步保存 — 旧版直接读 500ms 防抖前
    // 的旧 config, 界面显示新值实际跑旧值
    if (this.configDirty) {
      clearTimeout(this.configSaveTimer);
      this.configSaveTimer = null;
      await this.saveConfig({silent: true});
      this.configDirty = false;
    }
    // v4.1 (I5): 主页不再有 chunking select, 直接读 config (从设置页同步过来)
    const preset = this.config.chunking_preset || 'balanced';
    this.isProcessing = true;
    // v4.1.8.2 (审计 F10): 重跑时 renderState 一律重建 — 旧版 _initRenderState
    // "存在即跳过", 残留的 mode='full' 会让新一轮流式直接落进每帧全量 diff 路径
    for (const p of paths) {
      this.renderState[p] = {
        lastPartialLen: 0, renderedHTML: '', renderedOriginalLen: 0,
        rafScheduled: false, mode: 'streaming',
      };
    }
    // v4.1 (I6) / v4.1.8.2 (审计 F1): watchdog 改活动型 — 有校对事件就续期
    // (dispatch 里 _armProofreadWatchdog), 只在真正无响应 60s 时兜底复位
    this._armProofreadWatchdog();
    for (const p of paths) {
      const t = this.tasks.find(t => t.path === p);
      // v4.3.1 (UX #5): 重跑同时清旧 error — 否则失败文件重跑期间/成功后
      // 仍显示上一轮的 error-mark (后端成功 result.error=null 不会覆盖)
      if (t) { t.status = 'running'; t.error = ''; }
    }
    this.renderFileList();
    this.updateFileCount();
    this.setProcessingButtons(true);
    this.appendLog(`[启动] ${paths.length} 个文件${forceRerun ? ' (强制重新校对, 忽略缓存)' : ''}, 模式=${this.config.prompt_mode || 'strict'}, 分块=${preset}`);
    try {
      // v4.3.1 (UX #7): 第 5 个位置参数 force_rerun (pywebview 按位置传参)
      const result = await window.pywebview.api.start_proofread(
        paths,
        this.config.prompt_mode || 'strict',
        this.config.custom_prompt || '',
        preset,
        forceRerun ? true : false
      );
      // v4.1.8.2 (审计 B3/F4): 统一契约检查 — 旧版不检查 ok, 启动失败时文件
      // 永久卡"处理中"且开始按钮永久禁用
      if (!result || result.ok === false) {
        throw new Error((result && result.error) || '启动失败 (无返回)');
      }
      this.currentTaskId = result.task_id;
      this.appendLog(`[Task] id=${result.task_id}, 共 ${result.total_files} 个文件`);
      // v4.3.1 (UX #7): 缓存命中上报 — 告知哪些文件被跳过 + 指引重跑通道
      // (force_rerun 时后端返回空数组, 天然不弹)
      const cached = Array.isArray(result.cached_files) ? result.cached_files : [];
      if (cached.length > 0) {
        this.showToast(`已跳过 ${cached.length} 个文件（命中上次校对缓存，右键文件可强制重新校对）`, 'info');
      }
    } catch (e) {
      this.appendLog('[错误] start_proofread 失败: ' + e);
      this._clearProofreadWatchdog();
      this.isProcessing = false;
      this.setProcessingButtons(false);
      // 把预标为 running 的文件复位, 否则 hasPending=false 开始按钮永久禁用
      for (const p of paths) {
        const t = this.tasks.find(t => t.path === p);
        if (t && t.status === 'running') t.status = 'pending';
      }
      this.renderFileList();
      this.updateFileCount();
    }
  },

  // v4.3.1 (UX #7): 单文件强制重新校对 (右键菜单入口) — 有任务在跑时拒绝,
  // 防并发双任务打乱后端 engine 状态
  _rerunSingleFile(filePath) {
    if (this.isProcessing) {
      this.showToast('有任务正在运行，请等当前任务结束再重新校对', 'error');
      return;
    }
    const t = this.tasks.find(t => t.path === filePath);
    if (!t) return;
    t.status = 'pending';
    this.renderFileList();
    this.updateFileCount();
    this.appendLog(`[重跑] ${filePath.split(/[\\/]/).pop()} (忽略缓存, 强制重新校对)`);
    this._runProofread([filePath], { forceRerun: true });
  },

  // v4.1.8.2 (审计 F1/C1): 活动型 watchdog — 每次收到校对事件就重设 60s,
  // onTaskComplete/cancel/启动失败时清除
  _armProofreadWatchdog() {
    this._clearProofreadWatchdog();
    this._proofreadWatchdog = setTimeout(() => {
      if (this.isProcessing) {
        this.isProcessing = false;
        this.setProcessingButtons(false);
        this.appendLog('[警告] 60 秒无任何事件, 自动复位 (可能后端异常)');
        // 把仍标 running 的文件复位, 避免 F4 的"开始按钮永久禁用"
        for (const t of this.tasks) {
          if (t.status === 'running') t.status = 'failed';
        }
        this.renderFileList();
        this.updateFileCount();
      }
    }, 60000);
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
      if (r.ok) {
        this.setProcessingButtons(true, true); // paused
        // v4.3.1 (UX #14): 暂停期间无任何事件, 不误杀 — 清掉活动 watchdog,
        // 否则挂起 60s 后被兜底复位把 running 文件误标 failed
        this._clearProofreadWatchdog();
      }
    } catch (e) {
      this.appendLog('[错误] pause 失败: ' + e);
    }
  },

  async resumeProofread() {
    try {
      const r = await window.pywebview.api.resume_proofread();
      this.appendLog(`[${r.action || 'resume'}] ${r.ok ? '已恢复' : '失败'}`);
      if (r.ok) {
        this.setProcessingButtons(true, false);
        // v4.3.1 (UX #14): 恢复后重新布防活动 watchdog
        this._armProofreadWatchdog();
      }
    } catch (e) {
      this.appendLog('[错误] resume 失败: ' + e);
    }
  },

  async cancelProofread() {
    try {
      const r = await window.pywebview.api.cancel_proofread();
      this.appendLog(`[${r.action || 'cancel'}] ${r.ok ? '已取消' : '失败'}`);
      // v4.1.8.2 (审计 F1): 取消时清 watchdog (旧注释声称清掉但代码没清)
      if (r.ok) this._clearProofreadWatchdog();
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
    if (clearBtn) {
      // v4.3.1 (UX #15): 处理中/空列表两种禁用原因
      if (processing) {
        this._setDisabledReason(clearBtn, true, '校对进行中，结束后可用');
      } else if (this.tasks.length === 0) {
        this._setDisabledReason(clearBtn, true, '列表为空');
      } else {
        this._setDisabledReason(clearBtn, false, '');
      }
    }
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
    // v4.1.8.2 (审计 F2): 只对"当前选中"的文件调度渲染 — 后端默认并发=2
    // 文件级并发, 旧版不校验选中态, 面板内容被另一文件的流覆盖串台.
    // 未选中文件不动 state (lastPartialLen 保持 0), 切回时 selectFile →
    // renderCompare 一次性补渲染全量 partial.
    if (fileKey === this.selectedFileKey) {
      this.scheduleRender(fileKey);
    }
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

  // v4.1.8.2 (审计 C2): payload 改为 {file_key, status} — 成功/失败/取消
  // 三条路径都推此事件, 旧版无条件标"完成"让失败文件全程绿灯
  markFileDone(data) {
    const fileKey = (data && data.file_key) !== undefined ? data.file_key : data;
    const status = (data && data.status) || 'completed';
    const t = this.tasks.find(t => t.path === fileKey);
    if (t) {
      t.status = status;
      this.renderFileList();
      // v4.1.5: 文件完成, 刷新按钮态
      if (this.selectedFileKey === fileKey) {
        this.renderCompare(fileKey);
        this.selectFile(fileKey);
      }
    }
  },

  updateStats(stats) {
    const el = document.getElementById('progress-stats');
    if (!el || !stats) return;
    // v4.1.8.2 (审计, updateStats 空值防护): 字段缺省兜底
    const total = stats.total_files || 0;
    const done = stats.completed_files || 0;
    const pct = total > 0 ? Math.round((done / total) * 100) : 0;
    const etaVal = stats.eta || 0;
    const speed = stats.speed || 0;
    // v4.3.1 (UX #20): 删掉行内 "| 剩余 ~Xs" — ETA 只在下方 #progress-eta
    // 独立行显示 (旧版同一信息显示两遍)
    el.textContent = `${pct}% | ${done}/${total} 文件 | ${stats.total_tokens || 0} tokens | ${speed.toFixed(1)} t/s`;
    const fill = document.getElementById('progress-fill');
    if (fill) fill.style.width = pct + '%';
    // ETA
    const etaEl = document.getElementById('progress-eta');
    if (etaEl) {
      etaEl.textContent = etaVal > 0 ? `预计剩余: ${etaVal.toFixed(0)} 秒` : '';
    }
  },

  // v4.3.1 (UX #18): 块级进度 — 多块文件每块完成时后端推 {file_key, chunk, total};
  // 单块文件 (total<=1) 不显示, 任务收尾由 onTaskComplete 恢复 hidden
  handleChunkProgress(data) {
    const el = document.getElementById('chunk-progress');
    if (!el || !data) return;
    const total = Number(data.total) || 0;
    if (total <= 1) {
      el.hidden = true;
      return;
    }
    el.hidden = false;
    el.textContent = `当前文件: 块 ${Number(data.chunk) || 0}/${total}`;
  },

  onTaskComplete(results) {
    this._clearProofreadWatchdog();
    this.isProcessing = false;
    this.setProcessingButtons(false);
    // v4.3.1 (UX #18): 任务收尾, 块级进度行恢复 hidden
    const chunkEl = document.getElementById('chunk-progress');
    if (chunkEl) chunkEl.hidden = true;
    // v4.1.8.2 (审计 B7): 丢弃旧任务的晚到 onTaskComplete — 重入清理后旧
    // 任务的 CANCELLED 收尾会落在新任务启动之后, 把 UI 重置成"已结束"
    if (results && results.task_id && this.currentTaskId
        && results.task_id !== this.currentTaskId) {
      this.appendLog(`[提示] 忽略旧任务 (${results.task_id}) 的完成事件`);
      return;
    }
    this.currentTaskId = null;
    // v4.1 (I6): 后端异常时 (run() 顶层 try/except) 会推 {"error": "..."}
    // v4.1.8.2 (审计 F4/C8): 把仍标 running 的文件复位 — 旧版只打日志,
    // 文件永久卡"处理中"且 hasPending=false 使开始按钮永久禁用
    if (results && results.error) {
      this.appendLog('[错误] 后端任务异常: ' + results.error);
      // v4.3.1 (UX #19): 后端异常也要 toast (日志区在别页看不见)
      // v4.3.1 (UX #5): 人话化 + 原始错误保留在日志
      this.showToast('校对异常: ' + this._humanizeError(results.error), 'error');
      for (const t of this.tasks) {
        if (t.status === 'running') t.status = 'failed';
      }
      this.renderFileList();
      this.updateFileCount();
      return;
    }
    // v4.3.1 (UX #19): 完成日志改人话汇总 — 旧版 JSON.stringify(Object.keys(...))
    // 用户看不懂; 按 results 各项 status 统计成功/失败/取消, 配 toast 全局回音
    let okCount = 0, failCount = 0, cancelCount = 0;
    if (results) {
      for (const [key, info] of Object.entries(results)) {
        if (key === 'task_id') continue;
        const st = (info && info.status) || 'completed';
        if (st === 'completed') okCount++;
        else if (st === 'cancelled') cancelCount++;
        else failCount++;
        const t = this.tasks.find(t => t.path === key);
        if (t && info.result) {
          t.original = info.result.original || '';
          t.corrected = info.result.corrected || '';
          t.status = info.status || 'completed';
          // v4.3.1 (UX #5): 无条件回写 error — 旧版只在有值时覆盖, 重跑成功后
          // 上一轮旧 error 残留, 结果页永远显示 error-mark
          t.error = info.result.error || '';
        }
      }
      this.appendLog(`完成：成功 ${okCount} / 失败 ${failCount} / 取消 ${cancelCount}`);
      // toast: 有失败优先报失败 (引导去结果对比页看原因); 全成功报成功;
      // 全取消不算成功也不算失败, info 提示
      if (failCount > 0) {
        this.showToast(`校对完成：失败 ${failCount} 个，详情见结果对比页`, 'error');
      } else if (okCount > 0) {
        this.showToast(`校对完成：成功 ${okCount} 个`, 'success');
      } else if (cancelCount > 0) {
        this.showToast(`校对已取消（共 ${cancelCount} 个文件）`, 'info');
      }
      this.renderFileList();
    }
    // v4.1.8.2 (审计 F13): 任务完成后刷新复制/导出按钮 — 旧版 onFileDone 时
    // isProcessing 仍为 true 把按钮禁用, onTaskComplete 不刷新导致永远灰色
    if (this.selectedFileKey) this.selectFile(this.selectedFileKey);
    this.updateFileCount();
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
      // v4.3.1 (UX #16): 术语统一 — "流式"是内部实现词, 用户视角叫"校对输出"
      revisedEl.innerHTML = '<div class="type-emptystate">校对输出将在这里实时显示</div>';
      return;
    }

    const t = this.tasks.find(t => t.path === fileKey);
    if (!t) {
      originalEl.innerHTML = '<div class="type-emptystate">选择文件查看原文</div>';
      revisedEl.innerHTML = '<div class="type-emptystate">校对输出将在这里实时显示</div>';
      return;
    }

    // v4.1.8.2 (审计 F2): 兜底守卫 — 非当前选中文件的渲染请求直接丢弃
    // (RAF 回调可能在用户切换文件后才执行)
    if (fileKey !== this.selectedFileKey) return;

    // 2. (🟠 修复 9): 错误态 fallback — 右栏显示 error-mark
    if (t.error) {
      originalEl.textContent = t.original || '';
      // v4.3.1 (UX #5): 人话一行在前 + 原始错误小字 (error-raw) 在后;
      // 鉴权/连接类错误补"前往 API 接口页"行动按钮 (renderCompare 由 App
      // 方法调用, this=App, 箭头函数闭包保证绑定)
      const isConfigErr = this._isApiConfigError(t.error);
      revisedEl.innerHTML =
        `<div class="error-mark"><div>${this.escapeHtml(this._humanizeError(t.error))}</div>` +
        `<div class="error-raw">原始错误: ${this.escapeHtml(t.error)}</div>` +
        (isConfigErr ? '<button type="button" class="btn btn-standard btn-subtle error-goto-api">前往 API 接口页</button>' : '') +
        '</div>';
      const gotoBtn = revisedEl.querySelector('.error-goto-api');
      if (gotoBtn) gotoBtn.addEventListener('click', () => this.setView('api'));
      return;
    }

    // 3. 左栏原文字: t.original 在 handleFileStart / onTaskComplete 时已设
    //    大文件 original_truncated 场景: t.original 为空, 异步调 read_file 读
    // v4.1.8.2 (审计 F22): 内容未变时不重写 — 旧版流式期间每帧全量替换
    // 文本节点触发重排 (大文件 30FPS 下代价集中)
    if (t.original) {
      if (originalEl.textContent !== t.original) originalEl.textContent = t.original;
    } else if (t._originalTruncated) {
      // 大文件未推 original: 异步 read_file 补上
      originalEl.innerHTML = '<div class="type-emptystate">原文较大, 正在加载...</div>';
      this._loadOriginalFallback(fileKey);
    } else {
      // v4.3.1 (UX #16): 术语统一 — 流式开始前不再出现"流式"字眼
      originalEl.innerHTML = '<div class="type-emptystate">选择文件后在此显示原文</div>';
    }

    // 4. 右栏: D 方案 (流式) 或 diff_main (全量)
    const state = this._initRenderState(fileKey);
    const partial = this.streamingContent[fileKey] || t.corrected || '';

    // 4a. 全量模式: 用户点"查看增删标记"后, 用 diff_main 重渲染
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
    // v4.1.8.2 (审计 F3): 早退分支必须幂等回写 — 旧版直接 return, 切换到
    // 另一个已完成文件时右栏残留上一个文件的 diff HTML (必现)
    if (partial.length === state.lastPartialLen) {
      if (revisedEl.innerHTML !== state.renderedHTML) {
        revisedEl.innerHTML = state.renderedHTML;
      }
      return;
    }

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
      // v4.1.8.2 (审计 B10): read_file 改返回 {ok, content/error}
      const r = await window.pywebview.api.read_file(fileKey);
      t._loadingOriginal = false;
      if (r && r.ok === false) {
        this.appendLog('[提示] 加载原文字失败: ' + (r.error || '未知'));
        return;
      }
      // v4.1.8.2 (审计 F9): 结果无条件存到 task 上 — 旧版只在"恰好选中"时
      // 才保存, 未选中时被丢弃, 流式期间每个事件 (≈30/s) 都重新全量读一遍文件
      if (!t.original) {
        t.original = (r && r.content) || '';
        if (t.path === this.selectedFileKey) {
          this.renderCompare(fileKey);
        }
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
    // v4.1.8.2 (审计 F10): 流式期间禁止切全量 — 切过去后每帧对整个 partial
    // 跑 diff_main, 50K 字 30FPS 全量 diff 明显卡顿
    if (this.isProcessing) {
      this.appendLog('[提示] 处理中暂不能切换 diff 模式');
      return;
    }
    const state = this._initRenderState(key);
    const t = this.tasks.find(t => t.path === key);
    if (!t || !t.corrected) return;  // 没结果不让切
    const btn = document.getElementById('btn-toggle-diff-mode');
    if (state.mode === 'streaming') {
      state.mode = 'full';
      // v4.3.1 (UX #16): 术语统一 — "流式/完整 diff"改为用户视角的"逐字/增删标记"
      if (btn) btn.textContent = '返回逐字对比';
    } else {
      state.mode = 'streaming';
      // 切回流式: 重置累积, 重新从 partial 增量
      state.lastPartialLen = 0;
      state.renderedHTML = '';
      state.renderedOriginalLen = 0;
      if (btn) btn.textContent = '查看增删标记';
    }
    this.renderCompare(key);
  },

  // v4.1.5 (🔴 修复 1): 后端 onFileStart 推送 {file_key, original, original_truncated}
  // 同步设 t.original, 让左栏原文字在流式开始就有数据
  handleFileStart(data) {
    if (!data || !data.file_key) return;
    // v4.3.1 (UX #18): 新文件开始时清掉上一文件的块级进度残留
    const chunkEl = document.getElementById('chunk-progress');
    if (chunkEl) chunkEl.hidden = true;
    const t = this.tasks.find(t => t.path === data.file_key);
    if (!t) return;
    // original 可能是 null (大文件) 或 string
    t.original = data.original || '';
    t._originalTruncated = !!data.original_truncated;
  },

  // ====== DeAI textarea 拖入 (v4.3.0, 评审#4 修正版) ======
  // 纯文本拖放: 不 preventDefault, 只 stopPropagation 防 body 级吞默认,
  //   保留浏览器原生"光标处插入"语义; 文件拖放: preventDefault 后等
  //   pywebview DOM 通道推 onDeaiTextDrop (Python read_file_text 编码兜底,
  //   规避 File.text() 恒 UTF-8 把 GBK 记事本文件变乱码的问题).
  bindDeaiTextDrop() {
    for (const id of ['deai-input', 'deai-sample']) {
      const el = document.getElementById(id);
      if (!el || el.dataset.dropBound) continue;
      el.dataset.dropBound = '1';
      el.addEventListener('dragenter', () => el.classList.add('textarea-drag'));
      el.addEventListener('dragover', (e) => { e.stopPropagation(); el.classList.add('textarea-drag'); });
      el.addEventListener('dragleave', () => el.classList.remove('textarea-drag'));
      el.addEventListener('drop', (e) => {
        e.stopPropagation();
        el.classList.remove('textarea-drag');
        const dt = e.dataTransfer || {};
        const types = dt.types ? Array.from(dt.types) : [];
        if (types.includes('Files')) {
          // 文件: preventDefault 阻止浏览器打开文件, 内容等 onDeaiTextDrop 推送
          e.preventDefault();
          this.appendLog('[DeAI] 正在读取拖入的文件...');
          return;
        }
        // 纯文本: 交给浏览器原生插入, 稍后刷新计数
        setTimeout(() => this._updateDeaiCharCount(), 0);
      });
    }
  },

  async handleDeaiTextDrop(data) {
    if (!data || !Array.isArray(data.paths) || !data.paths.length) return;
    const el = document.getElementById(data.target);
    if (!el) return;
    let applied = 0;
    for (const p of data.paths) {
      if (!/\.(txt|md|markdown|text)$/i.test(p)) {
        const name = p.replace(/\\/g, '/').split('/').pop();
        this.appendLog(`[DeAI] 跳过不支持的文件类型: ${name} (仅 .txt/.md)`);
        // v4.3.1 (UX #2): 拖错文件类型给即时回音
        this.showToast(`仅支持 .txt/.md 文件（已跳过: ${name}）`, 'error');
        continue;
      }
      try {
        const r = await window.pywebview.api.read_file(p);
        if (!r || r.ok === false) {
          this.appendLog('[DeAI] 读取失败: ' + ((r && r.error) || '未知'));
          continue;
        }
        await this._applyDroppedText(el, r.content || '');
        applied++;
      } catch (e) {
        this.appendLog('[DeAI] 读取失败: ' + e);
      }
    }
    if (applied) this._updateDeaiCharCount();
  },

  async _applyDroppedText(el, text) {
    if (!text) return;
    if (el.value.trim()) {
      // 已有内容: WinUI 三命令对话框 (追加/替换/取消)
      const r = await this.showConfirmDialog({
        title: '文本框已有内容',
        body: `拖入 ${text.length} 字, 如何处理?`,
        primaryText: '追加到末尾',
        closeText: '替换现有内容',
        secondaryText: '取消',
        icon: 'info',
      });
      if (r === false) return;
      if (r === true) el.value = el.value.replace(/\s+$/, '') + '\n\n' + text;
      else el.value = text;
    } else {
      el.value = text;
    }
    this.appendLog(`[DeAI] 已拖入 ${text.length} 字`);
    // v4.3.1 (UX #2): 拖入成功 toast
    this.showToast(`已拖入 ${text.length} 字`, 'success');
  },

  _updateDeaiCharCount() {
    for (const [id, counter] of [['deai-input', 'deai-input-chars'],
                                 ['deai-sample', 'deai-sample-chars']]) {
      const el = document.getElementById(id);
      const out = document.getElementById(counter);
      if (!el || !out) continue;
      const len = el.value.length;
      out.textContent = len
        ? `${len} 字 · 预计分 ${this._deaiChunkEstimate(len)} 块`
        : '0 字';
    }
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
          // v4.3.1 (UX #2): 复制成功 toast (结果对比页无日志区)
          this.showToast('已复制到剪贴板', 'success');
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
      // v4.3.1 (UX #2): fallback 成功同样要 toast
      this.showToast('已复制到剪贴板', 'success');
    } catch (e) {
      this.appendLog('[错误] 复制失败: ' + e);
      // v4.3.1 (UX #2): 失败 toast
      this.showToast('复制失败: ' + e, 'error');
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
        // v4.3.1 (UX #2): 导出成功 toast (只报文件名, 完整路径进日志)
        this.showToast('已导出: ' + String(r.path || '').split(/[\\/]/).pop(), 'success');
      } else if (r.cancelled) {
        // v4.3.1 (UX #2): 用户取消不打扰, 只记日志
        this.appendLog('[导出] 用户取消保存');
      } else {
        this.appendLog(`[错误] 导出失败: ${r.error}`);
        this.showToast('导出失败: ' + (r.error || '未知'), 'error');
      }
    } catch (e) {
      this.appendLog('[错误] 导出失败: ' + e);
      this.showToast('导出失败: ' + e, 'error');
    }
  },

  // ====== 日志 ======
  appendLog(msg) {
    const el = document.getElementById('log-output');
    if (!el) return;
    const time = new Date().toLocaleTimeString('zh-CN', {hour12: false});
    el.textContent += `[${time}] ${msg}\n`;
    // v4.1.8.2 (审计 F23): 日志上限 500 行 — 旧版无上限增长, 长会话内存
    // 与每次 textContent 全量重建都在恶化
    const lines = el.textContent.split('\n');
    if (lines.length > 500) {
      el.textContent = lines.slice(lines.length - 500).join('\n');
    }
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
    const ok = await this.saveConfig({silent: true});
    // v4.1.8.2 (审计 F17): 保存失败回滚 dirty 并重试 — 旧版先清 dirty 再保存,
    // 失败后这批修改既没落盘也不会再触发 beforeunload 兜底, 永久丢失
    if (!ok) {
      this.configDirty = true;
      this.configSaveTimer = setTimeout(() => this.autoSaveConfig(), 2000);
    }
  },

  // v4.3.1 (UX #9): triggerBtn = 触发点击的那个按钮 — 反馈 (✓ 已保存 2 秒)
  // 作用于它, 不再硬取 btn-save-config (校对参数页 js-save-config 点击时
  // 反馈跑到 API 页, 本页毫无回音); 不传则兜底 btn-save-config
  async saveConfigNow(triggerBtn) {
    if (!this.urlValid) {
      this.appendLog('[错误] URL 格式无效,无法保存');
      // v4.3.1 (UX #9): 参数页等无日志区可见的失败原因
      this.showToast('URL 格式无效，无法保存', 'error');
      return;
    }
    this.configDirty = false;
    if (this.configSaveTimer) clearTimeout(this.configSaveTimer);
    const ok = await this.saveConfig({silent: false});
    // v4.1.8.2 (审计 F17): 失败回滚 dirty, 允许后续重试/beforeunload 兜底
    if (!ok) this.configDirty = true;
    // v4.1.6 (P4): 显式保存按钮文案变 "✓ 已保存" 2 秒, 给用户一个明确视觉反馈.
    const btn = triggerBtn || document.getElementById('btn-save-config');
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

  // v4.1.6 (P1+P2): 抽 helper, 12 字段从 DOM 一次性收集.
  // 复用场景: saveConfig (异步) + beforeunload (同步 fire-and-forget).
  // v4.1.8.2 (审计 F8): 数值字段统一 NaN 兜底 + min/max 钳制 — HTML min/max
  // 挡不住手输, concurrency=0 会让后端 Semaphore(0) 永久死锁
  _clampNum(raw, fallback, min, max, isInt) {
    let v = isInt ? parseInt(raw, 10) : parseFloat(raw);
    if (Number.isNaN(v)) v = fallback;
    return Math.max(min, Math.min(max, v));
  },

  _collectAllConfig() {
    return {
      api_base:           this.getVal('cfg-api-base'),
      api_key:            this.getVal('cfg-api-key'),
      model:              this.getVal('cfg-model'),
      prompt_mode:        this.getVal('cfg-prompt-mode'),
      temperature:        this._clampNum(this.getVal('cfg-temperature'), 0.1, 0, 2, false),
      concurrency:        this._clampNum(this.getVal('cfg-concurrency'), 2, 1, 16, true),
      max_retries:        this._clampNum(this.getVal('cfg-max-retries'), 3, 0, 10, true),
      timeout:            this._clampNum(this.getVal('cfg-timeout'), 120, 10, 300, true),
      chunking_preset:    this.getVal('cfg-chunking-preset'),
      context_max_chars:  this._clampNum(this.getVal('cfg-context-max-chars'), 800, 200, 2000, true),
      context_max_chunks: this._clampNum(this.getVal('cfg-context-max-chunks'), 2, 1, 5, true),
      custom_prompt:      this.getVal('cfg-custom-prompt'),
      // v4.3.3: 本地标点修复开关 (checkbox; 元素缺失时回退当前配置 —
      // 默认 True 字段不能在 DOM 缺失时被静默写成 False, 评审 E-3)
      punct_fix:          (() => {
        const cb = document.getElementById('cfg-punct-fix');
        return cb ? cb.checked : (this.config.punct_fix !== false);
      })(),
      // v4.3.4: 标点修复 v2 规则选项 (checkbox 缺失时回退当前配置)
      punct_quote_style:  this.getVal('cfg-punct-quote-style') || this.config.punct_quote_style || 'curly',
      punct_fullwidth_alnum: (() => {
        const cb = document.getElementById('cfg-punct-fullwidth-alnum');
        return cb ? cb.checked : (this.config.punct_fullwidth_alnum !== false);
      })(),
      punct_repeat_compress: (() => {
        const cb = document.getElementById('cfg-punct-repeat-compress');
        return cb ? cb.checked : (this.config.punct_repeat_compress === true);
      })(),
      punct_dash_tilde: (() => {
        const cb = document.getElementById('cfg-punct-dash-tilde');
        return cb ? cb.checked : (this.config.punct_dash_tilde !== false);
      })(),
    };
  },

  async saveConfig(opts = {}) {
    const updates = this._collectAllConfig();
    const entries = Object.entries(updates);
    // v4.1.8.2 (审计 F11): 改回串行 await — pywebview 6.2.1 每个 JS 调用起
    // 独立线程且无顺序保证, 旧版 Promise.all 并发 12 个调用时 save_config
    // 线程可能先于部分 set_config 执行, 落盘的是混合旧值
    let failCount = 0;
    let failDetail = '';
    for (const [k, v] of entries) {
      try {
        const r = await window.pywebview.api.set_config(k, v);
        // v4.1.8.2 (审计 B9): set_config 返回 {ok, error}, 失败计入
        if (r && r.ok === false) {
          failCount++;
          failDetail += `${k}: ${r.error || '未知'}; `;
        }
      } catch (e) {
        failCount++;
        failDetail += `${k}=${e}; `;
      }
    }
    if (failCount) {
      this.appendLog(`[错误] set_config 失败 (${failCount}/${entries.length}): ${failDetail}`);
    }
    try {
      // v4.1.6 (P3): save_config 返回 {ok, error}, 失败时不静默吞错.
      const r = await window.pywebview.api.save_config();
      if (!r || !r.ok) {
        this.appendLog(`[错误] save_config: ${(r && r.error) || '返回无 ok 字段'}`);
        return false;
      }
      this.config = await window.pywebview.api.get_config();
      // v4.1 (I5): config 变了, 主页 chunking 只读 label 也要同步刷新
      this.renderChunkingDisplay();
      // v4.1.6 (P5): 始终显示保存反馈 (silent 模式也打, 用户知道后台已经落了盘).
      this.appendLog(`[设置] 已保存 (${entries.length} 字段)`);
      return true;
    } catch (e) {
      this.appendLog('[错误] save_config 异常: ' + e);
      return false;
    }
  },

  toggleKeyVisibility() {
    const input = document.getElementById('cfg-api-key');
    if (input) input.type = input.type === 'password' ? 'text' : 'password';
  },

  async fetchModels() {
    const base = this.getVal('cfg-api-base');
    const key = this.getVal('cfg-api-key');
    const fetchBtn = document.getElementById('btn-fetch-models');
    this.appendLog('[测试] 拉取模型列表...');
    // v4.3.1 (UX #3): 拉取中禁用按钮 (⟳ 图标按钮文字不变, 禁用即足够)
    if (fetchBtn) fetchBtn.disabled = true;
    // v4.1 (I3): 改异步, 立即拿 task_id, 后端跑 requests.get, 完成推 onFetchModelsComplete
    try {
      const r = await window.pywebview.api.fetch_models(base, key);
      if (r && r.ok) {
        this._pendingFetchTaskId = r.task_id;
        this.appendLog(`[测试] 后台拉取中 (task_id=${r.task_id})...`);
      } else {
        this.appendLog(`[错误] 启动拉取失败: ${r.error || '未知'}`);
        // v4.3.1 (UX #3): 启动失败立即恢复按钮 (旧版点了失败按钮卡死不可再点)
        if (fetchBtn) fetchBtn.disabled = false;
      }
    } catch (e) {
      this.appendLog('[错误] fetch_models 失败: ' + e);
      if (fetchBtn) fetchBtn.disabled = false;
    }
  },

  // v4.3.1 (UX #3): 内联连接结果 — 写入 API 卡片 #api-conn-result (绿=成功 红=失败)
  _showConnResult(text, ok) {
    const el = document.getElementById('api-conn-result');
    if (!el) return;
    el.textContent = text;
    el.className = 'form-hint ' + (ok ? 'conn-ok' : 'conn-fail');
  },

  // v4.3.1 (UX #3): 恢复"测试连接"按钮文案与可用态
  _restoreTestConnBtn() {
    const btn = document.getElementById('btn-test-connection');
    if (btn && btn.dataset.origLabel) {
      btn.textContent = btn.dataset.origLabel;
      btn.disabled = false;
    }
  },

  // v4.1 (I3): fetch_models / test_connection 完成后回调
  handleFetchModelsComplete(data) {
    if (!data) return;
    // v4.1.8.2 (审计 F12/B8): onFetchModelsComplete 已入 MULTI_ALLOWED 不再
    // 同名覆盖, 两个 pending id 各自按 task_id 精确路由; 删除旧的空 if 死块
    const isTest = this._pendingTestTaskId === data.task_id;
    if (isTest) this._pendingTestTaskId = null;
    else if (this._pendingFetchTaskId === data.task_id) this._pendingFetchTaskId = null;
    else {
      // 两个 pending id 都不匹配: 旧任务晚到, 忽略
      return;
    }
    // v4.3.1 (UX #3): fetch 分支结束即恢复拉取按钮 (test 分支的按钮由
    // _restoreTestConnBtn 恢复, 不在此动以免误启用还在飞的测试)
    const fetchBtn = document.getElementById('btn-fetch-models');
    if (fetchBtn && !isTest) fetchBtn.disabled = false;
    if (data.ok) {
      if (isTest) {
        this.appendLog(`[测试] 连接成功, 发现 ${data.count} 个模型`);
        // v4.3.1 (UX #3): 结果内联显示 (绿字), 不再只进校对页日志
        this._showConnResult(`连接成功，发现 ${data.count} 个模型`, true);
        this._restoreTestConnBtn();
        return;
      }
      // v4.3.2: Model 双框合一 — 拉取结果填进 datalist, 点输入框右侧箭头
      // 原生下拉直接选择 (选中触发 input 事件 -> 走既有防抖自动保存)
      const dl = document.getElementById('model-datalist');
      if (dl) {
        dl.innerHTML = '';
        for (const m of (data.models || [])) {
          const opt = document.createElement('option');
          opt.value = m;
          dl.appendChild(opt);
        }
        this.showToast(`已获取 ${data.count} 个模型: 点 Model 输入框右侧箭头直接选择`, 'info');
      }
      this.appendLog(`[测试] 成功, 发现 ${data.count} 个模型`);
    } else {
      this.appendLog(`[${isTest ? '测试' : '错误'}] 失败: ${data.error}`);
      // v4.3.1 (UX #3): 失败红字内联显示原因 + 恢复测试按钮
      if (isTest) {
        this._showConnResult('连接失败: ' + (data.error || '未知'), false);
        this._restoreTestConnBtn();
      }
    }
  },

  async testConnection() {
    const base = this.getVal('cfg-api-base');
    const key = this.getVal('cfg-api-key');
    const btn = document.getElementById('btn-test-connection');
    this.appendLog('[测试] 测试连接...');
    // v4.3.1 (UX #3): 点击立即置"测试中…"禁用 — 旧版点了没有任何变化像坏了
    if (btn) {
      if (!btn.dataset.origLabel) btn.dataset.origLabel = btn.textContent;
      btn.textContent = '测试中…';
      btn.disabled = true;
    }
    // v4.3.1 (UX #3): 内联结果行同步显示进行中状态 (中性灰, 不带红绿)
    const resultEl = document.getElementById('api-conn-result');
    if (resultEl) {
      resultEl.textContent = '测试中…';
      resultEl.className = 'form-hint';
    }
    // v4.1 (I3): 也走异步, 通过 onFetchModelsComplete 拿到结果
    try {
      const r = await window.pywebview.api.test_connection(base, key);
      if (r && r.ok) {
        this._pendingTestTaskId = r.task_id;
        this.appendLog(`[测试] 后台测试中 (task_id=${r.task_id})...`);
      } else {
        this.appendLog(`[测试] 失败: ${r.error || '未知'}`);
        // v4.3.1 (UX #3): 启动失败 — 内联红字 + 恢复按钮
        this._showConnResult('连接失败: ' + ((r && r.error) || '未知'), false);
        this._restoreTestConnBtn();
      }
    } catch (e) {
      this.appendLog('[错误] test_connection 失败: ' + e);
      this._showConnResult('连接失败: ' + e, false);
      this._restoreTestConnBtn();
    }
  },

  applyTemplate(name) {
    if (!name) return;
    const tpl = this.apiTemplates.find(t => t.name === name);
    if (!tpl) return;
    this.setVal('cfg-api-base', tpl.api_base);
    this.setVal('cfg-model', tpl.model);
    // v4.1.8.2 (审计 F18): 输入框已有 key 时不覆盖 — 所有模板都定义了占位
    // api_key (sk-/EMPTY/ollama), 旧版选模板即把用户真实 key 静默替换并自动落盘
    const currentKey = this.getVal('cfg-api-key');
    if (tpl.api_key !== undefined && !currentKey) {
      this.setVal('cfg-api-key', tpl.api_key);
    }
    this.validateApiBase();
    this.markConfigDirty();
    this.appendLog(`[模板] 已应用: ${name}${currentKey ? ' (保留已有 API Key)' : ''}`);
  },

  // ====== DeAI 3 步 (v4.3.0: 运行中按钮=取消 + 超大文本确认) ======
  async _deaiStepFlow(step, getText, startApi) {
    // 运行中点击 = 取消该任务 (评审#7: 防重复启动)
    if (this.deai['running' + step]) {
      const r = await window.pywebview.api.deai_cancel(this.deai['step' + step + 'TaskId']);
      if (r && r.ok) {
        this.appendLog('[DeAI] 取消请求已发送 (当前块完成后停止)');
      } else {
        this.appendLog('[DeAI] 取消失败: ' + ((r && r.error) || '未知'));
        this.deai['running' + step] = false;
      }
      return;
    }
    const text = getText();
    if (!text) { this.appendLog('[DeAI] 请先输入文本'); return; }
    if (!(await this._confirmLargeDeaiText(text))) return;
    this.setDeaiStepUI(step, 'running', '调用 LLM 中...');
    this.deai['running' + step] = true;
    try {
      const taskId = await startApi(text);
      this.deai['step' + step + 'TaskId'] = taskId;
    } catch (e) {
      this.deai['running' + step] = false;
      this.setDeaiStepUI(step, 'error', String(e));
    }
  },

  async deaiStep1() {
    await this._deaiStepFlow(1, () => this.getVal('deai-input'),
      (t) => window.pywebview.api.deai_step1_detect(t, this.deai.styleCardSlug));
  },

  async deaiStep2() {
    await this._deaiStepFlow(2, () => this.getVal('deai-input'),
      (t) => window.pywebview.api.deai_step2_rewrite(
        t, this.getVal('deai-sample'), this.deai.styleCardSlug));
  },

  async deaiStep3() {
    const rewritten = this.getDeaiOutput(2);
    await this._deaiStepFlow(3, () => rewritten,
      (t) => window.pywebview.api.deai_step3_audit(
        t, this.deai.styleCardSlug,
        // v4.3.0: step2 超长落盘模式引用后端文件, 全文不过 IPC
        this.deai.step2File ? this.deai.step2TaskId : ''));
  },

  // 超大文本确认 (评审#6): > 20 万字弹框, 给出预计调用次数
  async _confirmLargeDeaiText(text) {
    if (text.length <= 200000) return true;
    const blocks = this._deaiChunkEstimate(text.length);
    return await this.showConfirmDialog({
      title: '超大文本',
      body: `共 ${text.length} 字, 按当前分块预设预计分 ${blocks} 块, ` +
            `每步 ${blocks} 次 LLM 调用 (3 步约 ${blocks * 3} 次), 耗时较长且消耗较多 token。继续?`,
      primaryText: '继续',
      secondaryText: '取消',
      icon: 'info',
    });
  },

  // 预计块数 (与后端 whole_file 兜底逻辑一致)
  _deaiChunkEstimate(len) {
    const preset = this.config.chunking_preset || 'balanced';
    const found = (this.chunkingPresets || []).find(p => p.key === preset);
    let maxChars = found ? found.max_chars : 3000;
    if (!maxChars && len > 20000) maxChars = 6000;
    if (!maxChars) return 1;
    return Math.max(1, Math.ceil(len / maxChars));
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
    // 按钮联动 — v4.1.8.2 (审计 F26): 只动自己的按钮.
    // v4.3.0 (评审#7): running 态按钮可点 = 取消该任务; 其它态恢复原文案.
    const ownBtn = document.getElementById('btn-deai-step' + step);
    if (ownBtn) {
      if (state === 'running') {
        if (!ownBtn.dataset.origLabel) ownBtn.dataset.origLabel = ownBtn.textContent;
        ownBtn.textContent = '取消';
        ownBtn.disabled = false;
      } else {
        if (ownBtn.dataset.origLabel) ownBtn.textContent = ownBtn.dataset.origLabel;
        ownBtn.disabled = false;
      }
    }
  },

  handleDeaiStream(data) {
    if (!data || !data.task_id) return;
    // v4.3.0: 分块进度显示; 超长时 partial 已是后端降级的尾部预览, 直接渲染
    const status = data.progress
      ? `生成中… 块 ${data.progress.chunk}/${data.progress.total}`
      : '生成中...';
    if (data.task_id === this.deai.step1TaskId) {
      this.setDeaiOutput(1, data.partial);
      this.setDeaiStepUI(1, 'running', status);
    } else if (data.task_id === this.deai.step2TaskId) {
      this.setDeaiOutput(2, data.partial);
      this.setDeaiStepUI(2, 'running', status);
    } else if (data.task_id === this.deai.step3TaskId) {
      this.setDeaiOutput(3, data.partial);
      this.setDeaiStepUI(3, 'running', status);
    }
  },

  // v4.1.7: 复用 onDeaiStream 路由, 如果 step='distill' 转给 distill handler
  // v4.1.8.2 (审计 F28): distill 事件按 task_id 精确路由 — 旧版只看 step,
  // 并发蒸馏多个 profile 时状态文本互相覆盖
  handleDeaiStreamOrDistill(data) {
    if (data && data.step === 'distill') {
      if (this.deai.distillTaskId && data.task_id === this.deai.distillTaskId) {
        this.handleDeaiDistillStream(data);
      }
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
    // v4.1.8.2 (审计 F28): 按 task_id 精确路由, 忽略旧蒸馏任务
    if (data.step === 'distill') {
      if (!this.deai.distillTaskId || data.task_id !== this.deai.distillTaskId) return;
      this.deai.distillTaskId = null;
      // v4.3.1 (UX #13): 蒸馏收尾清 running 标志 + 恢复按钮原文案
      this.deai.distillRunning = false;
      const status = document.getElementById('deai-distill-status');
      if (status) {
        status.textContent = `蒸馏完成: ${data.card_chars} 字符 (${data.distilled_at})`;
      }
      this._restoreDistillBtn();
      // 重新计算蒸馏按钮可用态 (distillTaskId 已清, 按 samples 数判定)
      this.selectStyleProfile(this.deai.styleCardSlug);
      this.appendLog(`[DeAI] 蒸馏完成: ${data.slug} (${data.card_chars} 字符)`);
      // v4.3.1 (UX #2): 蒸馏完成 toast (任务跑 10-30s, 用户可能切到别的页)
      this.showToast(`蒸馏完成: ${data.slug}（${data.card_chars} 字符）`, 'success');
      this.loadStyleProfiles();  // 刷新列表里的 distilled_at 标记
      return;
    }
    if (data.task_id === this.deai.step1TaskId) {
      this.deai.running1 = false;
      this.deai.step1File = (data.truncated && data.result_file) ? data.result_file : null;
      this.setDeaiOutput(1, data.result || '');
      this.setDeaiStepUI(1, 'done', data.truncated ? `已完成 (完整 ${data.total_len} 字已存盘)` : '已完成');
      const copyBtn = document.getElementById('btn-deai-copy-1');
      if (copyBtn) copyBtn.disabled = false;
      // 解锁 step 2
      const btn2 = document.getElementById('btn-deai-step2');
      if (btn2) btn2.disabled = false;
      const status2 = document.getElementById('deai-status-2');
      if (status2) { status2.textContent = '可运行'; status2.className = 'deai-step-status status-ready'; }
    } else if (data.task_id === this.deai.step2TaskId) {
      this.deai.running2 = false;
      this.deai.step2File = (data.truncated && data.result_file) ? data.result_file : null;
      // 超长落盘模式: lastResult 只是头部预览, 复制/导出走 deai_copy/save_result
      this.deai.lastResult = data.result || '';
      this.setDeaiOutput(2, data.result || '');
      this.setDeaiStepUI(2, 'done', data.truncated ? `已完成 (完整 ${data.total_len} 字已存盘)` : '已完成');
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
      this.deai.running3 = false;
      this.deai.step3File = (data.truncated && data.result_file) ? data.result_file : null;
      this.setDeaiOutput(3, data.result || '');
      this.setDeaiStepUI(3, 'done', data.truncated ? `已完成 (完整 ${data.total_len} 字已存盘)` : '已完成');
      const copyBtn = document.getElementById('btn-deai-copy-3');
      if (copyBtn) copyBtn.disabled = false;
    }
  },

  handleDeaiError(data) {
    if (!data || !data.task_id) return;
    // v4.3.0 (评审#3): 取消分流 — 结构化 cancelled 标志, 不与失败混淆
    if (data.cancelled) {
      this.appendLog('[DeAI] 已取消 (已完成部分已保留)');
      // v4.3.1 (UX #13): 蒸馏取消 — 在 step1-3 循环前按 task_id 精确拦截,
      // 恢复按钮文案/可用态 (旧版取消分支只匹配 step1-3, 蒸馏按钮卡在"取消")
      if (data.step === 'distill') {
        if (this.deai.distillTaskId && data.task_id !== this.deai.distillTaskId) return;
        this.deai.distillTaskId = null;
        this.deai.distillRunning = false;
        const dstatus = document.getElementById('deai-distill-status');
        if (dstatus) dstatus.textContent = '已取消';
        this._restoreDistillBtn();
        this.selectStyleProfile(this.deai.styleCardSlug);
        return;
      }
      for (const step of [1, 2, 3]) {
        if (data.task_id === this.deai['step' + step + 'TaskId']) {
          this.deai['running' + step] = false;
          // 已完成的中间结果填回输出框 (保留部分成果)
          if (data.partial && !data.partial.startsWith('…(内容过长')) {
            this.setDeaiOutput(step, data.partial);
          }
          const statusEl = document.getElementById('deai-status-' + step);
          if (statusEl) {
            statusEl.textContent = '已取消 (可重新运行)';
            statusEl.className = 'deai-step-status';
          }
          // setDeaiStepUI 恢复按钮原文案
          this.setDeaiStepUI(step, 'idle', '');
          break;
        }
      }
      return;
    }
    this.appendLog(`[DeAI 错误] ${data.error}`);
    // v4.3.1 (UX #2): 失败 toast — 步骤错误与蒸馏失败统一右下角提示
    // (用户可能停在校对页, 日志区不可见); 取消分支不打扰
    this.showToast((data.step === 'distill' ? '蒸馏失败: ' : '去 AI 味处理失败: ') + data.error, 'error');
    // v4.1.7: 蒸馏失败 — v4.1.8.2 (审计 F28): 按 task_id 精确路由
    if (data.step === 'distill') {
      if (this.deai.distillTaskId && data.task_id !== this.deai.distillTaskId) return;
      this.deai.distillTaskId = null;
      // v4.3.1 (UX #13): 失败同样清 running + 恢复按钮原文案
      this.deai.distillRunning = false;
      const status = document.getElementById('deai-distill-status');
      if (status) status.textContent = `蒸馏失败: ${data.error}`;
      this._restoreDistillBtn();
      this.selectStyleProfile(this.deai.styleCardSlug);
      return;
    }
    if (data.task_id === this.deai.step1TaskId) {
      this.deai.running1 = false;
      this.setDeaiStepUI(1, 'error', '错误: ' + data.error);
    } else if (data.task_id === this.deai.step2TaskId) {
      this.deai.running2 = false;
      this.setDeaiStepUI(2, 'error', '错误: ' + data.error);
    } else if (data.task_id === this.deai.step3TaskId) {
      this.deai.running3 = false;
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
    // v4.3.0: 超长落盘模式 — 后端直读文件写剪贴板, 全文不过前端
    const file = this.deai['step' + step + 'File'];
    if (file && window.pywebview && window.pywebview.api && window.pywebview.api.deai_copy_result) {
      const r = await window.pywebview.api.deai_copy_result(this.deai['step' + step + 'TaskId']);
      if (r && r.ok) {
        this.appendLog(`[DeAI] 已复制 Step ${step} 完整结果 (${r.length} 字符)`);
        // v4.3.1 (UX #2): 落盘文件模式复制成功 toast
        this.showToast('已复制到剪贴板', 'success');
        return;
      }
      this.appendLog('[提示] 完整结果复制失败 (' + ((r && r.error) || '未知') + '), 尝试当前显示内容');
    }
    const text = this.getDeaiOutput(step);
    if (!text) return;
    // v4.1.3 (I1): 同样优先 Python Win32 剪贴板, 失败 fallback
    if (window.pywebview && window.pywebview.api && window.pywebview.api.copy_to_clipboard) {
      try {
        const r = await window.pywebview.api.copy_to_clipboard(text);
        if (r && r.ok) {
          this.appendLog(`[DeAI] 已复制 Step ${step} 结果 (${r.length} 字符)`);
          // v4.3.1 (UX #2): 普通模式复制成功 toast
          this.showToast('已复制到剪贴板', 'success');
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
      // v4.3.1 (UX #2): fallback 成功同样要 toast
      this.showToast('已复制到剪贴板', 'success');
    } catch (e) {
      this.appendLog('[错误] 复制失败: ' + e);
      this.showToast('复制失败: ' + e, 'error');
    }
  },

  async exportDeaiResult() {
    const fmt = this.getVal('deai-export-fmt') || 'txt';
    // v4.3.0: 超长落盘模式 — 后端直读文件弹保存框, 全文不过前端
    if (this.deai.step2File && this.deai.step2TaskId) {
      try {
        const r = await window.pywebview.api.deai_save_result(this.deai.step2TaskId, fmt);
        if (r && r.ok) {
          this.appendLog(`[DeAI] 已导出完整结果: ${r.path}`);
          // v4.3.1 (UX #2): 落盘文件模式导出成功 toast
          this.showToast('已导出: ' + String(r.path || '').split(/[\\/]/).pop(), 'success');
          return;
        }
        if (r && r.cancelled) { this.appendLog('[DeAI] 用户取消保存'); return; }  // 取消不打扰
        this.appendLog('[DeAI 错误] 导出失败: ' + (r && r.error));
        this.showToast('导出失败: ' + ((r && r.error) || '未知'), 'error');
      } catch (e) {
        this.appendLog('[错误] 导出失败: ' + e);
        this.showToast('导出失败: ' + e, 'error');
      }
      return;
    }
    const text = this.deai.lastResult || this.getDeaiOutput(2);
    if (!text) return;
    try {
      // v4.1.4: 传空 file_path, 后端 export_result 走 DeAI fallback 路径
      // (默认位置 = home/Documents, 默认文件名 = deai_result-YYMMDD-HHMMSS.<ext>)
      // 之前用 'deai_result.xxx' hack 路径会让默认位置指向 cwd, 用户体验差
      const r = await window.pywebview.api.export_result('', text, fmt);
      if (r.ok) {
        this.appendLog(`[DeAI] 已导出: ${r.path}`);
        // v4.3.1 (UX #2): 普通模式导出成功 toast
        this.showToast('已导出: ' + String(r.path || '').split(/[\\/]/).pop(), 'success');
      } else if (r.cancelled) {
        this.appendLog('[DeAI] 用户取消保存');
      } else {
        this.appendLog(`[DeAI 错误] 导出失败: ${r.error}`);
        this.showToast('导出失败: ' + (r.error || '未知'), 'error');
      }
    } catch (e) {
      this.appendLog('[错误] 导出失败: ' + e);
      this.showToast('导出失败: ' + e, 'error');
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
      // v4.3.1 (UX #12): 风格库页 Profile 列表卡片同步刷新
      this.renderStyleProfileList();
    } catch (e) {
      this.appendLog('[DeAI 错误] 加载风格 profile 失败: ' + e);
    }
  },

  renderStyleProfileSelect() {
    // v4.2.0: Profile 下拉在「去 AI 味」与「风格库」两页各有一个镜像,
    // 同一数据源同时填充并保持选中一致
    for (const sel of [document.getElementById('deai-style-profile'),
                       document.getElementById('styles-profile-select')]) {
      if (sel) this._fillStyleProfileSelect(sel);
    }
    // 恢复选中态
    for (const sel of [document.getElementById('deai-style-profile'),
                       document.getElementById('styles-profile-select')]) {
      if (sel && this.deai.styleCardSlug) sel.value = this.deai.styleCardSlug;
    }
  },

  _fillStyleProfileSelect(sel) {
    if (!sel) return;
    sel.innerHTML = '<option value="">-- 不选, 用默认 --</option>';
    const optgroupBuiltin = document.createElement('optgroup');
    // v4.1.8.2 (审计 C9): 套数动态取, 不再硬编码
    optgroupBuiltin.label = `预置 (${(this.deai.styleProfiles.builtin || []).length} 套)`;
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

  // v4.3.1 (UX #12): 风格库页 Profile 列表 — custom profile 一行一项,
  // 带「查看」(9 轴风格卡) 与「删除」入口; builtin 为只读预置, 只在上游下拉可选
  renderStyleProfileList() {
    const host = document.getElementById('styles-profile-list');
    if (!host) return;
    host.innerHTML = '';
    const customs = this.deai.styleProfiles.custom || [];
    if (customs.length === 0) {
      const empty = document.createElement('div');
      empty.className = 'stats-secondary';
      empty.textContent = '暂无自定义 profile (上方新建并加 3 篇范文后可蒸馏)';
      host.appendChild(empty);
      return;
    }
    for (const p of customs) {
      const row = document.createElement('div');
      row.className = 'style-profile-item';
      // p: {key, name, samples_count, distilled_at} — 蒸馏时间只显示日期部分
      const meta = document.createElement('span');
      meta.className = 'style-profile-item-meta';
      const distilledAt = p.distilled_at ? String(p.distilled_at).slice(0, 10) : '';
      meta.textContent = `${p.name}（${p.samples_count} 篇 / ${p.distilled_at ? '已蒸馏·' + distilledAt : '未蒸馏'}）`;
      meta.title = p.key;
      const actions = document.createElement('span');
      actions.className = 'style-profile-item-actions';
      const viewBtn = document.createElement('button');
      viewBtn.type = 'button';
      viewBtn.className = 'btn btn-standard btn-subtle';
      viewBtn.textContent = '查看';
      viewBtn.title = '查看蒸馏出的 9 轴风格卡';
      viewBtn.addEventListener('click', () => this._showStyleCard(p.key));
      const delBtn = document.createElement('button');
      delBtn.type = 'button';
      delBtn.className = 'btn btn-standard btn-subtle';
      delBtn.textContent = '删除';
      delBtn.title = '删除该 profile (含范文与风格卡)';
      delBtn.addEventListener('click', () => this._deleteStyleProfile(p.key, p.name));
      actions.appendChild(viewBtn);
      actions.appendChild(delBtn);
      row.appendChild(meta);
      row.appendChild(actions);
      host.appendChild(row);
    }
  },

  // v4.3.1 (UX #12): 删除 custom profile — 危险操作走 ContentDialog (danger),
  // 删除的是当前选中项时先清选定再刷新
  async _deleteStyleProfile(slug, name) {
    const confirmed = await this.showConfirmDialog({
      title: '删除 Profile?',
      body: `将删除「${name || slug}」的 profile 目录、全部范文与已蒸馏的风格卡，不可恢复。`,
      primaryText: '删除',
      secondaryText: '取消',
      icon: 'warning',
      danger: true,
    });
    if (!confirmed) return;
    try {
      const r = await window.pywebview.api.delete_style_profile(slug);
      if (r && r.ok) {
        this.appendLog(`[DeAI] 已删除 profile: ${slug}`);
        this.showToast(`已删除 profile: ${name || slug}`, 'success');
        if (this.deai.styleCardSlug === slug) await this.selectStyleProfile('');
        await this.loadStyleProfiles();
      } else {
        this.appendLog(`[DeAI 错误] 删除失败: ${r && r.error}`);
        this.showToast('删除失败: ' + ((r && r.error) || '未知'), 'error');
      }
    } catch (e) {
      this.appendLog('[DeAI 错误] delete_style_profile: ' + e);
      this.showToast('删除失败: ' + e, 'error');
    }
  },

  // v4.3.1 (UX #12): 查看 9 轴风格卡 — 直接操作 dialog-root (showConfirmDialog
  // 的 body 只适合一两行文本, 风格卡是长 markdown, 需要 pre-wrap + 限高滚动);
  // 复用同一对话框骨架: 只留"关闭"次按钮, 关闭时还原被改动的 class/hidden
  _showStyleCard(slug) {
    const root = document.getElementById('dialog-root');
    const titleEl = document.getElementById('dialog-title-text');
    const bodyEl = document.getElementById('dialog-body-text');
    const iconEl = document.getElementById('dialog-icon');
    const btnP = document.getElementById('dialog-btn-primary');
    const btnS = document.getElementById('dialog-btn-secondary');
    const btnC = document.getElementById('dialog-btn-close');
    if (!root || !titleEl || !bodyEl || !btnP || !btnS) return;
    window.pywebview.api.get_style_card(slug).then((r) => {
      if (!r || r.ok === false) {
        this.showToast('读取风格卡失败: ' + ((r && r.error) || '未知'), 'error');
        return;
      }
      // 同一 dialog-root 只有一个实例: 已有对话框在开时不叠加
      if (!root.hidden) return;
      titleEl.textContent = `风格卡: ${r.name || slug}`;
      bodyEl.textContent = r.card_markdown || '(风格卡为空)';
      bodyEl.classList.add('dialog-body-pre');
      if (iconEl) { iconEl.dataset.icon = 'document'; iconEl.className = 'nav-icon'; }
      btnP.hidden = true;
      if (btnC) btnC.hidden = true;
      btnS.textContent = '关闭';
      root.hidden = false;
      btnS.focus();
      const close = () => {
        root.hidden = true;
        // 还原共享元素, 不污染下次 showConfirmDialog
        bodyEl.classList.remove('dialog-body-pre');
        btnP.hidden = false;
        btnS.onclick = null;
        smoke.onclick = null;
        document.removeEventListener('keydown', onKey, true);
      };
      const onKey = (e) => { if (e.key === 'Escape') { e.stopPropagation(); close(); } };
      const smoke = root.querySelector('.dialog-smoke');
      btnS.onclick = close;
      smoke.onclick = close;
      document.addEventListener('keydown', onKey, true);
    }).catch((e) => {
      this.appendLog('[DeAI 错误] get_style_card: ' + e);
      this.showToast('读取风格卡失败: ' + e, 'error');
    });
  },

  async selectStyleProfile(slug) {
    this.deai.styleCardSlug = slug || '';
    // v4.3.1 (UX #11): 两页镜像下拉同步 — 触发侧 (去AI味页/风格库页任一) 变了,
    // 另一侧跟随同一选中, 旧版只更新触发侧会残留旧选中
    for (const sel of [document.getElementById('deai-style-profile'),
                       document.getElementById('styles-profile-select')]) {
      if (sel) sel.value = this.deai.styleCardSlug;
    }
    const info = document.getElementById('deai-profile-info');
    const btnAdd = document.getElementById('btn-deai-add-sample');
    const btnDistill = document.getElementById('btn-deai-distill');
    if (!slug) {
      if (info) info.textContent = '未选 profile (用默认 V5 prompt)';
      if (btnAdd) this._setDisabledReason(btnAdd, true, '');
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
      // v4.3.1 (UX #15): 禁用给原因 title — 预置为只读抽象风格
      if (btnAdd) this._setDisabledReason(btnAdd, true, '预置 Profile 为只读抽象风格, 不支持加范文/蒸馏');
      if (btnDistill) btnDistill.disabled = true;
    } else {
      // custom 分支: 启用并清掉 builtin 分支留下的禁用原因 title
      if (btnAdd) this._setDisabledReason(btnAdd, false, '');
      // 蒸馏条件: samples >= 3 (后端强制, 前端做提示)
      // v4.1.8.2 (审计 F28): 有蒸馏任务在跑时保持禁用 — 旧版切走再切回即
      // 重新可点, 可并发起第二个蒸馏
      if (btnDistill) {
        const samples = p ? (p.samples_count || 0) : 0;
        btnDistill.disabled = samples < 3 || !!this.deai.distillTaskId;
        if (samples < 3) {
          if (info) info.textContent += ` (还需 ${3 - samples} 篇才能蒸馏)`;
        }
      }
    }
  },

  async createStyleProfile() {
    const slug = this.getVal('deai-new-profile-slug').trim();
    const name = this.getVal('deai-new-profile-name').trim();
    // v4.3.1 (UX #2): 风格库页无日志区, 校验失败/成功/异常全走 toast
    if (!slug) { this.appendLog('[DeAI] 请输入 slug'); this.showToast('请输入 slug', 'error'); return; }
    if (!name) { this.appendLog('[DeAI] 请输入显示名'); this.showToast('请输入显示名', 'error'); return; }
    try {
      const r = await window.pywebview.api.create_style_profile(slug, name, '');
      if (r.ok) {
        this.appendLog(`[DeAI] 已创建 profile: ${slug}`);
        this.showToast(`已创建 profile: ${slug}`, 'success');
        this.setVal('deai-new-profile-slug', '');
        this.setVal('deai-new-profile-name', '');
        await this.loadStyleProfiles();
        // v4.3.1 (UX #11): 自动选上 — selectStyleProfile 已同步两页镜像下拉,
        // 旧版只 set deai 页 select, 风格库页下拉残留旧值
        this.selectStyleProfile(slug);
      } else {
        this.appendLog(`[DeAI 错误] 创建失败: ${r.error}`);
        this.showToast('创建失败: ' + (r.error || '未知'), 'error');
      }
    } catch (e) {
      this.appendLog('[DeAI 错误] create_style_profile: ' + e);
      this.showToast('创建 profile 失败: ' + e, 'error');
    }
  },

  async addSampleToProfile() {
    const slug = this.deai.styleCardSlug;
    if (!slug) { this.appendLog('[DeAI] 请先选定 custom profile'); this.showToast('请先选定 custom profile', 'error'); return; }
    const content = this.getVal('deai-sample-content').trim();
    if (!content) { this.appendLog('[DeAI] 范文内容不能为空'); this.showToast('范文内容不能为空', 'error'); return; }
    try {
      const r = await window.pywebview.api.add_sample_to_profile(slug, content, '');
      if (r.ok) {
        this.appendLog(`[DeAI] 已加范文 (${slug}): ${r.filename} (累计 ${r.samples_count} 篇)`);
        this.showToast(`已加范文（累计 ${r.samples_count} 篇）`, 'success');
        this.setVal('deai-sample-content', '');
        await this.loadStyleProfiles();
        await this.selectStyleProfile(slug);
      } else {
        this.appendLog(`[DeAI 错误] 加范文失败: ${r.error}`);
        this.showToast('加范文失败: ' + (r.error || '未知'), 'error');
      }
    } catch (e) {
      this.appendLog('[DeAI 错误] add_sample_to_profile: ' + e);
      this.showToast('加范文失败: ' + e, 'error');
    }
  },

  async distillStyleProfile() {
    // v4.3.1 (UX #13): 运行中点击 = 取消蒸馏 (与 3 步工作流同款交互, 防重复启动)
    if (this.deai.distillRunning) {
      const r = await window.pywebview.api.deai_cancel(this.deai.distillTaskId);
      if (r && r.ok) {
        this.appendLog('[DeAI] 蒸馏取消请求已发送 (下一个流式块后停止)');
        const statusEl = document.getElementById('deai-distill-status');
        if (statusEl) statusEl.textContent = '取消中...';
      } else {
        this.appendLog('[DeAI] 蒸馏取消失败: ' + ((r && r.error) || '未知'));
        this.deai.distillRunning = false;
        this.deai.distillTaskId = null;
        this._restoreDistillBtn();
      }
      return;
    }
    const slug = this.deai.styleCardSlug;
    if (!slug) { this.appendLog('[DeAI] 请先选定 custom profile'); this.showToast('请先选定 custom profile', 'error'); return; }
    const status = document.getElementById('deai-distill-status');
    const btn = document.getElementById('btn-deai-distill');
    if (status) status.textContent = '蒸馏中...';
    // v4.3.1 (UX #13): 按钮变"取消"可点 (旧版直接禁用, 跑 10-30s 无法中途取消)
    if (btn) {
      if (!btn.dataset.origLabel) btn.dataset.origLabel = btn.textContent;
      btn.textContent = '取消';
      btn.disabled = false;
    }
    this.deai.distillRunning = true;
    try {
      // v4.1.8.2 (审计 L5/F28): 后端现在返回 {ok, task_id|error} 并按 slug 去重
      const r = await window.pywebview.api.distill_style_profile(slug);
      if (!r || r.ok === false) {
        throw new Error((r && r.error) || '启动失败');
      }
      this.deai.distillTaskId = r.task_id;
      this.appendLog(`[DeAI] 蒸馏任务启动: ${r.task_id}`);
      // v4.3.1 (UX #2): 启动成功 info toast (蒸馏要 10-30s, 让用户知道已在跑)
      this.showToast('蒸馏任务已启动，完成后会提示', 'info');
    } catch (e) {
      this.deai.distillRunning = false;
      this.deai.distillTaskId = null;
      this._restoreDistillBtn();
      if (status) status.textContent = '蒸馏启动失败: ' + e;
      this.appendLog('[DeAI 错误] distill_style_profile: ' + e);
      // v4.3.1 (UX #2): 启动失败 toast
      this.showToast('蒸馏启动失败: ' + e, 'error');
    }
  },

  // v4.3.1 (UX #13): 蒸馏按钮恢复原文案 (dataset.origLabel 由启动时记录)
  _restoreDistillBtn() {
    const btn = document.getElementById('btn-deai-distill');
    if (btn && btn.dataset.origLabel) btn.textContent = btn.dataset.origLabel;
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
