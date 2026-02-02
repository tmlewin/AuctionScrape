# ProcureWatch

**AI-powered procurement/tender scraper** - Point it at any government tender website and it extracts opportunities automatically using AI. No CSS selectors or manual configuration needed.

---

## Quick Start (2 Minutes)

### 1. Install Dependencies

```bash
# Using uv (recommended)
uv sync

# Or using pip
pip install -e .
```

### 2. Set Up Your API Key (FREE)

Get a free Groq API key at: https://console.groq.com/

Create a `.env` file in the project root:

```env
GROQ_API_KEY=gsk_your_key_here
CRAWL4AI_LLM_PROVIDER=groq/llama-3.3-70b-versatile
```

### 3. Scrape Your First Website

```bash
# Basic scrape (single page)
python -m procurewatch.cli.main quick scrape https://purchasing.alberta.ca/search

# Multi-page scrape (5 pages)
python -m procurewatch.cli.main quick scrape https://purchasing.alberta.ca/search --max-pages 5

# Save results to JSON
python -m procurewatch.cli.main quick scrape https://purchasing.alberta.ca/search -o results.json
```

That's it! The AI figures out the page structure automatically.

---

## Common Use Cases

### Scrape Multiple Pages

```bash
# Scrape up to 10 pages with auto-pagination detection
python -m procurewatch.cli.main quick scrape https://example.com/tenders --max-pages 10
```

### Filter by Keywords

```bash
# Only extract opportunities mentioning "IT" or "software"
python -m procurewatch.cli.main quick scrape https://example.com --keywords "IT,software"
```

### Filter by Status

```bash
# Only open opportunities
python -m procurewatch.cli.main quick scrape https://example.com --status open
```

### Filter by Date

```bash
# Posted in last 30 days, closing within 14 days
python -m procurewatch.cli.main quick scrape https://example.com --since 30 --closing-within 14
```

### Deep Scrape (Follow Links)

```bash
# Follow detail page links to get full descriptions
python -m procurewatch.cli.main quick scrape https://example.com --deep --max-pages 3
```

### Export to JSON

```bash
# Save results to a file
python -m procurewatch.cli.main quick scrape https://example.com -o results.json
```

### Save to Database

```bash
# Initialize database first (one time)
python -m procurewatch.cli.main init

# Then scrape with --save flag
python -m procurewatch.cli.main quick scrape https://example.com --save
```

---

## All Options Reference

```
python -m procurewatch.cli.main quick scrape [URL] [OPTIONS]

PAGINATION:
  --max-pages, -p N      Maximum pages to scrape (default: 1)
  --pagination TYPE      auto, click_next, load_more, infinite_scroll, none
  --next-selector CSS    Custom CSS selector for Next button

FILTERS:
  --keywords, -k TEXT    Comma-separated keywords (e.g., "IT,software")
  --status TEXT          Status filter: open, closed, awarded
  --categories TEXT      Comma-separated categories
  --since N              Only posted within N days
  --closing-within N     Only closing within N days
  --location TEXT        Geographic location filter
  --min-value N          Minimum opportunity value
  --max-value N          Maximum opportunity value

DEEP SCRAPE:
  --deep                 Follow detail page links for full descriptions
  --max-details N        Maximum detail pages to scrape (default: 50)

OUTPUT:
  --output, -o PATH      Save results to JSON file
  --save, -s             Save opportunities to database

ADVANCED:
  --provider TEXT        LLM provider (default: from .env)
  --headed               Show browser window (for debugging)
  --delay N              Delay between pages in ms (default: 2000)
  --retries N            Max retry attempts (default: 3)
  --stop-on-error        Stop on first error
  --generate-config, -g  Generate reusable YAML config
```

---

## LLM Providers

### Groq (Recommended - FREE)

```env
GROQ_API_KEY=gsk_your_key_here
CRAWL4AI_LLM_PROVIDER=groq/llama-3.3-70b-versatile
```

**Limits**: 12,000 tokens/minute (free), 30,000 tokens/minute (dev tier)

Get key at: https://console.groq.com/

### Ollama (Local - FREE & Unlimited)

```bash
# Install Ollama first: https://ollama.ai
ollama pull llama3.3

# Use in scraper
python -m procurewatch.cli.main quick scrape https://example.com --provider ollama/llama3.3
```

### OpenAI

```env
OPENAI_API_KEY=sk-your-key-here
CRAWL4AI_LLM_PROVIDER=openai/gpt-4o-mini
```

### DeepSeek

```env
DEEPSEEK_API_KEY=sk-your-key-here
CRAWL4AI_LLM_PROVIDER=deepseek/deepseek-chat
```

