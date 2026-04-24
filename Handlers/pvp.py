"""Онлайн-режим 1×1: дуэли между реальными игроками.

Раньше модуль назывался «PvP», сейчас вся видимая часть переименована в «Онлайн».
Команда /pvp оставлена как алиас для совместимости.

Доступные режимы:
- 🎲 Кости, 🎯 Дартс, 🏀 Баскетбол, ⚽ Футбол — бросают Telegram-дайс, больше = победа.
- 🎡 Рулетка — оба крутят барабан (0–36), больше = победа.
- 🪙 Монетка — орёл/решка, каждый выбирает сторону.

Экономика:
- Создатель делает ставку → сумма списывается сразу.
- Второй игрок платит ту же ставку при присоединении (либо играет бесплатно,
  если заработал это через 50 побед).
- При обычной победе победитель получает банк минус 5% комиссии.
- При ничьей ставки возвращаются обоим.
- Бесплатный вход: банк = ставка создателя; победа «бесплатника» — 50% банка,
  вторая половина возвращается создателю.
"""
import asyncio
import logging
import random
import time
from typing import Optional

from aiogram import F, Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database import (
    conn,
    cursor,
    db_get_user,
    db_has_free_games,
    db_increment_pvp_wins,
)
from utils import safe_send_message

logger = logging.getLogger(__name__)
router = Router()


MIN_BET = 100
MAX_BET = 5_000_000
COMMISSION = 0.05


MODES = {
    "dice":       {"label": "🎲 Кости",      "emoji": "🎲"},
    "darts":      {"label": "🎯 Дартс",      "emoji": "🎯"},
    "basketball": {"label": "🏀 Баскетбол",  "emoji": "🏀"},
    "football":   {"label": "⚽ Футбол",     "emoji": "⚽"},
    "roulette":   {"label": "🎡 Рулетка",    "emoji": "🎡"},
    "coin":       {"label": "🪙 Монетка",    "emoji": "🪙"},
}


class OnlineState(StatesGroup):
    waiting_bet = State()


def _deduct(user_id: int, amount: int) -> bool:
    """Атомарное списание ставки с профиля игрока."""
    try:
        cursor.execute("BEGIN IMMEDIATE")
        cursor.execute(
            "UPDATE users SET balance = balance - ? WHERE id = ? AND balance >= ?",
            (amount, user_id, amount),
        )
        ok = cursor.rowcount > 0
        conn.commit()
        return ok
    except Exception:
        cursor.execute("ROLLBACK")
        logger.exception("online:_deduct")
        return False


def _credit(user_id: int, amount: int) -> None:
    if amount <= 0:
        return
    cursor.execute(
        "UPDATE users SET balance = balance + ? WHERE id = ?",
        (amount, user_id),
    )
    conn.commit()


def _menu_text(user_id: int) -> str:
    user_data = db_get_user(user_id)
    wins = user_data[13] if len(user_data) > 13 else 0
    has_free = db_has_free_games(user_id)
    if has_free:
        status = "🏆 VIP: все игры бесплатны"
    else:
        status = f"🏅 Побед: {wins}/50 до бесплатного входа"
    return (
        "🌐 <b>Онлайн — 1×1 дуэли</b>\n\n"
        f"{status}\n\n"
        "Выбирай режим игры, создавай заявку или присоединяйся к существующей.\n"
        "Комиссия арены: 5% с выигрыша."
    )


def _menu_kb() -> types.InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🎲 Кости",     callback_data="on:mode:dice")
    kb.button(text="🎯 Дартс",     callback_data="on:mode:darts")
    kb.button(text="🏀 Баскет",    callback_data="on:mode:basketball")
    kb.button(text="⚽ Футбол",    callback_data="on:mode:football")
    kb.button(text="🎡 Рулетка",   callback_data="on:mode:roulette")
    kb.button(text="🪙 Монетка",   callback_data="on:mode:coin")
    kb.button(text="🔍 Найти соперника", callback_data="on:list")
    kb.button(text="📋 Мои заявки",      callback_data="on:my")
    kb.adjust(2, 2, 2, 1, 1)
    return kb.as_markup()


