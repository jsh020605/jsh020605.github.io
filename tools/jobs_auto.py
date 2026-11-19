#!/usr/bin/env python3
"""물리치료사 채용 공고 자동 수집 → cal/jobs.json (GitHub Actions가 매일 실행).

- 굿잡피티(goodjobpt.com) 목록, 메디잡(medijob.cc) 목록을 읽는다. 로그인·개인정보 없음(공개 공고만).
- 고르는 기준: 서울·인천·경기 서남부, 병원급(의원·한의원·요양병원·요양원·복지관·센터 제외), 아직 모집 중.
- 전에 있던 공고(사람인 등 손으로 넣은 것 포함)는 마감일이 지나기 전까지 그대로 둔다.
  '채용시마감' 공고는 목록에서 사라지고 30일이 지나면 뺀다.
- 한 사이트가 막혀도 다른 사이트 결과와 전 목록은 그대로 저장한다.
사용: python3 tools/jobs_auto.py  (저장소 맨 위에서)
"""
import datetime, html, http.cookiejar, json, os, re, sys, time, urllib.parse, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "cal", "jobs.json")
KST = datetime.timezone(datetime.timedelta(hours=9))
NOW = datetime.datetime.now(KST)
TODAY = NOW.date()
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"

GYEONGGI_OK = ["부천", "김포", "시흥", "안산", "광명", "수원", "안양", "고양", "부평"]   # 경기는 이 도시만
SKIP_NAME = ["의원", "한의원", "요양병원", "요양원", "복지관", "센터", "복지재단", "주간보호", "어린이집", "학교"]
SKIP_NAME_EXCEPT = ["병원"]   # 이름에 '병원'이 있으면 '센터' 같은 단어가 있어도 통과 (단 요양병원은 뺌)


def fetch(opener, url, data=None, headers=None, tries=2):
    last = None
    for _ in range(tries):
        try:
            req = urllib.request.Request(url, data=data, headers={"User-Agent": UA, **(headers or {})})
            with opener.open(req, timeout=40) as r:
                return r.read().decode("utf-8", "ignore")
        except Exception as e:  # noqa: BLE001
            last = e; time.sleep(3)
    raise last


def clean(t):
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", t or ""))).strip()


def region_ok(reg):
    reg = reg.replace(">", " ")
    if reg.startswith("서울") or reg.startswith("인천"):
        return True
    return any(c in reg for c in GYEONGGI_OK)


def name_ok(name):
    # 병원급만: 이름에 '병원'이 있어야 하고, 요양병원·한방병원은 뺀다 (대학교 이름은 통과)
    if "요양" in name or "한방" in name:
        return False
    if "대학" in name:
        return True
    return "병원" in name


