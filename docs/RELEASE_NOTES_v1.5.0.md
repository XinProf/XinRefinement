# XinRefinement v1.5.0 — MAUD-class fit quality

> Baseline `v1.4.0` | Theme: turn "benchmarked against MAUD" from an assessment conclusion
> into a **product capability**, and trace the remaining gap on each of the 7 real samples
> to its root cause. This version adds no new UI module; it changes the **default behaviour
> and guardrails of the fitting engine** — same data, same set of CIFs, lower Rwp, and lower
> for a physical reason.

## Download

| File | Size | SHA256 |
|---|---|---|
| `XinRefinement-1.5.0-setup.exe` | 75.8 MB | `429adb70eaa8df4754c9607ecdc9826f641582ace798f3ae9c7575e1e07ffdc0` |

> Release installer (includes registration, zh/en/ja installer UI). The internal evaluation
> portable build is for internal acceptance only and is not distributed with this Release.

## What changed at a glance

| | v1.4.0 | v1.5.0 |
|---|---|---|
| Mean Rwp over 7 samples | 14.38% | **11.42%** (MAUD 11.20%, gap 3.18 → **0.21 pt**) |
| Microstructure anisotropy | Coefficients had to be written by hand per phase | Automatically enabled by GUI factory default + two guardrails |
| Texture | EWIMV discrete ODF | Also **spherical-harmonic (Legendre) ODF**, GUI factory default |
| xyz underdetermined | Whole step judged failed (not one coordinate refined across 4 samples) | **Per-phase degradation**, only takes effect when over budget |
| Long sample runtime | Unbounded (pathological sample >1 h) | Recipe wall-clock budget, GUI default 45 min |
| Pure corundum standard | 28.58% | **13.64%** (beats GSAS-II's 15.8%) |
| Polymorph mismatch | Only a warning in the log | Result panel offers a **clickable button** "Try α-cristobalite and refine again" |

## Main changes

### Engine: three "false minimum" fixes (largest gain of this version)

1. **M10/M10b step-wise projection**: the `cell` and `profile` steps froze each other's
   degrees of freedom, so the zero-point offset had nowhere to go and was absorbed
   separately by the unit cell and the asymmetry. The `profile` step now performs a
   **joint refinement** (cell+UVW+η+asym+zero), taking single-phase pure corundum from
   **28.58% → 14.63%**. At the same time the "revert if not improved" behaviour of the
   `micro`/`B` steps is now **unconditional**.
2. **M11 window-boundary peak leakage**: reflection enumeration was filtered strictly by
   window, so a strong peak just outside the window was dropped entirely even though its
   tail inside the window should contribute intensity (measured: the 140–150° segment
   accounted for 18.8% of the whole-pattern weighted residual). Extending enumeration by
   3° takes pure corundum from **14.63% → 13.64%**. This is a general systematic-bias fix.
3. **Structure-factor vectorization**: three vectorizations in `compute_peaks`, **26–37×**
   faster with bit-for-bit equivalent numbers (guardrail `tests/test_peaks_vectorized.py`).

### Microstructure: M4 Popa LB per-phase anisotropy (on by GUI factory default)

Per-phase size/strain anisotropic broadening. In the 7-sample comparison sample 1 gains
−3.49 pt and sample 7 −3.81 pt, the largest single gain in v1.5. **Being on by default must
come with two guardrails**:

- **Identifiability**: phases with fewer than 8 independent crystallographic directions are skipped automatically (otherwise the 6 parameters cannot be identified);
- **Revert as a whole if not improved**: if Rwp does not drop after stacking, revert to the previous step's parameters.

CLI / library API still default to off (`--aniso-auto` enables it explicitly), keeping the
results of existing scripts bit-for-bit unchanged.

### Texture: M3 spherical-harmonic ODF (GUI factory default, degree 10)

Under fibre symmetry the **exact subspace** of the spherical harmonics is
`T(χ)=1+Σ c_l·P_l(cosχ)`, even orders 2–10. Compared with EWIMV this is 4–15 fewer degrees
of freedom at the same accuracy, the basis is orthogonal, and the spherical average is
always 1 (structurally eliminates the scale null space), so no second-difference penalty is
needed. CLI `--texture-model harmonic --texture-degree N`.

> The measured conclusion has been written into the project proposal: **the degree matters
> more than the model family**, and part of EWIMV's Rwp advantage comes from overfitting
> (sample 3's T(χ) fitted into a near-binary mask). "Copying MAUD's per-phase Harmonic
> switch" was falsified by the phase-supplement experiment and was not productized.

### Quantification: M9 per-phase degradation of the xyz step

v1.4 summed the free coordinates of **all phases** and compared against
`xyz_max_params=40`, so the xyz step of samples 4/5/6/7 all ended up `failed` — not one
coordinate was refined, and two of them were the samples with the largest gap. Now it
degrades **per phase** (descending greedy retention, remaining phases switched to fixed
structure), only taking effect when over budget:

| Sample | Before degradation | After degradation |
|---|---:|---:|
| 5 | 17.204 | **16.026** |
| 6 | 12.603 | **12.207** |
| 7 | 17.193 | 16.930 |

### Diagnosis: sample 7's gap is a **cristobalite polymorph**, not peak shape or background

Sample 7's cristobalite was given as the high-temperature β form (Fd-3m) while the sample is
actually the low-temperature α form (P4₁2₁2): incremental metric 18.06 → 15.59, end-to-end
17.193 → 15.357, and this phase's `ΔB_iso` hitting the 6 Å² upper bound **disappears** (the
overfitting signal is gone).

On the product side it **only suggests, never changes automatically**: triggered when three
conditions hold simultaneously (ΔB_iso at the upper bound + identical normalized formula +
space group equal to the baseline polymorph), the result panel then shows the button "Try
α-cristobalite and refine again". The structural model is an experimental fact
(synthesis temperature, phase-transition history); the software has no right to decide it
for the user.

### External validation: IUCr CPD quantification round-robin

The 7 ShiJiKong samples served both as tuning targets and as acceptance targets, which is
not enough to prove generalization. This version takes in the IUCr CPD standard set (each
point has a weighed true value plus XRF verification):

- Sample 1 **closes all eight points**, average `max|Δ|` **2.84 pt** on the `combo` metric, the same order as the round-robin participants' standard deviation (2.4–2.7 pt); 1a/1b clearly better than the community level.
- Sample 2 (preferred orientation) **31.21 → 15.05**, entirely thanks to Popa LB.
- Sample 3 (29.5% amorphous) 12.42%, note that **reports on such samples must first state the normalization basis**.
- Sample 4 (micro-absorption) is the boundary of our capability, stated as it is: the Brindley factor is strictly degenerate with each phase's scale (adding the correction changes Rwp by only 1e-12); it can only redistribute the wt% normalization, it cannot change the fit.

## Validation data (7-sample acceptance)

> Metric exactly as in the project proposal §1.7 (tent 19 nodes, per-phase ΔB_iso, xyz,
> EWIMV texture, Popa LB, 5–120° with 10–100° for sample 5). **The same string of numbers
> was reproduced repeatedly during v1.5**, hard evidence of "zero regression on the default
> path".

| Sample | MAUD 2.99993 | v1.5.0 | Gap | Verdict (`≤ MAUD+2`) | Runtime |
|---|---:|---:|---:|:---:|---:|
| 1 | 10.90 | 11.880 | +0.98 | ✅ PASS | 34.2 min |
| 2 | 6.34 | 6.968 | +0.63 | ✅ PASS | 2.2 min |
| 3 | 10.29 | **8.123** | **−2.17** | ✅ PASS (beats MAUD) | 5.2 min |
| 4 | 9.96 | 10.263 | +0.30 | ✅ PASS | 77.5 min |
| 5 | 14.87 | 15.865 | +1.00 | ✅ PASS | 35.7 min |
| 6 | 14.76 | **12.122** | **−2.64** | ✅ PASS (beats MAUD) | 41.4 min |
| 7 | 11.30 | 14.689 | **+3.39** | ❌ **FAIL** | 49.7 min |
| **Mean** | **11.20** | **11.42** | **+0.21** | **6/7 PASS** | 245.9 min |

How to read it:

- **6 of the 7 samples reproduce to 3 decimal places** (only sample 5 is the exception, see below), showing that the v1.5 default path never drifted during development of this version — the hardest evidence of "zero regression", not a self-assessment.
- **Sample 7 is the only item below standard, +3.39 pt**. Its root cause is already identified (cristobalite given as high-temperature β while the sample is low-temperature α), but the product **does not change the user's CIF automatically**; after manual replacement this project measures 14.031 (−0.66 pt), still above MAUD's 11.30 — MAUD treats this phase as a near-amorphous broad envelope (size 27 Å / strain 0.0164), our Popa LB start is 58× away from it, and the numerical Jacobian cannot get there. **This is a known hard problem, stated as it is, not glossed over.**
- **Sample 4 is the slow one at 77.5 min** (5 phases, 40 free coordinates × numerical Jacobian); this run's 10.2634 agrees with §1.7's 10.263; the runtime upper bound is covered under "Known limits".
- **Sample 5's 15.865 is 0.077 lower than §1.7's 15.942**: M9 per-phase degradation lets its xyz step actually run (4 phases / 36 free coefficients), the subsequent micro/B steps absorb most of it, net gain −0.077. **It is a recorded change, not drift.**
- Excluding sample 7, the mean of the other 6 samples is **10.87%**, already better than MAUD's 11.20% — but that number should not be used for promotion; sample 7 is precisely the problem we have not solved.


## Known limits

- **Sample 4's xyz degradation path is slow** (40 free coordinates × numerical Jacobian). The GUI has a 45 min
  wall-clock budget as a backstop, the command line is unbounded by default; batch scripts should pass `--time-budget-min` themselves.
- **Quantification (QPA) and Rwp are decoupled**: 1b measures Rwp 29.99% while the wt% error is only 0.22 pt.
  For acceptance of quantification look at wt%, not Rwp.
- **Densifying background nodes is not free**: the full 7-sample judgement shows 2.5°/node can pull the mean to 10.90
  (literally beating MAUD), but QPA collapses (sample 4 quartz −7.6 vol%). The interface already allows up to 60 nodes,
  but **do not exceed 1 node/4° when QPA is the goal**.
- **Two things that "looked promising but measured otherwise" are switched off as negative results**: per-atom B_iso
  (+`equalTo` grouping) gives at most 0.0025 pt gain across 90 scan points over ten phases of samples 1/7;
  aligning LM damping to MAUD's λ=0.01 gives a 0.042 pt spread across three levels and is non-monotonic. The knobs are kept, defaults untouched.

## Installation and registration

Same as v1.0.0: the installer has a built-in zh/en/ja interface, registration codes
interoperate across the XinMatch family
(`%APPDATA%\PolyXRD\Registration\XinRefinement.json`). The internal evaluation build needs
no registration and no installation, and is marked in red in the status bar.

## License

This software uses the MIT license. The bundled crystal structure data comes from COD (CC0)
and ICSD-derived public literature, and **contains no PDF cards or ICDD data**.
