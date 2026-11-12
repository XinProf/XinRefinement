# v1.0.0 local binary acceptance sheet (manual)

> Artifacts exist **locally only**: `dist/` is excluded by `.gitignore`, not committed, not
> uploaded, not published. Once everything is confirmed, you decide how to distribute.

## 1. Artifact list (two variants, following XinMatch)

| Variant | Artifact | Path | Notes |
|---|---|---|---|
| **Release** release | GUI / CLI | `dist/XinRefinement-1.0.0/XinRefinement.exe`, `…CLI.exe` | windowed + console, onedir |
| | Installer | `dist/installer/XinRefinement-1.0.0-setup.exe` | Inno Setup, zh/en/ja; **includes the PolyXRD-Reg registration mechanism** |
| **Internal evaluation** internal | GUI / CLI | `dist/XinRefinement-internal-1.0.0/XinRefinement.exe`, `…CLI.exe` | no registration, no installation |
| | Portable build | `dist/installer/XinRefinement-internal-1.0.0-portable.zip` | unzip and run; status bar shows "internal evaluation build" in red |

The variant is fixed by the bundled `variant.txt` (under `_internal/`) and read at runtime by
`xinrefinement.build_variant`; **a missing marker is treated as the release build** (fail-safe).

Rebuild: `python tools/build_binaries.py` (both variants take about 3.5 minutes) or a single
variant with `--variant release` / `--variant internal`.
The build script has reproducible settings built in (`SOURCE_DATE_EPOCH` = git HEAD commit time,
`PYTHONHASHSEED=0`), so consecutive builds of the same commit are **byte-for-byte identical**
(see §2.1); after building, the script prints the first 16 characters of each artifact's
SHA-256. Full verification:

```bash
sha256sum dist/XinRefinement-1.0.0/XinRefinement.exe \
          dist/XinRefinement-1.0.0/XinRefinementCLI.exe \
          dist/installer/XinRefinement-1.0.0-setup.exe \
          dist/installer/XinRefinement-internal-1.0.0-portable.zip
```

### 1.2 v1.0.0 release artifact hashes (measured on the final build)

| File | Size | SHA-256 |
|---|---|---|
| `XinRefinement-1.0.0/XinRefinement.exe` | 8.4 MB | `d452f324d8ffa1b62c2728e15de97a15a7254fcb16e354dca275f24227c5eb32` |
| `XinRefinement-1.0.0/XinRefinementCLI.exe` | 8.3 MB | `009236bd21789f3de9c21adaee4143b308c33a92ef6fa0d193fefef31b9d0916` |
| `installer/XinRefinement-1.0.0-setup.exe` | 67.6 MB | `410d74d9c35c8d8fc5e77bd3a42a443b4f5d7b9c653b3e7e1798136f031be54e` |
| `installer/XinRefinement-internal-1.0.0-portable.zip` | 113.9 MB | `3c2a3842a3c48f14a822326f4f30f56f2f5f9c7444656c6c9f19f299976340c4` |

The internal evaluation build's `XinRefinement.exe` / `XinRefinementCLI.exe` have **exactly the
same hashes** as the first two rows above: in onedir mode the variant is decided by
`_internal/variant.txt`, and the exe itself carries no variant difference.

### 1.1 Machine-readable self-check of the two variants (no need to drive the GUI)

```bat
set XINREFINEMENT_SELFTEST_REG_OUT=%TEMP%\reg.json
dist\XinRefinement-1.0.0\XinRefinement.exe
type %TEMP%\reg.json
:: release build → {"variant":"release","registration_enabled":true,"status_text":"未注册"}

dist\XinRefinement-internal-1.0.0\XinRefinement.exe
type %TEMP%\reg.json
:: internal build → {"variant":"internal","registration_enabled":false,"status_text":"内部评估版本"}
```

Registration status file: `%APPDATA%\PolyXRD\Registration\XinRefinement.json`
(the same family directory as XinMatch, registration codes interoperable).
Developer code generation: `python tools/make_reg_code.py "Organisation Department Name"`.

## 1.5 Source-mode pre-check (optional; run this first to rule out environment problems quickly)

`run_dev.bat` does not package or freeze anything; it runs directly from the working-tree
source, used to tell "code problems" apart from "packaging problems":

```bat
run_dev.bat                                    :: start the GUI (title should contain v1.0.0)
run_dev.bat --version                          :: should print XinRefinement 1.0.0
run_dev.bat refine tests\data\virtual_b\v50_wide.xy ^
    xinrefinement\data\anatase.cif xinrefinement\data\rutile.cif ^
    --peak-height -o out.json                  :: Rwp should be 3.409617
run_dev.bat refine <pattern> <phase.cif...> --recipe --report out_dir --esd
```

The interpreter is chosen automatically in this order (first hit wins):
`%XINREFINEMENT_DEV_PYTHON%` → `.venv\Scripts\python.exe` → `venv\Scripts\python.exe` →
`D:\Project\XRD\python310\python.exe` → `python` on PATH.
To change interpreters just set the environment variable:
`set XINREFINEMENT_DEV_PYTHON=D:\path\to\python.exe`.

If source mode passes but the exe fails → the problem is in packaging (missing hiddenimport /
data file); if both fail → the problem is in the code or the data.

## 2. Six-round robustness acceptance (suggested order)

