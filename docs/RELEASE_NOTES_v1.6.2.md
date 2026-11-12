# XinRefinement v1.6.2 — Stop button now actually stops

> Baseline `v1.6.1` | Theme: **"Stop" taking effect only after the current step finishes is an
> implementation defect**. After starting run-all, pressing Stop meant waiting a long time —
> not because the computation is slow, but because the cancel flag was only checked between
> steps, so all the fitting rounds inside one step ran to completion before returning to the
> top of the loop.
>
> **Zero numerical change**: the golden 50/50 case is still `3.4074156640940005`, CLI/API
> bit-for-bit unchanged.

## Download

| File | Size | SHA256 |
|---|---|---|
| `XinRefinement-1.6.2-setup.exe` | 75.9 MB | `135cb1e87cf47522c25ba903f28cee244d83d8043b760ba13f6f6ee214c93b2f` |

> Release installer (includes registration, zh/en/ja installer UI). The internal evaluation
> portable build (`XinRefinement-internal-1.6.2-portable.zip`, 114.2 MB,
> sha256 `c51f786881c1ed8d965b27b31c9d406e2b51a648f6246a45a84f3f09e2abced1`)
> is for internal acceptance only and is not distributed with this Release.

## What changed at a glance

| | v1.6.1 | v1.6.2 |
|---|---|---|
| Pressing Stop | Waits for the whole current step (cell step measured **19.8 s**) | Interrupts at the next residual evaluation (**16 ms** scale) |
| How cancel was recorded | Could produce a "some step failed" record + a spurious warning box | Cancel is passed through, the log writes "refinement stopped by user", **no failure record left** |
| Progress bar | Stuck at "running microstructure…" | Changes to "stopped" |
| Already computed results | Discarded | **Partial results still filled in** (pattern, Rwp, all result pages) |

## Why it was slow (root cause)

The loop in `RefineWorker.run()` is:

```python
for step in todo:
    if self._cancel:        # ← the only place that checks the stop flag
        break
    result, rec = self._runner.run_step(step, ...)
```

So the moment Stop takes effect = the moment the current step finishes, and a step often
performs more than one fit internally:

| Step | What actually happens inside |
|---|---|
| Unit cell parameters | solve → refine the full cell → solve again with the new cell (3 fits) |
| Microstructure | PO trial (one short fit per phase × per candidate axis) → formal solve → re-solve |
| Peak shape parameters | Up to 4 LM runs (Rwp>10% always triggers the restart chain) |

More importantly: the engine **already had** a fine-grained hook,
`RefineConfig.cancel_cb` + `_check_cancel()` (placed at the residual function entry, covering
both the in-house LM and the scipy backends), but the GUI never wired it up — only one test
anywhere in the repository used it, making it dead code.

## What changed

### 1. Cancel hook wired into three residual closures

- **Main solve**: already had it.
- **Cell engine `refine_cell_full`**: **an independent residual closure with no check at all before** —
  the cell step is one of the slowest in the whole chain, the place that most needed it was the slowest.
- **Coordinate engine `refine_sites`**: the numerical Jacobian performs O(n_free) evaluations of
  "multi-phase whole pattern + linear layer" per iteration, so the xyz step can now also stop within a second.

### 2. The recipe layer no longer records "cancel" as "failed"

Every engine call in the recipe is wrapped in `except Exception → StepRecord("failed")` — correct
for genuine numerical failures (continue with the next step), but wrong for a user cancel. The
7 fallbacks now re-raise `RefineCancelled` first; `run_all` catches it within a step and
**returns the part already completed** (the run-all semantics are "stop at the last completed
step", not throwing the exception at the caller).

### 3. UI wrap-up

- The cancel callback is attached to `inputs.config` and carried automatically into every step
  config through `replace()` in `config_for`.
- After cancelling: the progress bar shows "stopped", the log appends
  "=== refinement stopped by user (current step interrupted at residual evaluation) ===",
  the partial results already computed are filled in as usual (pattern + Rwp + all result
  pages), and **no failure warning box is shown**.

## Verification

- Full regression **532 items: 532 passed / 0 failed / 0 skipped, EXIT=0**
  (527 in v1.6.1; adds 5 in `tests/test_v162_cancel.py`).
- golden CLI Rwp 50/50 case **`3.4074156640940005`** unchanged (with `cancel_cb=None` the
  engine is bit-for-bit unchanged, guarded by a dedicated test).
- Behaviour guarded by the new tests: cancel stops at the Nth residual evaluation
  (`calls == 3`), stop latency < 0.5 s, bit-for-bit identical Rwp with no callback, the cell
  engine takes effect independently, and no spurious `status='failed'` record is left after
  cancelling a run-all.
- Also fixes an existing assertion that "happened to hold": `test_serialize_uses_relative_paths`
  asserted "same drive → relative path", but `_rel()` has prefix semantics via `relative_to`,
  and it only passed because pytest's tmp happened to be on C: and the project on D:. It now
  checks the real contract.

## Build and reproducibility

This version performed a reproducibility audit of the build chain; the conclusion has two layers:

- **PyInstaller artifacts (the `.exe` layer) are byte-for-byte reproducible**: with a fixed
  `SOURCE_DATE_EPOCH` (taken from the git commit time) and `PYTHONHASHSEED=0`, two builds of the
  same commit produce exactly the same `XinRefinement.exe` / `XinRefinementCLI.exe` hashes
  (measured twice, including with a different `--distpath`). The source version can therefore be
  traced back from the artifact.
- **The installer (Inno Setup layer) is not byte-for-byte reproducible**: the same input and the
  same `SOURCE_DATE_EPOCH` produce **the same size but different bytes** across two packagings
  (the PE header timestamp comes from the compiler stub and is not affected by epoch). The
  SHA256 in the table above is therefore valid only for **this one asset of this Release**, and
  does not mean "anyone rebuilding gets the same hash string"; a rebuild from the same source
  produces a different installer hash, though the two `.exe` files inside can be matched
  byte-for-byte.
- **One process constraint**: `SOURCE_DATE_EPOCH` takes the HEAD commit time at build time, so
  **you must commit first and build afterwards**. If you build before committing, the PE
  timestamp in the artifact points at the previous commit — the content is unaffected, but the
  source version cannot be inferred from the artifact and rebuild hashes will not match.
- **How this asset was actually built**: after `06b115c` (the release commit that tag `v1.6.2`
  points to), with `SOURCE_DATE_EPOCH=1794219055` fixed to that commit's commit time; the
  artifact contains `XinRefinement.exe` = `2b2436de…`, `XinRefinementCLI.exe` = `16c99cb3…`,
  both byte-for-byte reproducible from the same source.

## Known limits

- Stopping is **cooperative**: the engine checks the flag at residual evaluation, so the
  **single** evaluation in progress will finish (about 16 ms for sample 1; correspondingly
  longer with more phases and points). There is no thread kill — that would leave numpy/BLAS
  internal state and temporary caches unreclaimable.
- **Sample 7 is still below standard** (+3.39 pt, the near-amorphous broad-envelope starting
  point of cristobalite); this version does not touch the engine.

## Installation and registration

Same as v1.6.1: the installer has a built-in zh/en/ja interface, registration codes
interoperate across the XinMatch family
(`%APPDATA%\PolyXRD\Registration\XinRefinement.json`). The internal evaluation build needs
no registration and no installation, and is marked in red in the status bar.

## License

This software uses the MIT license (`LICENSE` / `LICENSE-CN`, full text viewable from the Help
menu). The bundled crystal structure data comes from COD (CC0) and ICSD-derived public
literature, and **contains no PDF cards or ICDD data**.
