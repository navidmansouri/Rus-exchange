import sqlite3
from datetime import datetime

DB_PATH = "exchange.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        username TEXT,
        full_name TEXT,
        ruble_amount REAL,
        rial_amount REAL,
        rate REAL,
        card_number TEXT,
        status TEXT DEFAULT 'pending',
        receipt_file_id TEXT,
        created_at TEXT,
        updated_at TEXT
    )''')
    
    # Default settings
    defaults = {
        'ruble_rate': '0',           # قیمت هر روبل به ریال
        'bank_card': '',             # شماره کارت ایرانی
        'bank_name': '',             # نام صاحب کارت
        'bank_label': '',            # نام بانک
        'min_order': '1000',         # حداقل سفارش (روبل)
        'max_order': '100000',       # حداکثر سفارش (روبل)
        'bot_active': 'true',        # ربات فعال/غیرفعال
    }
    for k, v in defaults.items():
        c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))
    
    conn.commit()
    conn.close()

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

def create_order(user_id, username, full_name, ruble_amount, rate, card_number):
    rial_amount = ruble_amount * rate
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute('''INSERT INTO orders 
        (user_id, username, full_name, ruble_amount, rial_amount, rate, card_number, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (user_id, username, full_name, ruble_amount, rial_amount, rate, card_number, now, now))
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
