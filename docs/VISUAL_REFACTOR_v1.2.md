# Market State Explorer v1.2 — Visual Clarity Refactor

Goal: make State Map and Trajectory readable at a glance without changing any quantitative model mathematics.

## State Map
- Default to density view for historical context instead of plotting every historical bar as a marker.
- Overlay only a small recent window with a recency gradient and a highlighted current state.
- Optional Recent-only and Full-scatter modes remain available for drill-down.
- Optional coloring by bar direction or positioning state.

## Trajectory
- Default to 12 recent valid states rather than 50.
- Provide 2D state-space, Effort over time, Result over time, and Strength/Velocity over time views.
- Highlight first, previous, and current states; emphasize the last move.
- Keep longer windows available as a deliberate user choice.

## Insight layer
- Add concise deterministic summaries of current region and recent directional drift.
- Boundary warnings remain explicit and do not become trade signals.

## Guardrail
No Effort, Result, Positioning, Delta, OI, validation, normalization, event, threshold, or look-ahead logic is changed by this release.
