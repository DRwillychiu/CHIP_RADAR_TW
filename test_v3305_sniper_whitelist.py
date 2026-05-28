"""v3.30.5 sniper 白名單 (僅蔣承翰用漲停法) 測試"""
import sys
sys.path.insert(0, '.')

from excel_report import _is_sniper_master, SNIPER_MASTER_WHITELIST, SNIPER_STYLES

all_pass = True
print("=" * 60)
print("  v3.30.5 sniper 白名單測試 (僅蔣承翰)")
print("=" * 60)

# 1. 蔣承翰 → sniper (唯一)
print("\n1. 蔣承翰 → sniper mode = True")
ok = _is_sniper_master("蔣承翰") is True
print(f"  {'OK' if ok else 'FAIL'} _is_sniper_master('蔣承翰') = {_is_sniper_master('蔣承翰')}")
if not ok: all_pass = False

# 2. 迷你哥/松山哥 (原 sniper day_trader) → 現在 False
print("\n2. 迷你哥/松山哥 (原 sniper) → 現在 False")
ok = _is_sniper_master("迷你哥/松山哥") is False
print(f"  {'OK' if ok else 'FAIL'} = {_is_sniper_master('迷你哥/松山哥')}")
if not ok: all_pass = False

# 3. Tradow (原 sniper next_day_flipper) → 現在 False
print("\n3. Tradow (原 sniper) → 現在 False")
ok = _is_sniper_master("Tradow") is False
print(f"  {'OK' if ok else 'FAIL'} = {_is_sniper_master('Tradow')}")
if not ok: all_pass = False

# 4. 巨人傑 (原 sniper 兩 style 都有) → 現在 False
print("\n4. 巨人傑 (原 sniper) → 現在 False")
ok = _is_sniper_master("巨人傑") is False
print(f"  {'OK' if ok else 'FAIL'} = {_is_sniper_master('巨人傑')}")
if not ok: all_pass = False

# 5. 一般 swing master (民哥) → False (不變)
print("\n5. 民哥 (一般) → False (不變)")
ok = _is_sniper_master("民哥") is False
print(f"  {'OK' if ok else 'FAIL'} = {_is_sniper_master('民哥')}")
if not ok: all_pass = False

# 6. 不存在的 master → False
print("\n6. 不存在 master → False")
ok = _is_sniper_master("不存在的人XYZ") is False
print(f"  {'OK' if ok else 'FAIL'} = {_is_sniper_master('不存在的人XYZ')}")
if not ok: all_pass = False

# 7. 白名單內容 = 只有蔣承翰
print("\n7. SNIPER_MASTER_WHITELIST 僅含蔣承翰")
ok = SNIPER_MASTER_WHITELIST == {"蔣承翰"}
print(f"  {'OK' if ok else 'FAIL'} 白名單 = {SNIPER_MASTER_WHITELIST}")
if not ok: all_pass = False

# 8. SNIPER_STYLES 保留 (向後相容, 仍是雙條件用)
print("\n8. SNIPER_STYLES 保留")
ok = SNIPER_STYLES == {"next_day_flipper", "day_trader"}
print(f"  {'OK' if ok else 'FAIL'} SNIPER_STYLES = {SNIPER_STYLES}")
if not ok: all_pass = False

print()
print("─" * 60)
print(f"  整體: {'OK ALL PASS' if all_pass else 'FAIL HAS FAIL'}")
sys.exit(0 if all_pass else 1)
