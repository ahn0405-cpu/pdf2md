#!/usr/bin/env python3
"""단권화 노트 기계 검사. 사람이 읽어야 아는 것은 SKILL.md 「발행 직전 확인」 참조."""
import re, sys, glob, os

BOLD = re.compile(r'\*\*(.+?)\*\*')

def bold_too_long(path, limit=10):
    hits = []
    for i, line in enumerate(open(path, encoding='utf-8'), 1):
        if line.lstrip().startswith('|'):      # 표 안은 제외
            continue
        for m in BOLD.finditer(line):
            t = m.group(1)
            t = re.sub(r'[`\[\]()·,/…\s]', '', t)   # 기호·공백 제외하고 센다
            if len(t) > limit:
                hits.append((i, len(t), m.group(1)))
    return hits

def heading_depth(path):
    bad = []
    for i, line in enumerate(open(path, encoding='utf-8'), 1):
        m = re.match(r'^(#{7,})\s', line)
        if m: bad.append((i, len(m.group(1))))
    return bad

def footnote_pairs(path):
    s = open(path, encoding='utf-8').read()
    nums = set(re.findall(r'\[\^(\d+)\]', s))
    bad = []
    for n in sorted(nums, key=int):
        if s.count(f'[^{n}]') < 2:
            bad.append(n)
    return bad

def stray_footnote(path):
    return [i for i, line in enumerate(open(path, encoding='utf-8'), 1)
            if re.match(r'^\d{3}\)\s', line.strip())]

def starts_with_2(path):
    """②로 시작하는 판례 블록: 헤딩 다음 헤딩이 ②인데 그 앞에 ①이 없는 경우는
    본진 참조일 수 있으므로 경고만."""
    s = open(path, encoding='utf-8').read()
    return len(re.findall(r'^#{3,6} ② ', s, re.M)) - len(re.findall(r'^#{3,6} ① ', s, re.M))

def warn_count(path):
    """한 판례(①~다음 판례 전)에 ⚠️ 3개 이상"""
    s = open(path, encoding='utf-8').read()
    blocks = re.split(r'^#{3,6} (?:①|\d{2,4}[가-힣]+[가-힣0-9,]*)', s, flags=re.M)
    return [i for i, b in enumerate(blocks) if b.count('⚠️') >= 3]

def forbidden(path):
    s = open(path, encoding='utf-8').read()
    out = []
    if '관련 법리' in s: out.append('관련 법리')
    if re.search(r'대법원 \d{2,4}[가-힣]', s): out.append('대법원+사건번호')
    if re.search(r'대법원 \d{4}\.', s): out.append('선고일자')
    return out

def main(paths):
    total = 0
    for p in sorted(paths):
        msgs = []
        b = bold_too_long(p)
        if b: msgs.append(f'BOLD 10자 초과 {len(b)}건: ' +
                          ', '.join(f'{ln}행({n}자)' for ln, n, _ in b[:6]) +
                          (' …' if len(b) > 6 else ''))
        h = heading_depth(p)
        if h: msgs.append(f'헤딩 7단계 {len(h)}건: {h[:5]}')
        f = footnote_pairs(p)
        if f: msgs.append(f'각주 짝 없음: {f}')
        sf = stray_footnote(p)
        if sf: msgs.append(f'평문 각주(NNN\\)): {sf}')
        d = starts_with_2(p)
        if d > 0: msgs.append(f'②가 ①보다 {d}개 많음(본진 참조면 정상)')
        fb = forbidden(p)
        if fb: msgs.append(f'금지: {fb}')
        if msgs:
            total += 1
            print(f'\n■ {os.path.basename(p)}')
            for m in msgs: print('  -', m)
    print(f'\n지적된 파일 {total} / 검사 {len(paths)}')

if __name__ == '__main__':
    args = sys.argv[1:] or glob.glob('output/*.md')
    main(args)
