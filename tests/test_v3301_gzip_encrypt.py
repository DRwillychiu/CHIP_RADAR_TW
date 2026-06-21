# v3.51.0 機構級重整: tests/ 子目錄 → 加 src/ 到 sys.path
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import src  # noqa: F401 — side effect: 把 src/* 8 子目錄加進 sys.path

"""v3.30.1 gzip encrypt/decrypt round-trip + 壓縮率測試"""
import sys
import json
sys.path.insert(0, '.')

from crawler import encrypt_data, decrypt_data, PBKDF2_ITERATIONS

PWD = 'testpass123'
all_pass = True

print("=" * 60)
print("  v3.30.1 gzip encrypt/decrypt 測試")
print("=" * 60)

# ── 1. round-trip identity (gzip on) ──
print("\n1. Gzip ON round-trip identity")
sample = '{"hello": "world", "num": 12345, "list": [1,2,3]}'
token = encrypt_data(sample, PWD, use_gzip=True)
recovered = decrypt_data(token, PWD)
ok = recovered == sample
print(f"  {'✅' if ok else '❌'} round-trip identity: original={sample}, recovered={recovered}")
if not ok: all_pass = False

# ── 2. round-trip identity (gzip off, backward compat) ──
print("\n2. Gzip OFF round-trip (backward compat)")
token2 = encrypt_data(sample, PWD, use_gzip=False)
recovered2 = decrypt_data(token2, PWD)
ok2 = recovered2 == sample
print(f"  {'✅' if ok2 else '❌'} Gzip OFF 仍正常: recovered={recovered2}")
if not ok2: all_pass = False

# ── 3. decrypt_data 用 magic bytes auto-detect ──
print("\n3. decrypt_data auto-detect 兩種模式都通")
print(f"  Gzip ciphertext 長度: {len(token)} chars")
print(f"  Plain  ciphertext 長度: {len(token2)} chars")

# ── 4. 壓縮率 (用比較像真實 latest.json 的內容) ──
print("\n4. 真實 size 壓縮率 (模擬 30 MB JSON)")
# 構造類似真實 latest.json 的高重複度 JSON
big_data = {
    "branches": [
        {
            "code": f"9{i:03d}",
            "name": f"分點_{i}",
            "buys": [
                {
                    "code": f"2{j:03d}",
                    "name": f"個股_{j}",
                    "buy_lot": 100, "sell_lot": 50,
                    "buy_amt": 100000, "sell_amt": 30000,
                    "trade_pattern": "波段持股",
                    "insight_narrative": "蔣承翰(隔日沖型)於凱基-城中分點搶買創意(3443) 11 張共 1,546 萬元,淨買 11 張,今日漲停 (+9.96%)。隔日沖風格偏好高動能漲停股,留倉特徵符合其於高點佈局、隔日開盤即出貨的操作邏輯。",
                } for j in range(20)
            ],
        } for i in range(56)
    ]
}
big_json = json.dumps(big_data, ensure_ascii=False)
big_size_kb = len(big_json) / 1024

token_gz = encrypt_data(big_json, PWD, use_gzip=True)
token_no = encrypt_data(big_json, PWD, use_gzip=False)

gz_kb = len(token_gz) / 1024
no_kb = len(token_no) / 1024
compression = (1 - gz_kb / no_kb) * 100
print(f"  原始 JSON: {big_size_kb:,.1f} KB")
print(f"  Gzip OFF ciphertext: {no_kb:,.1f} KB")
print(f"  Gzip ON  ciphertext: {gz_kb:,.1f} KB ({compression:.1f}% 縮減)")

# 驗證 gzip 版仍能 decrypt
recovered_big = decrypt_data(token_gz, PWD)
ok_big = recovered_big == big_json
print(f"  {'✅' if ok_big else '❌'} 大型 JSON gzip 解密 identity")
if not ok_big: all_pass = False

# 預期壓縮率 > 50% (對 JSON 文字效果應該很好)
ok_compression = compression > 50
print(f"  {'✅' if ok_compression else '❌'} 壓縮率 {compression:.1f}% > 50% (目標)")
if not ok_compression:
    print(f"     ⚠️ 預期 JSON 壓縮率 60-70%, 實測 {compression:.1f}% 偏低")
    all_pass = False

# ── 5. UTF-8 中文 round-trip ──
print("\n5. UTF-8 中文 round-trip")
chinese = "蔣承翰(隔日沖型)於凱基-城中分點搶買創意(3443)"
ctoken = encrypt_data(chinese, PWD, use_gzip=True)
crecov = decrypt_data(ctoken, PWD)
okc = crecov == chinese
print(f"  {'✅' if okc else '❌'} 中文 identity: '{crecov}'")
if not okc: all_pass = False

print()
print("─" * 60)
print(f"  整體: {'✅ ALL PASS' if all_pass else '❌ HAS FAIL'}")
sys.exit(0 if all_pass else 1)
