import os
import json
import csv
import time
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    KeyboardButton, ReplyKeyboardMarkup
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, ConversationHandler, filters
)

TOKEN = os.getenv("TOKEN")
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS", "").split(",")))

PRODUCTS_FILE = "products.json"
ORDERS_FILE = "orders.csv"

PRODUCTS = {}
user_carts = {}
adding_product = {}
maintenance_mode = False

def load_products():
    global PRODUCTS
    if os.path.exists(PRODUCTS_FILE):
        with open(PRODUCTS_FILE, "r") as f:
            PRODUCTS = json.load(f)
    else:
        PRODUCTS = {
            "Filtré": ["30€", "50€", "70€"],
            "Weed": ["50€", "100€"]
        }

def save_products():
    with open(PRODUCTS_FILE, "w") as f:
        json.dump(PRODUCTS, f)

def save_order(user_id, cart, address, phone, status):
    with open(ORDERS_FILE, "a", newline='') as f:
        writer = csv.writer(f)
        for item in cart:
            writer.writerow([
                time.strftime("%Y-%m-%d %H:%M:%S"),
                user_id,
                item["produit"],
                item["prix"],
                address,
                phone,
                status
            ])

def get_cart_total(cart):
    total = 0
    for item in cart:
        try:
            price = int(item["prix"].replace("€", ""))
            total += price
        except:
            continue
    return total

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if maintenance_mode:
        await update.message.reply_text("🚧 Service en maintenance.")
        return
    keyboard = [[InlineKeyboardButton(name, callback_data=name)] for name in PRODUCTS]
    await update.message.reply_text("📦 Que veux-tu commander :", reply_markup=InlineKeyboardMarkup(keyboard))

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data

    if data.startswith("add_"):
        _, produit, prix = data.split("_", 2)
        if user_id not in user_carts:
            user_carts[user_id] = []
        user_carts[user_id].append({"produit": produit, "prix": prix})
        await query.message.reply_text(f"✅ Ajouté au panier : {produit} {prix}")
        return

    if data.startswith("valider_") or data.startswith("refuser_"):
        await handle_admin_validation(query, context)
        return

    if data in PRODUCTS:
        buttons = [
            [InlineKeyboardButton(price, callback_data=f"add_{data}_{price}")]
            for price in PRODUCTS[data]
        ]
        await query.message.reply_text(
            f"💰 Choisis un prix pour {data} :", reply_markup=InlineKeyboardMarkup(buttons)
        )

async def view_cart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    cart = user_carts.get(user_id, [])
    if not cart:
        await update.message.reply_text("🛒 Ton panier est vide.")
        return
    total = get_cart_total(cart)
    message = "🛍️ *Ton panier :*\n"
    for item in cart:
        message += f"- {item['produit']} {item['prix']}\n"
    message += f"\n💶 *Total :* {total}€\n\n📍 Envoie ton adresse de livraison :"
    await update.message.reply_text(message, parse_mode="Markdown")

async def get_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    address = update.message.text
    cart = user_carts.get(user_id, [])
    if not cart:
        await update.message.reply_text("❌ Ton panier est vide.")
        return

    total = get_cart_total(cart)
    arr = ''.join(filter(str.isdigit, address))
    arr_ok = any(arr.startswith(f"130{i:02}") for i in range(1, 17))
    if not arr_ok and total < 150:
        await update.message.reply_text("❌ Commande refusée : minimum 150€ hors 13001–13016.")
        save_order(user_id, cart, address, "Non fourni", "Refusée")
        return

    for admin_id in ADMIN_IDS:
        await context.bot.send_message(
            chat_id=admin_id,
            text=f"📦 Nouvelle commande\nID: {user_id}\nAdresse: {address}\nTotal: {total}€",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Valider", callback_data=f"valider_{user_id}")],
                [InlineKeyboardButton("❌ Refuser", callback_data=f"refuser_{user_id}")]
            ])
        )
    await update.message.reply_text("🕐 Commande envoyée, en attente de validation...")

async def handle_admin_validation(query, context):
    data = query.data
    user_id = int(data.split("_")[1])
    cart = user_carts.get(user_id, [])
    if not cart:
        await query.message.reply_text("❌ Aucun panier trouvé.")
        return

    if data.startswith("valider_"):
        msg = "✅ Ta commande a été validée."
        status = "Validée"
    else:
        msg = "❌ Ta commande a été refusée."
        status = "Refusée"

    await context.bot.send_message(chat_id=user_id, text=msg)
    save_order(user_id, cart, "Adresse envoyée", "Non fourni", status)
    del user_carts[user_id]
    await query.message.reply_text(f"Commande {status}.")

async def add_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id not in ADMIN_IDS:
        await update.message.reply_text("🚫 Accès refusé.")
        return ConversationHandler.END
    await update.message.reply_text("Nom du produit ?")
    return 0

async def get_product_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    adding_product[user_id] = {"name": update.message.text}
    await update.message.reply_text("Prix disponibles ? (ex: 30€, 50€, 100€)")
    return 1

async def get_product_prices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    prices = update.message.text.split(",")
    name = adding_product[user_id]["name"]
    PRODUCTS[name] = [p.strip() for p in prices]
    save_products()
    del adding_product[user_id]
    await update.message.reply_text(f"✅ Produit ajouté : {name}")
    return ConversationHandler.END

async def list_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not PRODUCTS:
        await update.message.reply_text("Aucun produit.")
        return
    message = "📦 Produits :\n"
    for p, prices in PRODUCTS.items():
        message += f"- {p} : {', '.join(prices)}\n"
    await update.message.reply_text(message)

async def maintenance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global maintenance_mode
    if update.message.from_user.id not in ADMIN_IDS:
        await update.message.reply_text("❌")
        return
    maintenance_mode = not maintenance_mode
    await update.message.reply_text(f"Maintenance {'activée' if maintenance_mode else 'désactivée'}.")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Ajout annulé.")
    return ConversationHandler.END

def main():
    load_products()
    app = ApplicationBuilder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("addproduct", add_product)],
        states={
            0: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_product_name)],
            1: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_product_prices)]
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("listproducts", list_products))
    app.add_handler(CommandHandler("maintenance", maintenance))
    app.add_handler(CommandHandler("viewcart", view_cart))
    app.add_handler(conv_handler)
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, get_address))

    print("✅ Bot lancé.")
    app.run_polling()

if __name__ == "__main__":
    main()