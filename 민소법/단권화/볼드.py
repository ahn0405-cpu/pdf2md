import re, sys
BOLD = re.compile(r'\*\*(.+?)\*\*', re.S)
def dump(path, only_quote=True, limit=15):
    s=open(path,encoding='utf-8').read(); lines=s.split('\n')
    isq=[]
    for ln in lines:
        q=ln.lstrip().startswith('>'); isq.extend([q]*(len(ln)+1))
    for m in BOLD.finditer(s):
        t=re.sub(r'[`\[\]()·,/…\s>\n]','',m.group(1))
        if len(t)<=limit: continue
        if only_quote and not isq[m.start()]: continue
        print(f'{len(t):2d}|{m.group(1)}')
for p in sys.argv[1:]:
    print('#####', p); dump(p)
