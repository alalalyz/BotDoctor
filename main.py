import os
import json
import csv
import time
import logging
import threading
from flask import Flask
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)

# === CONFIGURATION ===
TOKEN = os.getenv("TOKEN")
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS", "123456789").split(',')))
ALLOWED_ARR = [f"130{i:02}" for i in range(1, 17)]
app = ApplicationBuilder().token(TOKEN).build()
flask_app = Flask(__name__)

# === FICHIERS ===
PRODUCTS_FILE = "products.json"
TRANSACTIONS_FILE = "transactions.csv"
LOG_FILE = "bot.log"

user_data = {}
products = []
cooldowns = {}
COOLDOWN_SECONDS = 600

# === LOGGING ===
logging.basicConfig(filename=LOG_FILE, level=logging.INFO)

# === CHARGER PRODUITS ===
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
    user_id = update.effective_user.id
    user_data[user_id] = {'cart': [], 'step': None}
    name = update.effective_user.first_name
    await update.message.reply_text(f"Bienvenue {name} 👋 Tape /help pour les infos.")
    await send_product_menu(update, user_id)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "/start – Démarrer le bot\n"
        "/help – Obtenir de l'aide\n"
        "Choisis tes produits, valide ton panier, entre ton adresse et ton numéro (facultatif).\n"
        "📦 En dehors des arrondissements 13001 à 13016, le minimum est 150€."
    )

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("⛔ Tu n'es pas admin.")
        return
    kb = [
        [InlineKeyboardButton("➕ Ajouter produit", callback_data="add_product")],
        [InlineKeyboardButton("📦 Gérer produits", callback_data="manage_products")]
    ]
    await update.message.reply_text("🔧 Panel admin :", reply_markup=InlineKeyboardMarkup(kb))

