import os
import json
import csv
import time
from flask import Flask, request
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    KeyboardButton, ReplyKeyboardMarkup
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, ConversationHandler, filters
)

TOKEN = os.getenv("TOKEN")
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS", "123456").split(",")))
APP_URL = os.getenv("APP_URL")  # ex: https://ton-app.onrender.com

PRODUCTS_FILE = 'products.json'
ORDERS_FILE = 'orders.csv'
user_data = {}
cart = {}
adding_product = {}
maintenance_mode = False

app_flask = Flask(__name__)

def load_products():
    if os.path.exists(PRODUCTS_FILE):
        with open(PRODUCTS_FILE, 'r') as file:
            return json.load(file)
    return {
        "Weed": ["30€", "50€", "100€"],
        "Filtré": ["20€", "40€", "70€"]
    }

def save_products():
    with open(PRODUCTS_FILE, 'w') as file:
        json.dump(PRODUCTS, file)

def save_order(user_id, produit, address, phone, status):
    with open(ORDERS_FILE, 'a', newline='') as file:
        writer = csv.writer(file)
        writer.writerow([time.strftime("%Y-%m-%d %H:%M:%S"), user_id, produit, address, phone, status])

PRODUCTS = load_products()

NOTICE = """
🚚 *INFO LIVRAISON*

- Livraison dans tous les arrondissements de Marseille.
- ⚠️ En dehors de *13001 à 13016*, un minimum de commande de *150€* est requis.

📩 Contact : [@DocteurSto](https://t.me/DocteurSto)
"""

NAME, PRICES = range(2)
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if maintenance_mode:
        await update.message.reply_text("🚧 Le bot est en maintenance.")
        return

    await update.message.reply_text(NOTICE, parse_mode='Markdown', disable_web_page_preview=True)

    keyboard = [[InlineKeyboardButton(name, callback_data=f"select_{name}")] for name in PRODUCTS]
    if update.message.from_user.id in ADMIN_IDS:
        keyboard.append([InlineKeyboardButton("⚙️ Menu Admin", callback_data="admin_menu")])

    await update.message.reply_text("👋 Bienvenue ! Que veux-tu commander :", reply_markup=InlineKeyboardMarkup(keyboard))

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data

    if data.startswith("select_"):
        product = data.split("_", 1)[1]
        keyboard = [[InlineKeyboardButton(p, callback_data=f"add_{product}_{p}")] for p in PRODUCTS[product]]
        await query.message.reply_text(f"🛍 Choisis le prix pour {product} :", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("add_"):
        _, product, price = data.split("_", 2)
        cart.setdefault(user_id, []).append(f"{product} {price}")
        await query.message.reply_text(f"✅ Ajouté : {product} {price}")
        await show_cart(user_id, context)

    elif data == "valider_commande":
        if user_id not in cart or not cart[user_id]:
            await query.message.reply_text("🛒 Ton panier est vide.")
            return

        user_data[user_id] = {"produit": ', '.join(cart[user_id])}
        button = KeyboardButton('📱 Envoyer mon numéro', request_contact=True)
        reply_markup = ReplyKeyboardMarkup([[button]], resize_keyboard=True, one_time_keyboard=True)
        await query.message.reply_text("📞 Envoie ton numéro ou tape ton adresse directement :", reply_markup=reply_markup)

    elif data == "vider_panier":
        cart[user_id] = []
        await query.message.reply_text("🗑 Panier vidé.")
        await show_cart(user_id, context)

    elif data == "admin_menu" and user_id in ADMIN_IDS:
        await query.message.reply_text(
            "🛠 Menu Admin :",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ Ajouter un produit", callback_data="addproduct")],
                [InlineKeyboardButton("📃 Voir produits", callback_data="listproducts")],
                [InlineKeyboardButton("🚧 Toggle maintenance", callback_data="maintenance_toggle")]
            ])
        )
            elif data == "listproducts" and user_id in ADMIN_IDS:
        message = "📦 *Produits disponibles :*\n\n"
        for name, prices in PRODUCTS.items():
            message += f"• *{name}* : {', '.join(prices)}\n"
        await query.message.reply_text(message, parse_mode="Markdown")

    elif data == "maintenance_toggle" and user_id in ADMIN_IDS:
        global maintenance_mode
        maintenance_mode = not maintenance_mode
        status = "activé" if maintenance_mode else "désactivé"
        await query.message.reply_text(f"⚠️ Maintenance {status}.")

