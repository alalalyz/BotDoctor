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

# === ENVIRONNEMENT ===
TOKEN = os.getenv("TOKEN")
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS", "").split(",")))
ALLOWED_ARR = [f"130{i:02}" for i in range(1, 17)]

PRODUCTS_FILE = "products.json"
ORDERS_FILE = "orders.csv"

user_data = {}
adding_product = {}
maintenance_mode = False

# === CHARGEMENT DES PRODUITS ===
def load_products():
    if os.path.exists(PRODUCTS_FILE):
        with open(PRODUCTS_FILE, 'r') as f:
            return json.load(f)
    return {"Filtré": ["30€", "50€", "70€"], "Weed": ["50€", "100€"]}

def save_products():
    with open(PRODUCTS_FILE, 'w') as f:
        json.dump(PRODUCTS, f)

def save_order(user_id, produit, address, phone, status):
    with open(ORDERS_FILE, 'a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([
            time.strftime("%Y-%m-%d %H:%M:%S"),
            user_id,
            produit,
            address,
            phone,
            status
        ])

PRODUCTS = load_products()

# === NOTICE ===
NOTICE = """
🚚 *INFORMATION LIVRAISON :*

- Livraison dans tous les arrondissements de Marseille.
- *ATTENTION* : En dehors des arrondissements 13001 à 13016, un minimum de commande de *150€* est requis.

📞 L'appel sera en inconnu pour protéger l'anonymat du livreur.
👉 Contact @DocteurSto ou @S_Ottoo pour plus d’infos.
"""

# === ÉTAPES CONVERSATION ===
NAME, PRICES = range(2)

# === DÉMARRAGE ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if maintenance_mode:
        await update.message.reply_text("🚧 Le service est en maintenance.")
        return

    await update.message.reply_text(NOTICE, parse_mode='Markdown')
    keyboard = [[InlineKeyboardButton(name, callback_data=name)] for name in PRODUCTS.keys()]
    await update.message.reply_text("Bienvenue ! Que veux-tu commander ?", reply_markup=InlineKeyboardMarkup(keyboard))

# === SÉLECTION PRODUIT ===
async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data

    if data in PRODUCTS:
        kb = [[InlineKeyboardButton(price, callback_data=f"{data}|{price}")] for price in PRODUCTS[data]]
        await query.message.reply_text(f"Quel prix pour {data} ?", reply_markup=InlineKeyboardMarkup(kb))
    elif "|" in data:
        produit, prix = data.split("|")
        user_data[user_id] = {"produit": f"{produit} {prix}"}
        btn = KeyboardButton("📱 Envoyer mon numéro", request_contact=True)
        await query.message.reply_text(
            "Souhaites-tu partager ton numéro ? (facultatif)", 
            reply_markup=ReplyKeyboardMarkup([[btn]], resize_keyboard=True, one_time_keyboard=True)
        )
        await query.message.reply_text("Sinon, envoie directement ton *adresse de livraison*", parse_mode='Markdown')
    elif data.startswith("valider_") or data.startswith("refuser_"):
        target = int(data.split("_")[1])
        status = "Validée" if data.startswith("valider") else "Refusée"
        await context.bot.send_message(
            chat_id=target,
            text="✅ Ta commande a été validée, un livreur arrive !" if status == "Validée"
            else "❌ Ta commande a été refusée, réessaie plus tard."
        )
        save_order(target, user_data[target]['produit'], user_data[target]['address'], user_data[target].get('phone', 'Non fourni'), status)
        del user_data[target]
        await query.message.reply_text(f"Commande {status.lower()} pour {target}.")
    elif data.startswith("remove_"):
        pname = data.replace("remove_", "")
        if pname in PRODUCTS:
            del PRODUCTS[pname]
            save_products()
            await query.message.reply_text(f"✅ Produit {pname} supprimé.")

# === CONTACT ===
async def get_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    phone = update.message.contact.phone_number
    user_data[user_id]["phone"] = phone
    await update.message.reply_text("Merci ! Envoie maintenant ton adresse de livraison.")

# === ADRESSE ===
async def get_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    address = update.message.text.strip()
    data = user_data.get(user_id)
    if not data:
        return
    user_data[user_id]["address"] = address
    phone = user_data[user_id].get("phone", "Non fourni")
    produit = user_data[user_id]["produit"]
    arr = address[:5]
    if arr not in ALLOWED_ARR and int(produit.split()[-1].replace("€", "")) < 150:
        await update.message.reply_text("❌ Minimum de 150€ requis hors arrondissements 13001–13016.")
        return
    for admin in ADMIN_IDS:
        await context.bot.send_message(
            chat_id=admin,
            text=f"🛒 *Commande de {user_id}* :\n"
                 f"• Produit : {produit}\n"
                 f"• Adresse : {address}\n"
                 f"• Téléphone : {phone}\n"
                 f"• [Contacter](tg://user?id={user_id})",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Valider", callback_data=f"valider_{user_id}")],
                [InlineKeyboardButton("❌ Refuser", callback_data=f"refuser_{user_id}")]
            ])
        )
    await update.message.reply_text("Commande envoyée pour validation. Merci !")

# === AJOUT PRODUIT ===
async def add_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id not in ADMIN_IDS:
        await update.message.reply_text("🚫 Pas autorisé.")
        return ConversationHandler.END
    await update.message.reply_text("Nom du produit ?")
    return NAME

async def get_product_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    adding_product[user_id] = {"name": update.message.text}
    await update.message.reply_text("Prix ? (séparés par virgules : 20€, 50€...)")
    return PRICES

async def get_product_prices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    prices = [p.strip() for p in update.message.text.split(",")]
    name = adding_product[user_id]["name"]
    PRODUCTS[name] = prices
    save_products()
    await update.message.reply_text(f"✅ Produit {name} ajouté.")
    del adding_product[user_id]
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Ajout annulé.")
    return ConversationHandler.END

# === MAINTENANCE MODE ===
async def maintenance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global maintenance_mode
    if update.message.from_user.id not in ADMIN_IDS:
        return
    maintenance_mode = not maintenance_mode
    await update.message.reply_text(f"🔧 Maintenance {'activée' if maintenance_mode else 'désactivée'}.")

# === LISTE PRODUITS / SUPPRESSION ===
async def list_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = "🛒 *Produits disponibles :*\n\n"
    for k, v in PRODUCTS.items():
        msg += f"- *{k}* : {', '.join(v)}\n"
    await update.message.reply_text(msg, parse_mode='Markdown')

async def remove_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id not in ADMIN_IDS:
        return
    kb = [[InlineKeyboardButton(k, callback_data=f"remove_{k}")] for k in PRODUCTS]
    await update.message.reply_text("Quel produit supprimer ?", reply_markup=InlineKeyboardMarkup(kb))

# === MAIN ===
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

    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("listproducts", list_products))
    app.add_handler(CommandHandler("removeproduct", remove_product))
    app.add_handler(CommandHandler("maintenance", maintenance))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(MessageHandler(filters.CONTACT, get_contact))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, get_address))

    print("🚀 Bot en ligne")
    app.run_polling()

if __name__ == "__main__":
    main()