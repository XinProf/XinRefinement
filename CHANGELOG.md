# Changelog

> English is the default for this changelog. A complete Chinese reference
> copy is kept in [CHANGELOG-CN.md](CHANGELOG-CN.md); version numbers and
> content are kept in sync.


## Unreleased — v1.7.0 (2026-11-13) — Amorphous hump component (opt-in)

Theme: samples that contain a genuinely amorphous fraction (glass, fumed
silica) scatter a broad hump that a Bragg-only model cannot carry, and the
common workaround — a denser background — silently eats intensity from
overlapping peaks. This adds a **physical** broad component instead, refined
analytically so it cannot masquerade as background freedom.

### Feature
- `RefineConfig.amorphous = ((center_deg, fwhm_deg), ...)` and
  `amorphous_eta` (pseudo-Voigt mixing, default 0.5); CLI `--amorphous 22:9`
  (repeatable/comma-separated) and `--amorphous-eta`; GUI background dialog
  gains an "amorphous hump" group (enable + center + FWHM); `RefineRequest.
  amorphous` plus a `amorphous_hump` capability flag in the API.
- The hump amplitude is solved **in the linear layer** together with the phase
  scales and background coefficients (`linear.amorphous_basis` +
  `solve_linear_detail(amorphous=...)`), so it adds **zero nonlinear
  parameters** and cannot steal degrees of freedom from the peak model.
  Center and FWHM are user-supplied and not refined on purpose: freeing them
  degenerates into a background that absorbs overlapping peaks.
- Results expose the amplitude (`RefineResult.amorphous` /
  `SolveResult.amorphous`); background coefficients keep their old length.
- Disabled by default: with `amorphous=()` every code path is bit-identical
  to v1.6.4 (golden CLI Rwp still `3.4074156640940005`).

### Tests
- 579 → **586 collected / 586 passed / 0 skipped**; 7 new cases in
  `tests/test_v170_amorphous.py` cover basis normalisation and FWHM
  definition, amplitude recovery on a synthetic pattern (250 → 250 ±5%),
  the manual-background branch, the bit-identical disabled path, and the
  `SolveResult` contract.

### Benchmark evidence (and an honest negative result)
- Sample 7 (alpha cristobalite, re-selected texture axis, 13.072%) with a
  22°/9° hump: **13.181%** — 0.109 pt *worse*, with QPA drifting 2.7 vol%
  (quartz 16.03 → 17.41, cristobalite 19.81 → 17.15). Acceptance criterion
  (ΔRwp ≤ −0.5 pt, QPA drift ≤ 1 vol%) **not met**.
- A shape sweep at frozen parameters (5 centers × 6 FWHM, amplitude solved
  analytically) gives at best **−0.026 pt on sample 7** and **−0.076 pt on
  sample 6**, with most amplitudes coming out negative — i.e. the fit does
  not want the hump at all.
- Splitting the weighted residual by Bragg position explains why: **17.1% of
  the points sit on a peak but carry 52.8% of the squared residual**
  (on-peak mean residual +0.42σ vs +0.10σ between peaks). The remaining gap
  is a **peak-shape / intensity** problem, not an unmodelled amorphous
  background.
- Therefore the component ships as an **opt-in modelling capability for data
  that really contains glass** (where the user knows the hump position), not
  as a benchmark improvement. The next lever for samples 6/7 is the peak
  profile, not the background.
- Follow-up peak-shape experiments (2026-11-14; frozen-parameter diagnostics,
  **no production code changes**): a two-component "sharp core + broad
  Lorentz wing" profile first looked promising (best −1.112 pt, QPA drift
  0.67 vol%), but a single pseudo-Voigt using only the **existing** knobs
  (global FWHM ×0.85 plus η +0.3) reaches −1.379 pt. The new shape family
  therefore adds no expressive power and is **rejected**. `ka_ratio` scans
  top out at −0.142 pt (at 0.6), and locking QPA retains 98% of the
  dual-shape gain, so neither the Kα doublet nor phase-scale freedom is the
  bottleneck. The improvement is concentrated on the 28.5° fluorite (111)
  region: the 15–30° bin carries 83% of the total weighted-SS reduction,
  while the 24–26° region worsens.
- **K30 fixed**: whenever Popa LB anisotropy is active,
  `forward._accumulate_peaks()` takes η from `tch_eta()` and ignores
  `ProfileParams.eta`, even though the `profile` recipe step still refined it
  via `refine_eta=True`. Sweeping η from 0 to 1 changed Rwp by exactly 0 pt;
  all 7 benchmark samples run 100% through that TCH branch (0 scalar peaks)
  and the GUI ships with `aniso_auto` enabled, so the dead parameter sat on
  the product default path. `nonlinear.eta_is_active()` now probes the cached
  peak list at `refine()` entry and locally clears `refine_eta` when no
  scalar-branch peak exists. The computed pattern, Rwp and every refined
  parameter are **bit-identical on all 7 samples** (`max|diff| = 0`); only
  `n_params` drops by one, which corrects `Rexp` (previously low by
  0.0007–0.0015). `SolveResult.config` still reports the caller's original
  setting, so the public contract is unchanged. `tch_eta()` itself is
  untouched — giving the TCH branch a real η degree of freedom would move the
  default numerical path and needs its own project.
- The only surviving lever (a +0.2 η bias on TCH peaks) also **fails** the
  full-recipe on/off check: Rwp 13.2231% → 12.6790% (−0.544 pt) but QPA
  drifts 9.44 vol% (fluorite 25.09 → 34.53) and runtime grows 1.59×. This is
  the same degenerate solution as the rejected per-phase width scaling — the
  28.5° peak is fitted by moving phase fractions, not by improving the shape.
  No production code was changed in any of these experiments.


## v1.6.4 (2026-11-12) — Third batch of audit remediation (engineering robustness + read performance)

Theme: absorb the five "safe to fix, no numerical impact" items from the 2026-11-11 global
audit — bounded reclamation of the project extraction session directory, corrupted embedded
results no longer failing silently, a single read from disk for legacy text patterns, e.s.d.
repeated evaluation collapsed into one, and accumulation of recipe `records` on a second
consecutive run. **Zero changes to the engine and numerical path**
(golden CLI Rwp 3.4074156640940005 unchanged bit for bit); what is delivered is only the
user-perceivable robustness plus the repeated read/evaluation overhead.

### Fix A07: `.xinr` extraction session directory changed from "write-only, never delete" to bounded reclamation
- Root cause: the session directory in `gui/project.py` is created as `<stem>_<mtime>` under
  `tempfile.gettempdir()`, **one new directory per mtime, never cleaned up**; re-saving the
  same project after one change leaves one more copy of the embedded pattern/CIF, and
  long-term use fills up the temp directory.
- Fix: add `_session_root/_dir_bytes/_prune_sessions`; `_extract_session_dir` reclaims after
  `mkdir` (so that the current directory already exists): **triple limits of keeping the
  newest 8 / 7 days / 512 MB**, judged by mtime newest→oldest, then finally deleting from the
  oldest by total bytes.
- The current directory is **absolutely retained** by `protect`: `keep` is only a count
  threshold, entries in the top 8 but already over age are still deleted, only `protect` is
  never deleted; all `OSError` are swallowed, and a cleanup failure never affects opening the
  project.
- Expected behaviour: after an over-age directory is deleted, opening that project the next
  time **re-extracts the embedded data once** — this is expected by design, not a defect
  (the embedded data always lives in the `.xinr`; only the temporary copy is re-extracted).

### Fix A08: decoding failure of the embedded `result/refine.json` no longer silent
- Root cause: in `_load_zip`, `except (UnicodeDecodeError, json.JSONDecodeError) →
  result_full = None`; the UI result area inexplicably becomes empty, and the user cannot
  tell whether "refinement was never run" or "the project file is broken".
- Fix: the load result gains a `warnings` key (appended entry by entry on the zip path; the
  legacy `.xrp` JSON path returns an empty list for the same key, so callers need not check
  whether the key exists); `main_window.apply_project()` appends each warning to the end of
  the status-bar message, with the text "the project's embedded refinement result
  (result/refine.json) cannot be parsed and has been ignored; the result area may be
  incomplete". No modal dialog is shown.

### Fix B07: legacy text pattern 2–3 disk reads collapsed into 1
- Root cause: `load_pattern` first `read_bytes` and decodes the whole text,
  `detect_vendor_format` then `open`s and reads the 4 KB header, the FullProf
  self-consistency check of `.dat` does `read_text` over the whole file again, and the
  Shimadzu txt loaders each read it once more.
- Fix: `core/patterns.py` reads the raw bytes only once (`_decode_text` and `_read_text`
  split, the latter kept as a thin shell), passed down through four optional parameters —
  `detect_format(head=, full_text=)`, `load_pattern(raw=, key=)` and `raw=` for the 7 text
  loaders. `full_text` is only given for `.dat` (in `detect_format`, "read from disk by
  itself only when `full_text` is None"; non-`.dat` extensions do not enter that branch).
- Measured physical `open()` calls per single file: `.xy` 2→1, two-column `.csv` 2→1,
  Shimadzu `.txt` 5→1, FullProf `.dat` 3→1.
- Contract unchanged: the `Pattern.meta` key set and values (including floats) are unchanged
  verbatim (locked by `tests/data/pattern_meta_golden.json`); exception types and message
  texts are unchanged verbatim.

### Fix B02: `estimate_esd` computed in three places changed to reuse once
- Root cause: the result panel `_fill_results`, saving the project `project_state`, and
  exporting the report `export_report` each call `estimate_esd`, each time about 4p
  full-pattern forward evaluations, all on the main thread — one refinement runs it 3 times
  for nothing.
- Fix: add `MainWindow._esd_for(res)` single-value cache, key = `id(res)` + rwp/iters
  + phase name and unit cell as fallback (to prevent `id()` being reused by GC); **failures
  are also cached as results** (the exception path is equally expensive).
- Measured: 4 consecutive result-panel/save-project requests → `estimate_esd` actually
  called **1 time**.
- The returned object is shared across multiple places; callers must not modify its ndarray
  in place (already written into the docstring).

### Fix records: `run_all()` clears `state.records` before starting
- Root cause: `run_all` in `recipe.py` resets `current`/`time_report` but not
  `state.records`; when the same runner runs twice consecutively, the record count doubles
  and the rollback index is misaligned.
- Fix: one line `self.state.records.clear()` + guard test
  `test_run_all_twice_does_not_accumulate_records` (after two consecutive runs the records
  are still exactly the length of `DEFAULT_STEPS`, with the same key order).
- Measured: the same runner run twice, 8→16 before the change, 8→8 after.

### Tests
- Full regression **579 collected / 579 passed / 0 failed / 0 skipped**
  (553 collected in the previous batch; 26 cases added in this batch: the three reclamation
  limits and protect semantics in `test_project_sessions.py`, single read plus
  `pattern_meta_golden.json` metadata freeze in `test_patterns_single_read.py`, the three
  states of cache hit / cached on failure / invalidation in `test_v164_esd_cache.py`, the
  warnings key in `test_project_zip.py` and `test_i18n_project.py`, records
  non-accumulation in `test_recipe.py`; plus a concurrency/isolation-related `conftest`
  autouse fixture).
- `tests/conftest.py` adds an autouse fixture that redirects the `.xinr` extraction session
  root to `tmp_path`: tests never read or write the real `%TEMP%` (cleanup is a newly added
  write side effect; without isolation it would delete other people's data in the real temp
  directory).
- `test_version_consistency.py` is green: `__version__` / iss `AppVersion` /
  latest CHANGELOG heading agree in three places (1.6.4).

### Environment notes (pitfalls already hit — don't hit them again)
- pytest's `--basetemp` **must not be placed inside the repository working tree** (e.g.
  `D:\XinRefinement\.pytest_tmp_*`): it will hit the sandbox's "max 50 bulk deletions per
  turn" protection during the `tmp_path` reuse/cleanup phase, reporting `SystemExit: 1`,
  manifesting as 75 **false ERRORs** (not a product defect). Correct approach:
  `--basetemp="$TEMP/xinr_..."`, always with `-o addopts=""`.
- The leftover `.pytest_tmp_*` directories in the repo are historical artifacts, already
  ignored by `*pytest_tmp*/` in `.gitignore`, and are not committed as part of this delivery.

## v1.6.3 (2026-11-11) — e.s.d. report value column fix + low-risk audit fixes

Theme: fix A11 (the "value" column of the e.s.d. text/JSON report was mistakenly filled with
e.s.d. and the true parameter values were missing), and absorb 6 low-risk fixes from the
previous round of global code audit. **Zero changes to the engine and numerical path**
(golden CLI Rwp 3.4074156640940005 unchanged bit for bit).

### Fix A11: e.s.d. report "value" column
- Root cause: the e.s.d. table in `cli/refine.py` uses `zip(esd.labels, esd.esd, esd.esd)`,
  so the "value" column and the "e.s.d." column share the same source; `EsdResult` did not
  store the true parameter values.
- Fix: `EsdResult` gains `values` (`estimate_esd` fills it with `concat(x_final, c)`,
  strictly in the same order as `labels`); the text report changes to
  `zip(labels, values, esd)`, and the JSON esd section gains `values`. The calculation paths
  for e.s.d./covariance/correlation/scale/content e.s.d. are all left untouched.
- The e.s.d. of TCH boundary (X/Y=0) parameters is still recorded as NaN → the text shows
  "— (TCH boundary, undefined)", while the value column shows the true value as usual.

### Fixes (previous round of global audit F01–F06)
- F01: `name_mineral` is lost when rebuilding in the `structure_with_cell` / xyz step → display name degrades (Quartz→SiO2).
- F02: legacy `_unpack` rebuilding `ProfileParams` misses carrying over `size_strain`.
- F03: `_solve_raw` in `api.report()` misses `refine_po`, inconsistent with `api.refine()`.
- F04: `.xinr`/`.xinm` pattern serialization `10g→17g`, save/reopen identical bit for bit.
- F05: CLI `-o` auto-creates the parent directory when missing; `to_report` texture gains `model/degree/coeffs`.
- F06: step buttons still show the Chinese title after a language switch → changed to `tr(f'step.{key}')`.

### Tests
- De-fragilizing the cancellation test: the cancel predicate in
  `test_run_all_does_not_record_cancel_as_failure` changes from "absolute wall clock
  `> 0.15s`" to "residual checkpoint call count", eliminating timing false failures on slow
  machines / under heavy load; the assertion returns to the real product contract
  (cancellation is not recorded as failed), and no longer attaches the precondition "at
  least one step completed", which `run_all` never promised.

### Notes
- Baseline tier: the document's authoritative value of 532 passed / 0 skipped requires "local COD profile + XinMatch/gemmi available"; without these external dependencies, before this round of fixes it was 1 failed / 525 passed / 6 skipped, **after this round of fixes it is 0 failed / 6 skipped** (collected 553), golden unchanged bit for bit (see section 2 of `docs/audit-20261111-architecture.md`).

## v1.6.2 (released 2026-11-09) — the stop button actually stops

Theme: **"stop" takes effect only after the current step finishes — that is an implementation
defect**. After the user clicks the one-click consecutive run and wants to abort, pressing
stop takes a long time — the reason is not slow computation, but that the cancel flag is
checked only **between steps**; the multiple fitting rounds inside one step (3 solves in the
cell step, PO trial + formal + re-solve in the micro step, up to 4 LM restarts in the profile
step) all have to finish before returning to the top of the loop. **Zero changes to the
engine and numerical path** (golden unchanged); only the existing cancel hook is wired to
where it should be.

### Root cause (stated first, to avoid misdiagnosing it as a "performance problem")

```python
for step in todo:
    if self._cancel:        # ← only here is the stop flag checked
        break
    result, rec = self._runner.run_step(step, ...)
```

