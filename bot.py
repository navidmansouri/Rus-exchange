import asyncio
import logging
from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
)
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

from config import BOT_TOKEN, ADMIN_ID
from database import (
    init_db, get_setting, set_setting,
    create_order, get_order, update_order_status,
    update_order_receipt, get_all_orders, get_user_orders
)

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ─── States ───────────────────────────────────────────────────────────────────

class OrderStates(StatesGroup):
    waiting_amount = State()
    waiting_card   = State()
    waiting_receipt = State()

class AdminStates(StatesGroup):
    set_rate    = State()
    set_card    = State()
    set_name    = State()
    set_bank    = State()
    set_min     = State()
    set_max     = State()

# ─── Keyboards ────────────────────────────────────────────────────────────────

def main_menu():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="💱 تابلو قیمت")],
        [KeyboardButton(text="📝 ثبت سفارش")],
        [KeyboardButton(text="📦 سفارشات من")],
        [KeyboardButton(text="📞 پشتیبانی")],
    ], resize_keyboard=True)

def admin_menu():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📊 سفارشات جدید"), KeyboardButton(text="📋 همه سفارشات")],
        [KeyboardButton(text="💰 تغییر قیمت روبل"), KeyboardButton(text="🏦 تغییر کارت بانکی")],
        [KeyboardButton(text="⚙️ تنظیمات"), KeyboardButton(text="🔙 خروج از پنل ادمین")],
    ], resize_keyboard=True)

def cancel_keyboard():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="❌ انصراف")]
    ], resize_keyboard=True)

def order_action_keyboard(order_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ تأیید سفارش", callback_data=f"approve_{order_id}"),
            InlineKeyboardButton(text="❌ رد سفارش",   callback_data=f"reject_{order_id}"),
        ]
    ])

# ─── Helpers ──────────────────────────────────────────────────────────────────

def format_number(n):
    return f"{int(n):,}"

def status_fa(status):
    return {
        'pending':          '⏳ در انتظار پرداخت',
        'receipt_uploaded': '📤 فیش آپلود شده',
        'approved':         '✅ تأیید شده',
        'rejected':         '❌ رد شده',
        'completed':        '✔️ تکمیل شده',
    }.get(status, status)

async def notify_admin(text, **kwargs):
    try:
        await bot.send_message(ADMIN_ID, text, **kwargs)
    except Exception as e:
        logging.error(f"Admin notify error: {e}")

# ─── /start ───────────────────────────────────────────────────────────────────

@dp.message(CommandStart())
async def cmd_start(msg: Message, state: FSMContext):
    await state.clear()
    is_admin = msg.from_user.id == ADMIN_ID
    name = msg.from_user.first_name

    welcome = (
        f"👋 سلام {name} عزیز!\n\n"
        "🇷🇺➡️🇮🇷 به صرافی روبل به ریال خوش اومدی.\n\n"
        "از منو زیر یه گزینه انتخاب کن:"
    )
    if is_admin:
        welcome += "\n\n🔑 برای پنل ادمین: /admin"

    await msg.answer(welcome, reply_markup=main_menu())

# ─── تابلو قیمت ──────────────────────────────────────────────────────────────

@dp.message(F.text == "💱 تابلو قیمت")
async def price_board(msg: Message):
    rate = get_setting('ruble_rate')
    min_o = get_setting('min_order')
    max_o = get_setting('max_order')
    bank_label = get_setting('bank_label') or 'ایران'

    if not rate or rate == '0':
        await msg.answer("⚠️ قیمت هنوز توسط ادمین تنظیم نشده. لطفاً بعداً مراجعه کن.")
        return

    rate_f = float(rate)
    text = (
        "━━━━━━━━━━━━━━━━━━\n"
        "📊 *تابلو قیمت*\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"🇷🇺 *۱ روبل روسیه*\n"
        f"   = `{format_number(rate_f)}` ریال\n\n"
        f"📌 حداقل سفارش: `{format_number(float(min_o))}` روبل\n"
        f"📌 حداکثر سفارش: `{format_number(float(max_o))}` روبل\n\n"
        f"🏦 پرداخت از طریق: کارت بانک {bank_label}\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "برای ثبت سفارش روی *📝 ثبت سفارش* بزن"
    )
    await msg.answer(text, parse_mode="Markdown")

# ─── ثبت سفارش ───────────────────────────────────────────────────────────────

