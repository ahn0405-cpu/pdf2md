/* PDF -> Markdown 변환기 (브라우저에서 동작).
 *
 * MuPDF(WASM)의 구조화 텍스트에서 글꼴·크기·굵기·좌표를 받아 원본의 시각적 서식을
 * Markdown으로 옮긴다. 파일은 이 함수 밖으로 나가지 않는다.
 *
 * 핵심 아이디어
 * - 문서 전체의 글자 크기 분포에서 '본문 크기'를 추정하고, 그보다 큰 크기를 h1..h6에 매핑한다.
 *   PDF 북마크(목차)가 있으면 그쪽을 우선한다.
 * - 표는 페이지에 그려진 괘선(벡터 경로)을 모아 격자를 복원해서 만든다.
 * - 페이지를 가로 여백(gutter) 기준으로 단(column)으로 나눠 읽기 순서를 되살린다.
 * - 여러 페이지에 반복되는 머리말/꼬리말·쪽번호를 통계로 찾아 제거한다.
 */

export const DEFAULT_OPTIONS = {
  detectHeadings: true,     // 글자 크기/북마크로 제목 인식
  useToc: true,             // PDF 북마크를 제목 계층에 사용
  detectLists: true,        // 글머리표·번호 목록 인식
  inlineStyles: true,       // **굵게**, *기울임*, `고정폭`
  links: true,              // PDF 링크 주석을 [text](url) 로
  tables: 'markdown',       // markdown | html | text | skip
  images: 'extract',        // extract | base64 | skip
  stripHeaderFooter: true,  // 반복 머리말/꼬리말·쪽번호 제거
  joinHyphens: true,        // 줄바꿈 하이픈 병합
  pageSeparator: false,     // 페이지마다 --- 삽입
  pageComment: false,       // 페이지마다 <!-- page N --> 주석
  frontMatter: false,       // YAML front matter
  columns: true,            // 다단 레이아웃 읽기 순서 복원
};

const STEXT_FLAGS = 'preserve-whitespace,preserve-spans,preserve-images';
// 이미지를 쓰지 않을 때는 아예 만들지 않는다 — 만들어 두면 해제 비용만 든다
const STEXT_FLAGS_NO_IMAGES = 'preserve-whitespace,preserve-spans';

/* ------------------------------------------------------------------ */
/* 문자열 유틸                                                          */
/* ------------------------------------------------------------------ */

const BULLETS = '•‣▪▫●○◦⁃∙·■□❖➤➔§';
const BULLET_RE = new RegExp(`^\\s*([${BULLETS}]|[-*+–—])\\s+(?=\\S)`);
const ORDERED_RE = new RegExp(
  '^\\s*(' +
  '\\d{1,3}[.)]' +               // 1. / 1)
  '|\\(\\d{1,3}\\)' +            // (1)
  '|[a-zA-Z][.)]' +              // a. / a)
  '|\\([a-zA-Z]\\)' +            // (a)
  '|[ivxIVX]{1,5}[.)]' +         // iv.
  '|[가-힣][.)]' +       // 가. / 가)
  '|\\([가-힣]\\)' +     // (가)
  ')\\s+(?=\\S)'
);
const CIRCLED_RE = /^\s*([①-⑳㉑-㉟㊱-㊿])\s*(?=\S)/;
const NUMBERED_HEADING_RE = /^\s*(?:\d+(?:\.\d+){0,4}[.)]?\s+\S|제\s*\d+\s*[장절편관조항]\s*)/;

// 한자·가나는 아무 곳에서나 줄이 바뀌므로 이어 붙일 때 공백을 넣지 않는다.
// 한글은 어절 사이 공백에서 줄이 바뀌므로 공백을 되살려야 한다.
const NOSPACE_CJK_RE = /[⺀-鿿豈-﫿぀-ヿㇰ-ㇿ]/;
const MONO_NAME_RE = /(mono|courier|consol|menlo|d2coding|nanumgothiccoding)/i;

const normWs = (s) => s.replace(/\s+/g, ' ').trim();
const isNospaceCjk = (ch) => NOSPACE_CJK_RE.test(ch);

/** 머리말/꼬리말 비교용 지문 — 숫자는 자리표시자로 바꾼다. */
function fingerprint(text) {
  return text.normalize('NFKC').replace(/\d+/g, '#').replace(/\s+/g, '').toLowerCase();
}

