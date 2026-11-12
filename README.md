# XinRefinement

<p align="center">
  <img src="assets/icons/logo_512.png" width="180" alt="XinRefinement logo">
</p>

**General-purpose desktop software for whole-pattern fitting of powder diffraction data (Rietveld structural refinement / Le Bail / profile refinement).**

> [Chinese (Simplified)](README-CN.md) · English

Three entry points — Qt6 GUI, command line, and Python library API — covering the complete workflow of "import pattern + phase CIF → whole-pattern fitting → quantification and uncertainty → report".
XinRefinement and its family project XinMatch divide the work: XinMatch handles peak-shape processing and phase analysis, while XinRefinement does only whole-pattern fitting (structural refinement, profile refinement, quantification).

Current version: **v1.4.0** (in development, unreleased) · Previous version: v1.3.0
v1.4.0 theme: wrapping up cross-checks — bringing capabilities already landed in v1.3 but not yet in the production recipe to real-sample validation:
automatic preferred-orientation probing + window strategy in the micro step, per-phase ΔB_iso, and atomic-coordinate xyz steps,
plus a full re-test and modeling-gap assessment using 7 manually refined MAUD real samples;
see [CHANGELOG](CHANGELOG.md) and
[Evaluation Report §11.5](docs/评估报告-实样对拍-MAUD-v1.md).
v1.3.0 theme: the entire MAUD reference checklist has landed — the μ·r calculator (Brindley
inputs computed automatically from chemical composition), theoreticalWeights weighting, canvas point-and-click background anchors, EWIMV discrete ODF texture,
Popa LB anisotropic size/strain, and pluggable optimizers (lm/trf/dogbox);
see [CHANGELOG](CHANGELOG.md).
v1.2.0 theme: refinement-quality upgrades driven by real-sample cross-checks (true unit-cell refinement in the recipe, integrated-intensity convention,
factory-default adaptive tent background, weighting modes, Brindley microabsorption, interpolated/manual background);
see [CHANGELOG](CHANGELOG.md).
v1.1.0 theme: interoperability with XinMatch 3.4.0 (`.xinm` import / `.xinr` self-contained project).

---

## Features

### Family interoperability (new in v1.1.0)
- **Import XinMatch phase analysis (`.xinm`)**: `File → Import XinMatch Phase Analysis…` loads the pattern (including wavelength, with the d-axis immediately available) + phase CIF + metadata in one shot, then goes straight to recipe refinement; phases without a structure (PDF2-type) are listed as "reference only" with a prompt to supply a CIF manually
- **Project file `.xinr` (self-contained zip container)**: embeds the pattern CSV (`%.10g`, zero round-trip error) + CIF + full refinement results (`result/refine.json`); still opens and reproduces the last results after switching machines or moving directories; legacy `.xrp` kept permanently read-only compatible
- **Library API**: `capabilities()` exposes the `xinm_import` capability flag, so external programs can probe it before deciding whether to expose the import entry point

### Refinement engine
- **Parameter model**: a declarative parameter registry (`ParameterRegistry`), full unit cell constrained by crystal system (cubic 1 → triclinic 6); dual-track compatible with the legacy `_pack/_unpack` path and bit-for-bit identical
- **Solver**: variable projection (analytical elimination of the scale factor and background) + dual LM / scipy-trf backends, with bound constraints and multi-start restarts
- **Symmetry**: all 230 space groups via spglib, including H/R settings and the symmetry null space of Wyckoff sites (free-coordinate dimensions)
- **Peak shape**: Caglioti FWHM, TCH size/strain separation, η (pseudo-Voigt), low-angle asymmetry, Kα1/Kα2 doublet, March–Dollase preferred orientation
- **Structure**: atomic coordinates (Wyckoff-constrained), isotropic B, occupancies (including degenerate-anchoring handling)
- **Quantification and uncertainty**: Hill–Howard QPA, Schur-complement parameter e.s.d. (including scale/background/weight fraction), Durbin–Watson statistic
- **Le Bail**: structure-free intensity extraction + multiphase quantification; **CIF write-back**: unit cell / coordinates / B / occupancies

