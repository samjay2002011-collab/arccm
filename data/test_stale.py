import sqlite3
import sys
sys.path.insert(0, r"C:\Users\Administrator\Desktop\tt_8004")

from backend import actions, pioneer_write

conn = sqlite3.connect(r"C:\Users\Administrator\Desktop\tt_8004\data\rampart_local.db")
account = "RAIDER23765"

# Let's check what happens with current_total and now_total
body = [{"instance_id": "dummy", "current_total": 1, "now_total": 4}]
res = pioneer_write.move(conn, account, "backpack", body)
print("Result of stale check:", res)
