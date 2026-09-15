"""Benchmark charts, rendered to PNG next to summary.md.

summary.md is each chart's table view: every value a chart shows is also in the table.
Visual rules follow the dataviz reference palette: validated categorical slots (at most three
pipelines, the count that stays distinguishable for every pair), solid hairline gridlines, thin
marks, a 2px surface gap between stacked segments, rounded data-ends, text in ink colours only,
and a legend whenever a chart has two or more series.
"""

from collections.abc import Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path

from matplotlib import rc_context
from matplotlib.axes import Axes
from matplotlib.backend_bases import RendererBase
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.patches import PathPatch, Rectangle
from matplotlib.path import Path as MplPath
from matplotlib.text import Text

from triage.bench.golden import Split
from triage.bench.scoring import BenchmarkSummary, GroupSummary, Proportion

DPI = 144

SURFACE = "#fcfcfb"
INK_PRIMARY = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#898781"
GRIDLINE = "#e1e0d9"
BASELINE = "#c3c2b7"
WHITE = "#ffffff"
SERIES = ("#2a78d6", "#eb6834", "#1baf7a")
"""Categorical slots 1-3 (blue, orange, aqua), validated for every pair."""

_GROUPS = (*(split.value for split in Split), "all")
_RATE_ROWS: tuple[tuple[str, str], ...] = (
    ("Decision accuracy", "decision_accuracy"),
    ("Category accuracy", "category_accuracy"),
    ("Priority accuracy", "priority_accuracy"),
    ("Routing accuracy", "routing_accuracy"),
    ("Accuracy when auto-resolved", "accuracy_when_auto_resolved"),
    ("False-confident rate (lower is better)", "false_confident_rate"),
    ("Escalation recall", "escalation_recall"),
)


@dataclass(frozen=True, slots=True)
class OutcomeShare:
    label: str
    color: str
    count: int
    share: float
    direct_label: bool
    """Only the two segments the story is about carry an in-bar percentage."""


def outcome_shares(group: GroupSummary) -> list[OutcomeShare]:
    """Partition every ticket-run in the group into exactly one outcome."""
    total = group.decision_accuracy.total
    if total == 0:
        return []
    no_credit = group.escalation_rate.successes - group.escalation_recall.successes
    rows = (
        ("Correct", SERIES[0], group.decision_accuracy.successes, True),
        ("Escalated, no credit", INK_MUTED, no_credit, False),
        ("Confident error", SERIES[1], group.false_confident_rate.successes, True),
        ("Infrastructure failure", BASELINE, group.unexpected_outcomes, False),
    )
    return [
        OutcomeShare(label, color, count, count / total, labelled)
        for label, color, count, labelled in rows
    ]


def ink_on(fill: str) -> str:
    """White or primary ink, whichever contrasts more with `fill`."""
    fill_luminance = _relative_luminance(fill)
    on_white = 1.05 / (fill_luminance + 0.05)
    on_ink = (fill_luminance + 0.05) / (_relative_luminance(INK_PRIMARY) + 0.05)
    return WHITE if on_white >= on_ink else INK_PRIMARY


def plot_outcomes(summaries: Sequence[BenchmarkSummary], path: Path) -> Path:
    """100% stacked bars: where each split's ticket-runs ended up."""
    _check_series(summaries)
    rows = [
        (name if len(summaries) == 1 else f"{name} · {summary.pipeline}", group)
        for name in _GROUPS
        for summary in summaries
        if (group := _group(summary, name)) is not None
    ]
    width, left, right, top, bottom = 1100, 200, 40, 116, 40
    pitch, bar = 40, 20
    plot_width = width - left - right
    height = top + pitch * len(rows) + bottom

    with _chart_style():
        figure, canvas = _figure(width, height)
        renderer = canvas.get_renderer()  # type: ignore[no-untyped-call]
        axes = figure.add_axes(
            (left / width, bottom / height, plot_width / width, pitch * len(rows) / height)
        )
        _percent_axis(axes, ticks=(0, 0.25, 0.5, 0.75, 1.0))
        axes.set_ylim(len(rows) - 0.5, -0.5)

        gap, radius_x, radius_y = 2 / plot_width, 4 / plot_width, 4 / pitch
        half = bar / pitch / 2
        legend: dict[str, str] = {}
        for index, (label, group) in enumerate(rows):
            axes.text(
                -12 / plot_width,
                index,
                label,
                ha="right",
                va="center",
                color=INK_SECONDARY,
                fontsize=_pt(13),
            )
            shares = [share for share in outcome_shares(group) if share.count]
            start = 0.0
            for position, share in enumerate(shares):
                end = start + share.share
                is_last = position == len(shares) - 1
                visible_end = end if is_last else end - gap
                if visible_end > start:
                    y0, y1 = index - half, index + half
                    patch = (
                        PathPatch(
                            _rounded_end(start, visible_end, y0, y1, radius_x, radius_y),
                            facecolor=share.color,
                            edgecolor="none",
                        )
                        if is_last
                        else Rectangle(
                            (start, y0),
                            visible_end - start,
                            y1 - y0,
                            facecolor=share.color,
                            edgecolor="none",
                        )
                    )
                    axes.add_patch(patch)
                    legend[share.label] = share.color
                    if share.direct_label:
                        _label_inside(axes, renderer, start, visible_end, index, share)
                start = end

        title = "Where tickets ended up"
        if len(summaries) == 1:
            title += f": {summaries[0].pipeline}"
        _header(figure, title, "Share of ticket-runs in each split. Values are in summary.md.")
        _legend(figure, renderer, 24, 84, list(legend.items()))
        figure.savefig(path, facecolor=SURFACE)
    return path


