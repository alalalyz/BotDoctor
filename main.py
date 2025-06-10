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

TOKEN = os.getenv('TOKEN')
ADMIN_IDS = list(map(int, os.getenv('ADMIN_IDS', '').split(',')))

PRODUCTS_FILE = 'products.json'
ORDERS_FILE = 'orders.csv'

user_data = {}         # {user_id: {produit, prix, phone, address}}
user_cart = {}         # {user_id: [{"produit": str, "prix": str}]}
adding_product = {}    # Pour le mode /addproduct
maintenance_mode = False

def load_products():
    if os.path.exists(PRODUCTS_FILE):
        with open(PRODUCTS_FILE, 'r') as f:
            return json.load(f)
    return {
        "Filtré": ["30€", "50€", "70€"],
        "Weed": ["50€", "100€"]
    }

def save_products():
    with open(PRODUCTS_FILE, 'w') as f:
        json.dump(PRODUCTS, f)

def save_order(user_id, cart, address, phone, status):
    with open(ORDERS_FILE, 'a', newline='') as f:
        writer = csv.writer(f)
        for item in cart:
            writer.writerow([
                time.strftime("%Y-%m-%d %H:%M:%S"),
                user_id,
                item["produit"] + " " + item["prix"],
                address,
                phone,
                status
            ])

PRODUCTS = load_products()
NOTICE = """
🚚 *INFORMATION LIVRAISON :*

- Livraison possible dans tous les arrondissements.
- *ATTENTION* : En dehors du 1er au 16ème arrondissement, un minimum de commande de *150€* est requis.

Pour discuter du minimum ou plus d'informations :
👉 [@DocteurSto](https://t.me/DocteurSto) | [@S_Ottoo](https://t.me/S_Ottoo)
"""

NAME, PRICES = range(2)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if maintenance_mode:
        await update.message.reply_text("🚧 Le service est en maintenance.")
        return

    user_id = update.message.from_user.id
    user_cart[user_id] = []

    await update.message.reply_text(NOTICE, parse_mode='Markdown', disable_web_page_preview=True)
    keyboard = [[InlineKeyboardButton(prod, callback_data=prod)] for prod in PRODUCTS]
    await update.message.reply_text("Bienvenue ! Choisis une catégorie :", reply_markup=InlineKeyboardMarkup(keyboard))

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    choice = query.data

    if choice.startswith("valider_") or choice.startswith("refuser_"):
        return

    if choice in PRODUCTS:
        keyboard = [[InlineKeyboardButton(price, callback_data=f"{choice} {price}")] for price in PRODUCTS[choice]]
        await query.message.reply_text(f"Choisis un prix pour {choice} :", reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        produit, prix = choice.split(" ", 1)
        if user_id not in user_cart:
            user_cart[user_id] = []
        user_cart[user_id].append({"produit": produit, "prix": prix})
        user_data[user_id] = {"produit": produit, "prix": prix}
        button = KeyboardButton("📱 Envoyer mon numéro", request_contact=True)
        reply_markup = ReplyKeyboardMarkup([[button]], resize_keyboard=True, one_time_keyboard=True)
        await query.message.reply_text("Partage ton numéro ou envoie ton adresse directement :", reply_markup=reply_markup)

async def get_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    phone = update.message.contact.phone_number
    if user_id in user_data:
        user_data[user_id]["phone"] = phone
    await update.message.reply_text("Merci ! Envoie ton adresse de livraison.")

async def get_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    address = update.message.text.strip()
    if user_id not in user_cart or not user_cart[user_id]:
        await update.message.reply_text("❌ Tu dois d'abord ajouter un produit.")
        return

    phone = user_data.get(user_id, {}).get("phone", "Non fourni")
    total = sum(int(item["prix"].replace("€", "")) for item in user_cart[user_id])
    arr = ''.join(filter(str.isdigit, address))
    is_marseille = any(arr.startswith(f"130{i:02}") for i in range(1, 17))

    if not is_marseille and total < 150:
        await update.message.reply_text("❌ Minimum de 150€ requis pour les zones hors 13001-13016.")
        save_order(user_id, user_cart[user_id], address, phone, "Refusée")
        user_cart[user_id] = []
        return

    user_data[user_id]["address"] = address
    telegram_link = f"[Contacter le client](tg://user?id={user_id})"

    for admin_id in ADMIN_IDS:
        txt = f"🛒 *Nouvelle commande :*\n\n"
        for item in user_cart[user_id]:
            txt += f"- {item['produit']} {item['prix']}\n"
        txt += f"\n📍 *Adresse* : {address}\n📞 *Numéro* : {phone}\n🆔 *ID* : `{user_id}`\n{telegram_link}"
        await context.bot.send_message(
            chat_id=admin_id,
            text=txt,
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Valider", callback_data=f"valider_{user_id}")],
                [InlineKeyboardButton("❌ Refuser", callback_data=f"refuser_{user_id}")]
            ])
        )

    await update.message.reply_text("Merci ! Commande transmise pour validation.")

async def validate_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = int(data.split("_")[1])

    if user_id not in user_cart:
        await query.message.reply_text("❌ Panier introuvable.")
        return

    status = "Validée" if "valider" in data else "Refusée"
    msg = "✅ Ta commande a été validée." if status == "Validée" else "❌ Commande refusée."

    await context.bot.send_message(chat_id=user_id, text=msg)
    address = user_data[user_id].get("address", "Inconnue")
    phone = user_data[user_id].get("phone", "Non fourni")
    save_order(user_id, user_cart[user_id], address, phone, status)

    del user_cart[user_id]
    if user_id in user_data:
        del user_data[user_id]

    await query.message.reply_text(f"Commande {status.lower()}.")

async def add_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ Pas autorisé.")
        return ConversationHandler.END
    await update.message.reply_text("Nom du nouveau produit ?")
    return NAME

async def get_product_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    adding_product[user_id] = {"name": update.message.text}
    await update.message.reply_text("Prix disponibles ? (séparés par virgules)")
    return PRICES

async def get_product_prices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    prices = [p.strip() for p in update.message.text.split(",")]
    product = adding_product[user_id]["name"]
    PRODUCTS[product] = prices
    save_products()
    del adding_product[user_id]
    await update.message.reply_text(f"✅ Produit *{product}* ajouté.", parse_mode='Markdown')
    return ConversationHandler.END

async def list_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not PRODUCTS:
        await update.message.reply_text("Aucun produit.")
        return
    txt = "🛒 *Produits disponibles :*\n\n"
    for p, prices in PRODUCTS.items():
        txt += f"- *{p}* : {', '.join(prices)}\n"
    await update.message.reply_text(txt, parse_mode='Markdown')

async def maintenance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global maintenance_mode
    if update.message.from_user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ Pas autorisé.")
        return
    maintenance_mode = not maintenance_mode
    await update.message.reply_text(f"🔧 Maintenance {'activée' if maintenance_mode else 'désactivée'}.")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Ajout annulé.")
    return ConversationHandler.END

def main():
    app = ApplicationBuilder().token(TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("addproduct", add_product)],
        states={
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_product_name)],
            PRICES: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_product_prices)],
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("listproducts", list_products))
    app.add_handler(CommandHandler("maintenance", maintenance))
    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(validate_order, pattern="^(valider_|refuser_)"))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(MessageHandler(filters.CONTACT, get_contact))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, get_address))

    print("✅ Bot lancé.")
    app.run_polling()

if __name__ == '__main__':
    main()