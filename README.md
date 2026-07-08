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

Engine only:

```powershell
python -m engine.app
```

Desktop:

```powershell
cd desktop
npm install
npm run tauri:dev
```

Optional real market adapters:

```powershell
pip install -e .[data]
```

Optional OpenAI-compatible LLM:

```powershell
$env:OPENAI_API_KEY="..."
$env:OPENAI_BASE_URL="https://api.openai.com/v1"
$env:OPENAI_MODEL="gpt-4o-mini"
```

Without optional dependencies, the engine uses deterministic local sample data so the full research loop remains usable.

