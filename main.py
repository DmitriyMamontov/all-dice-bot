# main.py

import logging
import os
import asyncio
import threading
import time
import urllib.request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes

# 🔧 Настройка логирования
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# 🔑 Токен бота
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', "7528268046:AAHk9nL55UUflfZg0RXHvKM149JdX76vGwQ")

# 🎮 Импорты игр с обработкой ошибок
try:
    from black_white import start_black_white, stop_black_white, rules_black_white, button_handler_black_white
    from double_pig import start_double_pig, stop_double_pig, rules_double_pig, button_handler_double_pig

    logger.info("✅ Все игры успешно загружены")
except ImportError as e:
    logger.error(f"❌ Ошибка импорта игр: {e}")


    # Создаем заглушки чтобы бот не падал
    async def game_stub(*args, **kwargs):
        await args[0].message.reply_text("⚠️ Игра временно недоступна")


    start_black_white = stop_black_white = rules_black_white = button_handler_black_white = game_stub
    start_double_pig = stop_double_pig = rules_double_pig = button_handler_double_pig = game_stub

# 📊 Глобальное состояние игр
active_games = {}


# 🔄 Функция самопинга чтобы Render не останавливал сервис
def start_keep_alive():
    """Пингует сервис каждые 5 минут чтобы не уснул"""

    def ping_loop():
        while True:
            try:
                # Этот URL нужно заменить на ваш реальный URL Render
                # Пока заглушка - раскомментируйте когда будет URL
                # urllib.request.urlopen("https://your-bot-name.onrender.com", timeout=10)
                logger.info("🏓 Самопинг выполнен")
            except Exception as e:
                logger.warning(f"🏓 Самопинг не удался: {e}")
            time.sleep(300)  # 5 минут

    thread = threading.Thread(target=ping_loop, daemon=True)
    thread.start()
    logger.info("🔛 Самопинг активирован")


# 🗑️ Автоудаление сообщений
async def _auto_delete_message(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int, delay: int = 8):
    await asyncio.sleep(delay)
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        pass


# 🎯 Команда /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        keyboard = [
            [InlineKeyboardButton("Чёрные-Белые", callback_data="select_game:black_white")],
            [InlineKeyboardButton("Двойная свинка", callback_data="select_game:double_pig")],
        ]
        await update.message.reply_text(
            "🎲 *Выберите игру:*",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        logger.info(f"🎮 Пользователь {update.effective_user.id} запустил бота")
    except Exception as e:
        logger.error(f"❌ Ошибка в /start: {e}")
        await update.message.reply_text("❌ Произошла ошибка. Попробуйте позже.")


# 🔘 Обработчик кнопок
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        await query.answer()
        chat_id = query.message.chat.id
        data = query.data

        # Выбор игры
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

        # Передача управления в активную игру
        if chat_id in active_games:
            current_game = active_games[chat_id]
            if current_game == "black_white" and data.startswith("bw_"):
                await button_handler_black_white(update, context)
                return
            elif current_game == "double_pig" and data.startswith("dp_"):
                await button_handler_double_pig(update, context)
                return

        await query.answer("Сначала выберите игру командой /start", show_alert=True)
    except Exception as e:
        logger.error(f"❌ Ошибка в обработчике кнопок: {e}")


# ⏹️ Команда /stop
async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chat_id = update.effective_chat.id
        if chat_id in active_games:
            game_type = active_games[chat_id]
            if game_type == "black_white":
                await stop_black_white(update, context)
            elif game_type == "double_pig":
                await stop_double_pig(update, context)
            del active_games[chat_id]
            logger.info(f"⏹️ Игра остановлена в чате {chat_id}")
        else:
            msg = await update.message.reply_text("Нет активной игры. Начните с /start")
            asyncio.create_task(_auto_delete_message(context, chat_id, msg.message_id))
    except Exception as e:
        logger.error(f"❌ Ошибка в /stop: {e}")


# 📖 Команда /rules
async def rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chat_id = update.effective_chat.id
        if chat_id in active_games:
            game_type = active_games[chat_id]
            if game_type == "black_white":
                await rules_black_white(update, context)
            elif game_type == "double_pig":
                await rules_double_pig(update, context)
        else:
            msg = await update.message.reply_text("Нет активной игры. Начните с /start")
            asyncio.create_task(_auto_delete_message(context, chat_id, msg.message_id))
    except Exception as e:
        logger.error(f"❌ Ошибка в /rules: {e}")


# ⚙️ Настройка команд бота
async def post_init(application):
    try:
        await application.bot.set_my_commands([
            BotCommand("start", "Выбрать игру"),
            BotCommand("stop", "Остановить текущую игру"),
            BotCommand("rules", "Показать правила текущей игры"),
        ])
        logger.info("✅ Команды бота установлены")
    except Exception as e:
        logger.error(f"❌ Ошибка установки команд: {e}")


# 🚀 Главная функция
def main():
    try:
        logger.info("🎲 Запускаю универсального бота...")

        # Запускаем самопинг (пока заглушка)
        # start_keep_alive()  # 🚨 РАСКОММЕНТИРУЙТЕ КОГДА БУДЕТ URL RENDER

        # Создаем приложение
        app = ApplicationBuilder().token(TOKEN).post_init(post_init).build()

        # Регистрируем обработчики
        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("stop", stop))
        app.add_handler(CommandHandler("rules", rules))
        app.add_handler(CallbackQueryHandler(button_handler))

        # Запускаем бота
        logger.info("✅ Бот успешно запущен и готов к работе!")
        app.run_polling(
            drop_pending_updates=True,
            allowed_updates=Update.ALL_TYPES
        )

    except Exception as e:
        logger.error(f"💥 Критическая ошибка: {e}")
        logger.info("🔄 Попытка перезапуска через 10 секунд...")
        time.sleep(10)
        main()  # Рекурсивный перезапуск


if __name__ == "__main__":
    main()