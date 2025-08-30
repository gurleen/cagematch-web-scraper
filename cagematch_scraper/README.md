## cagematch-scraper

Scrape wrestler data from cagematch.net into CSV files using Python and uv.

### Quick start

1) Ensure uv is installed, then inside the project:

```
uv run cagematch-scraper scrape --out-dir ./data --limit 20 --rate 1.0
```

This will create `./data/workers.csv` and `./data/profiles.csv`.

### CLI

```
cagematch-scraper scrape [OPTIONS]

Options:
  --out-dir PATH  Output directory (default: ./data)
  --limit INT     Number of workers from the list to process (0 for all)
  --rate FLOAT    Seconds delay between requests (default: 1.0)
```

### Notes

- Be respectful: keep a small `--rate` to avoid overloading the site.
- The parser is best-effort and may miss fields if the site structure changes.
