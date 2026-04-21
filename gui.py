"""GUI entry point for Auto-rocokingdom."""
from __future__ import annotations

import logging
import queue
import threading
import tkinter as tk
from tkinter import scrolledtext, ttk

from config import CONFIG
from core.engine import Engine
from core.logger import setup_logging
from modes import MODE_REGISTRY


class _QueueLogHandler(logging.Handler):
    def __init__(self, q: queue.Queue) -> None:
        super().__init__()
        self.queue = q

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.queue.put(("log", self.format(record)))
        except Exception:
            self.handleError(record)


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("洛克王国自动化助手")
        self.resizable(False, False)

        self._stop_event = threading.Event()
        self._msg_queue: queue.Queue = queue.Queue()
        self._engine_thread: threading.Thread | None = None

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
        for key, cls in sorted(MODE_REGISTRY.items()):
            ttk.Radiobutton(
                mode_frame,
                text=f"{key}：{cls().label}",
                variable=self._mode_var,
                value=key,
            ).pack(anchor="w", pady=2)

        # Status
        status_frame = ttk.LabelFrame(self, text="实时状态", padding=8)
        status_frame.pack(fill="x", **pad)

        self._battle_var = tk.StringVar(value="0")
        self._pollute_var = tk.StringVar(value="0")
        self._state_var = tk.StringVar(value="待机")
        self._score_var = tk.StringVar(value="—")

        for label, var in (
            ("战斗次数", self._battle_var),
            ("污染次数", self._pollute_var),
            ("当前状态", self._state_var),
            ("检测分数", self._score_var),
        ):
            row = ttk.Frame(status_frame)
            row.pack(fill="x", pady=1)
            ttk.Label(row, text=label + "：", width=9, anchor="w").pack(side="left")
            ttk.Label(row, textvariable=var, anchor="w").pack(side="left")

        # Start / stop button
        btn_frame = ttk.Frame(self, padding=(12, 4))
        btn_frame.pack(fill="x")
        self._btn = ttk.Button(btn_frame, text="开始运行", command=self._toggle, width=22)
        self._btn.pack(expand=True)

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

    # ---------------------------------------------------------------- control

    def _toggle(self) -> None:
        if self._engine_thread and self._engine_thread.is_alive():
            self._do_stop()
        else:
            self._do_start()

    def _do_start(self) -> None:
        self._stop_event.clear()
        key = self._mode_var.get()
        mode = MODE_REGISTRY[key]()
        engine = Engine(
            mode,
            stop_event=self._stop_event,
            status_callback=lambda s: self._msg_queue.put(("status", s)),
        )
        self._engine_thread = threading.Thread(target=engine.run, daemon=True)
        self._engine_thread.start()
        self._btn.config(text="停止运行")
        self._state_var.set("运行中…")
        self._set_mode_state("disabled")

    def _do_stop(self) -> None:
        self._stop_event.set()
        self._btn.config(text="开始运行")
        self._state_var.set("已停止")
        self._set_mode_state("normal")

    def _set_mode_state(self, state: str) -> None:
        for child in self.winfo_children():
            if isinstance(child, ttk.LabelFrame) and child.cget("text") == "选择模式":
                for rb in child.winfo_children():
                    rb.config(state=state)

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
                self._do_stop()
        self.after(100, self._poll)

    def _append_log(self, text: str) -> None:
        self._log.config(state="normal")
        self._log.insert("end", text + "\n")
        self._log.see("end")
        self._log.config(state="disabled")

    def _update_status(self, data: dict) -> None:
        if "battle_count" in data:
            self._battle_var.set(str(data["battle_count"]))
        if "pollute_count" in data:
            self._pollute_var.set(str(data["pollute_count"]))
        if "state" in data:
            self._state_var.set(data["state"])
        if "score" in data:
            val = data["score"]
            self._score_var.set(f"{val:.3f}" if isinstance(val, float) else "—")


def main() -> None:
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
