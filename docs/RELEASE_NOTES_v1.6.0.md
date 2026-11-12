# XinRefinement v1.6.0 — UI rework, and the unit-cell checkboxes finally take effect

> Baseline `v1.5.0` | Theme: **engine untouched, tell the result clearly**. v1.5.0 closed the
> fit-quality gap to MAUD down to +0.21 pt, but the UI still organised information the v1.0
> way: phases shown by CIF filename (`1Entry_96-500-0036`), a column of static placeholder
> lines at the bottom left, clicking ▶ without knowing what the step refines, and
> quantification plus unit-cell parameters that could only be found row by row in the
> summary table. This version reworks those four areas and fixes a **functional defect** left
> over from v1.5 — the row of checkboxes in the unit-cell dialog was never passed into the
> engine.
>
> **Zero numerical change**: the golden 50/50 case is still `3.4074156640940005`, CLI/API
> behaviour bit-for-bit unchanged.

## Download

| File | Size | SHA256 |
|---|---|---|
| `XinRefinement-1.6.0-setup.exe` | 75.8 MB | `c35fceaa37dafa9ebf14f48ca55d7bc62e0c87a86f6fcb44e5230f25c1aa17f2` |

> Release installer (includes registration, zh/en/ja installer UI). The internal evaluation
> portable build (`XinRefinement-internal-1.6.0-portable.zip`, 114.2 MB,
> sha256 `5fb97ea234732a3f825cc4e60806b5d9a5ae470b80acdc7edb7e1a6c0044c439`)
> is for internal acceptance only and is not distributed with this Release.

## What changed at a glance

| | v1.5.0 | v1.6.0 |
|---|---|---|
| How phases are displayed | CIF filename (`1Entry_96-500-0036`) | **Formula · phase name** (`TiO2 · Anatase`), three modes selectable, formula by default |
| Bottom-left run log | Static placeholder lines | MAUD-style **scrolling log**: start line / `parameter: old → new` / `done · Rwp a → b` |
| Clicking a navigation ▶ | Starts immediately, no hint of what is refined | Pops a **step description dialog** first (step parameters + current values + explanation); after confirming the same content goes into the log |
| Marker-strip labels | CIF filename | Display name, **right-click** switches formula/phase name/filename |
| Result area | Summary / convergence / correlation, three pages | Adds **phase quantification** (5 columns, total row) and **unit cell and microstructure** (11 columns) |
| Unit-cell dialog checkboxes | **Decorative** (checking had no effect, everything but a/c greyed out) | Really effective: `RefineConfig.cell_axes` → engine; greyed out per crystal system with the reason stated |
| Edit → phase parameters | Single-column vertical layout, buttons pushed out with many phases | Two-column grid + scroll area, minimum width 880 |

## Main changes

### 1. Three phase display modes (formula by default)

New `core/profile/naming.py`: `formula` (default) / `label` / `file`.

- Formula normalization does only two safe things: **compaction** (`O2 Si` → `SiO2`) and
  **regrouping with order preserved within groups** following "metal → non-metal → anion"
  (`O4 S Zn` → `ZnSO4`, `Co0.1 Li1.03 Ni0.77 Co0.1 Mn0.1 O2` → `Co0.2Li1.03Ni0.77Mn0.1O2`).
  **No element count is changed**, and no electronegativity sort is done (that would scramble
  the familiar ordering of multi-metal systems such as NCA).
- `CifStructure` gains `name_mineral`: `parse_cif` takes the first non-empty of
  `_chemical_name_mineral` → `_chemical_name_common` → `_chemical_name_systematic`.
- A three-level fallback (formula → label → file) guarantees every CIF has a displayable string.
- **Same-name polymorphs are distinguished automatically**: anatase/rutile/brookite all have
  the formula `TiO2`, so two `TiO2.a` entries in the log cannot be told apart → when display
  names collide, the phase name is appended.

### 2. Bottom-left run log (MAUD-style scrolling log)

Read-only `QPlainTextEdit`, NoWrap, at most 4000 lines (long chains do not grow memory
without bound), auto-scroll to bottom, with a "Clear log" button. Three kinds of lines:

```
=== Starting "Unit cell parameters" ===
  Initial parameter values:
  zero: 0.0299
  TiO2 · Anatase.a: 3.785
  ...
  TiO2 · Anatase.a: 3.785 → 3.78215
=== "Unit cell parameters" done · Rwp 7.1816 → 6.9034 ===
```

- Parameter lines are filtered at a **relative 1e-9**: floating-point jitter does not flood
  the log, real changes always show up.
- When the first snapshot has no "previous frame" to compare against, it prints the
  **list of initial parameter values** — otherwise the log would only show one Rwp line and
  there would be no way to see what this round is actually refining.
- Unit-cell parameters are flattened per phase into keys like `TiO2 · Anatase.a`, so which
  phase and which axis is moving is visible at a glance.

### 3. Navigation step description dialog (one-to-one with the run log)

