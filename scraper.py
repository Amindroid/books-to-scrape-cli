#!/usr/bin/env python3
"""Responsibly scrape book listings from Books to Scrape.

This script targets https://books.toscrape.com/, a website created for
web-scraping practice. Always review a website's terms of use and robots.txt
before adapting this project to another website.

Examples:
    python scraper.py
    python scraper.py --max-pages 5 --output output/books.json
    python scraper.py --format both --delay 1.5 --overwrite --verbose
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
import time
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Literal
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup, Tag
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

DEFAULT_START_URL = "https://books.toscrape.com/"
DEFAULT_OUTPUT = Path("books.csv")
DEFAULT_DELAY_SECONDS = 1.0
DEFAULT_TIMEOUT_SECONDS = 20.0
DEFAULT_RETRIES = 3
USER_AGENT = "PortfolioBookScraper/1.0 (+https://github.com/your-username)"
OUTPUT_FIELDS = (
    "title",
    "price_gbp",
    "availability",
    "rating",
    "book_url",
    "image_url",
    "source_page",
)
OutputFormat = Literal["csv", "json", "both"]
RATING_MAP = {"One": 1, "Two": 2, "Three": 3, "Four": 4, "Five": 5}


@dataclass(frozen=True)
class Book:
    title: str
    price_gbp: Decimal | None
    availability: str
    rating: int | None
    book_url: str
    image_url: str
    source_page: str

    def to_row(self) -> dict[str, str | int | None]:
        row = asdict(self)
        row["price_gbp"] = str(self.price_gbp) if self.price_gbp is not None else None
        return row


@dataclass(frozen=True)
class ScrapeSummary:
    pages_requested: int
    pages_processed: int
    books_extracted: int
    duplicate_books_skipped: int
    stop_reason: Literal[
        "finished",
        "max_pages",
        "request_failed",
        "pagination_loop",
    ]


def configure_logging(verbose: bool) -> None:

    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )


def create_session(retries: int) -> requests.Session:

    retry_strategy = Retry(
        total=retries,
        connect=retries,
        read=retries,
        status=retries,
        backoff_factor=0.75,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"})
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def validate_start_url(url: str) -> str:

    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("--start-url must be a complete HTTP or HTTPS URL.")
    return url


def fetch_page(
    session: requests.Session, url: str, timeout: float
) -> BeautifulSoup:

    response = session.get(url, timeout=timeout)
    response.raise_for_status()
    return BeautifulSoup(response.text, "html.parser")


def text_or_empty(element: Tag | None) -> str:

    return element.get_text(" ", strip=True) if element else ""


def parse_price(value: str) -> Decimal | None:

    normalized = value.replace("£", "").replace("Â", "").strip()
    try:
        return Decimal(normalized)
    except (InvalidOperation, ValueError):
        logging.warning("Could not parse price value: %r", value)
        return None


def parse_rating(element: Tag | None) -> int | None:

    if element is None:
        return None
    classes = element.get("class", [])
    return next((RATING_MAP[name] for name in RATING_MAP if name in classes), None)


def extract_books(soup: BeautifulSoup, page_url: str) -> list[Book]:

    books: list[Book] = []

    for index, card in enumerate(soup.select("article.product_pod"), start=1):
        title_link = card.select_one("h3 a")
        price_element = card.select_one("p.price_color")
        image_element = card.select_one("div.image_container img")

        if title_link is None or price_element is None or image_element is None:
            logging.warning("Skipped malformed listing %s on %s", index, page_url)
            continue

        relative_book_url = title_link.get("href")
        relative_image_url = image_element.get("src")
        title = title_link.get("title", "").strip()

        if not title or not relative_book_url or not relative_image_url:
            logging.warning("Skipped incomplete listing %s on %s", index, page_url)
            continue

        books.append(
            Book(
                title=title,
                price_gbp=parse_price(text_or_empty(price_element)),
                availability=text_or_empty(card.select_one("p.instock")),
                rating=parse_rating(card.select_one("p.star-rating")),
                book_url=urljoin(page_url, relative_book_url),
                image_url=urljoin(page_url, relative_image_url),
                source_page=page_url,
            )
        )

    return books


def find_next_page(soup: BeautifulSoup, current_url: str) -> str | None:
    next_link = soup.select_one("li.next a")
    href = next_link.get("href") if next_link else None
    return urljoin(current_url, href) if href else None


def scrape_books(
    session: requests.Session,
    start_url: str,
    timeout: float,
    delay: float,
    max_pages: int | None,
) -> tuple[list[Book], ScrapeSummary]:
    current_url: str | None = start_url
    books: list[Book] = []

    seen_urls: set[str] = set()
    visited_pages: set[str] = set()

    pages_requested = 0
    pages_processed = 0
    duplicates_skipped = 0

    stop_reason: Literal[
        "finished",
        "max_pages",
        "request_failed",
        "pagination_loop",
    ] = "finished"

    while current_url is not None:
        if max_pages is not None and pages_processed >= max_pages:
            stop_reason = "max_pages"
            break

        if current_url in visited_pages:
            logging.error("Pagination loop detected: %s", current_url)
            stop_reason = "pagination_loop"
            break

        visited_pages.add(current_url)

        pages_requested += 1
        logging.info(
            "Fetching page %s: %s",
            pages_requested,
            current_url,
        )

        try:
            soup = fetch_page(session, current_url, timeout)
        except requests.RequestException as error:
            logging.error(
                "Could not fetch %s: %s",
                current_url,
                error,
            )
            stop_reason = "request_failed"
            break

        page_books = extract_books(soup, current_url)
        new_books = 0

        for book in page_books:
            if book.book_url in seen_urls:
                duplicates_skipped += 1
                continue

            seen_urls.add(book.book_url)
            books.append(book)
            new_books += 1

        pages_processed += 1

        logging.info(
            "Extracted %s unique book(s) from page %s",
            new_books,
            pages_processed,
        )

        current_url = find_next_page(soup, current_url)

        if (
            current_url is not None
            and current_url not in visited_pages
            and (
                max_pages is None
                or pages_processed < max_pages
            )
        ):
            logging.debug(
                "Waiting %.2f second(s) before the next request",
                delay,
            )
            time.sleep(delay)

    return books, ScrapeSummary(
        pages_requested=pages_requested,
        pages_processed=pages_processed,
        books_extracted=len(books),
        duplicate_books_skipped=duplicates_skipped,
        stop_reason=stop_reason,
    )


def output_paths(output: Path, output_format: OutputFormat) -> list[Path]:

    output = output.expanduser()
    formats = ("csv", "json") if output_format == "both" else (output_format,)

    if output_format != "both":
        expected_suffix = f".{output_format}"
        if output.suffix and output.suffix.lower() != expected_suffix:
            raise ValueError(f"Output must use the {expected_suffix} extension for --format {output_format}.")
        return [output.with_suffix(expected_suffix)]

    base = output.with_suffix("") if output.suffix else output
    return [base.with_suffix(f".{file_format}") for file_format in formats]


def prepare_output_paths(
    paths: Sequence[Path], overwrite: bool
) -> list[Path]:

    resolved_paths = [path.resolve() for path in paths]
    existing = [path for path in resolved_paths if path.exists()]
    if existing and not overwrite:
        names = ", ".join(str(path) for path in existing)
        raise FileExistsError(f"Output file(s) already exist: {names}. Use --overwrite to replace them.")

    for path in resolved_paths:
        path.parent.mkdir(parents=True, exist_ok=True)
    return resolved_paths


def write_csv(books: Iterable[Book], output: Path) -> None:
    
    with output.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=OUTPUT_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(book.to_row() for book in books)


def write_json(books: Iterable[Book], output: Path) -> None:

    rows = [book.to_row() for book in books]
    with output.open("w", encoding="utf-8") as file:
        json.dump(rows, file, indent=2, ensure_ascii=False)
        file.write("\n")


def write_outputs(books: Sequence[Book], paths: Sequence[Path]) -> None:

    for path in paths:
        if path.suffix.lower() == ".csv":
            write_csv(books, path)
        elif path.suffix.lower() == ".json":
            write_json(books, path)
        else:
            raise ValueError(f"Unsupported output extension: {path.suffix}")
        logging.info("Wrote %s record(s) to %s", len(books), path)


def build_parser() -> argparse.ArgumentParser:

    parser = argparse.ArgumentParser(
        description="Scrape book listings from Books to Scrape and export structured data.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--start-url",
        default=DEFAULT_START_URL,
        help="First catalog page to scrape.",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Output path. With --format both, this is used as the base filename.",
    )
    parser.add_argument(
        "--format",
        choices=("csv", "json", "both"),
        default="csv",
        help="Output format.",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="Maximum number of pages to scrape. Omit to scrape until the final page.",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=DEFAULT_DELAY_SECONDS,
        help="Seconds to wait between page requests.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="Timeout in seconds for each HTTP request.",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=DEFAULT_RETRIES,
        help="Retry count for temporary connection and server errors.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Allow replacement of existing output files.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show detailed diagnostic messages.",
    )
    return parser


def validate_arguments(args: argparse.Namespace) -> None:

    validate_start_url(args.start_url)
    if args.max_pages is not None and args.max_pages < 1:
        raise ValueError("--max-pages must be at least 1.")
    if args.delay < 0:
        raise ValueError("--delay cannot be negative.")
    if args.timeout <= 0:
        raise ValueError("--timeout must be greater than 0.")
    if args.retries < 0:
        raise ValueError("--retries cannot be negative.")


def main() -> int:

    args = build_parser().parse_args()
    configure_logging(args.verbose)

    try:
        validate_arguments(args)
        paths = prepare_output_paths(
            output_paths(args.output, args.format), args.overwrite
        )
    except (ValueError, FileExistsError, OSError) as error:
        logging.error("Invalid configuration: %s", error)
        return 2

    session = create_session(args.retries)
    try:
        books, summary = scrape_books(
            session=session,
            start_url=args.start_url,
            timeout=args.timeout,
            delay=args.delay,
            max_pages=args.max_pages,
        )
    finally:
        session.close()

    if summary.pages_processed == 0:
        logging.error("No pages were processed, so no output files were created.")
        return 1

    try:
        write_outputs(books, paths)
    except OSError as error:
        logging.error("Could not write output: %s", error)
        return 1
    
    if summary.stop_reason in {
        "request_failed",
        "pagination_loop",
    }:
        logging.warning(
            "Run incomplete (%s). Saved %s book(s) "
            "from %s processed page(s).",
            summary.stop_reason,
            summary.books_extracted,
            summary.pages_processed,
        )
        return 3
    logging.info(
        "Completed successfully. Pages processed: %s | Books collected: %s | Duplicate books skipped: %s",
        summary.pages_processed,
        summary.books_extracted,
        summary.duplicate_books_skipped,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
