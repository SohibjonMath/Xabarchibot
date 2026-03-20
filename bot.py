#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
import logging
from telegram import (
    Update,
    ReplyKeyboardMarkup,
    KeyboardButton,
    WebAppInfo,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from telegram.constants import ParseMode
from telegram.error import Forbidden, BadRequest, NetworkError, RetryAfter, TimedOut
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# ================== CONFIG ==================
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
WEB_APP_URL = os.getenv("WEB_APP_URL", "https://xplusy.netlify.app/").strip()
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "2049065724").strip())

OPERATORS_CSV = os.getenv("OPERATORS", "").strip()
OPERATORS_JSON = os.getenv("OPERATORS_JSON", "").strip()
OPERATOR_GROUP_ID_RAW = os.getenv("OPERATOR_GROUP_ID", "").strip()

# ================== LOGGING ==================
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("OrzuMallBot")

# ================== KEYS ==================
CHAT_MODE_KEY = "chat_mode"
SEARCH_MODE_KEY = "search_mode"
ACTIVE_CHAT_USER_KEY = "active_chat_user_id"

SESSIONS_KEY = "sessions"
USER_PROFILES_KEY = "user_profiles"
NOTIF_MAP_KEY = "notif_map"


def parse_operators() -> list[int]:
    operators = set()

    if OPERATORS_JSON:
        try:
            data = json.loads(OPERATORS_JSON)
            for x in data:
                operators.add(int(x))
        except Exception as e:
            logger.warning("OPERATORS_JSON parse xato: %s", e)

    if OPERATORS_CSV:
        for x in OPERATORS_CSV.split(","):
            x = x.strip()
            if x:
                try:
                    operators.add(int(x))
                except ValueError:
                    logger.warning("OPERATORS CSV noto'g'ri qiymat: %s", x)

    operators.add(ADMIN_CHAT_ID)
    return sorted(operators)


OPERATORS = parse_operators()
OPERATOR_GROUP_ID = int(OPERATOR_GROUP_ID_RAW) if OPERATOR_GROUP_ID_RAW else None


def is_operator(chat_id: int) -> bool:
    return chat_id in OPERATORS


def is_admin_or_operator(update: Update) -> bool:
    chat_id = update.effective_chat.id if update.effective_chat else None
    return bool(chat_id and is_operator(chat_id))


# ================== STORAGE HELPERS ==================
def get_sessions(app) -> dict:
    if SESSIONS_KEY not in app.bot_data:
        app.bot_data[SESSIONS_KEY] = {}
    return app.bot_data[SESSIONS_KEY]


def get_profiles(app) -> dict:
    if USER_PROFILES_KEY not in app.bot_data:
        app.bot_data[USER_PROFILES_KEY] = {}
    return app.bot_data[USER_PROFILES_KEY]


def get_notif_map(app) -> dict:
    if NOTIF_MAP_KEY not in app.bot_data:
        app.bot_data[NOTIF_MAP_KEY] = {}
    return app.bot_data[NOTIF_MAP_KEY]


# ================== UI ==================
def main_keyboard() -> ReplyKeyboardMarkup:
    kb = [
        [KeyboardButton("🛍 OrzuMall.uz", web_app=WebAppInfo(url=WEB_APP_URL))],
        [KeyboardButton("🔎 Bizda yo‘q mahsulotni topish")],
        [KeyboardButton("📞 Bog'lanish"), KeyboardButton("ℹ️ Ma'lumot")],
        [KeyboardButton("💬 Chat")],
    ]
    return ReplyKeyboardMarkup(
        keyboard=kb,
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Tugmalardan tanlang…",
    )


def session_keyboard(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🙋 Men javob beraman", callback_data=f"claim:{user_id}"),
            InlineKeyboardButton("✅ Suhbatni yakunlash", callback_data=f"close:{user_id}"),
        ]
    ])