/** Markdown 특수문자 이스케이프(과하지 않게). */
export function escapeMd(text) {
  return text.replace(/\\/g, '\\\\').replace(/([*_`[\]<>])/g, '\\$1');
}

const LEADING_NUM_RE = /^(\s*)(\d{1,9})([.)]\s)/;

/** 문단 첫머리가 우연히 Markdown 문법으로 읽히는 것을 막는다.
 *  번호는 `\1.` 이 아니라 `1\.` 처럼 구두점 앞에 역슬래시를 넣어야 한다. */
export function escapeLeading(line) {
  const m = LEADING_NUM_RE.exec(line);
  if (m) return `${m[1]}${m[2]}\\${m[3]}${line.slice(m[0].length)}`;
  return line.replace(/^(\s*)([#>|]|[-+*](?=\s))/, '$1\\$2');
}

/** 전체가 하나의 강조로 감싸인 경우에만 그 표시를 벗긴다. */
export function stripOuterEmphasis(text) {
  for (const mark of ['***', '**', '*']) {
    if (text.length > 2 * mark.length && text.startsWith(mark) && text.endsWith(mark)) {
      const inner = text.slice(mark.length, -mark.length);
      if (!inner.includes(mark)) return inner;
    }
  }
  return text;
}

function htmlEscape(text) {
  return text.replace(/&/g, '&amp;').replace(/</g, '&lt;')
             .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

/** 이미지 중복 판정용 해시 (FNV-1a + 길이). */
function contentHash(bytes) {
  let h = 0x811c9dc5;
  for (let i = 0; i < bytes.length; i++) {
    h ^= bytes[i];
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return `${bytes.length}-${h.toString(16)}`;
}

/* ------------------------------------------------------------------ */
/* 표: 페이지에 그려진 괘선에서 격자를 복원                              */
/* ------------------------------------------------------------------ */

/** 페이지의 벡터 경로에서 가로/세로 괘선을 모은다. */
function collectRules(mupdf, page) {
  const hs = [];   // {y, x0, x1}
  const vs = [];   // {x, y0, y1}
  const THIN = 2.0;

  const addSubpath = (pts) => {
    if (pts.length < 2) return;
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (const [x, y] of pts) {
      x0 = Math.min(x0, x); y0 = Math.min(y0, y);
      x1 = Math.max(x1, x); y1 = Math.max(y1, y);
    }
    const w = x1 - x0, h = y1 - y0;
    // 가는 선이거나 가는 직사각형(칠해진 괘선)이면 선으로 본다
    if (h <= THIN && w > THIN) hs.push({ y: (y0 + y1) / 2, x0, x1 });
    else if (w <= THIN && h > THIN) vs.push({ x: (x0 + x1) / 2, y0, y1 });
  };

  // 경로 좌표는 경로 자신의 공간(PDF 좌표계, 아래가 원점)으로 오고, 그 좌표를
  // 구조화 텍스트와 같은 공간(위가 원점)으로 옮기는 행렬이 콜백 인자로 함께 온다.
  // 적용하지 않으면 글자와 다른 자리에 놓여 표를 찾지 못한다. 회전된 페이지도 이 행렬이 처리한다.
  const apply = (m, x, y) => [m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5]];

  const walker = (m) => {
    let pts = [];
    let start = null;
    return {
      moveTo(x, y) { addSubpath(pts); start = apply(m, x, y); pts = [start]; },
      lineTo(x, y) { pts.push(apply(m, x, y)); },
      curveTo(x1, y1, x2, y2, x3, y3) {
        pts.push(apply(m, x1, y1), apply(m, x2, y2), apply(m, x3, y3));
      },
      closePath() { if (start) pts.push(start); addSubpath(pts); pts = []; },
    };
  };

  // 콜백이 받는 path/stroke/colorspace 는 소유권이 있는 참조라 받은 쪽이 해제해야 한다.
  const drain = (path, ctm, ...owned) => {
    try {
      const w = walker(ctm || [1, 0, 0, 1, 0, 0]);
      path.walk(w);
      w.closePath();
    } finally {
      for (const obj of [path, ...owned]) {
        try { obj?.destroy?.(); } catch { /* 무시 */ }
      }
    }
  };

  let device;
  try {
    // 괘선을 찾는 데 필요한 두 콜백만 선언한다. mupdf 는 선언해 둔 콜백에 대해서만
    // 래퍼 객체를 만들어 넘기므로, 쓰지도 않을 no-op 을 늘어놓으면 그만큼 그냥 샌다.
    device = new mupdf.Device({
      fillPath(path, evenOdd, ctm, colorspace) { drain(path, ctm, colorspace); },
      strokePath(path, stroke, ctm, colorspace) { drain(path, ctm, stroke, colorspace); },
    });
    page.run(device, mupdf.Matrix.identity);
  } catch {
    return { hs: [], vs: [] };
  } finally {
    try { device?.close?.(); device?.destroy?.(); } catch { /* 무시 */ }
  }
  return { hs, vs };
}

/** 좌표가 가까운 괘선들을 하나로 합친다. */
function clusterRules(rules, key, tol) {
  const sorted = [...rules].sort((a, b) => a[key] - b[key]);
  const out = [];
  for (const r of sorted) {
    const last = out[out.length - 1];
    if (last && Math.abs(r[key] - last[key]) <= tol) {
      last.lo = Math.min(last.lo, r.lo);
      last.hi = Math.max(last.hi, r.hi);
    } else {
      out.push({ [key]: r[key], lo: r.lo, hi: r.hi });
    }
  }
  return out;
}

/** 서로 맞닿은 괘선들을 묶어 표 후보 영역을 만든다. */
function findTableGrids(hs, vs) {
  const H = clusterRules(hs.map(r => ({ y: r.y, lo: r.x0, hi: r.x1 })), 'y', 2.5);
  const V = clusterRules(vs.map(r => ({ x: r.x, lo: r.y0, hi: r.y1 })), 'x', 2.5);
  if (H.length < 2 || V.length < 2) return [];

  const SLACK = 3.0;
  const touches = (h, v) =>
    v.x >= h.lo - SLACK && v.x <= h.hi + SLACK &&
    h.y >= v.lo - SLACK && h.y <= v.hi + SLACK;

  // 교차 관계로 연결 요소를 찾는다 (한 페이지에 표가 여럿일 수 있다)
  const nodes = [...H.map(h => ({ kind: 'h', r: h })), ...V.map(v => ({ kind: 'v', r: v }))];
  const parent = nodes.map((_, i) => i);
  const find = (i) => (parent[i] === i ? i : (parent[i] = find(parent[i])));
  const union = (a, b) => { const ra = find(a), rb = find(b); if (ra !== rb) parent[ra] = rb; };

  for (let i = 0; i < nodes.length; i++) {
    for (let j = i + 1; j < nodes.length; j++) {
      if (nodes[i].kind === nodes[j].kind) continue;
      const h = nodes[i].kind === 'h' ? nodes[i].r : nodes[j].r;
      const v = nodes[i].kind === 'h' ? nodes[j].r : nodes[i].r;
      if (touches(h, v)) union(i, j);
    }
  }

  const groups = new Map();
  nodes.forEach((n, i) => {
    const root = find(i);
    if (!groups.has(root)) groups.set(root, { h: [], v: [] });
    groups.get(root)[n.kind].push(n.r);
  });

  const grids = [];
  for (const g of groups.values()) {
    if (g.h.length < 2 || g.v.length < 2) continue;      // 최소 1행 1열
    const ys = g.h.map(h => h.y).sort((a, b) => a - b);
    const xs = g.v.map(v => v.x).sort((a, b) => a - b);
    const bbox = [xs[0], ys[0], xs[xs.length - 1], ys[ys.length - 1]];
    if (bbox[2] - bbox[0] < 20 || bbox[3] - bbox[1] < 10) continue;
    grids.push({ xs, ys, bbox });
  }
  return grids;
}

/** 격자에 글 조각을 배치해 표 데이터를 만든다.
 *
 * 한 행의 셀들은 같은 기준선을 공유해 MuPDF 가 한 줄로 묶어 버리므로,
 * 줄이 아니라 스팬 단위로 넣어야 열이 뭉개지지 않는다. */
function gridToRows(grid, spans) {
  const { xs, ys } = grid;
  const rows = Array.from({ length: ys.length - 1 },
    () => Array.from({ length: xs.length - 1 }, () => []));

  for (const span of spans) {
    if (!span.text.trim()) continue;
    const cx = (span.bbox[0] + span.bbox[2]) / 2;
    const cy = (span.bbox[1] + span.bbox[3]) / 2;
    let r = -1, c = -1;
    for (let i = 0; i < ys.length - 1; i++) if (cy >= ys[i] && cy <= ys[i + 1]) { r = i; break; }
    for (let i = 0; i < xs.length - 1; i++) if (cx >= xs[i] && cx <= xs[i + 1]) { c = i; break; }
    if (r >= 0 && c >= 0) rows[r][c].push(span);
  }

  return rows.map(row => row.map(cell => {
    cell.sort((a, b) => (a.bbox[1] - b.bbox[1]) || (a.bbox[0] - b.bbox[0]));
    // 같은 기준선끼리는 이어 붙이고, 줄이 바뀌면 개행으로 남긴다
    const lines = [];
    let lastY = null;
    for (const s of cell) {
      if (lastY !== null && Math.abs(s.bbox[1] - lastY) > 1.5) lines.push('');
      lines[Math.max(0, lines.length - 1)] = (lines[lines.length - 1] || '') + s.text;
      if (!lines.length) lines.push(s.text);
      lastY = s.bbox[1];
    }
    return lines.map(normWs).filter(Boolean).join('\n');
  }));
}

/* ------------------------------------------------------------------ */
/* 표 렌더링                                                            */
/* ------------------------------------------------------------------ */

function cleanGrid(rows) {
  const kept = rows.filter(r => r.some(c => c && c.trim()));
  if (!kept.length) return { grid: [], width: 0 };
  const width = Math.max(...kept.map(r => r.length));
  const grid = kept.map(r => {
    const cells = r.map(c => normWs((c || '').replace(/\n+/g, '\n')).replace(/ ?\n ?/g, '\n'));
    while (cells.length < width) cells.push('');
    return cells;
  });
  return { grid, width };
}

export function tableToMarkdown(rows) {
  const { grid, width } = cleanGrid(rows);
  if (!grid.length) return '';
  // 셀 내용이 표 문법·강조·원시 HTML 로 읽히지 않게 막는다
  const cell = (t) => escapeMd(t).replace(/\|/g, '\\|').replace(/\n/g, '<br>');
  const header = grid[0].map((c, i) => c || `열${i + 1}`);
  const out = [
    `| ${header.map(cell).join(' | ')} |`,
    `| ${Array(width).fill('---').join(' | ')} |`,
  ];
  for (const r of grid.slice(1)) out.push(`| ${r.map(cell).join(' | ')} |`);
  return out.join('\n');
}

export function tableToHtml(rows) {
  const { grid } = cleanGrid(rows);
  if (!grid.length) return '';
  const out = ['<table>'];
  grid.forEach((row, i) => {
    const tag = i === 0 ? 'th' : 'td';
    out.push('  <tr>' + row.map(c =>
      `<${tag}>${htmlEscape(c).replace(/\n/g, '<br>')}</${tag}>`).join('') + '</tr>');
  });
  out.push('</table>');
  return out.join('\n');
}

export function tableToText(rows) {
  const { grid } = cleanGrid(rows);
  if (!grid.length) return '';
  return '```\n' + grid.map(r => r.map(c => c.replace(/\n/g, ' ')).join('\t')).join('\n') + '\n```';
}

/* ------------------------------------------------------------------ */
/* 줄/블록 모델                                                         */
/* ------------------------------------------------------------------ */

const lineText = (line) => line.spans.map(s => s.text).join('');

function lineSize(line) {
  let total = 0, sum = 0;
  for (const s of line.spans) {
    const n = s.text.trim().length;
    if (n) { total += n; sum += n * s.size; }
  }
  return total ? sum / total : 0;
}

const allBold = (line) => {
  const s = line.spans.filter(x => x.text.trim());
  return s.length > 0 && s.every(x => x.bold);
};
const allMono = (line) => {
  const s = line.spans.filter(x => x.text.trim());
  return s.length > 0 && s.every(x => x.mono);
};

function rectToBox(r) {
  return Array.isArray(r) ? [r[0], r[1], r[2], r[3]] : [r.x, r.y, r.x + r.w, r.y + r.h];
}

/** 글리프 사각형(8개 좌표) -> [x0,y0,x1,y1] */
function quadToBox(q) {
  const xs = [q[0], q[2], q[4], q[6]];
  const ys = [q[1], q[3], q[5], q[7]];
  return [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)];
}

/** 구조화 텍스트를 훑어 블록/줄/스팬과 이미지를 한 번에 모은다.
 *
 * asJSON 대신 walk 를 쓰는 이유: 글자 크기가 정수로 반올림되지 않고,
 * 글꼴의 굵게/기울임/고정폭 여부를 이름 추측 없이 정확히 얻을 수 있으며,
 * 글자 단위 좌표가 있어 표 셀에 글을 배치할 수 있다.
 */
/** 같은 기준선에 놓인 조각들을 한 줄로 합친다.
 *
 * preserve-spans 를 켜면 MuPDF 가 글꼴이 바뀔 때마다 줄을 끊어 준다. 그대로 두면
 * "Body Text: DejaVuSans" 처럼 한 줄인 제목이 둘로 쪼개지므로 다시 이어 붙인다. */
function mergeSameBaseline(lines) {
  const sorted = [...lines].sort((a, b) => (a.bbox[1] - b.bbox[1]) || (a.bbox[0] - b.bbox[0]));
  const out = [];
  for (const line of sorted) {
    const prev = out[out.length - 1];
    const height = Math.max(line.bbox[3] - line.bbox[1], 1e-6);
    const overlap = prev
      ? Math.min(prev.bbox[3], line.bbox[3]) - Math.max(prev.bbox[1], line.bbox[1])
      : 0;
    if (prev && overlap > height * 0.6) {
      prev.spans.push(...line.spans);
      prev.spans.sort((a, b) => a.bbox[0] - b.bbox[0]);
      prev.bbox = unionBox([prev.bbox, line.bbox]);
    } else {
      out.push(line);
    }
  }
  return out;
}

function parsePage(st, linkRects, wantImages) {
  const blocks = [];
  const images = [];
  let block = null;
  let line = null;
  let cur = null;

  const pushSpan = () => {
    if (cur && cur.text) {
      cur.link = linkFor(cur.bbox, linkRects);
      line.spans.push(cur);
    }
    cur = null;
  };

  st.walk({
    beginTextBlock(bbox) { block = { kind: 'text', bbox: rectToBox(bbox), lines: [] }; },
    endTextBlock() {
      if (block && block.lines.length) {
        block.lines = mergeSameBaseline(block.lines);
        blocks.push(block);
      }
      block = null;
    },
    beginLine(bbox) { line = { bbox: rectToBox(bbox), spans: [] }; cur = null; },
    endLine() {
      pushSpan();
      if (line && line.spans.length && lineText(line).trim()) {
        line.bbox = unionBox(line.spans.map(s => s.bbox));
        (block ? block.lines : (blocks.push({ kind: 'text', bbox: line.bbox, lines: [] }),
          blocks[blocks.length - 1].lines)).push(line);
      }
      line = null;
      cur = null;
    },
    onChar(c, origin, font, size, quad) {
      // walk 는 글자마다 Font 래퍼를 새로 만들어 넘긴다. 이 참조는 GC 가 돌 때까지
      // WASM 힙에 남으므로, 필요한 값만 읽고 그 자리에서 돌려준다.
      // (긴 문서를 여러 개 변환할 때 메모리가 계속 느는 가장 큰 원인이었다)
      const name = font.getName?.() || '';
      const style = {
        size: Math.round(size * 100) / 100,
        bold: !!font.isBold?.(),
        italic: !!font.isItalic?.(),
        mono: !!font.isMono?.() || MONO_NAME_RE.test(name),
      };
      try { font.destroy?.(); } catch { /* 무시 */ }

      if (!line) return;
      const box = quadToBox(quad);
      const key = `${name}|${style.size}|${style.bold}|${style.italic}|${style.mono}`;
      // 같은 글꼴이어도 가로로 크게 벌어지면 다른 조각으로 본다(표 셀 구분)
      const contiguous = cur && cur.key === key && (box[0] - cur.bbox[2]) <= style.size * 1.2;
      if (contiguous) {
        cur.text += c;
        cur.bbox = unionBox([cur.bbox, box]);
      } else {
        pushSpan();
        cur = { key, text: c, bbox: box, link: null, ...style };
      }
    },
    onImageBlock(bbox, ctm, image) {
      // walk 가 넘겨주는 이미지와 거기서 뜬 Pixmap 은 받은 쪽이 해제해야 한다.
      // 놓치면 WASM 힙에 그대로 쌓여 파일을 여러 개 변환할수록 메모리가 계속 는다.
      let pix = null;
      try {
        if (!wantImages) return;
        const b = rectToBox(bbox);
        if (b[2] - b[0] < 12 || b[3] - b[1] < 12) return;   // 구분선·아이콘 수준은 건너뜀
        pix = image.toPixmap();
        images.push({ bbox: b, data: new Uint8Array(pix.asPNG()), ext: 'png' });
      } catch { /* 디코딩 실패는 건너뜀 */
      } finally {
        try { pix?.destroy?.(); } catch { /* 무시 */ }
        try { image?.destroy?.(); } catch { /* 무시 */ }
      }
    },
  });

  return { blocks, images };
}

function unionBox(boxes) {
  return [
    Math.min(...boxes.map(b => b[0])), Math.min(...boxes.map(b => b[1])),
    Math.max(...boxes.map(b => b[2])), Math.max(...boxes.map(b => b[3])),
  ];
}

function linkFor(bbox, linkRects) {
  if (!linkRects.length) return null;
  const area = Math.max((bbox[2] - bbox[0]) * (bbox[3] - bbox[1]), 1e-6);
  for (const { rect, uri } of linkRects) {
    const ix = Math.max(0, Math.min(bbox[2], rect[2]) - Math.max(bbox[0], rect[0]));
    const iy = Math.max(0, Math.min(bbox[3], rect[3]) - Math.max(bbox[1], rect[1]));
    if (ix * iy > 0.4 * area) return uri;
  }
  return null;
}

function overlapRatio(a, b) {
  const ix = Math.max(0, Math.min(a[2], b[2]) - Math.max(a[0], b[0]));
  const iy = Math.max(0, Math.min(a[3], b[3]) - Math.max(a[1], b[1]));
  return (ix * iy) / Math.max((a[2] - a[0]) * (a[3] - a[1]), 1e-6);
}

/* ------------------------------------------------------------------ */
/* 읽기 순서 (밴드 -> 단)                                               */
/* ------------------------------------------------------------------ */

function splitColumns(elems, x0, x1, depth = 0) {
  if (depth >= 2 || elems.length < 4) return [elems];
  const width = x1 - x0;
  if (width <= 0) return [elems];

  const BINS = 200;
  const covered = new Array(BINS).fill(false);
  for (const el of elems) {
    const b0 = Math.max(0, Math.floor((el.bbox[0] - x0) / width * BINS));
    const b1 = Math.min(BINS - 1, Math.ceil((el.bbox[2] - x0) / width * BINS));
    for (let i = b0; i <= b1; i++) covered[i] = true;
  }

  let best = null;
  for (let i = 0; i < BINS;) {
    if (covered[i]) { i++; continue; }
    let j = i;
    while (j < BINS && !covered[j]) j++;
    const center = ((i + j - 1) / 2) / BINS;
    if (center >= 0.20 && center <= 0.80 && (j - i) >= BINS * 0.035) {
      if (!best || (j - 1 - i) > (best[1] - best[0])) best = [i, j - 1];
    }
    i = j;
  }
  if (!best) return [elems];

  const cut = x0 + ((best[0] + best[1]) / 2 / BINS) * width;
  const left = elems.filter(e => (e.bbox[0] + e.bbox[2]) / 2 < cut);
  const right = elems.filter(e => (e.bbox[0] + e.bbox[2]) / 2 >= cut);
  if (!left.length || !right.length) return [elems];
  return [...splitColumns(left, x0, cut, depth + 1), ...splitColumns(right, cut, x1, depth + 1)];
}

const byPosition = (a, b) =>
  (Math.round(a.bbox[1] * 10) - Math.round(b.bbox[1] * 10)) ||
  (Math.round(a.bbox[0] * 10) - Math.round(b.bbox[0] * 10));

function flushBand(band, pageBox) {
  const cols = splitColumns(band, pageBox[0], pageBox[2]);
  if (cols.length <= 1) return [...band].sort(byPosition);
  cols.sort((a, b) => Math.min(...a.map(e => e.bbox[0])) - Math.min(...b.map(e => e.bbox[0])));
  return cols.flatMap(col => [...col].sort(byPosition));
}

function orderElements(elems, pageBox, useColumns) {
  const sorted = [...elems].sort(byPosition);
  if (!useColumns || sorted.length < 4) return sorted;

  const pageW = (pageBox[2] - pageBox[0]) || 1;
  const ordered = [];
  let band = [];
  for (const el of sorted) {
    // 전폭 요소를 경계로 세로 밴드를 나눈 뒤, 각 밴드 안에서만 단을 찾는다
    if ((el.bbox[2] - el.bbox[0]) > pageW * 0.66) {
      if (band.length) { ordered.push(...flushBand(band, pageBox)); band = []; }
      ordered.push(el);
    } else {
      band.push(el);
    }
  }
  if (band.length) ordered.push(...flushBand(band, pageBox));
  return ordered;
}

/* ------------------------------------------------------------------ */
/* 블록 병합                                                            */
/* ------------------------------------------------------------------ */

const elemAllMono = (el) => el.lines?.length > 0 && el.lines.every(allMono);

/** 블록 안 줄 간격의 중앙값 — 사이에 빈 줄이 몇 개 들어갔는지 재는 자. */
function linePitch(el) {
  const lines = el.lines || [];
  if (lines.length < 2) return 0;
  const gaps = [];
  for (let i = 1; i < lines.length; i++) gaps.push(lines[i].bbox[1] - lines[i - 1].bbox[1]);
  gaps.sort((a, b) => a - b);
  return gaps[Math.floor(gaps.length / 2)];
}

function elemSize(el) {
  const sizes = el.lines.map(lineSize).filter(Boolean).sort((a, b) => a - b);
  return sizes.length ? sizes[Math.floor(sizes.length / 2)] : 0;
}

/** 줄 간격만큼만 떨어진 연속 텍스트 블록을 한 문단 덩어리로 합친다.
 *  PDF 생성기에 따라 한 문단의 각 줄이 별개 블록으로 나오는 경우가 많다. */
function mergeTextElements(elems) {
  const out = [];
  for (const el of elems) {
    const prev = out[out.length - 1];
    if (el.kind !== 'text' || !prev || prev.kind !== 'text') { out.push(el); continue; }

    const size = elemSize(el) || 10;
    const prevSize = elemSize(prev) || 10;
    const gap = el.bbox[1] - prev.bbox[3];
    // 코드는 줄마다 들여쓰기가 달라지는 게 정상이라 정렬 조건을 적용하지 않는다
    const bothMono = elemAllMono(prev) && elemAllMono(el);
    const aligned = bothMono || Math.abs(el.bbox[0] - prev.bbox[0]) <= Math.max(2, size * 1.6);
    const similar = Math.abs(size - prevSize) <= Math.max(0.4, prevSize * 0.12);
    // 코드에는 빈 줄이 들어가는 게 정상이라, 고정폭끼리는 빈 줄 세 개까지 건너뛰어 잇는다.
    // (끊어 버리면 코드 블록이 펜스 여러 개로 쪼개지고, 한 줄만 남은 조각은
    //  코드로 인식조차 못 해 `- foo` 가 진짜 목록으로 바뀐다)
    const pitch = linePitch(prev) || linePitch(el) || size * 1.35;
    const maxGap = bothMono ? pitch * 3.5 : Math.max(size * 0.55, 2.5);

    if (gap >= -1 && gap <= maxGap && aligned && similar) {
      prev.lines.push(...el.lines);
      prev.bbox = unionBox([prev.bbox, el.bbox]);
    } else {
      out.push(el);
    }
  }
  return out;
}

/* ------------------------------------------------------------------ */
/* 머리말/꼬리말                                                        */
/* ------------------------------------------------------------------ */

const inRunningZone = (y0, y1, h) => y1 <= h * 0.10 || y0 >= h * 0.90;

/** 그 줄이 가로줄 하나를 혼자 쓰는지.
 *  매 페이지 반복되는 본문 말머리("Best for:"처럼 뒤에 내용이 이어지는 말)는
 *  지문만 보면 꼬리말과 구별되지 않는다. 진짜 머리말/꼬리말은 줄을 혼자 차지한다. */
function isStandaloneLine(bbox, pageLines, running) {
  const height = Math.max(bbox[3] - bbox[1], 1e-6);
  for (const other of pageLines) {
    if (other.bbox === bbox) continue;
    const ov = Math.min(bbox[3], other.bbox[3]) - Math.max(bbox[1], other.bbox[1]);
    if (ov > height * 0.5 && !running.has(other.fp)) return false;
  }
  return true;
}

function detectRunning(pages) {
  if (pages.length < 3) return new Set();
  const seen = new Map();
  pages.forEach((page, pno) => {
    for (const line of page.allLines) {
      if (!inRunningZone(line.bbox[1], line.bbox[3], page.height)) continue;
      if (!line.text || line.text.length > 120) continue;
      if (!seen.has(line.fp)) seen.set(line.fp, new Set());
      seen.get(line.fp).add(pno);
    }
  });
  const threshold = Math.max(2, Math.ceil(pages.length * 0.5));
  const out = new Set();
  for (const [fp, pnos] of seen) if (fp && pnos.size >= threshold) out.add(fp);
  return out;
}

/* ------------------------------------------------------------------ */
/* 크기 통계 · 목록 들여쓰기 단계                                        */
/* ------------------------------------------------------------------ */

function collectSizeStats(pages) {
  const counter = new Map();
  for (const page of pages) {
    for (const block of page.blocks) {
      for (const line of block.lines) {
        for (const span of line.spans) {
          const n = span.text.trim().length;
          if (!n) continue;
          const key = Math.round(span.size * 10) / 10;
          counter.set(key, (counter.get(key) || 0) + n);
        }
      }
    }
  }
  if (!counter.size) return { bodySize: 10, headingMap: [] };

  let bodySize = 10, most = -1;
  for (const [size, chars] of counter) if (chars > most) { most = chars; bodySize = size; }

  // 한글 제목은 "개요"처럼 두세 글자인 경우가 흔하므로 문턱을 낮게 잡는다
  const candidates = [...counter.entries()]
    .filter(([size, chars]) => size >= bodySize * 1.08 && chars >= 3)
    .map(([size]) => size)
    .sort((a, b) => b - a);

  const grouped = [];
  for (const size of candidates) {
    if (grouped.length && Math.abs(grouped[grouped.length - 1] - size) < 0.5) continue;
    grouped.push(size);
  }
  return { bodySize, headingMap: grouped.slice(0, 6).map((size, i) => ({ size, level: i + 1 })) };
}

const looksLikeList = (t) => BULLET_RE.test(t) || ORDERED_RE.test(t) || CIRCLED_RE.test(t);

/** 목록 항목의 왼쪽 시작 x좌표를 군집화해 들여쓰기 단계를 만든다.
 *  고정 폭으로 나누면 문서마다 들여쓰기 폭이 달라 단계가 틀어진다. */
function listIndentStops(pages, bodySize) {
  const xs = [];
  for (const page of pages) {
    for (const block of page.blocks) {
      for (const line of block.lines) {
        const t = normWs(lineText(line));
        if (t && looksLikeList(t)) xs.push(Math.round(line.bbox[0] * 10) / 10);
      }
    }
  }
  if (!xs.length) return [];

  const tol = Math.max(4, bodySize * 0.5);
  xs.sort((a, b) => a - b);
  const clusters = [[xs[0]]];
  for (const x of xs.slice(1)) {
    const last = clusters[clusters.length - 1];
    if (x - last[last.length - 1] <= tol) last.push(x);
    else clusters.push([x]);
  }
  // 단계는 최대 5개까지, 자주 등장한 위치를 우선한다(오탐 방지)
  clusters.sort((a, b) => b.length - a.length);
  const keep = clusters.slice(0, 5).sort((a, b) => a[0] - b[0]);
  return keep.map(c => c.reduce((s, v) => s + v, 0) / c.length);
}

/* ------------------------------------------------------------------ */
/* 렌더러                                                              */
/* ------------------------------------------------------------------ */

class Renderer {
  constructor(opt, bodySize, headingMap, listStops) {
    this.opt = opt;
    this.bodySize = bodySize;
    this.headingMap = headingMap;
    this.listStops = listStops;
  }

  renderInline(spans) {
    const merged = [];
    for (const sp of spans) {
      if (!sp.text) continue;
      const prev = merged[merged.length - 1];
      if (prev && prev.bold === sp.bold && prev.italic === sp.italic &&
          prev.mono === sp.mono && prev.link === sp.link) {
        // 같은 서식이라도 좌표가 벌어져 있으면 공백을 되살린다
        if (sp.bbox[0] - prev.bbox[2] > sp.size * 0.2 &&
            !/\s$/.test(prev.text) && !/^\s/.test(sp.text)) prev.text += ' ';
        prev.text += sp.text;
        prev.bbox = unionBox([prev.bbox, sp.bbox]);
      } else {
        merged.push({ ...sp });
      }
    }

    let out = '';
    let prevBox = null;
    for (const sp of merged) {
      const raw = sp.text;
      if (!raw.trim()) { out += raw ? ' ' : ''; prevBox = sp.bbox; continue; }
      // 조각 사이가 눈에 띄게 벌어져 있으면 공백을 되살린다
      // (PDF 는 칸을 띄울 때 공백 문자 없이 좌표만 옮기는 경우가 많다)
      if (prevBox && !/\s$/.test(out) && !/^\s/.test(raw) &&
          sp.bbox[0] - prevBox[2] > sp.size * 0.2) {
        out += ' ';
      }
      prevBox = sp.bbox;
      const lead = raw.slice(0, raw.length - raw.trimStart().length);
      const trail = raw.slice(raw.trimEnd().length);
      const core = raw.trim();

      let text;
      if (this.opt.inlineStyles && sp.mono) {
        let tick = '`';
        while (core.includes(tick)) tick += '`';
        // 내용이 백틱으로 시작/끝나면 공백을 덧대야 안쪽 백틱이 살아남는다
        const pad = core.startsWith('`') || core.endsWith('`') ? ' ' : '';
        text = `${tick}${pad}${core}${pad}${tick}`;
      } else {
        text = escapeMd(core);
        if (this.opt.inlineStyles) {
          if (sp.bold && sp.italic) text = `***${text}***`;
          else if (sp.bold) text = `**${text}**`;
          else if (sp.italic) text = `*${text}*`;
        }
      }
      if (this.opt.links && sp.link) text = `[${text}](${sp.link})`;
      out += `${lead}${text}${trail}`;
    }
    return out.replace(/[ \t]+/g, ' ').trim();
  }

  /** 같은 문단에 속한 줄들을 자연스럽게 잇는다. */
  joinLines(chunks) {
    let out = '';
    for (const rendered of chunks) {
      if (!rendered) continue;
      if (!out) { out = rendered; continue; }
      const trimmed = out.trimEnd();
      const prevChar = trimmed.slice(-1);
      const nextChar = rendered.trimStart().slice(0, 1);
      if (this.opt.joinHyphens && prevChar === '-' && /[a-zA-Z]/.test(nextChar)) {
        out = trimmed.slice(0, -1) + rendered.trimStart();
      } else if (',.)]}·'.includes(nextChar)) {
        out = trimmed + rendered.trimStart();
      } else if (isNospaceCjk(prevChar) && isNospaceCjk(nextChar)) {
        out = trimmed + rendered.trimStart();
      } else {
        out = trimmed + ' ' + rendered.trimStart();
      }
    }
    return out;
  }

  /** [마크다운 글머리, 원본 마커, 마커를 뗀 본문] 또는 null. */
  listMarker(text) {
    if (!this.opt.detectLists) return null;
    let m = BULLET_RE.exec(text);
    if (m) return ['-', m[1], text.slice(m[0].length)];
    m = ORDERED_RE.exec(text);
    if (m) {
      const num = m[1].replace(/\D/g, '');
      return [num ? `${num}.` : '1.', m[1], text.slice(m[0].length)];
    }
    m = CIRCLED_RE.exec(text);
    // 원문자는 번호 정보를 잃지 않도록 본문 앞에 남긴다
    if (m) return ['-', '', text];
    return null;
  }

  indentLevel(x0) {
    if (!this.listStops.length) return 0;
    let best = 0;
    for (let i = 1; i < this.listStops.length; i++) {
      if (Math.abs(this.listStops[i] - x0) < Math.abs(this.listStops[best] - x0)) best = i;
    }
    return Math.min(4, best);
  }

  headingLevel(line) {
    if (!this.opt.detectHeadings) return null;
    const text = normWs(lineText(line));
    if (!text || text.length > 200) return null;
    const size = Math.round(lineSize(line) * 100) / 100;
    for (const { size: mapped, level } of this.headingMap) {
      if (Math.abs(size - mapped) < 0.26) return level;
    }
    // 본문 크기지만 굵고 짧으며 마침표로 끝나지 않는 번호형 제목
    if (allBold(line) && size >= this.bodySize - 0.3 && text.length <= 80 &&
        !/(다\.|요\.|[.,;])$/.test(text) && NUMBERED_HEADING_RE.test(text)) {
      return this.headingMap.length ? Math.min(6, this.headingMap.length + 1) : 3;
    }
    return null;
  }
}

