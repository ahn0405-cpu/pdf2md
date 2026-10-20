import re
from 경로 import 노트들
for p in 노트들():
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
        chunks=re.findall(r'\*\*(.+?)\*\*', gloss)
        heads=[b[0] for b in chunks]
        letters=[ch for ch in mn if ch.isalpha() or '가'<=ch<='힣']
        # 굵은 덩어리 하나가 붙은 두문자 글자 여러 개를 맡을 수 있다 — `[초과 적법]` = **초과**하면 … **적법**
        k=0; miss=[]; n=0
        while n<len(letters):
            ch=letters[n]; j2=k
            while j2<len(chunks) and chunks[j2][0]!=ch: j2+=1
            if j2>=len(chunks): miss.append(ch); n+=1; continue
            t=1
            while n+t<len(letters) and t<len(chunks[j2]) and chunks[j2][t]==letters[n+t]: t+=1
            n+=t; k=j2+1
        if miss:
            print(f'{p}:{i+1}  [{m.group(1)}]  머리={"".join(heads)}  ❌미대응:{"".join(miss)}')
