# tour.json

```json
{
  "url": "https://example.com",
  "format": "landscape",
  "elements": "elements.json",
  "title_card": {"text": "Acme Notes in 20 seconds", "subtitle": "notes that write themselves", "seconds": 2.0},
  "steps": [
    {"do": "click", "target": "#2"},
    {"do": "caption", "text": "Type a thought", "seconds": 3},
    {"do": "type", "target": "#9", "text": "Buy milk and call mom"},
    {"do": "click", "target": "#10"},
    {"do": "highlight", "target": "css=#result", "seconds": 1.6},
    {"do": "caption", "text": "Free, forever", "seconds": 3.5},
    {"do": "scroll", "to": "#21", "seconds": 1.6, "at": 0.35},
    {"do": "zoom", "target": "#21", "scale": 1.8, "seconds": 2.2},
    {"do": "wait", "seconds": 0.8}
  ]
}
```

| Key | What |
|---|---|
| `url` | the page the tour starts on |
| `format` | `landscape` (1920x1080), `vertical` (1080x1920, the site's mobile layout) or `square` (1080x1080). Inspect with the same format |
| `elements` | the elements.json of inspect (for `#N` targets), relative to the tour file |
| `title_card` | optional: a title over the blurred first frame, with a subtitle and an accent bar |
| `settle`, `lead_in`, `tail` | seconds to wait after the first load (1.5), before the first step (0.6) and after the last (1.0) |
| `steps` | in order, below |

## Targets

`#12` (a number from inspect), `css=.pricing button` (any CSS selector), or `text=Start free` (visible text). A `#N` falls back to its text
when the page changed since inspect.

## Steps

| `do` | Keys | What |
|---|---|---|
| `caption` | `text`, `seconds` (2.5) | a caption at the bottom from this moment; the next steps run while it shows |
| `click` | `target`, `move_s` (0.7), `settle` (0.9) | the element is scrolled into view, the cursor glides to it, a real click with a red ripple |
| `hover` | `target`, `settle` (0.8) | the cursor glides to the element and rests (a hover effect shows) |
| `type` | `target`, `text`, `delay_ms` (70) | clicks the field and types, letter by letter |
| `press` | `key` (Enter) | a key on the focused element |
| `scroll` | `to` (a target, a pixel offset, `top` or `bottom`), `seconds` (1.4), `at` (0.25: where the target ends up, as a share of the height) | an eased scroll |
| `zoom` | `target`, `scale` (1.8), `seconds` (2), `scroll` (true) | the video zooms in on the element (eased in and out), the page waits |
| `highlight` | `target`, `seconds` (2), `cursor` (true) | a red rounded ring around the element; the cursor points at it |
| `wait` | `seconds` | the page as it is (animations keep playing) |
| `goto` | `url`, `settle` (1) | another page |

A step that fails (an element that is not there or hidden, a password field) is reported and skipped; the rest of the tour runs. The script
never types into a password or payment field and never presses Enter in a password field.

## Timing that works

- 15 to 40 seconds in all; a caption every 4 to 8 seconds; 3 to 8 words each.
- A zoom of 1.4 to 2 on something small (a price, a button, a result) for 2 to 3 seconds.
- Let a result sit for a second after the click that made it (`settle`), then highlight it.
- Vertical videos show the site's mobile layout: inspect with `--format vertical` so the numbers match.