async def send_product_menu(update_or_query, user_id):
    if not products:
        await update_or_query.message.reply_text("⚠️ Aucun produit disponible.")
        return
    kb = [[InlineKeyboardButton(p['name'], callback_data=f"add_{i}")] for i, p in enumerate(products)]
    kb += [[
        InlineKeyboardButton("🛒 Voir panier", callback_data="view_cart"),
        InlineKeyboardButton("❌ Vider", callback_data="clear_cart")
    ]]
    if user_id in ADMIN_IDS:
        kb += [[InlineKeyboardButton("🔧 Admin Panel", callback_data="admin_panel")]]
    await update_or_query.message.reply_text("👋 Choisis un produit :", reply_markup=InlineKeyboardMarkup(kb))

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data
    await query.answer()

    if data.startswith("add_"):
        index = int(data.split("_")[1])
        user_data[user_id]['cart'].append(products[index])
        await query.message.reply_text(f"✅ {products[index]['name']} ajouté au panier.")

    elif data == "view_cart":
        cart = user_data[user_id]['cart']
        await query.message.reply_text(get_cart_text(cart),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Valider", callback_data="validate")],
                [InlineKeyboardButton("❌ Vider", callback_data="clear_cart")]
            ])
        )

    elif data == "clear_cart":
        user_data[user_id]['cart'] = []
        await query.message.reply_text("🧹 Panier vidé.")

    elif data == "validate":
        now = time.time()
        if user_id in cooldowns and now - cooldowns[user_id] < COOLDOWN_SECONDS:
            await query.message.reply_text("🕐 Patiente un peu avant de commander à nouveau.")
            return
        cooldowns[user_id] = now
        await query.message.reply_text("📍 Entre ton arrondissement (ex: 13003) :")
        user_data[user_id]['step'] = "get_arr"

    elif data.startswith("valider_") or data.startswith("refuser_"):
        target_id = int(data.split("_")[1])
        status = "Validée" if "valider_" in data else "Refusée"
        d = user_data.get(target_id, {})
        cart_txt = get_cart_text(d.get('cart', []))
        save_transaction(target_id, cart_txt, d.get("address", "-"), status, get_cart_total(d.get('cart', [])), d.get("phone"))
        await context.bot.send_message(chat_id=target_id, text=f"✅ Commande {status.lower()}.\nMerci pour ta confiance !")
        await query.message.reply_text(f"Commande {status} pour {target_id}.")

    elif data == "add_product" and user_id in ADMIN_IDS:
        user_data[user_id]['step'] = "add_name"
        await query.message.reply_text("🆕 Nom du produit ?")

    elif data == "manage_products" and user_id in ADMIN_IDS:
        kb = [[InlineKeyboardButton(f"📝 {p['name']}", callback_data=f"edit_{i}")] for i, p in enumerate(products)]
        await query.message.reply_text("📦 Modifier un produit :", reply_markup=InlineKeyboardMarkup(kb))

    elif data.startswith("edit_") and user_id in ADMIN_IDS:
        index = int(data.split("_")[1])
        user_data[user_id]['edit_index'] = index
        user_data[user_id]['step'] = "edit_name"
        await query.message.reply_text(f"Nouveau nom pour {products[index]['name']} ?")

    elif data == "admin_panel":
        await admin_panel(query, context)

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    txt = update.message.text
    step = user_data.get(user_id, {}).get('step')

    if step == "get_arr":
        user_data[user_id]['arr'] = txt.strip()
        await update.message.reply_text("📬 Ton adresse complète ?")
        user_data[user_id]['step'] = "get_address"

    elif step == "get_address":
        user_data[user_id]['address'] = txt.strip()
        await update.message.reply_text("📞 Envoie ton numéro (facultatif). L’appel sera en inconnu.\nÉcris « non » si tu ne veux pas.")
        user_data[user_id]['step'] = "get_phone"

    elif step == "get_phone":
        if txt.lower() != "non":
            user_data[user_id]['phone'] = txt.strip()
        arr = user_data[user_id].get("arr", "")
        total = get_cart_total(user_data[user_id]["cart"])
        if arr not in ALLOWED_ARR and total < 150:
            await update.message.reply_text("❌ Minimum de 150€ hors arrondissements 13001 à 13016.")
            return
        for admin in ADMIN_IDS:
            await context.bot.send_message(
                chat_id=admin,
                text=f"📥 Commande de {user_id} :\n{get_cart_text(user_data[user_id]['cart'])}\n📍 {user_data[user_id]['address']}\n📞 {user_data[user_id].get('phone', 'Non fourni')}",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ Valider", callback_data=f"valider_{user_id}")],
                    [InlineKeyboardButton("❌ Refuser", callback_data=f"refuser_{user_id}")]
                ])
            )
        await update.message.reply_text("🕐 Commande envoyée pour validation.")
        user_data[user_id]['step'] = None

    elif step == "add_name":
        user_data[user_id]['new_name'] = txt.strip()
        user_data[user_id]['step'] = "add_price"
        await update.message.reply_text("💰 Prix en € ?")

    elif step == "add_price":
        try:
            price = float(txt)
            products.append({"name": user_data[user_id]['new_name'], "price": price})
            save_products()
            await update.message.reply_text(f"✅ Produit « {user_data[user_id]['new_name']} » ajouté.")
            user_data[user_id]['step'] = None
        except:
            await update.message.reply_text("❌ Prix invalide. Réessaye.")

    elif step == "edit_name":
        index = user_data[user_id]['edit_index']
        products[index]['name'] = txt.strip()
        user_data[user_id]['step'] = "edit_price"
        await update.message.reply_text("💸 Nouveau prix ?")

    elif step == "edit_price":
        try:
            price = float(txt)
            index = user_data[user_id]['edit_index']
            products[index]['price'] = price
            save_products()
            await update.message.reply_text(f"✅ Produit modifié : {products[index]['name']} - {price}€")
            user_data[user_id]['step'] = None
        except:
            await update.message.reply_text("❌ Prix invalide.")

# === INIT ET RUN ===
def setup():
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

def run_bot():
    app.run_polling()

@flask_app.route('/')
def index():
    return "✅ Bot en ligne."
    
def run_bot():
    print("🔁 BOT EN TRAIN DE SE CONNECTER À TELEGRAM...")
    app.run_polling()
    
def run_flask():
    flask_app.run(host='0.0.0.0', port=10000)

setup()
threading.Thread(target=run_bot).start()
run_flask()