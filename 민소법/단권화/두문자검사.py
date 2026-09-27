import re, glob
for p in sorted(glob.glob('output/*.md')):
    lines=open(p,encoding='utf-8').read().split('\n')
    for i,ln in enumerate(lines):
        if '한 줄 요약' not in ln: continue
        m=re.search(r'`\[([^\]]+)\]`', ln)
        if not m: continue
        mn=m.group(1).replace(' ','')
        buf=ln[m.end():]
        for j in range(1,6):
            if i+j>=len(lines): break
            t=lines[i+j].strip().lstrip('>').strip()
            if not t: break
            if re.match(r'^[-*]\s|^#|^\|', t): break      # 다음 항목
            buf+=' '+t
        if '=' not in buf:
            print(f'{p}:{i+1}  [{m.group(1)}]  ⚠️풀이없음'); continue
        gloss=buf.split('=',1)[1]
        heads=[b[0] for b in re.findall(r'\*\*(.+?)\*\*', gloss)]
        k=0; miss=[]
        for ch in mn:
            if not ch.isalpha() and not ('가'<=ch<='힣'): continue
            j2=k
            while j2<len(heads) and heads[j2]!=ch: j2+=1
            if j2>=len(heads): miss.append(ch)
            else: k=j2+1
        if miss:
            print(f'{p}:{i+1}  [{m.group(1)}]  머리={"".join(heads)}  ❌미대응:{"".join(miss)}')