@router.message(Command("online", "pvp"))
async def online_menu(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(_menu_text(message.from_user.id), reply_markup=_menu_kb(), parse_mode="HTML")


@router.callback_query(F.data == "on:menu")
async def on_menu_cb(call: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await call.answer()
    try:
        await call.message.edit_text(_menu_text(call.from_user.id), reply_markup=_menu_kb(), parse_mode="HTML")
    except Exception:
        await call.message.answer(_menu_text(call.from_user.id), reply_markup=_menu_kb(), parse_mode="HTML")


@router.callback_query(F.data.startswith("on:mode:"))
async def on_pick_mode(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    mode = call.data.split(":")[2]
    if mode not in MODES:
        return
    await state.update_data(game_mode=mode)
    await state.set_state(OnlineState.waiting_bet)

    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Назад", callback_data="on:menu")
    try:
        await call.message.edit_text(
            f"💸 <b>Дуэль — {MODES[mode]['label']}</b>\n\n"
            f"Введи сумму ставки (мин. {MIN_BET:,} 💎, макс. {MAX_BET:,} 💎).",
            reply_markup=kb.as_markup(),
            parse_mode="HTML",
        )
    except Exception:
        pass


@router.message(OnlineState.waiting_bet)
async def on_create(message: types.Message, state: FSMContext):
    if not (message.text or "").isdigit():
        return await message.reply("❌ Нужно число.")
    bet = int(message.text)
    if bet < MIN_BET:
        return await message.reply(f"❌ Минимальная ставка — {MIN_BET:,} 💎.")
    if bet > MAX_BET:
        return await message.reply(f"❌ Максимальная ставка — {MAX_BET:,} 💎.")

    user_id = message.from_user.id
    has_free = db_has_free_games(user_id)

    if not has_free:
        if not _deduct(user_id, bet):
            balance = db_get_user(user_id)[0]
            return await message.reply(f"❌ Недостаточно средств. Баланс: {balance:,} 💎")

    data = await state.get_data()
    mode = data.get("game_mode", "dice")
    join_type = "free" if has_free else "paid"

    cursor.execute(
        "INSERT INTO pvp_games (creator_id, bet, created_at, join_type, game_mode, status) "
        "VALUES (?, ?, ?, ?, ?, 'waiting')",
        (user_id, bet, int(time.time()), join_type, mode),
    )
    conn.commit()
    game_id = cursor.lastrowid
    await state.clear()

    kb = InlineKeyboardBuilder()
    kb.button(text="❌ Отменить заявку", callback_data=f"on:cancel:{game_id}")
    kb.button(text="⬅️ В меню", callback_data="on:menu")
    kb.adjust(1)
    await message.answer(
        f"✅ <b>Заявка #{game_id} создана</b>\n\n"
        f"Режим: {MODES[mode]['label']}\n"
        f"Ставка: <b>{bet:,}</b> 💎 "
        f"({'🏆 VIP' if has_free else '💰 Платная'})\n"
        f"⏳ Ждём соперника…",
        reply_markup=kb.as_markup(),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("on:list"))
async def on_list(call: types.CallbackQuery):
    await call.answer()
    parts = call.data.split(":")
    mode_filter: Optional[str] = parts[2] if len(parts) >= 3 else None

    if mode_filter:
        cursor.execute(
            "SELECT id, creator_id, bet, game_mode FROM pvp_games "
            "WHERE status = 'waiting' AND game_mode = ? ORDER BY bet DESC LIMIT 10",
            (mode_filter,),
        )
    else:
        cursor.execute(
            "SELECT id, creator_id, bet, game_mode FROM pvp_games "
            "WHERE status = 'waiting' ORDER BY bet DESC LIMIT 10"
        )
    games = cursor.fetchall()

    kb = InlineKeyboardBuilder()
    for key, meta in MODES.items():
        kb.button(text=meta["emoji"], callback_data=f"on:list:{key}")

    if not games:
        kb.button(text="⬅️ В меню", callback_data="on:menu")
        kb.adjust(len(MODES), 1)
        try:
            return await call.message.edit_text(
                "🔍 <b>Заявок нет</b>\nСтань первым, кто создаст дуэль.",
                reply_markup=kb.as_markup(),
                parse_mode="HTML",
            )
        except Exception:
            return

    for gid, cr_id, bet, mode in games:
        meta = MODES.get(mode, {"emoji": "🎮"})
        if cr_id == call.from_user.id:
            kb.button(text=f"🗑 #{gid} {meta['emoji']} {bet:,}", callback_data=f"on:cancel:{gid}")
        else:
            kb.button(text=f"⚔️ {meta['emoji']} {bet:,}", callback_data=f"on:join:{gid}")
            kb.button(text=f"🆓 {meta['emoji']}",          callback_data=f"on:join_free:{gid}")

    kb.button(text="🔄 Обновить", callback_data="on:list")
    kb.button(text="⬅️ В меню",   callback_data="on:menu")

    layout = [len(MODES)]
    mine = [g for g in games if g[1] == call.from_user.id]
    others = [g for g in games if g[1] != call.from_user.id]
    layout += [1] * len(mine)
    layout += [2] * len(others)
    layout += [2]
    kb.adjust(*layout)

    try:
        await call.message.edit_text(
            "🔍 <b>Заявки</b>\n⚔️ — платная (полный приз)\n🆓 — бесплатная (50% приза)\n"
            + (f"Фильтр: <code>{mode_filter}</code>\n" if mode_filter else ""),
            reply_markup=kb.as_markup(),
            parse_mode="HTML",
        )
    except Exception:
        pass


@router.callback_query(F.data.startswith("on:cancel:"))
async def on_cancel(call: types.CallbackQuery):
    game_id = int(call.data.split(":")[2])
    user_id = call.from_user.id
    cursor.execute("SELECT creator_id, bet, status, join_type FROM pvp_games WHERE id = ?", (game_id,))
    row = cursor.fetchone()
    if not row:
        return await call.answer("❌ Заявка не найдена.", show_alert=True)
    cr_id, bet, status, join_type = row
    if cr_id != user_id:
        return await call.answer("❌ Это не твоя заявка.", show_alert=True)
    if status != "waiting":
        return await call.answer("❌ Игра уже началась.", show_alert=True)

    if join_type == "paid":
        _credit(user_id, bet)
    cursor.execute("DELETE FROM pvp_games WHERE id = ?", (game_id,))
    conn.commit()
    await call.answer("✅ Заявка отменена, ставка возвращена.")
    await on_list(call)


@router.callback_query(F.data.startswith("on:my"))
async def on_my(call: types.CallbackQuery):
    await call.answer()
    uid = call.from_user.id
    cursor.execute(
        "SELECT id, bet, game_mode FROM pvp_games WHERE creator_id = ? AND status = 'waiting' ORDER BY id DESC",
        (uid,),
    )
    rows = cursor.fetchall()
    kb = InlineKeyboardBuilder()
    if not rows:
        text = "📋 У тебя нет активных заявок."
    else:
        text = "📋 <b>Активные заявки</b>\n\n"
        for gid, bet, mode in rows:
            meta = MODES.get(mode, {"emoji": "🎮"})
            text += f"• #{gid} {meta['emoji']} — {bet:,} 💎\n"
            kb.button(text=f"🗑 Отменить #{gid}", callback_data=f"on:cancel:{gid}")
    kb.button(text="⬅️ В меню", callback_data="on:menu")
    kb.adjust(1)
    try:
        await call.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")
    except Exception:
        pass


@router.callback_query(F.data.startswith("on:join"))
async def on_join(call: types.CallbackQuery):
    is_free_request = "free" in call.data
    game_id = int(call.data.split(":")[-1])
    joiner_id = call.from_user.id

    cursor.execute(
        "SELECT creator_id, bet, status, game_mode, join_type FROM pvp_games WHERE id = ?",
        (game_id,),
    )
    row = cursor.fetchone()
    if not row:
        return await call.answer("❌ Заявка не найдена.", show_alert=True)
    cr_id, bet, status, mode, creator_join = row
    if status != "waiting":
        return await call.answer("❌ Уже идёт или завершена.", show_alert=True)
    if cr_id == joiner_id:
        return await call.answer("❌ Нельзя против себя.", show_alert=True)

    joiner_has_free = db_has_free_games(joiner_id)
    joiner_is_free = is_free_request or joiner_has_free

    deducted = False
    if not joiner_is_free:
        if not _deduct(joiner_id, bet):
            balance = db_get_user(joiner_id)[0]
            return await call.answer(f"❌ Нужно {bet:,} 💎. Баланс: {balance:,}", show_alert=True)
        deducted = True

    cursor.execute(
        "UPDATE pvp_games SET joiner_id = ?, status = 'active', join_type = ? "
        "WHERE id = ? AND status = 'waiting'",
        (joiner_id, "free" if joiner_is_free else "paid", game_id),
    )
    if cursor.rowcount == 0:
        if deducted:
            _credit(joiner_id, bet)
        conn.commit()
        return await call.answer("❌ Другой игрок успел раньше.", show_alert=True)
    conn.commit()

    await call.answer()
    await call.message.edit_text(
        f"⚔️ <b>Дуэль #{game_id}</b>\n"
        f"Режим: {MODES[mode]['label']}\n"
        f"Создатель: <code>{cr_id}</code>\n"
        f"Соперник:  <code>{joiner_id}</code> "
        f"({'🆓 бесплатно' if joiner_is_free else '💰 платно'})\n"
        f"Банк: <b>{(bet if joiner_is_free else bet * 2):,}</b> 💎",
        parse_mode="HTML",
    )

    player_free_flag = joiner_is_free and creator_join != "free"
    try:
        if mode == "coin":
            await play_coin(call, cr_id, joiner_id, bet, player_free_flag, game_id)
        elif mode == "roulette":
            await play_roulette(call, cr_id, joiner_id, bet, player_free_flag, game_id)
        else:
            await play_dice_mode(call, cr_id, joiner_id, bet, player_free_flag, game_id, mode)
    except Exception:
        logger.exception("online: play error mode=%s", mode)


async def _spin_dice(bot, chat_id: int, emoji: str) -> int:
    msg = await bot.send_dice(chat_id, emoji=emoji)
    await asyncio.sleep(3)
    return msg.dice.value


async def play_dice_mode(call, cr_id, joiner_id, bet, is_free, game_id, mode):
    meta = MODES[mode]
    bot = call.message.bot
    chat_id = call.message.chat.id

    await call.message.answer(f"{meta['emoji']} Ход создателя…", parse_mode="HTML")
    await asyncio.sleep(1)
    val1 = await _spin_dice(bot, chat_id, meta["emoji"])

    await call.message.answer(f"{meta['emoji']} Ход соперника…", parse_mode="HTML")
    await asyncio.sleep(1)
    val2 = await _spin_dice(bot, chat_id, meta["emoji"])

    await finish_duel(call, cr_id, joiner_id, val1, val2, bet, is_free, game_id, meta["label"])


async def play_roulette(call, cr_id, joiner_id, bet, is_free, game_id):
    bot = call.message.bot
    chat_id = call.message.chat.id

    await call.message.answer("🎡 Крутим барабан для создателя…", parse_mode="HTML")
    await asyncio.sleep(1.5)
    v1 = random.randint(0, 36)
    await bot.send_message(chat_id, f"🎡 Выпало у создателя: <b>{v1}</b>", parse_mode="HTML")
    await asyncio.sleep(1)

    await call.message.answer("🎡 Крутим барабан для соперника…", parse_mode="HTML")
    await asyncio.sleep(1.5)
    v2 = random.randint(0, 36)
    await bot.send_message(chat_id, f"🎡 Выпало у соперника: <b>{v2}</b>", parse_mode="HTML")
    await asyncio.sleep(1)

    await finish_duel(call, cr_id, joiner_id, v1, v2, bet, is_free, game_id, "🎡 Рулетка")


async def play_coin(call, cr_id, joiner_id, bet, is_free, game_id):
    bot = call.message.bot
    chat_id = call.message.chat.id

    v1 = random.randint(0, 1)
    v2 = 1 - v1
    label = {0: "Орёл 🦅", 1: "Решка 🪙"}
    await call.message.answer("🪙 Подбрасываем монетку…", parse_mode="HTML")
    await asyncio.sleep(1.5)

    target = random.randint(0, 1)
    await bot.send_message(
        chat_id,
        f"🪙 Выпало: <b>{label[target]}</b>\n"
        f"Создатель ставил: {label[v1]}\n"
        f"Соперник ставил:  {label[v2]}",
        parse_mode="HTML",
    )
    if v1 == target:
        await finish_duel(call, cr_id, joiner_id, 1, 0, bet, is_free, game_id, "🪙 Монетка")
    else:
        await finish_duel(call, cr_id, joiner_id, 0, 1, bet, is_free, game_id, "🪙 Монетка")


async def finish_duel(call, cr_id, joiner_id, val1, val2, bet, is_free, game_id, label):
    winner_id: Optional[int] = None
    lines = []

    if val1 > val2:
        winner_id = cr_id
        if is_free:
            win_amount = bet
            _credit(cr_id, win_amount)
            lines.append(f"🏆 Победил создатель. Возврат ставки: {win_amount:,} 💎")
        else:
            pot = bet * 2
            win_amount = pot - int(pot * COMMISSION)
            _credit(cr_id, win_amount)
            lines.append(f"🏆 Победил создатель. Выигрыш: {win_amount:,} 💎 (комиссия {int(pot * COMMISSION):,})")
    elif val2 > val1:
        winner_id = joiner_id
        if is_free:
            win_amount = int(bet * 0.5)
            refund = bet - win_amount
            _credit(joiner_id, win_amount)
            _credit(cr_id, refund)
            lines.append(f"🏆 Победил соперник. Приз: {win_amount:,} 💎 (создателю вернули {refund:,} 💎)")
        else:
            pot = bet * 2
            win_amount = pot - int(pot * COMMISSION)
            _credit(joiner_id, win_amount)
            lines.append(f"🏆 Победил соперник. Выигрыш: {win_amount:,} 💎 (комиссия {int(pot * COMMISSION):,})")
    else:
        _credit(cr_id, bet)
        if not is_free:
            _credit(joiner_id, bet)
        lines.append(f"🤝 Ничья ({val1} : {val2}). Ставки возвращены.")

    cursor.execute(
        "UPDATE pvp_games SET status = 'finished', winner_id = ? WHERE id = ?",
        (winner_id, game_id),
    )
    conn.commit()

    if winner_id:
        new_wins = db_increment_pvp_wins(winner_id)
        if new_wins == 50:
            try:
                await safe_send_message(
                    call.message.bot,
                    winner_id,
                    "🎉 Ты достиг 50 побед в онлайн-режиме!\n"
                    "Теперь все онлайн-игры для тебя бесплатные.",
                    parse_mode="HTML",
                )
            except Exception:
                pass

    header = f"⚔️ <b>Дуэль #{game_id} — {label}</b>\nСчёт: {val1} : {val2}"
    try:
        await call.message.answer("\n".join([header] + lines), parse_mode="HTML")
    except Exception:
        pass

    msg = f"{header}\n" + "\n".join(lines)
    for uid in {cr_id, joiner_id}:
        try:
            await safe_send_message(call.message.bot, uid, msg, parse_mode="HTML")
        except Exception:
            pass
