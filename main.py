# main.py

import logging
import os
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes

from black_white import start_black_white, stop_black_white, rules_black_white, button_handler_black_white
from double_pig import start_double_pig, stop_double_pig, rules_double_pig, button_handler_double_pig

# 🔑 Безопасное получение токена
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', "7528268046:AAHk9nL55UUflfZg0RXHvKM149JdX76vGwQ")

# Настройка логирования для хостинга
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[
        logging.StreamHandler()  # Важно для хостинга!
    ]
)
logger = logging.getLogger(__name__)

# Глобальное состояние: какая игра активна в чате
active_games = {}  # chat_id -> "black_white" or "double_pig"


async def _auto_delete_message(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int, delay: int = 8):
    """Удаляет сообщение через delay секунд."""
    await asyncio.sleep(delay)
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        pass  # Игнорируем ошибки (сообщение могло быть удалено вручную)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start — выбор игры"""
    keyboard = [
        [InlineKeyboardButton("Чёрные-Белые", callback_data="select_game:black_white")],
        [InlineKeyboardButton("Двойная свинка", callback_data="select_game:double_pig")],
    ]
    msg = await update.message.reply_text(
        "🎲 *Выберите игру:*",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Общий обработчик всех кнопок"""
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat.id
    data = query.data

    # === Выбор игры из главного меню ===
    if data.startswith("select_game:"):
        game_type = data.split(":", 1)[1]

        # Удаляем сообщение с выбором игры
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
        else:
            await query.answer("Неизвестная игра.", show_alert=True)
        return

    # === Передача управления в активную игру ===
    if chat_id in active_games:
        current_game = active_games[chat_id]

        if current_game == "black_white":
            if any(data.startswith(prefix) for prefix in ["bw_", "delete_rules"]):
                await button_handler_black_white(update, context)
                return

        elif current_game == "double_pig":
            if any(data.startswith(prefix) for prefix in ["dp_", "delete_rules"]):
                await button_handler_double_pig(update, context)
                return

        await query.answer("Эта кнопка не относится к текущей игре.", show_alert=True)
        return

    await query.answer("Сначала выберите игру командой /start", show_alert=True)


async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /stop — завершить текущую игру"""
    chat_id = update.effective_chat.id
    if chat_id in active_games:
        game_type = active_games[chat_id]
        if game_type == "black_white":
            await stop_black_white(update, context)
        elif game_type == "double_pig":
            await stop_double_pig(update, context)
        del active_games[chat_id]
    else:
        msg = await update.message.reply_text("Нет активной игры. Начните с /start")
        asyncio.create_task(_auto_delete_message(context, chat_id, msg.message_id))


async def rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /rules — показать правила текущей игры"""
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


async def post_init(application):
    """Установка команд после инициализации"""
    try:
        await application.bot.set_my_commands([
            BotCommand("start", "Выбрать игру"),
            BotCommand("stop", "Остановить текущую игру"),
            BotCommand("rules", "Показать правила текущей игры"),
        ])
        logger.info("✅ Команды бота установлены")
    except Exception as e:
        logger.error(f"❌ Ошибка установки команд: {e}")


def main():
    """Запуск бота"""
    try:
        # Создаем приложение с post_init
        app = ApplicationBuilder().token(TOKEN).post_init(post_init).build()

        # Регистрируем обработчики
        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("stop", stop))
        app.add_handler(CommandHandler("rules", rules))
        app.add_handler(CallbackQueryHandler(button_handler))

        # Запуск бота
        logger.info("🎲 Запускаю универсального бота...")
        app.run_polling(
            drop_pending_updates=True,
            allowed_updates=Update.ALL_TYPES
        )
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}")
        raise


if __name__ == "__main__":
    main()