# How to generate the two diagrams

Run the prompt below **twice** — once per JSON file. Paste the prompt text, then paste the
entire contents of the JSON file directly underneath it in the same message.

Works with Gemini (Nano Banana Pro), ChatGPT image gen, or any image model that accepts long prompts.

---

## THE PROMPT (paste this, then paste the JSON below it)

Generate a single high-resolution 16:9 software architecture diagram.

STYLE — this is the most important part:
Flat 2D vector illustration in the style of an official AWS or Azure reference-architecture
diagram. Pure white background with a very faint light-grey dot grid. No 3D, no isometric
projection, no photorealism, no gradients, no drop-shadow clutter, no decorative background art.

Every component is drawn as a white rounded-rectangle card with a 2px coloured border and a soft
shadow. In the top-left corner of each card sits a 48x48 rounded square icon tile filled with that
component's accent colour, containing a simple white line-art glyph. A small numbered circle badge
in the same accent colour sits on the card's top-left edge. Inside the card: the component name in
bold dark-navy 18px, and one short grey caption line beneath it.

Arrows are thin dark-grey orthogonal lines with solid triangular arrowheads, each labelled with a
few words in small grey italic text. Typography is Inter or Helvetica throughout.

CONTENT:
Build the diagram strictly from the JSON specification below.
- `title` is large bold dark-navy text at the top centre; `subtitle` is smaller grey text beneath it.
- Each entry in `components` is one card. Use its `name`, `caption`, `step` number, the accent
  colour looked up from `color_key` using its `role`, and draw the glyph described in
  `icon_description`. Place it according to its `position` field. Honour any `emphasis` field.
- Each entry in `groups` is a dashed rounded boundary drawn around the listed components, with the
  group `label` in small text at the boundary's top-left.
- Each entry in `connections` is a labelled arrow from the source card to the target card. Apply the
  `style` field where present (red dashed for failure/repair paths, purple for tool calls, amber for
  human/feedback paths).
- Each entry in `callouts` is a small banner or note box placed as its `placement` describes.
- `legend` is a single horizontal row of colour swatches with labels in the bottom-left corner.

RULES:
Spell every label exactly as written in the JSON. Do not invent, rename, merge, or omit any
component. Do not add any element that is not in the specification. Leave generous whitespace —
readability beats density. All text must be crisp and legible.

Here is the specification:

```json
<PASTE THE FULL CONTENTS OF THE JSON FILE HERE>
```

---

## Tips if the first result is poor

- If text comes out garbled, add: "Render all text as clean, sharp, correctly spelled vector type."
- If it ignores layout, add: "Arrange the cards in a single left-to-right row as the `position`
  fields describe. Do not stack them in a grid."
- Generate the two diagrams in the **same chat session** and for the second one add: "Match the
  exact visual style, card design, icon tile style and arrow style of the previous diagram."
  That consistency matters more than anything else when the two are shown side by side.
