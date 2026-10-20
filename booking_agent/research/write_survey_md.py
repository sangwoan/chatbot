"""platform_survey.csv(원본) → PLATFORM_SURVEY.md 요약 문서.

    python3 research/write_survey_md.py
"""
import csv
from collections import Counter
from pathlib import Path

HERE = Path(__file__).parent
rows = list(csv.DictReader(open(HERE / "platform_survey.csv", encoding="utf-8-sig")))
ORDER = ["불가 · 봇 차단", "불가 · 약관 금지", "비권장 · 봇 방어", "비권장 · 매크로 단속", "조건부 · 약관 확인 필요", "확인 실패"]
c = Counter((r["자동 감시 판정"], r["지역"]) for r in rows)

L = []
L.append("# 예약·티켓 사이트 자동 감시 가능 여부 조사 (2026-10-19, 갱신 2026-10-20)\n")
L.append("국내 72곳 + 해외 78곳 = 150곳. 많이 쓰이는 예약·티켓 사이트를 골라 만든 목록이며 트래픽 순위는 아니다.\n")
L.append("## 방법\n")
L.append("- 사이트마다 일반 요청 최대 3번: robots.txt → 대상 페이지 → 약관 페이지. robots.txt가 막은 페이지는 열지 않았다. 브라우저 자동화·우회는 쓰지 않았다(`check_sites.py`).")
L.append("- 공식 알림·대기·API와 주요 사이트 약관·매크로 단속은 웹 검색으로 따로 확인했다.")
L.append("- 온보딩하며 직접 확인한 사이트는 판정 근거에 확인일을 적었다.")
L.append("- 법률 판단이 아니다.\n")
L.append("## 판정 기준\n")
L.append("| 판정 | 뜻 |\n|---|---|")
L.append("| 불가 · 봇 차단 | robots.txt가 일반 봇 전체 금지, robots.txt부터 403, 일반 요청이 차단·챌린지, 또는 잔여 조회에 매크로 방지·대기열 적용 |")
L.append("| 불가 · 약관 금지 | 약관의 자동화·스크레이핑 금지 조항 확인, 또는 매크로 적발 제재 보도 |")
L.append("| 비권장 · 봇 방어 | Akamai Bot Manager·DataDome·PerimeterX·Kasada·Imperva·AWS WAF·F5 흔적. 자동 조회가 막힐 가능성이 높고, 막힌 뒤 계속하면 우회가 된다 |")
L.append("| 비권장 · 매크로 단속 | 국내 티켓 예매처·NOL 계열처럼 매크로 감시·강제 취소가 보도된 곳 |")
L.append("| 조건부 · 약관 확인 필요 | robots 허용, 차단 없음, 봇 방어 미감지. 약관에 금지 조항이 없을 때만 알림 전용·60초 이상 간격·정직한 식별로 감시 후보. 차단되면 즉시 중단 |\n")
L.append("## 결과 요약\n")
L.append("| 판정 | 국내 | 해외 | 합계 |\n|---|---:|---:|---:|")
for v in ORDER:
    k, g = c[(v, "국내")], c[(v, "해외")]
    if k + g:
        L.append(f"| {v} | {k} | {g} | {k + g} |")
L.append("")
L.append("- 자동 감시를 명시적으로 **허용**한다고 밝힌 예약 사이트는 찾지 못했다.")
L.append("- 가장 확실한 방법은 사이트가 직접 주는 **공식 알림·대기·API**다(아래 표).")
L.append("- 국내 공공 예약 시스템은 잔여 조회 자체에 매크로 방지(동적 경로)·대기열(NetFUNNEL)을 거는 경우가 많다. 서울시 공공예약·국립공원이 그랬고, 대신 공식 대기신청이 있는 곳이 많다.\n")
L.append("## 새 규칙 기준 (2026-10-19 사용자 결정)\n")
L.append("불법이 아니고 사이트 정책에 명시적 금지가 없으면 허용한다(PLAN.md 원칙 5, §9). robots.txt 금지와 약관의 자동화 금지는 명시적 금지로 보고, 기술적 차단은 정책과 상관없이 제외한다.\n")
L.append("| 새 규칙 판정 | 국내 | 해외 | 합계 |\n|---|---:|---:|---:|")
nc = Counter((r["새 규칙 판정"], r["지역"]) for r in rows)
for v in sorted({r["새 규칙 판정"] for r in rows}):
    k, g = nc[(v, "국내")], nc[(v, "해외")]
    L.append(f"| {v} | {k} | {g} | {k + g} |")
L.append("")
for label in ("후보 · 금지 문구 못 찾음", "후보 · 약관 확인 필요"):
    names = [r["사이트"] + (" (봇 방어)" if "봇 방어" in r["새 규칙 판정"] else "") for r in rows if r["새 규칙 판정"].startswith(label)]
    L.append(f"- **{label}** ({len(names)}): " + ", ".join(names))
L.append("\n후보는 온보딩(§9.3) 때 약관 원문과 잔여 조회 방식을 확인하고 `watches.yaml`의 `sites`에 판정을 기록해야 감시가 시작된다. 봇 방어가 있는 곳은 차단되면 그 즉시 멈춘다.\n")
L.append("## 공식 알림·대기·API\n")
L.append("| 사이트 | 기능 | 자동 감시 판정 | 출처 |\n|---|---|---|---|")
for r in rows:
    if r["공식 알림·대기·API"] != "-":
        src = f"[링크]({r['공식 기능 출처']})" if r["공식 기능 출처"] else "-"
        L.append(f"| {r['사이트']} | {r['공식 알림·대기·API']} | {r['자동 감시 판정']} | {src} |")
L.append("")
L.append("## 전체 표\n")
L.append("| 지역 | 분류 | 사이트 | 새 규칙 판정 | 처음 판정 | 근거 | 공식 기능 |\n|---|---|---|---|---|---|---|")
for r in rows:
    off = r["공식 알림·대기·API"] if r["공식 알림·대기·API"] != "-" else ""
    L.append(f"| {r['지역']} | {r['분류']} | {r['사이트']} | {r['새 규칙 판정']} | {r['자동 감시 판정']} | {r['판정 근거']} | {off} |")
L.append("")
L.append("상세 컬럼(robots.txt·일반 요청 결과·봇 방어 흔적·약관 검사 결과·비고)은 `platform_survey.csv`(원본). 대상 목록은 `sites.csv`. 이 문서는 `python3 research/write_survey_md.py`로 다시 만든다.\n")
L.append("## 한계\n")
L.append("- robots.txt는 Python `robotparser`로 판독했다(와일드카드 미지원). 구글 항공권·똑닥·에어서울은 원문을 보고 고쳤다.")
L.append("- 봇 방어 흔적은 첫 페이지 기준이다. 실제 예약 조회 API는 더 강하게 막혀 있을 수 있다(서울시 공공예약·국립공원 사례).")
L.append("- 약관 자동 검사는 첫 페이지에서 약관 링크를 찾은 경우만 했다. 나머지는 '미확인'이다.")
L.append("- SRT는 2026-09-01 KTX(코레일+)로 통합됐다.")
(HERE / "PLATFORM_SURVEY.md").write_text("\n".join(L) + "\n", encoding="utf-8")
print("wrote PLATFORM_SURVEY.md", len(L), "lines")
