// cr_a_chips.xs - XQ filter (screener) script A: broker-branch chip snapshot
// Chip Radar TW goal 3 (2026-10-08). NOT a trading signal; every stock passes.
// Run once over all listed + OTC stocks, daily frequency, then export.
//
// Field names are the official XSHelp names (lists?a=FCHIP), checked
// 2026-10-08; fields 1-4, 9-14, 18-19 already ran in probe_chip_fields.xs.
// Owner rule exception (2026-10-08): only the GetField field names are
// Chinese; everything else is ASCII.
//
// Columns (lots unless noted):
//  1 mf_buy   2 mf_sell   3 mf_net   4 mf_net_ratio (main-force net / volume)
//  5 mf_buy_streak / 6 mf_sell_streak (consecutive days net > 0 / < 0, max 60)
//  7 mf_net_5d   8 mf_net_20d   9 mf_net_60d (sums)
// 10 top10_net  11 key_net  12 local_net  13 gov_net (broker groups)
// 14 buyer_cnt  15 seller_cnt  16 branch_cnt  17 net_buy_branch_cnt
// 18 seller_buyer_ratio (sellers / buyers; > 1 = few buyers took many sellers)
// 19 lock_rate (%)  20 mf_cost  21 mf_avg_buy_cost  22 mf_hold (estimated)
// 23 close_vs_mf_cost (close / main-force cost - 1)
// 24 top10_net_5d  25 key_net_5d (sums)

setbarfreq("D");
settotalbar(80);

var: i(0), v(0), stopB(false), stopS(false), streakB(0), streakS(0),
     s5(0), s20(0), s60(0), t5(0), k5(0), x(0), buyers(0), sellers(0), cost(0);

streakB = 0; streakS = 0; stopB = false; stopS = false;
s5 = 0; s20 = 0; s60 = 0; t5 = 0; k5 = 0;
for i = 0 to 59 begin
    x = GetField("主力買賣超張數", "D")[i];
    if i < 5 then s5 = s5 + x;
    if i < 20 then s20 = s20 + x;
    s60 = s60 + x;
    if not stopB then begin
        if x > 0 then streakB = streakB + 1 else stopB = true;
    end;
    if not stopS then begin
        if x < 0 then streakS = streakS + 1 else stopS = true;
    end;
end;
for i = 0 to 4 begin
    t5 = t5 + GetField("綜合前十大券商買賣超張數", "D")[i];
    k5 = k5 + GetField("關鍵券商買賣超張數", "D")[i];
end;

v = GetField("成交量", "D");
buyers = GetField("買家數", "D");
sellers = GetField("賣家數", "D");
cost = GetField("主力成本", "D");

ret = 1;

OutputField(1, GetField("主力買張", "D"), 0, "mf_buy");
OutputField(2, GetField("主力賣張", "D"), 0, "mf_sell");
OutputField(3, GetField("主力買賣超張數", "D"), 0, "mf_net");
if v > 0 then OutputField(4, GetField("主力買賣超張數", "D") / v, 4, "mf_net_ratio")
else OutputField(4, 0, 4, "mf_net_ratio");
OutputField(5, streakB, 0, "mf_buy_streak");
OutputField(6, streakS, 0, "mf_sell_streak");
OutputField(7, s5, 0, "mf_net_5d");
OutputField(8, s20, 0, "mf_net_20d");
OutputField(9, s60, 0, "mf_net_60d");
OutputField(10, GetField("綜合前十大券商買賣超張數", "D"), 0, "top10_net");
OutputField(11, GetField("關鍵券商買賣超張數", "D"), 0, "key_net");
OutputField(12, GetField("地緣券商買賣超張數", "D"), 0, "local_net");
OutputField(13, GetField("官股券商買賣超張數", "D"), 0, "gov_net");
OutputField(14, buyers, 0, "buyer_cnt");
OutputField(15, sellers, 0, "seller_cnt");
OutputField(16, GetField("分公司交易家數", "D"), 0, "branch_cnt");
OutputField(17, GetField("分公司淨買超金額家數", "D"), 0, "net_buy_branch_cnt");
if buyers > 0 then OutputField(18, sellers / buyers, 2, "seller_buyer_ratio")
else OutputField(18, 0, 2, "seller_buyer_ratio");
OutputField(19, GetField("籌碼鎖定率", "D"), 2, "lock_rate");
OutputField(20, cost, 2, "mf_cost");
OutputField(21, GetField("主力平均買超成本", "D"), 2, "mf_avg_buy_cost");
OutputField(22, GetField("主力持股", "D"), 0, "mf_hold");
if cost > 0 then OutputField(23, Close / cost - 1, 4, "close_vs_mf_cost")
else OutputField(23, 0, 4, "close_vs_mf_cost");
OutputField(24, t5, 0, "top10_net_5d");
OutputField(25, k5, 0, "key_net_5d");
