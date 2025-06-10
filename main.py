import os
import json
import csv
import time
import threading
from flask import Flask
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    KeyboardButton, ReplyKeyboardMarkup
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler,
    filters, ContextTypes, ConversationHandler
)

# === CONFIG ===
TOKEN = os.getenv('TOKEN')
ADMIN_IDS = list(map(int, os.getenv('ADMIN_IDS', '').split(',')))
ALLOWED_ARR = [f"130{i:02}" for i in range(1, 17)]

PRODUCTS_FILE = 'products.json'
ORDERS_FILE = 'orders.csv'
user_data = {}
products = []
cooldowns = {}
COOLDOWN_SECONDS = 600
maintenance_mode = False

# === Flask pour Render ===
flask_app = Flask(__name__)

# === Fonctions de base ===
def load_products():
    if os.path.exists(PRODUCTS_FILE):
        with open(PRODUCTS_FILE, 'r') as f:
            return json.load(f)
    return []

def save_products():
    with open(PRODUCTS_FILE, 'w') as f:
        json.dump(products, f)

def save_order(user_id, items, address, phone, status):
    with open(ORDERS_FILE, 'a', newline='') as file:
        writer = csv.writer(file)
        writer.writerow([time.strftime("%Y-%m-%d %H:%M:%S"), user_id, items, address, phone, status])

def get_cart_total(cart):
    return sum(item['price'] for item in cart)

def get_cart_text(cart):
    if not cart:
        return "🛒 Panier vide."
    lines = [f"• {item['name']} - {item['price']}€" for item in cart]
    return "\n".join(lines) + f"\n\n💰 Total : {get_cart_total(cart)}€"
    # === Bot Telegram ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data[user_id] = {'cart': [], 'step': None}
    await update.message.reply_text("Bienvenue 👋 Tape /help pour commencer.")
    await send_product_menu(update, user_id)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "/start – Démarrer\n"
        "/help – Infos\n"
        "/admin – Panel admin\n"
        "🛒 Ajoute des produits, valide ton panier, entre adresse et numéro (facultatif).\n"
        "📦 Minimum 150€ hors arrondissements 13001 à 13016."
    )

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("⛔ Tu n'es pas admin.")
        return
    kb = [
        [InlineKeyboardButton("➕ Ajouter produit", callback_data="add_product")],
        [InlineKeyboardButton("📦 Modifier produits", callback_data="edit_product")]
    ]
    await update.message.reply_text("🔧 Panel admin :", reply_markup=InlineKeyboardMarkup(kb))

