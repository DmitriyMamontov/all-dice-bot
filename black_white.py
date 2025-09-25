# black_white.py

import logging
import random
import asyncio
import time
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

_games = {}
_last_edit_time = {}


async def _auto_delete_message(context, chat_id, message_id, delay=8):
    await asyncio.sleep(delay)
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        pass


async def _safe_edit_message(context, chat_id, message_id, text, reply_markup=None, parse_mode="Markdown"):
    now = time.time()
    last = _last_edit_time.get(chat_id, 0)
    wait_min = 1.5
    if now - last < wait_min:
        await asyncio.sleep(wait_min - (now - last))
    _last_edit_time[chat_id] = time.time()

    try:
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            reply_markup=reply_markup,
            parse_mode=parse_mode
        )
    except Exception as e:
        err = str(e)
        if "Message is not modified" in err:
            logger.debug("safe_edit_message: no changes — skipped.")
            return
        if "Too Many Requests" in err or "Flood control" in err or "retry after" in err:
            retry = 2
            m = re.search(r"retry ?after\s*(\d+)", err, re.IGNORECASE)
            if m:
                try:
                    retry = int(m.group(1)) + 1
                except Exception:
                    retry = 2
            logger.warning(f"safe_edit_message: Flood control ({err}). Ждём {retry}s и пробуем отправить новое сообщение.")
            await asyncio.sleep(retry)
            try:
                msg = await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup, parse_mode=parse_mode)
                try:
                    await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
                except Exception:
                    pass
                if chat_id in _games:
                    _games[chat_id]["main_message_id"] = msg.message_id
            except Exception as e2:
                logger.error(f"safe_edit_message: Повторная отправка не удалась: {e2}")
        else:
            logger.error(f"safe_edit_message: Ошибка редактирования сообщения: {e}")


async def _update_lobby(chat_id, context):
    game = _games[chat_id]
    players = "\n".join(f"👤 {p['username']}" for p in game["players"].values()) or "—"
    text = f"🎲 *Игра: Чёрные-Белые*\n\nУчастники ({len(game['players'])}):\n{players}"

    if len(game["players"]) >= 2:
        keyboard = [
            [InlineKeyboardButton(f"{i} раунда", callback_data=f"bw_set_rounds_{i}") for i in range(2, 5)],
            [InlineKeyboardButton(f"{i} раундов", callback_data=f"bw_set_rounds_{i}") for i in range(5, 7)],
            [InlineKeyboardButton("📜 Правила", callback_data="bw_show_rules")],
        ]
    else:
        keyboard = [
            [InlineKeyboardButton("Присоединиться 🎲", callback_data="bw_join")],
            [InlineKeyboardButton("📜 Правила", callback_data="bw_show_rules")],
        ]

    await _safe_edit_message(context, chat_id, game["main_message_id"], text, InlineKeyboardMarkup(keyboard))


async def _update_dice_selection(chat_id, context):
    game = _games[chat_id]
    text = f"🎲 Выбрано {game['rounds_total']} раундов.\n\n*Выберите формат игры:*"
    keyboard = [
        [InlineKeyboardButton("4 кубика (2⚪ + 2⚫)", callback_data="bw_set_dice_4")],
        [InlineKeyboardButton("6 кубиков (3⚪ + 3⚫)", callback_data="bw_set_dice_6")],
        [InlineKeyboardButton("8 кубиков (4⚪ + 4⚫)", callback_data="bw_set_dice_8")],
        [InlineKeyboardButton("📜 Правила", callback_data="bw_show_rules")],
    ]
    await _safe_edit_message(context, chat_id, game["main_message_id"], text, InlineKeyboardMarkup(keyboard))


