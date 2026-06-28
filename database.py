import sqlite3
import random
import string
from datetime import datetime

DB_PATH = "exchange.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # تنظیمات
    c.execute('''CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )''')

    # کاربران ثبت‌نام شده
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER UNIQUE,
        username TEXT,
        first_name TEXT,
        last_name TEXT,
        address TEXT,
        phone_ru TEXT,
        phone_ir TEXT,
        referral_code TEXT UNIQUE,
        referred_by TEXT,
        created_at TEXT
    )''')

    # حساب‌های بانکی روسی کاربر
    c.execute('''CREATE TABLE IF NOT EXISTS bank_accounts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        phone TEXT,
        card_number TEXT,
        bank_name TEXT,
        owner_name TEXT,
        created_at TEXT
    )''')

    # سفارشات
    c.execute('''CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        username TEXT,
        full_name TEXT,
        ruble_amount REAL,
        rial_amount REAL,
        rate REAL,
        ruble_type TEXT DEFAULT 'cash',
        bank_account_id INTEGER,
        card_info TEXT,
        status TEXT DEFAULT 'pending',
        receipt_file_id TEXT,
        created_at TEXT,
        updated_at TEXT
    )''')

    defaults = {
        'ruble_rate_cash':   '0',
        'ruble_rate_card':   '0',
        'bank_card':         '',
        'bank_name':         '',
        'bank_label':        '',
        'min_order':         '1000',
        'max_order':         '100000',
        'bot_active':        'true',
    }
    for k, v in defaults.items():
        c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))

    conn.commit()
    conn.close()

# ─── تنظیمات ──────────────────────────────────────────────────────────────────

def get_setting(key):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key=?", (key,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None

def set_setting(key, value):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
    conn.commit()
    conn.close()

# ─── کاربران ──────────────────────────────────────────────────────────────────

def generate_referral_code():
    while True:
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT id FROM users WHERE referral_code=?", (code,))
        exists = c.fetchone()
        conn.close()
        if not exists:
            return code

def get_user(user_id):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None

def create_user(user_id, username, first_name, last_name, address, phone_ru, phone_ir, referred_by=None):
    code = generate_referral_code()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute('''INSERT INTO users
        (user_id, username, first_name, last_name, address, phone_ru, phone_ir, referral_code, referred_by, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (user_id, username, first_name, last_name, address, phone_ru, phone_ir, code, referred_by, now))
    conn.commit()
    conn.close()
    return code

def update_user(user_id, **kwargs):
    if not kwargs:
        return
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    sets = ", ".join(f"{k}=?" for k in kwargs)
    vals = list(kwargs.values()) + [user_id]
    c.execute(f"UPDATE users SET {sets} WHERE user_id=?", vals)
    conn.commit()
    conn.close()

def get_user_by_referral(code):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE referral_code=?", (code,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None

def get_all_users(limit=100):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM users ORDER BY id DESC LIMIT ?", (limit,))
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]

# ─── حساب‌های بانکی ───────────────────────────────────────────────────────────

def add_bank_account(user_id, phone, card_number, bank_name, owner_name):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute('''INSERT INTO bank_accounts (user_id, phone, card_number, bank_name, owner_name, created_at)
        VALUES (?, ?, ?, ?, ?, ?)''', (user_id, phone, card_number, bank_name, owner_name, now))
    acc_id = c.lastrowid
    conn.commit()
    conn.close()
    return acc_id

def get_bank_accounts(user_id):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM bank_accounts WHERE user_id=? ORDER BY id DESC", (user_id,))
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_bank_account(acc_id):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM bank_accounts WHERE id=?", (acc_id,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None

def delete_bank_account(acc_id, user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM bank_accounts WHERE id=? AND user_id=?", (acc_id, user_id))
    conn.commit()
    conn.close()

# ─── سفارشات ──────────────────────────────────────────────────────────────────

def create_order(user_id, username, full_name, ruble_amount, rate, ruble_type, bank_account_id, card_info):
    rial_amount = ruble_amount * rate
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute('''INSERT INTO orders
        (user_id, username, full_name, ruble_amount, rial_amount, rate, ruble_type, bank_account_id, card_info, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (user_id, username, full_name, ruble_amount, rial_amount, rate, ruble_type, bank_account_id, card_info, now, now))
    order_id = c.lastrowid
    conn.commit()
    conn.close()
    return order_id

def get_order(order_id):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM orders WHERE id=?", (order_id,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None

def update_order_status(order_id, status):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute("UPDATE orders SET status=?, updated_at=? WHERE id=?", (status, now, order_id))
    conn.commit()
    conn.close()

def update_order_receipt(order_id, file_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute("UPDATE orders SET receipt_file_id=?, status='receipt_uploaded', updated_at=? WHERE id=?",
              (file_id, now, order_id))
    conn.commit()
    conn.close()

def get_all_orders(status=None, limit=50):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    if status:
        c.execute("SELECT * FROM orders WHERE status=? ORDER BY id DESC LIMIT ?", (status, limit))
    else:
        c.execute("SELECT * FROM orders ORDER BY id DESC LIMIT ?", (limit,))
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_user_orders(user_id):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM orders WHERE user_id=? ORDER BY id DESC LIMIT 10", (user_id,))
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]