@dp.message(F.text == "📝 ثبت سفارش")
async def start_order(msg: Message, state: FSMContext):
    rate = get_setting('ruble_rate')
    if not rate or rate == '0':
        await msg.answer("⚠️ در حال حاضر قیمت ثبت نشده. لطفاً بعداً مراجعه کن.")
        return

    if get_setting('bot_active') != 'true':
        await msg.answer("⚠️ ربات موقتاً غیرفعال است. بعداً مراجعه کنید.")
        return

    min_o = get_setting('min_order')
    max_o = get_setting('max_order')
    rate_f = float(rate)

    await msg.answer(
        f"📝 *ثبت سفارش جدید*\n\n"
        f"نرخ فعلی: `{format_number(rate_f)}` ریال به ازای هر روبل\n\n"
        f"چند روبل می‌خوای بخری؟\n"
        f"_(حداقل: {format_number(float(min_o))} | حداکثر: {format_number(float(max_o))} روبل)_",
        parse_mode="Markdown",
        reply_markup=cancel_keyboard()
    )
    await state.set_state(OrderStates.waiting_amount)

@dp.message(OrderStates.waiting_amount)
async def get_amount(msg: Message, state: FSMContext):
    if msg.text == "❌ انصراف":
        await state.clear()
        await msg.answer("سفارش لغو شد.", reply_markup=main_menu())
        return

    try:
        amount = float(msg.text.replace(',', '').strip())
    except:
        await msg.answer("⚠️ عدد معتبر وارد کن (مثلاً: 5000)")
        return

    min_o = float(get_setting('min_order'))
    max_o = float(get_setting('max_order'))

    if amount < min_o:
        await msg.answer(f"⚠️ حداقل سفارش {format_number(min_o)} روبل است.")
        return
    if amount > max_o:
        await msg.answer(f"⚠️ حداکثر سفارش {format_number(max_o)} روبل است.")
        return

    rate = float(get_setting('ruble_rate'))
    rial = amount * rate

    await state.update_data(ruble_amount=amount, rate=rate, rial_amount=rial)

    await msg.answer(
        f"✅ مقدار: `{format_number(amount)}` روبل\n"
        f"💰 مبلغ قابل پرداخت: `{format_number(rial)}` ریال\n\n"
        f"شماره کارت ایرانی خودت رو وارد کن\n"
        f"_(که روبل‌ها به این حساب واریز بشه)_",
        parse_mode="Markdown"
    )
    await state.set_state(OrderStates.waiting_card)

@dp.message(OrderStates.waiting_card)
async def get_card(msg: Message, state: FSMContext):
    if msg.text == "❌ انصراف":
        await state.clear()
        await msg.answer("سفارش لغو شد.", reply_markup=main_menu())
        return

    card = msg.text.replace('-', '').replace(' ', '').strip()
    if not card.isdigit() or len(card) != 16:
        await msg.answer("⚠️ شماره کارت باید ۱۶ رقم باشه. دوباره وارد کن:")
        return

    data = await state.get_data()
    ruble_amount = data['ruble_amount']
    rial_amount  = data['rial_amount']
    rate         = data['rate']

    bank_card   = get_setting('bank_card')
    bank_name   = get_setting('bank_name')
    bank_label  = get_setting('bank_label')

    # ذخیره سفارش
    username  = msg.from_user.username or ''
    full_name = msg.from_user.full_name or ''
    order_id  = create_order(msg.from_user.id, username, full_name, ruble_amount, rate, card)

    await state.update_data(order_id=order_id, card_number=card)

    text = (
        f"🧾 *خلاصه سفارش #{order_id}*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"🇷🇺 مقدار روبل: `{format_number(ruble_amount)}`\n"
        f"💵 نرخ: `{format_number(rate)}` ریال/روبل\n"
        f"💰 مبلغ پرداختی: `{format_number(rial_amount)}` ریال\n"
        f"💳 کارت روسیه شما: `{card}`\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"🏦 *مبلغ رو به این کارت واریز کن:*\n\n"
        f"شماره کارت: `{bank_card}`\n"
        f"به نام: *{bank_name}*\n"
        f"بانک: {bank_label}\n\n"
        f"💰 مبلغ: `{format_number(rial_amount)}` ریال\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "بعد از پرداخت، *عکس فیش* رو اینجا بفرست 👇"
    )
    await msg.answer(text, parse_mode="Markdown", reply_markup=cancel_keyboard())
    await state.set_state(OrderStates.waiting_receipt)

