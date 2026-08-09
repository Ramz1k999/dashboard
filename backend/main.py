import os
import sys
import asyncio
from datetime import datetime, timezone
from typing import List

# 1. Фикс для работы Playwright на Windows (убирает ошибку NotImplementedError)
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# 2. Обязательные локальные импорты проекта
import importer
import models
import schemas
from database import Base, SessionLocal, engine, get_db
from dmed_parser import fetch_patients_by_date

Base.metadata.create_all(bind=engine)

API_KEY = os.environ.get("RIOBSIATM_API_KEY")

app = FastAPI(
    title="RIOBSIATM Patient Status Board API",
    description="Backend for the RIOBSIATM patient status dashboard.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("RIOBSIATM_CORS_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------
# ФОНОВЫЙ ПЛАНИРОВЩИК И ПАРСИНГ
# ---------------------------------------------------------
scheduler = AsyncIOScheduler()

async def run_parser_job():
    """Фоновая задача: запрашивает данные с zordoc.uz через REST API и записывает их в БД."""
    print(f"[{datetime.now()}] Запуск обновления данных из zordoc.uz...")
    
    # Забираем записи за сегодня автоматически
    raw_patients = await fetch_patients_by_date()
    
    if not raw_patients:
        print("[ПАРСЕР] Нет новых данных за сегодня или произошла ошибка сети.")
        return

    db = SessionLocal()
    try:
        # Очищаем старые данные перед полной перезаписью
        db.query(models.Patient).delete()

        added_count = 0
        for row in raw_patients:
            # Безопасно извлекаем вложенные словари ответа API
            patient_info = row.get("patient") or {}
            surname = patient_info.get("surname", "")
            name = patient_info.get("name", "")
            
            # Собираем полное имя для проверки и отображения
            full_name = f"{surname} {name}".strip()
            
            # Проверяем, есть ли слово "новорожденный" (как в вашем примере)
            if "новорожденный" in surname.lower() or "новорожденный" in name.lower():
                continue

            display_name = full_name if full_name else "Неизвестно"
            
            # Определяем локацию (палата или отделение)
            chamber = row.get("chamber") or {}
            department = row.get("department") or {}
            location = chamber.get("number") or department.get("title") or "Стационар"

            patient = models.Patient(
                name=display_name,
                location=location,
                is_transit=False,
                position=added_count
            )
            db.add(patient)
            added_count += 1

        db.commit()
        print(f"[{datetime.now()}] База данных успешно обновлена! Сохранено записей: {added_count}")

    except Exception as e:
        db.rollback()
        print(f"[ОШИБКА ЗАПИСИ В БД]: {e}")
    finally:
        db.close()
# ---------------------------------------------------------


def require_api_key(x_api_key: str = Header(default=None)):
    if API_KEY and x_api_key != API_KEY:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing X-API-Key")


def seed_if_empty(db: Session):
    if db.query(models.Patient).count() > 0:
        return
    seed = [
        ("Анна Самарова", "Родблок 04", False),
        ("Михаил Волков", "Транспортировка на УЗИ 2", True),
        ("Елена Петрова", "Палата 12В - Перинатальный уход", False),
        ("Дмитрий Ковалёв", "Родблок 09", False),
        ("Ольга Никитина", "Транспортировка в неонатальное отделение", True),
        ("Иван Соколов", "Операционная 3 - Хирургия", False),
    ]
    for i, (name, location, is_transit) in enumerate(seed):
        db.add(models.Patient(name=name, location=location, is_transit=is_transit, position=i))
    db.commit()


@app.on_event("startup")
def on_startup():
    db = SessionLocal()
    try:
        seed_if_empty(db)
    finally:
        db.close()
    
    importer.start_watching()
    
    # Запустит первый раз немедленно при старте, а затем каждые 10 минут
    scheduler.add_job(
        run_parser_job, 
        'interval', 
        minutes=10, 
        id='dmed_parser_job',
        next_run_time=datetime.now()
    )
    scheduler.start()

@app.on_event("shutdown")
def on_shutdown():
    importer.stop_watching()
    scheduler.shutdown()


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/server-time")
def server_time():
    """Lets the dashboard sync its clock to the server instead of the viewer's device clock."""
    return {"iso": datetime.now(timezone.utc).isoformat()}


@app.get("/api/patients", response_model=List[schemas.PatientOut])
def list_patients(db: Session = Depends(get_db)):
    return db.query(models.Patient).order_by(models.Patient.position, models.Patient.id).all()


@app.get("/api/patients/{patient_id}", response_model=schemas.PatientOut)
def get_patient(patient_id: int, db: Session = Depends(get_db)):
    patient = db.get(models.Patient, patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    return patient


@app.post(
    "/api/patients",
    response_model=schemas.PatientOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_api_key)],
)
def create_patient(payload: schemas.PatientCreate, db: Session = Depends(get_db)):
    patient = models.Patient(**payload.model_dump())
    db.add(patient)
    db.commit()
    db.refresh(patient)
    return patient


@app.put(
    "/api/patients/{patient_id}",
    response_model=schemas.PatientOut,
    dependencies=[Depends(require_api_key)],
)
def update_patient(patient_id: int, payload: schemas.PatientUpdate, db: Session = Depends(get_db)):
    patient = db.get(models.Patient, patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(patient, field, value)
    patient.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(patient)
    return patient


@app.get("/api/import/status", response_model=List[schemas.ImportLogOut])
def import_status(db: Session = Depends(get_db)):
    """Recent CSV import attempts, most recent first — lets the admin panel
    show 'last updated 6 minutes ago' or flag a failed import."""
    return (
        db.query(models.ImportLog)
        .order_by(models.ImportLog.imported_at.desc())
        .limit(20)
        .all()
    )


@app.post("/api/import/scan", dependencies=[Depends(require_api_key)])
def import_scan_now():
    """Manual 'check the drop folder now' trigger, e.g. for a button in the admin panel."""
    importer.scan_once()
    return {"status": "scanned"}


@app.delete(
    "/api/patients/{patient_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_api_key)],
)
def delete_patient(patient_id: int, db: Session = Depends(get_db)):
    patient = db.get(models.Patient, patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    db.delete(patient)
    db.commit()
    return None