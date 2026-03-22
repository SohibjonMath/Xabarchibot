import json
import logging
import os
import random
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ChatMemberHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    MessageReactionHandler,
    filters,
)

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("OrzuMallXabarchi")

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

TZ = os.getenv("TZ", "Asia/Tashkent").strip()
ZONE = ZoneInfo(TZ)

CONTEST_CHAT_ID = os.getenv("CONTEST_CHAT_ID", "").strip()
INVITE_CHAT_ID = os.getenv("INVITE_CHAT_ID", CONTEST_CHAT_ID).strip()

MORNING_HOUR = int(os.getenv("MORNING_HOUR", "6"))
MORNING_MINUTE = int(os.getenv("MORNING_MINUTE", "0"))

WINNER_HOUR = int(os.getenv("WINNER_HOUR", "20"))
WINNER_MINUTE = int(os.getenv("WINNER_MINUTE", "0"))

TOP_HOUR = int(os.getenv("TOP_HOUR", "21"))
TOP_MINUTE = int(os.getenv("TOP_MINUTE", "0"))

RANKING_CUTOFF_HOUR = int(os.getenv("RANKING_CUTOFF_HOUR", "21"))
RANKING_CUTOFF_MINUTE = int(os.getenv("RANKING_CUTOFF_MINUTE", "0"))

ADMIN_USER_IDS = [
    int(x.strip()) for x in os.getenv("ADMIN_USER_IDS", "").split(",") if x.strip()
]

DISCOUNT_PERCENT = int(os.getenv("DISCOUNT_PERCENT", "25"))
DISCOUNT_MAX_SUM = int(os.getenv("DISCOUNT_MAX_SUM", "1000000"))
DISCOUNT_HOURS = int(os.getenv("DISCOUNT_HOURS", "72"))
WINNER_COOLDOWN_DAYS = int(os.getenv("WINNER_COOLDOWN_DAYS", "30"))

INVITE_RETENTION_DAYS = int(os.getenv("INVITE_RETENTION_DAYS", "90"))

STATE_DIR = Path(os.getenv("STATE_DIR", "./data"))
STATE_DIR.mkdir(parents=True, exist_ok=True)
STATE_FILE = STATE_DIR / "bot_state.json"

MAX_MESSAGE_LEN = 3800


def tz_now() -> datetime:
    return datetime.now(ZONE)


def is_admin(user_id: int | None) -> bool:
    return user_id is not None and user_id in ADMIN_USER_IDS


def format_money(n: int) -> str:
    return f"{n:,}".replace(",", " ")


def html_escape(s: str) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def mention_html(user_id: int, label: str) -> str:
    return f'<a href="tg://user?id={user_id}">{html_escape(label)}</a>'


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            logger.exception("State o'qilmadi")
    return {
        "current_post_id": None,
        "current_post_date": None,
        "participants": [],
        "participants_meta": {},
        "discounts": {},
        "winner_history": {},
        "invite_links": {},
        "invite_joins": [],
    }


STATE = load_state()


