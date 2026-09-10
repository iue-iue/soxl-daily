
# ============================================================
# 毎日の判定 v7.5（取得時刻 / 実行帯ガード / 当日除外 / FP行
#                + 終値の二重確認 / 境界警告 / C2併記
#                + バー配分ガード / DV_alt併記 / 09:30バーのFP追加）
#   判定ロジックは v5 から変更なし
#   ★v7.3〈2026-09-02〉: 3b の第2ソースを stooq → yfinance日足 に差し替え。
#     stooqのCSVエンドポイントがJSチャレンジ化して取得不能になったため。
#     あわせて「形の検証」を必須にし、取れなかったときに★★で目立たせる。
#   ★v7.4〈2026-09-07〉: (1) サイズ上限を BASE_SIZE として先頭に定数化
#     （`03` Q35: 10% → 14%。2026-09-08の②の執行後、次のトレードから）
#     (2) 加速型の「余裕」を1行印字（`01` F39・表示のみ／判定は変えない）
#   ★v7.5〈2026-09-09〉: (1) BASE_SIZE = 14 を既定に（適用開始）
#     (2) 6b) 暦チェック（OPEX日 / FOMC発表日）を表示。判定・サイズ計算は不変
# ============================================================

# ############################################################
# ★ 1回のサイズ上限（%）。ここだけを書き換える。
#   〜2026-09-08（②見送り）… 10
#   ★2026-09-09 以降の実弾 … 14   （`03` Q35 / `04` §7 v5.21 / 早見表 v5.19）
#   ⚠️ 撤退トリガー: 実現DDが −8.70% に達したら 10 に戻す（`03` Q36・観察20トレード）
#   ⚠️ ⑤には適用しない（5%上限）。OPEX日の①系はカードの数字を手で半分にする（`03` Q50）
BASE_SIZE = 14
# ############################################################

# ===== GitHub Actions 用の差分（ここだけ Colab 版と違う。判定ロジックは同一） =====
#   (a) pip は requirements.txt で済ませる  (b) 出力先は out/  (c) 自動DLなし
#   (d) 実行窓ガード: 米国東部時間 09:00〜09:25 の外なら何もせず終了（cron を 13:08/14:08 UTC の2本置き、
#       夏時間・冬時間のどちらでも片方だけが窓に入る。遅延で窓を外れた回は出力しない）
import sys, pandas as _pd
_now_et = _pd.Timestamp.now(tz="America/New_York")
if not ((__import__("os").environ.get("GHA_FORCE", "") == "1") or
        (_now_et.weekday() < 5 and (9, 0) <= (_now_et.hour, _now_et.minute) < (9, 25))):
    print("実行窓の外（ET %s）のため終了。出力は更新しません。" % _now_et.strftime("%Y-%m-%d %H:%M"))
    sys.exit(0)
import yfinance as yf, pandas as pd, numpy as np, datetime, os

ET = "America/New_York"
JST = "Asia/Tokyo"
T0930, T1600 = datetime.time(9,30), datetime.time(16,0)

# ---------- 0) 取得時刻の記録と実行帯ガード（v6新設） ----------
now_et  = pd.Timestamp.now(tz=ET)
now_jst = now_et.tz_convert(JST)
RUN_JST = now_jst.strftime("%Y-%m-%d %H:%M JST")
RUN_ET  = now_et.strftime("%Y-%m-%d %H:%M ET")
in_rth  = (now_et.weekday() < 5) and (T0930 <= now_et.time() < T1600)
today_et = now_et.normalize().tz_localize(None)
print("="*60)
print("取得時刻 %s  /  %s" % (RUN_JST, RUN_ET))
if in_rth:
    print("!! 警告: 米国ザラ場中に実行しています（`04` §1の安全実行帯の外）")
    print("   当日の未完成バーが日足に混入しうる時間帯です。下の 2) で当日は自動除外しますが、")
    print("   日足ファイル（コードH-1/H-2）にこの保護はありません。ザラ場中に取り直さないこと。")
    print("   ※半日立会（13:00 ET引け）の当日を基準にしたい日は 16:00 ET 以降に回すこと")