More importantly: the engine **already has** a fine-grained hook — `RefineConfig.cancel_cb` +
`_check_cancel()`, whose comment states "put it at the residual function entry… covers both
backends, fastest response". But the GUI never wired it up; in the whole repository only
`tests/test_recipe.py` used it once, i.e. dead code.

Measured quantification (sample 1: 5751 points / 5 phases):

| | Value |
|---|---|
| single residual evaluation | **16 ms** ← the order of magnitude of stop latency after the fix |
| entire `cell` step | **19.8 s** ← the time to wait after pressing stop before the fix |

### Fix: cancel hook wired into three residual closures

- **Main solve**: already present (`residual_fn` first line of `_build_residual`).
- **`refine_cell_full`** (unit cell engine): **an independent residual closure with no check
  at all before** — the cell step is one of the slowest steps in the whole chain; missing the
  hook here means the place that should be fastest is the slowest.
- **`refine_sites`** (coordinate engine): the numerical Jacobian performs O(n_free)
  "multi-phase full pattern + linear layer" evaluations per iteration, so the xyz step can
  also stop within a second.

### Fix: the recipe layer no longer records "cancel" as "failed"

Every engine call in the recipe is wrapped in `except Exception → StepRecord("failed")`. That
is right for genuine numerical failures (continue with the next step), but wrong for user
cancellation: after swallowing it, the log writes "some step failed" and the UI pops a fake
failure warning. Add `_reraise_if_cancelled()` to pass `RefineCancelled` through first in the
7 fallbacks; `run_all` catches it inside the step and **returns the completed part** (the
consecutive-run semantics is "stop at the last completed step", not throwing the exception to
the CLI/tests).

### Fix: UI finalization no longer stuck at "running…"

- `RefineWorker` attaches `cancel_cb=self._cancel_requested` into `inputs.config`, and
  `config_for`'s `replace()` carries it automatically into each step's config (no need to add
  a parameter to `run_step`).
- After catching `RefineCancelled`: the partial results already computed are back-filled
  through `finished_ok` as usual (the UI shows the current pattern and Rwp); only when there
  is no result does it go through `failed`, and the latter does not show a modal dialog in
  the cancellation scenario.
- On cancellation, `_on_worker_done` changes the progress bar to "stopped" and appends to the
  log `=== Refinement stopped by user (the current step was interrupted at residual evaluation) ===` (completed in all three languages).

### Fix: a test assertion that was only "accidentally true" (`test_i18n_project`)

`test_serialize_uses_relative_paths` asserts "same drive letter → relative path", but
`_rel()` uses the **prefix** semantics of `relative_to`, writing a relative path only when
the data is inside the project directory subtree. The old assertion passed only because
pytest's tmp happened to be on C:, while the project was on D: (cross-drive → absolute);
switching to a same-drive basetemp immediately turns it red, although serialization itself is
fine. Changed to genuinely test the contract: inside the subtree → relative and restorable,
outside the subtree → absolute.

### Internal

- `i18n/catalog.py` adds `log.cancelled` in each of the three languages
- `tests/test_v162_cancel.py` 5 items: in-step cancellation stops at the Nth evaluation
  (`calls == 3`), stop latency < 0.5 s, Rwp identical bit for bit when `cancel_cb=None`, the
  unit cell engine takes effect independently, cancellation in a consecutive run leaves no
  fake `failed` record

### Regression

- Full **532 items: 532 passed / 0 failed / 0 skipped, EXIT=0**
  (= 527 in v1.6.1 + 5 in this round)
- golden CLI Rwp 50/50 tiers **3.4074156640940005** unchanged (with `cancel_cb=None` the
  engine is unchanged bit for bit)

## v1.6.1 (released 2026-11-09) — pattern interaction tool row and license information

Theme: **give the pattern an operator console**. v1.6.0 made the information clear,
but the pattern itself still had only matplotlib's built-in row of English icons,
squeezed below the plot; zooming into an angle range required the scroll wheel and
dragging, and measuring a peak position required a screenshot and a ruler. This
release applies UI tweaks to the six items named one by one; **the engine and the
numerical path are untouched, line for line** (golden unchanged). All new pattern
operations are canvas-level view transforms and annotations and do not touch
refinement data.

### Design rationale (stated up front to avoid misuse)

- **Pattern operations change only "how you look", not the data**: `zoom/pan` change
  only `xlim/ylim`; `crosshair` and manual peaks are annotation layer (artist) items,
  rebuilt after a clean redraw, and never enter the result table, the report, or
  the fit
- **mode tools are mutually exclusive with matplotlib's built-in `pan`/`zoom`**: the
  two drag systems compete for the same mouse events (the built-in tools consume
  motion first at the `toolmanager` layer), so `_cancel_nav_mode()` is called before
  entering a mode; clicking the same button again exits and returns the original
  semantics of axis clicks
- **Vertical direction is strictly divided by function**: `zoom_x` compresses only the
  horizontal axis, `zoom_y` only the vertical axis, `zoom_rect` both. After
  `zoom_x`/`zoom_rect`, `_scale_y_to_view()` is called so the vertical axis fits the
  **current view** — otherwise zooming into a weak peak still leaves it flattened
  into a straight line by the global maximum, looking like "no zoom happened"
- **Reversed axes are not hard-coded**: in d mode (`2θ→d`) the horizontal axis is
  reversed; `_set_xlim/_set_ylim` restore the direction internally via
  `ax.xaxis_inverted()`, whereas assigning `(lo, hi)` directly would flip the axis back
- **The license body is stored in exactly one place**: `LicenseDialog` reads
  `licenses/LICENSE` / `LICENSE-CN` from disk at runtime and does not duplicate the
  body in code — two copies inevitably drift, and changing one while forgetting the
  other is only a matter of time

### New: pattern operation row (9 buttons, `gui/plot_tools.py` + `gui/button_icons.py`)

Layout: middle column, top to bottom = matplotlib navigation bar → **pattern
operation row** → pattern canvas.

| # | Button | Behavior |
|---|---|---|
| ① | `reset` original pattern | Restore the initial `xlim/ylim` (including d-mode direction), clear rubber-band residue |
| ② | `zoom_x` horizontal rubber band | Drag out an angle range, **changes only the horizontal axis**; the vertical axis then fits that range |
| ③ | `zoom_y` vertical rubber band | Drag out an intensity range, **changes only the vertical axis** |
| ④ | `zoom_rect` rectangular rubber band | Drag out a rectangle; both axes change |
| ⑤ | `pan_left` pan left | `pan_x(-0.25)`, view shifts left by 1/4 width |
| ⑥ | `pan_right` pan right | `pan_x(+0.25)` |
| ⑦ | `zoom_in` zoom in | `zoom_scale(0.8)`, anchored at the **center** of the view |
| ⑧ | `zoom_out` zoom out | `zoom_scale(1.25)`, same anchor |
| ⑨ | `crosshair` crosshair | Red vertical line follows the cursor + readout at upper right `2θ = …° · I = …`; **right-click** to add/remove a manual peak |

- `PatternCanvas.PLOT_TOOLS = ("zoom_x","zoom_y","zoom_rect","crosshair")`; with
  `tool=None` everything behaves as before; a rubber band draws a red band while
  dragging and computes-and-disappears on release
- **Manual peaks**: `manual_peaks: list[float]`; a click within `_PEAK_TOL=0.25°` is
  treated as removal (clicking again undoes it), otherwise the peak is inserted in
  ascending order; displayed as a red dashed line + vertical angle label, and
  `_peak_artists` is rebuilt by `_draw_overlays()` after every `_redraw()`
- **Cleared on pattern change**: `clear()` wipes manual peaks and the crosshair —
  leaving the previous sample's peak annotations is more misleading than having none
- All icons are drawn in code (`button_icons.plot_icon(key)`, five sizes 16/20/24/32/48),
  with no external assets; `QFrame.VLine` is inserted between groups, and the trailing
  `lbl_hint` serves as the crosshair readout display

### Fix: navigation bar one size smaller and moved above the pattern

- `NavigationToolbar2QT` moved from **below** the pattern to above, chip 36 → **30**,
  `iconSize` 24 → 20; coloring still goes through `colorize_nav_toolbar(toolbar, chip=30)`
- The order is intentional: above is first the "built-in tools" (pan/zoom/save image),
  immediately followed by this project's pattern operation row — both rows are
  "operations on the plot", and keeping them together beats separating them with a canvas

### Fix: status bar "internal evaluation build" centered, bold, one size larger

- `AlignRight` → `AlignCenter`; `font.setPointSizeF(max(pt, 9.0) + 1.0)` +
  `setBold(True)`, color taken from alert red
- Still uses `addPermanentWidget(label, 1)` rather than `showMessage()`: the latter is
  displaced by any single `statusBar().showMessage("2θ = …")` (the crosshair readout
  writes there), and a persistent label only survives in the permanent area

### Fix: bottom left now reads only "Refinement log", dropping "(code run)"

- `panel.log` Chinese changed from "精修日志（跑码）" to "精修日志"; en/ja synced to
  `Refinement log` / `精密化ログ`. The window's own behavior is unchanged

### New: copyright and license in the Help page

- The Help menu gains **"Copyright & License…"** (above "About…", with a separator),
  opening `LicenseDialog`: license summary + read-only full text (`QTextBrowser`,
  Consolas 11px)
- `AboutDialog`'s button area gains "View full license" in sync; both entries show
  the same content
- `license_path()` searches in order `sys._MEIPASS` → two levels above the package →
  exe directory, and returns `tr("license.missing")` instead of raising when not found
  (a missing file should not make the dialog fail to open)
- Packaging: `xinrefinement.spec`'s `datas` gains `LICENSE` / `LICENSE-CN` →
  `licenses/`, otherwise the dialog in the installed build shows only "file missing"

### New: step gear coloring (eight colors for distinction)

- `STEP_GEAR_COLORS`: `zero #1f77b4` / `bg #ff7f0e` / `scale #2ca02c` /
  `cell #d62728` / `profile #9467bd` / `xyz #8c564b` / `micro #e377c2` /
  `B #17becf`, font size 16 + bold, tooltip gives the step name
- Color is only an **identification aid** and does not encode state (whether a step
  has run or has converged is still read from other indicators), avoiding the
  misreading "red means failed"

### Internal

- `i18n/catalog.py`: about 20 keys added per language × 3 (`plot.*` 9 tooltips +
  `plot.crosshair_hint` / `cursor_x` / `cursor_d` / `cursor_y` /
  `peak_added` / `peak_removed`, `license.menu/title/view/head/summary/missing`)
- New module `gui/plot_tools.py` (`PlotToolBar` + `TOOL_GROUPS` + `MODE_TOOLS`);
  `gui/button_icons.py` grown by about 200 lines (4 color schemes + 5 drawing
  helpers + 9 button renderers)
- `PatternCanvas` new signals `cursorInfo(str)` / `manualPeaksChanged(list)`;
  the main window connects `cursorInfo` to the status bar, on the same channel as
  the existing `axisHint`
- Toolbar size parameterized: `_render_colored_icon(..., chip=)` /
  `colorize_nav_toolbar(toolbar, chip=)`, the main window passes 30
- `tests/test_v161_gui.py` 15 items (all 9 buttons present / layout order / nav bar
  size reduction / zoom-pan-reset / three rubber-band modes / crosshair readout and
  exit / peak add and remove / clear on pattern change / status bar label / log
  title / eight gear colors / license entries and body text / packaging path resolution)

### Regression

