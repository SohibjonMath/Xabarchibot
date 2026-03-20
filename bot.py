import logging
import os
from datetime import time

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("OrzuMallForwardBot")

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
TARGET_CHANNEL = os.getenv("TARGET_CHANNEL", "").strip()   # masalan: @orzumalluz
TZ = os.getenv("TZ", "Asia/Tashkent").strip()

# Har kuni 07:30
POST_HOUR = int(os.getenv("POST_HOUR", "7"))
POST_MINUTE = int(os.getenv("POST_MINUTE", "30"))

# Qaysi chatdan va qaysi postni forward qilish
SOURCE_CHAT_ID = os.getenv("SOURCE_CHAT_ID", "").strip()   # masalan: -1001234567890
SOURCE_MESSAGE_ID = int(os.getenv("SOURCE_MESSAGE_ID", "0"))

HELP_TEXT = """Salom. Men forward repost botman.

Ishlash tartibi:
1) SOURCE_CHAT_ID va SOURCE_MESSAGE_ID ni Variables ga yozasiz
2) Botni maqsad kanalga admin qilasiz
3) Har kuni avtomatik forward qiladi

Buyruqlar:
/start - yordam
/status - joriy sozlamalar
/testforward - hozir sinab ko‘radi
"""


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message:
        await update.message.reply_text(HELP_TEXT)


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    text = (
        f"TARGET_CHANNEL: {TARGET_CHANNEL or 'kiritilmagan'}\n"
        f"SOURCE_CHAT_ID: {SOURCE_CHAT_ID or 'kiritilmagan'}\n"
        f"SOURCE_MESSAGE_ID: {SOURCE_MESSAGE_ID if SOURCE_MESSAGE_ID else 'kiritilmagan'}\n"
        f"Vaqt: {POST_HOUR:02d}:{POST_MINUTE:02d}\n"
        f"TZ: {TZ}"
    )
    await update.message.reply_text(text)


async def do_forward(context: ContextTypes.DEFAULT_TYPE) -> None:
    if not TARGET_CHANNEL:
        logger.error("TARGET_CHANNEL kiritilmagan.")
        return
    if not SOURCE_CHAT_ID or not SOURCE_MESSAGE_ID:
        logger.error("SOURCE_CHAT_ID yoki SOURCE_MESSAGE_ID kiritilmagan.")
        return

    try:
        await context.bot.forward_message(
            chat_id=TARGET_CHANNEL,
            from_chat_id=SOURCE_CHAT_ID,
            message_id=SOURCE_MESSAGE_ID,
        )
        logger.info(
            "Forward muvaffaqiyatli yuborildi. source=%s message_id=%s target=%s",
            SOURCE_CHAT_ID,
            SOURCE_MESSAGE_ID,
            TARGET_CHANNEL,
        )
    except Exception as e:
        logger.exception("Forward xatoligi: %s", e)


async def testforward(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message:
        await update.message.reply_text("Test forward yuborilmoqda...")
    await do_forward(context)


def main() -> None:
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN topilmadi. Railway Variables ga qo‘ying.")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("testforward", testforward))

    jq = app.job_queue
    if jq is None:
        logger.warning(
            "JobQueue yo‘q. requirements.txt ichida python-telegram-bot[job-queue] bo‘lishi kerak."
        )
    else:
        jq.run_daily(
            do_forward,
            time=time(hour=POST_HOUR, minute=POST_MINUTE),
            name="daily_forward_post",
        )
        logger.info("Kunlik forward yoqildi: %02d:%02d", POST_HOUR, POST_MINUTE)

    logger.info("Bot ishga tushdi.")
    app.run_polling(close_loop=False)


if __name__ == "__main__":
    main()
