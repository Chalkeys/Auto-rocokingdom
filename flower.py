"""刷花助手 —— 独立脚本，不依赖自动逃跑模块。"""
from __future__ import annotations

import logging
import queue
import threading
import time
import tkinter as tk
from tkinter import scrolledtext, ttk

from config import CONFIG
from core.input import press_once
from core.logger import setup_logging
from core.window import find_all_windows_by_keyword, find_window_by_keyword

try:
    import win32gui as _win32gui
except ImportError:
    _win32gui = None


# ─────────────────────────────── worker helpers ───────────────────────────────

def _wait(secs: float, stop: threading.Event, on_tick=None) -> bool:
    """等待 secs 秒，每秒调用 on_tick(remaining)，可被 stop 打断。
    返回 True 表示被打断。"""
    end = time.monotonic() + secs
    while True:
        left = end - time.monotonic()
        if left <= 0:
            return False
        if stop.wait(min(1.0, left)):
            return True
        if on_tick:
            on_tick(max(0, int(end - time.monotonic())))


def _resolve_hwnd(target, keyword):
    if target is not None:
        return target if (_win32gui and _win32gui.IsWindow(target)) else None
    return find_window_by_keyword(keyword)


# ──────────────────────────────── workers ────────────────────────────────────

def _plan1_worker(target_hwnd, n_sec: float, stop: threading.Event, push):
    """方案1：Tab → 3 → Esc，每隔 n_sec 秒重复。"""
    count = 0
    while not stop.is_set():
        hwnd = _resolve_hwnd(target_hwnd, CONFIG.window_title_keyword)
        if hwnd is None:
            push("未找到游戏窗口，2s 后重试")
            stop.wait(2)
            continue

        count += 1
        push(f"第 {count} 次：Tab → 3 → Esc")
        logging.info("[刷花] 方案1 第 %d 次", count)
        press_once(hwnd, "tab");  time.sleep(0.15)
        press_once(hwnd, "3");    time.sleep(0.15)
        press_once(hwnd, "esc")

        if _wait(n_sec, stop, lambda r, c=count: push(f"第 {c} 次完成，{r}s 后重复")):
            break


def _plan2_worker(target_hwnd, x_min: float, stop: threading.Event, push):
    """方案2：1 → 等5s → 1，每隔 x_min 分钟重复。"""
    count = 0
    while not stop.is_set():
        hwnd = _resolve_hwnd(target_hwnd, CONFIG.window_title_keyword)
        if hwnd is None:
            push("未找到游戏窗口，2s 后重试")
            stop.wait(2)
            continue

        count += 1
        push(f"第 {count} 次：第一次按 1")
        press_once(hwnd, "1")
        logging.info("[刷花] 方案2 第 %d 次：第一次按1", count)

        if _wait(5, stop, lambda r, c=count: push(f"第 {c} 次：{r}s 后按第二个 1")):
            break

        hwnd = _resolve_hwnd(target_hwnd, CONFIG.window_title_keyword)
        if hwnd and not stop.is_set():
            push(f"第 {count} 次：第二次按 1")
            press_once(hwnd, "1")
            logging.info("[刷花] 方案2 第 %d 次：第二次按1", count)

        def _fmt(r, c=count):
            m, s = divmod(r, 60)
            push(f"第 {c} 次完成，{m}m {s:02d}s 后重复")

        if _wait(x_min * 60, stop, _fmt):
            break


