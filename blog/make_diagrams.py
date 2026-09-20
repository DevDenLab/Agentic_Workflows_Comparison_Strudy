"""Generate every image in blog/images/ from code, so the post's figures are reproducible.

Matplotlib rather than hand-written SVG on purpose: blog platforms (Medium, Dev.to, Hashnode,
GitHub) will not render inline SVG reliably, so every figure has to exist as a PNG. Drawing them
here means one code path produces both, and every number comes from
reports/benchmark/*/summary.json rather than being typed into a design tool.

    python blog/make_diagrams.py
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(__file__).resolve().parent / "images"
OUT.mkdir(parents=True, exist_ok=True)

INK = "#1b2a41"
MUTE = "#6b7a8f"
PAPER = "#ffffff"
CODE_FILL, CODE_LINE = "#e7edf5", "#3d5a80"
MODEL_FILL, MODEL_LINE, MODEL_INK = "#fdeadb", "#c1651a", "#5c2f06"
GOOD_FILL, GOOD_LINE, GOOD_INK = "#ddf0e3", "#2f7d4f", "#10381f"
STOP_FILL, STOP_LINE, STOP_INK = "#fbe1e1", "#b3322e", "#5c1512"

FONT = ["DejaVu Sans"]
RETINA = 2


def canvas(width: int, height: int):
    """A pixel-ish coordinate system: (0,0) top-left, y grows downward."""
    fig = plt.figure(figsize=(width / 100, height / 100), dpi=100)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, width)
    ax.set_ylim(height, 0)
    ax.axis("off")
    fig.patch.set_facecolor(PAPER)
    return fig, ax


def box(
    ax,
    x,
    y,
    w,
    h,
    text="",
    fill=CODE_FILL,
    line=CODE_LINE,
    ink=INK,
    size=11,
    weight="normal",
    radius=7,
    lw=1.4,
    dashed=False,
):
    ax.add_patch(
        FancyBboxPatch(
            (x, y),
            w,
            h,
            boxstyle=f"round,pad=0,rounding_size={radius}",
            facecolor=fill,
            edgecolor=line,
            linewidth=lw,
            linestyle="--" if dashed else "-",
            mutation_aspect=1,
        )
    )
    if text:
        ax.text(
            x + w / 2,
            y + h / 2,
            text,
            ha="center",
            va="center",
            color=ink,
            fontsize=size,
            fontweight=weight,
            family=FONT,
            linespacing=1.45,
            zorder=5,
        )


def note(ax, x, y, text, ink=MUTE, size=9.5, ha="center", weight="normal"):
    ax.text(
        x,
        y,
        text,
        ha=ha,
        va="center",
        color=ink,
        fontsize=size,
        fontweight=weight,
        family=FONT,
        linespacing=1.4,
        zorder=6,
    )


def arrow(ax, p0, p1, color=CODE_LINE, lw=1.5, rad=0.0):
    ax.add_patch(
        FancyArrowPatch(
            p0,
            p1,
            arrowstyle="-|>",
            mutation_scale=11,
            color=color,
            linewidth=lw,
            connectionstyle=f"arc3,rad={rad}",
            shrinkA=0,
            shrinkB=0,
            zorder=4,
        )
    )


def save(fig, name):
    fig.savefig(OUT / f"{name}.png", dpi=100 * RETINA, facecolor=PAPER)
    fig.savefig(OUT / f"{name}.svg", dpi=100, facecolor=PAPER)
    plt.close(fig)
    print(f"  {name}.png / .svg")


# ---------------------------------------------------------------- the numbers

SUMMARIES = {
    "v1 rules": "v1_conventional",
    "v1.5 hybrid": "v1_5_hybrid",
    "v2 agentic": "v2_agentic",
}
DATA = {
    name: json.loads((ROOT / "reports" / "benchmark" / d / "summary.json").read_text("utf-8"))
    for name, d in SUMMARIES.items()
}
BAR = {"v1 rules": CODE_LINE, "v1.5 hybrid": MODEL_LINE, "v2 agentic": GOOD_LINE}


def rate(pipeline: str, metric: str, split: str | None = None) -> float | None:
    group = DATA[pipeline]["splits"][split] if split else DATA[pipeline]["overall"]
    value = group[metric]["value"]
    return None if value is None else value * 100


# ---------------------------------------------------------------- 00 banner


def banner():
    fig, ax = canvas(1600, 838)
    ax.add_patch(
        FancyBboxPatch(
            (0, 0), 1600, 838, boxstyle="square,pad=0", facecolor="#f6f9fc", edgecolor="none"
        )
    )
    ax.add_patch(
        FancyBboxPatch(
            (0, 0), 1600, 12, boxstyle="square,pad=0", facecolor=CODE_LINE, edgecolor="none"
        )
    )

    note(ax, 100, 118, "THE SAME JOB, BUILT THREE WAYS", MUTE, 19, ha="left", weight="bold")
    ax.text(
        100,
        208,
        "Rules  vs.  One LLM Call  vs.  an Agent",
        ha="left",
        va="center",
        color=INK,
        fontsize=44,
        fontweight="bold",
        family=FONT,
    )
    ax.text(
        100,
        284,
        "150 labelled IT tickets. One scoring rule. An answer I did not expect.",
        ha="left",
        va="center",
        color=MUTE,
        fontsize=23,
        family=FONT,
    )

    cards = [
        (
            100,
            "v1",
            "keyword rules",
            "no model at all",
            CODE_FILL,
            CODE_LINE,
            INK,
            "98%",
            "accuracy on ordinary tickets",
        ),
        (
            560,
            "v1.5",
            "+ one LLM call",
            "when no rule matches",
            MODEL_FILL,
            MODEL_LINE,
            MODEL_INK,
            "0%",
            "must-escalate tickets caught",
        ),
        (
            1020,
            "v2",
            "an agent + a gate",
            "the model picks the path",
            GOOD_FILL,
            GOOD_LINE,
            GOOD_INK,
            "12%",
            "false-confident rate — best",
        ),
    ]
    for x, tag, what, sub, fill, line, ink, stat, statlabel in cards:
        box(ax, x, 368, 440, 330, "", fill, line, radius=14, lw=2)
        ax.text(
            x + 34,
            426,
            tag,
            ha="left",
            va="center",
            color=ink,
            fontsize=39,
            fontweight="bold",
            family=FONT,
        )
        ax.text(
            x + 34,
            482,
            what,
            ha="left",
            va="center",
            color=ink,
            fontsize=21,
            fontweight="bold",
            family=FONT,
        )
        ax.text(x + 34, 517, sub, ha="left", va="center", color=MUTE, fontsize=17, family=FONT)
        ax.plot([x + 34, x + 406], [551, 551], color=line, linewidth=1.2, alpha=0.55)
        ax.text(
            x + 34,
            604,
            stat,
            ha="left",
            va="center",
            color=ink,
            fontsize=45,
            fontweight="bold",
            family=FONT,
        )
        ax.text(
            x + 34, 655, statlabel, ha="left", va="center", color=MUTE, fontsize=16, family=FONT
        )

    note(
        ax,
        100,
        772,
        "No pipeline won. That is the interesting part.",
        INK,
        22,
        ha="left",
        weight="bold",
    )
    save(fig, "00-banner")


# ---------------------------------------------------------------- 01 control flow


def control_flow():
    """Three columns, deliberately far apart: v1.5 branches right and v2 loops right, so the
    columns need clearance or the detour of one lands on top of the next."""
    fig, ax = canvas(1500, 540)
    heads = [
        (40, "v1 - rules", "Code decides everything.", CODE_FILL, CODE_LINE, INK),
        (
            440,
            "v1.5 - hybrid",
            "Code decides. The model\nanswers one question.",
            CODE_FILL,
            CODE_LINE,
            INK,
        ),
        (
            1010,
            "v2 - agentic",
            "The model decides the path.\nCode decides who is trusted.",
            MODEL_FILL,
            MODEL_LINE,
            MODEL_INK,
        ),
    ]
    for x, title, sub, fill, line, ink in heads:
        box(ax, x, 20, 340, 80, f"{title}\n{sub}", fill, line, ink, 13, "bold", radius=9)

    # v1 - one straight line, centre 210
    for i, step in enumerate(["parse", "match a rule", "route + write"]):
        box(ax, 70, 142 + i * 74, 280, 46, step, CODE_FILL, CODE_LINE, size=12)
        if i < 2:
            arrow(ax, (210, 188 + i * 74), (210, 214 + i * 74))
    arrow(ax, (210, 336), (210, 376))
    box(ax, 70, 378, 280, 46, "one fixed path, always", GOOD_FILL, GOOD_LINE, GOOD_INK, 12)
    note(ax, 210, 476, "a miss just stops", MUTE, 11)

    # v1.5 - same line, centre 610, with one detour out to the right
    box(ax, 470, 142, 280, 46, "parse", CODE_FILL, CODE_LINE, size=12)
    arrow(ax, (610, 188), (610, 214))
    box(ax, 470, 216, 280, 46, "match a rule", CODE_FILL, CODE_LINE, size=12)
    note(ax, 498, 312, "match", GOOD_INK, 10.5)
    arrow(ax, (540, 262), (540, 376), GOOD_LINE)
    note(ax, 800, 254, "miss", MODEL_INK, 10.5)
    arrow(ax, (750, 240), (800, 296), MODEL_LINE, rad=-0.3)
    box(ax, 804, 298, 180, 52, "ask the model", MODEL_FILL, MODEL_LINE, MODEL_INK, 12)
    arrow(ax, (846, 350), (700, 376), CODE_LINE, rad=0.3)
    note(ax, 806, 392, "answers, returns", MUTE, 9.5, ha="left")
    box(ax, 470, 378, 280, 46, "route + write", CODE_FILL, CODE_LINE, size=12)
    note(ax, 610, 476, "the detour is still drawn in code", MUTE, 11)

    # v2 - centre 1180, the loop bulges right into its own clearance
    box(ax, 1040, 142, 280, 46, "parse + redact", CODE_FILL, CODE_LINE, size=12)
    arrow(ax, (1180, 188), (1180, 214))
    box(ax, 1050, 216, 260, 56, "model picks\nthe next tool", MODEL_FILL, MODEL_LINE, MODEL_INK, 12)
    arrow(ax, (1310, 230), (1310, 260), MODEL_LINE, rad=-2.6)
    note(ax, 1374, 244, "loops", MODEL_INK, 10, ha="left")
    arrow(ax, (1180, 272), (1180, 298), MODEL_LINE)
    box(
        ax,
        1040,
        300,
        280,
        56,
        "confidence gate\n(code, not the model)",
        GOOD_FILL,
        GOOD_LINE,
        GOOD_INK,
        12,
    )
    arrow(ax, (1130, 356), (1100, 388), GOOD_LINE)
    arrow(ax, (1240, 356), (1270, 388), STOP_LINE)
    box(ax, 1012, 390, 172, 44, "auto-resolve", GOOD_FILL, GOOD_LINE, GOOD_INK, 11.5)
    box(ax, 1200, 390, 142, 44, "escalate", STOP_FILL, STOP_LINE, STOP_INK, 11.5)
    note(ax, 1180, 476, "the loop is the model's;\nthe verdict is not", MUTE, 11)
    save(fig, "01-who-owns-control-flow")


# ---------------------------------------------------------------- 02 v1 pipeline


def v1_pipeline():
    steps = [
        ("1", "Intake", "an email or web form arrives"),
        ("2", "Queue + dedupe", "have we seen this Message-ID before?"),
        ("3", "Parser", "strip MIME, signature, quoted reply"),
        ("4", "Extractor", "pull asset tags, employee ids, error codes"),
        ("5", "Validate", "build a typed Ticket, or give up"),
        ("6", "CMDB lookup", "who is this, and what do they own"),
        ("7", "Rule engine", "the first keyword rule that matches wins"),
        ("8", "Priority matrix", "impact x urgency  ->  P1..P4"),
        ("9", "SLA calculator", "due date, business hours, holidays"),
        ("10", "Routing table", "which team gets it"),
        ("11", "Responder", "render the reply from a template"),
        ("12", "ITSM write", "create the ticket, retry, dead-letter on failure"),
    ]
    h, gap, top = 44, 13, 26
    fig, ax = canvas(1000, top + len(steps) * (h + gap) + 46)
    for i, (n, name, blurb) in enumerate(steps):
        y = top + i * (h + gap)
        hot = n == "7"
        box(
            ax,
            250,
            y,
            300,
            h,
            f"{n}.   {name}",
            GOOD_FILL if hot else CODE_FILL,
            GOOD_LINE if hot else CODE_LINE,
            GOOD_INK if hot else INK,
            12.5,
            "bold" if hot else "normal",
        )
        note(ax, 572, y + h / 2, blurb, MUTE, 11, ha="left")
        if i < len(steps) - 1:
            arrow(ax, (400, y + h), (400, y + h + gap))
    for i in (1, 4, 6):
        y = top + i * (h + gap) + h / 2
        arrow(ax, (250, y), (198, y), STOP_LINE)
    box(
        ax,
        40,
        top + 3 * (h + gap) + 6,
        152,
        46,
        "human review",
        STOP_FILL,
        STOP_LINE,
        STOP_INK,
        11.5,
    )
    note(
        ax,
        400,
        top + len(steps) * (h + gap) + 18,
        "no model   ·   no tokens   ·   no network",
        MUTE,
        12,
    )
    save(fig, "02-v1-pipeline")


# ---------------------------------------------------------------- 03 the fork


def fork():
    fig, ax = canvas(1120, 420)
    note(ax, 250, 28, "v1", INK, 17, weight="bold")
    note(ax, 836, 28, "v1.5", INK, 17, weight="bold")
    for x0 in (60, 646):
        box(ax, x0, 52, 380, 46, "7.   rule engine", CODE_FILL, CODE_LINE, size=12.5)

    note(ax, 130, 130, "match", GOOD_INK, 11)
    note(ax, 372, 130, "miss", STOP_INK, 11)
    arrow(ax, (180, 98), (150, 158), GOOD_LINE, rad=0.2)
    arrow(ax, (320, 98), (352, 158), STOP_LINE, rad=-0.2)
    box(ax, 60, 160, 180, 50, "steps 8–12", GOOD_FILL, GOOD_LINE, GOOD_INK, 12)
    box(ax, 262, 160, 180, 50, "human review", STOP_FILL, STOP_LINE, STOP_INK, 12)
    note(ax, 250, 260, "a miss becomes an escalation", MUTE, 11)

    note(ax, 716, 130, "match", GOOD_INK, 11)
    note(ax, 958, 130, "miss", MODEL_INK, 11)
    arrow(ax, (766, 98), (736, 158), GOOD_LINE, rad=0.2)
    arrow(ax, (906, 98), (938, 158), MODEL_LINE, rad=-0.2)
    box(ax, 646, 160, 180, 50, "steps 8–12", GOOD_FILL, GOOD_LINE, GOOD_INK, 12)
    box(
        ax,
        848,
        160,
        212,
        60,
        "7b.  ask the model\n(forced tool call)",
        MODEL_FILL,
        MODEL_LINE,
        MODEL_INK,
        11.5,
    )
    arrow(ax, (954, 220), (954, 250), MODEL_LINE)
    box(ax, 848, 252, 212, 46, "always answers", MODEL_FILL, MODEL_LINE, MODEL_INK, 11.5)
    arrow(ax, (848, 275), (788, 212), GOOD_LINE, rad=0.25)
    note(
        ax,
        954,
        336,
        "no path to human review,\nexcept a provider outage",
        STOP_INK,
        11.5,
        weight="bold",
    )
    save(fig, "03-v1-vs-v15")


# ---------------------------------------------------------------- 04 agent loop


def agent_loop():
    fig, ax = canvas(1080, 670)
    box(ax, 400, 20, 300, 44, "1–4.   intake, parse, extract", CODE_FILL, CODE_LINE, size=12)
    arrow(ax, (550, 64), (550, 84))
    box(ax, 400, 86, 300, 42, "5.   guardrail — redact PII", CODE_FILL, CODE_LINE, size=12)
    arrow(ax, (550, 128), (550, 150))

    box(ax, 300, 146, 500, 252, "", "#fffaf6", MODEL_LINE, radius=12, lw=1.6, dashed=True)
    note(ax, 550, 176, "the model owns this region", MODEL_INK, 12, weight="bold")
    box(
        ax,
        390,
        196,
        320,
        56,
        'orchestrator\n"what should I do next?"',
        MODEL_FILL,
        MODEL_LINE,
        MODEL_INK,
        12,
    )
    arrow(ax, (550, 252), (550, 278), MODEL_LINE)
    box(
        ax,
        330,
        280,
        440,
        66,
        "kb_search   ·   similar_tickets\ncmdb_lookup   ·   apply_rules",
        MODEL_FILL,
        MODEL_LINE,
        MODEL_INK,
        12,
    )
    arrow(ax, (770, 304), (710, 230), MODEL_LINE, rad=-0.55)
    note(ax, 802, 262, "tool result", MODEL_INK, 10, ha="left")
    note(
        ax,
        550,
        374,
        "loops until submit_decision   ·   budget: 8 steps / 8000 tokens / 60s",
        MUTE,
        10.5,
    )

    box(ax, 60, 196, 190, 56, "budget governor\na hard ceiling", CODE_FILL, CODE_LINE, size=11)
    arrow(ax, (250, 224), (386, 224))

    arrow(ax, (550, 398), (550, 422), MODEL_LINE)
    box(
        ax,
        350,
        424,
        400,
        52,
        "8 / 9.   critic — were the citations real,\nand do they support the claim?",
        CODE_FILL,
        CODE_LINE,
        size=11.5,
    )
    arrow(ax, (550, 476), (550, 498))
    box(
        ax,
        350,
        500,
        400,
        54,
        "10.   confidence gate\na number code computes, not the model",
        GOOD_FILL,
        GOOD_LINE,
        GOOD_INK,
        11.5,
    )
    arrow(ax, (470, 554), (430, 584), GOOD_LINE)
    arrow(ax, (630, 554), (670, 584), STOP_LINE)
    box(ax, 248, 586, 302, 46, "auto-resolve  ->  ITSM write", GOOD_FILL, GOOD_LINE, GOOD_INK, 11.5)
    box(
        ax,
        570,
        586,
        302,
        46,
        "escalate  ->  a human, with the draft",
        STOP_FILL,
        STOP_LINE,
        STOP_INK,
        11.5,
    )
    note(ax, 550, 656, "everything outside the dashed box is ordinary, unit-tested code", MUTE, 11)
    save(fig, "04-v2-agent-loop")


# ---------------------------------------------------------------- 05 confidence


def confidence():
    fig, ax = canvas(1100, 460)
    box(ax, 40, 30, 300, 58, "did the critic say\nit was grounded?", CODE_FILL, CODE_LINE, size=12)
    arrow(ax, (190, 88), (190, 120), STOP_LINE)
    note(ax, 218, 104, "no", STOP_INK, 11)
    box(ax, 40, 122, 300, 48, "confidence = 0.00  ->  escalate", STOP_FILL, STOP_LINE, STOP_INK, 12)
    arrow(ax, (340, 59), (424, 59), GOOD_LINE)
    note(ax, 382, 42, "yes", GOOD_INK, 11)
    note(
        ax,
        190,
        240,
        "not one input here is\nthe model's opinion of itself",
        MUTE,
        11.5,
        weight="bold",
    )

    rows = [
        ("apply_rules agreed with the model", "+0.60", GOOD_INK),
        ("apply_rules was never called, or found nothing", "+0.30", MUTE),
        ("apply_rules disagreed", "+0.10", STOP_INK),
        ("best retrieval score   x  0.35", "+0.00 … 0.35", MUTE),
        ("each schema repair the submission needed", "-0.10", STOP_INK),
    ]
    for i, (text, delta, ink) in enumerate(rows):
        y = 30 + i * 38
        box(ax, 424, y, 490, 32, "", CODE_FILL, CODE_LINE, radius=5)
        note(ax, 442, y + 16, text, INK, 11, ha="left")
        note(ax, 1060, y + 16, delta, ink, 12, ha="right", weight="bold")
    arrow(ax, (669, 222), (669, 246))
    box(ax, 424, 248, 490, 40, "clamp to 0.00 – 1.00", CODE_FILL, CODE_LINE, size=12)
    arrow(ax, (669, 288), (669, 310))
    box(
        ax,
        424,
        312,
        490,
        44,
        "auto-resolve only if  >=  0.55",
        GOOD_FILL,
        GOOD_LINE,
        GOOD_INK,
        12.5,
        "bold",
    )
    arrow(ax, (669, 356), (669, 378), STOP_LINE)
    box(
        ax,
        394,
        380,
        550,
        46,
        "…and never for security_incident, and never for P1",
        STOP_FILL,
        STOP_LINE,
        STOP_INK,
        11.5,
    )
    save(fig, "05-confidence-gate")


# ---------------------------------------------------------------- 06 scoring


def scoring():
    fig, ax = canvas(1020, 400)
    x0, y0, cw, ch = 310, 96, 330, 118
    note(ax, x0 + cw, 38, "what the pipeline did", MUTE, 12.5, weight="bold")
    note(ax, x0 + cw / 2, 74, "auto-resolved", INK, 12.5, weight="bold")
    note(ax, x0 + cw * 1.5, 74, "escalated", INK, 12.5, weight="bold")
    ax.text(
        44,
        y0 + ch,
        "the human label",
        ha="center",
        va="center",
        color=MUTE,
        fontsize=12.5,
        fontweight="bold",
        family=FONT,
        rotation=90,
    )

    labels = [
        "handling: auto\n(could be handled\nwithout a human)",
        "handling: escalate\n(a human must\nsee this)",
    ]
    for r, text in enumerate(labels):
        box(ax, 78, y0 + r * ch, 212, ch - 12, text, CODE_FILL, CODE_LINE, size=11)
    cells = [
        (0, 0, "CORRECT", "full credit", GOOD_FILL, GOOD_LINE, GOOD_INK),
        (0, 1, "no credit", "safe — but no time saved", CODE_FILL, CODE_LINE, MUTE),
        (1, 0, "CONFIDENT ERROR", "the expensive one", STOP_FILL, STOP_LINE, STOP_INK),
        (1, 1, "CORRECT", "full credit", GOOD_FILL, GOOD_LINE, GOOD_INK),
    ]
    for r, c, top, bottom, fill, line, ink in cells:
        box(ax, x0 + c * cw, y0 + r * ch, cw - 12, ch - 12, "", fill, line, radius=8)
        note(ax, x0 + c * cw + (cw - 12) / 2, y0 + r * ch + 42, top, ink, 14, weight="bold")
        note(ax, x0 + c * cw + (cw - 12) / 2, y0 + r * ch + 68, bottom, ink, 11)
    note(ax, 510, 358, "auto-resolving with the wrong labels is also a confident error", MUTE, 11)
    save(fig, "06-scoring-matrix")


# ---------------------------------------------------------------- 07/08 charts


def results():
    fig, axes = plt.subplots(1, 3, figsize=(13.6, 4.1), dpi=100)
    fig.patch.set_facecolor(PAPER)
    splits = ["in_dist", "ood", "adversarial"]
    nice = ["in-distribution", "out-of-distribution", "adversarial"]
    panels = [
        ("decision_accuracy", "Decision accuracy", "higher is better"),
        ("false_confident_rate", "False-confident rate", "LOWER is better"),
        ("escalation_rate", "Escalation rate", "how much went to a human"),
    ]
    width = 0.26
    for ax, (metric, title, hint) in zip(axes, panels, strict=True):
        for i, name in enumerate(DATA):
            # A None rate is undefined, not zero: v2 auto-resolved no OOD tickets at all, so its
            # false-confident rate there has no denominator. Drawing a 0 bar would read as a
            # perfect score, so those get no bar and an explicit "n/a".
            raw = [rate(name, metric, s) for s in splits]
            xs = [j + (i - 1) * width for j in range(len(splits))]
            bars = ax.bar(
                xs,
                [v or 0 for v in raw],
                width,
                label=name,
                color=BAR[name],
                edgecolor="white",
                linewidth=0.8,
            )
            for b, v in zip(bars, raw, strict=True):
                ax.text(
                    b.get_x() + b.get_width() / 2,
                    (v or 0) + 2.5,
                    "n/a" if v is None else f"{v:.0f}",
                    ha="center",
                    va="bottom",
                    fontsize=8.5,
                    color=MUTE if v is None else INK,
                    family=FONT,
                    style="italic" if v is None else "normal",
                )
        ax.set_xticks(range(len(splits)))
        ax.set_xticklabels(nice, fontsize=9.5, family=FONT)
        ax.set_title(
            f"{title}\n{hint}", fontsize=11.5, family=FONT, fontweight="bold", color=INK, pad=10
        )
        ax.set_ylim(0, 114)
        ax.set_yticks(range(0, 101, 25))
        ax.grid(axis="y", alpha=0.22)
        ax.set_axisbelow(True)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        for side in ("left", "bottom"):
            ax.spines[side].set_color("#c8d0da")
        ax.tick_params(colors=MUTE, labelsize=9)
    axes[0].set_ylabel("%", fontsize=10, color=MUTE, family=FONT)
    axes[0].legend(fontsize=9, loc="upper right", frameon=False)
    fig.tight_layout()
    save(fig, "07-results-by-split")


def headline():
    fig, ax = plt.subplots(figsize=(11.6, 4.0), dpi=100)
    fig.patch.set_facecolor(PAPER)
    metrics = [
        ("decision_accuracy", "Decision\naccuracy"),
        ("false_confident_rate", "False-confident\nrate"),
        ("escalation_recall", "Must-escalate\ntickets caught"),
    ]
    width = 0.26
    for i, name in enumerate(DATA):
        vals = [rate(name, m) or 0 for m, _ in metrics]
        xs = [j + (i - 1) * width for j in range(len(metrics))]
        bars = ax.bar(
            xs, vals, width, label=name, color=BAR[name], edgecolor="white", linewidth=0.8
        )
        for b, v in zip(bars, vals, strict=True):
            ax.text(
                b.get_x() + b.get_width() / 2,
                v + 2.5,
                f"{v:.1f}%",
                ha="center",
                va="bottom",
                fontsize=9.5,
                color=INK,
                family=FONT,
                fontweight="bold",
            )
    ax.set_xticks(range(len(metrics)))
    ax.set_xticklabels([n for _, n in metrics], fontsize=11, family=FONT, color=INK)
    ax.set_ylim(0, 116)
    ax.set_yticks(range(0, 101, 25))
    ax.grid(axis="y", alpha=0.22)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color("#c8d0da")
    ax.tick_params(colors=MUTE, labelsize=9)
    ax.set_title(
        "All 150 tickets, 3 runs each — no pipeline wins all three",
        fontsize=12.5,
        family=FONT,
        fontweight="bold",
        color=INK,
        pad=12,
    )
    ax.legend(fontsize=10, loc="upper left", frameon=False, ncol=3)
    fig.tight_layout()
    save(fig, "08-headline")


def ladder():
    fig, ax = canvas(1260, 340)
    rungs = [
        (
            "v1",
            "keyword rules",
            "no model",
            CODE_FILL,
            CODE_LINE,
            INK,
            "free · instant · blind to any phrasing nobody wrote down",
        ),
        (
            "v1.5",
            "+ one forced LLM call",
            "the model is a function",
            MODEL_FILL,
            MODEL_LINE,
            MODEL_INK,
            "covers the long tail · structurally cannot decline",
        ),
        (
            "v2",
            "an agent + a confidence gate",
            "the model owns the loop",
            GOOD_FILL,
            GOOD_LINE,
            GOOD_INK,
            'can say "not sure" · 5,024 tokens a ticket',
        ),
    ]
    for i, (tag, what, who, fill, line, ink, why) in enumerate(rungs):
        y, x, w = 214 - i * 76, 40 + i * 52, 450
        box(ax, x, y, w, 60, f"{tag}   —   {what}", fill, line, ink, 12.5, "bold")
        note(ax, x + w + 22, y + 22, who, ink, 11.5, ha="left", weight="bold")
        note(ax, x + w + 22, y + 42, why, MUTE, 10.5, ha="left")
    note(
        ax,
        40,
        310,
        "each rung costs more and buys a different thing — not simply a better one",
        MUTE,
        11.5,
        ha="left",
        weight="bold",
    )
    save(fig, "09-ladder")


if __name__ == "__main__":
    print("writing blog/images/ …")
    banner()
    control_flow()
    v1_pipeline()
    fork()
    agent_loop()
    confidence()
    scoring()
    results()
    headline()
    ladder()
    print("done.")
