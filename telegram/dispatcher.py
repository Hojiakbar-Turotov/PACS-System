import os
import time
import asyncio
import logging
import concurrent.futures
from pathlib import Path
from typing import Optional

import requests
from telethon import TelegramClient
from telethon.sessions import StringSession
from FastTelethonhelper import upload_file as fast_upload_file, download_file as fast_download_file

from core.config import (
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHANNEL_ID,
    TELEGRAM_API_ID,
    TELEGRAM_API_HASH,
    TELEGRAM_STRING_SESSION,
    ARCHIVES_DIR,
)
from core.database import get_connection, log_event, DB_LOCK

logger = logging.getLogger("TELEGRAM_DISPATCHER")

def format_uzbek_date(date_str: str) -> str:
    """YYYYMMDD -> DD-oy YYYY (Masalan: 30-sentabr 2026)"""
    if not date_str:
        return ""
    months = {
        1: "yanvar", 2: "fevral", 3: "mart", 4: "aprel",
        5: "may", 6: "iyun", 7: "iyul", 8: "avgust",
        9: "sentabr", 10: "oktabr", 11: "noyabr", 12: "dekabr"
    }
    s = str(date_str).strip()
    digits = "".join(c for c in s if c.isdigit())
    if len(digits) >= 8:
        try:
            y = int(digits[:4])
            m = int(digits[4:6])
            d = int(digits[6:8])
            if 1 <= m <= 12 and 1 <= d <= 31:
                return f"{d:02d}-{months[m]} {y}"
        except Exception:
            pass
    return s

def build_caption(patient_name: str, patient_id: str, study_date: str, study_desc: str = None, is_update: bool = False) -> str:
    """Telegram uchun aniq formatdagi matn"""
    formatted_date = format_uzbek_date(study_date)
    lines = []
    if is_update:
        lines.append("🔄 Yangilandi")
        
    lines.append(f"👤 Bemor: {patient_name}")
    lines.append(f"🆔 ID: {patient_id}")
    lines.append(f"📅 Sana: {formatted_date}")
    
    # Agar tekshiruv sohasi ma'lum bo'lsa va standart bo'lmagan bo'lsa qo'shish
    if study_desc:
        clean_desc = str(study_desc).strip()
        if clean_desc and clean_desc not in ("-", "None", "UNKNOWN", "CT Exam", "CT Tekshiruv"):
            lines.append(f"🔬 Tekshiruv: {clean_desc}")
            
    return "\n".join(lines)

async def _send_mtproto_async(zip_path: Path, caption_text: str, study_id: int = None) -> int:
    """Telethon MTProto + FastTelethon parallel uploader orqali maksimal tezlikda yuborish (StringSession)"""
    client = TelegramClient(StringSession(TELEGRAM_STRING_SESSION), TELEGRAM_API_ID, TELEGRAM_API_HASH)
    await client.connect()
    if not await client.is_user_authorized():
        await client.start(bot_token=TELEGRAM_BOT_TOKEN)
    try:
        channel_peer = int(TELEGRAM_CHANNEL_ID)
        last_logged = [0]
        start_time = time.time()
        last_time = [start_time]
        last_bytes = [0]
        speed_mb_s = [0.0]
        
        def progress_cb(current, total):
            if not total:
                return
            now_t = time.time()
            dt = now_t - last_time[0]
            if dt >= 0.4 or current == total:
                d_bytes = current - last_bytes[0]
                if dt > 0:
                    speed_mb_s[0] = round((d_bytes / (1024 * 1024)) / dt, 1)
                last_time[0] = now_t
                last_bytes[0] = current

            pct = int((current / total) * 100)
            cur_mb = round(current / (1024 * 1024), 1)
            tot_mb = round(total / (1024 * 1024), 1)
            speed_val = speed_mb_s[0]
            sp_str = f" • ⚡ {speed_val} MB/s" if speed_val > 0 else " • ⚡ 0.0 MB/s"
            
            if study_id:
                try:
                    from core.progress_tracker import update_progress
                    update_progress(
                        study_id=study_id,
                        stage="UPLOADING_TG",
                        percent=pct,
                        text=f"Telegramga: {pct}% ({cur_mb}/{tot_mb} MB){sp_str}",
                        current=current,
                        total=total,
                        speed=f"{speed_val} MB/s"
                    )
                except Exception:
                    pass

            if pct - last_logged[0] >= 20 or pct == 100:
                last_logged[0] = pct
                log_event("MONITOR", f"⚡ Tezkor yuklanmoqda: {cur_mb}/{tot_mb} MB ({pct}%){sp_str}")
                print(f"[FAST TELEGRAM] {zip_path.name}: {cur_mb}/{tot_mb} MB ({pct}%){sp_str}")

        # 1-usul: FastTelethon parallel yuklash
        try:
            with open(str(zip_path), 'rb') as f:
                input_file = await fast_upload_file(
                    client=client,
                    file=f,
                    name=zip_path.name,
                    progress_callback=progress_cb
                )
            msg = await client.send_file(
                channel_peer,
                input_file,
                caption=caption_text,
                force_document=True
            )
            return msg.id
        except Exception as e_fast:
            logger.warning(f"FastTelethon xatoligi: {e_fast}, standart Telethon yuklashga o'tilmoqda...")
            msg = await client.send_file(
                channel_peer,
                str(zip_path),
                caption=caption_text,
                force_document=True,
                progress_callback=progress_cb
            )
            return msg.id
    finally:
        await client.disconnect()