### Graphical user interface (PySide6)
- Three-pane main window: phase list + interactive pattern + guided refinement (8 steps, single-step ▶ / gear settings / one-click run-all / stop)
- **MAUD-style phase marker bars**: one bar per phase, phase name on the left, colored by phase, bar height ∝ relative intensity within the phase
- **Axis switching**: horizontal 2θ ↔ d-spacing (Bragg conversion, auto-reversal), vertical counts ↔ log ↔ √; left-click on an axis to cycle, right-click for the menu
- **Phase parameter editing**: unit cell a/b/c/α/β/γ, March–Dollase preferred orientation, space group / point group / Laue group
- Three tabs in the results area: summary (R factors / content / DW / e.s.d.), convergence curve, correlation matrix
- Trilingual UI (Simplified Chinese / English / Japanese, switch without restart), project file `.xinr` (self-contained) / `.xrp` (path references, legacy compatible)
- Report export: HTML + PNG + JSON refinement log

### Command line and library API
```bash
XinRefinementCLI refine <pattern> <phase.cif...> [-o out.json]
                        [--recipe] [--report DIR] [--quant] [--esd] [--peak-height]
```
- `--recipe`: step-by-step refinement following the standard recipe; `--report`: the HTML/PNG/JSON trio; `--quant`: Hill–Howard quantification table; `--esd`: Schur e.s.d.
- Library API: `xinrefinement/api.py` (`RefineRequest` / `RefineResponse`, `refine` / `quant` / `report` / `capabilities`, `API_VERSION`), callable by external programs such as XinMatch

### Dual build variants
| Variant | Form | Registration |
|---|---|---|
| **Release** | Inno Setup installer (zh/en/ja) | Integrated with the PolyXRD-Reg offline registration mechanism |
| **Internal evaluation build** | Installation-free portable zip | No registration; the status bar is labeled "Internal Evaluation Version" |

---

## Installation

