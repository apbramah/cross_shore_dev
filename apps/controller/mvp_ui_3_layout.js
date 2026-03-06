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
  meta: {
    version: 1,
    name: "mvp_ui_3_layout",
  },
  wsDefaultUrl: "ws://127.0.0.1:8766",
  screen: {
    columns: 5,
    positionsPerColumn: 10,
  },
  // Button mappings are gamepad button indices.
  // Assign cw/ccw/sw per encoder. Set to null if unassigned.
  encoders: [
    { id: "E1", column: 1, cwButton: 0, ccwButton: 1, swButton: 2 },
    { id: "E2", column: 2, cwButton: 3, ccwButton: 4, swButton: 5 },
    { id: "E3", column: 3, cwButton: 6, ccwButton: 7, swButton: 8 },
    { id: "E4", column: 4, cwButton: 9, ccwButton: 10, swButton: 11 },
    { id: "E5", column: 5, cwButton: 12, ccwButton: 13, swButton: 14 },
  ],
  columns: [
    {
      id: "C1",
      title: "Column 1",
      positions: [
        {
          id: "C1P1",
          label: "Motors",
          commandKey: "motors_on",
          defaultValue: 1,
          values: [
            { label: "OFF", value: 0 },
            { label: "ON", value: 1 },
          ],
        },
        {
          id: "C1P2",
          label: "Gyro Heading",
          commandKey: "gyro_heading_correction",
          defaultValue: 5376,
          values: [
            { label: "-8192", value: -8192 },
            { label: "-4096", value: -4096 },
            { label: "-2048", value: -2048 },
            { label: "-1024", value: -1024 },
            { label: "0", value: 0 },
            { label: "1024", value: 1024 },
            { label: "2048", value: 2048 },
            { label: "4096", value: 4096 },
            { label: "5376", value: 5376 },
            { label: "8192", value: 8192 },
          ],
        },
        { id: "C1P3", label: "Spare", commandKey: null, values: [] },
        { id: "C1P4", label: "Spare", commandKey: null, values: [] },
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
      title: "Column 2",
      positions: [
        { id: "C2P1", label: "Spare", commandKey: null, values: [] },
        { id: "C2P2", label: "Spare", commandKey: null, values: [] },
        { id: "C2P3", label: "Spare", commandKey: null, values: [] },
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
      title: "Column 3",
      positions: [
        { id: "C3P1", label: "Spare", commandKey: null, values: [] },
        { id: "C3P2", label: "Spare", commandKey: null, values: [] },
        { id: "C3P3", label: "Spare", commandKey: null, values: [] },
        { id: "C3P4", label: "Spare", commandKey: null, values: [] },
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
      title: "Column 4",
      positions: [
        { id: "C4P1", label: "Spare", commandKey: null, values: [] },
        { id: "C4P2", label: "Spare", commandKey: null, values: [] },
        { id: "C4P3", label: "Spare", commandKey: null, values: [] },
        { id: "C4P4", label: "Spare", commandKey: null, values: [] },
        { id: "C4P5", label: "Spare", commandKey: null, values: [] },
        { id: "C4P6", label: "Spare", commandKey: null, values: [] },
        { id: "C4P7", label: "Spare", commandKey: null, values: [] },
        { id: "C4P8", label: "Spare", commandKey: null, values: [] },
        { id: "C4P9", label: "Spare", commandKey: null, values: [] },
        { id: "C4P10", label: "Spare", commandKey: null, values: [] },
      ],
    },
    {
      id: "C5",
      title: "Column 5",
      positions: [
        { id: "C5P1", label: "Spare", commandKey: null, values: [] },
        { id: "C5P2", label: "Spare", commandKey: null, values: [] },
        { id: "C5P3", label: "Spare", commandKey: null, values: [] },
        { id: "C5P4", label: "Spare", commandKey: null, values: [] },
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
