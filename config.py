from dotenv import load_dotenv
import os
from pathlib import Path

# .env faylini yuklash
load_dotenv()

API_TOKEN = os.getenv("API_TOKEN")
TELETHON_API_ID = int(os.getenv("TELETHON_API_ID"))
TELETHON_API_HASH = os.getenv("TELETHON_API_HASH")
BOT_SESSION_STRING = os.getenv("BOT_SESSION_STRING")
ADMIN_ID = int(os.getenv("ADMIN_ID"))


# Asosiy sozlamalar
I18N_DOMAIN = 'messages'
LOCALES_DIR = Path(__file__).parent / 'locales'
DEFAULT_LANGUAGE = 'uz'

# Mavjud tillar
LANGUAGES = {
    'uz': "O'zbek 🇺🇿",
    'ru': "Русский 🇷🇺"
}
