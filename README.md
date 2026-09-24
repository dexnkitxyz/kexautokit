# KexAuto

โปรแกรมรับสินค้าอัตโนมัติจากบาร์โค้ด/QR code ในไฟล์ PDF สำหรับ Windows

โปรแกรมสามารถอ่านบาร์โค้ดจาก PDF แล้วพิมพ์ข้อมูลลงในหน้าต่างปลายทาง โดยรองรับ
การกำหนดลำดับการทำงาน การตรวจข้อความบนหน้าจอด้วย OCR และโหมดทดสอบก่อนยิงข้อมูลจริง

## วิธีใช้งานสำหรับผู้ใช้ทั่วไป

แนะนำให้ใช้ไฟล์ `kexauto.exe` จาก GitHub Releases เพราะไม่ต้องติดตั้ง Python หรือไลบรารี

1. ดาวน์โหลด `kexauto.exe` จากหน้า Releases
2. เปิดไฟล์ แล้วเลือกไฟล์ PDF
3. ตรวจสอบหน้าต่างปลายทางและค่าการตั้งค่า
4. ทดลองด้วย **Dry run (ทดสอบ ไม่พิมพ์จริง)** ก่อน
5. เมื่อพร้อม ให้กดเริ่มทำงานจริง

โปรแกรมจะค้นหา Poppler และ Tesseract ที่ฝังมากับตัวโปรแกรมให้อัตโนมัติ
หากไม่พบ สามารถระบุพาธได้จากหน้าตั้งค่า

> โปรแกรมควบคุมเมาส์และคีย์บอร์ดจริงเมื่อทำงาน หยุดฉุกเฉินได้โดยเลื่อนเมาส์ไปมุมซ้ายบนสุด
> (0,0) หรือกดปุ่มหยุดในโปรแกรม

## วิธีรันจาก source code

ต้องใช้ Windows และ Python 3.10 ขึ้นไป

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe auto_receive.py
```

หรือเปิด `setup_and_run.bat`

## การ build เป็นไฟล์ EXE

ตรวจสอบให้มีโฟลเดอร์ `poppler` และ `tesseract` อยู่ในโปรเจกต์ก่อน build

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\build_exe.bat
```

ไฟล์ที่ได้อยู่ที่ `dist_release\kexauto.exe`

## ไฟล์ตั้งค่าและข้อมูลผู้ใช้

การตั้งค่าและ cache จะเก็บแยกต่อผู้ใช้ที่:

```text
%LOCALAPPDATA%\KexAuto\
```

จึงสามารถแจก `kexauto.exe` ให้ผู้ใช้อื่นได้โดยไม่ปะปนกับการตั้งค่าของผู้สร้าง

## การเผยแพร่เวอร์ชัน

โปรเจกต์มี GitHub Actions สำหรับสร้าง Release เมื่อ push tag รูปแบบ `v1.0.0`:

```powershell
git tag v1.0.0
git push origin v1.0.0
```

Workflow จะ build และแนบ `kexauto.exe` ใน GitHub Release ให้อัตโนมัติ
ปุ่ม **อัปเดต** ในโปรแกรมจะตรวจสอบ Release ล่าสุดและติดตั้งทับไฟล์เดิม
