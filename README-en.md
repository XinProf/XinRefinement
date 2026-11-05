# XinRefinement

<p align="center">
  <img src="assets/icons/logo_512.png" width="180" alt="XinRefinement logo">
</p>

**Desktop software for whole-pattern fitting of powder diffraction data (Rietveld structural refinement / Le Bail / profile refinement).**

[简体中文](README.md) · English

Three entry points — Qt6 GUI, command line, and a Python library API — covering the full workflow
«import pattern + phase CIFs → whole-pattern fit → quantification and uncertainties → report».
Division of labour within the family: XinMatch handles peak processing and phase identification,
XinRefinement only performs whole-pattern fitting (structural refinement, profile refinement, quantification).

Current version: **v1.1.0** (released 2026-11-05) · Previous: v1.0.0
v1.1.0 theme: interoperability with XinMatch 3.4.0 (`.xinm` import / self-contained `.xinr` projects).

---

## Features

### Family interoperability (new in v1.1.0)
- **Import XinMatch phase analysis (`.xinm`)** — `File → Import XinMatch phase analysis…` loads the pattern
  (including wavelength, so the d-spacing axis works immediately), the phase CIFs and the metadata in one go,
  and drops you straight into recipe refinement. Phases without structure (e.g. PDF2 cards) are listed as
  *reference only* together with a hint to supply a CIF manually.
- **Project file `.xinr` (self-contained zip container)** — embeds the pattern as CSV (`%.10g`, lossless
  round-trip), the CIFs and the full refinement result (`result/refine.json`). Projects keep working after
  moving to another machine or directory, and the previous result is restored on open. Legacy `.xrp` files
  stay readable (read-only compatible).
- **Library API** — `capabilities()` exposes an `xinm_import` capability flag so host applications can probe
  support before showing an import entry point.

### Refinement engine
- **Parameter model** — declarative parameter registry (`ParameterRegistry`) with cell constraints per crystal
  system (cubic 1 → triclinic 6); bit-identical to the legacy `_pack/_unpack` path.
- **Solver** — variable projection (scale factors and background eliminated analytically) with LM / scipy-trf
  backends, bound constraints and multi-start restarts.
- **Symmetry** — spglib, all 230 space groups, including H/R settings and Wyckoff-site null spaces for free
  coordinates.
- **Peak shape** — Caglioti FWHM, TCH size/strain separation, η (pseudo-Voigt), low-angle asymmetry,
  Kα1/Kα2 doublet, March–Dollase preferred orientation.
- **Structure** — atomic coordinates (Wyckoff-constrained), isotropic B, occupancies (with degenerate-anchor
  handling).
- **Quantification and uncertainties** — Hill–Howard QPA, Schur-complement e.s.d. for all parameters
  (scale/background/weight fractions), Durbin–Watson statistic.
- **Le Bail** — structure-free intensity extraction with multi-phase quantification; **CIF write-back** of cell,
  coordinates, B and occupancies.

### GUI (PySide6)
- Three-pane main window: phase list + interactive pattern + navigation-style refinement
  (8 steps, per-step ▶, gear settings, run-all, stop).
- **MAUD-style phase tick strips** — one strip per phase, labelled on the left, coloured per phase, bar height
  proportional to the in-phase relative intensity.
- **Axis switching** — horizontal 2θ ↔ d (Bragg conversion, automatically reversed); vertical counts ↔ log ↔ √;
  left-click cycles, right-click opens a menu.
- **Phase parameter editor** — cell a/b/c/α/β/γ, March–Dollase preferred orientation, space/point/Laue group.
- Result area with three tabs: summary (R factors / weight fractions / DW / e.s.d.), convergence curve,
  correlation matrix.
- Trilingual UI (Simplified Chinese / English / Japanese, switched without restart); project files `.xinr`
  (self-contained) or `.xrp` (path references, legacy compatible).
- Report export: HTML + PNG + JSON refinement log.

