import sqlite3

conn = sqlite3.connect(r"C:\Users\Administrator\Desktop\tt_8004\data\rampart_local.db")
cur = conn.cursor()
rows = cur.execute("SELECT instance_id, name, qty, container, asset_id, stack_size FROM instances WHERE account='RAIDER23765' AND (name LIKE '%mag%' or type LIKE '%mag%')").fetchall()
print("All matching 'mag':")
for r in rows:
    print(r)