async def send_product_menu(update, user_id):
    if not products:
        await update.message.reply_text("Aucun produit pour le moment.")
        return
    kb = [[InlineKeyboardButton(p['name'], callback_data=f"add_{i}")] for i, p in enumerate(products)]
    kb += [[
        InlineKeyboardButton("🛒 Voir panier", callback_data="view_cart"),
        InlineKeyboardButton("❌ Vider", callback_data="clear_cart")
    ]]
    if user_id in ADMIN_IDS:
        kb.append([InlineKeyboardButton("🔧 Admin", callback_data="admin_panel")])
    await update.message.reply_text("Choisis un produit :", reply_markup=InlineKeyboardMarkup(kb))
    async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data
    await query.answer()

    if data.startswith("add_"):
        index = int(data.split("_")[1])
        user_data[user_id]['cart'].append(products[index])
        await query.message.reply_text(f"{products[index]['name']} ajouté au panier.")

    elif data == "view_cart":
        await query.message.reply_text(
            get_cart_text(user_data[user_id]['cart']),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Valider", callback_data="validate")],
                [InlineKeyboardButton("❌ Vider", callback_data="clear_cart")]
            ])
        )

    elif data == "clear_cart":
        user_data[user_id]['cart'] = []
        await query.message.reply_text("Panier vidé.")

    elif data == "validate":
        now = time.time()
        if user_id in cooldowns and now - cooldowns[user_id] < COOLDOWN_SECONDS:
            await query.message.reply_text("⏳ Attends un peu avant de recommander.")
            return
        cooldowns[user_id] = now
        await query.message.reply_text("📍 Ton adresse complète ? (avec l'arrondissement)")
        user_data[user_id]['step'] = 'get_address'

    elif data.startswith("valider_") or data.startswith("refuser_"):
        target_id = int(data.split("_")[1])
        status = "Validée" if "valider_" in data else "Refusée"
        cart_txt = get_cart_text(user_data[target_id]['cart'])
        save_order(
            target_id,
            cart_txt,
            user_data[target_id]["address"],
            user_data[target_id].get("phone", "Non fourni"),
            status
        )
        await context.bot.send_message(chat_id=target_id, text=f"Commande {status.lower()}. Merci 🙏")
        await query.message.reply_text(f"Commande {status} pour {target_id}.")
        if target_id in user_data:
            del user_data[target_id]

    elif data == "add_product" and user_id in ADMIN_IDS:
        user_data[user_id]['step'] = "add_name"
        await query.message.reply_text("Nom du nouveau produit ?")

    elif data == "edit_product" and user_id in ADMIN_IDS:
        kb = [[InlineKeyboardButton(p['name'], callback_data=f"edit_{i}")] for i, p in enumerate(products)]
        await query.message.reply_text("Produit à modifier :", reply_markup=InlineKeyboardMarkup(kb))

    elif data.startswith("edit_") and user_id in ADMIN_IDS:
        index = int(data.split("_")[1])
        user_data[user_id]['edit_index'] = index
        user_data[user_id]['step'] = "edit_name"
        await query.message.reply_text(f"Nouveau nom pour {products[index]['name']} ?")

    elif data == "admin_panel":
        await admin_panel(query, context)
        async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text

    if user_id not in user_data:
        user_data[user_id] = {'cart': [], 'step': None}

    step = user_data[user_id].get('step')

    if step == "get_address":
        user_data[user_id]["address"] = text
        if not any(text.startswith(arr) for arr in ALLOWED_ARR):
            if get_cart_total(user_data[user_id]['cart']) < 150:
                await update.message.reply_text("❌ Minimum 150€ requis hors 13001–13016.")
                return
        await update.message.reply_text("📱 Envoie ton numéro de téléphone.")
        user_data[user_id]['step'] = 'get_phone'

    elif step == "get_phone":
        user_data[user_id]["phone"] = text
        cart_txt = get_cart_text(user_data[user_id]['cart'])
        for admin_id in ADMIN_IDS:
            await context.bot.send_message(
                chat_id=admin_id,
                text=f"🛒 Nouvelle commande :\n\n{cart_txt}\n\n📍 Adresse : {user_data[user_id]['address']}\n📞 Num : {text}",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ Valider", callback_data=f"valider_{user_id}")],
                    [InlineKeyboardButton("❌ Refuser", callback_data=f"refuser_{user_id}")]
                ])
            )
        await update.message.reply_text("✅ Commande envoyée aux livreurs.")
        user_data[user_id]['step'] = None

    elif step == "add_name":
        user_data[user_id]['new_name'] = text
        user_data[user_id]['step'] = "add_price"
        await update.message.reply_text("Prix du produit ? (en chiffre uniquement)")

    elif step == "add_price":
        try:
            price = int(text)
            name = user_data[user_id]['new_name']
            products.append({"name": name, "price": price})
            save_products()
            await update.message.reply_text(f"✅ Produit {name} ({price}€) ajouté.")
        except:
            await update.message.reply_text("⛔ Prix invalide.")
        user_data[user_id]['step'] = None

    elif step == "edit_name":
        index = user_data[user_id]['edit_index']
        products[index]['name'] = text
        user_data[user_id]['step'] = "edit_price"
        await update.message.reply_text("Prix ?")

    elif step == "edit_price":
        try:
            price = int(text)
            index = user_data[user_id]['edit_index']
            products[index]['price'] = price
            save_products()
            await update.message.reply_text("✅ Produit modifié.")
        except:
            await update.message.reply_text("⛔ Prix invalide.")
        user_data[user_id]['step'] = None

def main():
    global products
    products = load_products()
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('help', help_command))
    app.add_handler(CommandHandler('admin', admin_panel))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.run_polling()

# Pour Render
@flask_app.route('/')
def index():
    return "Bot actif !"

def run_flask():
    flask_app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))

if __name__ == "__main__":
    threading.Thread(target=run_flask).start()
    main()