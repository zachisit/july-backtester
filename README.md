# July Backtester

> A professional-grade Python engine for stress-testing US equity strategies with Monte Carlo simulation and Walk-Forward Analysis.

![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python&logoColor=white)
![License: MIT](https://img.shields.io/badge/License-MIT-green)
[![Tests](https://github.com/zachisit/july-backtester/actions/workflows/tests.yml/badge.svg)](https://github.com/zachisit/july-backtester/actions/workflows/tests.yml)
![Tests: 562/562 Passing](https://img.shields.io/badge/Tests-562%2F562%20Passing-brightgreen)

---

**What it does:**

- Tests trading strategies against full historical US equity data (Polygon, Norgate, Yahoo Finance, or local CSV)
- Runs Monte Carlo simulation (1,000 reshuffles per strategy) and Walk-Forward Analysis to distinguish genuine edges from luck
- Produces a summary table with Sharpe, Calmar, Win Rate, MC Score, WFA Verdict, and SPY/QQQ outperformance
- Generates detailed PDF tearsheets with equity curves, drawdown plots, R-Multiple histograms, and VIX regime heatmaps

Full documentation: [docs/README_full.md](docs/README_full.md)

---

## Installation

```bash
git clone <repository-url>
cd july-backtester
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate.bat
pip install -r requirements.txt
```

Add your Polygon.io API key to a `.env` file (copy `.env.example` to get started):

```env
POLYGON_API_KEY=your_key_here
```

---

## Quick Example — Yahoo Finance (no API key required)

Set these four lines in `config.py`:

```python
"data_provider": "yahoo",
"symbols_to_test": ["SPY"],
"start_date": "2010-01-01",
"initial_capital": 100000.0,
```

Run:

```bash
python main.py
```

The engine runs every strategy in `custom_strategies/` against SPY, prints a results table, and writes output to `output/runs/<timestamp>/`.

---

## First Time?

Run the interactive setup wizard to generate a ready-to-use `config.py`:

```bash
python main.py --init
```

The wizard walks you through provider selection, API key setup, capital and date range, and symbol choice, then writes a `config_starter.py`. Rename it to `config.py` and you're ready to run.

---

## Portfolio Run

To test all strategies against the Nasdaq 100, set `portfolios` in `config.py`:

```python
"data_provider": "polygon",
"portfolios": {
    "Nasdaq 100": "nasdaq_100.json",
},
```

Then run `python main.py`. Results appear in the terminal and in `output/runs/<run_id>/`.

Validate your config before a long run:

```bash
python main.py --dry-run
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

## Documentation

Full reference including all configuration options, feature deep-dives, and the strategy plugin guide:

**[docs/README_full.md](docs/README_full.md)**

Covers:
- All configuration keys and defaults
- Monte Carlo block-bootstrap sampling
- Walk-Forward Analysis — single-split and rolling multi-fold
- Parameter sensitivity sweep
- VIX regime heatmap
- Short selling with borrow cost
- ML trade feature export
- Data provider setup (Polygon, Norgate, Yahoo Finance, CSV)
- Strategy plugin system — adding custom strategies
- Output files reference

---

## Contributing

1. Fork the repository and create a branch
2. Add a strategy plugin in `custom_strategies/` — see the [Plugin System](docs/README_full.md#adding-custom-strategies-plugin-system) guide
3. Validate with `python main.py --dry-run` and run a quick backtest
4. Open a pull request

Please do not commit `.env` files, `data_cache/`, or `output/`.

---

## License

[MIT License](LICENSE)