ABOUT_TEXT = (
    "<b>🛒 OrzuMall.uz</b> — qulay va tezkor online xaridlar markazi.\n\n"
    "✅ Mahsulotlar\n"
    "🚚 Yetkazib berish\n"
    "💳 Xavfsiz to‘lov\n"
    "📲 Barchasi bitta bot orqali\n\n"
    "🔎 <b>Bizda yo‘q mahsulotni topish</b> tugmasi orqali rasm, video yoki nom yuboring — operator sizga taxminiy narx va yetkazib berish muddatini aytadi."
)

CONTACT_TEXT = (
    "<b>📞 Bog'lanish</b>\n"
    "Bot: @OrzuMallUZ_bot\n"
    "Telefon: +998 XX XXX XX XX\n"
    "Ish vaqti: 09:00–21:00"
)

WELCOME_TEXT = (
    "Assalomu alaykum! 👋\n"
    "OrzuMall botiga xush kelibsiz.\n\n"
    "Pastdagi tugmalar orqali davom eting 👇"
)

SEARCH_INTRO_TEXT = (
    "<b>🔎 Bizda yo‘q mahsulotni topish</b>\n\n"
    "Mahsulot rasmi, videosi yoki nomini yuboring.\n"
    "Operator sizga: \n"
    "• taxminiy umumiy summa\n"
    "• tezkor yetkazib berish vaqti\n"
    "• olib kelish imkoniyati\n"
    "haqida javob beradi.\n\n"
    "Qancha ko‘p ma'lumot bersangiz, shuncha tez aniq javob olasiz."
)


# ================== HELPERS ==================
def user_display_name(user) -> str:
    if not user:
        return "User"
    name = " ".join(filter(None, [getattr(user, "first_name", None), getattr(user, "last_name", None)])).strip()
    return name or getattr(user, "full_name", None) or "User"


def profile_text(profile: dict) -> str:
    name = profile.get("full_name", "Noma'lum")
    username = profile.get("username") or "yo‘q"
    return f"👤 Ism: {name}\n🔗 Username: {username}"


def session_status_text(session: dict) -> str:
    status = session.get("status", "waiting")
    operator_id = session.get("operator_id")

    if status == "assigned" and operator_id:
        return f"🟢 Holat: operator biriktirilgan (<code>{operator_id}</code>)"
    if status == "closed":
        return "⚪ Holat: yopilgan"
    return "🟡 Holat: navbatda"


def session_topic_label(session: dict) -> str:
    topic = session.get("topic", "chat")
    if topic == "search_request":
        return "🔎 So‘rov turi: bizda yo‘q mahsulotni topish"
    return "💬 So‘rov turi: oddiy chat"


def build_operator_ticket_text(session: dict, profile: dict | None = None) -> str:
    user_id = session["user_id"]
    user_name = session.get("user_name", "User")
    username = session.get("username")
    status_line = session_status_text(session)

    uname = f"@{username}" if username else "yo‘q"
    last_messages = session.get("messages", [])[-5:]

    body = [
        "<b>💬 Yangi / faol chat</b>",
        session_topic_label(session),
        f"👤 {user_name}",
        f"🔗 Username: {uname}",
        f"🆔 USER_ID: <code>{user_id}</code>",
    ]

    if profile:
        body.append(f"ℹ️ Profil: {profile_text(profile).replace(chr(10), ' | ')}")

    body += [status_line, "", "<b>Oxirgi xabarlar:</b>"]

    if last_messages:
        for m in last_messages:
            body.append(f"• {m}")
    else:
        body.append("• Hozircha xabar yo‘q")

    if session.get("topic") == "search_request":
        body += ["", "<b>Operator uchun:</b>", "• Mahsulotni toping", "• Umumiy summani yozing", "• Yetkazib berish vaqtini ayting"]

    body.append("")
    body.append("<i>Operator tugma orqali chatni olishi yoki yopishi mumkin</i>")
    return "\n".join(body)