def plot_rates(summaries: Sequence[BenchmarkSummary], path: Path) -> Path:
    """Small multiples, one per split: each rate as a dot with its 95% interval."""
    _check_series(summaries)
    groups = [name for name in _GROUPS if any(_group(s, name) for s in summaries)]
    width, left, right, bottom, facet_gap = 1240, 270, 28, 40, 44
    top = 116 if len(summaries) > 1 else 92
    pitch = 34
    facet_width = (width - left - right - facet_gap * (len(groups) - 1)) / len(groups)
    plot_height = pitch * len(_RATE_ROWS)
    height = top + 28 + plot_height + bottom
    offsets = [(i - (len(summaries) - 1) / 2) * 0.26 for i in range(len(summaries))]

    with _chart_style():
        figure, canvas = _figure(width, height)
        renderer = canvas.get_renderer()  # type: ignore[no-untyped-call]
        for column, name in enumerate(groups):
            x = left + column * (facet_width + facet_gap)
            axes = figure.add_axes(
                (x / width, bottom / height, facet_width / width, plot_height / height)
            )
            _percent_axis(axes, ticks=(0, 0.5, 1.0))
            axes.set_ylim(len(_RATE_ROWS) - 0.5, -0.5)
            _figure_text(figure, x, top, name, size=13, color=INK_PRIMARY, weight="semibold")
            for row, (label, attribute) in enumerate(_RATE_ROWS):
                if column == 0:
                    axes.text(
                        -14 / facet_width,
                        row,
                        label,
                        ha="right",
                        va="center",
                        color=INK_SECONDARY,
                        fontsize=_pt(13),
                    )
                drawn = False
                for series, summary in enumerate(summaries):
                    group = _group(summary, name)
                    rate: Proportion | None = getattr(group, attribute) if group else None
                    if rate is None or rate.value is None:
                        continue
                    if rate.ci_low is None or rate.ci_high is None:
                        continue
                    y = row + offsets[series]
                    color = SERIES[series]
                    axes.plot(
                        [rate.ci_low, rate.ci_high],
                        [y, y],
                        color=color,
                        linewidth=_pt(2),
                        solid_capstyle="round",
                        zorder=2,
                    )
                    axes.plot(
                        [rate.value],
                        [y],
                        linestyle="none",
                        marker="o",
                        markersize=_pt(11),
                        markerfacecolor=color,
                        markeredgecolor=SURFACE,
                        markeredgewidth=_pt(2),
                        zorder=3,
                    )
                    drawn = True
                if not drawn:
                    axes.text(
                        0.02,
                        row,
                        "no cases",
                        ha="left",
                        va="center",
                        color=INK_MUTED,
                        fontsize=_pt(12),
                    )

        title = "Rates with 95% intervals"
        if len(summaries) == 1:
            title += f": {summaries[0].pipeline}"
        _header(
            figure,
            title,
            "Dot: rate over all runs. Line: 95% Wilson interval, sample size = tickets. "
            "Values are in summary.md.",
        )
        if len(summaries) > 1:
            entries = [(s.pipeline, SERIES[i]) for i, s in enumerate(summaries)]
            _legend(figure, renderer, 24, 84, entries)
        figure.savefig(path, facecolor=SURFACE)
    return path


# --- helpers ----------------------------------------------------------------------


def _pt(px: float) -> float:
    """Matplotlib sizes are in points; this spec is in pixels at DPI."""
    return px * 72 / DPI


