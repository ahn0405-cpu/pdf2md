/* 단일 HTML 빌드.
 *
 *   node build.mjs           ->  dist/pdf2md.html
 *
 * 결과물은 파일 하나로, 크롬에서 그냥 열면 된다. 서버도 인터넷도 필요 없다.
 * MuPDF의 WASM은 gzip 후 base64로 페이지 안에 넣고, 실행 시점에 브라우저가 푼다.
 *
 * 왜 인라인 모듈 하나로 합치나:
 *  - file:// 로 연 페이지는 다른 파일을 import 할 수 없다(CORS). 인라인 모듈은 가능하다.
 *  - 인라인 모듈은 최상위 await 를 쓸 수 있어, WASM 압축을 푼 뒤에 MuPDF 초기화가
 *    이어지도록 순서를 보장할 수 있다.
 */
import fs from 'node:fs';
import path from 'node:path';
import zlib from 'node:zlib';
import { fileURLToPath } from 'node:url';

const ROOT = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.join(ROOT, 'src');
const DIST = path.join(ROOT, 'dist');
const MUPDF = path.join(ROOT, 'node_modules', 'mupdf', 'dist');

const read = (p) => fs.readFileSync(p, 'utf8');

/** 우리 모듈을 즉시실행 함수로 감싼다.
 *
 * 그냥 이어 붙이면 모듈마다 있는 같은 이름의 내부 함수가 부딪힌다
 * (예: markdown.js 의 renderList 와 app.js 의 renderList).
 * 모듈 경계를 유지해야 원본 파일을 고칠 때 이름을 신경 쓰지 않아도 된다.
 */
function moduleToIife(name, source) {
  const exports = new Map();   // 바깥 이름 -> 안쪽 이름

  // export { a as b, c }
  source.replace(/^\s*export\s*\{([^}]*)\}\s*;?\s*$/gm, (_, body) => {
    for (const part of body.split(',')) {
      const [local, , exported] = part.trim().split(/\s+/);
      if (local) exports.set(exported || local, local);
    }
    return '';
  });
  // export function foo / export const foo / export class Foo
  for (const m of source.matchAll(/^\s*export\s+(?:async\s+)?(?:function|class|const|let|var)\s+([A-Za-z_$][\w$]*)/gm)) {
    exports.set(m[1], m[1]);
  }

  const body = source
    .replace(/^\s*import\s[^;]*?;\s*$/gm, (line) => {
      // import { a, b } from './x.js';  ->  const { a, b } = __ns_x;
      const named = /import\s*\{([^}]*)\}\s*from\s*['"]\.\/([\w.-]+)\.js['"]/.exec(line);
      if (named) return `const {${named[1]}} = __ns_${named[2].replace(/\W/g, '_')};`;
      return '';
    })
    .replace(/^\s*export\s*\{[^}]*\}\s*;?\s*$/gm, '')
    .replace(/^(\s*)export\s+(?=(async\s+)?(function|class|const|let|var)\b)/gm, '$1');

  const returned = [...exports].map(([out, local]) => (out === local ? out : `${out}: ${local}`)).join(', ');
  const id = name.replace(/\W/g, '_');
  return `const __ns_${id} = (() => {\n${body}\nreturn { ${returned} };\n})();\n`;
}

function buildMupdfBundle() {
  // mupdf-wasm.js: 기본 내보내기를 지역 변수로 바꾼다
  let wasmGlue = read(path.join(MUPDF, 'mupdf-wasm.js'));
  if (!wasmGlue.includes('export default _;')) {
    throw new Error('mupdf-wasm.js 형태가 예상과 다릅니다. 빌드 스크립트를 확인하세요.');
  }
  wasmGlue = wasmGlue.replace('export default _;', 'const __libmupdf_wasm_factory = _;');

  // mupdf.js: 내부 import 를 위 변수로 연결하고, 네임스페이스를 지역 변수로 받는다
  let core = read(path.join(MUPDF, 'mupdf.js'));
  const importLine = 'import libmupdf_wasm from "./mupdf-wasm.js";';
  if (!core.includes(importLine) || !core.includes('export default {')) {
    throw new Error('mupdf.js 형태가 예상과 다릅니다. 빌드 스크립트를 확인하세요.');
  }
  core = core
    .replace(importLine, 'const libmupdf_wasm = __libmupdf_wasm_factory;')
    .replace('export default {', 'const __mupdfNamespace = {')
    .replace(/^(\s*)export\s+(?=(async\s+)?(function|class|const|let|var)\b)/gm, '$1');

  return `${wasmGlue}\n${core}\n`;
}