def send_file_mtproto(zip_path: Path, caption_text: str, study_id: int = None) -> int:
    """Har qanday oqimdan (thread) xavfsiz chaqiriladigan MTProto yuborish funksiyasi"""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(asyncio.run, _send_mtproto_async(zip_path, caption_text, study_id))
        return future.result()

def send_file_bot_api(zip_path: Path, caption_text: str) -> int:
    """Standart Telegram Bot API (fayl hajmi 45 MB dan kichik bo'lganda zahira sifatida)"""
    url_doc = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument"
    with open(str(zip_path), 'rb') as f:
        files = {'document': (zip_path.name, f, 'application/zip')}
        data = {'chat_id': TELEGRAM_CHANNEL_ID, 'caption': caption_text}
        res = requests.post(url_doc, data=data, files=files, timeout=180)
        
    if res.status_code == 200:
        return res.json().get('result', {}).get('message_id', 0)
    raise RuntimeError(f"Bot API error: {res.text}")

def send_study_to_telegram(
    study_id: int,
    patient_name: str,
    patient_id: str,
    study_desc: str,
    study_date: str,
    slices_count: int,
    zip_path: Path,
    is_update: bool = False,
    force: bool = False
) -> bool:
    """Bemor tekshiruv ZIP arxivini Telegram kanaliga yagona fayl sifatida yuborish"""
    try:
        # Boshlang'ich holatni darhol xabar qilish
        if study_id:
            try:
                from core.progress_tracker import update_progress
                update_progress(
                    study_id=study_id,
                    stage="UPLOADING_TG",
                    percent=1,
                    text="Telegram serveriga ulanmoqda... 0% • ⚡ 0.0 MB/s",
                    speed="0.0 MB/s",
                    force_db=True
                )
            except Exception:
                pass

        # 1. Takrorlanishni tekshirish
        with DB_LOCK:
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT id, instances_count, last_sent_instances, telegram_status FROM studies WHERE id = ?", (study_id,))
            row = cursor.fetchone()
            conn.close()

        if row and not force:
            last_sent = row["last_sent_instances"] or 0
            curr_status = row["telegram_status"]
            # Agar oldin yuborilgan bo'lsa va kadrlar soni o'zgarmagan bo'lsa
            if curr_status == 'SENT' and last_sent > 0 and last_sent == slices_count:
                log_event("INFO", f"ℹ️ Bemor allaqachon Telegramga yuborilgan ({slices_count} kadr o'zgarmagan). Takror yuborilmadi: {patient_name}")
                return True
            # Agar kadrlar soni farq qilsa, bu yangilanish!
            if curr_status == 'SENT' and last_sent > 0 and last_sent != slices_count:
                is_update = True
                log_event("INFO", f"🔄 Kadrlar soni yangilandi ({last_sent} -> {slices_count} kadr). Telegramga yangilanish sifatida yuborilmoqda: {patient_name}")

        zip_size_mb = round(zip_path.stat().st_size / (1024 * 1024), 1)
        action_name = "Yangilandi deb qayta yuborilmoqda" if is_update else "Yuborilmoqda"
        log_event("INFO", f"Telegramga {action_name}: {patient_name} ({patient_id}), Arxiv: {zip_path.name} ({zip_size_mb} MB, {slices_count} kadr)")

        # 2. Matnni shakllantirish (Sana: 02-oktabr 2026, fotosuratsiz)
        caption_text = build_caption(
            patient_name=patient_name,
            patient_id=patient_id,
            study_date=study_date,
            study_desc=study_desc,
            is_update=is_update
        )

        # 3. Yagona ZIP faylni MTProto orqali yuborish (2 GB gacha bitta fayl!)
        message_id = None
        try:
            message_id = send_file_mtproto(zip_path, caption_text, study_id=study_id)
            log_event("INFO", f"✅ MTProto orqali bitta butun ZIP yuborildi: {zip_path.name} (Msg ID: {message_id})")
        except Exception as e_mtproto:
            logger.warning(f"MTProto orqali yuborishda xatolik: {e_mtproto}. Bot API tekshirilmoqda...")
            # Agar fayl <= 45 MB bo'lsa, standart Bot API ga fallback
            if zip_path.stat().st_size <= 45 * 1024 * 1024:
                message_id = send_file_bot_api(zip_path, caption_text)
                log_event("INFO", f"✅ Bot API orqali yuborildi: {zip_path.name} (Msg ID: {message_id})")
            else:
                raise e_mtproto

        # 4. Bazani yangilash
        with DB_LOCK:
            conn = get_connection()
            conn.execute("""
                UPDATE studies 
                SET telegram_status = 'SENT',
                    telegram_message_id = ?,
                    telegram_error = NULL,
                    last_sent_instances = ?,
                    instances_count = ?
                WHERE id = ?
            """, (message_id, slices_count, slices_count, study_id))
            conn.commit()
            conn.close()

        try:
            from core.progress_tracker import mark_completed
            mark_completed(study_id, success=True)
        except Exception:
            pass

        log_event("INFO", f"Arxiv muvaffaqiyatli yetkazildi: {patient_name} [{slices_count} kadr]")
        return True

    except Exception as e:
        logger.error(f"Telegram yuborish xatosi: {e}", exc_info=True)
        log_event("ERROR", f"Telegram yuborish xatosi [{patient_name}]: {e}")
        try:
            from core.progress_tracker import mark_completed
            mark_completed(study_id, success=False, error_msg=str(e))
        except Exception:
            pass
        try:
            with DB_LOCK:
                conn = get_connection()
                conn.execute("""
                    UPDATE studies 
                    SET telegram_status = 'FAILED', telegram_error = ?
                    WHERE id = ?
                """, (str(e), study_id))
                conn.commit()
                conn.close()
        except Exception:
            pass
        return False