- Full **527 items: 527 passed / 0 failed / 0 skipped, EXIT=0**
  (`--basetemp` clean directory; = v1.6.0's 512 + `test_v161_gui.py` 15)
- golden CLI Rwp 50/50 bin **3.4074156640940005** (still unchanged, confirming this
  release did not touch the engine)
- `tests/test_gui_smoke.py::test_nav_toolbar_colorized_icons` assertion 36 → 30
  (direct consequence of the one-size chip reduction)

## v1.6.0 (released 2026-11-08) — UI restructuring and unit-cell checkboxes actually taking effect

Theme: **don't touch the engine, explain the results clearly**. v1.5.0 brought the
fit quality to MAUD's +0.21 pt, but the UI still used v1.0's way of organizing
information — phases were shown by CIF file name (`1Entry_96-500-0036`), the bottom
left was a string of static placeholder rows, clicking ▶ gave no indication of what
that step would refine, and quantitative results and unit-cell parameters could only
be found row by row in the summary table. This release reworks four areas per the
itemized UI requirements and, along the way, found and fixed a **functional defect**
left over from v1.5: the checkbox row in the unit-cell dialog was never passed to
the engine.

### Design rationale (stated up front to avoid misuse)

- **The default display convention is the chemical formula** (`TiO2`), with the phase
  name as subtitle (`TiO2 · Anatase`); when `_chemical_name_mineral` is missing it
  falls back to the common / systematic name, then to the file name — a three-level
  fallback guarantee that a displayable string always exists
- **Formula normalization does not change element counts**: only compacting
  (`O2 Si` → `SiO2`) and regrouping "metal → non-metal → anion" with order preserved
  within groups (`O4 S Zn` → `ZnSO4`). **No electronegativity ordering** — that would
  disrupt the familiar order of multi-metal systems such as NCA and could also
  distort the occupancy recipe
- **Polymorphs with the same name must be distinguishable**: anatase/rutile/brookite
  all have the formula `TiO2`; two `TiO2.a` entries in the log make it impossible to
  tell which is moving; when display names collide, the phase name is appended
  automatically
- **Engine default behavior is bit-for-bit unchanged**: `cell_axes` defaults to
  `None` (all axes released per crystal system); with `axes_override=None`,
  `refine_cell_full` is bit-identical to v1.5 (guarded by tests)

### New: three modes for phase display convention (`core/profile/naming.py`)

- `phase_label(struct, mode)` / `label_map(structs, mode)`,
  `mode ∈ {"formula", "label", "file"}`, `DEFAULT_PHASE_LABEL_MODE="formula"`
- Normalization only does "compact + three-group order preservation"; when no element
  can be parsed (parentheses, placeholder `?`), **only compact, never guess**
- `CifStructure` gains `name_mineral` (`parse_cif` takes the first non-empty of
  `_chemical_name_mineral` → `_chemical_name_common` →
  `_chemical_name_systematic`)
- Four places in the UI use it uniformly: the phase list at upper left, the marker
  strip below the pattern, the result summary, and the two new result pages

### New: bottom-left code-run window (MAUD-style scrolling log)

- The former `param_tree` (static placeholder list) is replaced by a read-only
  `QPlainTextEdit`: NoWrap + `setMaximumBlockCount(4000)` (long chains no longer grow
  memory without bound) + auto-scroll to bottom + a "Clear log" button
- **Three kinds of lines**: `=== start "some step" ===` / `param: old → new` /
  `=== "some step" done · Rwp a → b ===`. Parameter lines are filtered at
  **relative 1e-9** so floating-point jitter does not flood the log
- `RefineWorker.step_snapshot = Signal(str, object, object)` is emitted **before**
  `step_finished`, ensuring parameter lines come before the closing line (reversing
  the order would make the log read as "conclusion first, then parameters")
- When the first snapshot has no "previous frame" to compare against, it prints the
  **list of parameter initial values** — otherwise the log would contain only a
  single Rwp line and the user could not see what this round was actually refining
- The snapshot flattens the unit cell per phase into keys such as
  `TiO2 · Anatase.a`, so it is immediately visible which axis of which phase is moving

### New: navigation step description dialog (one-to-one with the code-run window)

- Clicking any ▶ first opens `StepDescribeDialog`: "parameters refined in this step +
  current values", "description", "click Start refinement after confirming"; the
  button reads "▶ Start refinement", not "OK" (to avoid users thinking it is the
  confirm key for changing parameters)
- Each of the eight steps has its checklist: `zero` gives the current zero offset,
  `bg` the background mode/node count/peak-shape basis, `scale` the per-phase scale,
  `cell` the **components actually refined** per phase, `profile` the U/V/W/η/asym/width
  basis, `xyz` the over-budget policy, `micro` the X/Y/anisotropic/texture settings,
  `B` the ΔB_iso and the 6 Å² upper bound
- After confirmation, **the same content** is written into the code-run window before
  starting; the header line is not printed twice

### New: two result-area tabs (bottom right)

- **Phase quantification**: display name / wt% / e.s.d. / Z / unit-cell volume, with a
  total row at the end (QPA theoretically normalizes to 100; the total row is the
  fastest consistency check)
- **Unit cell and microstructure**: display name / refined components / a b c α β γ /
  V / crystallite size D / microstrain ε — 11 columns laid out flat, no longer
  crammed into a single column
- Anisotropic phases: the coefficients are a Cholesky 3×3, and the UI takes the
  **mean of the singular values** (volume average) converted to Å / ε in the same
  dimension as the isotropic case, marking the D column with `*` (explained in the
  header tooltip); when `aniso` is present, the scalar X/Y are no longer read (after
  the micro step enables Popa LB the scalars are no longer refined, so reading only
  X/Y would keep showing the initial values)

### Fix: the unit-cell dialog checkboxes were **decorative** (v1.5 leftover defect)

- **Symptom**: `CellDialog` called `setEnabled(False)` on all checkboxes other than
  a/c and wrote "all 6 parameters released by P1.2" — a statement long out of date
  (`refine_cell_full` had already released all parameters per crystal system); more
  seriously, `_settings["cell"]` **was never passed to the engine**, so checking a box
  did nothing and refinement always released everything per crystal system
- **Fix**: `RefineConfig.cell_axes: dict | None` (phase name → allowed components) →
  `recipe._run_cell` → `refine_cell_full(axes_override=...)` →
  `apply_cell_scales(..., axes=...)`; `resolve_axes(system, requested)` gives the
  single convention "allowed by crystal system ∩ user selection", silently dropping
  illegal axes
- **Dialog rework**: one group box per phase, an internal 3×2 checkbox grid, two
  columns side by side (four phases no longer require scrolling 24 rows); axes that
  are not free in the crystal system are greyed out with a reason tooltip (cubic
  releases only a; tetragonal/hexagonal/trigonal release a and c; monoclinic adds β;
  triclinic releases all)
- **Degree-of-freedom count synced**: the recipe message used to report "2 params"
  per the crystal system's full release, and still reported 2 when only a was
  checked; it now reports "1 param" per the selection
- End-to-end verification: `{'anatase': ('a',), 'rutile': ('a',)}` → only a moves
  (3.785 → 3.78215), c stays at 9.5196

### Fix: layout of Edit → Phase parameter editing (single column was incomplete)

- The page now uses a two-column `QGridLayout`: unit cell / preferred orientation /
  texture and anisotropy / microstrain / symmetry in two paired columns, wrapped in a
  `QScrollArea`, minimum width 880 — with multiple phases the bottom buttons are no
  longer pushed out of the window
- The phase-selection combo uses display names (`SiO2 · Quartz`), no longer CIF file names

### Fix: marker strip label below the pattern + right-click to switch convention

- The text on the left of the marker strip changed from CIF file name to display name;
  `PatternCanvas` gains `phaseLabelMode = Signal(str)`; right-clicking the marker
  strip pops up a three-mode menu (current item checked)
- Internal visibility/coloring still uses `CifStructure.name`: labels are for humans,
  keys are for the program, and conflating the two would make phase toggles fail
  after switching convention (guarded by tests)

### Internal

- `i18n/catalog.py`: about 40 keys added per language × 3 (`panel.log` / `log.*` /
  `quant.*` / `cell.*` / `disp.*` / `stepdesc.*`)
- `retranslate()` now locates tabs via `result_tabs.indexOf(widget)` — hard-coded
  indices shift the entire row once a page is added (that is how v1.5 got it wrong)
- `tests/test_v16_naming_and_cell_axes.py` 17 items (naming 7 + cell axes 10),
  `tests/test_v16_gui.py` 20 items (code-run window 4 / display convention 3 /
  description dialog 4 / two new pages 2 / cell dialog and end-to-end 7)

### Regression

- Full **512 items: 512 passed / 0 failed / 0 skipped, EXIT=0**
  (`--basetemp` clean directory; 41 more than v1.5.0's 471 = `test_v16_*` 17+20
  + the 4 items no longer skipped after installing `gemmi` locally)
- golden CLI Rwp 50/50 bin **3.4074156640940005** (intentional value since M11, unchanged)
- Fixed two test issues **masked by skipping** (they began actually running after
  `gemmi` was installed locally):
  - `test_joint_s1`'s golden constant was still the pre-M11 `3.409617019598457`,
    while the measured API path now reproduces the golden `3.4074156640940005`
    (the `.xinm` `%.10g` round-trip still has zero deviation) → the constant was
    aligned with golden, and this history is recorded in the docstring
  - `test_xyz_phase_select`'s bit-exact assertion (`abs=0, rel=0`) differs by 8e-11
    when the full suite runs consecutively: the policy only selects phases and does
    not take part in the numerical path; the difference comes from BLAS multi-thread
    reduction not being bit-reproducible, amplified after 25 iterations → relaxed to
    relative 1e-9, while step state and degradation list remain strictly equal

## v1.5.0 (released 2026-11-07): fit quality benchmarked against MAUD

Theme: **turn "benchmarking against MAUD" from an evaluation conclusion into a product
capability**. The v1.4 cross-check proved that Popa LB anisotropy (M4) is the single
largest gain, but it existed only in benchmark scripts — on the product path it took
effect only when coefficients were written by hand for each phase (K17, same-family
defect). This version makes it a default-available capability with guardrails, and
localizes sample 7's gap to "the cristobalite structural model".

### Design rules (stated up front to avoid misuse)

- **CLI / library API remain off by default**: `aniso_auto` defaults to `False`, golden
  (3.409617019598457) bit-identical; **the GUI microstructure gear is factory-default on**,
  justified by sample 1 −3.49 / sample 7 −3.81 pt in the 7-sample cross-check
- **A new degree of freedom needs two guardrails** before it may be on by default:
  ① identifiability (phases with fewer than 8 directions are skipped automatically);
  ② **revert wholesale if not improved** (if Rwp does not decrease after the micro step
  stacks anisotropy/texture, revert to the previous step's parameters). The guardrails
  take effect only when a new degree of freedom is enabled; the default path stays
  bit-identical

### Added: M9 performance guardrail — recipe wall-clock budget and adaptive iteration reduction for slow steps

- **Motivation**: ShiJK 7-sample fully automatic measurement gives a slowest sample 4 =
  44.5 min (5-phase xyz 40-parameter downgrade); with no cap the old engine could take
  **>1 h** on pathological samples (experience uncontrollable during the GUI busy window)
- **Mechanism** (`RecipeRunner(time_budget_s=...)`, core/CLI default 0 = unlimited,
  bit-level zero regression):
  - the clock starts when a run starts; optional steps (xyz/micro/B) with insufficient
    remaining budget are recorded as `skipped` and the run continues (the chain is not
    interrupted)
  - `xyz` step: measure the **time of a single residual evaluation** with a control solve
    (or a `max_iter=1` probe), then use "numerical Jacobian ≈ 2(n_free+1) evaluations per
    iteration" to cap the site iteration limit within the remaining budget; if the budget
    does not even allow 1 iteration the whole step is skipped. Iteration counts and skip
    actions are written into `StepRecord.message` and `runner.time_report`
  - `micro` step: if the PO trial is expected to exceed the remaining budget, skip the
    trial; the iteration limit of the formal step is capped likewise
- **Wiring**: GUI factory default **45 min** (the micro gear gains "refinement time budget
  (minutes, 0=unlimited)", passed in by `RefineWorker`); CLI `--time-budget-min`
- **Verification**: `tests/test_time_guard.py` 5 items (zero regression when unlimited /
  xyz skipped under a tiny budget with results bit-identical to the truncated chain /
  micro skipped when the budget is exhausted / CLI wiring / GUI default); full regression
  exit 0

### Added: M8c polymorph suggestion (suggestion only, never auto-modifies the user's CIF)

- **Motivation**: `solve()` has long warned, when ΔB_iso hits its upper bound, that "this
  phase's structural model may not match the sample (polymorph/occupancy/disorder)", but
  that sentence **was not actionable** — the user had to go find a CIF of another
  polymorph and confirm that space group, chemical formula and atom count all matched.
  The measured evidence is hard: sample 7's cristobalite was given as high-temperature β
  (Fd-3m) while the sample is actually low-temperature α (P4₁2₁2), end-to-end 14.689 →
  **14.031** (−0.66 pt), and the ΔB_iso bound collision of that phase vanished at the
  same time (4.10 → 1.93)
- **Mechanism** (`core/refine/polymorph.py`):
  - triggering requires **three conditions at once**, preferring no report over a false
    report: ① the phase's ΔB_iso hits its upper bound; ② the normalized chemical formula
    equals the candidate's (`'O2 Si'`/`'SiO2'` both normalize to `O2Si`); ③ the space group
    equals that candidate's **baseline polymorph** (β cristobalite `Fd-3m`). Bound
    collision alone would produce false positives — in the 7-sample re-run 4 samples had a
    phase at its bound, the vast majority from texture/scale absorption
  - `apply_suggestion()` returns the replaced phase list, **keeping the original phase
    names** (so the result table, recipe messages and QPA keys never shift), and takes
    everything else from the built-in CIF
  - only the in-memory model and `_cif_paths` are changed; **the user's CIF on disk is
    never written back**: the structural model is part of the experimental facts
    (synthesis temperature, phase-transition history), and the software has no right to
    decide it for the user
- **Built-in structure**: `xinrefinement/data/cristobalite_alpha.cif`, α-cristobalite
  P4₁2₁2 (#92), a=4.9727 Å, c=6.9257 Å, Si 4a (0.301,0.301,0), O 8b (0.239,0.104,0.179).
  Values taken from COD 9017338 (Lee & Xu 2019, Acta Cryst. B75, 812) and **re-laid out
  from the structural parameters**; contains no PDF card or ICDD data
- **Wiring**: the GUI result panel gains a hidden-by-default button "Try α-cristobalite and
  re-refine" (a button rather than a modal: it neither pressures an immediate decision nor
  blocks the event loop in offscreen tests); the CLI appends "## Suggestion: the phase
  structure may be another polymorph" at the end of the report
- **Verification**: the built-in CIF is **bit-equivalent** to the α cristobalite in
  measured sample 6 (unit cell, atom list, calculated pattern max|Δ|=0, hence 14.031 is
  necessarily reproduced); `tests/test_polymorph.py` 11 items +
  `tests/test_polymorph_gui.py` 4 items

### Added: M7 optimizer numerical parameterization (λ / Jacobian step, defaults bit-identical)

- **Motivation**: MAUD's `Marquardt LS` uses λ=0.01 and a derivative step of 1e-4; our
  historical default was λ=1e-3 (the step was already 1e-4). Benchmarking requires
  **same-parameter comparison**, and these two values were hard-coded in `lm.py`.
- **Changes** (three places, all defaults = historical behavior):
  - `lm.py`: `_jacobian(..., step=1e-4)`, `lm_minimize(..., lambda0=1e-3, step=1e-4)`,
    `h = step·max(1,|x_j|)`;
  - `optimizers.py`: `_run_lm` takes `lambda0`/`step` from `kw` (defaults if not given);
  - `nonlinear.py`: `RefineConfig.lm_lambda0` / `lm_step`, passed through at both
    `_optimize(...)` call sites (main call and restart chain);
  - CLI: `--lm-lambda` / `--lm-step`.
- **Conclusion: judged as noise, no default value change.** Sample 1 jointly refined from
  the original starting point (zero+UVW+η+asym+cell+tent19), three λ levels = 1e-3 / 3e-3 /
  1e-2: Rwp = 23.8142 / **23.7725** / 23.8097, **range 0.042 pt and non-monotonic**,
  maximum QPA drift 0.08 vol% → damping is not the convergence bottleneck (project plan
  §1.11). The knobs are kept for same-parameter comparison; **the default path is unchanged
  by a single byte**.
- **Incidental evidence K23**: **all three** levels gave `restarted=True` — the restart
  chain triggers on "Rwp>10%", which real measured samples always satisfy, so every
  `refine_uvw=True` runs 3 extra restart points (the bulk of the 302–511 s in this table).
  This is a real cost problem, but changing it changes numbers, so it is left for later
  (the criterion should be "restart candidates are selected and do not degrade", not
  deleting restarts).
- **Verification**: `tests/test_lm_params.py` 11 items (defaults bit-identical / λ only
  affects the path, not the minimum / a larger λ gives more conservative steps / the step
  size does not change Jacobian accuracy / `_run_lm` pass-through / `RefineConfig` defaults
  = historical / config actually reaches `_optimize` / CLI flag and mapping); **golden
  8-level bit comparison** (see the tripwire below); full regression **471 items: 467
  passed / 4 skipped, EXIT=0** (all 4 skips are XinMatch-related, reasons now surface the
  real exception).

### Conclusion (negative): M5 peak-shape basis change (tanθ → 1/d) inconsistent across three samples, default stays tan-based

- **Motivation**: the tanθ basis `FWHM² = U·tan²θ + V·tanθ + W` **diverges** as 2θ→180°
  (with pure corundum U=0.188, FWHM ≈ 0.85° at 100°, whereas GSAS-II gives only 0.11° at
  the same position). MAUD's `caglioti_d_dep` uses `x = 1/d = 2sinθ/λ`, which **saturates
  at 2/λ** as 2θ→180° instead of blowing up, and looks like the more reasonable
  parameterization.
- **Engine-side additions** (defaults bit-identical):
  - `forward.caglioti_d(wavelength, U, V, W)` and `width_function(prm, ...)` dispatch on
    `ProfileParams.width_basis` (new field, default `"tan"`);
  - `size_strain.fwhm_gaussian/split_fwhm` gain `basis`/`wavelength` parameters — **this is
    mandatory**; all phases in the 7 samples enable Popa LB and go through the
    `split_fwhm` branch, so changing only `width_function` equals no change (we got this
    wrong once in the first version, and the first round of «no gain» was a false negative);
  - `convert_width_basis(...)`: **starting-point migration** for a basis change
    (3-parameter linear least squares over 240 equally spaced points). Note that it is a
    starting-point migration, **not an identity transform** — the d basis cannot fit the
    tan basis's high-angle divergence, so the round trip does not return the original
    coefficients; the two bases are equivalent, and the conversion exact, only when
    `U=V=0` (pure constant W);
  - the three call sites `lebail` / `valley` / `rbragg` dispatch accordingly;
  - CLI `--width-basis {tan,d}`.
- **Falsification experiment** (same recipe chain, only the basis changed):

  | Sample | MAUD | tan basis | d basis | Δ | Max QPA drift |
  |---|---:|---:|---:|---:|---|
  | 1 | 10.90 | 11.880 | **11.699** | −0.180 | 2.66 vol% |
  | 5 | 14.87 | 15.865 | 15.840 | −0.025 | 0.29 vol% |
  | 7 | 11.30 | 14.689 | **15.399** | **+0.710** | 2.31 vol% |

  Three-sample mean **+0.168 (worse)**, and the directions are inconsistent → **no
  portable gain whatsoever**.
- **Most intriguing finding**: sample 7 is precisely the sample with the heaviest
  cristobalite broad hump, and it got clearly worse after the basis change. This shows
  that the tan basis's high-angle divergence **partly corresponds to real broadening**
  (near-amorphous phases really are broader at high angle), and forcing a bounded basis
  instead suppressed the broadening that ought to be there. This corrects the intuition
  that "high-angle divergence must be a model defect", and demotes that project-plan
  justification in §1.5 from "defect" to "parameterization preference".
- **Product action**: **the default remains tan-based** (behavior since v1.0,
  bit-identical); `--width-basis d` and `ProfileParams.width_basis` are kept as
  experimental knobs for future re-checks after instrument or dataset changes. **Not in
  the GUI, not in factory defaults.**
- **Verification**: `tests/test_width_basis.py` 11 items (default bit-identical / analytic
  upper-bound assertion for bounded high angle under the d basis / conversion yields a
  usable starting point / conversion exact when `U=V=0` / CLI wiring / **the basis is not
  lost in a solve rebuild** / **the anisotropic path also respects the basis change**).

### Conclusion (negative): M6 per-atom B_iso + `equalTo` yields no increment, no engine rework

- **Motivation**: MAUD's approach is one `B_iso` per atom, with oxygen atoms in the same
  phase tied by `equalTo` group constraints. We only have a per-phase `ΔB_iso`. The
  project plan expected −0.3~0.8 pt, "and more physical".
- **Probe design** (`tools/probe_b_atom.py`): the per-phase `ΔB_iso` already shifts all
  atoms of the phase together, so the only new degree of freedom in per-atom B is the
  **intra-phase contrast** — with `equalTo` grouped by element this is one dimension,
  **cations vs oxygen**. At the converged point of `combo_tex_aniso`, add δ to non-oxygen
  and `−δ·n_nonO/n_O` to oxygen (the element-weighted sum is identically 0, strictly
  orthogonal to `ΔB_iso`), freeze everything else, solve only the scale/background linear
  layer, and scan δ∈[−3,3].
- **Result**: sample 1 (5 phases with 30/30/30/9/12 atoms) and sample 7 (5 phases,
  including an oxygen-free CaF₂) — **ten phases × 90 scan points, maximum gain −0.0025
  pt**, the rest landing exactly at δ=0; every curve is a **clean parabola with its vertex
  at δ=0** (rising 2–17 pt at δ=±3). Scanning each phase separately (to prevent two phases
  cancelling in opposite directions) is likewise all zero.
- **Conclusion**: the per-phase `ΔB_iso` already exhausts this dimension; opening more
  slots only adds parameters without changing Rwp. **P3 falsified, no structural-layer
  change.** Consistent with IUCr conclusion six (Rwp and QPA are decoupled) — the
  signal-to-noise ratio of this dataset cannot support such fine temperature factors. The
  probe and `--per-phase` are kept on file so that future high-count-rate synchrotron or
  low-temperature data can be re-run as is.
- **Boundary**: what is disproved is the "grouped by element" parameterization; "bridging
  oxygen / terminal oxygen grouping" is a chemical-criterion question (the Sample 5
  structural occupancy line) and is not counted under B-factor parameterization.

### Fix: golden baseline silently stale since M11 (rebuild + add a live tripwire)

- **How it was found**: while validating "default path bit-identical" for M7 this round,
  the golden assertion in `test_joint_s1.py` turned out to be **skipped** all along.
  Digging in revealed two things:
  1. the skip reason said "XinMatch is not on the import path", but the real cause was the
     missing **`gemmi`** (a XinMatch dependency). The path itself was fine; that sentence
     misled for a long time and now surfaces the real exception
     (`skip(f"XinMatch unavailable: {exc}")`);
  2. because that case was always skipped, **`tests/golden/method_b_roundtrip.json` had
     not been verified since `17525bb`** — all 8 TiO₂ round-trip levels had drifted (Rwp
     difference 1e-5 ~ 4.5e-3), and nobody noticed.

- **Attribution (via `git worktree` commit-by-commit comparison, not guesswork)**:
  `ff1f3e4` (before M11) is **bit-identical to golden at all 8 levels**; everything
  changed by `17525bb` (M11 window-boundary peak extension `_EDGE_MARGIN=3.0` +
  structure-factor vectorization). That is, **the drift comes from an intentional model
  change** (M11 added the tails of strong peaks just outside the window leaking into the
  window, a general systematic-bias correction); golden simply was not synchronized —
  **this is not a regression**.

- **Actions**:
  - rebuild golden to the current values (all 8 levels still within the original criteria,
    `judge()` = ALL PASS):

    | wa true value % | Rwp old | Rwp new | Δ |
    |---|---|---|---|
    | 0.1 | 3.8959708138097335 | 3.891433844001866 | −4.54e−3 |
    | 1   | 3.8782257222028744 | 3.8808825247049343 | +2.66e−3 |
    | 5   | 3.8054117416224207 | 3.8070177342913367 | +1.61e−3 |
    | 25  | 3.507020162018277  | 3.506232452969519  | −7.88e−4 |
    | 50  | 3.409617019598457  | **3.4074156640940005** | −2.20e−3 |
    | 75  | 3.7379587611090184 | 3.7369224494095543 | −1.04e−3 |
    | 95  | 3.9944324597818075 | 3.9943675584403002 | −6.49e−5 |
    | 99  | 4.042342465909672  | 4.042329832047317  | −1.26e−5 |

  - add `tests/test_golden_b.py`: **does not depend on XinMatch / COD archives**, uses only
    the in-repo `tests/data/virtual_b/v50_wide.xy` + built-in anatase/rutile CIFs to
    compare directly against the golden 50/50 level (five quantities `rwp`/`zero`/`U`/`V`/`W`
    at `rel=1e-12`), finishing in seconds. Any future silent baseline drift then turns red
    immediately.

- **Criterion for successors**: when a golden assertion fails, first run
  `git log -1 -- <trigger file>` to find the numerical-path change, and **do not** rebuild
  golden directly; the attribution method here (worktree commit-by-commit comparison) is
  reusable.

### Fix: M8d UI convention for background node count (node cap 30 → 60, initial value no longer drops to 3)

- **Motivation**: the best single-variant for sample 7 is a denser background (19 → 45
  nodes, −0.55 pt), and the full 7-sample re-measurement (project plan §1.9) also confirms
  improvement in 6 of 7 samples. But this path **was simply unreachable in the UI**, due to
  two defects:
  1. the background gear's node cap was hard-coded to **30**. At 5–120° with one node every
     2.5° you need 46, and the densest level under the old cap was one node per 3.8°;
  2. the dialog used `cur.get("n_bg", 3)` as the initial value, and 3 is a legacy fallback
     from the cheb era. The **first** time a user opens the background gear and clicks "OK"
     without changing anything, the factory adaptive value 19 is silently reduced to 3 —
     background flexibility collapses, with nothing abnormal visible in the UI.
- **Changes**:
  - `dialogs.py`: node cap `30 → 60`, plus a tooltip "≈1 node/6° is the factory adaptive
    value; try 1.5–2× when background undulation is pronounced or the fluorescence
    background is heavy"
  - `main_window.py`: add `_refine_window()` to consolidate the refinement-window
    convention in one place (micro gear > bg gear > fallback 5–90°), shared by
    `_make_inputs()` and the dialog initial value; `open_step_settings()` uses `setdefault`
    to inject `adaptive_n_bg(...)` for the `bg` step, so values the user set explicitly are
    not overwritten
- **Defaults unchanged**: the full 7-sample measurement (project plan §1.9) shows that the
  2.5° level pulls the mean from 11.43 to **10.90, literally 0.30 pt ahead of MAUD**, but
  this is a **false overtake** — QPA collapses: sample 4 quartz 18.09 → **10.49 vol%
  (−7.60)**, and for sample 7 a single node's difference throws the first/second phase by
  **6.0 / 6.4 vol%**. The mechanism is that surplus background nodes are collinear with the
  tails of broad/overlapping peaks, intensity moves between peaks and background at no
  cost, so Rwp necessarily drops while inter-phase scale loses identifiability. The
  intermediate 4.0° level (29 nodes) is also not worth it: sample 1 takes 63% of the gain
  while paying 62% of the drift
- **Verification**: `tests/test_bg_nodes.py` 6 items (46 nodes can be entered, explicit
  values not overwritten, window priority, dialog initial value = adaptive, no initial
  value injected for non-bg steps)
  (button hidden by default / shown on hit with replacement and re-run completed / not
  shown when no bound collision / stale suggestions cleared when a new round starts)

### Added: M8b per-phase isotropic size/strain (MAUD `Delft` convention)

- **Motivation**: `ProfileParams.X/Y` are **whole-pattern unique scalars**, whereas in
  measured multiphase samples the microstructure of different phases can differ by three
  orders of magnitude. MAUD's sample 7 model is **split per phase**: quartz
  `Delft/Isotropic` size 7586 Å, strain 4.0e-7 (i.e. no broadening), cristobalite also
  `Delft` but size 27.17 Å, strain 0.01636 (FWHM≈3.3° at 21.9°, essentially a
  near-amorphous broad hump); the other three phases use Popa LB. Until now we could only
  choose one of two: 6-parameter Popa LB for all phases, or no broadening for all phases
- **Consequence (measured)**: with Popa LB for all phases, the 6-parameter tensor of
  cristobalite ran away — FWHM in one direction was inflated to **1.87°**, whereas the
  pattern shows only **0.24°** at the same position (4.8× too broad); the model then
  filled the residual arbitrarily with a 19-dimensional EWIMV texture (adjacent bins
  jumping between 0.1 and 2.27). The 2 parameters per phase therefore do not merely "match
  MAUD better" but **impose a structural constraint on broadening**
- **Mechanism**:
  - `ProfileParams.size_strain = {phase: (X_deg, Y_deg)}`, `X = 4ε`, `Y = Kλ/D`, same
    units and semantics as the scalar X/Y
  - forward evaluation priority: if `aniso` hits that phase → use the per-peak-direction
    values; else if `size_strain` hits → use that phase's (X, Y); else use the global
    scalars `X`/`Y`. So "per-phase broad hump for cristobalite + global scalars for the
    remaining phases" can coexist
  - refinement switch `RefineConfig.refine_size_strain` (default **False**): when enabled,
    2 slots `phase[name].micro.X/.Y` are appended in the parameter registry for every phase
    **with a given starting value**; when off by default there are no slots, and the vector
    and bounds are bit-identical
- **Verification**: `tests/test_size_strain_phase.py` 5 items (bit-equivalent to scalar
  X/Y in the single-phase case / only affects the named phases / aniso takes priority /
  registry slots and pack→unpack round trip / off by default but still applied); core
  regression 139 items all pass, golden not drifted

### Added: sample 7 forensics tools (diagnostic only, not on the product path)

- `tools/diag_peak_width.py`: split the FWHM per peak into the Caglioti Gaussian term and
  the TCH Lorentzian term (when aniso is on the latter is taken per peak from `aniso_xy`
  by crystallographic direction), and compare against the measured half-width. Two
  pitfalls: ① Kα1/Kα2 are **two lines of the same hkl** (0.08° apart, Kα2 about 50%
  height); without de-duplication they are judged as "neighbour peak contamination";
  ② the measurement window must be adaptive at `4×FWHM_calc`; with a fixed window all
  12/12 cases in the 5-phase mixed pattern were rejected
- `tools/eval_sample7_bg.py`: `n_bg` scan (19/31/45). tent nodes are solved analytically
  through the linear layer, so **adding nodes does not increase the number of residual
  evaluations** and is nearly free; previously only `interp` + sparser 12 nodes had been
  tried, which never answered "does denser work". Positioned as diagnostics — a dense
  background absorbs overlapping-peak intensity and drifts QPA
- `tools/eval_sample7_sizestrain.py`: one-to-one replica of MAUD's per-phase mixed model
  (three phases Popa LB + isotropic quartz/cristobalite), two variants (seeded with MAUD
  values / neutral starting point)

### Conclusion: itemized attribution for sample 7 (M8b forensics, mostly negative results)

Sample 7 is the only sample still more than +3 above (14.689 vs MAUD 11.30). This round
changed one thing at a time on the same recipe chain; verdicts item by item (details in
`docs/立项-MAUD对标改进计划-v1.md` §1.8):

- **Effective**: replacing β cristobalite (Fd-3m) with α (P4₁2₁2) → **14.031** (−0.66 pt,
  gap +3.39 → +2.73), and the `ΔB_iso` bound collision disappears (cristobalite 4.10 →
  1.93). The control "β, no phase replacement" reproduces 14.689218140503746 bit-exactly,
  so the gain attribution is clean
- **Ineffective or worse**: anisotropy fully off +3.53, 8th-order spherical harmonics
  replacing EWIMV +1.52, replica of MAUD's three-phase LB + two-phase isotropic mixed model
  +1.92 (in the isotropic version both X/Y of cristobalite hit their upper bounds);
  tightening the B_iso upper bound from 6 to 1 Å² differs by only 0.04 pt
- **Monotonically effective but not additive**: background nodes 19→31→45 give
  14.689/14.471/14.142, but stacking with α makes it worse instead (14.095). The direction
  is closer to MAUD's interpolated background; making it a default that applies to all
  samples requires re-measuring the 7 samples first, so it is listed as a candidate
- **Conclusion**: the width-model line is **closed** — all three directions are worse;
  MAUD's 32 vol% cristobalite is propped up by its "27.2 Å/1.64% near-amorphous broad hump"
  parameterization (FWHM≈3.3° at 21.9°, an order of magnitude broader than any observable
  peak width in the pattern) and cannot be taken seriously for QPA; our 7% sharp-peak
  cristobalite is more defensible, and we do not copy it just to align

### Fix: window-boundary "peak leakage" (M11)

- **Symptom**: after M10 the residual diagnostics showed that **140–150° consumed 18.8% of
  the whole-pattern weighted SS** (local Rwp 27.98%), whereas each 15° interval in 5–140°
  has only 5.6–14.4%. At `149.5–150°` the observed peak height is 388 but the calculation
  gives only 148
- **Root cause**: reflection enumeration filtered strictly by `[tmin, tmax]`, so a strong
  peak located slightly outside the window was **dropped entirely**, although it still has
  a considerable tail inside the window. Measured over the same interval: `tmax=150` gives
  a calculated pattern maximum of 142370, `tmax=152` gives 300805 (**a 2.1× difference**)
- **Fix**: extend the `_phase_peaks` enumeration window by `forward._EDGE_MARGIN = 3.0°`;
  the accumulation side `_window_slice` already clips peaks to the grid, so no out-of-window
  intensity is introduced
- **Effect**: pure corundum **14.632 → 13.642%** (−0.99 pt); IUCr 1g base 14.029 → 13.955%.
  Guardrail `tests/test_edge_peaks.py` 3 items

### Added: recipe "stepwise projection" fix (M10/M10b, major fix) + structure-factor vectorization

**Background**: the v1.5 project document §1.4 attributed "IUCr single-phase pure corundum
28.58% vs GSAS-II 15.8%" to "peak-shape model shortcomings + too loose an LM convergence
criterion". **That attribution was wrong**; the real cause is stepwise projection at the
recipe layer.

- **Root-cause chain** (three layers stacking): the `zero` step refines at the default peak
  width → zero drifts to −0.1932 (true value −0.064); the `bg` step pulls zero and peak
  width together, stopping at −0.1601; the `cell` / `profile` steps **freeze zero** → the
  0.096° zero offset is absorbed separately by the unit cell (a/c low by 0.12%/0.18%) and
  `asym` (hitting the −0.05 lower bound) → Rwp stuck at **28.58%**
- **Decisive control**: joint refinement at the `solve()` level of `cell+U/V/W+η+asym+zero`
  converges to 14.633 / 14.637 / 14.635% from three starting points → **independent of the
  starting point**, so it is not an optimizer defect
- **Fix** (`core/refine/recipe.py`):
  - `profile` step: `refine_zero=True` (**decisive**), `refine_cell=True`,
    `refine_eta/asym=True`
  - `micro`/`B` steps: "revert if not improved" becomes **unconditional** (it previously
    applied only when opening a new degree of freedom, so 28.58% worsened by the B step to
    37.42% was still kept)
  - after the `profile` step, write `PhaseInfo.cell` back into `runner.phases`, otherwise
    the `(fa, fc)` refined inside `solve` is lost in the next step
- **Result**: single-phase pure corundum **28.582% → 14.632%** (−13.95 pt, overtaking
  GSAS-II's 15.8%); IUCr Sample 1 eight base/combo groups **8/8 all improved**, among them
  1b (corundum 94 wt%) base 29.99 → **13.95**, combo 29.24 → **13.44**
- **`width_probe` measured as no gain**: with zero released, on/off converge bit-identically,
  so the recipe no longer enables it by default (the field is kept for single-point
  experiments)
- **7-sample MAUD re-check** (`combo_tex_aniso`, same convention as §1.1): mean
  **12.56 → 11.43%**, gap to MAUD (11.20) **+1.36 → +0.23 pt**; sample 3 overtakes by 2.17
  pt, sample 6 by 2.64 pt, sample 7 from +5.89 to +3.39; only sample 4 slightly worse
  (+0.23 → +0.30, the xyz 40-parameter gain is not additive, K28)
  **no new physical model was introduced at any point**; strongly correlated parameters are
  simply no longer locked step by step
- **Performance cliff**: the triple Python loop in `compute_peaks` took 443 ms per call, 86%
  of the residual evaluation (H=19 → 59319 iterations, only about 2100 inside the window).
  Full vectorization gives **26–37×** (corundum 428 ms → 16 ms), end-to-end `solve` 9.2×,
  recipe `profile` step 287 s → 32 s. Numerically **bit-equivalent** (peak positions Δ=0,
  intensity relative difference ≤4e-16, PO `detail` entries all identical), guardrail
  `tests/test_peaks_vectorized.py` | large cells exceeding 4M reciprocal points
  automatically fall back to the loop version

### Added: xyz step underdetermined "per-phase downgrade" (M9, major fix)

- **Finding**: inspecting the step-by-step records of `combo_tex_aniso.json`, **4 of the 7
  samples had a `failed` xyz step, refining not a single atomic coordinate** — samples
  4(45), 5(87), 6(63), 7(48) all had total free coordinates above `xyz_max_params=40`. The
  two samples with the largest gaps (5:+2.33, 7:+5.89) are exactly among them
- **Root cause**: the v1.4 guardrail summed `n_free` over **all phases** and compared with
  the budget, failing the whole step when over. But in most cases **the single largest phase
  fits the budget**: sample 7 kaolinite 39 ≤ 40, sample 4 is 34 ≤ 40
- **Incremental verification** (`tools/eval_sample7_xyz.py`, baseline 26.709): refining the
  other 4 phases while excluding kaolinite is worth only −0.27 pt, whereas **refining
  kaolinite alone is worth −1.87 pt (24.835)**. → "prefer phases with fewer free
  coordinates" is the wrong strategy; the value lies precisely in the large phase squeezed
  out by the sum
- **Implementation**: `RefineConfig.xyz_phase_select` defaults to `"largest"` (greedy
  retention in descending `n_free`, other phases turned into `fixed_structures` constant
  bases, natively supported by the site engine), plus `"small"` (diagnostic control) and
  `"off"` (keeping the v1.4 whole-step `failed`). **Takes effect only when
  `n_free > xyz_max_params`; paths under the limit are bit-identical** (the test asserts
  that `params` and Rwp are bit-equal for `off`/`largest`, golden does not drift). This is
  not "adding degrees of freedom" but fixing a whole-step failure, hence on by default;
  skipped phases are written into `xyz_report["dropped_phases"]` and the recipe message,
  and the revert guardrail stays as before
- Wiring: CLI `--xyz-phase-select {off,largest,small}`; GUI micro gear "xyz underdetermined
  strategy" dropdown. `tests/test_xyz_phase_select.py` 8 items (default strategy, off keeps
  old behavior, largest/small select opposite phases, still fails when no phase fits,
  bit-level zero regression under the limit, skipped phases recorded, end-to-end recovery
  of synthetic truth)
- **K27: MAUD Delft size/strain parameters are not portable**. `7#.par` cristobalite
  D=27.168 Å / ε=0.01636 converts to X=3.7502°, Y=2.9241°, within reach of the bounds but
  the recipe starting point differs by 58×. `tools/eval_sample7_broad.py` scanned under the
  same M4/M5 convention (β baseline 18.059, α 15.592): **all broad-hump combinations are
  worse than their respective baselines** (MAUD parameters 19.008 for β / 18.567 for α);
  the only group that "drops 1.24 pt" (D=200/ε=0) has ΔB_iso hitting 6 Å² outright, not
  adopted under the acceptance criteria, and the MAUD parameters push cristobalite wt% down
  to 0.0 (deleting the phase in disguise) → **broad-hump route closed**
- Diagnostic tools: `tools/eval_sample7_broad.py` (`d`/`strain`/`alpha`/`m45`),
  `tools/eval_sample7_xyz.py` (`--list` / grouping, `s7_xyz.json`). Both are read-only and
  do not modify product code
- **4-sample end-to-end re-check** (`--model ewimv`, same recipe chain as `combo_tex_aniso`):
  sample 5 17.204 → **16.026 (−1.18)**, sample 6 12.603 → **12.207 (−0.40)**, sample 7
  17.193 → **16.930 (−0.26)**; **sample 4 excluded**: after downgrading to 40 parameters
  (34-parameter muscovite + small phases) it ran 77 min with no result (CPU kept advancing,
  not a dead loop) and was terminated — that sample was only 0.23 pt from MAUD, the lowest
  marginal value among the 4 failed samples. Samples 1/2/3 have `n_free ≤ 40` and are
  bit-level zero regression. `ΔB_iso` in all three samples did not hit bounds. Mean
  excluding sample 4 **12.29%** (was 12.56, gap +1.36 → +1.09); best combination stacked
  with M8's α cristobalite **12.07%** (gap +0.87)
- **Gains not additive + performance cost (M9 pending guardrail)**: sample 7's xyz step by
  itself drops 1.51 pt but only 0.26 pt remains at the end (the micro step absorbed the
  starting-point difference); total time ~17 → 34 min (doubled). **Sample 4's 40-parameter
  downgrade path ran > 77 min with no result**, showing the downgrade cannot be enabled
  indiscriminately; the next step needs a per-sample criterion (independent reflection
  count / parameter count of the retained phases, or a lower `max_iter` for the downgrade
  specifically); until then such samples can use `--xyz-phase-select off` to fall back to
  v1.4. Sample 7's `ΔB_iso` hitting 6.0 is an inherent cristobalite model problem (the old
  combo already had 5.9993), not introduced by M9

### Added: micro step automatically enables Popa LB anisotropy (M4)

- Root cause: `refine_aniso=True` took effect only when coefficients were **written per
  phase** in `prm.aniso`; otherwise it only emitted a warning that "no phase has coefficients
  configured" — **turning the switch on was the same as leaving it off**. The benchmark
  script `_full_recipe` reached 12.596% / 17.193% only by manually filling in
  `aniso_default()`; the GUI/CLI had no such path at all
- Add `RefineConfig.aniso_auto`: `solve._resolve_aniso` fills in an isotropic starting point
  `aniso_default(λ, prm.X, max(prm.Y, 0.05°))` for every phase lacking coefficients, and sets
  `refine_aniso` effective; the return signature changes to `(cfg, prm)`
- **Softened guardrail**: if a phase filled in automatically has fewer than
  `ANISO_MIN_DIRS=8` independent crystallographic directions in the window → skip that phase
  with a warning (do not fail the whole run; automatic mode should not make refinement
  fail); phases **explicitly configured** still raise the hard guardrail error
- Recipe semantics tightened: when anisotropy is on, the micro step **no longer refines the
  scalar X/Y** — `ProfileParams` states explicitly that "once enabled for a phase, the
  scalar X/Y are completely replaced by the per-peak-direction values"; putting both in
  would create two unidentifiable dead dimensions (LM only adds two noise directions)
- Wiring: CLI `--aniso-auto`; GUI microstructure gear checkbox "micro step automatically
  enables Popa LB anisotropic broadening" (factory default on; if anisotropy was checked
  per phase in the phase editor, the user configuration prevails)

