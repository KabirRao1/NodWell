# Metrics

Only numbers produced by the tools in `bench/` go here (CLAUDE.md §9). Every result records the
hardware, OS, and camera it was measured on. Spike observations live in `SPIKE_NOTES.md`, not here.

**No measurements yet.** The `bench/` tools are built from M1 onward.

## Result template

### <metric> — <date> — <commit>

| | |
|---|---|
| Machine / CPU / RAM | |
| OS | |
| Camera (model, resolution, fps) | |
| Lighting / distance | |
| Profile settings | |
| Command | `uv run python bench/<tool>.py ...` |

| Measure | p50 | p95 | n |
|---|---|---|---|
| | | | |

Notes:
