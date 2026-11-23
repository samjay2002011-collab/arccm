src=open('data/_probe_seg.py',encoding='utf-8').read()
i=src.find('    items = []')
seg=src[:i]+'    print("PAST-BRANCH", need, in_bag, want, flush=True)\n    return out\n'
ns={}
exec(compile(seg,'seg','exec'),ns)
f=ns['_fill_plan_of']
box = type('B', (), {'in_bag_of': lambda self, a: [], 'seat': lambda self, i: 'x', 'bag': set(),
                     'free_bag': lambda self: [], 'seat_room': lambda self, c: True,
                     'free_cell': lambda self: 'c'})()
seen=[]
def tr(frame,event,arg):
    if frame.f_code is f.__code__:
        seen.append((event, frame.f_lineno, frame.f_locals.get('need'), frame.f_locals.get('in_bag'), frame.f_lineno))
    return tr
import sys
sys.settrace(tr)
r=f({'box': box, 'stacks': [], 'pieces': [], 'in_bag': 3, 'aid': 'a'}, 2, 5)
sys.settrace(None)
for s in seen[:40]: print(s)
print(r['need'], r['in_bag'])