# ─────────────────────────────── GUI ─────────────────────────────────────────

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
        self.title("刷花助手")
        self.resizable(False, False)

        self._stop = threading.Event()
        self._q: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        self._hwnd_list: list[int | None] = [None]

        setup_logging()
        _h = _QueueLogHandler(self._q)
        _h.setLevel(logging.INFO)
        _h.setFormatter(logging.Formatter("%(asctime)s  %(message)s", datefmt="%H:%M:%S"))
        logging.getLogger().addHandler(_h)

        self._build_ui()
        self._poll()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ──────────────────────────────── UI ──────────────────────────────────────

    def _build_ui(self) -> None:
        P = {"padx": 12, "pady": 4}

        # ── 目标窗口 ──────────────────────────────────────────────────────────
        wf = ttk.LabelFrame(self, text="目标窗口", padding=8)
        wf.pack(fill="x", **P)
        self._win_combo = ttk.Combobox(wf, state="readonly", width=40)
        self._win_combo.pack(side="left", fill="x", expand=True)
        self._refresh_btn = ttk.Button(wf, text="刷新", width=6, command=self._refresh_wins)
        self._refresh_btn.pack(side="left", padx=(6, 0))
        self._refresh_wins()

        # ── 方案设置 ──────────────────────────────────────────────────────────
        pf = ttk.LabelFrame(self, text="方案设置", padding=8)
        pf.pack(fill="x", **P)

        self._plan_var = tk.StringVar(value="1")

        # 方案1
        ttk.Radiobutton(
            pf, text="方案1：小号大笑  Tab → 3 → Esc",
            variable=self._plan_var, value="1", command=self._on_plan_change,
        ).pack(anchor="w")

        p1p = ttk.Frame(pf)
        p1p.pack(anchor="w", padx=(22, 0), pady=(2, 8))
        ttk.Label(p1p, text="每次间隔").pack(side="left")
        self._n_sec_var = tk.StringVar(value="5")
        self._n_sec_spin = ttk.Spinbox(p1p, from_=1, to=3600, width=7,
                                        textvariable=self._n_sec_var)
        self._n_sec_spin.pack(side="left", padx=4)
        ttk.Label(p1p, text="秒").pack(side="left")

        ttk.Separator(pf, orient="horizontal").pack(fill="x", pady=4)

        # 方案2
        ttk.Radiobutton(
            pf, text="方案2：小号调时间  1 → 5s → 1",
            variable=self._plan_var, value="2", command=self._on_plan_change,
        ).pack(anchor="w")

        p2p = ttk.Frame(pf)
        p2p.pack(anchor="w", padx=(22, 0), pady=(2, 0))
        ttk.Label(p2p, text="每轮间隔").pack(side="left")
        self._x_min_var = tk.StringVar(value="10")
        self._x_min_spin = ttk.Spinbox(p2p, from_=1, to=1440, width=7,
                                        textvariable=self._x_min_var)
        self._x_min_spin.pack(side="left", padx=4)
        ttk.Label(p2p, text="分钟").pack(side="left")

        self._on_plan_change()

        # ── 状态 + 按钮 ───────────────────────────────────────────────────────
        sf = ttk.Frame(self, padding=(12, 2))
        sf.pack(fill="x")
        ttk.Label(sf, text="状态：").pack(side="left")
        self._state_var = tk.StringVar(value="待机")
        ttk.Label(sf, textvariable=self._state_var).pack(side="left")

        bf = ttk.Frame(self, padding=(12, 4))
        bf.pack(fill="x")
        self._btn = ttk.Button(bf, text="开始运行", command=self._toggle, width=24)
        self._btn.pack(expand=True)

        # ── 日志 ─────────────────────────────────────────────────────────────
        lf = ttk.LabelFrame(self, text="运行日志", padding=6)
        lf.pack(fill="both", expand=True, **P)
        self._log = scrolledtext.ScrolledText(
            lf, height=12, width=60, state="disabled",
            font=("Consolas", 9), bg="#1e1e1e", fg="#d4d4d4",
        )
        self._log.pack(fill="both", expand=True)

    def _on_plan_change(self) -> None:
        is1 = self._plan_var.get() == "1"
        self._n_sec_spin.config(state="normal" if is1 else "disabled")
        self._x_min_spin.config(state="disabled" if is1 else "normal")

    # ─────────────────────────── window picker ────────────────────────────────

    def _refresh_wins(self) -> None:
        wins = find_all_windows_by_keyword(CONFIG.window_title_keyword)
        self._hwnd_list = [None] + [hwnd for hwnd, *_ in wins]
        labels = ["自动（首个匹配）"] + [
            f"{title}  {w}×{h}  [0x{hwnd:08X}]" for hwnd, title, w, h in wins
        ]
        self._win_combo["values"] = labels
        self._win_combo.current(0)

    # ────────────────────────────── control ───────────────────────────────────

    def _toggle(self) -> None:
        if self._thread and self._thread.is_alive():
            self._do_stop()
        else:
            self._do_start()

    def _do_start(self) -> None:
        try:
            n_sec = float(self._n_sec_var.get())
            x_min = float(self._x_min_var.get())
        except ValueError:
            self._state_var.set("参数有误，请检查间隔设置")
            return

        self._stop.clear()
        idx = self._win_combo.current()
        target = self._hwnd_list[idx] if 0 <= idx < len(self._hwnd_list) else None

        push = lambda msg: self._q.put(("state", msg))

        plan = self._plan_var.get()
        if plan == "1":
            args = (target, n_sec, self._stop, push)
            worker = _plan1_worker
        else:
            args = (target, x_min, self._stop, push)
            worker = _plan2_worker

        self._thread = threading.Thread(target=worker, args=args, daemon=True)
        self._thread.start()
        self._btn.config(text="停止运行")
        self._state_var.set("运行中…")
        self._set_controls("disabled")

    def _do_stop(self) -> None:
        self._stop.set()
        self._btn.config(text="开始运行")
        self._state_var.set("已停止")
        self._set_controls("normal")
        self._on_plan_change()

    def _set_controls(self, state: str) -> None:
        self._win_combo.config(state=state if state == "disabled" else "readonly")
        self._refresh_btn.config(state=state)
        self._n_sec_spin.config(state=state)
        self._x_min_spin.config(state=state)
        for child in self.winfo_children():
            if isinstance(child, ttk.LabelFrame) and child.cget("text") == "方案设置":
                for w in child.winfo_children():
                    if isinstance(w, ttk.Radiobutton):
                        w.config(state=state)

    def _on_close(self) -> None:
        self._stop.set()
        self.destroy()

    # ──────────────────────────── queue poll ──────────────────────────────────

    def _poll(self) -> None:
        try:
            while True:
                kind, data = self._q.get_nowait()
                if kind == "log":
                    self._log.config(state="normal")
                    self._log.insert("end", data + "\n")
                    self._log.see("end")
                    self._log.config(state="disabled")
                elif kind == "state":
                    self._state_var.set(data)
        except queue.Empty:
            pass
        if self._thread and not self._thread.is_alive() and not self._stop.is_set():
            self._do_stop()
        self.after(100, self._poll)


def main() -> None:
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
