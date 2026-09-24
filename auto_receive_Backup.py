# -*- coding: utf-8 -*-
"""
โปรแกรม Auto รับสินค้าจากบาร์โค้ดใน PDF (+ ตรวจจับข้อความบนจอด้วย OCR)
=========================================================================

วิธีติดตั้งไลบรารี Python (รันใน Command Prompt / Terminal):

    pip install pdf2image pyzbar pillow pyautogui pygetwindow pyperclip pytesseract

ต้องติดตั้งโปรแกรมภายนอกเพิ่ม 2 ตัว:

1) Poppler (จำเป็นสำหรับอ่าน PDF):
    - โหลดจาก https://github.com/oschwartz10612/poppler-windows/releases
    - แตกไฟล์ zip เก็บไว้ที่ไหนก็ได้ เช่น C:\\poppler\\
    - จดพาธของโฟลเดอร์ย่อยชื่อ "bin" เช่น C:\\poppler\\poppler-24.02.0\\Library\\bin
    - เอาพาธนั้นไปใส่ในช่อง "Poppler bin path" ในโปรแกรม (ไม่ต้องใส่ถ้าเพิ่มลง PATH แล้ว)

2) Tesseract OCR (จำเป็นเฉพาะถ้าจะใช้ฟีเจอร์ "ตรวจจับข้อความบนจอ"):
    - โหลดจาก https://github.com/UB-Mannheim/tesseract/wiki
    - ตอนติดตั้ง ให้ติ๊กเลือกภาษาไทย (Thai) ในหน้า "Additional language data" ด้วย
    - จดพาธไฟล์ tesseract.exe เช่น C:\\Program Files\\Tesseract-OCR\\tesseract.exe
    - เอาพาธนั้นไปใส่ในช่อง "Tesseract.exe path" ในโปรแกรม (ไม่ต้องใส่ถ้าเพิ่มลง PATH แล้ว)

⚠️ ความปลอดภัยสำคัญมาก:
    - โปรแกรมนี้จะควบคุมคีย์บอร์ด/เมาส์จริงบนเครื่องคุณตอนกด "เริ่มทำงานจริง"
    - ให้ทดสอบด้วยโหมด "Dry run (ทดสอบ ไม่พิมพ์จริง)" ก่อนเสมอ
    - ระหว่างรันจริง ถ้าต้องการหยุดฉุกเฉิน ให้เลื่อนเมาส์ไปชนมุมซ้ายบนสุดของจอ (พิกัด 0,0)
      PyAutoGUI จะหยุดโปรแกรมทันที (Fail-Safe)
    - หรือกดปุ่ม "หยุด" ในโปรแกรมก็ได้ (จะหยุดหลังจบสเต็ปปัจจุบัน)
"""

import concurrent.futures
import copy
import ctypes
import glob
import json
import os
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog

try:
    import pyautogui
    import pygetwindow as gw
    import pyperclip
    import pytesseract
    from pdf2image import convert_from_path
    from pyzbar.pyzbar import decode as decode_barcodes
    from pyzbar.pyzbar import ZBarSymbol
except ImportError as e:
    print("ยังติดตั้งไลบรารีไม่ครบ:", e)
    print("รันคำสั่งนี้ก่อน: pip install pdf2image pyzbar pillow pyautogui pygetwindow pyperclip pytesseract")
    raise SystemExit(1)

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    DND_AVAILABLE = True
except ImportError:
    DND_AVAILABLE = False  # ไม่มีก็ไม่เป็นไร ใช้ปุ่มเลือกไฟล์แทนได้ปกติ

pyautogui.FAILSAFE = True   # เลื่อนเมาส์ไปมุมซ้ายบน (0,0) เพื่อหยุดฉุกเฉิน
pyautogui.PAUSE = 0.03

# In a one-file build, bundled resources are extracted temporarily, while
# user settings must remain beside the executable.
BASE_DIR = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, "frozen", False) else __file__))
RESOURCE_DIR = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE = os.path.join(BASE_DIR, "auto_receive_config.json")
OCR_PROFILES_FILE = os.path.join(BASE_DIR, "ocr_profiles.json")
CODES_CACHE_FILE = os.path.join(BASE_DIR, "extracted_codes_cache.json")
SEQUENCE_PROFILES_FILE = os.path.join(BASE_DIR, "sequence_profiles.json")

DEFAULT_CONFIG = {
    "batch_size": 70,
    "reverse_order": False,
    "dpi": 150,
    "pdf_path": "",
    "poppler_path": "",
    "target_window_title": "",
    "default_weight": "0.49",
    "start_delay": 5,
    "dry_run": False,
    "paste_method": True,
    "restore_clipboard": True,
    "force_english_layout": True,
    "only_qrcode": True,
    "ocr_lang": "tha+eng",
    "tesseract_path": "",
    "ocr_region": None,
    "verify_region": None,
    "verify_scroll_amount": 400,
    "verify_invert": False,
    "verify_passes": 3,
    "ocr_rules": [],
    "cancel_keywords": ["Cancel", "ยกเลิก"],
    "duplicate_keywords": ["กรุณาตรวจสอบน้ำหนัก", "ซ้ำ", "Duplicate"],
    "retry_limit": 1,
    "shortcuts": {
        "start": "F6",
        "stop": "F7",
    },
    # ลำดับการทำงานต่อ 1 บาร์โค้ด — แก้ไข/เรียงใหม่ได้จากหน้าโปรแกรม
    "sequence": [
        {"type": "TYPE_BARCODE"},
        {"type": "KEY", "value": "enter"},
        {"type": "WAIT", "value": "0.3"},
        {"type": "TYPE_WEIGHT"},
        {"type": "KEY", "value": "enter"},
        {"type": "KEY", "value": "tab"},
    ],
}

STEP_LABELS = {
    "TYPE_BARCODE": "พิมพ์บาร์โค้ด",
    "TYPE_WEIGHT": "พิมพ์น้ำหนัก",
    "KEY": "กดคีย์",
    "WAIT": "หน่วงเวลา (วินาที)",
    "CLICK": "คลิกตำแหน่ง",
    "WAIT_FOR_TEXT": "รอข้อความ (OCR)",
}


def step_to_display(step):
    t = step["type"]
    if t == "KEY":
        return f"กดคีย์: {step['value']}"
    if t == "WAIT":
        return f"หน่วงเวลา: {step['value']} วิ"
    if t == "CLICK":
        return f"คลิก: ({step['x']}, {step['y']})"
    if t == "WAIT_FOR_TEXT":
        return f"รอข้อความ (OCR) สูงสุด {step.get('timeout', '10')} วิ"
    return STEP_LABELS.get(t, t)


def step_to_columns(step):
    """คืนค่า (การกระทำ, ค่า/รายละเอียด) สำหรับแสดงเป็น 2 คอลัมน์ในตาราง"""
    t = step["type"]
    if t == "TYPE_BARCODE":
        return ("พิมพ์บาร์โค้ด", "")
    if t == "TYPE_WEIGHT":
        return ("พิมพ์น้ำหนัก", "")
    if t == "KEY":
        return ("กดคีย์", step.get("value", ""))
    if t == "WAIT":
        return ("หน่วงเวลา", f"{step.get('value', '')} วิ")
    if t == "CLICK":
        return ("คลิกตำแหน่ง", f"({step.get('x')}, {step.get('y')})")
    if t == "WAIT_FOR_TEXT":
        kws = step.get("keywords") or []
        kw_text = ", ".join(kws) if kws else "ทุกคำในโปรไฟล์"
        return ("รอข้อความ (OCR)", f"สูงสุด {step.get('timeout', '10')} วิ | คำ: {kw_text}")
    return (STEP_LABELS.get(t, t), "")


def rule_to_display(rule):
    kw = rule.get("keyword", "")
    action = rule.get("action")
    if action == "KEY":
        return f"เจอ '{kw}' → กดคีย์: {rule.get('value', 'enter')}"
    if action == "CLICK":
        return f"เจอ '{kw}' → คลิก: ({rule.get('x')}, {rule.get('y')})"
    if action == "PAUSE_WAIT_USER":
        return f"เจอ '{kw}' → หยุดรอให้คนกดเอง"
    if action == "TYPE_WEIGHT":
        return f"เจอ '{kw}' → พิมพ์น้ำหนัก"
    return f"เจอ '{kw}' → {action}"


def extract_barcodes(pdf_path, poppler_path="", only_qrcode=True, dpi=150):
    """อ่าน PDF ทีละหน้า แปลงเป็นรูป แล้วถอดบาร์โค้ดทั้งหมด เรียงบนลงล่างตามหน้า

    only_qrcode=True: เก็บเฉพาะ QR Code (สี่เหลี่ยมจัตุรัส) ตัดบาร์โค้ดเส้นตรง
    แบบ 1D (เช่น CODE128, EAN13) ทิ้งไป เผื่อใน 1 ใบมีบาร์โค้ดหลายแบบปนกัน
    แต่ต้องการใช้แค่ QR Code ตัวเดียว — และยังเร็วขึ้นด้วย เพราะบอก pyzbar
    ให้มองหาแค่ QR Code ตั้งแต่แรก ไม่ต้องเสียเวลาตรวจชนิดอื่น

    dpi: ความละเอียดตอนแปลงหน้า PDF เป็นรูป ยิ่งต่ำยิ่งเร็ว (ค่า default ลดจาก
    200 เหลือ 150 ซึ่งปกติยังคมพอสำหรับอ่าน QR Code) ปรับได้จากหน้าโปรแกรม
    """
    kwargs = {}
    if poppler_path.strip():
        kwargs["poppler_path"] = poppler_path.strip()
    cpu_count = os.cpu_count() or 4
    workers = max(2, min(8, cpu_count))
    # thread_count ให้ Poppler แปลงหลายหน้าพร้อมกัน (เร็วขึ้นมากถ้า PDF มีหลายหน้า)
    pages = convert_from_path(pdf_path, dpi=dpi, thread_count=workers, **kwargs)
    symbols = [ZBarSymbol.QRCODE] if only_qrcode else None

    def decode_one_page(page_img):
        found = decode_barcodes(page_img, symbols=symbols) if symbols else decode_barcodes(page_img)
        found.sort(key=lambda b: (b.rect.top, b.rect.left))
        return [b.data.decode("utf-8", errors="ignore") for b in found]

    # ถอดรหัสบาร์โค้ดหลายหน้าพร้อมกัน (แทนที่จะไล่ทีละหน้า) เร็วขึ้นมากบนเครื่องหลายคอร์
    codes = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        for page_codes in executor.map(decode_one_page, pages):
            codes.extend(page_codes)
    return codes


def ocr_capture_text(region, lang="tha+eng", tesseract_path="", ocr_timeout=8):
    """ถ่ายภาพหน้าจอ (หรือเฉพาะบริเวณที่กำหนด) แล้วอ่านตัวอักษรด้วย Tesseract OCR

    ocr_timeout: จำกัดเวลาที่ Tesseract ใช้อ่านต่อ 1 ครั้ง กันกรณี Tesseract ค้าง
    ไม่ตอบสนอง (raise RuntimeError ถ้าเกินเวลา) จะได้ไม่ทำให้ทั้งโปรแกรมค้างตามไปด้วย
    """
    if tesseract_path.strip():
        pytesseract.pytesseract.tesseract_cmd = tesseract_path.strip()
    if region:
        img = pyautogui.screenshot(
            region=(region["left"], region["top"], region["width"], region["height"])
        )
    else:
        img = pyautogui.screenshot()
    return pytesseract.image_to_string(img, lang=lang, timeout=ocr_timeout)


class CollapsibleFrame(tk.Frame):
    """Frame ที่พับ/ขยายได้พร้อมลูกศร ▼/▶ (หรือ locked=True เพื่อล็อกไม่ให้พับปิดได้ — หัวข้อคงที่ ไม่มีปุ่มพับ)"""

    def __init__(self, parent, title="", tooltip=None, locked=False, **kwargs):
        super().__init__(parent, **kwargs)
        self.is_expanded = True
        self.inner_frame = None
        self.locked = locked

        # หัวข้อ
        header = tk.Frame(self, bg="#e8e8e8", relief="solid", borderwidth=1)
        header.pack(fill="x")

        if locked:
            # ล็อกไว้ ไม่มีปุ่มพับ/กาง หัวข้อกดไม่ได้
            title_label = tk.Label(header, text=title, bg="#e8e8e8", fg="#333", font=("", 9, "bold"))
            title_label.pack(side="left", fill="x", expand=True, padx=8, pady=4)
        else:
            self.toggle_btn = tk.Label(header, text="▼", width=3, bg="#e8e8e8", fg="#333", cursor="hand2", font=("", 10, "bold"))
            self.toggle_btn.pack(side="left", padx=4, pady=4)

            title_label = tk.Label(header, text=title, bg="#e8e8e8", fg="#333", font=("", 9, "bold"))
            title_label.pack(side="left", fill="x", expand=True, padx=(0, 4), pady=4)

            self.toggle_btn.bind("<Button-1>", lambda e: self.toggle())
            title_label.bind("<Button-1>", lambda e: self.toggle())
        if tooltip:
            ToolTip(title_label, tooltip)
        
        # ตัวเนื้อหา
        self.inner_frame = tk.Frame(self)
        self.inner_frame.pack(fill="both", expand=True)
    
    def toggle(self):
        if self.locked:
            return
        if self.is_expanded:
            self.inner_frame.pack_forget()
            self.toggle_btn.config(text="▶")
            self.is_expanded = False
        else:
            self.inner_frame.pack(fill="both", expand=True)
            self.toggle_btn.config(text="▼")
            self.is_expanded = True


class ToolTip:
    """แสดงกล่องคำอธิบายเล็กๆ เมื่อเอาเมาส์ชี้ค้างไว้บน widget ประมาณ 2 วินาที"""

    def __init__(self, widget, text, delay=2000):
        self.widget = widget
        self.text = text
        self.delay = delay
        self.tip_window = None
        self.after_id = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _event=None):
        self._cancel_schedule()
        self.after_id = self.widget.after(self.delay, self._show)

    def _cancel_schedule(self):
        if self.after_id:
            try:
                self.widget.after_cancel(self.after_id)
            except Exception:
                pass
            self.after_id = None

    def _show(self):
        if self.tip_window or not self.text:
            return
        x = self.widget.winfo_rootx() + 10
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        self.tip_window = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        tw.attributes("-topmost", True)
        label = tk.Label(
            tw, text=self.text, justify="left", background="#ffffe0",
            relief="solid", borderwidth=1, font=("", 9), wraplength=320, padx=6, pady=3,
        )
        label.pack()

    def _hide(self, _event=None):
        self._cancel_schedule()
        if self.tip_window:
            self.tip_window.destroy()
            self.tip_window = None