/** 목록 마커를 span 목록 앞부분에서 걷어낸 사본을 돌려준다.
 *  마커 판정은 공백을 정규화한 문자열로 하지만 원문에는 공백이 그대로 남아 있다. */
export function stripMarkerSpans(spans, marker) {
  const wanted = [...marker].filter(ch => !/\s/.test(ch));
  if (!wanted.length) return spans;
  const out = [];
  let done = false;

  for (const sp of spans) {
    if (done) { out.push(sp); continue; }
    let rest = '';
    for (let i = 0; i < sp.text.length; i++) {
      const ch = sp.text[i];
      if (done) { rest = sp.text.slice(i); break; }
      if (/\s/.test(ch)) continue;
      if (wanted.length && ch === wanted[0]) {
        wanted.shift();
        if (!wanted.length) done = true;
        continue;
      }
      done = true;            // 예상과 다른 글자를 만나면 자르기를 중단한다
      rest = sp.text.slice(i);
      break;
    }
    if (rest.trim()) out.push({ ...sp, text: rest });
  }
  return out.length ? out : spans;
}

/** 코드 블록 본문 — 들여쓰기를 살린다.
 *  원문에 공백이 없으면 각 줄의 x좌표 차이를 글자 폭으로 나눠 복원한다. */
function codeBlockBody(lines) {
  const baseX = Math.min(...lines.map(l => l.bbox[0]));
  const sizes = lines.map(lineSize).filter(Boolean);
  const avgSize = sizes.length ? sizes.reduce((a, b) => a + b, 0) / sizes.length : 10;
  const charW = Math.max(1, avgSize * 0.6);

  // 빈 줄에는 글자가 없어 줄 자체가 없다. 가장 좁은 줄 간격을 한 줄 높이로 보고
  // 그보다 벌어진 자리에 빈 줄을 되살린다. (중앙값을 쓰면 빈 줄이 많은 코드에서
  // 기준 자체가 늘어나 정작 빈 줄을 못 찾는다)
  const pitches = [];
  for (let i = 1; i < lines.length; i++) {
    const d = lines[i].bbox[1] - lines[i - 1].bbox[1];
    if (d > 0) pitches.push(d);
  }
  // 간격이 하나뿐이면(줄이 둘) 그게 한 줄 높이인지 빈 줄이 낀 건지 알 수 없다 —
  // 그때만 글자 크기로 어림잡는다.
  const pitch = pitches.length >= 2
    ? Math.max(Math.min(...pitches), avgSize)
    : avgSize * 1.45;

  const out = [];
  lines.forEach((line, i) => {
    if (i > 0 && pitch > 0) {
      const blanks = Math.round((line.bbox[1] - lines[i - 1].bbox[1]) / pitch) - 1;
      for (let k = 0; k < Math.min(blanks, 3); k++) out.push('');
    }
    const raw = lineText(line).replace(/\s+$/, '');
    if (!raw.trim()) { out.push(''); return; }
    if (/^\s/.test(raw)) { out.push(raw); return; }
    const pad = Math.max(0, Math.round((line.bbox[0] - baseX) / charW));
    out.push(' '.repeat(pad) + raw);
  });
  return out.join('\n');
}

