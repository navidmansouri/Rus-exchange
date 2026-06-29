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
    get_user, create_user, update_user, get_user_by_referral, get_all_users,
    add_bank_account, get_bank_accounts, get_bank_account, delete_bank_account,
    create_order, get_order, update_order_status,
    update_order_receipt, get_all_orders, get_user_orders
)

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ─── States ───────────────────────────────────────────────────────────────────

class RegisterStates(StatesGroup):
    first_name  = State()
    last_name   = State()
    address     = State()
    phone_ru    = State()
    phone_ir    = State()
    referral    = State()

class AddBankStates(StatesGroup):
    phone       = State()
    card        = State()
    bank_name   = State()
    owner_name  = State()

class OrderStates(StatesGroup):
    ruble_type      = State()
    waiting_amount  = State()
    select_account  = State()
    waiting_receipt = State()

class AdminStates(StatesGroup):
    set_rate_cash   = State()
    set_rate_card   = State()
    set_card        = State()
    set_name        = State()
    set_bank        = State()
    set_min         = State()
    set_max         = State()
    set_support     = State()
    send_msg_order  = State()
    send_msg_text   = State()
    send_msg_photo  = State()

# ─── Keyboards ────────────────────────────────────────────────────────────────

def main_menu():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="💱 تابلو قیمت")],
        [KeyboardButton(text="📝 ثبت سفارش")],
        [KeyboardButton(text="📦 سفارشات من"), KeyboardButton(text="👤 پروفایل من")],
        [KeyboardButton(text="🏦 حساب‌های بانکی"), KeyboardButton(text="📞 پشتیبانی")],
    ], resize_keyboard=True)

def admin_menu():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📊 سفارشات جدید"), KeyboardButton(text="📋 همه سفارشات")],
        [KeyboardButton(text="💰 تغییر قیمت روبل"), KeyboardButton(text="🏦 تغییر کارت بانکی")],
        [KeyboardButton(text="📨 پیام به مشتری"), KeyboardButton(text="👥 لیست کاربران")],
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
        ],
        [
            InlineKeyboardButton(text="✔️ تکمیل شد (واریز انجام شد)", callback_data=f"complete_{order_id}"),
        ],
        [
            InlineKeyboardButton(text="📨 پیام به مشتری", callback_data=f"msg_{order_id}"),
        ]
    ])

def ruble_type_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💵 روبل نقدی",           callback_data="type_cash")],
        [InlineKeyboardButton(text="💳 روبل کارتی (حساب روس)", callback_data="type_card")],
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

def ruble_type_fa(t):
    return '💵 نقدی' if t == 'cash' else '💳 کارتی'

async def notify_admin(text, **kwargs):
    try:
        await bot.send_message(ADMIN_ID, text, **kwargs)
    except Exception as e:
        logging.error(f"Admin notify error: {e}")

