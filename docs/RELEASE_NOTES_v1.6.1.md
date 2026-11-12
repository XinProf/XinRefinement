# XinRefinement v1.6.1 — Pattern operation row and license information

> Baseline `v1.6.0` | Theme: **give the pattern a control panel**. v1.6.0 solved "how to tell
> the result", but the pattern itself was still read-only — only matplotlib's built-in row of
> English icons, squeezed below the canvas; zooming into an angle range meant probing with the
> wheel, and measuring a peak position meant taking a screenshot and comparing. This version
> makes six small UI adjustments and fills in complete copyright and license information on
> the Help page.
>
> **Zero numerical change**: the golden 50/50 case is still `3.4074156640940005`, CLI/API
> behaviour bit-for-bit unchanged.

## Download

| File | Size | SHA256 |
|---|---|---|
| `XinRefinement-1.6.1-setup.exe` | 75.8 MB | `34cb1288a16d282e1aa87d8a9446e40996225c92a5dcffd9a5cfa92dcef49b9d` |

> Release installer (includes registration, zh/en/ja installer UI). The internal evaluation
> portable build (`XinRefinement-internal-1.6.1-portable.zip`, 114.2 MB,
> sha256 `64afe606ebc5f6bd11811a243dad16dec54f76bace9c607dbbe04324f29658de`)
> is for internal acceptance only and is not distributed with this Release.

## What changed at a glance

| | v1.6.0 | v1.6.1 |
|---|---|---|
| Shortcut icon position | Squeezed **below** the pattern, chip 36 | Moved **above** the pattern, chip 30 (one size smaller) |
| Pattern operations | Only matplotlib's built-in pan/zoom | Adds **a row of 9 dedicated buttons**: reset / horizontal box zoom / vertical box zoom / rectangle box zoom / move left / move right / zoom in / zoom out / crosshair |
| Measuring peak position | Screenshot, then compare with a ruler | Crosshair **red vertical line follows the mouse** with a readout (angle + intensity), **right-click** drops a manual peak position, right-click again deletes it |
| Status bar "internal evaluation build" | Right-aligned, small, grey | **Centred, one size larger, red bold** |
| Bottom-left title | "Refinement log (run log)" | "Refinement log" |
| Help menu | Only "About…" (one-line summary) | Adds "**Copyright and license…**", opening a dialog with the **full license text** |
| Step gears | All the same colour | **Eight distinct colours** (one per step + tooltip) |

## Main changes

### 1. Pattern operation row (9 buttons)

Layout: middle column from top to bottom = matplotlib navigation bar → **pattern operation row** → pattern canvas.

| # | Button | Behaviour |
|---|---|---|
| ① | Original pattern | Restore the initial view (including reversed axis direction in d mode) |
| ② | Horizontal box zoom | Drag an angle range, **changes the horizontal axis only** |
| ③ | Vertical box zoom | Drag an intensity range, **changes the vertical axis only** |
| ④ | Rectangle box zoom | Drag a rectangle, changes both axes |
| ⑤ | Move left | Shift the view left by 1/4 of its width |
| ⑥ | Move right | Shift the view right by 1/4 of its width |
| ⑦ | Zoom in | Anchor at the **centre** of the view, zoom in step by step |
| ⑧ | Zoom out | The reverse of the above |
| ⑨ | Crosshair | Red vertical line follows the mouse, top right shows `2θ = …° · I = …`; **right-click** adds a manual peak position |

Key points:

- ②③④ are **three tools with clearly divided duties**, not "box zoom always squeezes both
  axes": when only the horizontal axis is squeezed the vertical axis **adapts to the current
  view automatically**, otherwise zooming into a weak peak is still flattened by the highest
  peak of the whole pattern and the button looks unresponsive.
- ⑤⑥⑦⑧ are **discrete operations**: panning uses a fixed fraction of the view width, zooming
  anchors at the view centre and does not use the mouse position (where the mouse happens to be
  when the button is clicked carries no meaning).
- ⑨ manual peak positions are drawn as a **red dashed line + vertical angle label**; a
  right-click within `0.25°` of an existing position deletes it. **Leaving the crosshair tool
  hides the line but keeps the manual peak positions.** Switching patterns (loading new data)
  clears both — keeping the previous sample's annotations is more misleading than having none.
