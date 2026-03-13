"""conftest.py — project-wide pytest configuration.

Forces matplotlib to use the non-interactive Agg backend before any test
module imports pyplot. Without this, matplotlib defaults to the Tk backend on
Windows, which fails in headless / CI environments where Tk is not installed.
"""
import matplotlib
matplotlib.use("Agg")