def save_state() -> None:
    STATE_FILE.write_text(
        json.dumps(STATE, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def remember_user(user) -> None:
    if not user or getattr(user, "is_bot", False):
        return
    STATE.setdefault("participants_meta", {})[str(user.id)] = {
        "username": getattr(user, "username", None),
        "first_name": getattr(user, "first_name", None),
        "last_name": getattr(user, "last_name", None),
    }
    save_state()


def display_name_for(uid: int, fallback: str | None = None) -> str:
    meta = STATE.get("participants_meta", {}).get(str(uid), {})
    username = meta.get("username")
    first_name = meta.get("first_name")
    last_name = meta.get("last_name")

    if username:
        return f"@{username}"

    full = " ".join(x for x in [first_name, last_name] if x).strip()
    if full:
        return full

    if fallback:
        return fallback

    return str(uid)


def label_with_you(label: str, target_uid: int | str, viewer_uid: int | None) -> str:
    try:
        if viewer_uid is not None and int(target_uid) == int(viewer_uid):
            return f"{label} (SIZ)"
    except Exception:
        pass
    return label


def cleanup_expired_discounts() -> None:
    now = tz_now()
    discounts = STATE.get("discounts", {})
    to_delete = []

    for uid, item in discounts.items():
        if item.get("used"):
            to_delete.append(uid)
            continue
        try:
            exp = datetime.fromisoformat(item["expires_at"])
            if exp <= now:
                to_delete.append(uid)
        except Exception:
            to_delete.append(uid)

    for uid in to_delete:
        discounts.pop(uid, None)

    if to_delete:
        save_state()


def cleanup_old_invites() -> None:
    now = tz_now()
    keep = []
    for item in STATE.get("invite_joins", []):
        try:
            ts = datetime.fromisoformat(item["ts"])
            if ts > now - timedelta(days=INVITE_RETENTION_DAYS):
                keep.append(item)
        except Exception:
            continue
    if keep != STATE.get("invite_joins", []):
        STATE["invite_joins"] = keep
        save_state()


def already_recent_winner(user_id: int) -> bool:
    raw = STATE.get("winner_history", {}).get(str(user_id))
    if not raw:
        return False
    try:
        dt = datetime.fromisoformat(raw)
        return dt > (tz_now() - timedelta(days=WINNER_COOLDOWN_DAYS))
    except Exception:
        return False


def register_invite_join(
    inviter_id: int,
    inviter_label: str,
    joined_id: int,
    joined_label: str,
    source: str,
) -> None:
    if inviter_id == joined_id:
        return

    # global duplicate: bir user bir marta hisoblanadi
    for item in STATE.get("invite_joins", []):
        if str(item.get("joined_id")) == str(joined_id):
            return

    STATE.setdefault("invite_joins", []).append(
        {
            "ts": tz_now().isoformat(),
            "inviter_id": inviter_id,
            "joined_id": joined_id,
            "inviter_label": inviter_label,
            "joined_label": joined_label,
            "source": source,
        }
    )
    save_state()


def ranking_anchor_for(dt: datetime) -> datetime:
    anchor = dt.replace(
        hour=RANKING_CUTOFF_HOUR,
        minute=RANKING_CUTOFF_MINUTE,
        second=0,
        microsecond=0,
    )
    if dt < anchor:
        anchor -= timedelta(days=1)
    return anchor


def active_window_bounds(now: datetime | None = None) -> tuple[datetime, datetime]:
    now = now or tz_now()
    start = ranking_anchor_for(now)
    end = start + timedelta(days=1)
    return start, end


def closed_window_bounds(days_ago: int = 0, now: datetime | None = None) -> tuple[datetime, datetime]:
    now = now or tz_now()
    active_start, _ = active_window_bounds(now)
    end = active_start - timedelta(days=days_ago)
    start = end - timedelta(days=1)
    return start, end


def score_events_between(start: datetime, end: datetime) -> list[tuple[str, int, str]]:
    cleanup_old_invites()

    scored: dict[str, int] = {}
    labels: dict[str, str] = {}

    for item in STATE.get("invite_joins", []):
        try:
            ts = datetime.fromisoformat(item["ts"])
        except Exception:
            continue

        if ts < start or ts >= end:
            continue

        inviter_id = str(item["inviter_id"])
        inviter_label = str(item.get("inviter_label") or inviter_id)

        scored[inviter_id] = scored.get(inviter_id, 0) + 1

        if inviter_label and not inviter_label.isdigit():
            labels[inviter_id] = inviter_label
        else:
            try:
                labels[inviter_id] = display_name_for(int(inviter_id), inviter_label)
            except Exception:
                labels[inviter_id] = inviter_label

    return sorted(
        [(uid, count, labels.get(uid, uid)) for uid, count in scored.items()],
        key=lambda x: (-x[1], x[0]),
    )


def ranking_title(start: datetime, end: datetime) -> str:
    return (
        f"📊 <b>REYTING</b>\n"
        f"<b>{start.strftime('%d.%m %H:%M')}</b> → <b>{end.strftime('%d.%m %H:%M')}</b>"
    )


def ranking_lines(ranking: list[tuple[str, int, str]], viewer_uid: int | None = None) -> list[str]:
    if not ranking:
        return ["Hozircha natija yo'q."]

    lines = []
    badges = ["🥇", "🥈", "🥉"]

    for i, (uid, count, raw_label) in enumerate(ranking, start=1):
        prefix = badges[i - 1] if i <= 3 else f"{i}."
        shown = label_with_you(raw_label, uid, viewer_uid)

        if str(raw_label).startswith("@"):
            label_html = html_escape(shown)
        else:
            try:
                label_html = mention_html(int(uid), shown)
            except Exception:
                label_html = html_escape(shown)

        lines.append(f"{prefix} {label_html} — <b>{count} ta</b> odam")

    return lines


def chunk_lines(header: str, lines: list[str], footer: str | None = None) -> list[str]:
    parts = []
    current = header + "\n\n"

    for line in lines:
        candidate = current + line + "\n"
        if len(candidate) > MAX_MESSAGE_LEN:
            if footer:
                current += "\n" + footer
            parts.append(current.strip())
            current = header + "\n\n" + line + "\n"
        else:
            current = candidate

    if footer:
        current += "\n" + footer

    parts.append(current.strip())
    return parts


async def send_long_reply(update: Update, header: str, lines: list[str], footer: str | None = None) -> None:
    parts = chunk_lines(header, lines, footer)
    for msg in parts:
        if update.callback_query:
            await update.callback_query.message.reply_text(
                msg,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        elif update.message:
            await update.message.reply_text(
                msg,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )


async def send_long_to_chat(bot, chat_id: str, header: str, lines: list[str], footer: str | None = None) -> None:
    parts = chunk_lines(header, lines, footer)
    for msg in parts:
        await bot.send_message(
            chat_id=chat_id,
            text=msg,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )


def contest_post_text() -> str:
    return (
        "🎁 <b>BUGUNGI MUSOBAQA BOSHLANDI!</b>\n\n"
        f"Bugun 1 ta omadli ishtirokchi <b>{DISCOUNT_PERCENT}% skidka</b> yutadi.\n\n"
        "<b>Qatnashish:</b>\n"
        "1️⃣ Shu postga reaksiya qoldiring\n"
        "2️⃣ Guruhda qoling\n\n"
        f"⏰ Natija bugun <b>{WINNER_HOUR:02d}:{WINNER_MINUTE:02d}</b> da e'lon qilinadi.\n\n"
        "<b>Skidka shartlari:</b>\n"
        "• Faqat 1 martalik\n"
        f"• Maksimal {format_money(DISCOUNT_MAX_SUM)} so'mgacha xaridlar uchun\n"
        f"• {DISCOUNT_HOURS} soat amal qiladi\n\n"
        "💬 Omad hammaga!"
    )


def winner_post_text(winner_id: int) -> str:
    label = display_name_for(winner_id)
    return (
        "🏆 <b>BUGUNGI G‘OLIB ANIQLANDI!</b>\n\n"
        f"🎉 Tabriklaymiz: {mention_html(winner_id, label)}\n\n"
        f"Sizga <b>{DISCOUNT_PERCENT}% skidka</b> berildi.\n\n"
        "<b>Shartlar:</b>\n"
        "• Faqat 1 martalik\n"
        f"• Maksimal {format_money(DISCOUNT_MAX_SUM)} so'mgacha xarid uchun\n"
        f"• {DISCOUNT_HOURS} soat amal qiladi\n\n"
        "📩 Buyurtma uchun admin bilan bog'laning."
    )


def admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🎁 Musobaqa posti", callback_data="postnow"),
                InlineKeyboardButton("🏆 G'olib tanlash", callback_data="drawnow"),
            ],
            [
                InlineKeyboardButton("📊 Joriy reyting", callback_data="top_active"),
                InlineKeyboardButton("📆 3 kunlik", callback_data="top3days"),
            ],
            [
                InlineKeyboardButton("📌 Bugungi holat", callback_data="today"),
                InlineKeyboardButton("💰 Faol skidkalar", callback_data="discounts"),
            ],
            [
                InlineKeyboardButton("🔗 Mening referralim", callback_data="myref"),
                InlineKeyboardButton("⚙️ Status", callback_data="status"),
            ],
            [InlineKeyboardButton("ℹ️ Yordam", callback_data="help")],
        ]
    )


