import sqlite3
import sys
sys.path.insert(0, r"C:\Users\Administrator\Desktop\tt_8004")

from backend import actions, pioneer_client as pc, pioneer_tree

conn = sqlite3.connect(r"C:\Users\Administrator\Desktop\tt_8004\data\rampart_local.db")
account = "RAIDER23765"

# Let's inspect what items exist in stash for RAIDER23765
data = pc.fetch_inventory_for(account)
tree = pioneer_tree.Tree((data or {}).get("items") or [])
pioneer_tree.layout(tree)

print("Inventory items count:", len(tree.by_id))

# Find Magnet
for iid, node in tree.by_id.items():
    if "Magnet" in str(node.get("name", "")) or node.get("gameAssetId") == -863904193:
        parent_id = tree.parent.get(iid)
        print(f"Magnet node: iid={iid}, amount={node.get('amount')}, parent={parent_id}, name={node.get('name')}")

# Test _fill_read for Magnet (-863904193)
found = actions._fill_read(conn, account, -863904193, want=3)
print("Found for Magnet:")
print("  in_bag:", found["in_bag"])
print("  stacks:", found["stacks"])
print("  pieces:", found["pieces"])
print("  locked:", found["locked"])

# Test _fill_plan_of
calc = actions._fill_plan_of(found, want=3, cap=15)
print("Calc want=3:")
print("  need:", calc["need"])
print("  plan:", calc["plan"])
print("  short:", calc["short"])
print("  cells:", calc["cells"])