async def _download_from_tg_async(study_id: int) -> bool:
    """Telegram kanalidagi xabardan ZIP arxivni qayta yuklab olish"""
    with DB_LOCK:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM studies WHERE id = ?", (study_id,))
        study = cursor.fetchone()
        conn.close()

    if not study or not study["telegram_message_id"]:
        raise ValueError("Tekshiruvning Telegram xabari ID si topilmadi")

    message_id = int(study["telegram_message_id"])
    patient_name = study["patient_name"] or "Unknown"
    date_folder = datetime.now().strftime("%Y-%m-%d")
    target_dir = ARCHIVES_DIR / date_folder
    target_dir.mkdir(parents=True, exist_ok=True)

    client = TelegramClient(StringSession(TELEGRAM_STRING_SESSION), TELEGRAM_API_ID, TELEGRAM_API_HASH)
    await client.connect()
    try:
        channel_peer = int(TELEGRAM_CHANNEL_ID)
        msg = await client.get_messages(channel_peer, ids=message_id)
        if not msg or not msg.media:
            raise RuntimeError(f"Telegram kanalida {message_id}-xabar yoki media fayl topilmadi")

        filename = getattr(msg.file, 'name', None) or f"{patient_name}_{study_id}.zip"
        target_path = target_dir / filename

        start_time = time.time()
        last_time = [start_time]
        last_bytes = [0]
        speed_mb_s = [0.0]

        def progress_cb(current, total):
            if not total: return
            now_t = time.time()
            dt = now_t - last_time[0]
            if dt >= 0.5 or current == total:
                d_bytes = current - last_bytes[0]
                if dt > 0:
                    speed_mb_s[0] = round((d_bytes / (1024 * 1024)) / dt, 1)
                last_time[0] = now_t
                last_bytes[0] = current

            pct = int((current / total) * 100)
            cur_mb = round(current / (1024 * 1024), 1)
            tot_mb = round(total / (1024 * 1024), 1)
            sp_str = f" • ⚡ {speed_mb_s[0]} MB/s" if speed_mb_s[0] > 0 else ""
            
            try:
                from core.progress_tracker import update_progress
                update_progress(
                    study_id=study_id,
                    stage="DOWNLOADING_TG",
                    percent=pct,
                    text=f"Telegramdan: {pct}% ({cur_mb}/{tot_mb} MB){sp_str}",
                    current=current,
                    total=total,
                    speed=f"{speed_mb_s[0]} MB/s"
                )
            except Exception:
                pass

        # Optimal parallel MTProto yuklab olish (FastTelethon)
        try:
            if hasattr(msg, 'document') and msg.document:
                with open(str(target_path), 'wb') as out_f:
                    await fast_download_file(
                        client=client,
                        location=msg.document,
                        out=out_f,
                        progress_callback=progress_cb
                    )
            else:
                await client.download_media(msg, file=str(target_path), progress_callback=progress_cb)
        except Exception as e_fast:
            logger.warning(f"FastTelethon yuklab olishda ogohlantirish: {e_fast}, standart download_media ga o'tilmoqda...")
            await client.download_media(msg, file=str(target_path), progress_callback=progress_cb)

        file_size = target_path.stat().st_size
        now_iso = datetime.now().isoformat()
        with DB_LOCK:
            conn = get_connection()
            conn.execute("""
                UPDATE studies SET
                    archive_path = ?,
                    archive_size_bytes = ?,
                    local_copy_status = 'STORED',
                    local_stored_at = ?,
                    progress_stage = 'IDLE',
                    progress_percent = 100,
                    progress_text = ''
                WHERE id = ?
            """, (str(target_path), file_size, now_iso, study_id))
            conn.commit()
            conn.close()

        try:
            from core.progress_tracker import mark_completed
            mark_completed(study_id, success=True)
        except Exception:
            pass

        log_event("INFO", f"📥 Telegramdan muvaffaqiyatli yuklab olindi: {filename} ({round(file_size/1024/1024, 1)} MB)")
        return True
    except Exception as e:
        logger.error(f"Telegramdan yuklab olish xatosi: {e}", exc_info=True)
        log_event("ERROR", f"Telegramdan yuklab olish xatosi [{patient_name}]: {e}")
        try:
            from core.progress_tracker import mark_completed
            mark_completed(study_id, success=False, error_msg=str(e))
        except Exception:
            pass
        return False
    finally:
        await client.disconnect()

def download_study_from_telegram(study_id: int):
    """Sinxron oqim orqali chaqiriluvchi Telegram yuklash funksiyasi"""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(asyncio.run, _download_from_tg_async(study_id))
        return future.result()
