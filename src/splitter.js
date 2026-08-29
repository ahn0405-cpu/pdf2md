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

/** 원본에서 from(0-기준)부터 count 쪽을 떼어낸 PDF를 만들어 버퍼로 돌려준다.
 *  saveToBuffer 의 결과는 문서와 별개라, 문서는 바로 돌려줘도 된다. */
function buildChunk(mupdf, src, from, count) {
  const dst = new mupdf.PDFDocument();
  try {
    for (let i = 0; i < count; i++) dst.graftPage(-1, src, from + i);
    return dst.saveToBuffer(SAVE_OPTIONS);
  } finally {
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
 * @param options.onPart     조각이 하나 완성될 때마다 호출. 여기서 bytes 를
 *                           Blob 으로 옮기고 part.bytes = null 로 비우면
 *                           메모리를 덜 쓴다.
 * @returns {{pageCount, parts, warnings, untouched}}
 */
export async function splitPdf(mupdf, bytes, options = {}) {
  const limit = Math.max(64 * 1024, Math.floor(options.limitBytes || DEFAULT_LIMIT));
  const name = options.name || 'document.pdf';
  const withRange = !!options.nameWithRange;
  const onProgress = options.onProgress || (() => {});
  const onPart = options.onPart || (() => {});
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
    if (bytes.length <= limit) {
      const part = { index: 1, from: 1, to: pageCount, pages: pageCount,
                     size: bytes.length, name, bytes };
      parts.push(part);
      onPart(part);
      onProgress({ pagesDone: pageCount, pageCount, parts: 1, message: '자를 필요가 없습니다' });
      return { pageCount, parts, warnings, untouched: true };
    }

    // 조각 수를 미리 어림해 이름의 자릿수를 정한다(01, 02 … 로 가지런히).
    const estimatedTotal = Math.max(2, Math.ceil(bytes.length / limit));
    let perPage = bytes.length / pageCount;   // 쪽당 바이트. 조각마다 다시 잰다.
    let start = 0;

    while (start < pageCount) {
      const remaining = pageCount - start;
      let lo = 0;              // 한도 안에 들어간다고 확인된 최대 쪽수
      let hi = remaining;      // 아직 넘지 않았을 수도 있는 최대 쪽수
      let guess = clamp(Math.round((limit / perPage) * 0.98), 1, remaining);
      let best = null;         // {count, size, buf}

      for (let tries = 0; tries < MAX_TRIES; tries++) {
        onProgress({
          pagesDone: start, pageCount, parts: parts.length,
          message: `${parts.length + 1}번째 조각을 재는 중 — ${start + 1}~${start + guess}쪽`,
        });
        await tick();

        const buf = buildChunk(mupdf, doc, start, guess);
        const size = buf.getLength();
        if (size <= limit) {
          best?.buf.destroy();
          best = { count: guess, size, buf };
          lo = guess;
        } else {
          buf.destroy();
          hi = guess - 1;
        }
        if (lo >= hi) break;   // 남은 후보가 없다 — lo 가 최적

        // 방금 잰 밀도로 다음 쪽수를 점찍고, 아직 안 본 구간으로 잘라 넣는다.
        // 구간이 매번 좁아지므로 제자리걸음은 생기지 않는다.
        guess = clamp(Math.round((guess * limit) / size * 0.99), lo + 1, hi);
      }

      // 한 쪽조차 한도를 넘는 경우(큰 스캔 이미지 한 장 등). 더 쪼갤 수단이
      // 없으니 그 쪽만 담은 조각을 그대로 낸다.
      if (!best) {
        const buf = buildChunk(mupdf, doc, start, 1);
        best = { count: 1, size: buf.getLength(), buf };
        if (best.size > limit) {
          warnings.push(`${start + 1}쪽 한 장이 ${formatSize(best.size)} 라 한도`
            + `(${formatSize(limit)})를 넘습니다. 이 조각은 그대로 두었습니다.`);
        }
      }

      const index = parts.length + 1;
      const from = start + 1;
      const to = start + best.count;
      const part = {
        index, from, to, pages: best.count, size: best.size,
        name: partName(name, index, Math.max(estimatedTotal, index), from, to, withRange),
        bytes: best.buf.asUint8Array().slice(),
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
