"""
Modern dark-themed GUI for WeChat anti-revoke patcher.
Requires: customtkinter >= 5.2
"""
import customtkinter as ctk
from tkinter import filedialog, messagebox
import threading
import os
import sys
import json

import patcher

# ── Theme ────────────────────────────────────────────────────────────────────

BG       = "#1e1e2e"   # window / root
SURFACE  = "#2a2a3f"   # card / panel
SURFACE2 = "#313244"   # input field bg
ACCENT   = "#7c3aed"   # primary button
ACCENT_H = "#6d28d9"   # primary button hover
DIMMED   = "#374151"   # secondary button
DIMMED_H = "#4b5563"   # secondary button hover
TEXT     = "#cdd6f4"   # main text
SUBTEXT  = "#a6adc8"   # muted text
GREEN    = "#a6e3a1"
RED      = "#f38ba8"
YELLOW   = "#f9e2af"
LOG_BG   = "#11111b"   # log terminal bg
LOG_FG   = "#bac2de"

STATUS_COLORS = {
    'ok':          GREEN,
    'patched':     YELLOW,
    'unsupported': RED,
    'error':       RED,
}
STATUS_LABELS = {
    'ok':          '● 已支持',
    'patched':     '◉ 已安装',
    'unsupported': '✕ 不支持',
    'error':       '✕ 错误',
}


def _data_path(filename: str) -> str:
    """Resolve a path inside the bundled data/ directory."""
    if getattr(sys, 'frozen', False):
        base = sys._MEIPASS
    else:
        base = os.path.dirname(__file__)
    return os.path.join(base, 'data', filename)


# ── Main application window ───────────────────────────────────────────────────

