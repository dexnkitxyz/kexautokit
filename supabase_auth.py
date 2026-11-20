import ctypes
import json
import os
import threading
import time
import tkinter as tk
from ctypes import wintypes
from tkinter import messagebox, simpledialog, ttk
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


LOCAL_APP_DATA = os.environ.get("LOCALAPPDATA") or os.path.join(
    os.path.expanduser("~"), "AppData", "Local"
)
AUTH_CONFIG_FILE = os.path.join(LOCAL_APP_DATA, "KexAuto", "supabase_config.json")
AUTH_SESSION_FILE = os.path.join(LOCAL_APP_DATA, "KexAuto", "supabase_session.bin")
DEFAULT_SUPABASE_URL = "https://somyunbwhmxgtiytsujj.supabase.co"
DEFAULT_SUPABASE_PUBLISHABLE_KEY = "sb_publishable_8PKER-1tBglYMg87OlJXsQ_1GqC1kX9"


class SupabaseAuthError(Exception):
    def __init__(self, message, authentication_failure=False):
        super().__init__(message)
        self.authentication_failure = authentication_failure


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
    ]


def _protect_windows_data(data, decrypt=False):
    if os.name != "nt":
        raise SupabaseAuthError("การบันทึก session แบบปลอดภัยรองรับบน Windows เท่านั้น")
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
    kernel32.LocalFree.restype = wintypes.HLOCAL
    source_buffer = ctypes.create_string_buffer(data)
    source = _DataBlob(
        len(data),
        ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_ubyte)),
    )
    destination = _DataBlob()
    if decrypt:
        operation = crypt32.CryptUnprotectData
        operation.argtypes = [
            ctypes.POINTER(_DataBlob),
            ctypes.POINTER(wintypes.LPWSTR),
            ctypes.POINTER(_DataBlob),
            wintypes.LPVOID,
            wintypes.LPVOID,
            wintypes.DWORD,
            ctypes.POINTER(_DataBlob),
        ]
        operation.restype = wintypes.BOOL
        succeeded = operation(
            ctypes.byref(source),
            None,
            None,
            None,
            None,
            0,
            ctypes.byref(destination),
        )
    else:
        operation = crypt32.CryptProtectData
        operation.argtypes = [
            ctypes.POINTER(_DataBlob),
            wintypes.LPCWSTR,
            ctypes.POINTER(_DataBlob),
            wintypes.LPVOID,
            wintypes.LPVOID,
            wintypes.DWORD,
            ctypes.POINTER(_DataBlob),
        ]
        operation.restype = wintypes.BOOL
        succeeded = operation(
            ctypes.byref(source),
            "KexAuto Supabase session",
            None,
            None,
            None,
            0,
            ctypes.byref(destination),
        )
    if not succeeded:
        raise SupabaseAuthError(
            f"Windows ไม่สามารถจัดการข้อมูลเข้าสู่ระบบได้ (รหัส {ctypes.get_last_error()})",
            authentication_failure=decrypt,
        )
    try:
        return ctypes.string_at(destination.pbData, destination.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(destination.pbData, wintypes.HLOCAL))


