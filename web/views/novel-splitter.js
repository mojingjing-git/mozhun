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

    log(msg) {
      if (window.App && typeof window.App.appendLog === 'function') {
        window.App.appendLog('[小说切分] ' + msg);
      } else {
        console.log('[小说切分] ' + msg);
      }
    },

    toast(msg, type) {
      if (window.App && typeof window.App.showToast === 'function') {
        window.App.showToast(msg, type || 'info');
      } else {
        console.log('[toast]', type || 'info', msg);
      }
    },
  };

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, c => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[c]));
  }

  // 暴露到 App.splitter (供主 app.js 引用)
  if (!window.App) window.App = {};
  window.App.splitter = splitter;

  // DOMContentLoaded 自动 init
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => splitter.init());
  } else {
    splitter.init();
  }
})();