# ---------- 1) 取得（30日・1時間足・プレ込み） ----------
frames = []
for sym in ["SOXL","SOXS"]:
    x = yf.Ticker(sym).history(period="30d", interval="1h", prepost=True,
                               auto_adjust=False, actions=False)
    x = x[["Open","High","Low","Close","Volume"]].copy()
    x["Ticker"] = sym
    frames.append(x)
raw = pd.concat(frames); raw.index.name = "Datetime"
df = raw.reset_index()
df["Datetime"] = pd.to_datetime(df["Datetime"], utc=True).dt.tz_convert(ET)
df["date"] = df["Datetime"].dt.normalize().dt.tz_localize(None)
df["t"] = df["Datetime"].dt.time

# ---------- 2) RTH日足の再構成（★v6: 未完成の当日は落とす） ----------
reg = df[(df["t"]>=T0930)&(df["t"]<T1600)]
def daily(tk):
    x = reg[reg["Ticker"]==tk].sort_values("Datetime"); g = x.groupby("date")
    o = pd.DataFrame(dict(O=g["Open"].first(), C=g["Close"].last(), H=g["High"].max(),
                          L=g["Low"].min(), V=g["Volume"].sum(), nb=g.size()))
    o["DV"] = x.assign(dv=x["Close"]*x["Volume"]).groupby("date")["dv"].sum()
    o = o[o["nb"]>=4]
    if in_rth and (today_et in o.index):
        o = o.drop(index=today_et)
        print("   -> %s: 未完成の当日 %s を日足から除外しました" % (tk, str(today_et.date())))
    return o
SL, SS = daily("SOXL"), daily("SOXS")

# ---------- 3) 併合ガード v4 ----------
common = SS.index.intersection(SL.index)
rS = SS.loc[common,"C"].pct_change(); rL = SL.loc[common,"C"].pct_change()
artifact = (rS.abs()>0.5) & ~((rL.abs()>0.15)&(np.sign(rL)!=np.sign(rS)))
jumps = list(common[artifact.fillna(False)])
try:
    sp = yf.Ticker("SOXS").splits
    if len(sp)>0:
        ix = pd.DatetimeIndex(sp.index)
        if ix.tz is not None: ix = ix.tz_localize(None)
        for dd in ix.normalize():
            if SS.index.min() <= dd <= SS.index.max() and dd not in jumps:
                jumps.append(dd)
                print("!! SOXS分割断層: %s → またぐ代金比較を無効化" % str(dd.date()))
except Exception as e:
    print("(注意) 分割履歴を取得できず: %s" % str(e))
vj = SS["V"].pct_change().abs() > 1.5
for dd in SS.index[vj.fillna(False)]:
    if dd not in jumps:
        jumps.append(dd); print("!! SOXS出来高断層の疑い: %s" % str(dd.date()))
def straddle(d1,d2):
    return any([(d1 < z <= d2) for z in jumps])

