# XinRefinement

<p align="center">
  <img src="assets/icons/logo_512.png" width="180" alt="XinRefinement logo">
</p>

**General-purpose desktop software for whole-pattern fitting of powder diffraction data — Rietveld structural refinement / Le Bail / profile fitting.**

[简体中文](README-CN.md) · English

## Current version: v1.7.0

| | |
|---|---|
| **Download** | [`XinRefinement-1.7.0-setup.exe`](https://github.com/XinProf/XinRefinement/releases/tag/v1.7.0) — Windows x64, zh/en/ja installer |
| **Release notes** | [v1.7.0 — Amorphous hump component + recipe-path fixes](https://github.com/XinProf/XinRefinement/releases/tag/v1.7.0) |
| **Changelog** | [CHANGELOG.md](CHANGELOG.md) |
| **SHA256** | `044641c5c0a48c307a7fe83dad52ff4459c990f0635d8f2a643846d06fdcb765` |

## What it does

- **Whole-pattern fitting**: Rietveld structural refinement, Le Bail, and profile-only fitting on powder patterns
- **Quantification**: phase amounts with e.s.d.; text / JSON / HTML reports
- **Profile model**: EWIMV texture, Popa LB anisotropic size/strain, Brindley micro-absorption, TCH peak shape, unit-cell and atomic-coordinate (xyz) refinement
- **Three entry points**: Qt6 GUI, command line, and Python library API
- **Family interoperability**: imports XinMatch phase analysis (`.xinm`) and stores self-contained `.xinr` projects

## Documentation

- [Evaluation report — cross-check against MAUD on 7 real samples](docs/评估报告-实样对拍-MAUD-v1.md)
- [Improvement plan and acceptance criteria](docs/立项-MAUD对标改进计划-v1.md)
- [Audit remediation backlog](docs/后续计划-审计整改-backlog.md)
- [Release notes archive](docs/)

## License

[LICENSE](LICENSE) · [LICENSE-CN](LICENSE-CN)
