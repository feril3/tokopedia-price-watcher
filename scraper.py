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

# **List User-Agent buat mobile mode**
mobile_user_agents = [
    "Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/537.36 (KHTML, like Gecko) Version/15.0 Mobile/15E148 Safari/537.36",
    "Mozilla/5.0 (Linux; Android 10; SM-G975F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/89.0.4389.72 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 9; Pixel 3) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Mobile Safari/537.36"
]

# **Batas jumlah request berjalan bersamaan**
semaphore = asyncio.Semaphore(2)  # Maksimum 2 request berjalan bersamaan

async def scrape_tokopedia(context, url):
    """Scraping 1 halaman produk dengan Playwright Async"""
    async with semaphore:  # Batasi jumlah request paralel
        page = await context.new_page()  # Buka tab baru

        try:
            print(f"🔥 Scraping: {url}")
            await page.goto(url, timeout=60000)  # Timeout 60 detik
            await page.wait_for_selector("h1", timeout=15000)  # Tunggu elemen muncul (maks 15 detik)

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
            return [url, "GAGAL", "GAGAL", "GAGAL"]

        finally:
            await page.close()  # Tutup tab setelah selesai

async def scrape_all():
    """Scraping semua produk secara paralel dengan batas maksimum request"""
    async with async_playwright() as p:
        user_agent = random.choice(mobile_user_agents)
        print(f"🕵️‍♂️ Menggunakan User-Agent: {user_agent}")

        browser = await p.webkit.launch(headless=True)  # **Jangan pakai `async with`**
        context = await browser.new_context(user_agent=user_agent)  # Buat browser context

        try:
            tasks = [scrape_tokopedia(context, url) for url in urls]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            return results
        finally:
            await context.close()
            await browser.close()

async def main():
    results = await scrape_all()
    results = [res if isinstance(res, list) else ["ERROR", "ERROR", "ERROR", "ERROR"] for res in results]
    
    # **Update ke Google Sheets lebih efisien**
    print("📌 Update data ke Google Sheets...")
    worksheet.batch_update([
        {"range": f"A2:D{len(results) + 1}", "values": results},
        {"range": "G1", "values": [["Last Updated: " + datetime.now().strftime("%A, %d %B %Y - %H:%M:%S")]]}
    ])
    
    print("✅ Data berhasil di-update!")

# **Jalankan Scraper**
asyncio.run(main())
