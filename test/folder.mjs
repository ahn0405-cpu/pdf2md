/* 폴더 읽고 쓰기 회귀 테스트.
 *
 * File System Access API 는 브라우저에만 있으므로, 명세대로 움직이는 가짜
 * 손잡이를 만들어 확인한다.
 */
import test from 'node:test';
import assert from 'node:assert/strict';

import { collectPdfs, ensureWritable, writeFile, supportsFolders } from '../src/folder.js';

/** 가짜 디렉터리 손잡이. entries 는 {이름: 문자열(파일 내용) | 하위 디렉터리}. */
function fakeDir(name, entries, permission = 'granted') {
  const dir = {
    kind: 'directory',
    name,
    written: new Map(),
    permission,
    asked: 0,
    async *values() {
      for (const [key, value] of Object.entries(entries)) {
        if (typeof value === 'string') {
          yield { kind: 'file', name: key, getFile: async () => ({ name: key, size: value.length }) };
        } else {
          yield value;
        }
      }
    },
    async queryPermission() { return dir.permission; },
    async requestPermission() { dir.asked++; dir.permission = 'granted'; return 'granted'; },
    async getFileHandle(fileName, opts) {
      if (!opts?.create && !dir.written.has(fileName)) {
        const err = new Error('없음'); err.name = 'NotFoundError'; throw err;
      }
      return {
        async createWritable() {
          const chunks = [];
          return {
            async write(data) { chunks.push(data); },
            async close() { dir.written.set(fileName, chunks); },
            async abort() { },
          };
        },
      };
    },
  };
  return dir;
}

test('폴더 안의 PDF만 골라 온다', async () => {
  const dir = fakeDir('사례집', {
    'a.pdf': 'AAA', 'memo.txt': 'x', 'B.PDF': 'BB', '.숨김.pdf': 'z',
  });
  const found = await collectPdfs(dir);
  assert.deepEqual(found.map((f) => f.file.name), ['.숨김.pdf', 'a.pdf', 'B.PDF']);
  for (const f of found) assert.equal(f.dir, dir);
});

test('하위 폴더도 훑고, 파일마다 제 폴더를 들고 온다', async () => {
  const sub = fakeDir('하위', { 'c.pdf': 'C' });
  const dir = fakeDir('위', { 'a.pdf': 'A', 하위: sub });
  const found = await collectPdfs(dir);
  assert.deepEqual(found.map((f) => f.file.name), ['a.pdf', 'c.pdf']);
  // 조각은 원본이 있던 그 폴더에 써야 한다
  assert.equal(found.find((f) => f.file.name === 'a.pdf').dir, dir);
  assert.equal(found.find((f) => f.file.name === 'c.pdf').dir, sub);
});

test('너무 깊은 폴더는 더 들어가지 않는다', async () => {
  let deepest = fakeDir('바닥', { 'deep.pdf': 'D' });
  for (let i = 0; i < 6; i++) deepest = fakeDir(`d${i}`, { child: deepest });
  const found = await collectPdfs(deepest, { maxDepth: 2 });
  assert.deepEqual(found, []);
});

test('숨김 폴더는 건너뛴다', async () => {
  const hidden = fakeDir('.git', { 'x.pdf': 'X' });
  const dir = fakeDir('위', { '.git': hidden });
  assert.deepEqual(await collectPdfs(dir), []);
});

test('쓰기 권한이 없으면 한 번 물어본다', async () => {
  const granted = fakeDir('a', {});
  assert.equal(await ensureWritable(granted), true);
  assert.equal(granted.asked, 0);

  const prompt = fakeDir('b', {}, 'prompt');
  assert.equal(await ensureWritable(prompt), true);
  assert.equal(prompt.asked, 1);
});

test('폴더에 파일을 쓴다', async () => {
  const dir = fakeDir('사례집', {});
  await writeFile(dir, '사례집-01.pdf', 'DATA');
  assert.deepEqual([...dir.written.keys()], ['사례집-01.pdf']);
  assert.deepEqual(dir.written.get('사례집-01.pdf'), ['DATA']);
});

test('쓰다가 실패하면 반쯤 쓴 파일을 남기지 않는다', async () => {
  const dir = fakeDir('사례집', {});
  let aborted = false;
  dir.getFileHandle = async () => ({
    async createWritable() {
      return {
        async write() { throw new Error('디스크가 가득 찼습니다'); },
        async close() { throw new Error('닫으면 안 된다'); },
        async abort() { aborted = true; },
      };
    },
  });
  await assert.rejects(() => writeFile(dir, 'x.pdf', 'DATA'), /디스크가 가득/);
  assert.equal(aborted, true);
});

test('폴더 기능이 없는 브라우저를 알아본다', () => {
  assert.equal(supportsFolders(), false);          // 노드에는 없다
  globalThis.showDirectoryPicker = () => {};
  assert.equal(supportsFolders(), true);
  delete globalThis.showDirectoryPicker;
});