| Round | Action | Pass criterion |
|---|---|---|
| 1 · Hash consistency | Build twice consecutively, compare the SHA-256 of the four artifacts | GUI/CLI **byte-for-byte identical** across the two builds (see §2.1; installer/zip may differ because of embedded timestamps); a mismatch means a non-determinism source must be investigated |
| 2 · CLI cold start | Double-click or `XinRefinementCLI.exe --version` | Prints `XinRefinement 1.0.0`, no missing-DLL error |
| 3 · CLI end to end | `XinRefinementCLI.exe refine <pattern.xy> <phase.cif> -o out.json` | JSON contains `r_factors`/`phases`; Rwp matches the source run (v50 two-phase = 3.409617) |
| 4 · GUI double-click smoke | Double-click `XinRefinement.exe` | Main window appears (title contains 1.0.0); import pattern + CIF → ▶ refine → pattern and result tables refresh; switching language (Settings→Language) changes the text immediately |
| 5 · Install/uninstall | Double-click the installer → choose Simplified Chinese → install to the default directory → launch → uninstall | Installer UI is Chinese; Start menu has both GUI and CLI entries; the directory is empty after uninstall |
| 6 · Variant difference | Run the two self-checks from §1.1 separately; then double-click both GUIs and look at the right end of the status bar | Release: Help menu has "Enter registration code…", status bar shows "not registered" → after entering a code it becomes "registered: organisation name"; internal: no registration menu, status bar shows "internal evaluation build" in red |

### 2.1 Round 1 supplement: reproducible build (already built into the script)

PyInstaller is **not reproducible** by default; measurement found two sources of
non-determinism, both handled in `tools/build_binaries.py`:

| Source | Symptom | Handling |
|---|---|---|
| PE header `TimeDateStamp` | Written with the build time; 4 bytes differ across two builds of 8 MB | Set `SOURCE_DATE_EPOCH` (supported by PyInstaller 6), value = git HEAD commit time `%ct` |
| Hash randomization of string sets | The marshal byte stream inside PYZ varies per process, compressed length jitters (measured 17 bytes difference between two builds) | Set `PYTHONHASHSEED=0` |

After these fixes, two consecutive builds on **the same commit** produce four byte-for-byte
identical exes (verified).
The installer and the portable zip still vary: Inno Setup has no `SOURCE_DATE_EPOCH` support and
`zipfile` writes file mtimes, so the two are only accepted for "functional consistency" and do
not take part in hash comparison.

## 3. Known notes

- The release build shows a "not registered; all rights reserved; commercial use prohibited"
  prompt on first launch (OK = continue using / enter registration code = complete
  registration); it is suppressed when running offscreen or with `POLYXRD_REG_NO_PROMPT=1`
  (automation-friendly).
- The registration code uses offline HMAC verification (the key ships with the software,
  obfuscation level); the same code can be used on multiple machines within the same
  organisation, with no machine binding.
- The internal evaluation build is a **portable zip** with no installer; if an internal
  installer is needed, the Inno configuration can be extended with an `--variant internal`
  AppId.
- No code signing: on first run Windows SmartScreen may warn of an "unknown publisher"; choose
  "Run anyway".
- The installer is 67.6 MB (including matplotlib/Qt runtimes), which is within the normal range.
- GUI first launch is about 2–4 s (onedir cold start, PyInstaller unpacking dependencies).
- Trilingual installation: the Simplified Chinese language file comes from a community
  translation (`packaging/inno/ChineseSimplified.isl`, not bundled with Inno Setup itself);
  English/Japanese use Inno's bundled language packs.

## 4. Acceptance record

The automatable part (rounds 1–3 and 6, plus the silent install of round 5) all passed on
2026-11-05; round 4, which involves GUI interaction, and "double-click the installer to see the
Chinese UI" still need manual confirmation.

| Round | Result | Notes |
|---|---|---|
| 1 · Hashes | ✅ automated | After fixing the two non-determinism sources (PE timestamp / hash randomization), two consecutive builds of the same commit give four byte-for-byte identical exes; `dist` measured `XinRefinement.exe = d452f324…`, `XinRefinementCLI.exe = 009236bd…` |
| 2 · CLI cold start | ✅ automated | Both variants print `XinRefinement 1.0.0`, no missing DLL |
| 3 · CLI end to end | ✅ automated | Both variants `rwp = 3.409617`, `chi2 = 1.205705`, 2 phases, `success = true`, bit-for-bit identical to source/golden |
| 4 · GUI smoke | 🟡 semi-automated | Offscreen launch + self-test JSON pass (window can be created, menus/icons/canvas load); **the real double-click still needs human visual check** |
| 5 · Install/uninstall | ✅ semi-automated | Silent install 534 files / 263 MB → installed `--version` normal → after writing a registration code the self-check reads `registered: acceptance test organisation` → uninstall leaves 0 residue and removes the registry entries; the Chinese installer UI needs human visual check |
| 6 · Variant difference | ✅ automated | Release `{release, registration_enabled: true, 未注册}`; internal `{internal, registration_enabled: false, 内部评估版本}`; setting `XINREFINEMENT_VARIANT=internal` on the release build still reports release (anti-bypass) |

> Note: in onedir mode the single-file exe **carries no variant difference** (the variant is
> decided by `_internal/variant.txt`), so the release and internal `XinRefinement.exe` having
> the same hash is expected and not a packaging error.
