import html as html_mod
import json
import os
import re
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

ACADEMIC_YEAR = os.getenv("TAU_YEAR", "2026")
SEMESTER = os.getenv("TAU_SEMESTER", "1")
DAY_MAP = {"א": 0, "ב": 1, "ג": 2, "ד": 3, "ה": 4}

TARGETS = [
    ("lstDep6", "0321", "מדעים מדויקים", "פיזיקה ואסטרונומיה"),
    ("lstDep6", "0341", "מדעים מדויקים", "גיאופיזיקה"),
    ("lstDep6", "0349", "מדעים מדויקים", "גאוגרפיה וסביבת האדם"),
    ("lstDep6", "0351", "מדעים מדויקים", "כימיה"),
    ("lstDep6", "0365", "מדעים מדויקים", "סטטיסטיקה וחקר ביצועים"),
    ("lstDep6", "0366-0372", "מדעים מדויקים", "מתמטיקה"),
    ("lstDep6", "0368", "מדעים מדויקים", "מדעי המחשב"),
    ("lstDep1", "08", "אמנויות", ""),
    ("lstDep2", "05", "הנדסה", ""),
    ("lstDep3", "10", "מדעי החברה", ""),
    ("lstDep4", "04", "מדעי החיים", ""),
    ("lstDep5", "06-16-21", "מדעי הרוח", ""),
    ("lstDep7", "14", "משפטים", ""),
    ("lstDep8", "12", "ניהול", ""),
    ("lstDep9", "01", "רפואה", ""),
    ("lstDep10", "11", "עבודה סוציאלית", ""),
]


def clean(s: str) -> str:
    s = re.sub(r"<[^>]+>", "", s)
    s = html_mod.unescape(s).replace("\xa0", " ")
    return re.sub(r"\s+", " ", s).strip()


def fetch_one(dep_field: str, dep_val: str, fac_name: str, dep_label: str, yom: int) -> list[dict]:
    url = "https://www.ims.tau.ac.il/tal/kr/Search_L.aspx"
    data = urllib.parse.urlencode([
        ("lstYear1", ACADEMIC_YEAR),
        ("ckSem", SEMESTER),
        ("ckYom", str(yom)),
        (dep_field, dep_val),
    ]).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://www.ims.tau.ac.il/tal/kr/search_p.aspx",
        },
    )
    raw = ""
    for attempt in range(3):
        try:
            raw = urllib.request.urlopen(req, timeout=25).read().decode("utf-8", errors="replace")
            break
        except Exception:
            if attempt == 2:
                return []
            time.sleep(1.5)

    results = []
    for b in re.split(r"<tr class='listtdbld'[^>]*>", raw)[1:]:
        m_head = re.match(r"\s*<td[^>]*>(.*?)</td>\s*<td[^>]*>(.*?)</td>", b, re.S)
        if not m_head:
            continue
        code_raw = clean(m_head.group(1))
        course_name = clean(m_head.group(2))
        m_code = re.search(r"(\d{4}-\d{4})", code_raw)
        code = m_code.group(1) if m_code else code_raw[:12]

        for row in re.finditer(r"<tr style='text-align:right'>(.*?)</tr>", b, re.S):
            tds = [clean(x) for x in re.findall(r"<td[^>]*>(.*?)</td>", row.group(1), re.S)]
            if len(tds) < 7:
                continue
            lecturer, mode, building, room, day_he, time_str, _sem = tds[:7]
            day_clean = day_he.replace("'", "").replace("׳", "").strip()
            if day_clean not in DAY_MAP or not building or not room:
                continue
            m_time = re.search(r"(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})", time_str)
            if not m_time:
                continue
            t1, t2 = m_time.group(1).zfill(5), m_time.group(2).zfill(5)
            start, end = (t1, t2) if t1 < t2 else (t2, t1)
            note = f"{dep_label} · {mode}" if (dep_label and mode) else (dep_label or mode or "שיעור")
            results.append({
                "course": course_name,
                "code": code,
                "lecturer": lecturer or "סגל החוג",
                "faculty": fac_name,
                "building": building,
                "room": room,
                "day": DAY_MAP[day_clean],
                "start": start,
                "end": end,
                "note": note,
            })
    return results


def main():
    tasks = [(t[0], t[1], t[2], t[3], yom) for t in TARGETS for yom in range(1, 6)]
    scraped = []
    with ThreadPoolExecutor(max_workers=5) as ex:
        futs = [ex.submit(fetch_one, *task) for task in tasks]
        for fut in as_completed(futs):
            scraped.extend(fut.result())

    if len(scraped) < 500:
        print(f"Too few lectures scraped ({len(scraped)}), keeping existing schedule.json")
        return

    seen = set()
    dedup = []
    for item in scraped:
        key = (item["code"], item["day"], item["start"], item["end"], item["building"], item["room"])
        if key not in seen:
            seen.add(key)
            dedup.append(item)

    out = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "lectures": dedup,
    }
    Path("schedule.json").write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"Updated schedule.json with {len(dedup)} lectures")


if __name__ == "__main__":
    main()
