import csv
import sys
import time
from dataclasses import dataclass, asdict
from typing import Dict, Iterable, List, Optional, Tuple

import requests
import typer
from bs4 import BeautifulSoup
from tqdm import tqdm

app = typer.Typer(add_completion=False, help="Scrape wrestler data from cagematch.net into CSVs.")


@app.callback()
def _root() -> None:
    """Cagematch scraper CLI."""


BASE_URL = "https://www.cagematch.net/"
LIST_URL = BASE_URL + "?id=2&view=workers"
ROBOTS_URL = BASE_URL + "robots.txt"


@dataclass
class WorkerRow:
    worker_id: str
    ring_name: str
    birthday: Optional[str]
    birthplace: Optional[str]
    height_cm: Optional[str]
    weight_kg: Optional[str]
    promotion: Optional[str]
    rating: Optional[str]
    votes: Optional[str]
    profile_url: str


@dataclass
class WorkerProfile:
    worker_id: str
    ring_name: Optional[str]
    birth_name: Optional[str]
    birthday: Optional[str]
    birthplace: Optional[str]
    height: Optional[str]
    weight: Optional[str]
    debut: Optional[str]
    twitter: Optional[str]
    instagram: Optional[str]
    facebook: Optional[str]
    wikipedia: Optional[str]
    website: Optional[str]


HEADERS = {
    "User-Agent": "cagematch-scraper/0.1 (+https://example.com; contact: none)",
}


def polite_get(session: requests.Session, url: str, rate_limit_s: float) -> requests.Response:
    time.sleep(rate_limit_s)
    response = session.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    return response


def parse_worker_list(html: str) -> List[WorkerRow]:
    soup = BeautifulSoup(html, "lxml")
    # Current site uses TBase TableBorderColor for list tables
    table = soup.find("table", class_="TBase")
    if table is None:
        return []
    rows: List[WorkerRow] = []
    for tr in table.find_all("tr"):
        classes = tr.get("class") or []
        if "THeaderRow" in classes:
            continue
        tds = tr.find_all("td")
        if len(tds) < 2:
            continue
        # Column order: #, Gimmick, Birthday, Birthplace, Height, Weight, Promotion, Rating, Votes
        gimmick_td = tds[1]
        link = gimmick_td.find("a")
        if not link or not link.get("href"):
            continue
        href = link["href"]
        profile_url = BASE_URL.rstrip("/") + "/" + href.lstrip("/")

        # Extract worker id from profile href (id=2&nr=XXXX)
        worker_id = ""
        try:
            from urllib.parse import parse_qs, urlparse

            qs = parse_qs(urlparse(profile_url).query)
            worker_id = (qs.get("nr") or [""])[0]
        except Exception:
            worker_id = ""

        ring_name = link.get_text(strip=True)

        def td_text(idx: int) -> Optional[str]:
            return tds[idx].get_text(strip=True) or None if len(tds) > idx else None

        birthday = td_text(2)
        birthplace = td_text(3)
        height_cm = td_text(4)
        weight_kg = td_text(5)

        # Promotion is an <a> with an <img alt="...">
        promotion = None
        if len(tds) > 6:
            img = tds[6].find("img")
            if img and img.get("alt"):
                promotion = img["alt"].strip() or None

        rating = td_text(7)
        votes = td_text(8)

        rows.append(
            WorkerRow(
                worker_id=worker_id,
                ring_name=ring_name,
                birthday=birthday,
                birthplace=birthplace,
                height_cm=height_cm,
                weight_kg=weight_kg,
                promotion=promotion,
                rating=rating,
                votes=votes,
                profile_url=profile_url,
            )
        )
    return rows


