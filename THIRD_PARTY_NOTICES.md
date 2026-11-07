# Sources and licenses

This repository contains the Python wrapper and locally authored workflow scripts. They are distributed under GPL-2.0-only; see LICENSE. The full GNU GPL text retains its original copyright notice.

The optional, separately downloaded native converter is BlueMatthew/WechatExporter:

- Source: https://github.com/BlueMatthew/WechatExporter
- Pinned release: https://github.com/BlueMatthew/WechatExporter/releases/tag/v1.9.5.13
- Upstream license: https://github.com/BlueMatthew/WechatExporter/blob/main/LICENSE

No upstream binaries are redistributed in this source repository or source ZIP. The downloader verifies a pinned original archive and executable; these hashes identify bytes and do not constitute an author signature. Preserve the upstream package's dependency notices when installing or redistributing it. The wrapper does not reimplement the native audio codecs.

Python runtime dependencies are zstandard, Pillow and PyAV, installed separately from requirements.txt. Their package license metadata and notices remain applicable; wheels and virtual environments are not bundled in the source release.

No original chat, phone backup, contact data, execution log or machine-specific installation metadata is part of this project. All test fixture content is authored synthetic data.
