"""
Watches a local folder for CSV files (dropped there by a staff member who
manually exported the patient list from their own authorized DMED session)
and loads them into the board's database.

Nothing here talks to DMED or any remote site — it only reads files that
already exist on local disk. This is intentionally decoupled from wherever
the CSV came from.

Two input formats are auto-detected:

1. DMED's raw "inpatient-care" export — no header row, 11 comma-separated
   columns, first column shaped like "10346-2026" (case id):
     0 case id       1 patient name   2 (unused)        3 (unused)
     4 department    5 bed + dept     6 attending doctor 7 (unused)
     8 admission dt  9 notes          10 (unused, "Просмотр")
   Rows whose name contains "новорожден" (any capitalization / ё-е form —
   i.e. newborns, usually listed as "Новорожденный (MOTHER NAME)") are
   skipped: newborns ride on the mother's record and aren't shown as their
   own row on the board.

2. A simple header'd format for manual/admin-panel-style input:
     name,location,is_transit

Row order in the file becomes board order. Every import fully replaces the
current patient list (see _apply_rows).
"""

import csv
import io
import logging
import os
import re
import shutil
import time
from datetime import datetime

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

import models
from database import SessionLocal

logger = logging.getLogger("riobsiatm.importer")

WATCH_DIR = os.environ.get(
    "RIOBSIATM_IMPORT_DIR", os.path.join(os.path.dirname(__file__), "import_dropbox")
)
PROCESSED_DIR = os.path.join(WATCH_DIR, "processed")
FAILED_DIR = os.path.join(WATCH_DIR, "failed")

TRUE_VALUES = {"1", "true", "yes", "y", "да", "истина"}

# Matches DMED's case-id shape, e.g. "10346-2026" — used to detect the raw
# export format (which has no header row) vs. the simple name/location CSV.
_CASE_ID_RE = re.compile(r"^\d+-\d{4}$")

_BED_NUMBER_RE = re.compile(r"^(\d+)")


def _is_newborn(name: str) -> bool:
    # DMED spells it "Новорожденный"/"Новорождённый" depending on export —
    # normalize ё→е before matching so both forms are caught.
    normalized = name.lower().replace("ё", "е")
    return "новорожден" in normalized


def _ensure_dirs():
    os.makedirs(WATCH_DIR, exist_ok=True)
    os.makedirs(PROCESSED_DIR, exist_ok=True)
    os.makedirs(FAILED_DIR, exist_ok=True)


def _wait_until_stable(path: str, timeout: float = 10.0) -> bool:
    """Waits until a file's size stops changing, so we don't read it mid-write
    (e.g. while it's still being copied/synced into the drop folder)."""
    deadline = time.time() + timeout
    last_size = -1
    while time.time() < deadline:
        try:
            size = os.path.getsize(path)
        except OSError:
            return False
        if size == last_size and size > 0:
            return True
        last_size = size
        time.sleep(0.3)
    return False


def _parse_dmed_export(text: str):
    """Parses DMED's raw inpatient-care export (no header, 11 columns)."""
    reader = csv.reader(io.StringIO(text))
    rows = []
    skipped_newborns = 0
    for cols in reader:
        if len(cols) < 6:
            continue  # malformed/short row — skip rather than fail the whole file
        name = (cols[1] or "").strip()
        if not name:
            continue
        if _is_newborn(name):
            skipped_newborns += 1
            continue

        department = (cols[4] or "").strip()
        bed_field = (cols[5] or "").strip()
        bed_match = _BED_NUMBER_RE.match(bed_field)
        bed = bed_match.group(1) if bed_match else ""
        location = f"{department}, место {bed}" if bed and department else (department or bed_field)

        rows.append({"name": name, "location": location or "—", "is_transit": False})

    if not rows:
        raise ValueError("В выгрузке DMED нет строк с пациентами (после исключения новорождённых)")
    logger.info("DMED export: %d patients, %d newborn rows excluded", len(rows), skipped_newborns)
    return rows