def parse_worker_profile(html: str, worker_id: str) -> WorkerProfile:
    soup = BeautifulSoup(html, "lxml")

    # Try to find key-value table sections used in cagematch profiles
    info_map: Dict[str, Optional[str]] = {
        "Ring Name": None,
        "Birth Name": None,
        "Birthday": None,
        "Birth Place": None,
        "Height": None,
        "Weight": None,
        "Debut": None,
    }

    # Social links
    socials: Dict[str, Optional[str]] = {
        "Twitter": None,
        "Instagram": None,
        "Facebook": None,
        "Wikipedia": None,
        "Website": None,
    }

    # Generic extraction: any two-column table with labels in first column
    for table in soup.find_all("table"):
        for tr in table.find_all("tr"):
            th = tr.find("th")
            td = tr.find("td")
            if not th or not td:
                continue
            label = th.get_text(strip=True)
            value = td.get_text(" ", strip=True)
            if label in info_map and value:
                info_map[label] = value

    # Socials can be in separate sections with icons/links
    for a in soup.find_all("a"):
        href = a.get("href") or ""
        text = a.get_text(strip=True)
        if "twitter.com" in href and not socials["Twitter"]:
            socials["Twitter"] = href
        elif "instagram.com" in href and not socials["Instagram"]:
            socials["Instagram"] = href
        elif "facebook.com" in href and not socials["Facebook"]:
            socials["Facebook"] = href
        elif "wikipedia.org" in href and not socials["Wikipedia"]:
            socials["Wikipedia"] = href
        elif href and text.lower() in {"official website", "website"} and not socials["Website"]:
            socials["Website"] = href

    return WorkerProfile(
        worker_id=worker_id,
        ring_name=info_map.get("Ring Name"),
        birth_name=info_map.get("Birth Name"),
        birthday=info_map.get("Birthday"),
        birthplace=info_map.get("Birth Place"),
        height=info_map.get("Height"),
        weight=info_map.get("Weight"),
        debut=info_map.get("Debut"),
        twitter=socials.get("Twitter"),
        instagram=socials.get("Instagram"),
        facebook=socials.get("Facebook"),
        wikipedia=socials.get("Wikipedia"),
        website=socials.get("Website"),
    )


def write_csv(path: str, rows: Iterable[Dict[str, Optional[str]]]) -> None:
    rows_list = list(rows)
    if not rows_list:
        return
    fieldnames = list(rows_list[0].keys())
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows_list)


