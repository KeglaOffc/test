"""Админ-панель казино-бота.

Все команды и callback-ы защищены проверкой ADMIN_ID.
"""
import asyncio
import os

from aiogram import F, Router, types
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database import (
    conn,
    cursor,
    db_get_global_stats,
    db_get_role,
    db_get_user,
    db_set_rig,
    db_set_role,
    get_maintenance_mode,
    get_real_id,
    is_admin_or_higher,
    set_maintenance_mode,
)
from Handlers.mining import CATALOG as MINING_CATALOG

router = Router()

OWNER_ID = int(os.getenv("ADMIN_ID", "5030561581"))

ALLOWED_ITEMS = (
    "mine_shield",
    "mine_scan",
    "energy_drink",
    "gold_ticket",
    "rerolls",
    "bet_insure",
)


def is_admin(user_id: int) -> bool:
    return is_admin_or_higher(user_id)


def is_owner(user_id: int) -> bool:
    return user_id == OWNER_ID or db_get_role(user_id) == "owner"


def back_to_panel_kb() -> types.InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Назад в панель", callback_data="admin:back")
    return builder.as_markup()


def build_admin_panel():
    stats = db_get_global_stats()
    total_users = stats[0] if stats[0] else 0
    total_bank = stats[1] if stats[1] else 0

    cursor.execute("SELECT COUNT(*) FROM users WHERE banned = 1")
    banned_count = cursor.fetchone()[0]

    builder = InlineKeyboardBuilder()
    builder.button(text="💰 Баланс", callback_data="admin:balance")
    builder.button(text="🔍 Информация", callback_data="admin:info")
    builder.button(text="🚫 Блокировки", callback_data="admin:ban")
    builder.button(text="⭐ Предметы", callback_data="admin:items")
    builder.button(text="⛏️ Майнинг", callback_data="admin:mining")
    builder.button(text="🎮 Игроки", callback_data="admin:players")
    builder.button(text="🎚 Подкрут", callback_data="admin:rig")
    builder.button(text="👑 Привилегии", callback_data="admin:privileges")
    builder.button(text="⏱ Сброс КД", callback_data="admin:cd")
    builder.button(text="📊 Экономика", callback_data="admin:econ")
    builder.button(text="📢 Рассылка", callback_data="admin:broadcast")
    builder.button(text="🏆 Топ", callback_data="admin:top")
    builder.button(text="📈 Статистика", callback_data="admin:stats")
    builder.button(text="🎁 Раздача всем", callback_data="admin:giveall")
    builder.button(text="🏷 Роли", callback_data="admin:roles")

    is_maint = get_maintenance_mode()
    maint_text = "🔴 Тех. работы: ВКЛ" if is_maint else "🟢 Тех. работы: ВЫКЛ"
    builder.button(text=maint_text, callback_data="admin:toggle_maintenance")

    builder.adjust(2, 2, 2, 2, 2, 2, 2, 2, 1)

    text = (
        "👑 <b>АДМИН-ПАНЕЛЬ</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"👥 Игроков: <code>{total_users}</code>\n"
        f"💰 Общий банк: <code>{total_bank:,}</code> 💎\n"
        f"🚫 Забанено: <code>{banned_count}</code>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "Выберите раздел или используйте команды ниже."
    )
    return text, builder.as_markup()


@router.message(Command("admin"))
async def admin_panel(message: types.Message):
    if message.chat.type != "private" or not is_admin(message.from_user.id):
        return
    text, markup = build_admin_panel()
    await message.answer(text, reply_markup=markup, parse_mode="HTML")


