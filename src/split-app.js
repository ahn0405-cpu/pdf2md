/* PDF 자르기 : 브라우저에서만 동작하는 UI.
 * 파일은 이 페이지 밖으로 전송되지 않는다. 자르기는 전부 이 탭 안에서 일어난다. */
import { splitPdf, formatSize, isOutOfMemory, safeChunkLimit, MB, DEFAULT_LIMIT } from './splitter.js';
import { collectPdfs, ensureWritable, supportsFolders, writeFile } from './folder.js';
import { loadMupdf } from './mupdf-runtime.js';

const $ = (id) => document.getElementById(id);

const drop = $('drop'), fileInput = $('fileInput'), listEl = $('fileList');
const splitBtn = $('splitBtn'), saveAllBtn = $('saveAllBtn'), clearBtn = $('clearBtn');
const limitInput = $('limitInput'), summaryEl = $('summary');
const folderRow = $('folderRow'), folderBtn = $('folderBtn');

// dir 는 조각을 쓸 폴더 손잡이(원본이 있던 폴더). 없으면 내려받기로 떨어진다.
let files = [];      // {uid, file, dir, status, parts, warnings, error, note, el}
let uidSeq = 0;
let running = false;
let mupdf = null;

/* 이만큼부터는 시간이 꽤 걸리고, 메모리를 아끼려고 조각도 한도보다 작아진다.
 * 시작하기 전에 미리 알려 준다. */
const HUGE = 300 * MB;

/* ---------------- 테마 ---------------- */
const savedTheme = localStorage.getItem('pdf2md-theme');
if (savedTheme) document.documentElement.setAttribute('data-theme', savedTheme);
else if (window.matchMedia?.('(prefers-color-scheme: dark)').matches)
  document.documentElement.setAttribute('data-theme', 'dark');
$('themeToggle').onclick = () => {
  const next = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', next);
  localStorage.setItem('pdf2md-theme', next);
};

/* ---------------- 설정 ---------------- */
const OPT_KEY = 'pdfsplit-options';

function readOptions() {
  const opts = { limit_mb: Number(limitInput.value) || DEFAULT_LIMIT / MB };
  document.querySelectorAll('[data-opt]').forEach((el) => { opts[el.dataset.opt] = el.checked; });
  return opts;
}

function restoreOptions() {
  let saved = {};
  try { saved = JSON.parse(localStorage.getItem(OPT_KEY) || '{}'); } catch { saved = {}; }
  if (saved.limit_mb) limitInput.value = saved.limit_mb;
  document.querySelectorAll('[data-opt]').forEach((el) => {
    if (saved[el.dataset.opt] !== undefined) el.checked = !!saved[el.dataset.opt];
  });
}
restoreOptions();
// 새로고침하면 브라우저가 이전 세션의 폼 상태를 스크립트보다 늦게 되돌려 놓는다.
window.addEventListener('pageshow', restoreOptions);

[limitInput, ...document.querySelectorAll('[data-opt]')].forEach((el) => {
  el.addEventListener('change', () => {
    localStorage.setItem(OPT_KEY, JSON.stringify(readOptions()));
    updateSummary();
  });
});
limitInput.addEventListener('input', updateSummary);

const limitBytes = () => {
  const mb = Math.min(Math.max(Number(limitInput.value) || 0, 1), 2000);
  return Math.round(mb * MB);
};

/* ---------------- 파일 수집 ---------------- */
drop.addEventListener('click', () => fileInput.click());
drop.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); fileInput.click(); }
});
fileInput.addEventListener('change', () => {
  addFiles(asEntries([...fileInput.files]));
  fileInput.value = '';
});

/** 폴더를 모르는 경로로 들어온 파일들. 조각은 내려받기로 간다. */
const asEntries = (list) => list.map((file) => ({ file, dir: null }));

['dragenter', 'dragover'].forEach((ev) =>
  drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add('over'); }));
['dragleave', 'drop'].forEach((ev) =>
  drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove('over'); }));

drop.addEventListener('drop', (e) => {
  const dt = e.dataTransfer;
  if (!dt) return;
  if (dt.items?.length && dt.items[0].webkitGetAsEntry) {
    const entries = [];
    for (const item of dt.items) {
      const entry = item.webkitGetAsEntry();
      if (entry) entries.push(entry);
    }
    walkEntries(entries).then((list) => addFiles(asEntries(list)));
  } else {
    addFiles(asEntries([...dt.files]));
  }
});
window.addEventListener('dragover', (e) => e.preventDefault());
window.addEventListener('drop', (e) => e.preventDefault());