### Added: micro step "revert if not improved" guardrail

- After stacking anisotropy (6 dimensions per phase) / texture (19 dimensions per phase) the
  degrees of freedom jump sharply, and under a short iteration budget LM may converge to a
  point worse than the input. Added to both the generic path and `_run_micro`: if Rwp does
  not decrease, revert to the previous step's parameters and state "microstructure degrees
  of freedom did not improve Rwp, reverted" in `StepRecord.message`
- Trigger condition `_extra_micro_freedom(cfg)` (any of `refine_aniso` / `aniso_auto` /
  `refine_texture` true); the default path does not enter this branch

### Added: spherical-harmonic (Legendre) texture ODF (M3)

- **Why**: v1.3's EWIMV is a 19-point discrete grid, far beyond the identifiable information
  content of a single pattern. The saved results for the 7 samples show a typical
  over-fitting shape — adjacent χ bins jump between 0.1 (lower bound) and 6.9 (e.g. sample 1
  calcite `[1.03, 1.25, 1.52, 1.16, 0.1, 0.1, 0.38, …]`), and the χ=90° endpoint is
  identically the initial value 1.0 because no reflection falls there (completely
  unconstrained)
- **Model**: for a Bragg–Brentano flat plate with sample spinning, the scattering vector
  always lies along the sample normal, so the ODF depends only on the polar angle χ; summing
  over m in the spherical-harmonic expansion leaves only even orders, and folding the
  (χ, 180°−χ) equivalence further reduces it to
  `T(χ) = 1 + Σ_{l∈{2,4,6,8,10}} c_l·P_l(cos χ)`. This is the **exact subspace** of MAUD's
  `Harmonic` (`_rita_harmonic_expansion_degree` 6/8/10) under this instrument geometry, not
  an approximate substitute