def ensure_user_session(sessions: dict, user, profile: dict, topic: str = "chat") -> dict:
    user_id = user.id
    session = sessions.get(user_id)

    if not session or session.get("status") == "closed":
        sessions[user_id] = {
            "user_id": user_id,
            "user_name": profile.get("full_name") or user_display_name(user),
            "username": user.username,
            "status": "waiting",
            "operator_id": None,
            "messages": [],
            "topic": topic,
        }
        return sessions[user_id]

    if topic == "search_request":
        session["topic"] = "search_request"
    elif "topic" not in session:
        session["topic"] = "chat"

    return session


# ================== SAFE SEND ==================
async def safe_send_message(bot, chat_id: int, text: str, **kwargs):
    try:
        return await bot.send_message(chat_id=chat_id, text=text, **kwargs)
    except Forbidden:
        logger.warning("Forbidden: chat_id=%s bot blocked or no permission.", chat_id)
        return None
    except BadRequest as e:
        logger.error("BadRequest: chat_id=%s error=%s", chat_id, e)
        return None
    except RetryAfter as e:
        logger.warning("RetryAfter: %s seconds. chat_id=%s", e.retry_after, chat_id)
        return None
    except (TimedOut, NetworkError) as e:
        logger.warning("Network/Timeout: chat_id=%s error=%s", chat_id, e)
        return None
    except Exception as e:
        logger.exception("Unexpected error while sending message: chat_id=%s error=%s", chat_id, e)
        return None


async def safe_reply(update: Update, text: str, **kwargs):
    if not update.message:
        return None
    try:
        return await update.message.reply_text(text, **kwargs)
    except Forbidden:
        logger.warning("Forbidden on reply: user blocked bot.")
        return None
    except BadRequest as e:
        logger.error("BadRequest on reply: %s", e)
        return None
    except (TimedOut, NetworkError) as e:
        logger.warning("Network/Timeout on reply: %s", e)
        return None
    except Exception as e:
        logger.exception("Unexpected error on reply: %s", e)
        return None


# ================== OPERATOR NOTIFY ==================
async def notify_operators(context: ContextTypes.DEFAULT_TYPE, text: str, reply_markup=None, user_id: int | None = None):
    notif_map = get_notif_map(context.application)

    if OPERATOR_GROUP_ID:
        sent = await safe_send_message(
            context.bot,
            OPERATOR_GROUP_ID,
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup,
        )
        if sent and user_id:
            notif_map[f"{OPERATOR_GROUP_ID}:{sent.message_id}"] = user_id
        return

    for op_id in OPERATORS:
        sent = await safe_send_message(
            context.bot,
            op_id,
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup,
        )
        if sent and user_id:
            notif_map[f"{op_id}:{sent.message_id}"] = user_id


async def notify_operators_media(
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    caption_text: str,
    profile: dict | None = None,
    photo=None,
    video=None,
    audio=None,
    voice=None,
    document=None,
):
    reply_markup = session_keyboard(user_id)
    full_caption = caption_text
    if profile:
        full_caption += "\n" + profile_text(profile)

    notif_map = get_notif_map(context.application)

    async def _send_media(target_chat_id: int):
        if photo:
            return await context.bot.send_photo(target_chat_id, photo=photo, caption=full_caption[:1024], parse_mode=ParseMode.HTML, reply_markup=reply_markup)
        if video:
            return await context.bot.send_video(target_chat_id, video=video, caption=full_caption[:1024], parse_mode=ParseMode.HTML, reply_markup=reply_markup)
        if audio:
            return await context.bot.send_audio(target_chat_id, audio=audio, caption=full_caption[:1024], parse_mode=ParseMode.HTML, reply_markup=reply_markup)
        if voice:
            return await context.bot.send_voice(target_chat_id, voice=voice, caption=full_caption[:1024], parse_mode=ParseMode.HTML, reply_markup=reply_markup)
        if document:
            return await context.bot.send_document(target_chat_id, document=document, caption=full_caption[:1024], parse_mode=ParseMode.HTML, reply_markup=reply_markup)
        return None

    if OPERATOR_GROUP_ID:
        try:
            sent = await _send_media(OPERATOR_GROUP_ID)
            if sent:
                notif_map[f"{OPERATOR_GROUP_ID}:{sent.message_id}"] = user_id
        except Exception as e:
            logger.exception("Operator group media yuborilmadi: %s", e)
        return

    for op_id in OPERATORS:
        try:
            sent = await _send_media(op_id)
            if sent:
                notif_map[f"{op_id}:{sent.message_id}"] = user_id
        except Exception as e:
            logger.exception("Operatorga media yuborilmadi: %s", e)


