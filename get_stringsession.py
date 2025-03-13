from telethon.sync import TelegramClient
from telethon.sessions import StringSession
from config import TELETHON_API_ID, TELETHON_API_HASH


with TelegramClient(StringSession(), TELETHON_API_ID, TELETHON_API_HASH) as client:
    print("Sizning session string: ", client.session.save())
