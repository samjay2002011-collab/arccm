import sqlite3

conn = sqlite3.connect(r'C:\Users\Administrator\Desktop\tt_8004\data\rampart_local.db')
cur = conn.cursor()
rows = cur.execute("SELECT instance_id, name, qty, container, asset_id, stack_size FROM instances WHERE account='RAIDER23765' AND name LIKE '%mag%' LIMIT 10").fetchall()
print("Found", len(rows), "mag rows:")
for r in rows:
    print(r)

ammo = cur.execute("SELECT instance_id, name, qty, container, asset_id, stack_size FROM instances WHERE account='RAIDER23765' AND (name LIKE '%ammo%' or type LIKE '%ammo%') LIMIT 10").fetchall()
print("Found", len(ammo), "ammo rows:")
for r in ammo:
    print(r)
