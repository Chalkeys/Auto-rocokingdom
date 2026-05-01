"""GUI entry point for Auto-rocokingdom."""
from __future__ import annotations

import ctypes
import logging
import queue
import sys
import threading
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

from config import CONFIG
from core.engine import Engine
from core.logger import setup_logging
from core.window import find_all_windows_by_keyword
from modes import MODE_REGISTRY
from modes.smart import ACTION_OPTIONS, SmartMode


class OverlayWindow(tk.Toplevel):
    """始终置顶的半透明悬浮状态窗口，可拖动、可调透明度。"""

    _BG = "#1a1a2e"
    _FG = "#e0e0e0"
    _ACCENT = "#4fc3f7"
    _BAR_BG = "#0d0d1a"

    def __init__(
        self,
        parent: tk.Tk,
        mode_var: tk.StringVar,
        state_var: tk.StringVar,
        battle_var: tk.StringVar,
        pollute_var: tk.StringVar,
        spirit_var: tk.StringVar,
    ) -> None:
        super().__init__(parent)
        self.overrideredirect(True)
        self.wm_attributes("-topmost", True)
        self.wm_attributes("-alpha", 0.85)
        self.config(bg=self._BG)
        self._dx = self._dy = 0

        # ── 标题栏（拖动区 + 关闭按钮）──────────────────────────────────
        bar = tk.Frame(self, bg=self._BAR_BG, cursor="fleur")
        bar.pack(fill="x")
        tk.Label(bar, text="Auto-Roco  HUD", bg=self._BAR_BG, fg="#666",
                 font=("", 8), padx=6, pady=3).pack(side="left")
        tk.Button(bar, text="×", bg=self._BAR_BG, fg="#ff6b6b", bd=0,
                  font=("", 10, "bold"), cursor="hand2",
                  activebackground=self._BAR_BG, activeforeground="#ff4444",
                  command=self.destroy).pack(side="right", padx=4)

        # ── 数据行 ──────────────────────────────────────────────────────
        body = tk.Frame(self, bg=self._BG, padx=12, pady=6)
        body.pack(fill="x")

        self._pollute_label: tk.Label | None = None
        for label_text, var in (
            ("模式", mode_var),
            ("状态", state_var),
            ("战斗", battle_var),
            ("污染", pollute_var),
            ("精灵", spirit_var),
        ):
            row = tk.Frame(body, bg=self._BG)
            row.pack(fill="x", pady=2)
            tk.Label(row, text=label_text, bg=self._BG, fg="#888",
                     font=("", 9), width=4, anchor="w").pack(side="left")
            value_label = tk.Label(row, textvariable=var, bg=self._BG, fg=self._ACCENT,
                                   font=("", 11, "bold"), anchor="w")
            value_label.pack(side="left")
            if label_text == "污染":
                self._pollute_label = value_label

        # ── 透明度滑块 ──────────────────────────────────────────────────
        tk.Frame(self, bg="#2a2a4a", height=1).pack(fill="x")
        alpha_row = tk.Frame(self, bg=self._BG, padx=12, pady=4)
        alpha_row.pack(fill="x")
        tk.Label(alpha_row, text="透明", bg=self._BG, fg="#888",
                 font=("", 9), width=4, anchor="w").pack(side="left")
        self._alpha_var = tk.IntVar(value=85)
        tk.Scale(
            alpha_row, from_=20, to=100, orient="horizontal",
            variable=self._alpha_var, command=self._on_alpha,
            bg=self._BG, fg=self._FG, troughcolor="#2a2a4a",
            highlightthickness=0, bd=0, length=120, showvalue=False,
        ).pack(side="left")

        # 仅在标题栏和数据区绑定拖动（避开透明度滑块所在的 alpha_row）
        self._bind_drag(bar)
        self._bind_drag(body)
        self.geometry("+40+40")

    def _on_alpha(self, _=None) -> None:
        self.wm_attributes("-alpha", self._alpha_var.get() / 100)

    def set_pollute_color(self, color: str) -> None:
        if self._pollute_label is not None:
            self._pollute_label.config(fg=color or self._ACCENT)

    def _bind_drag(self, widget: tk.Widget) -> None:
        if isinstance(widget, (tk.Scale, tk.Button)):
            return
        widget.bind("<ButtonPress-1>", self._drag_start)
        widget.bind("<B1-Motion>", self._drag_move)
        for child in widget.winfo_children():
            self._bind_drag(child)

    def _drag_start(self, event: tk.Event) -> None:
        self._dx = event.x_root - self.winfo_x()
        self._dy = event.y_root - self.winfo_y()

    def _drag_move(self, event: tk.Event) -> None:
        self.geometry(f"+{event.x_root - self._dx}+{event.y_root - self._dy}")