def short(t, n=22):
    t = re.sub(r"[★☆◆◇■□●○▶▷♥♡※【】\[\]<>「」『』]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t if len(t) <= n else t[:n].rstrip() + "…"


def kind_of(name, cat=""):
    c = cat or ""
    if "대학" in name or "대학병원" in c: return "대학병원"
    if "어린이재활" in name: return "어린이재활병원"
    if "재활" in name and "병원" in name: return "재활병원"
    if "종합병원" in c: return "종합병원"
    if "정형" in c or "척추" in c or "관절" in name or "척추" in name or "정형" in name: return "정형·척추 전문병원"
    if "재활" in c: return "재활병원"
    if "공공" in c or "공단" in c: return "공공병원"
    return "병원(종류 확인 중)"


# ---------- 굿잡피티 ----------
def goodjob(opener):
    items = []
    for page in (1, 2, 3):
        s = fetch(opener, "https://www.goodjobpt.com/bbs/board.php?bo_table=job&page=%d" % page)
        for row in re.findall(r"<tr[^>]*>(.*?)</tr>", s, re.S):
            m = re.search(r"wr_id=(\d+)", row)
            if not m: continue
            t = clean(row)
            # 예: "인천세종병원 인천세종병원 물리치료팀 물리치료사 채용(계약직) 🏥 종합병원 📍 인천 💼 계약직 👤 경력무관 조회 307 채용시마감"
            cat = (re.search(r"🏥\s*([^📍💼👤]+)", t) or [None, ""])[1].strip()
            reg = (re.search(r"📍\s*([^💼👤🏥]+)", t) or [None, ""])[1].strip()
            typ = (re.search(r"💼\s*([^👤📍🏥]+)", t) or [None, ""])[1].strip()
            car = (re.search(r"👤\s*(\S+)", t) or [None, ""])[1].strip()
            head = re.split(r"\s*(?:D-\d+|D-day)?\s*🏥", t)[0].strip()
            # 목록 글은 "병원이름 병원이름 제목" 모양 → 앞에서 두 번 반복되는 부분이 병원 이름
            words, name = head.split(" "), ""
            for n in range(1, len(words) // 2 + 1):
                if words[:n] == words[n:2 * n]: name = " ".join(words[:n])
            if not name: name = words[0]
            title = head[len(name):].strip()
            if title.startswith(name): title = title[len(name):].strip()
            status = t.rsplit(" ", 1)[-1]
            if "마감" in status and status not in ("채용시마감", "오늘마감"): continue   # 이미 마감
            if status not in ("지원가능", "채용시마감", "오늘마감"): continue
            if "병원 외" in cat or not region_ok(reg) or not name_ok(name): continue
            dm = re.search(r"D-(\d+)", t)
            if status == "오늘마감" or "D-day" in t: dl = TODAY.isoformat()
            elif dm: dl = (TODAY + datetime.timedelta(days=int(dm.group(1)))).isoformat()
            else: dl = "채용시마감"
            items.append({"hospital": f"{name} ({short(title)})", "region": reg, "type": typ or "병원", "career": car,
                          "pay": "", "deadline": dl, "url": f"https://www.goodjobpt.com/bbs/board.php?bo_table=job&wr_id={m.group(1)}",
                          "source": "굿잡피티", "kind": kind_of(name, cat), "_key": "gj" + m.group(1), "_name": name})
        time.sleep(1.5)
    return dedupe(items)


# ---------- 메디잡 ----------
def medijob(opener):
    items = []
    base = "https://www.medijob.cc/rec/cag/rec_cag_101"
    fetch(opener, base)   # 쿠키 받기
    for page in range(1, 7):
        q = urllib.parse.urlencode({"paging": "Y", "page": page, "rows": 50, "sidx": "registDate", "sord": "DESC"})
        s = fetch(opener, "https://www.medijob.cc/rec/cag/sub/rec_cag_101_list_01?" + q,
                  headers={"X-Requested-With": "XMLHttpRequest", "Referer": base})
        blocks = re.split(r'<div class="rec_li\s*"\s+id="', s)[1:]
        if not blocks: break
        for b in blocks:
            sid = re.match(r"(\d+)", b)
            if not sid: continue
            name = clean((re.search(r'class="rec_li_tit">(.*?)</div>', b, re.S) or [None, ""])[1])
            title = clean((re.search(r'title="채용제목"[^>]*>(.*?)</a>', b, re.S) or [None, ""])[1])
            spans = [clean(x) for x in re.findall(r"<span>(.*?)</span>", (re.search(r'class="rlc2">(.*?)</div>', b, re.S) or [None, ""])[1], re.S)]
            spans = [x for x in spans if x]
            pay = clean((re.search(r'class="rlc3">(.*?)</div>', b, re.S) or [None, ""])[1])
            dl_raw = clean((re.search(r'class="rlb2">(.*?)</div>', b, re.S) or [None, ""])[1]).replace("등록", "").strip()
            if "물리치료" not in title and "물리치료" not in pay: continue
            reg = next((x for x in spans if ">" in x or x.startswith("서울") or x.startswith("인천") or x.startswith("경기")), "")
            reg = re.sub(r"\s*>\s*", " ", reg).replace("경기 ", "")
            if not region_ok(reg) or not name_ok(name): continue
            dm = re.search(r"(\d{4}-\d{2}-\d{2})", dl_raw)
            dl = dm.group(1) if dm else "채용시마감"
            if dm and dl < TODAY.isoformat(): continue
            career = spans[0] if spans else ""
            typ = next((x for x in spans if any(k in x for k in ("정규", "계약", "파트", "알바", "아르바이트"))), "병원")
            pay2 = re.sub(r"^물리치료사\s*:\s*", "", pay)
            items.append({"hospital": f"{name} ({short(title)})", "region": reg, "type": typ, "career": career,
                          "pay": "" if "내규" in pay2 else pay2[:40], "deadline": dl,
                          "url": f"https://www.medijob.cc/com/cpn/com_cpn_100_view_02?recruitSeqno={sid.group(1)}",
                          "source": "메디잡", "kind": kind_of(name), "_key": "mj" + sid.group(1), "_name": name})
        time.sleep(1.5)
    return dedupe(items)


def dedupe(items):
    seen, out = set(), []
    for x in items:
        if x["_key"] in seen: continue
        seen.add(x["_key"]); out.append(x)
    return out


def norm_name(n):
    return re.sub(r"\(.*?\)|의료법인|의료재단|재단법인|\s", "", n or "")


def main():
    prev = {"items": []}
    try:
        prev = json.load(open(OUT, encoding="utf-8"))
    except Exception:  # noqa: BLE001
        pass
    prev_items = prev.get("items", [])
    first_seen = {x.get("url"): x.get("first", prev.get("date", TODAY.isoformat())) for x in prev_items}

    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    got, notes, ok_sources = [], [], set()
    for label, fn in (("굿잡피티", goodjob), ("메디잡", medijob)):
        try:
            r = fn(opener); got += r; ok_sources.add(label); notes.append(f"{label} {len(r)}")
        except Exception as e:  # noqa: BLE001
            notes.append(f"{label} 실패({type(e).__name__})")

    # 굿잡피티 ↔ 메디잡 같은 병원은 하나로 (출처 합치기)
    merged = []
    for x in got:
        twin = next((y for y in merged if y["source"] != x["source"] and norm_name(y["_name"]) == norm_name(x["_name"])
                     and y["deadline"] == x["deadline"]), None)
        if twin:
            twin["source"] = "굿잡피티, 메디잡"
            continue
        merged.append(x)

    urls = {x["url"] for x in merged}
    today = TODAY.isoformat()
    # 전 목록에서 이어서 둘 것: 이번에 못 읽은 사이트 공고, 사람인 등 손으로 넣은 공고 → 마감 전까지
    new_names = {(norm_name(x["_name"]), x["deadline"]) for x in merged}
    new_plain = {norm_name(x["_name"]) for x in merged}
    for x in prev_items:
        if x.get("url") in urls: continue
        pn = norm_name(str(x.get("hospital", "")).split(" (")[0])
        if (pn, x.get("deadline")) in new_names: continue                       # 같은 병원·같은 마감 → 새로 읽은 것만
        if pn in new_plain and not re.match(r"\d{4}", str(x.get("deadline", ""))): continue   # 채용시마감 옛 글 → 새 글로 대체
        src = str(x.get("source", ""))
        dl = str(x.get("deadline", ""))
        # 목록은 최근 글만 읽으므로 못 찾았다고 마감으로 보지 않는다 → 마감일 기준으로만 뺀다
        if re.match(r"\d{4}-\d{2}-\d{2}$", dl):
            if dl < today: continue
        else:   # 채용시마감: 처음 본 날부터 30일 지나면 뺀다
            fs = first_seen.get(x.get("url"), today)
            try:
                if (TODAY - datetime.date.fromisoformat(fs)).days > 30: continue
            except ValueError:
                pass
        merged.append({k: v for k, v in x.items() if not k.startswith("_")})

    for x in merged:
        x["first"] = first_seen.get(x["url"], today)
        x["isNew"] = (TODAY - datetime.date.fromisoformat(x["first"])).days <= 1
        x.pop("_key", None); x.pop("_name", None)

    def sort_key(x):
        dl = x.get("deadline", "")
        return (0 if re.match(r"\d{4}", dl) else 1, dl, x.get("hospital", ""))
    merged.sort(key=sort_key)

    by_src = {}
    for x in merged:
        for s in str(x.get("source", "")).split(", "):
            by_src[s] = by_src.get(s, 0) + 1
    soon = [x["hospital"].split(" (")[0] for x in merged if x.get("deadline") in (today, (TODAY + datetime.timedelta(days=1)).isoformat())]
    summary = (f"총 {len(merged)}건(신규 {sum(1 for x in merged if x['isNew'])}). 사이트별 " +
               "·".join(f"{k} {v}" for k, v in by_src.items()) + f" (자동 수집 {NOW:%m/%d %H:%M}, " + ", ".join(notes) + ")." +
               (" 오늘·내일 마감: " + ", ".join(soon[:5]) + "." if soon else ""))
    out = {"at": f"{NOW:%m/%d %H:%M}", "date": today, "summary": summary, "checked": "자동 수집 (매일)", "items": merged}
    if not ok_sources and prev_items:
        print("두 사이트 모두 실패 — 전 목록 유지"); return 0
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