function walkEntries(entries) {
  const out = [];
  const walk = (entry) => new Promise((resolve) => {
    if (entry.isFile) {
      entry.file((f) => { out.push(f); resolve(); }, resolve);
    } else if (entry.isDirectory) {
      const reader = entry.createReader();
      let all = [];
      const readMore = () => reader.readEntries((batch) => {
        if (!batch.length) { Promise.all(all.map(walk)).then(resolve); return; }
        all = all.concat(batch);
        readMore();
      }, resolve);
      readMore();
    } else resolve();
  });
  return Promise.all(entries.map(walk)).then(() => out);
}

function addFiles(incoming) {
  const pdfs = incoming.filter(({ file }) =>
    /\.pdf$/i.test(file.name) || file.type === 'application/pdf');
  let skipped = incoming.length - pdfs.length;
  pdfs.sort((a, b) => a.file.name.localeCompare(b.file.name, 'ko'));

  for (const { file, dir } of pdfs) {
    if (files.some((x) => x.file.name === file.name && x.file.size === file.size)) { skipped++; continue; }
    files.push({ uid: ++uidSeq, file, dir, status: 'wait', parts: [], warnings: [], error: null, note: '' });
  }
  renderList();
  if (skipped) toast(`PDF가 아니거나 중복인 파일 ${skipped}개를 건너뛰었습니다.`);
}

/* ---------------- 폴더 열기 ---------------- */
if (supportsFolders()) folderRow.hidden = false;

folderBtn.onclick = async () => {
  let dir;
  try {
    dir = await showDirectoryPicker({ mode: 'readwrite' });
  } catch (err) {
    if (err?.name !== 'AbortError') toast(`폴더를 열지 못했습니다: ${err.message || err}`);
    return;
  }
  if (!await ensureWritable(dir)) {
    toast('그 폴더에 쓸 권한을 받지 못했습니다. 조각을 원본 자리에 저장할 수 없습니다.');
    return;
  }
  folderBtn.disabled = true;
  folderBtn.textContent = '읽는 중…';
  try {
    const found = await collectPdfs(dir);
    if (!found.length) { toast('그 폴더에서 PDF를 찾지 못했습니다.'); return; }
    addFiles(found);
    toast(`PDF ${found.length}개를 가져왔습니다. 조각은 원본이 있던 폴더에 저장됩니다.`);
  } catch (err) {
    toast(`폴더를 읽지 못했습니다: ${err.message || err}`);
  } finally {
    folderBtn.disabled = false;
    folderBtn.textContent = '폴더 열기…';
  }
};

/* ---------------- 목록 ---------------- */
const BADGE = {
  wait: ['wait', '대기'], busy: ['busy', '자르는 중'],
  done: ['done', '완료'], skip: ['done', '그대로'], fail: ['fail', '실패'],
};

function renderList() {
  listEl.innerHTML = '';
  for (const item of files) {
    const li = document.createElement('li');
    li.className = 'item';

    const top = document.createElement('div');
    top.className = 'item-top';

    const badge = document.createElement('span');
    badge.className = `badge ${BADGE[item.status][0]}`;
    badge.textContent = BADGE[item.status][1];

    const name = document.createElement('span');
    name.className = 'item-name';
    name.textContent = item.file.name;

    const size = document.createElement('span');
    size.className = 'item-size';
    size.textContent = formatSize(item.file.size);

    const rm = document.createElement('button');
    rm.className = 'item-remove';
    rm.type = 'button';
    rm.title = '목록에서 제거';
    rm.textContent = '×';
    rm.onclick = () => {
      if (running) return;
      files = files.filter((x) => x.uid !== item.uid);
      renderList();
    };

    top.append(badge, name, size, rm);
    li.appendChild(top);

    if (item.status === 'busy') {
      const bar = document.createElement('div');
      bar.className = 'bar';
      bar.innerHTML = '<i></i>';
      li.appendChild(bar);
    }

    if (item.note) {
      const note = document.createElement('div');
      note.className = 'item-meta';
      note.textContent = item.note;
      li.appendChild(note);
    }

    if (item.dir) {
      const dest = document.createElement('div');
      dest.className = 'item-dest';
      dest.textContent = `📁 ${item.dir.name} 폴더에 저장`;
      li.appendChild(dest);
    }

    if (item.parts.length) {
      const parts = document.createElement('ul');
      parts.className = 'parts';
      for (const part of item.parts) parts.appendChild(renderPart(part));
      li.appendChild(parts);
    }

    for (const w of item.warnings) {
      const el = document.createElement('div');
      el.className = 'item-warn';
      el.textContent = `⚠ ${w}`;
      li.appendChild(el);
    }

    if (item.error) {
      const err = document.createElement('div');
      err.className = 'item-err';
      err.textContent = `✕ ${item.error}`;
      li.appendChild(err);
    }

    item.el = li;
    listEl.appendChild(li);
  }
  updateButtons();
  updateSummary();
}