def accounts_keyboard(accounts, suffix="select"):
    buttons = []
    for acc in accounts:
        label = f"💳 {acc['card_number']} | {acc['bank_name']}"
        buttons.append([InlineKeyboardButton(text=label, callback_data=f"{suffix}_{acc['id']}")])
    if suffix == "select":
        buttons.append([InlineKeyboardButton(text="➕ افزودن حساب جدید", callback_data="add_new_account")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def accounts_manage_keyboard(accounts):
    buttons = []
    for acc in accounts:
        label = f"💳 {acc['card_number']} | {acc['bank_name']}"
        buttons.append([
            InlineKeyboardButton(text=label, callback_data=f"view_{acc['id']}"),
            InlineKeyboardButton(text="🗑", callback_data=f"del_{acc['id']}"),
        ])
    buttons.append([InlineKeyboardButton(text="➕ افزودن حساب جدید", callback_data="new_bank")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# ─── /start ───────────────────────────────────────────────────────────────────

@dp.message(CommandStart())
async def cmd_start(msg: Message, state: FSMContext):
    await state.clear()

    # بررسی لینک رفرال
    args = msg.text.split()
    ref_code = args[1] if len(args) > 1 else None

    user = get_user(msg.from_user.id)

    if user:
        # کاربر قبلاً ثبت‌نام کرده - مستقیم به منو
        name = user['first_name']
        ref = user['referral_code']
        me = await bot.get_me()
        await msg.answer(
            f"👋 سلام {name} عزیز!\n\n"
            f"🇷🇺➡️🇮🇷 به صرافی روبل به ریال خوش اومدی.\n\n"
            f"🎟 کد رفرال شما: `{ref}`\n"
            f"لینک دعوت: `https://t.me/{me.username}?start={ref}`\n\n"
            "از منو زیر یه گزینه انتخاب کن:",
            parse_mode="Markdown",
            reply_markup=main_menu()
        )
        if msg.from_user.id == ADMIN_ID:
            await msg.answer("🔑 برای پنل ادمین: /admin")
        return  # ← مهم: اینجا متوقف میشه، ثبت‌نام شروع نمیشه

    # کاربر جدید - شروع ثبت‌نام
    await state.update_data(ref_code=ref_code)
    await msg.answer(
        "👋 سلام!\n\n"
        "🇷🇺➡️🇮🇷 به صرافی روبل به ریال خوش اومدی.\n\n"
        "برای شروع باید ثبت‌نام کنی.\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "👤 *نام* خودت رو وارد کن:",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove()
    )
    await state.set_state(RegisterStates.first_name)

# ─── ثبت‌نام ──────────────────────────────────────────────────────────────────

@dp.message(RegisterStates.first_name)
async def reg_first_name(msg: Message, state: FSMContext):
    await state.update_data(first_name=msg.text.strip())
    await msg.answer("👤 *نام خانوادگی* خودت رو وارد کن:", parse_mode="Markdown")
    await state.set_state(RegisterStates.last_name)

@dp.message(RegisterStates.last_name)
async def reg_last_name(msg: Message, state: FSMContext):
    await state.update_data(last_name=msg.text.strip())
    await msg.answer("🏠 *آدرس* خودت رو وارد کن (شهر، خیابان):", parse_mode="Markdown")
    await state.set_state(RegisterStates.address)

@dp.message(RegisterStates.address)
async def reg_address(msg: Message, state: FSMContext):
    await state.update_data(address=msg.text.strip())
    await msg.answer("📱 *شماره تماس روسی* خودت رو وارد کن:", parse_mode="Markdown")
    await state.set_state(RegisterStates.phone_ru)

@dp.message(RegisterStates.phone_ru)
async def reg_phone_ru(msg: Message, state: FSMContext):
    await state.update_data(phone_ru=msg.text.strip())
    await msg.answer("📱 *شماره تماس ایرانی* خودت رو وارد کن:", parse_mode="Markdown")
    await state.set_state(RegisterStates.phone_ir)

@dp.message(RegisterStates.phone_ir)
async def reg_phone_ir(msg: Message, state: FSMContext):
    await state.update_data(phone_ir=msg.text.strip())
    await msg.answer(
        "🎟 اگه کد رفرال داری وارد کن، وگرنه بنویس *ندارم*:",
        parse_mode="Markdown"
    )
    await state.set_state(RegisterStates.referral)

@dp.message(RegisterStates.referral)
async def reg_referral(msg: Message, state: FSMContext):
    data = await state.get_data()
    ref_input = msg.text.strip()
    referred_by = None

    # اول کد رفرال از لینک بررسی کن
    if data.get('ref_code'):
        ref_user = get_user_by_referral(data['ref_code'])
        if ref_user:
            referred_by = data['ref_code']

    # بعد کدی که تایپ کرده
    if not referred_by and ref_input.lower() not in ['ندارم', '-', 'no', '0']:
        ref_user = get_user_by_referral(ref_input)
        if ref_user:
            referred_by = ref_input
        else:
            await msg.answer("⚠️ کد رفرال معتبر نیست. ادامه بدون رفرال...")

    ref_code = create_user(
        msg.from_user.id,
        msg.from_user.username or '',
        data['first_name'],
        data['last_name'],
        data['address'],
        data['phone_ru'],
        data['phone_ir'],
        referred_by
    )

    await state.clear()
    me = await bot.get_me()
    await msg.answer(
        f"✅ *ثبت‌نام با موفقیت انجام شد!*\n\n"
        f"👤 {data['first_name']} {data['last_name']}\n\n"
        f"🎟 *کد رفرال شما:* `{ref_code}`\n"
        f"🔗 لینک دعوت:\n`https://t.me/{me.username}?start={ref_code}`\n\n"
        f"این لینک رو به دوستات بده!\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "حالا می‌تونی سفارش بدی 👇",
        parse_mode="Markdown",
        reply_markup=main_menu()
    )

    # اطلاع به ادمین
    await notify_admin(
        f"👤 *کاربر جدید ثبت‌نام کرد*\n"
        f"نام: {data['first_name']} {data['last_name']}\n"
        f"تلفن روسی: {data['phone_ru']}\n"
        f"تلفن ایرانی: {data['phone_ir']}\n"
        f"آدرس: {data['address']}\n"
        f"رفرال: {referred_by or 'ندارد'}\n"
        f"کد رفرال: `{ref_code}`",
        parse_mode="Markdown"
    )

# ─── پروفایل ──────────────────────────────────────────────────────────────────

@dp.message(F.text == "👤 پروفایل من")
async def my_profile(msg: Message):
    user = get_user(msg.from_user.id)
    if not user:
        await msg.answer("ابتدا /start بزن تا ثبت‌نام کنی.")
        return

    me = await bot.get_me()
    orders = get_user_orders(msg.from_user.id)
    total_orders = len(orders)

    await msg.answer(
        f"👤 *پروفایل شما*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"🔹 نام: {user['first_name']} {user['last_name']}\n"
        f"🔹 تلفن روسی: {user['phone_ru']}\n"
        f"🔹 تلفن ایرانی: {user['phone_ir']}\n"
        f"🔹 آدرس: {user['address']}\n"
        f"🔹 تعداد سفارشات: {total_orders}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"🎟 کد رفرال: `{user['referral_code']}`\n"
        f"🔗 لینک دعوت:\n`https://t.me/{me.username}?start={user['referral_code']}`",
        parse_mode="Markdown"
    )

# ─── حساب‌های بانکی ───────────────────────────────────────────────────────────

@dp.message(F.text == "🏦 حساب‌های بانکی")
async def bank_accounts_menu(msg: Message):
    user = get_user(msg.from_user.id)
    if not user:
        await msg.answer("ابتدا /start بزن تا ثبت‌نام کنی.")
        return
    accounts = get_bank_accounts(msg.from_user.id)
    if not accounts:
        await msg.answer(
            "❌ هنوز حساب بانکی اضافه نکردی.\n\n"
            "برای اضافه کردن روی دکمه زیر بزن:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="➕ افزودن حساب بانکی", callback_data="new_bank")]
            ])
        )
    else:
        await msg.answer(
            f"🏦 *حساب‌های بانکی شما* ({len(accounts)} حساب)\n\n"
            "برای مشاهده یا حذف، روی حساب بزن:",
            parse_mode="Markdown",
            reply_markup=accounts_manage_keyboard(accounts)
        )

@dp.callback_query(F.data == "new_bank")
async def new_bank_start(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await cb.message.answer(
        "🏦 *افزودن حساب بانکی روسی*\n\n"
        "📱 شماره تماس متصل به حساب بانکی رو وارد کن:",
        parse_mode="Markdown",
        reply_markup=cancel_keyboard()
    )
    await state.set_state(AddBankStates.phone)

@dp.callback_query(F.data == "add_new_account")
async def add_new_account_from_order(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await cb.message.answer(
        "🏦 *افزودن حساب بانکی روسی*\n\n"
        "📱 شماره تماس متصل به حساب بانکی رو وارد کن:",
        parse_mode="Markdown",
        reply_markup=cancel_keyboard()
    )
    await state.update_data(from_order=True)
    await state.set_state(AddBankStates.phone)

@dp.callback_query(F.data.startswith("view_"))
async def view_account(cb: CallbackQuery):
    acc_id = int(cb.data.split("_")[1])
    acc = get_bank_account(acc_id)
    if not acc or acc['user_id'] != cb.from_user.id:
        await cb.answer("حساب پیدا نشد.")
        return
    await cb.answer()
    await cb.message.answer(
        f"💳 *جزئیات حساب*\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📱 تلفن: {acc['phone']}\n"
        f"🔢 شماره کارت: `{acc['card_number']}`\n"
        f"🏦 بانک: {acc['bank_name']}\n"
        f"👤 صاحب حساب: {acc['owner_name']}\n"
        f"━━━━━━━━━━━━━━━━━━",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🗑 حذف این حساب", callback_data=f"del_{acc_id}")]
        ])
    )

@dp.callback_query(F.data.startswith("del_"))
async def delete_account(cb: CallbackQuery):
    acc_id = int(cb.data.split("_")[1])
    delete_bank_account(acc_id, cb.from_user.id)
    await cb.answer("حساب حذف شد.")
    await cb.message.edit_reply_markup(reply_markup=None)
    await cb.message.answer("✅ حساب بانکی حذف شد.", reply_markup=main_menu())

@dp.message(AddBankStates.phone)
async def bank_get_phone(msg: Message, state: FSMContext):
    if msg.text == "❌ انصراف":
        await state.clear()
        await msg.answer("لغو شد.", reply_markup=main_menu())
        return
    await state.update_data(bank_phone=msg.text.strip())
    await msg.answer("🔢 *شماره کارت* حساب رو وارد کن:", parse_mode="Markdown")
    await state.set_state(AddBankStates.card)

@dp.message(AddBankStates.card)
async def bank_get_card(msg: Message, state: FSMContext):
    if msg.text == "❌ انصراف":
        await state.clear()
        await msg.answer("لغو شد.", reply_markup=main_menu())
        return
    await state.update_data(bank_card=msg.text.strip())
    await msg.answer("🏦 *نام بانک* رو وارد کن:", parse_mode="Markdown")
    await state.set_state(AddBankStates.bank_name)

@dp.message(AddBankStates.bank_name)
async def bank_get_bank_name(msg: Message, state: FSMContext):
    if msg.text == "❌ انصراف":
        await state.clear()
        await msg.answer("لغو شد.", reply_markup=main_menu())
        return
    await state.update_data(bank_name=msg.text.strip())
    await msg.answer("👤 *اسم صاحب حساب* رو وارد کن:", parse_mode="Markdown")
    await state.set_state(AddBankStates.owner_name)

@dp.message(AddBankStates.owner_name)
async def bank_get_owner(msg: Message, state: FSMContext):
    if msg.text == "❌ انصراف":
        await state.clear()
        await msg.answer("لغو شد.", reply_markup=main_menu())
        return

    data = await state.get_data()
    acc_id = add_bank_account(
        msg.from_user.id,
        data['bank_phone'],
        data['bank_card'],
        data['bank_name'],
        msg.text.strip()
    )

    from_order = data.get('from_order', False)
    await state.clear()

    await msg.answer(
        f"✅ *حساب بانکی اضافه شد!*\n\n"
        f"📱 تلفن: {data['bank_phone']}\n"
        f"🔢 کارت: `{data['bank_card']}`\n"
        f"🏦 بانک: {data['bank_name']}\n"
        f"👤 صاحب: {msg.text.strip()}",
        parse_mode="Markdown",
        reply_markup=main_menu()
    )

    if from_order:
        await msg.answer("حالا برو دوباره *📝 ثبت سفارش* رو بزن.", parse_mode="Markdown")

# ─── تابلو قیمت ──────────────────────────────────────────────────────────────

@dp.message(F.text == "💱 تابلو قیمت")
async def price_board(msg: Message):
    from datetime import datetime
    rate_cash = get_setting('ruble_rate_cash')
    rate_card = get_setting('ruble_rate_card')
    min_o = get_setting('min_order')
    max_o = get_setting('max_order')
    bank_label = get_setting('bank_label') or 'ایران'
    now = datetime.now().strftime("%Y/%m/%d - %H:%M")

    if (not rate_cash or rate_cash == '0') and (not rate_card or rate_card == '0'):
        await msg.answer("⚠️ قیمت هنوز توسط ادمین تنظیم نشده.")
        return

    text = (
        "━━━━━━━━━━━━━━━━━━\n"
        "📊 *تابلو قیمت*\n"
        f"🕐 آخرین بروزرسانی: `{now}`\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"💵 *روبل نقدی:*\n"
        f"   هر روبل = `{format_number(float(rate_cash))}` ریال\n\n"
        f"💳 *روبل کارتی (حساب روس):*\n"
        f"   هر روبل = `{format_number(float(rate_card))}` ریال\n\n"
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
    user = get_user(msg.from_user.id)
    if not user:
        await msg.answer("⚠️ ابتدا باید ثبت‌نام کنی. /start بزن.")
        return

    if get_setting('bot_active') != 'true':
        await msg.answer("⚠️ ربات موقتاً غیرفعال است.")
        return

    rate_cash = get_setting('ruble_rate_cash')
    rate_card = get_setting('ruble_rate_card')
    if rate_cash == '0' and rate_card == '0':
        await msg.answer("⚠️ در حال حاضر قیمت ثبت نشده.")
        return

    await msg.answer(
        "📝 *ثبت سفارش جدید*\n\n"
        "نوع روبل رو انتخاب کن:",
        parse_mode="Markdown",
        reply_markup=ruble_type_keyboard()
    )
    await state.set_state(OrderStates.ruble_type)

@dp.callback_query(F.data.startswith("type_"))
async def select_ruble_type(cb: CallbackQuery, state: FSMContext):
    ruble_type = cb.data.split("_")[1]  # cash or card
    rate_key = f'ruble_rate_{ruble_type}'
    rate = float(get_setting(rate_key))
    min_o = get_setting('min_order')
    max_o = get_setting('max_order')

    await state.update_data(ruble_type=ruble_type, rate=rate)
    await cb.answer()
    await cb.message.answer(
        f"📝 *ثبت سفارش - {ruble_type_fa(ruble_type)}*\n\n"
        f"نرخ فعلی: `{format_number(rate)}` ریال به ازای هر روبل\n\n"
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

    data = await state.get_data()
    rate = data['rate']
    rial = amount * rate
    await state.update_data(ruble_amount=amount, rial_amount=rial)

    # نمایش حساب‌های بانکی کاربر
    accounts = get_bank_accounts(msg.from_user.id)
    if not accounts:
        await msg.answer(
            f"✅ مقدار: `{format_number(amount)}` روبل\n"
            f"💰 مبلغ قابل پرداخت: `{format_number(rial)}` ریال\n\n"
            "❌ هنوز حساب بانکی روسی اضافه نکردی!\n"
            "ابتدا از منو *🏦 حساب‌های بانکی* رو بزن و حساب اضافه کن.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="➕ افزودن حساب جدید", callback_data="add_new_account")]
            ])
        )
        return

    await msg.answer(
        f"✅ مقدار: `{format_number(amount)}` روبل\n"
        f"💰 مبلغ قابل پرداخت: `{format_number(rial)}` ریال\n\n"
        "💳 کدوم حساب بانکی روسیت رو انتخاب کن:",
        parse_mode="Markdown",
        reply_markup=accounts_keyboard(accounts)
    )
    await state.set_state(OrderStates.select_account)

@dp.callback_query(OrderStates.select_account, F.data.startswith("select_"))
async def select_account(cb: CallbackQuery, state: FSMContext):
    from datetime import datetime
    acc_id = int(cb.data.split("_")[1])
    acc = get_bank_account(acc_id)
    if not acc or acc['user_id'] != cb.from_user.id:
        await cb.answer("حساب معتبر نیست.")
        return

    data = await state.get_data()
    ruble_amount = data['ruble_amount']
    rial_amount  = data['rial_amount']
    rate         = data['rate']
    ruble_type   = data['ruble_type']

    bank_card   = get_setting('bank_card')
    bank_name   = get_setting('bank_name')
    bank_label  = get_setting('bank_label')

    card_info = f"{acc['card_number']} | {acc['bank_name']} | {acc['owner_name']} | {acc['phone']}"

    username  = cb.from_user.username or ''
    full_name = cb.from_user.full_name or ''
    order_id  = create_order(
        cb.from_user.id, username, full_name,
        ruble_amount, rate, ruble_type, acc_id, card_info
    )

    await state.update_data(order_id=order_id)

    text = (
        f"🧾 *خلاصه سفارش #{order_id}*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"🗓 تاریخ: `{datetime.now().strftime('%Y/%m/%d - %H:%M')}`\n"
        f"🇷🇺 نوع: {ruble_type_fa(ruble_type)}\n"
        f"🇷🇺 مقدار روبل: `{format_number(ruble_amount)}`\n"
        f"💵 نرخ: `{format_number(rate)}` ریال/روبل\n"
        f"💰 مبلغ پرداختی: `{format_number(rial_amount)}` ریال\n\n"
        f"💳 *حساب روسی شما:*\n"
        f"   شماره کارت: `{acc['card_number']}`\n"
        f"   بانک: {acc['bank_name']}\n"
        f"   صاحب حساب: {acc['owner_name']}\n"
        f"   تلفن: {acc['phone']}\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"🏦 *مبلغ رو به این کارت ایرانی واریز کن:*\n\n"
        f"شماره کارت: `{bank_card}`\n"
        f"به نام: *{bank_name}*\n"
        f"بانک: {bank_label}\n\n"
        f"💰 مبلغ: `{format_number(rial_amount)}` ریال\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "بعد از پرداخت، *عکس فیش* رو اینجا بفرست 👇"
    )
    await cb.answer()
    await cb.message.answer(text, parse_mode="Markdown", reply_markup=cancel_keyboard())
    await state.set_state(OrderStates.waiting_receipt)

    # اطلاع به ادمین
    await notify_admin(
        f"📝 *سفارش جدید ثبت شد*\n"
        f"سفارش #{order_id}\n"
        f"👤 {full_name} | @{username}\n"
        f"🇷🇺 {format_number(ruble_amount)} روبل {ruble_type_fa(ruble_type)}\n"
        f"💰 {format_number(rial_amount)} ریال\n"
        f"💳 کارت روس: {acc['card_number']}",
        parse_mode="Markdown"
    )

@dp.message(OrderStates.waiting_receipt, F.photo)
async def get_receipt(msg: Message, state: FSMContext):
    data = await state.get_data()
    order_id = data['order_id']
    file_id  = msg.photo[-1].file_id

    update_order_receipt(order_id, file_id)
    order = get_order(order_id)

    await msg.answer(
        f"✅ *فیش پرداخت دریافت شد!*\n\n"
        f"سفارش #{order_id} در صف بررسی قرار گرفت.\n"
        f"به زودی نتیجه رو بهت اطلاع می‌دیم 🙏",
        parse_mode="Markdown",
        reply_markup=main_menu()
    )

    username = f"@{order['username']}" if order['username'] else order['full_name']
    admin_text = (
        f"🔔 *فیش پرداخت جدید!*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"📦 سفارش: #{order_id}\n"
        f"👤 مشتری: {username}\n"
        f"🇷🇺 روبل: `{format_number(order['ruble_amount'])}` ({ruble_type_fa(order['ruble_type'])})\n"
        f"💰 مبلغ: `{format_number(order['rial_amount'])}` ریال\n"
        f"💳 کارت روس: {order['card_info']}\n"
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
async def receipt_not_photo(msg: Message, state: FSMContext):
    if msg.text == "❌ انصراف":
        await state.clear()
        await msg.answer("سفارش لغو شد.", reply_markup=main_menu())
        return
    await msg.answer("⚠️ لطفاً *عکس* فیش پرداخت رو بفرست.", parse_mode="Markdown")

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
            f"🔹 سفارش #{o['id']} | {ruble_type_fa(o['ruble_type'])}\n"
            f"   {format_number(o['ruble_amount'])} روبل | {format_number(o['rial_amount'])} ریال\n"
            f"   وضعیت: {status_fa(o['status'])}\n"
            f"   تاریخ: {o['created_at'][:10]}\n\n"
        )
    await msg.answer(text, parse_mode="Markdown")

# ─── پشتیبانی ─────────────────────────────────────────────────────────────────

@dp.message(F.text == "📞 پشتیبانی")
async def support(msg: Message):
    support_username = get_setting('support_username') or ''
    if support_username:
        contact = f"@{support_username}"
    else:
        contact = f"آیدی عددی: `{ADMIN_ID}`"
    await msg.answer(
        "📞 *پشتیبانی*\n\n"
        f"برای ارتباط با پشتیبانی:\n{contact}\n\n"
        "⏰ ساعت پاسخگویی: ۹ صبح تا ۱۰ شب",
        parse_mode="Markdown"
    )

# ─── پنل ادمین ───────────────────────────────────────────────────────────────

def is_admin(msg):
    return msg.from_user.id == ADMIN_ID

@dp.message(Command("admin"))
async def admin_panel(msg: Message, state: FSMContext):
    if not is_admin(msg): return
    await state.clear()
    await msg.answer("🔑 *پنل ادمین*", parse_mode="Markdown", reply_markup=admin_menu())

@dp.message(F.text == "🔙 خروج از پنل ادمین")
async def exit_admin(msg: Message, state: FSMContext):
    if not is_admin(msg): return
    await state.clear()
    await msg.answer("از پنل ادمین خارج شدی.", reply_markup=main_menu())

# تغییر قیمت
@dp.message(F.text == "💰 تغییر قیمت روبل")
async def change_rate(msg: Message, state: FSMContext):
    if not is_admin(msg): return
    cash = get_setting('ruble_rate_cash')
    card = get_setting('ruble_rate_card')
    await msg.answer(
        f"💰 *تغییر نرخ روبل*\n\n"
        f"نرخ فعلی نقدی: `{format_number(float(cash))}` ریال\n"
        f"نرخ فعلی کارتی: `{format_number(float(card))}` ریال\n\n"
        f"نرخ جدید *روبل نقدی* رو وارد کن (ریال):",
        parse_mode="Markdown",
        reply_markup=cancel_keyboard()
    )
    await state.set_state(AdminStates.set_rate_cash)

@dp.message(AdminStates.set_rate_cash)
async def save_rate_cash(msg: Message, state: FSMContext):
    if msg.text == "❌ انصراف":
        await state.clear()
        await msg.answer("لغو شد.", reply_markup=admin_menu())
        return
    try:
        rate = float(msg.text.replace(',', '').strip())
        set_setting('ruble_rate_cash', rate)
        await state.update_data(cash_rate=rate)
        await msg.answer(
            f"✅ نرخ نقدی: `{format_number(rate)}` ریال\n\n"
            f"حالا نرخ *روبل کارتی* رو وارد کن:",
            parse_mode="Markdown"
        )
        await state.set_state(AdminStates.set_rate_card)
    except:
        await msg.answer("⚠️ عدد معتبر وارد کن.")

@dp.message(AdminStates.set_rate_card)
async def save_rate_card(msg: Message, state: FSMContext):
    if msg.text == "❌ انصراف":
        await state.clear()
        await msg.answer("لغو شد.", reply_markup=admin_menu())
        return
    try:
        rate = float(msg.text.replace(',', '').strip())
        set_setting('ruble_rate_card', rate)
        data = await state.get_data()
        await msg.answer(
            f"✅ نرخ‌ها ذخیره شد!\n"
            f"💵 نقدی: `{format_number(data['cash_rate'])}` ریال\n"
            f"💳 کارتی: `{format_number(rate)}` ریال",
            parse_mode="Markdown",
            reply_markup=admin_menu()
        )
        await state.clear()
    except:
        await msg.answer("⚠️ عدد معتبر وارد کن.")

# تغییر کارت بانکی
@dp.message(F.text == "🏦 تغییر کارت بانکی")
async def change_card(msg: Message, state: FSMContext):
    if not is_admin(msg): return
    card = get_setting('bank_card')
    await msg.answer(
        f"کارت فعلی: `{card}`\n\n"
        "شماره کارت جدید رو وارد کن (هر تعداد کاراکتر):",
        parse_mode="Markdown",
        reply_markup=cancel_keyboard()
    )
    await state.set_state(AdminStates.set_card)

@dp.message(AdminStates.set_card)
async def save_card(msg: Message, state: FSMContext):
    if msg.text == "❌ انصراف":
        await state.clear()
        await msg.answer("لغو شد.", reply_markup=admin_menu())
        return
    set_setting('bank_card', msg.text.strip())
    await msg.answer(f"✅ کارت ذخیره شد.\n\nحالا نام صاحب کارت:", reply_markup=cancel_keyboard())
    await state.set_state(AdminStates.set_name)

@dp.message(AdminStates.set_name)
async def save_name(msg: Message, state: FSMContext):
    if msg.text == "❌ انصراف":
        await state.clear()
        await msg.answer("لغو شد.", reply_markup=admin_menu())
        return
    set_setting('bank_name', msg.text.strip())
    await msg.answer("✅ نام ذخیره شد.\n\nنام بانک:", reply_markup=cancel_keyboard())
    await state.set_state(AdminStates.set_bank)

@dp.message(AdminStates.set_bank)
async def save_bank(msg: Message, state: FSMContext):
    if msg.text == "❌ انصراف":
        await state.clear()
        await msg.answer("لغو شد.", reply_markup=admin_menu())
        return
    set_setting('bank_label', msg.text.strip())
    await msg.answer("✅ اطلاعات بانکی کامل ذخیره شد!", reply_markup=admin_menu())
    await state.clear()

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
            f"📦 *سفارش #{o['id']}* | {ruble_type_fa(o['ruble_type'])}\n"
            f"👤 {username}\n"
            f"🇷🇺 {format_number(o['ruble_amount'])} روبل\n"
            f"💰 {format_number(o['rial_amount'])} ریال\n"
            f"💳 کارت روس: {o['card_info']}\n"
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
            f"#{o['id']} | {username} | {ruble_type_fa(o['ruble_type'])}\n"
            f"   {format_number(o['ruble_amount'])}₽ | {status_fa(o['status'])}\n\n"
        )
    await msg.answer(text, parse_mode="Markdown")

# لیست کاربران
@dp.message(F.text == "👥 لیست کاربران")
async def list_users(msg: Message):
    if not is_admin(msg): return
    users = get_all_users(limit=30)
    if not users:
        await msg.answer("هنوز کاربری ثبت‌نام نکرده.")
        return
    text = f"👥 *کاربران ثبت‌نام شده:* {len(users)} نفر\n\n"
    for u in users:
        text += (
            f"🔹 {u['first_name']} {u['last_name']}\n"
            f"   📱 {u['phone_ru']} | کد: `{u['referral_code']}`\n"
            f"   رفرال: {u['referred_by'] or '—'}\n\n"
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
    try:
        await cb.message.edit_caption(
            caption=f"✅ *سفارش #{order_id} تأیید شد*\n{cb.message.caption or ''}",
            parse_mode="Markdown"
        )
    except:
        pass
    try:
        await bot.send_message(
            order['user_id'],
            f"🎉 *سفارش شما تأیید شد!*\n\n"
            f"سفارش #{order_id}\n"
            f"{format_number(order['ruble_amount'])} روبل {ruble_type_fa(order['ruble_type'])} به زودی واریز خواهد شد.\n\n"
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
    try:
        await cb.message.edit_caption(
            caption=f"❌ *سفارش #{order_id} رد شد*\n{cb.message.caption or ''}",
            parse_mode="Markdown"
        )
    except:
        pass
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

@dp.callback_query(F.data.startswith("complete_"))
async def complete_order(cb: CallbackQuery):
    if cb.from_user.id != ADMIN_ID: return
    order_id = int(cb.data.split("_")[1])
    order = get_order(order_id)
    if not order:
        await cb.answer("سفارش پیدا نشد.")
        return
    update_order_status(order_id, 'completed')
    await cb.answer("✔️ سفارش تکمیل شد")
    try:
        await cb.message.edit_caption(
            caption=f"✔️ *سفارش #{order_id} تکمیل شد*\n{cb.message.caption or ''}",
            parse_mode="Markdown"
        )
    except:
        pass
    try:
        await bot.send_message(
            order['user_id'],
            f"✔️ *سفارش #{order_id} تکمیل شد!*\n\n"
            f"واریز روبل به حساب شما انجام شد.\n"
            f"ممنون از اعتمادت 🙏",
            parse_mode="Markdown"
        )
    except:
        pass



@dp.message(F.text == "📨 پیام به مشتری")
async def send_msg_start(msg: Message, state: FSMContext):
    if not is_admin(msg): return
    await msg.answer(
        "📨 *ارسال پیام به مشتری*\n\n"
        "شماره سفارش رو وارد کن:",
        parse_mode="Markdown",
        reply_markup=cancel_keyboard()
    )
    await state.set_state(AdminStates.send_msg_order)

@dp.callback_query(F.data.startswith("msg_"))
async def send_msg_from_order(cb: CallbackQuery, state: FSMContext):
    if cb.from_user.id != ADMIN_ID: return
    order_id = int(cb.data.split("_")[1])
    await cb.answer()
    await state.update_data(msg_order_id=order_id)
    await bot.send_message(
        ADMIN_ID,
        f"📨 ارسال پیام برای سفارش #{order_id}\n\n"
        "متن پیام یا عکس رو بفرست:",
        reply_markup=cancel_keyboard()
    )
    await state.set_state(AdminStates.send_msg_text)

@dp.message(AdminStates.send_msg_order)
async def send_msg_get_order(msg: Message, state: FSMContext):
    if msg.text == "❌ انصراف":
        await state.clear()
        await msg.answer("لغو شد.", reply_markup=admin_menu())
        return
    try:
        order_id = int(msg.text.strip())
    except:
        await msg.answer("⚠️ شماره سفارش معتبر وارد کن.")
        return
    order = get_order(order_id)
    if not order:
        await msg.answer("⚠️ سفارش پیدا نشد.")
        return
    await state.update_data(msg_order_id=order_id)
    await msg.answer(
        f"📦 سفارش #{order_id} پیدا شد.\n\n"
        "حالا متن پیام یا عکس رو بفرست (یا هر دو):",
        reply_markup=cancel_keyboard()
    )
    await state.set_state(AdminStates.send_msg_text)

@dp.message(AdminStates.send_msg_text)
async def send_msg_to_customer(msg: Message, state: FSMContext):
    if msg.text == "❌ انصراف":
        await state.clear()
        await msg.answer("لغو شد.", reply_markup=admin_menu())
        return

    data = await state.get_data()
    order_id = data['msg_order_id']
    order = get_order(order_id)

    try:
        if msg.photo:
            # ارسال عکس با کپشن
            caption = f"📢 *پیام از صرافی - سفارش #{order_id}*\n\n"
            if msg.caption:
                caption += msg.caption
            await bot.send_photo(
                order['user_id'],
                msg.photo[-1].file_id,
                caption=caption,
                parse_mode="Markdown"
            )
        else:
            # ارسال متن
            await bot.send_message(
                order['user_id'],
                f"📢 *پیام از صرافی - سفارش #{order_id}*\n\n"
                f"{msg.text}",
                parse_mode="Markdown"
            )
        await msg.answer("✅ پیام با موفقیت ارسال شد!", reply_markup=admin_menu())
    except Exception as e:
        await msg.answer(f"❌ خطا در ارسال پیام: {e}", reply_markup=admin_menu())

    await state.clear()

# تنظیمات
@dp.message(F.text == "⚙️ تنظیمات")
async def admin_settings(msg: Message):
    if not is_admin(msg): return
    cash  = get_setting('ruble_rate_cash')
    card  = get_setting('ruble_rate_card')
    bcard = get_setting('bank_card')
    bname = get_setting('bank_name')
    bbank = get_setting('bank_label')
    min_o = get_setting('min_order')
    max_o = get_setting('max_order')
    active = get_setting('bot_active')

    text = (
        "⚙️ *تنظیمات فعلی*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"💵 نرخ نقدی: `{format_number(float(cash))}` ریال\n"
        f"💳 نرخ کارتی: `{format_number(float(card))}` ریال\n"
        f"🏦 کارت: `{bcard}`\n"
        f"👤 نام: {bname}\n"
        f"🏛 بانک: {bbank}\n"
        f"📉 حداقل: `{format_number(float(min_o))}` روبل\n"
        f"📈 حداکثر: `{format_number(float(max_o))}` روبل\n"
        f"🤖 وضعیت: {'✅ فعال' if active == 'true' else '❌ غیرفعال'}\n"
        "━━━━━━━━━━━━━━━━━━"
    )
    toggle = "غیرفعال کن" if active == 'true' else "فعال کن"
    support_u = get_setting('support_username') or 'تنظیم نشده'
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🤖 ربات رو {toggle}", callback_data="toggle_bot")],
        [InlineKeyboardButton(text="📉 تغییر حداقل/حداکثر", callback_data="set_limits")],
        [InlineKeyboardButton(text=f"📞 یوزرنیم پشتیبانی: @{support_u}", callback_data="set_support")],
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

@dp.callback_query(F.data == "set_support")
async def set_support_start(cb: CallbackQuery, state: FSMContext):
    if cb.from_user.id != ADMIN_ID: return
    await cb.answer()
    await bot.send_message(
        ADMIN_ID,
        "📞 یوزرنیم پشتیبانی رو وارد کن (بدون @):\n"
        "مثلاً: `myusername`",
        parse_mode="Markdown",
        reply_markup=cancel_keyboard()
    )
    await state.set_state(AdminStates.set_support)

@dp.message(AdminStates.set_support)
async def save_support(msg: Message, state: FSMContext):
    if msg.text == "❌ انصراف":
        await state.clear()
        await msg.answer("لغو شد.", reply_markup=admin_menu())
        return
    username = msg.text.strip().lstrip('@')
    set_setting('support_username', username)
    await msg.answer(f"✅ پشتیبانی تنظیم شد: @{username}", reply_markup=admin_menu())
    await state.clear()

@dp.callback_query(F.data == "set_limits")
async def set_limits(cb: CallbackQuery, state: FSMContext):
    if cb.from_user.id != ADMIN_ID: return
    await cb.answer()
    await bot.send_message(ADMIN_ID, "حداقل سفارش رو وارد کن (روبل):", reply_markup=cancel_keyboard())
    await state.set_state(AdminStates.set_min)

@dp.message(AdminStates.set_min)
async def save_min(msg: Message, state: FSMContext):
    if msg.text == "❌ انصراف":
        await state.clear()
        await msg.answer("لغو شد.", reply_markup=admin_menu())
        return
    try:
        v = float(msg.text.replace(',', '').strip())
        set_setting('min_order', v)
        await msg.answer(f"✅ حداقل: {format_number(v)}\n\nحداکثر سفارش رو وارد کن (روبل):")
        await state.set_state(AdminStates.set_max)
    except:
        await msg.answer("⚠️ عدد معتبر وارد کن.")

@dp.message(AdminStates.set_max)
async def save_max(msg: Message, state: FSMContext):
    if msg.text == "❌ انصراف":
        await state.clear()
        await msg.answer("لغو شد.", reply_markup=admin_menu())
        return
    try:
        v = float(msg.text.replace(',', '').strip())
        set_setting('max_order', v)
        await msg.answer(f"✅ حداکثر: {format_number(v)} ریال ذخیره شد!", reply_markup=admin_menu())
        await state.clear()
    except:
        await msg.answer("⚠️ عدد معتبر وارد کن.")

# ─── Run ──────────────────────────────────────────────────────────────────────

async def main():
    init_db()
    print("✅ ربات صرافی روبل به ریال شروع به کار کرد...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