- **Four structural advantages**: ① the Legendre basis is orthogonal, with good
  conditioning; ② low-order truncation is naturally smooth, so a second-difference penalty
  and end anchoring are **not needed**; ③ `∫P_l dΩ = 0 (l ≥ 2)` makes the spherical mean of
  T identically 1, so the null space "T times a constant ↔ that phase's scale divided by the
  constant" disappears structurally (EWIMV needs the hard anchor `TEXTURE_ANCHOR_W=100`; a
  test already asserts this property); ④ 2–4 dimensions per phase instead of 19
- **Interface**: `ProfileParams.texture[phase]` gains `model`/`degree`/`coeffs`; the old
  `axis`+`grid` configuration is **bit-compatible** (dispatch in `forward.texture_model`)
- **Wiring**: registry slots `phase[phase].texture.c2/c4/c6/c8/c10` (readable key names);
  `_pack`/`_unpack`/`_bounds` kept in sync in all three places (guarded by the registry
  bit-consistency test); spherical harmonics are **explicitly skipped** in regularization
  (otherwise the 19-dimensional grid penalty applied to 2-dimensional coefficients would
  blow up immediately)
- **Guardrail**: spherical harmonics require the number of independent χ bins in the window
  to be ≥ number of coefficients + 1, otherwise `ValueError` (under an orthogonal basis this
  is the strict identifiability condition; EWIMV keeps ≥ 3)
- CLI `--texture-model {ewimv,harmonic}` + `--texture-degree N`; the GUI microstructure gear
  gains a "texture model" dropdown (EWIMV / order 4/6/8/10, factory default order 10)
- **Order cap aligned with MAUD = 10**: measurement shows MAUD uses
  `_rita_harmonic_expansion_degree 10` (5 coefficients) for sample 3 fluorite and sample 1
  dolomite. The first version set the cap to 8 and the coefficient bounds to ±0.8; sample
  3's c2/c4 both hit the bounds and still lagged by 6 pt; after switching to order 10 + ±1.5,
  sample 3 went from 16.349 → **10.563** (EWIMV 19 params 10.385, MAUD 10.29). `legendre_even`
  uses closed-form P2…P10 polynomials (same values within 1e-14, 2× faster than `legval`)
- Tests `tests/test_texture_harmonic.py` 15 items: order validation, spherical mean
  identically 1, bit-identical with zero coefficients, bit-identical EWIMV dispatch,
  registry/`_pack`/`_bounds` three-way consistency, end-to-end recovery of synthetic
  texture, underdetermined guardrail
- First same-convention measurement (sample 2, 5–120°): EWIMV 7.723629917906768 vs harmonic
  order 10 **7.723629917905643, bit-identical** (no phase in that sample's `po.json` reaches
  the threshold, texture is empty). ⚠️ We once took 7.389 under a mis-set 5–90° convention
  as a model gain, but it was actually caused by the **narrower window**; corrected in
  project plan §1.2
- **7-sample measurement wrap-up**: order 10 reaches 10.563 on sample 3 (vs EWIMV 10.385 /
  MAUD 10.29), sample 7 reaches **17.487** (order 4 is 20.854, −3.37 pt; EWIMV 17.193),
  sample 1 13.329, sample 2 bit-identical, sample 6 order 4 is 12.744; sample 4 not run
  (about 2900 s for a single sample). Conclusion: **the order matters more than the model
  family**; spherical harmonics with 5 parameters can approach 19-parameter EWIMV
- **Per-phase selection validation (negative conclusion, productization withdrawn)**:
  `eval_texture_m3.py --tex-extra` adds texture by phase index. Sample 5, adding the
  fluorapatite for which MAUD enables Harmonic order 6, goes 17.204 → **17.150** (only
  −0.054 pt); sample 1, adding the third carbonate phase to enable all three, goes 13.329 →
  **13.401 (+0.072, actually worse, 23 min spent)**, and `ΔB_iso` is still 5.16 Å², the
  `xyz` maximum displacement still 0.0500. → MAUD's per-phase texture switches are local
  compensation within its own parameterization, **not portable truth**; "automatic per-phase
  texture selection" is not worth doing if it only copies the switches, and the remaining
  gap shifts to structural model/occupancy, sample 7 cristobalite, global peak shape

### Added: IUCr CPD quantitative round-robin external validation (`tools/eval_iucr_qpa.py`)

**Motivation**: the conclusions of M3/M4/M8/M9 all come from the 7 ShiJiKong samples; the
same data served both for tuning and for acceptance, so they cannot self-certify. The IUCr
CPD quantitative round-robin has **weighed true values + XRF cross-checks**, so the QPA
absolute error can be measured directly.

### Added: `.gss` reading probe and independent GSAS-II refinement cross-validation (`tools/gss_probe.py`, `tools/gsas2_xcheck.py`)

**Correction**: the earlier conclusion that "`.gss` is an old GSAS project that GSAS-II
cannot read" was **wrong** (verified after the user's correction) — `.gss` is the GSAS
standard ASCII powder data format, and the `imports/G2pwd_fxye.py` extensionlist of GSAS-II
explicitly includes `.gss`.

* `tools/gss_probe.py` (run with the local GSAS-II 5.8.2 interpreter):
  - all 28 `.gss` files were parsed and compared point by point with `txt/CPD-*.txt`,
    **28/28 consistent** (23 bit-identical; the 5 files zircon/mannitol/nizatidi/pharm1gr/
    pharm2gr differ by ≤1 count, over 33–40% of points, unrelated to intensity → a
    rounding-convention difference between the two export paths).
  - **Found and worked around an off-by-one in GSAS-II**: in `GetSTDdata`, `j += 1`
    increments before the `if j < Nch` bound check, so the **last data point of a STD-format
    bank is always dropped** (only 7250 of 7251 points read); the tool restores the last
    point from the file's final line and flags it.
  - `BANK … CONST 500.00 2.00` self-certifies a 5.00° start / 0.02° step; `n ≡ 1` confirms
    that the GSAS weight convention `σ² = y/n = y` has the same origin as our
    `weight_mode="sqrt"`.
