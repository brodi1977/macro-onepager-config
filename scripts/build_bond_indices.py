"""Builds data/bond_indices.json: weighted YTM / duration / spread / average rating for every
bond index on Bizportal's index list (Tel-Bond, Tel-Gov, All-Bond), for the page's "bond indices" tab.

Index-level figures are weight-weighted averages of the constituents' own figures:
 * the constituents and their weights come from Bizportal's "הרכב מדד" page of each index
   (each row links to the bond's TASE security number - matching is by security number only);
 * gross YTM / duration / spread over the matching government bond come from Bizportal's table
   of all listed bonds (/bonds/search);
 * credit ratings (Maalot / Midroog) come from each bond's own Bizportal page and are mapped
   onto one S&P-style scale (a bond rated by both gets the mean notch).
Plain HTTP only. Needs: requests, beautifulsoup4.
"""
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept-Language": "he-IL,he;q=0.9",
}
INDEX_LIST_URL = "https://www.bizportal.co.il/tradedata/bondindices"
SEARCH_URL = "https://www.bizportal.co.il/bonds/search"
COMPOSITION_URLS = [
    "https://www.bizportal.co.il/bonds/indices/indexcomposition/{id}",
    "https://www.bizportal.co.il/capitalmarket/indices/indexcomposition/{id}",
]
BOND_URL = "https://www.bizportal.co.il/bonds/quote/generalview/{paper_id}"
OUT = Path(__file__).resolve().parent.parent / "data" / "bond_indices.json"

SCALE = ["AAA", "AA+", "AA", "AA-", "A+", "A", "A-", "BBB+", "BBB", "BBB-",
         "BB+", "BB", "BB-", "B+", "B", "B-", "CCC+", "CCC", "CCC-", "CC", "C", "D"]
_MIDROOG = {"Aaa": "AAA", "Aa1": "AA+", "Aa2": "AA", "Aa3": "AA-", "A1": "A+", "A2": "A", "A3": "A-",
            "Baa1": "BBB+", "Baa2": "BBB", "Baa3": "BBB-", "Ba1": "BB+", "Ba2": "BB", "Ba3": "BB-",
            "B1": "B+", "B2": "B", "B3": "B-", "Caa1": "CCC+", "Caa2": "CCC", "Caa3": "CCC-", "Ca": "CC", "C": "C"}


def num(text: str):
    try:
        return float(text.replace(",", "").replace("%", "").strip())
    except ValueError:
        return None


def get(session: requests.Session, url: str, retries: int = 3) -> requests.Response:
    last = None
    for attempt in range(retries):
        try:
            r = session.get(url, headers=HEADERS, timeout=40)
            if r.status_code == 200:
                return r
            last = RuntimeError(f"HTTP {r.status_code} for {url}")
        except requests.RequestException as e:
            last = e
        time.sleep(1.5 * (attempt + 1))
    raise last


def list_indices(session) -> list[tuple[str, str]]:
    soup = BeautifulSoup(get(session, INDEX_LIST_URL).text, "html.parser")
    seen, out = set(), []
    for a in soup.select("table a[href*='/indices/generalview/']"):
        idx = a["href"].rstrip("/").split("/")[-1]
        if idx not in seen:
            seen.add(idx)
            out.append((idx, a.get_text(strip=True)))
    return out


def fetch_bond_table(session) -> dict[str, dict]:
    soup = BeautifulSoup(get(session, SEARCH_URL).text, "html.parser")
    bonds = {}
    for tr in soup.select("table tbody tr"):
        cells = [td.get_text(strip=True) for td in tr.select("td")]
        link = tr.select_one("a[href*='/bonds/quote/']")
        if len(cells) >= 8 and link:
            bonds[link["href"].rstrip("/").split("/")[-1]] = {"ytm": num(cells[5]), "duration": num(cells[6]), "spread": num(cells[7])}
    if len(bonds) < 500:
        raise RuntimeError(f"bond table looks wrong: only {len(bonds)} rows")
    return bonds


