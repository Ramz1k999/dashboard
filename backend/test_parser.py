import asyncio
import json
import httpx
from dmed_parser import load_cookies_from_state

async def debug_request():
    cookies = load_cookies_from_state()
    print(f"[1] Загружено кук из auth_state.json: {len(cookies)}")
    
    # Рекомендуется использовать полный поддомен mis.dmed.uz
    url = "https://mis.dmed.uz/inpatient-care" 
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    }

    async with httpx.AsyncClient(cookies=cookies, headers=headers, follow_redirects=True, timeout=15.0) as client:
        try:
            response = await client.get(url)
            print(f"[2] HTTP Status Code: {response.status_code}")
            print(f"[3] Итоговый URL после перенаправлений: {response.url}")
            
            # Сохраняем первые 500 символов ответа для анализа
            content_preview = response.text[:500]
            print(f"\n[4] Превью ответа:\n{content_preview}")
            
            if "login" in str(response.url).lower() or "auth" in str(response.url).lower():
                print("\n СЕССИЯ ИСТЕКЛА: Сайт перенаправил на страницу входа.")
            elif response.status_code == 200:
                print("\n УСПЕХ: Страница загружена!")

        except Exception as e:
            print(f"\n Ошибка при отправке запроса: {e}")

if __name__ == "__main__":
    asyncio.run(debug_request())