async def get_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    phone = update.message.contact.phone_number
    if user_id in user_data:
        user_data[user_id]["phone"] = phone
    await update.message.reply_text("📍 Envoie maintenant ton adresse de livraison complète.")

async def get_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    address = update.message.text.strip()

    if user_id not in user_data:
        return

    produit = user_data[user_id]["produit"]
    phone = user_data[user_id].get("phone", "Non fourni")
    user_data[user_id]["address"] = address

    arr = ''.join(filter(str.isdigit, address))
    arr_ok = any(arr.startswith(f"130{i:02}") for i in range(1, 17))
    prix_total = sum(int(''.join(filter(str.isdigit, p))) for p in produit.split() if "€" in p)

    if not arr_ok and prix_total < 150:
        await update.message.reply_text("❌ Minimum de 150€ requis hors arrondissements 13001 à 13016.")
        save_order(user_id, produit, address, phone, "Refusée")
        cart[user_id] = []
        return

    save_order(user_id, produit, address, phone, "En attente")
    lien = f"[Contacter le client](tg://user?id={user_id})"

    for admin_id in ADMIN_IDS:
        await context.bot.send_message(
            chat_id=admin_id,
            text=(
                f"📦 *Nouvelle commande :*\n"
                f"👤 ID : `{user_id}`\n"
                f"🛒 Produit : {produit}\n"
                f"📞 Numéro : {phone}\n"
                f"📍 Adresse : {address}\n"
                f"{lien}"
            ),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Valider", callback_data=f"valider_{user_id}")],
                [InlineKeyboardButton("❌ Refuser", callback_data=f"refuser_{user_id}")]
            ])
        )

    await update.message.reply_text("🕐 Commande envoyée aux admins, en attente de validation.")
    async def validate_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = int(data.split("_")[1])

    if user_id not in user_data:
        await query.message.reply_text("❌ Données introuvables.")
        return

    if "valider_" in data:
        status = "Validée"
        msg = "✅ Ta commande a été validée. Prépare-toi à recevoir ton colis !"
    else:
        status = "Refusée"
        msg = "❌ Désolé, ta commande a été refusée."

    save_order(user_id, user_data[user_id]["produit"], user_data[user_id]["address"], user_data[user_id].get("phone", "Non fourni"), status)

    await context.bot.send_message(chat_id=user_id, text=msg)
    await query.message.reply_text(f"Commande {status.lower()} pour l'utilisateur `{user_id}`.", parse_mode="Markdown")

    if user_id in user_data:
        del user_data[user_id]
    if user_id in cart:
        cart[user_id] = []

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Action annulée.")
    return ConversationHandler.END

def run_webhook():
    app = ApplicationBuilder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("addproduct", add_product)],
        states={
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_product_name)],
            PRICES: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_product_prices)]
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("listproducts", list_products))
    app.add_handler(CommandHandler("maintenance", maintenance))
    app.add_handler(conv_handler)
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(CallbackQueryHandler(validate_order, pattern="^(valider_|refuser_)"))
    app.add_handler(MessageHandler(filters.CONTACT, get_contact))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, get_address))

    webhook_url = os.getenv("WEBHOOK_URL")
    app.run_webhook(
        listen="0.0.0.0",
        port=int(os.environ.get("PORT", 5000)),
        webhook_url=webhook_url
    )

if __name__ == '__main__':
    run_webhook()