- Pattern operations and matplotlib's built-in pan/zoom are **mutually exclusive** (two drag
  systems would fight over the same mouse events); clicking the same button again exits and
  hands the original axis-click semantics back.

### 2. Navigation bar one size smaller, moved above the pattern

`NavigationToolbar2QT` moves from below the canvas to above it, chip 36 → **30**, `iconSize`
24 → 20, colour scheme unchanged. The two rows of "operations on the plot" now sit next to
each other, no more hunting across the canvas.

### 3. Status bar "internal evaluation build" centred, larger, red bold

- `AlignRight` → `AlignCenter`, font size `+1` and bold, colour `#d32f2f`.
- It still lives in the status bar's **permanent** area: the crosshair readout and axis hints
  are emitted through `statusBar().showMessage()`, and normal widgets get temporarily covered,
  so only a permanent-area label survives.

### 4. Bottom left now reads "Refinement log" only

The "（run log）" suffix is removed from the title, synchronized across zh/en/ja. Window
behaviour unchanged.

### 5. Copyright and license on the Help page

- The Help menu gains **"Copyright and license…"** (above "About…", with a separator), opening
  `LicenseDialog`: license summary + read-only full text (monospace font, scrollable).
- The same button entry point is also added to the "About" dialog.
- The full text is **read from disk at runtime** (`licenses/LICENSE` / `licenses/LICENSE-CN`)
  and not duplicated in code — two copies of the text would inevitably drift. In the source
  tree it points at the two files at the repository root; the installed build ships them via
  the packaging script; when they are missing it reports "license file missing" instead of
  failing to open the dialog.

### 6. Eight-colour step gears

Zero point / background / scale / unit cell / peak shape / coordinates / microstructure /
temperature factor each get a colour, font size 16 bold, tooltip gives the step name. Colour
is an **identification aid only** and does not encode state (whether a step has run or
converged still shows through other indicators), avoiding the misreading "red means failed".

## Verification

- Full regression **527 items: 527 passed / 0 failed / 0 skipped, EXIT=0**
  (512 in v1.6.0; adds 15 in `tests/test_v161_gui.py`).
- golden CLI Rwp 50/50 case **`3.4074156640940005`** unchanged, confirming this version did
  not touch the engine.
- Canvas behaviour measured offscreen: `xlim (5.0, 89.98)` → zoom out to `(26.245, 68.735)` →
  move right 1/4 → `(36.8675, 79.3575)` → reset back to `(5.0, 89.98)`; horizontal box zoom
  dragging 20→40 gives `(20.0, 40.0)` and the rubber band disappears on release; the crosshair
  at 25.3° reads `2θ = 25.300° · I = 39728`, a right-click produces `[25.3]`, another
  right-click returns to `[]`.
- Packaged artifact check: `XinRefinementCLI.exe --version` = `XinRefinement 1.6.1`; the
  frozen package's `_internal/licenses/` is confirmed to contain `LICENSE` (2411 B) and
  `LICENSE-CN` (1887 B), and the license dialog in the installed build reads the full text
  rather than only the summary.

## Known limits

- **Sample 7 is still below standard** (+3.39 pt, the near-amorphous broad-envelope starting
  point of cristobalite); this version does not touch the engine.
- Pattern operations are a **view-layer** feature: zoom/pan/crosshair/manual peak positions do
  not enter the result tables, do not enter the report, do not participate in fitting, and are
  not saved to project files.
- Unit-cell component checkboxes affect the `cell` step only; the joint refinement of the
  `profile` step still releases the full crystal system (same as v1.6.0).

## Installation and registration

Same as v1.6.0: the installer has a built-in zh/en/ja interface, registration codes
interoperate across the XinMatch family
(`%APPDATA%\PolyXRD\Registration\XinRefinement.json`). The internal evaluation build needs
no registration and no installation, and is marked in red in the status bar.

## License

This software uses the MIT license (`LICENSE` / `LICENSE-CN`, full text viewable from the Help
menu). The bundled crystal structure data comes from COD (CC0) and ICSD-derived public
literature, and **contains no PDF cards or ICDD data**.
