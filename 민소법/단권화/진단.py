import re, glob, sys
files = sys.argv[1:] or sorted(glob.glob('output/*.md'))
print(f'{"파일":34} 관련법리 결단無이유 취지1줄 문장뼈대 비유참조 판시BOLD초과')
for p in files:
    L = open(p,encoding='utf-8').read().split('\n')
    s = '\n'.join(L)
    관련법리 = sum('**관련 법리**' in l for l in L)
    문장뼈대 = sum('**문장 뼈대**' in l for l in L)
    비유참조 = len(re.findall(r'위 비유의|앞 비유|그 비유의', s))
    # 대법원/법원의 결단 — 이유 접속어가 없는 것
    결단 = [i for i,l in enumerate(L) if re.search(r'\*\*(대법원|법원)의 결단\*\*', l)]
    무이유 = 0
    벗김 = lambda l: re.sub(r'^[>\s]*>', '', l) if l.lstrip().startswith('>') else l
    for i in 결단:
        blk = L[i]
        j = i+1
        while j < len(L) and 벗김(L[j]).startswith('  ') and not re.match(r'\s*-\s\*\*', 벗김(L[j])):
            blk += ' ' + L[j].strip(); j += 1
        if not re.search(r'때문|이므로|이기에|므로|까닭|이유|아니므로|되므로|하므로', blk):
            무이유 += 1
    # 판례 취지 한 줄짜리
    취지 = [i for i,l in enumerate(L) if '**판례 취지**' in l]
    한줄 = 0
    for i in 취지:
        j=i+1; n=1
        while j<len(L) and 벗김(L[j]).startswith('  ') and not re.match(r'\s*-\s\*\*', 벗김(L[j])):
            n+=1; j+=1
        if n <= 1: 한줄 += 1
    # 판시 안 BOLD 15자 초과
    판시=[]; 기준=0
    깊이 = lambda l: len(re.findall(r'>', l[:len(l)-len(re.sub(r'^[>\s]*','',l))]))
    for line in L:
        알맹이 = re.sub(r'^[>\s]*','',line)
        if 알맹이.startswith('#'): 기준 = 깊이(line)   # 헤딩의 깊이가 그 절의 바탕
        q = 깊이(line) > 기준 and not 알맹이.startswith('|')
        판시.extend([q]*(len(line)+1))
    초과 = sum(1 for m in re.finditer(r'\*\*(.+?)\*\*', s, re.S)
               if m.start()<len(판시) and 판시[m.start()]
               and len(re.sub(r'[`\[\]()·,/…\s>\n]','',m.group(1)))>15)
    print(f'{p.replace("output/",""):34} {관련법리:6} {무이유:8} {한줄:7} {문장뼈대:7} {비유참조:7} {초과:9}')
