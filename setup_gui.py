#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk

PROJECT = Path(__file__).resolve().parent
LOGO = PROJECT / "setup-logo.png"
DATA = Path.home() / ".local/share/moriarty-v5"
VENV = DATA / "venv"
CONFIG = DATA / "gokboru/configuration.json"
LAUNCHER = Path.home() / ".local/bin/moriarty"


class SetupApp(tk.Tk):
    BG = "#070b12"
    SIDEBAR = "#0a111b"
    PANEL = "#0d1724"
    FIELD = "#111f2e"
    BORDER = "#24384c"
    RED = "#ef2948"
    BLUE = "#22a8ff"
    GREEN = "#3ad6a0"
    TEXT = "#eef6ff"
    MUTED = "#8196aa"
    STEPS = (
        ("01", "Welcome", "Installation overview"),
        ("02", "Identity", "Microsoft and Telegram"),
        ("03", "Intelligence", "Optional API connections"),
        ("04", "Review", "Confirm and install"),
    )

    def __init__(self) -> None:
        super().__init__()
        self.title("Gökbörü Intelligence — Setup")
        self.geometry("1040x720")
        self.minsize(900, 640)
        self.configure(bg=self.BG)
        self.step = 0
        self.installing = False
        self.web_process = None
        self.cli_process = None
        self.fields: dict[str, tk.StringVar] = {}
        self.step_buttons: list[tk.Label] = []
        self.pages: list[tk.Frame] = []
        self._styles()
        self._layout()
        self._show_step(0)
        self.protocol("WM_DELETE_WINDOW", self._close)

    def _styles(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(
            "Setup.TEntry", fieldbackground=self.FIELD, foreground=self.TEXT,
            insertcolor=self.TEXT, bordercolor=self.BORDER, lightcolor=self.BORDER,
            darkcolor=self.BORDER, padding=11,
        )
        style.map("Setup.TEntry", bordercolor=[("focus", self.BLUE)])
        style.configure("Setup.Horizontal.TProgressbar", troughcolor=self.FIELD, background=self.RED, borderwidth=0)

    def _layout(self) -> None:
        shell = tk.Frame(self, bg=self.BG)
        shell.pack(fill="both", expand=True)
        self._sidebar(shell)
        workspace = tk.Frame(shell, bg=self.BG)
        workspace.pack(side="left", fill="both", expand=True)

        header = tk.Frame(workspace, bg=self.BG, height=92)
        header.pack(fill="x", padx=42, pady=(24, 0))
        header.pack_propagate(False)
        self.eyebrow = tk.Label(header, text="SECURE INSTALLATION", fg=self.RED, bg=self.BG, font=("DejaVu Sans Mono", 10, "bold"))
        self.eyebrow.pack(anchor="w", pady=(4, 5))
        self.heading = tk.Label(header, text="", fg=self.TEXT, bg=self.BG, font=("DejaVu Sans", 25, "bold"))
        self.heading.pack(anchor="w")
        self.subtitle = tk.Label(header, text="", fg=self.MUTED, bg=self.BG, font=("DejaVu Sans", 10))
        self.subtitle.pack(anchor="w", pady=(4, 0))

        self.page_host = tk.Frame(workspace, bg=self.BG)
        self.page_host.pack(fill="both", expand=True, padx=42, pady=(8, 18))
        self._welcome_page()
        self._identity_page()
        self._api_page()
        self._review_page()

        footer = tk.Frame(workspace, bg="#080e16", height=86, highlightbackground="#182738", highlightthickness=1)
        footer.pack(fill="x", side="bottom")
        footer.pack_propagate(False)
        self.footer_status = tk.Label(footer, text="Step 1 of 4", fg=self.MUTED, bg="#080e16", font=("DejaVu Sans Mono", 9))
        self.footer_status.pack(side="left", padx=42)
        actions = tk.Frame(footer, bg="#080e16")
        actions.pack(side="right", padx=34, pady=18)
        self.back_button = self._button(actions, "BACK", self.back, secondary=True)
        self.back_button.pack(side="left", padx=6)
        self.next_button = self._button(actions, "CONTINUE", self.next)
        self.next_button.pack(side="left", padx=6)

    def _sidebar(self, parent: tk.Widget) -> None:
        side = tk.Frame(parent, width=285, bg=self.SIDEBAR, highlightbackground="#192939", highlightthickness=1)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        brand = tk.Frame(side, bg=self.SIDEBAR)
        brand.pack(fill="x", padx=24, pady=(25, 25))
        if LOGO.exists():
            self.logo_image = tk.PhotoImage(file=str(LOGO))
            tk.Label(brand, image=self.logo_image, bg=self.SIDEBAR, width=70, height=70).pack(side="left", padx=(0, 13))
        words = tk.Frame(brand, bg=self.SIDEBAR); words.pack(side="left")
        tk.Label(words, text="GÖKBÖRÜ", fg=self.RED, bg=self.SIDEBAR, font=("DejaVu Sans", 18, "bold")).pack(anchor="w", pady=(11, 0))
        tk.Label(words, text="INTELLIGENCE", fg=self.BLUE, bg=self.SIDEBAR, font=("DejaVu Sans Mono", 9, "bold")).pack(anchor="w", pady=(2, 0))
        for number, title, detail in self.STEPS:
            row = tk.Frame(side, bg=self.SIDEBAR, height=72)
            row.pack(fill="x", padx=18, pady=2)
            row.pack_propagate(False)
            marker = tk.Label(row, text=number, width=4, fg=self.MUTED, bg=self.FIELD, font=("DejaVu Sans Mono", 9, "bold"))
            marker.pack(side="left", fill="y", padx=(0, 12))
            words = tk.Frame(row, bg=self.SIDEBAR)
            words.pack(side="left", fill="both", expand=True)
            title_label = tk.Label(words, text=title, fg=self.TEXT, bg=self.SIDEBAR, font=("DejaVu Sans", 10, "bold"))
            title_label.pack(anchor="w", pady=(14, 1))
            tk.Label(words, text=detail, fg=self.MUTED, bg=self.SIDEBAR, font=("DejaVu Sans", 8)).pack(anchor="w")
            self.step_buttons.append(marker)
        tk.Label(side, text="LOCAL  /  PRIVATE\nNo investigation data leaves this device\nunless a selected provider requires it.", justify="left", fg="#587086", bg=self.SIDEBAR, font=("DejaVu Sans Mono", 8)).pack(side="bottom", anchor="w", padx=30, pady=28)

    def _page(self) -> tk.Frame:
        page = tk.Frame(self.page_host, bg=self.BG)
        page.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.pages.append(page)
        return page

    def _welcome_page(self) -> None:
        page = self._page()
        hero = self._card(page)
        hero.pack(fill="both", expand=True, pady=(4, 0))
        tk.Label(hero, text="G", fg=self.RED, bg=self.PANEL, font=("DejaVu Sans", 72, "bold")).pack(pady=(46, 4))
        tk.Label(hero, text="A clean, isolated intelligence workspace", fg=self.TEXT, bg=self.PANEL, font=("DejaVu Sans", 18, "bold")).pack()
        tk.Label(hero, text="Setup creates a private runtime, installs Chromium, and connects only the services you choose.", fg=self.MUTED, bg=self.PANEL, font=("DejaVu Sans", 10)).pack(pady=(8, 28))
        features = tk.Frame(hero, bg=self.PANEL)
        features.pack()
        for text in ("Isolated Python runtime", "Private local configuration", "Visible browser diagnostics"):
            tk.Label(features, text=f"  ✓  {text}  ", fg=self.GREEN, bg="#10231f", font=("DejaVu Sans", 9, "bold"), padx=9, pady=7).pack(side="left", padx=5)

    def _identity_page(self) -> None:
        page = self._page()
        grid = tk.Frame(page, bg=self.BG)
        grid.pack(fill="both", expand=True)
        left = self._card(grid); right = self._card(grid)
        left.pack(side="left", fill="both", expand=True, padx=(0, 9)); right.pack(side="left", fill="both", expand=True, padx=(9, 0))
        self._section(left, "MICROSOFT IDENTITY", "Used automatically by Truecaller and Sync.me")
        self._field(left, "microsoft_email", "Microsoft / Hotmail email")
        self._field(left, "microsoft_password", "Microsoft password", secret=True)
        tk.Label(left, text="If either field is missing, both browser identity providers are marked unavailable.", wraplength=290, justify="left", fg="#f4b942", bg=self.PANEL, font=("DejaVu Sans", 9)).pack(anchor="w", padx=24, pady=8)
        self._section(right, "TELEGRAM API", "Official API integration — no browser module")
        self._field(right, "telegram_api_id", "Telegram API ID")
        self._field(right, "telegram_api_hash", "Telegram API Hash", secret=True)
        tk.Label(right, text="Create free API credentials at my.telegram.org. These fields may be left blank and configured later.", wraplength=290, justify="left", fg=self.MUTED, bg=self.PANEL, font=("DejaVu Sans", 9)).pack(anchor="w", padx=24, pady=8)

    def _api_page(self) -> None:
        page = self._page()
        card = self._card(page); card.pack(fill="both", expand=True)
        self._section(card, "INTELLIGENCE CONNECTIONS", "Optional — services left blank are skipped")
        columns = tk.Frame(card, bg=self.PANEL); columns.pack(fill="both", expand=True, padx=12)
        left = tk.Frame(columns, bg=self.PANEL); right = tk.Frame(columns, bg=self.PANEL)
        left.pack(side="left", fill="both", expand=True, padx=8); right.pack(side="left", fill="both", expand=True, padx=8)
        for key, label in (("github_token", "GitHub Token"), ("gemini_api_key", "Gemini API Key"), ("brave_api_key", "Brave API Key")):
            self._field(left, key, label, secret=True)
        for key, label in (("breachdirectory_api_key", "BreachDirectory API Key"), ("hudsonrock_api_key", "Hudson Rock API Key"), ("opensanctions_api_key", "OpenSanctions API Key")):
            self._field(right, key, label, secret=True)

    def _review_page(self) -> None:
        page = self._page()
        card = self._card(page); card.pack(fill="both", expand=True)
        self._section(card, "READY TO INSTALL", "Review the installation target and configured services")
        self.review = tk.Label(card, text="", justify="left", anchor="nw", fg=self.TEXT, bg="#0a121d", font=("DejaVu Sans Mono", 9), padx=18, pady=13)
        self.review.pack(fill="x", padx=24, pady=(4, 10))
        tk.Label(card, text="INSTALLATION ACTIVITY", fg=self.BLUE, bg=self.PANEL, font=("DejaVu Sans Mono", 9, "bold")).pack(anchor="w", padx=24, pady=(2, 5))
        self.install_log = tk.Text(card, height=11, bg="#05090f", fg="#b9d3e8", insertbackground=self.TEXT, relief="flat", borderwidth=0, font=("DejaVu Sans Mono", 8), padx=12, pady=10, wrap="word", state="disabled")
        self.install_log.pack(fill="both", expand=True, padx=24, pady=(0, 10))
        self.progress = ttk.Progressbar(card, style="Setup.Horizontal.TProgressbar", maximum=100, mode="determinate")
        self.progress.pack(fill="x", padx=24, pady=(0, 8))
        progress_row = tk.Frame(card, bg=self.PANEL); progress_row.pack(fill="x", padx=24, pady=(0, 18))
        self.install_status = tk.Label(progress_row, text="No changes have been made yet.", fg=self.MUTED, bg=self.PANEL, font=("DejaVu Sans Mono", 9))
        self.install_status.pack(side="left")
        self.progress_percent = tk.Label(progress_row, text="0%", fg=self.BLUE, bg=self.PANEL, font=("DejaVu Sans Mono", 9, "bold"))
        self.progress_percent.pack(side="right")

    def _card(self, parent: tk.Widget) -> tk.Frame:
        return tk.Frame(parent, bg=self.PANEL, highlightbackground=self.BORDER, highlightthickness=1)

    def _section(self, parent: tk.Widget, title: str, subtitle: str) -> None:
        tk.Label(parent, text=title, fg=self.RED, bg=self.PANEL, font=("DejaVu Sans Mono", 10, "bold")).pack(anchor="w", padx=24, pady=(22, 3))
        tk.Label(parent, text=subtitle, fg=self.MUTED, bg=self.PANEL, font=("DejaVu Sans", 9)).pack(anchor="w", padx=24, pady=(0, 17))

    def _field(self, parent: tk.Widget, key: str, label: str, secret: bool = False) -> None:
        tk.Label(parent, text=label, fg=self.TEXT, bg=self.PANEL, font=("DejaVu Sans", 9, "bold")).pack(anchor="w", padx=24)
        value = self.fields.setdefault(key, tk.StringVar())
        ttk.Entry(parent, textvariable=value, show="•" if secret else "", style="Setup.TEntry").pack(fill="x", padx=24, pady=(5, 15))

    def _button(self, parent: tk.Widget, text: str, command, secondary: bool = False) -> tk.Button:
        return tk.Button(parent, text=text, command=command, bg=self.FIELD if secondary else self.RED, fg=self.TEXT, activebackground=self.BORDER if secondary else "#ff3655", activeforeground="white", relief="flat", borderwidth=0, padx=25, pady=11, font=("DejaVu Sans", 9, "bold"), cursor="hand2")

    def _show_step(self, index: int) -> None:
        self.step = max(0, min(index, len(self.pages) - 1))
        self.pages[self.step].tkraise()
        number, title, detail = self.STEPS[self.step]
        self.heading.configure(text=title)
        self.subtitle.configure(text=detail)
        self.footer_status.configure(text=f"Step {self.step + 1} of {len(self.STEPS)}")
        for idx, marker in enumerate(self.step_buttons):
            marker.configure(bg=self.RED if idx == self.step else self.FIELD, fg="white" if idx == self.step else self.MUTED)
        self.back_button.configure(state="disabled" if self.step == 0 or self.installing else "normal")
        self.next_button.configure(text="INSTALL" if self.step == 3 else "CONTINUE", state="disabled" if self.installing else "normal", command=self.next)
        if self.step == 3:
            self._update_review()

    def next(self) -> None:
        if self.installing:
            return
        if self.step < 3:
            self._show_step(self.step + 1)
        else:
            self._start_install()

    def back(self) -> None:
        if not self.installing and self.step > 0:
            self._show_step(self.step - 1)

    def _update_review(self) -> None:
        configured = [label for key, label in (
            ("microsoft_email", "Microsoft identity"), ("telegram_api_id", "Telegram API"),
            ("github_token", "GitHub"), ("gemini_api_key", "Gemini"), ("brave_api_key", "Brave"),
            ("breachdirectory_api_key", "BreachDirectory"), ("hudsonrock_api_key", "Hudson Rock"),
            ("opensanctions_api_key", "OpenSanctions"),
        ) if self.fields[key].get().strip()]
        microsoft_ready = bool(self.fields["microsoft_email"].get().strip() and self.fields["microsoft_password"].get())
        lines = [
            f"PROJECT       {PROJECT}", f"RUNTIME       {VENV}", f"CONFIG        {CONFIG}", "",
            f"MICROSOFT     {'READY' if microsoft_ready else 'NOT CONFIGURED — Truecaller and Sync.me disabled'}",
            f"CONNECTIONS   {', '.join(configured) if configured else 'None'}", "",
            "Security       Local configuration mode 600; secrets excluded from reports and logs.",
        ]
        self.review.configure(text="\n".join(lines))

    def _start_install(self) -> None:
        self.installing = True
        self.back_button.configure(state="disabled")
        self.next_button.configure(state="disabled", text="INSTALLING…")
        threading.Thread(target=self._install, daemon=True).start()

    def _ui_progress(self, value: float, text: str | None = None) -> None:
        value = max(0.0, min(100.0, value))
        def update() -> None:
            self.progress.configure(value=value)
            self.progress_percent.configure(text=f"{round(value)}%")
            if text is not None:
                self.install_status.configure(text=text)
        self.after(0, update)

    def _append_install_log(self, text: str) -> None:
        def write() -> None:
            self.install_log.configure(state="normal")
            self.install_log.insert("end", text)
            self.install_log.see("end")
            self.install_log.configure(state="disabled")
        self.after(0, write)

    def _run(self, command: list[str], progress_start: float, progress_end: float) -> None:
        safe = " ".join(command[:4])
        self._append_install_log(f"\n$ {safe}\n")
        process = subprocess.Popen(
            command, cwd=PROJECT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
        )
        captured: list[str] = []
        activity = progress_start
        span = progress_end - progress_start
        assert process.stdout is not None
        for line in iter(process.stdout.readline, ""):
            captured.append(line)
            self._append_install_log(line)
            percentages = re.findall(r"(?<!\d)(\d{1,3}(?:\.\d+)?)%", line)
            if percentages:
                reported = min(100.0, float(percentages[-1]))
                activity = max(activity, progress_start + span * reported / 100.0)
            elif re.search(r"Downloading|Collecting|Installing collected|Successfully installed|Unpacking|Setting up", line, re.IGNORECASE):
                activity = min(progress_end - 0.5, activity + max(0.35, span / 30.0))
            self._ui_progress(activity)
        code = process.wait()
        if code:
            raise subprocess.CalledProcessError(code, command, stderr="".join(captured[-80:]))
        self._ui_progress(progress_end)

    def _install(self) -> None:
        try:
            self._ui_progress(1, "Preparing isolated Python environment…")
            DATA.mkdir(parents=True, exist_ok=True)
            if not (VENV / "bin/python").exists():
                self._run([sys.executable, "-m", "venv", str(VENV)], 1, 8)
            else:
                self._ui_progress(8)
            python = str(VENV / "bin/python")
            self._ui_progress(8, "Updating the isolated package manager…")
            self._run([python, "-m", "pip", "install", "--upgrade", "pip"], 8, 18)
            self._ui_progress(18, "Installing Gökbörü components…")
            self._run([python, "-m", "pip", "install", "--no-cache-dir", "--force-reinstall", "-e", str(PROJECT)], 18, 68)
            self._ui_progress(68, "Downloading and preparing Chromium…")
            self._run([python, "-m", "playwright", "install", "chromium"], 68, 94)
            self._ui_progress(96, "Saving private local configuration…")
            CONFIG.parent.mkdir(parents=True, exist_ok=True)
            try:
                current = json.loads(CONFIG.read_text(encoding="utf-8")) if CONFIG.exists() else {}
            except (OSError, json.JSONDecodeError):
                current = {}
            for key, value in self.fields.items():
                entered = value.get() if key == "microsoft_password" else value.get().strip()
                if entered:
                    current[key] = entered
            current.update({"setup_complete": True, "language": "en"})
            CONFIG.write_text(json.dumps(current, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            CONFIG.chmod(0o600)
            LAUNCHER.parent.mkdir(parents=True, exist_ok=True)
            LAUNCHER.write_text(f'#!/usr/bin/env bash\nset -euo pipefail\nexport PYTHONPATH="{PROJECT}/src${{PYTHONPATH:+:$PYTHONPATH}}"\nexec "{python}" -m moriarty "$@"\n', encoding="utf-8")
            LAUNCHER.chmod(0o700)
            self._ui_progress(100, "Installation complete")
            self.after(0, self._complete)
        except Exception as exc:
            detail = ((exc.stderr if isinstance(exc, subprocess.CalledProcessError) else str(exc)) or str(exc))[-1800:]
            self.after(0, lambda d=detail: self._failed(d))

    def _complete(self) -> None:
        self.installing = False
        self._launch_control_center()

    def _failed(self, detail: str) -> None:
        self.installing = False
        self.install_status.configure(text="Installation failed")
        self.next_button.configure(text="RETRY", state="normal", command=self._start_install)
        self.back_button.configure(state="normal")
        messagebox.showerror("Installation error", detail)

    @staticmethod
    def _strip_ansi(value: str) -> str:
        if "\r" in value:
            value = value.rsplit("\r", 1)[-1]
        return re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", value)

    def _launch_control_center(self) -> None:
        for child in self.winfo_children():
            child.destroy()
        self.title("Gökbörü Intelligence — Control Center")
        self.geometry("1120x760")
        header = tk.Frame(self, bg=self.SIDEBAR, height=94, highlightbackground=self.RED, highlightthickness=1)
        header.pack(fill="x"); header.pack_propagate(False)
        if LOGO.exists():
            self.control_logo = tk.PhotoImage(file=str(LOGO))
            tk.Label(header, image=self.control_logo, bg=self.SIDEBAR, width=72, height=72).pack(side="left", padx=(24, 12), pady=10)
        title = tk.Frame(header, bg=self.SIDEBAR); title.pack(side="left", pady=18)
        tk.Label(title, text="GÖKBÖRÜ INTELLIGENCE", fg=self.TEXT, bg=self.SIDEBAR, font=("DejaVu Sans", 17, "bold")).pack(anchor="w")
        tk.Label(title, text="LOCAL ANALYST CONTROL CENTER", fg=self.BLUE, bg=self.SIDEBAR, font=("DejaVu Sans Mono", 9, "bold")).pack(anchor="w", pady=4)
        self.service_label = tk.Label(header, text="● STARTING SERVICES", fg="#f4b942", bg=self.SIDEBAR, font=("DejaVu Sans Mono", 9, "bold"))
        self.service_label.pack(side="right", padx=26)

        bar = tk.Frame(self, bg=self.BG); bar.pack(fill="x", padx=24, pady=(16, 10))
        self._button(bar, "OPEN WEB UI", self._open_web).pack(side="left")
        self._button(bar, "CLEAR CONSOLE", self._clear_terminal, secondary=True).pack(side="left", padx=8)
        tk.Label(bar, text="CLI CONSOLE  /  INTERACTIVE", fg=self.RED, bg=self.BG, font=("DejaVu Sans Mono", 9, "bold")).pack(side="right", pady=12)

        terminal_frame = tk.Frame(self, bg=self.PANEL, highlightbackground=self.BORDER, highlightthickness=1)
        terminal_frame.pack(fill="both", expand=True, padx=24, pady=(0, 22))
        self.terminal = tk.Text(terminal_frame, bg="#03070c", fg="#d8e7f2", insertbackground=self.TEXT, font=("DejaVu Sans Mono", 10), relief="flat", padx=15, pady=14, wrap="word", state="disabled")
        self.terminal.pack(fill="both", expand=True)
        self.terminal.tag_configure("prompt", foreground=self.RED, font=("DejaVu Sans Mono", 10, "bold"))
        self.terminal.tag_configure("success", foreground=self.GREEN)
        self.terminal.tag_configure("error", foreground="#ff5269")
        self.terminal.tag_configure("info", foreground=self.BLUE)
        self.terminal.tag_configure("heading", foreground="#ffd166", font=("DejaVu Sans Mono", 10, "bold"))
        self.terminal.tag_configure("table", foreground="#7dd3fc")
        self.terminal.tag_configure("muted", foreground=self.MUTED)
        command_bar = tk.Frame(terminal_frame, bg="#09111b", height=54); command_bar.pack(fill="x"); command_bar.pack_propagate(False)
        tk.Label(command_bar, text="gokboru  ›", fg=self.RED, bg="#09111b", font=("DejaVu Sans Mono", 10, "bold")).pack(side="left", padx=(15, 8))
        self.command_entry = tk.Entry(command_bar, bg="#09111b", fg=self.TEXT, insertbackground=self.TEXT, relief="flat", borderwidth=0, font=("DejaVu Sans Mono", 10))
        self.command_entry.pack(side="left", fill="both", expand=True, padx=(0, 12), pady=10)
        self.command_entry.bind("<Return>", self._send_command)
        self.command_entry.focus_set()
        self._start_services()

    def _start_services(self) -> None:
        python = str(VENV / "bin/python")
        env = os.environ.copy(); env["PYTHONPATH"] = str(PROJECT / "src") + ((":" + env["PYTHONPATH"]) if env.get("PYTHONPATH") else ""); env["PYTHONUNBUFFERED"] = "1"
        self.web_process = subprocess.Popen([python, "-u", "-m", "moriarty.web_workspace_entry"], cwd=PROJECT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
        self.cli_process = subprocess.Popen([python, "-u", "-m", "moriarty.console"], cwd=PROJECT, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=0)
        threading.Thread(target=self._read_cli, daemon=True).start()
        threading.Thread(target=self._read_web, daemon=True).start()
        self.service_label.configure(text="● ENGINE ONLINE", fg=self.GREEN)

    def _append_terminal(self, value: str) -> None:
        clean = self._strip_ansi(value)
        if not clean:
            return
        def write() -> None:
            self.terminal.configure(state="normal")
            for line in clean.splitlines(keepends=True):
                lowered = line.lower()
                stripped = line.strip()
                if "gokboru" in lowered and ">" in line:
                    tag = "prompt"
                elif any(token in lowered for token in ("[-]", "error", "failed", "unknown command", "not running")):
                    tag = "error"
                elif any(token in lowered for token in ("[+]", "complete", "ready", "engine online")):
                    tag = "success"
                elif stripped.startswith(("[*]", "[WEB]")):
                    tag = "info"
                elif stripped.startswith(("+", "|", "╔", "║", "╚")):
                    tag = "table"
                elif stripped and (stripped.isupper() or stripped.endswith("COMMANDS")):
                    tag = "heading"
                elif stripped.startswith(("Report:", "JSON report:")):
                    tag = "muted"
                else:
                    tag = "info"
                self.terminal.insert("end", line, tag)
            self.terminal.see("end")
            self.terminal.configure(state="disabled")
        self.after(0, write)

    def _read_cli(self) -> None:
        if not self.cli_process or not self.cli_process.stdout:
            return
        while True:
            raw = os.read(self.cli_process.stdout.fileno(), 1024)
            if not raw:
                break
            self._append_terminal(raw.decode("utf-8", errors="replace"))

    def _read_web(self) -> None:
        if not self.web_process or not self.web_process.stdout:
            return
        for line in iter(self.web_process.stdout.readline, ""):
            self._append_terminal(f"[WEB] {line}")

    def _send_command(self, _event=None) -> None:
        command = self.command_entry.get()
        self.command_entry.delete(0, "end")
        if not command.strip() or not self.cli_process or not self.cli_process.stdin:
            return
        self._append_terminal(command + "\n")
        try:
            self.cli_process.stdin.write((command + "\n").encode("utf-8")); self.cli_process.stdin.flush()
        except (BrokenPipeError, OSError):
            self._append_terminal("\n[console process is not running]\n")

    def _open_web(self) -> None:
        import webbrowser
        webbrowser.open("http://127.0.0.1:8765/")

    def _clear_terminal(self) -> None:
        self.terminal.configure(state="normal"); self.terminal.delete("1.0", "end"); self.terminal.configure(state="disabled")

    def _close(self) -> None:
        for process in (self.cli_process, self.web_process):
            if process and process.poll() is None:
                process.terminate()
        self.destroy()


if __name__ == "__main__":
    SetupApp().mainloop()
