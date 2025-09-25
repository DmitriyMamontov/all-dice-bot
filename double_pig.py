# double_pig.py

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
DICE_EMOJI = {1: "⚀", 2: "⚁", 3: "⚂", 4: "⚃", 5: "⚄", 6: "⚅"}


async def _auto_delete_message(context, chat_id, message_id, delay=8):
    await asyncio.sleep(delay)
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        pass


async def _safe_edit_message(context, chat_id, message_id, text, reply_markup=None, parse_mode="Markdown"):
    now = time.time()
    last = _last_edit_time.get(chat_id, 0)
    wait_min = 1.2
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
            logger.warning(f"_safe_edit_message: Flood control ({err}). Ждём {retry}s и пробуем отправить новое сообщение.")
            await asyncio.sleep(retry)
            try:
                msg = await context.bot.send_message(
                    chat_id=chat_id, text=text, reply_markup=reply_markup, parse_mode=parse_mode
                )
                try:
                    await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
                except Exception:
                    pass
                if chat_id in _games:
                    _games[chat_id]["main_message_id"] = msg.message_id
            except Exception as e2:
                logger.error(f"_safe_edit_message: Повторная отправка не удалась: {e2}")
        else:
            logger.error(f"_safe_edit_message: Ошибка редактирования: {e}")


async def _rules_message(chat_id, context):
    text = (
        "📜 *Правила «Двойной свинки»*\n\n"
        "▫️ Каждый ход игрок бросает 2 шестигранных кубика.\n"
        "▫️ Если выпадает хотя бы одна единица — ход сгорает, все очки этого хода теряются.\n"
        "▫️ Если выпадают две единицы — 💥 обнуляется весь общий счёт игрока.\n"
        "▫️ Если выпадает дубль (две одинаковые цифры, кроме единиц) — сумма удваивается, "
        "и игрок обязан бросать ещё раз.\n"
        "▫️ В остальных случаях сумма добавляется во *временные очки хода*.\n\n"
        "👉 Результат бросков копится во временных очках. Только когда игрок нажимает «✋ Остановиться», "
        "эти очки фиксируются и переходят в общий счёт. Если не нажать — есть риск всё потерять.\n\n"
        "▫️ Цель: первым достичь выбранного порога (50 / 100 / 150 очков)."
    )
    keyboard = [[InlineKeyboardButton("Я прочитал ✅", callback_data="dp_delete_rules")]]
    await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))


async def _update_lobby(chat_id, context):
    game = _games[chat_id]
    players_list = list(game["players"].values())
    players_text = "\n".join(f"👤 {p['username']}" for p in players_list) or "— Нет игроков —"

    text = f"🎯 *Игра: Двойная свинка*\n\nИгроки ({len(players_list)}):\n{players_text}\n\n"
    if len(players_list) >= 2:
        text += "Выберите цель по очкам (первый достиг — побеждает):"
        keyboard = [
            [
                InlineKeyboardButton("50 очков", callback_data="dp_set_target_50"),
                InlineKeyboardButton("100 очков", callback_data="dp_set_target_100"),
                InlineKeyboardButton("150 очков", callback_data="dp_set_target_150"),
            ],
            [InlineKeyboardButton("📜 Правила", callback_data="dp_show_rules")],
        ]
    else:
        text += "Нужно минимум 2 игрока, максимум 4. Нажмите «Присоединиться 🎲» чтобы играть."
        keyboard = [
            [InlineKeyboardButton("Присоединиться 🎲", callback_data="dp_join")],
            [InlineKeyboardButton("📜 Правила", callback_data="dp_show_rules")],
        ]

    await _safe_edit_message(context, chat_id, game["main_message_id"], text, InlineKeyboardMarkup(keyboard))


