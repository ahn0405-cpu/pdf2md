/* 큰 PDF를 정해진 크기 이하의 여러 PDF로 자른다.
 *
 * NotebookLM 을 비롯한 서비스들은 소스 한 개의 크기를 제한한다(200MB).
 * 한도를 넘는 PDF를 쪽 단위로 갈라, 조각마다 한도 안에 들어오게 만든다.
 *
 * 까다로운 점은 "몇 쪽까지 넣으면 한도에 딱 맞는가"를 미리 알 수 없다는 것이다.
 * 쪽들이 글꼴·이미지를 함께 쓰고 압축률도 제각각이라 쪽수와 파일 크기가 비례하지
 * 않는다. 그래서 실제로 저장해 크기를 재고, 잰 밀도(바이트/쪽)로 다음 쪽수를
 * 예측하며 구간을 좁힌다. 보통 조각당 2~4번이면 정해진다.
 */

export const MB = 1048576;

/** NotebookLM 한도는 200MB. MB 의 정의(1,000,000 / 1,048,576)가 서비스마다
 *  다르므로 조금 낮춰 잡는다. 190MB = 199.2MB(십진) 라 어느 쪽으로 재도 통과한다. */
export const DEFAULT_LIMIT = 190 * MB;

/** 저장 옵션. compress 는 필터가 없는 스트림만 압축한다. 이미 압축된 이미지를
 *  다시 건드리지 않으므로 화질 손실이 없고, 텍스트 위주 문서에서는 꽤 줄어든다. */
const SAVE_OPTIONS = 'compress';

/** 조각 하나를 정하는 데 쓸 시도 횟수 상한. 예측이 빗나가도 이 안에서 수렴한다. */
const MAX_TRIES = 14;

/** 한도의 이만큼을 채웠으면 그만 잰다. 마지막 몇 쪽을 더 밀어 넣으려고 큰 조각을
 *  또 만들면, 얻는 것보다 메모리 고점이 더 올라간다. */
const GOOD_ENOUGH = 0.9;

/* WASM 힙은 2GB가 상한이다. 재 보면 고점이 대략
 *
 *     원본 크기 + 조각 크기 × 6
 *
 * 까지 오른다. 조각을 담을 문서, 저장 버퍼, 그 버퍼가 1.5배씩 자라며 남기는 빈자리,
 * 시도를 되풀이하며 생기는 조각남까지 더해진 값이다. 330MB 문서를 190MB로 자르면
 * 고점이 1.4GB — 상한에 너무 가깝다. 실제 문서는 객체가 훨씬 많아 더 헤프므로
 * 예산을 1.1GB로 잡고, 남는 만큼만 조각에 쓴다. 조각이 더 잘게 나뉠 뿐,
 * 탭이 죽는 것보다는 낫다. */
const HEAP_BUDGET = 1150 * MB;
const CHUNK_COST = 6;
const MIN_CHUNK = 16 * MB;

/** 원본 크기를 보고 실제로 만들 조각의 최대 크기를 정한다. 사용자가 정한 한도를
 *  넘지는 않는다. */
export function safeChunkLimit(sourceSize, limit) {
  const affordable = Math.floor((HEAP_BUDGET - sourceSize) / CHUNK_COST);
  return Math.min(limit, Math.max(MIN_CHUNK, affordable));
}

const clamp = (v, lo, hi) => Math.min(Math.max(v, lo), hi);
const tick = () => new Promise((resolve) => setTimeout(resolve, 0));

