import re
BOLD = re.compile(r'\*\*(.+?)\*\*', re.S)
def norm(t): return re.sub(r'[`\[\]()·,/…\s>\n]','',t)

def split(path, specs):
    """specs: [(key, [seg,...]), ...]  파일 등장 순서대로.
    key: 해당 BOLD 내부 텍스트의 앞부분(정규화 후 startswith)
    seg: 볼드로 남길 조각들(줄바꿈을 넘지 않을 것)"""
    s = open(path,encoding='utf-8').read()
    used=set(); fails=[]
    def repl(m):
        inner=m.group(1); n=norm(inner)
        for i,(key,segs) in enumerate(specs):
            if i in used: continue
            if not n.startswith(norm(key)): continue
            used.add(i)
            out=[]; rest=inner
            for seg in segs:
                j=rest.find(seg)
                if j<0:
                    fails.append((key[:20],seg)); return m.group(0)
                out.append(rest[:j]); out.append('**'+seg+'**'); rest=rest[j+len(seg):]
            out.append(rest)
            return ''.join(out)
        return m.group(0)
    s2=BOLD.sub(repl,s)
    open(path,'w',encoding='utf-8').write(s2)
    miss=[k[:20] for i,(k,_) in enumerate(specs) if i not in used]
    msg=f'{path}: 적용 {len(used)}/{len(specs)}'
    if miss: msg+=f'\n  ❌미매칭: {miss}'
    if fails: msg+=f'\n  ❌조각실패: {fails}'
    print(msg)
