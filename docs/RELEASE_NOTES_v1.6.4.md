# XinRefinement v1.6.4 — Audit remediation batch 3 (robustness + read performance)

> Baseline `v1.6.3` | Theme: the five findings from the 2026-11-11 global audit that
> could be fixed without touching any numerical path — bounded recycling of the
> project extraction directory, no more silent loss of a corrupt embedded result,
> pattern loading reduced from 2–3 reads to 1, repeated e.s.d. evaluation collapsed
> into one call, and stale step records no longer accumulating on a reused runner.
>
> **Zero numerical change**: engine and numerical paths untouched; the golden 50/50
> case is still `3.4074156640940005`, CLI/API bit-for-bit unchanged.

## Download

| File | Size | SHA256 |
|---|---|---|
| `XinRefinement-1.6.4-setup.exe` | 75.3 MB | `258afa309558adfc18ca4a9bed3193213c2982b56006460291fae0a6f5b90701` |

> Release installer (offline registration, zh/en/ja installer UI).
> The internal portable build is for internal acceptance only and is not published.

## What changed at a glance

| | v1.6.3 | v1.6.4 |
|---|---|---|
| Temp directory | one new directory per project revision under `%TEMP%\xinrefinement_projects`, **never cleaned up** | bounded recycling: keep the newest 8 / 7 days / 512 MB; the directory currently in use is never removed |
| Corrupt embedded result | result panel silently went blank | status bar reports "result/refine.json could not be parsed and was ignored" |
| Opening a large pattern | the same file was read 2–3 times | read **once** (Shimadzu `.txt` 5 → 1, FullProf `.dat` 3 → 1) |
| Save project / export report | each recomputed e.s.d. (≈4p full-profile evaluations each, on the main thread) | computed once per refinement; failures are cached too |
| Reusing one runner | `state.records` accumulated, record count doubled | cleared before the run, record count equals the step count |

## Details

### A07 · Bounded recycling of the `.xinr` extraction directory
Extraction directories are still named `<stem>_<mtime>` and still reused for the same
mtime; recycling runs after each extraction with three limits: newest 8 entries,
7 days, 512 MB total for the set. **`protect` (the directory in use) is the only
absolute guarantee**; `keep` is a count threshold only, so an entry inside the newest
8 but older than 7 days is still removed. Every `OSError` during cleanup is swallowed —
cleanup is a side job and must never break opening a project. A recycled project is
simply extracted again the next time it is opened (expected behaviour).

### A08 · A corrupt `result/refine.json` is no longer silent
`load_project()` now returns a `warnings` list (the legacy `.xrp` path exposes the same
key with an empty list), and `apply_project()` appends each warning to the status bar
instead of showing a modal dialog. The caught exception set is still
`UnicodeDecodeError` / `JSONDecodeError` — it was not widened to `Exception`.

### B07 · Single-read loading for legacy text patterns
`.xy/.txt/.dat/.csv` used to be read 2–3 times (text decode, a 4096-byte header sniff,
then another full read inside the vendored reader). Now the raw bytes are read once and
threaded down through four **optional, defaulted** arguments — `head=` / `full_text=` /
`raw=` / `key=` — so default call behaviour is bit-identical. `Pattern.meta` keys and
values, and the type and text of every parse error, are unchanged (verified by running
the HEAD implementation side by side, not by letting the tests grade themselves).

### B02 · e.s.d. computed once instead of three times
`MainWindow._esd_for()` caches on `id(res)` + `rwp` + `iters` + `id(_phases)` + phase
names and cells. A failed `None` is cached as well — the failure path also costs 4p
full-profile evaluations, so retrying it is pointless. `new_project()` clears the cache.
The arguments and the numbers produced by `estimate_esd()` are untouched.

### records · `run_all()` clears `state.records` before running
Re-running a single `RecipeRunner` accumulated the previous run's `StepRecord`s
(record count doubled, rollback indices shifted). The list is now cleared in place, which
preserves the existing semantics of `run_all` returning the same list that `rollback()`
slices.

## Upgrade notes

- **Project files**: the `.xinr` format is unchanged; v1.6.3 projects open directly.
  `warnings` is a new key, and older versions simply ignore unknown keys.
- **Long-term use**: stale session directories under `%TEMP%\xinrefinement_projects`
  older than 7 days or beyond the newest 8 are removed automatically. Your `.xinr`
  files are never touched.
- **Known limits**: when two processes open projects at the same time, the recycling
  in process B may treat process A's session directory as "the 9th oldest" and remove
  it (`protect` is only effective within its own process); and re-saving a project does
  not carry over the `warnings` seen when it was opened (a warning is a fact about that
  particular load).

## Build and reproducibility

- Build environment: Python 3.10.11 + PyInstaller 6.22.3. `SOURCE_DATE_EPOCH` is taken
  from commit `7973d98` (`1794479509`).
- **The executables are reproducible**: same epoch, same source → `XinRefinement.exe`
  and `XinRefinementCLI.exe` are byte-identical across builds.
- **The installer is not reproducible**: ISCC honours `SOURCE_DATE_EPOCH` for embedded
  file times, but the PE header keeps the compiler stub timestamp, so two packagings of
  the same input have the same size and different bytes. **The published hash is
  therefore the hash of the uploaded artifact** — do not re-upload to chase the HEAD
  timestamp.
- The registration key is not in version control. Release builds inject it from
  `XR_REG_SECRET` or `xinrefinement/registration_secret.txt` (gitignored) so that
  previously issued registration codes keep validating; without a key the build falls
  back to the community placeholder, which is the path taken by source builds and the
  internal variant.

## Verify

```bash
sha256sum XinRefinement-1.6.4-setup.exe
# 258afa309558adfc18ca4a9bed3193213c2982b56006460291fae0a6f5b90701
```

Full regression: **579 passed / 0 failed / 0 skipped** (v1.6.3 baseline 553; this
release adds 26 cases).

> Note for developers: do not put pytest's `--basetemp` inside the repository working
> tree. `tmp_path` reuses and prunes numbered subdirectories, which in restricted
> environments can trip a bulk-delete guard and raise `SystemExit: 1` during fixture
> setup, showing up as a wall of bogus ERRORs. Use `--basetemp="$TEMP/xinr_..."`.
