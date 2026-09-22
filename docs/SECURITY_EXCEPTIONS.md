# Security Audit 例外清單

> 建立：2026-09-21 (v3.79.2)
> 適用：`.github/workflows/security-audit.yml` 的 `pip-audit --ignore-vuln`
> 複審週期：每季（與 `config/algo_params.yaml` 同步），或任一「複審觸發條件」成立時立即複審

## 為什麼需要這份文件

`pip-audit` 回報的是「這個套件版本有 advisory」，不是「這個 advisory 能影響我們的程式碼」。
兩者混為一談會造成告警疲勞——本專案的 Security Audit 已連續紅燈 10 週以上
（2026-07-19 ~ 2026-09-20，見 GitHub Actions 紀錄），紅燈本身失去訊號價值。

本文件逐條記錄「為什麼判定不適用」與「什麼情況要重新評估」。
**沒有列在這裡的 advisory 一律讓 workflow 變紅。**

## 本專案使用 cryptography 的完整表面積

以下四個 import 是全 repo 的完整清單（`grep -rn "from cryptography"` 驗證）：

| Import | 位置 |
|---|---|
| `PBKDF2HMAC` | `crawler.py:35`、`src/pipelines/crawler_output.py:18` |
| `hashes` | `crawler.py:36`、`src/pipelines/crawler_output.py:19` |
| `AESGCM` | `crawler.py:37`、`src/pipelines/crawler_output.py:20` |
| `InvalidTag` | `tests/test_v3390_pbkdf2_dynamic.py:24` |

用途：以密碼經 PBKDF2HMAC(SHA-256) 導出金鑰，再用 AES-GCM 加解密**本專案自己產生的**
每日 JSON 檔案。

**不存在**於本專案：TLS／對外服務、X.509 憑證解析或驗證、PKCS#7／PKCS#12、
SSH 金鑰、非對稱金鑰載入、Fernet、解析不可信來源的 ASN.1。
唯一的「外部輸入」是本程式自己先前加密產生的 ciphertext。

---

## 已修補（不在 ignore 清單）

> 下列三條由 `cryptography>=46.0.7` **真正修掉**，不靠 ignore 掩蓋。
> 升版後實測 `pip-audit`（不加任何 ignore）已不再報出這三條。

### PYSEC-2026-2141 / CVE-2026-26007 — 不適用，但已順帶修掉

- 元件：EC 公鑰載入未驗證點位於正確 prime-order subgroup（僅 SECT 二進位曲線）
- 嚴重度：CVSS 3.1 7.5 High；修補版本 46.0.5
- 適用性：**NOT APPLICABLE**（本專案不載入任何非對稱／EC 金鑰）
- 為何不在 ignore 清單：`>=46.0.7` 已高於其 fix 版本，pip-audit 不再報出

### PYSEC-2026-35 / CVE-2026-34073 — 不適用，但已順帶修掉

- 元件：X.509 name constraints 只比對子憑證 SAN、未比對 peer name
- 嚴重度：CVSS 3.1 5.3 Medium；修補版本 46.0.6
- 適用性：**NOT APPLICABLE**（本專案無憑證驗證路徑）
- 為何不在 ignore 清單：同上

### PYSEC-2026-36 / CVE-2026-39892 — **適用，已修**

- 元件：`src/rust/src/buf.rs` 的 `CffiBuf` 共用 buffer 擷取層
- 影響版本：45.0.0 – 46.0.6；修補版本：**46.0.7**
- **為何適用**：advisory 正文只舉 `Hash.update()` 為例，照字面讀容易誤判成「只影響 hashes」。
  實際比對原始碼，46.0.7 的修補是在 `CffiBuf` 加上 `is_c_contiguous()` 檢查，
  而 `backend/aead.rs` 的 `encrypt(nonce: CffiBuf, data: CffiBuf, ...)` 與
  `backend/kdf.rs` 的 `derive_pbkdf2_hmac(key_material: CffiBuf, ...)`
  **都從這同一層取參數**。→ AESGCM 與 PBKDF2HMAC 確實在受影響路徑上。