async def _update_board(chat_id, context):
    game = _games[chat_id]
    if not game["turn_order"]:
        return
    current_player_id = game["current_player"]
    current_player_name = _games[chat_id]["players"][current_player_id]["username"]

    lines = []
    for uid, p in game["players"].items():
        tp = p.get("turn_points", 0)
        marker = "➡️" if uid == current_player_id else "⏳"
        line = f"{marker} {p['username']}: {p['total']} (текущий ход +{tp})"
        lines.append(line)

    recent = game.get("history", [])[-12:]
    hist_lines = []
    if recent:
        hist_lines.append("\n*Последние броски / действия:*")
        for entry in recent:
            if entry.get("dice"):
                emojis = entry.get("dice_emojis", "")
                note = entry.get("note", "")
                hist_lines.append(f"👤 {entry['player']}: {emojis} → {note}")
            elif entry.get("action") == "hold":
                hist_lines.append(f"👤 {entry['player']}: сохранено +{entry['added']}")
            else:
                hist_lines.append(f"👤 {entry.get('player')}: {entry.get('note','')}")

    text = (
        f"🎲 *Двойная свинка* — цель: *{game['target_score']}* очков\n"
        f"Раунд {game.get('round_index',1)}\n\n"
        f"*Ход: {current_player_name}*\n\n"
        "*Счёт игроков:*\n" + "\n".join(lines) +
        ("\n\n" + "\n".join(hist_lines) if hist_lines else "")
    )

    current_player = game["players"][current_player_id]
    if current_player.get("must_roll", False):
        keyboard = [
            [InlineKeyboardButton("Бросить 🎲", callback_data="dp_roll")],
            [InlineKeyboardButton("📜 Правила", callback_data="dp_show_rules")],
        ]
    else:
        keyboard = [
            [InlineKeyboardButton("Бросить 🎲", callback_data="dp_roll"),
             InlineKeyboardButton("Остановиться ✋", callback_data="dp_hold")],
            [InlineKeyboardButton("📜 Правила", callback_data="dp_show_rules")],
        ]

    await _safe_edit_message(context, chat_id, game["main_message_id"], text, InlineKeyboardMarkup(keyboard))


async def _show_final_results(chat_id, context, winner_id=None):
    game = _games[chat_id]
    players = list(game["players"].items())
    players.sort(key=lambda p: p[1]["total"], reverse=True)

    recent = game.get("history", [])[-12:]
    history_lines = []
    if recent:
        history_lines.append("*Последние броски / действия:*")
        for entry in recent:
            if entry.get("dice"):
                emojis = entry.get("dice_emojis", "")
                note = entry.get("note", "")
                history_lines.append(f"👤 {entry['player']}: {emojis} → {note}")
            elif entry.get("action") == "hold":
                history_lines.append(f"👤 {entry['player']}: сохранено +{entry['added']}")
            else:
                history_lines.append(f"👤 {entry.get('player')}: {entry.get('note','')}")

    table_lines = []
    for i, (uid, p) in enumerate(players):
        pts = p["total"]
        medal = ["🥇", "🥈", "🥉"][i] if i < 3 else ""
        table_lines.append(f"{medal} {p['username']}: {pts}")

    winner_name = game["players"][winner_id]["username"] if winner_id else players[0][1]["username"]
    text = (
        "🏆 *ФИНАЛ - Двойная свинка* 🏆\n\n"
        + ("\n".join(history_lines) + "\n\n" if history_lines else "")
        + "*Итог:* \n" + "\n".join(table_lines) +
        f"\n\n🎉 Победитель: *{winner_name}*"
    )

    keyboard = [
        [InlineKeyboardButton("Новая игра 🔄", callback_data="dp_new_game")],
        [InlineKeyboardButton("Выбрать другую игру 🎮", callback_data="dp_switch_game")],
        [InlineKeyboardButton("📜 Правила", callback_data="dp_show_rules")],
    ]

    try:
        await _safe_edit_message(context, chat_id, game["main_message_id"], text, InlineKeyboardMarkup(keyboard))
    except Exception as e:
        logger.error(f"Не удалось обновить финальное сообщение: {e}")
        msg = await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown",
                                             reply_markup=InlineKeyboardMarkup(keyboard))
        _games[chat_id]["main_message_id"] = msg.message_id

    game["phase"] = "finished"


