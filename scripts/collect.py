#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI TOKEN CHECK - daily collector
- OpenRouter Datasets API (rankings-daily): daily token totals, top 50 models (backfill from 2025-01-01)
- OpenRouter Models API: current price per model (price history accumulates from first run)
- yfinance: KOSPI / Nikkei / Korea-Japan AI infra stocks
- Optional: Artificial Analysis API (AA_API_KEY secret)
Output: data/dashboard.json (+ raw stores)
"""
import os, re, json, time, math, traceback
import datetime as dt

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
OR_BASE = "https://openrouter.ai/api/v1"
OR_KEY = os.environ.get("OPENROUTER_API_KEY", "").strip()
AA_KEY = os.environ.get("AA_API_KEY", "").strip()
START = "2025-01-01"
HDRS = {"HTTP-Referer": "https://bluelagoon1222.github.io/AI-Token-Check/", "X-Title": "AI TOKEN CHECK"}
ERRORS = []

KST = dt.timezone(dt.timedelta(hours=9))

# ---------------------------------------------------------------- vendors
CHINA = {"deepseek", "qwen", "moonshotai", "z-ai", "thudm", "zhipuai", "minimax", "baidu", "bytedance",
         "bytedance-seed", "tencent", "stepfun-ai", "stepfun", "xiaomi", "meituan", "inclusionai",
         "alibaba", "01-ai", "kwaipilot", "baichuan", "iflytek", "sensetime", "ant-group", "openbmb"}
US = {"openai", "anthropic", "google", "meta-llama", "meta", "x-ai", "amazon", "microsoft", "nvidia",
      "perplexity", "ibm-granite", "arcee-ai", "nousresearch", "allenai", "liquid", "inception", "cognitivecomputations"}
MAJOR = {"openai", "anthropic", "google"}
VENDOR_NAME = {
    "openai": "OpenAI", "anthropic": "Anthropic", "google": "Google", "meta-llama": "Meta", "x-ai": "xAI",
    "deepseek": "DeepSeek", "qwen": "Qwen(알리바바)", "moonshotai": "Moonshot(키미)", "z-ai": "Z.ai(GLM)",
    "minimax": "MiniMax", "mistralai": "Mistral(프랑스)", "xiaomi": "샤오미", "bytedance-seed": "바이트댄스",
    "bytedance": "바이트댄스", "tencent": "텐센트", "baidu": "바이두", "stepfun-ai": "StepFun", "meituan": "메이퉁",
    "amazon": "Amazon", "microsoft": "Microsoft", "nvidia": "NVIDIA", "cohere": "Cohere(캐나다)",
    "openrouter": "OpenRouter(라우터)", "other": "기타(상위50 밖)",
}


def vendor(slug):
    return slug.split("/")[0].lower() if "/" in slug else slug.lower()


def region(v):
    if v in CHINA:
        return "CN"
    if v in US:
        return "US"
    return "ETC"


# ---------------------------------------------------------------- stocks (yfinance tickers)
STOCKS = [
    {"t": "^KS11", "name": "코스피", "c": "KR", "layer": "지수"},
    {"t": "^N225", "name": "닛케이225", "c": "JP", "layer": "지수"},
    {"t": "000660.KS", "name": "SK하이닉스", "c": "KR", "layer": "메모리"},
    {"t": "005930.KS", "name": "삼성전자", "c": "KR", "layer": "메모리"},
    {"t": "285A.T", "name": "키옥시아", "c": "JP", "layer": "메모리"},
    {"t": "042700.KS", "name": "한미반도체", "c": "KR", "layer": "장비·검사"},
    {"t": "6857.T", "name": "어드반테스트", "c": "JP", "layer": "장비·검사"},
    {"t": "8035.T", "name": "도쿄일렉트론", "c": "JP", "layer": "장비·검사"},
    {"t": "6146.T", "name": "디스코", "c": "JP", "layer": "장비·검사"},
    {"t": "007660.KS", "name": "이수페타시스", "c": "KR", "layer": "기판·부품"},
    {"t": "4062.T", "name": "이비덴", "c": "JP", "layer": "기판·부품"},
    {"t": "001440.KS", "name": "대한전선", "c": "KR", "layer": "광통신·전선"},
    {"t": "5803.T", "name": "후지쿠라", "c": "JP", "layer": "광통신·전선"},
    {"t": "5801.T", "name": "후루카와전기", "c": "JP", "layer": "광통신·전선"},
    {"t": "5802.T", "name": "스미토모전공", "c": "JP", "layer": "광통신·전선"},
    {"t": "267260.KS", "name": "HD현대일렉트릭", "c": "KR", "layer": "전력기기"},
    {"t": "010120.KS", "name": "LS ELECTRIC", "c": "KR", "layer": "전력기기"},
    {"t": "298040.KS", "name": "효성중공업", "c": "KR", "layer": "전력기기"},
    {"t": "9984.T", "name": "소프트뱅크그룹", "c": "JP", "layer": "데이터센터·투자"},
]


# ---------------------------------------------------------------- io helpers
def p(*a):
    print(*a, flush=True)


def load(name, default):
    path = os.path.join(DATA, name)
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return default


def save(name, obj):
    os.makedirs(DATA, exist_ok=True)
    with open(os.path.join(DATA, name), "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))


def err(where, e):
    msg = f"{where}: {type(e).__name__}: {e}"
    ERRORS.append(msg)
    p("[ERROR]", msg)
    traceback.print_exc()


def or_get(path, params=None, auth=True):
    h = dict(HDRS)
    if auth and OR_KEY:
        h["Authorization"] = f"Bearer {OR_KEY}"
    last = None
    for attempt in range(5):
        r = requests.get(OR_BASE + path, params=params, headers=h, timeout=90)
        if r.status_code == 429:
            time.sleep(15 * (attempt + 1))
            continue
        if r.status_code >= 500:
            last = r.status_code
            time.sleep(10)
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError(f"OpenRouter request failed ({path}, last status {last or 429})")


# ---------------------------------------------------------------- 1. rankings
def update_rankings():
    store = load("rankings_daily.json", {"days": {}, "as_of": None})
    days = store["days"]
    if not OR_KEY:
        ERRORS.append("OPENROUTER_API_KEY 미등록 — 토큰 데이터 수집 생략")
        return store
    end = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None).date() - dt.timedelta(days=1)
    floor = dt.date.fromisoformat(START)
    start = floor if not days else max(dt.date.fromisoformat(max(days)) - dt.timedelta(days=3), floor)
    cur = start
    while cur <= end:
        w_end = min(cur + dt.timedelta(days=29), end)
        js = or_get("/datasets/rankings-daily", {"start_date": cur.isoformat(), "end_date": w_end.isoformat()})
        fetched = {}
        for row in js.get("data", []):
            try:
                fetched.setdefault(row["date"], {})[row["model_permaslug"]] = int(row["total_tokens"])
            except Exception:
                continue
        days.update(fetched)
        store["as_of"] = (js.get("meta") or {}).get("as_of", store.get("as_of"))
        p(f"rankings {cur} ~ {w_end}: {len(fetched)} days")
        cur = w_end + dt.timedelta(days=1)
        time.sleep(2.5)
    store["days"] = days
    save("rankings_daily.json", store)
    return store


def aggregates(days):
    out = []
    for d in sorted(days):
        m = days[d]
        total = sum(m.values())
        other = m.get("other", 0)
        named = total - other
        cn = sum(v for s, v in m.items() if s != "other" and region(vendor(s)) == "CN")
        us = sum(v for s, v in m.items() if s != "other" and region(vendor(s)) == "US")
        out.append({"d": d, "total": total, "named": named, "cn": cn, "us": us,
                    "cn_share": cn / named if named else None,
                    "us_share": us / named if named else None,
                    "top50_share": named / total if total else None})
    return out


def avg(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


# ---------------------------------------------------------------- 2. models / prices
def fetch_models():
    js = or_get("/models", auth=bool(OR_KEY))
    out = {}
    for m in js.get("data", []):
        pr = m.get("pricing") or {}
        try:
            pin = float(pr.get("prompt", 0)) * 1e6
            pout = float(pr.get("completion", 0)) * 1e6
        except Exception:
            continue
        if pin < 0 or pout < 0:
            continue
        rec = {"id": m.get("id"), "name": m.get("name"), "created": m.get("created"),
               "in": round(pin, 4), "out": round(pout, 4)}
        for k in {m.get("id"), m.get("canonical_slug")}:
            if k:
                out[k] = rec
    return out


def price_for(slug, models):
    if slug.endswith(":free"):
        return None
    if slug in models:
        return models[slug]
    base = re.sub(r"-\d{4}-?\d{2}-?\d{2}$", "", slug)
    if base in models:
        return models[base]
    return models.get(slug.split(":")[0])


def blended(rec):
    # 3:1 input:output blended price (Artificial Analysis convention), USD per 1M tokens
    return (3 * rec["in"] + rec["out"]) / 4


# ---------------------------------------------------------------- 3. optional Artificial Analysis
def fetch_aa():
    if not AA_KEY:
        return None
    r = requests.get("https://artificialanalysis.ai/api/v2/data/llms/models",
                     headers={"x-api-key": AA_KEY}, timeout=60)
    r.raise_for_status()
    rows = []
    for m in r.json().get("data", []):
        ev = m.get("evaluations") or {}
        idx = ev.get("artificial_analysis_intelligence_index")
        if idx is None:
            continue
        cr = (m.get("model_creator") or {})
        rows.append({"name": m.get("name"), "creator": cr.get("name"), "creator_slug": (cr.get("slug") or "").lower(),
                     "index": idx, "price": (m.get("pricing") or {}).get("price_1m_blended_3_to_1")})
    rows.sort(key=lambda x: -x["index"])
    return rows[:20]


# ---------------------------------------------------------------- 4. stocks
def update_stocks():
    import yfinance as yf
    tick = [s["t"] for s in STOCKS]
    df = yf.download(tick, start=START, auto_adjust=True, progress=False, threads=True)
    close = df["Close"]
    out = []
    for s in STOCKS:
        if s["t"] not in close.columns:
            continue
        ser = close[s["t"]].dropna()
        if ser.empty:
            continue
        out.append({**s, "dates": [i.strftime("%Y-%m-%d") for i in ser.index],
                    "close": [round(float(v), 2) for v in ser.values]})
    save("stocks.json", out)
    return out


def ret_stats(rec):
    import pandas as pd
    ser = pd.Series(rec["close"], index=pd.to_datetime(rec["dates"]))
    last = ser.iloc[-1]

    def r(n):
        return round((last / ser.iloc[-1 - n] - 1) * 100, 2) if len(ser) > n else None
    ytd_base = ser[ser.index < pd.Timestamp(ser.index[-1].year, 1, 1)]
    ytd = round((last / ytd_base.iloc[-1] - 1) * 100, 2) if len(ytd_base) else None
    return {"t": rec["t"], "name": rec["name"], "c": rec["c"], "layer": rec["layer"],
            "last": round(float(last), 2), "date": rec["dates"][-1],
            "d1": r(1), "w1": r(5), "m1": r(21), "ytd": ytd}


# ---------------------------------------------------------------- 5. analysis
def correlation(agg, stocks):
    """Weekly lead-lag correlation: token metrics (lead 0~4 weeks) vs KOSPI / SK hynix weekly return."""
    import pandas as pd
    if len(agg) < 120:
        return None
    df = pd.DataFrame(agg).set_index("d")
    df.index = pd.to_datetime(df.index)
    w_tok = df["total"].resample("W-FRI").sum()
    feats = {
        "토큰 사용량 주간 증가율": w_tok.pct_change(),
        "토큰 사용량 증가율 가속(2차)": w_tok.pct_change().diff(),
        "중국 모델 점유율 주간 변화(%p)": df["cn_share"].resample("W-FRI").mean().diff() * 100,
    }
    targets = {}
    for s in stocks:
        if s["t"] in ("^KS11", "000660.KS", "^N225"):
            ser = pd.Series(s["close"], index=pd.to_datetime(s["dates"]))
            targets[s["name"]] = ser.resample("W-FRI").last().pct_change()
    res = []
    for fname, f in feats.items():
        f = f.iloc[:-1]  # drop incomplete week
        for tname, t in targets.items():
            row = {"feature": fname, "target": tname, "lags": []}
            for lag in range(0, 5):
                x = pd.concat([f.shift(lag), t], axis=1).dropna()
                x = x.replace([float("inf"), float("-inf")], float("nan")).dropna()
                if len(x) < 20:
                    row["lags"].append(None)
                    continue
                row["lags"].append(round(float(x.iloc[:, 0].corr(x.iloc[:, 1])), 3))
            row["n"] = int(len(pd.concat([f, t], axis=1).dropna()))
            res.append(row)
    return res


def event_study(events, stocks):
    import pandas as pd
    look = {s["t"]: pd.Series(s["close"], index=pd.to_datetime(s["dates"])) for s in stocks
            if s["t"] in ("^KS11", "000660.KS", "^N225")}
    out = []
    for e in events:
        row = dict(e)
        d = pd.Timestamp(e["date"])
        for t, key in (("^KS11", "kospi"), ("000660.KS", "hynix"), ("^N225", "nikkei")):
            ser = look.get(t)
            if ser is None:
                continue
            after = ser[ser.index >= d]
            before = ser[ser.index < d]
            if len(after) == 0 or len(before) == 0:
                continue
            base = before.iloc[-1]
            row[key + "_1d"] = round((after.iloc[0] / base - 1) * 100, 2)
            row[key + "_5d"] = round((after.iloc[min(4, len(after) - 1)] / base - 1) * 100, 2) if len(after) >= 5 else None
            row[key + "_20d"] = round((after.iloc[19] / base - 1) * 100, 2) if len(after) >= 20 else None
        out.append(row)
    return out


# ---------------------------------------------------------------- main
def main():
    now_kst = dt.datetime.now(KST)
    today = now_kst.date().isoformat()
    alerts = []

    # rankings
    try:
        rk = update_rankings()
    except Exception as e:
        err("rankings", e)
        rk = load("rankings_daily.json", {"days": {}, "as_of": None})
    days = rk.get("days", {})
    agg = aggregates(days)
    last_day = max(days) if days else None

    # models & prices
    models = {}
    try:
        models = fetch_models()
        p("models:", len(models))
    except Exception as e:
        err("models", e)

    top_models, vendors, price_moves, new_models = [], [], [], []
    ph = load("price_history.json", {})
    pidx = load("price_index.json", {})

    if last_day:
        latest = days[last_day]
        sorted_days = sorted(days)
        last7 = sorted_days[-7:]
        prev7 = sorted_days[-14:-7]
        named_total = sum(v for s, v in latest.items() if s != "other")
        # slug 7d change
        def s_avg(slug, ds):
            return avg([days[d].get(slug, 0) for d in ds]) if ds else None

        recent_slugs = set()
        for d in sorted_days[-30:]:
            recent_slugs |= {s for s in days[d] if s != "other"}

        # price snapshot for recent slugs
        if models:
            snap = {}
            for s in recent_slugs:
                rec = price_for(s, models)
                if rec:
                    snap[s] = [rec["in"], rec["out"]]
            if snap:
                ph[today] = snap
                keep = sorted(ph)[-400:]
                ph = {k: ph[k] for k in keep}
                save("price_history.json", ph)

        rank = 0
        for s, v in sorted(latest.items(), key=lambda kv: -kv[1]):
            if s == "other":
                continue
            rank += 1
            vv = vendor(s)
            a7, p7 = s_avg(s, last7), s_avg(s, prev7)
            rec = price_for(s, models) if models else None
            top_models.append({
                "rank": rank, "slug": s, "name": (rec or {}).get("name") or s, "vendor": VENDOR_NAME.get(vv, vv),
                "region": region(vv), "tokens": v, "share": v / named_total if named_total else None,
                "chg7": (a7 / p7 - 1) if (a7 and p7) else None,
                "in": rec["in"] if rec else None, "out": rec["out"] if rec else None,
                "blended": round(blended(rec), 4) if rec else None,
            })
            # new model detection
            if rec and rec.get("created"):
                age = (dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) - dt.datetime.fromtimestamp(rec["created"], dt.timezone.utc).replace(tzinfo=None)).days
                if age <= 21:
                    new_models.append({"slug": s, "name": rec.get("name"), "rank": rank, "age": age,
                                       "region": region(vv), "vendor": VENDOR_NAME.get(vv, vv)})

        # vendor shares
        def vshare(ds):
            acc, tot = {}, 0
            for d in ds:
                for s, v in days[d].items():
                    if s == "other":
                        continue
                    acc[vendor(s)] = acc.get(vendor(s), 0) + v
                    tot += v
            return {k: v / tot for k, v in acc.items()} if tot else {}
        v_now, v_prev = vshare(last7), vshare(prev7)
        for k, sh in sorted(v_now.items(), key=lambda kv: -kv[1])[:15]:
            vendors.append({"v": k, "name": VENDOR_NAME.get(k, k), "region": region(k),
                            "share": sh, "prev": v_prev.get(k), "chg": (sh - v_prev.get(k, 0)) * 100})

        # price index (token-weighted blended, today's prices x latest day tokens)
        num = den = 0.0
        cover = 0
        for m in top_models:
            if m["blended"] and m["blended"] > 0:
                num += m["tokens"] * m["blended"]
                den += m["tokens"]
                cover += m["tokens"]
        if den > 0 and models:
            pidx[today] = {"wavg": round(num / den, 4), "spend": round(num / 1e6, 0), "tok_date": last_day,
                           "coverage": round(cover / named_total, 3) if named_total else None}
            save("price_index.json", pidx)

        # price moves vs previous snapshot
        dates_ph = sorted(ph)
        if len(dates_ph) >= 2:
            cur_d, prev_d = dates_ph[-1], dates_ph[-2]
            rank_of = {m["slug"]: m["rank"] for m in top_models}
            for s, (pin, pout) in ph[cur_d].items():
                old = ph[prev_d].get(s)
                if not old:
                    continue
                nb, ob = (3 * pin + pout) / 4, (3 * old[0] + old[1]) / 4
                if ob <= 0:
                    continue
                ch = nb / ob - 1
                if abs(ch) >= 0.2:
                    vv = vendor(s)
                    price_moves.append({"slug": s, "vendor": VENDOR_NAME.get(vv, vv), "region": region(vv),
                                        "old": round(ob, 4), "new": round(nb, 4), "chg": round(ch * 100, 1),
                                        "rank": rank_of.get(s), "from": prev_d, "to": cur_d})

        # ---------------- alerts
        for pm in price_moves:
            vv = vendor(pm["slug"])
            if pm["chg"] <= -50 and (vv in MAJOR or (pm["rank"] or 99) <= 20):
                lvl = "red"
            elif pm["chg"] <= -20:
                lvl = "yellow"
            else:
                lvl = "info"
            title = f"{pm['vendor']} {pm['slug'].split('/')[-1]} 가격 {pm['chg']:+.1f}%"
            detail = (f"혼합단가 ${pm['old']} → ${pm['new']} /100만토큰 ({pm['from']}→{pm['to']}). "
                      + ("단가 급락 이벤트 — 과거 코스피 단기 급락과 동행한 유형" if pm["chg"] < 0
                         else "단가 인상 — 과거 코스피 상승 구간과 동행한 유형"))
            alerts.append({"level": lvl, "type": "가격", "title": title, "detail": detail, "label": "확정",
                           "kid": "price|" + pm["slug"] + "|" + pm["to"]})

        for nm in new_models:
            if nm["region"] == "CN" and nm["rank"] <= 10:
                lvl = "red"
            elif nm["region"] == "CN":
                lvl = "yellow"
            else:
                lvl = "info"
            alerts.append({"level": lvl, "type": "신모델",
                           "title": f"{nm['vendor']} 신모델 {nm['name']} 사용량 {nm['rank']}위 진입",
                           "detail": f"출시 {nm['age']}일 차에 상위 {nm['rank']}위. "
                                     + ("중국 고성능·저가 모델 확산 — 딥시크·키미 K3 유형 점검" if nm["region"] == "CN" else ""),
                           "label": "확정", "kid": "new|" + nm["slug"]})

        cn_now = avg([a["cn_share"] for a in agg[-7:]])
        cn_prev = avg([a["cn_share"] for a in agg[-14:-7]])
        if cn_now is not None and cn_prev is not None:
            dd = (cn_now - cn_prev) * 100
            if abs(dd) >= 2.5:
                alerts.append({"level": "red" if dd >= 5 else ("yellow" if dd > 0 else "info"), "type": "점유율",
                               "title": f"중국 모델 점유율 주간 {dd:+.1f}%p ({cn_prev*100:.1f}% → {cn_now*100:.1f}%)",
                               "detail": "상위 50개 모델 토큰 기준. 점유율 '수준'보다 급변이 신호.", "label": "확정",
                               "kid": "cn|" + today})

        wk = [a["total"] for a in agg[-28:]]
        if len(wk) == 28:
            w = [sum(wk[i:i + 7]) for i in range(0, 28, 7)]
            g = [w[i] / w[i - 1] - 1 for i in range(1, 4)]
            if g[-1] < 0 <= g[-2]:
                alerts.append({"level": "yellow", "type": "사용량", "title": f"토큰 사용량 주간 감소 전환 ({g[-1]*100:+.1f}%)",
                               "detail": "직전 주 증가 → 이번 주 감소. 기업 비용 축소 신호 여부 점검.", "label": "확정"})
            elif g[-1] >= 0.3:
                alerts.append({"level": "info", "type": "사용량", "title": f"토큰 사용량 주간 급증 ({g[-1]*100:+.1f}%)",
                               "detail": "사용량 가속 — 2026년 8월 반등기와 같은 유형.", "label": "확정"})

    # Artificial Analysis (optional)
    aa = None
    try:
        aa = fetch_aa()
        if aa:
            for i, m in enumerate(aa[:5]):
                if region(m["creator_slug"]) == "CN" or m["creator_slug"] in ("moonshot", "moonshotai", "alibaba", "zhipu", "kimi"):
                    alerts.append({"level": "red", "type": "성능", "title": f"중국 모델 {m['name']} 지능지수 {i+1}위({m['index']})",
                                   "detail": "프런티어 성능 격차 축소 이벤트 — 키미 K3(2026.7) 유형", "label": "확정",
                                   "kid": "aa|" + str(m["name"])})
    except Exception as e:
        err("artificial_analysis", e)

    # stocks
    stocks = load("stocks.json", [])
    try:
        stocks = update_stocks()
    except Exception as e:
        err("stocks", e)

    # events (manual history + detected red alerts appended to log)
    ev_manual = load("events_manual.json", [])
    ev_log = load("events_log.json", [])
    cutoff = (now_kst.date() - dt.timedelta(days=30)).isoformat()
    for a in alerts:
        if a["level"] == "red":
            kid = a.get("kid") or (today + "|" + a["title"])
            if not any(e.get("key") == kid and e.get("date", "") >= cutoff for e in ev_log):
                ev_log.append({"key": kid, "date": today, "title": a["title"], "kind": a["type"],
                               "direction": "-", "note": a["detail"], "source": "자동 감지"})
    save("events_log.json", ev_log)
    events = []
    try:
        events = event_study(ev_manual + ev_log, stocks)
    except Exception as e:
        err("event_study", e)
        events = ev_manual + ev_log

    corr = None
    try:
        corr = correlation(agg, stocks)
    except Exception as e:
        err("correlation", e)

    stats = []
    for s in stocks:
        try:
            stats.append(ret_stats(s))
        except Exception:
            pass

    # summary
    summary = []
    if agg:
        a1 = agg[-1]
        w_now = sum(a["total"] for a in agg[-7:])
        w_prev = sum(a["total"] for a in agg[-14:-7]) if len(agg) >= 14 else None
        summary.append(f"OpenRouter 전체 토큰 {last_day}: {a1['total']/1e12:.2f}조 토큰 (확정)")
        if w_prev:
            summary.append(f"최근 7일 토큰 합계 전주 대비 {(w_now/w_prev-1)*100:+.1f}% (확정)")
        if a1["cn_share"] is not None:
            summary.append(f"중국 모델 점유율 {a1['cn_share']*100:.1f}% / 미국 {a1['us_share']*100:.1f}% — 상위 50개 기준 (확정)")
        if top_models:
            t = top_models[0]
            summary.append(f"사용량 1위 {t['name']} ({t['vendor']}), 점유율 {t['share']*100:.1f}% (확정)")
    if pidx:
        k = sorted(pidx)[-1]
        summary.append(f"토큰가중 평균 혼합단가 ${pidx[k]['wavg']:.3f}/100만토큰, 일 지출 추정 ${pidx[k]['spend']:,.0f} (추정: 입력3:출력1 가정)")
    for st in stats:
        if st["t"] in ("^KS11", "000660.KS"):
            summary.append(f"{st['name']} {st['date']} 종가 {st['last']:,} ({st['d1']:+.2f}%, 1주 {st['w1']:+.2f}%) (확정)")
    if price_moves:
        summary.append(f"가격 변동(±20% 이상) {len(price_moves)}건 감지 (확정)")

    order = {"red": 3, "yellow": 2, "info": 1}
    alerts.sort(key=lambda a: -order[a["level"]])
    level = alerts[0]["level"] if alerts and alerts[0]["level"] in ("red", "yellow") else "green"

    dash = {
        "meta": {"updated_kst": now_kst.strftime("%Y-%m-%d %H:%M"), "rank_as_of": rk.get("as_of"),
                 "last_rank_date": last_day, "errors": ERRORS, "has_or_key": bool(OR_KEY), "has_aa": aa is not None},
        "alert": {"level": level, "items": alerts},
        "summary": summary,
        "tokens": {"dates": [a["d"] for a in agg], "total": [a["total"] for a in agg],
                   "cn_share": [round(a["cn_share"] * 100, 2) if a["cn_share"] is not None else None for a in agg],
                   "us_share": [round(a["us_share"] * 100, 2) if a["us_share"] is not None else None for a in agg],
                   "top50_share": [round(a["top50_share"] * 100, 2) if a["top50_share"] is not None else None for a in agg]},
        "vendors": vendors,
        "top_models": top_models[:30],
        "new_models": new_models,
        "price_index": {"dates": sorted(pidx), "wavg": [pidx[k]["wavg"] for k in sorted(pidx)],
                        "spend": [pidx[k]["spend"] for k in sorted(pidx)]},
        "price_moves": price_moves,
        "aa": aa,
        "stocks": stocks,
        "stock_stats": stats,
        "corr": corr,
        "events": events,
    }
    save("dashboard.json", dash)
    p("done. alerts:", len(alerts), "errors:", ERRORS)


if __name__ == "__main__":
    main()