class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        # Load patch data
        with open(_data_path('patch.json'), 'r', encoding='utf-8') as f:
            self._patch_data = json.load(f)
        self._apps_cfg = self._patch_data['Apps']

        # Window setup
        ctk.set_appearance_mode("dark")
        self.title("微信防撤回补丁")
        self.geometry("500x500")
        self.resizable(False, False)
        self.configure(fg_color=BG)

        self._build_ui()
        self._auto_detect()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        # ── Header ──────────────────────────────────────────────────────────
        header = ctk.CTkFrame(self, fg_color=SURFACE, corner_radius=0, height=54)
        header.pack(fill="x")
        header.pack_propagate(False)

        ctk.CTkLabel(
            header,
            text="  🛡  微信防撤回补丁",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color=TEXT,
            anchor="w",
        ).pack(side="left", padx=16)

        ctk.CTkLabel(
            header,
            text="v1.0  ",
            font=ctk.CTkFont(size=12),
            text_color=SUBTEXT,
            anchor="e",
        ).pack(side="right", padx=8)

        # ── Admin warning (Windows only) ──────────────────────────────────
        if sys.platform == 'win32' and not patcher.is_admin():
            warn = ctk.CTkFrame(self, fg_color="#3b1e08", corner_radius=0, height=28)
            warn.pack(fill="x")
            warn.pack_propagate(False)
            ctk.CTkLabel(
                warn,
                text="  ⚠  请以管理员身份运行以修改系统文件",
                font=ctk.CTkFont(size=11),
                text_color=YELLOW,
                anchor="w",
            ).pack(side="left", padx=12)

        # ── Path card ────────────────────────────────────────────────────
        card = ctk.CTkFrame(self, fg_color=SURFACE, corner_radius=12)
        card.pack(fill="x", padx=16, pady=(16, 0))

        ctk.CTkLabel(card, text="安装路径", font=ctk.CTkFont(size=12),
                     text_color=SUBTEXT).pack(anchor="w", padx=16, pady=(12, 4))

        path_row = ctk.CTkFrame(card, fg_color="transparent")
        path_row.pack(fill="x", padx=16, pady=(0, 4))

        self._path_var = ctk.StringVar()
        self._path_entry = ctk.CTkEntry(
            path_row,
            textvariable=self._path_var,
            placeholder_text="微信安装目录 (含 WeChatWin.dll)",
            fg_color=SURFACE2,
            border_color=SURFACE2,
            text_color=TEXT,
            font=ctk.CTkFont(size=12),
        )
        self._path_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self._path_var.trace_add("write", lambda *_: self._on_path_change())

        ctk.CTkButton(
            path_row,
            text="浏览",
            width=60,
            fg_color=DIMMED,
            hover_color=DIMMED_H,
            text_color=TEXT,
            font=ctk.CTkFont(size=12),
            command=self._browse,
        ).pack(side="right")

        # ── Status row ───────────────────────────────────────────────────
        info_row = ctk.CTkFrame(card, fg_color="transparent")
        info_row.pack(fill="x", padx=16, pady=(4, 12))

        self._version_label = ctk.CTkLabel(
            info_row, text="版本: —",
            font=ctk.CTkFont(size=12), text_color=SUBTEXT)
        self._version_label.pack(side="left")

        self._status_label = ctk.CTkLabel(
            info_row, text="",
            font=ctk.CTkFont(size=12), text_color=SUBTEXT)
        self._status_label.pack(side="left", padx=(16, 0))

        self._backup_label = ctk.CTkLabel(
            info_row, text="",
            font=ctk.CTkFont(size=11), text_color=SUBTEXT)
        self._backup_label.pack(side="right")

        # ── Action buttons ───────────────────────────────────────────────
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=16, pady=16)

        self._patch_btn = ctk.CTkButton(
            btn_frame,
            text="安装补丁",
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color=ACCENT,
            hover_color=ACCENT_H,
            text_color="#ffffff",
            height=42,
            corner_radius=8,
            command=self._do_patch,
        )
        self._patch_btn.pack(side="left", expand=True, fill="x", padx=(0, 8))

        self._restore_btn = ctk.CTkButton(
            btn_frame,
            text="还原",
            font=ctk.CTkFont(size=14),
            fg_color=DIMMED,
            hover_color=DIMMED_H,
            text_color=TEXT,
            height=42,
            corner_radius=8,
            command=self._do_restore,
        )
        self._restore_btn.pack(side="right", expand=True, fill="x", padx=(8, 0))

        # ── Log area ─────────────────────────────────────────────────────
        log_header = ctk.CTkFrame(self, fg_color="transparent")
        log_header.pack(fill="x", padx=16)
        ctk.CTkLabel(log_header, text="运行日志",
                     font=ctk.CTkFont(size=11), text_color=SUBTEXT).pack(side="left")
        ctk.CTkButton(
            log_header,
            text="清空",
            width=40, height=20,
            fg_color="transparent",
            hover_color=SURFACE2,
            text_color=SUBTEXT,
            font=ctk.CTkFont(size=10),
            command=self._clear_log,
        ).pack(side="right")

        self._log = ctk.CTkTextbox(
            self,
            fg_color=LOG_BG,
            text_color=LOG_FG,
            font=ctk.CTkFont(family="Consolas", size=11),
            border_width=1,
            border_color=SURFACE,
            corner_radius=8,
            state="disabled",
        )
        self._log.pack(fill="both", expand=True, padx=16, pady=(4, 8))

        # ── Footer hint ──────────────────────────────────────────────────
        ctk.CTkLabel(
            self,
            text="使用前请关闭微信  ·  更新微信后需重新安装补丁",
            font=ctk.CTkFont(size=10),
            text_color=SUBTEXT,
        ).pack(pady=(0, 8))

        # Initial state
        self._set_buttons_enabled(False)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _log_line(self, text: str):
        """Append a line to the log area (thread-safe)."""
        def _do():
            self._log.configure(state="normal")
            self._log.insert("end", text + "\n")
            self._log.see("end")
            self._log.configure(state="disabled")
        self.after(0, _do)

    def _clear_log(self):
        self._log.configure(state="normal")
        self._log.delete("1.0", "end")
        self._log.configure(state="disabled")

    def _set_buttons_enabled(self, patch_on: bool, restore_on: bool = False):
        self._patch_btn.configure(state="normal" if patch_on else "disabled")
        self._restore_btn.configure(state="normal" if restore_on else "disabled")

    def _refresh_status(self, path: str):
        """Update version/status labels from the given install path."""
        if not path:
            self._version_label.configure(text="版本: —", text_color=SUBTEXT)
            self._status_label.configure(text="", text_color=SUBTEXT)
            self._backup_label.configure(text="")
            self._set_buttons_enabled(False)
            return

        version, status, msg = patcher.get_status(path, self._apps_cfg)
        color = STATUS_COLORS.get(status, SUBTEXT)
        badge = STATUS_LABELS.get(status, '')

        self._version_label.configure(
            text=f"版本: {version}" if version else "版本: —",
            text_color=TEXT)
        self._status_label.configure(text=badge, text_color=color)

        has_bak = patcher.backup_exists(path)
        self._backup_label.configure(
            text="备份: 存在" if has_bak else "",
            text_color=SUBTEXT)

        patch_ok = status in ('ok',)
        self._set_buttons_enabled(patch_ok, restore_on=has_bak)

    # ── Event handlers ────────────────────────────────────────────────────────

    def _auto_detect(self):
        self._log_line("正在自动查找微信安装路径…")

        def _detect():
            found = patcher.find_wechat_path()
            if found:
                self.after(0, lambda: self._path_var.set(found))
                self._log_line(f"找到: {found}")
            else:
                self._log_line("未自动找到，请手动选择路径")

        threading.Thread(target=_detect, daemon=True).start()

    def _browse(self):
        path = filedialog.askdirectory(title="选择微信安装目录")
        if path:
            self._path_var.set(path)

    def _on_path_change(self):
        path = self._path_var.get().strip()
        self._refresh_status(path)

    def _do_patch(self):
        path = self._path_var.get().strip()
        if not path:
            messagebox.showwarning("提示", "请先选择微信安装路径")
            return

        if sys.platform == 'win32' and not patcher.is_admin():
            messagebox.showerror(
                "权限不足",
                "修改系统文件需要管理员权限。\n请右键程序 → 以管理员身份运行。")
            return

        self._set_buttons_enabled(False)
        self._log_line("─" * 40)
        self._log_line("开始安装防撤回补丁…")

        def _run():
            try:
                patcher.patch(path, self._apps_cfg, self._log_line)
            except Exception as e:
                self._log_line(f"✗ 失败: {e}")
                self.after(0, lambda: messagebox.showerror("安装失败", str(e)))
            finally:
                self.after(0, lambda: self._refresh_status(path))

        threading.Thread(target=_run, daemon=True).start()

    def _do_restore(self):
        path = self._path_var.get().strip()
        if not path:
            messagebox.showwarning("提示", "请先选择微信安装路径")
            return

        if not messagebox.askyesno("确认还原", "确定要还原到备份版本吗？"):
            return

        self._set_buttons_enabled(False)
        self._log_line("─" * 40)
        self._log_line("开始还原…")

        def _run():
            try:
                patcher.restore(path, self._log_line)
            except Exception as e:
                self._log_line(f"✗ 失败: {e}")
                self.after(0, lambda: messagebox.showerror("还原失败", str(e)))
            finally:
                self.after(0, lambda: self._refresh_status(path))

        threading.Thread(target=_run, daemon=True).start()
