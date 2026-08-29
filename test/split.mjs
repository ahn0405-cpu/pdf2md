/* PDF 자르기 회귀 테스트.
 *
 *   npm test
 *
 * 크기를 재는 도구라 픽스처를 파일로 두지 않고, 여기서 원하는 크기의 PDF를
 * 만들어 쓴다(쪽마다 압축되지 않는 데이터를 실어 크기를 조절한다).
 */
import test from 'node:test';
import assert from 'node:assert/strict';

import * as mupdf from 'mupdf';
import { splitPdf, partName, formatSize, safeChunkLimit, MB, DEFAULT_LIMIT } from '../src/splitter.js';

/** 압축되지 않는(=크기를 예측할 수 있는) 바이트열. */
function noise(n, seed) {
  const out = new Uint8Array(n);
  let s = (seed * 2654435761) >>> 0;
  for (let i = 0; i < n; i++) { s = (s * 1664525 + 1013904223) >>> 0; out[i] = s >>> 24; }
  return out;
}

/** 쪽마다 payload 바이트를 실은 PDF. 각 쪽에 "PAGE-n" 글자가 들어 있어
 *  잘린 결과가 어느 쪽인지 텍스트로 확인할 수 있다. */
function samplePdf(pages, payload) {
  const doc = new mupdf.PDFDocument();
  const font = doc.addSimpleFont(new mupdf.Font('Helvetica'));
  for (let i = 0; i < pages; i++) {
    const resources = { Font: { F1: font } };
    if (payload > 0) {
      resources.XObject = { Bulk: doc.addRawStream(noise(payload, i + 1),
        { Type: 'XObject', Subtype: 'Form', BBox: [0, 0, 1, 1] }) };
    }
    const page = doc.addPage([0, 0, 300, 300], 0, resources,
      `BT /F1 24 Tf 20 150 Td (PAGE-${i + 1}) Tj ET`);
    doc.insertPage(-1, page);
  }
  const buf = doc.saveToBuffer('');
  const bytes = buf.asUint8Array().slice();
  buf.destroy();
  doc.destroy();
  return bytes;
}

/** 조각에서 쪽 글자를 읽어 온다: ['PAGE-3', 'PAGE-4'] */
function pageLabels(bytes) {
  const doc = new mupdf.PDFDocument(bytes);
  const out = [];
  try {
    for (let i = 0; i < doc.countPages(); i++) {
      const page = doc.loadPage(i);
      const st = page.toStructuredText();
      out.push(st.asText().trim());
      st.destroy();
      page.destroy();
    }
  } finally {
    doc.destroy();
  }
  return out;
}

const LIMIT = 2 * MB;
const source = samplePdf(30, 200 * 1024);          // 30쪽 × 200KB ≈ 6MB
const result = await splitPdf(mupdf, source, { limitBytes: LIMIT, name: '보고서.pdf' });

/* ---------------- 크기 ---------------- */

test('모든 조각이 한도 이하다', () => {
  assert.ok(result.parts.length > 1, `조각이 ${result.parts.length}개뿐이다`);
  for (const p of result.parts) {
    assert.ok(p.size <= LIMIT, `${p.name} 이 ${formatSize(p.size)} 로 한도를 넘었다`);
    assert.equal(p.size, p.data.length);
  }
});

test('한도를 알뜰하게 채운다', () => {
  // 마지막 조각을 뺀 나머지는 한 쪽 더 넣으면 한도를 넘는 상태여야 한다.
  // 지나치게 작게 잘라 조각 수가 불어나는 퇴행을 잡는다.
  const perPage = source.length / 30;
  for (const p of result.parts.slice(0, -1)) {
    assert.ok(p.size + perPage > LIMIT,
      `${p.name} 이 ${formatSize(p.size)} 로 한도(${formatSize(LIMIT)})에 한참 못 미친다`);
  }
});

/* ---------------- 내용 ---------------- */

test('쪽을 빠뜨리거나 겹치지 않고 순서대로 나눈다', () => {
  let expected = 1;
  for (const p of result.parts) {
    assert.equal(p.from, expected);
    assert.equal(p.pages, p.to - p.from + 1);
    expected = p.to + 1;
  }
  assert.equal(expected - 1, 30);
  assert.equal(result.pageCount, 30);
});

test('조각 안의 쪽 내용이 원본 그대로다', () => {
  const seen = [];
  for (const p of result.parts) seen.push(...pageLabels(p.data));
  assert.deepEqual(seen, Array.from({ length: 30 }, (_, i) => `PAGE-${i + 1}`));
});