# ================== SUPPORT COMMANDS ==================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data[CHAT_MODE_KEY] = False
    context.user_data[SEARCH_MODE_KEY] = False
    await safe_reply(update, WELCOME_TEXT, reply_markup=main_keyboard())


async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await safe_reply(update, "Menyu 👇", reply_markup=main_keyboard())


async def chat_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_chat or not update.effective_user:
        return

    user_id = update.effective_user.id
    profiles = get_profiles(context.application)
    profile = profiles.get(user_id)
    if not profile:
        profile = {
            "full_name": user_display_name(update.effective_user),
            "username": f"@{update.effective_user.username}" if update.effective_user.username else "yo‘q",
        }
        profiles[user_id] = profile

    context.user_data[SEARCH_MODE_KEY] = False

    sessions = get_sessions(context.application)
    session = ensure_user_session(sessions, update.effective_user, profile, topic="chat")

    if session.get("status") in ("waiting", "assigned"):
        session["topic"] = "chat"
        context.user_data[CHAT_MODE_KEY] = True
        await safe_reply(update, "💬 Chat rejimi yoqildi.\nSavolingizni yozing, operatorga yuboraman.", reply_markup=main_keyboard())


async def search_product_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_chat or not update.effective_user:
        return

    user_id = update.effective_user.id
    profiles = get_profiles(context.application)
    profile = profiles.get(user_id)
    if not profile:
        profile = {
            "full_name": user_display_name(update.effective_user),
            "username": f"@{update.effective_user.username}" if update.effective_user.username else "yo‘q",
        }
        profiles[user_id] = profile

    context.user_data[CHAT_MODE_KEY] = False

    sessions = get_sessions(context.application)
    session = ensure_user_session(sessions, update.effective_user, profile, topic="search_request")
    session["topic"] = "search_request"
    if session.get("status") == "closed":
        session["status"] = "waiting"
        session["operator_id"] = None

    context.user_data[SEARCH_MODE_KEY] = True
    await safe_reply(update, SEARCH_INTRO_TEXT, parse_mode=ParseMode.HTML, reply_markup=main_keyboard())


async def chat_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data[CHAT_MODE_KEY] = False
    context.user_data[SEARCH_MODE_KEY] = False
    await safe_reply(update, "✅ Chat rejimi o‘chirildi.", reply_markup=main_keyboard())


async def queue_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin_or_operator(update):
        return

    sessions = get_sessions(context.application)
    waiting = [s for s in sessions.values() if s.get("status") == "waiting"]

    if not waiting:
        await safe_reply(update, "Navbatda chat yo‘q.")
        return

    lines = ["<b>🟡 Navbatdagi chatlar:</b>"]
    for s in waiting[:20]:
        topic_icon = "🔎" if s.get("topic") == "search_request" else "💬"
        lines.append(f"• {topic_icon} {s.get('user_name', 'User')} — <code>{s['user_id']}</code>")

    await safe_reply(update, "\n".join(lines), parse_mode=ParseMode.HTML)


async def my_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin_or_operator(update):
        return

    op_id = update.effective_chat.id
    sessions = get_sessions(context.application)
    mine = [s for s in sessions.values() if s.get("status") == "assigned" and s.get("operator_id") == op_id]

    if not mine:
        await safe_reply(update, "Sizga biriktirilgan chat yo‘q.")
        return

    lines = ["<b>🟢 Sizga biriktirilgan chatlar:</b>"]
    for s in mine[:20]:
        topic_icon = "🔎" if s.get("topic") == "search_request" else "💬"
        lines.append(f"• {topic_icon} {s.get('user_name', 'User')} — <code>{s['user_id']}</code>")

    await safe_reply(update, "\n".join(lines), parse_mode=ParseMode.HTML)