# ---------- 3b) 終値の二重確認（★v7.3改訂・`01` F36(1)） ----------
# 【2026-09-02の変更】stooqのCSVエンドポイントがJSチャレンジ（bot防御）に変わり取得不能。
#   pd.read_csv はHTMLエラーページを「成功」で返すため、例外ベースのガードでは検知できず
#   11ファイル連続で SRC2_CLOSE が空のまま沈黙していた。
#   → (1) 第2ソースを yfinance の日足に差し替え
#      (2) 「形の検証」を必須にする（例外を待たない）
#      (3) 取れなかったら★★で目立たせる
#   ※同一ベンダー・別エンドポイントなので、F36(1)の「ソース間0.1%乖離」までは捕まえられない。
#     捕まえられるのは (a)時間足からの日足再構成のミス (b)調整断層 (c)片方だけの改訂
#     (d)★クロージングオークション（再構成=15:30バー終値 / 公式=16:00バー始値）。
SRC2 = None
try:
    bd = SL.index[-1]
    y2 = yf.download("SOXL",
                     start=(bd - pd.Timedelta(days=12)).strftime("%Y-%m-%d"),
                     interval="1d", auto_adjust=False, actions=False, progress=False)
    if isinstance(y2.columns, pd.MultiIndex):
        y2.columns = y2.columns.get_level_values(0)
    ix2 = pd.to_datetime(y2.index)
    try:
        ix2 = ix2.tz_localize(None)
    except TypeError:
        pass
    y2.index = ix2.normalize()

    # ★形の検証（例外を待たない）
    assert "Close" in y2.columns, "日足に Close 列なし（列=%s）" % list(y2.columns)[:6]
    assert len(y2) >= 3, "日足の行数が %d 本しかない" % len(y2)

    if bd in y2.index:
        v = y2.loc[bd, "Close"]
        v = float(v.iloc[0]) if hasattr(v, "iloc") else float(v)
        if pd.isna(v):
            print("!! 突合できず: yf日足の %s の終値が NaN" % str(bd.date()))
        else:
            SRC2 = v
            gap = (SRC2/SL["C"].iloc[-1] - 1)*100
            print("終値突合  再構成 %.4f / yf日足 %.4f   乖離 %+.4f%%" % (SL["C"].iloc[-1], SRC2, gap))
            if abs(gap) > 0.05:
                print("   !! 0.05%%超の乖離（`01` F36(1)）。")
                print("      引け位置・CC2が境界付近なら、判定が反転しうる。両方の値を運用ログに残すこと")
    else:
        print("!! 突合できず: yf日足に基準日 %s の行なし（時差・未反映）" % str(bd.date()))
except Exception as e:
    print("!! 突合できず（第2ソース不通）: %s" % repr(e))

if SRC2 is None:
    print("   ★★ SRC2_CLOSE が空になります。F36(1)の境界警告は片翼のみで稼働中。")
    print("      引け位置が0.33±0.05 / CC2が−4%±0.5 に入る日は、手で日足を確認すること")

# ---------- 3c) バー配分ガード（★v7.2新設・2026-08-17 実測） ----------
# 実測（`04` §12 2026-08-17）: SOXL 8/14 の 09:30バーが V=0 / 10:30バーが 25,060,585。
# 8分後の再取得で 18,398,363 / 6,662,222 に分かれ、**2本計も日合計も完全に一致**した。
#   → これは「欠損」ではなく **09:30バーの出来高が次のバーに繰り入れられた配分ズレ**。
#   → 日合計Vは保存される。**V基準の②③は無傷**。
#   → DV は Σ(バー終値×バー出来高) なので配分で変わる。同一Vで **+0.65%** ずれた実測あり。
#      ②はDV基準なので、金曜のSOXSで同じことが起きると境界近傍で判定が反転しうる。
ZEROV = 0
for tk_, dd_ in [("SOXL", SL), ("SOXS", SS)]:
    zz = reg[(reg["Ticker"]==tk_) & (reg["Volume"]<=0) & (reg["date"].isin(dd_.index))]
    for _, r_ in zz.iterrows():
        ZEROV += 1
        print("!! バー配分ズレの疑い: %s %s のRTHバー %s が出来高0"
              % (tk_, str(r_["date"].date()), r_["Datetime"].strftime("%H:%M")))
if ZEROV > 0:
    print("   → 日合計Vは保存される型（2026-08-17実測）。**V基準の②③は安全**。")
    print("      ただし **DVは不正確になりうる**。下の DV_alt と符号が割れていないか必ず確認すること")
    print("      判定を変えるのではなく、割れたら `03` Q14 と `04` §12 に記録する")
else:
    print("バー配分ガード: RTHに出来高0のバーなし")

# ---------- 3d) DV_alt（配分に依存しない代金の近似・★v7.2・判定には使わない） ----------
# DV_alt = 日合計V × 日終値。バー配分ズレの影響を受けない。
# ★★ 判定は従来どおり DV（②）と V（③）で行う。DV_alt は記録専用（`03` Q14の材料）。
SL_DVA = SL["V"] * SL["C"]
SS_DVA = SS["V"] * SS["C"]