class SectionDialog:
    """หน้าต่างตั้งค่าแยกต่างหาก เปิด/ปิดผ่านปุ่มเมนูซ้ายสุด
    มี .inner_frame ให้ใส่เนื้อหาแบบเดียวกับ CollapsibleFrame (โค้ดเดิมใช้ต่อได้โดยไม่ต้องแก้)
    สร้างครั้งเดียวตอนเปิดโปรแกรม แล้วซ่อน/โชว์ด้วย withdraw()/deiconify() แทนการสร้างใหม่ทุกครั้ง
    เพื่อให้ widget ภายในไม่หายไประหว่างที่หน้าต่างถูกซ่อนอยู่"""

    def __init__(self, parent, title):
        self.window = tk.Toplevel(parent)
        self.window.title(title)
        self.window.geometry("640x420")
        self.window.protocol("WM_DELETE_WINDOW", self.hide)
        self.window.withdraw()
        self.inner_frame = ttk.Frame(self.window, padding=10)
        self.inner_frame.pack(fill="both", expand=True)

    def show(self):
        self.window.deiconify()
        self.window.lift()
        self.window.focus_set()

    def hide(self):
        self.window.withdraw()


class AutoReceiveApp:
    def __init__(self, root):
        self.root = root
        root.title("KexAuto - รับสินค้าจากบาร์โค้ด PDF")
        icon_path = os.path.join(RESOURCE_DIR, "kexauto.ico")
        if os.path.exists(icon_path):
            root.iconbitmap(icon_path)
        root.geometry("1200x800")
        root.minsize(1200, 800)

        self.config_data = self.load_config_file()
        self.sequence_profiles = self.load_sequence_profiles_file()
        self.ocr_profiles = self.load_ocr_profiles_file()
        self.log_queue = queue.Queue()
        self.fail_log_queue = queue.Queue()
        self.stop_event = threading.Event()
        self.resume_event = threading.Event()
        self.worker_thread = None
        self.ocr_region = self.config_data.get("ocr_region")
        self.verify_region = self.config_data.get("verify_region")
        self.ocr_rules = list(self.config_data.get("ocr_rules", []))
        self.shortcuts = dict(DEFAULT_CONFIG["shortcuts"])
        self.shortcuts.update(self.config_data.get("shortcuts", {}))
        self._shortcut_bindings = []
        self.stats = {"completed": 0, "cancel": 0, "duplicate": 0}
        self.extracted_codes = self.load_codes_cache()

        self.build_ui()
        self.setup_shortcuts()
        self.root.after(150, self.poll_log_queue)
        
        # Auto-detect Poppler และ Tesseract ตอนเปิดโปรแกรม
        self.root.after(500, self._auto_detect_on_startup)

    # ---------- config persistence ----------
    def load_config_file(self):
        config_path = CONFIG_FILE
        if not os.path.exists(config_path):
            config_path = os.path.join(RESOURCE_DIR, "auto_receive_config.json")
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                merged = DEFAULT_CONFIG.copy()
                merged.update(data)
                if merged.get("poppler_path") and not os.path.isdir(merged["poppler_path"]):
                    merged["poppler_path"] = ""
                if merged.get("tesseract_path") and not os.path.isfile(merged["tesseract_path"]):
                    merged["tesseract_path"] = ""
                return merged
            except Exception:
                pass
        return json.loads(json.dumps(DEFAULT_CONFIG))  # deep copy

    def save_config_to_disk(self, path=None):
        path = path or CONFIG_FILE
        data = self.gather_config_from_ui()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        self.log(f"บันทึกการตั้งค่าไว้ที่: {path}")

    def load_sequence_profiles_file(self):
        if not os.path.exists(SEQUENCE_PROFILES_FILE):
            return {}
        try:
            with open(SEQUENCE_PROFILES_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return {}
            return {
                str(name): steps
                for name, steps in data.items()
                if str(name).strip() and isinstance(steps, list)
            }
        except (OSError, json.JSONDecodeError):
            return {}

    def save_sequence_profiles_file(self):
        with open(SEQUENCE_PROFILES_FILE, "w", encoding="utf-8") as f:
            json.dump(self.sequence_profiles, f, ensure_ascii=False, indent=2)

    def load_codes_cache(self):
        if os.path.exists(CODES_CACHE_FILE):
            try:
                with open(CODES_CACHE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return data.get("codes", [])
            except Exception:
                return []
        return []

    def save_codes_cache(self):
        with open(CODES_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "codes": self.extracted_codes,
                    "pdf_path": self.pdf_path_var.get(),
                    "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                },
                f,
                ensure_ascii=False,
                indent=2,
            )

    def load_ocr_profiles_file(self):
        if os.path.exists(OCR_PROFILES_FILE):
            try:
                with open(OCR_PROFILES_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def save_ocr_profiles_file(self):
        with open(OCR_PROFILES_FILE, "w", encoding="utf-8") as f:
            json.dump(self.ocr_profiles, f, ensure_ascii=False, indent=2)

    def gather_config_from_ui(self):
        return {
            "pdf_path": self.pdf_path_var.get(),
            "poppler_path": self.poppler_path_var.get(),
            "target_window_title": self.window_title_var.get(),
            "default_weight": self.weight_var.get(),
            "start_delay": int(self.delay_var.get() or 5),
            "dry_run": self.dry_run_var.get(),
            "batch_size": int(self.batch_size_var.get() or 0),
            "reverse_order": self.reverse_order_var.get(),
            "sequence": self.sequence,
            "sequence_profile": self.sequence_profile_var.get() if hasattr(self, "sequence_profile_var") else "",
            "paste_method": self.paste_method_var.get(),
            "restore_clipboard": self.restore_clipboard_var.get(),
            "force_english_layout": self.force_english_layout_var.get(),
            "only_qrcode": self.only_qrcode_var.get(),
            "dpi": int(self.dpi_var.get() or 150),
            "ocr_lang": self.ocr_lang_var.get(),
            "tesseract_path": self.tesseract_path_var.get(),
            "ocr_region": self.ocr_region,
            "verify_region": self.verify_region,
            "verify_scroll_amount": int(self.verify_scroll_amount_var.get() or 400),
            "verify_invert": self.verify_invert_var.get(),
            "verify_passes": int(self.verify_passes_var.get() or 3),
            "ocr_rules": self.ocr_rules,
            "cancel_keywords": self._keywords_from_text(self.cancel_keywords_var.get()),
            "duplicate_keywords": self._keywords_from_text(self.duplicate_keywords_var.get()),
            "retry_limit": int(self.retry_limit_var.get() or 1),
            "shortcuts": self.shortcuts,
        }

    # ---------- UI ----------
    def build_ui(self):
        pad = {"padx": 8, "pady": 4}

        # ---------- แถบเครื่องมือด้านบน (คงที่ ไม่เลื่อนตามเนื้อหา) ----------
        toolbar = ttk.Frame(self.root)
        toolbar.pack(side="top", fill="x")
        ttk.Button(toolbar, text="📂 ดึงบาร์โค้ด", command=self.preview_barcodes).pack(
            side="left", padx=(6, 2), pady=4
        )
        ttk.Button(toolbar, text="💾 บันทึก", command=lambda: self.save_config_to_disk()).pack(
            side="left", padx=2, pady=4
        )
        ttk.Separator(toolbar, orient="vertical").pack(side="left", fill="y", padx=6, pady=4)
        ttk.Button(toolbar, text="▶ เริ่มทำงาน", command=self.start_automation).pack(
            side="left", padx=2, pady=4
        )
        ttk.Button(toolbar, text="■ หยุด", command=self.stop_automation).pack(side="left", padx=2, pady=4)
        self.resume_btn = ttk.Button(
            toolbar, text="▶ ดำเนินการต่อ", command=self.resume_automation, state="disabled"
        )
        self.resume_btn.pack(side="left", padx=2, pady=4)
        ttk.Separator(toolbar, orient="vertical").pack(side="left", fill="y", padx=6, pady=4)
        self.stats_var = tk.StringVar()
        self._update_stats_label()
        ttk.Label(toolbar, textvariable=self.stats_var, foreground="#164e63").pack(
            side="right", padx=8, pady=4
        )
        ttk.Separator(toolbar, orient="horizontal").pack(side="top", fill="x")

        # ---------- ห่อทั้งหน้าด้วย canvas+scrollbar ให้เลื่อนดูได้ ----------
        outer = ttk.Frame(self.root)
        outer.pack(fill="both", expand=True)
        canvas = tk.Canvas(outer, highlightthickness=0)
        vscroll = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vscroll.set)
        canvas.pack(side="left", fill="both", expand=True)
        vscroll.pack(side="right", fill="y")

        scroll_frame = ttk.Frame(canvas)
        scroll_window = canvas.create_window((0, 0), window=scroll_frame, anchor="nw")

        def on_frame_configure(_e):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def on_canvas_configure(e):
            canvas.itemconfig(scroll_window, width=e.width)

        scroll_frame.bind("<Configure>", on_frame_configure)
        canvas.bind("<Configure>", on_canvas_configure)

        def on_mousewheel(e):
            canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")

        canvas.bind_all("<MouseWheel>", on_mousewheel)
        self.root = scroll_frame  # เนื้อหาด้านล่างทั้งหมดแนบกับ scroll_frame แทน root โดยตรง
        self._real_root = outer.winfo_toplevel()  # เก็บ toplevel จริงไว้ใช้ตอน withdraw/deiconify

        # ---------- ปุ่มเมนูซ้ายสุด: เปิดหน้าต่างตั้งค่าแยกแต่ละหัวข้อ ----------
        nav_frame = ttk.Frame(self.root)
        nav_frame.pack(side="left", fill="y", padx=(4, 0), pady=4)
        ttk.Label(nav_frame, text="เมนู", font=("", 9, "bold")).pack(pady=(2, 6))
        self.nav_buttons = {}  # เก็บไว้เผื่อใช้อ้างอิงทีหลัง

        def create_nav_button(text, command):
            return tk.Button(
                nav_frame,
                text=text,
                width=10,
                height=2,
                anchor="center",
                justify="center",
                command=command,
            )

        main_area = ttk.Frame(self.root)
        main_area.pack(side="left", fill="both", expand=True, padx=4, pady=4)

        target_bar = ttk.Frame(main_area)
        target_bar.pack(fill="x", pady=(0, 4))
        ttk.Label(target_bar, text="ชื่อหน้าต่างโปรแกรมเป้าหมาย:").pack(side="left")
        self.window_title_var = tk.StringVar(value=self.config_data.get("target_window_title", ""))
        self.window_combo = ttk.Combobox(target_bar, textvariable=self.window_title_var)
        self.window_combo.pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(target_bar, text="รีเฟรชรายชื่อหน้าต่าง", command=self.refresh_windows).pack(side="left")

        frm_file = SectionDialog(self._real_root, "ไฟล์และโปรแกรมเป้าหมาย")
        nav_btn1 = create_nav_button("📁\nไฟล์", frm_file.show)
        nav_btn1.pack(pady=3, fill="x")
        self.nav_buttons["file"] = nav_btn1

        self.pdf_path_var = tk.StringVar(value=self.config_data.get("pdf_path", ""))

        drop_frame = tk.Frame(frm_file.inner_frame, relief="ridge", borderwidth=2, bg="#f5f5f5")
        drop_frame.grid(row=0, column=0, columnspan=4, sticky="we", pady=(4, 8))

        existing_name = os.path.basename(self.pdf_path_var.get()) if self.pdf_path_var.get() else ""
        self.drop_label_var = tk.StringVar(
            value=f"✅ {existing_name}" if existing_name else "📄 ลากไฟล์ PDF มาวางตรงนี้"
        )
        drop_label = tk.Label(
            drop_frame, textvariable=self.drop_label_var, bg="#f5f5f5", fg="#555", font=("", 10), pady=10
        )
        drop_label.pack(fill="x")

        browse_btn_frame = tk.Frame(drop_frame, bg="#f5f5f5")
        browse_btn_frame.pack(pady=(0, 12))
        ttk.Button(browse_btn_frame, text="📂 เลือกไฟล์ PDF", command=self.browse_pdf).pack()

        if DND_AVAILABLE:
            for widget in (drop_frame, drop_label, browse_btn_frame):
                widget.drop_target_register(DND_FILES)
                widget.dnd_bind("<<Drop>>", self.on_pdf_drop)
        else:
            hint = "ลากไฟล์วางยังไม่พร้อมใช้งาน (ต้องติดตั้งเพิ่ม: pip install tkinterdnd2) — ตอนนี้ใช้ปุ่มเลือกไฟล์แทนได้ปกติ"
            ToolTip(drop_frame, hint)
            ToolTip(drop_label, hint)

        ttk.Label(frm_file.inner_frame, text="พาธไฟล์ที่เลือก:").grid(row=1, column=0, sticky="w")
        ttk.Entry(frm_file.inner_frame, textvariable=self.pdf_path_var, width=55, state="readonly").grid(
            row=1, column=1, columnspan=3, sticky="we"
        )

        self.poppler_path_var = tk.StringVar(value=self.config_data.get("poppler_path", ""))
        poppler_label = ttk.Label(frm_file.inner_frame, text="Poppler bin path:")
        poppler_label.grid(row=2, column=0, sticky="w")
        ToolTip(poppler_label, "ใส่เฉพาะถ้ายังไม่ได้เพิ่ม Poppler ลง PATH ของ Windows")
        ttk.Entry(frm_file.inner_frame, textvariable=self.poppler_path_var, width=45).grid(row=2, column=1, sticky="we")
        ttk.Button(frm_file.inner_frame, text="เลือกโฟลเดอร์...", command=self.browse_poppler).grid(row=2, column=2, padx=2)
        ttk.Button(frm_file.inner_frame, text="🔍 ค้นหาอัตโนมัติ", command=self.find_poppler_auto).grid(row=2, column=3)

        frm_file.inner_frame.columnconfigure(1, weight=1)

        frm_val = SectionDialog(self._real_root, "ค่าเริ่มต้นและจังหวะเวลา")
        nav_btn2 = create_nav_button("⚙️\nค่าเริ่มต้น", frm_val.show)
        nav_btn2.pack(pady=3, fill="x")
        self.nav_buttons["defaults"] = nav_btn2

        self.weight_var = tk.StringVar(value=self.config_data.get("default_weight", "0.49"))
        ttk.Label(frm_val.inner_frame, text="น้ำหนัก default:").grid(row=0, column=0, sticky="w")
        ttk.Entry(frm_val.inner_frame, textvariable=self.weight_var, width=10).grid(row=0, column=1, sticky="w")

        self.delay_var = tk.StringVar(value=str(self.config_data.get("start_delay", 5)))
        delay_label = ttk.Label(frm_val.inner_frame, text="นับถอยหลัง:")
        delay_label.grid(row=0, column=2, sticky="w")
        ToolTip(delay_label, "วินาทีที่รอก่อนเริ่ม ให้เวลาสลับไปโฟกัสโปรแกรมเป้าหมาย")
        ttk.Entry(frm_val.inner_frame, textvariable=self.delay_var, width=6).grid(row=0, column=3, sticky="w")

        self.batch_size_var = tk.StringVar(value=str(self.config_data.get("batch_size", 70)))
        batch_label = ttk.Label(frm_val.inner_frame, text="หยุดพักทุกๆ (รอบ):")
        batch_label.grid(row=1, column=0, sticky="w", pady=(4, 0))
        batch_entry = ttk.Entry(frm_val.inner_frame, textvariable=self.batch_size_var, width=6)
        batch_entry.grid(row=1, column=1, sticky="w", pady=(4, 0))
        tip_text = "กันระบบเป้าหมายขัดข้องเมื่อคีย์ติดต่อกันนานเกินไป — ใส่ 0 ถ้าไม่ต้องการหยุดพัก"
        ToolTip(batch_label, tip_text)
        ToolTip(batch_entry, tip_text)

        self.reverse_order_var = tk.BooleanVar(value=self.config_data.get("reverse_order", False))
        cb_reverse = ttk.Checkbutton(
            frm_val.inner_frame, text="เรียงจากรายการสุดท้ายมาแรกสุด", variable=self.reverse_order_var
        )
        cb_reverse.grid(row=2, column=0, columnspan=3, sticky="w", pady=(4, 0))
        ToolTip(
            cb_reverse,
            "กลับลำดับการประมวลผลทั้งหมด: เริ่มจากรายการสุดท้ายในไฟล์ PDF ไล่ย้อนมาจนถึงรายการแรก "
            "แทนที่จะเริ่มจากรายการแรกตามปกติ",
        )

        frm_seq = CollapsibleFrame(
            main_area,
            title="ลำดับการทำงาน",
            tooltip="ลำดับการทำงานต่อ 1 บาร์โค้ด — แก้ให้ตรงกับโปรแกรมจริงของคุณ",
            locked=True,
        )
        frm_seq.pack(fill="both", expand=True, **pad)

        self.sequence = copy.deepcopy(self.config_data.get("sequence", DEFAULT_CONFIG["sequence"]))
        self.sequence_profile_var = tk.StringVar(
            value=self.config_data.get("sequence_profile", "")
        )
        active_profile = self.sequence_profile_var.get()
        if active_profile and active_profile in self.sequence_profiles:
            self.sequence = copy.deepcopy(self.sequence_profiles[active_profile])
        elif active_profile:
            self.sequence_profile_var.set("")

        ttk.Label(frm_seq.inner_frame, text="โปรไฟล์ลำดับ:").grid(
            row=0, column=0, sticky="w", padx=4, pady=(4, 0)
        )
        self.sequence_profile_combo = ttk.Combobox(
            frm_seq.inner_frame,
            textvariable=self.sequence_profile_var,
            values=sorted(self.sequence_profiles),
            state="readonly",
            width=28,
        )
        self.sequence_profile_combo.grid(row=0, column=1, sticky="w", padx=2, pady=(4, 0))
        self.sequence_profile_combo.bind("<<ComboboxSelected>>", self.apply_sequence_profile)
        ttk.Button(
            frm_seq.inner_frame, text="บันทึกเป็นโปรไฟล์...", command=self.save_sequence_profile
        ).grid(row=0, column=2, padx=2, pady=(4, 0))
        ttk.Button(
            frm_seq.inner_frame, text="ลบโปรไฟล์", command=self.delete_sequence_profile
        ).grid(row=0, column=3, padx=2, pady=(4, 0))

        seq_tree_frame = ttk.Frame(frm_seq.inner_frame)
        seq_tree_frame.grid(row=1, column=0, columnspan=5, sticky="nswe", padx=4, pady=4)
        frm_seq.inner_frame.rowconfigure(1, weight=1)
        for _col in range(5):
            frm_seq.inner_frame.columnconfigure(_col, weight=1)
        self.seq_tree = ttk.Treeview(
            seq_tree_frame, columns=("action", "detail"), show="tree headings", height=20, selectmode="browse"
        )
        self.seq_tree.heading("#0", text="ลำดับ")
        self.seq_tree.column("#0", width=55, anchor="center", stretch=False)
        self.seq_tree.heading("action", text="การกระทำ")
        self.seq_tree.column("action", width=200)
        self.seq_tree.heading("detail", text="ค่า / รายละเอียด")
        self.seq_tree.column("detail", width=220)
        seq_scroll = ttk.Scrollbar(seq_tree_frame, orient="vertical", command=self.seq_tree.yview)
        self.seq_tree.configure(yscrollcommand=seq_scroll.set)
        self.seq_tree.pack(side="left", fill="both", expand=True)
        seq_scroll.pack(side="right", fill="y")
        self.seq_tree.bind("<Double-Button-1>", self.edit_step)
        self.refresh_seq_listbox()
        ToolTip(self.seq_tree, "ดับเบิลคลิกที่สเต็ปเพื่อแก้ไขค่า เช่น เวลาหน่วง โดยไม่ต้องลบแล้วเพิ่มใหม่")

        ttk.Button(frm_seq.inner_frame, text="▲ ขึ้น", command=self.move_step_up).grid(row=2, column=0)
        ttk.Button(frm_seq.inner_frame, text="▼ ลง", command=self.move_step_down).grid(row=2, column=1)
        ttk.Button(frm_seq.inner_frame, text="ลบสเต็ปนี้", command=self.delete_step).grid(row=2, column=2)

        self.new_step_type = tk.StringVar(value="KEY")
        ttk.OptionMenu(
            frm_seq.inner_frame, self.new_step_type, "KEY",
            "TYPE_BARCODE", "TYPE_WEIGHT", "KEY", "WAIT", "CLICK", "WAIT_FOR_TEXT",
            command=self.on_step_type_change,
        ).grid(row=3, column=0, sticky="w", pady=(8, 0))

        self.new_step_value = tk.StringVar(value="enter")
        step_value_entry = ttk.Entry(frm_seq.inner_frame, textvariable=self.new_step_value, width=12)
        step_value_entry.grid(row=3, column=1, pady=(8, 0))
        ToolTip(step_value_entry, "คีย์: ชื่อปุ่ม เช่น enter/tab | Wait: วินาที | รอข้อความ: timeout วินาที")

        ttk.Button(frm_seq.inner_frame, text="+ เพิ่มสเต็ป", command=self.add_step).grid(row=2, column=3)
        ttk.Button(
            frm_seq.inner_frame, text="📍 จับตำแหน่งเมาส์ (นับ 3 วิ) → เพิ่มเป็นสเต็ปคลิก",
            command=self.capture_click_position,
        ).grid(row=4, column=0, columnspan=4, sticky="we", pady=(6, 4))

        frm_run = SectionDialog(self._real_root, "ตัวเลือกก่อนเริ่มทำงาน")
        nav_btn4 = create_nav_button("🔧\nตัวเลือก", frm_run.show)
        nav_btn4.pack(pady=3, fill="x")
        self.nav_buttons["options"] = nav_btn4

        self.dry_run_var = tk.BooleanVar(value=self.config_data.get("dry_run", False))
        cb_dry = ttk.Checkbutton(frm_run.inner_frame, text="Dry run", variable=self.dry_run_var)
        cb_dry.grid(row=0, column=0, sticky="w")
        ToolTip(cb_dry, "ทดสอบ แสดง log เฉยๆ ไม่พิมพ์/คลิกจริง")

        self.only_qrcode_var = tk.BooleanVar(value=self.config_data.get("only_qrcode", True))
        cb_qr = ttk.Checkbutton(frm_run.inner_frame, text="เฉพาะ QR Code", variable=self.only_qrcode_var)
        cb_qr.grid(row=0, column=1, sticky="w")
        ToolTip(cb_qr, "เก็บเฉพาะ QR Code เท่านั้น ตัดบาร์โค้ดเส้นตรงแบบ 1D ทิ้ง")

        self.dpi_var = tk.StringVar(value=str(self.config_data.get("dpi", 150)))
        dpi_label = ttk.Label(frm_run.inner_frame, text="DPI สแกน:")
        dpi_label.grid(row=0, column=2, sticky="w")
        dpi_entry = ttk.Entry(frm_run.inner_frame, textvariable=self.dpi_var, width=5)
        dpi_entry.grid(row=0, column=3, sticky="w")
        dpi_tip = "ความละเอียดตอนแปลงหน้า PDF เป็นรูป ยิ่งต่ำยิ่งเร็ว (แนะนำ 100-150) แต่ถ้า QR เล็กมากอาจต้องเพิ่มเป็น 200"
        ToolTip(dpi_label, dpi_tip)
        ToolTip(dpi_entry, dpi_tip)

        self.paste_method_var = tk.BooleanVar(value=self.config_data.get("paste_method", True))
        cb_paste = ttk.Checkbutton(frm_run.inner_frame, text="วางจากคลิปบอร์ด", variable=self.paste_method_var)
        cb_paste.grid(row=0, column=2, sticky="w")
        ToolTip(cb_paste, "วางข้อความจากคลิปบอร์ดแทนพิมพ์ทีละตัว (แนะนำ กันตัวอักษรตกหล่น)")

        self.restore_clipboard_var = tk.BooleanVar(value=self.config_data.get("restore_clipboard", True))
        cb_restore = ttk.Checkbutton(
            frm_run.inner_frame, text="คืนค่าคลิปบอร์ดเดิม", variable=self.restore_clipboard_var
        )
        cb_restore.grid(row=0, column=3, sticky="w")
        ToolTip(
            cb_restore,
            "คืนค่าคลิปบอร์ดของคุณกลับหลังวางแต่ละครั้ง ถ้าโปรแกรมเป้าหมายบางทีวางไม่เข้า "
            "(อาการเป็นๆ หายๆ) ลองปิดตัวนี้ดู จะช่วยลดโอกาสวางไม่ทันได้ แลกกับคลิปบอร์ดเดิมของคุณจะหายไป",
        )

        self.force_english_layout_var = tk.BooleanVar(value=self.config_data.get("force_english_layout", True))
        cb_english = ttk.Checkbutton(
            frm_run.inner_frame, text="บังคับภาษาอังกฤษก่อนพิมพ์", variable=self.force_english_layout_var
        )
        cb_english.grid(row=1, column=2, columnspan=2, sticky="w")
        ToolTip(
            cb_english,
            "สลับคีย์บอร์ดเป็นภาษาอังกฤษ (US) อัตโนมัติก่อนพิมพ์/วางทุกครั้ง แก้ปัญหาคีย์บอร์ดไทย "
            "ทำให้ Ctrl+V หรือการพิมพ์ทำงานไม่เสถียรกับบางโปรแกรม (ใช้ได้บน Windows เท่านั้น)",
        )

        self.force_refresh_var = tk.BooleanVar(value=False)
        cb_force = ttk.Checkbutton(frm_run.inner_frame, text="บังคับดึงใหม่ก่อนเริ่ม", variable=self.force_refresh_var)
        cb_force.grid(row=1, column=0, columnspan=2, sticky="w")
        ToolTip(cb_force, "ไม่ใช้ข้อมูลบาร์โค้ดที่เคยดึงไว้ ให้อ่าน PDF ใหม่ทุกครั้งก่อนเริ่ม")

        self.codes_count_var = tk.StringVar(value=self._codes_count_text())
        ttk.Label(frm_run.inner_frame, textvariable=self.codes_count_var, foreground="grey").grid(
            row=2, column=0, columnspan=3, sticky="w"
        )

        self.start_index_var = tk.StringVar(value="1")
        start_idx_label = ttk.Label(frm_run.inner_frame, text="เริ่มจากรายการที่:")
        start_idx_label.grid(row=3, column=0, sticky="w", pady=(4, 0))
        start_idx_entry = ttk.Entry(frm_run.inner_frame, textvariable=self.start_index_var, width=6)
        start_idx_entry.grid(row=3, column=1, sticky="w", pady=(4, 0))
        tip = "ใส่เลขลำดับที่ต้องการเริ่ม เช่น เคยทำถึงรายการ 10 แล้ว อยากย้อนกลับไปทำใหม่จากรายการ 5 ก็ใส่ 5 (ค่าเริ่มต้น 1 = เริ่มจากรายการแรก)"
        ToolTip(start_idx_label, tip)
        ToolTip(start_idx_entry, tip)

        retry_label = ttk.Label(frm_run.inner_frame, text="กรอกซ้ำสูงสุด:")
        retry_label.grid(row=4, column=0, sticky="w", pady=(4, 0))
        self.retry_limit_var = tk.StringVar(value=str(self.config_data.get("retry_limit", 1)))
        retry_entry = ttk.Entry(frm_run.inner_frame, textvariable=self.retry_limit_var, width=6)
        retry_entry.grid(row=4, column=1, sticky="w", pady=(4, 0))
        retry_tip = "เมื่อพบคำแจ้งเตือน (ยกเลิก/ซ้ำ) ระบบจะหยุดรอให้กด 'ดำเนินการต่อ' แล้วกรอกบาร์โค้ดเดิมซ้ำตามจำนวนนี้"
        ToolTip(retry_label, retry_tip)
        ToolTip(retry_entry, retry_tip)

        frm_run.inner_frame.columnconfigure(0, weight=1)
        frm_run.inner_frame.columnconfigure(1, weight=1)

        # ---------- 5) OCR: ตรวจจับข้อความบนจอ ----------
        frm_ocr = SectionDialog(self._real_root, "ตรวจจับข้อความบนจอ (OCR)")
        nav_btn5 = create_nav_button("🔍\nOCR", frm_ocr.show)
        nav_btn5.pack(pady=3, fill="x")
        self.nav_buttons["ocr"] = nav_btn5

        self.tesseract_path_var = tk.StringVar(value=self.config_data.get("tesseract_path", ""))
        tess_label = ttk.Label(frm_ocr.inner_frame, text="Tesseract.exe path:")
        tess_label.grid(row=0, column=0, sticky="w")
        ToolTip(tess_label, "ใส่เฉพาะถ้ายังไม่ได้เพิ่ม Tesseract ลง PATH ของ Windows")
        ttk.Entry(frm_ocr.inner_frame, textvariable=self.tesseract_path_var, width=35).grid(row=0, column=1, sticky="we")
        ttk.Button(frm_ocr.inner_frame, text="เลือกไฟล์...", command=self.browse_tesseract).grid(row=0, column=2, padx=2)
        ttk.Button(frm_ocr.inner_frame, text="🔍 ค้นหาอัตโนมัติ", command=self.find_tesseract_auto).grid(row=0, column=3)

        self.ocr_lang_var = tk.StringVar(value=self.config_data.get("ocr_lang", "tha+eng"))
        ttk.Label(frm_ocr.inner_frame, text="ภาษาที่อ่าน (lang):").grid(row=1, column=0, sticky="w")
        ttk.Entry(frm_ocr.inner_frame, textvariable=self.ocr_lang_var, width=15).grid(row=1, column=1, sticky="w")

        cancel_label = ttk.Label(frm_ocr.inner_frame, text="คำแจ้งเตือนยกเลิก:")
        cancel_label.grid(row=2, column=0, sticky="w")
        ToolTip(cancel_label, "คั่นหลายคำด้วยเครื่องหมายจุลภาค (,)")
        self.cancel_keywords_var = tk.StringVar(
            value=", ".join(self.config_data.get("cancel_keywords", DEFAULT_CONFIG["cancel_keywords"]))
        )
        ttk.Entry(frm_ocr.inner_frame, textvariable=self.cancel_keywords_var, width=30).grid(
            row=2, column=1, columnspan=3, sticky="we"
        )

        dup_label = ttk.Label(frm_ocr.inner_frame, text="คำแจ้งเตือนซ้ำ:")
        dup_label.grid(row=3, column=0, sticky="w")
        ToolTip(dup_label, "คั่นหลายคำด้วยเครื่องหมายจุลภาค (,)")
        self.duplicate_keywords_var = tk.StringVar(
            value=", ".join(self.config_data.get("duplicate_keywords", DEFAULT_CONFIG["duplicate_keywords"]))
        )
        ttk.Entry(frm_ocr.inner_frame, textvariable=self.duplicate_keywords_var, width=30).grid(
            row=3, column=1, columnspan=3, sticky="we"
        )

        self.ocr_region_var = tk.StringVar(value=self._region_to_str(self.ocr_region))
        ttk.Button(frm_ocr.inner_frame, text="🖱️ เลือกพื้นที่ตรวจจับบนจอ", command=self.select_ocr_region).grid(
            row=4, column=0, sticky="w", pady=(4, 4)
        )
        ttk.Label(frm_ocr.inner_frame, textvariable=self.ocr_region_var).grid(row=4, column=1, columnspan=2, sticky="w")

        test_ocr_btn = ttk.Button(frm_ocr.inner_frame, text="🔍 ทดสอบอ่าน OCR ตอนนี้เลย", command=self.test_ocr_now)
        test_ocr_btn.grid(row=4, column=3, sticky="w", padx=(10, 0))
        ToolTip(
            test_ocr_btn,
            "ใช้ตอนเจอปัญหา 'ไม่พบข้อความ' — กดปุ่มนี้เพื่อดูว่า OCR อ่านอะไรได้บ้างจากพื้นที่ที่เลือกไว้ ณ ตอนนี้",
        )

        ttk.Separator(frm_ocr.inner_frame, orient="horizontal").grid(row=5, column=0, columnspan=4, sticky="we", pady=6)

        ttk.Label(frm_ocr.inner_frame, text="โปรไฟล์คำ:").grid(row=6, column=0, sticky="w")
        self.ocr_profile_var = tk.StringVar(value="")
        self.profile_combo = ttk.Combobox(
            frm_ocr.inner_frame, textvariable=self.ocr_profile_var, values=list(self.ocr_profiles.keys()), width=22
        )
        self.profile_combo.grid(row=6, column=1, sticky="w")
        btns = ttk.Frame(frm_ocr.inner_frame)
        btns.grid(row=6, column=2, columnspan=2, sticky="w")
        ttk.Button(btns, text="โหลด", command=self.load_selected_profile).pack(side="left", padx=2)
        ttk.Button(btns, text="บันทึกเป็นโปรไฟล์", command=self.save_current_as_profile).pack(side="left", padx=2)
        ttk.Button(btns, text="ลบโปรไฟล์", command=self.delete_selected_profile).pack(side="left", padx=2)

        self.rules_listbox = tk.Listbox(frm_ocr.inner_frame, height=5)
        self.rules_listbox.grid(row=7, column=0, columnspan=4, sticky="we", padx=4, pady=4)
        self.refresh_rules_listbox()

        rule_ctrl = ttk.Frame(frm_ocr.inner_frame)
        rule_ctrl.grid(row=8, column=0, columnspan=4, sticky="we")

        ttk.Label(rule_ctrl, text="คำที่ตรวจจับ:").grid(row=0, column=0, sticky="w")
        self.new_rule_keyword = tk.StringVar()
        ttk.Entry(rule_ctrl, textvariable=self.new_rule_keyword, width=16).grid(row=0, column=1, padx=4)

        self.new_rule_action = tk.StringVar(value="TYPE_WEIGHT")
        ttk.OptionMenu(
            rule_ctrl, self.new_rule_action, "TYPE_WEIGHT",
            "TYPE_WEIGHT", "KEY", "CLICK", "PAUSE_WAIT_USER",
        ).grid(row=0, column=2, padx=4)

        self.new_rule_value = tk.StringVar(value="enter")
        rule_value_entry = ttk.Entry(rule_ctrl, textvariable=self.new_rule_value, width=10)
        rule_value_entry.grid(row=0, column=3, padx=4)
        ToolTip(rule_value_entry, "ชื่อคีย์ ใช้กับ action=กดคีย์ เช่น enter, tab, esc")

        ttk.Button(rule_ctrl, text="+ เพิ่มคำ", command=self.add_rule).grid(row=1, column=0, pady=4)
        ttk.Button(
            rule_ctrl, text="📍 จับตำแหน่งคลิกสำหรับคำนี้ (action=CLICK)",
            command=self.capture_click_for_rule,
        ).grid(row=1, column=1, columnspan=3, pady=4, sticky="w")
        ttk.Button(rule_ctrl, text="▲", width=3, command=self.move_rule_up).grid(row=1, column=4)
        ttk.Button(rule_ctrl, text="▼", width=3, command=self.move_rule_down).grid(row=1, column=5)
        ttk.Button(rule_ctrl, text="ลบ", command=self.delete_rule).grid(row=1, column=6)

        frm_ocr.inner_frame.columnconfigure(1, weight=1)
        frm_ocr.inner_frame.columnconfigure(2, weight=1)
        frm_ocr.inner_frame.columnconfigure(3, weight=1)

        # ---------- 6) ตรวจสอบรายการที่ตกหลุด (ทำหลังกรอกครบทุกรายการแล้ว) ----------
        frm_verify = SectionDialog(self._real_root, "ตรวจสอบรายการที่ตกหลุด")
        nav_btn6 = create_nav_button("✅\nตรวจสอบ", frm_verify.show)
        nav_btn6.pack(pady=3, fill="x")
        self.nav_buttons["verify"] = nav_btn6

        ttk.Separator(nav_frame, orient="horizontal").pack(fill="x", pady=6)
        nav_btn_codes = create_nav_button("📋\nรายการบาร์โค้ด", self.show_codes_window)
        nav_btn_codes.pack(pady=3, fill="x")
        self.nav_buttons["codes"] = nav_btn_codes

        nav_btn_shortcuts = create_nav_button("⌨️\nปุ่มลัด", self.open_shortcuts_window)
        nav_btn_shortcuts.pack(pady=3, fill="x")
        self.nav_buttons["shortcuts"] = nav_btn_shortcuts

        self.verify_region_var = tk.StringVar(value=self._region_to_str(self.verify_region))
        ttk.Button(
            frm_verify.inner_frame, text="🖱️ เลือกพื้นที่ตารางผลลัพธ์", command=self.select_verify_region
        ).grid(row=0, column=0, sticky="w", pady=(4, 4))
        ttk.Label(frm_verify.inner_frame, textvariable=self.verify_region_var).grid(
            row=0, column=1, columnspan=2, sticky="w"
        )
        test_verify_btn = ttk.Button(
            frm_verify.inner_frame, text="🔍 ทดสอบอ่านพื้นที่นี้", command=self.test_verify_region_now
        )
        test_verify_btn.grid(row=0, column=3, sticky="w", padx=(10, 0))
        ToolTip(
            test_verify_btn,
            "ทดสอบก่อนรันจริง — ถ่ายภาพพื้นที่ที่เลือกไว้ 1 ครั้ง แล้วโชว์ว่า OCR อ่านอะไรได้บ้าง "
            "ใช้เช็คว่าครอบตรงตำแหน่งตารางจริงหรือยัง ก่อนจะไปเลื่อนดูหลายสิบครั้ง",
        )

        scroll_label = ttk.Label(frm_verify.inner_frame, text="จำนวนครั้งเลื่อนดู:")
        scroll_label.grid(row=1, column=0, sticky="w", pady=(4, 0))
        self.verify_scroll_var = tk.StringVar(value="30")
        scroll_entry = ttk.Entry(frm_verify.inner_frame, textvariable=self.verify_scroll_var, width=6)
        scroll_entry.grid(row=1, column=1, sticky="w", pady=(4, 0))
        scroll_tip = "ระบบจะหมุน scroll wheel เหนือตารางเท่านี้ครั้ง สะสมข้อความจากทุกรอบไว้เทียบ ยิ่งรายการเยอะยิ่งต้องเลื่อนหลายครั้ง"
        ToolTip(scroll_label, scroll_tip)
        ToolTip(scroll_entry, scroll_tip)

        amount_label = ttk.Label(frm_verify.inner_frame, text="ระยะเลื่อนต่อครั้ง:")
        amount_label.grid(row=1, column=2, sticky="w", pady=(4, 0), padx=(10, 0))
        self.verify_scroll_amount_var = tk.StringVar(
            value=str(self.config_data.get("verify_scroll_amount", 400))
        )
        amount_entry = ttk.Entry(frm_verify.inner_frame, textvariable=self.verify_scroll_amount_var, width=6)
        amount_entry.grid(row=1, column=3, sticky="w", pady=(4, 0))
        amount_tip = (
            "ระยะที่หมุน scroll wheel ต่อ 1 ครั้ง ยิ่งค่าน้อยยิ่งเลื่อนทีละนิด (ซ้อนทับกันมากขึ้น "
            "ปลอดภัยไม่มีช่องโหว่ แต่ต้องใช้จำนวนครั้งเลื่อนดูเยอะขึ้นตาม) ถ้าตั้งมากเกินไปอาจเลื่อนข้ามแถว "
            "จนบางรายการไม่เคยถูกถ่ายภาพเห็นเลย — ค่าเริ่มต้น 400 ลองปรับดูได้ตามความเร็วการเลื่อนจริงของตาราง"
        )
        ToolTip(amount_label, amount_tip)
        ToolTip(amount_entry, amount_tip)

        self.verify_invert_var = tk.BooleanVar(value=self.config_data.get("verify_invert", False))
        cb_invert = ttk.Checkbutton(
            frm_verify.inner_frame,
            text="เจอในตาราง = ตกหลุด (ใช้กับหน้า 'คงเหลือในร้าน')",
            variable=self.verify_invert_var,
        )
        cb_invert.grid(row=2, column=0, columnspan=4, sticky="w", pady=(4, 0))
        ToolTip(
            cb_invert,
            "ไม่ติ๊ก (ค่า default): ใช้กับตารางยืนยันรับเข้าสำเร็จ — ไม่เจอในตาราง = ตกหลุด\n"
            "ติ๊ก: ใช้กับตารางรายการคงเหลือ/ค้างอยู่ — เจอในตาราง = ตกหลุด (ยังไม่ผ่านขั้นต่อไป)",
        )

        passes_label = ttk.Label(frm_verify.inner_frame, text="จำนวนรอบตรวจสอบ (ยืนยันซ้ำ):")
        passes_label.grid(row=3, column=0, columnspan=2, sticky="w", pady=(4, 0))
        self.verify_passes_var = tk.StringVar(value=str(self.config_data.get("verify_passes", 3)))
        passes_entry = ttk.Entry(frm_verify.inner_frame, textvariable=self.verify_passes_var, width=6)
        passes_entry.grid(row=3, column=2, sticky="w", pady=(4, 0))
        passes_tip = (
            "OCR อาจอ่านพลาดบางแถวแบบสุ่มในแต่ละรอบ ทำให้ผลไม่นิ่ง (เช่น เจอ 30, 28, 29 สลับกันไป) "
            "ตั้งค่านี้ให้มากกว่า 1 เพื่อตรวจซ้ำหลายรอบแล้วรวมผล — เจอรายการไหนแม้แค่รอบเดียวจากทั้งหมด "
            "ก็นับว่าเจอจริง แม่นยำกว่าเชื่อผลจากรอบเดียว (ยิ่งตั้งมากยิ่งแม่นแต่ยิ่งใช้เวลานาน)"
        )
        ToolTip(passes_label, passes_tip)
        ToolTip(passes_entry, passes_tip)

        ttk.Button(
            frm_verify.inner_frame, text="🔍 ตรวจสอบรายการที่ตกหลุด", command=self.check_missing_codes
        ).grid(row=4, column=0, columnspan=4, sticky="we", pady=(6, 4))

        frm_log = CollapsibleFrame(main_area, title="Log")
        frm_log.pack(fill="both", expand=True, **pad)
        log_frame = ttk.Frame(frm_log.inner_frame)
        log_frame.pack(fill="both", expand=True)
        log_scrollbar = ttk.Scrollbar(log_frame, orient="vertical")
        log_scrollbar.pack(side="right", fill="y")
        self.log_text = tk.Text(
            log_frame, height=10, wrap="none", yscrollcommand=log_scrollbar.set
        )
        self.log_text.pack(side="left", fill="both", expand=True)
        log_scrollbar.config(command=self.log_text.yview)

        frm_fail_log = CollapsibleFrame(
            main_area, title="Log ผิดเงื่อนไข (OCR หาไม่เจอ)",
            tooltip="แยกเก็บเฉพาะรายการที่สเต็ป 'รอข้อความ (OCR)' หาไม่เจอภายในเวลาที่กำหนด "
                    "พร้อมรายการถัดไปอีก 1 รายการ ไว้ตรวจสอบย้อนหลังโดยไม่ต้องไล่หาใน Log หลัก",
        )
        frm_fail_log.pack(fill="both", expand=False, **pad)
        fail_log_frame = ttk.Frame(frm_fail_log.inner_frame)
        fail_log_frame.pack(fill="both", expand=True)
        fail_log_scrollbar = ttk.Scrollbar(fail_log_frame, orient="vertical")
        fail_log_scrollbar.pack(side="right", fill="y")
        self.fail_log_text = tk.Text(
            fail_log_frame, height=6, wrap="none", yscrollcommand=fail_log_scrollbar.set, foreground="#b91c1c"
        )
        self.fail_log_text.pack(side="left", fill="both", expand=True)
        fail_log_scrollbar.config(command=self.fail_log_text.yview)
        ttk.Button(
            frm_fail_log.inner_frame, text="🗑️ ล้าง log นี้",
            command=lambda: self.fail_log_text.delete("1.0", tk.END),
        ).pack(anchor="e", pady=(4, 0))

        self.refresh_windows()

    # ---------- UI actions: ไฟล์/หน้าต่าง ----------
    def browse_pdf(self):
        path = filedialog.askopenfilename(filetypes=[("PDF files", "*.pdf")])
        if path:
            self.pdf_path_var.set(path)
            self.drop_label_var.set(f"✅ {os.path.basename(path)}")

    def on_pdf_drop(self, event):
        try:
            paths = self.root.tk.splitlist(event.data)
        except Exception:
            paths = [event.data]
        if not paths:
            return
        path = paths[0].strip("{}")
        if not path.lower().endswith(".pdf"):
            messagebox.showerror("ไฟล์ไม่ถูกต้อง", "กรุณาลากเฉพาะไฟล์ .pdf เท่านั้น")
            return
        self.pdf_path_var.set(path)
        self.drop_label_var.set(f"✅ {os.path.basename(path)}")
        self.log(f"รับไฟล์จากการลากวาง: {path}")

    def _auto_detect_on_startup(self):
        """ค้นหา Poppler และ Tesseract อัตโนมัติเมื่อเปิดโปรแกรม"""
        # ค้นหา Poppler
        if not self.poppler_path_var.get():
            project_poppler = os.path.join(RESOURCE_DIR, "poppler")
            import glob
            possible_paths = glob.glob(os.path.join(project_poppler, "poppler-*", "Library", "bin"))
            if possible_paths:
                self.poppler_path_var.set(possible_paths[0])
                self.log(f"✅ พบ Poppler ที่: {possible_paths[0]}")
        
        # ค้นหา Tesseract
        if not self.tesseract_path_var.get():
            project_tesseract = os.path.join(RESOURCE_DIR, "tesseract")
            tesseract_exe = os.path.join(project_tesseract, "tesseract.exe")
            if os.path.exists(tesseract_exe):
                self.tesseract_path_var.set(tesseract_exe)
                self.log(f"✅ พบ Tesseract ที่: {tesseract_exe}")

    def find_poppler_auto(self):
        """ค้นหา poppler/bin ในโปรเจกต์ folder"""
        project_poppler = os.path.join(RESOURCE_DIR, "poppler")
        
        # ค้นหา poppler-X.X.X/Library/bin ภายในโฟลเดอร์ poppler
        import glob
        possible_paths = glob.glob(os.path.join(project_poppler, "poppler-*", "Library", "bin"))
        
        if possible_paths:
            found_path = possible_paths[0]
            self.poppler_path_var.set(found_path)
            self.log(f"✅ พบ Poppler ที่: {found_path}")
            return
        
        messagebox.showinfo(
            "ติดตั้ง Poppler",
            f"ไม่พบ Poppler ในโปรเจกต์\n\n"
            f"วิธีติดตั้ง:\n"
            f"1. ดาวน์โหลด https://github.com/oschwartz10612/poppler-windows/releases\n"
            f"2. แตกไฟล์ลงที่: {project_poppler}\\\n"
            f"   (ตัวอย่าง: {project_poppler}\\poppler-24.02.0\\)\n"
            f"3. กดปุ่มค้นหาใหม่"
        )

    def browse_poppler(self):
        path = filedialog.askdirectory()
        if path:
            self.poppler_path_var.set(path)

    def find_tesseract_auto(self):
        """ค้นหา tesseract.exe ในโปรเจกต์ folder"""
        project_tesseract = os.path.join(RESOURCE_DIR, "tesseract")
        
        tesseract_exe = os.path.join(project_tesseract, "tesseract.exe")
        
        if os.path.exists(tesseract_exe):
            self.tesseract_path_var.set(tesseract_exe)
            self.log(f"✅ พบ Tesseract ที่: {tesseract_exe}")
            return
        
        messagebox.showinfo(
            "ติดตั้ง Tesseract",
            f"ไม่พบ Tesseract ในโปรเจกต์\n\n"
            f"วิธีติดตั้ง:\n"
            f"1. ดาวน์โหลด https://github.com/UB-Mannheim/tesseract/wiki\n"
            f"2. ตอนติดตั้ง เลือกเสน่ห์ติดตั้งที่: {project_tesseract}\\\n"
            f"3. ✅ เลือกภาษา Thai ในหน้า 'Additional language data'\n"
            f"4. กดปุ่มค้นหาใหม่"
        )

    def browse_tesseract(self):
        path = filedialog.askopenfilename(filetypes=[("tesseract.exe", "tesseract.exe"), ("All files", "*.*")])
        if path:
            self.tesseract_path_var.set(path)

    def refresh_windows(self):
        try:
            titles = [t for t in gw.getAllTitles() if t.strip()]
        except Exception:
            titles = []
        self.window_combo["values"] = titles

    # ---------- ลำดับการทำงาน (sequence) ----------
    def refresh_sequence_profiles(self):
        self.sequence_profile_combo["values"] = sorted(self.sequence_profiles)

    def save_sequence_profile(self):
        current_name = self.sequence_profile_var.get().strip()
        name = simpledialog.askstring(
            "บันทึกโปรไฟล์ลำดับ",
            "ชื่อโปรไฟล์ เช่น เครื่องชั่ง A หรือ รับสินค้าแบบเร็ว:",
            initialvalue=current_name,
            parent=self.root,
        )
        if name is None:
            return
        name = name.strip()
        if not name:
            messagebox.showerror("ผิดพลาด", "กรุณาระบุชื่อโปรไฟล์")
            return
        if name in self.sequence_profiles and name != current_name:
            if not messagebox.askyesno("ยืนยันการเขียนทับ", f"โปรไฟล์ '{name}' มีอยู่แล้ว ต้องการเขียนทับหรือไม่?"):
                return
        self.sequence_profiles[name] = copy.deepcopy(self.sequence)
        self.sequence_profile_var.set(name)
        self.refresh_sequence_profiles()
        self.save_sequence_profiles_file()
        self.save_config_to_disk()
        self.log(f"บันทึกโปรไฟล์ลำดับ '{name}' แล้ว")

    def apply_sequence_profile(self, _event=None):
        name = self.sequence_profile_var.get().strip()
        if not name:
            return
        profile = self.sequence_profiles.get(name)
        if profile is None:
            return
        self.sequence = copy.deepcopy(profile)
        self.refresh_seq_listbox()
        self.save_config_to_disk()
        self.log(f"เลือกใช้โปรไฟล์ลำดับ '{name}' แล้ว")

    def delete_sequence_profile(self):
        name = self.sequence_profile_var.get().strip()
        if not name or name not in self.sequence_profiles:
            messagebox.showinfo("ลบโปรไฟล์", "กรุณาเลือกโปรไฟล์ที่ต้องการลบ")
            return
        if not messagebox.askyesno("ยืนยันการลบ", f"ต้องการลบโปรไฟล์ '{name}' หรือไม่?"):
            return
        del self.sequence_profiles[name]
        self.sequence_profile_var.set("")
        self.refresh_sequence_profiles()
        self.save_sequence_profiles_file()
        self.save_config_to_disk()
        self.log(f"ลบโปรไฟล์ลำดับ '{name}' แล้ว")

    def refresh_seq_listbox(self):
        selected = self._selected_step_index()
        self.seq_tree.delete(*self.seq_tree.get_children())
        for i, step in enumerate(self.sequence):
            action, detail = step_to_columns(step)
            self.seq_tree.insert("", "end", iid=str(i), text=str(i + 1), values=(action, detail))
        if selected is not None and 0 <= selected < len(self.sequence):
            self.seq_tree.selection_set(str(selected))

    def _selected_step_index(self):
        sel = self.seq_tree.selection()
        if not sel:
            return None
        return int(sel[0])

    def on_step_type_change(self, selected_type):
        defaults = {
            "KEY": "enter",
            "WAIT": "0.5",
            "WAIT_FOR_TEXT": "10",
            "TYPE_BARCODE": "",
            "TYPE_WEIGHT": "",
            "CLICK": "",
        }
        self.new_step_value.set(defaults.get(selected_type, ""))

    def add_step(self):
        stype = self.new_step_type.get()
        val = self.new_step_value.get().strip()
        if stype == "KEY":
            step = {"type": "KEY", "value": val or "enter"}
        elif stype == "WAIT":
            try:
                float(val)
            except ValueError:
                messagebox.showerror("ผิดพลาด", "ใส่ตัวเลขวินาที เช่น 0.5")
                return
            step = {"type": "WAIT", "value": val}
        elif stype in ("TYPE_BARCODE", "TYPE_WEIGHT"):
            step = {"type": stype}
        elif stype == "WAIT_FOR_TEXT":
            try:
                timeout_val = float(val) if val else 10.0
            except ValueError:
                messagebox.showerror("ผิดพลาด", "ใส่ตัวเลขวินาที (timeout) เช่น 10")
                return
            keywords = self.pick_keywords_dialog([])
            step = {"type": "WAIT_FOR_TEXT", "timeout": str(timeout_val), "keywords": keywords}
        else:
            messagebox.showinfo("ใช้ปุ่มจับตำแหน่งเมาส์", "สำหรับสเต็ปคลิก ให้ใช้ปุ่ม 'จับตำแหน่งเมาส์' ด้านล่าง")
            return
        self.sequence.append(step)
        self.refresh_seq_listbox()

    def capture_click_position(self):
        def worker():
            for i in (3, 2, 1):
                self.log(f"ย้ายเมาส์ไปตำแหน่งที่ต้องการคลิก... จับภาพใน {i} วิ")
                time.sleep(1)
            x, y = pyautogui.position()
            step = {"type": "CLICK", "x": x, "y": y}
            self.sequence.append(step)
            self.root.after(0, self.refresh_seq_listbox)
            self.log(f"เพิ่มสเต็ปคลิกตำแหน่ง ({x}, {y}) แล้ว")

        threading.Thread(target=worker, daemon=True).start()

    def move_step_up(self):
        i = self._selected_step_index()
        if i is None or i == 0:
            return
        self.sequence[i - 1], self.sequence[i] = self.sequence[i], self.sequence[i - 1]
        self.refresh_seq_listbox()
        self.seq_tree.selection_set(str(i - 1))

    def move_step_down(self):
        i = self._selected_step_index()
        if i is None or i == len(self.sequence) - 1:
            return
        self.sequence[i + 1], self.sequence[i] = self.sequence[i], self.sequence[i + 1]
        self.refresh_seq_listbox()
        self.seq_tree.selection_set(str(i + 1))

    def delete_step(self):
        i = self._selected_step_index()
        if i is None:
            return
        del self.sequence[i]
        self.refresh_seq_listbox()

    def edit_step(self, _event=None):
        idx = self._selected_step_index()
        if idx is None:
            return
        step = self.sequence[idx]
        t = step["type"]
        if t == "KEY":
            new_val = simpledialog.askstring(
                "แก้ไขคีย์", "ชื่อคีย์ (เช่น enter, tab, esc):", initialvalue=step.get("value", "")
            )
            if not new_val:
                return
            step["value"] = new_val.strip()
        elif t == "WAIT":
            new_val = simpledialog.askstring(
                "แก้ไขเวลาหน่วง", "จำนวนวินาที เช่น 0.5:", initialvalue=step.get("value", "")
            )
            if not new_val:
                return
            try:
                float(new_val)
            except ValueError:
                messagebox.showerror("ผิดพลาด", "ใส่ตัวเลขวินาทีเท่านั้น")
                return
            step["value"] = new_val.strip()
        elif t == "WAIT_FOR_TEXT":
            new_val = simpledialog.askstring(
                "แก้ไข timeout", "จำนวนวินาทีสูงสุดที่จะรอ:", initialvalue=step.get("timeout", "")
            )
            if not new_val:
                return
            try:
                float(new_val)
            except ValueError:
                messagebox.showerror("ผิดพลาด", "ใส่ตัวเลขวินาทีเท่านั้น")
                return
            step["timeout"] = new_val.strip()
            if messagebox.askyesno("แก้ไขคำที่จะรอ", "ต้องการแก้ไขคำที่จะรอสำหรับสเต็ปนี้ด้วยหรือไม่?"):
                step["keywords"] = self.pick_keywords_dialog(step.get("keywords", []))
        elif t == "CLICK":
            if not messagebox.askyesno(
                "แก้ไขตำแหน่งคลิก",
                f"ตำแหน่งปัจจุบัน ({step.get('x')}, {step.get('y')})\nต้องการจับตำแหน่งใหม่หรือไม่?",
            ):
                return

            def worker():
                for i in (3, 2, 1):
                    self.log(f"ย้ายเมาส์ไปตำแหน่งใหม่... จับภาพใน {i} วิ")
                    time.sleep(1)
                x, y = pyautogui.position()
                step["x"], step["y"] = x, y
                self.root.after(0, self.refresh_seq_listbox)
                self.log(f"แก้ไขตำแหน่งคลิกเป็น ({x}, {y}) แล้ว")

            threading.Thread(target=worker, daemon=True).start()
            return
        else:
            return  # TYPE_BARCODE / TYPE_WEIGHT ไม่มีค่าให้แก้ไข
        self.refresh_seq_listbox()

    # ---------- ปุ่มลัด ----------
    def setup_shortcuts(self):
        self.apply_shortcuts()

    def _shortcut_sequence(self, shortcut):
        parts = [part.strip() for part in str(shortcut).split("+") if part.strip()]
        if not parts:
            return None
        key_aliases = {
            "ESC": "Escape",
            "ESCAPE": "Escape",
            "RETURN": "Return",
            "SPACE": "space",
            "DEL": "Delete",
            "DELETE": "Delete",
            "PGUP": "Prior",
            "PGDN": "Next",
        }
        key = parts.pop()
        key = key_aliases.get(key.upper(), key)
        if len(key) == 1:
            key = key.upper()
        elif key.upper().startswith("F") and key[1:].isdigit():
            key = key.upper()
        modifiers = []
        modifier_map = {"CTRL": "Control", "CONTROL": "Control", "SHIFT": "Shift", "ALT": "Alt"}
        for part in parts:
            modifier = modifier_map.get(part.upper())
            if not modifier:
                return None
            if modifier not in modifiers:
                modifiers.append(modifier)
        if not key:
            return None
        return f"<{'-'.join(modifiers + [key])}>"

    def _format_shortcut_event(self, event):
        modifiers = []
        if event.state & 0x0004:
            modifiers.append("Ctrl")
        if event.state & 0x0001:
            modifiers.append("Shift")
        if event.state & 0x0008:
            modifiers.append("Alt")
        key = {
            "Escape": "Escape",
            "Return": "Return",
            "space": "Space",
            "Delete": "Delete",
            "Prior": "PgUp",
            "Next": "PgDn",
        }.get(event.keysym, event.keysym)
        if len(key) == 1:
            key = key.upper()
        return "+".join(modifiers + [key])

    def apply_shortcuts(self):
        for binding in self._shortcut_bindings:
            self._real_root.unbind_all(binding)
        self._shortcut_bindings = []
        callbacks = {"start": self.start_automation, "stop": self.stop_automation}
        for action, callback in callbacks.items():
            sequence = self._shortcut_sequence(self.shortcuts.get(action, ""))
            if sequence:
                def handle_shortcut(_event, cb=callback):
                    cb()
                    return "break"

                self._real_root.bind_all(sequence, handle_shortcut, add="+")
                self._shortcut_bindings.append(sequence)

    def open_shortcuts_window(self):
        win = tk.Toplevel(self._real_root)
        win.title("ปุ่มลัด")
        win.resizable(False, False)
        frame = ttk.Frame(win, padding=12)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="กำหนดปุ่มลัดสำหรับเริ่มและหยุดการทำงาน").grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 10)
        )
        entries = {}
        for row, (action, label) in enumerate((("start", "เริ่มทำงาน:"), ("stop", "หยุดทำงาน:")), 1):
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=4)
            value = tk.StringVar(value=self.shortcuts.get(action, ""))
            entries[action] = value
            entry = ttk.Entry(frame, textvariable=value, width=18)
            entry.grid(row=row, column=1, pady=4)
            ttk.Button(
                frame,
                text="กดปุ่มเพื่อบันทึก",
                command=lambda var=value: self._capture_shortcut(win, var),
            ).grid(row=row, column=2, padx=(8, 0), pady=4)

        ttk.Label(
            frame, text="ตัวอย่าง: F6, Ctrl+F6, Ctrl+Shift+S (เว้นว่างเพื่อปิดปุ่มลัด)"
        ).grid(row=3, column=0, columnspan=3, sticky="w", pady=(6, 10))

        def save():
            new_shortcuts = {action: value.get().strip() for action, value in entries.items()}
            sequences = [self._shortcut_sequence(value) for value in new_shortcuts.values() if value]
            if None in sequences or len(sequences) != len(set(sequences)):
                messagebox.showerror("ปุ่มลัดไม่ถูกต้อง", "รูปแบบปุ่มลัดไม่ถูกต้อง หรือใช้ปุ่มซ้ำกัน", parent=win)
                return
            self.shortcuts = new_shortcuts
            self.apply_shortcuts()
            self.save_config_to_disk()
            win.destroy()
            self.log("บันทึกการตั้งค่าปุ่มลัดแล้ว")

        buttons = ttk.Frame(frame)
        buttons.grid(row=4, column=0, columnspan=3, sticky="e")
        ttk.Button(buttons, text="บันทึก", command=save).pack(side="left", padx=3)
        ttk.Button(buttons, text="ยกเลิก", command=win.destroy).pack(side="left", padx=3)

    def _capture_shortcut(self, parent, variable):
        dialog = tk.Toplevel(parent)
        dialog.title("กดปุ่มลัด")
        dialog.resizable(False, False)
        ttk.Label(dialog, text="กดปุ่มหรือชุดปุ่มที่ต้องการใช้งาน").pack(padx=20, pady=20)
        modifier_keys = {"Control_L", "Control_R", "Shift_L", "Shift_R", "Alt_L", "Alt_R", "Win_L", "Win_R"}

        def capture(event):
            if event.keysym in modifier_keys:
                return "break"
            shortcut = self._format_shortcut_event(event)
            if shortcut:
                variable.set(shortcut)
                dialog.destroy()
            return "break"

        dialog.bind("<KeyPress>", capture)
        dialog.grab_set()
        dialog.focus_force()

    def _codes_count_text(self):
        return f"มีข้อมูลบาร์โค้ดที่ดึงไว้อยู่: {len(self.extracted_codes)} รายการ (กด 'เริ่มทำงาน' จะใช้ชุดนี้เลย)"

    @staticmethod
    def _keywords_from_text(value):
        return [item.strip() for item in str(value).split(",") if item.strip()]

    def _update_stats_label(self):
        self.stats_var.set(
            f"กรอกแล้ว: {self.stats['completed']} | ยกเลิก: {self.stats['cancel']} | ซ้ำ: {self.stats['duplicate']}"
        )

    def _reset_stats(self):
        self.stats = {"completed": 0, "cancel": 0, "duplicate": 0}
        self.root.after(0, self._update_stats_label)

    def update_codes_count_label(self):
        self.codes_count_var.set(self._codes_count_text())

    def show_codes_window(self):
        win = tk.Toplevel(self.root)
        win.title(f"รายการบาร์โค้ดที่ดึงมา ({len(self.extracted_codes)} รายการ)")
        win.geometry("420x520")
        ttk.Label(
            win, text=f"ทั้งหมด {len(self.extracted_codes)} รายการ", font=("", 11, "bold")
        ).pack(pady=6)
        frame = ttk.Frame(win)
        frame.pack(fill="both", expand=True, padx=8, pady=4)
        scrollbar = ttk.Scrollbar(frame)
        scrollbar.pack(side="right", fill="y")
        lb = tk.Listbox(frame, yscrollcommand=scrollbar.set)
        lb.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=lb.yview)
        for i, c in enumerate(self.extracted_codes, 1):
            lb.insert(tk.END, f"{i}. {c}")
        ttk.Button(
            win, text="ดึงบาร์โค้ดใหม่จาก PDF (รีเฟรชรายการนี้)",
            command=lambda: [win.destroy(), self.preview_barcodes()],
        ).pack(pady=6)

    # ---------- OCR: พื้นที่ตรวจจับ ----------
    def _region_to_str(self, region):
        if not region:
            return "(ยังไม่ได้เลือกพื้นที่)"
        return f"({region['left']}, {region['top']}) ขนาด {region['width']}x{region['height']}"

    def test_ocr_now(self):
        if not self.ocr_region:
            if not messagebox.askyesno(
                "ยังไม่ได้เลือกพื้นที่", "ยังไม่ได้เลือกพื้นที่ตรวจจับ จะทดสอบอ่านทั้งจอแทนหรือไม่?"
            ):
                return
        lang = self.ocr_lang_var.get()
        tesseract_path = self.tesseract_path_var.get()
        self._real_root.withdraw()
        time.sleep(0.3)  # ให้หน้าต่างโปรแกรมนี้หลบไปก่อน จะได้ไม่บังพื้นที่ที่จะอ่าน
        try:
            text = ocr_capture_text(self.ocr_region, lang, tesseract_path)
        except Exception as e:
            self._real_root.deiconify()
            messagebox.showerror("OCR อ่านไม่สำเร็จ", str(e))
            return
        self._real_root.deiconify()
        keywords = [r.get("keyword", "") for r in self.ocr_rules if r.get("keyword")]
        found_kws = [kw for kw in keywords if kw in text]
        result_msg = f"ข้อความที่ OCR อ่านได้:\n\n{text.strip() or '(ไม่พบตัวอักษรเลย)'}"
        if keywords:
            if found_kws:
                result_msg += f"\n\n✅ เจอคำที่ตรงกับโปรไฟล์: {', '.join(found_kws)}"
            else:
                result_msg += f"\n\n❌ ไม่เจอคำใดในโปรไฟล์ ({', '.join(keywords)}) ในข้อความนี้"
        messagebox.showinfo("ผลทดสอบ OCR", result_msg)

    def test_verify_region_now(self):
        if not self.verify_region:
            messagebox.showerror("ผิดพลาด", "กรุณาเลือกพื้นที่ตารางผลลัพธ์ก่อน (ปุ่ม 'เลือกพื้นที่ตารางผลลัพธ์')")
            return
        lang = self.ocr_lang_var.get()
        tesseract_path = self.tesseract_path_var.get()
        self._real_root.withdraw()
        time.sleep(0.3)
        try:
            text = ocr_capture_text(self.verify_region, lang, tesseract_path)
        except Exception as e:
            self._real_root.deiconify()
            messagebox.showerror("OCR อ่านไม่สำเร็จ", str(e))
            return
        self._real_root.deiconify()

        sample_matches = 0
        sample_checked = self.extracted_codes[:20]
        text_norm = self.normalize_for_ocr_match(text)
        if sample_checked:
            sample_matches = sum(
                1 for c in sample_checked
                if self.normalize_for_ocr_match(self.get_match_key(c)) in text_norm
            )

        result_msg = f"ข้อความที่ OCR อ่านได้จากพื้นที่นี้:\n\n{text.strip() or '(ไม่พบตัวอักษรเลย)'}"
        if sample_checked:
            result_msg += (
                f"\n\nลองเทียบกับ {len(sample_checked)} รายการแรกที่ดึงจาก PDF: "
                f"เจอตรงกัน {sample_matches} รายการ"
            )
            if sample_matches == 0:
                result_msg += (
                    "\n\n⚠️ ไม่เจอเลยสักรายการ — พื้นที่นี้อาจไม่ได้ครอบตรงตำแหน่งตารางจริง "
                    "ลองเลือกพื้นที่ใหม่ให้ครอบคอลัมน์ที่โชว์รหัสสินค้าโดยตรง"
                )
        messagebox.showinfo("ผลทดสอบพื้นที่ตารางผลลัพธ์", result_msg)

    def select_region_overlay(self, on_selected, prompt_text="ลากเมาส์เลือกพื้นที่ แล้วปล่อยเมาส์ (กด Esc เพื่อยกเลิก)"):
        """เปิด overlay เต็มจอให้ลากเลือกพื้นที่สี่เหลี่ยม แล้วเรียก on_selected(region) เมื่อเลือกเสร็จ"""
        self._real_root.withdraw()
        time.sleep(0.3)
        overlay = tk.Toplevel()
        overlay.attributes("-fullscreen", True)
        overlay.attributes("-alpha", 0.35)
        overlay.attributes("-topmost", True)
        overlay.configure(bg="black")
        canvas = tk.Canvas(overlay, cursor="cross", bg="grey20", highlightthickness=0)
        canvas.pack(fill="both", expand=True)
        info = tk.Label(overlay, text=prompt_text, bg="yellow", fg="black")
        info.place(relx=0.5, rely=0.03, anchor="n")
        state = {}

        def on_press(e):
            state["x0"], state["y0"] = e.x, e.y

        def on_drag(e):
            canvas.delete("sel")
            canvas.create_rectangle(state.get("x0", e.x), state.get("y0", e.y), e.x, e.y, outline="red", width=2, tags="sel")

        def finish(left, top, width, height):
            overlay.destroy()
            self._real_root.deiconify()
            if width < 5 or height < 5:
                self.log("ยกเลิกการเลือกพื้นที่ (พื้นที่เล็กเกินไปหรือกดยกเลิก)")
                return
            on_selected({"left": left, "top": top, "width": width, "height": height})

        def on_release(e):
            x0, y0 = state.get("x0", e.x), state.get("y0", e.y)
            x1, y1 = e.x, e.y
            left, top = min(x0, x1), min(y0, y1)
            width, height = abs(x1 - x0), abs(y1 - y0)
            finish(left, top, width, height)

        def on_escape(_e):
            overlay.destroy()
            self._real_root.deiconify()
            self.log("ยกเลิกการเลือกพื้นที่")

        canvas.bind("<ButtonPress-1>", on_press)
        canvas.bind("<B1-Motion>", on_drag)
        canvas.bind("<ButtonRelease-1>", on_release)
        overlay.bind("<Escape>", on_escape)

    def select_ocr_region(self):
        def on_selected(region):
            self.ocr_region = region
            self.ocr_region_var.set(self._region_to_str(region))
            self.log(f"ตั้งพื้นที่ตรวจจับข้อความ: {region}")

        self.select_region_overlay(on_selected)

    def select_verify_region(self):
        def on_selected(region):
            self.verify_region = region
            self.verify_region_var.set(self._region_to_str(region))
            self.log(f"ตั้งพื้นที่ตารางผลลัพธ์: {region}")

        self.select_region_overlay(
            on_selected, "ลากเมาส์เลือกพื้นที่ตารางผลลัพธ์ในโปรแกรมเป้าหมาย แล้วปล่อยเมาส์ (กด Esc เพื่อยกเลิก)"
        )

    # ---------- ตรวจสอบรายการที่ตกหลุด ----------
    def get_match_key(self, code):
        """ตัดเอาแค่ส่วนแรกก่อนช่องว่างมาเช็ค เช่น 'TIK0120266882 1 1 BPK001' -> 'TIK0120266882'
        รองรับทั้งกรณี QR เก็บมาเป็นรหัสเดี่ยวๆ และแบบมีส่วนต่อท้าย (กล่องที่/รหัสอื่น)"""
        code = (code or "").strip()
        return code.split()[0] if " " in code else code

    def normalize_for_ocr_match(self, text):
        """แก้ปัญหา OCR อ่านตัวอักษรที่หน้าตาคล้ายกันสับสน (พบบ่อยสุดคือ O กับเลข 0)
        แปลงให้เป็นมาตรฐานเดียวกันก่อนเทียบ ใช้กับทั้งรหัสจาก PDF และข้อความที่ OCR อ่านได้"""
        return (text or "").upper().replace("O", "0")

    def check_missing_codes(self):
        if not self.extracted_codes:
            messagebox.showerror("ผิดพลาด", "ยังไม่มีข้อมูลบาร์โค้ดที่ดึงไว้ กรุณากด 'ดึงบาร์โค้ดจาก PDF' ก่อน")
            return
        if not self.verify_region:
            messagebox.showerror("ผิดพลาด", "กรุณาเลือกพื้นที่ตารางผลลัพธ์ก่อน")
            return
        try:
            scroll_count = int(self.verify_scroll_var.get() or 30)
        except ValueError:
            messagebox.showerror("ผิดพลาด", "ใส่จำนวนครั้งเลื่อนดู เป็นตัวเลขเท่านั้น")
            return
        try:
            scroll_amount = int(self.verify_scroll_amount_var.get() or 400)
        except ValueError:
            messagebox.showerror("ผิดพลาด", "ใส่ระยะเลื่อนต่อครั้ง เป็นตัวเลขเท่านั้น")
            return
        try:
            passes = int(self.verify_passes_var.get() or 1)
            passes = max(1, passes)
        except ValueError:
            messagebox.showerror("ผิดพลาด", "ใส่จำนวนรอบตรวจสอบ เป็นตัวเลขเท่านั้น")
            return
        if self.worker_thread and self.worker_thread.is_alive():
            messagebox.showinfo("กำลังทำงานอยู่", "รอให้งานปัจจุบันเสร็จก่อน")
            return
        if not messagebox.askyesno(
            "ยืนยันการตรวจสอบ",
            f"จะเลื่อนดูตารางในโปรแกรมเป้าหมาย {scroll_count} ครั้ง x {passes} รอบ เพื่ออ่านรายการทั้งหมด\n"
            "ระหว่างนี้อย่าไปยุ่งกับเมาส์/คีย์บอร์ด\n\n"
            "สลับไปโฟกัสตารางในโปรแกรมเป้าหมายให้พร้อมก่อนกด Yes\n\nยืนยันหรือไม่?",
        ):
            return

        region = dict(self.verify_region)
        lang = self.ocr_lang_var.get()
        tesseract_path = self.tesseract_path_var.get()
        codes_to_check = list(self.extracted_codes)
        invert = self.verify_invert_var.get()

        def worker():
            code_keys_norm = {
                c: self.normalize_for_ocr_match(self.get_match_key(c)) for c in codes_to_check
            }
            matched_codes = set()  # รวมผล "เจอ" จากทุกรอบด้วย union กันรอบไหนพลาด
            center_x = region["left"] + region["width"] // 2
            center_y = region["top"] + region["height"] // 2

            for p in range(passes):
                if self.stop_event.is_set():
                    self.log("ยกเลิกการตรวจสอบ")
                    return
                self.log(f"=== รอบตรวจสอบที่ {p + 1}/{passes} (เลื่อนดู {scroll_count} ครั้ง ระยะ {scroll_amount}/ครั้ง) ===")

                if p > 0:
                    # เลื่อนกลับขึ้นบนสุดก่อนเริ่มรอบใหม่ ไม่งั้นจะค้างอยู่ท้ายตารางจากรอบก่อน
                    self.log("  เลื่อนกลับขึ้นบนสุดของตาราง...")
                    try:
                        pyautogui.moveTo(center_x, center_y)
                        pyautogui.scroll(scroll_amount * (scroll_count + 5))
                    except Exception:
                        pass
                    time.sleep(0.5)

                accumulated = []
                for i in range(scroll_count):
                    if self.stop_event.is_set():
                        self.log("ยกเลิกการตรวจสอบ")
                        return
                    self.log(f"  อ่านครั้งที่ {i + 1}/{scroll_count}...")
                    try:
                        text = ocr_capture_text(region, lang, tesseract_path, ocr_timeout=5)
                        accumulated.append(text)
                    except Exception as e:
                        self.log(f"  ⚠️ OCR อ่านไม่สำเร็จรอบนี้: {e}")
                    try:
                        pyautogui.moveTo(center_x, center_y)
                        pyautogui.scroll(-scroll_amount)
                    except Exception:
                        pass
                    time.sleep(0.4)

                combined_text_norm = self.normalize_for_ocr_match("\n".join(accumulated))
                found_this_pass = 0
                for c, key in code_keys_norm.items():
                    if key in combined_text_norm and c not in matched_codes:
                        matched_codes.add(c)
                        found_this_pass += 1
                self.log(f"  รอบนี้เจอเพิ่ม {found_this_pass} รายการ (สะสมรวม {len(matched_codes)} รายการ)")

            if invert:
                # โหมด "คงเหลือ/ค้างอยู่": เจอในตาราง = ยังไม่ผ่านขั้นต่อไป = ตกหลุด
                missing = [c for c in codes_to_check if c in matched_codes]
            else:
                # โหมด default: ไม่เจอในตารางยืนยันรับเข้า (ในทุกรอบเลย) = ตกหลุด
                missing = [c for c in codes_to_check if c not in matched_codes]
            self.log(
                f"ตรวจสอบเสร็จสิ้น ({passes} รอบ) พบรายการที่ตกหลุด {len(missing)} จากทั้งหมด {len(codes_to_check)} รายการ"
            )
            self.root.after(0, lambda: self.show_missing_report(missing, len(codes_to_check)))

        self.stop_event.clear()
        self.worker_thread = threading.Thread(target=worker, daemon=True)
        self.worker_thread.start()

    def show_missing_report(self, missing, total):
        win = tk.Toplevel(self.root)
        win.title(f"รายการที่ตกหลุด ({len(missing)} จาก {total})")
        win.geometry("420x520")
        if missing:
            ttk.Label(
                win, text=f"พบรายการที่ตกหลุด {len(missing)} จากทั้งหมด {total} รายการ",
                font=("", 11, "bold"), foreground="#b91c1c",
            ).pack(pady=6)
        else:
            ttk.Label(
                win, text=f"ไม่พบรายการตกหลุด ครบทั้ง {total} รายการ ✅",
                font=("", 11, "bold"), foreground="#15803d",
            ).pack(pady=6)

        frame = ttk.Frame(win)
        frame.pack(fill="both", expand=True, padx=8, pady=4)
        scrollbar = ttk.Scrollbar(frame)
        scrollbar.pack(side="right", fill="y")
        lb = tk.Listbox(frame, yscrollcommand=scrollbar.set)
        lb.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=lb.yview)
        for i, c in enumerate(missing, 1):
            lb.insert(tk.END, f"{i}. {c}")

        def copy_list():
            try:
                pyperclip.copy("\n".join(missing))
                messagebox.showinfo("คัดลอกแล้ว", "คัดลอกรายการที่ตกหลุดไปยังคลิปบอร์ดแล้ว")
            except Exception as e:
                messagebox.showerror("ผิดพลาด", str(e))

        if missing:
            ttk.Button(win, text="📋 คัดลอกรายการที่ตกหลุด", command=copy_list).pack(pady=6)

    # ---------- OCR: โปรไฟล์คำ ----------
    def refresh_rules_listbox(self):
        self.rules_listbox.delete(0, tk.END)
        for r in self.ocr_rules:
            self.rules_listbox.insert(tk.END, rule_to_display(r))

    def pick_keywords_dialog(self, initial=None):
        """เปิดกล่องให้ติ๊กเลือกว่าจะรอคำไหนบ้างจากโปรไฟล์คำปัจจุบัน คืนค่า list ของคำที่เลือก"""
        initial = set(initial or [])
        seen = set()
        all_keywords = []
        for r in self.ocr_rules:
            kw = r.get("keyword", "")
            if kw and kw not in seen:
                seen.add(kw)
                all_keywords.append(kw)
        if not all_keywords:
            messagebox.showinfo(
                "ยังไม่มีคำ", "ยังไม่มีคำในโปรไฟล์ OCR (ข้อ 5) กรุณาเพิ่มคำ หรือโหลดโปรไฟล์คำก่อน"
            )
            return list(initial)

        win = tk.Toplevel(self.root)
        win.title("เลือกคำที่จะรอ")
        win.grab_set()
        ttk.Label(
            win, text="เลือกคำที่จะให้สเต็ปนี้รอ\n(ไม่ติ๊กเลย = รอทุกคำในโปรไฟล์ปัจจุบัน)",
            justify="left",
        ).pack(padx=10, pady=(10, 6), anchor="w")

        vars_map = {}
        frame = ttk.Frame(win)
        frame.pack(padx=10, pady=4, fill="both", expand=True)
        for kw in all_keywords:
            v = tk.BooleanVar(value=(kw in initial))
            ttk.Checkbutton(frame, text=kw, variable=v).pack(anchor="w")
            vars_map[kw] = v

        result = {"selected": None}

        def on_ok():
            result["selected"] = [kw for kw, v in vars_map.items() if v.get()]
            win.destroy()

        def on_cancel():
            result["selected"] = None
            win.destroy()

        btns = ttk.Frame(win)
        btns.pack(pady=8)
        ttk.Button(btns, text="ตกลง", command=on_ok).pack(side="left", padx=4)
        ttk.Button(btns, text="ยกเลิก", command=on_cancel).pack(side="left", padx=4)
        win.protocol("WM_DELETE_WINDOW", on_cancel)
        win.wait_window()
        if result["selected"] is None:
            return list(initial)
        return result["selected"]

    def add_rule(self):
        kw = self.new_rule_keyword.get().strip()
        if not kw:
            messagebox.showerror("ผิดพลาด", "กรุณาใส่คำที่ต้องการให้ตรวจจับก่อน")
            return
        action = self.new_rule_action.get()
        if action == "KEY":
            rule = {"keyword": kw, "action": "KEY", "value": self.new_rule_value.get().strip() or "enter"}
        elif action == "TYPE_WEIGHT":
            rule = {"keyword": kw, "action": "TYPE_WEIGHT"}
        elif action == "PAUSE_WAIT_USER":
            rule = {"keyword": kw, "action": "PAUSE_WAIT_USER"}
        elif action == "CLICK":
            messagebox.showinfo(
                "ใช้ปุ่มจับตำแหน่งเมาส์",
                "สำหรับ action คลิก ใส่คำในช่องด้านบนก่อน แล้วกดปุ่ม 'จับตำแหน่งคลิกสำหรับคำนี้' แทน",
            )
            return
        else:
            return
        self.ocr_rules.append(rule)
        self.refresh_rules_listbox()
        self.new_rule_keyword.set("")

    def capture_click_for_rule(self):
        kw = self.new_rule_keyword.get().strip()
        if not kw:
            messagebox.showerror("ผิดพลาด", "กรุณาใส่คำที่ต้องการให้ตรวจจับก่อน")
            return

        def worker():
            for i in (3, 2, 1):
                self.log(f"ย้ายเมาส์ไปตำแหน่งที่ต้องการคลิกสำหรับคำ '{kw}'... จับภาพใน {i} วิ")
                time.sleep(1)
            x, y = pyautogui.position()
            rule = {"keyword": kw, "action": "CLICK", "x": x, "y": y}
            self.ocr_rules.append(rule)
            self.root.after(0, self.refresh_rules_listbox)
            self.root.after(0, lambda: self.new_rule_keyword.set(""))
            self.log(f"เพิ่มเงื่อนไข '{kw}' -> คลิก ({x},{y}) แล้ว")

        threading.Thread(target=worker, daemon=True).start()

    def move_rule_up(self):
        sel = self.rules_listbox.curselection()
        if not sel or sel[0] == 0:
            return
        i = sel[0]
        self.ocr_rules[i - 1], self.ocr_rules[i] = self.ocr_rules[i], self.ocr_rules[i - 1]
        self.refresh_rules_listbox()
        self.rules_listbox.selection_set(i - 1)

    def move_rule_down(self):
        sel = self.rules_listbox.curselection()
        if not sel or sel[0] == len(self.ocr_rules) - 1:
            return
        i = sel[0]
        self.ocr_rules[i + 1], self.ocr_rules[i] = self.ocr_rules[i], self.ocr_rules[i + 1]
        self.refresh_rules_listbox()
        self.rules_listbox.selection_set(i + 1)

    def delete_rule(self):
        sel = self.rules_listbox.curselection()
        if not sel:
            return
        del self.ocr_rules[sel[0]]
        self.refresh_rules_listbox()

    def load_selected_profile(self):
        name = self.ocr_profile_var.get()
        if not name or name not in self.ocr_profiles:
            messagebox.showinfo("เลือกโปรไฟล์", "กรุณาเลือกโปรไฟล์จากรายการก่อน")
            return
        self.ocr_rules = list(self.ocr_profiles[name])
        self.refresh_rules_listbox()
        self.log(f"โหลดโปรไฟล์คำ '{name}' แล้ว ({len(self.ocr_rules)} คำ)")

    def save_current_as_profile(self):
        name = simpledialog.askstring(
            "บันทึกโปรไฟล์", "ตั้งชื่อโปรไฟล์ (ถ้าซ้ำชื่อเดิมจะทับของเดิม):",
            initialvalue=self.ocr_profile_var.get(),
        )
        if not name:
            return
        self.ocr_profiles[name] = list(self.ocr_rules)
        self.save_ocr_profiles_file()
        self.profile_combo["values"] = list(self.ocr_profiles.keys())
        self.ocr_profile_var.set(name)
        self.log(f"บันทึกโปรไฟล์คำ '{name}' แล้ว ({len(self.ocr_rules)} คำ)")

    def delete_selected_profile(self):
        name = self.ocr_profile_var.get()
        if name in self.ocr_profiles:
            del self.ocr_profiles[name]
            self.save_ocr_profiles_file()
            self.profile_combo["values"] = list(self.ocr_profiles.keys())
            self.ocr_profile_var.set("")
            self.log(f"ลบโปรไฟล์ '{name}' แล้ว")

    def preview_barcodes(self):
        pdf_path = self.pdf_path_var.get().strip()
        if not pdf_path or not os.path.exists(pdf_path):
            messagebox.showerror("ผิดพลาด", "กรุณาเลือกไฟล์ PDF ที่มีอยู่จริงก่อน")
            return
        if self.worker_thread and self.worker_thread.is_alive():
            messagebox.showinfo("กำลังทำงานอยู่", "รอให้งานปัจจุบันเสร็จก่อน")
            return

        poppler_path = self.poppler_path_var.get()
        only_qrcode = self.only_qrcode_var.get()
        try:
            dpi = int(self.dpi_var.get() or 150)
        except ValueError:
            dpi = 150
        self.log("กำลังอ่าน PDF และสแกนบาร์โค้ด... (หน้าต่างอาจดูเหมือนไม่ตอบสนองชั่วครู่ รอสักครู่ไม่ต้องปิดโปรแกรม)")

        def worker():
            try:
                codes = extract_barcodes(pdf_path, poppler_path, only_qrcode, dpi)
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror("อ่าน PDF ไม่สำเร็จ", str(e)))
                self.log(f"❌ อ่าน PDF ไม่สำเร็จ: {e}")
                return
            if not codes:
                self.root.after(
                    0, lambda: messagebox.showwarning("ไม่พบบาร์โค้ด", "อ่าน PDF ได้ แต่ไม่พบบาร์โค้ดในไฟล์นี้")
                )
                self.log("ไม่พบบาร์โค้ดในไฟล์นี้")
                return
            preview = "\n".join(f"{i+1}. {c}" for i, c in enumerate(codes[:30]))
            more = f"\n... และอีก {len(codes)-30} รายการ" if len(codes) > 30 else ""
            self.log(f"อ่านสำเร็จ พบบาร์โค้ดทั้งหมด {len(codes)} รายการ")
            self.extracted_codes = codes
            self.save_codes_cache()
            self.root.after(0, self.update_codes_count_label)
            self.root.after(
                0,
                lambda: messagebox.showinfo("พบบาร์โค้ด", f"พบทั้งหมด {len(codes)} รายการ:\n\n{preview}{more}"),
            )

        self.worker_thread = threading.Thread(target=worker, daemon=True)
        self.worker_thread.start()

    # ---------- logging ----------
    def log(self, msg):
        self.log_queue.put(msg)

    def log_fail(self, msg):
        self.fail_log_queue.put(msg)

    def poll_log_queue(self):
        try:
            while True:
                msg = self.log_queue.get_nowait()
                self.log_text.insert(tk.END, msg + "\n")
                self.log_text.see(tk.END)
        except queue.Empty:
            pass
        try:
            while True:
                msg = self.fail_log_queue.get_nowait()
                self.fail_log_text.insert(tk.END, msg + "\n")
                self.fail_log_text.see(tk.END)
        except queue.Empty:
            pass
        self.root.after(150, self.poll_log_queue)

    # ---------- automation ----------
    def start_automation(self):
        if self.worker_thread and self.worker_thread.is_alive():
            messagebox.showinfo("กำลังทำงานอยู่", "โปรแกรมกำลังรันอยู่แล้ว")
            return

        if self.extracted_codes and not self.force_refresh_var.get():
            self.log(f"ใช้ข้อมูลบาร์โค้ดที่เคยดึงไว้ก่อนหน้า ({len(self.extracted_codes)} รายการ) ไม่ดึงใหม่")
            self._confirm_and_run(list(self.extracted_codes))
            return

        pdf_path = self.pdf_path_var.get().strip()
        if not pdf_path or not os.path.exists(pdf_path):
            messagebox.showerror("ผิดพลาด", "กรุณาเลือกไฟล์ PDF ที่มีอยู่จริงก่อน")
            return

        poppler_path = self.poppler_path_var.get()
        only_qrcode = self.only_qrcode_var.get()
        try:
            dpi = int(self.dpi_var.get() or 150)
        except ValueError:
            dpi = 150
        self.log("กำลังอ่าน PDF และสแกนบาร์โค้ด... (หน้าต่างอาจดูเหมือนไม่ตอบสนองชั่วครู่ รอสักครู่ไม่ต้องปิดโปรแกรม)")

        def extraction_worker():
            try:
                codes = extract_barcodes(pdf_path, poppler_path, only_qrcode, dpi)
            except Exception as e:
                self.log(f"❌ อ่าน PDF ไม่สำเร็จ: {e}")
                self.root.after(0, lambda: messagebox.showerror("อ่าน PDF ไม่สำเร็จ", str(e)))
                return
            if not codes:
                self.log("ไม่พบบาร์โค้ดในไฟล์นี้ ยกเลิกการทำงาน")
                self.root.after(
                    0,
                    lambda: messagebox.showwarning("ไม่พบบาร์โค้ด", "ไม่พบบาร์โค้ดในไฟล์นี้ ยกเลิกการทำงาน"),
                )
                return
            self.extracted_codes = codes
            self.save_codes_cache()
            self.root.after(0, self.update_codes_count_label)
            self.root.after(0, lambda: self._confirm_and_run(codes))

        self.worker_thread = threading.Thread(target=extraction_worker, daemon=True)
        self.worker_thread.start()

    def _confirm_and_run(self, codes):
        if self.reverse_order_var.get():
            codes = list(reversed(codes))
        total = len(codes)
        try:
            start_index = int(self.start_index_var.get().strip() or 1)
        except ValueError:
            messagebox.showerror("ผิดพลาด", "กรุณาใส่ 'เริ่มจากรายการที่' เป็นตัวเลขเท่านั้น")
            return
        if start_index < 1 or start_index > total:
            messagebox.showerror("ผิดพลาด", f"'เริ่มจากรายการที่' ต้องอยู่ระหว่าง 1 ถึง {total}")
            return
        run_codes = codes[start_index - 1:]

        dry_run = self.dry_run_var.get()
        if not dry_run:
            start_note = (
                f" (เริ่มจากรายการที่ {start_index} จากทั้งหมด {total})" if start_index > 1 else ""
            )
            ok = messagebox.askyesno(
                "ยืนยันการรันจริง",
                f"จะพิมพ์/คลิกจริง {len(run_codes)} รายการ{start_note} ไปยังโปรแกรมที่โฟกัสอยู่\n"
                "สลับหน้าต่างไปโฟกัสโปรแกรมเป้าหมายให้พร้อมก่อนกด Yes\n\n"
                "ยืนยันหรือไม่?",
            )
            if not ok:
                self.log("ยกเลิกโดยผู้ใช้")
                return

        config = self.gather_config_from_ui()
        self.save_config_to_disk()  # จำการตั้งค่าไว้อัตโนมัติ
        self._reset_stats()
        self.stop_event.clear()
        self.worker_thread = threading.Thread(
            target=self.run_automation, args=(config, run_codes, dry_run, total, start_index), daemon=True
        )
        self.worker_thread.start()

    def stop_automation(self):
        self.stop_event.set()
        self.resume_event.set()  # ปลดล็อกกรณีกำลังหยุดรออยู่ ไม่ให้ค้าง
        self.log("สั่งหยุด... จะหยุดหลังจบสเต็ปปัจจุบัน")

    def resume_automation(self):
        self.resume_event.set()

    def force_english_keyboard_layout(self):
        """สลับภาษาแป้นพิมพ์ของหน้าต่างที่โฟกัสอยู่เป็นอังกฤษ (US) ก่อนพิมพ์/วาง
        แก้ปัญหาคีย์บอร์ดภาษาไทยทำให้ Ctrl+V หรือการพิมพ์จำลองทำงานไม่เสถียรกับบางโปรแกรม"""
        try:
            user32 = ctypes.windll.user32
            KLF_ACTIVATE = 0x00000001
            hkl = user32.LoadKeyboardLayoutW("00000409", KLF_ACTIVATE)  # 0409 = English (US)
            if not hkl:
                return
            hwnd = user32.GetForegroundWindow()
            WM_INPUTLANGCHANGEREQUEST = 0x0050
            user32.PostMessageW(hwnd, WM_INPUTLANGCHANGEREQUEST, 0, hkl)
        except Exception:
            pass  # ไม่ใช่ Windows หรือเรียกไม่สำเร็จ ข้ามไปได้ ไม่กระทบการทำงานหลัก

    def type_text(self, text, config):
        if config.get("force_english_layout", True):
            self.force_english_keyboard_layout()
            time.sleep(0.05)  # ให้เวลาสลับภาษาก่อนพิมพ์/วางจริง

        paste_method = config.get("paste_method", True)
        restore_clipboard = config.get("restore_clipboard", True)
        if paste_method:
            old_clip = None
            if restore_clipboard:
                try:
                    old_clip = pyperclip.paste()
                except Exception:
                    pass
            pyperclip.copy(str(text))
            time.sleep(0.1)  # ให้เวลาคลิปบอร์ดอัปเดตก่อนกด paste
            pyautogui.hotkey("ctrl", "v")
            # รอให้นานพอที่โปรแกรมเป้าหมายจะอ่านคลิปบอร์ดเสร็จจริงๆ ก่อนคืนค่าเดิม
            # (0.05 วิเดิมสั้นเกินไป — ถ้าโปรแกรมเป้าหมายช้ากว่านี้ จะโดนคืนค่าทับ
            # ก่อนอ่านทัน กลายเป็นวางข้อมูลผิด/ไม่วางให้แบบเงียบๆ เป็นครั้งคราว)
            time.sleep(0.35)
            if old_clip is not None:
                try:
                    pyperclip.copy(old_clip)
                except Exception:
                    pass
        else:
            pyautogui.typewrite(str(text), interval=0.05)

    def wait_for_ocr_match(self, config, timeout, keywords=None):
        rules = config.get("ocr_rules", [])
        if keywords:
            rules = [r for r in rules if r.get("keyword") in keywords]
        region = config.get("ocr_region")
        lang = config.get("ocr_lang", "tha+eng")
        tesseract_path = config.get("tesseract_path", "")
        if not rules:
            self.log("  (ไม่มีคำที่ตรงเงื่อนไขในโปรไฟล์ OCR ข้ามการตรวจจับ)")
            return None
        start = time.time()
        attempt = 0
        while time.time() - start < timeout:
            if self.stop_event.is_set():
                return None
            attempt += 1
            remaining = max(0, timeout - (time.time() - start))
            self.log(f"  ⏳ ตรวจครั้งที่ {attempt} (เหลือเวลา ~{remaining:.0f} วิ)...")
            try:
                per_call_timeout = max(2, min(8, remaining))
                text = ocr_capture_text(region, lang, tesseract_path, ocr_timeout=per_call_timeout)
            except Exception as e:
                self.log(f"  ⚠️ OCR อ่านหน้าจอไม่สำเร็จรอบนี้: {e} (ลองรอบถัดไป)")
                time.sleep(0.5)
                continue
            for rule in rules:
                kw = rule.get("keyword", "")
                if kw and kw in text:
                    return rule
            time.sleep(1.0)
        return None

    def detect_input_error(self, config):
        keywords_by_type = (
            ("cancel", config.get("cancel_keywords", [])),
            ("duplicate", config.get("duplicate_keywords", [])),
        )
        all_keywords = [
            (kind, keyword)
            for kind, keywords in keywords_by_type
            for keyword in keywords
            if keyword
        ]
        if not all_keywords or not config.get("ocr_region"):
            return None
        try:
            text = ocr_capture_text(
                config["ocr_region"],
                config.get("ocr_lang", "tha+eng"),
                config.get("tesseract_path", ""),
                ocr_timeout=3,
            )
        except Exception as e:
            self.log(f"  ⚠️ ตรวจข้อความแจ้งเตือนไม่สำเร็จ: {e}")
            return None
        for kind, keyword in all_keywords:
            if keyword.lower() in text.lower():
                return kind, keyword
        return None

    def wait_for_retry(self, kind, keyword):
        self.stats[kind] += 1
        self.root.after(0, self._update_stats_label)
        self.resume_event.clear()
        self.root.after(0, lambda: self.resume_btn.config(state="normal"))
        self.log(
            f"⏸ พบข้อความ '{keyword}' ({kind}) ระบบหยุดรอ — "
            "แก้ไขหน้าจอปลายทางแล้วกด 'ดำเนินการต่อ' เพื่อกรอกซ้ำ"
        )
        while not self.resume_event.is_set():
            if self.stop_event.is_set():
                return False
            time.sleep(0.2)
        self.root.after(0, lambda: self.resume_btn.config(state="disabled"))
        self.log("▶ ดำเนินการต่อและกรอกข้อมูลเดิมซ้ำ")
        return True

    def execute_rule_action(self, rule, config, dry_run):
        action = rule.get("action")
        if action == "TYPE_WEIGHT":
            w = config.get("default_weight", "0.49")
            self.log(f"  พิมพ์น้ำหนัก: {w}")
            if not dry_run:
                self.type_text(w, config)
        elif action == "KEY":
            self.log(f"  กดคีย์: {rule.get('value', 'enter')}")
            if not dry_run:
                pyautogui.press(rule.get("value", "enter"))
        elif action == "CLICK":
            self.log(f"  คลิก: ({rule.get('x')}, {rule.get('y')})")
            if not dry_run:
                pyautogui.click(rule.get("x"), rule.get("y"))
        elif action == "PAUSE_WAIT_USER":
            self.log(
                "  ⏸ พบเงื่อนไขให้หยุดรอ — กรุณาจัดการเองที่หน้าจอ "
                "แล้วกดปุ่ม '▶ ดำเนินการต่อ (หลังหยุดรอ)' ในโปรแกรมนี้เพื่อไปต่อ"
            )
            self.resume_event.clear()
            self.root.after(0, lambda: self.resume_btn.config(state="normal"))
            while not self.resume_event.is_set():
                if self.stop_event.is_set():
                    return
                time.sleep(0.2)
            self.root.after(0, lambda: self.resume_btn.config(state="disabled"))
            self.log("  ▶ ดำเนินการต่อแล้ว")

    def run_automation(self, config, codes, dry_run, total_count=None, start_index=1):
        try:
            total_count = total_count or len(codes)
            if start_index > 1:
                self.log(
                    f"เริ่มจากรายการที่ {start_index} จากทั้งหมด {total_count} รายการ "
                    f"(เหลือที่จะทำ {len(codes)} รายการ)"
                )
            else:
                self.log(f"เจอบาร์โค้ดทั้งหมด {total_count} รายการ")
            delay = int(config.get("start_delay", 5) or 5)
            for i in range(delay, 0, -1):
                if self.stop_event.is_set():
                    self.log("ยกเลิกก่อนเริ่ม")
                    return
                self.log(f"เริ่มใน {i} วินาที... สลับไปโฟกัสโปรแกรมเป้าหมายตอนนี้")
                time.sleep(1)

            title = config.get("target_window_title", "").strip()
            if title and not dry_run:
                wins = gw.getWindowsWithTitle(title)
                if wins:
                    win = wins[0]
                    try:
                        win.activate()
                        time.sleep(0.3)
                    except Exception as e:
                        self.log(f"เตือน: โฟกัสหน้าต่างไม่สำเร็จ ({e}) กรุณาคลิกโฟกัสเอง")
                    # Windows มักบล็อกการ activate() แบบเงียบๆ ไม่ error แต่โฟกัสไม่ติดจริง
                    # เสริมด้วยการคลิกเมาส์จริงที่แถบหัวหน้าต่าง (Windows ไม่บล็อกการคลิกจริง)
                    try:
                        click_x = win.left + max(20, win.width // 2)
                        click_y = win.top + 10
                        pyautogui.click(click_x, click_y)
                        time.sleep(0.3)
                    except Exception:
                        pass
                else:
                    self.log(f"เตือน: ไม่พบหน้าต่างชื่อ '{title}' กรุณาคลิกโฟกัสโปรแกรมเป้าหมายเอง")

            for offset, code in enumerate(codes):
                idx = start_index + offset  # ลำดับจริงเทียบกับไฟล์ทั้งหมด ไม่ใช่แค่ในชุดที่เหลือ
                retries = 0
                while True:
                    if self.stop_event.is_set():
                        self.log("หยุดโดยผู้ใช้")
                        return
                    self.log(f"[{idx}/{total_count}] บาร์โค้ด: {code}" + (f" (ครั้งที่ {retries + 1})" if retries else ""))
                    for step in config["sequence"]:
                        if self.stop_event.is_set():
                            return
                        stype = step["type"]
                        if stype == "TYPE_BARCODE":
                            self.log(f"  พิมพ์: {code}")
                            if not dry_run:
                                self.type_text(code, config)
                        elif stype == "TYPE_WEIGHT":
                            w = config.get("default_weight", "0.49")
                            self.log(f"  พิมพ์น้ำหนัก: {w}")
                            if not dry_run:
                                self.type_text(w, config)
                        elif stype == "KEY":
                            self.log(f"  กดคีย์: {step['value']}")
                            if not dry_run:
                                pyautogui.press(step["value"])
                        elif stype == "WAIT":
                            time.sleep(float(step["value"]))
                        elif stype == "CLICK":
                            self.log(f"  คลิก: ({step['x']}, {step['y']})")
                            if not dry_run:
                                pyautogui.click(step["x"], step["y"])
                        elif stype == "WAIT_FOR_TEXT":
                            timeout = float(step.get("timeout", 10))
                            step_keywords = step.get("keywords") or None
                            kw_note = f" (เฉพาะคำ: {', '.join(step_keywords)})" if step_keywords else ""
                            self.log(f"  รอข้อความจากหน้าจอ (OCR) สูงสุด {timeout:.0f} วิ...{kw_note}")
                            matched = self.wait_for_ocr_match(config, timeout, step_keywords)
                            if matched is None:
                                self.log("  ไม่พบข้อความที่ตรงเงื่อนไข ข้ามไปขั้นตอนถัดไป")
                                self.log_fail(f"รายการที่ {idx} ({code}) — ไม่ตรงตามเงื่อนไข (OCR หาไม่เจอ)")
                                if offset + 1 < len(codes):
                                    next_idx = idx + 1
                                    next_code = codes[offset + 1]
                                    self.log_fail(
                                        f"รายการที่ {next_idx} ({next_code}) — ถัดจากรายการที่ไม่ตรงเงื่อนไข (เก็บไว้ตรวจสอบ)"
                                    )
                            else:
                                self.log(f"  พบคำว่า '{matched.get('keyword')}' -> ดำเนินการ: {matched.get('action')}")
                                self.execute_rule_action(matched, config, dry_run)

                    time.sleep(0.3)
                    error = None if dry_run else self.detect_input_error(config)
                    if error:
                        kind, keyword = error
                        retry_limit = max(0, int(config.get("retry_limit", 1) or 0))
                        if retries >= retry_limit:
                            self.log(f"❌ พบข้อผิดพลาดซ้ำเกินจำนวนที่กำหนด ({retry_limit}) หยุดการทำงาน")
                            return
                        retries += 1
                        if not self.wait_for_retry(kind, keyword):
                            return
                        continue
                    self.stats["completed"] += 1
                    self.root.after(0, self._update_stats_label)
                    break

                batch_size = int(config.get("batch_size", 0) or 0)
                if batch_size > 0 and idx % batch_size == 0 and idx != total_count:
                    self.log(
                        f"⏸ ครบ {batch_size} รอบแล้ว หยุดพักกันระบบเป้าหมายขัดข้อง — "
                        "เตรียม/รีสตาร์ทโปรแกรมเป้าหมายให้พร้อม แล้วกด '▶ ดำเนินการต่อ (หลังหยุดรอ)'"
                    )
                    self.resume_event.clear()
                    self.root.after(0, lambda: self.resume_btn.config(state="normal"))
                    while not self.resume_event.is_set():
                        if self.stop_event.is_set():
                            return
                        time.sleep(0.2)
                    self.root.after(0, lambda: self.resume_btn.config(state="disabled"))
                    self.log("▶ ดำเนินการต่อแล้ว")
            self.log("✅ เสร็จสิ้นทุกรายการ")
        except pyautogui.FailSafeException:
            self.log("🛑 หยุดฉุกเฉิน (เมาส์ชนมุมจอ)")
        except Exception as e:
            self.log(f"❌ เกิดข้อผิดพลาด: {e}")


if __name__ == "__main__":
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # แก้พิกัดจอเพี้ยนจาก Windows DPI Scaling
    except Exception:
        pass  # ไม่ใช่ Windows หรือเวอร์ชันเก่า ข้ามไปได้ ไม่กระทบการทำงาน
    root = TkinterDnD.Tk() if DND_AVAILABLE else tk.Tk()
    app = AutoReceiveApp(root)
    root.mainloop()
