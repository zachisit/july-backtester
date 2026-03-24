"""
Autoresearch chart generator — Plotly version.
Reads all iteration JSONs and generates a professional equity curve chart.
Dynamic colors, scalable legend, interactive HTML + static PNG export.
"""

import json
import glob
import os

try:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
except ImportError:
    print("plotly not installed. Run: pip install plotly kaleido")
    exit(1)


# ── Base colors ───────────────────────────────────────────────────
GRAY       = "#64748b"
TEXT_DARK  = "#1e293b"
TEXT_MID   = "#475569"
TEXT_LIGHT = "#94a3b8"
BG         = "#ffffff"
BG_LIGHT   = "#f8fafc"
GRID       = "#e2e8f0"
BASELINE_COLOR = "#64748b"

# ── Dynamic color palettes ────────────────────────────────────────
KEPT_COLORS = [
    "#2563eb", "#7c3aed", "#0891b2", "#0d9488",
    "#4f46e5", "#0284c7", "#6d28d9", "#0e7490",
]
DISCARDED_COLORS = [
    "#dc2626", "#ea580c", "#ca8a04", "#e11d48",
    "#9333ea", "#c026d3", "#0369a1", "#b45309",
]

BEST_COLOR = "#16a34a"


def load_iterations(folder="autoresearch_runs"):
    """Load all iteration JSON files."""
    files = sorted(glob.glob(os.path.join(folder, "iteration_*.json")))
    iterations = []
    for f in files:
        with open(f) as fh:
            data = json.load(fh)
            data["_filename"] = os.path.basename(f)
            iterations.append(data)
    return iterations


def get_score(iteration):
    """Calculate total return % from equity curve."""
    ec = iteration.get("equity_curve", [])
    if len(ec) > 1:
        return round(((ec[-1]["value"] / ec[0]["value"]) - 1) * 100, 2)
    return 0


def classify_iterations(iterations):
    """Split into baseline, best, kept, discarded."""
    if not iterations:
        return None, None, [], []

    baseline = iterations[0]
    best_score = get_score(baseline)
    best = baseline
    kept = [baseline]
    discarded = []

    for it in iterations[1:]:
        score = get_score(it)
        if score > best_score:
            best_score = score
            best = it
            kept.append(it)
        else:
            discarded.append(it)

    return baseline, best, kept, discarded


def get_color(idx, palette):
    """Get a color from palette, cycling if needed."""
    return palette[idx % len(palette)]