@dp.message(OrderStates.waiting_receipt, F.photo)
async def get_receipt(msg: Message, state: FSMContext):
    data = await state.get_data()
    order_id = data['order_id']
    file_id  = msg.photo[-1].file_id

    update_order_receipt(order_id, file_id)
    order = get_order(order_id)

    await msg.answer(
        f"✅ *فیش پرداخت دریافت شد!*\n\n"
        f"سفارش #{order_id} شما در صف بررسی قرار گرفت.\n"
        f"به زودی نتیجه رو بهت اطلاع می‌دیم 🙏",
        parse_mode="Markdown",
        reply_markup=main_menu()
    )

    # اطلاع به ادمین
    username = f"@{order['username']}" if order['username'] else order['full_name']
    admin_text = (
        f"🔔 *فیش پرداخت جدید!*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"📦 سفارش: #{order_id}\n"
        f"👤 مشتری: {username}\n"
        f"🇷🇺 روبل: `{format_number(order['ruble_amount'])}`\n"
        f"💰 مبلغ: `{format_number(order['rial_amount'])}` ریال\n"
        f"💳 کارت مشتری: `{order['card_number']}`\n"
        "━━━━━━━━━━━━━━━━━━"
    )
    await notify_admin(admin_text, parse_mode="Markdown")
    await bot.send_photo(
        ADMIN_ID,
        file_id,
        caption=f"فیش سفارش #{order_id}",
        reply_markup=order_action_keyboard(order_id)
    )
    await state.clear()

@dp.message(OrderStates.waiting_receipt)
async def receipt_not_photo(msg: Message):
    if msg.text == "❌ انصراف":
        await msg.answer("سفارش لغو شد.", reply_markup=main_menu())
        return
    await msg.answer("⚠️ لطفاً *عکس* فیش پرداخت رو بفرست (نه فایل یا متن).", parse_mode="Markdown")

# ─── سفارشات من ──────────────────────────────────────────────────────────────

@dp.message(F.text == "📦 سفارشات من")
async def my_orders(msg: Message):
    orders = get_user_orders(msg.from_user.id)
    if not orders:
        await msg.answer("هنوز سفارشی ثبت نکردی.")
        return

    text = "📦 *آخرین سفارشات شما:*\n\n"
    for o in orders:
        text += (
            f"🔹 سفارش #{o['id']}\n"
            f"   {format_number(o['ruble_amount'])} روبل | {format_number(o['rial_amount'])} ریال\n"
            f"   وضعیت: {status_fa(o['status'])}\n"
            f"   تاریخ: {o['created_at'][:10]}\n\n"
        )
    await msg.answer(text, parse_mode="Markdown")

# ─── پشتیبانی ─────────────────────────────────────────────────────────────────

@dp.message(F.text == "📞 پشتیبانی")
async def support(msg: Message):
    await msg.answer(
        "📞 *پشتیبانی*\n\n"
        "برای ارتباط با پشتیبانی پیام بده:\n"
        "@YourUsername\n\n"  # ← اینجا یوزرنیم خودت رو بذار
        "⏰ ساعت پاسخگویی: ۹ صبح تا ۱۰ شب",
        parse_mode="Markdown"
    )

# ─── پنل ادمین ───────────────────────────────────────────────────────────────

def is_admin(msg):
    return msg.from_user.id == ADMIN_ID

@dp.message(Command("admin"))
async def admin_panel(msg: Message, state: FSMContext):
    if not is_admin(msg):
        return
    await state.clear()
    await msg.answer("🔑 *پنل ادمین*\nیه گزینه انتخاب کن:", parse_mode="Markdown", reply_markup=admin_menu())

@dp.message(F.text == "🔙 خروج از پنل ادمین")
async def exit_admin(msg: Message, state: FSMContext):
    if not is_admin(msg): return
    await state.clear()
    await msg.answer("از پنل ادمین خارج شدی.", reply_markup=main_menu())

# تغییر قیمت
@dp.message(F.text == "💰 تغییر قیمت روبل")
async def change_rate(msg: Message, state: FSMContext):
    if not is_admin(msg): return
    rate = get_setting('ruble_rate')
    await msg.answer(
        f"قیمت فعلی: `{format_number(float(rate))}` ریال\n\nقیمت جدید هر روبل رو وارد کن (ریال):",
        parse_mode="Markdown", reply_markup=cancel_keyboard()
    )
    await state.set_state(AdminStates.set_rate)

