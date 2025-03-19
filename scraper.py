import asyncio
from playwright.async_api import async_playwright
import gspread
import random
from datetime import datetime

# **Koneksi ke Google Sheets**
gc = gspread.service_account(filename="credentials.json")  # Pastikan file ini ada
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
semaphore = asyncio.Semaphore(5)  # Maksimum 5 request berjalan bersamaan

async def scrape_tokopedia(context, url):
    """Scraping 1 halaman produk dengan Playwright Async"""
    async with semaphore:  # Batasi jumlah request paralel
        page = await context.new_page()  # Buka tab baru

        try:
            print(f"🔥 Scraping: {url}")
            await page.goto(url, timeout=60000)  # Timeout 60 detik
            await page.wait_for_selector("h1", timeout=15000)  # Tunggu elemen muncul (maks 15 detik)

            # **Simulasi aktivitas manusia**
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
        user_agent = random.choice(mobile_user_agents)  # Pilih User-Agent random
        print(f"🕵️‍♂️ Menggunakan User-Agent: {user_agent}")

        browser = await p.webkit.launch(headless=True)  # Pakai WebKit & headless
        context = await browser.new_context(user_agent=user_agent)  # Set user-agent di Context

        try:
            tasks = [scrape_tokopedia(context, url) for url in urls]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Cek kalau ada error, kasih log
            for res in results:
                if isinstance(res, Exception):
                    print(f"⚠️ Error: {res}")

            return results

        finally:
            await context.close()
            await browser.close()

async def main():
    results = await scrape_all()

    # **Simpan ke Google Sheets**
    print("📌 Update data ke Google Sheets...")
    worksheet.update(values=results, range_name="A2")
    
    # **Tambahkan Timestamp di Cell G1**
    timestamp = datetime.now().strftime("%A, %d %B %Y - %H:%M:%S")
    worksheet.update("G1", [[f"Last Updated: {timestamp}"]])
    
    print("✅ Data berhasil di-update!")

# **Jalankan Scraper**
asyncio.run(main())