async def done_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin_or_operator(update):
        return

    op_id = update.effective_chat.id
    user_id = context.user_data.get(ACTIVE_CHAT_USER_KEY)

    if not user_id:
        await safe_reply(update, "Avval biror chatni oling.")
        return

    sessions = get_sessions(context.application)
    session = sessions.get(user_id)

    if not session or session.get("status") != "assigned" or session.get("operator_id") != op_id:
        context.user_data.pop(ACTIVE_CHAT_USER_KEY, None)
        await safe_reply(update, "Bu chat sizga biriktirilmagan yoki yopilgan.")
        return

    session["status"] = "closed"
    session["operator_id"] = None
    context.user_data.pop(ACTIVE_CHAT_USER_KEY, None)

    await safe_send_message(context.bot, user_id, "✅ Suhbat yakunlandi.\nYana savolingiz bo‘lsa, <b>💬 Chat</b> yoki <b>🔎 Bizda yo‘q mahsulotni topish</b> tugmasini bosing.", parse_mode=ParseMode.HTML)
    await safe_reply(update, f"✅ Chat yakunlandi: <code>{user_id}</code>", parse_mode=ParseMode.HTML)


# ================== CALLBACKS ==================
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not update.effective_chat:
        return

    operator_chat_id = update.effective_chat.id
    real_operator_id = query.from_user.id if query.from_user else operator_chat_id

    if not is_operator(real_operator_id):
        await query.answer("Siz operator emassiz", show_alert=True)
        return

    data = query.data or ""
    if ":" not in data:
        await query.answer()
        return

    action, raw_user_id = data.split(":", 1)
    try:
        user_id = int(raw_user_id)
    except ValueError:
        await query.answer("Noto‘g‘ri user_id", show_alert=True)
        return

    sessions = get_sessions(context.application)
    profiles = get_profiles(context.application)
    session = sessions.get(user_id)

    if not session:
        await query.answer("Sessiya topilmadi", show_alert=True)
        return

    if action == "claim":
        if session.get("status") == "closed":
            await query.answer("Bu chat yopilgan", show_alert=True)
            return

        assigned_operator = session.get("operator_id")
        if assigned_operator and assigned_operator != real_operator_id:
            await query.answer("Bu chatni boshqa operator oldi", show_alert=True)
            return

        session["status"] = "assigned"
        session["operator_id"] = real_operator_id

        if context.application.user_data.get(real_operator_id) is None:
            context.application.user_data[real_operator_id] = {}
        context.application.user_data[real_operator_id][ACTIVE_CHAT_USER_KEY] = user_id

        ready_text = "👨‍💼 Operator ulandi.\nSavolingizni yozishingiz mumkin."
        if session.get("topic") == "search_request":
            ready_text = "👨‍💼 Operator ulandi.\nMahsulot bo‘yicha narx va yetkazib berish muddatini yozib beradi."
        await safe_send_message(context.bot, user_id, ready_text)

        new_text = build_operator_ticket_text(session, profiles.get(user_id))
        try:
            await query.edit_message_text(text=new_text, parse_mode=ParseMode.HTML, reply_markup=session_keyboard(user_id))
        except Exception:
            pass

        await query.answer("Chat sizga biriktirildi")
        return

    if action == "close":
        if session.get("status") == "closed":
            await query.answer("Allaqachon yopilgan")
            return

        assigned_operator = session.get("operator_id")
        if assigned_operator and assigned_operator != real_operator_id:
            await query.answer("Faqat biriktirilgan operator yopishi mumkin", show_alert=True)
            return

        session["status"] = "closed"
        session["operator_id"] = None

        if context.application.user_data.get(real_operator_id):
            if context.application.user_data[real_operator_id].get(ACTIVE_CHAT_USER_KEY) == user_id:
                context.application.user_data[real_operator_id].pop(ACTIVE_CHAT_USER_KEY, None)

        await safe_send_message(context.bot, user_id, "✅ Suhbat yakunlandi.\nYana savolingiz bo‘lsa, <b>💬 Chat</b> yoki <b>🔎 Bizda yo‘q mahsulotni topish</b> tugmasini bosing.", parse_mode=ParseMode.HTML)

        new_text = build_operator_ticket_text(session, profiles.get(user_id))
        try:
            await query.edit_message_text(text=new_text, parse_mode=ParseMode.HTML, reply_markup=session_keyboard(user_id))
        except Exception:
            pass

        await query.answer("Suhbat yopildi")
        return

    await query.answer()