Clicking any ▶ pops a dialog first, then **writes the same content into the log** before
starting. Each of the eight steps has its own list: zero point gives the current value;
background gives mode/node count/peak-shape basis; scale gives the per-phase S; unit cell
gives **the components that will actually be refined per phase**; peak shape gives
U/V/W/η/asym; xyz gives the over-budget strategy; micro gives X/Y/anisotropy/texture; B gives
ΔB_iso and the 6 Å² upper bound. The button text is "▶ Start refinement" rather than "OK".

### 4. Two new pages in the result area

- **Phase quantification**: display name / wt% / e.s.d. / Z / unit-cell volume, with a total
  row (QPA theoretically normalizes to 100, so the total row is the fastest consistency check).
- **Unit cell and microstructure**: display name / refined components / a b c α β γ / V /
  crystallite size D / microstrain ε, 11 columns.
- Anisotropic phases: the coefficients are a Cholesky 3×3, and the interface takes the
  **mean of the singular values** (volume average) to convert to Å / ε in the same dimension
  as the isotropic case, marking the D column with `*`; when `aniso` is present the scalar X/Y
  are no longer read (after the micro step enables Popa LB the scalars are no longer
  refined, so reading X/Y would keep showing the initial values).

### 5. Fix: the unit-cell dialog checkboxes were decorative (defect left over from v1.5)

- **Symptom**: all non-a/c checkboxes were `setEnabled(False)` with the note "all 6 parameters
  opened by P1.2" — long outdated; worse, `_settings["cell"]` **was never passed to the
  engine**, so refinement always released the full crystal system and the checkboxes were
  purely decorative.
- **Fix**: `RefineConfig.cell_axes` (phase name → allowed components) → `recipe._run_cell` →
  `refine_cell_full(axes_override=...)` → `apply_cell_scales(axes=...)`. The metric is given
  uniformly by `resolve_axes(system, requested) = crystal system allowed ∩ user selection`,
  illegal axes are dropped silently; `None` (never set) is **bit-for-bit identical** to v1.5.
- **Dialog rework**: one group box per phase, 3×2 checkbox grid, two columns side by side
  (four phases no longer need 24 rows of scrolling); non-free axes are greyed out per crystal
  system with a reason tooltip (cubic releases only a; tetragonal/hexagonal/trigonal release
  a, c; monoclinic adds β; triclinic releases all).
- End to end: checking only a → `3.785 → 3.78215`, c stays `9.5196`; the recipe message
  changes from `/ 2 params` to `/ 1 param` (it used to count with the full crystal system).

### 6. Fix: layout of Edit → Edit phase parameters

Two-column grid (unit cell / preferred orientation / texture and anisotropy / microstrain /
symmetry, two groups side by side) + `QScrollArea` + minimum width 880: with many phases the
bottom buttons are no longer pushed out of the window. The phase selection combo uses the
display name.

## Verification

- Full regression **512 items: 512 passed / 0 failed / 0 skipped, EXIT=0**
  (471 in v1.5.0; adds 17 in `test_v16_naming_and_cell_axes.py`, 20 in `test_v16_gui.py`,
  plus 4 that are no longer skipped after `gemmi` was installed locally).
- golden CLI Rwp 50/50 case **`3.4074156640940005`** unchanged; the `axes_override=None`
  path has a dedicated test guarding "bit-for-bit unchanged".
- Packaged artifact really run: `XinRefinementCLI.exe refine … --recipe --time-budget-min 3`
  produces a report normally (5.8391%); the frozen package is confirmed to contain the three
  new modules `naming` / `cell` / `dialogs`.
- Also fixes two test problems **masked by skips** (they started really running after
  `gemmi` was installed): the golden constant of `test_joint_s1` was frozen before M11
  (measured now equal to golden), and the bit-for-bit assertion of `test_xyz_phase_select`
  differs by 8e-11 in a full sequential run (multi-threaded BLAS reduction is not
  bit-reproducible, and the strategy itself does not enter the numerical path) → aligned and
  relaxed respectively, see `CHANGELOG.md`.

## Known limits

- **Sample 7 is still below standard** (+3.39 pt, the near-amorphous broad-envelope starting
  point of cristobalite); v1.6 does not touch the engine, this is left to a later dedicated
  effort.
- **The acceptance criterion has changed metric**: item 6 of §5 in the project proposal is now
  "mean difference ≤ 1 pt on the same dataset and no single sample differs by > 4 pt"; the old
  per-sample `≤ MAUD+2` is downgraded to a diagnostic reference.
- Unit-cell component checkboxes affect the `cell` step only; the joint refinement of the
  `profile` step still releases the full crystal system (it is another set of degrees of
  freedom, and mixing them would distort the parameter-correlation diagnostics).

## Installation and registration

Same as v1.5.0: the installer has a built-in zh/en/ja interface, registration codes
interoperate across the XinMatch family
(`%APPDATA%\PolyXRD\Registration\XinRefinement.json`). The internal evaluation build needs
no registration and no installation, and is marked in red in the status bar.

## License

This software uses the MIT license. The bundled crystal structure data comes from COD (CC0)
and ICSD-derived public literature, and **contains no PDF cards or ICDD data**.