# ---------- 4) 判定カード ----------
pC, pC2, pC3 = SL["C"].iloc[-1], SL["C"].iloc[-2], SL["C"].iloc[-3]
CC  = (pC/pC2-1)*100
CC2 = (pC/pC3-1)*100
pos = (pC-SL["L"].iloc[-1])/(SL["H"].iloc[-1]-SL["L"].iloc[-1])
sig1 = (CC2<=-4) and (CC<=0)
lowc, highc = pos<1.0/3, pos>2.0/3
rets = SL["C"].pct_change()*100
sd20 = float(rets.tail(20).std())
volc = min(1.0, 5.5/sd20)
if rets.notna().sum() < 20:
    print("!! 警告: 日次リターン%d本（20本未満）。SDは日足で要確認" % rets.notna().sum())

# ①ランのN日目（Q11用）: 過去に遡って連続日数を数える
CCs = SL["C"].pct_change()*100; CC2s = SL["C"].pct_change(2)*100
sigs = ((CC2s<=-4)&(CCs<=0)).fillna(False).values
runN = 0
for v in sigs[::-1]:
    if v: runN += 1
    else: break

base = SL.index[-1]
nb_base = int(SL["nb"].iloc[-1])
print("="*60)
print("基準セッション %s（RTH %d本）  SOXL終値 %.2f" % (str(base.date()), nb_base, pC))
if nb_base < 7:
    print("!! 基準セッションのバーが7本未満です。未完成の日を掴んでいないか確認すること")
print("CC %+.2f%%  CC2 %+.2f%%  引け位置 %.3f" % (CC, CC2, pos))
print("[A]安値引け %s  [B]①条件 %s  高値引け %s" % (lowc, sig1, highc))
if sig1:
    print("①ラン %d日目 %s" % (runN, "← ★4日目以降: Q11ペーパー対象（セル係数1.0案を記録）" if runN>=4 else ""))
print("20日SD %.2f%%  ボラ係数 %.2f %s" % (sd20, volc, "【暴風圏】" if sd20>=9 else ""))
# ★v7: 引け位置の境界警告（`01` F36(1)）
if abs(pos - 1.0/3) <= 0.05:
    print("   !! 引け位置 %.3f はA判定の境界（0.333±0.05）です。" % pos)
    print("      ソース差0.1%%で反転しうる帯。両ソースの値を運用ログに残し、迷ったら小さく（A単独扱い）")
# ★v7.2: CC・CC2・SOXSの閾値近傍もその場で警告する（`04` §5の二重確認リストの自動化）
if abs(CC) <= 0.5:
    print("   !! CC %+.3f%% は 0 の±0.5%%以内（`04` §5）。取得時刻で0.08pt動いた実測あり（8/17）" % CC)
if abs(CC2 + 4.0) <= 0.5:
    print("   !! CC2 %+.3f%% は −4%% の±0.5%%以内（`04` §5）。日足の公式終値で二重確認すること" % CC2)
# ★v7: C2符号＝下げの組成（`03` Q26・ペーパー記録のみ。判定には使わない）
try:
    oc_t  = SL["C"].iloc[-1]/SL["O"].iloc[-1] - 1
    oc_t1 = SL["C"].iloc[-2]/SL["O"].iloc[-2] - 1
    on_t  = SL["O"].iloc[-1]/SL["C"].iloc[-2] - 1
    on_t1 = SL["O"].iloc[-2]/SL["C"].iloc[-3] - 1
    C2 = int((oc_t + oc_t1) < (on_t + on_t1))
    print("(Q26ログ用) C2=%d ← 直近2日 日中計 %+.2f%% / 夜間計 %+.2f%%  ※判定には使わない"
          % (C2, (oc_t+oc_t1)*100, (on_t+on_t1)*100))
except Exception:
    C2 = -1
prevON = (SL["O"].iloc[-1]/SL["C"].iloc[-2]-1)*100
print("(Q12ログ用) 前夜の夜間リターン: %+.2f%%" % prevON)

