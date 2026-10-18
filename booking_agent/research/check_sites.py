"""One-time survey of booking/ticketing sites (personal research).

Per site, at most three plain requests with an honest User-Agent:
  1. robots.txt
  2. the listed page, only if robots.txt allows it for generic bots
  3. the terms-of-service page linked from (2), only if robots.txt allows it
No browser automation, no retries, no evasion.

usage: python3 -I check_sites.py sites.csv out_dir
"""
import concurrent.futures as cf
import csv
import json
import os
import re
import subprocess
import sys
import tempfile
from html import unescape
from urllib import robotparser
from urllib.parse import urljoin, urlparse

UA = "Mozilla/5.0 (compatible; booking-agent-survey/1.0; one-time personal research)"
TOKEN = "booking-agent-survey"

CHALLENGE = re.compile(
    r"just a moment|cf-chl|attention required|challenge-platform|pardon our interruption|request unsuccessful"
    r"|_incapsula_resource|px-captcha|captcha-delivery|are you a robot|unusual traffic|access denied"
    r"|자동입력 방지|비정상적인 접근|접근이 차단|접근이 제한", re.I)
TERMS_TEXT = re.compile(
    r"^\s*(서비스\s*)?이용\s*약관|^\s*(회원\s*)?약관\s*$|terms\s*(of\s*(use|service|sale))?\s*$|terms\s*(&|and)\s*conditions"
    r"|conditions\s*of\s*(use|carriage|sale)|利用規約|ご利用規約|会員規約|^\s*agb\s*$|nutzungsbedingungen"
    r"|conditions\s*g[ée]n[ée]rales|^\s*cgu\s*$|t[ée]rminos|condizioni", re.I)
TERMS_HREF = re.compile(r"terms|agreement|yakgwan|stipulation|clause|kiyaku|/agb|/cgu|policy/?service|service/?policy|termsofuse|/tos\b", re.I)
NOT_TERMS = re.compile(r"privacy|개인정보|위치|location|cookie|쿠키|youth|청소년|email|이메일|마케팅", re.I)
AUTO_KW = re.compile(
    r"매크로|자동화된|자동화\s*(도구|프로그램|수단|방법|시스템)|자동\s*접속|자동\s*수집|자동으로\s*수집|크롤링|크롤러|스크래핑|스크레이핑"
    r"|로봇|봇\s*프로그램|기계적\s*(수단|방법|장치)|\brobots?\b|\bspiders?\b|\bscrap(e|er|ers|ing)\b|\bcrawl(er|ers|ing)?\b"
    r"|automated\s+(means|systems?|software|process(es)?|devices?|tools?|scripts?|access|quer(y|ies)|methods?|programs?)"
    r"|data\s*mining|screen\s*scraping|\bbots?\b|ロボット|スクレイピング|クローラ|自動(的)?(な|に)?(手段|プログラム|ツール|アクセス|取得|収集)|ボット"
    r"|automatisiert|automatischen?\s+(mitteln|programmen)|aspiration|automatizad", re.I)


def fetch(url, tmproot, max_bytes=5_000_000):
    with tempfile.TemporaryDirectory(dir=tmproot) as td:
        hf, bf = os.path.join(td, "h"), os.path.join(td, "b")
        cmd = ["curl", "-sS", "-L", "--max-redirs", "6", "--max-time", "20", "--compressed",
               "--max-filesize", str(max_bytes), "-A", UA,
               "-H", "Accept: text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.8",
               "-H", "Accept-Language: ko-KR,ko;q=0.9,en;q=0.8",
               "-D", hf, "-o", bf, "-w", "%{http_code}\t%{url_effective}", url]
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=35)
        except subprocess.TimeoutExpired:
            return {"status": None, "url": url, "headers": {}, "allh": {}, "cookies": [], "body": b"", "error": "timeout"}
        code, _, eff = p.stdout.partition("\t")
        status = int(code) if code.isdigit() and code != "000" else None
        headers, allh, cookies = {}, {}, []
        if os.path.exists(hf):
            raw = open(hf, "rb").read().decode("latin-1")
            blocks = [b for b in re.split(r"\r?\n\r?\n", raw) if b.strip().upper().startswith("HTTP")]
            for i, b in enumerate(blocks):
                for line in b.splitlines()[1:]:
                    k, _, v = line.partition(":")
                    k, v = k.strip().lower(), v.strip()
                    if not k:
                        continue
                    if k == "set-cookie":
                        cookies.append(v)
                    allh[k] = v
                    if i == len(blocks) - 1:
                        headers[k] = v
        body = open(bf, "rb").read() if os.path.exists(bf) else b""
        return {"status": status, "url": eff or url, "headers": headers, "allh": allh, "cookies": cookies,
                "body": body, "error": p.stderr.strip()[:160] if status is None else ""}