Release artifacts are on [GitHub Releases](https://github.com/PolyXRD/XinRefinement/releases) (currently `v1.1.0`).

### Release (recommended)
1. Download `XinRefinement-1.1.0-setup.exe` (67.6 MB, SHA-256 `046179e6…a44926`), double-click to install (choose from Simplified Chinese / English / Japanese);
2. On first launch a prompt appears: "This software is unregistered. All rights reserved. Commercial use is prohibited." —
   click "OK" to continue the trial, or click "Enter Registration Code" and paste your code to complete registration;
3. After installation, the Start menu contains **XinRefinement** (GUI) and **XinRefinementCLI** (command line).

Registration codes are issued by the developer based on the "organization / department name", verified offline with no network connection required, and valid across multiple machines within the same organization.
Applications and technical support: **sshztx@outlook.com**

### Internal evaluation build
Building from source (see below) produces `XinRefinement-internal-1.1.0-portable.zip`; unzip and run it directly, with no installation and no registration required
(for internal testing and evaluation only, **not distributed with Releases**).

---

## Quick start

### Graphical user interface
```bash
XinRefinement.exe
```
1. **Import pattern** (`.xy/.txt/.dat/.csv/.xye`) + **import CIF** (multiple selection allowed);
   If phase analysis was already completed in XinMatch, use `File → Import XinMatch Phase Analysis…` and select `.xinm` to have the pattern and CIFs ready in one step;
2. Per-phase marker bars appear below the pattern area; check the phase toggles for a live preview;
3. Click ▶ step by step in the navigation pane on the right, or use "one-click run-all" to run all 8 steps of the standard recipe at once;
4. View Rwp / content / e.s.d. in the results area; "Export Report" on the toolbar outputs HTML+PNG+JSON;
5. `File → Save Project…` saves as `.xinr` (pattern/CIF/results embedded, so you can continue on another machine).

### Command line
```bash
# Single-pass unified refinement
XinRefinementCLI refine pattern.xy phase_a.cif phase_b.cif -o out.json --peak-height

# Recipe step-by-step + HTML report + quantification + e.s.d.
XinRefinementCLI refine pattern.xy phase_a.cif phase_b.cif --recipe --report report_dir --quant --esd
```

### Running from source (development)
```bash
python -m pytest -q            # tests
python -m xinrefinement.gui    # GUI
python -m xinrefinement.cli --help
run_dev.bat                    # Windows one-click launch (auto-selects the interpreter, runs the latest source)
```

---

## Build (local)

```bash
python tools/build_binaries.py                    # Full pipeline for both variants
python tools/build_binaries.py --variant release  # Build the release variant only
python tools/build_binaries.py --variant internal # Build the internal evaluation variant only
```

Artifacts (in `dist/`, not committed):

| Path | Description |
|---|---|
| `dist/XinRefinement-1.1.0/` | onedir, GUI + CLI dual exe sharing dependencies |
| `dist/installer/XinRefinement-1.1.0-setup.exe` | Release installer (Inno Setup, zh/en/ja) — the only artifact shipped with Releases |
| `dist/XinRefinement-internal-1.1.0/` + `…-portable.zip` | Internal evaluation build directory and portable build (not publicly released) |

Dependency: Inno Setup 6 (needed only for the installer). The packaging script performs a read-back check of the variant marker to prevent the internal build from degrading into a forced-registration build.
Builds pin `SOURCE_DATE_EPOCH` (= git HEAD commit time) and `PYTHONHASHSEED=0`;
two consecutive builds of the same commit produce four exes that are **byte-for-byte identical** (the installer/zip contains embedded timestamps, which are excluded from hash comparison).

---

## Testing and validation

| Category | Result |
|---|---|
| Unit / integration tests | **286 all green** (engine, offscreen GUI smoke, CLI, i18n, registration and variants, `.xinm`/`.xinr` interoperability) |
| Family chain S1–S4 | Real COD entries (7206075 + 9001681) `.xinm` → import → refinement **Rwp 3.409617019598457** (bit-for-bit identical to the P0 golden value), Wt 50.03/49.97; `.xinr` reproduces after deleting the source (rel 1e-9) |
| Synthetic benchmark `bench_b` (family golden) | 8/8 PASS, Rwp 3.41–4.04%, bit-for-bit identical before and after porting |
| Full benchmark `bench_full` (5 crystal systems × 1–3 phases) | 18/18 PASS |
| Real-sample anchor | NCM811 real sample converged (Rwp 11.25%) |
| **GSAS-II cross-validation** | Maximum unit-cell relative difference **0.031%** (real sample) / **0.015%** (two-phase) |

For the cross-validation method and conclusions, see [`docs/CROSS_VALIDATION.md`](docs/CROSS_VALIDATION.md).

---

## Project structure

```
xinrefinement/
  core/            # Engine (GUI-independent)
    io/            # .xinm import (XinMatch phase-analysis state)
    profile/       # CIF parsing, peak shape, structure factors
    refine/        # Solvers, parameter registry, recipe, e.s.d., Le Bail, diagnostics
    report.py      # HTML/PNG/JSON reports
    palette.py     # Family color palette (shared by GUI and reports)
  gui/             # PySide6 UI (main window, canvas, dialogs, icons)
  cli/             # CLI entry point
  i18n/            # Trilingual catalogs
  data/            # Bundled CIFs, space-group tables, brand assets
  api.py           # Public library API contract
  registration.py  # PolyXRD-Reg registration (shared with family projects)
  build_variant.py # Build-variant detection
packaging/         # PyInstaller spec + Inno Setup scripts
tools/             # Build, cross-validation, benchmarks, key generation
docs/              # Plans, task manuals, acceptance sheets, cross-validation
tests/             # pytest (incl. offscreen GUI smoke tests)
```

---

## Documentation

| Document | Contents |
|---|---|
| [`CHANGELOG.md`](CHANGELOG.md) | Version change log |
| [`docs/RELEASE_NOTES_v1.1.0.md`](docs/RELEASE_NOTES_v1.1.0.md) | v1.1.0 release notes (interoperability features and acceptance data) |
| [`docs/RELEASE_1.0.0.md`](docs/RELEASE_1.0.0.md) | v1.0.0 release acceptance checklist (six rounds of robustness) |
| [`docs/JOINT_PLAN_xinm_xinr.md`](docs/JOINT_PLAN_xinm_xinr.md) | `.xinm`/`.xinr` format contract with XinMatch (single source of truth) |
| [`docs/PROJECT_PLAN.md`](docs/PROJECT_PLAN.md) | Technical design and architecture decisions |
| [`docs/TASKS.md`](docs/TASKS.md) | Task manual (P1–P5 delivery records) |
| [`docs/CROSS_VALIDATION.md`](docs/CROSS_VALIDATION.md) | Cross-validation of structural quantities against GSAS-II |
| [`README-en.md`](README-en.md) | English README |

---

## License

**Dual license**: an academic license (non-commercial research and teaching) or a separately requested commercial license.
Copyright (c) 2026 PolyXRD Team. See [`LICENSE`](LICENSE) / [`LICENSE-CN`](LICENSE-CN) for details.

The licensing and registration mechanism is inherited from the family project XinMatch; commercial use requires a written commercial license first.

Third-party components: PySide6 (LGPL-3.0), matplotlib (PSF-based), NumPy / SciPy (BSD-3-Clause), spglib (BSD-3-Clause).

---

## Contact

- Registration code requests / commercial licensing / issue reports: **sshztx@outlook.com**
