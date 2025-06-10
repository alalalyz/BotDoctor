import os
import json
import csv
import time
import threading
from flask import Flask
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes
)

# === CONFIG ===
TOKEN = os.getenv("TOKEN")
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS", "123456789").split(',')))
ALLOWED_ARR = [f"130{i:02}" for i in range(1, 17)]

PRODUCTS_FILE = "products.json"
TRANSACTIONS_FILE = "transactions.csv"

user_data = {}
products = []

app = ApplicationBuilder().token(TOKEN).build()
flask_app = Flask(__name__)

# === Chargement fichiers ===
if os.path.exists(PRODUCTS_FILE):
    with open(PRODUCTS_FILE, 'r') as f:
        products = json.load(f)

def save_products():
    with open(PRODUCTS_FILE, 'w') as f:
        json.dump(products, f)

def save_transaction(uid, items, address, status, total, phone=None):
    with open(TRANSACTIONS_FILE, 'a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([uid, items, address, phone or "-", status, total])

def get_cart_total(cart):
    return sum(item["price"] for item in cart)

def get_cart_text(cart):
    if not cart:
        return "🛒 Panier vide."
    lines = [f"• {item['name']} - {item['price']}€" for item in cart]
    total = get_cart_total(cart)
    return "\n".join(lines) + f"\n\n💰 Total : {total}€"

# === HANDLERS ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user_data[uid] = {'cart': [], 'step': None}
    await send_product_menu(update, uid)

async def send_product_menu(update, uid):
    if not products:
        await update.message.reply_text("Aucun produit disponible.")
        return
    kb = [[InlineKeyboardButton(p['name'], callback_data=f"add_{i}")] for i, p in enumerate(products)]
    kb.append([
        InlineKeyboardButton("🛒 Voir panier", callback_data="view_cart"),
        InlineKeyboardButton("❌ Vider", callback_data="clear_cart")
    ])
    if uid in ADMIN_IDS:
        kb.append([
            InlineKeyboardButton("➕ Ajouter produit", callback_data="admin_add"),
            InlineKeyboardButton("📦 Modifier produits", callback_data="admin_edit")
        ])
    await update.message.reply_text("🛍 Choisis un produit :", reply_markup=InlineKeyboardMarkup(kb))

async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    data = query.data

    if data.startswith("add_"):
        index = int(data.split("_")[1])
        user_data[uid]['cart'].append(products[index])
        await query.message.reply_text(f"{products[index]['name']} ajouté au panier.")

    elif data == "view_cart":
        cart = user_data[uid]['cart']
        text = get_cart_text(cart)
        kb = [[
            InlineKeyboardButton("✅ Valider", callback_data="validate"),
            InlineKeyboardButton("❌ Vider", callback_data="clear_cart")
        ]]
        await query.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb))

    elif data == "clear_cart":
        user_data[uid]['cart'] = []
        await query.message.reply_text("Panier vidé.")

    elif data == "validate":
        await query.message.reply_text("📍 Ton arrondissement ?")
        user_data[uid]['step'] = "arr"

    elif data.startswith("valider_") or data.startswith("refuser_"):
        target = int(data.split("_")[1])
        status = "Validée" if "valider_" in data else "Refusée"
        d = user_data.get(target, {})
        cart = d.get('cart', [])
        total = get_cart_total(cart)
        txt = get_cart_text(cart)
        save_transaction(target, txt, d.get("address", "-"), status, total, d.get("phone", "-"))
        await context.bot.send_message(chat_id=target, text=f"Commande {status.lower()} ✅")
        await query.message.reply_text(f"Commande {status} pour {target}")

    elif data == "admin_add" and uid in ADMIN_IDS:
        user_data[uid]['step'] = "add_name"
        await query.message.reply_text("Nom du produit ?")

    elif data == "admin_edit" and uid in ADMIN_IDS:
        kb = [[InlineKeyboardButton(f"{p['name']}", callback_data=f"edit_{i}")] for i, p in enumerate(products)]
        await query.message.reply_text("Modifier quel produit :", reply_markup=InlineKeyboardMarkup(kb))

    elif data.startswith("edit_") and uid in ADMIN_IDS:
        index = int(data.split("_")[1])
        user_data[uid]['edit_index'] = index
        user_data[uid]['step'] = "edit_name"
        await query.message.reply_text("Nouveau nom ?")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    txt = update.message.text
    step = user_data.get(uid, {}).get('step')

    if step == "arr":
        user_data[uid]['arr'] = txt
        await update.message.reply_text("Adresse complète ?")
        user_data[uid]['step'] = "addr"

    elif step == "addr":
        user_data[uid]['address'] = txt
        await update.message.reply_text("Numéro de téléphone (facultatif, écrit « non » sinon) :")
        user_data[uid]['step'] = "phone"

    elif step == "phone":
        if txt.lower() != "non":
            user_data[uid]['phone'] = txt
        arr = user_data[uid].get("arr", "")
        total = get_cart_total(user_data[uid]["cart"])
        if arr not in ALLOWED_ARR and total < 150:
            await update.message.reply_text("Minimum 150€ hors arrondissements 13001 à 13016.")
            return
        for admin in ADMIN_IDS:
            await context.bot.send_message(
                chat_id=admin,
                text=f"🛒 Nouvelle commande de {uid}\n{get_cart_text(user_data[uid]['cart'])}\n📍 {user_data[uid]['address']}\n📞 {user_data[uid].get('phone', '-')}",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ Valider", callback_data=f"valider_{uid}")],
                    [InlineKeyboardButton("❌ Refuser", callback_data=f"refuser_{uid}")]
                ])
            )
        await update.message.reply_text("Commande envoyée, en attente de validation.")
        user_data[uid]['step'] = None

    elif step == "add_name":
        user_data[uid]['new_name'] = txt
        user_data[uid]['step'] = "add_price"
        await update.message.reply_text("Prix du produit ?")

    elif step == "add_price":
        try:
            price = float(txt)
            products.append({"name": user_data[uid]['new_name'], "price": price})
            save_products()
            await update.message.reply_text("✅ Produit ajouté.")
            user_data[uid]['step'] = None
        except:
            await update.message.reply_text("❌ Prix invalide.")

    elif step == "edit_name":
        user_data[uid]['new_name'] = txt
        user_data[uid]['step'] = "edit_price"
        await update.message.reply_text("Nouveau prix ?")

    elif step == "edit_price":
        try:
            price = float(txt)
            index = user_data[uid]['edit_index']
            products[index]['name'] = user_data[uid]['new_name']
            products[index]['price'] = price
            save_products()
            await update.message.reply_text("✅ Produit modifié.")
            user_data[uid]['step'] = None
        except:
            await update.message.reply_text("❌ Prix invalide.")

# === BOT ===
def setup():
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_buttons))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

@flask_app.route("/")
def home():
    return "Bot actif."

def run_flask():
    flask_app.run(host="0.0.0.0", port=10000)

def run_telegram():
    app.run_polling()

setup()
threading.Thread(target=run_telegram).start()
run_flask()