class SupabaseClient:
    def __init__(self, url, anon_key):
        if not isinstance(url, str) or not isinstance(anon_key, str):
            raise SupabaseAuthError("รูปแบบการตั้งค่า Supabase ไม่ถูกต้อง")
        self.url = url.strip().rstrip("/")
        self.anon_key = anon_key.strip()
        parsed_url = urlparse(self.url)
        if parsed_url.scheme != "https" or not parsed_url.netloc:
            raise SupabaseAuthError("URL ของ Supabase ต้องขึ้นต้นด้วย https://")
        if not self.anon_key:
            raise SupabaseAuthError("กรุณาระบุ Supabase anon/publishable key")
        self.access_token = None
        self.refresh_token = None
        self.expires_at = 0
        self.user = None

    @classmethod
    def from_config(cls):
        config = {}
        try:
            with open(AUTH_CONFIG_FILE, "r", encoding="utf-8") as config_file:
                config = json.load(config_file)
        except FileNotFoundError:
            config = {}
        except (OSError, json.JSONDecodeError) as error:
            raise SupabaseAuthError(f"อ่านไฟล์ตั้งค่า Supabase ไม่สำเร็จ: {error}") from error
        if not isinstance(config, dict):
            raise SupabaseAuthError("รูปแบบไฟล์ตั้งค่า Supabase ไม่ถูกต้อง")
        return cls(
            config.get("url") or DEFAULT_SUPABASE_URL,
            config.get("anon_key") or DEFAULT_SUPABASE_PUBLISHABLE_KEY,
        )

    def _request(self, method, path, body=None, token=None):
        headers = {"apikey": self.anon_key}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode("utf-8")
        request = Request(self.url + path, data=data, headers=headers, method=method)
        try:
            with urlopen(request, timeout=15) as response:
                raw_response = response.read()
        except HTTPError as error:
            raw_response = error.read()
            try:
                payload = json.loads(raw_response.decode("utf-8")) if raw_response else {}
            except json.JSONDecodeError:
                payload = {}
            if not isinstance(payload, dict):
                payload = {}
            detail = (
                payload.get("msg")
                or payload.get("message")
                or payload.get("error_description")
                or payload.get("error")
                or f"HTTP {error.code}"
            )
            authentication_failure = error.code in (400, 401, 403, 404) and (
                path.startswith("/auth/v1/") or path.startswith("/functions/v1/")
            )
            raise SupabaseAuthError(
                str(detail), authentication_failure=authentication_failure
            ) from error
        except (URLError, TimeoutError, OSError) as error:
            raise SupabaseAuthError(f"เชื่อมต่อ Supabase ไม่สำเร็จ: {error}") from error
        if not raw_response:
            return {}
        try:
            return json.loads(raw_response.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise SupabaseAuthError("Supabase ส่งข้อมูลตอบกลับที่อ่านไม่ได้") from error

    def _save_session(self, session):
        if not isinstance(session, dict):
            raise SupabaseAuthError("Supabase ส่งข้อมูล session กลับมาไม่ถูกต้อง")
        access_token = session.get("access_token")
        refresh_token = session.get("refresh_token")
        user = session.get("user")
        if not access_token or not refresh_token or not isinstance(user, dict):
            raise SupabaseAuthError("Supabase ไม่ได้ส่งข้อมูล session กลับมา")
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.expires_at = time.time() + int(session.get("expires_in", 3600))
        self.user = user
        self._persist_refresh_token()

    def _persist_refresh_token(self):
        if not self.refresh_token:
            raise SupabaseAuthError("ไม่พบ refresh token สำหรับบันทึก session")
        try:
            os.makedirs(os.path.dirname(AUTH_SESSION_FILE), exist_ok=True)
            encrypted = _protect_windows_data(self.refresh_token.encode("utf-8"))
            with open(AUTH_SESSION_FILE, "wb") as session_file:
                session_file.write(encrypted)
        except OSError as error:
            raise SupabaseAuthError(f"บันทึก session ไม่สำเร็จ: {error}") from error

    @staticmethod
    def clear_saved_session():
        try:
            os.remove(AUTH_SESSION_FILE)
        except FileNotFoundError:
            pass
        except OSError as error:
            raise SupabaseAuthError(f"ลบ session ที่บันทึกไว้ไม่สำเร็จ: {error}") from error

    def restore_saved_session(self):
        try:
            with open(AUTH_SESSION_FILE, "rb") as session_file:
                encrypted = session_file.read()
        except FileNotFoundError as error:
            raise SupabaseAuthError("ไม่พบ session ที่บันทึกไว้") from error
        except OSError as error:
            raise SupabaseAuthError(f"อ่าน session ที่บันทึกไว้ไม่สำเร็จ: {error}") from error
        try:
            refresh_token = _protect_windows_data(encrypted, decrypt=True).decode("utf-8")
        except UnicodeDecodeError as error:
            raise SupabaseAuthError(
                "ข้อมูล session ที่บันทึกไว้ไม่ถูกต้อง", authentication_failure=True
            ) from error
        if not refresh_token:
            raise SupabaseAuthError(
                "ไม่พบ refresh token ใน session ที่บันทึกไว้",
                authentication_failure=True,
            )
        self.refresh_token = refresh_token
        self._refresh_session()
        return self.verify_session()

    def sign_in(self, email, password):
        session = self._request(
            "POST",
            "/auth/v1/token?grant_type=password",
            {"email": email, "password": password},
        )
        self._save_session(session)
        return self.user

    def _refresh_session(self):
        session = self._request(
            "POST",
            "/auth/v1/token?grant_type=refresh_token",
            {"refresh_token": self.refresh_token},
        )
        self._save_session(session)

    def verify_session(self):
        if not self.access_token or not self.refresh_token:
            raise SupabaseAuthError("ไม่พบ session กรุณาเข้าสู่ระบบใหม่")
        if self.expires_at - time.time() < 60:
            self._refresh_session()
        user = self._request("GET", "/auth/v1/user", token=self.access_token)
        if not isinstance(user, dict) or user.get("id") != self.user.get("id"):
            raise SupabaseAuthError("บัญชีนี้ถูกเพิกถอนแล้ว กรุณาติดต่อผู้ดูแล")
        self.user = user
        return user

    def _manage_users(self, action, **data):
        return self._request(
            "POST",
            "/functions/v1/manage-users",
            {"action": action, **data},
            token=self.access_token,
        )

    def is_admin(self):
        result = self._manage_users("status")
        return isinstance(result, dict) and result.get("is_admin") is True

    def list_users(self):
        result = self._manage_users("list")
        users = result.get("users")
        if not isinstance(users, list):
            raise SupabaseAuthError("รูปแบบรายชื่อผู้ใช้จากเซิร์ฟเวอร์ไม่ถูกต้อง")
        return users

    def create_user(self, email, password):
        return self._manage_users("create", email=email, password=password)

    def delete_user(self, user_id):
        return self._manage_users("delete", user_id=user_id)


class LoginWindow:
    def __init__(self, root, on_login):
        self.root = root
        self.on_login = on_login
        self.root.title("KexAuto - เข้าสู่ระบบ")
        self.root.geometry("420x360")
        self.root.resizable(False, False)
        self._auth_in_progress = False

        frame = ttk.Frame(root, padding=24)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="เข้าสู่ระบบ KexAuto", font=("", 16, "bold")).pack(pady=(4, 18))
        ttk.Label(frame, text="อีเมล").pack(anchor="w")
        self.email_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self.email_var).pack(fill="x", pady=(3, 10))
        ttk.Label(frame, text="รหัสผ่าน").pack(anchor="w")
        self.password_var = tk.StringVar()
        self.password_entry = ttk.Entry(frame, textvariable=self.password_var, show="*")
        self.password_entry.pack(fill="x", pady=(3, 12))
        self.status_var = tk.StringVar()
        ttk.Label(frame, textvariable=self.status_var, foreground="#b42318", wraplength=360).pack(
            fill="x", pady=(0, 8)
        )
        buttons = ttk.Frame(frame)
        buttons.pack(fill="x")
        self.login_button = ttk.Button(buttons, text="เข้าสู่ระบบ", command=self._submit)
        self.login_button.pack(side="left", fill="x", expand=True, padx=(0, 5))
        ttk.Button(buttons, text="ตั้งค่า Supabase", command=self._configure).pack(
            side="left", fill="x", expand=True, padx=(5, 0)
        )
        self.password_entry.bind("<Return>", lambda _event: self._submit())
        self.retry_button = ttk.Button(
            frame, text="ลองเชื่อมต่อใหม่", command=self._restore_saved_session
        )
        self.root.after(100, self._restore_saved_session)

    def _configure(self):
        window = tk.Toplevel(self.root)
        window.title("ตั้งค่า Supabase")
        window.geometry("520x280")
        window.transient(self.root)
        frame = ttk.Frame(window, padding=16)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Project URL").pack(anchor="w")
        url_var = tk.StringVar(value=DEFAULT_SUPABASE_URL)
        key_var = tk.StringVar(value=DEFAULT_SUPABASE_PUBLISHABLE_KEY)
        try:
            with open(AUTH_CONFIG_FILE, "r", encoding="utf-8") as config_file:
                saved_config = json.load(config_file)
            if not isinstance(saved_config, dict):
                raise SupabaseAuthError("รูปแบบไฟล์ตั้งค่า Supabase ไม่ถูกต้อง")
            url_var.set(saved_config.get("url") or DEFAULT_SUPABASE_URL)
            key_var.set(saved_config.get("anon_key") or DEFAULT_SUPABASE_PUBLISHABLE_KEY)
        except FileNotFoundError:
            pass
        except (OSError, json.JSONDecodeError, SupabaseAuthError) as error:
            messagebox.showerror("อ่านการตั้งค่าไม่สำเร็จ", str(error), parent=window)
        ttk.Entry(frame, textvariable=url_var).pack(fill="x", pady=(3, 10))
        ttk.Label(frame, text="anon / publishable key (ห้ามใช้ service_role key)").pack(anchor="w")
        ttk.Entry(frame, textvariable=key_var).pack(fill="x", pady=(3, 12))
        ttk.Label(
            frame,
            text=f"บันทึกไว้ที่ {AUTH_CONFIG_FILE}",
            wraplength=480,
        ).pack(anchor="w", pady=(0, 10))

        def save_config():
            try:
                client = SupabaseClient(url_var.get(), key_var.get())
                os.makedirs(os.path.dirname(AUTH_CONFIG_FILE), exist_ok=True)
                with open(AUTH_CONFIG_FILE, "w", encoding="utf-8") as config_file:
                    json.dump(
                        {"url": client.url, "anon_key": client.anon_key},
                        config_file,
                        ensure_ascii=False,
                        indent=2,
                    )
            except (OSError, SupabaseAuthError) as error:
                messagebox.showerror("ตั้งค่าไม่สำเร็จ", str(error), parent=window)
                return
            messagebox.showinfo("ตั้งค่าสำเร็จ", "บันทึกการตั้งค่า Supabase แล้ว", parent=window)
            window.destroy()

        ttk.Button(frame, text="บันทึก", command=save_config).pack(anchor="e")

    def _restore_saved_session(self):
        if self._auth_in_progress:
            return
        if not os.path.isfile(AUTH_SESSION_FILE):
            self.status_var.set("ตั้งค่า Supabase แล้วเข้าสู่ระบบ ระบบจะจำการเข้าสู่ระบบไว้ในเครื่องนี้")
            self.retry_button.pack_forget()
            self.root.deiconify()
            return
        self._auth_in_progress = True
        self.login_button.configure(state="disabled")
        self.status_var.set("กำลังตรวจสอบ session ที่บันทึกไว้อย่างปลอดภัย...")

        def restore():
            try:
                client = SupabaseClient.from_config()
                user = client.restore_saved_session()
                is_admin = client.is_admin()
                self.root.after(0, lambda: self.on_login(client, user, is_admin))
            except Exception as error:
                self.root.after(0, lambda error=error: self._restore_failed(error))

        threading.Thread(target=restore, daemon=True).start()

    def _restore_failed(self, error):
        self._auth_in_progress = False
        self.login_button.configure(state="normal")
        self.root.deiconify()
        if isinstance(error, SupabaseAuthError) and error.authentication_failure:
            try:
                SupabaseClient.clear_saved_session()
            except SupabaseAuthError as clear_error:
                self.status_var.set(f"{error}\n{clear_error}")
                self.retry_button.pack(pady=(8, 0))
                return
            self.status_var.set(f"ต้องเข้าสู่ระบบใหม่: {error}")
            self.retry_button.pack_forget()
            return
        self.status_var.set(f"ตรวจสอบ session ไม่สำเร็จ: {error}")
        self.retry_button.pack(pady=(8, 0))

    def _submit(self):
        if self._auth_in_progress:
            return
        email = self.email_var.get().strip()
        password = self.password_var.get()
        if not email or not password:
            self.status_var.set("กรุณากรอกอีเมลและรหัสผ่าน")
            return
        self.login_button.configure(state="disabled")
        self._auth_in_progress = True
        self.retry_button.pack_forget()
        self.status_var.set("กำลังตรวจสอบบัญชี...")

        def authenticate():
            try:
                client = SupabaseClient.from_config()
                user = client.sign_in(email, password)
                is_admin = client.is_admin()
                self.root.after(0, lambda: self.on_login(client, user, is_admin))
            except Exception as error:
                self.root.after(0, lambda error=error: self._login_failed(error))

        threading.Thread(target=authenticate, daemon=True).start()

    def _login_failed(self, error):
        self._auth_in_progress = False
        self.login_button.configure(state="normal")
        self.status_var.set(str(error))