* `tools/gsas2_xcheck.py` (fully scripted Rietveld via `GSASIIscriptable`):
  - cpd-1g (3 phases, 5–120°, `wRmin=8.65%`): staged conventional refinement **38.9%**, best
    with all-phase spherical harmonics SH-8 **31.5%**, still far worse than our **12.03%**.
    Per-peak checks show GSAS-II is stuck in a local minimum (CaF₂ (220) 38% low, unbounded
    SH coefficients making CaF₂ (311) negative in intensity); our per-peak deviation without
    any texture model is only 7–9%.
  - **Reverse finding**: for the single-phase pure corundum standard, GSAS-II **15.8%** vs
    our **30.6–31.5%**. Five different W/eta initial values converge to the same minimum
    (FWHM 0.195° at low angle, ~0.85° at high angle) → **model-level peak-shape mismatch**
    (high-angle width divergence, LM considers itself converged at an over-broad minimum),
    not an initial-value problem. Registered as the next main target for M5/M7 (details in
    the last subsection of project document §1.4).

- Data: `D:\Project\XRD\XRData\IUCr\`. `Must do/Rietveld/1a|1b|1c|1g.txt` and
  `txt/CPD-1X_raw.txt` are **byte-identical by md5**; `txt/` additionally has 1d/1e/1f/1h,
  so Sample 1 expands to **8 composition points = 24 wt% values** (5–150°, 0.02°, 7251
  points, Cu Kα1 1.54056, CaF₂(111) at 28.28° matching measurement)
- Convention: `tent` 18 nodes + `weight_mode="sqrt"`; `base` = zero/bg/scale/cell/profile/B,
  `combo` = additionally `po_probe + xyz + biso + aniso_auto + eta`
- **Engine self-consistency (synthetic round-trip)**: synthesize the 1g composition from the
  same three CIFs and recover it — noise-free Δ=0.00, ZnO **−0.03** at Poisson Imax7000,
  +0.03 at high counts → QPA normalization and `ZMV` are defect-free (corundum
  6/253.514/101.961, ZnO 2/47.598/81.379, fluorite 4/163.059/78.074 checked one by one)
- **Micro-absorption falsified**: fluorite μ=301.7 cm⁻¹ is **higher** than ZnO 276.4 and
  corundum 126.4, the opposite direction to measurement (CaF₂ is actually high); at r=5 μm
  the Brindley factors of the three phases differ by only 3–4%, not enough in magnitude →
  micro-absorption correction **should not** be added for this dataset
- **No multiplicity/symmetry errors**: against the PDF reference intensities bundled in the
  CIFs, the corundum ratio is 0.97–1.02; ZnO/fluorite rise monotonically to 1.05–1.16 as d
  decreases, caused by the CIF's bundled B_iso≈0.5 — being **monotonic rather than jumping**
  rules out extinction-rule-level errors
- **ZnO intensity is drawn away by overlapping phases (not multiplicatively suppressed)**:
  ZnO's relative deviation is −16 ~ −22% at contents 1.36/4.04/15.25/32.89/34.21/55.22%, but
  **only −2.4% at 93.59%** (1c) → the initial judgment of "uniformly 23% multiplicatively
  weak" was overturned by 1c. Refitting as `Δ ≈ −c·w·(100−w)` gives c = 0.0016~0.0038
  (≈0.0025) over seven points, i.e. **proportional intensity transfer**: the more
  neighbouring phases, the stronger and the more they take, and when ZnO fills everything
  there is nobody to take from
- **Preferred orientation cleanly falsified**: manual scan of (001)/(100) × r=1.00–0.80,
  10 groups in total (`tools/eval_iucr_po_scan.py`), **none better than r=1.00**, and every
  r<1 pushes ZnO further down (−5.91 → −6.65) → `po_probe`'s "below threshold" is correct
- **Convention correction (and an incidental API trap)**: the `profile` step of
  `RecipeRunner` hard-codes `refine_asym=True`, so **`RefineConfig.refine_asym` is an
  ineffective switch on the recipe path** (measured on/off Rwp identical to 1e-11). The
  upside is that it proves our tanθ asymmetry **has always been on**, already aligned with
  MAUD's `_riet_asymmetry_tan_dep` convention; an in-place note has been added in
  `recipe.py` so successors do not use it as a switch
- **Community benchmark**: the round-robin 1h participant mean is corundum 37.23(+2.11),
  ZnO 28.83(−1.36), fluorite 33.94(−0.75), with participant std 2.4–2.7 → the correct
  yardstick is **2.5 pt rather than zero**; our 1a(0.78)/1b(0.22)/1c(1.55) beat the
  community level
- **Rwp and QPA decoupled**: 1b has Rwp 29.99% while max\|Δ\| is only **0.22 pt** (the main
  phase's peak shape determines Rwp, the minor phases determine quantification) → the
  acceptance criteria gain "do not use Rwp as a proxy for QPA"
- **Sample 2/4 structure completion**: COD 1000054 (brucite), 1011032 (magnetite), 5000119
  (zircon), downloaded by number and cached by `tools/eval_iucr_qpa.py`; `curl` exits with
  code 56 against the local crystallography.net, so `urllib` + backoff retry was used
  instead
- **New regression test** `tests/test_qpa_roundtrip.py` (4 items): synthesize → refine must
  recover the known wt% (≤0.25 pt noise-free, ≤0.5 pt with noise). This test was previously
  missing, which is why "ZnO systematically low" could not be quickly ruled out as an engine
  problem
- Regression: full `pytest` **405 items all green** (no F/E, only spglib
  DeprecationWarning); golden 3.409617 bit-identical

### Added: MAUD per-phase model inventory (`tools/dump_maud_model.py`)

- Tabulates the **per-phase** switches of the 7 samples' `.par` files (texture
  model/expansion order, Popa LB vs Delft Isotropic, crystallite size, microstrain,
  antiphase domains), written to `maud_model.json`
- Three corrections: ① MAUD's texture and size/strain are **selected per phase** (sample 1
  enables Harmonic only for Mg/Cal/Dol, with quartz and cristobalite using Delft 2 params),
  not one global set; ② **sample 1's cristobalite is already the α phase P4₁2₁2** (consistent
  with MAUD), so M8's "β→α" conclusion applies only to sample 7; ③ when reading MAUD
  results one must verify that the same-named `.par.lst` is **non-empty** — sample 6's
  `6#.par` is an unconverged intermediate state (`.lst` empty, 3 phases, 15.89%), and the
  converged `6b#.par` (14.76%, 4 phases) is the real baseline

### Added: MAUD benchmarking diagnostics and reproduction tools (`tools/`)

- `diag_residual.py`: interval-wise Rwp contribution + residual mean + strongest-reflection
  attribution per phase, results cached in `diag_<sample>_<tag>.pkl` for closer inspection
- `eval_uvw.py`: same model with only the Caglioti U/V/W swapped (our refined values vs
  MAUD's fixed values), used to decide "whether the peak-width model is the source of the
  gap"
- `report_v15.py`: three-stage table of base / +EWIMV / +Popa LB against MAUD;
  **the mean is computed per stage with the covered n/7 noted**, never mixing samples with
  different coverage
- `eval_cristobalite.py` gains a `models_m4m5` stage: redo the cristobalite polymorph
  comparison under the M4/M5 convention, and record whether that phase's `ΔB_iso` still
  hits the 6 Å² upper bound
- `eval_texture_m3.py`: **the same recipe chain** as `bench_v14`'s `combo_tex_aniso`, only
  the texture model changed (ewimv / harmonic:4/6/8), per-sample resumption from
  checkpoints, table output via `--report`

### Benchmark results (same dataset `D:\Project\XRDdata\ShiJK-Refinement`, MAUD 2.99993 same batch)

| Sample | MAUD 2 | v1.3 base | +EWIMV | **+Popa LB (M4/M5)** | Gap |
|---|---|---|---|---|---|
| 1 | 10.90 | 23.880 | 16.085 | **12.596** | +1.70 |
| 2 | 6.34 | 7.764 | 7.845 | **7.724** | +1.38 |
| 3 | 10.29 | 24.525 | 11.285 | **10.385** | +0.10 |
| 4 | 9.96 | 14.888 | 11.746 | **10.186** | +0.23 |
| 5 | 14.87 | 17.721 | 17.702 | **17.204** | +2.33 |
| 6 | 14.76 | 16.381 | 15.020 | **12.603** | **−2.16 (overtakes MAUD)** |
| 7 | 11.30 | 26.748 | 21.001 | **17.193** | +5.89 |
| **Mean** | **11.20** | 18.84 | 14.38 | **12.56** | +1.36 |

(Generated by `tools/report_v15.py`, all 7 samples under the same convention:
`weight_mode=sqrt` + Rwp with background + window per actual data. **Means are not mixed**:
each stage notes the number of samples covered.)

### Diagnostic conclusion: sample 7's gap is neither peak width nor background, but the cristobalite polymorph

- Residual distribution (`tools/diag_residual.py`): **25–30° accounts for 20.3% of the
  weighted SS** (calculation low), **20–25° for 20.0%**; 85–90° calculation high. The
  **apex of the 21.86° cristobalite main peak is calculated at only 53% of the observed
  value**, while the peak flanks basically match
- **The peak-width hypothesis is falsified**: replacing Caglioti U/V/W with MAUD's refined
  values on the same data (0.00253/0.00272/0.00231, 5× narrower than ours) makes Rwp
  **17.27 → 17.64 (worse)**. Our broad peak width is what the data demand, not a defect
  (`tools/eval_uvw.py`)
- **Polymorph replacement is effective** (incremental convention, M4/M5 configuration):
  β high-temperature Fd-3m **18.06** → α low-temperature P4₁2₁2 **15.59 (−2.47 pt)**;
  removing the phase entirely instead raises it to 19.04 (the phase must stay). See
  `tools/eval_cristobalite.py models_m4m5`
- **End-to-end verification**: replacing sample 7's cristobalite CIF with the α phase gives
  a complete recipe of **17.193 → 15.357 (−1.84 pt)**, and that phase's `ΔB_iso` **no longer
  hits the 6 Å² upper bound** (the collision disappearing = the over-fitting signal
  disappearing, which is the healthy signal). See `tools/eval_sample7_alpha.py`
- Product-side action: the `ΔB_iso` bound-collision warning gains the hint "it may also be
  that this phase's structural model does not match the sample (polymorph/occupancy/
  disorder)", together with this measured evidence

### Regression

- Full **471 items: 467 passed / 4 skipped, EXIT=0** (`--basetemp` clean directory); all 4
  skips are XinMatch-related (the real cause is the missing `gemmi`; the skip reasons now
  surface the real exception instead of the misleading hard-coded "not on the import path")
- golden CLI Rwp 50/50 level **3.4074156640940005** (the intentional value since M11; the
  baseline has been rebuilt and `tests/test_golden_b.py` added as a live tripwire)
- Re-running sample 3 on the new code path: **10.3854917764 vs 10.3854917760** (the
  last-digit difference comes from the floating-point accumulation order after removing two
  dead dimensions), and the runtime goes 317 s → 238 s

## v1.4.0 (2026-11-06, pushed)

Theme: **Cross-check wrap-up — connecting capabilities already landed in v1.3 but absent from the production recipe to real-sample validation**.
Seven-sample re-measurement under one protocol ([`docs/评估报告-实样对拍-MAUD-v1.md`](docs/评估报告-实样对拍-MAUD-v1.md)
§11.5) confirms zero regression in the v1.3 engine; then, following "model completion → full re-measurement", three recipe capabilities are completed,
and a data-driven disposition conclusion is given for the disordered cristobalite model.

### Design decisions (stated up front to avoid misuse)

- **All new capabilities are off by default in the CLI / library API** (`po_probe` / `refine_biso` /
  `refine_xyz` are all `False`), guaranteeing bit-for-bit zero regression against golden and existing callers;
  **the GUI ships only `po_probe` enabled by default**, on the basis of the three gap samples in the 7-sample cross-check
  at −4.82 / −12.60 / −4.45 pt respectively. `refine_biso` / `refine_xyz` remain off by default in the GUI
  and must be checked explicitly in the micro gear — their gains on real samples are unstable, so they are not silently enabled
- **A recipe step being "available" ≠ "executed by default"**: `available` for the `xyz` / `B` steps
  changes from `False` to `True`, but without explicit enablement `run_step` still records
  `skipped` and does not fake execution

### New: automatic preferred-orientation probing in the micro step (task #19)

- Root cause: in the real-sample cross-check, preferred orientation of CaF₂(111) in sample 3 is off by −12.06 pt,
  yet the engine refines `r` only when (h,k,l) is **pre-filled** in `prm.po_r`;
  the factory recipe carries no such information, so the micro step idled
- `RecipeRunner._run_micro`: per-phase × low-index candidate axes
  `DEFAULT_PO_AXES = ((001),(100),(110),(111),(101))` short refinement of `r`
  (only 1 nonlinear degree of freedom per candidate), selected by Rwp gain ≥ `po_probe_min_gain`
  (default 0.3 pt), at most `po_probe_max_phases` (default 2) phases included,
  then `r=1` is written back to `po_r` and handed to the formal micro step together with X/Y refinement
- **Mutual-exclusion guard**: no probing when the user has already configured `po_r`, when EWIMV texture is on,
  or for phases covered by the `DEFAULT_PO_HKL` built-in habit-plane table. In practice, letting the probe
  override the built-in habit planes replaces the more accurate default axis with a noise axis (synthetic control 5.4235 → 5.4265)
- Details are recorded in `runner.po_probe_report` and written to `StepRecord.message`;
  with `po_probe=False`, `run_step` never enters that branch
- **Window strategy**: the micro gear gains `tmin/tmax`;
  `_make_inputs` adapts the number of background nodes to the window; measured on 5–120° vs 5–90°,
  samples 1/3/7 drop a further 0.834 / 0.812 / 0.940 pt
- CLI: `--po-probe` / `--po-probe-min-gain` / `--po-probe-max-phases` /
  `--po-probe-max-iter`

### New: per-phase ΔB_iso (task #18)

- `B_iso` in COD-exported CIFs is always 0; measured on sample 1, calculated intensity at 40–120° is
  systematically too high (§4.6). `ProfileParams.b_iso = {phase name: ΔB}` shares the global
  `bfactor` form `exp(−B/(2d²))`, superimposed per phase, suppressing only high angles without shifting peak positions
- Landing points: `forward._accumulate_peaks` / `nonlinear._pack/_unpack/_bounds`
  and the `phase[…].B_iso` slot in `ParameterRegistry` (bit-for-bit cross-check passed) /
  `solve._resolve_biso` (missing phases filled with 0; warning when `tmax<60°` and the global `bfactor` are both on) /
  recipe `B` step / CLI `--refine-biso` / GUI micro gear
- Upper bound 6 Å²; injected ΔB=1.5 in synthetic data is recovered within ±10%
- **Bound-hit guard** (from the real-sample baseline): 4 of 7 samples push some phase to 6 Å², and the phases
  hitting the bound overlap highly with those gaining from PO/texture (e.g. CaF₂ in samples 3/7) — indicating that B is absorbing
  **model error in preferred orientation / texture / scale**, not a physical temperature factor. `solve()` appends
  a "confirm PO and texture before enabling the B step" warning when any phase hits the bound; the B step therefore
  remains opt-in, with no factory default

### New: atomic-coordinate xyz step wired into the recipe (task #17)

- `CifStructure.source_path`: `parse_cif` writes the CIF path; the xyz step must
  **re-read the unexpanded asymmetric unit + symops** (`parse_cif` already expands equivalent positions,
  so Wyckoff sites cannot be recovered). `parse_cif_string` / manually built structures are `None` and are skipped automatically
