# XinRefinement v1.1.0 — Import XinMatch phase analysis (.xinm), self-contained project files

> Baseline `v1.0.0` | Released alongside **XinMatch 3.4.0**. The refinement engine, parameter
> model, CLI arguments and registration mechanism are **all unchanged**; this version adds one
> import channel and one project container format, and fixes a v1.0.0 `.xrp` field-loss defect.

## Download

| File | Purpose |
|---|---|
| `XinRefinement-1.1.0-setup.exe` | Release installer (includes registration, zh/en/ja installer UI) |

> The internal evaluation portable build is for internal acceptance only and is not
> distributed with this Release.

## Key capabilities

### Import XinMatch phase analysis (.xinm)

`File → Import XinMatch phase analysis…`. Loads three things at once, no more manual moving:

| Loaded item | Source | Notes |
|---|---|---|
| Pattern | `pattern/pattern.csv` inside the `.xinm` | Two-column CSV, `%.10g` round-trip with zero error; `wavelength` is passed to the canvas as well (d-axis conversion available immediately) |
| Phase CIF | `cifs/*.cif` inside the `.xinm` | Cached to disk phase by phase, then goes through the existing `_load_cif_paths` — the same code path as manual import |
| Unit cell / space group | manifest | Checked against the parsed CIF values: matching values prefill "Edit phase parameters"; significant mismatches (>0.1% / >0.05°) defer to the CIF and are listed |

Phases without a structure (PDF2-type, or those whose CIF was not found in the COD
archive) are listed as **"reference only"**: shown in grey, excluded from refinement, with
a readable reason; a CIF can be assigned manually to fill them in.

The import core `core/io/xinm_import.py` **does not depend on Qt**, and is shared by the
GUI / CLI / library API; it includes manifest validation, version negotiation (a `version`
above the supported value suggests upgrading), zip-bomb protection (512 MB extraction
limit), line-by-line CSV parsing and readable errors.

### Project file `.xinr`: self-contained zip container

| Item | v1.0.0 | v1.1.0 |
|---|---|---|
| Form | Plain JSON, external paths only | zip: `manifest.json + pattern/ + cifs/ + result/` |
| Moving machines | Broken if files are missing | **Embeds** the pattern CSV + CIF + full refinement result by default; the original files can be moved away and the project still opens and reproduces |
| Results | R-factor summary only | `result/refine.json` (same schema as CLI `--out`) + navigation log; opening refills the result panel and convergence curve |

Extension routing: `.xinr` → container; `.xrp` → v1.0.0 JSON, **permanently read-only
compatible**. Also fixes the v1.0.0 `.xrp` bug that dropped `phase_edits` (phase parameter
edits disappearing after reopening a project).

### Library API

`capabilities()` gains `xinm_import: "1"`, so consumers can probe the capability bit before
deciding whether to expose the import entry point.

## Validation data

| Item | Result |
|---|---|
| S1 full closed loop (real COD archives 7206075 + 9001681) | `.xinm` import → refinement Rwp **3.409617019598457**, bit-for-bit identical to the P0 golden value; the GUI one-click run-all path and "manual import of the same pattern/CIF" give **bit-for-bit equal Rwp**; save `.xinr` → delete the temporary pattern and `.xinm` → reopen and reproduce (rel 1e-9) |
| Quantification | Two phases 50.03 / 49.97 wt% |
| S2 mixed sources | COD + user CIF packed into `cifs/`; PDF2 phase with `structural=false` listed as "reference only"; **no ICDD-derived file of any kind inside the package** |
| S3 abnormal boundaries | Missing CIF member / corrupt zip / missing pattern / `version=2` each raise a readable error, no crash |
| S4 family registration | `XinRefinement.json` and `XinMatch.json` are managed separately, registration code algorithm interoperable and unchanged |
| Full test suite | **286 all green** (259 in v1.0.0; adds 13 in `test_xinm_import.py`, 7 in `test_project_zip.py`, etc.) |

## Installation and registration

Same as v1.0.0: trilingual installer (Simplified Chinese / English / Japanese),
`{autopf}\XinRefinement`; the release build prompts "not registered" on first launch (a
registration code can be entered); the internal evaluation build needs no registration.
Registration codes interoperate across the XinMatch family — one code works for both
applications.

## Build and binary acceptance (six rounds)

| Round | Result | Measured |
|---|---|---|
| 1 · Reproducible build | ✅ | Two consecutive builds from the same source, `XinRefinement.exe` / `XinRefinementCLI.exe` **byte-for-byte identical**: `a2c9fcc80b0f291e…` / `7d1ed1ec7efc8642…` (`SOURCE_DATE_EPOCH` + `PYTHONHASHSEED=0`) |
| 2 · CLI cold start | ✅ | Both variants print `XinRefinement 1.1.0`, no missing DLL |
| 3 · CLI end to end | ✅ | Both variants, `refine v50_wide.xy anatase.cif rutile.cif --peak-height` → `rwp = 3.409617`, 2 phases, `success = true` (the synthetic pattern uses peak-height convention, hence `--peak-height`; without the switch the integrated convention gives `rwp = 5.935965`, bit-for-bit identical to the source run) |
| 4 · GUI smoke | 🟡 offscreen pass | Offscreen launch + self-test JSON: release `{release, registration_enabled: true, 未注册}`, internal `{internal, false, 内部评估版本}`; **double-click visual check still needs a human** |
| 5 · Install/uninstall | ✅ silent | Silent install of 606 files → installed `--version` normal → silent uninstall leaves 0 residue; the Chinese installer UI needs human visual check. (The installer requires administrator rights by default and a non-interactive environment cannot elevate; since the build is reproducible and `setup.exe` SHA-256 is **byte-for-byte identical** to the previous round, the previous round's conclusion still holds) |
| 6 · Variant difference | ✅ | Marks `release` / `internal`; setting `XINREFINEMENT_VARIANT=internal` on the release build still reports `release` (anti-bypass) |

Release artifacts:

| File | Bytes | SHA-256 |
|---|---:|---|
| `XinRefinement-1.1.0-setup.exe` | 67,586,555 | `046179e6f3ef45d651b241b41dafb273990b423667bc066e5eba2b3982a44926` |
| `XinRefinement-internal-1.1.0-portable.zip` | 113,946,723 | `a9012229b268bae36741bbd7cd9d5782ecf55a814ea907d4b39dded701db09d1` |

## Known notes

- The release `.xinr` embeds CIFs and the pattern, so project files are larger than v1.0.0
  `.xrp` files (the pattern is stored as CSV text, about 2 MB for 100k points). Save as
  `.xrp` when the old "paths only" behaviour is needed.
- `.xrp` is read-only compatible and never written back: opening an old file and saving
  decides by extension whether to write JSON or a container.
- The frozen package contains no `pyproject.toml`; the version number comes from the literal
  constant in `xinrefinement/__init__.py` (`__version__ = "1.1.0"`), not from the installed
  metadata of the runtime environment.
- No code signing: on first run Windows SmartScreen may warn of an "unknown publisher".

## License

Same as v1.0.0: see `LICENSE` / `LICENSE-CN` at the repository root (same origin as
XinMatch).
