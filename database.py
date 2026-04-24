"""Слой доступа к SQLite-базе казино-бота."""
import logging
import sqlite3
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

DB_FILE = "casino_main.db"
conn = sqlite3.connect(DB_FILE, check_same_thread=False)
cursor = conn.cursor()


def init_tables() -> None:
    """Создаёт недостающие таблицы с дефолтными значениями."""
    try:
        # Таблица пользователей
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            balance INTEGER DEFAULT 5000,
            rig_prob INTEGER DEFAULT 50,
            banned INTEGER DEFAULT 0,
            total_bets INTEGER DEFAULT 0,
            total_wins INTEGER DEFAULT 0,
            games_played INTEGER DEFAULT 0,
            rigged_mode TEXT DEFAULT 'off',
            boost_end INTEGER DEFAULT 0,
            custom_id TEXT UNIQUE,
            luck_end INTEGER DEFAULT 0,
            last_bonus INTEGER DEFAULT 0
        )
        ''')

        # Таблица дневной статистики
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS daily_stats (
            user_id INTEGER PRIMARY KEY,
            profit INTEGER DEFAULT 0
        )
        ''')

        # История билетов для системных лотерей
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS lottery_tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            lottery_type TEXT,
            buy_time INTEGER
        )
        ''')

        # Пользовательские лотереи
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_lotteries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            creator_id INTEGER,
            title TEXT,
            prize_pool INTEGER,
            ticket_price INTEGER,
            max_tickets INTEGER,
            sold_tickets INTEGER DEFAULT 0,
            end_time INTEGER,
            status TEXT DEFAULT 'active'
        )
        ''')

        # Билеты для пользовательских лотерей
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_lottery_tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lottery_id INTEGER,
            user_id INTEGER,
            FOREIGN KEY(lottery_id) REFERENCES user_lotteries(id)
        )
        ''')

        # Состояние часовой лотереи
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS hourly_state (
            draw_id INTEGER PRIMARY KEY AUTOINCREMENT,
            prize_pool INTEGER DEFAULT 100000
        )
        ''')

        cursor.execute("INSERT OR IGNORE INTO hourly_state (draw_id, prize_pool) VALUES (1, 100000)")

        # Состояние недельной лотереи
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS weekly_state (
            draw_id INTEGER PRIMARY KEY AUTOINCREMENT,
            prize_pool INTEGER DEFAULT 1000000,
            start_time INTEGER DEFAULT 0
        )
        ''')
        
        now = int(time.time())
        cursor.execute("INSERT OR IGNORE INTO weekly_state (draw_id, prize_pool, start_time) VALUES (1, 1000000, ?)", (now,))

        # Состояние МЕГА-лотереи (новая)
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS mega_state (
            draw_id INTEGER PRIMARY KEY AUTOINCREMENT,
            prize_pool INTEGER DEFAULT 5000000,
            start_time INTEGER DEFAULT 0
        )
        ''')
        
        cursor.execute("INSERT OR IGNORE INTO mega_state (draw_id, prize_pool, start_time) VALUES (1, 5000000, ?)", (now,))

        # Таблица подкрутки
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS rig_table (
            user_id INTEGER,
            game TEXT,
            rig_type TEXT,
            status TEXT DEFAULT 'active',
            PRIMARY KEY (user_id, game)
        )
        ''')

        # Таблица майнинг ферм
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS mining_farms (
            user_id INTEGER PRIMARY KEY,
            total_hs REAL DEFAULT 0,
            total_watt INTEGER DEFAULT 0,
            last_collect INTEGER DEFAULT 0,
            slots INTEGER DEFAULT 3
        )
        ''')

        # Таблица устройств майнинга
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS mining_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            name TEXT,
            hs REAL,
            watt INTEGER,
            wear REAL DEFAULT 100.0
        )
        ''')

        # Таблица для игры MINES
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS mines_games (
            user_id INTEGER PRIMARY KEY,
            mines_pos TEXT,
            field_size INTEGER DEFAULT 5,
            bet INTEGER,
            status TEXT DEFAULT 'active'
        )
        ''')

        # Таблица для PvP игр
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS pvp_games (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            creator_id INTEGER,
            joiner_id INTEGER,
            bet INTEGER,
            status TEXT DEFAULT 'waiting',
            winner_id INTEGER,
            created_at INTEGER,
            join_type TEXT DEFAULT 'paid',
            game_mode TEXT DEFAULT 'dice'
        )
        ''')

        # Рынок предметов майнинга
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS mining_market (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            seller_id INTEGER,
            item_id INTEGER,
            name TEXT,
            hs REAL,
            watt INTEGER,
            wear REAL,
            price INTEGER,
            status TEXT DEFAULT 'open',
            buyer_id INTEGER,
            created_at INTEGER
        )
        ''')

        # Таблица настроек бота (для тех. работ)
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS bot_settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
        ''')
        # Инициализируем тех. работы выключенными
        cursor.execute("INSERT OR IGNORE INTO bot_settings (key, value) VALUES ('maintenance_mode', '0')")

        conn.commit()
        logger.info("Все таблицы инициализированы")
    except Exception as e:
        logger.error("Ошибка при инициализации таблиц: %s", e)


def apply_migrations() -> None:
    """Добавляет новые колонки к существующим таблицам, без потери данных."""
    migrations = [
        ("mining_items", "lvl", "INTEGER DEFAULT 1"),
        ("mining_items", "upgrades", "TEXT DEFAULT ''"),
        ("mining_farms", "auto_repair", "INTEGER DEFAULT 0"),
        ("mining_farms", "auto_opt", "INTEGER DEFAULT 0"),
        ("mining_farms", "auto_collect", "INTEGER DEFAULT 0"),
        ("mining_farms", "overclock_shield", "INTEGER DEFAULT 0"),
        ("mining_farms", "silent_mode", "INTEGER DEFAULT 0"),
        ("mining_farms", "antihack", "INTEGER DEFAULT 0"),
        ("users", "mine_shield", "INTEGER DEFAULT 0"),
        ("users", "mine_scan", "INTEGER DEFAULT 0"),
        ("users", "rerolls", "INTEGER DEFAULT 0"),
        ("users", "has_cashback", "INTEGER DEFAULT 0"),
        ("users", "aura_active", "INTEGER DEFAULT 0"),
        ("users", "incognito_mode", "INTEGER DEFAULT 0"),
        ("users", "safe_box_level", "INTEGER DEFAULT 0"),
        ("users", "bet_insure", "INTEGER DEFAULT 0"),
        ("users", "energy_drink", "INTEGER DEFAULT 0"),
        ("users", "gold_ticket", "INTEGER DEFAULT 0"),
        ("pvp_games", "join_type", "TEXT DEFAULT 'paid'"),
        ("pvp_games", "game_mode", "TEXT DEFAULT 'dice'"),
        ("users", "pvp_wins", "INTEGER DEFAULT 0"),
        ("users", "free_games_unlocked", "INTEGER DEFAULT 0"),
        ("lottery_tickets", "numbers", "TEXT DEFAULT ''"),
        ("lottery_tickets", "draw_id", "INTEGER DEFAULT 0"),
        ("lottery_tickets", "status", "TEXT DEFAULT 'active'"),
        ("lottery_tickets", "win", "INTEGER DEFAULT 0"),
        ("hourly_state", "winning_numbers", "TEXT DEFAULT ''"),
        ("hourly_state", "drawn_at", "INTEGER DEFAULT 0"),
        ("weekly_state", "winning_numbers", "TEXT DEFAULT ''"),
        ("weekly_state", "drawn_at", "INTEGER DEFAULT 0"),
        ("mega_state", "winning_numbers", "TEXT DEFAULT ''"),
        ("mega_state", "drawn_at", "INTEGER DEFAULT 0"),
        ("users", "privilege", "TEXT DEFAULT 'none'"),
        ("users", "last_wheel", "INTEGER DEFAULT 0"),
        ("users", "scratch_pack", "INTEGER DEFAULT 0"),
        ("users", "rig_force", "TEXT DEFAULT 'off'"),
    ]

    for table, column, definition in migrations:
        try:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
            conn.commit()
            logger.info("Колонка %s добавлена в %s", column, table)
        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e):
                continue
            logger.error("Ошибка в таблице %s: %s", table, e)


def get_real_id(target: str) -> Optional[int]:
    """
    Получает реальный ID пользователя по числовому ID или custom_id.
    
    Args:
        target: Числовой ID или пользовательский ID
    
    Returns:
        ID пользователя или None
    """
    target = str(target).strip()

    if target.isdigit():
        cursor.execute("SELECT id FROM users WHERE id = ?", (int(target),))
        res = cursor.fetchone()
        if res:
            return res[0]

    cursor.execute("SELECT id FROM users WHERE custom_id = ?", (target,))
    res = cursor.fetchone()
    return res[0] if res else None


def db_get_user(user_id: int) -> List[Any]:
    """
    Получает данные пользователя или создаёт нового.

    Returns:
        [0  balance,
         1  rig_prob,
         2  banned,
         3  total_bets,
         4  total_wins,
         5  games_played,
         6  rigged_mode,
         7  boost_end,
         8  custom_id,
         9  luck_end,
         10 last_bonus,
         11 has_cashback,
         12 bet_insure,
         13 pvp_wins,
         14 free_games_unlocked,
         15 safe_box_level]
    """
    cursor.execute(
        """
        SELECT balance, rig_prob, banned, total_bets, total_wins,
               games_played, rigged_mode, boost_end, custom_id, luck_end, last_bonus,
               has_cashback, bet_insure, pvp_wins, free_games_unlocked, safe_box_level
        FROM users WHERE id = ?
        """,
        (user_id,),
    )
    res = cursor.fetchone()

    if not res:
        cursor.execute(
            "INSERT INTO users (id, custom_id, balance) VALUES (?, ?, ?)",
            (user_id, str(user_id), 5000),
        )
        conn.commit()
        logger.info("Новый пользователь создан: %s", user_id)
        return [5000, 50, 0, 0, 0, 0, 'off', 0, str(user_id), 0, 0, 0, 0, 0, 0, 0]

    return list(res)


def db_update_stats(user_id: int, bet: int = 0, win: int = 0, deducted: bool = False) -> int:
    """
    Обновляет баланс и статистику игрока.
    
    Включает логику:
    - Применение буста (x2 выигрыш)
    - Кэшбэк 5% при наличии
    - Страховка ставки (возврат 50% при проигрыше)
    
    Args:
        user_id: ID пользователя
        bet: Размер ставки
        win: Размер выигрыша
        deducted: Если True, то ставка уже была списана ранее (не вычитать из баланса)
    
    Returns:
        Новый баланс пользователя
    """
    user_data = db_get_user(user_id)
    if not user_data:
        return 0
    
    current_balance = user_data[0]
    boost_end = user_data[7]
    has_cashback = user_data[11] if len(user_data) > 11 else 0
    bet_insure = user_data[12] if len(user_data) > 12 else 0

    # Привилегия (может отсутствовать у старых пользователей — ленивый запрос)
    try:
        cursor.execute("SELECT privilege FROM users WHERE id = ?", (user_id,))
        priv_row = cursor.fetchone()
        privilege = (priv_row[0] if priv_row else "none") or "none"
    except Exception:
        privilege = "none"

    final_win = win

    # Буст x2
    try:
        if isinstance(boost_end, (int, float)) and boost_end > time.time():
            final_win = int(win * 2)
    except (TypeError, ValueError):
        pass

    # Кэшбэк 5% (от клевера / буста из магазина)
    if has_cashback and bet > 0:
        final_win += int(bet * 0.05)

    # VIP-кэшбэк с проигрышей: bronze 2%, silver 5%, gold 10%
    if win == 0 and bet > 0:
        vip_cashback = {"bronze": 0.02, "silver": 0.05, "gold": 0.10}.get(privilege, 0)
        if vip_cashback:
            final_win += int(bet * vip_cashback)

    # Страховка ставки: при проигрыше возвращает 50%
    if win == 0 and bet > 0 and bet_insure > 0:
        final_win = int(bet * 0.5)
        cursor.execute(
            "UPDATE users SET bet_insure = bet_insure - 1 WHERE id = ?", (user_id,)
        )

    MAX_LIMIT = 900_000_000_000_000_000
    
    if deducted:
        new_balance = current_balance + final_win
    else:
        new_balance = current_balance - bet + final_win
    
    # Сейф защищает часть баланса от обнуления: 20% за уровень
    safe_level = user_data[15] if len(user_data) > 15 else 0
    if new_balance < 0 and safe_level > 0:
        protected_amount = int(current_balance * 0.2 * safe_level)
        new_balance = max(0, protected_amount)
    
    if new_balance > MAX_LIMIT:
        new_balance = MAX_LIMIT
    if new_balance < 0:
        new_balance = 0
    
    # Обновляем баланс и статистику
    cursor.execute("""
        UPDATE users 
        SET balance = ?, total_bets = total_bets + ?, total_wins = total_wins + ?, 
            games_played = games_played + 1 
        WHERE id = ?
    """, (new_balance, bet, final_win, user_id))
    
    # Обновляем дневную статистику
    net_profit = final_win - bet
    cursor.execute("""
        INSERT INTO daily_stats (user_id, profit) 
        VALUES (?, ?) 
        ON CONFLICT(user_id) DO UPDATE SET profit = profit + ?
    """, (user_id, net_profit, net_profit))
    
    conn.commit()
    return new_balance


def db_get_rig(user_id: int) -> str:
    """Возвращает текущую подкрутку игрока: 'off' / 'win' / 'lose'."""
    try:
        cursor.execute("SELECT rig_force FROM users WHERE id = ?", (user_id,))
        row = cursor.fetchone()
        if not row:
            return "off"
        val = (row[0] or "off").strip().lower()
        return val if val in ("win", "lose") else "off"
    except Exception:
        return "off"


def db_set_rig(user_id: int, mode: str) -> bool:
    """Устанавливает подкрутку для игрока. Принимает 'off'/'win'/'lose'."""
    mode = (mode or "off").strip().lower()
    if mode not in ("off", "win", "lose"):
        return False
    try:
        cursor.execute("UPDATE users SET rig_force = ? WHERE id = ?", (mode, user_id))
        conn.commit()
        return cursor.rowcount > 0
    except Exception:
        logger.exception("db_set_rig")
        return False


def db_get_global_stats() -> Tuple[int, Optional[int]]:
    """Получает общую статистику: количество игроков и сумму всех балансов"""
    cursor.execute("SELECT COUNT(id), SUM(balance) FROM users")
    return cursor.fetchone()


def db_get_user_stats(user_id: int) -> Dict[str, Any]:
    """Получает детальную статистику пользователя"""
    cursor.execute("""
        SELECT balance, total_bets, total_wins, games_played
        FROM users WHERE id = ?
    """, (user_id,))
    res = cursor.fetchone()
    
    if not res:
        return {}
    
    return {
        'balance': res[0],
        'total_bets': res[1],
        'total_wins': res[2],
        'games_played': res[3],
        'winrate': round((res[2] / res[1] * 100) if res[1] > 0 else 0, 2)
    }


def db_ban_user(user_id: int, reason: str = "Нарушение правил") -> bool:
    """Блокирует пользователя"""
    try:
        cursor.execute("UPDATE users SET banned = 1 WHERE id = ?", (user_id,))
        conn.commit()
        logger.warning("Пользователь %s заблокирован. Причина: %s", user_id, reason)
        return True
    except Exception as e:
        logger.error("Ошибка при блокировке: %s", e)
        return False


def db_unban_user(user_id: int) -> bool:
    """Разблокирует пользователя"""
    try:
        cursor.execute("UPDATE users SET banned = 0 WHERE id = ?", (user_id,))
        conn.commit()
        logger.info("Пользователь %s разблокирован", user_id)
        return True
    except Exception as e:
        logger.error("Ошибка при разблокировке: %s", e)
        return False


def get_top_users(limit: int = 10) -> List[Tuple[int, int, int]]:
    """
    Получает топ пользователей по балансу.
    
    Returns:
        [(user_id, balance, games_played), ...]
    """
    cursor.execute("""
        SELECT id, balance, games_played 
        FROM users 
        ORDER BY balance DESC 
        LIMIT ?
    """, (limit,))
    return cursor.fetchall()


def clear_daily_stats():
    """Очищает дневную статистику"""
    try:
        cursor.execute("DELETE FROM daily_stats")
        conn.commit()
        logger.info("Дневная статистика очищена")
    except Exception as e:
        logger.error("Ошибка при очистке статистики: %s", e)


def set_maintenance_mode(enabled: bool):
    """Включает или выключает режим тех. работ"""
    val = '1' if enabled else '0'
    cursor.execute("INSERT INTO bot_settings (key, value) VALUES ('maintenance_mode', ?) ON CONFLICT(key) DO UPDATE SET value = ?", (val, val))
    conn.commit()


def get_maintenance_mode() -> bool:
    """Проверяет, включен ли режим тех. работ"""
    cursor.execute("SELECT value FROM bot_settings WHERE key = 'maintenance_mode'")
    res = cursor.fetchone()
    return res and res[0] == '1'


def db_increment_pvp_wins(user_id: int) -> int:
    """
    Увеличивает счетчик PVP побед пользователя и проверяет достижение 50 побед.
    
    Returns:
        Новое количество PVP побед
    """
    try:
        cursor.execute("UPDATE users SET pvp_wins = pvp_wins + 1 WHERE id = ?", (user_id,))
        cursor.execute("SELECT pvp_wins FROM users WHERE id = ?", (user_id,))
        result = cursor.fetchone()
        if not result:
            logger.warning("Пользователь %s не найден при увеличении PVP-побед", user_id)
            return 0

        new_wins = result[0]
        if new_wins == 50:
            cursor.execute(
                "UPDATE users SET free_games_unlocked = 1 WHERE id = ?", (user_id,)
            )
            logger.info(
                "Пользователь %s достиг 50 PVP побед и получил бесплатные игры",
                user_id,
            )

        conn.commit()
        return new_wins
    except Exception as e:
        logger.error("Ошибка при увеличении PVP-побед для %s: %s", user_id, e)
        conn.rollback()
        return 0


def db_has_free_games(user_id: int) -> bool:
    """Проверяет, имеет ли пользователь бесплатный доступ к играм"""
    try:
        cursor.execute("SELECT free_games_unlocked FROM users WHERE id = ?", (user_id,))
        res = cursor.fetchone()
        return bool(res and res[0] == 1)
    except Exception as e:
        logger.error("Ошибка при проверке бесплатных игр для %s: %s", user_id, e)
        return False