def fetch_composition(session, index_id: str) -> list[dict]:
    for template in COMPOSITION_URLS:
        try:
            r = get(session, template.format(id=index_id), retries=2)
        except Exception:
            continue
        table = BeautifulSoup(r.text, "html.parser").select_one("table")
        if table is None:
            continue
        heads = [th.get_text(" ", strip=True) for th in table.select("thead th")]
        try:
            i_w, i_y = heads.index("משקל ב-%"), heads.index("תשואה ברוטו")
            i_d = next(i for i, h in enumerate(heads) if h.startswith('מח"'))
            i_s = heads.index("מרווח מהממשלתי")
        except (ValueError, StopIteration):
            continue
        rows = []
        for tr in table.select("tbody tr"):
            tds = [td.get_text(strip=True) for td in tr.select("td")]
            link = tr.select_one("a[href*='/quote/generalview/']")
            if link and len(tds) > max(i_w, i_y, i_d, i_s):
                rows.append({"paper_id": link["href"].rstrip("/").split("/")[-1], "weight": num(tds[i_w]) or 0.0,
                             "ytm": num(tds[i_y]), "duration": num(tds[i_d]), "spread": num(tds[i_s])})
        if rows:
            return rows
    raise RuntimeError(f"no composition table for index {index_id}")


def to_notch(symbol):
    if not symbol:
        return None
    s = re.sub(r"\.il$", "", re.sub(r"^il", "", symbol.strip()), flags=re.I)
    s = _MIDROOG.get(s, s)
    return SCALE.index(s) if s in SCALE else None


def fetch_rating_notch(session, paper_id: str):
    try:
        text = BeautifulSoup(get(session, BOND_URL.format(paper_id=paper_id)).text, "html.parser").get_text(" ", strip=True)
    except Exception:
        return None
    m = re.search(r"דירוג מעלות(.*?)דירוג מידרוג(.*?)שיעור ריבית", text)
    if not m:
        return None
    ma = re.search(r"\bil[A-Z][A-Za-z+\-]*", m.group(1))
    mi = re.search(r"\b[A-Z][a-z]*\d?\.il\b", m.group(2))
    notches = [n for n in (to_notch(ma.group(0) if ma else None), to_notch(mi.group(0) if mi else None)) if n is not None]
    return sum(notches) / len(notches) if notches else None


def wmean(rows: list[dict], key: str):
    have = [(r["weight"], r[key]) for r in rows if r["weight"] and r.get(key) is not None]
    wsum = sum(w for w, _ in have)
    return (sum(w * v for w, v in have) / wsum if wsum else None), wsum


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    with requests.Session() as session:
        indices = list_indices(session)
        bonds = fetch_bond_table(session)
        print(f"{len(indices)} indices, {len(bonds)} bonds")

        compositions, failed = {}, {}
        for idx, name in indices:
            try:
                compositions[idx] = fetch_composition(session, idx)
            except Exception as e:
                failed[idx] = str(e)[:100]
        print(f"compositions: {len(compositions)} ok, {len(failed)} failed")
        if len(compositions) < len(indices) / 2:
            raise SystemExit("too many composition pages failed - refusing to overwrite the data file")

        ids = sorted({r["paper_id"] for rows in compositions.values() for r in rows})
        print(f"fetching ratings for {len(ids)} bonds...")
        with ThreadPoolExecutor(max_workers=12) as pool:
            notches = dict(zip(ids, pool.map(lambda pid: fetch_rating_notch(session, pid), ids)))

    out_rows = []
    for idx, name in indices:
        rows = compositions.get(idx)
        if not rows:
            out_rows.append({"id": idx, "name": name, "error": failed.get(idx, "no composition")})
            continue
        for r in rows:
            b = bonds.get(r["paper_id"], {})
            for key in ("ytm", "duration", "spread"):
                if b.get(key) is not None:
                    r[key] = b[key]
            r["notch"] = notches.get(r["paper_id"])
        total = sum(r["weight"] for r in rows)
        ytm, _ = wmean(rows, "ytm")
        dur, _ = wmean(rows, "duration")
        spr, _ = wmean(rows, "spread")
        notch, rated_w = wmean(rows, "notch")
        found_w = sum(r["weight"] for r in rows if r["ytm"] is not None or r["duration"] is not None)
        out_rows.append({
            "id": idx, "name": name, "constituents": len(rows),
            "coverage_pct": round(100 * found_w / total, 1) if total else 0.0,
            "ytm": round(ytm, 2) if ytm is not None else None,
            "duration": round(dur, 2) if dur is not None else None,
            "spread": round(spr, 2) if spr is not None else None,
            "rating": SCALE[max(0, min(len(SCALE) - 1, int(round(notch))))] if notch is not None else None,
            "rating_coverage_pct": round(100 * rated_w / total, 1) if total else 0.0,
        })

    OUT.parent.mkdir(parents=True, exist_ok=True)
    payload = {"generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
               "source": "Bizportal", "indices": out_rows}
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {OUT} ({len(out_rows)} indices)")


if __name__ == "__main__":
    main()
