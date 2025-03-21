import asyncio
from playwright.async_api import async_playwright
import gspread
import json
import os
import random
import pytz
import logging
import sys
from datetime import datetime
from google.oauth2.service_account import Credentials

# **Fix Encoding untuk Emoji di Windows**
sys.stdout.reconfigure(encoding="utf-8")

# **Setup Logging ke File & Console**
LOG_FILE = "scraper.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, mode="w", encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)
log = logging.getLogger("scraper")

# **Ambil credentials dari file credentials.json atau env (GitHub Secrets)**
CREDENTIALS_PATH = "credentials.json"

if os.path.exists(CREDENTIALS_PATH):
    with open(CREDENTIALS_PATH, "r", encoding="utf-8") as file:
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

# **Daftar User-Agent Rotating**
MOBILE_USER_AGENTS = [
    "Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/537.36 (KHTML, like Gecko) Version/15.0 Mobile/15E148 Safari/537.36",
    "Mozilla/5.0 (Linux; Android 10; SM-G975F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/89.0.4389.72 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 11; Pixel 5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Mobile Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X) AppleWebKit/537.36 (KHTML, like Gecko) Version/14.0 Mobile/15E148 Safari/537.36"
]

def get_random_user_agent():
    return random.choice(MOBILE_USER_AGENTS)

# **Batas jumlah request berjalan bersamaan**
semaphore = asyncio.Semaphore(5)

async def scrape_tokopedia(context, url, retry=False):
    """Scraping 1 halaman produk dengan Playwright Async"""
    async with semaphore:
        page = await context.new_page()
        page.set_default_navigation_timeout(20000)
        
        try:
            log.info(f"🔍 Scraping{' (Retry)' if retry else ''}: {url}")
            await page.goto(url, timeout=20000)
            await page.wait_for_selector("h1", timeout=5000)
            
            # **Ambil Nama Produk**
            nama_produk = await page.inner_text("h1") if await page.query_selector("h1") else "TIDAK ADA"
            harga_diskon = await page.inner_text("h3[data-testid='pdpProductPrice']") if await page.query_selector("h3[data-testid='pdpProductPrice']") else "TIDAK ADA"
            harga_asli = await page.inner_text("span[data-testid='pdpSlashPrice']") if await page.query_selector("span[data-testid='pdpSlashPrice']") else harga_diskon
            
            log.info(f"✅ {nama_produk} | Harga: {harga_asli} → {harga_diskon}")
            return url, nama_produk, harga_asli, harga_diskon
        
        except Exception as e:
            log.warning(f"⚠️ Error scraping {url}: {e}")
            return url, "GAGAL", "GAGAL", "GAGAL"
        
        finally:
            await page.close()

async def main():
    start_time = datetime.now()
    jakarta_tz = pytz.timezone("Asia/Jakarta")
    timestamp = datetime.now(jakarta_tz).strftime("%A, %d %B %Y - %H:%M:%S")

    BATCH_SIZE = 100
    all_results = {url: ["GAGAL", "GAGAL", "GAGAL"] for url in urls}  # ⬅️ Inisialisasi biar urutan tetap

    async with async_playwright() as p:
        user_agent = get_random_user_agent()
        log.info(f"🕵️‍♂️ Menggunakan User-Agent: {user_agent}")
        browser = await p.webkit.launch(headless=True)
        context = await browser.new_context(user_agent=user_agent)

        failed_urls = []

        for i in range(0, len(urls), BATCH_SIZE):
            batch_urls = urls[i:i + BATCH_SIZE]
            log.info(f"📦 Scraping batch {i//BATCH_SIZE + 1} ({len(batch_urls)} produk)...")

            tasks = [scrape_tokopedia(context, url) for url in batch_urls]
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)

            for res in batch_results:
                if res[1] == "GAGAL":
                    failed_urls.append(res[0])
                all_results[res[0]] = list(res[1:])

            worksheet.batch_update([
                {"range": f"A2:D{len(urls) + 1}", "values": [[k] + list(v) for k, v in all_results.items()]}
            ])

        await context.close()
        await browser.close()

    # **Retry Session untuk Produk Gagal**
    if failed_urls:
        log.info(f"🔄 Retry untuk {len(failed_urls)} produk gagal...")
        async with async_playwright() as p:
            user_agent = get_random_user_agent()
            browser = await p.webkit.launch(headless=True)
            context = await browser.new_context(user_agent=user_agent)

            tasks = [scrape_tokopedia(context, url, retry=True) for url in failed_urls]
            retry_results = await asyncio.gather(*tasks, return_exceptions=True)

            for res in retry_results:
                if res[1] != "GAGAL":
                    all_results[res[0]] = list(res[1:])

            await context.close()
            await browser.close()

        worksheet.batch_update([
            {"range": f"A2:D{len(urls) + 1}", "values": [[k] + list(v) for k, v in all_results.items()]}
        ])

    # **Hitung waktu eksekusi**
    end_time = datetime.now()
    total_time = end_time - start_time
    minutes, seconds = divmod(int(total_time.total_seconds()), 60)

    # **Update ke Google Sheets**
    worksheet.update(values=[[f"Last Updated (WIB): {timestamp}"]], range_name="G1")
    worksheet.update(values=[[f"🚀 Scrape selesai dalam {minutes} menit {seconds} detik, berhasil scrape {len([v for v in all_results.values() if v[0] != 'GAGAL'])} produk dari total {len(urls)} produk ({(len([v for v in all_results.values() if v[0] != 'GAGAL']) / len(urls)) * 100:.2f}%)"]], range_name="G2")
    log.info(f"✅ Scrape selesai dalam {minutes} menit {seconds} detik!")

# **Jalankan Scraper**
asyncio.run(main())
