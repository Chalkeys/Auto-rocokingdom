"""Auto-Roco 统一启动器。"""
from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import messagebox, ttk

import updater
from version import __version__

_FROZEN = getattr(sys, "frozen", False)
_BASE = os.path.dirname(sys.executable if _FROZEN else os.path.abspath(__file__))


def _find_cmd(exe_name: str, script_name: str) -> list[str]:
    """Return the command to launch a sub-tool (EXE or Python script)."""
    if _FROZEN:
        for candidate in [exe_name, exe_name.lower()]:
            p = os.path.join(_BASE, f"{candidate}.exe")
            if os.path.exists(p):
                return [p]
        return []
    for candidate in [script_name, script_name.lower(), exe_name.lower()]:
        p = os.path.join(_BASE, f"{candidate}.py")
        if os.path.exists(p):
            return [sys.executable, p]
    return []


class Launcher(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Auto-Roco 启动器")
        self.resizable(False, False)
        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        P = {"padx": 16, "pady": 4}

        # ── 标题 ──
        hdr = ttk.Frame(self, padding=(16, 14, 16, 6))
        hdr.pack(fill="x")
        ttk.Label(hdr, text="Auto-Roco", font=("", 16, "bold")).pack(side="left")
        ttk.Label(hdr, text=f"  v{__version__}", foreground="gray").pack(
            side="left", anchor="s", pady=3
        )

        ttk.Separator(self, orient="horizontal").pack(fill="x", padx=16)

        # ── 工具按钮 ──
        tools = ttk.Frame(self, padding=(16, 14, 16, 14))
        tools.pack()
        self._tool_btn(tools, "自动战斗助手", "AutoRoco", "gui").grid(
            row=0, column=0, padx=8
        )
        self._tool_btn(tools, "刷花助手", "Flower", "flower").grid(
            row=0, column=1, padx=8
        )

        ttk.Separator(self, orient="horizontal").pack(fill="x", padx=16)

        # ── 更新区 ──
        upd = ttk.LabelFrame(self, text="更新", padding=8)
        upd.pack(fill="x", **P)

        top = ttk.Frame(upd)
        top.pack(fill="x")
        self._upd_var = tk.StringVar(value=f"当前版本 v{__version__}")
        ttk.Label(top, textvariable=self._upd_var, foreground="gray").pack(side="left")
        self._check_btn = ttk.Button(top, text="检查更新", width=10, command=self._check_update)
        self._check_btn.pack(side="right")

        self._prog_var = tk.DoubleVar()
        self._progress = ttk.Progressbar(upd, variable=self._prog_var, maximum=100, length=320)

        self._dl_frame = ttk.Frame(upd)

        # ── 页脚 ──
        ttk.Label(
            self,
            text=f"github.com/{updater.REPO}",
            foreground="gray",
            font=("", 8),
            cursor="hand2",
        ).pack(pady=(2, 10))

    def _tool_btn(
        self, parent: tk.Widget, label: str, exe_name: str, script_name: str
    ) -> ttk.Button:
        cmd = _find_cmd(exe_name, script_name)

        def _launch() -> None:
            if not cmd:
                messagebox.showwarning("找不到工具", f"未找到 {exe_name}.exe 或 {script_name}.py")
                return
            subprocess.Popen(cmd, cwd=_BASE)

        return ttk.Button(parent, text=label, width=18, command=_launch)

    # ---------------------------------------------------------------- update

    def _check_update(self) -> None:
        self._check_btn.config(state="disabled")
        self._upd_var.set("检查中…")
        threading.Thread(target=self._do_check, daemon=True).start()

    def _do_check(self) -> None:
        try:
            # Lightweight: check version file first; only fetch full release if newer
            remote_ver = updater.fetch_remote_version()
            if not remote_ver:
                self.after(0, self._upd_var.set, "无法获取远程版本")
                return
            if not updater.is_newer(remote_ver, __version__):
                self.after(0, self._upd_var.set, f"已是最新版本 v{__version__}")
                return
            # Fetch full release info for assets
            info = updater.fetch_release()
            self.after(0, self._on_update_found, info)
        except Exception as e:
            self.after(0, self._upd_var.set, f"检查失败：{e}")
        finally:
            self.after(0, self._check_btn.config, {"state": "normal"})

    def _on_update_found(self, info: updater.ReleaseInfo) -> None:
        notes_preview = info.notes[:300] + ("…" if len(info.notes) > 300 else "")
        answer = messagebox.askyesno(
            "发现新版本",
            f"v{info.version} 已发布。\n\n{notes_preview}\n\n是否立即下载？",
        )
        if not answer:
            self._upd_var.set(f"跳过 v{info.version}")
            return

        exe_assets = [a for a in info.assets if a.name.lower().endswith(".exe")]
        if not exe_assets:
            messagebox.showinfo(
                "无可下载资源",
                f"v{info.version} 未附带 EXE 文件。\n请前往 GitHub 手动下载。",
            )
            return

        self._upd_var.set(f"下载 v{info.version}…")
        self._progress.pack(fill="x", pady=(6, 2))
        self._check_btn.config(state="disabled")

        dest_dir = os.path.join(_BASE, "updates")
        threading.Thread(
            target=self._do_download,
            args=(exe_assets, dest_dir, info.version),
            daemon=True,
        ).start()

    def _do_download(
        self, assets: list, dest_dir: str, version: str
    ) -> None:
        total = len(assets)
        try:
            for i, asset in enumerate(assets):
                dest = os.path.join(dest_dir, asset.name)
                self.after(0, self._upd_var.set, f"下载 {asset.name}  ({i + 1}/{total})")

                def _prog(done: int, size: int, idx: int = i) -> None:
                    if size:
                        pct = (idx + done / size) / total * 100
                        self.after(0, self._prog_var.set, pct)

                updater.download_file(asset.url, dest, _prog)

            self.after(0, self._on_download_done, dest_dir, version)
        except Exception as e:
            self.after(0, self._upd_var.set, f"下载失败：{e}")
        finally:
            self.after(0, self._check_btn.config, {"state": "normal"})

    def _on_download_done(self, dest_dir: str, version: str) -> None:
        self._prog_var.set(100)
        self._upd_var.set(f"v{version} 已下载 → 关闭程序后替换文件")
        if messagebox.askyesno("下载完成", f"新版本已下载至：\n{dest_dir}\n\n关闭程序后将旧文件替换即可。\n\n现在打开下载目录？"):
            os.startfile(dest_dir)


# ------------------------------------------------------------------ admin / main

def _ensure_admin() -> None:
    try:
        if ctypes.windll.shell32.IsUserAnAdmin():
            return
    except Exception:
        return
    exe = sys.executable
    params = " ".join(f'"{a}"' for a in ([] if _FROZEN else sys.argv))
    ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, 1)
    sys.exit(0)


def main() -> None:
    _ensure_admin()
    Launcher().mainloop()


if __name__ == "__main__":
    main()