---

## Understanding the Output

When you run a scrape, you'll see:

```
Page 1/5 - 10 opportunities
Page 2/5 - 10 opportunities
...

Results:
  Pages scraped: 5/5
  Opportunities: 42
  Pagination: click_next
  Avg confidence: 88.5%
  Time: 45.2s

Sample opportunities:
  1. Road Construction Project 2026
     ID: AB-2026-00123
     Agency: City of Edmonton
     Status: Open
     Closes: Mar 15, 2026
```

### Confidence Score

| Score | Meaning |
|-------|---------|
| 85-100% | Excellent - All fields extracted correctly |
| 70-85% | Good - Most fields extracted, some may be missing |
| 50-70% | Fair - Basic info extracted, many fields missing |
| <50% | Poor - Extraction may have failed |

### Rate Limit Errors

If you see:
```
Rate limit error: Limit 12000, Used 11008, Requested 3934
Waiting for 2 seconds before retrying...
```

This means you're hitting Groq's free tier limit. Solutions:
1. **Add more delay**: `--delay 15000` (15 seconds between pages)
2. **Upgrade to Groq Dev tier** (free, just needs credit card)
3. **Use Ollama locally** (unlimited)

---

## Troubleshooting

### "GROQ_API_KEY not set"

Create a `.env` file in the project root:
```env
GROQ_API_KEY=gsk_your_key_here
```

### Windows Unicode Errors

If you see `'charmap' codec can't encode character`:

```bash
# Run with UTF-8 encoding
set PYTHONIOENCODING=utf-8
python -m procurewatch.cli.main quick scrape https://example.com
```

Or use the test script which handles this automatically:
```bash
python test_multipage.py
```

### "Browser not installed"

```bash
# Install Playwright browsers
playwright install chromium
```

### Low Confidence on Some Pages

- **Rate limiting**: Increase delay with `--delay 15000`
- **Complex page structure**: Try `--headed` to see what's happening
- **Dynamic content**: Add `--delay 5000` to wait for content to load

---

## Project Structure

```
ProcureWatch/
├── .env                    # Your API keys (create this)
├── configs/portals/        # Saved portal configurations
├── data/                   # SQLite database (after init)
├── src/procurewatch/
│   ├── cli/                # Command-line interface
│   ├── core/
│   │   ├── backends/       # Crawl4AI, Playwright, HTTP scrapers
│   │   ├── extract/        # Data extraction logic
│   │   └── normalize/      # Date/value parsing
│   └── persistence/        # Database models
└── test_multipage.py       # Quick test script
```

---

## Architecture Overview

```
┌────────────────────────────────────────────────────────────┐
│                    HOW IT WORKS                            │
├────────────────────────────────────────────────────────────┤
│                                                            │
│  1. BROWSER (Crawl4AI + Playwright)                        │
│     → Loads page, executes JavaScript, renders content     │
│                                                            │
│  2. PAGINATION (Heuristic Detection)                       │
│     → Finds "Next" button using 50+ CSS patterns           │
│     → No AI needed - fast and free                         │
│                                                            │
│  3. EXTRACTION (LLM-Powered)                               │
│     → AI reads page content                                │
│     → Extracts: title, agency, dates, status, etc.         │
│     → Works on ANY website automatically                   │
│                                                            │
│  4. STORAGE (SQLite)                                       │
│     → Saves opportunities with deduplication               │
│     → Tracks changes over time                             │
│                                                            │
└────────────────────────────────────────────────────────────┘
```

---

## Examples

### Alberta Purchasing Connection

```bash
python -m procurewatch.cli.main quick scrape https://purchasing.alberta.ca/search --max-pages 5 -o alberta.json
```

### MERX (Canada)

```bash
python -m procurewatch.cli.main quick scrape https://www.merx.com/search --max-pages 3 --keywords "construction"
```

### AusTender (Australia)

```bash
python -m procurewatch.cli.main quick scrape https://www.tenders.gov.au/search --max-pages 5
```

---

## Tips for Best Results

1. **Start small**: Test with 1-2 pages first
2. **Use filters**: Narrow down with `--keywords` and `--status open`
3. **Increase delay for free tier**: `--delay 15000` (15 seconds)
4. **Watch the browser**: Use `--headed` to see what's happening
5. **Export results**: Always use `-o results.json` to save your work

---

## Need Help?

- Check the logs for detailed error messages
- Use `--headed` to see the browser in action
- Try `python test_multipage.py` for a quick test
- Reduce `--max-pages` if hitting rate limits

---

## License

MIT License - Use freely for personal or commercial projects.
