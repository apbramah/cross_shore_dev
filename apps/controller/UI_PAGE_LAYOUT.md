# MVP UI Page Layout – Naming Reference

Simple diagram of `mvp_ui_3.html` structure for consistent naming when tweaking the UI. Full overhaul will follow command-architecture changes; this is the current MVP layout.

---

## Recent updates (2026-03-15)

- Added top action button `posDisplayBtn` (`Pos Display`) next to lockoff/motors actions.
- Added Position Display overlay panel `#posDisplayPanel` that replaces surface+dock while open.
- Position Display left panel now includes:
  - telemetry readouts (`posDisplayPan`, `posDisplayTilt`, `posDisplayRoll`, `posDisplayZoom`, `posDisplayIris`, `posDisplayFocus`)
  - heading offset slider (`posDisplayHeadingOffset`, `posDisplayHeadingOffsetVal`)
  - sim mode toggle (`posDisplaySimMode`)
- Position Display map area includes iframe `#posDisplayFrame` and close button `#posDisplayClose`.
- Engineering page actions now include:
  - Position map `lat, lon` input (`posDisplayLatLon`)
  - what3words input/apply (`posDisplayW3WWords`, `posDisplayW3WApply`)
  - what3words API key input (`posDisplayW3WKey`)
  - Theme Lab panel with 8-color pickers, preset controls, and JSON import/export
- Head config editor table now includes network push workflow UI:
  - per-row `Push To Head` action
  - per-row push status cell
  - `Match Console LAN Subnet` helper action

---

## App shell

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  TOPBAR (class="topbar")                                                     │
│  ├── head-selector-row    [Select Head]  <select id="heads" hidden>          │
│  ├── connection-row       [connectionPill] Head: &lt;name&gt; Lens: &lt;name&gt; (status colours)   │
│  └── top-actions-row      [Pos Display] [Lockoff] [Motors On] [Motors Off]     │
├─────────────────────────────────────────────────────────────────────────────┤
│  SURFACE (id="surfaceMain", class="surface")                                  │
│  ┌───────────────────────────────────────────────────────────────────────┐   │
│  │  One visible PAGE at a time (tab content)                             │   │
│  │  • page-control  • page-slow  • page-fast  • page-ipconfig  • page-   │   │
│  │                                                          inputtests   │   │
│  └───────────────────────────────────────────────────────────────────────┘   │
├─────────────────────────────────────────────────────────────────────────────┤
│  DOCK (id="dockMain", class="dock")                                          │
│  └── dockGrid   →  Tab buttons (Control, Slow, Fast, Network, Engineering)   │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Topbar regions (consistent names):**

| Name                | Element / ID           | Description                          |
|---------------------|------------------------|--------------------------------------|
| **head-selector-row** | `headSelectorBtn`, `heads` | Select Head button (and hidden dropdown) |
| **connection-row**    | `connectionPill` | Single pill: "Head: &lt;name&gt; Lens: &lt;name&gt;" (grey/yellow/green status) |
| **top-actions-row**   | `posDisplayBtn`, `lockoffBtn`, `touchMotorsOn`, `touchMotorsOff` | Pos Display, Lockoff, Motors On, Motors Off |

---

## Pages (surface content)

Only one page has `class="page active"`; the rest are `class="page"` and hidden. The **dock** switches the active page.

---

### Page: Control (`id="page-control"`)