def _chart_style() -> AbstractContextManager[None]:
    """Scoped rcParams: the system sans, without touching matplotlib's global state."""
    return rc_context(
        {
            "font.family": "sans-serif",
            "font.sans-serif": ["Segoe UI", "Helvetica Neue", "Arial", "DejaVu Sans"],
        }
    )


def _check_series(summaries: Sequence[BenchmarkSummary]) -> None:
    if not summaries:
        raise ValueError("nothing to plot")
    if len(summaries) > len(SERIES):
        raise ValueError(
            f"at most {len(SERIES)} pipelines per chart stay distinguishable; facet the rest"
        )


def _group(summary: BenchmarkSummary, name: str) -> GroupSummary | None:
    return summary.overall if name == "all" else summary.splits.get(name)


def _figure(width: int, height: int) -> tuple[Figure, FigureCanvasAgg]:
    figure = Figure(figsize=(width / DPI, height / DPI), dpi=DPI, facecolor=SURFACE)
    return figure, FigureCanvasAgg(figure)


def _figure_text(
    figure: Figure,
    x: float,
    y: float,
    text: str,
    *,
    size: float,
    color: str,
    weight: str = "normal",
    va: str = "top",
) -> Text:
    """Text positioned in pixels from the figure's top-left corner."""
    return figure.text(
        x / figure.bbox.width,
        1 - y / figure.bbox.height,
        text,
        fontsize=_pt(size),
        color=color,
        fontweight=weight,
        va=va,
    )


def _header(figure: Figure, title: str, subtitle: str) -> None:
    _figure_text(figure, 24, 20, title, size=17, color=INK_PRIMARY, weight="semibold")
    _figure_text(figure, 24, 48, subtitle, size=13, color=INK_SECONDARY)


def _legend(
    figure: Figure, renderer: RendererBase, x: float, y: float, entries: Sequence[tuple[str, str]]
) -> None:
    width, height = figure.bbox.width, figure.bbox.height
    for label, color in entries:
        figure.add_artist(
            Rectangle(
                (x / width, 1 - (y + 11) / height),
                11 / width,
                11 / height,
                transform=figure.transFigure,
                facecolor=color,
                edgecolor="none",
            )
        )
        text = _figure_text(
            figure, x + 17, y + 5.5, label, size=13, color=INK_SECONDARY, va="center"
        )
        x += 17 + text.get_window_extent(renderer).width + 24


def _percent_axis(axes: Axes, *, ticks: Sequence[float]) -> None:
    axes.set_facecolor(SURFACE)
    for spine in axes.spines.values():
        spine.set_visible(False)
    axes.set_xlim(0, 1)
    axes.set_xticks(list(ticks), [f"{tick:.0%}" for tick in ticks])
    axes.set_yticks([])
    axes.tick_params(length=0, labelsize=_pt(12), labelcolor=INK_MUTED, pad=_pt(6))
    for tick in ticks:
        if tick > 0:
            axes.axvline(tick, color=GRIDLINE, linewidth=_pt(1), zorder=0)
    axes.axvline(0, color=BASELINE, linewidth=_pt(1), zorder=0)


def _rounded_end(
    x0: float, x1: float, y0: float, y1: float, radius_x: float, radius_y: float
) -> MplPath:
    """A bar that is square at the baseline (x0) and rounded at its data-end (x1)."""
    radius_x = min(radius_x, x1 - x0)
    radius_y = min(radius_y, (y1 - y0) / 2)
    vertices = [
        (x0, y0),
        (x1 - radius_x, y0),
        (x1, y0),
        (x1, y0 + radius_y),
        (x1, y1 - radius_y),
        (x1, y1),
        (x1 - radius_x, y1),
        (x0, y1),
        (x0, y0),
    ]
    codes = [
        MplPath.MOVETO,
        MplPath.LINETO,
        MplPath.CURVE3,
        MplPath.CURVE3,
        MplPath.LINETO,
        MplPath.CURVE3,
        MplPath.CURVE3,
        MplPath.LINETO,
        MplPath.CLOSEPOLY,
    ]
    return MplPath(vertices, codes)


def _label_inside(
    axes: Axes, renderer: RendererBase, x0: float, x1: float, y: float, share: OutcomeShare
) -> None:
    """Place a percentage inside a segment only if it fits with padding; never clip it."""
    label = axes.text(
        (x0 + x1) / 2,
        y,
        f"{share.share:.0%}",
        ha="center",
        va="center",
        color=ink_on(share.color),
        fontsize=_pt(12),
    )
    available = (x1 - x0) * axes.bbox.width
    if label.get_window_extent(renderer).width + 16 > available:
        label.remove()


def _relative_luminance(hex_color: str) -> float:
    channels = [int(hex_color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]
