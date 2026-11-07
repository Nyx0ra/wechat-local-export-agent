# Local chat export implementation plan

Goal: package the existing local scripts into an agent-readable source project without any real user data.

Architecture: Python stage CLI; explicit backup and target selection; read-only source queries; time window applied before copying messages or selecting media; independent verification reads the same window from the original database. Native conversion is optional and uses an externally installed pinned upstream tool.

Decisions: retain the existing single-account/single-shard compatibility boundary. Use ISO 8601 timestamps with explicit UTC offset and a half-open [start, end) interval. Reject invalid, naive or reversed windows. Keep runtime data outside this repository. No new phone backup, publishing or real-chat access in this task.

- [x] Copy only reusable Python source and dependency pins; omit all local metadata, binaries and environments.
- [x] Write failing time-window and synthetic-backup integration tests.
- [x] Implement window validation, SQL filtering, media scoping, empty results and config immutability.
- [x] Add agent instructions, quick start, compatibility/privacy documentation, pinned upstream bootstrap and CI.
- [x] Run tests in a fresh external environment; inspect the distributable for privacy and packaging exclusions; create a source-only ZIP.

Verification: offset-equivalent boundaries, end exclusivity, tied timestamps, empty windows, unsupported/encrypted inputs, identity ambiguity, unrelated messages/media, missing dictionaries/media, HTML escaping, UTF-8, source immutability, tampering detection, and absence of machine/user-specific metadata in the release.

Do not treat synthetic compatibility as a new-device end-to-end certification.
