import json, collections, sys
path = sys.argv[1]
# По каждому решению: были ли кандидаты с гейнами прикрытия/вытеснения/отпора?
cover = disp = defen = 0
cand_actions = collections.Counter()
paths_with_cover = 0
n = 0
for l in open(path):
    try:
        d = json.loads(l)
    except Exception:
        continue
    n += 1
    blob = json.dumps(d, ensure_ascii=False)
    if 'прикрываем' in blob:
        cover += 1
    if 'вытесняем нарушителя' in blob:
        disp += 1
    if 'ОТПОР' in blob:
        defen += 1
print(f"записей: {n}")
print(f"решений, где среди кандидатов было 'прикрываем': {cover}")
print(f"решений, где среди кандидатов было 'вытесняем нарушителя': {disp}")
print(f"решений, где среди кандидатов было 'ОТПОР': {defen}")
