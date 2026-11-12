**First official release.**

XinRefinement is a desktop application for general-purpose powder diffraction whole-pattern
fitting (Rietveld structural refinement / Le Bail / pattern refinement), offering three entry
points — a Qt6 graphical interface, a command line, and a Python library API — and covering
the complete workflow from "import pattern + phase CIF → whole-pattern fitting →
quantification and uncertainty → report". Division of labour with the family project
XinMatch: XinMatch handles peak shape processing and phase analysis, XinRefinement does
whole-pattern fitting only.

## Download

| File | Applies to | Notes |
|---|---|---|
| `XinRefinement-1.0.0-setup.exe` | Windows x64 | Release installer (Simplified Chinese / English / Japanese), includes offline PolyXRD-Reg registration |

The internal evaluation build (portable zip, no installation) is for internal testing only
and is not distributed with this Release.

## Key capabilities

### Refinement engine

- Variable projection (scale factors and background eliminated analytically) + LM / scipy-trf dual backends, with bound constraints and multi-start restarts
- spglib, all 230 space groups, including H/R settings and Wyckoff-site-symmetry null-space free coordinates
- Peak shape: Caglioti FWHM, TCH size/strain separation, η (pseudo-Voigt), low-angle asymmetry, Kα1/Kα2 doublet
- Structure: atomic coordinates, isotropic B, occupancy; March–Dollase preferred orientation
- Quantification and uncertainty: Hill–Howard QPA, Schur-complement e.s.d. for all parameters, Durbin–Watson
- Le Bail intensity extraction + multi-phase quantification; CIF write-back (unit cell / coordinates / B / occupancy)

### Graphical interface

- Three-pane main window + 8-step guided refinement (single-step ▶ / gear settings / one-click run-all / Stop button)
- MAUD-style phase marker strip: one row per phase, coloured by phase, stick height ∝ relative intensity within the phase; residual panel narrowed
- Axis switching: horizontal axis 2θ ↔ d value (Bragg conversion, automatically reversed), vertical axis counts ↔ log ↔ √;
  left-click the axis to cycle, right-click for a menu
- Edit → Edit phase parameters: six unit-cell parameters, March–Dollase preferred orientation, space group / point group / Laue group
- Three result pages: summary (R factors / content / DW / e.s.d.), convergence curve, correlation matrix
- Trilingual interface (zh / en / ja, switching without restart), project file `.xrp`, HTML+PNG+JSON report export

### Command line

```bash
XinRefinementCLI refine pattern.xy phase_a.cif phase_b.cif -o out.json
XinRefinementCLI refine pattern.xy phase_a.cif phase_b.cif --recipe --report out_dir --quant --esd
```

## Validation data

| Item | Result |
|---|---|
| Unit/integration tests | 259 all green (engine, GUI offscreen smoke, CLI, i18n, registration and variants) |
| Synthetic benchmark `bench_b` (family golden) | 8/8 PASS, Rwp 3.41–4.04%, bit-for-bit identical to before the port |
| Full benchmark `bench_full` (5 crystal systems × 1–3 phases) | 18/18 PASS |
| Real sample NCM811 | Converged, Rwp 11.25% |
| Cross-validation against GSAS-II | Maximum relative unit-cell difference 0.031% (real sample) / 0.015% (two-phase) |

## Installation and registration

1. Run `XinRefinement-1.0.0-setup.exe` and choose the installation language;
2. On first launch a prompt appears: "This software is not registered. All rights reserved; commercial use is prohibited." —
   choose "OK" to continue the trial, or "Enter registration code" to complete registration;
3. After installation the Start menu contains **XinRefinement** (GUI) and **XinRefinementCLI** (command line).

Registration codes are issued per "organisation / department name", verified offline, no
network required, and valid on multiple machines within the same organisation;
applications and technical support: **sshztx@outlook.com**.

## Known notes

- No code signing: on first run Windows SmartScreen may warn of an "unknown publisher"; choose "Run anyway".
- The registration code uses offline HMAC verification (the key ships with the software, giving obfuscation-level strength).
- The installer is about 67 MB (including Qt / matplotlib runtimes); GUI cold start is about 2–4 s.

## License

Dual license: academic license (non-commercial research and teaching) or a separately
requested commercial license.
Copyright (c) 2026 PolyXRD Team. See `LICENSE` / `LICENSE-CN` in the repository.