test('쪽끼리 함께 쓰는 자원을 조각마다 한 번만 옮긴다', async () => {
  // 쪽마다 graft map 을 새로 만들면 공유 자원이 쪽 수만큼 복제된다. 20MB를
  // 함께 쓰는 20쪽이 40MB 가 아니라 420MB 로 불어나고, 큰 문서에서는 WASM 힙
  // 상한(2GB)에 부딪혀 realloc 실패로 죽는다 — 실제로 그랬다.
  const doc = new mupdf.PDFDocument();
  const shared = doc.addRawStream(noise(2 * MB, 7),
    { Type: 'XObject', Subtype: 'Form', BBox: [0, 0, 1, 1] });
  for (let i = 0; i < 8; i++) {
    const own = doc.addRawStream(noise(128 * 1024, i + 1),
      { Type: 'XObject', Subtype: 'Form', BBox: [0, 0, 1, 1] });
    doc.insertPage(-1, doc.addPage([0, 0, 300, 300], 0,
      { XObject: { Shared: shared, Own: own } }, ''));
  }
  const buf = doc.saveToBuffer('');
  const bytes = buf.asUint8Array().slice();
  buf.destroy();
  doc.destroy();

  // 조각마다 공유분(2MB)은 한 번씩 들어간다. 그 위에 쪽마다 128KB 씩 얹히므로
  // 3MB 한도에는 여러 쪽이 함께 들어가야 한다. 쪽마다 복제하면 한 쪽만으로
  // 2.1MB 라 조각마다 한 쪽씩 밖에 못 담는다.
  const r = await splitPdf(mupdf, bytes, { limitBytes: 3 * MB, name: 'shared.pdf' });
  const total = r.parts.reduce((a, p) => a + p.size, 0);
  assert.ok(r.parts[0].pages >= 4,
    `첫 조각에 ${r.parts[0].pages}쪽밖에 못 담았다 (공유 자원이 쪽마다 복제된 듯하다)`);
  assert.ok(total < bytes.length * 2,
    `조각 합계가 ${formatSize(total)} 로 원본 ${formatSize(bytes.length)} 의 두 배를 넘었다`);
});

/* ---------------- 이름 ---------------- */

test('조각 이름에 번호를 0으로 채워 붙인다', () => {
  assert.equal(result.parts[0].name, '보고서-01.pdf');
  assert.equal(partName('a.pdf', 7, 120, 1, 9), 'a-007.pdf');
  assert.equal(partName('a.PDF', 2, 3, 10, 19, true), 'a-02 (10-19쪽).pdf');
});

test('쪽 범위를 이름에 넣을 수 있다', async () => {
  const r = await splitPdf(mupdf, source, { limitBytes: LIMIT, name: '보고서.pdf', nameWithRange: true });
  assert.match(r.parts[0].name, /^보고서-01 \(1-\d+쪽\)\.pdf$/);
});

/* ---------------- 예외적인 입력 ---------------- */

test('이미 한도 이하면 손대지 않는다', async () => {
  const small = samplePdf(3, 1024);
  const r = await splitPdf(mupdf, small, { limitBytes: LIMIT, name: '작은.pdf' });
  assert.equal(r.untouched, true);
  assert.equal(r.parts.length, 1);
  assert.equal(r.parts[0].name, '작은.pdf');
  assert.deepEqual(r.parts[0].data, small);    // 다시 저장하지 않는다
});

test('한 쪽이 한도보다 크면 그 쪽만 담고 알린다', async () => {
  const fat = samplePdf(3, 700 * 1024);        // 쪽마다 700KB
  const r = await splitPdf(mupdf, fat, { limitBytes: 400 * 1024, name: '큰쪽.pdf' });
  assert.equal(r.parts.length, 3);
  for (const p of r.parts) assert.equal(p.pages, 1);
  assert.equal(r.warnings.length, 3);
  assert.match(r.warnings[0], /1쪽 한 장이 .* 한도.*넘습니다/);
});

test('암호가 걸린 PDF는 이유를 밝히고 멈춘다', async () => {
  const bytes = new Uint8Array(await import('node:fs')
    .then((fs) => fs.readFileSync(new URL('./fixtures/encrypted.pdf', import.meta.url))));
  await assert.rejects(() => splitPdf(mupdf, bytes, { limitBytes: 1024 }), /암호로 보호된 PDF/);
});

test('PDF가 아니면 열 수 없다고 알린다', async () => {
  await assert.rejects(() => splitPdf(mupdf, new Uint8Array([1, 2, 3]), { limitBytes: 1024 }),
    /PDF를 열 수 없습니다/);
});

test('조각을 어떤 형태로 받을지 정할 수 있다', async () => {
  // 브라우저는 여기서 Blob 을 바로 만들어, 자바스크립트 힙에 큰 사본을 하나 덜
  // 만든다. 넘어오는 것은 WASM 메모리를 가리키는 뷰라 반드시 복사해야 한다.
  const sizes = [];
  const r = await splitPdf(mupdf, source, {
    limitBytes: LIMIT,
    takeBytes: (view) => { sizes.push(view.length); return { fake: view.length }; },
  });
  assert.deepEqual(r.parts.map((p) => p.data.fake), sizes);
  assert.deepEqual(r.parts.map((p) => p.size), sizes);
});