# ★v7.2: 基準日の09:30バー（＝寄り値・当日高値の素）を明示する（`03` Q19-2）
b930 = reg[(reg["Ticker"]=="SOXL") & (reg["date"]==base) & (reg["t"]==T0930)]
if len(b930) > 0:
    O930 = float(b930["Open"].iloc[0]); H930 = float(b930["High"].iloc[0]); V930 = float(b930["Volume"].iloc[0])
    print("(Q19-2ログ用) 基準日の09:30バー: 始値 %.4f / 高値 %.4f / 出来高 %.0f" % (O930, H930, V930))
    print("   ※ 09:30バーの始値・高値は取得ごとに2値を往復した実測あり（8/10 142.80↔141.15・高値143.45↔142.67）。")
    print("      A/B/②/③の判定には使わないが、ONと朝のギャップ別サイズ・持ち越しパネルは動く（7/22はONで2.21pt）")
else:
    O930 = H930 = V930 = float("nan")
    print("(Q19-2ログ用) 基準日の09:30バーが取得できません（半日立会・欠損の可能性）")

sig2 = False
if base.weekday()==4 and len(SS)>=2 and base in SS.index:
    j = list(SS.index).index(base)
    if j>=1 and not straddle(SS.index[j-1], base):
        sig2 = SS["DV"].iloc[j] > SS["DV"].iloc[j-1]
        d2dv  = (SS["DV"].iloc[j]/SS["DV"].iloc[j-1]-1)*100
        d2dva = (SS_DVA.iloc[j]/SS_DVA.iloc[j-1]-1)*100
        print("② SOXS売買代金 %+.2f%% → %s" % (d2dv, "発動" if sig2 else "不発"))
        print("   (参考・判定外) DV_alt %+.2f%%  ※日合計V×終値。配分ズレに強い近似（`03` Q14）" % d2dva)
        if (d2dv > 0) != (d2dva > 0):
            print("   !! ②が DV と DV_alt で割れています → `03` Q14 の記録対象")
            print("      **DV基準を正として続行**（ルールは変えない）。割れた事実だけを `04` §12 に残す")
sCC = (SS["C"].iloc[-1]/SS["C"].iloc[-2]-1)*100
dV  = (SS["V"].iloc[-1]/SS["V"].iloc[-2]-1)*100
dDV = (SS["DV"].iloc[-1]/SS["DV"].iloc[-2]-1)*100
dDVA = (SS_DVA.iloc[-1]/SS_DVA.iloc[-2]-1)*100
sig3 = (sCC<=-5) and (SS["V"].iloc[-1]<SS["V"].iloc[-2]) and not straddle(SS.index[-2],SS.index[-1])
print("③ SOXS当日 %+.2f%% / V %+.1f%% / 代金 %+.1f%% → V基準で%s" % (sCC, dV, dDV, "発動" if sig3 else "不発"))
print("   (参考・判定外) DV_alt %+.1f%%  ※Vが正ならDV_altも正（③のV脚は配分ズレに無関係）" % dDVA)
if abs(sCC + 5.0) <= 0.5:
    print("   !! SOXS %+.3f%% は −5%% の±0.5%%以内（`04` §5）。日足の公式終値で二重確認すること" % sCC)
if (sCC<=-5) and ((dV<0) != (dDV<0)):
    print("   !! ③がV/DVで割れています → Q14の記録対象（V基準を正として続行）")

# ---------- 5) 当日プレ ----------
nx = df[(df["Ticker"]=="SOXL")&(df["date"]>base)&(df["t"]<T0930)].sort_values("Datetime")
P5=P7=P9=latest=None
for _,b in nx.iterrows():
    if b["t"]==datetime.time(4,0): P5=float(b["Close"])
    if b["t"]==datetime.time(6,0): P7=float(b["Close"])
    if b["t"]==datetime.time(8,0): P9=float(b["Close"])
    latest=float(b["Close"])
if latest is not None:
    print("プレ最新 %.2f  ギャップ推定 %+.2f%%" % (latest, (latest/pC-1)*100))
    if sd20>=9:
        print("   !! 暴風圏: 22時読みでも±3pt級のズレ実測あり。②の+3%判定は境界±3ptで見送り側へ（F13追記）")