- The metadata whitelist of `cell.structure_with_cell` gains `source_path`,
  ensuring the xyz step still finds the CIF after the cell step refines the unit cell
- `site.refine_sites` gains `fixed_structures` (phases not taking part in structural refinement enter the variable projection
  as constant basis, preventing their intensity from being absorbed into the scale of refined phases) and `bg_points` pass-through
  (the fixed layer of manual/interpolated background must match, otherwise coordinates absorb the background difference)
- `RecipeRunner._run_xyz`: the unit cell refined by the cell step overrides `SiteModel.cell`;
  if the number of free coordinate parameters > `xyz_max_params` (default 40), the step is judged `failed`;
  after refinement `solve` is re-run to compare Rwp, and **the original structure is rolled back entirely if there is no improvement**;
  diagnostics are written to `runner.xyz_report`
- **Metadata inheritance**: when the site engine rebuilds the structure from the asymmetric unit, it only restores
  `formula/spacegroup`; the recipe layer inherits `z_declared / n_asym / n_sym_ops / source_path`
  item by item, otherwise QPA degrades silently and the next xyz step cannot find the CIF
- **Performance guard `XYZ_SITE_MAX_ITER=12`**: the site LM uses a numerical Jacobian, and each iteration
  requires O(n_free) evaluations of "multi-phase full pattern + linear layer"; a real 5-phase system using the recipe's
  `max_iter=40` would run for a dozen minutes without converging. The xyz step is capped separately at 12 iterations
  (coordinate refinement usually plateaus within 8–12), and the iteration budget of the main `solve` is unchanged
- **Real-sample re-measurement (3 gap samples)**: sample 1 accepts 14 free parameters,
  Rwp 23.880 → **21.628% (−2.251 pt)**, maximum displacement 0.0266, matching the calcite O-coordinate gap
  named in §4.6; sample 3 improves only −0.118 pt (its gap is CaF₂(111) texture, not coordinates); sample 7 has 48 free parameters and triggers
  `xyz_max_params=40`, is judged failed and rolled back entirely, with Rwp/QPA unchanged bit for bit
- CLI `--refine-xyz` / `--xyz-max-params`; GUI micro gear switch

### Fixes

- `core/absorption.py`: the chemical formula of the gehlenite CIF in sample 5 is inconsistent with occupancy,
  and `infer_z` raises, making μ·r uncomputable. Added `_density_from_cell_mass` fallback
  (compute ρ directly from unit-cell occupancy mass), with output `density_source="cell_mass"` and
  a "please check the structural model" warning; all phases of the 7 samples are now computable
- `tools/bench_v14.py::stage_base` referenced an undefined `runner` (triggered only when re-running the base
  stage); changed to construct `RecipeRunner` explicitly
- One outdated assertion in `tests/test_biso.py` still expected `available=False` for the `xyz` step;
  synced to the v1.4 behaviour; the `recipe.py` module docstring is updated from the v1.1
  "xyz/B not landed" to the v1.4 opt-in semantics
- `README-en.md` had long been stuck at v1.1.0; the current version is added along with an explicit note that
  "feature descriptions remain at the v1.1.0 baseline, see the Chinese CHANGELOG for new features", no longer pretending to be in sync

### Tests

- Added `tests/test_po_probe.py` (4 items), `tests/test_biso.py` (6 items),
  `tests/test_xyz_recipe.py` (6 items): defaults off, true-axis recovery,
  mutual-exclusion/threshold guards, registry bit-for-bit cross-check, synthetic ΔB recovery and bound-hit warning, xyz step
  skipped / underdetermined / iteration cap / metadata inheritance / no-degradation promise
- `tests/test_absorption.py` adds a density-fallback case (restoring the fixture with `try/finally`)
- `tests/test_gui_smoke.py` / `tests/test_recipe.py` synced to
  "7 done / 1 skipped" and the `len(DEFAULT_STEPS)-1` snapshot semantics
- **Full regression**: 368 collected / 364 passed / 4 skipped / 0 failed
  (v1.3.0 collected 350, a net increase of 18)

### Real-sample re-measurement conclusion (7 samples, see evaluation report §11.5)

- **v1.3 zero regression**: base matches the v1.2 tent14 baseline bit for bit, mean 18.8439%
- **Automatic PO probing**: end-to-end −4.816 / −12.604 / −4.451 pt on samples 1/3/7;
  sample 3 automatically selects CaF₂(111) `r≈0.448`, within ≤0.05 pt of the full-axis exhaustive upper bound;
  window 5–120° gives a further 0.81–0.94 pt
- **EWIMV / Popa LB**: texture on 1/3/7 is worth −6.004 / −13.666 / −5.206 pt
  (but with 19 free parameters, so no default); anisotropic on sample 5 −0.768 pt
- **μ·r QPA**: Rwp unchanged (mathematically degenerate), hematite wt% in sample 4 +4.60 pt at most;
  gehlenite in sample 5 triggers the `cell_mass` density fallback
- **Combined setting**: 5–120° + PO + B + xyz enabled together, sample 1 23.880 → 17.185%,
  sample 3 24.525 → 13.537%; **gains are not additive** — B first pushes CaF₂ ΔB to
  6 Å², absorbing most of the high-angle mismatch, so in the combination the micro step retains only one third of its standalone gain
- **#21 disordered cristobalite**: no disorder model is introduced. Rwp of the three polytypes 26.709/26.350/25.235,
  wt% 2.72/3.52/5.27; removing the phase +1.00 pt; ΔB_iso damping moves at most 0.11 pt
  and wt% still drifts. Downgraded to "reference phase only", wt% not reported, requiring TEM/IR or
  manual interpretation of the 21.9° single peak by Le Bail; no new engine switch, no modification of user data

### Documentation

- `docs/评估报告-实样对拍-MAUD-v1.md` §11.5: v1.4 full re-measurement record
  (zero-regression baseline / incremental-metric corrections / PO·EWIMV·μ·r / PO probing and window /
  ΔB_iso and bound hits / xyz and combined setting / disordered cristobalite / release decisions and remaining gaps)
- Reproducible scripts `tools/bench_v14.py`, `tools/eval_cristobalite.py`
  (benchmark data lands in a temporary directory, not committed to Git)

### Build fix: the installer could never build (version number drift)

- Symptom: `tools/build_binaries.py build-installer` reports "installer not generated" after PyInstaller finishes.
  `AppVersion` in `packaging/inno/xinrefinement.iss` was still `1.1.0`, so ISCC named the artifact `...-1.1.0-setup.exe`,
  while the script looked for the file by `__version__` (`1.4.0`) — a guaranteed miss, wasting the preceding
  ten-plus minutes of packaging.
- Fix: the iss keeps a single `#ifndef AppVersion` default (synced with `__version__`),
  and every other occurrence uses `{#AppVersion}`; `build_installer()` injects it via
  `ISCC /DAppVersion=<ver> /DDistDir=<dir>`, leaving a single source of truth for the version number.
- Guard added: `tests/test_version_consistency.py` (3 items) — the iss default must equal
  `__version__`, no literal version number may appear in the file outside `#define`, and the build script must pass
  `/DAppVersion=`.

## v1.3.0 (pushed)

Theme: the MAUD source-code review borrowing list **fully landed** (μ·r calculator, theoreticalWeights,
canvas-picked background, EWIMV texture, Popa LB anisotropic, pluggable optimizer) + one important design
review conclusion (μ·r refinement falsified, replaced by a calculator). Tests 350 collected / 346 passed / 4 skipped.

### Design review (important)

- **μ·r refinement falsified, downgraded to an experimental mechanism**: the Brindley factor is a constant scalar per phase,
  **completely degenerate** with the per-phase free scale of the linear layer (only the product S_p·f(μr_p) is identifiable).
  Numerical experiments confirm: μ·r is mathematically unidentifiable in single-pattern refinement; LM drifts
  to the boundary on a zero-gradient plane (true value 2.0 → bound 20.0), and **Rwp is unchanged bit for bit while wt% drifts silently** — MAUD's Brindley
  implementation is isomorphic and suffers the same degeneracy. The mechanism code in `RefineConfig.refine_microabs` is retained only for
  future experiments such as multi-pattern joint/constrained scaling; the production path (recipe/GUI/CLI) never exposes it

### New

- **μ·r calculator `core/absorption.py`** (the correct path replacing refinement): embeds an element
  mass attenuation coefficient table (`core/mu_table.py`, generated from xraylib 4.3 / NIST-Chantler evaluation,
  Z=1–94 × 6 anodes, zero runtime dependency); `calc_mu_r(CIF, grain radius)` computes element mass fractions
  from unit-cell occupancy, ρ=Z·M/(N_A·V), μ=(μ/ρ)·ρ, and outputs μ·r.
  Physical check: anatase ρ=3.890 (literature 3.89), μ/ρ=124 cm²/g (literature 124–129).
  GUI phase parameter editing adds "compute μ·r from composition" (grain radius input + calculation detail popup);
  CLI `--grain-size phase=r_μm` (takes precedence over a manual `--microabs` of the same name)
- **theoreticalWeights weighting mode** (borrowed from MAUD `theoreticalWeights`):
  `weight_mode="theoretical"`, σ=√max(ycalc,1) uses calculated values instead of observed values for weighting
  (robust against weak-peak noise drift); the `solve()` entry bootstraps it into a fixed σ array from initial parameters
  (static σ guarantees residual determinism), and the engine/e.s.d./Rwp metrics stay automatically consistent;
  GUI background popup adds a "weighting mode" dropdown; CLI `--weight-mode theoretical`
- **Canvas-picked background anchors** (borrowed from MAUD manual background points): toolbar "pick background" switch,
  left click in the main axes adds/removes anchors (±0.15° means the same point, intensity taken from measured interpolation), right click clears;
  d-axis mode converts automatically (stored as 2θ); anchors are written back to settings.bg and the mode switches to manual,
  taking effect on the next refinement via the existing `bg_points` engine path; project save/restore closes the loop; zh/en/ja

### EWIMV discrete ODF texture (task #14)

Specification in [`docs/规格-EWIMV织构-v1.md`](docs/规格-EWIMV织构-v1.md) (implemented).

- **Model**: under Bragg–Brentano flat-plate symmetric reflection geometry the scattering vector is always along the sample normal, so the texture
  factor degenerates to a **constant per reflection** `T(χ_hkl)` — χ is the angle between the plane normal and the texture axis (0–90°,
  computed with reciprocal basis vectors, correct for non-orthogonal crystal systems). 19-point grid per phase (5° step) with linear interpolation
- **Regularization**: second-difference smoothness penalty `√λ·(T[k−1]−2T[k]+T[k+1])` (λ defaults to 1.0,
  adjustable in CLI/GUI) + **end-node anchoring at 1.0** (weight 100). Anchoring is not merely a physical assertion
  (far-field returns to no texture); it also **removes the null space "T scaled by a constant ↔ that phase's scale divided by the constant"** —
  without it the level of T is unidentifiable and LM drifts along the flat plate
- **Guards**: fewer than 3 independent χ buckets within a phase (5° bucketing) raises `ValueError` directly (no result when underdetermined);
  phases with texture on ignore March–Dollase r with a warning (no two models for the same degree of freedom)
- **Landing points**: `ProfileParams.texture` / peak directions in `compute_peaks(with_dirs=)` /
  `RefineConfig.refine_texture`+`texture_lambda` / registry `texture` group
  (19 slots/phase) / GUI phase editing "texture (EWIMV)" / CLI `--texture phase=h,k,l`
- **Measured** (synthetic pattern, anatase (001) direction T=3): no-texture model 17.91% → texture on
  0.002%, T(0) recovered exactly as 3.000, end node 1.000

### Popa LB anisotropic size/strain (task #15)

- **Model**: 2nd-order spherical harmonic truncation + **Cholesky parameterization** (row-major lower-triangular `L`, 6 parameters):

  `1/D² = |L_sᵀn|²`, `ε² = |L_εᵀn|²` → `Y = (180/π)·Kλ/√(1/D²)`,
  `X = (180/π)·4ε` (same units and semantics as scalar TCH, bit-for-bit degenerate verification possible)

  Cholesky is used rather than direct quadratic-form coefficients because `|Lᵀn|` is **differentiable everywhere** with respect to the parameters,
  whereas the direct quadratic form has a divergent `sqrt` derivative at q=0, which LM numerical differences would amplify
- **Identifiability guard** (a hard requirement of this task): `aniso_mode` defaults to `"size"` (6 parameters);
  fewer than 8 independent crystal directions in the window raises an error; `"both"` (12 parameters) gives a warning that
  "size and strain will absorb each other". Measurement confirms: pure-size synthetic data + both mode → Rwp 0.14% but the
  L matrix is garbage and the ratio is 52 instead of 3.3; size only → parameters and ratio are both correct
- **Landing points**: `ProfileParams.aniso` / registry `aniso` slot (6 or 12/phase,
  separate bounds for diagonal/off-diagonal) / GUI "anisotropic size/strain (Popa LB)" / CLI `--aniso`
- **Measured** (synthetic D_a=200 Å, D_c=60 Å): isotropic 30.80% → anisotropic 0.06%,
  `size` diagonal recovered 4.999e-3 / 1.664e-2 (true values 5.000e-3 / 1.667e-2),
  Dmax/Dmin 3.346 (true value 3.333)

### Pluggable optimizers (task #16)

- Added `core/refine/optimizers.py`: `OPTIMIZERS = {lm, trf, dogbox}` +
  alias `scipy = trf`, unified entry `minimize()`; cost is always `0.5·||r||²`
  (so restart comparisons are directly comparable); unknown methods **raise and list the available options**, with no silent fallback;
  when scipy is missing, falls back automatically to the in-house LM (historical behaviour)
- `nonlinear.refine` and `cell.refine_cell_full` both go through the registry; CLI
  `--backend lm|trf|dogbox|scipy`; a new optimizer only needs one `_run_xxx` function registered
- All three methods converge to the same solution on the same well-conditioned problem (cost agrees to 1e-4 relative), with consistent
  bound projection; end-to-end trf/dogbox converge to the same basin as lm in Rwp

### Fixes

- **Restart start points dropped extension fields** (`nonlinear._restart_points`): previously `ProfileParams` was rebuilt by hand,
  silently zeroing X/Y, microabs, texture and aniso — `registry.pack` then crashed outright after a restart
  (exposed by the v1.3 anisotropic measurements). Changed to `dataclasses.replace`
  modifying only U/V/W, keeping all other fields
- **Removed the module-level circular import between `registry` and `nonlinear`**: registry now imports
  nonlinear locally when needed, so import order no longer affects importability

### Documentation

- `docs/规格-EWIMV织构-v1.md`: EWIMV discrete ODF texture specification + implementation record
  (fiber 1D ODF + smoothness penalty + six acceptance items A1–A6 with measured values)

## v1.2.0 (unreleased)

Theme: P0 defect fixes exposed by the real-sample cross-check (7 manually refined MAUD samples, see
[`docs/评估报告-实样对拍-MAUD-v1.md`](docs/评估报告-实样对拍-MAUD-v1.md))
+ factory default upgrade + the first three items borrowed from the MAUD source review
([`docs/MAUD源码复核-v1.md`](docs/MAUD源码复核-v1.md)).

### Fixes

- **Fake execution of the "unit cell parameters" recipe step** (`core/refine/recipe.py`): `config_for`
  never set `refine_cell`, the `run_cell_step` referenced in comments did not exist anywhere in the repository,
  and the step had status=done while Rwp was identical bit for bit before and after. It is now orchestrated by `RecipeRunner._run_cell`
  as "solve → `refine_cell_full` (release free components by crystal system) → solve again with the new unit cell",
  with the new unit cell written back to the phase list shared by subsequent steps. Real sample 1: that step 36.29% → 26.57%,
  recipe final value 33.74% → 25.92%