/** 한 페이지를 단일 HTML 로 묶는다.
 *
 * @param shared   WASM 준비 코드 + MuPDF 본체 (두 페이지가 같은 것을 쓴다)
 * @param page     src/ 안의 HTML 이름
 * @param modules  의존 순서대로 이어 붙일 src/*.js (마지막이 진입점)
 * @param outName  dist/ 에 쓸 이름
 */
function buildPage(shared, page, modules, outName) {
  const app = modules
    .map((name) => moduleToIife(name, read(path.join(SRC, `${name}.js`))))
    .join('\n');
  // 모듈 하나를 목록에서 빠뜨리면 참조가 조용히 undefined 가 된다(화면이 그냥
  // 안 뜬다). 빌드 때 잡는다. mupdf_runtime 은 위 공통 코드가 넣어 준다.
  const defined = new Set([...modules.map((n) => n.replace(/\W/g, '_')), 'mupdf_runtime']);
  for (const [, id] of app.matchAll(/__ns_([A-Za-z0-9_]+)/g)) {
    if (!defined.has(id)) {
      throw new Error(`${page}: '${id}' 모듈이 빌드 목록에 없습니다.`);
    }
  }

  const script = [shared, app].join('\n');

  let html = read(path.join(SRC, page));
  html = html
    .replace(/<link rel="stylesheet" href="([\w-]+\.css)">/g,
             (_, css) => `<style>\n${read(path.join(SRC, css))}\n</style>`)
    .replace(/\s*<script type="module" src="[\w-]+\.js"><\/script>/,
             `\n<script type="module">\n${script}\n</script>`);

  if (html.includes('<link rel="stylesheet"') || html.includes('<script type="module" src=')) {
    throw new Error(`${page} 의 자리표시자를 찾지 못했습니다.`);
  }

  fs.mkdirSync(DIST, { recursive: true });
  const out = path.join(DIST, outName);
  fs.writeFileSync(out, html);
  console.log(`${path.relative(ROOT, out)}  ${(Buffer.byteLength(html) / 1048576).toFixed(1)} MB`);
}

function main() {
  const wasm = fs.readFileSync(path.join(MUPDF, 'mupdf-wasm.wasm'));
  const gz = zlib.gzipSync(wasm, { level: 9 });
  const wasmB64 = gz.toString('base64');

  const preamble = `
/* MuPDF(WASM) — 페이지 안에 들어 있다. 여기서 압축을 풀어 넘긴다. */
const __WASM_GZ_B64 = "${wasmB64}";

function __b64ToBytes(b64) {
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

async function __gunzip(bytes) {
  if (typeof DecompressionStream === 'undefined') {
    throw new Error('이 브라우저는 DecompressionStream 을 지원하지 않습니다. 크롬을 써 주세요.');
  }
  const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'));
  return new Uint8Array(await new Response(stream).arrayBuffer());
}

globalThis.$libmupdf_wasm_Module = { wasmBinary: await __gunzip(__b64ToBytes(__WASM_GZ_B64)) };
`;

  const runtime = `
/* 빌드본에서는 WASM이 이미 초기화돼 있으므로 그대로 돌려준다. */
const __ns_mupdf_runtime = { loadMupdf: async () => __mupdfNamespace };
`;

  const shared = [preamble, buildMupdfBundle(), runtime].join('\n');

  // 의존 순서대로 (마지막 모듈이 나머지를 가져다 쓴다)
  buildPage(shared, 'index.html', ['markdown', 'zip', 'converter', 'app'], 'pdf2md.html');
  buildPage(shared, 'split.html', ['folder', 'splitter', 'split-app'], 'pdfsplit.html');

  console.log(`WASM ${(wasm.length / 1048576).toFixed(1)} MB → gzip ${(gz.length / 1048576).toFixed(1)} MB`);
}

main();
