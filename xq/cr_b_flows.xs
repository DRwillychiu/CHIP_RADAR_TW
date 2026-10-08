// cr_b_flows.xs - XQ filter (screener) script B: institutions, credit,
// day trading and size. Chip Radar TW goal 3 (2026-10-08). NOT a trading
// signal; every stock passes. Run once over all listed + OTC stocks, daily
// frequency, then export.
//
// Field names are the official XSHelp names (lists?a=FCHIP / FVOLUME /
// FBASIC), checked 2026-10-08; none of them ran before -> if compile or run
// fails, report the error text and the line number.
// Owner rule exception (2026-10-08): only the GetField field names are Chinese.
//
// Columns (lots unless noted):
//  1 foreign_net  2 trust_net  3 dealer_net  4 inst_net
//  5 foreign_buy_streak  6 trust_buy_streak (consecutive days net > 0, max 60)
//  7 foreign_net_5d  8 trust_net_5d
//  9 margin_bal  10 margin_chg  11 short_bal  12 short_chg  13 sbl_sell
// 14 daytrade_lots (cash day trade)  15 daytrade_ratio (/ volume)
// 16 turnover_e (100m NTD)  17 mcap_e (100m NTD)  18 shares_lots
// 19 volume  20 vol_ratio_5 (volume / mean of the previous 5 days)
// 21 foreign_ratio (foreign net / volume)  22 trust_ratio (trust net / volume)

setbarfreq("D");
settotalbar(80);

var: i(0), v(0), avg5(0), stopF(false), stopT(false), streakF(0), streakT(0),
     f5(0), t5(0), x(0), y(0);

streakF = 0; streakT = 0; stopF = false; stopT = false; f5 = 0; t5 = 0;
for i = 0 to 59 begin
    x = GetField("外資買賣超", "D")[i];
    y = GetField("投信買賣超", "D")[i];
    if i < 5 then begin
        f5 = f5 + x;
        t5 = t5 + y;
    end;
    if not stopF then begin
        if x > 0 then streakF = streakF + 1 else stopF = true;
    end;
    if not stopT then begin
        if y > 0 then streakT = streakT + 1 else stopT = true;
    end;
end;
avg5 = 0;
for i = 1 to 5 begin
    avg5 = avg5 + GetField("成交量", "D")[i];
end;
avg5 = avg5 / 5;
v = GetField("成交量", "D");

ret = 1;

OutputField(1, GetField("外資買賣超", "D"), 0, "foreign_net");
OutputField(2, GetField("投信買賣超", "D"), 0, "trust_net");
OutputField(3, GetField("自營商買賣超", "D"), 0, "dealer_net");
OutputField(4, GetField("法人買賣超張數", "D"), 0, "inst_net");
OutputField(5, streakF, 0, "foreign_buy_streak");
OutputField(6, streakT, 0, "trust_buy_streak");
OutputField(7, f5, 0, "foreign_net_5d");
OutputField(8, t5, 0, "trust_net_5d");
OutputField(9, GetField("融資餘額張數", "D"), 0, "margin_bal");
OutputField(10, GetField("融資增減張數", "D"), 0, "margin_chg");
OutputField(11, GetField("融券餘額張數", "D"), 0, "short_bal");
OutputField(12, GetField("融券增減張數", "D"), 0, "short_chg");
OutputField(13, GetField("借券賣出張數", "D"), 0, "sbl_sell");
OutputField(14, GetField("現股當沖張數", "D"), 0, "daytrade_lots");
if v > 0 then OutputField(15, GetField("現股當沖張數", "D") / v, 4, "daytrade_ratio")
else OutputField(15, 0, 4, "daytrade_ratio");
OutputField(16, GetField("成交金額(億)", "D"), 2, "turnover_e");
OutputField(17, GetField("總市值(億)", "D"), 2, "mcap_e");
OutputField(18, GetField("發行張數(張)", "D"), 0, "shares_lots");
OutputField(19, v, 0, "volume");
if avg5 > 0 then OutputField(20, v / avg5, 2, "vol_ratio_5")
else OutputField(20, 0, 2, "vol_ratio_5");
if v > 0 then OutputField(21, GetField("外資買賣超", "D") / v, 4, "foreign_ratio")
else OutputField(21, 0, 4, "foreign_ratio");
if v > 0 then OutputField(22, GetField("投信買賣超", "D") / v, 4, "trust_ratio")
else OutputField(22, 0, 4, "trust_ratio");