function renderPart(part) {
  const li = document.createElement('li');
  li.className = 'part';

  const name = document.createElement('span');
  name.className = 'part-name';
  name.textContent = part.name;

  const meta = document.createElement('span');
  meta.className = 'part-meta';
  meta.textContent = `${part.from}-${part.to}쪽 · ${formatSize(part.size)}`;

  const dl = document.createElement('button');
  dl.className = 'item-dl';
  dl.type = 'button';
  dl.textContent = '⬇';
  dl.title = `${part.name} 내려받기`;
  dl.onclick = () => savePart(part);

  li.append(name, meta);
  if (part.saved || part.saveError) {
    const state = document.createElement('span');
    state.className = 'part-state' + (part.saveError ? ' fail' : '');
    state.textContent = part.saveError ? `✕ ${part.saveError}` : '저장됨';
    li.append(state);
  }
  li.append(dl);
  return li;
}

function updateButtons() {
  const saved = files.filter((f) => f.parts.length);
  splitBtn.disabled = running || !files.some((f) => f.status === 'wait');
  splitBtn.textContent = running ? '자르는 중…' : '자르기 시작';
  saveAllBtn.disabled = running || !saved.length;
  saveAllBtn.title = '조각을 브라우저의 내려받기 폴더로 따로 저장합니다';
  clearBtn.disabled = running || !files.length;
  limitInput.disabled = running;
}

function updateSummary() {
  if (!files.length) { summaryEl.hidden = true; return; }
  const limit = limitBytes();
  const waiting = files.filter((f) => f.status === 'wait');
  const parts = files.reduce((a, f) => a + f.parts.length, 0);
  const bits = [`파일 ${files.length}개`];
  if (waiting.length) {
    // 큰 원본은 메모리를 아끼려고 한도보다 작게 자른다. 예상 개수도 그 기준으로.
    const guess = waiting.reduce((a, f) => a + (f.file.size <= limit ? 1
      : Math.ceil(f.file.size / safeChunkLimit(f.file.size, limit))), 0);
    bits.push(`한도 ${formatSize(limit)} 기준 약 ${guess}조각 예상`);
  }
  if (parts) bits.push(`조각 ${parts}개 완성`);
  summaryEl.hidden = false;
  summaryEl.textContent = bits.join(' · ');
}

/* ---------------- 자르기 ---------------- */
splitBtn.onclick = async () => {
  const queue = files.filter((f) => f.status === 'wait');
  if (!queue.length) return;

  running = true;
  updateButtons();

  if (!mupdf) {
    summaryEl.hidden = false;
    summaryEl.textContent = 'PDF 엔진을 준비하는 중…';
    try {
      mupdf = await loadMupdf();
    } catch (err) {
      running = false;
      renderList();
      toast(`PDF 엔진을 불러오지 못했습니다: ${err.message || err}`);
      return;
    }
  }

  const opts = readOptions();
  for (const item of queue) {
    item.status = 'busy';
    item.error = null;
    item.note = '읽는 중…';
    renderList();
    await new Promise((r) => setTimeout(r, 0));   // 진행 표시가 그려지도록 양보
    await splitOne(item, opts);
  }

  running = false;
  renderList();
  const fails = files.filter((f) => f.status === 'fail').length;
  toast(fails ? `자르기 완료 (실패 ${fails}건)` : '자르기 완료');
};

