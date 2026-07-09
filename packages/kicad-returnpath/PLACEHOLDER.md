# kicad-returnpath (reserved)

Reserved slot for the **return-path checker** tool — a CLI-first DRC-style checker
that flags capacitive-touch sensor traces whose ground return path is missing or
too far. Spec: [`docs/return-path-checker-v1-spec.md`](../../docs/return-path-checker-v1-spec.md).

This directory is a placeholder: it holds no package yet, so it is listed under
`[tool.uv.workspace] exclude` in the root `pyproject.toml`. When the checker gets
its first module, add a `pyproject.toml` here (hatchling backend, depending on the
shared core) and remove this path from the workspace `exclude` list.
