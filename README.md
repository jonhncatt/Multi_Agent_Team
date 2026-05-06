# Vintage Programmer

Single repository. Multiple user languages.

- [日本語 README](README.ja.md)
- [中文 README](README.zh-CN.md)
- [English README](README.en.md)
- [Windows Guide](README.windows.md)
- [Release Flow](RELEASING.md)

Current stable release: `v2.7.3`

This repository keeps one code mainline and localizes user-facing text through a locale layer instead of splitting into separate language-specific repos.

Default deployment language can be set in `.env` with `VP_DEFAULT_LOCALE`.

- Supported values: `zh-CN`, `ja-JP`, `en`
- Effective priority: current user selection in Settings > local browser preference > browser language > `VP_DEFAULT_LOCALE`

Current product focus is the single-agent chat workbench.