async function splitOne(item, opts) {
  const limit = limitBytes();
  try {
    if (item.file.size > HUGE) {
      item.note = '큰 파일입니다. 몇 분 걸릴 수 있고, 그동안 화면이 멈춘 것처럼 보입니다.';
      renderList();
      await new Promise((r) => setTimeout(r, 0));
    }
    let bytes = new Uint8Array(await item.file.arrayBuffer());
    const started = performance.now();
    const writes = [];

    const job = splitPdf(mupdf, bytes, {
      limitBytes: limit,
      name: item.file.name,
      nameWithRange: opts.name_range,
      onProgress: ({ pagesDone, pageCount, message }) => {
        item.note = message || `${pageCount}쪽 중 ${pagesDone}쪽 처리`;
        // 진행 중에는 목록 전체를 다시 그리지 않는다(깜빡임과 낭비)
        const el = item.el?.querySelector('.item-meta');
        if (el) el.textContent = item.note; else renderList();
      },
      // WASM 메모리를 가리키는 뷰에서 곧장 Blob 을 만든다. 자바스크립트 힙에
      // 조각만 한 사본을 하나 덜 만든다.
      takeBytes: (view) => new Blob([view], { type: 'application/pdf' }),
      onPart: (part) => {
        item.parts.push(part);
        // 원본이 있던 폴더가 있으면 그 자리에 바로 쓴다. 쓰기는 기다리지 않고
        // 다음 조각을 계속 만든다(디스크는 느리고 CPU 는 놀 이유가 없다).
        // 자를 필요가 없던 파일은 이름이 원본과 같다 — 제 자신을 덮어쓰지 않는다.
        if (item.dir && part.name !== item.file.name) writes.push(writePart(item, part));
        else if (opts.auto_save) savePart(part);
        renderList();
      },
    });
    // 원본은 PDF 엔진이 들고 있다. 이쪽 사본은 붙잡고 있을 이유가 없다.
    bytes = null;
    const result = await job;
    await Promise.all(writes);

    item.warnings = result.warnings;
    item.status = result.untouched ? 'skip' : 'done';
    const elapsed = (performance.now() - started) / 1000;
    const saved = item.parts.filter((p) => p.saved).length;
    item.note = result.untouched
      ? `${result.pageCount}쪽 · ${formatSize(item.file.size)} — 이미 한도 이하라 그대로 둡니다`
      : `${result.pageCount}쪽 → ${result.parts.length}조각 · ${elapsed.toFixed(1)}초`
        + (saved ? ` · ${saved}개를 원본 폴더에 저장` : '');
  } catch (err) {
    item.status = 'fail';
    item.note = '';
    item.error = isOutOfMemory(err)
      ? `PDF 엔진의 메모리 한계(2GB)를 넘었습니다 (${err.message || err}).`
        + ' 다른 탭을 닫고, 한 조각 최대 크기를 줄여 다시 해 보세요.'
      : (err.message || String(err));
  }
  renderList();
}

/* ---------------- 내려받기 ---------------- */
function saveBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 8000);
}

/** 조각을 원본이 있던 폴더에 쓴다. 실패해도 자르기 자체는 계속한다 —
 *  ⬇ 로 내려받으면 되니까. */
async function writePart(item, part) {
  try {
    await writeFile(item.dir, part.name, part.data);
    part.saved = true;
  } catch (err) {
    part.saveError = err.message || String(err);
  }
  renderList();
}

function savePart(part) {
  if (!part.data) return;
  saveBlob(part.data, part.name);
}

saveAllBtn.onclick = async () => {
  const all = files.flatMap((f) => f.parts);
  if (!all.length) return;
  saveAllBtn.disabled = true;
  saveAllBtn.textContent = '저장 중…';
  try {
    for (const part of all) {
      savePart(part);
      // 연달아 저장하면 브라우저가 뒤쪽 몇 개를 흘린다
      await new Promise((r) => setTimeout(r, 250));
    }
    toast(`${all.length}개를 저장했습니다.`);
  } finally {
    saveAllBtn.textContent = '전체 저장';
    updateButtons();
  }
};

clearBtn.onclick = () => {
  files = [];
  renderList();
};

/* ---------------- 토스트 ---------------- */
const toastEl = document.createElement('div');
toastEl.className = 'toast';
document.body.appendChild(toastEl);
let toastTimer = null;
function toast(msg) {
  toastEl.textContent = msg;
  toastEl.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toastEl.classList.remove('show'), 2600);
}

renderList();
