# kicad-returnpath

A geometric **current-return-path checker** for KiCad PCBs. It parses a
`.kicad_pcb`, identifies the reference plane under each routed signal trace, and
reports where the return path is broken — a plane void the trace crosses
(*split-crossing*), degraded, or unreferenced.

CLI-first and headless (CI-friendly); a thin in-KiCad IPC layer is planned on top.
Full design: [`docs/return-path-checker-v1-spec.md`](../../docs/return-path-checker-v1-spec.md).

```
return-path check BOARD.kicad_pcb
```

Exits `0` (clean), `1` (finding at or above `--fail-on`, default `error`), or `2`
(bad args / unreadable board).

## Walking skeleton (this build)

The first end-to-end slice: parse a real **KiCad-10** board (file version
`20260206`), detect **split-crossing** findings with the *both-ends-on-plane*
interior predicate (§4.4), and print a grouped, severity-iconed text report.

The parser honours the §3 contract — nets are **name-based** everywhere
(`(net "GND")`, no net numbers, no zone `net_name` child) and a single zone can
**span multiple layers** (the reference plane is selected per `filled_polygon`
layer). A pre-KiCad-10 board (numeric nets / `net_name` child) is **rejected**
rather than silently passed — the exact failure mode the real-board retest surfaced.

Built on the shared [`kicad-core`](../kicad-core) S-expression parser and Shapely.
Licensed GPL-3.0-or-later.
