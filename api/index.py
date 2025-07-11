import os
import json
import asyncio
import random
import logging
import traceback
from flask import Flask, request, jsonify
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import (
   Application,
   CommandHandler,
   MessageHandler,
   filters,
   ContextTypes,
   ConversationHandler,
   CallbackQueryHandler,
)
from PIL import Image, ImageDraw, ImageFont

# --- Flask App Setup for Vercel ---
app = Flask(__name__)

# --- Configuration using Environment Variables ---
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
ADMIN_ID = int(os.environ.get('ADMIN_ID', 0))
TARGET_GROUP_ID = int(os.environ.get('TARGET_GROUP_ID', 0))
VERCEL_URL = os.environ.get('VERCEL_URL')

# --- Bot Configuration ---
MEMBERS_TO_ADD = 10
WATERMARK_TEXT = "Your Group Name"

# --- File Paths for Serverless Environment ---
PUBLIC_DIR = "/var/task/public/" if os.path.exists("/var/task/public/") else "public/"
TMP_DIR = "/tmp"

USERS_FILE = os.path.join(TMP_DIR, "bot_users.json")
ELIGIBLE_USERS_FILE = os.path.join(TMP_DIR, "eligible_users.json")
COUNTS_FILE = os.path.join(TMP_DIR, "user_add_counts.json")
LEADERBOARD_FILE = os.path.join(TMP_DIR, "leaderboard.json")

IMAGE_FILES = {f'style{i}': os.path.join(PUBLIC_DIR, f'style{i}.png') for i in range(1, 9)}
PREVIEW_FILES = {1: os.path.join(PUBLIC_DIR, 'styles1_preview.png'), 2: os.path.join(PUBLIC_DIR, 'styles2_preview.png')}
FONT_FILE = os.path.join(PUBLIC_DIR, "Chonburi-Regular.ttf")
WATERMARK_FONT_FILE = os.path.join(PUBLIC_DIR, "arial.ttf")

# --- Logging Setup ---
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Conversation States ---
CHOOSING_STYLE, TYPING_NAME, TYPING_BROADCAST, CONFIRM_BROADCAST = range(4)

# --- Data Handling Functions ---
def load_json_data(filename: str, data_type=dict):
   if not os.path.exists(filename): return data_type()
   try:
       with open(filename, "r") as f: return data_type(json.load(f))
   except (json.JSONDecodeError, IOError, FileNotFoundError): return data_type()

def save_json_data(filename: str, data):
   data_to_save = list(data) if isinstance(data, set) else data
   with open(filename, "w") as f: json.dump(data_to_save, f, indent=4)

def add_user(user_id: int):
   users = load_json_data(USERS_FILE, set)
   users.add(user_id)
   save_json_data(USERS_FILE, users)

# --- Image Creation Function ---
def create_name_image(name: str, background_filename: str) -> (str, str):
   try:
       if not os.path.exists(background_filename): return None, f"'{background_filename}' not found"
       if not os.path.exists(FONT_FILE): return None, f"'{FONT_FILE}' not found"
       base_image = Image.open(background_filename).convert("RGBA")
       d = ImageDraw.Draw(base_image)
       main_font = ImageFont.truetype(FONT_FILE, int(base_image.width / 5.5))
       W, H = base_image.size
       _, _, text_width, _ = d.textbbox((0, 0), name, font=main_font)
       d.text(((W - text_width) / 2, H * 0.10), name, font=main_font, fill=(255, 255, 255), stroke_width=int(main_font.size / 25), stroke_fill=(0, 0, 0))
       try:
           watermark_font = ImageFont.truetype(WATERMARK_FONT_FILE, int(base_image.width / 30))
           _, _, wm_width, wm_height = d.textbbox((0, 0), WATERMARK_TEXT, font=watermark_font)
           d.text((W - wm_width - 20, H - wm_height - 20), WATERMARK_TEXT, font=watermark_font, fill=(255, 255, 255, 128))
       except IOError: logger.warning("Watermark font not found, skipping watermark.")
       output_filename = os.path.join(TMP_DIR, f"card_for_{''.join(c for c in name if c.isalnum())}.png")
       base_image.convert("RGB").save(output_filename)
       return output_filename, None
   except Exception as e:
       logger.error(f"Critical error in create_name_image: {e}", exc_info=True)
       return None, str(e)