def user_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🔗 Mening referralim", callback_data="myref"),
                InlineKeyboardButton("📊 Joriy reyting", callback_data="top_active"),
            ],
            [InlineKeyboardButton("📆 3 kunlik", callback_data="top3days")],
            [InlineKeyboardButton("ℹ️ Yordam", callback_data="help")],
        ]
    )


def menu_for(user_id: int | None) -> InlineKeyboardMarkup:
    return admin_keyboard() if is_admin(user_id) else user_keyboard()


HELP_TEXT = (
    "🤖 <b>OrzuMall Xabarchi</b>\n\n"
    "• 06:00 da contest post\n"
    "• 20:00 da random g'olib\n"
    "• 21:00 → 21:00 reyting\n"
    "• Referral + kontaktdan qo'shish hisobi\n"
    "• 3 kunlik natijalar"
)


async def reply_text(update: Update, text: str, **kwargs) -> None:
    if update.callback_query:
        await update.callback_query.message.reply_text(text, **kwargs)
    elif update.message:
        await update.message.reply_text(text, **kwargs)


async def send_menu(update: Update, text: str) -> None:
    markup = menu_for(update.effective_user.id if update.effective_user else None)
    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=markup,
                disable_web_page_preview=True,
            )
            return
        except Exception:
            pass
        await update.callback_query.message.reply_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=markup,
            disable_web_page_preview=True,
        )
    elif update.message:
        await update.message.reply_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=markup,
            disable_web_page_preview=True,
        )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user:
        remember_user(update.effective_user)
    await send_menu(update, HELP_TEXT)