- 處置：`requirements.txt` 下界升為 `>=46.0.7`
- 補充（不影響處置，僅供風險分級）：觸發條件是傳入**非連續 buffer**
  （PoC 用 `buf[::-1]` 這類反向切片的 memoryview）。本專案全 repo 的
  `memoryview` / `.getbuffer()` / `bytearray(` 命中數為 **0**，
  傳入的一律是 `bytes` / `str.encode()`（永遠 C-contiguous），故無可觸發路徑。
  屬「應修但無立即利用風險」，已修。

---

## 例外清單（`--ignore-vuln`）

> 這 4 條是升版到 46.0.7 後**實測仍會報出**的全部項目。
> 清單刻意與實測結果一致——不 ignore 任何已經修掉的 ID，
> 以免看不出「哪些是真修、哪些是暫時放行」。

| ID | 元件 | 嚴重度 | 修補版本 | 不適用理由 |
|---|---|---|---|---|
| `GHSA-537c-gmf6-5ccf` | wheel 內靜態連結的 OpenSSL（2026-06-09 批次 18 個 CVE） | 7.5 High | 48.0.1 | 18 條逐條核對，無一觸及 plain AES-GCM / PBKDF2 / SHA-256（見下方「近距離誤判」） |
| `PYSEC-2026-3552` | PKCS#7 EnvelopedData 解密的 Bleichenbacher oracle | CVSS 4.0 | 50.0.0 | 本專案不使用 PKCS#7 |
| `PYSEC-2026-3553` | X.509 `build_chain_inner` 重複自簽中繼憑證造成指數級 path building（DoS） | CVSS 4.0，僅可用性 | 49.0.0 | 本專案不建構憑證鏈 |
| `PYSEC-2026-3554` | X.509 verifier 接受萬用字元 SAN 逃逸 permittedSubtrees | CVSS 4.0 | 49.0.0 | 本專案不做 X.509 驗證 |

這 4 條的修補版本都在 47.0.0 以上，會撞到下方「放寬上界前必讀」列出的環境限制，
因此選擇「明確記錄後放行」而非為了儀表板變綠去跨 4 個 major 版本。

### GHSA-537c-gmf6-5ccf 的近距離誤判（最容易判錯，已排除）

該 OpenSSL 批次中三條「看起來相關但實際不相關」的：

- `CVE-2026-45446` 是 **AES-GCM-SIV / AES-SIV**（RFC 8452），與 `AESGCM` 用的 plain GCM 不同模式
- `CVE-2026-45445` 是 **AES-OCB**，另一種模式
- `CVE-2026-34181` 是 **PKCS#12 PBMAC1** 接受過短 HMAC key，屬 PKCS#12 處理流程，非 PBKDF2 KDF primitive 本身

其餘 15 條分布於 PKCS7_verify、CMS、QUIC、TLS/OCSP、ASN.1、CMP/CRMF、DHX。

---

## 複審觸發條件（任一成立即須重新評估，不等季度）

1. 專案開始使用上表任一元件：X.509／憑證驗證、PKCS#7／PKCS#12、
   非對稱或 EC 金鑰載入、TLS 連線終止、Fernet
2. 開始對**不可信來源**的資料呼叫 cryptography（目前只加解密自己產生的檔案）
3. 程式碼開始傳 `memoryview` / `bytearray` / `.getbuffer()` 給 cryptography
   （會讓 buffer 類 advisory 從理論變成可觸發）
4. 上述任一 advisory 被上游重新分級，或發布新的 affected range
5. `requirements.txt` 的 cryptography 上界放寬跨越 major 版本

## 放寬上界前必讀（47.0.0 以上的環境限制）

目前釘 `<47.0`。若未來要放寬，以下與本專案四支 API 無關、但會擋住執行環境：

- **47.0.0**：移除 SECT 曲線、移除 OpenSSL 1.1.x 支援、Rust MSRV 升至 1.83.0
- **48.0.0**：需 Python ≥ 3.9
- **49.0.0**：**移除 32-bit Windows wheels**、移除 x86_64 macOS wheels、ChaCha20 nonce 語意變更
- **50.0.0**：DSA 與 FFDH 全面 deprecated

45.x → 46.0.7 對 `PBKDF2HMAC` / `hashes` / `AESGCM` / `InvalidTag`
**無任何移除或簽章變更**（已查遍 46.0.0–46.0.7 changelog，46.0.1 以後皆為純資安修補）。