# --- Keyboard Helper ---
def get_style_keyboard(page: int = 1) -> InlineKeyboardMarkup:
   keyboard = []
   if page == 1:
       keyboard = [[InlineKeyboardButton(f"Style {i}", callback_data=f'style{i}') for i in range(1, 3)], [InlineKeyboardButton(f"Style {i}", callback_data=f'style{i}') for i in range(3, 5)]]
       keyboard.append([InlineKeyboardButton("🎲 Surprise Me!", callback_data='random_style'), InlineKeyboardButton("Next Page ➡️", callback_data='page_2')])
   else:
       keyboard = [[InlineKeyboardButton(f"Style {i}", callback_data=f'style{i}') for i in range(5, 7)], [InlineKeyboardButton(f"Style {i}", callback_data=f'style{i}') for i in range(7, 9)]]
       keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data='page_1')])
   return InlineKeyboardMarkup(keyboard)

# --- Bot Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
   add_user(update.effective_user.id)
   await update.message.reply_html(
       "👋 <b>Welcome!</b>\n\nThis bot lets you create awesome custom profile pictures by contributing to our community.\n\n"
       f"To get started, add <b>{MEMBERS_TO_ADD} members</b> to the group, then send me the <b>/create</b> command in this private chat.\n\n"
       "Use <b>/myprogress</b> to check your status and <b>/top</b> to see the top contributors!"
   )

async def ping_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
   await update.message.reply_text("Pong!")

