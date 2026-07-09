# kicad-core (reserved)

Reserved slot for the **lean shared core** — S-expression read/emit (`sexpr.py`)
plus the KiCad IPC bridge — that the per-tool packages will depend on.

Deliberately empty for now. Per the migration posture in
[`docs/return-path-checker-v1-spec.md`](../../docs/return-path-checker-v1-spec.md) §11
(**"remodel now, extract `kicad-core` later"**), the core is not carved out of
`kicad-captouch` until the return-path checker actually imports it — a shared
boundary designed against a single consumer is a guess.

Because it holds no package yet, this path is listed under
`[tool.uv.workspace] exclude` in the root `pyproject.toml`. When the core is
extracted, add a `pyproject.toml` here and remove that exclude entry.
