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
    filters, ContextTypes, ConversationHandler
)

# 🔥 Variables d'environnement
TOKEN = os.getenv('TOKEN')
ADMIN_IDS = list(map(int, os.getenv('ADMIN_IDS', '').split(',')))

user_data = {}
adding_product = {}
maintenance_mode = False

# Sauvegarde produits
PRODUCTS_FILE = 'products.json'
# Sauvegarde commandes
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

# Notice Livraison
NOTICE = """
🚚 *INFORMATION LIVRAISON :*

- Livraison possible dans tous les arrondissements.
- *ATTENTION* : En dehors du 1er au 16ème arrondissement, un minimum de commande de *150€* est requis.

Pour discuter du minimum ou plus d'informations :
👉 Contactez : [@DocteurSto](https://t.me/DocteurSto) ou [@S_Ottoo](https://t.me/S_Ottoo)
"""

# States
NAME, PRICES, REMOVE_CONFIRM = range(3)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if maintenance_mode:
        await update.message.reply_text("🚧 Le service est actuellement en maintenance. Merci de revenir plus tard.")
        return

    await update.message.reply_text(
        NOTICE,
        parse_mode='Markdown',
        disable_web_page_preview=True
    )

    keyboard = []
    for product in PRODUCTS.keys():
        keyboard.append([InlineKeyboardButton(product, callback_data=product)])

    await update.message.reply_text(
        "Bienvenue ! Que veux-tu commander :",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    choice = query.data

    if choice.startswith('valider_') or choice.startswith('refuser_'):
        return

    if choice in PRODUCTS:
        keyboard = [[InlineKeyboardButton(price, callback_data=f"{choice} {price}")] for price in PRODUCTS[choice]]
        await query.message.reply_text(
            f"Quel prix pour {choice} ?",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        produit = choice
        user_data[user_id] = {"produit": produit}
        button = KeyboardButton('📱 Envoyer mon numéro', request_contact=True)
        reply_markup = ReplyKeyboardMarkup([[button]], one_time_keyboard=True, resize_keyboard=True)
        await query.message.reply_text(
            "🔒 *Ton anonymat est respecté."*

"
            "Si tu veux être contacté plus rapidement pour la livraison, tu peux partager ton numéro (facultatif).
"
            "_Attention :_ tu recevras un appel **en numéro masqué** pour protéger ton anonymat.",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        await update.effective_message.reply_text(
            "Sinon, envoie directement ton adresse de livraison (et ton arrondissement)."
        )

async def get_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    phone_number = update.message.contact.phone_number

    if user_id in user_data:
        user_data[user_id]["phone"] = phone_number

    await update.message.reply_text("Merci pour ton numéro ! Maintenant, envoie ton adresse de livraison.")

async def get_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    address = update.message.text.strip()

    if user_id not in user_data:
        return

    produit = user_data[user_id]["produit"]
    user_data[user_id]["address"] = address
    phone = user_data[user_id].get("phone", "Non fourni")

    # Extraire l'arrondissement
    arr = ''.join(filter(str.isdigit, address))
    arr_ok = any(arr.startswith(f"130{i:02}") for i in range(1, 17))

    if not arr_ok and not any(price.startswith("150") or "150" in price for price in produit):
        await update.message.reply_text("❌ Minimum de 150€ requis pour les zones hors 13001-13016.")
        save_order(user_id, produit, address, phone, "Refusée")
        return

    telegram_link = f"[Contacter le client](tg://user?id={user_id})"

    for admin_id in ADMIN_IDS:
        await context.bot.send_message(
            chat_id=admin_id,
            text=f"🛒 **Nouvelle commande :**
"
                 f"**Produit :** {produit}
"
                 f"**Adresse :** {address}
"
                 f"**Numéro :** {phone}
"
                 f"**ID Telegram :** `{user_id}`
"
                 f"{telegram_link}",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Valider la commande", callback_data=f"valider_{user_id}")],
                [InlineKeyboardButton("❌ Refuser", callback_data=f"refuser_{user_id}")]
            ])
        )

    await update.message.reply_text("Merci ! Votre commande est en attente de validation.")

async def validate_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    user_id = int(data.split("_")[1])
    if "valider_" in data:
        status = "Validée"
        message = "✅ Votre commande a été validée. Un livreur est en route, prépare le paiement !"
    else:
        status = "Refusée"
        message = "❌ Désolé, ta commande a été refusée. Réessaie plus tard."

    await context.bot.send_message(chat_id=user_id, text=message)
    save_order(user_id, user_data[user_id]["produit"], user_data[user_id]["address"], user_data[user_id].get("phone", "Non fourni"), status)

    if user_id in user_data:
        del user_data[user_id]

    await query.message.reply_text(f"Commande {status.lower()}.")

def main():
    app = ApplicationBuilder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('addproduct', add_product)],
        states={
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_product_name)],
            PRICES: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_product_prices)]
        },
        fallbacks=[]
    )

    app.add_handler(CommandHandler('start', start))
    app.add_handler(CallbackQueryHandler(validate_order, pattern='^(valider_|refuser_)'))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(MessageHandler(filters.CONTACT, get_contact))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, get_address))
    app.add_handler(conv_handler)

    print("✅ Bot démarré.")
    app.run_polling()

if __name__ == '__main__':
    main()
