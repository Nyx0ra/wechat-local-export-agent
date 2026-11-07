# Local validation

Version: 0.1.0. Validation date: 2026-11-07.

Environment actually exercised: Windows x64, CPython 3.12.13, fresh external virtual environment with zstandard 0.25.0, Pillow 13.0.0 and PyAV 19.0.2. It does not depend on the prior export's environment.

Command: `python -B -m unittest discover -s tests -v`.

Result: **32 tests passed**. Tests cover timezone equivalence and half-open boundaries, malformed/reversed ranges, one-sided and empty selections, complete selected conversations, multiple contact candidates, group rejection, unsupported schemas, duplicate message shards, output/source overlap, frozen configuration, stage order, unknown direction, original database immutability, missing dictionary and exact dictionary validation, range-excluded unsupported bodies, range/account-scoped media, missing payload reporting, synthetic image and MP3 decoding, HTML escaping, source/output body comparison, tampering detection, upstream archive integrity/traversal rejection, and privacy-check failures on deliberately introduced synthetic sensitive examples.

The pinned public upstream archive was downloaded using tools/fetch_upstream.py outside the project. ZIP and EXE SHA-256 matched the lock. Its `--help` exited successfully. No real chat or backup was passed to that program during project validation.

Source privacy checks passed with no findings, including an external private deny list for prior-case identifiers. That deny list and all scan/test working files remain outside the source release. The repository and ZIP contain source/docs/examples only; no native binaries, phone backup, real chat, raw runtime logs, virtual environment or bytecode cache.

CI is configured for Windows/Ubuntu and Python 3.12/3.13; those remote jobs have not been run. Actual local validation does not claim that all CI matrix entries or every phone/WeChat version are compatible.

Not verified: a new real-phone end-to-end run, every Apple Devices backup variant, new-message-format compatibility, native SILK conversion on synthetic phone backup, automatic dictionary discovery, encrypted backup decryption, SQLCipher decryption or full phone-history coverage.

Distribution handoff additionally checks the source ZIP's file list and reads each UTF-8 member against local deny terms; the extracted archive is tested in a new external directory. No remote repository is configured and no upload is part of this task.
