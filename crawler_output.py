"""
crawler_output.py — 輸出層 (v3.35.0 B1 從 crawler.py 拆出)

AES-256-GCM + PBKDF2-SHA256 + gzip 加密/解密。
所有寫出檔案的「資料盔甲」: latest.json / daily JSON / positions.json 都經此層。

⚠️ 加密層改動 backward compat 至關重要 (紀律 10):
   decrypt_data 用 gzip magic bytes (1F 8B) auto-detect,
   舊未壓縮 ciphertext 仍能正常解密。前端 index.html decryptToken 同邏輯。

被 import 處: crawler.py / master_profile.py / db_pipeline.py /
              histock_branch_audit.py / stress_test_data_integrity.py / tests
              (全部透過 crawler.py re-export, 舊 `from crawler import X` 不變)
"""
import os
import base64

from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


PBKDF2_ITERATIONS = 100000   # 預設值 (v3.30.1 起延用); 升 600k 規劃見下方註解

# P1-1 (v3.39.0): PBKDF2 動態 iterations 升級鋪路
#   v3.30.1 起 outer JSON (latest.json 等) 已含 "iterations" 欄位, 但
#   decrypt_data 之前 hardcode 100k. 改成接受 iterations 參數 → 為未來升
#   600k 鋪路 (新檔寫 600k, 舊 archive 仍用 100k, 透過 outer.iterations
#   自動辨識, 不破 backward compat).
#   前端 index.html decryptToken 同步改 (本 patch 一起修).

# v3.30.1 (2026-05-24, 專業審視 A.1):
# encrypt_data 加 gzip 壓縮 (預設 ON), 預期 latest.json 12MB → ~4MB.
# decrypt_data 用 gzip magic bytes (1F 8B) 自動偵測, 完全 backward compat
# 舊未壓縮 ciphertext 仍能正常解密 (沒 magic bytes → 跳過 gzip.decompress).
import gzip


def encrypt_data(plaintext: str, password: str, use_gzip: bool = True,
                  iterations: int = None) -> str:
    """加密 + (可選) gzip 壓縮.

    v3.30.1: 預設 use_gzip=True. 對 JSON 文字壓縮率 60-70%,
    AES-GCM ciphertext 體積等比例縮小. 前端 decryptToken 用 magic bytes
    auto-detect, 不需 API 變更.
    v3.39.0 P1-1: 加 iterations 參數 (預設 PBKDF2_ITERATIONS, 升級時改值即可).
    呼叫端應同時將實際使用的 iterations 寫進 outer JSON, 讓 decrypt 自動辨識.
    """
    if iterations is None:
        iterations = PBKDF2_ITERATIONS
    salt = os.urandom(16)
    iv = os.urandom(12)
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=iterations)
    key = kdf.derive(password.encode("utf-8"))
    aesgcm = AESGCM(key)

    if use_gzip:
        plain_bytes = gzip.compress(plaintext.encode("utf-8"), compresslevel=9)
    else:
        plain_bytes = plaintext.encode("utf-8")

    ct = aesgcm.encrypt(iv, plain_bytes, None)
    return base64.b64encode(salt + iv + ct).decode("ascii")


def decrypt_data(token: str, password: str, iterations: int = None) -> str:
    """解密 + (auto-detect) gzip decompress.

    v3.30.1: 解出 plaintext bytes 後檢查 magic bytes (1F 8B),
    是 gzip 就 decompress, 否則直接 decode. 完全 backward compat.
    v3.39.0 P1-1: 加 iterations 參數 (預設 PBKDF2_ITERATIONS = 100k);
    呼叫端應從 outer JSON 讀 iterations 傳入, 才能解新加密 (600k+) 的檔案.
    """
    if iterations is None:
        iterations = PBKDF2_ITERATIONS
    raw = base64.b64decode(token)
    salt, iv, ct = raw[:16], raw[16:28], raw[28:]
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=iterations)
    key = kdf.derive(password.encode("utf-8"))
    aesgcm = AESGCM(key)
    plain_bytes = aesgcm.decrypt(iv, ct, None)

    # v3.30.1: gzip magic bytes auto-detect
    if len(plain_bytes) >= 2 and plain_bytes[0] == 0x1F and plain_bytes[1] == 0x8B:
        plain_bytes = gzip.decompress(plain_bytes)

    return plain_bytes.decode("utf-8")