- **GUI single refinement used the old peak-height convention** (`gui/main_window.py`): `integrated=False`
  → `True` (the standard Rietveld scale S convention; CLI already used True). Real sample 1 differs by 3.65 percentage points
  under the same configuration
- **Unit-cell write-back dropped metadata** (`core/refine/cell.py`): added the public entry `structure_with_cell`,
  shared by `apply_cell_scales` and recipe write-back; failing to carry over `formula/z_declared`
  would silently turn QPA into None after unit-cell refinement
- **CLI failure branch crash** (`cli/refine.py`): `rec.note` → `rec.message`
  (`StepRecord` has no note field, so AttributeError was triggered only on a real failure)

### New

- **Weighting mode `weight_mode`** (borrowed from MAUD `getWeight`, related to P0 cross-check §4.3):
  `sqrt` (default, counting statistics, bit-for-bit identical to v1.1.x) / `file` (pattern-supplied
  σ, i.e. `_pd_meas_intensity_sigma`) / `unit` / `1/y`; residuals and Rwp share the same convention;
  `esd.py` follows the same convention; CLI `--weight-mode`
- **Brindley micro-absorption correction (per phase)** (borrowed from MAUD `MicroAbsorptionBrindley`):
  `ProfileParams.microabs = {phase name: μ·r}`, factor `(1−e^(−μr))/(μr)` multiplied into that phase's
  calculated intensity (small μr uses a Taylor expansion to avoid cancellation); off by default and unchanged bit for bit;
  the GUI phase parameter editing dialog gains a "micro-absorption correction" group; CLI `--microabs phase=μr`;
  v1.2.0 only applies it, without refinement
- **Interpolated background `bg_mode="interp"`** (borrowed from the MAUD `backgroundSubtraction`
  default 10-iteration semantics): `interp_background_nodes` extracts anchors automatically
  (2σ band hugging the background + in-segment median; synthetic-pattern recovery error of p50 <1 counts),
  extracted once and then taken through the P2.2 fixed-background branch; CLI `--bg-mode interp`
- **Manual background points actually wired up** (P2.2 disconnection fix): the manual mode of the GUI background popup
  was previously downgraded to cheb and `bg_points` never reached the engine; it now flows through `RefineConfig.bg_points`
  across solve/`refine_cell_full`/recipe full paths, and the background curve is rebuilt correctly in the results area
- **`adaptive_n_bg(tmin, tmax)`**: tent/interp node count adapts at ≈1 node/6°

### Changes (defaults)

- **GUI factory background default `tent` + adaptive node count** (previously cheb + fixed 3 terms):
  real-sample cross-check §11.2 measured a 7-sample mean of 23.06% → 18.84% (tent14);
  values explicitly set by the user in the gear popup take precedence

### Measured effect (7 real samples, factory "one-click full run" setting)

| Config | 7-sample mean Rwp |
|---|---|
| v1.1.1 factory (cheb3 + peak-height convention + fake cell execution) | 26.00% |
| v1.2.0 factory (tent14 + integrated=True + real cell execution) | 18.84% |
| v1.2.0 factory + interp14 (borrowed 1a, two layers are additive) | 19.01% |
| MAUD manual reference | 11.23% |

> interp (fixed interpolation layer + free Chebyshev layer) is essentially on par with free tent (0.17 points apart,
> with wins and losses varying by sample): the implementation has reproduced the equivalent capability of the MAUD background framework;
> the first version with "fixed curve only, no stackable polynomial layer" degraded markedly (sample 2: 19.49% vs 7.76%),
> so the two-layer structure is a necessary condition.

### Validation

- Added `tests/test_weight_mode.py` (5 items), `tests/test_microabs.py` (4 items),
  `tests/test_bg_interp.py` (5 items); `test_recipe.py`/`test_gui_smoke.py`
  gain 3 P0 regression locks; full `pytest` → **303 collected, 299 passed / 4 skipped / 0 failed**
  (v1.1.0 baseline collected 286, no regression)
- Subsequent borrowing-list items (EWIMV ODF / Popa LB / multiple optimizers / theoreticalWeights /
  canvas-picked background / μ·r refinement) are registered in the task list, scheduled for v1.3+

### Documentation

- `docs/MAUD源码复核-v1.md`: module-by-module review of the upstream source (v3.09),
  6 borrowable capabilities and 4 items not recommended for adoption

## v1.1.0 (released 2026-11-05)

Theme: connecting the "phase search (XinMatch) → full-pattern refinement (XinRefinement)" family pipeline.
The plan and format contract are in [`docs/JOINT_PLAN_xinm_xinr.md`](docs/JOINT_PLAN_xinm_xinr.md),
release notes in [`docs/RELEASE_NOTES_v1.1.0.md`](docs/RELEASE_NOTES_v1.1.0.md),
installer in [Release v1.1.0](https://github.com/PolyXRD/XinRefinement/releases/tag/v1.1.0).
Companion version: **XinMatch 3.4.0**. The refinement engine, parameter model, CLI arguments and registration mechanism are unchanged.

### New

- **Import XinMatch phase analysis (`.xinm`)**: a new entry in the File menu; loads pattern + selected phase CIFs +
  wavelength/anode metadata; phases with `structural=false` (PDF2-type entries without structure) are listed as "reference only"
  with a prompt to supply a CIF manually, and do not take part in refinement; the import core `core/io/xinm_import.py` has no Qt dependency
  and is shared by GUI/CLI/library API, including zip-bomb protection and version negotiation (version > supported value prompts an upgrade)
- **Project file upgraded to `.xinr` (self-contained zip container)**: embeds the pattern by default (canonical CSV, `%.10g`,
  round-trip relative error ≤ 1e-9) + CIFs + full refinement results (`result/refine.json`, same schema family as CLI `--out`:
  R factors/parameters/phases/convergence history/diagnostics/e.s.d.), so the refinement can still be opened after moving machines or directories;
  opening a project immediately restores the result summary and convergence curve, **reproducing the previous result without re-refining**;
  extension split — `.xinr` uses the container, `.xrp` keeps the v1.0.0 JSON path reference (**old files remain read-only compatible forever**);
  also fixes the v1.0.0 `.xrp` losing `phase_edits`
- **Unit-cell/space-group consistency check on import**: if manifest and CIF agree, `phase_edits` is pre-filled (recording the source);
  on significant mismatch (>0.1% or >0.05°) the CIF wins and a list is shown; space-group symbols are normalized with `:1`/underscores
  to avoid false positives; a phase with `structural=true` but no CIF in the package is downgraded to "reference only" with a reason that includes the file name
- **Library API**: `capabilities()` gains the `xinm_import: "1"` capability flag

### Validation

- Added `tests/test_xinm_import.py` (13 items, including cross-repository round-trip and S2/S3/S4 scenarios),
  `tests/test_project_zip.py` (7 items, including `result_full` round-trip and self-contained opening when source is missing),
  `tests/test_joint_s1.py` (3 items, full loop with real COD records 7206075 + 9001681)
- S1 numerical fidelity: after `.xinm` import through the public API → **Rwp 3.409617019598457 (bit-for-bit identical to the P0 golden value)**,
  quantification 50.03 / 49.97 wt%; under the GUI one-click full-run setting, the "import path" and "manual import of the same pattern + CIF"
  give bit-for-bit equal Rwp; after saving `.xinr` and deleting the temporary pattern and `.xinm`, reopening reproduces Rwp (rel 1e-9)
- S2 mixed sources: COD + user CIF phases packaged, PDF2 phase reference-only and **no ICDD-derived files in the package**;
  S3 boundaries: missing CIF / corrupted zip / missing pattern / version=2 all give readable prompts without crashing
- Full test suite 259 → **286 all green**; i18n adds `menu.import_xinm` in three languages

### Binaries and six-round acceptance

- The build script fixes a **false failure**: a trailing `print("⚠ …")` threw
  `UnicodeEncodeError` on a GBK console, so all artifacts were generated but the exit code was 1 (CI would misjudge). `main()` now calls
  `reconfigure(errors="replace")` first.
- Six automated rounds all pass (report `.scratch/accept110.json`): two builds of the exe from the same source are **byte-identical**
  (`a2c9fcc8…` / `7d1ed1ec…`); `--version` of both variants' CLI → `XinRefinement 1.1.0`;
  CLI end-to-end `rwp = 3.409617`; offscreen GUI self-test reports `release/unregistered` and
  `internal/internal evaluation build` for the two variants; silent install 606 files → uninstall leaves 0 residue; setting
  `XINREFINEMENT_VARIANT=internal` on the release build still reports `release` (anti-bypass).
- Release artifacts: `XinRefinement-1.1.0-setup.exe` 67,586,555 B
  (`046179e6f3ef45d6…`), `XinRefinement-internal-1.1.0-portable.zip` 113,946,723 B
  (`a9012229b268bae3…`). See `docs/RELEASE_NOTES_v1.1.0.md`.

## v1.0.0 (released 2026-11-05)

**First official release.** General-purpose powder diffraction full-pattern fitting (Rietveld structural refinement / Le Bail / pattern refinement).

### Engine

- **Refinement core**: variable projection (analytic elimination of linear scale/background) + LM / scipy-trf dual backends; all 230 space groups such as Pnma/R-3m (spglib), including H/R settings and Wyckoff null-space free coordinates
- **Parameter model**: declarative `ParameterRegistry` (pack/unpack/bounds bit-for-bit identical to the old path), full unit cell constrained by crystal system (cubic 1 → triclinic 6)
- **Structural refinement**: atomic coordinates (Wyckoff constraints), isotropic B, occupancy (including `occ_anchor` degeneracy handling)
- **Pattern refinement**: zero/sample displacement, three background modes (Chebyshev/tent/manual points), Caglioti+TCH size-strain, η, asym, Kα1/Kα2, March-Dollase multi-phase PO
- **Quantification and uncertainty**: Hill-Howard QPA, Schur-complement parameter e.s.d. (including scale/background/content), DW statistic
- **Le Bail**: structure-free intensity extraction + multi-phase quantification; **CIF write-back**: unit cell/coordinates/B/occupancy

### GUI (PySide6)

- Three-pane main window + 8-step guided refinement (single step / one-click full run / background thread / stop / rollback)
- Interactive pattern: measured/calculated/residual dual axes, background curve, per-phase peak-position bars, rubber-band zoom, per-phase toggle with immediate redraw
- **Axis switching**: horizontal axis 2θ ↔ d value (Bragg conversion d=λ/2sinθ, axis reversed automatically, tick marks
  converted in sync; wavelength defaults to Cu Kα1 from the pattern meta); vertical axis counts ↔ log ↔ √
  (FunctionScale); left click cycles the axis label, right click opens a menu, hover shows an operation hint and a pointing-hand
  cursor; when pan/zoom is active, clicks are yielded to the toolbar
- **MAUD-style phase tick bars**: a narrow tick axis per phase below the main pattern, phase names labelled on the left in phase colours,
  Bragg tick height ∝ relative intensity within the phase (|F|²·LP normalized); residual panel height narrowed (1 → 0.55)
- **Edit → Edit phase parameters**: edit unit cell a/b/c/α/β/γ per phase (written back to the structure and refreshing tick bars
  immediately), March–Dollase preferred orientation hkl+r (propagated to the forward model and refinement),
  space group/point group/Laue group (display and logging); double-clicking a phase list item jumps straight there; persisted with `.xrp`
- **Refine menu**: one-click full run (default configuration) / stop
- **Help → About**: family layout (inherits the XinMatch copyright holder PolyXRD Team, contact details
  and the Academic/Commercial dual license, root LICENSE / LICENSE-CN)
- **Brand assets**: logo / window icon / splash screen come from the project `assets/`
  (swappable live in source mode; a bundled copy lives in `xinrefinement/data/assets/` when packaged,
  three-level fallback: project root → PyInstaller `_MEIPASS` → inside the package)
- **Navigation toolbar icons in colour**: vector matplotlib sources re-coloured to the SVG brand palette
  (home blue / back orange / forward green / pan purple / zoom cyan / subplot red / edit brown /
  save dark blue), same-hue rounded light backgrounds, QtSvg high-DPI rendering, silent fallback to the original icon on failure
- **Colour icons for function buttons**: new (blue document + green plus) / import pattern (cyan · diffraction peak shape) /
  import CIF (purple · hexagonal lattice) / ▶Refine (green · play triangle) / report export (orange · export arrow),
  drawn programmatically with QPainter (zero asset dependency), clear at 16–48px across sizes and high DPI
- Gear dialogs: background, unit cell (per-phase checkboxes), peak shape, atoms, temperature factors, PO, microstructure
- Three result pages: summary (R factors/content/DW/e.s.d.), convergence curve, correlation matrix
- Trilingual i18n (zh/en/ja, switching requires no restart), project file `.xrp` save/restore
- Report export: HTML + PNG + JSON refinement log

### Command line and API

- `XinRefinementCLI refine <pattern> <cif...>`: `--recipe` (stepwise recipe), `--report` (HTML/PNG/JSON directory), `--quant` (WPF quantification), `--esd` (Schur e.s.d.), `--version`
- Public library API: `xinrefinement/api.py` (`RefineRequest`/`RefineResponse`, `refine`/`quant`/`report`/`capabilities`, `API_VERSION`)

### Two variants and registration (modeled on XinMatch)

- **Release build**: Inno Setup installer; wired into the PolyXRD-Reg offline registration mechanism
  (`xinrefinement/registration.py` is verbatim identical in source to XinMatch, same keys, interoperable registration codes),
  shows an unregistered copyright notice at startup, Help menu "Enter registration code…", and the right end of the status bar shows "Registered: organization name / Not registered"
- **Internal evaluation build**: installer-free portable zip, no registration; the right end of the status bar shows "Internal evaluation build" in red
- The variant is fixed by the bundled `variant.txt` (missing → treated as release, fail-safe); frozen builds ignore the environment variable,
  preventing `XINREFINEMENT_VARIANT` from bypassing the registration notice
- Registration state file `%APPDATA%\PolyXRD\Registration\XinRefinement.json`;
  developer-side code generation `tools/make_reg_code.py "organization name"`
- Acceptance helper: `XINREFINEMENT_SELFTEST_REG_OUT=<json>` exports variant/registration state at startup and exits

### Acceptance

- **259 tests all green**; `bench_b` family golden round-trip **8/8 PASS** (Rwp 3.41–4.04%, bit-for-bit identical to before the port)
- Virtual-sample full benchmark **18/18 PASS** (5 crystal systems × 1–3 phases × injected knobs)
- Real anchors: NCM811 real sample converges (Rwp 11.25% registered); **GSAS-II 5.8.2 cross-validation of the unit cell, maximum relative difference 0.031% (real sample) / 0.015% (two-phase)**
- Release artifacts: `XinRefinement-1.0.0-setup.exe` (Windows x64 installer, zh/en/ja, with PolyXRD-Reg registration);
  the internal evaluation build `XinRefinement-internal-1.0.0-portable.zip` is for internal use only and is not distributed with Releases
- **Reproducible build**: the build script pins `SOURCE_DATE_EPOCH` (= git HEAD commit time) and `PYTHONHASHSEED=0`,
  eliminating the two sources of non-determinism in PyInstaller — the PE header timestamp and string-set hash randomization — so two consecutive builds
  of the same commit give four byte-identical exes (installer/zip still vary because of embedded timestamps and get functional acceptance only)

### Known limitations

- If X/Y of the TCH size-strain stops at 0 (the branch switch point) after refinement, its e.s.d. is recorded as empty (derivative undefined)
- Occupancy refinement requires anchored sites (absolute occupancy of all sites in a single phase is absorbed by scale and is physically unidentifiable)
- GSAS-II cross-validation and FullProf/MAUD/Profex comparisons for multi-phase QPA are manual steps
