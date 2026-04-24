"""
Autoresearch chart generator — Plotly version.
Smart scaling: adapts colors and legend based on iteration count.
- Under 15 iterations: individual colors per line
- Over 15 iterations: gray cloud + highlighted baseline/best/top kept
Interactive HTML + static PNG export.
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


# ── Colors ────────────────────────────────────────────────────────
GRAY       = "#64748b"
CLOUD_GRAY = "#cbd5e1"
TEXT_DARK  = "#1e293b"
TEXT_MID   = "#475569"
TEXT_LIGHT = "#94a3b8"
BG         = "#ffffff"
BG_LIGHT   = "#f8fafc"
GRID       = "#e2e8f0"
BASELINE_COLOR = "#64748b"
BEST_COLOR = "#16a34a"

INDIVIDUAL_COLORS = [
    "#2563eb", "#dc2626", "#7c3aed", "#ea580c",
    "#0891b2", "#ca8a04", "#4f46e5", "#e11d48",
    "#0d9488", "#9333ea", "#0284c7", "#c026d3",
    "#6366f1", "#b45309", "#0e7490", "#0369a1",
    "#8b5cf6", "#a21caf", "#1d4ed8", "#db2777",
]

# Threshold: below this = individual colors, above = cloud mode
CLOUD_THRESHOLD = 15


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


def generate_chart(iterations, output_folder="autoresearch_runs"):
    """Generate interactive HTML + static PNG chart with smart scaling."""

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
    use_cloud = n_iterations > CLOUD_THRESHOLD

    # Dynamic sizing
    if use_cloud:
        # In cloud mode, table only shows top 10 + baseline + best
        visible_rows = min(n_iterations, 12)
    else:
        visible_rows = n_iterations

    table_height_per_row = 34
    table_header_height = 40
    table_total = table_header_height + (table_height_per_row * visible_rows)
    chart_height = max(500, 450 + min(n_iterations, 20) * 5)
    total_height = 200 + chart_height + table_total + 100

    chart_ratio = chart_height / (chart_height + table_total)
    table_ratio = 1 - chart_ratio

    # ── Build figure ──────────────────────────────────────────────
    fig = make_subplots(
        rows=2, cols=1,
        row_heights=[chart_ratio, table_ratio],
        vertical_spacing=0.06,
        specs=[[{"type": "scatter"}], [{"type": "table"}]],
    )

    # ── CLOUD MODE (>15 iterations) ──────────────────────────────
    if use_cloud:
        _draw_cloud_mode(fig, iterations, baseline, best, kept, discarded)
    else:
        _draw_individual_mode(fig, iterations, baseline, best, kept, discarded)

    # ── Table ─────────────────────────────────────────────────────
    _draw_table(fig, iterations, baseline, best, kept, discarded,
                use_cloud, table_header_height, table_height_per_row)

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

    mode_label = "cloud mode" if use_cloud else "individual mode"

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
                f'AI-driven strategy iteration — modify → measure → keep/discard → repeat'
                f'    ({n_iterations} iterations, {mode_label})'
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


# ══════════════════════════════════════════════════════════════════
# INDIVIDUAL MODE (<= 15 iterations)
# Each iteration gets its own unique color
# ══════════════════════════════════════════════════════════════════

def _draw_individual_mode(fig, iterations, baseline, best, kept, discarded):
    """Draw each iteration with its own color."""

    # Assign colors
    color_idx = 0
    iter_meta = {}
    for i, it in enumerate(iterations):
        if i == 0:
            iter_meta[i] = {"color": BASELINE_COLOR, "status": "baseline"}
        elif it is best:
            iter_meta[i] = {"color": BEST_COLOR, "status": "best"}
        elif it in kept:
            iter_meta[i] = {"color": INDIVIDUAL_COLORS[color_idx % len(INDIVIDUAL_COLORS)], "status": "kept"}
            color_idx += 1
        else:
            iter_meta[i] = {"color": INDIVIDUAL_COLORS[color_idx % len(INDIVIDUAL_COLORS)], "status": "discarded"}
            color_idx += 1

    # Draw order: discarded → kept → baseline → best
    for status_filter in ["discarded", "kept", "baseline", "best"]:
        for i, it in enumerate(iterations):
            if iter_meta[i]["status"] != status_filter:
                continue

            ec = it.get("equity_curve", [])
            if not ec:
                continue

            dates = [p["date"][:10] for p in ec]
            values = [p["value"] for p in ec]
            score = get_score(it)
            color = iter_meta[i]["color"]
            status = iter_meta[i]["status"]
            strategy = it.get("strategy", f"Iteration {i}")

            if status == "baseline":
                line = dict(color=color, width=2.5, dash="dash")
                opacity = 1.0
                label = f"#{i} Baseline — {score:.1f}%"
            elif status == "best":
                line = dict(color=BEST_COLOR, width=3.5)
                opacity = 1.0
                label = f"#{i} ★ Best — {score:.1f}%"
            elif status == "kept":
                line = dict(color=color, width=2.0)
                opacity = 1.0
                label = f"#{i} Kept — {score:.1f}%"
            else:
                line = dict(color=color, width=1.5)
                opacity = 1.0
                label = f"#{i} Discarded — {score:.1f}%"

            fig.add_trace(
                go.Scatter(
                    x=dates, y=values, mode="lines",
                    line=line, opacity=opacity, name=label,
                    hovertemplate=(
                        f"<b>#{i} {status.title()}</b><br>"
                        f"{strategy}<br>"
                        "Date: %{x}<br>Value: $%{y:,.0f}"
                        "<extra></extra>"
                    ),
                ),
                row=1, col=1,
            )

            # Endpoint annotations
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


# ══════════════════════════════════════════════════════════════════
# CLOUD MODE (> 15 iterations)
# All iterations as thin gray cloud, highlight baseline + best + top 3 kept
# ══════════════════════════════════════════════════════════════════

TOP_KEPT_COLORS = ["#2563eb", "#7c3aed", "#0891b2"]

def _draw_cloud_mode(fig, iterations, baseline, best, kept, discarded):
    """Draw iterations as a gray cloud with highlighted key lines."""

    baseline_score = get_score(baseline)

    # Find top 3 kept (excluding baseline and best)
    kept_scores = []
    for it in kept:
        if it is not baseline and it is not best:
            kept_scores.append((get_score(it), it))
    kept_scores.sort(key=lambda x: x[0], reverse=True)
    top_kept = [it for _, it in kept_scores[:3]]

    # 1. Draw ALL iterations as thin gray cloud (back layer)
    cloud_drawn = False
    for i, it in enumerate(iterations):
        if it is baseline or it is best or it in top_kept:
            continue

        ec = it.get("equity_curve", [])
        if not ec:
            continue

        dates = [p["date"][:10] for p in ec]
        values = [p["value"] for p in ec]
        score = get_score(it)
        status = "kept" if it in kept else "discarded"

        fig.add_trace(
            go.Scatter(
                x=dates, y=values, mode="lines",
                line=dict(color=CLOUD_GRAY, width=0.8),
                opacity=0.4,
                name=f"Other iterations ({len(iterations) - len(top_kept) - 2} total)",
                legendgroup="cloud",
                showlegend=(not cloud_drawn),
                hovertemplate=(
                    f"<b>#{i} {status.title()}</b><br>"
                    f"{it.get('strategy', 'N/A')}<br>"
                    "Date: %{x}<br>Value: $%{y:,.0f}<br>"
                    f"Return: {score:.1f}%"
                    "<extra></extra>"
                ),
            ),
            row=1, col=1,
        )
        cloud_drawn = True

    # 2. Draw top 3 kept (colored, medium weight)
    for j, it in enumerate(top_kept):
        ec = it.get("equity_curve", [])
        if not ec:
            continue

        idx = iterations.index(it)
        dates = [p["date"][:10] for p in ec]
        values = [p["value"] for p in ec]
        score = get_score(it)
        color = TOP_KEPT_COLORS[j % len(TOP_KEPT_COLORS)]

        fig.add_trace(
            go.Scatter(
                x=dates, y=values, mode="lines",
                line=dict(color=color, width=2.0),
                opacity=0.8,
                name=f"#{idx} Kept — {score:.1f}%",
                hovertemplate=(
                    f"<b>#{idx} Kept</b><br>"
                    f"{it.get('strategy', 'N/A')}<br>"
                    "Date: %{x}<br>Value: $%{y:,.0f}"
                    "<extra></extra>"
                ),
            ),
            row=1, col=1,
        )

    # 3. Draw baseline (dashed gray)
    ec_base = baseline.get("equity_curve", [])
    if ec_base:
        dates = [p["date"][:10] for p in ec_base]
        values = [p["value"] for p in ec_base]

        fig.add_trace(
            go.Scatter(
                x=dates, y=values, mode="lines",
                line=dict(color=BASELINE_COLOR, width=2.5, dash="dash"),
                name=f"#0 Baseline — {baseline_score:.1f}%",
                hovertemplate=(
                    "<b>#0 Baseline</b><br>"
                    f"{baseline.get('strategy', 'N/A')}<br>"
                    "Date: %{x}<br>Value: $%{y:,.0f}"
                    "<extra></extra>"
                ),
            ),
            row=1, col=1,
        )
        fig.add_annotation(
            x=dates[-1], y=values[-1],
            text=f"${values[-1]:,.0f}",
            showarrow=True, arrowhead=0, arrowcolor=BASELINE_COLOR,
            ax=60, ay=25,
            font=dict(size=13, color=BASELINE_COLOR, family="Courier New, monospace"),
            row=1, col=1,
        )

    # 4. Draw best (thick green, front)
    ec_best = best.get("equity_curve", [])
    if ec_best and best is not baseline:
        best_idx = iterations.index(best)
        dates = [p["date"][:10] for p in ec_best]
        values = [p["value"] for p in ec_best]
        best_score = get_score(best)

        fig.add_trace(
            go.Scatter(
                x=dates, y=values, mode="lines",
                line=dict(color=BEST_COLOR, width=3.5),
                name=f"#{best_idx} ★ Best — {best_score:.1f}%",
                hovertemplate=(
                    f"<b>#{best_idx} ★ Best</b><br>"
                    f"{best.get('strategy', 'N/A')}<br>"
                    "Date: %{x}<br>Value: $%{y:,.0f}"
                    "<extra></extra>"
                ),
            ),
            row=1, col=1,
        )
        fig.add_annotation(
            x=dates[-1], y=values[-1],
            text=f"<b>${values[-1]:,.0f}</b>",
            showarrow=True, arrowhead=0, arrowcolor=BEST_COLOR,
            ax=60, ay=-25,
            font=dict(size=14, color=BEST_COLOR, family="Courier New, monospace"),
            row=1, col=1,
        )


# ══════════════════════════════════════════════════════════════════
# TABLE
# ══════════════════════════════════════════════════════════════════

def _draw_table(fig, iterations, baseline, best, kept, discarded,
                use_cloud, table_header_height, table_height_per_row):
    """Draw the iteration table. In cloud mode, show only top rows."""

    baseline_score = get_score(baseline)

    # Decide which rows to show
    if use_cloud:
        # Show: baseline, best, top 5 kept, top 5 discarded (by score)
        show_indices = {0}  # baseline always
        best_idx = iterations.index(best)
        show_indices.add(best_idx)

        # Top 5 kept by score (excluding baseline and best)
        kept_with_score = [(get_score(it), iterations.index(it)) for it in kept
                           if it is not baseline and it is not best]
        kept_with_score.sort(key=lambda x: x[0], reverse=True)
        for _, idx in kept_with_score[:5]:
            show_indices.add(idx)

        # Top 5 discarded by score (closest to beating best)
        disc_with_score = [(get_score(it), iterations.index(it)) for it in discarded]
        disc_with_score.sort(key=lambda x: x[0], reverse=True)
        for _, idx in disc_with_score[:5]:
            show_indices.add(idx)

        visible = sorted(show_indices)
    else:
        visible = list(range(len(iterations)))

    # Build table data
    t_iter = []
    t_strategy = []
    t_return = []
    t_delta = []
    t_sharpe = []
    t_trades = []
    t_winrate = []
    t_maxdd = []
    t_status = []

    row_fills = []
    c_iter = []
    c_strategy = []
    c_delta = []
    c_status = []

    for i in visible:
        it = iterations[i]
        score = get_score(it)
        delta = score - baseline_score
        is_baseline = (i == 0)
        is_best = (it is best and it is not baseline)
        is_kept = it in kept and not is_baseline and not is_best

        t_iter.append(str(i))
        t_strategy.append(it.get("strategy", f"Iteration {i}"))
        t_return.append(f"{score:.1f}%")
        t_delta.append("—" if is_baseline else f"{'+' if delta >= 0 else ''}{delta:.1f}%")
        t_sharpe.append(f"{it.get('sharpe_ratio', 0):.2f}")
        t_trades.append(str(it.get("trades", 0)))
        t_winrate.append(f"{it.get('win_rate', 0) * 100:.1f}%")
        t_maxdd.append(f"{it.get('max_drawdown', 0) * 100:.1f}%")

        if is_baseline:
            t_status.append("BASELINE")
            c_status.append(TEXT_LIGHT)
            row_fills.append("#f8fafc")
            c_iter.append(BASELINE_COLOR)
            c_strategy.append(TEXT_MID)
        elif is_best:
            t_status.append("★ BEST")
            c_status.append(BEST_COLOR)
            row_fills.append("#dcfce7")
            c_iter.append(BEST_COLOR)
            c_strategy.append(BEST_COLOR)
        elif is_kept:
            t_status.append("✓ KEPT")
            c_status.append("#2563eb")
            row_fills.append("#eff6ff")
            c_iter.append("#2563eb")
            c_strategy.append("#2563eb")
        else:
            t_status.append("✗ DISCARDED")
            c_status.append("#dc2626")
            row_fills.append("#fef2f2")
            c_iter.append("#dc2626")
            c_strategy.append(TEXT_MID)

        c_delta.append(
            TEXT_LIGHT if is_baseline
            else (BEST_COLOR if delta > 0 else ("#dc2626" if delta < 0 else TEXT_LIGHT))
        )

    # Add "showing X of Y" note in cloud mode
    if use_cloud:
        t_iter.append("...")
        t_strategy.append(f"Showing {len(visible)} of {len(iterations)} iterations")
        t_return.append("")
        t_delta.append("")
        t_sharpe.append("")
        t_trades.append("")
        t_winrate.append("")
        t_maxdd.append("")
        t_status.append("")
        row_fills.append("#f8fafc")
        c_iter.append(TEXT_LIGHT)
        c_strategy.append(TEXT_LIGHT)
        c_delta.append(TEXT_LIGHT)
        c_status.append(TEXT_LIGHT)

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
                values=[t_iter, t_strategy, t_return, t_delta,
                        t_sharpe, t_trades, t_winrate, t_maxdd, t_status],
                fill_color=[row_fills],
                align=["center", "left", "right", "right", "right",
                       "right", "right", "right", "center"],
                font=dict(
                    size=13,
                    color=[c_iter, c_strategy, TEXT_DARK, c_delta,
                           TEXT_DARK, TEXT_DARK, TEXT_DARK, TEXT_DARK, c_status],
                    family="Courier New, monospace",
                ),
                line_color=GRID,
                height=table_height_per_row,
            ),
            columnwidth=[0.3, 2.2, 0.6, 0.6, 0.6, 0.5, 0.6, 0.6, 0.9],
        ),
        row=2, col=1,
    )


# ══════════════════════════════════════════════════════════════════
# SUMMARY
# ══════════════════════════════════════════════════════════════════

def print_summary(iterations, baseline, best, kept, discarded):
    """Print a text summary of all iterations."""

    if not iterations:
        print("No iterations found.")
        return

    baseline_score = get_score(baseline)
    best_score = get_score(best)

    print(f"\n{'=' * 80}")
    print("  AUTORESEARCH ITERATION SUMMARY")
    print(f"{'=' * 80}")

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

    print(f"{'=' * 80}")
    print(f"\n  BEST: Iteration {iterations.index(best)} — {best_score:.2f}% total return")
    print(f"  Baseline: {baseline_score:.2f}%")
    print(f"  Improvement: +{best_score - baseline_score:.2f}%")
    print(f"  Mode: {'Cloud' if len(iterations) > CLOUD_THRESHOLD else 'Individual'}"
          f" ({len(iterations)} iterations)")
    print()


if __name__ == "__main__":
    iterations = load_iterations()
    baseline, best, kept, discarded = classify_iterations(iterations)
    print_summary(iterations, baseline, best, kept, discarded)
    generate_chart(iterations)