def decode(body, headers):
    m = re.search(r"charset=([\w-]+)", headers.get("content-type", ""), re.I) or \
        re.search(rb"charset=[\"']?([\w-]+)", body[:3000], re.I)
    cs = m.group(1) if m else "utf-8"
    cs = cs.decode() if isinstance(cs, bytes) else cs
    try:
        return body.decode(cs, errors="ignore")
    except LookupError:
        return body.decode("utf-8", errors="ignore")


def text_of(html):
    t = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", unescape(t)).strip()


def waf_signs(r):
    h, c = r["allh"], " ".join(r["cookies"]).lower()
    hs, server = json.dumps(h).lower(), h.get("server", "").lower()
    body = r["body"][:200_000].decode("latin-1").lower()
    s = []
    if "cf-ray" in h or "cloudflare" in server or "__cf_bm" in c:
        s.append("Cloudflare")
    if "akamai" in server or "akamai" in hs or "_abck=" in c or "bm_sz=" in c or "ak_bmsc=" in c:
        s.append("Akamai" + (" Bot Manager" if ("_abck=" in c or "bm_sz=" in c) else ""))
    if "x-iinfo" in h or "incap_ses" in c or "visid_incap" in c:
        s.append("Imperva")
    if "_px" in c or "px-captcha" in body or "perimeterx" in body:
        s.append("PerimeterX")
    if "x-datadome" in h or "datadome=" in c or "captcha-delivery" in body:
        s.append("DataDome")
    if "aws-waf-token" in c or "awswaf" in body:
        s.append("AWS WAF")
    if "x-kpsdk" in hs or "kpsdk" in body:
        s.append("Kasada")
    if re.search(r"(^|;\s*|,\s*)ts0[0-9a-f]{6,}=", c):
        s.append("F5")
    if "x-amz-cf-id" in h:
        s.append("CloudFront")
    return s


def robots_for(url, tmproot):
    p = urlparse(url)
    root = f"{p.scheme}://{p.netloc}"
    r = fetch(root + "/robots.txt", tmproot, 600_000)
    st, rp = r["status"], robotparser.RobotFileParser()
    if st is None:
        return {"robots": "확인 실패", "robots_status": None, "robots_note": r["error"]}, None
    if st in (401, 403):
        rp.disallow_all = True
        return {"robots": "robots.txt 접근 거부", "robots_status": st}, rp
    if 400 <= st < 500:
        rp.allow_all = True
        return {"robots": "없음(제한 없음)", "robots_status": st}, rp
    if st >= 500:
        return {"robots": "서버 오류", "robots_status": st}, None
    txt = decode(r["body"], r["headers"])
    if "<html" in txt[:800].lower() or "<!doctype" in txt[:200].lower():
        rp.allow_all = True
        return {"robots": "없음(HTML 응답)", "robots_status": st}, rp
    rp.parse(txt.splitlines())
    root_ok, page_ok = rp.can_fetch(TOKEN, root + "/"), rp.can_fetch(TOKEN, url)
    if not root_ok and not page_ok:
        label = "전체 금지(일반 봇)"
    elif not page_ok:
        label = "해당 페이지 금지"
    else:
        label = "허용"
    return {"robots": label, "robots_status": st}, rp


