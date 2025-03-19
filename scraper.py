import asyncio
from playwright.async_api import async_playwright
import gspread
import json
import os
import random
from datetime import datetime
from google.oauth2.service_account import Credentials

# **Ambil credentials dari file credentials.json atau env (GitHub Secrets)**
CREDENTIALS_PATH = "credentials.json"

if os.path.exists(CREDENTIALS_PATH):
    with open(CREDENTIALS_PATH, "r") as file:
        creds_dict = json.load(file)
else:
    creds_json = os.getenv("CREDENTIALS_JSON")
    if not creds_json:
        raise ValueError("❌ ERROR: Credential tidak ditemukan!")
    creds_dict = json.loads(creds_json)

# **Tambahkan scope yang benar**
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)

# **Koneksi ke Google Sheets**
gc = gspread.authorize(creds)
sh = gc.open("Price Watcher")  # Ganti dengan nama Google Sheet lo
worksheet = sh.sheet1

# **Ambil daftar link dari Google Sheet**
urls = worksheet.col_values(1)[1:]  # Ambil link dari kolom pertama, skip header

# **Gunakan 1 User-Agent yang Stabil**
USER_AGENT = "Mozilla/5.0 (Linux; Android 10; SM-G975F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/89.0.4389.72 Mobile Safari/537.36"

# **Batas jumlah request berjalan bersamaan**
semaphore = asyncio.Semaphore(5)  # Maksimum 5 request berjalan bersamaan

async def random_delay():
    """Tambahin delay random supaya lebih manusiawi"""
    delay = random.uniform(2, 5)  # Delay lebih pendek
    print(f"⏳ Delay {delay:.2f} detik sebelum request...")
    await asyncio.sleep(delay)

async def scrape_tokopedia(context, url, retry=0):
    """Scraping 1 halaman produk dengan Playwright Async + Retry Mechanism"""
    async with semaphore:
        await random_delay()  # Tambahkan delay random sebelum request

        page = await context.new_page()  # Buka tab baru
        try:
            print(f"🔥 Scraping: {url}")
            await page.goto(url, timeout=30000)  # Timeout 30 detik
            await page.wait_for_selector("h1", timeout=10000)  # Tunggu elemen muncul (maks 10 detik)

            # **Set viewport seperti device asli**
            await page.set_viewport_size({"width": 390, "height": 844})

            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(random.uniform(1.5, 3))  # Delay pendek biar lebih natural

            # **Ambil Nama Produk**
            try:
                nama_produk = await page.inner_text("h1")
            except:
                nama_produk = "TIDAK ADA"

            # **Ambil Harga Diskon (Jika Ada)**
            try:
                harga_diskon = await page.inner_text("h3[data-testid='pdpProductPrice']")
            except:
                harga_diskon = "TIDAK ADA"

            # **Ambil Harga Sebelum Diskon**
            try:
                harga_asli = await page.inner_text("span[data-testid='pdpSlashPrice']")
            except:
                harga_asli = harga_diskon  # Kalau nggak ada harga coret, set harga asli sama dengan harga diskon

            print(f"✅ {nama_produk} | Harga: {harga_asli} → {harga_diskon}")
            return [url, nama_produk, harga_asli, harga_diskon]

        except Exception as e:
            print(f"⚠️ Error scraping {url}: {e}")
            if retry < 3:  # 🔄 Coba lagi max 3 kali kalau error
                print(f"🔄 Retry {retry + 1}/3 untuk {url}...")
                return await scrape_tokopedia(context, url, retry + 1)
            return [url, "GAGAL", "GAGAL", "GAGAL"]

        finally:
            await page.close()  # Tutup tab setelah selesai

async def scrape_all():
    """Scraping semua produk secara paralel dengan batas maksimum request"""
    async with async_playwright() as p:
        print(f"🕵️‍♂️ Menggunakan User-Agent