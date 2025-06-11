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

user_data = {}
user_cart = {}
adding_product = {}
maintenance_mode = False

PRODUCTS_FILE = 'products.json'
ORDERS_FILE = 'orders.csv'

def load_products():
    if os.path.exists(PRODUCTS_FILE):
        with open(PRODUCTS_FILE, 'r') as file:
            return json.load(file)
    return {"Filtré": ["30€", "50€", "70€"], "Weed": ["50€", "100€"]}

def save_products():
    with open(PRODUCTS_FILE, 'w') as file:
        json.dump(PRODUCTS, file)

def save_order(user_id, produits, address, phone, status):
    with open(ORDERS_FILE, 'a', newline='') as file:
        writer = csv.writer(file)
        writer.writerow([time.strftime("%Y-%m-%d %H:%M:%S"), user_id, produits, address, phone, status])

PRODUCTS = load_products()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if maintenance_mode:
        await update.message.reply_text("🚧 Le service est en maintenance.")
        return

    user_id = update.message.from_user.id
    user_cart[user_id] = []

    keyboard = [[InlineKeyboardButton(prod, callback_data=prod)] for prod in PRODUCTS]
    await update.message.reply_text(
        "Bienvenue ! Choisis une catégorie de produit :",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data

    if data.startswith('valider_') or data.startswith('refuser_'):
        return

    if data in PRODUCTS:
        keyboard = [[InlineKeyboardButton(price, callback_data=f"{data}|{price}")] for price in PRODUCTS[data]]
        await query.message.reply_text(f"Choisis un prix pour {data} :", reply_markup=InlineKeyboardMarkup(keyboard))
    elif "|" in data:
        produit, prix = data.split("|")
        user_cart.setdefault(user_id, []).append(f"{produit} - {prix}")
        await query.message.reply_text(f"✅ Ajouté : {produit} - {prix}\n\nTu peux ajouter d'autres ou taper /valider pour finaliser.")

async def get_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    phone = update.message.contact.phone_number
    user_data[user_id] = user_data.get(user_id, {})
    user_data[user_id]["phone"] = phone
    await update.message.reply_text("Merci ! Maintenant, envoie ton adresse de livraison (avec l’arrondissement).")

async def get_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    address = update.message.text.strip()
    produit = "\n".join(user_cart.get(user_id, []))
    total = sum(int(p.split('€')[0].split()[-1]) for p in user_cart.get(user_id, []) if '€' in p)
    phone = user_data.get(user_id, {}).get("phone", "Non fourni")

    arr = ''.join(filter(str.isdigit, address))
    arr_ok = any(arr.startswith(f"130{i:02}") for i in range(1, 17))

    if not arr_ok and total < 150:
        await update.message.reply_text("❌ Commande refusée : minimum 150€ requis hors 13001-13016.")
        save_order(user_id, produit, address, phone, "Refusée")
        return

    user_data[user_id] = {
        "produit": produit,
        "address": address,
        "phone": phone,
        "total": total
    }

    for admin in ADMIN_IDS:
        await context.bot.send_message(
            admin,
            f"📦 *Nouvelle commande :*\n\n"
            f"*Produit(s)* :\n{produit}\n"
            f"*Total* : {total}€\n"
            f"*Adresse* : {address}\n"
            f"*Téléphone* : {phone}\n"
            f"ID : `{user_id}`",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Valider", callback_data=f"valider_{user_id}")],
                [InlineKeyboardButton("❌ Refuser", callback_data=f"refuser_{user_id}")]
            ])
        )
    await update.message.reply_text("Commande envoyée à l’équipe. Tu seras contacté rapidement.")

async def validate_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = int(query.data.split('_')[1])
    status = "Validée" if query.data.startswith("valider") else "Refusée"
    message = "✅ Commande validée. Prépare l’argent !" if status == "Validée" else "❌ Commande refusée. Réessaie plus tard."

    await context.bot.send_message(chat_id=user_id, text=message)
    data = user_data.get(user_id, {})
    save_order(user_id, data.get("produit", ""), data.get("address", ""), data.get("phone", ""), status)
    if user_id in user_cart:
        del user_cart[user_id]
    if user_id in user_data:
        del user_data[user_id]
    await query.message.reply_text(f"Commande {status.lower()} pour {user_id}.")

# Gestion produits
NAME, PRICES = range(2)

async def add_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id not in ADMIN_IDS:
        await update.message.reply_text("🚫 Pas autorisé.")
        return ConversationHandler.END
    await update.message.reply_text("Nom du produit ?")
    return NAME

async def get_product_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    adding_product[user_id] = {"name": update.message.text}
    await update.message.reply_text("Prix ? (séparés par virgule)")
    return PRICES

async def get_product_prices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    prices = [p.strip() for p in update.message.text.split(',')]
    name = adding_product[user_id]["name"]
    PRODUCTS[name] = prices
    save_products()
    del adding_product[user_id]
    await update.message.reply_text(f"✅ Produit '{name}' ajouté avec : {', '.join(prices)}")
    return ConversationHandler.END

async def list_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not PRODUCTS:
        await update.message.reply_text("Aucun produit.")
        return
    msg = "🛒 Produits disponibles :\n\n"
    for name, prices in PRODUCTS.items():
        msg += f"- {name} : {', '.join(prices)}\n"
    await update.message.reply_text(msg)

async def view_cart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    cart = user_cart.get(user_id, [])
    if not cart:
        await update.message.reply_text("🛒 Ton panier est vide.")
        return
    total = sum(int(p.split('€')[0].split()[-1]) for p in cart if '€' in p)
    await update.message.reply_text("🧾 Panier actuel :\n\n" + "\n".join(cart) + f"\n\nTotal : {total}€")

async def maintenance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global maintenance_mode
    if update.message.from_user.id not in ADMIN_IDS:
        await update.message.reply_text("🚫 Pas autorisé.")
        return
    maintenance_mode = not maintenance_mode
    await update.message.reply_text(f"🔧 Mode maintenance {'activé' if maintenance_mode else 'désactivé'}.")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Ajout annulé.")
    return ConversationHandler.END

def main():
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
    app.add_handler(CommandHandler("cart", view_cart))
    app.add_handler(CommandHandler("valider", get_contact))
    app.add_handler(conv_handler)
    app.add_handler(CallbackQueryHandler(validate_order, pattern="^(valider_|refuser_)"))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(MessageHandler(filters.CONTACT, get_contact))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, get_address))

    print("✅ Bot lancé avec polling.")
    app.run_polling()

if __name__ == '__main__':
    main()