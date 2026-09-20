import sys, io
def apply(path, pairs):
    s=open(path,encoding='utf-8').read(); n=0; miss=[]
    for old,new in pairs:
        if old in s: s=s.replace(old,new); n+=1
        else: miss.append(old[:40])
    open(path,'w',encoding='utf-8').write(s)
    print(f'{path}: 적용 {n}/{len(pairs)}' + (f'  ❌미매칭 {miss}' if miss else ''))
