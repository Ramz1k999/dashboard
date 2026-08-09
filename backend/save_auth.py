import asyncio
import os
from playwright.async_api import async_playwright

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(BASE_DIR, "auth_state.json")

async def create_auth_state():
    async with async_playwright() as p:
        # headless=False открывает видимое окно браузера
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()

        print("Открываем страницу авторизации...")
        await page.goto("https://mis.dmed.uz/inpatient-care")

        print("\n==================================================")
        print("1. Войдите в аккаунт через открывшееся окно браузера.")
        print("2. Дождитесь полной загрузки рабочего кабинета.")
        print("3. Вернитесь в этот терминал и нажмите ENTER.")
        print("==================================================\n")

        # Ожидаем действия в консоли после ручного входа
        input("Нажмите ENTER здесь, когда авторизуетесь на сайте...")

        # Сохраняем куки и localStorage
        await context.storage_state(path=STATE_FILE)
        print(f"\n[УСПЕХ] Сессия сохранена в файл: {STATE_FILE}")

        await browser.close()

if __name__ == "__main__":
    asyncio.run(create_auth_state())