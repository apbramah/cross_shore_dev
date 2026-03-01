from __future__ import annotations

import queue
import time
from typing import Optional

import customtkinter as ctk

from .bit_runner import BitCallbacks, BitRunner
from .canon_protocol import (
    BAUD,
    CMD_FOCUS_POS,
    CMD_IRIS_POS,
    CMD_ZOOM_POS,
    SCMD_FOCUS_SWITCH,
    SCMD_IRIS_SWITCH,
    SCMD_ZOOM_SWITCH,
    SRC_CAMERA,
    SRC_OFF,
    SRC_PC,
    SUBCMD_C0,
    build_type_b,
    build_type_c_switch,
    decode_lens_name_type_c,
    hexdump,
    unpack_type_b_value,
)
from .frame_parser import CanonFrameParser
from .fuji_bit_runner import FujiBitCallbacks, FujiBitRunner
from .fuji_frame_parser import FujiL10FrameParser
from .fuji_protocol import (
    FUJI_BAUD,
    FUJI_BITS,
    FUJI_PARITY,
    FUJI_STOP,
    SW4_HOST_ALL,
    SW4_RELEASE_ALL,
    build_connect,
    build_focus_control,
    build_iris_control,
    build_lens_name_request,
    build_position_request_focus,
    build_position_request_iris,
    build_position_request_zoom,
    build_switch4_control,
    build_switch4_position_request,
    build_zoom_control,
    build_request,
    decode_lens_name_chunk,
    decode_position_response,
    hexdump as fuji_hexdump,
    parse_l10_frame,
)
from .gamepad import GamepadConfig, GamepadRunner, PYGAME_OK
from .serial_worker import SerialConfig, SerialWorker
from .utils import HEX_RE, extract_port_name, list_com_ports


