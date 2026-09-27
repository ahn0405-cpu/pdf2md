"""짝 판례 점검 — 구별 개념이 가리킨 상대 판례가 노트 어딘가에서 실제로 다뤄지는지."""
import re, glob
CASE = re.compile(r'\b\d{2,4}\s?(?:다|므|마|모|두|누|후|허|그|카|재다|재누)\s?\d{2,6}')
files=sorted(glob.glob('output/*.md'))
treated=set()
for p in files:
    for ln in open(p,encoding='utf-8'):
        st=ln.strip()
        # 실질 취급으로 보는 자리: 헤딩 / 판시 인용문 / 각주 정의 / 표의 칸
        if re.match(r'^#{2,6}\s', st) or st.startswith('>') or re.match(r'^\[\^\d+\]:', st) or st.startswith('|'):
            for m in CASE.finditer(ln): treated.add(m.group().replace(' ',''))
miss={}
for p in files:
    lines=open(p,encoding='utf-8').read().split('\n')
    for i,ln in enumerate(lines):
        if '구별 개념' not in ln: continue
        buf=ln
        for j in range(1,4):
            if i+j>=len(lines): break
            t=lines[i+j].strip().lstrip('>').strip()
            if not t or re.match(r'^[-*]\s|^#',t): break
            buf+=' '+t
        for m in CASE.finditer(buf):
            c=m.group().replace(' ','')
            if c not in treated: miss.setdefault(c,[]).append(f'{p}:{i+1}')
for c,v in miss.items(): print(f'❌ {c}  구별 개념만 있고 취급 없음  {v}')
print('구별 개념이 가리킨 상대 판례 — 모두 취급됨' if not miss else f'총 {len(miss)}건')

print('\n--- 「반대 결론」·「세트」로 짝을 선언한 자리 ---')
for p in files:
    for i,ln in enumerate(open(p,encoding='utf-8')):
        if re.search(r'반대 결론|반드시 세트|짝(?:입니다|이다|입니다)|와 짝', ln):
            print(f'{p}:{i+1}  {ln.strip()[:95]}')
