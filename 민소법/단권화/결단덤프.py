import re, sys
for p in sys.argv[1:]:
    L=open(p,encoding='utf-8').read().split('\n')
    print(f'##### {p}')
    for i,l in enumerate(L):
        if '의 결단**' not in l: continue
        j=i+1; blk=[l]
        while j<len(L) and L[j].startswith('  ') and not re.match(r'\s*-\s\*\*', L[j]):
            blk.append(L[j]); j+=1
        if re.search(r'때문|이므로|므로|까닭|이유', ' '.join(blk)): continue
        k=j; 판시=[]
        while k<len(L) and k<j+40:
            if L[k].strip().startswith('>'): 판시.append(L[k].strip())
            if 판시 and not L[k].strip().startswith('>') and L[k].strip(): break
            k+=1
        print(f'--- {i+1}'); print('\n'.join(blk))
        print('  판시>', ' '.join(x.lstrip('> ') for x in 판시)[:280])
