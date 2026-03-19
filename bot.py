from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

BOT_TOKEN = "8625347327:AAE4Y13zOSV4RROVRHo2YmvEo8Ne8O788VM"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Salom.\n"
        "Chat ID olish uchun /id yozing."
    )

async def get_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user

    text = (
        f"Chat ID: {chat.id}\n"
        f"Chat turi: {chat.type}\n"
        f"Nomi: {chat.title or user.first_name}"
    )
    await update.message.reply_text(text)

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("id", get_id))

    print("Bot ishga tushdi...")
    app.run_polling()

if __name__ == "__main__":
    main()