def find_terms(html, base):
    best = None
    for href, inner in re.findall(r"<a\b[^>]*?href=[\"']([^\"'#][^\"']*)[\"'][^>]*>(.*?)</a>", html, re.S | re.I):
        label = text_of(inner)[:60]
        if not label and not href:
            continue
        if NOT_TERMS.search(label) or NOT_TERMS.search(href) or href.lower().startswith(("javascript:", "mailto:", "tel:")):
            continue
        score = 0
        if TERMS_TEXT.search(label):
            score = 3
        elif TERMS_HREF.search(href):
            score = 1
        if score and (best is None or score > best[0]):
            best = (score, urljoin(base, unescape(href)), label)
    return best


def survey(row, tmproot):
    out = dict(row)
    info, rp = robots_for(row["url"], tmproot)
    out.update(info)
    if rp is not None and not rp.can_fetch(TOKEN, row["url"]):
        out["home"] = "미접속(robots.txt 금지)"
        return out
    r = fetch(row["url"], tmproot)
    out["home_status"], out["home_url"], out["waf"] = r["status"], r["url"], waf_signs(r)
    html = decode(r["body"], r["headers"]) if r["body"] else ""
    small = len(html) < 30_000
    if r["status"] is None:
        out["home"] = "접속 실패: " + r["error"]
    elif r["status"] in (401, 403, 405, 406, 429, 503):
        out["home"] = f"차단(HTTP {r['status']})"
    elif small and CHALLENGE.search(html):
        out["home"] = "챌린지/차단 페이지"
    elif r["status"] >= 400:
        out["home"] = f"HTTP {r['status']}"
    else:
        out["home"] = "통과"
    if out["home"] != "통과":
        return out
    t = find_terms(html, r["url"])
    if not t:
        out["terms"] = "약관 링크 못 찾음"
        return out
    out["terms_url"], out["terms_label"] = t[1], t[2]
    if urlparse(t[1]).scheme not in ("http", "https"):
        out["terms"] = "약관 링크 형식 미지원"
        return out
    trp_info, trp = robots_for(t[1], tmproot) if urlparse(t[1]).netloc != urlparse(row["url"]).netloc else (None, rp)
    if trp is not None and not trp.can_fetch(TOKEN, t[1]):
        out["terms"] = "약관 페이지 robots 금지"
        return out
    tr = fetch(t[1], tmproot)
    out["terms_status"] = tr["status"]
    if tr["status"] != 200 or not tr["body"]:
        out["terms"] = f"약관 페이지 열기 실패({tr['status']})"
        return out
    tt = text_of(decode(tr["body"], tr["headers"]))
    out["terms_len"] = len(tt)
    hits = []
    for m in AUTO_KW.finditer(tt):
        hits.append(tt[max(0, m.start() - 70): m.end() + 90])
        if len(hits) >= 3:
            break
    if hits:
        out["terms"] = "자동화 금지 조항 의심"
        out["terms_hits"] = hits
    elif len(tt) < 3000:
        out["terms"] = "약관 내용 로딩 안 됨(JS 등)"
    else:
        out["terms"] = "자동화 키워드 없음"
    return out


def main():
    sites, outdir = sys.argv[1], sys.argv[2]
    tmproot = os.path.join(outdir, "tmp")
    os.makedirs(tmproot, exist_ok=True)
    rows = list(csv.DictReader(open(sites, encoding="utf-8")))
    results = []
    with cf.ThreadPoolExecutor(max_workers=12) as ex:
        futs = {ex.submit(survey, r, tmproot): r for r in rows}
        for i, f in enumerate(cf.as_completed(futs), 1):
            try:
                res = f.result()
            except Exception as e:
                res = dict(futs[f], error=f"{type(e).__name__}: {e}")
            results.append(res)
            print(f"[{i:3d}/{len(rows)}] {res['name']}: robots={res.get('robots')} home={res.get('home')} terms={res.get('terms', '-')}", flush=True)
    order = {r["url"]: i for i, r in enumerate(rows)}
    results.sort(key=lambda r: order[r["url"]])
    json.dump(results, open(os.path.join(outdir, "results.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