async def _start_round(chat_id, context):
    game = _games[chat_id]
    for p in game["players"].values():
        p["has_played_this_round"] = False
        p["last_roll"] = None
        p["pending_draw"] = None

    dc = game["dice_count"]
    game["round_dice_pool"] = ["white"]*(dc//2) + ["black"]*(dc//2)
    await _update_board(chat_id, context)


async def _update_board(chat_id, context):
    game = _games[chat_id]
    if not game.get("current_player"):
        if game.get("turn_order"):
            game["current_player"] = game["turn_order"][0]
        else:
            return

    current_player_id = game["current_player"]
    current_player_name = _games[chat_id]["players"][current_player_id]["username"]

    history_lines = []
    for rnd in range(1, game["current_round"] + 1):
        if rnd in game["round_history"] and game["round_history"][rnd]:
            history_lines.append(f"\n*Раунд {rnd}:*")
            for throw in game["round_history"][rnd]:
                dice_emojis = "".join("⚪" if d == "white" else "⚫" for d in throw["dice"])
                values_str = ", ".join(map(str, throw["values"]))
                sign = "+" if throw["result"] >= 0 else ""
                history_lines.append(f"👤 {throw['player']} бросил {dice_emojis} ({values_str}) → {sign}{throw['result']}")

    players_status = []
    for pid, p in game["players"].items():
        status = "✅" if p["has_played_this_round"] else ("➡️" if pid == current_player_id else "⏳")
        diff = p["white_total"] - p["black_total"]
        players_status.append(f"{status} {p['username']}: ⚪{p['white_total']} ⚫{p['black_total']} ➡️ {diff}")

    text = (
        f"🎲 *Раунд {game['current_round']} из {game['rounds_total']}*\n"
        f"Ход: {current_player_name}\n\n"
        "Общий счёт:\n" + "\n".join(players_status) +
        ("\n\n*История бросков:*" + "\n".join(history_lines) if history_lines else "")
    )

    player = game["players"][current_player_id]
    if not player["has_played_this_round"]:
        if player.get("pending_draw") is not None:
            keyboard = [
                [InlineKeyboardButton("Бросить кубики 🎯", callback_data="bw_roll")],
                [InlineKeyboardButton("📜 Правила", callback_data="bw_show_rules")],
            ]
        else:
            keyboard = [
                [InlineKeyboardButton("Тянуть кубики 🎲", callback_data="bw_draw")],
                [InlineKeyboardButton("📜 Правила", callback_data="bw_show_rules")],
            ]
    else:
        keyboard = [[InlineKeyboardButton("📜 Правила", callback_data="bw_show_rules")]]

    await _safe_edit_message(context, chat_id, game["main_message_id"], text, InlineKeyboardMarkup(keyboard))


async def _show_final_results(chat_id, context):
    game = _games[chat_id]
    players = list(game["players"].values())
    players.sort(key=lambda p: (p["white_total"] - p["black_total"], p["white_total"]), reverse=True)

    history_lines = []
    for rnd in range(1, game["rounds_total"] + 1):
        if rnd in game["round_history"] and game["round_history"][rnd]:
            history_lines.append(f"*Раунд {rnd}:*")
            for throw in game["round_history"][rnd]:
                dice_emojis = "".join("⚪" if d == "white" else "⚫" for d in throw["dice"])
                values_str = ", ".join(map(str, throw["values"]))
                sign = "+" if throw["result"] >= 0 else ""
                history_lines.append(f"👤 {throw['player']} бросил {dice_emojis} ({values_str}) → {sign}{throw['result']}")
            history_lines.append("")

    table_lines = []
    for i, p in enumerate(players):
        diff = p["white_total"] - p["black_total"]
        medal = ["🥇", "🥈", "🥉"][i] if i < 3 else ""
        table_lines.append(f"{medal} {p['username']}: ⚪{p['white_total']} ⚫{p['black_total']} ➡️ {diff}")

    winner = players[0]["username"] if players else "—"
    text = (
        "🏆 *ФИНАЛЬНЫЕ ИТОГИ* 🏆\n\n"
        + ("\n".join(history_lines) + "\n" if history_lines else "")
        + "\n*Общий результат:*\n"
        + "\n".join(table_lines)
        + f"\n\n🎉 Победитель: *{winner}*!"
    )

    keyboard = [
        [InlineKeyboardButton("Новая игра 🔄", callback_data="bw_new_game")],
        [InlineKeyboardButton("Выбрать другую игру 🎮", callback_data="bw_switch_game")],
        [InlineKeyboardButton("📜 Правила", callback_data="bw_show_rules")],
    ]

    await _safe_edit_message(context, chat_id, game["main_message_id"], text, InlineKeyboardMarkup(keyboard))
    game["phase"] = "finished"


async def _rules_message(chat_id, context):
    text = (
        "📜 *Правила игры «Чёрные-Белые»:*\n\n"
        "▫️ В коробке кубики ⚪ и ⚫ (белые = +, чёрные = -).\n"
        "▫️ Выберите формат: 4 (2⚪+2⚫), 6 (3⚪+3⚫) или 8 (4⚪+4⚫) кубиков.\n"
        "▫️ Первый игрок тянет половину кубиков.\n"
        "▫️ Второму достаются оставшиеся.\n"
        "▫️ Если игроков >2 — каждый тянет до 2 кубиков.\n"
        "▫️ Побеждает тот, у кого больше разница ⚪ − ⚫."
    )
    keyboard = [[InlineKeyboardButton("Я прочитал ✅", callback_data="bw_delete_rules")]]
    await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))


