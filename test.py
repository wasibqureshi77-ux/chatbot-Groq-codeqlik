#!/usr/bin/env python3
"""
Reusable Website Scraper for RAG / Chatbot Knowledge Base

Features:
- Crawls same-domain pages from a start URL
- Optionally reads sitemap.xml
- Extracts title, meta description, headings, paragraphs, lists, tables, links, image alt text
- Removes scripts/styles/nav noise as much as possible
- Saves:
  1. scraped_pages.json
  2. rag_chunks.jsonl
  3. scraped_pages.md

Install:
    pip install requests beautifulsoup4 lxml

Example:
    python scrape_website.py --url https://codeqlik.com/ --max-pages 100 --out data/codeqlik_scrape

Notes:
- For JavaScript-heavy websites, requests may not see all rendered text.
  In that case use Playwright/Selenium version.
- Always respect a website's robots.txt, terms, and rate limits.
"""

import argparse
import json
import re
import time
from collections import deque
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import urljoin, urlparse, urlunparse, urldefrag
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup


SKIP_EXTENSIONS = (
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".ico",
    ".pdf", ".zip", ".rar", ".7z",
    ".mp4", ".mp3", ".avi", ".mov", ".webm",
    ".css", ".js", ".map",
    ".woff", ".woff2", ".ttf", ".eot",
    ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx"
)

NOISE_SELECTORS = [
    "script", "style", "noscript", "iframe", "svg",
    "header", "footer", "nav",
    ".navbar", ".menu", ".sidebar", ".breadcrumb",
    ".cookie", ".cookies", ".popup", ".modal",
    ".advertisement", ".ads", ".ad",
]


@dataclass
class ScrapedPage:
    url: str
    status_code: int
    title: str
    meta_description: str
    h1: List[str]
    h2: List[str]
    h3: List[str]
    headings: List[str]
    paragraphs: List[str]
    lists: List[str]
    tables: List[Dict]
    links: List[Dict]
    image_alts: List[str]
    clean_text: str
    word_count: int
    scraped_at: str


def normalize_url(url: str) -> str:
    """
    Normalize URL to reduce duplicate crawl.
    Removes fragments, trims trailing slash except root, removes common tracking params.
    """
    url, _fragment = urldefrag(url)
    parsed = urlparse(url)

    # Normalize scheme and host
    scheme = parsed.scheme.lower() or "https"
    netloc = parsed.netloc.lower()

    # Remove common tracking query params
    query = parsed.query
    if query:
        kept = []
        for part in query.split("&"):
            key = part.split("=", 1)[0].lower()
            if not (
                key.startswith("utm_")
                or key in {"fbclid", "gclid", "mc_cid", "mc_eid"}
            ):
                kept.append(part)
        query = "&".join(kept)

    path = re.sub(r"/+", "/", parsed.path or "/")
    if path != "/" and path.endswith("/"):
        path = path[:-1]

    return urlunparse((scheme, netloc, path, "", query, ""))


def is_valid_url(url: str, base_netloc: str, include_subdomains: bool = False) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False

    netloc = parsed.netloc.lower()
    base_netloc = base_netloc.lower()

    if include_subdomains:
        if not (netloc == base_netloc or netloc.endswith("." + base_netloc)):
            return False
    else:
        if netloc != base_netloc:
            return False

    path_lower = parsed.path.lower()
    if path_lower.endswith(SKIP_EXTENSIONS):
        return False

    # Skip common non-content paths
    skip_patterns = [
        "/wp-admin", "/admin", "/login", "/signup",
        "/cart", "/checkout", "/account",
        "mailto:", "tel:",
    ]
    if any(pattern in url.lower() for pattern in skip_patterns):
        return False

    return True