async def help_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user:
        remember_user(update.effective_user)
    await send_menu(update, HELP_TEXT)


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cleanup_expired_discounts()
    cleanup_old_invites()
    active_start, active_end = active_window_bounds()

    text = (
        "<b>⚙️ Joriy sozlamalar</b>\n\n"
        f"• CONTEST_CHAT_ID: <code>{html_escape(CONTEST_CHAT_ID or 'kiritilmagan')}</code>\n"
        f"• INVITE_CHAT_ID: <code>{html_escape(INVITE_CHAT_ID or 'kiritilmagan')}</code>\n"
        f"• Contest posti: <b>{MORNING_HOUR:02d}:{MORNING_MINUTE:02d}</b>\n"
        f"• Winner: <b>{WINNER_HOUR:02d}:{WINNER_MINUTE:02d}</b>\n"
        f"• Reyting post: <b>{TOP_HOUR:02d}:{TOP_MINUTE:02d}</b>\n"
        f"• Reyting oynasi: <b>{active_start.strftime('%d.%m %H:%M')}</b> → <b>{active_end.strftime('%d.%m %H:%M')}</b>\n"
        f"• Invite events: <b>{len(STATE.get('invite_joins', []))}</b>\n"
        f"• Faol skidkalar: <b>{len(STATE.get('discounts', []))}</b>\n"
        f"• TZ: <b>{TZ}</b>"
    )
    await reply_text(update, text, parse_mode=ParseMode.HTML)


