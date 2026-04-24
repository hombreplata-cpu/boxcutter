"""
rekordbox_tools_gui.py

Lexicon-inspired GUI launcher for BoxCutter.
Provides a visual interface for configuring and running all four scripts
without needing to touch the command line.

Requirements:
    pip install -r requirements.txt

Usage:
    python rekordbox_tools_gui.py
"""

import json
import os
import platform
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox
from tkinter import font as tkfont

# ─────────────────────────── Config persistence ────────────────────────────

CONFIG_FILE = Path.home() / ".boxcutter_config.json"

DEFAULT_CONFIG = {
    "music_root": "",
    "flac_root": "",
    "mp3_root": "",
    "delete_dir": str(Path.home() / "Desktop" / "DELETE"),
    "exclude_dirs": [],
}


def load_config():
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE) as f:
                data = json.load(f)
            cfg = DEFAULT_CONFIG.copy()
            cfg.update(data)
            return cfg
        except Exception:  # noqa: S110 — config load failure is expected; fall back to defaults
            pass
    return DEFAULT_CONFIG.copy()


def save_config(cfg):
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(cfg, f, indent=2)
    except Exception:  # noqa: S110 — best-effort save; failure is non-fatal
        pass


# ─────────────────────────── Colour palette ────────────────────────────────
# Inspired by Lexicon: deep navy blacks, electric cyan accents, tight typography

BG = "#0d1117"
BG_PANEL = "#161b22"
BG_INPUT = "#1c2128"
BG_HOVER = "#21262d"
ACCENT = "#00e5ff"
ACCENT_DIM = "#0097a7"
TEXT = "#e6edf3"
TEXT_DIM = "#7d8590"
BORDER = "#30363d"
GREEN = "#3fb950"
ORANGE = "#d29922"
RED = "#f85149"
FONT_MONO = "Consolas" if platform.system() == "Windows" else "Menlo"


SCRIPTS_DIR = Path(__file__).parent / "scripts"

