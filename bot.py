import os
import gspread
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from oauth2client.service_account import ServiceAccountCredentials

# --- Налаштування ---
TOKEN = os.getenv("TOKEN")
TABLE_NAME = 'СЕКС ШОП ТОВАРИ'
CREDENTIALS_FILE = os.getenv("CREDENTIALS_FILE", "xsebot-37780ea5328e.json")
ORDER_SHEET_NAME = 'ЗАМОВЛЕННЯ'
ADMIN_ID = 7779301550  # Телеграм ID адміністратора

user_cart = {}  # Словник кошиків користувачів

# --- Google Sheets ---
def get_gsheet_client():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
    return gspread.authorize(creds)

def get_products_from_sheet(sheet_name):
    client = get_gsheet_client()
    sheet = client.open(TABLE_NAME).worksheet(sheet_name)
    return sheet.get_all_records()

def get_categories():
    client = get_gsheet_client()
    sheet = client.open(TABLE_NAME)
    return [ws.title for ws in sheet.worksheets() if ws.title != ORDER_SHEET_NAME]

def save_order(name, phone, np, items, total):
    client = get_gsheet_client()
    sheet = client.open(TABLE_NAME).worksheet(ORDER_SHEET_NAME)
    sheet.append_row([name, phone, np, "; ".join(items), total, datetime.now().strftime("%Y-%m-%d %H:%M:%S")])

# --- Команди ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_cart[update.effective_user.id] = []
    categories = get_categories()
    buttons = [[InlineKeyboardButton(cat, callback_data=f"category:{cat}")] for cat in categories]
    filters_row = [
        InlineKeyboardButton("💸 До 300 грн", callback_data="filter:0:300"),
        InlineKeyboardButton("💰 300–600 грн", callback_data="filter:300:600"),
        InlineKeyboardButton("💎 Понад 600 грн", callback_data="filter:600:10000")
    ]
    markup = InlineKeyboardMarkup(buttons + [filters_row] + [[InlineKeyboardButton("🛒 Кошик", callback_data="view_cart")]])
    await update.message.reply_text("Оберіть категорію товарів або фільтр за ціною:", reply_markup=markup)

async def handle_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    category = query.data.split(":")[1]
    products = get_products_from_sheet(category)
    for idx, product in enumerate(products):
        text = f"*{product['НАЗВА']}*\n{product['ОПИС']}\n💰 {product['ЦІНА']}"
        buttons = [[InlineKeyboardButton("🛒 Додати до кошика", callback_data=f"add:{category}:{idx}")]]
        markup = InlineKeyboardMarkup(buttons)
        try:
            await query.message.reply_photo(photo=product['ФОТО'], caption=text, parse_mode="Markdown", reply_markup=markup)
        except:
            await query.message.reply_text(text, parse_mode="Markdown", reply_markup=markup)

async def add_to_cart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("Додано до кошика ✅")
    user_id = query.from_user.id
    _, category, idx = query.data.split(":")
    product = get_products_from_sheet(category)[int(idx)]
    item_text = f"{product['НАЗВА']} ({product['ЦІНА']})"
    user_cart.setdefault(user_id, []).append(item_text)

async def view_cart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    cart = user_cart.get(user_id, [])
    if not cart:
        await query.message.reply_text("Ваш кошик порожній 🧺")
        return
    text = "🧾 *Ваше замовлення:*\n" + "\n".join(cart) + "\n\n✍️ Введіть ім’я, телефон і Нову Пошту через крапку з комою: \n`Ім’я; Телефон; Відділення`"
    context.user_data['ordering'] = True
    await query.message.reply_text(text, parse_mode="Markdown")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if context.user_data.get("ordering"):
        context.user_data["ordering"] = False
        cart = user_cart.get(user_id, [])
        total_price = sum([int(i.split("(")[1].split("грн")[0].strip()) for i in cart if "грн" in i])
        save_order_data = [s.strip() for s in update.message.text.strip().split(";")]
        if len(save_order_data) < 3:
            await update.message.reply_text("⚠️ Введіть *Ім’я; Телефон; Відділення Нової Пошти* в одному рядку, розділяючи крапкою з комою.", parse_mode="Markdown")
            return
        name, phone, np = save_order_data[0], save_order_data[1], save_order_data[2]
        save_order(name, phone, np, cart, f"{total_price} грн")
        await update.message.reply_text("✅ Дякуємо! Ваше замовлення прийнято.")
        await context.bot.send_message(chat_id=ADMIN_ID, text=f"📥 НОВЕ ЗАМОВЛЕННЯ:\n👤 {name}\n📞 {phone}\n🏤 НП: {np}\n📦 {len(cart)} товарів на суму {total_price} грн")
        user_cart[user_id] = []

async def handle_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, min_price, max_price = query.data.split(":")
    min_price = int(min_price)
    max_price = int(max_price)
    all_products = []
    for category in get_categories():
        all_products += get_products_from_sheet(category)
    filtered = [p for p in all_products if min_price <= int(p['ЦІНА'].replace("грн", "").strip()) <= max_price]
    if not filtered:
        await query.message.reply_text("Немає товарів у цьому ціновому діапазоні.")
        return
    for product in filtered:
        text = f"*{product['НАЗВА']}*\n{product['ОПИС']}\n💰 {product['ЦІНА']}"
        try:
            await query.message.reply_photo(photo=product['ФОТО'], caption=text, parse_mode="Markdown")
        except:
            await query.message.reply_text(text, parse_mode="Markdown")

# --- Запуск ---
def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_category, pattern="^category:"))
    app.add_handler(CallbackQueryHandler(add_to_cart, pattern="^add:"))
    app.add_handler(CallbackQueryHandler(view_cart, pattern="^view_cart$"))
    app.add_handler(CallbackQueryHandler(handle_filter, pattern="^filter:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("✅ Бот запущено")
    app.run_polling()

if __name__ == '__main__':
    main()