async def contest_post(context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not CONTEST_CHAT_ID:
        logger.warning("CONTEST_CHAT_ID yo'q.")
        return False

    cleanup_expired_discounts()
    STATE["participants"] = []
    STATE["current_post_date"] = tz_now().date().isoformat()

    try:
        msg = await context.bot.send_message(
            chat_id=CONTEST_CHAT_ID,
            text=contest_post_text(),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
        STATE["current_post_id"] = msg.message_id
        save_state()
        return True
    except Exception:
        logger.exception("Contest posti yuborilmadi")
        return False


async def reaction_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        reaction = update.message_reaction
        if not reaction or str(reaction.chat.id) != str(CONTEST_CHAT_ID):
            return
        if reaction.message_id != STATE.get("current_post_id"):
            return

        actor = reaction.user
        if not actor or actor.is_bot:
            return

        remember_user(actor)
        participants = set(STATE.get("participants", []))
        participants.add(actor.id)
        STATE["participants"] = list(participants)
        save_state()
    except Exception:
        logger.exception("Reaction handler xato")


async def draw_winner(context: ContextTypes.DEFAULT_TYPE) -> tuple[bool, str]:
    if not CONTEST_CHAT_ID:
        return False, "CONTEST_CHAT_ID kiritilmagan."

    cleanup_expired_discounts()
    participant_ids = [int(x) for x in STATE.get("participants", [])]
    eligible = [uid for uid in participant_ids if not already_recent_winner(uid)]

    if not participant_ids:
        try:
            await context.bot.send_message(
                chat_id=CONTEST_CHAT_ID,
                text="Bugun hali hech kim reaksiya qoldirmadi.",
            )
        except Exception:
            logger.exception("Contest chatga xabar yuborilmadi")
        return False, "Ishtirokchilar yo'q."

    if not eligible:
        return False, "Cooldown sababli g'olib yo'q."

    winner_id = random.choice(eligible)
    now = tz_now()
    expires_at = now + timedelta(hours=DISCOUNT_HOURS)

    STATE.setdefault("discounts", {})[str(winner_id)] = {
        "user_id": winner_id,
        "label": display_name_for(winner_id),
        "discount_percent": DISCOUNT_PERCENT,
        "max_amount": DISCOUNT_MAX_SUM,
        "issued_at": now.isoformat(),
        "expires_at": expires_at.isoformat(),
        "used": False,
    }
    STATE.setdefault("winner_history", {})[str(winner_id)] = now.isoformat()
    save_state()

    try:
        await context.bot.send_message(
            chat_id=CONTEST_CHAT_ID,
            text=winner_post_text(winner_id),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception:
        logger.exception("Winner xabari yuborilmadi")
        return False, "G'olib tanlandi, lekin xabar yuborilmadi."

    return True, "✅ G'olib tanlandi."


async def myref(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user:
        return
    remember_user(user)

    if not INVITE_CHAT_ID:
        await reply_text(update, "❌ INVITE_CHAT_ID kiritilmagan.")
        return

    old = STATE.get("invite_links", {}).get(str(user.id))
    if old and old.get("invite_link"):
        await reply_text(
            update,
            f"🔗 <b>Sizning taklif havolangiz:</b>\n\n<code>{html_escape(old['invite_link'])}</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    try:
        link = await context.bot.create_chat_invite_link(
            chat_id=INVITE_CHAT_ID,
            name=f"ref_{user.id}",
            creates_join_request=False,
        )
        STATE.setdefault("invite_links", {})[str(user.id)] = {
            "invite_link": link.invite_link,
            "created_at": tz_now().isoformat(),
            "name": getattr(link, "name", None),
        }
        save_state()

        await reply_text(
            update,
            f"🔗 <b>Sizning taklif havolangiz:</b>\n\n<code>{html_escape(link.invite_link)}</code>",
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        logger.exception("Referral link yaratilmadi")
        await reply_text(update, "Referral havolani yaratib bo'lmadi.")


async def new_members_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.message
    if not msg or str(msg.chat.id) != str(INVITE_CHAT_ID) or not msg.new_chat_members:
        return

    inviter = msg.from_user
    if inviter:
        remember_user(inviter)

    for member in msg.new_chat_members:
        if member.is_bot:
            continue
        remember_user(member)

        if inviter and not inviter.is_bot and inviter.id != member.id:
            register_invite_join(
                inviter_id=inviter.id,
                inviter_label=display_name_for(inviter.id),
                joined_id=member.id,
                joined_label=display_name_for(member.id),
                source="direct_add",
            )


async def chat_member_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cmu = update.chat_member
    if not cmu or str(cmu.chat.id) != str(INVITE_CHAT_ID):
        return

    joined_user = getattr(cmu.new_chat_member, "user", None)
    if not joined_user or joined_user.is_bot:
        return

    old_status = getattr(cmu.old_chat_member, "status", None)
    new_status = getattr(cmu.new_chat_member, "status", None)

    # old_status None bo'lsa ham join deb olamiz
    joined_now = new_status in ("member", "administrator", "restricted") and old_status != new_status
    if not joined_now:
        return

    remember_user(joined_user)

    inv_link = getattr(cmu, "invite_link", None)
    if inv_link and getattr(inv_link, "name", None):
        name = inv_link.name or ""
        if name.startswith("ref_"):
            try:
                inviter_id = int(name.split("_", 1)[1])
                register_invite_join(
                    inviter_id=inviter_id,
                    inviter_label=display_name_for(inviter_id),
                    joined_id=joined_user.id,
                    joined_label=display_name_for(joined_user.id),
                    source="personal_link",
                )
            except Exception:
                logger.exception("Invite link parse bo'lmadi")


async def top_active(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    start, end = active_window_bounds()
    ranking = score_events_between(start, end)
    header = ranking_title(start, end)
    lines = ranking_lines(ranking, update.effective_user.id if update.effective_user else None)
    await send_long_reply(update, header, lines, "🔗 Referral havola: /myref")


async def top_prev(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    start, end = closed_window_bounds(0)
    ranking = score_events_between(start, end)
    header = ranking_title(start, end)
    lines = ranking_lines(ranking, update.effective_user.id if update.effective_user else None)
    await send_long_reply(update, header, lines)


async def top3days(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    viewer_uid = update.effective_user.id if update.effective_user else None

    for days_ago in range(0, 3):
        start, end = closed_window_bounds(days_ago)
        ranking = score_events_between(start, end)
        header = ranking_title(start, end)
        lines = ranking_lines(ranking, viewer_uid)
        await send_long_reply(update, header, lines)


async def post_top_daily(context: ContextTypes.DEFAULT_TYPE) -> None:
    if not INVITE_CHAT_ID:
        return

    start, end = closed_window_bounds(0)
    ranking = score_events_between(start, end)
    header = ranking_title(start, end)
    lines = ranking_lines(ranking)
    await send_long_to_chat(
        context.bot,
        INVITE_CHAT_ID,
        header,
        lines,
        "🔗 Referral havolangiz uchun: /myref",
    )


async def today(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    active_start, active_end = active_window_bounds()
    prev_start, prev_end = closed_window_bounds(0)

    text = (
        "📌 <b>Bugungi holat</b>\n\n"
        f"• Contest sana: <b>{STATE.get('current_post_date') or 'yo‘q'}</b>\n"
        f"• Contest post ID: <code>{STATE.get('current_post_id') or 'yo‘q'}</code>\n"
        f"• Contest ishtirokchilari: <b>{len(STATE.get('participants', []))}</b>\n"
        f"• Invite join eventlar: <b>{len(STATE.get('invite_joins', []))}</b>\n\n"
        f"• Joriy reyting oynasi:\n"
        f"<b>{active_start.strftime('%d.%m %H:%M')}</b> → <b>{active_end.strftime('%d.%m %H:%M')}</b>\n\n"
        f"• Oxirgi yopilgan oyna:\n"
        f"<b>{prev_start.strftime('%d.%m %H:%M')}</b> → <b>{prev_end.strftime('%d.%m %H:%M')}</b>"
    )
    await reply_text(update, text, parse_mode=ParseMode.HTML)


async def discounts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cleanup_expired_discounts()
    items = STATE.get("discounts", {})
    if not items:
        await reply_text(update, "Faol skidkalar yo'q.")
        return

    now = tz_now()
    lines = ["📊 <b>Faol skidkalar</b>\n"]

    for uid, item in items.items():
        try:
            exp = datetime.fromisoformat(item["expires_at"])
        except Exception:
            continue

        remain = exp - now
        total_sec = int(remain.total_seconds())
        if total_sec <= 0:
            continue

        hours = total_sec // 3600
        minutes = (total_sec % 3600) // 60
        label = item.get("label") or display_name_for(int(uid))

        lines.append(
            f"• {mention_html(int(uid), label)}\n"
            f"  └ {item['discount_percent']}% | max {format_money(item['max_amount'])} so'm | {hours} soat {minutes} daqiqa qoldi"
        )

    await reply_text(update, "\n".join(lines), parse_mode=ParseMode.HTML, disable_web_page_preview=True)


async def postnow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ok = await contest_post(context)
    await reply_text(update, "✅ Contest posti yuborildi." if ok else "❌ Contest posti yuborilmadi.")


async def drawnow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ok, message = await draw_winner(context)
    await reply_text(update, message)


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return

    data = query.data
    user_id = update.effective_user.id if update.effective_user else None

    admin_buttons = {"postnow", "drawnow", "today", "discounts", "status"}
    if data in admin_buttons and not is_admin(user_id):
        await query.answer("Bu bo'lim faqat admin uchun.", show_alert=True)
        return

    await query.answer()

    if data == "help":
        await help_menu(update, context)
    elif data == "status":
        await status(update, context)
    elif data == "postnow":
        await postnow(update, context)
    elif data == "drawnow":
        await drawnow(update, context)
    elif data == "today":
        await today(update, context)
    elif data == "discounts":
        await discounts(update, context)
    elif data == "myref":
        await myref(update, context)
    elif data == "top_active":
        await top_active(update, context)
    elif data == "top3days":
        await top3days(update, context)


def main() -> None:
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN topilmadi.")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_menu))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("postnow", postnow))
    app.add_handler(CommandHandler("drawnow", drawnow))
    app.add_handler(CommandHandler("today", today))
    app.add_handler(CommandHandler("discounts", discounts))
    app.add_handler(CommandHandler("myref", myref))
    app.add_handler(CommandHandler("top", top_active))
    app.add_handler(CommandHandler("topprev", top_prev))
    app.add_handler(CommandHandler("top3days", top3days))
    app.add_handler(CallbackQueryHandler(button_handler))

    app.add_handler(MessageReactionHandler(reaction_handler))
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, new_members_handler))
    app.add_handler(ChatMemberHandler(chat_member_handler, ChatMemberHandler.CHAT_MEMBER))

    jq = app.job_queue
    if jq is not None:
        jq.run_daily(
            contest_post,
            time=time(hour=MORNING_HOUR, minute=MORNING_MINUTE, tzinfo=ZONE),
            name="daily_contest",
        )
        jq.run_daily(
            draw_winner,
            time=time(hour=WINNER_HOUR, minute=WINNER_MINUTE, tzinfo=ZONE),
            name="daily_winner",
        )
        jq.run_daily(
            post_top_daily,
            time=time(hour=TOP_HOUR, minute=TOP_MINUTE, tzinfo=ZONE),
            name="daily_top_ranking",
        )

    app.run_polling(close_loop=False, allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