async def _advance_turn(chat_id, context):
    game = _games[chat_id]
    if not game["turn_order"]:
        return
    game["turn_order"].append(game["turn_order"].pop(0))
    game["current_player"] = game["turn_order"][0]
    new_player = game["players"][game["current_player"]]
    new_player["turn_points"] = new_player.get("turn_points", 0)
    new_player["must_roll"] = new_player.get("must_roll", False)
    await _update_board(chat_id, context)


# === ИСПРАВЛЕНО: используем send_message вместо reply_text ===
async def start_double_pig(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id in _games and _games[chat_id]["phase"] != "finished":
        msg = await context.bot.send_message(
            chat_id=chat_id,
            text="Игра уже идёт! /stop чтобы завершить."
        )
        asyncio.create_task(_auto_delete_message(context, chat_id, msg.message_id))
        return

    _games[chat_id] = {
        "players": {},
        "phase": "lobby",
        "main_message_id": None,
        "target_score": None,
        "turn_order": [],
        "current_player": None,
        "round_index": 1,
        "history": [],
    }

    keyboard = [[InlineKeyboardButton("Присоединиться 🎲", callback_data="dp_join")]]
    msg = await context.bot.send_message(
        chat_id=chat_id,
        text="🎯 *Игра: Двойная свинка*\n\nЖдём игроков!\nМинимум 2 участника.",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    _games[chat_id]["main_message_id"] = msg.message_id


async def stop_double_pig(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id in _games:
        del _games[chat_id]
        msg = await context.bot.send_message(
            chat_id=chat_id,
            text="🛑 Игра «Двойная свинка» завершена."
        )
        asyncio.create_task(_auto_delete_message(context, chat_id, msg.message_id))
    else:
        msg = await context.bot.send_message(
            chat_id=chat_id,
            text="Нет активной игры «Двойная свинка»."
        )
        asyncio.create_task(_auto_delete_message(context, chat_id, msg.message_id))


async def rules_double_pig(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _rules_message(update.effective_chat.id, context)


async def button_handler_double_pig(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat.id
    user_id = query.from_user.id
    username = query.from_user.username or query.from_user.first_name

    if query.data == "dp_delete_rules":
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=query.message.message_id)
        except Exception as e:
            logger.error(f"Ошибка удаления правил: {e}")
        return

    if chat_id not in _games:
        await query.answer("Игра не найдена.", show_alert=True)
        return

    game = _games[chat_id]

    if query.data == "dp_switch_game":
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
        return

    if query.data == "dp_join":
        if game["phase"] != "lobby":
            await query.answer("Лобби закрыто!", show_alert=True)
            return
        if len(game["players"]) >= 4:
            await query.answer("Максимум 4 игрока.", show_alert=True)
            return
        if user_id in game["players"]:
            await query.answer("Ты уже в игре!", show_alert=True)
            return
        game["players"][user_id] = {
            "username": username,
            "total": 0,
            "turn_points": 0,
            "history": [],
            "must_roll": False,
        }
        await _update_lobby(chat_id, context)
        return

    if query.data.startswith("dp_set_target_"):
        if game["phase"] != "lobby":
            await query.answer("Нельзя менять цель теперь.", show_alert=True)
            return
        target = int(query.data.split("_")[-1])
        game["target_score"] = target
        if len(game["players"]) < 2:
            await query.answer("Нужно минимум 2 игрока.", show_alert=True)
            return
        game["phase"] = "playing"
        game["turn_order"] = list(game["players"].keys())
        random.shuffle(game["turn_order"])
        game["current_player"] = game["turn_order"][0]
        game["history"] = []
        for p in game["players"].values():
            p["turn_points"] = 0
            p["must_roll"] = False
            p["history"] = []
        await _update_board(chat_id, context)
        return

    if query.data == "dp_show_rules":
        await _rules_message(chat_id, context)
        return

    if query.data == "dp_roll":
        if game["phase"] != "playing":
            await query.answer("Игра не запущена.", show_alert=True)
            return
        if user_id != game["current_player"]:
            await query.answer("⏳ Сейчас ход другого игрока!\nПодожди своей очереди 😉", show_alert=True)
            return

        d1, d2 = random.randint(1, 6), random.randint(1, 6)
        dice_sum = d1 + d2
        dice_emojis = f"{DICE_EMOJI[d1]} {DICE_EMOJI[d2]}"
        player = game["players"][user_id]
        log_entry = {"player": player["username"], "user_id": user_id, "dice": (d1, d2), "dice_emojis": dice_emojis, "sum": dice_sum}

        if d1 == 1 and d2 == 1:
            player["total"] = 0
            player["turn_points"] = 0
            player["must_roll"] = False
            log_entry["note"] = "Две единицы — общий счёт обнулён 💥"
            player["history"].append(log_entry)
            game["history"].append(log_entry)
            await _update_board(chat_id, context)
            await asyncio.sleep(0.5)
            await _advance_turn(chat_id, context)
            return

        if d1 == 1 or d2 == 1:
            player["turn_points"] = 0
            player["must_roll"] = False
            log_entry["note"] = "Выпала единица — ход сгорел 🔴"
            player["history"].append(log_entry)
            game["history"].append(log_entry)
            await _update_board(chat_id, context)
            await asyncio.sleep(0.5)
            await _advance_turn(chat_id, context)
            return

        if d1 == d2:
            added = dice_sum * 2
            player["turn_points"] += added
            player["must_roll"] = True
            log_entry["note"] = f"Дубль! Сумма удвоена → +{added} (обязан бросать ещё) 🔁"
            player["history"].append(log_entry)
            game["history"].append(log_entry)
            await _update_board(chat_id, context)
            return

        player["turn_points"] += dice_sum
        player["must_roll"] = False
        log_entry["note"] = f"+{dice_sum}"
        player["history"].append(log_entry)
        game["history"].append(log_entry)
        await _update_board(chat_id, context)
        return

    if query.data == "dp_hold":
        if game["phase"] != "playing":
            await query.answer("Игра не запущена.", show_alert=True)
            return
        if user_id != game["current_player"]:
            await query.answer("⏳ Сейчас ход другого игрока!\nПодожди своей очереди 😉", show_alert=True)
            return

        player = game["players"][user_id]
        if player.get("must_roll", False):
            await query.answer("После дубля нельзя остановиться — нужно бросать ещё! 🎲", show_alert=True)
            return

        added = player["turn_points"]
        player["total"] += added
        player["turn_points"] = 0
        player["must_roll"] = False

        hold_entry = {"player": player["username"], "user_id": user_id, "action": "hold", "added": added, "note": f"Сохранено +{added}"}
        player["history"].append(hold_entry)
        game["history"].append(hold_entry)

        if player["total"] >= game["target_score"]:
            await _show_final_results(chat_id, context, winner_id=user_id)
            return

        await _advance_turn(chat_id, context)
        return

    if query.data == "dp_new_game":
        _games[chat_id] = {
            "players": {},
            "phase": "lobby",
            "main_message_id": game["main_message_id"],
            "target_score": None,
            "turn_order": [],
            "current_player": None,
            "round_index": 1,
            "history": [],
        }
        keyboard = [[InlineKeyboardButton("Присоединиться 🎲", callback_data="dp_join")]]
        text = "🎯 *Игра: Двойная свинка*\n\nЖдём игроков!\nМинимум 2 участника."
        try:
            await _safe_edit_message(context, chat_id, game["main_message_id"], text, InlineKeyboardMarkup(keyboard))
        except Exception:
            msg = await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
            _games[chat_id]["main_message_id"] = msg.message_id
        await query.answer("Новая игра создана!", show_alert=False)
        return