export function formatSize(n) {
  if (n < 1024) return `${n} B`;
  if (n < MB) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / MB).toFixed(1)} MB`;
}

/** 조각 파일 이름: `보고서-01.pdf` 또는 `보고서-01 (1-120쪽).pdf`.
 *  번호를 0으로 채워 파일 목록에서 순서대로 늘어서게 한다. */
export function partName(originalName, index, total, from, to, withRange = false) {
  const base = String(originalName).replace(/\.pdf$/i, '') || 'document';
  const num = String(index).padStart(Math.max(2, String(total).length), '0');
  return withRange ? `${base}-${num} (${from}-${to}쪽).pdf` : `${base}-${num}.pdf`;
}

/** 메모리가 모자라 실패했는가. MuPDF 는 WASM 힙이 차면 realloc/malloc 실패로
 *  알려 온다. 문서가 잘못된 것이 아니므로 더 작게 잘라 다시 시도할 수 있다. */
export function isOutOfMemory(err) {
  return /realloc|malloc|out of memory|allocat/i.test(String(err?.message || err));
}

/** 원본에서 from(0-기준)부터 count 쪽을 떼어낸 PDF를 만들어 버퍼로 돌려준다.
 *
 * 반드시 graft map 을 하나 만들어 그 위에서 옮긴다. 쪽마다 graftPage 를 따로
 * 부르면 MuPDF 가 매번 새 map 을 만들어, 쪽들이 함께 쓰는 글꼴·이미지를 쪽 수만큼
 * 복제한다(20MB를 함께 쓰는 20쪽 → 40MB 가 아니라 420MB). 큰 문서에서는 곧바로
 * WASM 힙 상한(2GB)에 부딪힌다.
 *
 * saveToBuffer 의 결과는 문서와 별개라, 문서는 바로 돌려줘도 된다.
 */
function buildChunk(mupdf, src, from, count) {
  const dst = new mupdf.PDFDocument();
  const map = dst.newGraftMap();
  try {
    for (let i = 0; i < count; i++) map.graftPage(-1, src, from + i);
    return dst.saveToBuffer(SAVE_OPTIONS);
  } finally {
    map.destroy();
    dst.destroy();
  }
}

/** 큰 PDF를 한도 이하의 조각들로 자른다.
 *
 * @param mupdf              MuPDF 네임스페이스
 * @param bytes              원본 PDF (Uint8Array)
 * @param options.limitBytes 조각 하나의 최대 바이트 (기본 190MB)
 * @param options.name       원본 파일명 — 조각 이름을 짓는 데 쓴다
 * @param options.nameWithRange 이름에 쪽 범위를 넣을지
 * @param options.onProgress 진행 알림 {pagesDone, pageCount, parts, message}
 * @param options.onPart     조각이 하나 완성될 때마다 호출
 * @param options.takeBytes  완성된 조각을 무엇으로 받을지. WASM 메모리를 그대로
 *                           가리키는 뷰가 넘어오니 반드시 복사해 가야 한다.
 *                           기본은 Uint8Array 사본, 브라우저에서는 Blob 을 바로
 *                           만들어 자바스크립트 힙에 사본을 하나 덜 만든다.
 * @returns {{pageCount, parts, warnings, untouched}}
 */
export async function splitPdf(mupdf, bytes, options = {}) {
  const limit = Math.max(64 * 1024, Math.floor(options.limitBytes || DEFAULT_LIMIT));
  const name = options.name || 'document.pdf';
  const withRange = !!options.nameWithRange;
  const onProgress = options.onProgress || (() => {});
  const onPart = options.onPart || (() => {});
  const takeBytes = options.takeBytes || ((view) => view.slice());
  const sourceSize = bytes.length;
  const warnings = [];
  const parts = [];

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

  try {
    const pageCount = doc.countPages();
    if (!pageCount) throw new Error('페이지가 없는 PDF입니다.');

    // 이미 한도 이하면 손대지 않는다. 다시 저장하면 서명·양식이 상할 수 있고,
    // 무엇보다 자를 이유가 없다.
    if (sourceSize <= limit) {
      const part = { index: 1, from: 1, to: pageCount, pages: pageCount,
                     size: sourceSize, name, data: takeBytes(bytes) };
      parts.push(part);
      onPart(part);
      onProgress({ pagesDone: pageCount, pageCount, parts: 1, message: '자를 필요가 없습니다' });
      return { pageCount, parts, warnings, untouched: true };
    }

    // 원본은 이제 PDF 엔진이 들고 있다. 자바스크립트 쪽 사본까지 붙잡고 있으면
    // 330MB짜리를 두 벌 이고 가는 셈이라, 참조를 놓아 준다.
    bytes = null;

    // 메모리 예산에 맞춰 실제로 만들 조각 크기를 정한다.
    const target = safeChunkLimit(sourceSize, limit);
    if (target < limit * 0.95) {
      warnings.push(`메모리를 아끼려고 조각을 ${formatSize(target)} 이하로`
        + ` 잘랐습니다(요청한 한도는 ${formatSize(limit)}).`
        + ' 원본이 클수록 조각을 작게 만들어야 브라우저가 버팁니다.');
    }

    // 조각 수를 미리 어림해 이름의 자릿수를 정한다(01, 02 … 로 가지런히).
    const estimatedTotal = Math.max(2, Math.ceil(sourceSize / target));
    let perPage = sourceSize / pageCount;   // 쪽당 바이트. 조각마다 다시 잰다.
    let start = 0;
    let tightOnMemory = false;

    while (start < pageCount) {
      const remaining = pageCount - start;
      let lo = 0;              // 한도 안에 들어간다고 확인된 최대 쪽수
      let hi = remaining;      // 아직 넘지 않았을 수도 있는 최대 쪽수
      let guess = clamp(Math.round((target / perPage) * 0.98), 1, remaining);
      let best = null;         // {count, size, buf}

      for (let tries = 0; tries < MAX_TRIES; tries++) {
        onProgress({
          pagesDone: start, pageCount, parts: parts.length,
          message: `${parts.length + 1}번째 조각을 재는 중 — ${start + 1}~${start + guess}쪽`,
        });
        await tick();

        let buf;
        try {
          buf = buildChunk(mupdf, doc, start, guess);
        } catch (err) {
          // 메모리가 모자란 것뿐이면 절반으로 줄여 다시 해 본다. 조각이 더
          // 잘게 나뉠 뿐 결과는 쓸 수 있다.
          if (!isOutOfMemory(err) || guess <= 1) throw err;
          hi = Math.min(hi, guess - 1);
          if (!tightOnMemory) {
            tightOnMemory = true;
            warnings.push('메모리가 모자라 조각을 한도보다 작게 잘랐습니다.'
              + ' 다른 탭을 닫고 다시 하면 조각 수가 줄어듭니다.');
          }
          if (lo >= hi) break;
          guess = clamp(Math.floor(guess / 2), lo + 1, hi);
          continue;
        }

        const size = buf.getLength();
        if (size <= target) {
          best?.buf.destroy();
          best = { count: guess, size, buf };
          lo = guess;
          // 충분히 채웠으면 그만 잰다. 큰 조각을 한 번 더 만드는 값이 비싸다.
          if (size >= target * GOOD_ENOUGH) break;
        } else {
          buf.destroy();
          hi = guess - 1;
        }
        if (lo >= hi) break;   // 남은 후보가 없다 — lo 가 최적

        // 방금 잰 밀도로 다음 쪽수를 점찍고, 아직 안 본 구간으로 잘라 넣는다.
        // 구간이 매번 좁아지므로 제자리걸음은 생기지 않는다.
        guess = clamp(Math.round((guess * target) / size * 0.99), lo + 1, hi);
      }

      // 한 쪽조차 한도를 넘는 경우(큰 스캔 이미지 한 장 등). 더 쪼갤 수단이
      // 없으니 그 쪽만 담은 조각을 그대로 낸다.
      if (!best) {
        const buf = buildChunk(mupdf, doc, start, 1);
        best = { count: 1, size: buf.getLength(), buf };
        if (best.size > target) {
          warnings.push(`${start + 1}쪽 한 장이 ${formatSize(best.size)} 라 한도`
            + `(${formatSize(target)})를 넘습니다. 이 조각은 그대로 두었습니다.`);
        }
      }

      const index = parts.length + 1;
      const from = start + 1;
      const to = start + best.count;
      const part = {
        index, from, to, pages: best.count, size: best.size,
        name: partName(name, index, Math.max(estimatedTotal, index), from, to, withRange),
        data: takeBytes(best.buf.asUint8Array()),
      };
      best.buf.destroy();
      parts.push(part);
      onPart(part);

      perPage = best.size / best.count;   // 다음 조각의 첫 짐작에 쓴다
      start = to;
      onProgress({ pagesDone: start, pageCount, parts: parts.length, message: '' });
      await tick();
    }

    // 조각 수가 처음 어림보다 늘었으면 번호 자릿수가 어긋난다. 다 만든 뒤
    // 진짜 개수로 이름을 다시 짓는다.
    for (const p of parts) p.name = partName(name, p.index, parts.length, p.from, p.to, withRange);

    return { pageCount, parts, warnings, untouched: false };
  } finally {
    doc.destroy?.();
  }
}
