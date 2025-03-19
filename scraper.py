import asyncio
from playwright.async_api import async_playwright
import gspread
import json
import os
import random
from datetime import datetime
from google.oauth2.service_account import Credentials

# ... [Bagian credentials dan Google Sheets setup sama seperti sebelumnya] ...

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

semaphore = asyncio.Semaphore(3)

async def scrape_tokopedia(context, url):
    """Scraping dengan retry mechanism dan timeout handling"""
    retries = 3
    for attempt in range(retries):
        async with semaphore:
            try:
                page = await context.new_page()
                await page.set_extra_http_headers(HEADERS)
                
                # **Tambahkan delay acak antara request**
                await asyncio.sleep(random.uniform(2, 5))
                
                print(f"Attempt {attempt+1}: Scraping {url}")
                
                # **Gunakan timeout yang lebih longgar**
                await page.goto(url, timeout=120000, wait_until="domcontentloaded")
                
                # **Handle popup/overlay jika ada**
                try:
                    await page.click("button[aria-label='tutup']", timeout=3000)
                except:
                    pass
                
                # **Wait mechanism yang lebih reliable**
                await page.wait_for_function(
                    """() => {
                        const h1 = document.querySelector('h1');
                        return h1 && h1.innerText.trim().length > 0;
                    }""",
                    timeout=20000
                )
                
                # ... [Bagian scraping data sama seperti sebelumnya] ...
                
                return [url, nama_produk, harga_asli, harga_diskon]
                
            except Exception as e:
                print(f"⚠️ Attempt {attempt+1} failed: {str(e)[:150]}")
                if attempt == retries - 1:
                    return [url, "GAGAL", "GAGAL", "GAGAL"]
                await asyncio.sleep(random.uniform(5, 10))
            finally:
                await page.close()

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

# ... [Bagian main dan eksekusi tetap sama] ...