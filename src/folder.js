/* 폴더를 직접 읽고 쓰기 (File System Access API).
 *
 * 웹 페이지가 만든 파일은 보통 브라우저의 내려받기 폴더로 간다. 원본이 있던
 * 자리에 두려면 사용자가 폴더를 한 번 골라 줘야 한다. 그 뒤로는 그 폴더의 PDF를
 * 읽고, 자른 조각을 같은 자리에 바로 쓴다.
 *
 * 크롬 계열에서만 된다. 없으면 지금까지처럼 내려받기로 떨어진다.
 */

/** 이 브라우저가 폴더 열기를 지원하는가. */
export function supportsFolders() {
  return typeof globalThis.showDirectoryPicker === 'function';
}

/** 폴더 안의 PDF를 모아 온다. 하위 폴더도 훑되, 조각은 각자 원본이 있던 폴더에
 *  쓸 수 있도록 그 폴더 손잡이를 함께 들고 온다. */
export async function collectPdfs(dir, { maxDepth = 4 } = {}) {
  const out = [];
  const walk = async (handle, depth) => {
    for await (const entry of handle.values()) {
      if (entry.kind === 'file') {
        if (/\.pdf$/i.test(entry.name)) out.push({ file: await entry.getFile(), dir: handle });
      } else if (entry.kind === 'directory' && depth < maxDepth && !entry.name.startsWith('.')) {
        await walk(entry, depth + 1);
      }
    }
  };
  await walk(dir, 0);
  out.sort((a, b) => a.file.name.localeCompare(b.file.name, 'ko'));
  return out;
}

/** 쓰기 권한이 있는지 확인하고, 없으면 한 번 물어본다. */
export async function ensureWritable(dir) {
  if (!dir.queryPermission) return true;               // 권한 질의가 없는 구현
  const opts = { mode: 'readwrite' };
  if (await dir.queryPermission(opts) === 'granted') return true;
  return await dir.requestPermission(opts) === 'granted';
}

/** 폴더에 파일 하나를 쓴다. 같은 이름이 있으면 덮어쓴다 — 다시 자를 때마다
 *  `-01 (2)` 같은 찌꺼기가 쌓이지 않게. */
export async function writeFile(dir, name, data) {
  const handle = await dir.getFileHandle(name, { create: true });
  const writable = await handle.createWritable();
  try {
    await writable.write(data);
  } catch (err) {
    await writable.abort?.();
    throw err;
  }
  await writable.close();
}
