# -*- coding: utf-8 -*-
"""
test_v3390_pbkdf2_dynamic.py — v3.39.0 P1-1 PBKDF2 動態 iterations 測試

驗證:
  1. 預設 iterations (100k) 加密 → 預設解密 round-trip
  2. 加密 100k → 解密強制傳 100k (顯式) round-trip
  3. 加密 600k → 解密傳 600k round-trip (新值)
  4. 加密 100k → 用 600k 解密失敗 (InvalidTag)
  5. encrypt_data backward compat: 不傳 iterations 仍用預設
  6. decrypt_data backward compat: 不傳 iterations 仍用預設

跑法: python test_v3390_pbkdf2_dynamic.py
"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from crawler_output import encrypt_data, decrypt_data, PBKDF2_ITERATIONS
from cryptography.exceptions import InvalidTag

PASS = 0
FAIL = 0

def check(name, cond, detail=''):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name}  {detail}")

PWD = 'testpass123'
MSG = '中文 + emoji 🎯 + JSON {"a":1}'

print(f"\n[Case 1] 預設 iterations ({PBKDF2_ITERATIONS}) round-trip")
ct1 = encrypt_data(MSG, PWD)
pt1 = decrypt_data(ct1, PWD)
check("預設 round-trip", pt1 == MSG)

print(f"\n[Case 2] 顯式傳 100k iterations round-trip")
ct2 = encrypt_data(MSG, PWD, iterations=100000)
pt2 = decrypt_data(ct2, PWD, iterations=100000)
check("顯式 100k round-trip", pt2 == MSG)

print("\n[Case 3] 加密 600k → 解密 600k round-trip (新升級)")
ct3 = encrypt_data(MSG, PWD, iterations=600000)
pt3 = decrypt_data(ct3, PWD, iterations=600000)
check("600k round-trip", pt3 == MSG)

print("\n[Case 4] 加密 100k → 解密 600k 失敗 (key mismatch)")
ct4 = encrypt_data(MSG, PWD, iterations=100000)
got_invalid = False
try:
    decrypt_data(ct4, PWD, iterations=600000)
except InvalidTag:
    got_invalid = True
check("100k → 600k 解密 raise InvalidTag", got_invalid)

print("\n[Case 5] encrypt_data 不傳 iterations (backward compat)")
ct5 = encrypt_data(MSG, PWD)   # 不傳
pt5 = decrypt_data(ct5, PWD, iterations=PBKDF2_ITERATIONS)   # 用相同預設解
check("encrypt 預設 = PBKDF2_ITERATIONS", pt5 == MSG)

print("\n[Case 6] decrypt_data 不傳 iterations (backward compat)")
ct6 = encrypt_data(MSG, PWD, iterations=PBKDF2_ITERATIONS)
pt6 = decrypt_data(ct6, PWD)   # 不傳
check("decrypt 預設 = PBKDF2_ITERATIONS", pt6 == MSG)

print("\n[Case 7] use_gzip=False 仍 round-trip (gzip + iterations 兩個相容)")
ct7 = encrypt_data(MSG, PWD, use_gzip=False, iterations=600000)
pt7 = decrypt_data(ct7, PWD, iterations=600000)
check("gzip=False + 600k round-trip", pt7 == MSG)

print(f"\n{'='*60}")
print(f"test_v3390_pbkdf2_dynamic: {PASS} PASS / {FAIL} FAIL")
sys.exit(0 if FAIL == 0 else 1)
