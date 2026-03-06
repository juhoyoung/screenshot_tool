"""
Screenshot Tray Application
- PrintScreen 키로 활성 창 캡처
- 시스템 트레이에서 실행 (pystray는 별도 스레드)
- PNG/JPEG/BMP/WEBP 형식 지원
- 저장 위치 및 형식 설정 가능
- 활성 창 이름으로 폴더 자동 생성

[수정 내역]
- 'main thread is not in main loop' 오류 수정:
    tkinter 메인 루프를 메인 스레드에 두고
    pystray를 daemon 스레드로 분리.
    설정창은 tk.Toplevel로 구현하여 루프 공유.
- UI 레이아웃 수정: 라디오버튼 2열 그리드 배치
- 경로 지정: 📁 폴더 선택 버튼 → filedialog.askdirectory 팝업
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading
import json
import os
import sys
import re
import queue
from datetime import datetime

try:
    import win32gui
    from PIL import ImageGrab, Image, ImageDraw
    import pystray
    from pystray import MenuItem as item
    import keyboard
    HAS_DEPS = True
except ImportError:
    HAS_DEPS = False

# 실행 환경(exe 또는 스크립트)에 따른 경로 설정
if getattr(sys, 'frozen', False):
    application_path = os.path.dirname(sys.executable)
else:
    application_path = os.path.dirname(os.path.abspath(__file__))

CONFIG_FILE = os.path.join(application_path, "config.json")

DEFAULT_CONFIG = {
    "save_path":         os.path.join(os.path.expanduser("~"), "Pictures", "Screenshots"),
    "image_format":      "PNG",
    "quality":           95,
    "show_notification": True,
    "hotkey":            "print_screen",
}


# ────────────────────────────────────────────
# 유틸
# ────────────────────────────────────────────

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            for k, v in DEFAULT_CONFIG.items():
                cfg.setdefault(k, v)
            return cfg
        except Exception:
            pass
    return DEFAULT_CONFIG.copy()


def save_config(cfg):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def sanitize(name: str) -> str:
    name = re.sub(r'[\\/:*?"<>|]', "_", name).strip(". ")
    return (name or "Unknown")[:64]


def make_icon():
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([4, 14, 60, 54], radius=7, fill=(26, 26, 46))
    d.ellipse([17, 19, 47, 49], fill=(0, 212, 255))
    d.ellipse([25, 27, 39, 41], fill=(10, 10, 24))
    d.rectangle([44, 16, 58, 22], fill=(26, 26, 46))
    return img


# ────────────────────────────────────────────
# 메인 앱
# ────────────────────────────────────────────

class ScreenshotApp:

    def __init__(self):
        self.config = load_config()
        self.tray_icon = None
        self.is_running = True
        self.last_path = ""
        self._settings_win = None

        # 메인 스레드에 tkinter 루트 생성 (숨김)
        self.root = tk.Tk()
        self.root.withdraw()

        # 백그라운드 → 메인 스레드 작업 큐
        self._q = queue.Queue()
        self.root.after(80, self._drain)

    # ── 큐 드레인 ───────────────────────────

    def _drain(self):
        try:
            while True:
                self._q.get_nowait()()
        except queue.Empty:
            pass
        if self.is_running:
            self.root.after(80, self._drain)

    def _later(self, fn):
        self._q.put(fn)

    # ── 캡처 ────────────────────────────────

    def take_screenshot(self):
        """keyboard 스레드 콜백 → 메인 스레드로 위임"""
        self._later(self._capture)

    def _capture(self):
        if not HAS_DEPS:
            return
        try:
            hwnd  = win32gui.GetForegroundWindow()
            title = win32gui.GetWindowText(hwnd)

            if "Screenshot Settings" in title:
                return

            rect = win32gui.GetWindowRect(hwnd)
            x1, y1, x2, y2 = rect
            if x2 - x1 <= 0 or y2 - y1 <= 0:
                return

            img = ImageGrab.grab(bbox=(x1, y1, x2, y2))
            folder  = sanitize(title)
            fmt     = self.config["image_format"].upper()
            ext     = "jpg" if fmt == "JPEG" else fmt.lower()
            ts      = datetime.now().strftime("%Y%m%d_%H%M%S")
            fname   = f"{ts}.{ext}"
            savedir = os.path.join(self.config["save_path"], folder)
            os.makedirs(savedir, exist_ok=True)
            fpath   = os.path.join(savedir, fname)

            kw = {}
            if fmt == "JPEG":
                img = img.convert("RGB")
                kw["quality"] = self.config.get("quality", 95)
            elif fmt == "PNG":
                kw["optimize"] = True
            img.save(fpath, format=fmt, **kw)

            self.last_path = fpath
            if self.config.get("show_notification", True):
                self._notify("📸 저장됨", f"{folder}  ›  {fname}")

        except Exception as e:
            self._notify("오류", str(e))

    def _notify(self, title, msg):
        try:
            if self.tray_icon:
                self.tray_icon.notify(msg, title)
        except Exception:
            pass

    # ── 트레이 메뉴 콜백 ────────────────────

    def _t_capture(self, *_): self._later(self._capture)
    def _t_settings(self, *_): self._later(self._open_settings)
    def _t_folder(self, *_):   self._later(self._open_folder)
    def _t_quit(self, *_):     self._later(self._quit)

    # ── 설정창 ──────────────────────────────

    def _open_settings(self):
        if self._settings_win and self._settings_win.winfo_exists():
            self._settings_win.lift()
            self._settings_win.focus_force()
            return
        self._settings_win = SettingsWindow(
            self.root, self.config, self._apply_settings)

    def _apply_settings(self, new_cfg):
        old_hk = self.config.get("hotkey", "print_screen")
        self.config = new_cfg
        save_config(new_cfg)
        if HAS_DEPS:
            try:   keyboard.remove_hotkey(old_hk)
            except Exception: pass
            try:   keyboard.add_hotkey(self.config["hotkey"], self.take_screenshot)
            except Exception: pass

    # ── 폴더 열기 ───────────────────────────

    def _open_folder(self):
        p = self.last_path if self.last_path else self.config["save_path"]
        d = os.path.dirname(p) if os.path.isfile(p) else p
        os.makedirs(d, exist_ok=True)
        os.startfile(d)

    # ── 종료 ────────────────────────────────

    def _quit(self):
        self.is_running = False
        if HAS_DEPS:
            try: keyboard.remove_hotkey(self.config.get("hotkey"))
            except Exception: pass
        if self.tray_icon:
            threading.Thread(target=self.tray_icon.stop, daemon=True).start()
        self.root.after(200, self.root.destroy)

    # ── 실행 ────────────────────────────────

    def run(self):
        if not HAS_DEPS:
            self._no_deps_ui(); return

        keyboard.add_hotkey(self.config["hotkey"], self.take_screenshot)

        menu = pystray.Menu(
            item("📸  지금 캡처",       self._t_capture),
            item("⚙️  설정",            self._t_settings),
            item("📂  저장 폴더 열기",  self._t_folder),
            pystray.Menu.SEPARATOR,
            item("❌  종료",            self._t_quit),
        )
        self.tray_icon = pystray.Icon("ScreenshotTray", make_icon(),
                                      "Screenshot Tray", menu)
        # pystray → 서브 스레드
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

        # tkinter → 메인 스레드
        self.root.mainloop()

    def _no_deps_ui(self):
        self.root.deiconify()
        self.root.title("패키지 설치 필요")
        self.root.geometry("520x260")
        self.root.configure(bg="#1a1a2e")
        tk.Label(self.root, text="필요한 패키지를 설치해주세요",
                 font=("Segoe UI", 13, "bold"),
                 fg="#ff6b6b", bg="#1a1a2e").pack(pady=(28, 8))
        cmd = "pip install pillow pystray pywin32 keyboard"
        frm = tk.Frame(self.root, bg="#0a0a15", padx=12, pady=10)
        frm.pack(padx=24, fill="x")
        tk.Label(frm, text=cmd, font=("Consolas", 10),
                 fg="#00d4ff", bg="#0a0a15").pack()
        tk.Button(self.root, text="클립보드에 복사",
                  command=lambda: [self.root.clipboard_clear(),
                                   self.root.clipboard_append(cmd)],
                  bg="#00d4ff", fg="#0f0f1a",
                  font=("Segoe UI", 10, "bold"),
                  relief="flat", padx=20, pady=8).pack(pady=16)
        self.root.mainloop()


# ────────────────────────────────────────────
# 설정 창 (Toplevel — 메인 루프 공유)
# ────────────────────────────────────────────

class SettingsWindow(tk.Toplevel):
    C = dict(
        BG="#0f0f1a", CARD="#1a1a2e", ACCENT="#00d4ff",
        TEXT="#e8eaf6", SUB="#8892b0", BORDER="#2a2a45",
    )

    def __init__(self, parent, config, on_save):
        super().__init__(parent)
        self.cfg    = config.copy()
        self.on_save = on_save
        self._build()

    def _build(self):
        C = self.C
        BG, CARD, ACCENT, TEXT, SUB, BORDER = (
            C["BG"], C["CARD"], C["ACCENT"],
            C["TEXT"], C["SUB"], C["BORDER"])

        self.title("Screenshot Settings")
        self.geometry("580x650")
        self.resizable(False, False)
        self.configure(bg=BG)
        self.lift(); self.focus_force()

        F_H  = ("Segoe UI", 17, "bold")
        F_L  = ("Segoe UI", 10)
        F_S  = ("Segoe UI", 9)
        F_B  = ("Segoe UI", 10, "bold")
        F_M  = ("Consolas", 9)

        # ── 헤더 ────────────────────────────
        hdr = tk.Frame(self, bg=CARD, padx=22, pady=14)
        hdr.pack(fill="x")
        tk.Label(hdr, text="📸", font=("Segoe UI Emoji", 22),
                 bg=CARD, fg=ACCENT).pack(side="left")
        tf = tk.Frame(hdr, bg=CARD)
        tf.pack(side="left", padx=10)
        tk.Label(tf, text="Screenshot Tray",  font=F_H, bg=CARD, fg=TEXT).pack(anchor="w")
        tk.Label(tf, text="활성 창 자동 캡처 프로그램", font=F_S, bg=CARD, fg=SUB).pack(anchor="w")
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")

        # ── 스크롤 캔버스 ────────────────────
        wrap = tk.Frame(self, bg=BG)
        wrap.pack(fill="both", expand=True)
        cv = tk.Canvas(wrap, bg=BG, highlightthickness=0)
        sb = ttk.Scrollbar(wrap, orient="vertical", command=cv.yview)
        sf = tk.Frame(cv, bg=BG)
        sf.bind("<Configure>",
                lambda e: cv.configure(scrollregion=cv.bbox("all")))
        cv.create_window((0, 0), window=sf, anchor="nw")
        cv.configure(yscrollcommand=sb.set)
        cv.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        cv.bind_all("<MouseWheel>",
                    lambda e: cv.yview_scroll(int(-e.delta / 120), "units"))

        # ── 헬퍼 ────────────────────────────
        def sec(t):
            f = tk.Frame(sf, bg=BG)
            f.pack(fill="x", padx=20, pady=(18, 4))
            tk.Label(f, text=t, font=("Segoe UI", 9, "bold"),
                     fg=ACCENT, bg=BG).pack(side="left")
            tk.Frame(f, bg=BORDER, height=1).pack(
                side="left", fill="x", expand=True, padx=(8, 0), pady=5)

        def card():
            f = tk.Frame(sf, bg=CARD, padx=16, pady=12)
            f.pack(fill="x", padx=20, pady=2)
            return f

        # ══ 저장 위치 ════════════════════════
        sec("  저장 위치")
        row = card()
        tk.Label(row, text="기본 저장 경로", font=F_L,
                 fg=TEXT, bg=CARD, anchor="w").pack(anchor="w")

        pr = tk.Frame(row, bg=CARD)
        pr.pack(fill="x", pady=(6, 0))

        self.path_var = tk.StringVar(value=self.cfg["save_path"])
        tk.Entry(pr, textvariable=self.path_var, font=F_M,
                 bg="#0a0a15", fg=ACCENT, insertbackground=ACCENT,
                 relief="flat", bd=4,
                 highlightthickness=1,
                 highlightbackground=BORDER,
                 highlightcolor=ACCENT
                 ).pack(side="left", fill="x", expand=True, ipady=4)

        tk.Button(pr, text="  📁 폴더 선택  ",
                  font=F_S, bg=ACCENT, fg="#0f0f1a",
                  relief="flat", padx=8, pady=5,
                  cursor="hand2",
                  activebackground="#44eeff",
                  activeforeground="#0f0f1a",
                  command=self._browse
                  ).pack(side="left", padx=(8, 0))

        tk.Label(sf,
                 text="  💡 활성 창 이름으로 하위 폴더가 자동 생성됩니다",
                 font=F_S, fg=SUB, bg=BG
                 ).pack(anchor="w", padx=24, pady=(2, 0))

        # ══ 이미지 형식 ══════════════════════
        sec("  이미지 형식")
        row = card()
        tk.Label(row, text="파일 형식", font=F_L,
                 fg=TEXT, bg=CARD, anchor="w").pack(anchor="w", pady=(0, 8))

        self.fmt_var = tk.StringVar(value=self.cfg["image_format"])
        fmts = [
            ("PNG",  "무손실 압축  (권장)"),
            ("JPEG", "손실 압축  ·  용량 작음"),
            ("BMP",  "비압축  ·  용량 큼"),
            ("WEBP", "최고 압축률"),
        ]
        grid = tk.Frame(row, bg=CARD)
        grid.pack(fill="x")
        for i, (f, desc) in enumerate(fmts):
            col, r = i % 2, i // 2
            cell = tk.Frame(grid, bg=CARD)
            cell.grid(row=r, column=col, sticky="w",
                      padx=(0, 30), pady=3)
            tk.Radiobutton(
                cell, text=f, variable=self.fmt_var, value=f,
                font=("Segoe UI", 10, "bold"), fg=ACCENT,
                bg=CARD, selectcolor=BG,
                activebackground=CARD, activeforeground=ACCENT,
                cursor="hand2", command=self._fmt_changed
            ).pack(side="left")
            tk.Label(cell, text=f"  {desc}", font=F_S,
                     fg=SUB, bg=CARD).pack(side="left")

        # JPEG 품질
        self.q_card = card()
        tk.Label(self.q_card, text="JPEG 품질", font=F_L,
                 fg=TEXT, bg=CARD, anchor="w").pack(anchor="w", pady=(0, 6))
        qr = tk.Frame(self.q_card, bg=CARD)
        qr.pack(fill="x")
        self.q_var   = tk.IntVar(value=self.cfg.get("quality", 95))
        self.q_label = tk.Label(qr, text=f"{self.q_var.get()}%",
                                font=("Consolas", 11, "bold"),
                                fg=ACCENT, bg=CARD, width=5)
        self.q_label.pack(side="right")
        self.q_scale = ttk.Scale(
            qr, from_=10, to=100, variable=self.q_var,
            orient="horizontal",
            command=lambda v: self.q_label.config(text=f"{int(float(v))}%"))
        self.q_scale.pack(side="left", fill="x", expand=True)
        self._fmt_changed()

        # ══ 단축키 ═══════════════════════════
        sec("  단축키")
        row = card()
        tk.Label(row, text="캡처 단축키", font=F_L,
                 fg=TEXT, bg=CARD, anchor="w").pack(anchor="w", pady=(0, 6))

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("D.TCombobox",
                        fieldbackground="#0a0a15", background=CARD,
                        foreground=ACCENT, selectbackground=ACCENT,
                        selectforeground="#0f0f1a", arrowcolor=ACCENT,
                        bordercolor=BORDER)
        style.configure("TScrollbar",
                        background=CARD, troughcolor=BG,
                        arrowcolor=SUB, bordercolor=BG)

        self.hk_var = tk.StringVar(value=self.cfg.get("hotkey", "print_screen"))
        ttk.Combobox(row,
                     textvariable=self.hk_var,
                     values=["print_screen", "ctrl+shift+s", "ctrl+alt+s",
                             "ctrl+shift+p", "f12", "ctrl+f12"],
                     font=("Consolas", 10), width=26,
                     state="readonly", style="D.TCombobox"
                     ).pack(anchor="w")

        # ══ 알림 ═════════════════════════════
        sec("  알림 및 기타")
        row = card()
        self.notify_var = tk.BooleanVar(value=self.cfg.get("show_notification", True))
        tk.Checkbutton(row, text="캡처 후 트레이 알림 표시",
                       variable=self.notify_var, font=F_L,
                       fg=TEXT, bg=CARD, selectcolor=ACCENT,
                       activebackground=CARD, activeforeground=ACCENT,
                       cursor="hand2").pack(anchor="w")

        # ── 하단 버튼 ────────────────────────
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")
        bar = tk.Frame(self, bg=CARD, padx=20, pady=12)
        bar.pack(fill="x")
        tk.Button(bar, text="취소", font=F_B,
                  bg=BORDER, fg=SUB, relief="flat",
                  padx=22, pady=7, cursor="hand2",
                  activebackground="#3a3a55",
                  command=self.destroy
                  ).pack(side="right", padx=(8, 0))
        tk.Button(bar, text="✓  저장", font=F_B,
                  bg=ACCENT, fg="#0f0f1a", relief="flat",
                  padx=22, pady=7, cursor="hand2",
                  activebackground="#44eeff",
                  command=self._save
                  ).pack(side="right")

        self.protocol("WM_DELETE_WINDOW", self.destroy)

    def _fmt_changed(self):
        on = self.fmt_var.get() == "JPEG"
        self.q_scale.configure(state="normal" if on else "disabled")
        self.q_label.configure(fg=self.C["ACCENT"] if on else self.C["SUB"])

    def _browse(self):
        cur = self.path_var.get()
        init = cur if os.path.isdir(cur) else os.path.expanduser("~")
        chosen = filedialog.askdirectory(
            parent=self,
            title="저장 폴더 선택",
            initialdir=init,
        )
        if chosen:
            self.path_var.set(os.path.normpath(chosen))

    def _save(self):
        self.cfg.update({
            "save_path":         self.path_var.get(),
            "image_format":      self.fmt_var.get(),
            "quality":           int(self.q_var.get()),
            "hotkey":            self.hk_var.get(),
            "show_notification": self.notify_var.get(),
        })
        self.on_save(self.cfg)
        messagebox.showinfo("저장 완료", "설정이 저장되었습니다.", parent=self)
        self.destroy()


def main():
    ScreenshotApp().run()


if __name__ == "__main__":
    main()