Main control view (default).

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  PAGE: Control                                                               │
│  ┌───────────────────────────────────────────────────────────────────────┐   │
│  │  control-sliders-card (single card)                                    │   │
│  │  ├── control-quick-row     (#controlQuickButtonRow)  ← quick buttons  │   │
│  │  └── control-slider-grid   (#controlSliderGrid)      ← slider grid     │   │
│  └───────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
```

| Region name           | ID / class                  | Description              |
|-----------------------|-----------------------------|--------------------------|
| **control-quick-row** | `controlQuickButtonRow`     | Fixed buttons: Tilt, Roll Invert, Zoom Invert, Wipe Once, Wiper On/Off (toggle) |
| **control-slider-grid** | `controlSliderGrid`       | Fixed 6 sliders: row1 Pan Speed, Tilt Speed, Roll Speed; row2 Pan Trim, Joystick Expo, Zoom Speed. Value shown next to each label. |

---

### Page: Slow (`id="page-slow"`)

Slow channel: fixed slider grid (gain/accel) + same quick buttons as Control.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  PAGE: Slow                                                                  │
│  ┌───────────────────────────────────────────────────────────────────────┐   │
│  │  slow-sliders-card                                                      │   │
│  │  ├── slow-quick-row        (#slowQuickButtonRow)  ← Tilt, Roll Invert,  │   │
│  │  │                         Zoom Invert, Wipe Once, Wiper On/Off         │   │
│  │  └── slow-slider-grid      (#slowSliderGrid)  ← row1: Pan/Tilt/Roll     │   │
│  │                             Gain; row2: Pan/Tilt/Roll Acceleration     │   │
│  └───────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
```

| Region name          | ID / class        | Description           |
|----------------------|-------------------|------------------------|
| **slow-quick-row**   | `slowQuickButtonRow` | Same 5 buttons as Control (Tilt, Roll Invert, Zoom Invert, Wipe Once, Wiper On/Off) |
| **slow-slider-grid** | `slowSliderGrid`  | Row1: Pan Gain, Tilt Gain, Roll Gain; Row2: Pan Accel, Tilt Accel, Roll Accel |

---

### Page: Fast / Settings 2 (`id="page-fast"`)

Definitive list of 13 rows (shaping + slow mix).

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  PAGE: Fast (Settings 2)                                                     │
│  ┌───────────────────────────────────────────────────────────────────────┐   │
│  │  stack-row-card                                                        │   │
│  │  ├── command-list-title   "Fast Controls (1-10)"                       │   │
│  │  └── fast-control-rows    (#fastControlRows)  ← 13 fixed rows:         │   │
│  │       Iris Source, Zoom Feedback Dampening, Zoom Expo,                 │   │
│  │       Dead Band Pan/Tilt/Roll/Zoom, Pan Invert,                         │   │
│  │       Pan/Tilt/Roll Lock Off Range, Lock Off Dead Band,                 │   │
│  │       Lock off Response Speed                                          │   │
│  └───────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
```

| Region name          | ID / class        | Description           |
|----------------------|-------------------|------------------------|
| **fast-list-title**  | `.command-list-title` | "Fast Controls (1-10)" |
| **fast-control-rows** | `fastControlRows` | 13 fixed rows (see list above) |

---

### Page: Network / IP config (`id="page-ipconfig"`) — Control 2

Shown when **Control 2** is selected. Network, WiFi, and head config (moved from Engineering).

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  PAGE: Control 2 (Network)                                                   │
│  ┌─ LAN card ───────────────────────────────────────────────────────────┐   │
│  │  "LAN settings" + desc (Ethernet eth0)                                │   │
│  │  Address, Prefix, Gateway | Save/Apply/Factory | networkInfo, etc.   │   │
│  │  $ ifconfig eth0 (ifconfigEth)                                       │   │
│  ├─ WiFi card ──────────────────────────────────────────────────────────┤   │
│  │  "WiFi" + desc (Wireless wlan0) | SSID, Password, buttons, wifiStatus │   │
│  │  WiFi table (wifiTableBody) | $ ifconfig wlan0 (ifconfigWifi)          │   │
│  └─ Head config card (bottom) ───────────────────────────────────────────┘   │
│     [Edit Head IDs (Full Screen)]                                            │
└─────────────────────────────────────────────────────────────────────────────┘
```

| Region name             | ID / class           | Description                |
|-------------------------|----------------------|----------------------------|
| **LAN card**       | first `.card`  | Title "LAN settings", desc, form, then ifconfig eth0 |
| **WiFi card**      | second `.card` | Title "WiFi", desc, form, wifi table, then ifconfig wlan0 |
| **Head config card** | third `.card`     | “Edit Head IDs (Full Screen)” button |

---

### Page: Engineering / Input tests (`id="page-inputtests"`)

Engineering actions (theme, Theme Lab, position-map inputs, brightness, calibrate).

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  PAGE: Engineering                                                          │
│  ┌─ engineering-actions-card ───────────────────────────────────────────┐   │
│  │  command-list-title "Engineering Actions"                              │   │
│  │  input-test-controls: Theme, Theme Lab, Pos map coords, w3w,         │   │
│  │                       Screen Brightness, Calibrate Inputs             │   │
│  ├─ connection-state-card ──────────────────────────────────────────────┤   │
│  │  connectionState (info)                                                │   │
│  ├─ calibration-state-card ─────────────────────────────────────────────┤   │
│  │  calibrationState (info)                                               │   │
│  └─ screen-brightness-state-card ────────────────────────────────────────┘   │
│     screenBrightnessState (info)                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

| Region name                   | ID / class               | Description                    |
|------------------------------|---------------------------|--------------------------------|
| **engineering-actions-card** | first `.stack-row-card`   | Theme, Theme Lab, position map coordinates/w3w, brightness, calibrate |
| **connection-state-card**    | second `.stack-row-card`  | connectionState text          |
| **calibration-state-card**   | third `.stack-row-card`   | calibrationState text         |
| **screen-brightness-state-card** | fourth `.stack-row-card` | screenBrightnessState text    |

---

## Overlays / modals

These sit above the app when open; they are not part of the surface/dock.

| Name               | Container ID        | Description                          |
|--------------------|---------------------|--------------------------------------|
| **keyboard-overlay** | `kbd`             | On-screen keyboard (kbdTargetLabel, kbdBuffer, kbdRows, kbdBack, kbdClear, kbdCancel, kbdOk) |
| **head-picker**    | `headPicker`        | Head selector modal (headPickerClose, headPickerList, headPickerCancel) |
| **head-config-editor** | `headConfigEditor` | Full-screen Head ID table (headConfigClose, headTableBodyEditor, headConfigDone) |
| **position-display-panel** | `posDisplayPanel` | Full-screen content swap panel with telemetry + embedded map iframe |

---

## Summary: IDs and region names

| Region name (use in specs) | Primary ID / location |
|----------------------------|------------------------|
| topbar                     | `.topbar` |
| head-selector-row          | `headSelectorBtn`, `heads` |
| connection-row             | `connectionPill` |
| top-actions-row            | `homeBtn`, `lockoffBtn`, `touchMotorsOn`, `touchMotorsOff` |
| surface                    | `surfaceMain` |
| dock                       | `dockMain`, `dockGrid` |
| page-control               | `page-control` |
| control-quick-row          | `controlQuickButtonRow` |
| control-slider-grid        | `controlSliderGrid` |
| page-slow                  | `page-slow` |
| slow-quick-row             | `slowQuickButtonRow` |
| slow-slider-grid           | `slowSliderGrid` |
| page-fast                  | `page-fast` |
| fast-control-rows         | `fastControlRows` |
| page-ipconfig              | `page-ipconfig` |
| page-inputtests            | `page-inputtests` |
| keyboard-overlay           | `kbd` |
| head-picker                | `headPicker` |
| head-config-editor         | `headConfigEditor` |

Use the **region names** in the left column when describing changes (e.g. “move lens name into connection-row” or “add a label to control-slider-grid”).
