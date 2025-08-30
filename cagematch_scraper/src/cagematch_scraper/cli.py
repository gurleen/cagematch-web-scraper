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