function renderTextBlock(el, r, tocTitles) {
  const chunks = [];
  const gaps = [];
  for (let i = 1; i < el.lines.length; i++) {
    gaps.push(Math.max(0, el.lines[i].bbox[1] - el.lines[i - 1].bbox[3]));
  }
  gaps.sort((a, b) => a - b);
  const medianGap = gaps.length ? gaps[Math.floor(gaps.length / 2)] : 0;

  // 코드 블록: 블록 전체가 고정폭 글꼴
  if (el.lines.length > 1 && el.lines.every(allMono)) {
    const body = codeBlockBody(el.lines);
    // 본문 안에 백틱 울타리가 들어 있으면 더 긴 울타리로 감싸야 안 깨진다
    let fence = '```';
    while (new RegExp(`^\\s*${fence}(?!\`)`, 'm').test(body)) fence += '`';
    return [`${fence}\n${body}\n${fence}`];
  }

  let pending = [];
  let pendingPrefix = '';
  const flush = () => {
    if (!pending.length) return;
    const text = r.joinLines(pending);
    if (text) chunks.push(pendingPrefix ? pendingPrefix + text : escapeLeading(text));
    pending = [];
    pendingPrefix = '';
  };

  let prevLine = null;
  for (const line of el.lines) {
    const text = normWs(lineText(line));
    if (!text) continue;

    // 1) 북마크(목차) 제목 우선  2) 글자 크기 기반
    let level = null;
    for (const { level: lvl, title } of tocTitles) {
      if (title && (text === title || (title.length > 6 && text.startsWith(title)))) { level = lvl; break; }
    }
    if (level === null) level = r.headingLevel(line);

    if (level !== null) {
      flush();
      const inline = stripOuterEmphasis(r.renderInline(line.spans)).trim();
      if (inline) chunks.push('#'.repeat(level) + ' ' + inline);
      prevLine = line;
      continue;
    }

    const marker = r.listMarker(text);
    if (marker) {
      flush();
      const [bullet, rawMarker, rest] = marker;
      const indent = '  '.repeat(r.indentLevel(line.bbox[0]));
      const trimmed = stripMarkerSpans(line.spans, rawMarker);
      const inline = r.renderInline(trimmed) || escapeMd(normWs(rest));
      pendingPrefix = `${indent}${bullet} `;
      pending = [inline];
      prevLine = line;
      continue;
    }

    // 문단 분리: 줄 간격이 눈에 띄게 벌어지면 새 문단
    if (prevLine && medianGap > 0) {
      const gap = line.bbox[1] - prevLine.bbox[3];
      if (gap > Math.max(medianGap * 1.8, medianGap + lineSize(line) * 0.6)) flush();
    }

    const inline = r.renderInline(line.spans);
    if (inline) pending.push(inline);
    prevLine = line;
  }

  flush();
  return chunks.filter(c => c.trim());
}