async def handle_new_members(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
   if update.message.chat.id != TARGET_GROUP_ID: return
   adder = update.message.from_user
   adder_id_str = str(adder.id)
   num_added = len(update.message.new_chat_members)
   add_user(adder.id)
   for member in update.message.new_chat_members:
       await update.message.reply_html(f"👋 Welcome to the group, <b>{member.first_name}</b>!")
   counts = load_json_data(COUNTS_FILE)
   current_count = counts.get(adder_id_str, 0) + num_added
   counts[adder_id_str] = current_count
   leaderboard = load_json_data(LEADERBOARD_FILE)
   user_info = leaderboard.get(adder_id_str, {'name': adder.first_name, 'count': 0})
   user_info['count'] += num_added
   user_info['name'] = adder.first_name
   leaderboard[adder_id_str] = user_info
   save_json_data(LEADERBOARD_FILE, leaderboard)
   if current_count >= MEMBERS_TO_ADD:
       eligible_users = load_json_data(ELIGIBLE_USERS_FILE, set)
       eligible_users.add(adder.id)
       save_json_data(ELIGIBLE_USERS_FILE, eligible_users)
       counts[adder_id_str] = 0
       await update.message.reply_html(
           f"🎉 <b>Congratulations {adder.first_name}!</b> 🎉\n\n"
           "You've completed the challenge! To create your custom image, please start a "
           f"private chat with me (<a href='tg://user?id={context.bot.id}'>click here</a>) and send the <b>/create</b> command."
       )
   else:
       await update.message.reply_html(f"Thank you, {adder.first_name}! Your progress: <b>{current_count}/{MEMBERS_TO_ADD}</b>")
   save_json_data(COUNTS_FILE, counts)

async def myprogress_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
   user_id_str = str(update.effective_user.id)
   counts = load_json_data(COUNTS_FILE)
   current_count = counts.get(user_id_str, 0)
   await update.message.reply_html(f"📈 Your current progress: <b>{current_count}/{MEMBERS_TO_ADD}</b> members added.")

async def top_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
   leaderboard = load_json_data(LEADERBOARD_FILE)
   if not leaderboard:
       await update.message.reply_text("The leaderboard is empty. Start adding members!")
       return
   sorted_users = sorted(leaderboard.values(), key=lambda x: x['count'], reverse=True)
   text = "🏆 <b>Top Contributors</b> 🏆\n\n"
   for i, user in enumerate(sorted_users[:5], 1):
       medals = {1: "🥇", 2: "🥈", 3: "🥉"}
       text += f"{medals.get(i, f'<b>{i}.</b>')} {user['name']} - {user['count']} members\n"
   await update.message.reply_html(text)

async def create_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
   user_id = update.effective_user.id
   add_user(user_id)
   if user_id not in load_json_data(ELIGIBLE_USERS_FILE, set):
       await update.message.reply_html(f"Sorry, you must first add <b>{MEMBERS_TO_ADD} members</b> to the group to use this command.")
       return ConversationHandler.END
   try:
       with open(PREVIEW_FILES[1], "rb") as preview_photo:
           await update.message.reply_photo(photo=preview_photo, caption="Please choose a style from Page 1:", reply_markup=get_style_keyboard(page=1))
   except FileNotFoundError:
       await update.message.reply_text(f"Admin Error: The preview file '{PREVIEW_FILES[1]}' was not found.")
       return ConversationHandler.END
   return CHOOSING_STYLE

async def handle_page_and_style_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
   query = update.callback_query
   await query.answer()
   choice = query.data
   if choice.startswith('page_'):
       page_num = int(choice.split('_')[1])
       try:
           media = InputMediaPhoto(media=open(PREVIEW_FILES[page_num], 'rb'))
           await query.edit_message_media(media=media, reply_markup=get_style_keyboard(page=page_num))
       except FileNotFoundError:
           await context.bot.send_message(chat_id=query.from_user.id, text=f"Admin Error: The preview file '{PREVIEW_FILES[page_num]}' was not found.")
       return CHOOSING_STYLE
   if choice == 'random_style':
       choice = random.choice(list(IMAGE_FILES.keys()))
   context.user_data['chosen_style'] = choice
   await query.edit_message_caption(caption=f"Great! You selected {choice}.")
   await context.bot.send_message(chat_id=query.from_user.id, text="Now, please type the name you want on the image.")
   return TYPING_NAME

async def handle_name_and_create(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
   name = update.message.text
   style = context.user_data.get('chosen_style')
   user_id = update.effective_user.id
   await update.message.reply_text("Awesome! Creating your image now, please wait...")
   image_file, error_message = create_name_image(name, IMAGE_FILES[style])
   if image_file:
       try:
           with open(image_file, 'rb') as photo:
               await update.message.reply_photo(photo, caption=f"Here is your masterpiece for '{name}'!")
           eligible_users = load_json_data(ELIGIBLE_USERS_FILE, set)
           eligible_users.discard(user_id)
           save_json_data(ELIGIBLE_USERS_FILE, eligible_users)
       finally:
           if os.path.exists(image_file): os.remove(image_file)
   else:
       await update.message.reply_text("Sorry, an error occurred. The admin has been notified.")
       await context.bot.send_message(chat_id=ADMIN_ID, text=f"⚠️ Image Generation Failed!\n\nUser: {update.effective_user.first_name}\nError: `{error_message}`")
   context.user_data.clear()
   return ConversationHandler.END

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
   if update.effective_user.id != ADMIN_ID: return
   keyboard = [[InlineKeyboardButton("📊 View Stats", callback_data='admin_stats')], [InlineKeyboardButton("📢 Broadcast Message", callback_data='admin_broadcast')]]
   await update.message.reply_html("🔑 <b>Admin Dashboard</b>", reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
   query = update.callback_query
   await query.answer()
   choice = query.data
   if choice == 'admin_stats':
       await query.message.delete()
       await stats_command(query, context)
       return ConversationHandler.END
   elif choice == 'admin_broadcast':
       await query.message.edit_text("Please enter the message to broadcast to all users.\nTo cancel, send /cancel.")
       return TYPING_BROADCAST

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
   user_id = update.effective_user.id if isinstance(update, Update) else update.from_user.id
   if user_id != ADMIN_ID: return
   users = load_json_data(USERS_FILE, set)
   await context.bot.send_message(chat_id=user_id, text=f"📊 Bot Statistics\n\n👤 Total Unique Users: {len(users)}")

async def check_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
   if update.effective_user.id != ADMIN_ID: return
   try:
       user_id_to_check = int(context.args[0])
       user_id_str = str(user_id_to_check)
       counts = load_json_data(COUNTS_FILE)
       eligible_users = load_json_data(ELIGIBLE_USERS_FILE, set)
       leaderboard = load_json_data(LEADERBOARD_FILE)
       current_count = counts.get(user_id_str, 0)
       is_eligible = user_id_to_check in eligible_users
       total_adds = leaderboard.get(user_id_str, {}).get('count', 0)
       text = (f"<b>User Status Check:</b> <code>{user_id_to_check}</code>\n\n"
               f"<b>Current Progress:</b> {current_count}/{MEMBERS_TO_ADD}\n"
               f"<b>Total Adds (Leaderboard):</b> {total_adds}\n"
               f"<b>Eligible for /create:</b> {is_eligible}")
       await update.message.reply_html(text)
   except (IndexError, ValueError):
       await update.message.reply_text("Usage: /check_user <user_id>")

async def handle_broadcast_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
   context.user_data['broadcast_message'] = update.message.text
   users = load_json_data(USERS_FILE, set)
   await update.message.reply_html(f"<u>Message Preview</u>:\n\n{update.message.text}\n\nThis will be sent to <b>{len(users)}</b> users. Are you sure?\nReply with <b>yes</b> to confirm.")
   return CONFIRM_BROADCAST

async def handle_broadcast_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
   if update.message.text.lower() != 'yes':
       await update.message.reply_text("Broadcast cancelled.")
   else:
       await update.message.reply_text("Broadcasting... This may take a moment.")
       message_text = context.user_data.get('broadcast_message')
       users = load_json_data(USERS_FILE, set)
       success, fail = 0, 0
       for user_id in users:
           try:
               await context.bot.send_message(chat_id=user_id, text=message_text)
               success += 1
           except Exception: fail += 1
           await asyncio.sleep(0.1)
       await update.message.reply_text(f"✅ Sent: {success}\n❌ Failed: {fail}")
   context.user_data.clear()
   return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
   message = update.callback_query.message if update.callback_query else update.message
   await message.reply_text('Action cancelled.')
   context.user_data.clear()
   return ConversationHandler.END

# --- Bot Setup and Webhook Handling ---
async def setup_bot():
   application = Application.builder().token(TELEGRAM_TOKEN).build()
   
   create_conv = ConversationHandler(
       entry_points=[CommandHandler('create', create_command, filters=filters.ChatType.PRIVATE)],
       states={
           CHOOSING_STYLE: [CallbackQueryHandler(handle_page_and_style_choice)],
           TYPING_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_name_and_create)],
       },
       fallbacks=[CommandHandler('cancel', cancel)],
   )
   broadcast_conv = ConversationHandler(
       entry_points=[CallbackQueryHandler(pattern='^admin_broadcast$', callback=admin_callback_handler)],
       states={
           TYPING_BROADCAST: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_broadcast_message)],
           CONFIRM_BROADCAST: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_broadcast_confirmation)],
       },
       fallbacks=[CommandHandler('cancel', cancel)],
   )
   
   application.add_handler(create_conv)
   application.add_handler(broadcast_conv)
   application.add_handler(CommandHandler("start", start))
   application.add_handler(CommandHandler("ping", ping_command))
   application.add_handler(CommandHandler("myprogress", myprogress_command))
   application.add_handler(CommandHandler("top", top_command))
   application.add_handler(CommandHandler("admin", admin_command))
   application.add_handler(CommandHandler("check_user", check_user_command))
   application.add_handler(CallbackQueryHandler(pattern='^admin_stats$', callback=admin_callback_handler))
   application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, handle_new_members))
   
   return application

# --- Flask Routes for Vercel ---
@app.route('/api', methods=['POST'])
async def webhook():
   try:
       application = await setup_bot()
       update_data = request.get_json(force=True)
       update = Update.de_json(update_data, application.bot)
       async with application:
           await application.process_update(update)
       return jsonify({"status": "ok"})
   except Exception as e:
       error_message = f"Webhook Error:\n<pre>{traceback.format_exc()}</pre>"
       logger.error(error_message)
       try:
           bot = (await setup_bot()).bot
           await bot.send_message(chat_id=ADMIN_ID, text=error_message, parse_mode='HTML')
       except Exception as e2:
           logger.error(f"Failed to send error message to admin: {e2}")
       return jsonify({"status": "error"}), 500

@app.route('/set_webhook', methods=['GET'])
async def set_webhook():
   if not VERCEL_URL: return "Error: VERCEL_URL environment variable not set.", 500
   application = await setup_bot()
   webhook_url = f"https://{VERCEL_URL}/api"
   success = await application.bot.set_webhook(url=webhook_url)
   if success:
       return f"Webhook set successfully to {webhook_url}", 200
   else:
       return "Webhook setup failed.", 500

@app.route('/')
def health_check():
   return "Bot is running.", 200