if P5 and P7 and P9:
    early, late = P7/P5-1, P9/P7-1
    acc = (late>early) and (P9>pC)
    print("加速型P9版: early %+.2f%% late %+.2f%% → %s" % (early*100, late*100, "★加速型（サイズ半分）" if acc else "非加速型"))
    margin = (late-early)*100
    print("   余裕 %+.3f pt %s" % (margin, "★★ 系統差・当日読みで反転しうる（`01` F39）" if abs(margin)<0.5 else ""))
else:
    print("加速型判定: P7/P9未取得（22:00 JST以降に再実行）")

# ---------- 6) 注文カード（v5.5） ----------
print("="*60)
cell = 1.0 if (sig1 and lowc) else (0.5 if (sig1 or lowc) else 0.0)
if sig1 or lowc:
    nm = "A+B（通常）" if (sig1 and lowc) else ("B単独（半分）" if sig1 else "A単独（半分）")
    print("シグナル: %s   サイズ %d%% x %.1f x %.2f = 資金の %.2f%%（加速型なら更に半分）" % (nm, BASE_SIZE, cell, volc, BASE_SIZE*cell*volc))
    print("[モードA 昼]  SOXL 指値 %.2f（-5%% 主案）/ 副案 %.2f（-3%%）" % (pC*0.95, pC*0.97))
    print("              ※通常セッション限定・当日限り。★発注前にプレ最新値を確認: プレが指値より下なら昼モード不成立（見送るか22時へ）")
    print("[モードB/C]   寄り成行（22:00にP9で加速型判定後）。指値のみの口座は直前値x1.10以上・通常限定")
elif sig2:
    print("シグナル: ②のみ   サイズ %d%% x 1.0 x %.2f = 資金の %.2f%%" % (BASE_SIZE, volc, BASE_SIZE*volc))
    print("[モードA 昼]  SOXL 指値 %.2f（+3%%）※!! 通常セッション限定（プレ通し厳禁）" % (pC*1.03))
    print("[モードB/C]   ギャップ推定+3%超なら見送り（境界±3ptは見送り側へ）。それ以外は寄り成行")
elif sig3:
    print("シグナル: ③  SOXS 指値 %.2f（±0%%）※通常セッション限定   サイズ %d%% x 1.0 x %.2f = 資金の %.2f%%" % (SS["C"].iloc[-1], BASE_SIZE, volc, BASE_SIZE*volc))
else:
    print("シグナルなし → 見送り（待機は損ではない）。**指値も置かない**")
print("!! 出口（引け5:00 JST or 翌朝6-7時アフター売り）に動けない日は発注しない")

# ---------- 6b) ★v7.5 暦チェック（表示のみ・判定は変えない）: FOMC前夜 / OPEX日 ----------
#   `01` F45（FOMC前夜 +1.01%・⑤はFOMC週でも執行）／F46・F49（OPEX日の昼は負・①はサイズ半分＝`03` Q50）
#   `_FOMC_DECISION` は声明発表日（会合2日目）。年が変わったらFedの公表日程で追記する。
try:
    _FOMC_DECISION = ["2026-09-16", "2026-10-28", "2026-12-09"]
    _nxt = base + pd.Timedelta(days=1)
    while _nxt.weekday() >= 5:
        _nxt += pd.Timedelta(days=1)
    _nd = pd.Timestamp(_nxt.date())
    _tf = pd.Timestamp(year=_nd.year, month=_nd.month, day=15)
    while _tf.weekday() != 4:
        _tf += pd.Timedelta(days=1)
    _is_opex = (_nd == _tf)
    _is_fomc = str(_nd.date()) in _FOMC_DECISION
    print("")
    print("[暦] 判定対象日 %s  OPEX日=%s  FOMC発表日=%s   ※第3金曜が休場の月は木曜が満期（手で確認）／FOMCは年1回リストを追記" %
          (str(_nd.date()), "★YES" if _is_opex else "no", "★YES" if _is_fomc else "no"))
    if _is_opex:
        print("  ★ OPEX日: 非シグナル日ならSOXSのペーパー記録（⑦・`03` Q49）。①系が立っているなら上のサイズを手で半分に（`03` Q50・暫定）")
    if _is_fomc:
        print("  ★ 今夜はFOMC前夜（%s引け → %s寄り）: ⑤はFOMC週でも見送らない（`01` F45・`03` Q47）。火曜上昇なら⑥のペーパー記録（`03` Q48）。窓内のCPI・雇用統計だけが除外" %
              (str(base.date()), str(_nd.date())))