# === ИСПРАВЛЕНО: используем send_message вместо reply_text ===
async def start_black_white(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id in _games:
        msg = await context.bot.send_message(
            chat_id=chat_id,
            text="Игра уже идёт! /stop чтобы завершить."
        )
        asyncio.create_task(_auto_delete_message(context, chat_id, msg.message_id))
        return

    lock = asyncio.Lock()
    _games[chat_id] = {
        "players": {},
        "rounds_total": None,
        "dice_count": None,
        "current_round": 1,
        "main_message_id": None,
        "current_player": None,
        "turn_order": [],
        "phase": "lobby",
        "round_history": {},
        "round_dice_pool": [],
        "pending_draw": None,
        "lock": lock,
    }

    keyboard = [[InlineKeyboardButton("Присоединиться 🎲", callback_data="bw_join")]]
    msg = await context.bot.send_message(
        chat_id=chat_id,
        text="🎲 *Игра: Чёрные-Белые*\n\nЖдём игроков!\nМинимум 2 участника.",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )
    _games[chat_id]["main_message_id"] = msg.message_id


async def stop_black_white(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id in _games:
        del _games[chat_id]
        msg = await context.bot.send_message(
            chat_id=chat_id,
            text="🛑 Игра «Чёрные-Белые» завершена."
        )
        asyncio.create_task(_auto_delete_message(context, chat_id, msg.message_id))
    else:
        msg = await context.bot.send_message(
            chat_id=chat_id,
            text="Нет активной игры «Чёрные-Белые»."
        )
        asyncio.create_task(_auto_delete_message(context, chat_id, msg.message_id))


async def rules_black_white(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _rules_message(update.effective_chat.id, context)


async def button_handler_black_white(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat.id
    user = query.from_user
    user_id = user.id
    username = user.username or user.first_name

    if query.data == "bw_delete_rules":
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=query.message.message_id)
        except Exception as e:
            logger.error(f"Ошибка удаления правил: {e}")
        return

    if chat_id not in _games:
        await query.answer("Игра не найдена.", show_alert=True)
        return

    game = _games[chat_id]
    lock = game["lock"]

    async def _handle_draw():
        pool = game["round_dice_pool"]
        n_players = len(game["turn_order"]) if game.get("turn_order") else len(game["players"])

        if n_players == 2:
            half = game["dice_count"] // 2
            first_player_turn = not any(p["has_played_this_round"] for p in game["players"].values())
            if first_player_turn:
                if len(pool) < half:
                    dc = game["dice_count"]
                    game["round_dice_pool"] = ["white"]*(dc//2) + ["black"]*(dc//2)
                    await _update_board(chat_id, context)
                    await query.answer("Ошибка состояния: перезапуск раунда.", show_alert=True)
                    return
                chosen = random.sample(pool, half)
                for c in chosen:
                    pool.remove(c)
                game["round_dice_pool"] = pool
            else:
                chosen = pool[:]
                game["round_dice_pool"] = []
        else:
            draw_count = min(2, len(pool))
            if draw_count == 0:
                dc = game["dice_count"]
                game["round_dice_pool"] = ["white"]*(dc//2) + ["black"]*(dc//2)
                for p in game["players"].values():
                    p["has_played_this_round"] = False
                    p["pending_draw"] = None
                await _update_board(chat_id, context)
                await query.answer("Кубики закончились — перезапуск раунда.", show_alert=True)
                return
            chosen = random.sample(pool, draw_count)
            for c in chosen:
                pool.remove(c)
            game["round_dice_pool"] = pool

        player = game["players"][user_id]
        player["pending_draw"] = chosen
        game["pending_draw"] = chosen
        await _update_board(chat_id, context)
        await query.answer("Кубики вытянуты — нажми 'Бросить кубики' 🎯", show_alert=False)

    async def _handle_roll():
        player = game["players"][user_id]
        chosen = player.get("pending_draw") or game.get("pending_draw")
        if not chosen:
            await query.answer("Сначала вытяни кубики!", show_alert=True)
            await _update_board(chat_id, context)
            return

        player["pending_draw"] = None
        game["pending_draw"] = None

        values = [random.randint(1, 6) for _ in chosen]
        white_sum = sum(v for v, c in zip(values, chosen) if c == "white")
        black_sum = sum(v for v, c in zip(values, chosen) if c == "black")
        total_result = white_sum - black_sum

        player.update({
            "white_total": player["white_total"] + white_sum,
            "black_total": player["black_total"] + black_sum,
            "score": player["score"] + total_result,
            "has_played_this_round": True,
            "last_roll": {"dice": chosen, "values": values, "result": total_result},
            "history": player.get("history", []) + [total_result],
        })

        game["round_history"].setdefault(game["current_round"], []).append({
            "player": player["username"],
            "dice": chosen,
            "values": values,
            "result": total_result,
        })

        await _update_board(chat_id, context)

        played_count = sum(1 for p in game["players"].values() if p["has_played_this_round"])
        if played_count < len(game["players"]):
            idx = game["turn_order"].index(user_id)
            next_idx = (idx + 1) % len(game["turn_order"])
            game["current_player"] = game["turn_order"][next_idx]
            await asyncio.sleep(0.05)
            await _update_board(chat_id, context)
        else:
            if game["current_round"] >= game["rounds_total"]:
                await asyncio.sleep(1.2)
                await _show_final_results(chat_id, context)
            else:
                game["current_round"] += 1
                for p in game["players"].values():
                    p["has_played_this_round"] = False
                    p["last_roll"] = None
                    p["pending_draw"] = None
                dc = game["dice_count"]
                game["round_dice_pool"] = ["white"]*(dc//2) + ["black"]*(dc//2)
                game["turn_order"].append(game["turn_order"].pop(0))
                game["current_player"] = game["turn_order"][0]
                await _start_round(chat_id, context)

    if query.data == "bw_join":
        async with lock:
            if game["phase"] != "lobby":
                await query.answer("Лобби закрыто!", show_alert=True)
                return
            if user_id in game["players"]:
                await query.answer("Ты уже в игре!", show_alert=True)
                return
            game["players"][user_id] = {
                "username": username,
                "white_total": 0,
                "black_total": 0,
                "score": 0,
                "has_played_this_round": False,
                "last_roll": None,
                "history": [],
                "pending_draw": None,
            }
            await _update_lobby(chat_id, context)
            await query.answer(f"✅ {username} присоединился!")

    elif query.data.startswith("bw_set_rounds_"):
        async with lock:
            if game["phase"] != "lobby":
                await query.answer("Нельзя выбрать раунды сейчас!", show_alert=True)
                return
            rounds = int(query.data.split("_")[-1])
            if not (2 <= rounds <= 20):
                await query.answer("Выберите корректное количество раундов!", show_alert=True)
                return
            game["rounds_total"] = rounds
            game["phase"] = "choose_dice"
            await _update_dice_selection(chat_id, context)

    elif query.data.startswith("bw_set_dice_"):
        async with lock:
            if game["phase"] != "choose_dice":
                await query.answer("Сначала выберите количество раундов!", show_alert=True)
                return
            dice_count = int(query.data.split("_")[-1])
            if dice_count not in (4, 6, 8):
                await query.answer("Недопустимый формат!", show_alert=True)
                return
            game["dice_count"] = dice_count
            game["phase"] = "playing"
            game["turn_order"] = list(game["players"].keys())
            random.shuffle(game["turn_order"])
            game["current_player"] = game["turn_order"][0]
            game["current_round"] = 1
            game["round_history"] = {i: [] for i in range(1, game["rounds_total"] + 1)}
            await _start_round(chat_id, context)

    elif query.data == "bw_draw":
        async with lock:
            if user_id != game["current_player"]:
                await query.answer("❌ Сейчас не твой ход!", show_alert=True)
                return
            if game["players"][user_id]["has_played_this_round"]:
                await query.answer("Ты уже сделал ход!", show_alert=True)
                return
            await _handle_draw()

    elif query.data == "bw_roll":
        async with lock:
            if user_id != game["current_player"]:
                await query.answer("❌ Сейчас не твой ход!", show_alert=True)
                return
            if game["players"][user_id]["has_played_this_round"]:
                await query.answer("Ты уже сделал ход!", show_alert=True)
                return
            await _handle_roll()

    elif query.data == "bw_show_rules":
        await _rules_message(chat_id, context)

    elif query.data == "bw_new_game":
        async with lock:
            _games[chat_id] = {
                "players": {},
                "rounds_total": None,
                "dice_count": None,
                "current_round": 1,
                "main_message_id": game["main_message_id"],
                "current_player": None,
                "turn_order": [],
                "phase": "lobby",
                "round_history": {},
                "round_dice_pool": [],
                "pending_draw": None,
                "lock": lock,
            }
            keyboard = [[InlineKeyboardButton("Присоединиться 🎲", callback_data="bw_join")]]
            text = "🎲 *Игра: Чёрные-Белые*\n\nЖдём игроков!\nМинимум 2 участника."
            try:
                await _safe_edit_message(context, chat_id, game["main_message_id"], text, InlineKeyboardMarkup(keyboard))
            except Exception:
                msg = await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
                _games[chat_id]["main_message_id"] = msg.message_id
            await query.answer("Новая игра создана!", show_alert=False)

    elif query.data == "bw_switch_game":
        if chat_id in _games:
            del _games[chat_id]
        keyboard = [
            [InlineKeyboardButton("Чёрные-Белые", callback_data="select_game:black_white")],
            [InlineKeyboardButton("Двойная свинка", callback_data="select_game:double_pig")],
        ]
        await context.bot.send_message(
            chat_id=chat_id,
            text="🎲 *Выберите игру:*",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        await query.answer("Возврат к выбору игры", show_alert=False)

    else:
        return