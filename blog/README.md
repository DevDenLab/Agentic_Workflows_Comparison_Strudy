# blog/

A long-form write-up of the whole experiment, in Markdown, ready to paste into Medium, Dev.to,
Hashnode or a GitHub README.

| File | What it is |
|---|---|
| [`rules-vs-llm-vs-agent.md`](rules-vs-llm-vs-agent.md) | The post. Terminology first, then v1 → v1.5 → v2, then the benchmark and the honest read. |
| `images/00-banner.png` | Cover image, 1600×838 (1.91:1, works as a social card too). |
| `images/01`–`09` | Every figure in the post, PNG at 2× plus an SVG twin. |
| `make_diagrams.py` | Generates all of the above. |

## Regenerating the figures

```bash
python blog/make_diagrams.py
```

Every chart reads `reports/benchmark/*/summary.json`, so the numbers in the images cannot drift
from the numbers in the post. Re-run `make bench` first if the benchmark has changed.

Figures are drawn with matplotlib rather than hand-written SVG because blog platforms do not render
inline SVG reliably — the PNGs are the ones to upload, and the SVGs are there if you want to scale
or edit them.

## Publishing notes

- Image links are relative (`images/…`), which works on GitHub as-is. Most platforms want the
  images uploaded individually — the filenames are ordered so they match the order they appear.
- The post assumes no prior knowledge: the terminology section defines everything from "triage" to
  "prompt injection" before it is used.
- Every number in it came from the committed benchmark summaries, and every ticket quoted is a real
  case from `data/golden/`.
