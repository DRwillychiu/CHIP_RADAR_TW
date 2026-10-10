// cr_a_chips.xs - XQ filter (screener) script A: broker-branch chip snapshot
// Chip Radar TW goal 3 (2026-10-08). NOT a trading signal; every stock passes.
// Run once over all listed + OTC stocks, daily frequency, then export.
// Field names: official XSHelp lists?a=FCHIP / FVOLUME (checked 2026-10-08).
// Owner rule exception (2026-10-08): only the GetField field names are
// Chinese; everything else is ASCII.
// v3 (2026-10-08): uses only the constructs that already compiled and ran
// in probe_chip_fields.xs on the owner's XQ (single-line var, boolean +
// not, for, if/then/else, GetField(...)[i], 4-argument OutputField,
// ret = 1). No IsLastBar, no Close, no arrays, no variable named v (V may
// be the Volume shorthand).
//
// Columns (lots unless noted):
//  1 mf_buy  2 mf_sell  3 mf_net  4 mf_net_ratio (main-force net / volume)
//  5 mf_buy_streak  6 mf_sell_streak (consecutive days net > 0 / < 0, max 60)
//  7 mf_net_5d  8 mf_net_20d  9 mf_net_60d (sums)
// 10 top10_net  11 key_net  12 local_net  13 gov_net (broker groups)
// 14 buyer_cnt  15 seller_cnt  16 branch_cnt  17 net_buy_branch_cnt
// 18 seller_buyer_ratio (sellers / buyers)
// 19 lock_rate (%)  20 mf_cost
// 21 top10_net_5d  22 key_net_5d (sums)
// 23 volume (index-0 volume; xq_import.py compares it with the export's own
//    total-volume column to prove index 0 is the export's data date)
// close vs main-force cost is computed locally from the export price column.
// v4 (2026-10-08): the v3 run on the owner's XQ returned 0 stocks; the
// export header named columns 1-20 and left 21-24 as generic columns, so
// every stock stopped at the main-force average-buy-cost field (v3 column
// 21). That field and the main-force holding field (v3 column 22, never
// reached, unproven) are removed. Every field
// left already returned data on the owner's XQ (probe run, or a named
// column in the v3 export).
// v4.1 (2026-10-08): the B run at 20:39 returned 10/07 values under a
// 10/08 data date (all 1920 volumes equal the 10/07 total; foreign, trust,
// dealer and margin equal TWSE 10/07). Column 23 makes the same check
// possible for A.

var: i(0), volNow(0), mfX(0), stopB(false), stopS(false), streakB(0), streakS(0);
var: s5(0), s20(0), s60(0), t5(0), k5(0), nBuy(0), nSell(0), mfRatio(0), sbRatio(0);

SetBarFreq("D");
SetTotalBar(65);

streakB = 0;
streakS = 0;
stopB = false;
stopS = false;
s5 = 0;
s20 = 0;
s60 = 0;
t5 = 0;
k5 = 0;
for i = 0 to 59 begin
    mfX = GetField("主力買賣超張數", "D")[i];
    if i < 5 then s5 = s5 + mfX;
    if i < 20 then s20 = s20 + mfX;
    s60 = s60 + mfX;
    if not stopB then begin
        if mfX > 0 then streakB = streakB + 1 else stopB = true;
    end;
    if not stopS then begin
        if mfX < 0 then streakS = streakS + 1 else stopS = true;
    end;
end;
for i = 0 to 4 begin
    t5 = t5 + GetField("綜合前十大券商買賣超張數", "D")[i];
    k5 = k5 + GetField("關鍵券商買賣超張數", "D")[i];
end;
volNow = GetField("成交量", "D");
nBuy = GetField("買家數", "D");
nSell = GetField("賣家數", "D");
mfRatio = 0;
if volNow > 0 then mfRatio = GetField("主力買賣超張數", "D") / volNow;
sbRatio = 0;
if nBuy > 0 then sbRatio = nSell / nBuy;

ret = 1;

OutputField(1, GetField("主力買張", "D"), 0, "mf_buy");
OutputField(2, GetField("主力賣張", "D"), 0, "mf_sell");
OutputField(3, GetField("主力買賣超張數", "D"), 0, "mf_net");
OutputField(4, mfRatio, 4, "mf_net_ratio");
OutputField(5, streakB, 0, "mf_buy_streak");
OutputField(6, streakS, 0, "mf_sell_streak");
OutputField(7, s5, 0, "mf_net_5d");
OutputField(8, s20, 0, "mf_net_20d");
OutputField(9, s60, 0, "mf_net_60d");
OutputField(10, GetField("綜合前十大券商買賣超張數", "D"), 0, "top10_net");
OutputField(11, GetField("關鍵券商買賣超張數", "D"), 0, "key_net");
OutputField(12, GetField("地緣券商買賣超張數", "D"), 0, "local_net");
OutputField(13, GetField("官股券商買賣超張數", "D"), 0, "gov_net");
OutputField(14, nBuy, 0, "buyer_cnt");
OutputField(15, nSell, 0, "seller_cnt");
OutputField(16, GetField("分公司交易家數", "D"), 0, "branch_cnt");
OutputField(17, GetField("分公司淨買超金額家數", "D"), 0, "net_buy_branch_cnt");
OutputField(18, sbRatio, 2, "seller_buyer_ratio");
OutputField(19, GetField("籌碼鎖定率", "D"), 2, "lock_rate");
OutputField(20, GetField("主力成本", "D"), 2, "mf_cost");
OutputField(21, t5, 0, "top10_net_5d");
OutputField(22, k5, 0, "key_net_5d");
OutputField(23, volNow, 0, "volume");