# ────────────────────────────── Main App ───────────────────────────────────


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("BoxCutter")
        self.geometry("1100x740")
        self.minsize(900, 600)
        self.configure(bg=BG)
        self.resizable(True, True)

        self.config_data = load_config()
        self._build_ui()
        self._show_page("setup")

    # ── Layout ──────────────────────────────────────────────────────────────

    def _build_ui(self):
        # Sidebar
        self.sidebar = tk.Frame(self, bg=BG_PANEL, width=220)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        self._build_sidebar()

        # Main content area
        self.content = tk.Frame(self, bg=BG)
        self.content.pack(side="left", fill="both", expand=True)

        self.pages = {}
        self._build_page_setup()
        self._build_page_relocate()
        self._build_page_cleanup()
        self._build_page_remove_missing()
        self._build_page_strip_comments()

    def _build_sidebar(self):
        # Logo / header
        logo_frame = tk.Frame(self.sidebar, bg=BG_PANEL, pady=24)
        logo_frame.pack(fill="x")
        tk.Label(logo_frame, text="◈", font=(FONT_MONO, 22), fg=ACCENT, bg=BG_PANEL).pack()
        tk.Label(
            logo_frame, text="BoxCutter", font=(FONT_MONO, 11, "bold"), fg=TEXT, bg=BG_PANEL
        ).pack()
        tk.Label(
            logo_frame, text="for Rekordbox 7", font=(FONT_MONO, 9), fg=TEXT_DIM, bg=BG_PANEL
        ).pack(pady=(2, 0))

        sep = tk.Frame(self.sidebar, bg=BORDER, height=1)
        sep.pack(fill="x", padx=16, pady=8)

        nav_items = [
            ("setup", "⚙  Setup & Paths"),
            ("relocate", "⇄  Relocate Tracks"),
            ("cleanup", "⌫  Library Cleanup"),
            ("remove_missing", "✗  Remove Missing"),
            ("strip_comments", "⊘  Strip URL Comments"),
        ]

        self.nav_buttons = {}
        for page_id, label in nav_items:
            btn = tk.Label(
                self.sidebar,
                text=label,
                font=(FONT_MONO, 10),
                fg=TEXT_DIM,
                bg=BG_PANEL,
                anchor="w",
                padx=20,
                pady=10,
                cursor="hand2",
            )
            btn.pack(fill="x")
            btn.bind("<Button-1>", lambda e, p=page_id: self._show_page(p))
            btn.bind("<Enter>", lambda e, b=btn: b.configure(bg=BG_HOVER, fg=TEXT))
            btn.bind("<Leave>", lambda e, b=btn, p=page_id: self._nav_leave(b, p))
            self.nav_buttons[page_id] = btn

        # Version footer
        tk.Label(self.sidebar, text="v1.0.0", font=(FONT_MONO, 8), fg=TEXT_DIM, bg=BG_PANEL).pack(
            side="bottom", pady=12
        )

    def _nav_leave(self, btn, page_id):
        if getattr(self, "_active_page", None) == page_id:
            btn.configure(bg=BG_PANEL, fg=ACCENT)
        else:
            btn.configure(bg=BG_PANEL, fg=TEXT_DIM)

    def _show_page(self, page_id):
        for _pid, frame in self.pages.items():
            frame.pack_forget()
        self.pages[page_id].pack(fill="both", expand=True)
        self._active_page = page_id

        for pid, btn in self.nav_buttons.items():
            if pid == page_id:
                btn.configure(fg=ACCENT, bg=BG_PANEL)
            else:
                btn.configure(fg=TEXT_DIM, bg=BG_PANEL)

    # ── Reusable widget builders ─────────────────────────────────────────────

    def _page_frame(self):
        f = tk.Frame(self.content, bg=BG, padx=40, pady=32)
        return f

    def _heading(self, parent, title, subtitle=""):
        tk.Label(
            parent, text=title, font=(FONT_MONO, 18, "bold"), fg=TEXT, bg=BG, anchor="w"
        ).pack(fill="x")
        if subtitle:
            tk.Label(
                parent, text=subtitle, font=(FONT_MONO, 10), fg=TEXT_DIM, bg=BG, anchor="w"
            ).pack(fill="x", pady=(2, 0))
        tk.Frame(parent, bg=ACCENT, height=2).pack(fill="x", pady=(12, 20))

    def _path_row(self, parent, label, var, hint="", browse_dir=True):
        row = tk.Frame(parent, bg=BG)
        row.pack(fill="x", pady=5)
        tk.Label(
            row, text=label, font=(FONT_MONO, 9, "bold"), fg=TEXT_DIM, bg=BG, width=22, anchor="w"
        ).pack(side="left")
        entry = tk.Entry(
            row,
            textvariable=var,
            font=(FONT_MONO, 10),
            bg=BG_INPUT,
            fg=TEXT,
            insertbackground=ACCENT,
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=ACCENT,
        )
        entry.pack(side="left", fill="x", expand=True, ipady=6, padx=(0, 8))
        if hint:
            entry.insert(0, hint)
        btn = tk.Label(
            row,
            text="Browse",
            font=(FONT_MONO, 9),
            fg=ACCENT,
            bg=BG_INPUT,
            padx=10,
            pady=6,
            cursor="hand2",
            relief="flat",
        )
        btn.pack(side="left")
        if browse_dir:
            btn.bind("<Button-1>", lambda e: self._browse_dir(var))
        else:
            btn.bind("<Button-1>", lambda e: self._browse_file(var))
        return entry

    def _browse_dir(self, var):
        d = filedialog.askdirectory(title="Select folder")
        if d:
            var.set(d)
            save_config(self.config_data)

    def _browse_file(self, var):
        f = filedialog.askopenfilename(title="Select file")
        if f:
            var.set(f)

    def _checkbox(self, parent, text, var):
        cb = tk.Checkbutton(
            parent,
            text=text,
            variable=var,
            font=(FONT_MONO, 10),
            fg=TEXT,
            bg=BG,
            selectcolor=BG_INPUT,
            activebackground=BG,
            activeforeground=TEXT,
            cursor="hand2",
        )
        cb.pack(anchor="w", pady=3)

    def _run_button(self, parent, label, command):
        btn = tk.Label(
            parent,
            text=label,
            font=(FONT_MONO, 11, "bold"),
            fg=BG,
            bg=ACCENT,
            padx=24,
            pady=10,
            cursor="hand2",
        )
        btn.pack(anchor="w", pady=(16, 6))
        btn.bind("<Button-1>", lambda e: command())
        btn.bind("<Enter>", lambda e: btn.configure(bg=ACCENT_DIM))
        btn.bind("<Leave>", lambda e: btn.configure(bg=ACCENT))
        return btn

    def _dry_run_button(self, parent, label, command):
        btn = tk.Label(
            parent,
            text=label,
            font=(FONT_MONO, 10),
            fg=ACCENT,
            bg=BG_INPUT,
            padx=18,
            pady=8,
            cursor="hand2",
            relief="flat",
        )
        btn.pack(anchor="w", pady=(0, 16))
        btn.bind("<Button-1>", lambda e: command())
        btn.bind("<Enter>", lambda e: btn.configure(fg=TEXT))
        btn.bind("<Leave>", lambda e: btn.configure(fg=ACCENT))
        return btn

    def _output_console(self, parent):
        frame = tk.Frame(
            parent, bg=BG_PANEL, relief="flat", highlightthickness=1, highlightbackground=BORDER
        )
        frame.pack(fill="both", expand=True, pady=(12, 0))
        txt = tk.Text(
            frame,
            font=(FONT_MONO, 9),
            bg=BG_PANEL,
            fg=TEXT,
            insertbackground=ACCENT,
            relief="flat",
            bd=0,
            wrap="word",
            padx=12,
            pady=10,
            state="disabled",
        )
        txt.pack(fill="both", expand=True, side="left")
        sb = tk.Scrollbar(
            frame, command=txt.yview, bg=BG_PANEL, troughcolor=BG_PANEL, activebackground=BORDER
        )
        sb.pack(side="right", fill="y")
        txt.configure(yscrollcommand=sb.set)

        # Colour tags
        txt.tag_configure("accent", foreground=ACCENT)
        txt.tag_configure("green", foreground=GREEN)
        txt.tag_configure("orange", foreground=ORANGE)
        txt.tag_configure("red", foreground=RED)
        txt.tag_configure("dim", foreground=TEXT_DIM)
        return txt

    def _append_console(self, console, text, tag=None):
        console.configure(state="normal")
        if tag:
            console.insert("end", text + "\n", tag)
        else:
            console.insert("end", text + "\n")
        console.see("end")
        console.configure(state="disabled")

    def _clear_console(self, console):
        console.configure(state="normal")
        console.delete("1.0", "end")
        console.configure(state="disabled")

    # ── Script runner ────────────────────────────────────────────────────────

    def _run_script(self, console, script_name, args):
        self._clear_console(console)
        script_path = SCRIPTS_DIR / script_name
        if not script_path.exists():
            self._append_console(console, f"ERROR: script not found: {script_path}", "red")
            return

        cmd = [sys.executable, str(script_path)] + args
        self._append_console(console, "$ " + " ".join(cmd), "dim")
        self._append_console(console, "", None)

        q = queue.Queue()

        def reader(proc, q):
            for line in iter(proc.stdout.readline, ""):
                q.put(line)
            proc.stdout.close()
            q.put(None)

        def poll():
            try:
                while True:
                    line = q.get_nowait()
                    if line is None:
                        self._append_console(console, "\n── Done ──", "green")
                        return
                    line = line.rstrip()
                    if "[dry-run]" in line.lower():
                        tag = "orange"
                    elif "error" in line.lower() or "warn" in line.lower():
                        tag = "red"
                    elif (
                        line.startswith("===")
                        or line.startswith("---")
                        or line.startswith("SUMMARY")
                    ):
                        tag = "accent"
                    elif "->" in line:
                        tag = "green"
                    else:
                        tag = None
                    self._append_console(console, line, tag)
            except queue.Empty:
                pass
            self.after(50, poll)

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        t = threading.Thread(target=reader, args=(proc, q), daemon=True)
        t.start()
        poll()

    # ── Pages ────────────────────────────────────────────────────────────────

    # SETUP PAGE ─────────────────────────────────────────────────────────────
    def _build_page_setup(self):
        page = self._page_frame()
        self.pages["setup"] = page

        self._heading(
            page,
            "Setup & Paths",
            "Configure your music library locations. These paths are saved locally.",
        )

        self._v_music_root = tk.StringVar(value=self.config_data["music_root"])
        self._v_flac_root = tk.StringVar(value=self.config_data["flac_root"])
        self._v_mp3_root = tk.StringVar(value=self.config_data["mp3_root"])
        self._v_delete_dir = tk.StringVar(value=self.config_data["delete_dir"])

        for var, key in [
            (self._v_music_root, "music_root"),
            (self._v_flac_root, "flac_root"),
            (self._v_mp3_root, "mp3_root"),
            (self._v_delete_dir, "delete_dir"),
        ]:
            var.trace_add("write", lambda *a, k=key, v=var: self._on_path_change(k, v))

        section = tk.Frame(
            page,
            bg=BG_PANEL,
            relief="flat",
            highlightthickness=1,
            highlightbackground=BORDER,
            padx=20,
            pady=20,
        )
        section.pack(fill="x", pady=(0, 16))

        tk.Label(
            section, text="LIBRARY ROOTS", font=(FONT_MONO, 9, "bold"), fg=ACCENT, bg=BG_PANEL
        ).pack(anchor="w", pady=(0, 10))

        self._path_row(
            section,
            "Music Root",
            self._v_music_root,
            hint="Root folder containing all your DJ music",
        )
        self._path_row(
            section,
            "FLAC / Target Root",
            self._v_flac_root,
            hint="High-quality folder (relocate target)",
        )
        self._path_row(
            section,
            "MP3 / Source Root",
            self._v_mp3_root,
            hint="Folder to migrate away from (optional)",
        )
        self._path_row(
            section,
            "DELETE folder",
            self._v_delete_dir,
            hint="Where cleanup moves unreferenced files",
        )

        self._run_button(section, "  Save Paths  ", self._save_paths)

        # Info box
        info = tk.Frame(
            page,
            bg=BG_PANEL,
            relief="flat",
            highlightthickness=1,
            highlightbackground=BORDER,
            padx=20,
            pady=20,
        )
        info.pack(fill="x")
        tk.Label(
            info,
            text="ℹ  WHERE TO FIND REKORDBOX FILES",
            font=(FONT_MONO, 9, "bold"),
            fg=ACCENT,
            bg=BG_PANEL,
        ).pack(anchor="w")

        hints = [
            ("Rekordbox DB (Windows)", r"%APPDATA%\Pioneer\rekordbox\master.db"),
            ("Rekordbox DB (macOS)", "~/Library/Pioneer/rekordbox/master.db"),
            ("Backups location", "Same folder as master.db (timestamped)"),
        ]
        for label, path in hints:
            row = tk.Frame(info, bg=BG_PANEL)
            row.pack(fill="x", pady=3)
            tk.Label(
                row,
                text=label,
                font=(FONT_MONO, 9, "bold"),
                fg=TEXT_DIM,
                bg=BG_PANEL,
                width=30,
                anchor="w",
            ).pack(side="left")
            tk.Label(row, text=path, font=(FONT_MONO, 9), fg=TEXT, bg=BG_PANEL, anchor="w").pack(
                side="left"
            )

    def _on_path_change(self, key, var):
        self.config_data[key] = var.get()

    def _save_paths(self):
        save_config(self.config_data)
        messagebox.showinfo("Saved", "Paths saved to ~/.boxcutter_config.json")

    # RELOCATE PAGE ──────────────────────────────────────────────────────────
    def _build_page_relocate(self):
        page = self._page_frame()
        self.pages["relocate"] = page

        self._heading(
            page,
            "Relocate Tracks",
            "Re-point broken or MP3 track paths to a FLAC (or other) target root.",
        )

        opts_frame = tk.Frame(
            page,
            bg=BG_PANEL,
            relief="flat",
            highlightthickness=1,
            highlightbackground=BORDER,
            padx=20,
            pady=20,
        )
        opts_frame.pack(fill="x", pady=(0, 8))

        self._v_rel_target = tk.StringVar(value=self.config_data.get("flac_root", ""))
        self._v_rel_source = tk.StringVar(value=self.config_data.get("mp3_root", ""))
        self._v_rel_pref_ext = tk.StringVar(value="flac")
        self._v_rel_missing = tk.BooleanVar(value=False)
        self._v_rel_all = tk.BooleanVar(value=False)

        self._path_row(opts_frame, "Target Root  ↗", self._v_rel_target)
        self._path_row(opts_frame, "Source Root  ↙", self._v_rel_source)

        row = tk.Frame(opts_frame, bg=BG_PANEL)
        row.pack(fill="x", pady=5)
        tk.Label(
            row,
            text="Prefer extension",
            font=(FONT_MONO, 9, "bold"),
            fg=TEXT_DIM,
            bg=BG_PANEL,
            width=22,
            anchor="w",
        ).pack(side="left")
        ext_entry = tk.Entry(
            row,
            textvariable=self._v_rel_pref_ext,
            font=(FONT_MONO, 10),
            bg=BG_INPUT,
            fg=TEXT,
            insertbackground=ACCENT,
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=ACCENT,
            width=10,
        )
        ext_entry.pack(side="left", ipady=6)

        self._checkbox(
            opts_frame, "Missing only  (skip tracks that already resolve)", self._v_rel_missing
        )
        self._checkbox(opts_frame, "All tracks  (re-check even existing paths)", self._v_rel_all)

        console = self._output_console(page)

        self._dry_run_button(
            page, "  ▷  Dry Run (preview only)  ", lambda: self._run_relocate(console, dry=True)
        )
        self._run_button(
            page, "  ▶  Run Relocate  ", lambda: self._run_relocate(console, dry=False)
        )

        self._rel_console = console

    def _run_relocate(self, console, dry):
        target = self._v_rel_target.get().strip()
        source = self._v_rel_source.get().strip()
        if not target:
            messagebox.showwarning(
                "Missing Path", "Set a Target Root first (Setup tab or field above)."
            )
            return
        args = ["--target-root", target]
        if source:
            args += ["--source-root", source]
        if self._v_rel_pref_ext.get().strip():
            args += ["--prefer-ext", self._v_rel_pref_ext.get().strip()]
        if self._v_rel_missing.get():
            args.append("--missing-only")
        if self._v_rel_all.get():
            args.append("--all-tracks")
        if dry:
            args.append("--dry-run")
        self._run_script(console, "rekordbox_relocate.py", args)

    # CLEANUP PAGE ───────────────────────────────────────────────────────────
    def _build_page_cleanup(self):
        page = self._page_frame()
        self.pages["cleanup"] = page

        self._heading(
            page,
            "Library Cleanup",
            "Find audio files on disk not referenced in Rekordbox and move them to a DELETE folder.",
        )

        opts_frame = tk.Frame(
            page,
            bg=BG_PANEL,
            relief="flat",
            highlightthickness=1,
            highlightbackground=BORDER,
            padx=20,
            pady=20,
        )
        opts_frame.pack(fill="x", pady=(0, 8))

        self._v_cl_scan_root = tk.StringVar(value=self.config_data.get("music_root", ""))
        self._v_cl_delete_dir = tk.StringVar(value=self.config_data.get("delete_dir", ""))
        self._v_cl_exclude = tk.StringVar(value="")

        self._path_row(opts_frame, "Scan Root", self._v_cl_scan_root)
        self._path_row(opts_frame, "DELETE folder", self._v_cl_delete_dir)
        self._path_row(opts_frame, "Exclude folder (opt)", self._v_cl_exclude)

        console = self._output_console(page)

        self._dry_run_button(
            page, "  ▷  Dry Run (preview only)  ", lambda: self._run_cleanup(console, dry=True)
        )
        self._run_button(page, "  ▶  Run Cleanup  ", lambda: self._run_cleanup(console, dry=False))

    def _run_cleanup(self, console, dry):
        scan = self._v_cl_scan_root.get().strip()
        if not scan:
            messagebox.showwarning("Missing Path", "Set a Scan Root first.")
            return
        args = ["--scan-root", scan]
        dd = self._v_cl_delete_dir.get().strip()
        if dd:
            args += ["--delete-dir", dd]
        exc = self._v_cl_exclude.get().strip()
        if exc:
            args += ["--exclude", exc]
        if dry:
            args.append("--dry-run")
        self._run_script(console, "rekordbox_cleanup.py", args)

    # REMOVE MISSING PAGE ────────────────────────────────────────────────────
    def _build_page_remove_missing(self):
        page = self._page_frame()
        self.pages["remove_missing"] = page

        self._heading(
            page,
            "Remove Missing Tracks",
            "Soft-delete tracks from the Rekordbox DB whose files no longer exist on disk.",
        )

        info = tk.Frame(
            page,
            bg=BG_PANEL,
            relief="flat",
            highlightthickness=1,
            highlightbackground=BORDER,
            padx=20,
            pady=14,
        )
        info.pack(fill="x", pady=(0, 8))
        tk.Label(
            info,
            text="This performs a soft delete (rb_local_deleted=1) — identical to how "
            "Rekordbox removes tracks itself. No rows are destroyed. A timestamped backup "
            "is created automatically before any changes.",
            font=(FONT_MONO, 9),
            fg=TEXT_DIM,
            bg=BG_PANEL,
            wraplength=700,
            justify="left",
        ).pack(anchor="w")

        console = self._output_console(page)

        self._dry_run_button(
            page,
            "  ▷  Dry Run (preview only)  ",
            lambda: self._run_script(console, "rekordbox_remove_missing.py", ["--dry-run"]),
        )
        self._run_button(
            page, "  ▶  Run Remove Missing  ", lambda: self._confirm_run_remove_missing(console)
        )

    def _confirm_run_remove_missing(self, console):
        if messagebox.askyesno(
            "Confirm",
            "This will soft-delete tracks from the Rekordbox database.\n"
            "A backup will be created first. Continue?",
        ):
            self._run_script(console, "rekordbox_remove_missing.py", [])

    # STRIP COMMENTS PAGE ────────────────────────────────────────────────────
    def _build_page_strip_comments(self):
        page = self._page_frame()
        self.pages["strip_comments"] = page

        self._heading(
            page,
            "Strip URL Comments",
            "Remove URLs from MP3/FLAC comment tags across your entire library.",
        )

        opts_frame = tk.Frame(
            page,
            bg=BG_PANEL,
            relief="flat",
            highlightthickness=1,
            highlightbackground=BORDER,
            padx=20,
            pady=20,
        )
        opts_frame.pack(fill="x", pady=(0, 8))

        self._v_sc_dir1 = tk.StringVar(value=self.config_data.get("music_root", ""))
        self._v_sc_dir2 = tk.StringVar(value="")

        self._path_row(opts_frame, "Directory 1", self._v_sc_dir1)
        self._path_row(opts_frame, "Directory 2 (opt)", self._v_sc_dir2)

        console = self._output_console(page)

        self._dry_run_button(
            page, "  ▷  Dry Run (preview only)  ", lambda: self._run_strip(console, dry=True)
        )
        self._run_button(
            page, "  ▶  Strip URL Comments  ", lambda: self._run_strip(console, dry=False)
        )

    def _run_strip(self, console, dry):
        dirs = [
            d
            for d in [
                self._v_sc_dir1.get().strip(),
                self._v_sc_dir2.get().strip(),
            ]
            if d
        ]
        if not dirs:
            messagebox.showwarning("Missing Path", "Set at least one directory to scan.")
            return
        args = dirs
        if not dry:
            args = args + ["--write"]
        self._run_script(console, "strip_comment_urls.py", args)


# ───────────────────────────────────────────────────────────────────────────


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
