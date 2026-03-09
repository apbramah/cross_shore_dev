/*
MVP UI 3 Slot Layout Configuration

Terminology:
- Column: one bottom-dock control bank (C1..C5)
- Position: one slot inside a column (P1..P10)
- Command: slow-command key sent to bridge (SET_SLOW_CONTROL.key)
- Value: one selectable command value for a position

Slot address format: CxPy (example: C1P1, C3P7)
*/

window.MVP_UI3_LAYOUT = {
  meta: { version: 2, name: "mvp_ui_3_layout" },
  wsDefaultUrl: "ws://127.0.0.1:8766",
  screen: { columns: 5, positionsPerColumn: 10 },
  encoders: [
    { id: "E1", column: 1, cwButton: 0, ccwButton: 1, swButton: 2 },
    { id: "E2", column: 2, cwButton: 3, ccwButton: 4, swButton: 5 },
    { id: "E3", column: 3, cwButton: 6, ccwButton: 7, swButton: 8 },
    { id: "E4", column: 4, cwButton: 10, ccwButton: 9, swButton: 11 },
    { id: "E5", column: 5, cwButton: 12, ccwButton: 13, swButton: 14 },
  ],
  columns: [
    {
      id: "C1",
      title: "Core",
      positions: [
        { id: "C1P1", label: "Motors", commandKey: "motors_on", defaultValue: 1, values: [{ label: "OFF", value: 0 }, { label: "ON", value: 1 }] },
        { id: "C1P2", label: "Control Mode", commandKey: "control_mode", defaultValue: "speed", values: [{ label: "Speed", value: "speed" }, { label: "Angle", value: "angle" }] },
        { id: "C1P3", label: "Lens Select", commandKey: "lens_select", defaultValue: "fuji", values: [{ label: "Fuji", value: "fuji" }, { label: "Canon", value: "canon" }] },
        { id: "C1P4", label: "Gyro Heading", commandKey: "gyro_heading_correction", defaultValue: 5376, values: [{ label: "-8192", value: -8192 }, { label: "-4096", value: -4096 }, { label: "-2048", value: -2048 }, { label: "-1024", value: -1024 }, { label: "0", value: 0 }, { label: "1024", value: 1024 }, { label: "2048", value: 2048 }, { label: "4096", value: 4096 }, { label: "5376", value: 5376 }, { label: "8192", value: 8192 }] },
        { id: "C1P5", label: "Spare", commandKey: null, values: [] },
        { id: "C1P6", label: "Spare", commandKey: null, values: [] },
        { id: "C1P7", label: "Spare", commandKey: null, values: [] },
        { id: "C1P8", label: "Spare", commandKey: null, values: [] },
        { id: "C1P9", label: "Spare", commandKey: null, values: [] },
        { id: "C1P10", label: "Spare", commandKey: null, values: [] },
      ],
    },
    {
      id: "C2",
      title: "Axis Source",
      positions: [
        { id: "C2P1", label: "Zoom Source", commandKey: "source_zoom", defaultValue: "pc", values: [{ label: "PC", value: "pc" }, { label: "Camera", value: "camera" }, { label: "Off", value: "off" }] },
        { id: "C2P2", label: "Focus Source", commandKey: "source_focus", defaultValue: "pc", values: [{ label: "PC", value: "pc" }, { label: "Camera", value: "camera" }, { label: "Off", value: "off" }] },
        { id: "C2P3", label: "Iris Source", commandKey: "source_iris", defaultValue: "pc", values: [{ label: "PC", value: "pc" }, { label: "Camera", value: "camera" }, { label: "Off", value: "off" }] },
        { id: "C2P4", label: "Spare", commandKey: null, values: [] },
        { id: "C2P5", label: "Spare", commandKey: null, values: [] },
        { id: "C2P6", label: "Spare", commandKey: null, values: [] },
        { id: "C2P7", label: "Spare", commandKey: null, values: [] },
        { id: "C2P8", label: "Spare", commandKey: null, values: [] },
        { id: "C2P9", label: "Spare", commandKey: null, values: [] },
        { id: "C2P10", label: "Spare", commandKey: null, values: [] },
      ],
    },
    {
      id: "C3",
      title: "Filter",
      positions: [
        { id: "C3P1", label: "Focus Filter", commandKey: "filter_enable_focus", defaultValue: 0, values: [{ label: "OFF", value: 0 }, { label: "ON", value: 1 }] },
        { id: "C3P2", label: "Iris Filter", commandKey: "filter_enable_iris", defaultValue: 0, values: [{ label: "OFF", value: 0 }, { label: "ON", value: 1 }] },
        { id: "C3P3", label: "Filter Num", commandKey: "filter_num", defaultValue: 1, values: [{ label: "1", value: 1 }, { label: "2", value: 2 }, { label: "4", value: 4 }, { label: "8", value: 8 }, { label: "16", value: 16 }] },
        { id: "C3P4", label: "Filter Den", commandKey: "filter_den", defaultValue: 1, values: [{ label: "1", value: 1 }, { label: "2", value: 2 }, { label: "4", value: 4 }, { label: "8", value: 8 }, { label: "16", value: 16 }] },
        { id: "C3P5", label: "Spare", commandKey: null, values: [] },
        { id: "C3P6", label: "Spare", commandKey: null, values: [] },
        { id: "C3P7", label: "Spare", commandKey: null, values: [] },
        { id: "C3P8", label: "Spare", commandKey: null, values: [] },
        { id: "C3P9", label: "Spare", commandKey: null, values: [] },
        { id: "C3P10", label: "Spare", commandKey: null, values: [] },
      ],
    },
    {
      id: "C4",
      title: "Shaping",
      positions: [
        { id: "C4P1", label: "Expo", commandKey: "shape_expo", defaultValue: 0.0, values: [{ label: "-0.5", value: -0.5 }, { label: "-0.25", value: -0.25 }, { label: "0.0", value: 0.0 }, { label: "0.25", value: 0.25 }, { label: "0.5", value: 0.5 }, { label: "0.75", value: 0.75 }] },
        { id: "C4P2", label: "Top Speed", commandKey: "shape_top_speed", defaultValue: 1.0, values: [{ label: "0.4", value: 0.4 }, { label: "0.6", value: 0.6 }, { label: "0.8", value: 0.8 }, { label: "1.0", value: 1.0 }, { label: "1.2", value: 1.2 }, { label: "1.5", value: 1.5 }] },
        { id: "C4P3", label: "Invert Yaw", commandKey: "shape_invert_yaw", defaultValue: 0, values: [{ label: "OFF", value: 0 }, { label: "ON", value: 1 }] },
        { id: "C4P4", label: "Invert Pitch", commandKey: "shape_invert_pitch", defaultValue: 0, values: [{ label: "OFF", value: 0 }, { label: "ON", value: 1 }] },
        { id: "C4P5", label: "Invert Roll", commandKey: "shape_invert_roll", defaultValue: 0, values: [{ label: "OFF", value: 0 }, { label: "ON", value: 1 }] },
        { id: "C4P6", label: "Deadband Yaw", commandKey: "shape_deadband_yaw", defaultValue: 0.0, values: [{ label: "0.000", value: 0.0 }, { label: "0.005", value: 0.005 }, { label: "0.010", value: 0.01 }, { label: "0.015", value: 0.015 }, { label: "0.020", value: 0.02 }, { label: "0.025", value: 0.025 }, { label: "0.030", value: 0.03 }, { label: "0.040", value: 0.04 }, { label: "0.050", value: 0.05 }] },
        { id: "C4P7", label: "Deadband Pitch", commandKey: "shape_deadband_pitch", defaultValue: 0.0, values: [{ label: "0.000", value: 0.0 }, { label: "0.005", value: 0.005 }, { label: "0.010", value: 0.01 }, { label: "0.015", value: 0.015 }, { label: "0.020", value: 0.02 }, { label: "0.025", value: 0.025 }, { label: "0.030", value: 0.03 }, { label: "0.040", value: 0.04 }, { label: "0.050", value: 0.05 }] },
        { id: "C4P8", label: "Deadband Roll", commandKey: "shape_deadband_roll", defaultValue: 0.0, values: [{ label: "0.000", value: 0.0 }, { label: "0.005", value: 0.005 }, { label: "0.010", value: 0.01 }, { label: "0.015", value: 0.015 }, { label: "0.020", value: 0.02 }, { label: "0.025", value: 0.025 }, { label: "0.030", value: 0.03 }, { label: "0.040", value: 0.04 }, { label: "0.050", value: 0.05 }] },
        { id: "C4P9", label: "Deadband Zoom", commandKey: "shape_deadband_zoom", defaultValue: 0.0, values: [{ label: "0.000", value: 0.0 }, { label: "0.005", value: 0.005 }, { label: "0.010", value: 0.01 }, { label: "0.015", value: 0.015 }, { label: "0.020", value: 0.02 }, { label: "0.025", value: 0.025 }, { label: "0.030", value: 0.03 }, { label: "0.040", value: 0.04 }, { label: "0.050", value: 0.05 }] },
        { id: "C4P10", label: "Spare", commandKey: null, values: [] },
      ],
    },
    {
      id: "C5",
      title: "Network",
      positions: [
        { id: "C5P1", label: "Apply Network", commandKey: "net_apply", defaultValue: 1, values: [{ label: "APPLY", value: 1 }] },
        { id: "C5P2", label: "Factory Net Reset", commandKey: "net_factory_reset", defaultValue: 1, values: [{ label: "RESET", value: 1 }] },
        { id: "C5P3", label: "WiFi Scan", commandKey: "wifi_scan", defaultValue: 1, values: [{ label: "SCAN", value: 1 }] },
        { id: "C5P4", label: "WiFi Disconnect", commandKey: "wifi_disconnect", defaultValue: 1, values: [{ label: "DISCONNECT", value: 1 }] },
        { id: "C5P5", label: "Spare", commandKey: null, values: [] },
        { id: "C5P6", label: "Spare", commandKey: null, values: [] },
        { id: "C5P7", label: "Spare", commandKey: null, values: [] },
        { id: "C5P8", label: "Spare", commandKey: null, values: [] },
        { id: "C5P9", label: "Spare", commandKey: null, values: [] },
        { id: "C5P10", label: "Spare", commandKey: null, values: [] },
      ],
    },
  ],
};