def can_fetch_robots(session: requests.Session, path: str) -> bool:
    try:
        text = session.get(ROBOTS_URL, headers=HEADERS, timeout=20).text
    except Exception:
        return True
    # Simplistic Disallow check
    disallows: List[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith("disallow:"):
            disallows.append(line.split(":", 1)[1].strip())
    from urllib.parse import urlparse

    p = urlparse(path)
    req_path = p.path or "/"
    return not any(req_path.startswith(d) for d in disallows)


@app.command()
def scrape(
    out_dir: str = typer.Option("./data", help="Output directory for CSV files"),
    limit: int = typer.Option(50, help="Limit number of workers from list (0 for all)"),
    rate: float = typer.Option(1.0, help="Seconds to wait between requests"),
) -> None:
    """Scrape worker list and profiles into two CSVs: workers.csv and profiles.csv"""
    import os
    os.makedirs(out_dir, exist_ok=True)

    session = requests.Session()

    if not can_fetch_robots(session, LIST_URL):
        typer.echo("Blocked by robots.txt for the list URL.")
        raise typer.Exit(code=2)

    typer.echo("Fetching workers list...")
    list_resp = polite_get(session, LIST_URL, rate)
    workers = parse_worker_list(list_resp.text)
    if limit and limit > 0:
        workers = workers[:limit]
    typer.echo(f"Found {len(workers)} workers in list (after limit).")

    # Write worker list table
    write_csv(
        os.path.join(out_dir, "workers.csv"),
        (asdict(w) for w in workers),
    )

    # Profiles
    profiles: List[WorkerProfile] = []
    for w in tqdm(workers, desc="Profiles"):
        if not can_fetch_robots(session, w.profile_url):
            continue
        try:
            resp = polite_get(session, w.profile_url, rate)
            profiles.append(parse_worker_profile(resp.text, w.worker_id))
        except Exception:
            continue

    write_csv(
        os.path.join(out_dir, "profiles.csv"),
        (asdict(p) for p in profiles),
    )

    typer.echo("Done. CSVs written in " + out_dir)


def iter_all_workers(session: requests.Session, rate: float, max_pages: int = 0) -> Iterable[WorkerRow]:
    page_index = 0
    offset = 0
    while True:
        url = LIST_URL + ("&s=" + str(offset) if offset else "")
        resp = polite_get(session, url, rate)
        rows = parse_worker_list(resp.text)
        if not rows:
            break
        for r in rows:
            yield r
        page_index += 1
        if max_pages and page_index >= max_pages:
            break
        offset += 100


PROMOTION_NAME_BY_KEY = {
    "wwe": "World Wrestling Entertainment",
    "aew": "All Elite Wrestling",
}

PROMOTION_ID_BY_KEY = {
    "wwe": 1,
    "aew": 2287,
}


def parse_promotion_roster_page(html: str, promotion_name: str) -> List[WorkerRow]:
    soup = BeautifulSoup(html, "lxml")
    rows: List[WorkerRow] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "id=2" in href and "nr=" in href:
            text = a.get_text(strip=True)
            # Extract id
            try:
                from urllib.parse import parse_qs, urlparse

                url = BASE_URL.rstrip("/") + "/" + href.lstrip("/")
                qs = parse_qs(urlparse(url).query)
                worker_id = (qs.get("nr") or [""])[0]
            except Exception:
                worker_id = ""
            if not worker_id or worker_id in seen:
                continue
            seen.add(worker_id)
            rows.append(
                WorkerRow(
                    worker_id=worker_id,
                    ring_name=text,
                    birthday=None,
                    birthplace=None,
                    height_cm=None,
                    weight_kg=None,
                    promotion=promotion_name,
                    rating=None,
                    votes=None,
                    profile_url=BASE_URL.rstrip("/") + "/" + href.lstrip("/"),
                )
            )
    return rows


@app.command()
def rosters(
    promotions: List[str] = typer.Option(["wwe", "aew"], help="Promotions to scrape: wwe, aew"),
    out_dir: str = typer.Option("./data/rosters", help="Base output directory"),
    rate: float = typer.Option(1.0, help="Seconds to wait between requests"),
    max_pages: int = typer.Option(0, help="Max pages of the global list to scan if fallback used (0=all)"),
    profiles: bool = typer.Option(True, help="Whether to fetch profiles"),
    profile_limit: int = typer.Option(0, help="Limit number of profiles per promotion (0=all)"),
) -> None:
    """Scrape rosters for selected promotions using promotion roster pages if available, else fallback to scanning the global list."""
    import os
    os.makedirs(out_dir, exist_ok=True)

    session = requests.Session()
    if not can_fetch_robots(session, LIST_URL):
        typer.echo("Blocked by robots.txt for the list URL.")
        raise typer.Exit(code=2)

    targets = []
    for key in promotions:
        key_norm = key.lower()
        if key_norm not in PROMOTION_NAME_BY_KEY:
            raise typer.BadParameter(f"Unknown promotion: {key}")
        targets.append((key_norm, PROMOTION_NAME_BY_KEY[key_norm], PROMOTION_ID_BY_KEY[key_norm]))

    # Attempt direct roster fetch first
    fetched_by_key: dict[str, List[WorkerRow]] = {}
    for key, promo_name, promo_id in targets:
        roster_url = f"{BASE_URL}?id=8&nr={promo_id}&page=15"
        try:
            resp = polite_get(session, roster_url, rate)
            rows = parse_promotion_roster_page(resp.text, promo_name)
        except Exception:
            rows = []
        if rows:
            fetched_by_key[key] = rows
            typer.echo(f"{key.upper()}: fetched {len(rows)} from promotion roster page.")

    # Fallback: scan global list if any target missing
    missing_keys = [k for k, _, _ in targets if k not in fetched_by_key]
    if missing_keys:
        typer.echo("Scanning global workers list for missing promotions...")
        all_rows = list(iter_all_workers(session, rate, max_pages=max_pages))
        for key, promo_name, _ in targets:
            if key in fetched_by_key:
                continue
            subset = [r for r in all_rows if (r.promotion or "").strip() == promo_name]
            fetched_by_key[key] = subset
            typer.echo(f"{key.upper()}: {len(subset)} workers matched promotion '{promo_name}'.")

    for key, promo_name, _ in targets:
        subset = fetched_by_key.get(key, [])

        # Write workers subset
        workers_path = os.path.join(out_dir, f"{key}_workers.csv")
        write_csv(workers_path, (asdict(w) for w in subset))

        # Fetch and write profiles
        if profiles:
            prof_list: List[WorkerProfile] = []
            subset_iter = subset if profile_limit == 0 else subset[:profile_limit]
            for w in tqdm(subset_iter, desc=f"{key.upper()} profiles"):
                if not can_fetch_robots(session, w.profile_url):
                    continue
                try:
                    resp = polite_get(session, w.profile_url, rate)
                    prof_list.append(parse_worker_profile(resp.text, w.worker_id))
                except Exception:
                    continue
            profiles_path = os.path.join(out_dir, f"{key}_profiles.csv")
            write_csv(profiles_path, (asdict(p) for p in prof_list))
            typer.echo(f"Wrote {workers_path} and {profiles_path}")
        else:
            typer.echo(f"Wrote {workers_path}")

