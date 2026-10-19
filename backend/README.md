# Backend

Python package for the AI Novel Writer API. Setup and run commands live in the repository root README.

Version 1.0.0 completes the MVP through M6: foreshadowing and the earlier milestones, plus LAN Compose deployment, single-user password-hash sessions, and SQLite backup/restore. E4 adds evidence-backed quality issues and repair candidates. E5 keeps manuscript writes, version snapshots, and AI or repair resolutions in one transaction, and records which task or repair produced a snapshot. E6 adds a versioned novel package (`ai-novel-writer-portable-v1`) that exports one novel and imports it as a new novel without overwriting existing rows or including API keys. Setup commands live in the repository root README. Conflict checks and quality checks do not change the manuscript or formal memory; a repair is written only after the author accepts it.