# ================== MEDIA HANDLER ==================
async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_chat or not update.effective_user:
        return

    chat_id = update.effective_chat.id

    if is_operator(chat_id):
        active_user_id = context.user_data.get(ACTIVE_CHAT_USER_KEY)

        if update.message.reply_to_message:
            notif_map = get_notif_map(context.application)
            key = f"{chat_id}:{update.message.reply_to_message.message_id}"
            group_key = f"{OPERATOR_GROUP_ID}:{update.message.reply_to_message.message_id}" if OPERATOR_GROUP_ID else None
            mapped_user = notif_map.get(key) or (notif_map.get(group_key) if group_key else None)
            if mapped_user:
                active_user_id = mapped_user
                context.user_data[ACTIVE_CHAT_USER_KEY] = mapped_user

        if not active_user_id:
            await safe_reply(update, "Avval chatni oling yoki ticketga reply qiling.")
            return

        sessions = get_sessions(context.application)
        session = sessions.get(active_user_id)
        if not session or session.get("status") == "closed":
            await safe_reply(update, "Bu chat yopilgan yoki topilmadi.")
            return

        if session.get("operator_id") not in (None, chat_id):
            await safe_reply(update, "Bu chat boshqa operatorga biriktirilgan.")
            return

        if session.get("operator_id") is None:
            session["operator_id"] = chat_id
            session["status"] = "assigned"

        caption = update.message.caption or "👨‍💼 Operatordan media"

        try:
            if update.message.photo:
                await context.bot.send_photo(active_user_id, update.message.photo[-1].file_id, caption=caption)
            elif update.message.video:
                await context.bot.send_video(active_user_id, update.message.video.file_id, caption=caption)
            elif update.message.audio:
                await context.bot.send_audio(active_user_id, update.message.audio.file_id, caption=caption)
            elif update.message.voice:
                await context.bot.send_voice(active_user_id, update.message.voice.file_id, caption=caption)
            elif update.message.document:
                await context.bot.send_document(active_user_id, update.message.document.file_id, caption=caption)

            await safe_reply(update, "✅ Foydalanuvchiga yuborildi.")
        except Exception as e:
            logger.exception("Operator media userga yuborilmadi: %s", e)
            await safe_reply(update, "⚠️ Yuborilmadi.")
        return

    user = update.effective_user
    user_id = user.id
    profiles = get_profiles(context.application)
    profile = profiles.get(user_id)
    if not profile:
        profile = {
            "full_name": user_display_name(user),
            "username": f"@{user.username}" if user.username else "yo‘q",
        }
        profiles[user_id] = profile

    if not context.user_data.get(CHAT_MODE_KEY) and not context.user_data.get(SEARCH_MODE_KEY):
        await safe_reply(update, "Avval <b>💬 Chat</b> yoki <b>🔎 Bizda yo‘q mahsulotni topish</b> tugmasini bosing.", parse_mode=ParseMode.HTML, reply_markup=main_keyboard())
        return

    sessions = get_sessions(context.application)
    topic = "search_request" if context.user_data.get(SEARCH_MODE_KEY) else "chat"
    session = ensure_user_session(sessions, user, profile, topic=topic)

    media_note = "📎 Media yuborildi"
    if update.message.photo:
        media_note = "🖼 Rasm yuborildi"
    elif update.message.video:
        media_note = "🎥 Video yuborildi"
    elif update.message.audio:
        media_note = "🎵 Audio yuborildi"
    elif update.message.voice:
        media_note = "🎤 Voice yuborildi"
    elif update.message.document:
        media_note = "📄 Fayl yuborildi"

    if update.message.caption:
        media_note += f": {update.message.caption}"

    session["messages"].append(media_note)

    if session.get("topic") == "search_request":
        caption_text = (
            "<b>🔎 Bizda yo‘q mahsulot so‘rovi keldi</b>\n"
            f"🆔 USER_ID: <code>{user_id}</code>\n"
            f"👤 {profile.get('full_name', user_display_name(user))}\n"
            "<b>Vazifa:</b> narx + yetkazib berish muddatini yozing."
        )
        user_ok_text = "✅ So‘rovingiz qabul qilindi.\nOperator mahsulotni ko‘rib, sizga umumiy summa va yetkazib berish vaqtini yozadi."
    else:
        caption_text = (
            "<b>💬 Userdan media keldi</b>\n"
            f"🆔 USER_ID: <code>{user_id}</code>\n"
            f"👤 {profile.get('full_name', user_display_name(user))}\n"
        )
        user_ok_text = "✅ Media operatorga yuborildi.\nJavob kelishini kuting."

    await notify_operators_media(
        context=context,
        user_id=user_id,
        caption_text=caption_text,
        profile=profile,
        photo=update.message.photo[-1].file_id if update.message.photo else None,
        video=update.message.video.file_id if update.message.video else None,
        audio=update.message.audio.file_id if update.message.audio else None,
        voice=update.message.voice.file_id if update.message.voice else None,
        document=update.message.document.file_id if update.message.document else None,
    )

    await safe_reply(update, user_ok_text, reply_markup=main_keyboard())


