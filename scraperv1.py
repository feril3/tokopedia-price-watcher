import asyncio
from playwright.async_api import async_playwright
import gspread
import json
import os
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

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)

# **Koneksi ke Google Sheets**
gc = gspread.authorize(creds)
sh = gc.open("Price Watcher")
input_sheet = sh.worksheet("InputScrape")
output_sheet = sh.worksheet("OutputScrape")

# **Ambil daftar SKU & Link Kompetitor dari Google Sheet**
rows = input_sheet.get_all_values()[1:]  # Ambil data tanpa header
sku_data = []

for row in rows:
    sku = row[0]
    category, sub_category, brand, gramasi, nama_hf, harga_hf = row[1:7]
    links = [link for link in row[7:] if link.startswith("http")]
    if links:
        sku_data.append((sku, category, sub_category, brand, gramasi, nama_hf, harga_hf, links))

# **User-Agent iPhone 12 Pro (Fix biar ga berubah-ubah)**
USER_AGENT = "Mozilla/5.0 (iPhone; CPU iPhone OS 14_2 like Mac OS X) AppleWebKit/537.36 (KHTML, like Gecko) Version/14.0 Mobile/15E148 Safari/537.36"

# **Batas jumlah request berjalan bersamaan**
semaphore = asyncio.Semaphore(5)

async def scrape_tokopedia(context, sku, category, sub_category, brand, gramasi, nama_hf, harga_hf, url, retry=False):
    async with semaphore:
        page = await context.new_page()
        page.set_default_navigation_timeout(20000)
        
        try:
            log.info(f"🔍 Scraping{' (Retry)' if retry else ''}: {url}")
            await page.goto(url, timeout=20000)
            await asyncio.sleep(1)  # **Tunggu 1 detik setelah load**
            await page.evaluate("window.scrollTo(0, 600)")  # **Scroll ke bawah sedikit**
            await asyncio.sleep(1)  # **Tunggu setelah scroll**
            
            # **Cek apakah toko sedang libur**
            page_text = await page.inner_text("body")
            if "Toko sedang libur" in page_text:
                log.warning(f"⚠️ Toko sedang libur: {url}")
                return [sku, category, sub_category, brand, gramasi, nama_hf, "Toko Libur", "Toko Libur", "Toko Libur", "Toko Libur", "0", url]
            
            # **Ambil Nama Produk & Harga**
            nama_produk = await page.inner_text("h1") if await page.query_selector("h1") else "TIDAK ADA"
            harga_diskon = await page.inner_text("h3[data-testid='pdpProductPrice']") if await page.query_selector("h3[data-testid='pdpProductPrice']") else "TIDAK ADA"
            harga_asli = await page.inner_text("span[data-testid='pdpSlashPrice']") if await page.query_selector("span[data-testid='pdpSlashPrice']") else harga_diskon
            
            # **Ambil Nama Seller**
            nama_seller_selector = "#pdpShopCredContainer > div.css-ye3g0z > div.css-i6bazn > div.css-1w46beh > div > h2"
            nama_seller = await page.inner_text(nama_seller_selector) if await page.query_selector(nama_seller_selector) else "TIDAK ADA"
            
            # **Ambil Total Rating**
            total_rating_selector = "#pdp_comp-social_proof_mini > div > div > div > div:nth-child(1) > button > span > span.subtitle > u"
            total_rating = await page.inner_text(total_rating_selector) if await page.query_selector(total_rating_selector) else "0"
            
            log.info(f"✅ {nama_produk} | Harga: {harga_asli} → {harga_diskon} | Seller: {nama_seller} | Rating: {total_rating}")
            return [sku, category, sub_category, brand, gramasi, nama_hf, nama_produk, harga_asli, harga_diskon, nama_seller, total_rating, url]
        
        except Exception as e:
            log.warning(f"⚠️ Error scraping {url}: {e}")
            return [sku, category, sub_category, brand, gramasi, nama_hf, "GAGAL", "GAGAL", "GAGAL", "GAGAL", "0", url]
        
        finally:
            await page.close()

async def batch_scrape(context, tasks, batch_size=5):
    """Jalanin scraping dalam batch biar tetep paralel"""
    results = []
    for i in range(0, len(tasks), batch_size):
        batch = tasks[i:i + batch_size]
        batch_results = await asyncio.gather(*batch, return_exceptions=True)
        results.extend(batch_results)
    return results

async def main():
    all_results = []
    async with async_playwright() as p:
        log.info(f"🕵️‍♂️ Menggunakan User-Agent: {USER_AGENT}")
        
        # **Set resolusi tetap ke iPhone 12 Pro (390x844)**
        browser = await p.webkit.launch(headless=True)
        context = await browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 390, "height": 1600},  # Lebar tetap mobile, tinggi diperpanjang
            device_scale_factor=3,
            is_mobile=True
        )

        tasks = [scrape_tokopedia(context, sku, category, sub_category, brand, gramasi, nama_hf, harga_hf, url) for sku, category, sub_category, brand, gramasi, nama_hf, harga_hf, links in sku_data for url in links]
        all_results = await batch_scrape(context, tasks, batch_size=5)

        await context.close()
        await browser.close()
    
    # **Fix URL Format (Jangan pake newline)**
    for i in range(len(all_results)):
        if isinstance(all_results[i][-1], list):
            all_results[i][-1] = " | ".join(all_results[i][-1])  # Pisahkan dengan pipe (|) biar rapi di Google Sheets
    
    output_sheet.update("A1:L1", [["SKU", "Kategori", "Sub Kategori", "Brand", "Gramasi", "Nama Produk HF", "Nama Produk (Kompetitor)", "Harga Normal", "Harga Diskon", "Nama Seller", "Rating", "Link Produk"]])
    output_sheet.update(f"A2:L{len(all_results) + 1}", all_results)
    log.info("✅ Scrape selesai!")

# **Jalankan Scraper**
if __name__ == "__main__":
    asyncio.run(main())