except Exception as _e:
    print("[暦] チェック失敗（判定には影響なし）: %s" % str(_e))

# ---------- 7) 保存（★v6: 取得時刻と基準セッションを列で同梱） ----------
os.makedirs("out", exist_ok=True)
OUT = "out/today_check.csv"
out = df[["Datetime","Ticker","Open","High","Low","Close","Volume"]].copy()
out["RUN_JST"] = RUN_JST
out["RUN_ET"] = RUN_ET
out["BASE_SESSION"] = str(base.date())
# ★v7.1: 次セッションのAIが「このCSVだけで」文脈を復元できるように判定結果を同梱する。
#   （コンソールのFP行は人が別途コピーしない限り失われる＝新チャットに届かない）
out["POS"] = round(float(pos), 4)          # 引け位置（A判定の素）
out["CC2"] = round(float(CC2), 4)          # 2日累計（B判定の素）
out["SD20"] = round(float(sd20), 3)        # 20日SD（暴風圏＝9%以上）
out["SIG"] = ("A" if lowc else "") + ("B" if sig1 else "") + \
             ("2" if sig2 else "") + ("3" if sig3 else "") or "none"
out["C2"] = C2                             # 下げの組成（`03` Q26・記録のみ）
out["SRC2_CLOSE"] = SRC2 if SRC2 is not None else ""   # 突合先の終値（`01` F36(1)）
out["ZEROV"] = ZEROV                       # ★v7.2: RTHの出来高0バー本数（配分ズレの検出）
out.to_csv(OUT, index=False, encoding="utf-8-sig")
if os.path.exists(OUT) and os.path.getsize(OUT)>0:
    print("保存OK: %s (%d行)  取得時刻列つき" % (OUT, len(out)))
    # GitHub Actions では自動DLなし（ワークフローがコミットする）

# ---------- 8) 判定フィンガープリント（★v6新設・`03` Q19 / `04` §12） ----------
# この1行をコピーして運用ログに貼る。同じ日に2回回して比較するときはコードJへ。
FP = "|".join([
    "RUN=" + RUN_JST,
    "BASE=" + str(base.date()),
    "NB=%d" % nb_base,
    "LO=%.4f" % SL["O"].iloc[-1], "LH=%.4f" % SL["H"].iloc[-1],
    "LL=%.4f" % SL["L"].iloc[-1], "LC=%.4f" % pC,
    "CC=%.4f" % CC, "CC2=%.4f" % CC2, "POS=%.4f" % pos,
    "A=%d" % int(lowc), "B=%d" % int(sig1), "S2=%d" % int(sig2), "S3=%d" % int(sig3),
    "SC=%.4f" % sCC,
    "SV=%.0f" % SS["V"].iloc[-1], "SV1=%.0f" % SS["V"].iloc[-2],
    "SDV=%.0f" % SS["DV"].iloc[-1], "SDV1=%.0f" % SS["DV"].iloc[-2],
    "SDVA=%.0f" % SS_DVA.iloc[-1], "SDVA1=%.0f" % SS_DVA.iloc[-2],
    "SD20=%.4f" % sd20, "VOLC=%.4f" % volc, "RUNN=%d" % runN,
    "C2=%d" % C2, "SRC2=%s" % ("%.4f" % SRC2 if SRC2 is not None else "NA"),
    "O930=%.4f" % O930, "H930=%.4f" % H930, "V930=%.0f" % V930,
    "LV=%.0f" % SL["V"].iloc[-1], "ZEROV=%d" % ZEROV,
])
print("")
print("FP " + FP)
