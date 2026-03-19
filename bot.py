import logging
import os
from datetime import time
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, ContextTypes

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("OrzuMallDailyBot")

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
TARGET_CHANNEL = os.getenv("TARGET_CHANNEL", "").strip()
TZ = os.getenv("TZ", "Asia/Tashkent").strip()
POST_HOUR = int(os.getenv("POST_HOUR", "7"))
POST_MINUTE = int(os.getenv("POST_MINUTE", "30"))

POST_TEXT = os.getenv(
    "POST_TEXT",
    "✨ OrzuMall — siz izlagan mahsulotlar shu yerda!\n\n"
    "🛍 Original parfumeriya\n"
    "💄 Koreys kosmetikasi\n"
    "👩 Ayollar uchun kerakli mahsulotlar\n"
    "🚚 Qulay buyurtma va tezkor aloqa\n\n"
    "Quyidagi havolalar orqali bizga qo‘shiling 👇"
).strip()

PHOTO_URL = os.getenv("PHOTO_URL", "").strip()
VIDEO_URL = os.getenv("VIDEO_URL", "").strip()

BTN1_TEXT = os.getenv("BTN1_TEXT", "🛍 Kanal")
BTN1_URL = os.getenv("BTN1_URL", "https://t.me/orzumalluz").strip()
BTN2_TEXT = os.getenv("BTN2_TEXT", "👥 Guruh")
BTN2_URL = os.getenv("BTN2_URL", "https://t.me/orzumallgroup").strip()
BTN3_TEXT = os.getenv("BTN3_TEXT", "🤖 Bot")
BTN3_URL = os.getenv("BTN3_URL", "https://t.me/OrzuMallUZ_bot").strip()
BTN4_TEXT = os.getenv("BTN4_TEXT", "🌐 Sayt")
BTN4_URL = os.getenv("BTN4_URL", "https://orzumall.uz").strip()

def build_keyboard():
    rows = []
    if BTN1_URL:
        rows.append([InlineKeyboardButton(BTN1_TEXT, url=BTN1_URL)])
    if BTN2_URL:
        rows.append([InlineKeyboardButton(BTN2_TEXT, url=BTN2_URL)])
    if BTN3_URL:
        rows.append([InlineKeyboardButton(BTN3_TEXT, url=BTN3_URL)])
    if BTN4_URL:
        rows.append([InlineKeyboardButton(BTN4_TEXT, url=BTN4_URL)])
    return InlineKeyboardMarkup(rows) if rows else None

async def publish_post(context: ContextTypes.DEFAULT_TYPE) -> None:
    if not TARGET_CHANNEL:
        logger.error("TARGET_CHANNEL kiritilmagan.")
        return

    keyboard = build_keyboard()

    try:
        if VIDEO_URL:
            await context.bot.send_video(
                chat_id=TARGET_CHANNEL,
                video=VIDEO_URL,
                caption=POST_TEXT,
                reply_markup=keyboard,
            )
        elif PHOTO_URL:
            await context.bot.send_photo(
                chat_id=TARGET_CHANNEL,
                photo=PHOTO_URL,
                caption=POST_TEXT,
                reply_markup=keyboard,
            )
        else:
            await context.bot.send_message(
                chat_id=TARGET_CHANNEL,
                text=POST_TEXT,
                reply_markup=keyboard,
                disable_web_page_preview=False,
            )
        logger.info("Post yuborildi: %s", TARGET_CHANNEL)
    except Exception:
        logger.exception("Post yuborishda xato bo‘ldi.")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Salom. Men OrzuMall kunlik reklama botiman.\n\n"
        "Buyruqlar:\n"
        "/testpost — postni hozir yuboradi\n"
        "/status — sozlamalarni ko‘rsatadi"
    )

async def testpost(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Test post yuborilyapti...")
    await publish_post(context)

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        f"TARGET_CHANNEL: {TARGET_CHANNEL or 'yo‘q'}\n"
        f"Vaqt: {POST_HOUR:02d}:{POST_MINUTE:02d}\n"
        f"TZ: {TZ}\n"
        f"PHOTO_URL: {'bor' if PHOTO_URL else 'yo‘q'}\n"
        f"VIDEO_URL: {'bor' if VIDEO_URL else 'yo‘q'}"
    )

def main() -> None:
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN topilmadi. Railway Variables ga qo‘ying.")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("testpost", testpost))
    app.add_handler(CommandHandler("status", status))

    jq = app.job_queue
    if jq is None:
        logger.warning("JobQueue yo‘q. requirements.txt ichida python-telegram-bot[job-queue] bo‘lishi kerak.")
    else:
        jq.run_daily(
            publish_post,
            time=time(hour=POST_HOUR, minute=POST_MINUTE),
            name="daily_post",
        )
        logger.info("Kunlik post yoqildi: %02d:%02d", POST_HOUR, POST_MINUTE)

    logger.info("Bot ishga tushdi.")
    app.run_polling(close_loop=False)

if __name__ == "__main__":
    main()