def generate_chart(iterations, output_folder="autoresearch_runs"):
    """Generate interactive HTML + static PNG chart."""

    if not iterations:
        print("No iterations found.")
        return

    baseline, best, kept, discarded = classify_iterations(iterations)
    baseline_score = get_score(baseline)
    best_score = get_score(best)
    improvement = round(best_score - baseline_score, 2)

    n_iterations = len(iterations)
    n_kept = len(kept)
    n_discarded = len(discarded)

    # Dynamic sizing
    table_height_per_row = 34
    table_header_height = 40
    table_total = table_header_height + (table_height_per_row * n_iterations)
    chart_height = max(500, 400 + n_iterations * 10)
    total_height = 200 + chart_height + table_total + 80

    chart_ratio = chart_height / (chart_height + table_total)
    table_ratio = 1 - chart_ratio

    # ── Build figure ──────────────────────────────────────────────
    fig = make_subplots(
        rows=2, cols=1,
        row_heights=[chart_ratio, table_ratio],
        vertical_spacing=0.06,
        specs=[[{"type": "scatter"}], [{"type": "table"}]],
    )

    # ── Assign colors to each iteration ───────────────────────────
    iter_colors = {}
    iter_status = {}
    kept_idx = 0
    discard_idx = 0

    for i, it in enumerate(iterations):
        if i == 0:
            iter_colors[i] = BASELINE_COLOR
            iter_status[i] = "baseline"
        elif it is best:
            iter_colors[i] = BEST_COLOR
            iter_status[i] = "best"
        elif it in kept:
            iter_colors[i] = get_color(kept_idx, KEPT_COLORS)
            iter_status[i] = "kept"
            kept_idx += 1
        else:
            iter_colors[i] = get_color(discard_idx, DISCARDED_COLORS)
            iter_status[i] = "discarded"
            discard_idx += 1

    # ── Draw all curves ───────────────────────────────────────────
    # Order: discarded (back) → kept → baseline → best (front)
    draw_order = []
    for i, it in enumerate(iterations):
        if iter_status[i] == "discarded":
            draw_order.append((i, it))
    for i, it in enumerate(iterations):
        if iter_status[i] == "kept":
            draw_order.append((i, it))
    for i, it in enumerate(iterations):
        if iter_status[i] == "baseline":
            draw_order.append((i, it))
    for i, it in enumerate(iterations):
        if iter_status[i] == "best":
            draw_order.append((i, it))

    for idx, it in draw_order:
        ec = it.get("equity_curve", [])
        if not ec:
            continue

        dates = [p["date"][:10] for p in ec]
        values = [p["value"] for p in ec]
        score = get_score(it)
        color = iter_colors[idx]
        status = iter_status[idx]
        strategy_name = it.get("strategy", f"Iteration {idx}")

        # Line style based on status
        if status == "baseline":
            line_dict = dict(color=color, width=2.5, dash="dash")
            opacity = 1.0
            label = f"#{idx} Baseline — {score:.1f}%"
        elif status == "best":
            line_dict = dict(color=BEST_COLOR, width=3.5)
            opacity = 1.0
            label = f"#{idx} ★ Best — {score:.1f}%"
        elif status == "kept":
            line_dict = dict(color=color, width=2.0)
            opacity = 1.0
            label = f"#{idx} Kept — {score:.1f}%"
        else:
            line_dict = dict(color=color, width=1.5)
            opacity = 1.0
            label = f"#{idx} Discarded — {score:.1f}%"

        fig.add_trace(
            go.Scatter(
                x=dates, y=values,
                mode="lines",
                line=line_dict,
                opacity=opacity,
                name=label,
                hovertemplate=(
                    f"<b>#{idx} {status.title()}</b><br>"
                    f"{strategy_name}<br>"
                    "Date: %{x}<br>"
                    "Value: $%{y:,.0f}"
                    "<extra></extra>"
                ),
            ),
            row=1, col=1,
        )

        # Endpoint annotations for baseline and best only
        if status == "baseline":
            fig.add_annotation(
                x=dates[-1], y=values[-1],
                text=f"${values[-1]:,.0f}",
                showarrow=True, arrowhead=0, arrowcolor=color,
                ax=60, ay=25,
                font=dict(size=13, color=color, family="Courier New, monospace"),
                row=1, col=1,
            )
        elif status == "best":
            fig.add_annotation(
                x=dates[-1], y=values[-1],
                text=f"<b>${values[-1]:,.0f}</b>",
                showarrow=True, arrowhead=0, arrowcolor=BEST_COLOR,
                ax=60, ay=-25,
                font=dict(size=14, color=BEST_COLOR, family="Courier New, monospace"),
                row=1, col=1,
            )

    # ── Iteration table ───────────────────────────────────────────
    table_data = {
        "iter": [], "change": [], "return": [], "delta": [],
        "sharpe": [], "trades": [], "winrate": [], "maxdd": [], "status": [],
    }
    row_fills = []
    colors_iter = []
    colors_change = []
    colors_delta = []
    colors_status = []

    for i, it in enumerate(iterations):
        score = get_score(it)
        delta = score - baseline_score
        status = iter_status[i]
        color = iter_colors[i]

        table_data["iter"].append(str(i))
        table_data["change"].append(it.get("strategy", f"Iteration {i}"))
        table_data["return"].append(f"{score:.1f}%")
        table_data["delta"].append(
            "—" if i == 0 else f"{'+' if delta >= 0 else ''}{delta:.1f}%"
        )
        table_data["sharpe"].append(f"{it.get('sharpe_ratio', 0):.2f}")
        table_data["trades"].append(str(it.get("trades", 0)))
        table_data["winrate"].append(f"{it.get('win_rate', 0) * 100:.1f}%")
        table_data["maxdd"].append(f"{it.get('max_drawdown', 0) * 100:.1f}%")

        # Status label and colors
        if status == "baseline":
            table_data["status"].append("BASELINE")
            colors_status.append(TEXT_LIGHT)
            row_fills.append("#f8fafc")
        elif status == "best":
            table_data["status"].append("★ BEST")
            colors_status.append(BEST_COLOR)
            row_fills.append("#dcfce7")
        elif status == "kept":
            table_data["status"].append("✓ KEPT")
            colors_status.append(color)
            row_fills.append("#eff6ff")
        else:
            table_data["status"].append("✗ DISCARDED")
            colors_status.append(color)
            row_fills.append("#fef2f2")

        colors_iter.append(color)
        colors_change.append(color if status in ("best", "kept") else TEXT_MID)
        colors_delta.append(
            TEXT_LIGHT if i == 0
            else (BEST_COLOR if delta > 0 else ("#dc2626" if delta < 0 else TEXT_LIGHT))
        )

    fig.add_trace(
        go.Table(
            header=dict(
                values=[
                    "<b>#</b>", "<b>Strategy</b>", "<b>Return</b>", "<b>vs Base</b>",
                    "<b>Sharpe</b>", "<b>Trades</b>", "<b>Win Rate</b>",
                    "<b>Max DD</b>", "<b>Status</b>",
                ],
                fill_color="#f1f5f9",
                align=["center", "left", "right", "right", "right",
                       "right", "right", "right", "center"],
                font=dict(size=13, color=TEXT_MID, family="Courier New, monospace"),
                line_color=GRID,
                height=table_header_height,
            ),
            cells=dict(
                values=[
                    table_data["iter"], table_data["change"], table_data["return"],
                    table_data["delta"], table_data["sharpe"], table_data["trades"],
                    table_data["winrate"], table_data["maxdd"], table_data["status"],
                ],
                fill_color=[row_fills],
                align=["center", "left", "right", "right", "right",
                       "right", "right", "right", "center"],
                font=dict(
                    size=13,
                    color=[
                        colors_iter, colors_change, TEXT_DARK,
                        colors_delta, TEXT_DARK, TEXT_DARK,
                        TEXT_DARK, TEXT_DARK, colors_status,
                    ],
                    family="Courier New, monospace",
                ),
                line_color=GRID,
                height=table_height_per_row,
            ),
            columnwidth=[0.3, 2.2, 0.6, 0.6, 0.6, 0.5, 0.6, 0.6, 0.9],
        ),
        row=2, col=1,
    )

    # ── Stats bar ─────────────────────────────────────────────────
    stats_text = (
        f'<span style="color:{TEXT_LIGHT};font-size:14px">ITERATIONS </span>'
        f'<span style="color:{TEXT_DARK};font-size:16px"><b>{n_iterations}</b></span>'
        f'<span style="color:{TEXT_LIGHT};font-size:14px">    KEPT </span>'
        f'<span style="color:#2563eb;font-size:16px"><b>{n_kept}</b></span>'
        f'<span style="color:{TEXT_LIGHT};font-size:14px">    DISCARDED </span>'
        f'<span style="color:#dc2626;font-size:16px"><b>{n_discarded}</b></span>'
        f'<span style="color:{TEXT_LIGHT};font-size:14px">    BASELINE </span>'
        f'<span style="color:{TEXT_MID};font-size:16px"><b>{baseline_score:.1f}%</b></span>'
        f'<span style="color:{TEXT_LIGHT};font-size:14px">    BEST </span>'
        f'<span style="color:{BEST_COLOR};font-size:16px"><b>{best_score:.1f}%</b></span>'
        f'<span style="color:{TEXT_LIGHT};font-size:14px">    IMPROVEMENT </span>'
        f'<span style="color:{BEST_COLOR};font-size:16px"><b>+{improvement:.1f}%</b></span>'
    )

    # ── Layout ────────────────────────────────────────────────────
    fig.update_layout(
        title=dict(
            text=(
                f'<span style="color:{BEST_COLOR};font-size:13px;letter-spacing:2px">'
                f'<b>AUTORESEARCH</b></span>'
                f'<span style="color:{TEXT_LIGHT};font-size:13px">'
                f'    Light Water Backtesting Engine</span>'
                '<br>'
                f'<span style="color:{TEXT_DARK};font-size:26px">'
                f'<b>Equity Curve Evolution</b></span>'
                '<br>'
                f'<span style="color:{TEXT_LIGHT};font-size:13px">'
                'AI-driven strategy iteration — modify → measure → keep/discard → repeat'
                '</span>'
                '<br><br>'
                f'{stats_text}'
            ),
            x=0.02,
            font=dict(family="Courier New, monospace"),
        ),
        height=total_height,
        width=1500,
        paper_bgcolor=BG,
        plot_bgcolor=BG_LIGHT,
        font=dict(family="Courier New, monospace", color=TEXT_DARK),
        legend=dict(
            orientation="v",
            yanchor="top",
            y=0.99,
            xanchor="left",
            x=1.02,
            font=dict(size=12, color=TEXT_MID, family="Courier New, monospace"),
            bgcolor="rgba(255,255,255,0.95)",
            bordercolor=GRID,
            borderwidth=1,
            tracegroupgap=5,
            itemwidth=30,
        ),
        margin=dict(t=200, l=80, r=250, b=40),
    )

    # Chart axes
    fig.update_xaxes(
        gridcolor=GRID, gridwidth=1,
        linecolor=GRID, linewidth=1,
        tickfont=dict(size=12, color=TEXT_MID, family="Courier New, monospace"),
        row=1, col=1,
    )
    fig.update_yaxes(
        gridcolor=GRID, gridwidth=1,
        linecolor=GRID, linewidth=1,
        tickformat="$,.0f",
        tickfont=dict(size=13, color=TEXT_MID, family="Courier New, monospace"),
        title=dict(text="Portfolio Value ($)", font=dict(size=14, color=TEXT_MID)),
        row=1, col=1,
    )

    # Footer
    fig.add_annotation(
        text=(
            f'<span style="color:{TEXT_LIGHT}">Powered by Claude Code × Autoresearch'
            f'          Light Water Backtesting Engine</span>'
        ),
        xref="paper", yref="paper",
        x=0.5, y=-0.01,
        showarrow=False,
        font=dict(size=11, family="Courier New, monospace"),
    )

    # ── Save ──────────────────────────────────────────────────────
    html_path = os.path.join(output_folder, "equity_curves.html")
    png_path = os.path.join(output_folder, "equity_curves.png")

    fig.write_html(html_path, include_plotlyjs="cdn")
    print(f"Interactive chart saved to {html_path}")

    try:
        fig.write_image(png_path, width=1500, height=total_height, scale=2)
        print(f"Static chart saved to {png_path}")
    except Exception as e:
        print(f"PNG export failed ({e}). Install kaleido: pip install kaleido")

    try:
        import webbrowser
        webbrowser.open("file://" + os.path.abspath(html_path))
    except Exception:
        pass