def _parse_simple_csv(text: str):
    """Parses the simple header'd format: name,location,is_transit."""
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise ValueError("Файл пустой или без заголовка")
    fieldnames = [f.strip().lower() for f in reader.fieldnames]
    if "name" not in fieldnames or "location" not in fieldnames:
        raise ValueError("В CSV должны быть колонки: name, location[, is_transit]")

    rows = []
    for raw_row in reader:
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in raw_row.items()}
        name = row.get("name", "")
        location = row.get("location", "")
        if not name or not location:
            continue  # skip incomplete rows rather than failing the whole import
        if _is_newborn(name):
            continue
        is_transit = row.get("is_transit", "").strip().lower() in TRUE_VALUES
        rows.append({"name": name, "location": location, "is_transit": is_transit})
    if not rows:
        raise ValueError("В CSV нет валидных строк (нужны непустые name и location)")
    return rows


def _parse_csv(raw: bytes):
    text = raw.decode("utf-8-sig")  # tolerate Excel's UTF-8 BOM
    stripped = text.strip()
    if not stripped:
        raise ValueError("Файл пустой")
    first_field = stripped.splitlines()[0].split(",")[0].strip().strip('"')
    if _CASE_ID_RE.match(first_field):
        return _parse_dmed_export(text)
    return _parse_simple_csv(text)


def _apply_rows(rows: list):
    db = SessionLocal()
    try:
        db.query(models.Patient).delete()
        for i, r in enumerate(rows):
            db.add(models.Patient(name=r["name"], location=r["location"], is_transit=r["is_transit"], position=i))
        db.commit()
    finally:
        db.close()


def _log_import(filename: str, row_count: int, status: str, detail: str = None):
    db = SessionLocal()
    try:
        db.add(models.ImportLog(filename=filename, row_count=row_count, status=status, detail=detail))
        db.commit()
    finally:
        db.close()


def process_file(path: str):
    filename = os.path.basename(path)
    if not filename.lower().endswith(".csv"):
        return
    if not _wait_until_stable(path):
        logger.warning("File %s never stabilized, skipping for now", filename)
        return

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    try:
        with open(path, "rb") as f:
            raw = f.read()
        rows = _parse_csv(raw)
        _apply_rows(rows)
        _log_import(filename, len(rows), "ok")
        dest = os.path.join(PROCESSED_DIR, f"{ts}__{filename}")
        shutil.move(path, dest)
        logger.info("Imported %d rows from %s", len(rows), filename)
    except Exception as e:  # noqa: BLE001 - report any parse/IO error and move on
        logger.exception("Failed to import %s", filename)
        _log_import(filename, 0, "error", str(e))
        try:
            dest = os.path.join(FAILED_DIR, f"{ts}__{filename}")
            shutil.move(path, dest)
        except Exception:
            pass


def scan_once():
    """Processes any CSV files already sitting in the watch folder. Useful on
    startup (in case a file arrived while the service was down) and as a
    manual 'check now' trigger from the admin panel."""
    _ensure_dirs()
    for name in sorted(os.listdir(WATCH_DIR)):
        full = os.path.join(WATCH_DIR, name)
        if os.path.isfile(full) and name.lower().endswith(".csv"):
            process_file(full)


class _CsvHandler(FileSystemEventHandler):
    def on_created(self, event):
        if not event.is_directory:
            process_file(event.src_path)

    def on_moved(self, event):
        if not event.is_directory:
            process_file(event.dest_path)


_observer = None


def start_watching():
    global _observer
    _ensure_dirs()
    scan_once()  # catch up on anything dropped while the app was down
    _observer = Observer()
    _observer.schedule(_CsvHandler(), WATCH_DIR, recursive=False)
    _observer.daemon = True
    _observer.start()
    logger.info("Watching %s for CSV drops", WATCH_DIR)


def stop_watching():
    if _observer:
        _observer.stop()
        _observer.join(timeout=5)
