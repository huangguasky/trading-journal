# Trading Journal

Trading Journal is a Tauri desktop stock research workstation. It focuses on a closed research loop:

```text
collect market and stock information
-> strategy analysis
-> structured report
-> follow-up performance tracking
-> review and improve decisions
```

It borrows a proven technical direction, but uses a different product shape and a smaller codebase:

- Tauri desktop app
- Rust shell for local process management
- Python local core API
- SQLite storage
- fixed pipelines for automated watchlist and market analysis
- ReAct only for flexible chat questions

## Architecture

```text
desktop/                 Tauri + React workspace
engine/
  app.py                 Local HTTP API
  config.py              Runtime settings
  runtime.py             CLI/runtime helpers
  data/                  Quotes, history, market context and news
  indicators/            Trend, momentum, volume, levels, chips
  strategies/            Strategy registry and builtin yaml files
  agent/                 Lightweight ReAct loop and tools
  analysis/              Stock pipeline, market pipeline, reports, tracking
  storage/               SQLite access and migrations
  tests/                 Core tests
```

## Main Workflows

### Watchlist Pipeline

Stable and deterministic. It always collects quote, history, indicators, news and strategy evidence before asking the optional LLM to explain conflicts.

```text
watchlist
-> market data
-> indicators
-> news and risks
-> strategy router
-> structured report
-> save history
-> create tracking task
```

### Market Review Pipeline

Fixed flow for CN, HK and US market review. Output follows a structured schema with market regime, score, indices, breadth, sector rotation, macro news, risk flags and tomorrow watch.

### Chat

Chat uses a small ReAct loop because user questions are open-ended. Tools include quote, history, indicators, news, last report, signal tracking and market context.

## Run

### Prerequisites

- Python 3.10 or later installed in the Conda environment named `tj`. Verify it
  with `conda run -n tj python --version`.

Install all providers and the engine together (there are no optional provider extras):

```powershell
conda run -n tj python -m pip install -e .
```

Engine only:

```powershell
conda run -n tj python -m engine.app
```

Command-line analysis:

```powershell
# Analyze a single stock
conda run -n tj python -m engine.runtime --stock AAPL

# Analyze multiple watchlist symbols
conda run -n tj python -m engine.runtime --watchlist AAPL MSFT 600519

# Analyze a market (cn, hk, or us)
conda run -n tj python -m engine.runtime --market cn
```

The commands print analysis results directly to the terminal. After installing the
project with `pip install -e .`, `tj-runtime` can be used instead of
`python -m engine.runtime`.

Desktop:

```powershell
cd desktop
npm install
npm run tauri:dev
```

All LLM, market-data and news credentials are managed only on the desktop Settings page. Environment variables are not read. Providers are tried in capability order and validated by their real response; when every source fails, the report lists missing sources and remediation instead of falling back to sample data.
