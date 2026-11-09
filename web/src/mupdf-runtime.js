/* MuPDF(WASM) 로더 — 개발용.
 *
 * 이 파일은 `npm run build` 로 단일 HTML을 만들 때 통째로 대체된다.
 * 배포본에서는 WASM이 페이지 안에 들어 있어 네트워크 요청이 전혀 없다.
 */
let cached = null;

export async function loadMupdf() {
  if (!cached) cached = await import('mupdf');
  return cached;
}
