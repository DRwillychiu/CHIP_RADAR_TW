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


PBKDF2_ITERATIONS = 100000

# v3.30.1 (2026-05-24, 專業審視 A.1):
# encrypt_data 加 gzip 壓縮 (預設 ON), 預期 latest.json 12MB → ~4MB.
# decrypt_data 用 gzip magic bytes (1F 8B) 自動偵測, 完全 backward compat
# 舊未壓縮 ciphertext 仍能正常解密 (沒 magic bytes → 跳過 gzip.decompress).
import gzip


def encrypt_data(plaintext: str, password: str, use_gzip: bool = True) -> str:
    """加密 + (可選) gzip 壓縮.

    v3.30.1: 預設 use_gzip=True. 對 JSON 文字壓縮率 60-70%,
    AES-GCM ciphertext 體積等比例縮小. 前端 decryptToken 用 magic bytes
    auto-detect, 不需 API 變更.
    """
    salt = os.urandom(16)
    iv = os.urandom(12)
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=PBKDF2_ITERATIONS)
    key = kdf.derive(password.encode("utf-8"))
    aesgcm = AESGCM(key)

    if use_gzip:
        plain_bytes = gzip.compress(plaintext.encode("utf-8"), compresslevel=9)
    else:
        plain_bytes = plaintext.encode("utf-8")

    ct = aesgcm.encrypt(iv, plain_bytes, None)
    return base64.b64encode(salt + iv + ct).decode("ascii")


def decrypt_data(token: str, password: str) -> str:
    """解密 + (auto-detect) gzip decompress.

    v3.30.1: 解出 plaintext bytes 後檢查 magic bytes (1F 8B),
    是 gzip 就 decompress, 否則直接 decode. 完全 backward compat.
    """
    raw = base64.b64decode(token)
    salt, iv, ct = raw[:16], raw[16:28], raw[28:]
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=PBKDF2_ITERATIONS)
    key = kdf.derive(password.encode("utf-8"))
    aesgcm = AESGCM(key)
    plain_bytes = aesgcm.decrypt(iv, ct, None)

    # v3.30.1: gzip magic bytes auto-detect
    if len(plain_bytes) >= 2 and plain_bytes[0] == 0x1F and plain_bytes[1] == 0x8B:
        plain_bytes = gzip.decompress(plain_bytes)

    return plain_bytes.decode("utf-8")

