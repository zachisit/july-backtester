# July Backtester

> A professional-grade Python engine for stress-testing US equity strategies with Monte Carlo simulation and Walk-Forward Analysis.

![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python&logoColor=white)
![License: MIT](https://img.shields.io/badge/License-MIT-green)
[![Tests](https://github.com/zachisit/july-backtester/actions/workflows/tests.yml/badge.svg)](https://github.com/zachisit/july-backtester/actions/workflows/tests.yml)

---

Tests trading strategies against full historical US equity data, runs 1,000-path Monte Carlo simulation and Walk-Forward Analysis to separate genuine edges from curve-fitting, and produces a summary table with Sharpe, Calmar, Win Rate, MC Score, WFA Verdict, and SPY/QQQ outperformance. Detailed PDF tearsheets include equity curves, drawdown plots, R-Multiple histograms, and VIX regime heatmaps.

Supports Polygon, Norgate, Yahoo Finance, and local CSV. Free to run against Yahoo Finance with no API key.

Full reference: [docs/README_full.md](docs/README_full.md)

---

## Installation

```bash
git clone https://github.com/zachisit/july-backtester.git
cd july-backtester
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate.bat
pip install -r requirements.txt
```

For Polygon data, add your API key to `.env` (copy `.env.example` to get started):

```env
POLYGON_API_KEY=your_key_here
```

---

## Quick Start

```mermaid
%%{init: {'theme': 'neutral'}}%%
graph TD
    A[Clone Repository] --> B[Create & Activate Virtual Environment]
    B --> C[pip install -r requirements.txt]
    C --> D{Choose Data Provider}
    D -->|Polygon.io| E[Add POLYGON_API_KEY to .env file]
    D -->|Yahoo / Norgate / CSV| F[No API Key Needed]
    E --> G[Run Setup Wizard: python main.py --init]
    F --> G
    G --> H[Review generated config.py]
    H --> I[Ready to Backtest]
```

**First time?** Run the setup wizard:

```bash
python main.py --init
```

```mermaid
%%{init: {'theme': 'neutral'}}%%
graph TD
    A[python main.py --init] --> B

    subgraph Step1 [Step 1 of 4 — Data Provider]
        B{Which provider?} -->|yahoo| C[No API key needed]
        B -->|csv| C
        B -->|norgate| C
        B -->|polygon| D[Enter Polygon API key\noptional — skip to add later]
    end

    C --> E
    D --> E

    subgraph Step2 [Step 2 of 4 — Capital & Dates]
        E[Enter initial capital\ndefault: 100 000] --> F[Enter start date\ndefault: 2010-01-01]
        F --> G[End date: always today\nset dynamically]
    end

    G --> H

    subgraph Step3 [Step 3 of 4 — What to Test]
        H{Single symbol\nor portfolio?} -->|single| I[Enter ticker symbols\ne.g. AAPL MSFT]
        H -->|portfolio| J{Portfolio type?}
        J -->|nasdaq100| K[Uses bundled nasdaq_100.json]
        J -->|custom| L[Enter tickers + portfolio name]
    end

    I --> M
    K --> M
    L --> M

    subgraph Step4 [Step 4 of 4 — Review & Write]
        M[Preview files to be written] --> N{Confirm?}
        N -->|No| O[Aborted — no files written]
        N -->|Yes| P[Write config_starter.py]
        P --> Q{Polygon key\nprovided?}
        Q -->|Yes| R[Append POLYGON_API_KEY to .env]
        Q -->|No| S[Done]
        R --> S
    end

    S --> T[Rename config_starter.py to config.py]
    T --> U[Run: python main.py]
```

**Or manually** — set these lines in `config.py` and run:

```python
"data_provider": "yahoo",
"symbols_to_test": ["SPY"],
"start_date": "2010-01-01",
"initial_capital": 100000.0,
```

```bash
python main.py
```

The engine runs every strategy in `custom_strategies/` against SPY, prints a results table, and writes output to `output/runs/<timestamp>/`.

**Portfolio run** — test all strategies against the Nasdaq 100:

```python
"data_provider": "polygon",
"portfolios": {
    "Nasdaq 100": "nasdaq_100.json",
},
```

Validate before a long run: `python main.py --dry-run`

See [examples/](examples/) for ready-to-use config files and annotated strategy examples.

### The Backtesting Lifecycle

```mermaid
%%{init: {'theme': 'neutral'}}%%
graph TD
    A[Edit config.py] -->|Set portfolios, dates, capital| B[Run: python main.py]
    B --> C{Execution Engine}
    C -->|Fetches/Loads Data| D[(Local Data Cache)]
    C -->|Calculates Edge| E[Monte Carlo & Walk-Forward Analysis]
    E --> F[Output Folder created: output/runs/RUN_ID/]
    F -->|Terminal Output| G[Summary Table & Correlation Matrix]
    F -->|Raw Trade Data| H[analyzer_csvs/ Portfolio / Strategy.csv]
    H --> I[Run: python report.py --all output/runs/RUN_ID]
    I --> J[PDF & Markdown Reports generated in detailed_reports/]
```

---

## CLI Flags

| Flag | Description |
| --- | --- |
| *(none)* | Full backtest run |
| `--init` | Launch the first-time setup wizard |
| `--dry-run` | Validate config and print run summary without fetching data |
| `--name <label>` | Prefix the output folder with a custom label |

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for dev setup, how to add a strategy plugin, and the PR checklist.

---

## License

[MIT License](LICENSE)
