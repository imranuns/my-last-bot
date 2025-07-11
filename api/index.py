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

# --- File Paths ---
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
       keyboard.append([InlineKeyboardButton("🎲 በእድል ምረጥልኝ", callback_data='random_style'), InlineKeyboardButton("ቀጣይ ገጽ ➡️", callback_data='page_2')])
   else:
       keyboard = [[InlineKeyboardButton(f"Style {i}", callback_data=f'style{i}') for i in range(5, 7)], [InlineKeyboardButton(f"Style {i}", callback_data=f'style{i}') for i in range(7, 9)]]
       keyboard.append([InlineKeyboardButton("⬅️ ተመለስ", callback_data='page_1')])
   return InlineKeyboardMarkup(keyboard)

# --- Bot Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
   add_user(update.effective_user.id)
   await update.message.reply_html(
       "👋 <b>እንኳን ደህና መጡ!</b>\n\nይህ ቦት ለቡድናችን አባላትን በመጨመር አስገራሚ የመገለጫ ምስሎችን እንዲሰሩ ያስችሎታል።\n\n"
       f"ለመጀመር <b>{MEMBERS_TO_ADD} አባላትን</b> ወደ ቡድኑ ይጨምሩና <b>/create</b> የሚለውን ትዕዛዝ በግል ይላኩልኝ።\n\n"
       "የእርስዎን እድገት ለማየት <b>/myprogress</b> ብለው ይጻፉ።"
   )

async def ping_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
   """A simple command to check if the bot is alive."""
   await update.message.reply_text("Pong!")

# ... (All other handlers like handle_new_members, myprogress_command, etc., are the same)
# For brevity, I am omitting the full code for them, but you should have them in your file.
# The following is just a placeholder to show where they should be.
async def handle_new_members(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
   # Your full handle_new_members logic here
   pass
async def myprogress_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
   # Your full myprogress_command logic here
   pass
async def top_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
   # Your full top_command logic here
   pass
async def create_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
   # Your full create_command logic here
   return CHOOSING_STYLE
async def handle_page_and_style_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
   # Your full handle_page_and_style_choice logic here
   return TYPING_NAME
async def handle_name_and_create(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
   # Your full handle_name_and_create logic here
   return ConversationHandler.END
async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
   # Your full admin_command logic here
   pass
async def admin_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
   # Your full admin_callback_handler logic here
   return TYPING_BROADCAST
async def check_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
   # Your full check_user_command logic here
   pass
async def handle_broadcast_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
   # Your full handle_broadcast_message logic here
   return CONFIRM_BROADCAST
async def handle_broadcast_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
   # Your full handle_broadcast_confirmation logic here
   return ConversationHandler.END
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
   # Your full cancel logic here
   return ConversationHandler.END


# --- Bot Setup and Webhook Handling ---
async def setup_bot():
   """Initializes the bot application and sets up all handlers."""
   application = Application.builder().token(TELEGRAM_TOKEN).build()
   
   # Add all your handlers here
   application.add_handler(CommandHandler("start", start))
   application.add_handler(CommandHandler("ping", ping_command)) # New test command
   # ... Add all other handlers (create_conv, broadcast_conv, etc.)
   
   return application

# --- Flask Routes for Vercel ---
@app.route('/api', methods=['POST'])
async def webhook():
   """Webhook endpoint to process updates from Telegram."""
   try:
       application = await setup_bot()
       update_data = request.get_json(force=True)
       update = Update.de_json(update_data, application.bot)
       
       # This is the most critical part. We run the update processing in an async context.
       async with application:
           await application.process_update(update)
           
       return jsonify({"status": "ok"})
   except Exception as e:
       # If any error happens, log it and send it to the admin
       error_message = f"An error occurred in the main webhook handler:\n\n<pre>{traceback.format_exc()}</pre>"
       logger.error(error_message)
       try:
           # Try to build a temporary bot instance just to send the error message
           bot = (await setup_bot()).bot
           await bot.send_message(chat_id=ADMIN_ID, text=error_message, parse_mode='HTML')
       except Exception as e2:
           logger.error(f"Failed to send error message to admin: {e2}")
           
       return jsonify({"status": "error"}), 500

@app.route('/set_webhook', methods=['GET'])
async def set_webhook():
   """Sets the webhook URL with Telegram."""
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

