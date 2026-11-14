# XinRefinement v1.7.0 — Release Notes

Released: 2026-11-14

## Highlights

### Amorphous hump component (opt-in)

Samples that contain a genuinely amorphous fraction (glass, fumed silica)
scatter a broad hump that a Bragg-only model cannot carry. The common
workaround — a denser background — silently eats intensity from overlapping
peaks. v1.7.0 adds a **physical** broad component instead:

- `RefineConfig.amorphous = ((center_deg, fwhm_deg), ...)` and `amorphous_eta`
  (pseudo-Voigt mixing, default 0.5); CLI `--amorphous 22:9` (repeatable /
  comma-separated) and `--amorphous-eta`; the GUI background dialog gains an
  "amorphous hump" group.
- The hump amplitude is solved **in the linear layer** together with phase
  scales and background, so it adds **zero nonlinear parameters** and cannot
  steal degrees of freedom from the peak model. Center and FWHM are
  user-supplied and intentionally not refined.
- Disabled by default; with `amorphous=()` every code path is bit-identical
  to v1.6.4 (golden CLI Rwp still `3.4074156640940005`).

### Recipe-path fixes

- **`refine_asym` is now a real switch (conclusion 7).** `RefineStep.config_for()`
  used to hard-code `refine_asym=(key == "profile")` and ignore
  `RefineConfig.refine_asym`, so passing `refine_asym=False` to `RecipeRunner`
  still refined the asymmetry term (Rwp identical to the flag being on). The
  field is now **tri-state**: `None` (default — reproduces the old numerical
  path bit-for-bit), `True` (force on), `False` (force off). CLI gains
  `--no-refine-asym`.
- **K30 fixed — `refine_eta` was a dead parameter on the anisotropy path.**
  When Popa LB anisotropy is active, `forward._accumulate_peaks()` took η from
  `tch_eta()` and ignored `ProfileParams.eta`, yet the `profile` recipe step
  still refined it (sweeping η 0→1 changed Rwp by exactly 0 pt; all 7
  benchmark samples run 100% through that TCH branch, and the GUI ships with
  `aniso_auto` enabled, so the dead parameter sat on the product default
  path). `nonlinear.eta_is_active()` now probes the cached peak list at
  `refine()` entry and clears `refine_eta` when no scalar-branch peak exists.
  The computed pattern, Rwp and every refined parameter are **bit-identical on
  all 7 samples**; only `n_params` drops by one, which corrects `Rexp`
  (previously low by 0.0007–0.0015).

## Honest benchmark notes (sample 7)

All of the following experiments were **negative** and are documented for
transparency rather than shipped as wins:

- Adding the amorphous hump at its known 22°/9° position: **+0.109 pt** Rwp
  with QPA drifting 2.7 vol% → not adopted as a benchmark improvement.
- A two-component "sharp core + broad wing" profile adds no expressive power
  beyond a single pseudo-Voigt using only existing knobs (global FWHM ×0.85
  plus η +0.3 reaches −1.379 pt). Rejected.
- `ka_ratio` scans top out at −0.142 pt (at 0.6); locking QPA retains 98% of
  the dual-shape gain — so neither the Kα doublet nor phase-scale freedom is
  the bottleneck.
- Fixed-QPA + peak-shape check: free QPA **13.2234%** → fixed QPA
  **14.9871%** (constraint costs **+1.7637 pt**) → fixed QPA + η +0.2
  **13.9907%** (shape gains **−0.9964 pt**). Net **+0.7673 pt → fails**.
  QPA freedom (1.76 pt) is worth more than any profile knob can return, so
  this family is **structurally** unviable while phase fractions stay free.
  The remaining explanation for sample 7 is the **structural model** (the
  bundled fluorite reference is an ideal CaF₂ CIF while the literature phase is
  an anion-excess defect structure) — an **input-data** problem, not an engine
  problem.

## Quality

- Test suite: **596 passed / 0 failed / 0 skipped**.
- Cross-checked against MAUD on 7 real samples; mean Rwp **11.030%** vs MAUD
  **11.203%**, every sample within tolerance.

## Download

- `XinRefinement-1.7.0-setup.exe` — Windows x64 installer (zh/en/ja).

## Upgrade notes

- Registration: the production registration key is embedded in the release
  build, so previously issued registration codes remain valid.
- Only the installer is published; portable / internal evaluation builds are
  not released.
