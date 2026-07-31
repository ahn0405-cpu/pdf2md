/* PDF → Markdown : 브라우저에서만 동작하는 UI.
 * 파일은 이 페이지 밖으로 전송되지 않는다. 변환은 전부 이 탭 안에서 일어난다. */
import { convert, DEFAULT_OPTIONS } from './converter.js';
import { makeZip } from './zip.js';
import { renderMarkdown } from './markdown.js';
import { loadMupdf } from './mupdf-runtime.js';

const $ = (id) => document.getElementById(id);

const drop = $('drop'), fileInput = $('fileInput'), listEl = $('fileList');
const convertBtn = $('convertBtn'), zipBtn = $('zipBtn'), clearBtn = $('clearBtn');
const summaryEl = $('summary');
const renderedEl = $('previewRendered'), sourceEl = $('previewSource');
const previewName = $('previewName');
const copyBtn = $('copyBtn'), dlBtn = $('dlBtn'), dlZipBtn = $('dlZipBtn');

let files = [];          // {uid, file, status, result, error, el}
let selectedUid = null;
let uidSeq = 0;
let running = false;
let mupdf = null;
const previewUrls = [];  // 미리보기용 blob URL — 정리 대상

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

/* ---------------- 옵션 ---------------- */
const OPT_KEY = 'pdf2md-options';

function readOptions() {
  const opts = {};
  document.querySelectorAll('[data-opt]').forEach((el) => {
    opts[el.dataset.opt] = el.type === 'checkbox' ? el.checked : el.value;
  });
  return opts;
}

(function restoreOptions() {
  let saved = {};
  try { saved = JSON.parse(localStorage.getItem(OPT_KEY) || '{}'); } catch { saved = {}; }
  document.querySelectorAll('[data-opt]').forEach((el) => {
    const v = saved[el.dataset.opt];
    if (v === undefined) return;
    if (el.type === 'checkbox') el.checked = !!v; else el.value = v;
  });
})();

document.querySelectorAll('[data-opt]').forEach((el) => {
  el.addEventListener('change', () => {
    localStorage.setItem(OPT_KEY, JSON.stringify(readOptions()));
    // 옵션이 바뀌면 기존 결과는 낡은 것이므로 다시 변환할 수 있게 되돌린다
    const stale = files.filter((f) => f.status === 'done');
    if (!stale.length || running) return;
    stale.forEach((f) => { f.status = 'wait'; });
    renderList();
    toast('옵션이 바뀌었습니다. 다시 변환하세요.');
  });
});

/* ---------------- 파일 수집 ---------------- */
drop.addEventListener('click', () => fileInput.click());
drop.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); fileInput.click(); }
});
fileInput.addEventListener('change', () => {
  addFiles([...fileInput.files]);
  fileInput.value = '';
});

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
    walkEntries(entries).then(addFiles);
  } else {
    addFiles([...dt.files]);
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
  const pdfs = incoming.filter((f) => /\.pdf$/i.test(f.name) || f.type === 'application/pdf');
  let skipped = incoming.length - pdfs.length;
  pdfs.sort((a, b) => a.name.localeCompare(b.name, 'ko'));

  for (const f of pdfs) {
    if (files.some((x) => x.file.name === f.name && x.file.size === f.size)) { skipped++; continue; }
    files.push({ uid: ++uidSeq, file: f, status: 'wait', result: null, error: null });
  }
  renderList();
  if (skipped) toast(`PDF가 아니거나 중복인 파일 ${skipped}개를 건너뛰었습니다.`);
}

