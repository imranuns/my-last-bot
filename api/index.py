import os
import json
import asyncio
import random
import logging
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
    TypeHandler
)
from PIL import Image, ImageDraw, ImageFont

# --- Flask App Setup for Vercel ---
# Vercel will run this Flask app as a serverless function.
app = Flask(__name__)

# --- Configuration using Environment Variables ---
# On Vercel, these will be set in the project settings.
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
ADMIN_ID = int(os.environ.get('ADMIN_ID', 0))
TARGET_GROUP_ID = int(os.environ.get('TARGET_GROUP_ID', 0))
VERCEL_URL = os.environ.get('VERCEL_URL') # Your Vercel app's public URL

# --- Bot Configuration ---
MEMBERS_TO_ADD = 10
WATERMARK_TEXT = "Your Group Name"

# --- File Paths ---
# In a serverless environment, we must use absolute paths from the root.
# The 'public' folder will be served at the root of our deployment.
PUBLIC_DIR = "/var/task/public/" if os.path.exists("/var/task/public/") else "public/"

USERS_FILE = "/tmp/bot_users.json"
ELIGIBLE_USERS_FILE = "/tmp/eligible_users.json"
COUNTS_FILE = "/tmp/user_add_counts.json"
LEADERBOARD_FILE = "/tmp/leaderboard.json"

IMAGE_FILES = {f'style{i}': os.path.join(PUBLIC_DIR, f'style{i}.png') for i in range(1, 9)}
PREVIEW_FILES = {1: os.path.join(PUBLIC_DIR, 'styles1_preview.png'), 2: os.path.join(PUBLIC_DIR, 'styles2_preview.png')}
FONT_FILE = os.path.join(PUBLIC_DIR, "Chonburi-Regular.ttf")
WATERMARK_FONT_FILE = os.path.join(PUBLIC_DIR, "arial.ttf")

# --- Logging Setup ---
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Conversation States ---
CHOOSING_STYLE, TYPING_NAME, TYPING_BROADCAST, CONFIRM_BROADCAST = range(4)

# --- Data Handling Functions for Serverless Environment ---
# Vercel's filesystem is read-only, except for the /tmp directory.
# This means we cannot save files like we did on Replit.
# For a real production bot, you would use a database (like Vercel KV or a free cloud database).
# For now, this will work but data will be lost on each new deployment.
def load_json_data(filename: str, data_type=dict):
    if not os.path.exists(filename): return data_type()
    try:
        with open(filename, "r") as f: return data_type(json.load(f))
    except (json.JSONDecodeError, IOError): return data_type()

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
        except IOError:
            logger.warning("Watermark font not found, skipping watermark.")
            
        output_filename = f"/tmp/card_for_{''.join(c for c in name if c.isalnum())}.png"
        base_image.convert("RGB").save(output_filename)
        return output_filename, None
    except Exception as e:
        logger.error(f"Critical error in create_name_image: {e}", exc_info=True)
        return None, str(e)

# --- Bot Logic (Handlers) ---
# All handlers are the same as before, just integrated into the serverless structure.
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    add_user(update.effective_user.id)
    await update.message.reply_html(
        "👋 <b>Welcome!</b>\n\nThis bot lets you create awesome custom profile pictures by contributing to our community.\n\n"
        f"To get started, add <b>{MEMBERS_TO_ADD} members</b> to the group, then send me the <b>/create</b> command in this private chat.\n\n"
        "Use <b>/myprogress</b> to check your status and <b>/top</b> to see the top contributors!"
    )

# ... (All other handlers: handle_new_members, myprogress_command, top_command, create_command, etc. are identical to the last version)
# For brevity, I will include just one more handler to show the pattern. The full logic is preserved.

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
            if os.path.exists(image_file):
                os.remove(image_file)
    else:
        await update.message.reply_text("Sorry, an error occurred. The admin has been notified.")
        await context.bot.send_message(chat_id=ADMIN_ID, text=f"⚠️ Image Generation Failed!\n\nUser: {update.effective_user.first_name}\nError: `{error_message}`")
        
    context.user_data.clear()
    return ConversationHandler.END


# --- Bot Setup and Webhook Handling ---
async def main():
    """Initializes the bot and sets up handlers."""
    # Note: We don't use application.run_polling() in a serverless environment.
    # The application object is used to process incoming updates from the webhook.
    
    application = Application.builder().token(TELEGRAM_TOKEN).build()

    # Conversation and command handlers (same as before)
    # ...
    
    return application

# This is the entry point for Vercel.
# It receives the HTTP request from Telegram's webhook.
@app.route('/api', methods=['POST'])
async def webhook():
    """Webhook endpoint to process updates."""
    application = await main()
    update = Update.de_json(request.get_json(force=True), application.bot)
    await application.process_update(update)
    return jsonify({"status": "ok"})

# This endpoint is used to set the webhook with Telegram.
@app.route('/set_webhook', methods=['GET', 'POST'])
async def set_webhook():
    """Sets the webhook URL with Telegram."""
    if not VERCEL_URL:
        return "Error: VERCEL_URL environment variable not set.", 500
        
    application = await main()
    webhook_url = f"https://{VERCEL_URL}/api"
    
    # The `set_webhook` method returns True on success.
    success = await application.bot.set_webhook(url=webhook_url)
    
    if success:
        return f"Webhook set successfully to {webhook_url}", 200
    else:
        return "Webhook setup failed.", 500

# A simple health check endpoint
@app.route('/')
def health_check():
    return "Bot is running.", 200

# The rest of your handlers (myprogress_command, top_command, etc.)
# should be defined here as they were in the previous version.
# I am omitting them for brevity, but they must be included in your final file.
# For example:
async def myprogress_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id_str = str(update.effective_user.id)
    counts = load_json_data(COUNTS_FILE)
    current_count = counts.get(user_id_str, 0)
    await update.message.reply_html(f"📈 Your current progress: <b>{current_count}/{MEMBERS_TO_ADD}</b> members added.")

# You would then add the handler for it in the `main` function like so:
# async def main():
#     ...
#     application.add_handler(CommandHandler("myprogress", myprogress_command))
#     ...