### Command line and library API
```bash
XinRefinementCLI refine <pattern> <phase.cif...> [-o out.json]
                        [--recipe] [--report DIR] [--quant] [--esd] [--peak-height]
```
- `--recipe`: step-by-step refinement along the standard recipe; `--report`: HTML/PNG/JSON bundle;
  `--quant`: Hill–Howard quantification table; `--esd`: Schur e.s.d.
- Library API: `xinrefinement/api.py` (`RefineRequest` / `RefineResponse`, `refine` / `quant` / `report` /
  `capabilities`, `API_VERSION`) for external callers such as XinMatch.

### Two build variants
| Variant | Form | Registration |
|---|---|---|
| **Release** | Inno Setup installer (zh/en/ja) | PolyXRD-Reg offline registration |
| **Internal evaluation** | Portable zip, no installation | No registration; status bar marked "internal build" |

---

## Installation

Builds are published on [GitHub Releases](https://github.com/PolyXRD/XinRefinement/releases) (currently `v1.1.0`).

### Release build (recommended)
1. Download `XinRefinement-1.1.0-setup.exe` (67.6 MB, SHA-256 `046179e6…a44926`) and run the installer
   (Simplified Chinese / English / Japanese).
2. On first launch the software reports "not registered — all rights reserved, commercial use prohibited".
   Press OK to continue evaluating, or "Enter registration code" to activate.
3. The Start menu contains **XinRefinement** (GUI) and **XinRefinementCLI** (command line).

Registration codes are issued per organisation/department, verified offline, and work on any number of
machines within the same organisation. Requests and support: **sshztx@outlook.com**

### Internal evaluation build
Building from source (see below) produces `XinRefinement-internal-1.1.0-portable.zip`; unzip and run —
no installation, no registration (internal testing only, **not distributed via Releases**).

---

## Quick start

### GUI
```bash
XinRefinement.exe
```
1. **Import pattern** (`.xy/.txt/.dat/.csv/.xye`) and **import CIFs** (multi-select).
   If the phase analysis was already done in XinMatch, use `File → Import XinMatch phase analysis…` and pick
   the `.xinm` file — pattern and CIFs arrive together.
2. Tick strips appear below the pattern; toggling a phase previews it instantly.
3. Refine step by step with ▶ on the right, or press "Run all" to execute all 8 recipe steps at once.
4. Inspect Rwp / weight fractions / e.s.d. in the result area; the toolbar "Export report" writes HTML+PNG+JSON.
5. `File → Save project…` stores a `.xinr` (pattern, CIFs and result embedded, portable across machines).

### Command line
```bash
# single unified refinement
XinRefinementCLI refine pattern.xy phase_a.cif phase_b.cif -o out.json --peak-height

# recipe steps + HTML report + quantification + e.s.d.
XinRefinementCLI refine pattern.xy phase_a.cif phase_b.cif --recipe --report report_dir --quant --esd
```

### Running from source (development)
```bash
python -m pytest -q            # tests
python -m xinrefinement.gui    # GUI
python -m xinrefinement.cli --help
run_dev.bat                    # one-click Windows launcher (picks an interpreter, runs latest source)
```

---

## Building (local)

```bash
python tools/build_binaries.py                    # both variants, full pipeline
python tools/build_binaries.py --variant release  # release only
python tools/build_binaries.py --variant internal # internal evaluation only
```

Artifacts (in `dist/`, not tracked):

| Path | Description |
|---|---|
| `dist/XinRefinement-1.1.0/` | onedir layout, GUI and CLI executables sharing dependencies |
| `dist/installer/XinRefinement-1.1.0-setup.exe` | release installer (Inno Setup, zh/en/ja) — the only file published to Releases |
| `dist/XinRefinement-internal-1.1.0/` + `…-portable.zip` | internal evaluation build (not published) |

Requirements: Inno Setup 6 (installer only). The build script re-reads the variant marker to prevent an
internal build from silently degrading into a registration-enforcing release build.

Builds pin `SOURCE_DATE_EPOCH` (= git HEAD commit time) and `PYTHONHASHSEED=0`, so two consecutive builds of
the same commit produce **byte-identical** executables (the installer and zip embed timestamps and are
excluded from hash comparison).

---

## Tests and validation

| Category | Result |
|---|---|
| Unit / integration tests | **286 passing** (engine, offscreen GUI smoke, CLI, i18n, registration and variants, `.xinm`/`.xinr` interoperability) |
| Family link S1–S4 | Real COD entries (7206075 + 9001681): `.xinm` → import → refinement gives **Rwp 3.409617019598457** (bit-identical to the P0 golden value), 50.03/49.97 wt%; `.xinr` reproduces the result after the sources are deleted (rel 1e-9) |
| Synthetic benchmark `bench_b` (family golden) | 8/8 PASS, Rwp 3.41–4.04%, bit-identical before and after the port |
| Full benchmark `bench_full` (5 crystal systems × 1–3 phases) | 18/18 PASS |
| Real anchor | NCM811 measured sample converges (Rwp 11.25%) |
| **GSAS-II cross-validation** | max cell relative difference **0.031%** (measured) / **0.015%** (two-phase) |

Method and conclusions: [`docs/CROSS_VALIDATION.md`](docs/CROSS_VALIDATION.md).

---

## Project layout

```
xinrefinement/
  core/            # engine (no GUI dependency)
    io/            # .xinm import (XinMatch phase-analysis state)
    profile/       # CIF parsing, peak shape, structure factors
    refine/        # solver, parameter registry, recipe, e.s.d., Le Bail, diagnostics
    report.py      # HTML/PNG/JSON reports
    palette.py     # family colour palette (shared by GUI and reports)
  gui/             # PySide6 interface (main window, canvas, dialogs, icons)
  cli/             # command-line entry point
  i18n/            # trilingual catalogue
  data/            # bundled CIFs, space-group tables, brand assets
  api.py           # public library API contract
  registration.py  # PolyXRD-Reg registration (shared with the family)
  build_variant.py # build-variant detection
packaging/         # PyInstaller spec + Inno Setup script
tools/             # build, cross-validation, benchmarks, code generation
docs/              # plans, task book, release checklists, cross-validation
tests/             # pytest (including offscreen GUI smoke tests)
```

---

## Documentation

| Document | Contents |
|---|---|
| [`CHANGELOG.md`](CHANGELOG.md) | Version history (Chinese) |
| [`docs/RELEASE_NOTES_v1.1.0.md`](docs/RELEASE_NOTES_v1.1.0.md) | v1.1.0 release notes (Chinese) |
| [`docs/RELEASE_1.0.0.md`](docs/RELEASE_1.0.0.md) | v1.0.0 release checklist (six robustness rounds, Chinese) |
| [`docs/JOINT_PLAN_xinm_xinr.md`](docs/JOINT_PLAN_xinm_xinr.md) | `.xinm`/`.xinr` format contract with XinMatch (single source of truth, Chinese) |
| [`docs/PROJECT_PLAN.md`](docs/PROJECT_PLAN.md) | Technical design and architecture decisions (Chinese) |
| [`docs/TASKS.md`](docs/TASKS.md) | Task book, P1–P5 delivery log (Chinese) |
| [`docs/CROSS_VALIDATION.md`](docs/CROSS_VALIDATION.md) | Structural cross-validation against GSAS-II |
| [`README.md`](README.md) | 简体中文 README |

---

## License

**Dual licensing**: academic licence (non-commercial research and teaching), or a separate commercial licence.
Copyright (c) 2026 PolyXRD Team. See [`LICENSE`](LICENSE) / [`LICENSE-CN`](LICENSE-CN).

Licence and registration follow the family project XinMatch; commercial use requires a written commercial licence.

Third-party components: PySide6 (LGPL-3.0), matplotlib (PSF-based), NumPy / SciPy (BSD-3-Clause),
spglib (BSD-3-Clause).

---

## Contact

- Registration codes / commercial licensing / bug reports: **sshztx@outlook.com**