def get_robot_parser(base_url: str, user_agent: str) -> Optional[RobotFileParser]:
    parsed = urlparse(base_url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"

    rp = RobotFileParser()
    rp.set_url(robots_url)

    try:
        rp.read()
        return rp
    except Exception:
        return None


def fetch_html(
    session: requests.Session,
    url: str,
    timeout: int,
) -> Tuple[int, str, str]:
    """
    Return: status_code, content_type, text
    """
    try:
        response = session.get(url, timeout=timeout, allow_redirects=True)
        content_type = response.headers.get("content-type", "")
        if "text/html" not in content_type.lower():
            return response.status_code, content_type, ""
        return response.status_code, content_type, response.text
    except requests.RequestException:
        return 0, "", ""


def discover_sitemap_urls(
    session: requests.Session,
    base_url: str,
    base_netloc: str,
    timeout: int,
    include_subdomains: bool = False,
) -> List[str]:
    """
    Try /sitemap.xml and extract URLs.
    Supports sitemap index and simple urlset.
    """
    parsed = urlparse(base_url)
    sitemap_url = f"{parsed.scheme}://{parsed.netloc}/sitemap.xml"

    discovered: List[str] = []
    queue = deque([sitemap_url])
    seen_sitemaps: Set[str] = set()

    while queue and len(seen_sitemaps) < 20:
        sm_url = queue.popleft()
        if sm_url in seen_sitemaps:
            continue
        seen_sitemaps.add(sm_url)

        try:
            res = session.get(sm_url, timeout=timeout)
            if res.status_code >= 400 or not res.text.strip():
                continue

            soup = BeautifulSoup(res.text, "xml")
            locs = [loc.get_text(strip=True) for loc in soup.find_all("loc")]

            for loc in locs:
                loc = normalize_url(loc)
                if loc.endswith(".xml"):
                    queue.append(loc)
                elif is_valid_url(loc, base_netloc, include_subdomains):
                    discovered.append(loc)

        except requests.RequestException:
            continue

    # De-duplicate while keeping order
    unique = []
    seen = set()
    for u in discovered:
        if u not in seen:
            unique.append(u)
            seen.add(u)

    return unique


def clean_space(text: str) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text


def remove_noise(soup: BeautifulSoup) -> None:
    for selector in NOISE_SELECTORS:
        for tag in soup.select(selector):
            tag.decompose()


def extract_table(table_tag) -> Dict:
    headers = []
    rows = []

    header_cells = table_tag.select("thead th")
    if header_cells:
        headers = [clean_space(cell.get_text(" ")) for cell in header_cells]

    for tr in table_tag.select("tr"):
        cells = tr.find_all(["td", "th"])
        row = [clean_space(cell.get_text(" ")) for cell in cells]
        row = [x for x in row if x]
        if row:
            rows.append(row)

    if not headers and rows:
        # Sometimes first row is header-like
        headers = rows[0]
        rows = rows[1:]

    return {
        "headers": headers,
        "rows": rows
    }


def extract_page(url: str, status_code: int, html: str) -> ScrapedPage:
    soup = BeautifulSoup(html, "lxml")

    title = clean_space(soup.title.get_text(" ")) if soup.title else ""

    meta_description = ""
    meta_tag = soup.find("meta", attrs={"name": re.compile(r"^description$", re.I)})
    if meta_tag and meta_tag.get("content"):
        meta_description = clean_space(meta_tag["content"])

    # Extract visible URL links before removing nav/footer if needed
    raw_links = []
    for a in soup.find_all("a", href=True):
        text = clean_space(a.get_text(" "))
        href = normalize_url(urljoin(url, a["href"]))
        if text or href:
            raw_links.append({"text": text, "href": href})

    image_alts = []
    for img in soup.find_all("img"):
        alt = clean_space(img.get("alt", ""))
        if alt:
            image_alts.append(alt)

    remove_noise(soup)

    h1 = [clean_space(x.get_text(" ")) for x in soup.find_all("h1")]
    h2 = [clean_space(x.get_text(" ")) for x in soup.find_all("h2")]
    h3 = [clean_space(x.get_text(" ")) for x in soup.find_all("h3")]

    headings = []
    for tag in soup.find_all(re.compile(r"^h[1-6]$")):
        txt = clean_space(tag.get_text(" "))
        if txt:
            headings.append(txt)

    paragraphs = []
    for tag in soup.find_all(["p"]):
        txt = clean_space(tag.get_text(" "))
        if len(txt) >= 25:
            paragraphs.append(txt)

    lists = []
    for tag in soup.find_all(["li"]):
        txt = clean_space(tag.get_text(" "))
        if len(txt) >= 3:
            lists.append(txt)

    tables = []
    for table in soup.find_all("table"):
        data = extract_table(table)
        if data["headers"] or data["rows"]:
            tables.append(data)

    # Main clean text from body
    body = soup.body or soup
    clean_text = clean_space(body.get_text(" "))

    # Remove repeated short whitespace and very tiny pages
    words = clean_text.split()
    word_count = len(words)

    # De-duplicate simple lists
    def dedupe(items: List[str]) -> List[str]:
        out = []
        seen = set()
        for item in items:
            key = item.lower()
            if key not in seen:
                out.append(item)
                seen.add(key)
        return out

    return ScrapedPage(
        url=url,
        status_code=status_code,
        title=title,
        meta_description=meta_description,
        h1=dedupe(h1),
        h2=dedupe(h2),
        h3=dedupe(h3),
        headings=dedupe(headings),
        paragraphs=dedupe(paragraphs),
        lists=dedupe(lists),
        tables=tables,
        links=raw_links[:300],
        image_alts=dedupe(image_alts),
        clean_text=clean_text,
        word_count=word_count,
        scraped_at=time.strftime("%Y-%m-%d %H:%M:%S"),
    )


def extract_internal_links(html: str, current_url: str, base_netloc: str, include_subdomains: bool) -> List[str]:
    soup = BeautifulSoup(html, "lxml")
    links = []

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        absolute = normalize_url(urljoin(current_url, href))
        if is_valid_url(absolute, base_netloc, include_subdomains):
            links.append(absolute)

    # De-duplicate while keeping order
    unique = []
    seen = set()
    for link in links:
        if link not in seen:
            unique.append(link)
            seen.add(link)

    return unique


def make_chunks(page: ScrapedPage, max_words: int = 450, overlap_words: int = 60) -> List[Dict]:
    """
    Convert page clean text into RAG-friendly chunks.
    """
    words = page.clean_text.split()
    chunks = []

    if not words:
        return chunks

    start = 0
    idx = 1

    while start < len(words):
        end = min(start + max_words, len(words))
        chunk_words = words[start:end]
        text = " ".join(chunk_words).strip()

        if text:
            chunks.append({
                "chunk_id": f"{slugify(page.title or page.url)}_{idx:03d}",
                "source_url": page.url,
                "title": page.title,
                "meta_description": page.meta_description,
                "word_count": len(chunk_words),
                "text": text
            })

        if end == len(words):
            break

        start = max(0, end - overlap_words)
        idx += 1

    return chunks


def slugify(text: str, max_len: int = 70) -> str:
    text = text.lower()
    text = re.sub(r"https?://", "", text)
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = text.strip("_")
    return text[:max_len] or "page"


def write_outputs(pages: List[ScrapedPage], output_dir: Path, chunk_words: int, overlap_words: int) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    pages_data = [asdict(page) for page in pages]

    json_path = output_dir / "scraped_pages.json"
    json_path.write_text(json.dumps(pages_data, ensure_ascii=False, indent=2), encoding="utf-8")

    all_chunks = []
    for page in pages:
        all_chunks.extend(make_chunks(page, max_words=chunk_words, overlap_words=overlap_words))

    jsonl_path = output_dir / "rag_chunks.jsonl"
    jsonl_path.write_text(
        "\n".join(json.dumps(chunk, ensure_ascii=False) for chunk in all_chunks),
        encoding="utf-8"
    )

    md_path = output_dir / "scraped_pages.md"
    md_lines = [
        "# Scraped Website Data",
        "",
        f"Pages scraped: {len(pages)}",
        f"RAG chunks: {len(all_chunks)}",
        "",
    ]

    for page in pages:
        md_lines.append(f"## {page.title or page.url}")
        md_lines.append("")
        md_lines.append(f"URL: {page.url}")
        md_lines.append(f"Status: {page.status_code}")
        md_lines.append(f"Words: {page.word_count}")
        if page.meta_description:
            md_lines.append(f"Meta description: {page.meta_description}")
        md_lines.append("")

        if page.headings:
            md_lines.append("### Headings")
            for h in page.headings:
                md_lines.append(f"- {h}")
            md_lines.append("")

        if page.paragraphs:
            md_lines.append("### Paragraphs")
            for p in page.paragraphs:
                md_lines.append(f"- {p}")
            md_lines.append("")

        if page.lists:
            md_lines.append("### List Items")
            for item in page.lists[:150]:
                md_lines.append(f"- {item}")
            md_lines.append("")

        md_lines.append("### Clean Text")
        md_lines.append(page.clean_text)
        md_lines.append("")

    md_path.write_text("\n".join(md_lines), encoding="utf-8")

    print("\nDone.")
    print(f"Pages JSON: {json_path}")
    print(f"RAG JSONL:  {jsonl_path}")
    print(f"Markdown:   {md_path}")
    print(f"Pages scraped: {len(pages)}")
    print(f"RAG chunks: {len(all_chunks)}")


def crawl(args) -> List[ScrapedPage]:
    start_url = normalize_url(args.url)
    parsed = urlparse(start_url)
    base_netloc = parsed.netloc.lower()

    session = requests.Session()
    session.headers.update({
        "User-Agent": args.user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    })

    robot_parser = None
    if args.respect_robots:
        robot_parser = get_robot_parser(start_url, args.user_agent)

    queue = deque([start_url])
    queued: Set[str] = {start_url}
    visited: Set[str] = set()
    pages: List[ScrapedPage] = []

    if args.use_sitemap:
        sitemap_urls = discover_sitemap_urls(
            session=session,
            base_url=start_url,
            base_netloc=base_netloc,
            timeout=args.timeout,
            include_subdomains=args.include_subdomains,
        )
        for u in sitemap_urls:
            if u not in queued:
                queue.append(u)
                queued.add(u)

        if sitemap_urls:
            print(f"Discovered {len(sitemap_urls)} sitemap URLs")

    while queue and len(pages) < args.max_pages:
        url = queue.popleft()

        if url in visited:
            continue

        visited.add(url)

        if robot_parser and not robot_parser.can_fetch(args.user_agent, url):
            print(f"Blocked by robots.txt: {url}")
            continue

        print(f"[{len(pages)+1}/{args.max_pages}] Fetching: {url}")

        status_code, content_type, html = fetch_html(session, url, args.timeout)

        if not html:
            print(f"  skipped: status={status_code}, content_type={content_type}")
            time.sleep(args.delay)
            continue

        page = extract_page(url, status_code, html)

        if page.word_count >= args.min_words:
            pages.append(page)
            print(f"  saved: {page.word_count} words | title={page.title[:80]}")
        else:
            print(f"  skipped: only {page.word_count} words")

        if args.crawl_links:
            links = extract_internal_links(html, url, base_netloc, args.include_subdomains)
            for link in links:
                if link not in visited and link not in queued and len(queued) < args.max_queue:
                    queue.append(link)
                    queued.add(link)

        time.sleep(args.delay)

    return pages


def parse_args():
    parser = argparse.ArgumentParser(description="Crawl and scrape a website into JSON/JSONL/Markdown.")
    parser.add_argument("--url", required=True, help="Start URL, e.g. https://codeqlik.com/")
    parser.add_argument("--out", default="scraped_output", help="Output folder")
    parser.add_argument("--max-pages", type=int, default=100, help="Maximum pages to scrape")
    parser.add_argument("--max-queue", type=int, default=1000, help="Maximum URLs to keep in queue")
    parser.add_argument("--delay", type=float, default=1.0, help="Delay between requests in seconds")
    parser.add_argument("--timeout", type=int, default=20, help="Request timeout in seconds")
    parser.add_argument("--min-words", type=int, default=30, help="Skip pages below this word count")
    parser.add_argument("--chunk-words", type=int, default=450, help="RAG chunk size in words")
    parser.add_argument("--overlap-words", type=int, default=60, help="RAG chunk overlap in words")
    parser.add_argument("--user-agent", default="Mozilla/5.0 (compatible; RAGWebsiteScraper/1.0)")
    parser.add_argument("--include-subdomains", action="store_true", help="Allow subdomains")
    parser.add_argument("--no-sitemap", dest="use_sitemap", action="store_false", help="Do not read sitemap.xml")
    parser.add_argument("--no-crawl-links", dest="crawl_links", action="store_false", help="Only scrape start URL and sitemap URLs")
    parser.add_argument("--no-robots", dest="respect_robots", action="store_false", help="Do not check robots.txt")
    parser.set_defaults(use_sitemap=True, crawl_links=True, respect_robots=True)
    return parser.parse_args()


def main():
    args = parse_args()
    pages = crawl(args)
    write_outputs(
        pages=pages,
        output_dir=Path(args.out),
        chunk_words=args.chunk_words,
        overlap_words=args.overlap_words,
    )


if __name__ == "__main__":
    main()