class UserManagementWindow:
    def __init__(self, parent, client):
        self.client = client
        self.window = tk.Toplevel(parent)
        self.window.title("จัดการผู้ใช้")
        self.window.geometry("760x420")
        self.window.transient(parent)

        toolbar = ttk.Frame(self.window, padding=8)
        toolbar.pack(fill="x")
        ttk.Button(toolbar, text="เพิ่มผู้ใช้", command=self._create_user).pack(side="left", padx=3)
        ttk.Button(toolbar, text="ลบผู้ใช้ที่เลือก", command=self._delete_user).pack(side="left", padx=3)
        ttk.Button(toolbar, text="รีเฟรช", command=self._load_users).pack(side="right", padx=3)
        self.status_var = tk.StringVar()
        ttk.Label(self.window, textvariable=self.status_var).pack(fill="x", padx=12)

        columns = ("email", "created_at", "last_sign_in_at")
        self.users_tree = ttk.Treeview(self.window, columns=columns, show="headings")
        self.users_tree.heading("email", text="อีเมล")
        self.users_tree.heading("created_at", text="วันที่สร้าง")
        self.users_tree.heading("last_sign_in_at", text="เข้าสู่ระบบล่าสุด")
        self.users_tree.column("email", width=290)
        self.users_tree.column("created_at", width=200)
        self.users_tree.column("last_sign_in_at", width=200)
        self.users_tree.pack(fill="both", expand=True, padx=12, pady=8)
        self._load_users()

    def _load_users(self):
        self.status_var.set("กำลังโหลดรายชื่อผู้ใช้...")
        try:
            users = self.client.list_users()
        except SupabaseAuthError as error:
            self.status_var.set("")
            messagebox.showerror("โหลดรายชื่อไม่สำเร็จ", str(error), parent=self.window)
            return
        for item in self.users_tree.get_children():
            self.users_tree.delete(item)
        for user in users:
            self.users_tree.insert(
                "",
                "end",
                iid=user["id"],
                values=(
                    user.get("email", ""),
                    user.get("created_at", ""),
                    user.get("last_sign_in_at", "") or "-",
                ),
            )
        self.status_var.set(f"ผู้ใช้ทั้งหมด {len(users)} บัญชี")

    def _create_user(self):
        email = simpledialog.askstring("เพิ่มผู้ใช้", "อีเมลผู้ใช้:", parent=self.window)
        if email is None:
            return
        password = simpledialog.askstring(
            "เพิ่มผู้ใช้", "กำหนดรหัสผ่าน (อย่างน้อย 8 ตัวอักษร):", show="*", parent=self.window
        )
        if password is None:
            return
        try:
            self.client.create_user(email.strip(), password)
        except SupabaseAuthError as error:
            messagebox.showerror("เพิ่มผู้ใช้ไม่สำเร็จ", str(error), parent=self.window)
            return
        messagebox.showinfo("เพิ่มผู้ใช้สำเร็จ", f"เพิ่มบัญชี {email.strip()} แล้ว", parent=self.window)
        self._load_users()

    def _delete_user(self):
        selection = self.users_tree.selection()
        if not selection:
            messagebox.showwarning("ยังไม่ได้เลือกผู้ใช้", "กรุณาเลือกบัญชีที่ต้องการลบ", parent=self.window)
            return
        user_id = selection[0]
        email = self.users_tree.item(user_id, "values")[0]
        if not messagebox.askyesno(
            "ยืนยันการลบผู้ใช้",
            f"ต้องการลบบัญชี {email} หรือไม่?\nผู้ใช้นี้จะเข้าสู่ระบบไม่ได้อีก",
            parent=self.window,
        ):
            return
        try:
            self.client.delete_user(user_id)
        except SupabaseAuthError as error:
            messagebox.showerror("ลบผู้ใช้ไม่สำเร็จ", str(error), parent=self.window)
            return
        self._load_users()
