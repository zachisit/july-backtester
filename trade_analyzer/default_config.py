# config.py
import os
from datetime import datetime

# --- File Paths & Output ---
# Base directory where timestamped report folders will be created
BASE_OUTPUT_DIRECTORY = "reports"
# Input trades file
TRADES_CSV_PATH = 'trades.csv'
# Format for saving plots for Markdown embedding
MARKDOWN_PLOT_FORMAT = 'png'

# --- Analysis Parameters ---
INITIAL_EQUITY = 50000
ROLLING_WINDOW = 50
TOP_N_LOSING_SYMBOLS = 5
PROFITABLE_PF_THRESHOLD = 1.5
UNPROFITABLE_PF_THRESHOLD = 1.0
TOP_N_TRADES_LIST = 15
BENCHMARK_TICKER = 'SPY'
RISK_FREE_RATE = 0.0
TRADING_DAYS_PER_YEAR = 252

# --- Plotting ---
A4_LANDSCAPE = (11.69, 8.27)
MAX_XTICKS_BEFORE_RESIZE = 25

# --- Debugging ---
VERBOSE_DEBUG = False # Set to True for more detailed console output

# --- PDF/Markdown Generation ---
# Estimate lines per page for text sections in PDF
LINES_PER_TEXT_PAGE = 45
# Subdirectory name within the timestamped folder for plot images
MARKDOWN_IMAGE_SUBDIR = "images"

# --- Data Columns ---
# Columns critical for basic processing, NaNs will cause rows to be dropped
CRITICAL_COLS = ['Profit', '% Profit', 'Date', 'Ex. date']
# Columns expected to be numeric, will be converted with errors='coerce'
NUMERIC_COLS = ['Price', 'Ex. Price', '% chg', 'Profit', 'Shares',
                'Position value', 'Cum. Profit', '# bars', 'Profit/bar', 'MAE', 'MFE']

# --- Walk-Forward Analysis ---
# Fraction of the trade history used as In-Sample (IS). The remainder is OOS.
# Set to None to disable WFA (N/A will appear in the report).
WFA_SPLIT_RATIO = None

# --- Monte Carlo ---
MC_SIMULATIONS = 1000  # Number of simulation paths to generate
MC_USE_PERCENTAGE_RETURNS = False # CRITICAL: Revert to False to use $ P/L, matching Amibroker's likely default
MC_PERCENTILES = [1, 5, 10, 25, 50, 75, 90, 95, 99]
MC_DRAWDOWN_AS_NEGATIVE = True # For display consistency with Amibroker's table

# NOTE: The base output directory is NOT created here automatically.
# It's assumed to exist or be creatable by the main script.
# The timestamped subdirectories WILL be created by main.py.