# ================== TEXT HANDLER ==================
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_chat:
        return

    text = (update.message.text or "").strip()
    chat_id = update.effective_chat.id

    if is_operator(chat_id):
        active_user_id = context.user_data.get(ACTIVE_CHAT_USER_KEY)

        if update.message.reply_to_message:
            notif_map = get_notif_map(context.application)
            key = f"{chat_id}:{update.message.reply_to_message.message_id}"
            group_key = f"{OPERATOR_GROUP_ID}:{update.message.reply_to_message.message_id}" if OPERATOR_GROUP_ID else None
            mapped_user = notif_map.get(key) or (notif_map.get(group_key) if group_key else None)
            if mapped_user:
                active_user_id = mapped_user
                context.user_data[ACTIVE_CHAT_USER_KEY] = mapped_user

        if text in ("📞 Bog'lanish", "ℹ️ Ma'lumot", "💬 Chat", "🛍 OrzuMall.uz", "🔎 Bizda yo‘q mahsulotni topish"):
            await safe_reply(update, "Operator panelida bu tugmalar ishlatilmaydi.")
            return

        if active_user_id:
            sessions = get_sessions(context.application)
            session = sessions.get(active_user_id)

            if not session:
                context.user_data.pop(ACTIVE_CHAT_USER_KEY, None)
                await safe_reply(update, "Chat topilmadi.")
                return

            if session.get("status") == "closed":
                context.user_data.pop(ACTIVE_CHAT_USER_KEY, None)
                await safe_reply(update, "Bu chat yopilgan.")
                return

            if session.get("operator_id") not in (None, chat_id):
                await safe_reply(update, "Bu chat boshqa operatorga biriktirilgan.")
                return

            if session.get("operator_id") is None:
                session["operator_id"] = chat_id
                session["status"] = "assigned"

            prefix = "👨‍💼 Operator"
            if session.get("topic") == "search_request":
                prefix = "👨‍💼 Mahsulot bo‘yicha javob"
            sent = await safe_send_message(context.bot, active_user_id, f"{prefix}:\n{text}")
            if sent:
                await safe_reply(update, "✅ Foydalanuvchiga yuborildi.")
            else:
                await safe_reply(update, "⚠️ Yuborilmadi.")
            return

        await safe_reply(update, "Sizda aktiv chat yo‘q.\nTugma orqali chatni oling yoki /queue va /my ni tekshiring.")
        return

    if text == "📞 Bog'lanish":
        context.user_data[CHAT_MODE_KEY] = False
        context.user_data[SEARCH_MODE_KEY] = False
        await safe_reply(update, CONTACT_TEXT, parse_mode=ParseMode.HTML, reply_markup=main_keyboard())
        return

    if text == "ℹ️ Ma'lumot":
        context.user_data[CHAT_MODE_KEY] = False
        context.user_data[SEARCH_MODE_KEY] = False
        await safe_reply(update, ABOUT_TEXT, parse_mode=ParseMode.HTML, reply_markup=main_keyboard())
        return

    if text == "💬 Chat":
        await chat_on(update, context)
        return

    if text == "🔎 Bizda yo‘q mahsulotni topish":
        await search_product_on(update, context)
        return

    user = update.effective_user
    user_id = user.id if user else chat_id
    profiles = get_profiles(context.application)
    profile = profiles.get(user_id)
    if not profile:
        profile = {
            "full_name": user_display_name(user),
            "username": f"@{user.username}" if user and user.username else "yo‘q",
        }
        profiles[user_id] = profile

    if context.user_data.get(SEARCH_MODE_KEY) is True and text not in ("🛍 OrzuMall.uz", "📞 Bog'lanish", "ℹ️ Ma'lumot", "💬 Chat", "🔎 Bizda yo‘q mahsulotni topish"):
        sessions = get_sessions(context.application)
        session = ensure_user_session(sessions, user, profile, topic="search_request")
        session["messages"].append(f"🔎 Mahsulot so‘rovi: {text}")

        ticket_text = build_operator_ticket_text(session, profile)
        await notify_operators(context, ticket_text, reply_markup=session_keyboard(user_id), user_id=user_id)

        await safe_reply(update, "✅ So‘rovingiz operatorga yuborildi.\nTez orada sizga taxminiy umumiy summa va yetkazib berish muddati yoziladi.", reply_markup=main_keyboard())
        return

    if context.user_data.get(CHAT_MODE_KEY) is True and text not in ("🛍 OrzuMall.uz", "📞 Bog'lanish", "ℹ️ Ma'lumot", "💬 Chat", "🔎 Bizda yo‘q mahsulotni topish"):
        sessions = get_sessions(context.application)
        session = ensure_user_session(sessions, user, profile, topic="chat")

        if session.get("status") == "closed":
            session["status"] = "waiting"
            session["operator_id"] = None
            session["messages"] = []
            session["topic"] = "chat"

        session["messages"].append(text)

        ticket_text = build_operator_ticket_text(session, profile)
        await notify_operators(context, ticket_text, reply_markup=session_keyboard(user_id), user_id=user_id)

        await safe_reply(update, "✅ Xabaringiz operatorga yuborildi.\nJavob kelishini kuting.", reply_markup=main_keyboard())
        return

    await safe_reply(update, "Tugmalardan foydalaning 👇", reply_markup=main_keyboard())


# ================== ERROR HANDLER ==================
async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.exception("Global error handler: %s", context.error)


# ================== MAIN ==================
def main():
    if not BOT_TOKEN:
        print("\n❌ BOT_TOKEN topilmadi.")
        print("PowerShell:  $env:BOT_TOKEN=\"YOUR_TOKEN\"  ;  python bot.py\n")
        raise SystemExit(1)

    logger.info("Operators: %s", OPERATORS)
    logger.info("Operator group: %s", OPERATOR_GROUP_ID)

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu))
    app.add_handler(CommandHandler("chat_on", chat_on))
    app.add_handler(CommandHandler("chat_off", chat_off))
    app.add_handler(CommandHandler("queue", queue_command))
    app.add_handler(CommandHandler("my", my_command))
    app.add_handler(CommandHandler("done", done_command))

    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO | filters.AUDIO | filters.VOICE | filters.Document.ALL, handle_media))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    app.add_error_handler(on_error)

    logger.info("✅ OrzuMall bot ishga tushdi. CTRL+C bilan to'xtatasiz.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
