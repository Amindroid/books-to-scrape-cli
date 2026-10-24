# Books to Scrape CLI

A Python command-line tool for extracting book listings from
[Books to Scrape](https://books.toscrape.com/) and exporting
structured CSV and JSON data.

## Overview

This project demonstrates a web-scraping workflow: requesting HTML
pages, extracting book metadata, following pagination links,
and saving the collected records.

It is designed for the Books to Scrape catalog, not arbitrary websites.

## Features

- Extract book titles, prices, availability, ratings, and URLs.
- Include image URLs and source-page URLs in the output.
- Follow pagination links.
- Skip duplicate books based on their URLs.
- Export CSV, JSON, or both formats.
- Configure request timeouts, retries, and delays between pages.
- Limit the number of pages processed.
- Protect existing output files unless overwriting is requested.

## Technologies

- Python 3.10+
- requests
- BeautifulSoup
- urllib3
- argparse
- dataclasses
- Decimal

## Installation

Download or clone this repository and open a terminal
in the project directory.

Create a virtual environment on Windows:

```powershell
py -m venv .venv
```

Install dependencies:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

The following examples use this Windows virtual environment.

## Usage

Scrape one page and export CSV:

```powershell
.\.venv\Scripts\python.exe scraper.py --max-pages 1 --output output/books.csv
```

Scrape up to three pages and export JSON:

```powershell
.\.venv\Scripts\python.exe scraper.py --max-pages 3 --format json --output output/books.json
```

Export both CSV and JSON:

```powershell
.\.venv\Scripts\python.exe scraper.py --max-pages 3 --format both --output output/books
```

Configure request settings:

```powershell
.\.venv\Scripts\python.exe scraper.py --max-pages 2 --delay 2 --timeout 30 --retries 2 --output output/books.csv
```

Add `--overwrite` to replace existing output files.

Show all available options:

```powershell
.\.venv\Scripts\python.exe scraper.py --help
```

## Output Fields

| Field | Description |
| --- | --- |
| `title` | Book title |
| `price_gbp` | Listed price in GBP |
| `availability` | Availability text |
| `rating` | Numeric rating, when recognized |
| `book_url` | Absolute book-page URL |
| `image_url` | Absolute image URL |
| `source_page` | Catalog page containing the listing |

## Project Structure

```text
books-to-scrape-cli/
├── scraper.py
├── requirements.txt
├── README.md
└── .gitignore
```

The `output` directory is created locally when needed.

## Current Limitations

- Internet access and access to the target website are required.
- Changes to the site's HTML may require updating the selectors.
- Records are collected in memory before export.
- Automated tests are not yet included.

## Verification Status

A recent local run encountered a connection timeout before
the first page could be retrieved.

A successful end-to-end run of the latest revision has not yet
been confirmed.

## Responsible Use

Use this tool responsibly. Review the target site's terms and
robots.txt before running or adapting the scraper.

The script does not automatically check robots.txt.
Use reasonable request delays and avoid unnecessary requests.

## Planned Improvements

- Add offline tests using HTML fixtures and mocked requests.
- Validate that pages contain the expected catalog structure.
- Restrict pagination to the intended domain.