@router.callback_query(F.data == "admin:back")
async def admin_back(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer()
    text, markup = build_admin_panel()
    await call.message.edit_text(text, reply_markup=markup, parse_mode="HTML")
    await call.answer()


@router.callback_query(F.data == "admin:toggle_maintenance")
async def admin_toggle_maintenance(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer()
    new_state = not get_maintenance_mode()
    set_maintenance_mode(new_state)
    await call.answer(
        "🔧 Тех. работы " + ("ВКЛЮЧЕНЫ" if new_state else "ВЫКЛЮЧЕНЫ")
    )
    text, markup = build_admin_panel()
    await call.message.edit_text(text, reply_markup=markup, parse_mode="HTML")


@router.message(Command("maintenance"))
async def admin_maintenance_cmd(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) < 2:
        state = "ВКЛЮЧЕНЫ" if get_maintenance_mode() else "ВЫКЛЮЧЕНЫ"
        return await message.answer(
            f"🔧 Статус тех. работ: <b>{state}</b>\n"
            "Использование: <code>/maintenance [on/off]</code>",
            parse_mode="HTML",
        )

    arg = parts[1].lower()
    if arg in ("on", "1", "true"):
        set_maintenance_mode(True)
        await message.answer(
            "🔴 <b>Технические работы ВКЛЮЧЕНЫ</b>\n"
            "Бот доступен только администраторам.",
            parse_mode="HTML",
        )
    elif arg in ("off", "0", "false"):
        set_maintenance_mode(False)
        await message.answer(
            "🟢 <b>Технические работы ВЫКЛЮЧЕНЫ</b>\nБот доступен всем.",
            parse_mode="HTML",
        )
    else:
        await message.answer(
            "Использование: <code>/maintenance [on/off]</code>", parse_mode="HTML"
        )




@router.callback_query(F.data == "admin:balance")
async def admin_balance_menu(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer()
    text = (
        "<b>💰 УПРАВЛЕНИЕ БАЛАНСОМ</b>\n\n"
        "<code>/setbal [Ник/ID] [сумма]</code> — установить точную сумму\n"
        "<code>/addbal [Ник/ID] [сумма]</code> — добавить сумму\n"
        "<code>/subbal [Ник/ID] [сумма]</code> — отнять сумму\n"
        "<code>/reset_money [Ник/ID]</code> — обнулить баланс\n\n"
        "Пример: <code>/setbal 123456789 100000</code>"
    )
    await call.message.edit_text(text, reply_markup=back_to_panel_kb(), parse_mode="HTML")


@router.callback_query(F.data == "admin:ban")
async def admin_ban_menu(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer()
    text = (
        "<b>🚫 БЛОКИРОВКИ</b>\n\n"
        "<code>/ban [Ник/ID]</code> — забанить/разбанить игрока\n"
        "<code>/getbans</code> — список забаненных\n"
        "<code>/deluser [ID]</code> — полностью удалить игрока (необратимо!)"
    )
    await call.message.edit_text(text, reply_markup=back_to_panel_kb(), parse_mode="HTML")


@router.callback_query(F.data == "admin:info")
async def admin_info_menu(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer()
    text = (
        "<b>🔍 ИНФОРМАЦИЯ О ИГРОКАХ</b>\n\n"
        "<code>/info [Ник/ID]</code> — подробная карточка игрока\n"
        "<code>/show_mines [ID]</code> — карта мин активной игры\n"
        "<code>/allplayers</code> — топ игроков по балансу"
    )
    await call.message.edit_text(text, reply_markup=back_to_panel_kb(), parse_mode="HTML")


@router.callback_query(F.data == "admin:stats")
async def admin_stats_menu(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer()
    stats = db_get_global_stats()

    cursor.execute("SELECT COUNT(*) FROM users WHERE banned = 1")
    banned_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM daily_stats WHERE profit > 0")
    winners_today = cursor.fetchone()[0]

    text = (
        "<b>📊 СТАТИСТИКА БОТА</b>\n\n"
        f"👥 Всего игроков: <code>{stats[0] or 0}</code>\n"
        f"💰 Общий банк: <code>{(stats[1] or 0):,}</code> 💎\n"
        f"🚫 Забанено: <code>{banned_count}</code>\n"
        f"🏆 Выигравших сегодня: <code>{winners_today}</code>"
    )
    await call.message.edit_text(text, reply_markup=back_to_panel_kb(), parse_mode="HTML")


@router.callback_query(F.data == "admin:items")
async def admin_items_menu(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer()
    text = (
        "<b>⭐ ВЫДАЧА ПРЕДМЕТОВ</b>\n\n"
        "<code>/additem [Ник/ID] [предмет] [кол-во]</code>\n\n"
        "Доступные предметы:\n"
        "• <code>mine_shield</code> — саперный щит\n"
        "• <code>mine_scan</code> — сканер мин\n"
        "• <code>energy_drink</code> — энергетик\n"
        "• <code>gold_ticket</code> — золотой билет\n"
        "• <code>rerolls</code> — переброс кубика\n"
        "• <code>bet_insure</code> — страховка\n\n"
        "Пример: <code>/additem player1 energy_drink 5</code>"
    )
    await call.message.edit_text(text, reply_markup=back_to_panel_kb(), parse_mode="HTML")


@router.callback_query(F.data == "admin:broadcast")
async def admin_broadcast_menu(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer()
    text = (
        "<b>📢 РАССЫЛКА</b>\n\n"
        "<code>/broadcast [текст]</code> — всем игрокам\n"
        "<code>/bcgroup [ID группы] [текст]</code> — в конкретный чат\n\n"
        "Пример: <code>/broadcast 🎉 Сегодня удвоенная награда в лотерее!</code>"
    )
    await call.message.edit_text(text, reply_markup=back_to_panel_kb(), parse_mode="HTML")


@router.callback_query(F.data == "admin:players")
async def admin_players_menu(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer()
    text = (
        "<b>🎮 УПРАВЛЕНИЕ ИГРОКАМИ</b>\n\n"
        "<code>/reset_user [ID]</code> — полный сброс\n"
        "<code>/reset_money [ID]</code> — обнулить баланс\n"
        "<code>/deluser [ID]</code> — удалить игрока\n"
        "<code>/getbans</code> — список забаненных\n"
        "<code>/allplayers</code> — все игроки"
    )
    await call.message.edit_text(text, reply_markup=back_to_panel_kb(), parse_mode="HTML")


@router.callback_query(F.data == "admin:mining")
async def admin_mining_menu(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer()
    text = (
        "<b>⛏️ УПРАВЛЕНИЕ МАЙНИНГОМ</b>\n\n"
        "<code>/mine_add [ID] [предмет] [кол-во]</code> — выдать железо\n"
        "<code>/mine_set [ID] [мощь H/s]</code> — установить мощность\n"
        "<code>/mine_watt [ID] [W]</code> — установить потребление\n"
        "<code>/mine_reset [ID]</code> — сбросить ферму\n"
        "<code>/mine_boost [ID] [кол-во]</code> — выдать энергетики"
    )
    await call.message.edit_text(text, reply_markup=back_to_panel_kb(), parse_mode="HTML")




@router.message(Command("setbal"))
async def admin_setbal(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    try:
        _, target, amt_s = message.text.split(maxsplit=2)
        amt = int(amt_s)
    except ValueError:
        return await message.answer(
            "Формат: <code>/setbal [Ник/ID] [сумма]</code>", parse_mode="HTML"
        )

    real_id = get_real_id(target)
    if not real_id:
        return await message.answer("❌ Игрок не найден.")

    cursor.execute("UPDATE users SET balance = ? WHERE id = ?", (amt, real_id))
    conn.commit()
    await message.answer(
        f"✅ Баланс <code>{target}</code> установлен на {amt:,} 💎", parse_mode="HTML"
    )


@router.message(Command("addbal"))
async def admin_addbal(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    try:
        _, target, amt_s = message.text.split(maxsplit=2)
        amt = int(amt_s)
    except ValueError:
        return await message.answer(
            "Формат: <code>/addbal [Ник/ID] [сумма]</code>", parse_mode="HTML"
        )

    real_id = get_real_id(target)
    if not real_id:
        return await message.answer("❌ Игрок не найден.")

    cursor.execute("UPDATE users SET balance = balance + ? WHERE id = ?", (amt, real_id))
    conn.commit()
    await message.answer(
        f"✅ Добавлено {amt:,} 💎 игроку <code>{target}</code>", parse_mode="HTML"
    )


@router.message(Command("subbal"))
async def admin_subbal(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    try:
        _, target, amt_s = message.text.split(maxsplit=2)
        amt = int(amt_s)
    except ValueError:
        return await message.answer(
            "Формат: <code>/subbal [Ник/ID] [сумма]</code>", parse_mode="HTML"
        )

    real_id = get_real_id(target)
    if not real_id:
        return await message.answer("❌ Игрок не найден.")

    cursor.execute(
        "UPDATE users SET balance = MAX(0, balance - ?) WHERE id = ?", (amt, real_id)
    )
    conn.commit()
    await message.answer(
        f"✅ Отнято {amt:,} 💎 у игрока <code>{target}</code>", parse_mode="HTML"
    )


@router.message(Command("reset_money"))
async def admin_reset_money(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    try:
        target = message.text.split()[1]
    except IndexError:
        return await message.answer(
            "Формат: <code>/reset_money [Ник/ID]</code>", parse_mode="HTML"
        )
    real_id = get_real_id(target)
    if not real_id:
        return await message.answer("❌ Игрок не найден.")
    cursor.execute("UPDATE users SET balance = 0 WHERE id = ?", (real_id,))
    conn.commit()
    await message.answer(f"✅ Баланс игрока <code>{target}</code> обнулён.", parse_mode="HTML")




@router.message(Command("rig", "podk"))
async def admin_rig(message: types.Message):
    """/rig <id> true|false|off — выставляет глобальную подкрутку для игрока."""
    if not is_admin(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) < 3:
        return await message.answer(
            "Формат: <code>/rig [ID|ник] [true|false|off]</code>\n"
            "• <code>true</code> — всегда победа\n"
            "• <code>false</code> — всегда поражение\n"
            "• <code>off</code> — честный режим",
            parse_mode="HTML",
        )
    target, mode = parts[1], parts[2].lower()
    mode_map = {"true": "win", "false": "lose", "off": "off", "win": "win", "lose": "lose"}
    if mode not in mode_map:
        return await message.answer("❌ Значение: true / false / off")

    real_id = get_real_id(target)
    if not real_id:
        return await message.answer("❌ Игрок не найден.")

    if not db_set_rig(real_id, mode_map[mode]):
        return await message.answer("❌ Не удалось применить подкрут.")

    label = {"win": "🟢 всегда победа", "lose": "🔴 всегда поражение", "off": "⚪ отключена"}
    await message.answer(
        f"✅ Подкрут для <code>{real_id}</code>: {label[mode_map[mode]]}",
        parse_mode="HTML",
    )


@router.message(Command("rigs"))
async def admin_rig_list(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    cursor.execute("SELECT id, custom_id, rig_force FROM users WHERE rig_force IN ('win','lose')")
    rows = cursor.fetchall()
    if not rows:
        return await message.answer("ℹ️ Подкруток сейчас нет.")
    lines = [
        f"• <code>{rid}</code> ({cid}): <b>{rig}</b>"
        for rid, cid, rig in rows
    ]
    await message.answer("🎚 <b>Активные подкруты:</b>\n" + "\n".join(lines), parse_mode="HTML")


@router.message(Command("setvip"))
async def admin_set_vip(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) < 3:
        return await message.answer(
            "Формат: <code>/setvip [ID|ник] [bronze|silver|gold|none]</code>",
            parse_mode="HTML",
        )
    target, tier = parts[1], parts[2].lower()
    if tier not in ("bronze", "silver", "gold", "none"):
        return await message.answer("❌ Тиры: bronze / silver / gold / none")
    real_id = get_real_id(target)
    if not real_id:
        return await message.answer("❌ Игрок не найден.")
    cursor.execute("UPDATE users SET privilege = ? WHERE id = ?", (tier, real_id))
    conn.commit()
    await message.answer(
        f"👑 Привилегия <code>{real_id}</code> установлена: <b>{tier}</b>",
        parse_mode="HTML",
    )


@router.message(Command("resetcd"))
async def admin_reset_cd(message: types.Message):
    """Сбрасывает КД на /bonus и /wheel."""
    if not is_admin(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) < 2:
        return await message.answer(
            "Формат: <code>/resetcd [ID|ник]</code>", parse_mode="HTML"
        )
    real_id = get_real_id(parts[1])
    if not real_id:
        return await message.answer("❌ Игрок не найден.")
    cursor.execute(
        "UPDATE users SET last_bonus = 0, last_wheel = 0 WHERE id = ?",
        (real_id,),
    )
    conn.commit()
    await message.answer(f"⏱ КД сброшено для <code>{real_id}</code>.", parse_mode="HTML")


@router.message(Command("econ"))
async def admin_econ(message: types.Message):
    """Сводка по экономике бота."""
    if not is_admin(message.from_user.id):
        return
    cursor.execute("SELECT COUNT(*), COALESCE(SUM(balance), 0) FROM users")
    total_users, total_bal = cursor.fetchone()
    cursor.execute("SELECT AVG(balance) FROM users")
    avg_bal = cursor.fetchone()[0] or 0
    cursor.execute(
        "SELECT privilege, COUNT(*) FROM users GROUP BY privilege"
    )
    priv_rows = cursor.fetchall()
    cursor.execute("SELECT COALESCE(SUM(profit), 0) FROM daily_stats")
    daily_profit = cursor.fetchone()[0] or 0
    cursor.execute(
        "SELECT COUNT(*) FROM lottery_tickets WHERE status = 'active'"
    )
    active_tickets = cursor.fetchone()[0] or 0

    priv_txt = ", ".join(f"{p or 'none'}: {c}" for p, c in priv_rows) or "—"
    text = (
        "📊 <b>ЭКОНОМИКА БОТА</b>\n"
        "━━━━━━━━━━━━━\n"
        f"👥 Игроков: {total_users}\n"
        f"💰 Общий банк: {total_bal:,} 💎\n"
        f"📈 Средний баланс: {int(avg_bal):,} 💎\n"
        f"🎟 Активных билетов: {active_tickets}\n"
        f"📅 Прибыль за сегодня (net): {daily_profit:,} 💎\n"
        f"👑 По привилегиям: {priv_txt}\n"
    )
    await message.answer(text, parse_mode="HTML")


@router.callback_query(F.data == "admin:rig")
async def admin_rig_menu(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer()
    cursor.execute("SELECT id, custom_id, rig_force FROM users WHERE rig_force IN ('win','lose')")
    rows = cursor.fetchall()
    rig_list = (
        "\n".join(f"• <code>{rid}</code> ({cid}): <b>{rig}</b>" for rid, cid, rig in rows)
        if rows else "—"
    )
    text = (
        "<b>🎚 ПОДКРУТ</b>\n\n"
        "<code>/rig [ID|ник] true|false|off</code>\n"
        "• <code>true</code> — всегда победа в играх без telegram-дайса\n"
        "• <code>false</code> — всегда поражение\n"
        "• <code>off</code> — честно\n\n"
        "Подкрут работает в: 💣 mines, 🎡 roulette, 📦 chests, 🪙 flip, 🚀 crash.\n"
        "Игры через telegram-дайс (slots / dice / darts / football / basket) управляются Telegram и не подкручиваются.\n\n"
        f"<b>Сейчас активно:</b>\n{rig_list}"
    )
    await call.message.edit_text(text, reply_markup=back_to_panel_kb(), parse_mode="HTML")


@router.callback_query(F.data == "admin:privileges")
async def admin_privileges_menu(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer()
    cursor.execute(
        "SELECT privilege, COUNT(*) FROM users WHERE privilege != 'none' GROUP BY privilege"
    )
    rows = cursor.fetchall()
    priv_list = "\n".join(f"• {p}: <b>{c}</b>" for p, c in rows) or "—"
    text = (
        "<b>👑 ПРИВИЛЕГИИ</b>\n\n"
        "<code>/setvip [ID|ник] bronze|silver|gold|none</code>\n\n"
        "Тиры:\n"
        "• 🥉 Bronze — +2% кэшбэк\n"
        "• 🥈 Silver — +5% кэшбэк\n"
        "• 🥇 Gold — +10% кэшбэк, двойной ежедневный бонус\n\n"
        f"<b>Выдано сейчас:</b>\n{priv_list}"
    )
    await call.message.edit_text(text, reply_markup=back_to_panel_kb(), parse_mode="HTML")


@router.callback_query(F.data == "admin:cd")
async def admin_cd_menu(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer()
    text = (
        "<b>⏱ СБРОС КД</b>\n\n"
        "<code>/resetcd [ID|ник]</code> — сбрасывает КД на /bonus и /wheel\n"
    )
    await call.message.edit_text(text, reply_markup=back_to_panel_kb(), parse_mode="HTML")


@router.callback_query(F.data == "admin:roles")
async def admin_roles_menu(call: types.CallbackQuery):
    if not is_owner(call.from_user.id):
        return await call.answer("Только для OWNER.", show_alert=True)
    cursor.execute(
        "SELECT id, custom_id, role FROM users WHERE role IN ('admin', 'helper') ORDER BY role DESC, id"
    )
    rows = cursor.fetchall() or []
    staff_lines = []
    for uid, nick, role in rows:
        label = "🛡 ADMIN" if role == "admin" else "🎧 HELPER"
        name = f"@{nick}" if nick else f"<code>{uid}</code>"
        staff_lines.append(f"{label} — {name} (id <code>{uid}</code>)")
    staff = "\n".join(staff_lines) if staff_lines else "— пусто —"
    text = (
        "<b>🏷 УПРАВЛЕНИЕ РОЛЯМИ</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "Роли:\n"
        "👑 <b>OWNER</b> — только ты (из env <code>ADMIN_ID</code>).\n"
        "🛡 <b>ADMIN</b> — все админ-команды, кроме смены ролей.\n"
        "🎧 <b>HELPER</b> — просмотр инфы игроков, бан/разбан, рассылка.\n"
        "— <b>PLAYER</b> — обычный игрок.\n\n"
        "Команды:\n"
        "<code>/setrole &lt;id|ник&gt; &lt;owner|admin|helper|player&gt;</code>\n"
        "<code>/staff</code> — показать список персонала.\n\n"
        f"<b>Текущий состав:</b>\n{staff}"
    )
    await call.message.edit_text(text, reply_markup=back_to_panel_kb(), parse_mode="HTML")


@router.message(Command("setrole"))
async def cmd_setrole(message: types.Message):
    if not is_owner(message.from_user.id):
        return
    parts = (message.text or "").split()
    if len(parts) < 3:
        return await message.answer(
            "Формат: <code>/setrole &lt;id|ник&gt; &lt;owner|admin|helper|player&gt;</code>",
            parse_mode="HTML",
        )
    target = parts[1]
    role = parts[2].lower().strip()
    real_id = get_real_id(target)
    if not real_id:
        return await message.answer("❌ Игрок не найден.")
    if role == "owner":
        return await message.answer("Owner назначается только через env <code>ADMIN_ID</code>.", parse_mode="HTML")
    if not db_set_role(real_id, role):
        return await message.answer("❌ Не удалось. Допустимо: admin / helper / player.")
    await message.answer(f"✅ Роль для <code>{real_id}</code> установлена: <b>{role}</b>.", parse_mode="HTML")


@router.message(Command("staff"))
async def cmd_staff(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    cursor.execute(
        "SELECT id, custom_id, role FROM users WHERE role IN ('admin', 'helper') ORDER BY role DESC, id"
    )
    rows = cursor.fetchall() or []
    if not rows:
        return await message.answer("Список персонала пуст.")
    lines = [f"👑 OWNER — <code>{OWNER_ID}</code>"]
    for uid, nick, role in rows:
        tag = "🛡 ADMIN" if role == "admin" else "🎧 HELPER"
        name = f"@{nick}" if nick else f"<code>{uid}</code>"
        lines.append(f"{tag} — {name} (id <code>{uid}</code>)")
    await message.answer("\n".join(lines), parse_mode="HTML")


@router.callback_query(F.data == "admin:econ")
async def admin_econ_menu(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer()
    cursor.execute("SELECT COUNT(*), COALESCE(SUM(balance), 0) FROM users")
    total_users, total_bal = cursor.fetchone()
    cursor.execute("SELECT AVG(balance) FROM users")
    avg_bal = cursor.fetchone()[0] or 0
    cursor.execute("SELECT COALESCE(SUM(profit), 0) FROM daily_stats")
    daily_profit = cursor.fetchone()[0] or 0
    cursor.execute(
        "SELECT COUNT(*) FROM lottery_tickets WHERE status = 'active'"
    )
    active_tickets = cursor.fetchone()[0] or 0
    text = (
        "<b>📊 ЭКОНОМИКА</b>\n\n"
        f"👥 Игроков: {total_users}\n"
        f"💰 Общий банк: {total_bal:,} 💎\n"
        f"📈 Средний баланс: {int(avg_bal):,} 💎\n"
        f"🎟 Активных билетов: {active_tickets}\n"
        f"📅 Прибыль за сегодня (net): {daily_profit:,} 💎\n\n"
        "Подробнее: <code>/econ</code>"
    )
    await call.message.edit_text(text, reply_markup=back_to_panel_kb(), parse_mode="HTML")




@router.message(Command("ban"))
async def admin_ban(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    try:
        target = message.text.split()[1]
    except IndexError:
        return await message.answer("Формат: <code>/ban [Ник/ID]</code>", parse_mode="HTML")

    real_id = get_real_id(target)
    if not real_id:
        return await message.answer("❌ Игрок не найден.")

    u = db_get_user(real_id)
    new_ban_state = 0 if u[2] else 1
    cursor.execute("UPDATE users SET banned = ? WHERE id = ?", (new_ban_state, real_id))
    conn.commit()

    res_text = "🚫 Забанен" if new_ban_state else "✅ Разбанен"
    await message.answer(
        f"{res_text} игрок <code>{target}</code> (ID: {real_id})", parse_mode="HTML"
    )


@router.message(Command("getbans"))
async def admin_getbans(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    cursor.execute("SELECT id, custom_id, balance FROM users WHERE banned = 1 ORDER BY id DESC")
    banned = cursor.fetchall()
    if not banned:
        return await message.answer("✅ Забаненных игроков нет.")

    lines = ["<b>🚫 СПИСОК ЗАБАНЕННЫХ:</b>", ""]
    for uid, nick, balance in banned[:50]:
        lines.append(
            f"🔴 ID: <code>{uid}</code> | Ник: <code>{nick or uid}</code> | "
            f"Баланс: {balance:,} 💎"
        )
    await message.answer("\n".join(lines), parse_mode="HTML")




@router.message(Command("allplayers"))
async def admin_allplayers(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    cursor.execute("SELECT COUNT(*) FROM users")
    total = cursor.fetchone()[0]

    cursor.execute(
        "SELECT id, custom_id, balance FROM users ORDER BY balance DESC LIMIT 20"
    )
    top_players = cursor.fetchall()

    lines = [f"<b>🎮 ТОП ИГРОКОВ ({total} всего)</b>", ""]
    for i, (uid, nick, balance) in enumerate(top_players, 1):
        lines.append(f"{i}. <code>{nick or uid}</code> — {balance:,} 💎")
    await message.answer("\n".join(lines), parse_mode="HTML")


@router.message(Command("info"))
async def admin_info(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    args = message.text.split()
    if len(args) < 2:
        return await message.answer(
            "Формат: <code>/info [Ник/ID]</code>", parse_mode="HTML"
        )

    target = args[1]
    real_id = get_real_id(target)
    if not real_id:
        return await message.answer("❌ Игрок не найден.")

    u = db_get_user(real_id)
    balance, _, banned, total_bets, wins, total_games, rig_mode, _, nickname = u[:9]
    losses = total_games - wins
    net_profit = wins - total_bets
    is_banned = "🚫 Да" if banned else "✅ Нет"

    text = (
        f"🔍 <b>ДАННЫЕ ИГРОКА: {target}</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"🎫 Ник: <code>{nickname}</code>\n"
        f"🔢 ID: <code>{real_id}</code>\n"
        f"💰 Баланс: <code>{balance:,}</code> 💎\n"
        f"⚙️ Подкрутка: <code>{rig_mode}</code>\n"
        f"🚫 В бане: {is_banned}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "<b>📊 Статистика:</b>\n"
        f"🎮 Игр: <code>{total_games}</code>\n"
        f"✅ Побед: <code>{wins}</code>\n"
        f"❌ Проигрышей: <code>{losses}</code>\n"
        f"📈 Профит: <code>{net_profit:,}</code> 💎"
    )
    await message.answer(text, parse_mode="HTML")




@router.message(Command("additem"))
async def admin_additem(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    try:
        _, target, item, amount_s = message.text.split(maxsplit=3)
        amount = int(amount_s)
    except ValueError:
        return await message.answer(
            "Формат: <code>/additem [Ник/ID] [предмет] [кол-во]</code>",
            parse_mode="HTML",
        )

    real_id = get_real_id(target)
    if not real_id:
        return await message.answer("❌ Игрок не найден.")

    if item not in ALLOWED_ITEMS:
        return await message.answer(
            f"❌ Неизвестный предмет. Доступные: {', '.join(ALLOWED_ITEMS)}"
        )

    cursor.execute(
        f"UPDATE users SET {item} = COALESCE({item}, 0) + ? WHERE id = ?",
        (amount, real_id),
    )
    conn.commit()
    await message.answer(
        f"✅ Выдано {amount} x <code>{item}</code> игроку <code>{target}</code>",
        parse_mode="HTML",
    )


@router.message(Command("show_mines"))
async def admin_show_mines(message: types.Message):
    if not is_admin(message.from_user.id):
        return

    args = message.text.split()
    if len(args) < 2 or not args[1].isdigit():
        return await message.answer("❌ Введите ID игрока цифрами.")

    target_id = int(args[1])

    cursor.execute(
        "SELECT mines_pos, field_size FROM mines_games "
        "WHERE user_id = ? AND status = 'active'",
        (target_id,),
    )
    res = cursor.fetchone()
    if not res:
        return await message.answer(f"❌ У игрока {target_id} нет активной игры.")

    mine_positions = {int(x) for x in res[0].split(",")}
    size = res[1]

    grid = [f"🕵️ <b>КАРТА МИН ({size}x{size})</b>\nID: <code>{target_id}</code>\n"]
    row = []
    for i in range(size * size):
        row.append("💣" if i in mine_positions else "💎")
        if (i + 1) % size == 0:
            grid.append(" ".join(row))
            row = []

    await message.answer("\n".join(grid), parse_mode="HTML")




@router.message(Command("reset_user"))
async def admin_reset_user(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    try:
        real_id = int(message.text.split()[1])
    except (IndexError, ValueError):
        return await message.answer(
            "Формат: <code>/reset_user [ID]</code>", parse_mode="HTML"
        )

    cursor.execute(
        """
        UPDATE users SET
            balance = 5000,
            total_bets = 0,
            total_wins = 0,
            games_played = 0,
            rigged_mode = 'off'
        WHERE id = ?
        """,
        (real_id,),
    )
    conn.commit()
    await message.answer(f"✅ Игрок {real_id} полностью сброшен.")


@router.message(Command("deluser"))
async def admin_deluser(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    try:
        real_id = int(message.text.split()[1])
    except (IndexError, ValueError):
        return await message.answer(
            "Формат: <code>/deluser [ID]</code>", parse_mode="HTML"
        )

    cursor.execute("DELETE FROM users WHERE id = ?", (real_id,))
    cursor.execute("DELETE FROM daily_stats WHERE user_id = ?", (real_id,))
    cursor.execute("DELETE FROM mines_games WHERE user_id = ?", (real_id,))
    conn.commit()
    await message.answer(f"✅ Игрок {real_id} удалён из системы.")




@router.message(Command("mine_add"))
async def admin_mine_add(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    try:
        _, user_id_s, item_name, amount_s = message.text.split(maxsplit=3)
        user_id = int(user_id_s)
        amount = int(amount_s)
    except ValueError:
        return await message.answer(
            "Формат: <code>/mine_add [ID] [предмет] [кол-во]</code>",
            parse_mode="HTML",
        )

    if item_name not in MINING_CATALOG:
        return await message.answer(f"❌ Предмет '{item_name}' не найден.")

    item = MINING_CATALOG[item_name]

    cursor.execute("SELECT 1 FROM mining_farms WHERE user_id = ?", (user_id,))
    if not cursor.fetchone():
        cursor.execute("INSERT INTO mining_farms (user_id) VALUES (?)", (user_id,))
        conn.commit()

    for _ in range(amount):
        cursor.execute(
            "INSERT INTO mining_items (user_id, name, hs, watt, wear, lvl) "
            "VALUES (?, ?, ?, ?, 100, 1)",
            (user_id, item["name"], item["hs"], item["watt"]),
        )
    conn.commit()
    await message.answer(
        f"✅ Добавлено {amount} x {item['name']} игроку {user_id}", parse_mode="HTML"
    )


@router.message(Command("mine_set"))
async def admin_mine_set(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    try:
        _, user_id_s, hs_s = message.text.split(maxsplit=2)
        user_id = int(user_id_s)
        hs = int(hs_s)
    except ValueError:
        return await message.answer(
            "Формат: <code>/mine_set [ID] [мощь]</code>", parse_mode="HTML"
        )

    cursor.execute(
        "UPDATE mining_farms SET total_hs = ? WHERE user_id = ?", (hs, user_id)
    )
    conn.commit()
    await message.answer(
        f"✅ Мощность фермы игрока {user_id} — {hs} H/s", parse_mode="HTML"
    )


@router.message(Command("mine_watt"))
async def admin_mine_watt(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    try:
        _, user_id_s, watt_s = message.text.split(maxsplit=2)
        user_id = int(user_id_s)
        watt = int(watt_s)
    except ValueError:
        return await message.answer(
            "Формат: <code>/mine_watt [ID] [W]</code>", parse_mode="HTML"
        )

    cursor.execute(
        "UPDATE mining_farms SET total_watt = ? WHERE user_id = ?", (watt, user_id)
    )
    conn.commit()
    await message.answer(
        f"✅ Потребление фермы игрока {user_id} — {watt} W/h", parse_mode="HTML"
    )


@router.message(Command("mine_reset"))
async def admin_mine_reset(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    try:
        user_id = int(message.text.split()[1])
    except (IndexError, ValueError):
        return await message.answer(
            "Формат: <code>/mine_reset [ID]</code>", parse_mode="HTML"
        )

    cursor.execute("DELETE FROM mining_items WHERE user_id = ?", (user_id,))
    cursor.execute("DELETE FROM mining_farms WHERE user_id = ?", (user_id,))
    conn.commit()
    await message.answer(f"✅ Ферма игрока {user_id} полностью сброшена.")


@router.message(Command("mine_boost"))
async def admin_mine_boost(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    try:
        _, user_id_s, amount_s = message.text.split(maxsplit=2)
        user_id = int(user_id_s)
        amount = int(amount_s)
    except ValueError:
        return await message.answer(
            "Формат: <code>/mine_boost [ID] [кол-во]</code>", parse_mode="HTML"
        )

    cursor.execute(
        "UPDATE users SET energy_drink = COALESCE(energy_drink, 0) + ? WHERE id = ?",
        (amount, user_id),
    )
    conn.commit()
    await message.answer(f"✅ Выдано {amount} энергетиков игроку {user_id}")




@router.message(Command("bcgroup"))
async def admin_broadcast_group(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    try:
        _, group_id_s, text = message.text.split(maxsplit=2)
        group_id = int(group_id_s)
    except ValueError:
        return await message.answer(
            "Формат: <code>/bcgroup [ID группы] [текст]</code>", parse_mode="HTML"
        )

    try:
        await message.bot.send_message(group_id, text, parse_mode="HTML")
        await message.answer(f"✅ Сообщение отправлено в чат {group_id}")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")


@router.message(Command("broadcast"))
async def admin_broadcast_all(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    text = message.text[len("/broadcast"):].strip()
    if not text:
        return await message.answer("Введите текст для рассылки.")

    cursor.execute("SELECT id FROM users WHERE banned = 0")
    users = cursor.fetchall()

    msg = await message.answer(f"🚀 Начинаю рассылку на {len(users)} пользователей…")

    count = 0
    for (uid,) in users:
        try:
            await message.bot.send_message(uid, text, parse_mode="HTML")
            count += 1
            if count % 20 == 0:
                await asyncio.sleep(0.5)
        except Exception:
            continue

    await msg.edit_text(f"✅ Рассылка завершена. Получили: {count}/{len(users)} чел.")


@router.message(Command("bchelp"))
async def admin_bc_help(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    await message.answer(
        "<b>📢 СПРАВКА ПО РАССЫЛКЕ</b>\n\n"
        "<code>/broadcast [текст]</code> — всем игрокам\n"
        "<code>/bcgroup [ID группы] [текст]</code> — в конкретный чат\n\n"
        "Поддерживаются HTML-теги: <b>жирный</b>, <i>курсив</i>, <code>код</code>.",
        parse_mode="HTML",
    )


@router.callback_query(F.data == "admin:top")
async def admin_top_menu(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer()
    cursor.execute(
        "SELECT custom_id, balance FROM users "
        "WHERE banned = 0 ORDER BY balance DESC LIMIT 10"
    )
    top_bal = cursor.fetchall()
    cursor.execute(
        "SELECT custom_id, games_played FROM users "
        "WHERE banned = 0 ORDER BY games_played DESC LIMIT 5"
    )
    top_games = cursor.fetchall()

    lines = ["<b>🏆 ТОП-10 ПО БАЛАНСУ</b>"]
    for i, (name, bal) in enumerate(top_bal, 1):
        lines.append(f"{i}. <code>{name or '—'}</code> — {bal:,} 💎")
    lines.append("")
    lines.append("<b>🎮 ТОП-5 ПО ИГРАМ</b>")
    for i, (name, games) in enumerate(top_games, 1):
        lines.append(f"{i}. <code>{name or '—'}</code> — {games} игр")

    await call.message.edit_text(
        "\n".join(lines), reply_markup=back_to_panel_kb(), parse_mode="HTML"
    )


@router.callback_query(F.data == "admin:giveall")
async def admin_giveall_menu(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer()
    text = (
        "<b>🎁 РАЗДАЧА ВСЕМ</b>\n\n"
        "<code>/giveall [сумма]</code> — начислить всем незабаненным игрокам\n"
        "Пример: <code>/giveall 1000</code>\n\n"
        "Можно использовать отрицательное значение для списания."
    )
    await call.message.edit_text(text, reply_markup=back_to_panel_kb(), parse_mode="HTML")


@router.message(Command("giveall"))
async def admin_giveall(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) != 2:
        return await message.answer("Формат: <code>/giveall [сумма]</code>", parse_mode="HTML")
    try:
        amount = int(parts[1])
    except ValueError:
        return await message.answer("❌ Сумма должна быть целым числом.")

    cursor.execute(
        "UPDATE users SET balance = MAX(0, balance + ?) WHERE banned = 0", (amount,)
    )
    affected = cursor.rowcount
    conn.commit()

    verb = "начислено" if amount >= 0 else "списано"
    await message.answer(
        f"✅ {verb} <b>{abs(amount):,}</b> 💎 у {affected} игроков.", parse_mode="HTML"
    )
