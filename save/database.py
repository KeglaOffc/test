import sqlite3
import time

# Устанавливаем соединение с базой данных
conn = sqlite3.connect("casino_main.db", check_same_thread=False)
cursor = conn.cursor()

# --- АКТУАЛЬНАЯ СТРУКТУРА ТАБЛИЦ ---

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

# --- ТАБЛИЦЫ ДЛЯ ЛОТЕРЕЙ ---

# История билетов для системных лотерей (Часовая и ПРО)
cursor.execute('''
CREATE TABLE IF NOT EXISTS lottery_tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    lottery_type TEXT,
    buy_time INTEGER
)
''')

# Таблица самих пользовательских лотерей
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

# Таблица билетов для ПОЛЬЗОВАТЕЛЬСКИХ лотерей
cursor.execute('''
CREATE TABLE IF NOT EXISTS user_lottery_tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lottery_id INTEGER,
    user_id INTEGER,
    FOREIGN KEY(lottery_id) REFERENCES user_lotteries(id)
)
''')

# Таблица состояния часовой лотереи
cursor.execute('''
CREATE TABLE IF NOT EXISTS hourly_state (
    draw_id INTEGER PRIMARY KEY AUTOINCREMENT,
    prize_pool INTEGER DEFAULT 100000
)
''')

# Инициализация первой часовой лотереи, если таблица пуста
cursor.execute("INSERT OR IGNORE INTO hourly_state (draw_id, prize_pool) VALUES (1, 100000)")

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
conn.commit()

# --- ФУНКЦИИ ДЛЯ РАБОТЫ С БД ---

def db_update_stats(user_id, bet=0, win=0):
    user_data = db_get_user(user_id) # Получаем данные пользователя
    # Предположим, мы добавили колонки has_cashback(10) и bet_insure(11)
    
    final_win = win
    
    # ЛОГИКА: Кэшбэк 5% (работает всегда при ставке)
    if user_data['has_cashback'] == 1:
        final_win += (bet * 0.05)
        
    # ЛОГИКА: Страховка ставки (если проигрыш и есть страховка)
    if win == 0 and bet > 0 and user_data['bet_insure'] > 0:
        final_win = bet * 0.5 # Возвращаем половину ставки
        cursor.execute("UPDATE users SET bet_insure = bet_insure - 1 WHERE id = ?", (user_id,))

def get_real_id(target):
    target = str(target)
    if target.isdigit():
        cursor.execute("SELECT id FROM users WHERE id = ?", (int(target),))
        res = cursor.fetchone()
        if res: return res[0]
    cursor.execute("SELECT id FROM users WHERE custom_id = ?", (target,))
    res = cursor.fetchone()
    return res[0] if res else None
    
def db_get_user(user_id):
    """Получает данные пользователя. Если его нет — создает нового."""
    cursor.execute("""
        SELECT balance, rig_prob, banned, total_bets, total_wins, 
               games_played, rigged_mode, boost_end, custom_id, luck_end, last_bonus
        FROM users WHERE id = ?
    """, (user_id,))
    res = cursor.fetchone()
    
    if not res:
        cursor.execute("INSERT INTO users (id, custom_id, balance) VALUES (?, ?, ?)", 
                       (user_id, str(user_id), 5000))
        conn.commit()
        return [5000, 50, 0, 0, 0, 0, 'off', 0, str(user_id), 0, 0]
    return list(res)

def db_update_stats(user_id, bet=0, win=0):
    """Обновляет баланс и статистику игрока. Возвращает актуальный баланс."""
    user = db_get_user(user_id)
    if not user:
        return 0
    
    # ИСПРАВЛЕННЫЙ БЛОК БУСТА (Безопасная проверка типа данных)
    # Мы проверяем, что в user[7] действительно число (float или int)
    try:
        # В db_get_user() boost_end — это 7-й индекс (8-й элемент)
        boost_end = user[7] 
        if isinstance(boost_end, (int, float)) and boost_end > time.time(): 
            win *= 2
    except (IndexError, TypeError):
        pass
        
    # ИСПРАВЛЕНО: Число без запятых
    MAX_LIMIT = 900000000000000000
    
    # Баланс — это 0-й индекс в результате db_get_user()
    current_balance = user[0] 
    
    new_bal = current_balance - bet + win
    
    # Проверки границ
    if new_bal > MAX_LIMIT: new_bal = MAX_LIMIT
    if new_bal < 0: new_bal = 0
    
    cursor.execute("""
        UPDATE users 
        SET balance = ?, total_bets = total_bets + ?, total_wins = total_wins + ?, games_played = games_played + 1 
        WHERE id = ?
    """, (new_bal, bet, win, user_id))
    
    net_profit = win - bet
    cursor.execute("""
        INSERT INTO daily_stats (user_id, profit) 
        VALUES (?, ?) 
        ON CONFLICT(user_id) DO UPDATE SET profit = profit + ?
    """, (user_id, net_profit, net_profit))
    
    conn.commit()
    return new_bal

def db_get_global_stats():
    """Получает количество игроков и общий банк."""
    cursor.execute("SELECT COUNT(id), SUM(balance) FROM users")
    return cursor.fetchone()
    
    # --- ТАБЛИЦЫ МАЙНИНГА ---

# Таблица ферм (общая статистика)
cursor.execute('''
CREATE TABLE IF NOT EXISTS mining_farms (
    user_id INTEGER PRIMARY KEY,
    total_hs REAL DEFAULT 0,
    total_watt INTEGER DEFAULT 0,
    last_collect INTEGER DEFAULT 0,
    slots INTEGER DEFAULT 3
)''')

# Таблица конкретных устройств пользователя
cursor.execute('''
CREATE TABLE IF NOT EXISTS mining_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    name TEXT,
    hs REAL,
    watt INTEGER,
    wear REAL DEFAULT 100.0
)''')

conn.commit()

# --- ТАБЛИЦА ДЛЯ ИГРЫ MINES ---
cursor.execute('''
CREATE TABLE IF NOT EXISTS mines_games (
    user_id INTEGER PRIMARY KEY,
    mines_pos TEXT,       -- Здесь храним индексы мин, например "2,5,10"
    field_size INTEGER DEFAULT 5,
    bet INTEGER,
    status TEXT DEFAULT 'active'
)
''')
conn.commit()

# --- АВТОМАТИЧЕСКАЯ МИГРАЦИЯ (ОБНОВЛЕНИЕ СТРУКТУРЫ) ---
# Этот блок добавит колонки в твою старую базу данных при запуске.
# --- ФУНКЦИЯ БЕЗОПАСНОЙ МИГРАЦИИ ---
def apply_migrations():
    # Список всех новых колонок, которые мы хотим видеть в базе
    migrations = [
        # (Таблица, Колонка, Тип и дефолтное значение)
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
        ("users", "safe_box_level", "INTEGER DEFAULT 0")
    ]

    for table, column, definition in migrations:
        try:
            # Пытаемся добавить колонку
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
            print(f"✅ Колонка {column} успешно добавлена в {table}")
        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e):
                # Если колонка уже есть — просто игнорируем и идем дальше
                pass
            else:
                print(f"❌ Непредвиденная ошибка в таблице {table}: {e}")
    
    conn.commit()

# Запускаем миграцию сразу после создания основных таблиц
apply_migrations()

try:
    cursor.execute("ALTER TABLE mines_games ADD COLUMN field_size INTEGER DEFAULT 5")
    conn.commit()
except:
    pass