/** 빈 줄을 정리한다 — 연속된 빈 줄은 하나로, 목록 항목 사이의 빈 줄은 없애
 *  촘촘한 목록으로 만든다. 코드 울타리 안쪽은 원문 그대로 둔다(빈 줄도 코드의 일부다). */
function normalizeBlankLines(markdown) {
  const item = /^\s*(?:[-*+]|\d{1,3}\.)\s+\S/;
  const lines = markdown.split('\n');
  const out = [];
  let fence = null;

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const open = /^\s*(`{3,}|~{3,})/.exec(line);
    if (fence === null && open) fence = open[1][0].repeat(open[1].length);
    else if (fence !== null && open && open[1].startsWith(fence)) fence = null;

    if (fence !== null || (open && fence === null)) { out.push(line); continue; }
    if (!line.trim()) {
      const prev = out[out.length - 1];
      if (prev === undefined || !prev.trim()) continue;      // 연속된 빈 줄은 하나로
      let j = i + 1;
      while (j < lines.length && !lines[j].trim()) j++;
      if (item.test(prev) && j < lines.length && item.test(lines[j])) continue;
    }
    out.push(line);
  }
  return out.join('\n');
}

/* ------------------------------------------------------------------ */
/* 메인                                                                */
/* ------------------------------------------------------------------ */

function safeStem(filename) {
  const stem = filename.replace(/\.pdf$/i, '') || 'document';
  return stem.replace(/[^\w\-.가-힣]+/g, '_').replace(/^_+|_+$/g, '') || 'document';
}

function tocByPage(doc, maxPages) {
  const byPage = new Map();
  const walk = (nodes, depth) => {
    for (const node of nodes || []) {
      const page = typeof node.page === 'number' ? node.page : null;
      if (page !== null && page >= 0 && page < maxPages) {
        if (!byPage.has(page)) byPage.set(page, []);
        byPage.get(page).push({ level: Math.min(6, Math.max(1, depth)), title: normWs(node.title || '') });
      }
      if (node.down) walk(node.down, depth + 1);
    }
  };
  try { walk(doc.loadOutline(), 1); } catch { /* 북마크 없음 */ }
  return byPage;
}

/**
 * PDF 한 개를 Markdown으로 변환한다.
 * @param {object} mupdf   mupdf.js 모듈
 * @param {Uint8Array} bytes
 * @param {string} filename
 * @param {object} options
 * @returns {{markdown:string, assets:Array, warnings:string[], stats:object, assetDir:string}}
 */
export function convert(mupdf, bytes, filename = 'document.pdf', options = {}) {
  const opt = { ...DEFAULT_OPTIONS, ...options };
  const stem = safeStem(filename);
  const assetDir = `${stem}.assets`;
  const warnings = [];
  const assets = [];

  let doc;
  try {
    doc = mupdf.Document.openDocument(bytes, 'application/pdf');
  } catch (err) {
    throw new Error(`PDF를 열 수 없습니다: ${err.message || err}`);
  }
  if (doc.needsPassword && doc.needsPassword()) {
    doc.destroy?.();
    throw new Error('암호로 보호된 PDF입니다. 암호를 해제한 뒤 다시 시도하세요.');
  }

  const pageCount = doc.countPages();
  const pages = [];

  try {
    const wantImages = opt.images !== 'skip';
    for (let pno = 0; pno < pageCount; pno++) {
      const page = doc.loadPage(pno);
      // 페이지 도중에 예외가 나도 WASM 쪽 객체는 반드시 돌려준다
      let st = null;
      try {
        const box = page.getBounds();
        const pageBox = Array.isArray(box) ? box : rectToBox(box);

        const linkRects = [];
        if (opt.links) {
          try {
            for (const link of page.getLinks()) {
              const uri = link.getURI?.();
              if (uri) {
                const b = link.getBounds();
                linkRects.push({ rect: Array.isArray(b) ? b : rectToBox(b), uri });
              }
              try { link.destroy?.(); } catch { /* 무시 */ }
            }
          } catch { /* 링크 없음 */ }
        }

        st = page.toStructuredText(wantImages ? STEXT_FLAGS : STEXT_FLAGS_NO_IMAGES);
        const { blocks, images } = parsePage(st, linkRects, wantImages);

        const grids = opt.tables !== 'skip' ? (() => {
          const { hs, vs } = collectRules(mupdf, page);
          return findTableGrids(hs, vs);
        })() : [];

        const allLines = blocks.flatMap(b => b.lines.map(l => {
          const t = normWs(lineText(l));
          return { bbox: l.bbox, text: t, fp: fingerprint(t) };
        }));

        pages.push({
          pno, pageBox, blocks, images, grids, allLines,
          height: pageBox[3] - pageBox[1] || 1,
        });
      } finally {
        try { st?.destroy?.(); } catch { /* 무시 */ }
        try { page.destroy?.(); } catch { /* 무시 */ }
      }
    }

    const { bodySize, headingMap } = collectSizeStats(pages);
    const running = opt.stripHeaderFooter ? detectRunning(pages) : new Set();
    const tocPages = (opt.useToc && opt.detectHeadings) ? tocByPage(doc, pageCount) : new Map();
    const listStops = opt.detectLists ? listIndentStops(pages, bodySize) : [];
    const renderer = new Renderer(opt, bodySize, headingMap, listStops);

    const totalChars = pages.reduce((sum, p) => sum + p.allLines.reduce((s, l) => s + l.text.length, 0), 0);
    if (pageCount && totalChars < 40 * Math.max(1, pageCount)) {
      const hasImage = pages.some(p => p.images.length);
      warnings.push(hasImage
        ? '텍스트 레이어가 거의 없습니다. 스캔 이미지 PDF로 보이며, OCR 처리 후 변환해야 본문이 추출됩니다.'
        : '추출할 텍스트를 찾지 못했습니다. 내용이 없는 PDF이거나 지원하지 않는 인코딩일 수 있습니다.');
    }

    const out = [];
    const imagePaths = new Map();
    let nTables = 0, nImages = 0, nHeadings = 0;

    if (opt.frontMatter) {
      const fm = ['---', `source: "${filename}"`];
      const title = tryMeta(doc, 'info:Title');
      const author = tryMeta(doc, 'info:Author');
      if (title) fm.push(`title: "${normWs(title)}"`);
      if (author) fm.push(`author: "${normWs(author)}"`);
      fm.push(`pages: ${pageCount}`, '---');
      out.push(fm.join('\n'));
    }

    for (const page of pages) {
      const elems = [];

      // --- 표 ---
      const tableBoxes = [];
      for (const grid of page.grids) {
        const inside = page.blocks.flatMap(b => b.lines).flatMap(l => l.spans)
          .filter(s => overlapRatio(s.bbox, grid.bbox) > 0.5);
        const rows = gridToRows(grid, inside);
        if (rows.length < 2 || !rows.some(r => r.some(c => c.trim()))) continue;
        elems.push({ kind: 'table', bbox: grid.bbox, payload: rows });
        tableBoxes.push(grid.bbox);
      }

      // --- 이미지 ---
      for (const img of page.images) elems.push({ kind: 'image', bbox: img.bbox, payload: img });

      // --- 텍스트 ---
      for (const block of page.blocks) {
        if (tableBoxes.some(tb => overlapRatio(block.bbox, tb) > 0.55)) continue;
        const lines = block.lines.filter(line => {
          if (!opt.stripHeaderFooter) return true;
          const [, y0, , y1] = line.bbox;
          const text = normWs(lineText(line));
          // 반복 문구 제거는 페이지 가장자리에서, 그 가로줄을 혼자 쓰는 줄에만 적용한다
          if (inRunningZone(y0, y1, page.height) && running.has(fingerprint(text)) &&
              isStandaloneLine(line.bbox, page.allLines, running)) return false;
          const edge = y1 < page.height * 0.08 || y0 > page.height * 0.92;
          if (edge && /^[-–—\s]*\d{1,4}\s*(\/\s*\d{1,4})?[-–—\s]*$/.test(text)) return false;
          return true;
        });
        if (lines.length) elems.push({ kind: 'text', bbox: block.bbox, lines });
      }

      const ordered = mergeTextElements(orderElements(elems, page.pageBox, opt.columns));
      const tocTitles = tocPages.get(page.pno) || [];
      const pageMd = [];

      for (const el of ordered) {
        if (el.kind === 'table') {
          const rendered = opt.tables === 'markdown' ? tableToMarkdown(el.payload)
                         : opt.tables === 'html' ? tableToHtml(el.payload)
                         : tableToText(el.payload);
          if (rendered) { pageMd.push(rendered); nTables++; }
          continue;
        }
        if (el.kind === 'image') {
          nImages++;
          const alt = `${stem} 이미지 ${nImages}`;
          const { data, ext } = el.payload;
          if (opt.images === 'base64') {
            pageMd.push(`![${alt}](data:image/${ext};base64,${bytesToBase64(data)})`);
          } else {
            // 페이지마다 반복되는 로고 등은 같은 파일 하나로 모은다
            const digest = contentHash(data);
            let path = imagePaths.get(digest);
            if (!path) {
              path = `${assetDir}/${stem}-p${page.pno + 1}-${nImages}.${ext}`;
              imagePaths.set(digest, path);
              assets.push({ name: path, data, mime: `image/${ext}` });
            }
            pageMd.push(`![${alt}](${path})`);
          }
          continue;
        }
        pageMd.push(...renderTextBlock(el, renderer, tocTitles));
      }

      nHeadings += pageMd.filter(c => c.startsWith('#')).length;
      if (pageMd.length) {
        if (opt.pageComment) out.push(`<!-- page ${page.pno + 1} -->`);
        out.push(...pageMd);
      }
      if (opt.pageSeparator && page.pno < pageCount - 1) out.push('---');
    }

    const markdown = normalizeBlankLines(out.filter(c => c.trim()).join('\n\n')).trim() + '\n';

    return {
      markdown,
      assets,
      assetDir: assets.length ? assetDir : '',
      warnings,
      stats: {
        pages: pageCount, tables: nTables, images: nImages,
        headings: nHeadings, chars: markdown.length, bodySize,
      },
    };
  } finally {
    try { doc.destroy?.(); } catch { /* 무시 */ }
  }
}

function tryMeta(doc, key) {
  try { return doc.getMetaData(key) || ''; } catch { return ''; }
}

export function bytesToBase64(bytes) {
  let binary = '';
  const CHUNK = 0x8000;
  for (let i = 0; i < bytes.length; i += CHUNK) {
    binary += String.fromCharCode.apply(null, bytes.subarray(i, i + CHUNK));
  }
  return btoa(binary);
}