/* ---------------- 진행 상황 ---------------- */

test('진행 상황을 쪽 단위로 알린다', async () => {
  const seen = [];
  const parted = [];
  await splitPdf(mupdf, source, {
    limitBytes: LIMIT,
    name: 'x.pdf',
    onProgress: (p) => seen.push(p.pagesDone),
    onPart: (p) => parted.push(p.index),
  });
  assert.ok(seen.length > 0);
  assert.equal(seen[seen.length - 1], 30);
  assert.deepEqual(parted, parted.map((_, i) => i + 1));
});

/* ---------------- 메모리 ---------------- */

/** WASM 객체의 생성과 반납을 세는 mupdf 대역.
 *
 * 조각마다 새 문서와 저장 버퍼를 만든다. 하나라도 돌려주지 않으면 큰 파일에서
 * 곧바로 힙 상한(2GB)에 부딪혀 브라우저 탭이 죽는다. 힙 크기를 재는 방식은
 * 자바스크립트 쪽 버퍼에 묻혀 잘 보이지 않아, 반납 여부를 직접 센다.
 */
function countingMupdf() {
  const live = new Map();
  const watch = (obj, kind) => {
    const release = obj.destroy.bind(obj);
    live.set(obj, kind);
    obj.destroy = () => { live.delete(obj); release(); };
    return obj;
  };
  class Counted extends mupdf.PDFDocument {
    constructor(...args) { super(...args); watch(this, 'document'); }
    saveToBuffer(...args) { return watch(super.saveToBuffer(...args), 'buffer'); }
    newGraftMap(...args) { return watch(super.newGraftMap(...args), 'graftMap'); }
  }
  return {
    api: { ...mupdf, PDFDocument: Counted,
           Document: { openDocument: (...a) => watch(mupdf.Document.openDocument(...a), 'document') } },
    leaked: () => [...live.values()],
  };
}

test('자르고 나면 WASM 객체를 하나도 남기지 않는다', async () => {
  const counted = countingMupdf();
  const r = await splitPdf(counted.api, source, { limitBytes: LIMIT, name: 'x.pdf' });
  assert.ok(r.parts.length > 1);
  assert.deepEqual(counted.leaked(), []);
});

test('도중에 실패해도 열어 둔 문서를 닫는다', async () => {
  const counted = countingMupdf();
  await assert.rejects(() => splitPdf(counted.api, source, {
    limitBytes: LIMIT,
    onPart: () => { throw new Error('중단'); },
  }), /중단/);
  assert.deepEqual(counted.leaked(), []);
});

/* ---------------- 메모리 예산 ---------------- */

test('원본이 클수록 조각을 작게 잡는다', () => {
  // WASM 힙 상한(2GB)에 부딪히지 않게, 원본이 차지한 만큼을 빼고 남는 것으로
  // 조각을 잡는다. 작은 원본은 사용자가 정한 한도를 그대로 쓴다.
  assert.equal(safeChunkLimit(4 * MB, 20 * MB), 20 * MB);   // 작으면 한도 그대로
  const mid = safeChunkLimit(330 * MB, 190 * MB);
  assert.ok(mid < 150 * MB && mid > 100 * MB, `330MB 원본에 ${formatSize(mid)}`);
  assert.ok(safeChunkLimit(800 * MB, 190 * MB) < mid);      // 클수록 더 작게
  assert.ok(safeChunkLimit(2000 * MB, 190 * MB) >= 16 * MB); // 바닥은 있다
  // 원본이 아무리 커도 사용자가 정한 한도는 넘지 않는다
  assert.ok(safeChunkLimit(4 * MB, 2 * MB) <= 2 * MB);
});

test('조각을 한도보다 작게 잡았으면 그 이유를 알린다', async () => {
  // safeChunkLimit 가 줄이는 상황을 작은 예산으로 흉내낼 수는 없으니, 큰 원본
  // 대신 경고 문구의 조건만 확인한다: 줄이지 않았으면 그런 경고가 없어야 한다.
  const r = await splitPdf(mupdf, source, { limitBytes: LIMIT, name: 'x.pdf' });
  assert.equal(r.warnings.filter((w) => w.includes('메모리를 아끼려고')).length, 0);
});

test('기본 한도는 NotebookLM 의 200MB 보다 낮다', () => {
  assert.ok(DEFAULT_LIMIT < 200 * 1000 * 1000);
  assert.ok(DEFAULT_LIMIT > 150 * MB);
});