@dp.message(AdminStates.set_rate)
async def save_rate(msg: Message, state: FSMContext):
    if msg.text == "❌ انصراف":
        await state.clear()
        await msg.answer("لغو شد.", reply_markup=admin_menu())
        return
    try:
        rate = float(msg.text.replace(',', '').strip())
        set_setting('ruble_rate', rate)
        await msg.answer(f"✅ قیمت به `{format_number(rate)}` ریال تغییر کرد.", parse_mode="Markdown", reply_markup=admin_menu())
        await notify_admin(f"📢 قیمت روبل به {format_number(rate)} ریال آپدیت شد.")
    except:
        await msg.answer("⚠️ عدد معتبر وارد کن.")
        return
    await state.clear()

# تغییر کارت بانکی
@dp.message(F.text == "🏦 تغییر کارت بانکی")
async def change_card(msg: Message, state: FSMContext):
    if not is_admin(msg): return
    card = get_setting('bank_card')
    await msg.answer(f"کارت فعلی: `{card}`\n\nشماره کارت جدید (۱۶ رقم):", parse_mode="Markdown", reply_markup=cancel_keyboard())
    await state.set_state(AdminStates.set_card)

@dp.message(AdminStates.set_card)
async def save_card(msg: Message, state: FSMContext):
    if msg.text == "❌ انصراف":
        await state.clear()
        await msg.answer("لغو شد.", reply_markup=admin_menu())
        return
    card = msg.text.replace('-', '').replace(' ', '').strip()
    if not card.isdigit() or len(card) != 16:
        await msg.answer("⚠️ شماره کارت ۱۶ رقم باشه.")
        return
    set_setting('bank_card', card)
    await msg.answer(f"✅ شماره کارت ذخیره شد: `{card}`\n\nحالا نام صاحب کارت:", parse_mode="Markdown")
    await state.set_state(AdminStates.set_name)

@dp.message(AdminStates.set_name)
async def save_name(msg: Message, state: FSMContext):
    set_setting('bank_name', msg.text.strip())
    await msg.answer("✅ نام ذخیره شد.\n\nنام بانک:", reply_markup=cancel_keyboard())
    await state.set_state(AdminStates.set_bank)

@dp.message(AdminStates.set_bank)
async def save_bank(msg: Message, state: FSMContext):
    set_setting('bank_label', msg.text.strip())
    await msg.answer("✅ اطلاعات بانکی کامل ذخیره شد!", reply_markup=admin_menu())
    await state.clear()

# تنظیمات
@dp.message(F.text == "⚙️ تنظیمات")
async def admin_settings(msg: Message):
    if not is_admin(msg): return
    rate  = get_setting('ruble_rate')
    card  = get_setting('bank_card')
    name  = get_setting('bank_name')
    bank  = get_setting('bank_label')
    min_o = get_setting('min_order')
    max_o = get_setting('max_order')
    active = get_setting('bot_active')

    text = (
        "⚙️ *تنظیمات فعلی*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"💱 نرخ روبل: `{format_number(float(rate))}` ریال\n"
        f"🏦 کارت: `{card}`\n"
        f"👤 نام: {name}\n"
        f"🏛 بانک: {bank}\n"
        f"📉 حداقل: `{format_number(float(min_o))}` روبل\n"
        f"📈 حداکثر: `{format_number(float(max_o))}` روبل\n"
        f"🤖 وضعیت ربات: {'✅ فعال' if active == 'true' else '❌ غیرفعال'}\n"
        "━━━━━━━━━━━━━━━━━━"
    )
    toggle = "غیرفعال کن" if active == 'true' else "فعال کن"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🤖 ربات رو {toggle}", callback_data="toggle_bot")],
        [InlineKeyboardButton(text="📉 تغییر حداقل/حداکثر", callback_data="set_limits")],
    ])
    await msg.answer(text, parse_mode="Markdown", reply_markup=kb)

