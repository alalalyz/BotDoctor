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

# Variables d'environnement
TOKEN = os.getenv('TOKEN')
ADMIN_IDS = list(map(int, os.getenv('ADMIN_IDS', '').split(',')))

user_data = {}
adding_product = {}
maintenance_mode = False

PRODUCTS_FILE = 'products.json'
ORDERS_FILE = 'orders.csv'

# Charger les produits
def load_products():
    if os.path.exists(PRODUCTS_FILE):
        with open(PRODUCTS_FILE, 'r') as file:
            return json.load(file)
    else:
        return {
            "Filtré": ["30€", "50€", "70€"],
            "Weed": ["50€", "100€"]
        }

# Sauvegarder les produits
def save_products():
    with open(PRODUCTS_FILE, 'w') as file:
        json.dump(PRODUCTS, file)

# Sauvegarder les commandes
def save_order(user_id, produit, address, phone, status):
    with open(ORDERS_FILE, 'a', newline='') as file:
        writer = csv.writer(file)
        writer.writerow([time.strftime("%Y-%m-%d %H:%M:%S"), user_id, produit, address, phone, status])

PRODUCTS = load_products()

NOTICE = """
🚚 *INFORMATION LIVRAISON :*

- Livraison possible dans tous les arrondissements.
- *ATTENTION* : En dehors du 1er au 16ème arrondissement, un minimum de commande de *150€* est requis.

Pour discuter du minimum ou plus d'informations :
👉 Contactez : [@DocteurSto](https://t.me/DocteurSto) ou [@S_Ottoo](https://t.me/S_Ottoo)
"""

# States
NAME, PRICES = range(2)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if maintenance_mode:
        await update.message.reply_text("🚧 Le service est actuellement en maintenance.")
        return

    await update.message.reply_text(NOTICE, parse_mode='Markdown', disable_web_page_preview=True)

    keyboard = [[InlineKeyboardButton(product, callback_data=product)] for product in PRODUCTS]
    await update.message.reply_text("Bienvenue ! Que veux-tu commander :", reply_markup=InlineKeyboardMarkup(keyboard))

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    choice = query.data

    if choice.startswith('valider_') or choice.startswith('refuser_'):
        return

    if choice in PRODUCTS:
        keyboard = [[InlineKeyboardButton(price, callback_data=f"{choice} {price}")] for price in PRODUCTS[choice]]
        await query.message.reply_text(f"Quel prix pour {choice} ?", reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        produit = choice
        user_data[user_id] = {"produit": produit}
        button = KeyboardButton('📱 Envoyer mon numéro', request_contact=True)
        reply_markup = ReplyKeyboardMarkup([[button]], one_time_keyboard=True, resize_keyboard=True)
        await query.message.reply_text(
            "🔒 *Ton anonymat est respecté.*\n\n"
            "Si tu veux être contacté plus rapidement pour la livraison, tu peux partager ton numéro (facultatif).\n"
            "_Attention :_ tu recevras un appel **en numéro masqué**.",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        await query.message.reply_text("Sinon, envoie directement ton adresse de livraison (et ton arrondissement).")

async def get_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    phone = update.message.contact.phone_number
    if user_id in user_data:
        user_data[user_id]["phone"] = phone
    await update.message.reply_text("Merci pour ton numéro ! Maintenant, envoie ton adresse de livraison.")

async def get_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    address = update.message.text.strip()
    if user_id not in user_data:
        return
        
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print(f"📩 /start reçu de {update.effective_user.id}")
    await update.message.reply_text("👋 Hello, ton bot est bien en ligne !")
    
    
    produit = user_data[user_id]["produit"]
    phone = user_data[user_id].get("phone", "Non fourni")
    user_data[user_id]["address"] = address

    arr = ''.join(filter(str.isdigit, address))
    arr_ok = any(arr.startswith(f"130{i:02}") for i in range(1, 17))
    if not arr_ok and not any("150" in p for p in produit.split()):
        await update.message.reply_text("❌ Minimum de 150€ requis hors 13001-13016.")
        save_order(user_id, produit, address, phone, "Refusée")
        return

    link = f"[Contacter le client](tg://user?id={user_id})"
    for admin_id in ADMIN_IDS:
        await context.bot.send_message(
            chat_id=admin_id,
            text=(
                f"🛒 *Nouvelle commande :*\n"
                f"**Produit :** {produit}\n"
                f"**Adresse :** {address}\n"
                f"**Numéro :** {phone}\n"
                f"**ID Telegram :** `{user_id}`\n"
                f"{link}"
            ),
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Valider", callback_data=f"valider_{user_id}")],
                [InlineKeyboardButton("❌ Refuser", callback_data=f"refuser_{user_id}")]
            ])
        )
    await update.message.reply_text("✅ Commande transmise ! En attente de validation.")

async def validate_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = int(data.split("_")[1])
    if "valider_" in data:
        status = "Validée"
        msg = "✅ Commande validée. Un livreur arrive."
    else:
        status = "Refusée"
        msg = "❌ Commande refusée."
    await context.bot.send_message(chat_id=user_id, text=msg)
    save_order(user_id, user_data[user_id]["produit"], user_data[user_id]["address"], user_data[user_id].get("phone", "Non fourni"), status)
    if user_id in user_data:
        del user_data[user_id]
    await query.message.reply_text(f"Commande {status.lower()}.")

async def add_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id not in ADMIN_IDS:
        await update.message.reply_text("🚫 Tu n'es pas admin.")
        return ConversationHandler.END
    await update.message.reply_text("Nom du produit ?", parse_mode='Markdown')
    return NAME

async def get_product_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    adding_product[user_id] = {"name": update.message.text}
    await update.message.reply_text("Prix ? (séparés par virgule)", parse_mode='Markdown')
    return PRICES

async def get_product_prices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    prices = [p.strip() for p in update.message.text.split(',')]
    name = adding_product[user_id]["name"]
    PRODUCTS[name] = prices
    save_products()
    del adding_product[user_id]
    await update.message.reply_text(f"✅ Produit *{name}* ajouté.", parse_mode='Markdown')
    return ConversationHandler.END

async def list_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not PRODUCTS:
        await update.message.reply_text("Aucun produit.")
        return
    msg = "🛒 *Produits disponibles :*\n\n"
    for name, prices in PRODUCTS.items():
        msg += f"- *{name}* : {', '.join(prices)}\n"
    await update.message.reply_text(msg, parse_mode='Markdown')

async def maintenance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global maintenance_mode
    if update.message.from_user.id not in ADMIN_IDS:
        await update.message.reply_text("🚫 Pas autorisé.")
        return
    maintenance_mode = not maintenance_mode
    status = "activé" if maintenance_mode else "désactivé"
    await update.message.reply_text(f"🚧 Maintenance {status}.")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Ajout annulé.")
    return ConversationHandler.END

def run_bot():
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
    app.add_handler(CallbackQueryHandler(validate_order, pattern='^(valider_|refuser_)'))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(MessageHandler(filters.CONTACT, get_contact))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, get_address))
    
async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✉️ Message reçu !")

app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))
print("✅ Bot en ligne.")
app.run_polling()

# Serveur Flask pour Render
app_flask = Flask(__name__)

@app_flask.route('/')
def index():
    return "Bot Telegram actif !"

if __name__ == '__main__':
    threading.Thread(target=run_bot).start()
    app_flask.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))