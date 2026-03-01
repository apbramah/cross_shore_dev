import sys
import time
from typing import Dict, Any, List

import customtkinter as ctk
import tkinter as tk

import mvp_protocol


class Joystick(ctk.CTkFrame):
    """
    Simple on-screen joystick:
      - circular base
      - draggable knob
      - exposes values in range [-1.0, +1.0] for x/y
    """

    def __init__(self, master=None, radius: int = 60, **kwargs):
        super().__init__(master, **kwargs)

        self._radius = radius
        size = radius * 2 + 12
        self._center = size // 2

        self._x = 0.0
        self._y = 0.0

        # Use a plain Tk canvas; let it inherit background from CTkFrame.
        # Avoid passing CTk-style fg_color lists (['light', 'dark']) into Tk.
        self.canvas = tk.Canvas(
            self,
            width=size,
            height=size,
            highlightthickness=0,
            borderwidth=0,
        )
        self.canvas.pack(expand=True, fill="both")

        r = radius
        c = self._center

        # Base circle
        self._base_id = self.canvas.create_oval(
            c - r,
            c - r,
            c + r,
            c + r,
            outline="#999999",
            width=2,
        )
        # Knob (smaller circle)
        self._knob_radius = max(10, radius // 3)
        self._knob_id = self.canvas.create_oval(
            c - self._knob_radius,
            c - self._knob_radius,
            c + self._knob_radius,
            c + self._knob_radius,
            fill="#3b8ed0",
            outline="",
        )

        self.canvas.bind("<Button-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)

    def _determine_bg(self, master) -> str:
        try:
            return str(master.cget("fg_color"))
        except Exception:
            return "#1e1e1e"

    # Public getters
    def get_x(self) -> float:
        return self._x

    def get_y(self) -> float:
        return self._y

    def _set_normalized(self, nx: float, ny: float) -> None:
        # Clamp to unit circle
        mag_sq = nx * nx + ny * ny
        if mag_sq > 1.0:
            mag = mag_sq ** 0.5
            nx /= mag
            ny /= mag

        self._x = max(-1.0, min(1.0, nx))
        self._y = max(-1.0, min(1.0, ny))

        # Update knob position in canvas coordinates
        r = self._radius
        c = self._center
        px = c + self._x * r
        py = c - self._y * r  # screen Y is inverted

        kr = self._knob_radius
        self.canvas.coords(
            self._knob_id,
            px - kr,
            py - kr,
            px + kr,
            py + kr,
        )

    def _event_to_normalized(self, event) -> None:
        # Convert mouse position to -1..+1 range
        x = event.x - self._center
        y = self._center - event.y  # invert so up is +ve
        nx = x / float(self._radius)
        ny = y / float(self._radius)
        self._set_normalized(nx, ny)

    def _on_press(self, event) -> None:
        self._event_to_normalized(event)

    def _on_drag(self, event) -> None:
        self._event_to_normalized(event)

    def _on_release(self, _event) -> None:
        # Leave knob where it is (no auto-center) so user can hold a position.
        # If you want auto-center, uncomment the next line.
        # self._set_normalized(0.0, 0.0)
        pass


class MVPDesktopApp(ctk.CTk):
    """
    CustomTkinter desktop UI that replaces mvp_bridge + mvp_ui.html.
    Sends UDP directly using mvp_protocol.
    """

    SEND_INTERVAL_MS = 50  # ~20 Hz

    def __init__(self):
        super().__init__()

        ctk.set_appearance_mode("System")
        ctk.set_default_color_theme("blue")

        self.title("Hydravision MVP Desktop Controller")
        self.geometry("1100x650")
        self.minsize(900, 550)

        # Heads / protocol state
        self.heads: List[Dict[str, Any]] = mvp_protocol.load_heads()
        self.selected_index: int = 0 if self.heads else -1

        self.control_state: Dict[str, Any] = {
            "invert": {"yaw": False, "pitch": False, "roll": False},
            "speed": 1.0,
            "zoom_gain": 60.0,
        }

        self._build_ui()

        # Periodic send loop
        self.after(self.SEND_INTERVAL_MS, self._send_loop)

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------- UI ----------
    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=1)
        self.grid_columnconfigure(2, weight=0)
        self.grid_rowconfigure(0, weight=1)

        # Left: head selection + settings
        left = ctk.CTkFrame(self, corner_radius=12)
        left.grid(row=0, column=0, sticky="nsw", padx=12, pady=12)
        left.grid_columnconfigure(0, weight=1)

        title = ctk.CTkLabel(
            left,
            text="Connection / Settings",
            font=ctk.CTkFont(size=18, weight="bold"),
        )
        title.grid(row=0, column=0, sticky="w", padx=12, pady=(12, 6))

        # Head selector
        head_label = ctk.CTkLabel(left, text="Select Head:")
        head_label.grid(row=1, column=0, sticky="w", padx=12, pady=(4, 2))

        values = self._head_display_values()
        self.head_combo = ctk.CTkComboBox(
            left,
            values=values or ["(no heads.json found)"],
            state="readonly",
            width=260,
            command=self._on_head_changed,
        )
        if values:
            self.head_combo.set(values[self.selected_index])
        else:
            self.head_combo.set("(no heads.json found)")
        self.head_combo.grid(row=2, column=0, padx=12, pady=(0, 8), sticky="w")

        self.head_status = ctk.CTkLabel(
            left,
            text=self._head_status_text(),
            wraplength=260,
            justify="left",
        )
        self.head_status.grid(row=3, column=0, sticky="w", padx=12, pady=(0, 10))

        # Invert checkboxes
        invert_frame = ctk.CTkFrame(left)
        invert_frame.grid(row=4, column=0, padx=12, pady=(4, 8), sticky="ew")

        self.inv_yaw_var = ctk.BooleanVar(value=False)
        self.inv_pitch_var = ctk.BooleanVar(value=False)
        self.inv_roll_var = ctk.BooleanVar(value=False)

        inv_yaw = ctk.CTkCheckBox(
            invert_frame,
            text="Invert Pan",
            variable=self.inv_yaw_var,
            command=self._update_invert,
        )
        inv_yaw.grid(row=0, column=0, padx=6, pady=4, sticky="w")
        inv_pitch = ctk.CTkCheckBox(
            invert_frame,
            text="Invert Tilt",
            variable=self.inv_pitch_var,
            command=self._update_invert,
        )
        inv_pitch.grid(row=1, column=0, padx=6, pady=4, sticky="w")
        inv_roll = ctk.CTkCheckBox(
            invert_frame,
            text="Invert Roll",
            variable=self.inv_roll_var,
            command=self._update_invert,
        )
        inv_roll.grid(row=2, column=0, padx=6, pady=(4, 8), sticky="w")

        # Speed slider
        speed_label = ctk.CTkLabel(left, text="Speed")
        speed_label.grid(row=5, column=0, sticky="w", padx=12, pady=(8, 2))

        speed_row = ctk.CTkFrame(left, fg_color="transparent")
        speed_row.grid(row=6, column=0, padx=12, pady=(0, 8), sticky="ew")
        speed_row.grid_columnconfigure(0, weight=1)

        self.speed_slider = ctk.CTkSlider(
            speed_row,
            from_=0.2,
            to=2.0,
            number_of_steps=36,
            command=self._on_speed_changed,
        )
        self.speed_slider.set(self.control_state["speed"])
        self.speed_slider.grid(row=0, column=0, sticky="ew", padx=(0, 8))

        self.speed_value_lbl = ctk.CTkLabel(
            speed_row,
            text=f"{self.control_state['speed']:.2f}",
            width=50,
        )
        self.speed_value_lbl.grid(row=0, column=1, sticky="e")

        # Zoom gain slider
        zg_label = ctk.CTkLabel(left, text="Zoom gain")
        zg_label.grid(row=7, column=0, sticky="w", padx=12, pady=(4, 2))

        zg_row = ctk.CTkFrame(left, fg_color="transparent")
        zg_row.grid(row=8, column=0, padx=12, pady=(0, 8), sticky="ew")
        zg_row.grid_columnconfigure(0, weight=1)

        self.zoom_gain_slider = ctk.CTkSlider(
            zg_row,
            from_=10,
            to=150,
            number_of_steps=140,
            command=self._on_zoom_gain_changed,
        )
        self.zoom_gain_slider.set(self.control_state["zoom_gain"])
        self.zoom_gain_slider.grid(row=0, column=0, sticky="ew", padx=(0, 8))

        self.zoom_gain_value_lbl = ctk.CTkLabel(
            zg_row,
            text=f"{int(self.control_state['zoom_gain'])}",
            width=40,
        )
        self.zoom_gain_value_lbl.grid(row=0, column=1, sticky="e")

        # Spacer
        left.grid_rowconfigure(99, weight=1)

        # Center: combined pan/tilt joystick
        center = ctk.CTkFrame(self, corner_radius=12)
        center.grid(row=0, column=1, sticky="nsew", padx=0, pady=12)
        center.grid_rowconfigure(1, weight=1)
        center.grid_columnconfigure(0, weight=1)

        pt_label = ctk.CTkLabel(
            center,
            text="Pan / Tilt (X / Y)",
            font=ctk.CTkFont(size=16, weight="bold"),
        )
        pt_label.grid(row=0, column=0, padx=12, pady=(12, 4), sticky="w")

        self.pan_tilt_joystick = Joystick(center)
        self.pan_tilt_joystick.grid(
            row=1,
            column=0,
            padx=12,
            pady=(0, 12),
            sticky="nsew",
        )

        # Right: roll / focus / iris / zoom velocity
        right = ctk.CTkFrame(self, corner_radius=12)
        right.grid(row=0, column=2, sticky="nse", padx=12, pady=12)
        right.grid_columnconfigure(0, weight=1)

        sliders_title = ctk.CTkLabel(
            right,
            text="Sliders",
            font=ctk.CTkFont(size=16, weight="bold"),
        )
        sliders_title.grid(row=0, column=0, padx=12, pady=(12, 6), sticky="w")

        # Roll
        self.roll_slider = self._add_axis_slider(
            right,
            row=1,
            label="Roll (Z)",
        )

        # Focus
        self.focus_slider = self._add_axis_slider(
            right,
            row=2,
            label="Focus (Xrotate)",
        )

        # Iris
        self.iris_slider = self._add_axis_slider(
            right,
            row=3,
            label="Iris (Yrotate)",
        )

        # Zoom velocity with return-to-centre
        zoom_label = ctk.CTkLabel(right, text="Zoom velocity (release to centre)")
        zoom_label.grid(row=4, column=0, padx=12, pady=(10, 2), sticky="w")

        zoom_row = ctk.CTkFrame(right, fg_color="transparent")
        zoom_row.grid(row=5, column=0, padx=12, pady=(0, 8), sticky="ew")
        zoom_row.grid_columnconfigure(0, weight=1)

        self.zoom_slider = ctk.CTkSlider(
            zoom_row,
            from_=-1.0,
            to=1.0,
            number_of_steps=40,
        )
        self.zoom_slider.set(0.0)
        self.zoom_slider.grid(row=0, column=0, sticky="ew", padx=(0, 8))

        self.zoom_value_lbl = ctk.CTkLabel(zoom_row, text="0.00", width=50)
        self.zoom_value_lbl.grid(row=0, column=1, sticky="e")

        # Bind mouse release so slider snaps back to 0
        self.zoom_slider.bind("<ButtonRelease-1>", self._on_zoom_released)

        right.grid_rowconfigure(99, weight=1)

    def _add_axis_slider(self, parent, row: int, label: str) -> ctk.CTkSlider:
        lbl = ctk.CTkLabel(parent, text=label)
        lbl.grid(row=row * 2 - 1, column=0, padx=12, pady=(4, 2), sticky="w")

        row_frame = ctk.CTkFrame(parent, fg_color="transparent")
        row_frame.grid(row=row * 2, column=0, padx=12, pady=(0, 6), sticky="ew")
        row_frame.grid_columnconfigure(0, weight=1)

        slider = ctk.CTkSlider(
            row_frame,
            from_=-1.0,
            to=1.0,
            number_of_steps=40,
        )
        slider.set(0.0)
        slider.grid(row=0, column=0, sticky="ew", padx=(0, 8))

        value_lbl = ctk.CTkLabel(row_frame, text="0.00", width=50)

        def _on_change(value: float) -> None:
            value_lbl.configure(text=f"{float(value):.2f}")

        slider.configure(command=_on_change)
        value_lbl.grid(row=0, column=1, sticky="e")

        return slider

    # ---------- UI helpers ----------
    def _head_display_values(self) -> List[str]:
        values: List[str] = []
        for h in self.heads or []:
            ip = h.get("ip", "?")
            port = h.get("port", mvp_protocol.UDP_DEFAULT_PORT)
            values.append(f"{h.get('name', 'HEAD')} ({ip}:{port})")
        return values

    def _head_status_text(self) -> str:
        if not self.heads:
            return "No heads loaded (check heads.json)."
        h = self.heads[self.selected_index]
        return f"Sending to: {h.get('name', 'HEAD')} @ {h.get('ip')}:{h.get('port', mvp_protocol.UDP_DEFAULT_PORT)}"

    def _on_head_changed(self, selected: str) -> None:
        values = self._head_display_values()
        try:
            idx = values.index(selected)
        except ValueError:
            return
        self.selected_index = idx
        self.head_status.configure(text=self._head_status_text())

    def _update_invert(self) -> None:
        self.control_state["invert"] = {
            "yaw": bool(self.inv_yaw_var.get()),
            "pitch": bool(self.inv_pitch_var.get()),
            "roll": bool(self.inv_roll_var.get()),
        }

    def _on_speed_changed(self, value: float) -> None:
        v = float(value)
        self.control_state["speed"] = v
        self.speed_value_lbl.configure(text=f"{v:.2f}")

    def _on_zoom_gain_changed(self, value: float) -> None:
        v = float(value)
        self.control_state["zoom_gain"] = v
        self.zoom_gain_value_lbl.configure(text=f"{int(v)}")

    def _on_zoom_released(self, _event) -> None:
        # Snap back to centre when the user lets go.
        self.zoom_slider.set(0.0)
        self.zoom_value_lbl.configure(text="0.00")

    # ---------- Send loop ----------
    def _collect_axes(self) -> Dict[str, float]:
        # Combined joystick: X = pan, Y = tilt
        pan_x = float(self.pan_tilt_joystick.get_x())
        tilt_y = float(self.pan_tilt_joystick.get_y())

        roll = float(self.roll_slider.get())
        focus = float(self.focus_slider.get())
        iris = float(self.iris_slider.get())
        zoom = float(self.zoom_slider.get())

        self.zoom_value_lbl.configure(text=f"{zoom:.2f}")

        return {
            "X": pan_x,
            "Y": tilt_y,
            "Z": roll,
            "Xrotate": focus,
            "Yrotate": iris,
            "Zrotate": zoom,
        }

    def _send_loop(self) -> None:
        try:
            if self.heads and 0 <= self.selected_index < len(self.heads):
                axes = self._collect_axes()
                packet = mvp_protocol.build_udp_packet(axes, self.control_state)
                mvp_protocol.send_udp(packet, self.heads[self.selected_index])
        except Exception as e:
            # Avoid crashing UI due to UDP issues; print to stderr.
            print(f"[MVPDesktop] Send loop error: {e}", file=sys.stderr)

        self.after(self.SEND_INTERVAL_MS, self._send_loop)

    # ---------- Cleanup ----------
    def _on_close(self) -> None:
        self.destroy()


if __name__ == "__main__":
    # Windows: improves DPI scaling sometimes
    if sys.platform.startswith("win"):
        try:
            import ctypes

            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass

    app = MVPDesktopApp()
    app.mainloop()

