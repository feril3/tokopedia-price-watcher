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

# **User-Agent Desktop Modern + Tambahkan Header Tambahan**
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
HEADERS = {
    "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://www.tokopedia.com/"
}

# **Konfigurasi Browser untuk Hindari HTTP/2 Issues**
BROWSER_ARGS = [
    "--disable-http2",  # Nonaktifkan HTTP/2
    "--disable-blink-features=AutomationControlled",
    "--no-sandbox",
    "--disable-dev-shm-usage"
]

# **Batas jumlah request berjalan bersamaan**
semaphore = asyncio.Semaphore(3)  # Maksimum 3 request berjalan bersamaan

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
            await page.goto(url, timeout=120000, wait_until="domcontentloaded")  # Timeout 120 detik
            await page.wait_for_selector("h1", timeout=20000)  # Tunggu elemen muncul (maks 20 detik)

            # **Handle popup/overlay jika ada**
            try:
                await page.click("button[aria-label='tutup']", timeout=3000)
            except:
                pass

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
    async with async_playwright() as p:
        # **Gunakan Chromium sebagai browser**
        browser = await p.chromium.launch(
            headless=True,
            args=BROWSER_ARGS,
            chromium_sandbox=False
        )
        
        # **Konfigurasi context dengan user-agent dan viewport**
        context = await browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1920, "height": 1080},
            bypass_csp=True
        )
        
        # **Aktifkan cache untuk mengurangi request**
        await context.route("**/*", lambda route: route.continue_())
        
        try:
            tasks = [scrape_tokopedia(context, url) for url in urls]
            return await asyncio.gather(*tasks, return_exceptions=True)
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