/* PDF → Markdown 프런트엔드 */
(function () {
  'use strict';

  var $ = function (id) { return document.getElementById(id); };

  var drop = $('drop'), fileInput = $('fileInput'), listEl = $('fileList');
  var convertBtn = $('convertBtn'), zipBtn = $('zipBtn'), clearBtn = $('clearBtn');
  var summaryEl = $('summary');
  var renderedEl = $('previewRendered'), sourceEl = $('previewSource');
  var previewName = $('previewName');
  var copyBtn = $('copyBtn'), dlBtn = $('dlBtn'), dlZipBtn = $('dlZipBtn');

  var files = [];        // {uid, file, status, job, error, el}
  var selectedUid = null;
  var uidSeq = 0;
  var running = false;
  // 서버의 PDF 엔진이 프로세스 단위로 직렬화되므로 요청도 한 건씩 보낸다.
  var CONCURRENCY = 1;

  // ---------------- 테마 ----------------
  var savedTheme = localStorage.getItem('pdf2md-theme');
  if (savedTheme) document.documentElement.setAttribute('data-theme', savedTheme);
  else if (window.matchMedia && matchMedia('(prefers-color-scheme: dark)').matches)
    document.documentElement.setAttribute('data-theme', 'dark');
  $('themeToggle').onclick = function () {
    var next = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    localStorage.setItem('pdf2md-theme', next);
  };

  // ---------------- 옵션 ----------------
  var OPT_KEY = 'pdf2md-options';
  function readOptions() {
    var opts = {};
    document.querySelectorAll('[data-opt]').forEach(function (el) {
      opts[el.dataset.opt] = el.type === 'checkbox' ? el.checked : el.value;
    });
    return opts;
  }
  function restoreOptions() {
    var saved;
    try { saved = JSON.parse(localStorage.getItem(OPT_KEY) || '{}'); } catch (e) { saved = {}; }
    document.querySelectorAll('[data-opt]').forEach(function (el) {
      var v = saved[el.dataset.opt];
      if (v === undefined) return;
      if (el.type === 'checkbox') el.checked = !!v; else el.value = v;
    });
  }
  restoreOptions();
  document.querySelectorAll('[data-opt]').forEach(function (el) {
    el.addEventListener('change', function () {
      localStorage.setItem(OPT_KEY, JSON.stringify(readOptions()));
      // 옵션이 바뀌면 기존 결과는 낡은 것이므로 다시 변환할 수 있게 되돌린다
      var stale = files.filter(function (f) { return f.status === 'done'; });
      if (!stale.length || running) return;
      stale.forEach(function (f) { f.status = 'wait'; });
      renderList();
      toast('옵션이 바뀌었습니다. 다시 변환하세요.');
    });
  });

  // ---------------- 파일 수집 ----------------
  drop.addEventListener('click', function () { fileInput.click(); });
  drop.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); fileInput.click(); }
  });
  fileInput.addEventListener('change', function () {
    addFiles(Array.prototype.slice.call(fileInput.files));
    fileInput.value = '';
  });

  ['dragenter', 'dragover'].forEach(function (ev) {
    drop.addEventListener(ev, function (e) { e.preventDefault(); drop.classList.add('over'); });
  });
  ['dragleave', 'drop'].forEach(function (ev) {
    drop.addEventListener(ev, function (e) { e.preventDefault(); drop.classList.remove('over'); });
  });
  drop.addEventListener('drop', function (e) {
    var dt = e.dataTransfer;
    if (!dt) return;
    if (dt.items && dt.items.length && dt.items[0].webkitGetAsEntry) {
      var entries = [];
      for (var i = 0; i < dt.items.length; i++) {
        var entry = dt.items[i].webkitGetAsEntry();
        if (entry) entries.push(entry);
      }
      walkEntries(entries).then(addFiles);
    } else {
      addFiles(Array.prototype.slice.call(dt.files));
    }
  });
  window.addEventListener('dragover', function (e) { e.preventDefault(); });
  window.addEventListener('drop', function (e) { e.preventDefault(); });

  function walkEntries(entries) {
    var out = [];
    function walk(entry) {
      return new Promise(function (resolve) {
        if (entry.isFile) {
          entry.file(function (f) { out.push(f); resolve(); }, resolve);
        } else if (entry.isDirectory) {
          var reader = entry.createReader();
          var all = [];
          (function readMore() {
            reader.readEntries(function (batch) {
              if (!batch.length) {
                Promise.all(all.map(walk)).then(resolve);
                return;
              }
              all = all.concat(batch);
              readMore();
            }, resolve);
          })();
        } else resolve();
      });
    }
    return Promise.all(entries.map(walk)).then(function () { return out; });
  }

  function addFiles(incoming) {
    var pdfs = incoming.filter(function (f) {
      return /\.pdf$/i.test(f.name) || f.type === 'application/pdf';
    });
    var skipped = incoming.length - pdfs.length;
    pdfs.sort(function (a, b) { return a.name.localeCompare(b.name, 'ko'); });

    pdfs.forEach(function (f) {
      var dup = files.some(function (x) {
        return x.file.name === f.name && x.file.size === f.size;
      });
      if (dup) { skipped++; return; }
      files.push({ uid: ++uidSeq, file: f, status: 'wait', job: null, error: null });
    });

    renderList();
    if (skipped) toast('PDF가 아니거나 중복인 파일 ' + skipped + '개를 건너뛰었습니다.');
  }

  // ---------------- 목록 렌더 ----------------
  function humanSize(n) {
    if (n < 1024) return n + ' B';
    if (n < 1024 * 1024) return (n / 1024).toFixed(0) + ' KB';
    return (n / 1024 / 1024).toFixed(1) + ' MB';
  }

  var BADGE = { wait: ['wait', '대기'], busy: ['busy', '변환 중'], done: ['done', '완료'], fail: ['fail', '실패'] };

  function renderList() {
    listEl.innerHTML = '';
    files.forEach(function (item) {
      var li = document.createElement('li');
      li.className = 'item' + (item.uid === selectedUid ? ' selected' : '');
      li.onclick = function (e) {
        if (e.target.classList.contains('item-remove')) return;
        if (item.job) select(item.uid);
      };

      var top = document.createElement('div');
      top.className = 'item-top';

      var badge = document.createElement('span');
      badge.className = 'badge ' + BADGE[item.status][0];
      badge.textContent = BADGE[item.status][1];

      var name = document.createElement('span');
      name.className = 'item-name';
      name.textContent = item.file.name;

      var size = document.createElement('span');
      size.className = 'item-size';
      size.textContent = humanSize(item.file.size);

      var rm = document.createElement('button');
      rm.className = 'item-remove';
      rm.type = 'button';
      rm.title = '목록에서 제거';
      rm.textContent = '×';
      rm.onclick = function () {
        if (running) return;
        files = files.filter(function (x) { return x.uid !== item.uid; });
        if (selectedUid === item.uid) { selectedUid = null; clearPreview(); }
        renderList();
      };

      top.append(badge, name, size, rm);
      li.appendChild(top);

      if (item.status === 'busy') {
        var bar = document.createElement('div');
        bar.className = 'bar';
        bar.innerHTML = '<i></i>';
        li.appendChild(bar);
      }

      if (item.job) {
        var s = item.job.stats || {};
        var meta = document.createElement('div');
        meta.className = 'item-meta';
        meta.append(
          chip(s.pages + '쪽'),
          chip('제목 ' + (s.headings || 0)),
          chip('표 ' + (s.tables || 0)),
          chip('이미지 ' + (s.images || 0)),
          chip((s.chars || 0).toLocaleString() + '자'),
          chip(s.elapsed + '초')
        );
        li.appendChild(meta);

        (item.job.warnings || []).forEach(function (w) {
          var el = document.createElement('div');
          el.className = 'item-warn';
          el.textContent = '⚠ ' + w;
          li.appendChild(el);
        });
      }

      if (item.error) {
        var err = document.createElement('div');
        err.className = 'item-err';
        err.textContent = '✕ ' + item.error;
        li.appendChild(err);
      }

      item.el = li;
      listEl.appendChild(li);
    });

    updateButtons();
    updateSummary();
  }

  function chip(text) {
    var s = document.createElement('span');
    s.textContent = text;
    return s;
  }

  function updateButtons() {
    var done = files.filter(function (f) { return f.status === 'done'; });
    convertBtn.disabled = running || !files.some(function (f) { return f.status !== 'done'; });
    zipBtn.disabled = running || done.length === 0;
    clearBtn.disabled = running || files.length === 0;
    convertBtn.textContent = running ? '변환 중…' : '변환 시작';
  }

  function updateSummary() {
    if (!files.length) { summaryEl.hidden = true; return; }
    var done = files.filter(function (f) { return f.status === 'done'; }).length;
    var fail = files.filter(function (f) { return f.status === 'fail'; }).length;
    var pages = files.reduce(function (a, f) { return a + ((f.job && f.job.stats.pages) || 0); }, 0);
    summaryEl.hidden = false;
    summaryEl.textContent = '파일 ' + files.length + '개 · 완료 ' + done +
      (fail ? ' · 실패 ' + fail : '') + (pages ? ' · 총 ' + pages + '쪽' : '');
  }

  // ---------------- 변환 ----------------
  convertBtn.onclick = function () {
    var queue = files.filter(function (f) { return f.status !== 'done'; });
    if (!queue.length) return;
    running = true;
    updateButtons();

    var opts = JSON.stringify(readOptions());
    var idx = 0;

    function next() {
      if (idx >= queue.length) return Promise.resolve();
      var item = queue[idx++];
      item.status = 'busy';
      item.error = null;
      renderList();
      return convertOne(item, opts).then(next);
    }

    var workers = [];
    for (var w = 0; w < Math.min(CONCURRENCY, queue.length); w++) workers.push(next());

    Promise.all(workers).then(function () {
      running = false;
      renderList();
      var first = files.find(function (f) { return f.status === 'done'; });
      if (first && !selectedUid) select(first.uid);
      var fails = files.filter(function (f) { return f.status === 'fail'; }).length;
      toast(fails ? '변환 완료 (실패 ' + fails + '건)' : '변환 완료');
    });
  };

  function convertOne(item, opts) {
    var fd = new FormData();
    fd.append('file', item.file, item.file.name);
    fd.append('options', opts);

    return fetch('/api/convert', { method: 'POST', body: fd })
      .then(function (res) {
        return res.json().catch(function () {
          throw new Error('서버 응답을 읽을 수 없습니다 (HTTP ' + res.status + ')');
        }).then(function (data) {
          if (!res.ok) throw new Error(data.error || ('HTTP ' + res.status));
          return data;
        });
      })
      .then(function (data) {
        item.job = data;
        item.status = 'done';
        // 보고 있던 파일을 다시 변환했으면 미리보기도 새 결과로 갱신한다
        if (!selectedUid || selectedUid === item.uid) select(item.uid);
        else renderList();
      })
      .catch(function (err) {
        item.status = 'fail';
        item.error = err.message || String(err);
        renderList();
      });
  }

  // ---------------- 미리보기 ----------------
  function select(uid) {
    selectedUid = uid;
    var item = files.find(function (f) { return f.uid === uid; });
    renderList();
    if (!item || !item.job) return clearPreview();

    var job = item.job;
    previewName.textContent = job.mdName;
    previewName.title = job.mdName;
    sourceEl.textContent = job.markdown;
    renderedEl.innerHTML = miniMarkdown.render(job.markdown, function (url) {
      if (/^(https?:|data:)/i.test(url)) return url;
      return '/api/asset/' + job.id + '/' + url.split('/').map(encodeURIComponent).join('/');
    });
    copyBtn.disabled = false;
    dlBtn.disabled = false;
    dlZipBtn.disabled = !(job.assets && job.assets.length);
    dlZipBtn.title = dlZipBtn.disabled ? '추출된 이미지가 없어 .md만 있으면 됩니다' : '';
    if (item.el) item.el.scrollIntoView({ block: 'nearest' });
  }

  function clearPreview() {
    previewName.textContent = '결과 없음';
    renderedEl.innerHTML = '<p class="empty">왼쪽에서 PDF를 선택하고 <b>변환 시작</b>을 누르면 결과가 여기에 표시됩니다.</p>';
    sourceEl.textContent = '';
    copyBtn.disabled = dlBtn.disabled = dlZipBtn.disabled = true;
  }

  document.querySelectorAll('.tab').forEach(function (tab) {
    tab.onclick = function () {
      document.querySelectorAll('.tab').forEach(function (t) { t.classList.remove('active'); });
      tab.classList.add('active');
      var rendered = tab.dataset.view === 'rendered';
      renderedEl.hidden = !rendered;
      sourceEl.hidden = rendered;
    };
  });

  copyBtn.onclick = function () {
    var item = files.find(function (f) { return f.uid === selectedUid; });
    if (!item || !item.job) return;
    var text = item.job.markdown;
    var done = function () { toast('마크다운을 복사했습니다.'); };
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(text).then(done, fallbackCopy);
    } else fallbackCopy();

    function fallbackCopy() {
      var ta = document.createElement('textarea');
      ta.value = text;
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.select();
      try { document.execCommand('copy'); done(); } catch (e) { toast('복사에 실패했습니다.'); }
      document.body.removeChild(ta);
    }
  };

  dlBtn.onclick = function () {
    var item = files.find(function (f) { return f.uid === selectedUid; });
    if (item && item.job) location.href = '/api/download/' + item.job.id;
  };
  dlZipBtn.onclick = function () {
    var item = files.find(function (f) { return f.uid === selectedUid; });
    if (item && item.job) location.href = '/api/bundle/' + item.job.id;
  };

  zipBtn.onclick = function () {
    var ids = files.filter(function (f) { return f.status === 'done'; })
                   .map(function (f) { return f.job.id; });
    if (!ids.length) return;
    fetch('/api/bundle', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ids: ids })
    }).then(function (res) {
      if (!res.ok) throw new Error('ZIP 생성에 실패했습니다.');
      return res.blob();
    }).then(function (blob) {
      var url = URL.createObjectURL(blob);
      var a = document.createElement('a');
      a.href = url;
      a.download = 'markdown.zip';
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      setTimeout(function () { URL.revokeObjectURL(url); }, 4000);
    }).catch(function (e) { toast(e.message); });
  };

  clearBtn.onclick = function () {
    files = [];
    selectedUid = null;
    clearPreview();
    renderList();
  };

  // ---------------- 토스트 ----------------
  var toastEl = document.createElement('div');
  toastEl.className = 'toast';
  document.body.appendChild(toastEl);
  var toastTimer = null;
  function toast(msg) {
    toastEl.textContent = msg;
    toastEl.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { toastEl.classList.remove('show'); }, 2600);
  }

  renderList();
})();
