Attempt to remove Signalling Server activitity and reduced to mvp for functional testing and customer demos. not proven yet.

## Recent development notes (2026-03-15)

- Main UI (`apps/controller/mvp_ui_3.html`) gained Position Display improvements (heading indicator behaviors, sim-mode wiring, what3words coordinate entry, Theme Lab with JSON import/export, and slider/theme consistency fixes).
- Standalone map (`apps/controller/position_map_standalone.html`) gained tile-provider failover, tile-status diagnostics, darker Leaflet controls, scale bar, tilt/roll overlay instrument, and lens-zoom-driven indicator marker behavior.
- Pi deploy flow now includes copying `position_map_standalone.html` to `/opt/ui/` and hash verification to prevent blank map runtime drift.

## Working status update (2026-03-15)

- Head IP programming from the Head ID Configuration flow is working end-to-end with explicit network config transaction mode, validation, and ACK/inferred-ACK status handling.
- Position map/Pos Display stack is working in runtime with standalone map deploy and verification flow.
