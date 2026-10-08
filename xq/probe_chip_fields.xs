// probe_chip_fields.xs - XQ filter (screener) script, field probe v1
// Chip Radar TW goal 3, step 1 (2026-10-08). NOT a trading signal.
//
// Purpose: one whole-market run tells which chip fields this subscription
// (chip analysis module) can read, whether they have data, how deep the
// history is, and whether the exported Excel carries the output columns.
//
// Owner rule exception (2026-10-08): only the GetField field names are
// Chinese, because XQ names its chip fields that way. Everything else ASCII.
//
// How to run: XS editor -> new script, type = filter (screener), paste,
// compile. Screener center -> custom strategy -> this script, frequency =
// daily, universe = all listed + OTC stocks -> run -> export to Excel.
// If compile or run fails on one field, report the error text and the line.

settotalbar(70);

var: i(0), streak(0), stopped(false), daysWithData(0);

// streak: consecutive trading days (from today back) with main-force net buy > 0
streak = 0;
stopped = false;
daysWithData = 0;
for i = 0 to 59 begin
    if GetField("主力買賣超張數", "D")[i] <> 0 then daysWithData = daysWithData + 1;
    if not stopped then begin
        if GetField("主力買賣超張數", "D")[i] > 0 then
            streak = streak + 1
        else
            stopped = true;
    end;
end;

// all stocks pass; this run only collects the columns below
ret = 1;

OutputField(1, GetField("主力買張", "D"), 0, "mf_buy_lots");
OutputField(2, GetField("主力賣張", "D"), 0, "mf_sell_lots");
OutputField(3, GetField("主力買賣超張數", "D"), 0, "mf_net_lots");
OutputField(4, streak, 0, "mf_net_buy_streak");
OutputField(5, daysWithData, 0, "mf_days_with_data_60");
OutputField(6, GetField("主力買賣超張數", "D")[59], 0, "mf_net_lots_d59");
OutputField(7, GetField("關鍵券商買賣超張數", "D"), 0, "key_broker_net");
OutputField(8, GetField("地緣券商買賣超張數", "D"), 0, "local_broker_net");
OutputField(9, GetField("官股券商買賣超張數", "D"), 0, "gov_broker_net");
OutputField(10, GetField("綜合前十大券商買賣超張數", "D"), 0, "top10_broker_net");
OutputField(11, GetField("買家數", "D"), 0, "buyer_count");
OutputField(12, GetField("賣家數", "D"), 0, "seller_count");
OutputField(13, GetField("分公司淨買超金額家數", "D"), 0, "net_buy_branch_count");
OutputField(14, GetField("籌碼鎖定率", "D"), 2, "chip_lock_rate");
OutputField(15, GetField("主力成本", "D"), 2, "mf_cost");
