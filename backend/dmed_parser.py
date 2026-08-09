import logging
from typing import List, Dict, Any
from datetime import datetime, timedelta
import httpx
import json

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s"
)
logger = logging.getLogger(__name__)

# Эндпоинт API
API_URL = "https://zordoc.uz/api/mis/v2/hospitalizations"


async def fetch_patients_by_date(target_date: str = None, per_page: int = 50) -> List[Dict[str, Any]]:
    """
    Сканирует страницы zordoc.uz и собирает ВСЕ записи за указанную дату (в формате 'YYYY-MM-DD').
    Если дата не передана, по умолчанию берется ВЧЕРАШНИЙ день.
    """
    if not target_date:
        yesterday = datetime.now() - timedelta(days=1)
        target_date = yesterday.strftime("%Y-%m-%d")

    headers = {
        "accept": "application/json, text/plain, */*",
        "accept-language": "en-US,en;q=0.9,ru;q=0.8",
        "authorization": "Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJpc3MiOiJodHRwczovL3pvcmRvYy51eiIsImlhdCI6MTc4MTIzNTE4NSwiZXhwIjoxODEyNzcxMTg1LCJuYmYiOjE3ODEyMzUxODUsImp0aSI6ImFJckpkY2MyZW5WUWlTV2giLCJzdWIiOiI0MDMzMDU0NSIsInBydiI6ImI0YmJhMDY3OGRjYmI4MDA1YmQyNzc0NmI2ZmY3MmI0YzdiN2Y3ZjYiLCJuYW1lIjoiWUFYU0hJTVVST0RPViBKQUxPTEFERElOIEFMSVNIRVIgT-KAmEfigJhMSSIsImVtYWlsIjpudWxsLCJyb2xlIjoiZGlyZWN0b3IifQ.b4asbNh6FW92-_tpCn4oo89Btu9GI_VATPWWPjVB9VQ",
        "clinic": "",
        "device-id": "c379e39d-fe70-431d-b880-ef2c24213fbb",
        "lang": "ru",
        "origin": "https://mis.dmed.uz",
        "priority": "u=1, i",
        "referer": "https://mis.dmed.uz/",
        "sec-ch-ua": '"Not=A?Brand";v="99", "Google Chrome";v="151", "Chromium";v="151"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "cross-site",
        "service-authorization": "Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzUxMiJ9.eyJpYXQiOjE3ODEyMzUxODUuNzUwMTMyLCJpc3MiOiJodHRwczovL3pvcmRvYy51eiIsImV4cCI6MTc4MTMyMTU4NS43NTAxMzIsInBpbmZsIjoiNTI2MDQwNDcxOTAwMTkiLCJuYW1lOiJKQUxMT0xBRERJTiIsInV1aWQiOiIwZDkwNjYzMC0yZmFmLTQwNmMtYWVhMi1iZTU4NzBiYzE1NDkiLCJzdXJuYW1lIjoiWUFYU0hJTVVST0RPViIsInBhdHJvbnltaWMiOiJBTElTSEVSIE_igJhH4oCYTEkiLCJyb2xlcyI6WyJkaXJlY3RvciJdLCJzcGVjaWFsdGllcyI6W10sImNsaW5pY191dWlkIjoiYzAyMDMyZDQtZDZkOS00ZjA3LWEzOTYtMjY2Mzg0NzY4ZWE2IiwicG9zaXRpb25zIjpbXX0.BD8j0ByERkow_RE0sqspAcjTHTIzI2_3_rJCb1MS7wzI62QgKHq12rfeaJv1tHmLMDZDeOUEHLIDxFoIr4mMMt3JeoVy969oYBb42mw_2gzBH3ourcgs8FS2ScFK7jDWQVCYpSg-zemRHBg_ipVV-hVmosC3kjkocixPvJaJXJtaUWYNa8nKWAkgoSr7SE7gzMNyU8ep228--0o2-TzOOdtMG5AdyL0cOLtZZXR3lkth_lC35kzcn-H2r25Zk9EbALcSP1EgVskerPUzB3UEogDgnR9t0pQdttLmMwV8B9AKzkpD96Th9G0cny5bc3XpHjSc4i7HWXeVxgG_o5Yx-Q",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
    }

    matched_patients = []
    page = 1
    max_empty_pages = 3  # Защита: остановится, если 3 страницы подряд идут старые данные
    empty_pages_count = 0

    logger.info(f"[ПАРСЕР] Сбор всех записей за дату: {target_date}")

    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        while True:
            params = {
                "page": page,
                "per_page": per_page,
                "status": "in_progress",
                "type_list": "emergency_room"
            }

            try:
                response = await client.get(API_URL, headers=headers, params=params)
                if response.status_code != 200:
                    logger.error(f"[ПАРСЕР] Ошибка на странице {page}: HTTP {response.status_code}")
                    break

                data = response.json()
                patients = data.get("data") or data.get("items") or data.get("hospitalizations") or []

                if not patients:
                    break

                page_matched = 0
                has_older_dates = False

                for item in patients:
                    created_at = item.get("created_at")
                    if created_at:
                        item_date = created_at.split("T")[0]

                        if item_date == target_date:
                            matched_patients.append(item)
                            page_matched += 1
                        elif item_date < target_date:
                            has_older_dates = True

                logger.info(f"[ПАРСЕР] Страница {page}: найдено за {target_date} — {page_matched} шт.")

                if page_matched == 0 and has_older_dates:
                    empty_pages_count += 1
                else:
                    empty_pages_count = 0

                if empty_pages_count >= max_empty_pages:
                    logger.info("[ПАРСЕР] Достигнуты более старые дни, завершаем обход.")
                    break

                if len(patients) < per_page:
                    break  # Конец данных

                page += 1

            except Exception as e:
                logger.error(f"[ПАРСЕР] Ошибка на странице {page}: {e}")
                break

    logger.info(f"[ПАРСЕР] Итог: успешно собрано записей за {target_date}: {len(matched_patients)}")
    return matched_patients


if __name__ == "__main__":
    import asyncio
    
    # Укажите нужную дату для теста в формате "YYYY-MM-DD" (например, вчерашнюю)
    TARGET_DATE = "2026-08-09" 

    print(f"Запуск теста за дату: {TARGET_DATE}...")
    result = asyncio.run(fetch_patients_by_date(target_date=TARGET_DATE))
    
    print(f"\n Результат: найдено записей за {TARGET_DATE}: {len(result)}")
    if result:
        print("\nПример первой записи:")
        print(json.dumps(result[0], ensure_ascii=False, indent=2))