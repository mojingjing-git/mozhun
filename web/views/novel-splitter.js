// web/views/novel-splitter.js — 小说切分视图 (v5.2b+)
//
// 借鉴自姊妹项目「小说分析器」frontend/src/pages/SplitterPage.vue 的形态
// (Apache-2.0 衍生, Copyright 2026 mojingjing-git; 见 docs/THIRD_PARTY_NOTICES.md §22)
//
// v5.2b 决策:
// - 走 App.splitter state, 复用 App.showToast / App.appendLog
// - 0 字段侵入 ProjectConfig (27→27), 选项只在前端页面内临时态
// - Bridge 调用走 try/catch, 失败显示人话原因
// - 路径 slug 化在 Python 端做, 前端只显示书名

(function () {
  'use strict';

  const splitter = {
    files: [],   // [{path, name, status, total, error, encodingWarning}]
    isRunning: false,

    // ====== 初始化 ======
    init() {
      this.bindEvents();
      this.log('小说切分视图已加载 (v5.2b)');
    },

    // ====== 事件绑定 ======
    bindEvents() {
      const addBtn = document.getElementById('btn-add-splitter-files');
      if (addBtn) addBtn.addEventListener('click', () => this.addFiles());

      const clearBtn = document.getElementById('btn-clear-splitter');
      if (clearBtn) clearBtn.addEventListener('click', () => this.clearAll());

      const batchBtn = document.getElementById('btn-batch-splitter');
      if (batchBtn) batchBtn.addEventListener('click', () => this.batchSplit());
    },

    // ====== 文件操作 ======
    async addFiles() {
      if (this.isRunning) {
        this.toast('切分进行中, 请先等待完成或取消', 'warn');
        return;
      }
      try {
        const paths = await window.pywebview.api.choose_files();
        if (!paths || paths.length === 0) return;
        for (const p of paths) {
          if (this.files.some(f => f.path === p)) continue;
          this.files.push({
            path: p,
            name: this.basename(p),
            status: 'idle',
            total: 0,
            error: '',
            encodingWarning: null,
          });
        }
        this.renderFileList();
        this.updateButtons();
        this.log(`已添加 ${paths.length} 本小说`);
      } catch (e) {
        this.toast('添加文件失败: ' + e, 'error');
        this.log('[小说切分] 添加文件失败: ' + e);
      }
    },

    clearAll() {
      this.files = [];
      this.renderFileList();
      this.updateButtons();
    },

    // ====== 单本预览 ======
    async previewFile(path) {
      try {
        const opts = this.collectOptions();
        const result = await window.pywebview.api.preview_splitter(path, opts);
        if (!result.ok) {
          this.toast('预览失败: ' + (result.error || '未知错误'), 'error');
          return;
        }
        // 渲染预览
        const card = document.getElementById('splitter-preview-card');
        const title = document.getElementById('splitter-preview-title');
        const out = document.getElementById('splitter-preview-output');
        title.textContent = `${this.basename(path)} - 共 ${result.total_chapters} 章 / ${result.total_words} 字 / 卷 ${result.total_volumes} / 去重 ${result.dedup_count}`;
        const lines = [];
        lines.push(`书名: ${result.metadata.title || '(未知)'}`);
        lines.push(`作者: ${result.metadata.author || '(未知)'}`);
        lines.push(`检测正则: ${result.pattern_name}  (${result.detected_pattern})`);
        lines.push(`预览 ${result.preview_count} 章:`);
        lines.push('');
        for (const ch of result.chapters) {
          const vol = ch.volume ? `[${ch.volume}] ` : '';
          lines.push(`${String(ch.index).padStart(4, '0')}. ${vol}${ch.title} (${ch.word_count} 字)`);
        }
        if (result.encoding_warning) {
          lines.push('');
          lines.push(`⚠ 编码警告: ${result.encoding_warning}`);
        }
        out.textContent = lines.join('\n');
        card.hidden = false;
      } catch (e) {
        this.toast('预览失败: ' + e, 'error');
      }
    },

    // ====== 批量切分 ======
    async batchSplit() {
      if (this.files.length === 0 || this.isRunning) return;
      this.isRunning = true;
      this.updateButtons();
      this.setStatus('processing');

      const opts = this.collectOptions();
      const paths = this.files.map(f => f.path);
      const book_names = this.files.map(f => f.name);

      const progress = document.getElementById('splitter-progress');
      const progressFill = document.getElementById('splitter-progress-fill');
      const progressStats = document.getElementById('splitter-progress-stats');
      progress.hidden = false;
      progressFill.style.width = '0%';
      progressStats.textContent = `开始切分 ${paths.length} 本...`;

      try {
        this.log(`开始批量切分 ${paths.length} 本...`);
        const result = await window.pywebview.api.batch_splitter(paths, book_names, opts);
        if (!result.ok) {
          this.toast('批量切分失败: ' + (result.error || '未知错误'), 'error');
          this.log('[小说切分] 批量切分失败: ' + (result.error || ''));
          this.setStatus('failed');
          return;
        }
        // 更新每本状态
        for (let i = 0; i < this.files.length; i++) {
          const f = this.files[i];
          const r = result.results[i];
          if (!r) continue;
          f.status = r.status === 'ok' ? 'done' : 'failed';
          f.total = r.total_chapters || 0;
          f.error = r.error || '';
          f.encodingWarning = r.encoding_warning || null;
        }
        progressFill.style.width = '100%';
        progressStats.textContent = `完成: ${result.success} 成功 / ${result.fail} 失败`;
        this.toast(`切分完成: ${result.success} 成功 / ${result.fail} 失败`, result.fail === 0 ? 'success' : 'warn');
        this.log(`批量切分完成: ${result.success} 成功 / ${result.fail} 失败`);
      } catch (e) {
        this.toast('批量切分异常: ' + e, 'error');
        this.log('[小说切分] 异常: ' + e);
        this.setStatus('failed');
      } finally {
        this.isRunning = false;
        this.renderFileList();
        this.updateButtons();
      }
    },

    // ====== 取消 ======
    async cancelSplit() {
      if (!this.isRunning) return;
      try {
        await window.pywebview.api.cancel_splitter();
        this.log('已发送取消信号');
        this.toast('已发送取消信号', 'info');
      } catch (e) {
        this.toast('取消失败: ' + e, 'error');
      }
    },

    // ====== 选项收集 ======
    collectOptions() {
      return {
        use_volume: document.getElementById('cfg-splitter-use-volume').checked,
        remove_ads: document.getElementById('cfg-splitter-remove-ads').checked,
        merge_tiny: document.getElementById('cfg-splitter-merge-tiny').checked,
        min_words: parseInt(document.getElementById('cfg-splitter-min-words').value, 10) || 0,
        max_words: parseInt(document.getElementById('cfg-splitter-max-words').value, 10) || 0,
      };
    },

    // ====== 渲染 ======
    renderFileList() {
      const list = document.getElementById('splitter-file-list');
      const count = document.getElementById('splitter-file-count');
      count.textContent = this.files.length;
      if (this.files.length === 0) {
        list.innerHTML = '<li class="file-list-empty">尚未添加文件 (点 + 添加小说 或拖入)</li>';
        return;
      }
      list.innerHTML = '';
      for (let i = 0; i < this.files.length; i++) {
        const f = this.files[i];
        const li = document.createElement('li');
        li.className = 'splitter-file-item';
        li.innerHTML = `
          <span class="file-name">${escapeHtml(f.name)}</span>
          <span class="file-status status-${f.status}">${this.statusLabel(f.status)}</span>
          <span class="file-info">${f.total ? f.total + ' 章' : ''}</span>
          <button class="btn btn-icon-only js-splitter-preview" data-idx="${i}" title="预览章节表">👁</button>
          <button class="btn btn-icon-only js-splitter-remove" data-idx="${i}" title="移除">✕</button>
        `;
        list.appendChild(li);
      }
      // 事件委托
      list.querySelectorAll('.js-splitter-preview').forEach(btn => {
        btn.addEventListener('click', () => this.previewFile(this.files[+btn.dataset.idx].path));
      });
      list.querySelectorAll('.js-splitter-remove').forEach(btn => {
        btn.addEventListener('click', () => this.removeFile(+btn.dataset.idx));
      });
    },

    removeFile(idx) {
      this.files.splice(idx, 1);
      this.renderFileList();
      this.updateButtons();
    },

    setStatus(status) {
      for (const f of this.files) {
        if (f.status === 'idle') f.status = status;
      }
      this.renderFileList();
    },

    statusLabel(s) {
      return {
        idle: '待切分',
        processing: '切分中',
        done: '✓ 完成',
        failed: '✗ 失败',
        cancelled: '已取消',
      }[s] || s;
    },

    updateButtons() {
      const clear = document.getElementById('btn-clear-splitter');
      const batch = document.getElementById('btn-batch-splitter');
      const hasFiles = this.files.length > 0;
      clear.disabled = !hasFiles || this.isRunning;
      batch.disabled = !hasFiles || this.isRunning;
    },

    // ====== 工具 ======
    basename(p) {
      if (!p) return '';
      // 兼容 Windows / POSIX
      const parts = p.replace(/\\/g, '/').split('/');
      return parts[parts.length - 1] || p;
    },

    // v5.4.3 (F15): 统一用小写 window.app。app.js 顶层语句 `window.app = App`
    // (app.js:3487) 只写小写, 旧版这里自建大写 window.App 空对象 → 两个
    // typeof 守卫恒假, 切分日志与 toast 永久走 console 分支 (build.spec console=False,
    // 用户什么都看不到)。守卫与调用点必须成对改: 只改守卫会让分支为真后
    // 在调用点抛 TypeError, 比现状更糟。
    log(msg) {
      if (window.app && typeof window.app.appendLog === 'function') {
        window.app.appendLog('[小说切分] ' + msg);
      } else {
        console.log('[小说切分] ' + msg);
      }
    },

    toast(msg, type) {
      if (window.app && typeof window.app.showToast === 'function') {
        window.app.showToast(msg, type || 'info');
      } else {
        console.log('[toast]', type || 'info', msg);
      }
    },

    // ====== 事件 (v5.4.3 F9) ======
    // 通用事件入口: app.js 的 dispatch 走 default: 分支把不认识的事件原样委派过来,
    // 这样 app.js 保持零 splitter 知识 (不新增 case, 不硬编码事件名)。
    // 返回 true = 已消费; false/未定义 = 不认识, 由 app.js 回落到 console.warn。
    onEvent(name, data) {
      if (name === 'onSplitterProgress') {
        this.handleProgress(data);
        return true;
      }
      return false;
    },

    // 进度条渲染。后端在 batch_splitter 的 await 期间按本推 (web_backend.py:2031),
    // 终态在返回前推 (web_backend.py:2050) —— 两路写者目标一致 (都收在 100% +
    // 成功/失败统计), 故交错无碍。
    handleProgress(data) {
      if (!data) return;
      const box = document.getElementById('splitter-progress');
      const fill = document.getElementById('splitter-progress-fill');
      const stats = document.getElementById('splitter-progress-stats');
      if (!box || !fill || !stats) return;
      box.hidden = false;
      const total = Number(data.total) || 0;
      const current = Number(data.current) || 0;
      if (data.stage === 'done') {
        // 终态固定 100% —— 若用 current/total 算, 失败本多时宽度不足 100% 会误导
        fill.style.width = '100%';
        stats.textContent = `完成: ${Number(data.success) || 0} 成功 / ${Number(data.fail) || 0} 失败`;
        return;
      }
      // processing 阶段: current 是 1-based (后端 enumerate(..., start=1)),
      // 即「正在切第 1 本」→ 1/total, 不需要 -1 修正。
      const pct = total > 0 ? Math.min(100, Math.round(current / total * 100)) : 0;
      fill.style.width = pct + '%';
      const book = data.book_name ? String(data.book_name) : '';
      stats.textContent = book
        ? `切分中 ${current}/${total}: ${book}`
        : `切分中 ${current}/${total}`;
    },
  };

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, c => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[c]));
  }

  // 暴露到 app.splitter (供 app.js 的 default: 事件委派 + 外部引用)
  // v5.4.3 (F15): 改挂小写 window.app —— 旧挂 window.App (大写) 是只写不读的
  // 孤儿对象。app.js 在 index.html:659 先加载且 window.app = App 是顶层语句,
  // 这里不会把已有实例覆盖成空对象 (index.html:661 在其后)。
  if (!window.app) window.app = {};
  window.app.splitter = splitter;

  // DOMContentLoaded 自动 init
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => splitter.init());
  } else {
    splitter.init();
  }
})();
