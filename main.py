# main.py

import logging
import os
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    raise ValueError("❌ Переменная окружения TELEGRAM_BOT_TOKEN не установлена!")

# 🎮 Импорты игр
try:
    from black_white import start_black_white, stop_black_white, rules_black_white, button_handler_black_white
    from double_pig import start_double_pig, stop_double_pig, rules_double_pig, button_handler_double_pig
except ImportError as e:
    logger.error(f"❌ Ошибка импорта игр: {e}")


    async def game_stub(update, context):
        await update.message.reply_text("⚠️ Игра временно недоступна")


    start_black_white = stop_black_white = rules_black_white = button_handler_black_white = game_stub
    start_double_pig = stop_double_pig = rules_double_pig = button_handler_double_pig = game_stub

active_games = {}


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("Чёрные-Белые", callback_data="select_game:black_white")],
        [InlineKeyboardButton("Двойная свинка", callback_data="select_game:double_pig")],
    ]
    await update.message.reply_text(
        "🎲 *Выберите игру:*",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat.id
    data = query.data

    if data.startswith("select_game:"):
        game_type = data.split(":", 1)[1]
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=query.message.message_id)
        except Exception:
            pass

        if game_type == "black_white":
            active_games[chat_id] = "black_white"
            await start_black_white(update, context)
        elif game_type == "double_pig":
            active_games[chat_id] = "double_pig"
            await start_double_pig(update, context)
        return

    if chat_id in active_games:
        game_type = active_games[chat_id]
        if game_type == "black_white" and (data.startswith("bw_") or data == "delete_rules"):
            await button_handler_black_white(update, context)
        elif game_type == "double_pig" and (data.startswith("dp_") or data == "delete_rules"):
            await button_handler_double_pig(update, context)


async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id in active_games:
        game_type = active_games.pop(chat_id)
        if game_type == "black_white":
            await stop_black_white(update, context)
        elif game_type == "double_pig":
            await stop_double_pig(update, context)
    else:
        await update.message.reply_text("Нет активной игры. Начните с /start")


async def rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id in active_games:
        game_type = active_games[chat_id]
        if game_type == "black_white":
            await rules_black_white(update, context)
        elif game_type == "double_pig":
            await rules_double_pig(update, context)
    else:
        await update.message.reply_text("Нет активной игры. Начните с /start")


async def post_init(app):
    await app.bot.set_my_commands([
        BotCommand("start", "Выбрать игру"),
        BotCommand("stop", "Остановить игру"),
        BotCommand("rules", "Правила текущей игры"),
    ])


async def main():
    app = ApplicationBuilder().token(TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stop", stop))
    app.add_handler(CommandHandler("rules", rules))
    app.add_handler(CallbackQueryHandler(button_handler))

    # 🔥 ИСПРАВЛЕНИЕ: Используем Webhook для Railway
    PORT = int(os.environ.get("PORT", 8000))

    # Получаем URL Railway
    RAILWAY_STATIC_URL = os.environ.get("RAILWAY_STATIC_URL", "")
    RAILWAY_PUBLIC_DOMAIN = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "")

    # Используем любой доступный URL
    railway_url = RAILWAY_STATIC_URL or RAILWAY_PUBLIC_DOMAIN or "all-dice-bot.up.railway.app"

    webhook_url = f"https://{railway_url}/{TOKEN}"

    logger.info(f"🚀 Устанавливаю webhook: {webhook_url}")
    await app.bot.set_webhook(url=webhook_url)

    logger.info("✅ Webhook установлен, запускаю сервер...")
    await app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=TOKEN,
        webhook_url=webhook_url,
        drop_pending_updates=True
    )


# 🔧 Простой запуск для Railway
if __name__ == "__main__":
    # Убираем всю сложную логику с event loop - просто запускаем
    asyncio.run(main())