/* ---------------- 목록 ---------------- */
function humanSize(n) {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / 1048576).toFixed(1)} MB`;
}

const BADGE = {
  wait: ['wait', '대기'], busy: ['busy', '변환 중'],
  done: ['done', '완료'], fail: ['fail', '실패'],
};

function renderList() {
  listEl.innerHTML = '';
  for (const item of files) {
    const li = document.createElement('li');
    li.className = 'item' + (item.uid === selectedUid ? ' selected' : '');
    li.onclick = (e) => {
      if (e.target.classList.contains('item-remove')) return;
      if (item.result) select(item.uid);
    };

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
    size.textContent = humanSize(item.file.size);

    const rm = document.createElement('button');
    rm.className = 'item-remove';
    rm.type = 'button';
    rm.title = '목록에서 제거';
    rm.textContent = '×';
    rm.onclick = () => {
      if (running) return;
      files = files.filter((x) => x.uid !== item.uid);
      if (selectedUid === item.uid) { selectedUid = null; clearPreview(); }
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

    if (item.result) {
      const s = item.result.stats;
      const meta = document.createElement('div');
      meta.className = 'item-meta';
      meta.append(
        chip(`${s.pages}쪽`), chip(`제목 ${s.headings}`), chip(`표 ${s.tables}`),
        chip(`이미지 ${s.images}`), chip(`${s.chars.toLocaleString()}자`),
        chip(`${item.result.elapsed.toFixed(2)}초`),
      );
      li.appendChild(meta);
      for (const w of item.result.warnings) {
        const el = document.createElement('div');
        el.className = 'item-warn';
        el.textContent = `⚠ ${w}`;
        li.appendChild(el);
      }
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

function chip(text) {
  const s = document.createElement('span');
  s.textContent = text;
  return s;
}

function updateButtons() {
  const done = files.filter((f) => f.status === 'done');
  convertBtn.disabled = running || !files.some((f) => f.status !== 'done');
  zipBtn.disabled = running || !done.length;
  clearBtn.disabled = running || !files.length;
  convertBtn.textContent = running ? '변환 중…' : '변환 시작';
}

function updateSummary() {
  if (!files.length) { summaryEl.hidden = true; return; }
  const done = files.filter((f) => f.status === 'done').length;
  const fail = files.filter((f) => f.status === 'fail').length;
  const pages = files.reduce((a, f) => a + (f.result?.stats.pages || 0), 0);
  summaryEl.hidden = false;
  summaryEl.textContent = `파일 ${files.length}개 · 완료 ${done}`
    + (fail ? ` · 실패 ${fail}` : '') + (pages ? ` · 총 ${pages}쪽` : '');
}

/* ---------------- 변환 ---------------- */
convertBtn.onclick = async () => {
  const queue = files.filter((f) => f.status !== 'done');
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

  const opts = mapOptions(readOptions());
  for (const item of queue) {
    item.status = 'busy';
    item.error = null;
    renderList();
    await new Promise((r) => setTimeout(r, 0));   // 진행 표시가 그려지도록 양보
    await convertOne(item, opts);
  }

  running = false;
  renderList();
  const first = files.find((f) => f.status === 'done');
  if (first && !selectedUid) select(first.uid);
  const fails = files.filter((f) => f.status === 'fail').length;
  toast(fails ? `변환 완료 (실패 ${fails}건)` : '변환 완료');
};

/** UI 의 snake_case 옵션명을 변환기의 camelCase 로 맞춘다. */
function mapOptions(raw) {
  const opts = {};
  for (const [key, value] of Object.entries(raw)) {
    const camel = key.replace(/_([a-z])/g, (_, c) => c.toUpperCase());
    if (camel in DEFAULT_OPTIONS) opts[camel] = value;
  }
  return opts;
}

async function convertOne(item, opts) {
  try {
    const bytes = new Uint8Array(await item.file.arrayBuffer());
    const started = performance.now();
    const result = convert(mupdf, bytes, item.file.name, opts);
    result.elapsed = (performance.now() - started) / 1000;
    result.mdName = item.file.name.replace(/\.pdf$/i, '') + '.md';
    item.result = result;
    item.status = 'done';
    // 보고 있던 파일을 다시 변환했으면 미리보기도 새 결과로 갱신한다
    if (!selectedUid || selectedUid === item.uid) select(item.uid);
    else renderList();
  } catch (err) {
    item.status = 'fail';
    item.error = err.message || String(err);
    renderList();
  }
}

/* ---------------- 미리보기 ---------------- */
function select(uid) {
  selectedUid = uid;
  const item = files.find((f) => f.uid === uid);
  renderList();
  if (!item?.result) { clearPreview(); return; }

  const { result } = item;
  previewName.textContent = result.mdName;
  previewName.title = result.mdName;
  sourceEl.textContent = result.markdown;

  // 추출한 이미지는 blob URL 로 걸어 준다 (네트워크 요청 없음)
  revokePreviewUrls();
  const urls = new Map();
  for (const asset of result.assets) {
    const url = URL.createObjectURL(new Blob([asset.data], { type: asset.mime }));
    urls.set(asset.name, url);
    previewUrls.push(url);
  }
  renderedEl.innerHTML = renderMarkdown(result.markdown, (u) => urls.get(u) || u);

  copyBtn.disabled = false;
  dlBtn.disabled = false;
  dlZipBtn.disabled = !result.assets.length;
  dlZipBtn.title = dlZipBtn.disabled ? '추출된 이미지가 없어 .md만 있으면 됩니다' : '';
  item.el?.scrollIntoView({ block: 'nearest' });
}

function revokePreviewUrls() {
  while (previewUrls.length) URL.revokeObjectURL(previewUrls.pop());
}

function clearPreview() {
  revokePreviewUrls();
  previewName.textContent = '결과 없음';
  renderedEl.innerHTML = '<p class="empty">왼쪽에서 PDF를 선택하고 <b>변환 시작</b>을 누르면 결과가 여기에 표시됩니다.</p>';
  sourceEl.textContent = '';
  copyBtn.disabled = dlBtn.disabled = dlZipBtn.disabled = true;
}

document.querySelectorAll('.tab').forEach((tab) => {
  tab.onclick = () => {
    document.querySelectorAll('.tab').forEach((t) => t.classList.remove('active'));
    tab.classList.add('active');
    const rendered = tab.dataset.view === 'rendered';
    renderedEl.hidden = !rendered;
    sourceEl.hidden = rendered;
  };
});

/* ---------------- 내려받기 ---------------- */
const selected = () => files.find((f) => f.uid === selectedUid);

function saveBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 4000);
}

copyBtn.onclick = async () => {
  const item = selected();
  if (!item?.result) return;
  try {
    await navigator.clipboard.writeText(item.result.markdown);
    toast('마크다운을 복사했습니다.');
    return;
  } catch { /* 아래 대체 경로로 */ }

  const ta = document.createElement('textarea');
  ta.value = item.result.markdown;
  ta.style.cssText = 'position:fixed;opacity:0';
  document.body.appendChild(ta);
  ta.select();
  try { document.execCommand('copy'); toast('마크다운을 복사했습니다.'); }
  catch { toast('복사에 실패했습니다.'); }
  ta.remove();
};

dlBtn.onclick = () => {
  const item = selected();
  if (!item?.result) return;
  saveBlob(new Blob([item.result.markdown], { type: 'text/markdown;charset=utf-8' }),
           item.result.mdName);
};

dlZipBtn.onclick = async () => {
  const item = selected();
  if (!item?.result) return;
  const entries = [{ name: item.result.mdName, data: item.result.markdown },
                   ...item.result.assets.map((a) => ({ name: a.name, data: a.data }))];
  saveBlob(await makeZip(entries), item.result.mdName.replace(/\.md$/, '') + '.zip');
};

zipBtn.onclick = async () => {
  const done = files.filter((f) => f.status === 'done');
  if (!done.length) return;

  const entries = [];
  const used = new Set();
  for (const item of done) {
    const { result } = item;
    const base = result.mdName.replace(/\.md$/, '');
    let unique = base;
    let n = 2;
    while (used.has(`${unique}.md`)) unique = `${base}-${n++}`;
    used.add(`${unique}.md`);

    let markdown = result.markdown;
    let assets = result.assets.map((a) => ({ name: a.name, data: a.data }));
    // 이름이 겹쳐 바뀌었다면 이미지 폴더와 본문 참조도 함께 옮긴다
    if (unique !== base && result.assetDir) {
      const newDir = `${unique}.assets`;
      markdown = markdown.split(`(${result.assetDir}/`).join(`(${newDir}/`);
      assets = assets.map((a) => ({ ...a, name: newDir + a.name.slice(result.assetDir.length) }));
    }
    entries.push({ name: `${unique}.md`, data: markdown }, ...assets);
  }

  try {
    saveBlob(await makeZip(entries), 'markdown.zip');
  } catch (err) {
    toast(`ZIP 생성에 실패했습니다: ${err.message || err}`);
  }
};

clearBtn.onclick = () => {
  files = [];
  selectedUid = null;
  clearPreview();
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