class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        ctk.set_appearance_mode("System")
        ctk.set_default_color_theme("blue")

        self.title("HydraVision Lens Tester")
        self.geometry("1250x820")
        self.minsize(1100, 720)

        self.worker = SerialWorker()
        self.parser = CanonFrameParser()

        # Fuji L10: second port, 38400 8N1
        self.fuji_worker = SerialWorker()
        self.fuji_parser = FujiL10FrameParser()
        self.fuji_lens_name = ""
        self.fuji_iris_pos: Optional[int] = None
        self.fuji_zoom_pos: Optional[int] = None
        self.fuji_focus_pos: Optional[int] = None
        self.fuji_connect_spam_enabled = False
        self.fuji_connect_spam_after_id: Optional[str] = None
        self.fuji_connect_spam_interval_ms = 100
        # Fuji GUI behavior: continuous polling keeps link/control alive.
        self.fuji_host_keepalive_enabled = True
        self.fuji_host_keepalive_after_id: Optional[str] = None
        self.fuji_host_keepalive_interval_ms = 100
        self.fuji_host_keepalive_tick_count = 0
        self.fuji_poll_seq = [0x54, 0x53, 0x52, 0x30, 0x31, 0x32, 0x33, 0x34, 0x35]
        self.fuji_poll_idx = 0
        self.fuji_auto_recovery_enabled = False
        self.fuji_auto_recovery_after_id: Optional[str] = None
        self.fuji_auto_reset_every = 20
        self.fuji_auto_connect_count = 0
        self.fuji_connect_sent_count = 0
        self.fuji_reset_sent_count = 0
        self.fuji_last_rx_func = "--"
        self.fuji_modem_state = {"dsr": False, "cts": False, "ri": False, "cd": False}
        self.fuji_name_poll_after_id: Optional[str] = None
        self.fuji_name_poll_attempts = 0
        self.fuji_name_poll_max_attempts = 20
        self.fuji_name_poll_interval_ms = 300
        self.fuji_sw4_bits: Optional[int] = None
        self.fuji_sw4_desired_bits = SW4_HOST_ALL
        self._modem_ui_syncing = False

        self.rx_frame_q: "queue.Queue[bytes]" = queue.Queue()

        self.bit_passed = False
        self.lens_name = ""
        self.zoom_follow: Optional[int] = None
        self.focus_follow: Optional[int] = None
        self.iris_follow: Optional[int] = None

        self.gamepad_cfg = GamepadConfig(enabled=True)
        self.gamepad_cfg.debug_log_buttons = True
        self.zoom_target = 30000
        self.focus_target = 30000
        self.iris_target = 30000

        self._build_ui()
        self._refresh_ports()

        self.gamepad_runner = GamepadRunner(
            worker=self.worker,
            cfg=self.gamepad_cfg,
            can_drive=self._gamepad_can_drive_active_tab,
            get_follow=self._gamepad_get_follow_active_tab,
            set_targets=self._ui_set_gamepad_targets_active_tab,
            log=self._ui_log,
            send_axis=self._gamepad_send_axis_active_tab,
            target_max=65535,
        )

        self.bit_runner = BitRunner(
            worker=self.worker,
            rx_frame_q=self.rx_frame_q,
            callbacks=BitCallbacks(
                log=self._ui_log,
                set_status=self._ui_set_bit_status,
                on_lens_id=self._ui_set_lens_name,
                on_targets=self._ui_set_targets,
                on_passed=self._mark_bit_passed,
                on_failed=self._mark_bit_failed,
            ),
        )

        self.fuji_bit_runner = FujiBitRunner(
            callbacks=FujiBitCallbacks(
                log=self._fuji_bit_log,
                set_status=self._fuji_ui_set_bit_status,
                send_connect=self._fuji_bit_send_connect,
                switch4_host=self._fuji_bit_switch4_host,
                read_sw4=self._fuji_bit_read_sw4,
                request_axis_position=self._fuji_bit_request_axis_position,
                send_axis_control=self._fuji_bit_send_axis_control,
                on_passed=self._fuji_bit_passed,
                on_failed=self._fuji_bit_failed,
            )
        )

        self.after(30, self._poll_rx)
        self.after(30, self._poll_rx_fuji)
        self.after(200, self._poll_fuji_modem_status)
        self.after(200, self._poll_gamepad_state)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------- UI ----------
    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.tabview = ctk.CTkTabview(self)
        self.tabview.grid(row=0, column=0, sticky="nsew", padx=12, pady=12)
        self.tabview.add("Canon")
        self.tabview.add("Fuji")

        canon_tab = self.tabview.tab("Canon")
        canon_tab.grid_columnconfigure(0, weight=0)
        canon_tab.grid_columnconfigure(1, weight=1)
        canon_tab.grid_rowconfigure(0, weight=1)

        left = ctk.CTkFrame(canon_tab, corner_radius=12)
        left.grid(row=0, column=0, sticky="nsw", padx=12, pady=12)

        right = ctk.CTkFrame(canon_tab, corner_radius=12)
        right.grid(row=0, column=1, sticky="nsew", padx=(0, 12), pady=12)
        right.grid_rowconfigure(4, weight=1)
        right.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(left, text="Connection", font=ctk.CTkFont(size=18, weight="bold")).grid(
            row=0, column=0, sticky="w", padx=12, pady=(12, 6)
        )

        self.port_combo = ctk.CTkComboBox(left, values=["(refresh)"], width=340)
        self.port_combo.grid(row=1, column=0, padx=12, pady=6, sticky="w")

        btn_row = ctk.CTkFrame(left, fg_color="transparent")
        btn_row.grid(row=2, column=0, padx=12, pady=6, sticky="w")
        ctk.CTkButton(btn_row, text="Refresh", command=self._refresh_ports, width=160).grid(row=0, column=0, padx=(0, 8))
        self.connect_btn = ctk.CTkButton(btn_row, text="Connect", command=self._connect, width=160)
        self.connect_btn.grid(row=0, column=1)

        self.status_lbl = ctk.CTkLabel(left, text="Status: Disconnected")
        self.status_lbl.grid(row=3, column=0, sticky="w", padx=12, pady=(2, 6))

        self.lens_lbl = ctk.CTkLabel(left, text="Lens: (unknown)")
        self.lens_lbl.grid(row=4, column=0, sticky="w", padx=12, pady=(0, 10))

        toggles = ctk.CTkFrame(left)
        toggles.grid(row=5, column=0, padx=12, pady=6, sticky="ew")
        self.dtr_var = ctk.BooleanVar(value=True)
        self.dsr_var = ctk.BooleanVar(value=True)
        self.rts_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(toggles, text="DTR", variable=self.dtr_var, command=self._on_dtr_toggle).grid(
            row=0, column=0, padx=10, pady=(10, 2), sticky="w"
        )
        ctk.CTkCheckBox(toggles, text="DSR (alias DTR)", variable=self.dsr_var, command=self._on_dsr_toggle).grid(
            row=1, column=0, padx=10, pady=(2, 2), sticky="w"
        )
        ctk.CTkCheckBox(toggles, text="RTS", variable=self.rts_var, command=self._apply_modem_lines).grid(
            row=2, column=0, padx=10, pady=(2, 10), sticky="w"
        )

        ctk.CTkLabel(left, text="Manual Send (Hex)", font=ctk.CTkFont(size=16, weight="bold")).grid(
            row=6, column=0, sticky="w", padx=12, pady=(14, 6)
        )
        self.hex_entry = ctk.CTkEntry(left, placeholder_text="e.g. 87 C0 01 6A 30 BF")
        self.hex_entry.grid(row=7, column=0, padx=12, pady=6, sticky="ew")
        ctk.CTkButton(left, text="Send Hex", command=self._send_hex_entry).grid(row=8, column=0, padx=12, pady=6, sticky="ew")

        ctk.CTkLabel(left, text="Gamepad", font=ctk.CTkFont(size=16, weight="bold")).grid(
            row=9, column=0, sticky="w", padx=12, pady=(16, 6)
        )

        self.gamepad_enabled_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            left, text="Enable gamepad", variable=self.gamepad_enabled_var, command=self._toggle_gamepad
        ).grid(row=10, column=0, padx=12, pady=(0, 6), sticky="w")

        self.gamepad_state_lbl = ctk.CTkLabel(left, text="State: (not started)")
        self.gamepad_state_lbl.grid(row=11, column=0, padx=12, pady=(0, 8), sticky="w")

        ctk.CTkLabel(left, text="Zoom deadband").grid(row=12, column=0, padx=12, pady=(6, 2), sticky="w")
        self.deadband_slider = ctk.CTkSlider(
            left, from_=0.0, to=0.5, number_of_steps=50, command=self._on_deadband_change
        )
        self.deadband_slider.set(self.gamepad_cfg.zoom_deadband)
        self.deadband_slider.grid(row=13, column=0, padx=12, pady=(0, 6), sticky="ew")

        self.deadband_lbl = ctk.CTkLabel(left, text=f"Deadband: {self.gamepad_cfg.zoom_deadband:.2f}")
        self.deadband_lbl.grid(row=14, column=0, padx=12, pady=(0, 12), sticky="w")

        self.bit_status_frame = ctk.CTkFrame(right, corner_radius=12, fg_color="#3a3a3a")
        self.bit_status_frame.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 8))
        self.bit_status_frame.grid_columnconfigure(0, weight=1)

        self.bit_status_title = ctk.CTkLabel(
            self.bit_status_frame, text="Connection & Control: NOT RUN", font=ctk.CTkFont(size=18, weight="bold")
        )
        self.bit_status_title.grid(row=0, column=0, sticky="w", padx=12, pady=(10, 2))

        self.bit_status_detail = ctk.CTkLabel(
            self.bit_status_frame,
            text="Connect to run automatic BIT (init, take control, sweep axes).",
            font=ctk.CTkFont(size=13),
        )
        self.bit_status_detail.grid(row=1, column=0, sticky="w", padx=12, pady=(0, 10))

        ctk.CTkLabel(right, text="Axis Control", font=ctk.CTkFont(size=18, weight="bold")).grid(
            row=1, column=0, sticky="w", padx=12, pady=(6, 6)
        )

        self.axis_frame = ctk.CTkFrame(right)
        self.axis_frame.grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 12))
        self.axis_frame.grid_columnconfigure(0, weight=1)
        self.axis_frame.grid_columnconfigure(1, weight=1)
        self.axis_frame.grid_columnconfigure(2, weight=1)

        self._build_axis_panel(col=0, name="Zoom", switch_scmd=SCMD_ZOOM_SWITCH, motion_cmd=CMD_ZOOM_POS)
        self._build_axis_panel(col=1, name="Focus", switch_scmd=SCMD_FOCUS_SWITCH, motion_cmd=CMD_FOCUS_POS)
        self._build_axis_panel(col=2, name="Iris", switch_scmd=SCMD_IRIS_SWITCH, motion_cmd=CMD_IRIS_POS)

        ctk.CTkLabel(right, text="TX/RX Log (frame-based)", font=ctk.CTkFont(size=18, weight="bold")).grid(
            row=3, column=0, sticky="w", padx=12, pady=(0, 6)
        )
        self.log_box = ctk.CTkTextbox(right, wrap="none", height=320)
        self.log_box.grid(row=4, column=0, sticky="nsew", padx=12, pady=(0, 12))
        self.log_box.configure(state="disabled")

        btns = ctk.CTkFrame(right, fg_color="transparent")
        btns.grid(row=5, column=0, sticky="w", padx=12, pady=(0, 12))
        ctk.CTkButton(btns, text="Clear Log", command=self._clear_log, fg_color="#555555").grid(row=0, column=0, padx=(0, 8))

        self._build_fuji_tab()

    def _build_axis_panel(self, col: int, name: str, switch_scmd: int, motion_cmd: int):
        frame = ctk.CTkFrame(self.axis_frame)
        frame.grid(row=0, column=col, padx=8, pady=10, sticky="ew")
        frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(frame, text=name, font=ctk.CTkFont(size=16, weight="bold")).grid(
            row=0, column=0, sticky="w", padx=10, pady=(10, 6)
        )

        src_var = ctk.StringVar(value="Camera")
        ctk.CTkOptionMenu(frame, values=["PC", "Camera", "Off"], variable=src_var).grid(
            row=1, column=0, padx=10, pady=6, sticky="ew"
        )

        def apply_src():
            if not self.worker.is_open():
                self._log("ERR", f"{name}: Not connected.")
                return
            sel = src_var.get()
            src_bits = SRC_PC if sel == "PC" else SRC_CAMERA if sel == "Camera" else SRC_OFF
            pkt = build_type_c_switch(switch_scmd, src_bits)
            self._send_frame(pkt, f"{name}_SRC_{sel}")

        ctk.CTkButton(frame, text="Apply Source", command=apply_src).grid(row=2, column=0, padx=10, pady=(0, 10), sticky="ew")

        slider = ctk.CTkSlider(frame, from_=0, to=60000, number_of_steps=60000)
        slider.set(30000)
        slider.grid(row=3, column=0, padx=10, pady=(6, 2), sticky="ew")

        val_lbl = ctk.CTkLabel(frame, text="Target: 30000")
        val_lbl.grid(row=4, column=0, padx=10, pady=(0, 6), sticky="w")

        follow_lbl = ctk.CTkLabel(frame, text="Follow: (n/a)")
        follow_lbl.grid(row=5, column=0, padx=10, pady=(0, 10), sticky="w")

        def on_slide(v):
            val_lbl.configure(text=f"Target: {int(float(v))}")

        slider.configure(command=on_slide)

        def send_pos():
            if not self.worker.is_open():
                self._log("ERR", f"{name}: Not connected.")
                return
            v = int(slider.get())
            pkt = build_type_b(motion_cmd, SUBCMD_C0, v)
            self._send_frame(pkt, f"{name}_POS({v})")

        ctk.CTkButton(frame, text="Send Position", command=send_pos).grid(row=6, column=0, padx=10, pady=(0, 10), sticky="ew")

        setattr(self, f"_{name.lower()}_follow_label", follow_lbl)
        setattr(self, f"_{name.lower()}_slider", slider)
        setattr(self, f"_{name.lower()}_src_var", src_var)

    def _build_fuji_tab(self):
        fuji_tab = self.tabview.tab("Fuji")
        fuji_tab.grid_columnconfigure(0, weight=0)
        fuji_tab.grid_columnconfigure(1, weight=1)
        fuji_tab.grid_rowconfigure(0, weight=1)
        fuji_left = ctk.CTkFrame(fuji_tab, corner_radius=12)
        fuji_left.grid(row=0, column=0, sticky="nsw", padx=12, pady=12)
        fuji_right = ctk.CTkFrame(fuji_tab, corner_radius=12)
        fuji_right.grid(row=0, column=1, sticky="nsew", padx=(0, 12), pady=12)
        fuji_right.grid_rowconfigure(4, weight=1)
        fuji_right.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(fuji_left, text="Fuji L10 Connection", font=ctk.CTkFont(size=18, weight="bold")).grid(
            row=0, column=0, sticky="w", padx=12, pady=(12, 6)
        )
        self.fuji_port_combo = ctk.CTkComboBox(fuji_left, values=["(refresh)"], width=340)
        self.fuji_port_combo.grid(row=1, column=0, padx=12, pady=6, sticky="w")
        fuji_btn_row = ctk.CTkFrame(fuji_left, fg_color="transparent")
        fuji_btn_row.grid(row=2, column=0, padx=12, pady=6, sticky="w")
        ctk.CTkButton(fuji_btn_row, text="Refresh", command=self._refresh_fuji_ports, width=160).grid(row=0, column=0, padx=(0, 8))
        self.fuji_connect_btn = ctk.CTkButton(fuji_btn_row, text="Connect", command=self._fuji_connect, width=160)
        self.fuji_connect_btn.grid(row=0, column=1)
        self.fuji_status_lbl = ctk.CTkLabel(fuji_left, text="Status: Disconnected")
        self.fuji_status_lbl.grid(row=3, column=0, sticky="w", padx=12, pady=(2, 6))
        self.fuji_lens_lbl = ctk.CTkLabel(fuji_left, text="Lens: (unknown)")
        self.fuji_lens_lbl.grid(row=4, column=0, sticky="w", padx=12, pady=(0, 10))
        fuji_toggles = ctk.CTkFrame(fuji_left)
        fuji_toggles.grid(row=5, column=0, padx=12, pady=6, sticky="ew")
        self.fuji_dtr_var = ctk.BooleanVar(value=True)
        self.fuji_dsr_var = ctk.BooleanVar(value=True)
        self.fuji_rts_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(fuji_toggles, text="DTR", variable=self.fuji_dtr_var, command=self._on_fuji_dtr_toggle).grid(
            row=0, column=0, padx=10, pady=(10, 2), sticky="w"
        )
        ctk.CTkCheckBox(
            fuji_toggles, text="DSR (alias DTR)", variable=self.fuji_dsr_var, command=self._on_fuji_dsr_toggle
        ).grid(row=1, column=0, padx=10, pady=(2, 2), sticky="w")
        ctk.CTkCheckBox(fuji_toggles, text="RTS", variable=self.fuji_rts_var, command=self._fuji_apply_modem_lines).grid(
            row=2, column=0, padx=10, pady=(2, 10), sticky="w"
        )
        ctk.CTkLabel(fuji_left, text="Manual Send (Hex)", font=ctk.CTkFont(size=16, weight="bold")).grid(
            row=6, column=0, sticky="w", padx=12, pady=(14, 6)
        )
        self.fuji_hex_entry = ctk.CTkEntry(fuji_left, placeholder_text="e.g. 00 01 00 DE")
        self.fuji_hex_entry.grid(row=7, column=0, padx=12, pady=6, sticky="ew")
        ctk.CTkButton(fuji_left, text="Send Hex", command=self._fuji_send_hex_entry).grid(row=8, column=0, padx=12, pady=6, sticky="ew")
        ctk.CTkLabel(fuji_left, text="Host control", font=ctk.CTkFont(size=16, weight="bold")).grid(
            row=9, column=0, sticky="w", padx=12, pady=(14, 6)
        )
        ctk.CTkButton(fuji_left, text="Switch 4 → Host (all)", command=self._fuji_switch4_host).grid(row=10, column=0, padx=12, pady=6, sticky="ew")
        ctk.CTkLabel(fuji_left, text="Link debug", font=ctk.CTkFont(size=16, weight="bold")).grid(
            row=11, column=0, sticky="w", padx=12, pady=(14, 6)
        )
        spam_row = ctk.CTkFrame(fuji_left, fg_color="transparent")
        spam_row.grid(row=12, column=0, padx=12, pady=6, sticky="ew")
        self.fuji_connect_spam_btn = ctk.CTkButton(
            spam_row, text="Start CONNECT spam", command=self._fuji_toggle_connect_spam, width=160
        )
        self.fuji_connect_spam_btn.grid(row=0, column=0, padx=(0, 8))
        ctk.CTkButton(spam_row, text="Send RESET pulse", command=self._fuji_send_reset_once, width=160).grid(row=0, column=1)
        ctk.CTkLabel(fuji_left, text="Spam interval (ms)").grid(row=13, column=0, padx=12, pady=(6, 2), sticky="w")
        self.fuji_spam_interval_entry = ctk.CTkEntry(fuji_left, placeholder_text="100")
        self.fuji_spam_interval_entry.grid(row=14, column=0, padx=12, pady=(0, 6), sticky="ew")
        self.fuji_spam_interval_entry.insert(0, str(self.fuji_connect_spam_interval_ms))
        auto_row = ctk.CTkFrame(fuji_left, fg_color="transparent")
        auto_row.grid(row=15, column=0, padx=12, pady=6, sticky="ew")
        self.fuji_auto_recovery_btn = ctk.CTkButton(
            auto_row, text="Start auto recovery", command=self._fuji_toggle_auto_recovery, width=160
        )
        self.fuji_auto_recovery_btn.grid(row=0, column=0, padx=(0, 8))
        self.fuji_auto_reset_entry = ctk.CTkEntry(auto_row, placeholder_text="reset every N", width=160)
        self.fuji_auto_reset_entry.grid(row=0, column=1)
        self.fuji_auto_reset_entry.insert(0, str(self.fuji_auto_reset_every))
        self.fuji_debug_status_lbl = ctk.CTkLabel(
            fuji_left,
            text="Debug: connect_sent=0 reset_sent=0 last_rx_func=--",
            font=ctk.CTkFont(size=12),
        )
        self.fuji_debug_status_lbl.grid(row=16, column=0, sticky="w", padx=12, pady=(2, 8))
        ctk.CTkLabel(fuji_left, text="Fuji startup/BIT", font=ctk.CTkFont(size=16, weight="bold")).grid(
            row=17, column=0, sticky="w", padx=12, pady=(8, 4)
        )
        self.fuji_sw4_lbl = ctk.CTkLabel(fuji_left, text="SW4: (unknown)")
        self.fuji_sw4_lbl.grid(row=18, column=0, sticky="w", padx=12, pady=(0, 2))
        fuji_ctl_row = ctk.CTkFrame(fuji_left, fg_color="transparent")
        fuji_ctl_row.grid(row=19, column=0, padx=12, pady=(0, 8), sticky="ew")
        ctk.CTkButton(fuji_ctl_row, text="Read SW4", command=self._fuji_read_switch4, width=160).grid(
            row=0, column=0, padx=(0, 8)
        )
        ctk.CTkButton(fuji_ctl_row, text="Run Fuji BIT", command=self._fuji_start_bit, width=160).grid(
            row=0, column=1
        )
        self.fuji_run_bit_on_connect_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            fuji_left,
            text="Run BIT on connect",
            variable=self.fuji_run_bit_on_connect_var,
        ).grid(row=20, column=0, sticky="w", padx=12, pady=(0, 8))

        self.fuji_bit_status_frame = ctk.CTkFrame(fuji_right, corner_radius=12, fg_color="#3a3a3a")
        self.fuji_bit_status_frame.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 8))
        self.fuji_bit_status_frame.grid_columnconfigure(0, weight=1)

        self.fuji_bit_status_title = ctk.CTkLabel(
            self.fuji_bit_status_frame,
            text="Connection & Control: NOT RUN (Fuji)",
            font=ctk.CTkFont(size=18, weight="bold"),
        )
        self.fuji_bit_status_title.grid(row=0, column=0, sticky="w", padx=12, pady=(10, 2))

        self.fuji_bit_status_detail = ctk.CTkLabel(
            self.fuji_bit_status_frame,
            text="Connect to run automatic BIT (connect, take host control, sweep axes).",
            font=ctk.CTkFont(size=13),
        )
        self.fuji_bit_status_detail.grid(row=1, column=0, sticky="w", padx=12, pady=(0, 10))

        ctk.CTkLabel(fuji_right, text="Fuji L10 Axis Control", font=ctk.CTkFont(size=18, weight="bold")).grid(
            row=1, column=0, sticky="w", padx=12, pady=(6, 6)
        )
        self.fuji_axis_frame = ctk.CTkFrame(fuji_right)
        self.fuji_axis_frame.grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 12))
        self.fuji_axis_frame.grid_columnconfigure(0, weight=1)
        self.fuji_axis_frame.grid_columnconfigure(1, weight=1)
        self.fuji_axis_frame.grid_columnconfigure(2, weight=1)
        self._build_fuji_axis_panel(col=0, name="Iris", req_func=build_position_request_iris, ctrl_func=build_iris_control)
        self._build_fuji_axis_panel(col=1, name="Zoom", req_func=build_position_request_zoom, ctrl_func=build_zoom_control)
        self._build_fuji_axis_panel(col=2, name="Focus", req_func=build_position_request_focus, ctrl_func=build_focus_control)
        ctk.CTkLabel(fuji_right, text="Fuji TX/RX Log", font=ctk.CTkFont(size=18, weight="bold")).grid(
            row=3, column=0, sticky="w", padx=12, pady=(0, 6)
        )
        self.fuji_log_box = ctk.CTkTextbox(fuji_right, wrap="none", height=320)
        self.fuji_log_box.grid(row=4, column=0, sticky="nsew", padx=12, pady=(0, 12))
        self.fuji_log_box.configure(state="disabled")
        fuji_btns = ctk.CTkFrame(fuji_right, fg_color="transparent")
        fuji_btns.grid(row=5, column=0, sticky="w", padx=12, pady=(0, 12))
        ctk.CTkButton(fuji_btns, text="Clear Log", command=self._fuji_clear_log, fg_color="#555555").grid(row=0, column=0, padx=(0, 8))
        self._refresh_fuji_ports()

    def _build_fuji_axis_panel(self, col: int, name: str, req_func, ctrl_func):
        frame = ctk.CTkFrame(self.fuji_axis_frame)
        frame.grid(row=0, column=col, padx=8, pady=10, sticky="ew")
        frame.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(frame, text=name, font=ctk.CTkFont(size=16, weight="bold")).grid(
            row=0, column=0, sticky="w", padx=10, pady=(10, 6)
        )
        src_var = ctk.StringVar(value="PC")
        ctk.CTkOptionMenu(frame, values=["PC", "Camera", "Off"], variable=src_var).grid(
            row=1, column=0, padx=10, pady=6, sticky="ew"
        )

        def apply_src():
            if not self.fuji_worker.is_open():
                self._fuji_log("ERR", f"{name}: Not connected.")
                return
            sel = src_var.get()
            bits = int(self.fuji_sw4_desired_bits)
            if name == "Focus":
                mask = 0x01
            elif name == "Zoom":
                mask = 0x02
            else:
                mask = 0x04
            # L10 switch4: bit=0 host, bit=1 local/camera.
            if sel == "Off":
                bits = SW4_RELEASE_ALL
            elif sel == "PC":
                bits &= ~mask
            else:
                bits |= mask
            self.fuji_sw4_desired_bits = bits & 0xFF
            pkt = build_switch4_control(self.fuji_sw4_desired_bits)
            self.fuji_worker.send(pkt)
            self._fuji_log("TX", f"{name}_SRC_{sel}: {fuji_hexdump(pkt)}")
            self._fuji_read_switch4()

        ctk.CTkButton(frame, text="Apply Source", command=apply_src).grid(
            row=2, column=0, padx=10, pady=(0, 10), sticky="ew"
        )
        slider = ctk.CTkSlider(frame, from_=0, to=65535, number_of_steps=65535)
        slider.set(32768)
        slider.grid(row=3, column=0, padx=10, pady=(6, 2), sticky="ew")
        val_lbl = ctk.CTkLabel(frame, text="Target: 32768")
        val_lbl.grid(row=4, column=0, padx=10, pady=(0, 6), sticky="w")
        follow_lbl = ctk.CTkLabel(frame, text="Position: (n/a)")
        follow_lbl.grid(row=5, column=0, padx=10, pady=(0, 6), sticky="w")
        def on_slide(v):
            val_lbl.configure(text=f"Target: {int(float(v))}")
        slider.configure(command=on_slide)
        def request_pos():
            if not self.fuji_worker.is_open():
                self._fuji_log("ERR", f"{name}: Not connected.")
                return
            pkt = req_func()
            self.fuji_worker.send(pkt)
            self._fuji_log("TX", f"{name}_REQ: {fuji_hexdump(pkt)}")
        def send_pos():
            if not self.fuji_worker.is_open():
                self._fuji_log("ERR", f"{name}: Not connected.")
                return
            v = int(slider.get())
            pkt = ctrl_func(v)
            self.fuji_worker.send(pkt)
            self._fuji_log("TX", f"{name}_CTRL({v}): {fuji_hexdump(pkt)}")
        ctk.CTkButton(frame, text="Request position", command=request_pos).grid(row=6, column=0, padx=10, pady=(0, 6), sticky="ew")
        ctk.CTkButton(frame, text="Send position", command=send_pos).grid(row=7, column=0, padx=10, pady=(0, 10), sticky="ew")
        setattr(self, f"_fuji_{name.lower()}_slider", slider)
        setattr(self, f"_fuji_{name.lower()}_follow_label", follow_lbl)
        setattr(self, f"_fuji_{name.lower()}_src_var", src_var)

    # ---------- Status panel helpers ----------
    def _set_bit_status(self, state: str, detail: str):
        if state == "idle":
            color = "#3a3a3a"
            title = "Connection & Control: NOT RUN"
        elif state == "running":
            color = "#5c4b00"
            title = "Connection & Control: RUNNING BIT..."
        elif state == "pass":
            color = "#0f5a20"
            title = "Connection & Control: COMPLETE"
        else:
            color = "#6a1b1b"
            title = "Connection & Control: FAILED"

        self.bit_status_frame.configure(fg_color=color)
        self.bit_status_title.configure(text=title)
        self.bit_status_detail.configure(text=detail)

    def _ui_set_bit_status(self, state: str, detail: str):
        self.after(0, lambda: self._set_bit_status(state, detail))

    def _set_fuji_bit_status(self, state: str, detail: str):
        if state == "idle":
            color = "#3a3a3a"
            title = "Connection & Control: NOT RUN (Fuji)"
        elif state == "running":
            color = "#5c4b00"
            title = "Connection & Control: RUNNING BIT... (Fuji)"
        elif state == "pass":
            color = "#0f5a20"
            title = "Connection & Control: COMPLETE (Fuji)"
        else:
            color = "#6a1b1b"
            title = "Connection & Control: FAILED (Fuji)"

        self.fuji_bit_status_frame.configure(fg_color=color)
        self.fuji_bit_status_title.configure(text=title)
        self.fuji_bit_status_detail.configure(text=detail)

    def _fuji_ui_set_bit_status(self, state: str, detail: str):
        self.after(0, lambda: self._set_fuji_bit_status(state, detail))

    # ---------- Gamepad UI handlers ----------
    def _on_deadband_change(self, v):
        self.gamepad_cfg.zoom_deadband = float(v)
        if hasattr(self, "gamepad_runner"):
            self.gamepad_runner.set_deadband(float(v))
        self.deadband_lbl.configure(text=f"Deadband: {self.gamepad_cfg.zoom_deadband:.2f}")

    def _toggle_gamepad(self):
        self.gamepad_cfg.enabled = bool(self.gamepad_enabled_var.get())
        if self.gamepad_cfg.enabled:
            if self._gamepad_can_drive_active_tab():
                self._start_gamepad()
            else:
                self.gamepad_state_lbl.configure(text="State: enabled (starts when active tab is ready)")
        else:
            self._stop_gamepad()
            self.gamepad_state_lbl.configure(text="State: disabled")

    def _start_gamepad(self):
        if not self.gamepad_cfg.enabled:
            return
        if not PYGAME_OK:
            self._log("ERR", "pygame not available. Install with: pip install pygame")
            self.gamepad_enabled_var.set(False)
            self.gamepad_cfg.enabled = False
            self.gamepad_state_lbl.configure(text="State: pygame missing")
            return
        if self.gamepad_runner.is_running():
            return
        try:
            self.gamepad_runner.start()
            self.gamepad_state_lbl.configure(text="State: starting...")
        except Exception as e:
            self._log("ERR", str(e))
            self.gamepad_state_lbl.configure(text="State: pygame missing")

    def _stop_gamepad(self):
        self.gamepad_runner.stop()
        self.gamepad_state_lbl.configure(text="State: stopped")

    def _poll_gamepad_state(self):
        if self.gamepad_runner.is_running() and self.gamepad_runner.is_connected():
            name = self.gamepad_runner.device_name()
            if name:
                self.gamepad_state_lbl.configure(text=f"State: connected ({name})")
        elif self.gamepad_runner.is_running():
            self.gamepad_state_lbl.configure(text="State: starting...")
        self.after(200, self._poll_gamepad_state)

    # ---------- Connection ----------
    def _refresh_ports(self):
        ports = list_com_ports()
        if not ports:
            ports = ["(no COM ports found)"]
        self.port_combo.configure(values=ports)
        self.port_combo.set(ports[0])

    def _connect(self):
        if self.worker.is_open():
            self._disconnect()
            return

        selected = self.port_combo.get().strip()
        if selected.startswith("(no COM"):
            self._log("ERR", "No COM port available.")
            return

        port = extract_port_name(selected)
        cfg = SerialConfig(port=port, baud=BAUD, dtr=self.dtr_var.get(), rts=self.rts_var.get())

        try:
            self.worker.open(cfg)
            self.status_lbl.configure(text=f"Status: Connected to {port} @ {BAUD} 8E1")
            self.connect_btn.configure(text="Disconnect")
            self._log("INFO", f"Opened {port} @ {BAUD}, 8E1, flow=None")
            self._apply_modem_lines()
            self._start_bit()
        except Exception as e:
            self._log("ERR", f"Open failed: {e}")
            self.status_lbl.configure(text="Status: Disconnected")
            self._set_bit_status("fail", f"Open failed: {e}")

    def _disconnect(self):
        self._stop_gamepad()
        self._stop_bit()
        try:
            self.worker.close()
        except Exception:
            pass
        self.status_lbl.configure(text="Status: Disconnected")
        self.connect_btn.configure(text="Connect")
        self.lens_lbl.configure(text="Lens: (unknown)")
        self._set_bit_status("idle", "Connect to run automatic BIT (init, take control, sweep axes).")
        self.bit_passed = False
        self.gamepad_state_lbl.configure(text="State: (not started)")
        self._log("INFO", "Port closed.")

    def _apply_modem_lines(self):
        if not self.worker.is_open():
            return
        try:
            self.worker.set_dtr(self.dtr_var.get())
            self.worker.set_rts(self.rts_var.get())
            self._log(
                "INFO",
                f"Lines: DTR/DSR_ALIAS={'ON' if self.dtr_var.get() else 'OFF'}, RTS={'ON' if self.rts_var.get() else 'OFF'}",
            )
        except Exception as e:
            self._log("ERR", f"Set lines failed: {e}")

    def _on_dtr_toggle(self):
        if self._modem_ui_syncing:
            return
        self._modem_ui_syncing = True
        self.dsr_var.set(self.dtr_var.get())
        self._modem_ui_syncing = False
        self._apply_modem_lines()

    def _on_dsr_toggle(self):
        if self._modem_ui_syncing:
            return
        self._modem_ui_syncing = True
        self.dtr_var.set(self.dsr_var.get())
        self._modem_ui_syncing = False
        self._apply_modem_lines()

    # ---------- Manual send ----------
    def _send_frame(self, frame: bytes, name: str):
        if not self.worker.is_open():
            self._log("ERR", "Not connected.")
            return
        try:
            self.worker.send(frame)
            self._log("TX", f"{name}: {hexdump(frame)}")
        except Exception as e:
            self._log("ERR", f"Send failed: {e}")

    def _send_hex_entry(self):
        s = self.hex_entry.get().strip()
        if not s:
            return
        if not HEX_RE.match(s):
            self._log("ERR", "Hex input contains invalid characters.")
            return
        parts = s.split()
        try:
            b = bytes(int(p, 16) for p in parts)
        except ValueError:
            self._log("ERR", "Could not parse hex bytes.")
            return
        self._send_frame(b, "MANUAL")

    # ---------- BIT ----------
    def _start_bit(self):
        self.bit_passed = False
        self.bit_runner.start()

    def _stop_bit(self):
        self.bit_runner.stop()

    def _mark_bit_passed(self):
        self.bit_passed = True
        if self.gamepad_cfg.enabled and self.gamepad_enabled_var.get():
            self.after(0, self._start_gamepad)
        else:
            self.after(0, lambda: self.gamepad_state_lbl.configure(text="State: disabled"))

    def _mark_bit_failed(self, _reason: str):
        self.bit_passed = False

    def _ui_set_lens_name(self, name: str):
        self.after(0, lambda: self._set_lens_name(name))

    def _set_lens_name(self, name: str):
        self.lens_name = name
        self.lens_lbl.configure(text=f"Lens: {name}")

    def _ui_set_targets(self, z: int, f: int, i: int):
        self.after(0, lambda: self._set_targets(z, f, i))

    def _set_targets(self, z: int, f: int, i: int):
        self.zoom_target = int(z)
        self.focus_target = int(f)
        self.iris_target = int(i)
        getattr(self, "_zoom_slider").set(self.zoom_target)
        getattr(self, "_focus_slider").set(self.focus_target)
        getattr(self, "_iris_slider").set(self.iris_target)

    def _gamepad_active_tab_name(self) -> str:
        try:
            return str(self.tabview.get())
        except Exception:
            return "Canon"

    def _gamepad_can_drive_active_tab(self) -> bool:
        tab = self._gamepad_active_tab_name()
        if tab == "Fuji":
            return self.fuji_worker.is_open()
        return self.worker.is_open() and self.bit_passed

    def _gamepad_get_follow_active_tab(self):
        tab = self._gamepad_active_tab_name()
        if tab == "Fuji":
            return (self.fuji_zoom_pos, self.fuji_focus_pos, self.fuji_iris_pos)
        return (self.zoom_follow, self.focus_follow, self.iris_follow)

    def _ui_set_gamepad_targets_active_tab(self, z: int, f: int, i: int):
        self.after(0, lambda: self._set_gamepad_targets_active_tab(z, f, i))

    def _set_gamepad_targets_active_tab(self, z: int, f: int, i: int):
        tab = self._gamepad_active_tab_name()
        if tab == "Fuji":
            if hasattr(self, "_fuji_zoom_slider"):
                getattr(self, "_fuji_zoom_slider").set(int(z))
            if hasattr(self, "_fuji_focus_slider"):
                getattr(self, "_fuji_focus_slider").set(int(f))
            if hasattr(self, "_fuji_iris_slider"):
                getattr(self, "_fuji_iris_slider").set(int(i))
            return
        self._set_targets(int(z), int(f), int(i))

    def _gamepad_send_axis_active_tab(self, axis: str, value: int):
        v = int(max(0, min(65535, value)))
        tab = self._gamepad_active_tab_name()

        if tab == "Fuji":
            if not self.fuji_worker.is_open():
                return
            if axis == "zoom":
                pkt = build_zoom_control(v)
            elif axis == "focus":
                pkt = build_focus_control(v)
            else:
                pkt = build_iris_control(v)
            self.fuji_worker.send(pkt)
            self._fuji_bit_log("TX", f"GAMEPAD_{axis.upper()}({v}): {fuji_hexdump(pkt)}")
            return

        if not self.worker.is_open() or not self.bit_passed:
            return
        if axis == "zoom":
            pkt = build_type_b(CMD_ZOOM_POS, SUBCMD_C0, min(v, 60000))
        elif axis == "focus":
            pkt = build_type_b(CMD_FOCUS_POS, SUBCMD_C0, min(v, 60000))
        else:
            pkt = build_type_b(CMD_IRIS_POS, SUBCMD_C0, min(v, 60000))
        self.worker.send(pkt)

    def _refresh_fuji_ports(self):
        ports = list_com_ports()
        if not ports:
            ports = ["(no COM ports found)"]
        self.fuji_port_combo.configure(values=ports)
        self.fuji_port_combo.set(ports[0])

    def _fuji_connect(self):
        if self.fuji_worker.is_open():
            self._fuji_disconnect()
            return
        selected = self.fuji_port_combo.get().strip()
        if selected.startswith("(no COM"):
            self._fuji_log("ERR", "No COM port available.")
            return
        port = extract_port_name(selected)
        cfg = SerialConfig(
            port=port,
            baud=FUJI_BAUD,
            dtr=self.fuji_dtr_var.get(),
            rts=self.fuji_rts_var.get(),
            bytesize=FUJI_BITS,
            parity=FUJI_PARITY,
            stopbits=FUJI_STOP,
        )
        try:
            self.fuji_worker.open(cfg)
            self.fuji_status_lbl.configure(text=f"Status: Connected to {port} @ {FUJI_BAUD} 8N1")
            self.fuji_connect_btn.configure(text="Disconnect")
            self._fuji_log("INFO", f"Opened {port} @ {FUJI_BAUD} 8N1")
            self.fuji_lens_name = ""
            self.fuji_sw4_desired_bits = SW4_HOST_ALL
            self.fuji_lens_lbl.configure(text="Lens: (unknown)")
            self._fuji_apply_modem_lines()
            # Fuji app style startup: connect (x2), discovery burst, then assert host (SW4=F8).
            self._fuji_send_connect_once()
            self._fuji_send_connect_once()
            self._fuji_send_discovery_burst()
            self._fuji_switch4_host()
            self._fuji_start_name_poll()
            self._fuji_start_host_keepalive()
            self._fuji_read_switch4()
            run_bit = True
            if hasattr(self, "fuji_run_bit_on_connect_var"):
                run_bit = bool(self.fuji_run_bit_on_connect_var.get())
            if run_bit:
                self._fuji_start_bit()
            else:
                self._set_fuji_bit_status("idle", "BIT skipped (Run BIT on connect is off).")
                self._fuji_log("INFO", "BIT auto-run skipped (Run BIT on connect is off).")
            if self.gamepad_cfg.enabled and self.gamepad_enabled_var.get():
                self.after(0, self._start_gamepad)
        except Exception as e:
            self._fuji_log("ERR", f"Open failed: {e}")
            self.fuji_status_lbl.configure(text="Status: Disconnected")
            self._set_fuji_bit_status("fail", f"Open failed: {e}")

    def _fuji_disconnect(self):
        self._fuji_stop_connect_spam()
        self._fuji_stop_auto_recovery()
        self._fuji_stop_name_poll()
        self._fuji_stop_host_keepalive()
        self._fuji_stop_bit()
        try:
            self.fuji_worker.close()
        except Exception:
            pass
        self.fuji_status_lbl.configure(text="Status: Disconnected")
        self.fuji_connect_btn.configure(text="Connect")
        self.fuji_lens_lbl.configure(text="Lens: (unknown)")
        self.fuji_lens_name = ""
        self.fuji_sw4_desired_bits = SW4_HOST_ALL
        self.fuji_iris_pos = self.fuji_zoom_pos = self.fuji_focus_pos = None
        self.fuji_last_rx_func = "--"
        self.fuji_sw4_bits = None
        self.fuji_modem_state = {"dsr": False, "cts": False, "ri": False, "cd": False}
        if hasattr(self, "fuji_sw4_lbl"):
            self.fuji_sw4_lbl.configure(text="SW4: (unknown)")
        self._set_fuji_bit_status("idle", "Connect to run automatic BIT (connect, take host control, sweep axes).")
        self._update_fuji_debug_status()
        self._fuji_log("INFO", "Port closed.")

    def _fuji_apply_modem_lines(self):
        if not self.fuji_worker.is_open():
            return
        try:
            self.fuji_worker.set_dtr(self.fuji_dtr_var.get())
            self.fuji_worker.set_rts(self.fuji_rts_var.get())
            self._fuji_log(
                "INFO",
                f"Lines: DTR/DSR_ALIAS={'ON' if self.fuji_dtr_var.get() else 'OFF'}, RTS={'ON' if self.fuji_rts_var.get() else 'OFF'}",
            )
        except Exception as e:
            self._fuji_log("ERR", f"Set lines failed: {e}")

    def _on_fuji_dtr_toggle(self):
        if self._modem_ui_syncing:
            return
        self._modem_ui_syncing = True
        self.fuji_dsr_var.set(self.fuji_dtr_var.get())
        self._modem_ui_syncing = False
        self._fuji_apply_modem_lines()

    def _on_fuji_dsr_toggle(self):
        if self._modem_ui_syncing:
            return
        self._modem_ui_syncing = True
        self.fuji_dtr_var.set(self.fuji_dsr_var.get())
        self._modem_ui_syncing = False
        self._fuji_apply_modem_lines()

    def _fuji_send_hex_entry(self):
        s = self.fuji_hex_entry.get().strip()
        if not s:
            return
        if not HEX_RE.match(s):
            self._fuji_log("ERR", "Hex input contains invalid characters.")
            return
        parts = s.split()
        try:
            b = bytes(int(p, 16) for p in parts)
        except ValueError:
            self._fuji_log("ERR", "Could not parse hex bytes.")
            return
        if not self.fuji_worker.is_open():
            self._fuji_log("ERR", "Not connected.")
            return
        try:
            self.fuji_worker.send(b)
            self._fuji_log("TX", f"MANUAL: {fuji_hexdump(b)}")
        except Exception as e:
            self._fuji_log("ERR", f"Send failed: {e}")

    def _fuji_switch4_host(self):
        if not self.fuji_worker.is_open():
            self._fuji_log("ERR", "Not connected.")
            return
        self.fuji_sw4_desired_bits = SW4_HOST_ALL
        pkt = build_switch4_control(SW4_HOST_ALL)
        self.fuji_worker.send(pkt)
        self._fuji_log("TX", f"Switch4 Host: {fuji_hexdump(pkt)}")

    def _fuji_read_switch4(self):
        if not self.fuji_worker.is_open():
            self._fuji_log("ERR", "Not connected.")
            return
        pkt = build_switch4_position_request()
        self.fuji_worker.send(pkt)
        self._fuji_log("TX", f"Switch4 Pos Req: {fuji_hexdump(pkt)}")

    def _fuji_sw4_text(self, bits: int) -> str:
        f = "HOST" if (bits & 0x01) == 0 else "LOCAL"
        z = "HOST" if (bits & 0x02) == 0 else "LOCAL"
        i = "HOST" if (bits & 0x04) == 0 else "CAMERA"
        ff = "HOST" if (bits & 0x10) == 0 else "LOCAL"
        return f"SW4: F={f} Z={z} I={i} FF={ff} (0x{bits:02X})"

    def _fuji_sync_source_ui_from_sw4(self, bits: int):
        # Keep dropdowns user-driven. Continuous SW4 polling can briefly report
        # local/camera and would otherwise force UI selections to jump.
        _ = bits

    def _fuji_start_bit(self):
        if self.fuji_bit_runner.is_running():
            return
        if not self.fuji_worker.is_open():
            self._fuji_log("ERR", "BIT: Not connected.")
            return
        self.fuji_bit_runner.start()

    def _fuji_stop_bit(self):
        self.fuji_bit_runner.stop()

    def _fuji_bit_log(self, tag: str, msg: str):
        self.after(0, lambda: self._fuji_log(tag, msg))

    def _fuji_bit_passed(self):
        detail = f"Connection and control complete. Lens ID: {self.fuji_lens_name or '(unknown lens)'}"
        self._fuji_ui_set_bit_status("pass", detail)

    def _fuji_bit_failed(self, reason: str):
        self._fuji_ui_set_bit_status("fail", reason)

    def _fuji_bit_send_connect(self):
        if not self.fuji_worker.is_open():
            raise RuntimeError("Not connected")
        pkt = build_connect(connection_request=True)
        self.fuji_worker.send(pkt)
        self.fuji_connect_sent_count += 1
        self.after(0, self._update_fuji_debug_status)
        self._fuji_bit_log("TX", f"CONNECT: {fuji_hexdump(pkt)}")

    def _fuji_bit_switch4_host(self):
        if not self.fuji_worker.is_open():
            raise RuntimeError("Not connected")
        pkt = build_switch4_control(SW4_HOST_ALL)
        self.fuji_worker.send(pkt)
        self._fuji_bit_log("TX", f"Switch4 Host: {fuji_hexdump(pkt)}")

    def _fuji_bit_read_sw4(self):
        if not self.fuji_worker.is_open():
            raise RuntimeError("Not connected")
        pkt = build_switch4_position_request()
        self.fuji_worker.send(pkt)
        self._fuji_bit_log("TX", f"Switch4 Pos Req: {fuji_hexdump(pkt)}")

    def _fuji_bit_send_axis_control(self, axis: str, value: int):
        v = max(0, min(65535, int(value)))
        if axis == "Iris":
            pkt = build_iris_control(v)
        elif axis == "Zoom":
            pkt = build_zoom_control(v)
        else:
            pkt = build_focus_control(v)
        self.fuji_worker.send(pkt)
        self._fuji_bit_log("TX", f"BIT_{axis}_CTRL({v}): {fuji_hexdump(pkt)}")

    def _fuji_bit_request_axis_position(self, axis: str):
        if axis == "Iris":
            pkt = build_position_request_iris()
        elif axis == "Zoom":
            pkt = build_position_request_zoom()
        else:
            pkt = build_position_request_focus()
        self.fuji_worker.send(pkt)
        self._fuji_bit_log("TX", f"BIT_{axis}_REQ: {fuji_hexdump(pkt)}")

    def _fuji_send_host_keepalive_once(self, log: bool = False):
        if not self.fuji_worker.is_open():
            return
        pkt = build_switch4_control(SW4_HOST_ALL)
        self.fuji_worker.send(pkt)
        if log:
            self._fuji_log("TX", f"Switch4 Host keepalive: {fuji_hexdump(pkt)}")

    def _fuji_start_host_keepalive(self):
        self._fuji_stop_host_keepalive()
        if not self.fuji_host_keepalive_enabled:
            return
        self.fuji_host_keepalive_tick_count = 0
        self.fuji_poll_idx = 0
        self._fuji_host_keepalive_tick()

    def _fuji_stop_host_keepalive(self):
        if self.fuji_host_keepalive_after_id is not None:
            try:
                self.after_cancel(self.fuji_host_keepalive_after_id)
            except Exception:
                pass
            self.fuji_host_keepalive_after_id = None

    def _fuji_host_keepalive_tick(self):
        if not self.fuji_worker.is_open():
            self._fuji_stop_host_keepalive()
            return
        try:
            # Periodically re-assert desired SW4 ownership so control mode
            # does not drift back to local/camera.
            if self.fuji_host_keepalive_tick_count % 5 == 0:
                sw4_pkt = build_switch4_control(int(self.fuji_sw4_desired_bits) & 0xFF)
                self.fuji_worker.send(sw4_pkt)
            func = self.fuji_poll_seq[self.fuji_poll_idx]
            self.fuji_poll_idx = (self.fuji_poll_idx + 1) % len(self.fuji_poll_seq)
            pkt = build_request(func)
            self.fuji_worker.send(pkt)
            self.fuji_host_keepalive_tick_count += 1
            if self.fuji_host_keepalive_tick_count % 20 == 0:
                self._fuji_log("INFO", "Fuji polling keepalive active.")
        except Exception as e:
            self._fuji_log("ERR", f"Host keepalive failed: {e}")
            self._fuji_stop_host_keepalive()
            return
        self.fuji_host_keepalive_after_id = self.after(
            self.fuji_host_keepalive_interval_ms, self._fuji_host_keepalive_tick
        )

    def _fuji_send_discovery_burst(self):
        if not self.fuji_worker.is_open():
            return
        # Match observed Fuji app startup requests.
        for func in (0x10, 0x11, 0x12, 0x13, 0x14, 0x15, 0x16, 0x17):
            pkt = build_request(func)
            self.fuji_worker.send(pkt)
        self._fuji_log("INFO", "Discovery burst sent (10h..17h).")

    def _fuji_send_connect_once(self):
        if not self.fuji_worker.is_open():
            self._fuji_log("ERR", "Not connected.")
            return
        pkt = build_connect(connection_request=True)
        self.fuji_worker.send(pkt)
        self.fuji_connect_sent_count += 1
        self._update_fuji_debug_status()
        self._fuji_log("TX", f"CONNECT: {fuji_hexdump(pkt)}")

    def _fuji_send_reset_once(self):
        if not self.fuji_worker.is_open():
            self._fuji_log("ERR", "Not connected.")
            return
        pkt = build_connect(connection_request=False)
        self.fuji_worker.send(pkt)
        self.fuji_reset_sent_count += 1
        self._update_fuji_debug_status()
        self._fuji_log("TX", f"RESET_REQ: {fuji_hexdump(pkt)}")

    def _fuji_toggle_connect_spam(self):
        if self.fuji_connect_spam_enabled:
            self._fuji_stop_connect_spam()
            return
        if self.fuji_auto_recovery_enabled:
            self._fuji_stop_auto_recovery()
        if not self.fuji_worker.is_open():
            self._fuji_log("ERR", "Not connected.")
            return
        s = self.fuji_spam_interval_entry.get().strip()
        try:
            iv = int(s)
        except Exception:
            iv = self.fuji_connect_spam_interval_ms
        self.fuji_connect_spam_interval_ms = max(20, min(2000, iv))
        self.fuji_connect_spam_enabled = True
        self.fuji_connect_spam_btn.configure(text="Stop CONNECT spam")
        self._fuji_log("INFO", f"CONNECT spam started ({self.fuji_connect_spam_interval_ms} ms)")
        self._fuji_connect_spam_tick()

    def _fuji_stop_connect_spam(self):
        self.fuji_connect_spam_enabled = False
        if self.fuji_connect_spam_after_id is not None:
            try:
                self.after_cancel(self.fuji_connect_spam_after_id)
            except Exception:
                pass
            self.fuji_connect_spam_after_id = None
        if hasattr(self, "fuji_connect_spam_btn"):
            self.fuji_connect_spam_btn.configure(text="Start CONNECT spam")

    def _fuji_toggle_auto_recovery(self):
        if self.fuji_auto_recovery_enabled:
            self._fuji_stop_auto_recovery()
            return
        if self.fuji_connect_spam_enabled:
            self._fuji_stop_connect_spam()
        if not self.fuji_worker.is_open():
            self._fuji_log("ERR", "Not connected.")
            return
        s_iv = self.fuji_spam_interval_entry.get().strip()
        try:
            iv = int(s_iv)
        except Exception:
            iv = self.fuji_connect_spam_interval_ms
        self.fuji_connect_spam_interval_ms = max(20, min(2000, iv))

        s_n = self.fuji_auto_reset_entry.get().strip()
        try:
            n = int(s_n)
        except Exception:
            n = self.fuji_auto_reset_every
        self.fuji_auto_reset_every = max(1, min(500, n))

        self.fuji_auto_connect_count = 0
        self.fuji_auto_recovery_enabled = True
        self.fuji_auto_recovery_btn.configure(text="Stop auto recovery")
        self._fuji_log(
            "INFO",
            f"Auto recovery started ({self.fuji_connect_spam_interval_ms} ms, reset every {self.fuji_auto_reset_every} connects)",
        )
        self._fuji_auto_recovery_tick()

    def _fuji_stop_auto_recovery(self):
        self.fuji_auto_recovery_enabled = False
        if self.fuji_auto_recovery_after_id is not None:
            try:
                self.after_cancel(self.fuji_auto_recovery_after_id)
            except Exception:
                pass
            self.fuji_auto_recovery_after_id = None
        if hasattr(self, "fuji_auto_recovery_btn"):
            self.fuji_auto_recovery_btn.configure(text="Start auto recovery")

    def _fuji_auto_recovery_tick(self):
        if not self.fuji_auto_recovery_enabled:
            return
        if not self.fuji_worker.is_open():
            self._fuji_log("WARN", "Auto recovery stopped (port closed)")
            self._fuji_stop_auto_recovery()
            return
        try:
            self._fuji_send_connect_once()
            self.fuji_auto_connect_count += 1
            if self.fuji_auto_connect_count % self.fuji_auto_reset_every == 0:
                self._fuji_send_reset_once()
        except Exception as e:
            self._fuji_log("ERR", f"Auto recovery send failed: {e}")
            self._fuji_stop_auto_recovery()
            return
        self.fuji_auto_recovery_after_id = self.after(self.fuji_connect_spam_interval_ms, self._fuji_auto_recovery_tick)

    def _fuji_connect_spam_tick(self):
        if not self.fuji_connect_spam_enabled:
            return
        if not self.fuji_worker.is_open():
            self._fuji_log("WARN", "CONNECT spam stopped (port closed)")
            self._fuji_stop_connect_spam()
            return
        try:
            self._fuji_send_connect_once()
        except Exception as e:
            self._fuji_log("ERR", f"CONNECT spam send failed: {e}")
            self._fuji_stop_connect_spam()
            return
        self.fuji_connect_spam_after_id = self.after(self.fuji_connect_spam_interval_ms, self._fuji_connect_spam_tick)

    def _fuji_log(self, tag: str, msg: str):
        ts = time.strftime("%H:%M:%S")
        line = f"[{ts}] {tag}: {msg}\n"
        self.fuji_log_box.configure(state="normal")
        self.fuji_log_box.insert("end", line)
        self.fuji_log_box.see("end")
        self.fuji_log_box.configure(state="disabled")

    def _fuji_clear_log(self):
        self.fuji_log_box.configure(state="normal")
        self.fuji_log_box.delete("1.0", "end")
        self.fuji_log_box.configure(state="disabled")

    def _poll_fuji_modem_status(self):
        try:
            self.fuji_modem_state = self.fuji_worker.get_modem_status()
            self._update_fuji_debug_status()
        except Exception:
            pass
        self.after(200, self._poll_fuji_modem_status)

    def _update_fuji_debug_status(self):
        if hasattr(self, "fuji_debug_status_lbl"):
            dsr = "1" if self.fuji_modem_state.get("dsr", False) else "0"
            cts = "1" if self.fuji_modem_state.get("cts", False) else "0"
            ri = "1" if self.fuji_modem_state.get("ri", False) else "0"
            cd = "1" if self.fuji_modem_state.get("cd", False) else "0"
            self.fuji_debug_status_lbl.configure(
                text=(
                    f"Debug: connect_sent={self.fuji_connect_sent_count} "
                    f"reset_sent={self.fuji_reset_sent_count} "
                    f"last_rx_func={self.fuji_last_rx_func} "
                    f"modem[DSR={dsr} CTS={cts} RI={ri} CD={cd}]"
                )
            )

    def _fuji_request_lens_name_2(self):
        if self.fuji_worker.is_open():
            self.fuji_worker.send(build_lens_name_request(first_half=False))
            self._fuji_log("TX", "LENS_NAME_2 request")

    def _fuji_start_name_poll(self):
        self._fuji_stop_name_poll()
        self.fuji_name_poll_attempts = 0
        self._fuji_name_poll_tick()

    def _fuji_stop_name_poll(self):
        if self.fuji_name_poll_after_id is not None:
            try:
                self.after_cancel(self.fuji_name_poll_after_id)
            except Exception:
                pass
            self.fuji_name_poll_after_id = None

    def _fuji_name_poll_tick(self):
        if not self.fuji_worker.is_open():
            self._fuji_stop_name_poll()
            return
        if self.fuji_lens_name:
            self._fuji_stop_name_poll()
            return
        if self.fuji_name_poll_attempts >= self.fuji_name_poll_max_attempts:
            self._fuji_log("WARN", "Lens name read timed out.")
            self._fuji_stop_name_poll()
            return
        self.fuji_name_poll_attempts += 1
        try:
            self.fuji_worker.send(build_lens_name_request(first_half=True))
            self._fuji_log("TX", "LENS_NAME_1 request")
        except Exception as e:
            self._fuji_log("ERR", f"LENS_NAME_1 send failed: {e}")
            self._fuji_stop_name_poll()
            return
        self.fuji_name_poll_after_id = self.after(self.fuji_name_poll_interval_ms, self._fuji_name_poll_tick)

    # ---------- RX parsing ----------
    def _poll_rx(self):
        try:
            while True:
                chunk = self.worker.rx_queue.get_nowait()
                frames = self.parser.feed(chunk)
                for f in frames:
                    self._handle_frame(f)
        except queue.Empty:
            pass
        self.after(30, self._poll_rx)

    def _poll_rx_fuji(self):
        try:
            while True:
                chunk = self.fuji_worker.rx_queue.get_nowait()
                frames = self.fuji_parser.feed(chunk)
                for f in frames:
                    self._handle_fuji_frame(f)
        except queue.Empty:
            pass
        self.after(30, self._poll_rx_fuji)

    def _handle_fuji_frame(self, frame: bytes):
        self._fuji_log("RX", fuji_hexdump(frame))
        parsed = parse_l10_frame(frame)
        if not parsed:
            return
        if self.fuji_auto_recovery_enabled:
            self._fuji_log("INFO", "Auto recovery stopped (valid Fuji frame received)")
            self._fuji_stop_auto_recovery()
        func, data_len, payload = parsed
        self.fuji_last_rx_func = f"0x{func:02X}"
        self._update_fuji_debug_status()
        if func == 0x11 or func == 0x12:
            s = decode_lens_name_chunk(payload)
            if s:
                if func == 0x11:
                    self.fuji_lens_name = s
                else:
                    self.fuji_lens_name = (self.fuji_lens_name + s).strip()[:30]
                self.fuji_lens_lbl.configure(text=f"Lens: {self.fuji_lens_name or '(unknown)'}")
                if self.fuji_lens_name:
                    self._fuji_stop_name_poll()
            if func == 0x11 and data_len == 15:
                self.after(0, self._fuji_request_lens_name_2)
        elif func == 0x30:
            v = decode_position_response(payload)
            if v is not None:
                self.fuji_iris_pos = v
                lbl = getattr(self, "_fuji_iris_follow_label", None)
                if lbl:
                    lbl.configure(text=f"Position: {v}")
                self._fuji_log("INFO", f"Iris position: {v}")
        elif func == 0x31:
            v = decode_position_response(payload)
            if v is not None:
                self.fuji_zoom_pos = v
                lbl = getattr(self, "_fuji_zoom_follow_label", None)
                if lbl:
                    lbl.configure(text=f"Position: {v}")
                self._fuji_log("INFO", f"Zoom position: {v}")
        elif func == 0x32:
            v = decode_position_response(payload)
            if v is not None:
                self.fuji_focus_pos = v
                lbl = getattr(self, "_fuji_focus_follow_label", None)
                if lbl:
                    lbl.configure(text=f"Position: {v}")
                self._fuji_log("INFO", f"Focus position: {v}")
        elif func == 0x54:
            if payload:
                bits = payload[0]
                self.fuji_sw4_bits = bits
                sw4_txt = self._fuji_sw4_text(bits)
                if hasattr(self, "fuji_sw4_lbl"):
                    self.fuji_sw4_lbl.configure(text=sw4_txt)
                self._fuji_log("INFO", sw4_txt)

    def _handle_frame(self, frame: bytes):
        self.rx_frame_q.put(frame)
        self._log("RX", hexdump(frame))

        if len(frame) == 6 and frame[-1] == 0xBF:
            cmd = frame[0]
            sub = frame[1]
            if sub == 0xC0:
                v = unpack_type_b_value(frame[2], frame[3], frame[4])
                self.bit_runner.update_follow(cmd, v)
                if cmd == CMD_ZOOM_POS:
                    self.zoom_follow = v
                    getattr(self, "_zoom_follow_label").configure(text=f"Follow: {v}")
                elif cmd == CMD_FOCUS_POS:
                    self.focus_follow = v
                    getattr(self, "_focus_follow_label").configure(text=f"Follow: {v}")
                elif cmd == CMD_IRIS_POS:
                    self.iris_follow = v
                    getattr(self, "_iris_follow_label").configure(text=f"Follow: {v}")
            return

        name = decode_lens_name_type_c(frame)
        if name:
            self._set_lens_name(name)
            self.bit_runner.update_lens_name(name)

    # ---------- Logging ----------
    def _log(self, tag: str, msg: str):
        ts = time.strftime("%H:%M:%S")
        line = f"[{ts}] {tag}: {msg}\n"
        self.log_box.configure(state="normal")
        self.log_box.insert("end", line)
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _ui_log(self, tag: str, msg: str):
        if msg == "Gamepad disconnected.":
            self.after(0, lambda: self.gamepad_state_lbl.configure(text="State: disconnected"))
        elif msg.startswith("Gamepad connected: "):
            dev = msg.split("Gamepad connected: ", 1)[1]
            self.after(0, lambda: self.gamepad_state_lbl.configure(text=f"State: connected ({dev})"))
        self.after(0, lambda: self._log(tag, msg))

    def _clear_log(self):
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")

    def _on_close(self):
        self._stop_gamepad()
        self._stop_bit()
        self._fuji_stop_connect_spam()
        self._fuji_stop_auto_recovery()
        self._fuji_stop_name_poll()
        self._fuji_stop_host_keepalive()
        self._fuji_stop_bit()
        try:
            self.worker.close()
        except Exception:
            pass
        try:
            self.fuji_worker.close()
        except Exception:
            pass
        self.destroy()