def print_summary(iterations):
    """Print a text summary of all iterations."""

    if not iterations:
        print("No iterations found.")
        return

    baseline, best, kept, discarded = classify_iterations(iterations)
    baseline_score = get_score(baseline)
    best_score = get_score(best)

    print("\n" + "=" * 80)
    print("  AUTORESEARCH ITERATION SUMMARY")
    print("=" * 80)

    for i, it in enumerate(iterations):
        score = get_score(it)
        delta = score - baseline_score
        sign = "+" if delta >= 0 else ""

        if i == 0:
            status = "BASELINE"
        elif it is best:
            status = "★ BEST"
        elif it in kept:
            status = "✓ KEPT"
        else:
            status = "✗ DISCARDED"

        print(
            f"  Iter {i:3d} | "
            f"Return: {score:8.2f}% | "
            f"vs Base: {sign}{delta:7.2f}% | "
            f"Sharpe: {it.get('sharpe_ratio', 0):6.3f} | "
            f"Trades: {it.get('trades', 0):4d} | "
            f"Win: {it.get('win_rate', 0) * 100:5.1f}% | "
            f"DD: {it.get('max_drawdown', 0) * 100:5.1f}% | "
            f"{status}"
        )

    print("=" * 80)
    print(f"\n  BEST: Iteration {iterations.index(best)} — {best_score:.2f}% total return")
    print(f"  Baseline: {baseline_score:.2f}%")
    print(f"  Improvement: +{best_score - baseline_score:.2f}%")
    print()


if __name__ == "__main__":
    iterations = load_iterations()
    baseline, best, kept, discarded = classify_iterations(iterations)
    print_summary(iterations)
    generate_chart(iterations)