@dp.callback_query(F.data == "toggle_bot")
async def toggle_bot(cb: CallbackQuery):
    if cb.from_user.id != ADMIN_ID: return
    current = get_setting('bot_active')
    new_val = 'false' if current == 'true' else 'true'
    set_setting('bot_active', new_val)
    status = '✅ فعال' if new_val == 'true' else '❌ غیرفعال'
    await cb.answer(f"ربات {status} شد")
    await cb.message.edit_reply_markup(reply_markup=None)
    await bot.send_message(ADMIN_ID, f"ربات {status} شد.", reply_markup=admin_menu())

# سفارشات جدید
@dp.message(F.text == "📊 سفارشات جدید")
async def new_orders(msg: Message):
    if not is_admin(msg): return
    orders = get_all_orders(status='receipt_uploaded', limit=20)
    if not orders:
        await msg.answer("📭 سفارش جدیدی برای بررسی نداری.")
        return
    for o in orders:
        username = f"@{o['username']}" if o['username'] else o['full_name']
        text = (
            f"📦 *سفارش #{o['id']}*\n"
            f"👤 {username}\n"
            f"🇷🇺 {format_number(o['ruble_amount'])} روبل\n"
            f"💰 {format_number(o['rial_amount'])} ریال\n"
            f"💳 کارت: `{o['card_number']}`\n"
            f"📅 {o['created_at'][:16]}"
        )
        kb = order_action_keyboard(o['id'])
        if o['receipt_file_id']:
            await bot.send_photo(ADMIN_ID, o['receipt_file_id'], caption=text, parse_mode="Markdown", reply_markup=kb)
        else:
            await msg.answer(text, parse_mode="Markdown", reply_markup=kb)

# همه سفارشات
@dp.message(F.text == "📋 همه سفارشات")
async def all_orders(msg: Message):
    if not is_admin(msg): return
    orders = get_all_orders(limit=15)
    if not orders:
        await msg.answer("هنوز هیچ سفارشی نداری.")
        return
    text = "📋 *آخرین ۱۵ سفارش:*\n\n"
    for o in orders:
        username = f"@{o['username']}" if o['username'] else o['full_name']
        text += (
            f"#{o['id']} | {username}\n"
            f"   {format_number(o['ruble_amount'])}₽ | {status_fa(o['status'])}\n\n"
        )
    await msg.answer(text, parse_mode="Markdown")

# تأیید/رد سفارش
@dp.callback_query(F.data.startswith("approve_"))
async def approve_order(cb: CallbackQuery):
    if cb.from_user.id != ADMIN_ID: return
    order_id = int(cb.data.split("_")[1])
    order = get_order(order_id)
    if not order:
        await cb.answer("سفارش پیدا نشد.")
        return
    update_order_status(order_id, 'approved')
    await cb.answer("✅ سفارش تأیید شد")
    await cb.message.edit_caption(
        caption=f"✅ *سفارش #{order_id} تأیید شد*\n{cb.message.caption or ''}",
        parse_mode="Markdown"
    )
    # اطلاع به مشتری
    try:
        await bot.send_message(
            order['user_id'],
            f"🎉 *سفارش شما تأیید شد!*\n\n"
            f"سفارش #{order_id}\n"
            f"{format_number(order['ruble_amount'])} روبل به زودی به کارت شما واریز خواهد شد.\n\n"
            f"ممنون از اعتمادت 🙏",
            parse_mode="Markdown"
        )
    except:
        pass

@dp.callback_query(F.data.startswith("reject_"))
async def reject_order(cb: CallbackQuery):
    if cb.from_user.id != ADMIN_ID: return
    order_id = int(cb.data.split("_")[1])
    order = get_order(order_id)
    if not order:
        await cb.answer("سفارش پیدا نشد.")
        return
    update_order_status(order_id, 'rejected')
    await cb.answer("❌ سفارش رد شد")
    await cb.message.edit_caption(
        caption=f"❌ *سفارش #{order_id} رد شد*\n{cb.message.caption or ''}",
        parse_mode="Markdown"
    )
    try:
        await bot.send_message(
            order['user_id'],
            f"❌ *سفارش #{order_id} رد شد*\n\n"
            f"متأسفیم، سفارش شما تأیید نشد.\n"
            f"برای اطلاعات بیشتر با پشتیبانی تماس بگیر.",
            parse_mode="Markdown"
        )
    except:
        pass

# ─── Run ──────────────────────────────────────────────────────────────────────

async def main():
    init_db()
    print("✅ ربات صرافی روبل به ریال شروع به کار کرد...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