class _QueueLogHandler(logging.Handler):
    def __init__(self, q: queue.Queue) -> None:
        super().__init__()
        self.queue = q

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.queue.put(("log", self.format(record)))
        except Exception:
            self.handleError(record)


def _force_foreground(hwnd: int) -> None:
    """Bring hwnd to foreground, bypassing Windows focus-steal restrictions."""
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    fg_hwnd = user32.GetForegroundWindow()
    fg_thread = user32.GetWindowThreadProcessId(fg_hwnd, None)
    cur_thread = kernel32.GetCurrentThreadId()
    attached = fg_thread != cur_thread and user32.AttachThreadInput(fg_thread, cur_thread, True)
    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    user32.BringWindowToTop(hwnd)
    user32.SetForegroundWindow(hwnd)
    if attached:
        user32.AttachThreadInput(fg_thread, cur_thread, False)


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("洛克王国自动化助手")
        self.resizable(False, False)

        self._stop_event = threading.Event()
        self._msg_queue: queue.Queue = queue.Queue()
        self._engine_thread: threading.Thread | None = None
        self._hwnd_list: list[int | None] = [None]
        self._overlay: OverlayWindow | None = None
        self._running_mode_var = tk.StringVar(value="—")
        self._saved_battle_count = 0
        self._saved_pollute_count = 0
        self._window_lost = False
        self._spirit_var = tk.StringVar(value="—")

        setup_logging()
        self._install_log_handler()
        self._build_ui()
        self._poll()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------ setup

    def _install_log_handler(self) -> None:
        handler = _QueueLogHandler(self._msg_queue)
        handler.setLevel(logging.INFO)
        handler.setFormatter(
            logging.Formatter("%(asctime)s  %(message)s", datefmt="%H:%M:%S")
        )
        logging.getLogger().addHandler(handler)

    def _build_ui(self) -> None:
        pad = {"padx": 12, "pady": 4}

        # Mode selection
        mode_frame = ttk.LabelFrame(self, text="选择模式", padding=8)
        mode_frame.pack(fill="x", **pad)

        self._mode_var = tk.StringVar(value="1")
        # Build action key/label lists from ACTION_OPTIONS (preserves dict order)
        self._smart_action_keys = [v[0] for v in ACTION_OPTIONS.values()]
        _action_labels = [v[1] for v in ACTION_OPTIONS.values()]

        for key, cls in sorted(MODE_REGISTRY.items()):
            ttk.Radiobutton(
                mode_frame,
                text=f"{key}：{cls().label}",
                variable=self._mode_var,
                value=key,
                command=self._on_mode_change,
            ).pack(anchor="w", pady=2)
            if key == "4":
                # Smart mode config sub-section
                self._smart_frame = ttk.Frame(mode_frame)
                self._smart_frame.pack(fill="x", padx=(22, 0), pady=(0, 4))
                for row_text, default_key, combo_attr in (
                    ("污染战斗", "gather", "_smart_pollute_combo"),
                    ("普通战斗", "escape", "_smart_normal_combo"),
                ):
                    row = ttk.Frame(self._smart_frame)
                    row.pack(fill="x", pady=1)
                    ttk.Label(row, text=row_text + "：", width=8, anchor="w").pack(side="left")
                    combo = ttk.Combobox(row, values=_action_labels, state="disabled", width=28)
                    combo.current(self._smart_action_keys.index(default_key))
                    combo.pack(side="left")
                    setattr(self, combo_attr, combo)
        self._on_mode_change()

        # Window picker
        win_frame = ttk.LabelFrame(self, text="目标窗口", padding=8)
        win_frame.pack(fill="x", **pad)

        self._win_combo = ttk.Combobox(win_frame, state="readonly", width=38)
        self._win_combo.pack(side="left", fill="x", expand=True)
        ttk.Button(win_frame, text="刷新", width=6, command=self._refresh_windows).pack(side="left", padx=(6, 0))
        self._refresh_windows()

        # Status
        status_frame = ttk.LabelFrame(self, text="实时状态", padding=8)
        status_frame.pack(fill="x", **pad)

        self._battle_var = tk.StringVar(value="0")
        self._pollute_var = tk.StringVar(value="0")
        self._state_var = tk.StringVar(value="待机")
        self._score_var = tk.StringVar(value="—")

        self._pollute_label: ttk.Label | None = None
        for label, var in (
            ("战斗次数", self._battle_var),
            ("污染次数", self._pollute_var),
            ("当前状态", self._state_var),
            ("检测分数", self._score_var),
            ("最近精灵", self._spirit_var),
        ):
            row = ttk.Frame(status_frame)
            row.pack(fill="x", pady=1)
            ttk.Label(row, text=label + "：", width=9, anchor="w").pack(side="left")
            value_lbl = ttk.Label(row, textvariable=var, anchor="w")
            value_lbl.pack(side="left")
            if label == "污染次数":
                self._pollute_label = value_lbl
                self._pollute_default_fg = value_lbl.cget("foreground")

        # Start / stop + overlay toggle
        btn_frame = ttk.Frame(self, padding=(12, 4))
        btn_frame.pack(fill="x")
        self._btn = ttk.Button(btn_frame, text="开始运行", command=self._toggle, width=22)
        self._btn.pack(side="left", expand=True)
        self._overlay_btn = ttk.Button(btn_frame, text="悬浮窗", command=self._toggle_overlay, width=8)
        self._overlay_btn.pack(side="left", padx=(6, 0))

        # Log area
        log_frame = ttk.LabelFrame(self, text="运行日志", padding=6)
        log_frame.pack(fill="both", expand=True, **pad)

        self._log = scrolledtext.ScrolledText(
            log_frame,
            height=14,
            width=64,
            state="disabled",
            font=("Consolas", 9),
            bg="#1e1e1e",
            fg="#d4d4d4",
        )
        self._log.pack(fill="both", expand=True)

        ttk.Label(
            self,
            text='点击"停止运行"或关闭窗口可随时退出',
            foreground="gray",
            font=("", 8),
        ).pack(pady=(0, 6))

    def _toggle_overlay(self) -> None:
        if self._overlay and self._overlay.winfo_exists():
            self._overlay.destroy()
            self._overlay = None
        else:
            self._overlay = OverlayWindow(
                self,
                mode_var=self._running_mode_var,
                state_var=self._state_var,
                battle_var=self._battle_var,
                pollute_var=self._pollute_var,
                spirit_var=self._spirit_var,
            )

    def _on_mode_change(self) -> None:
        state = "readonly" if self._mode_var.get() == "4" else "disabled"
        self._smart_pollute_combo.config(state=state)
        self._smart_normal_combo.config(state=state)

    # ---------------------------------------------------------------- control

    def _refresh_windows(self) -> None:
        wins = find_all_windows_by_keyword(CONFIG.window_title_keyword)
        self._hwnd_list = [None] + [hwnd for hwnd, *_ in wins]
        labels = ["自动（首个匹配）"] + [
            f"{title}  {w}×{h}  [0x{hwnd:08X}]" for hwnd, title, w, h in wins
        ]
        self._win_combo["values"] = labels
        self._win_combo.current(0)

    def _toggle(self) -> None:
        if self._engine_thread and self._engine_thread.is_alive():
            self._do_stop()
        else:
            self._do_start()

    def _do_start(self) -> None:
        self._window_lost = False
        self._stop_event.clear()
        key = self._mode_var.get()
        if key == "4":
            pollute = self._smart_action_keys[self._smart_pollute_combo.current()]
            normal = self._smart_action_keys[self._smart_normal_combo.current()]
            mode = SmartMode(pollute_action=pollute, normal_action=normal)
        else:
            mode = MODE_REGISTRY[key]()

        # Offer to inherit or reset previous session stats
        if self._saved_battle_count > 0 or self._saved_pollute_count > 0:
            inherit = messagebox.askyesno(
                "继承统计",
                f"上次运行：战斗 {self._saved_battle_count} 次，污染 {self._saved_pollute_count} 次\n"
                "是否继承统计数据？",
            )
            if not inherit:
                self._saved_battle_count = 0
                self._saved_pollute_count = 0
                self._battle_var.set("0")
                self._update_pollute_display(0)

        initial_battle = self._saved_battle_count
        initial_pollute = self._saved_pollute_count

        idx = self._win_combo.current()
        target_hwnd = self._hwnd_list[idx] if 0 <= idx < len(self._hwnd_list) else None
        if target_hwnd:
            try:
                _force_foreground(target_hwnd)
            except Exception:
                pass
        engine = Engine(
            mode,
            stop_event=self._stop_event,
            status_callback=lambda s: self._msg_queue.put(("status", s)),
            target_hwnd=target_hwnd,
            initial_battle_count=initial_battle,
            initial_pollute_count=initial_pollute,
        )
        self._engine_thread = threading.Thread(target=engine.run, daemon=True)
        self._engine_thread.start()
        self._btn.config(text="停止运行")
        self._state_var.set("运行中…")
        self._running_mode_var.set(mode.label)
        self._set_controls_state("disabled")

    def _do_stop(self) -> None:
        self._stop_event.set()
        self._btn.config(text="开始运行")
        self._state_var.set("已停止")
        self._running_mode_var.set("—")
        self._spirit_var.set("—")
        self._set_controls_state("normal")

    def _set_controls_state(self, state: str) -> None:
        for child in self.winfo_children():
            if not isinstance(child, ttk.LabelFrame):
                continue
            if child.cget("text") == "选择模式":
                for rb in child.winfo_children():
                    rb.config(state=state)
            elif child.cget("text") == "目标窗口":
                for w in child.winfo_children():
                    w.config(state=state if state == "disabled" else ("readonly" if isinstance(w, ttk.Combobox) else state))
        # Smart mode comboboxes: restore to readonly only when mode 4 is selected
        if state == "disabled":
            self._smart_pollute_combo.config(state="disabled")
            self._smart_normal_combo.config(state="disabled")
        else:
            self._on_mode_change()

    def _on_close(self) -> None:
        self._stop_event.set()
        self.destroy()

    # -------------------------------------------------------------- queue poll

    def _poll(self) -> None:
        try:
            while True:
                kind, data = self._msg_queue.get_nowait()
                if kind == "log":
                    self._append_log(data)
                elif kind == "status":
                    self._update_status(data)
        except queue.Empty:
            pass
        # Auto-reset button if engine thread ended on its own
        if self._engine_thread and not self._engine_thread.is_alive():
            if not self._stop_event.is_set():
                was_window_lost = self._window_lost
                self._do_stop()
                if was_window_lost:
                    self._window_lost = False
                    if messagebox.askyesno(
                        "窗口已丢失",
                        "游戏窗口已失去连接。\n是否刷新窗口列表并重新选择？",
                    ):
                        self._refresh_windows()
        self.after(100, self._poll)

    def _append_log(self, text: str) -> None:
        self._log.config(state="normal")
        self._log.insert("end", text + "\n")
        self._log.see("end")
        self._log.config(state="disabled")

    def _update_status(self, data: dict) -> None:
        if "battle_count" in data:
            self._saved_battle_count = int(data["battle_count"])
            self._battle_var.set(str(self._saved_battle_count))
        if "pollute_count" in data:
            self._saved_pollute_count = int(data["pollute_count"])
            self._update_pollute_display(self._saved_pollute_count)
        if "state" in data:
            self._state_var.set(data["state"])
        if "score" in data:
            val = data["score"]
            self._score_var.set(f"{val:.3f}" if isinstance(val, float) else "—")
        if "spirit_name" in data and data["spirit_name"]:
            self._spirit_var.set(data["spirit_name"])
        if data.get("window_lost"):
            self._window_lost = True

    def _update_pollute_display(self, count: int) -> None:
        if count >= 80:
            text, color = f"{count}（保底）", "#f44336"
        elif count >= 70:
            text, color = f"{count}（软保底）", "#ff9800"
        else:
            text, color = str(count), self._pollute_default_fg
        self._pollute_var.set(text)
        if self._pollute_label is not None:
            self._pollute_label.config(foreground=color)
        if self._overlay is not None and self._overlay.winfo_exists():
            self._overlay.set_pollute_color(color if count >= 70 else "")


def _ensure_admin() -> None:
    """若当前进程没有管理员权限，则通过 UAC 重新以管理员身份启动。"""
    try:
        if ctypes.windll.shell32.IsUserAnAdmin():
            return
    except Exception:
        return
    if getattr(sys, "frozen", False):
        exe = sys.executable
        params = " ".join(f'"{a}"' for a in sys.argv[1:])
    else:
        exe = sys.executable
        params = " ".join(f'"{a}"' for a in sys.argv)
    ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, 1)
    sys.exit(0)


def main() -> None:
    _ensure_admin()
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
