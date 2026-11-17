import json, sqlite3, collections, sys, os
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
g=json.load(open(os.path.join(ROOT,'data/pioneer_game_data.json'),encoding='utf-8'))['items-description']['itemDescriptions']
g={str(r['gameAssetId']):r for r in g} if isinstance(g,list) else g
items=json.load(open(os.path.join(ROOT,'data/items_db.json'),encoding='utf-8'))['items']
id2name={}
for row in items.values():
    for a in row.get('asset_ids') or []: id2name[str(a)]=row['name']
db=sqlite3.connect(os.path.join(ROOT,'data/rampart_local.db'))
unk=[r[0] for r in db.execute("select distinct asset_id from instances where asset_id is not null and asset_id<>'' and (name is null or name='' or name like 'Item %')")]
def brief(aid):
    r=g[aid]
    sc=[(id2name.get(str(e['gameAssetId']),str(e['gameAssetId'])),e['amount']) for e in ((r.get('scrap') or {}).get('rewardPackage') or {}).get('rewardedItems') or []]
    rc=[(id2name.get(str(e['gameAssetId']),str(e['gameAssetId'])),e['amount']) for e in (r.get('recycle') or {}).get('rewardedItems') or []]
    pools=(r.get('recycle') or {}).get('randomRewards') or {}
    rp=(r.get('scrap') or {}).get('rewardPackage') or {}
    return dict(itemType=r.get('itemType'), max=r.get('maxAmount'), q=r.get('qualityLevel'),
                tags=r.get('tags'), slot=(r.get('slotConfig') or {}).get('discriminator'),
                unique=r.get('unique'), scrap=sc, recycle=rc,
                scrapPool=bool((rp.get('randomRewards') or {}).get('pools')), recPool=bool((pools.get('pools'))),
                up=r.get('upgrade',{}).get('nextItemGameAssetId'))
cnt=collections.Counter()
for aid in sorted(unk,key=str):
    b=brief(aid)
    key=(b['itemType'],b['slot'],bool(b['scrap']),bool(b['recycle']),b['q'])
    cnt[key]+=1
for k,v in cnt.most_common(): print(v,k)
print()
for aid in sorted(unk,key=str):
    b=brief(aid)
    print(aid,'|',b['itemType'],'| max',b['max'],'| q',b['q'],'|',b['slot'],'| tags',b['tags'],'| scrap',b['scrap'],'| rec',b['recycle'],'| up',b['up'])
