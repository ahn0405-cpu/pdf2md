/* 회귀 테스트.
 *
 *   npm test
 *
 * test/fixtures/*.pdf 를 변환해 결과를 확인한다.
 * 픽스처를 다시 만들려면 test/make-fixtures.py 를 참고.
 */
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';

import * as mupdf from 'mupdf';
import { convert, escapeLeading, stripOuterEmphasis, stripMarkerSpans,
         tableToMarkdown, tableToHtml } from '../src/converter.js';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const FIXTURES = path.join(HERE, 'fixtures');

// 브라우저 전용 API 를 노드에서 대신한다
globalThis.btoa ??= (s) => Buffer.from(s, 'binary').toString('base64');

const load = (name) => new Uint8Array(fs.readFileSync(path.join(FIXTURES, `${name}.pdf`)));
const run = (name, options) => convert(mupdf, load(name), `${name}.pdf`, options);

const basic = run('basic');

/* ---------------- 서식 보존 ---------------- */

test('제목을 글자 크기로 계층화한다', () => {
  assert.match(basic.markdown, /^# 보고서 제목$/m);
  assert.match(basic.markdown, /^## 1\. 개요$/m);
});

test('한 문단의 여러 줄을 이어 붙인다', () => {
  assert.match(basic.markdown, /첫 줄이 여기서 끊기고 다음 줄로 이어진다\./);
});

test('줄바꿈으로 끊긴 단어를 하이픈에서 합친다', () => {
  assert.match(basic.markdown, /deliberately here\./);
});

test('목록과 중첩 단계를 인식한다', () => {
  assert.match(basic.markdown, /^- 첫째 항목$/m);
  assert.match(basic.markdown, /^ {2}- 둘째 항목$/m);
  assert.match(basic.markdown, /^1\. 번호 항목$/m);
});

test('괘선에서 표 격자를 복원한다', () => {
  assert.match(basic.markdown, /\| 항목 \| 값 \|/);
  assert.match(basic.markdown, /\| 매출 \| 100 \|/);
});

test('굵게·기울임·고정폭을 표시한다', () => {
  assert.match(basic.markdown, /\*\*bold\*\*/);
  assert.match(basic.markdown, /\*slanted\*/);
  assert.match(basic.markdown, /```/);
});

test('링크와 이미지를 남긴다', () => {
  assert.match(basic.markdown, /\(https:\/\/example\.com\/\)/);
  assert.match(basic.markdown, /!\[/);
  assert.equal(basic.assets.length, 1);
});

test('반복 머리말과 쪽번호를 지운다', () => {
  assert.doesNotMatch(basic.markdown, /반복 머리말/);
  assert.doesNotMatch(basic.markdown, /- 1 -/);
});

/* ---------------- 레이아웃 ---------------- */

test('머리말과 같은 문구라도 본문에 있으면 남긴다', () => {
  const md = run('header-in-body').markdown;
  assert.equal((md.match(/제3장 위험 관리/g) || []).length, 1);
  assert.doesNotMatch(md, /- 1 -/);
});

test('같은 줄에 내용이 이어지는 본문 말머리는 지우지 않는다', () => {
  const md = run('repeated-label').markdown;
  assert.equal((md.match(/추천 대상:/g) || []).length, 4);
  assert.doesNotMatch(md, /- 1 -/);
});

test('코드 블록의 들여쓰기를 살린다', () => {
  const md = run('indented-code').markdown;
  const body = md.split('```')[1].replace(/^\n|\n$/g, '');
  const indents = body.split('\n').map((l) => l.length - l.trimStart().length);
  assert.equal(indents[0], 0);
  assert.ok(indents[1] > indents[0], '둘째 줄이 더 깊어야 한다');
  assert.ok(indents[2] > indents[1], '셋째 줄이 더 깊어야 한다');
  assert.equal(indents[3], 0);
});

test('페이지마다 반복되는 이미지는 파일 하나로 모은다', () => {
  const result = run('repeated-image');
  assert.equal((result.markdown.match(/!\[/g) || []).length, 5);
  assert.equal(result.assets.length, 1);
});

test('2단 조판을 왼쪽 단 → 오른쪽 단 순서로 읽는다', () => {
  const md = run('two-columns').markdown;
  assert.ok(md.indexOf('왼쪽 단의 마지막') < md.indexOf('오른쪽 단의 첫'),
    '왼쪽 단이 모두 나온 뒤 오른쪽 단이 와야 한다');
  assert.match(md, /^# 전폭 제목$/m);
});

/* ---------------- 옵션 ---------------- */

test('옵션을 끄면 해당 서식을 만들지 않는다', () => {
  const plain = run('basic', {
    detectHeadings: false, detectLists: false, inlineStyles: false,
    images: 'skip', tables: 'skip',
  }).markdown;
  assert.doesNotMatch(plain, /^# 보고서 제목$/m);
  assert.doesNotMatch(plain, /\*\*bold\*\*/);
  assert.doesNotMatch(plain, /!\[/);
});

test('이미지를 base64 로 넣으면 별도 파일이 생기지 않는다', () => {
  const result = run('basic', { images: 'base64' });
  assert.match(result.markdown, /data:image\/png;base64,/);
  assert.equal(result.assets.length, 0);
});

test('페이지 구분선 옵션이 반영된다', () => {
  const md = run('basic', { pageSeparator: true }).markdown;
  assert.equal((md.split('\n').filter((l) => l.trim() === '---')).length, 2);
});

/* ---------------- 오류·경고 ---------------- */

test('암호가 걸린 PDF는 그 사실을 알린다', () => {
  assert.throws(() => run('encrypted'), /암호/);
});

test('망가진 PDF는 열 수 없다고 알린다', () => {
  assert.throws(() => run('broken'), /열 수 없습니다/);
});

test('스캔본은 OCR이 필요하다고 경고한다', () => {
  const result = run('scanned');
  assert.match(result.warnings.join(' '), /스캔 이미지 PDF/);
});

/* ---------------- Markdown 이스케이프 ---------------- */

test('번호 문단은 구두점 앞에 역슬래시를 넣는다', () => {
  // `\1.` 은 Markdown 이스케이프가 아니라 역슬래시가 그대로 보인다
  assert.equal(escapeLeading('1. 본문'), '1\\. 본문');
  assert.equal(escapeLeading('2) 본문'), '2\\) 본문');
  assert.equal(escapeLeading('# 본문'), '\\# 본문');
  assert.equal(escapeLeading('보통 문장'), '보통 문장');
});

test('강조가 여러 개인 제목은 표시를 벗기지 않는다', () => {
  assert.equal(stripOuterEmphasis('**제목**'), '제목');
  assert.equal(stripOuterEmphasis('***제목***'), '제목');
  assert.equal(stripOuterEmphasis('**A** **B**'), '**A** **B**');
});

test('표 셀은 원시 HTML·표 문법으로 읽히지 않게 막는다', () => {
  const html = tableToHtml([['<img src=x onerror=y>', 'a&b'], ['c', 'd']]);
  assert.doesNotMatch(html, /<img/);
  assert.match(html, /&lt;img/);
  const md = tableToMarkdown([['a|b', 'c*d*e'], ['x', 'y']]);
  assert.match(md, /a\\\|b/);
  assert.match(md, /c\\\*d\\\*e/);
});

test('목록 마커는 공백이 어긋나도 정확히 잘라낸다', () => {
  const span = (text) => ({ text, size: 10, bold: false, italic: false, mono: false, bbox: [0, 0, 0, 0] });
  const join = (spans) => spans.map((s) => s.text).join('');
  assert.equal(join(stripMarkerSpans([span('  •   항목 이름')], '•')), '   항목 이름');
  assert.equal(join(stripMarkerSpans([span('1'), span(')'), span(' 항목')], '1)')), ' 항목');
  assert.equal(join(stripMarkerSpans([span('① 원문자')], '')), '① 원문자');
});

/* ---------------- 결정성 ---------------- */

test('같은 입력은 항상 같은 결과를 낸다', () => {
  const a = run('basic').markdown;
  const b = run('basic').markdown;
  assert.equal(a, b);
});

/* ---------------- 메모리 ---------------- */

test('파일을 반복 변환해도 WASM 메모리가 늘지 않는다', () => {
  // mupdf 는 글자마다 Font 를, 그려진 경로마다 Path/ColorSpace 를 새로 만들어 넘긴다.
  // 소유권이 있는 참조라 받은 쪽이 해제해야 하고, 빠뜨리면 파일을 여러 개 변환할수록
  // WASM 힙이 끝없이 는다(브라우저 탭이 죽는다). 여기서 새는지 확인한다.
  const bytes = load('stress');
  const heap = () => process.memoryUsage().external / 1048576;

  for (let i = 0; i < 3; i++) convert(mupdf, bytes, 'stress.pdf');   // 힙을 미리 키운다
  const before = heap();
  for (let i = 0; i < 30; i++) convert(mupdf, bytes, 'stress.pdf');
  const grown = heap() - before;

  // 해제를 빠뜨리면 30회에 12MB 안팎 늘고, 제대로 돌려주면 0에 가깝다
  assert.ok(grown < 4, `WASM 힙이 30회 변환에 ${grown.toFixed(1)}MB 늘었다 (누수 의심)`);
});
