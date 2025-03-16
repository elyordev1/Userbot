from aiogram import Bot, Dispatcher, types
from aiogram.utils.exceptions import TelegramAPIError
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, BotCommand, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton
from telethon.sync import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError, FloodWaitError, UserDeactivatedBanError
from translations import i18n
from telethon.errors import FloodWaitError, UserDeactivatedBanError
from config import API_TOKEN, TELETHON_API_ID, TELETHON_API_HASH, BOT_SESSION_STRING, ADMIN_ID, LANGUAGES
from dp_helpers import get_daily_users, get_db_connection, get_monthly_users, get_total_users
from aiogram.dispatcher import Dispatcher
import logging
import asyncio
import pytz
import re
import sqlite3




# Faol Telethon clientlarini saqlash uchun dictionary
active_clients = {}

# Logger sozlamalari: xatoliklar konsolga yoki log fayliga yoziladi.
logging.basicConfig(level=logging.ERROR, format='%(asctime)s - %(levelname)s - %(message)s')

# Aiogram bot va dispatcher
bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)


# Foydalanuvchilar uchun ma'lumotlar bazasi(SQLite)
with get_db_connection() as db:
    cursor = db.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER UNIQUE,
        phone_number TEXT,
        session_string TEXT,
        language TEXT DEFAULT 'uz',
        registered_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)
db.commit()

# Xabarlar uchun ma'lumotlar bazasi
cursor.execute("""
CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    message_id INTEGER,
    chat_id INTEGER,
    send_time TEXT
)
""")
db.commit()

temp_data = {}  # Vaqtinchalik ma'lumotlarni saqlash uchun
searching_users = {}  # Qidiruv jarayonida bo‘lgan foydalanuvchilar

# Tashqi vaqt zonasi va kechikish vaqti
uzbekistan_tz = pytz.timezone('Asia/Tashkent')
send_delay = 1.5

user_sessions = {}

# Telethon bot uchun bitta session yaratamiz
bot_client = TelegramClient(StringSession(BOT_SESSION_STRING), TELETHON_API_ID, TELETHON_API_HASH)

def get_phone_button(language):
    text = "📲 Telefon raqamni yuborish" if language == "uz" else "📲 Отправить номер"
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    button = KeyboardButton(text, request_contact=True)
    keyboard.add(button)
    return keyboard


def add_language_column():
    try:
        with get_db_connection() as db:
            cursor = db.cursor()
            cursor.execute("""
                ALTER TABLE users 
                ADD COLUMN language TEXT DEFAULT 'uz'
            """)
            db.commit()
    except sqlite3.OperationalError as e:
        if "duplicate column name" not in str(e).lower():
            raise e


#==========================================language=========================================#
# Inline tugmalar yordamida til tanlash uchun keyboard
def get_language_inline_keyboard():
    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        InlineKeyboardButton(text="🇺🇿 O‘zbek", callback_data="set_lang:uz"),
        InlineKeyboardButton(text="🇷🇺 Русский", callback_data="set_lang:ru")
    )
    return keyboard

# Ma'lumotlar bazasiga til ustunini qo'shadigan funksiya (agar allaqachon mavjud bo'lmasa)
def setup_database():
    with get_db_connection() as db:
        cursor = db.cursor()
        cursor.execute("""
            ALTER TABLE users 
            ADD COLUMN language TEXT DEFAULT 'uz'
        """)
        db.commit()

# Foydalanuvchi tilini olish
def get_user_language(user_id):
    with get_db_connection() as db:
        cursor = db.cursor()
        cursor.execute("SELECT language FROM users WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        return result[0] if result else 'uz'

# Til o'zgartirish handleri (komanda orqali)
@dp.message_handler(commands=['language', 'lang'])
async def cmd_language(message: types.Message):
    # Foydalanuvchining hozirgi tilini olish
    current_lang = get_user_language(message.from_user.id)
    # i18n.get_text() yordamida mos xabarni olamiz (tilga mos variant)
    text = i18n.get_text("choose_language", current_lang)
    # Inline keyboard bilan til tanlashni yuboramiz
    await message.answer(text, reply_markup=get_language_inline_keyboard())

# Inline callback query handler: tugma bosilganda ishga tushadi

@dp.callback_query_handler(lambda c: c.data.startswith('set_lang:'))
async def process_language_choice(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    selected_lang = callback_query.data.split(":", 1)[1]
    temp_data[user_id] = {"state": "awaiting_phone", "language": selected_lang}

    with get_db_connection() as db:
        cursor = db.cursor()
        cursor.execute(
            "INSERT INTO users (user_id, language) VALUES (?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET language = ?",
            (user_id, selected_lang, selected_lang)
        )
        db.commit()

    # Inline keyboard tugmalarini o‘chirish
    await bot.delete_message(chat_id=user_id, message_id=callback_query.message.message_id)
    
    text = i18n.get_text("language_changed", selected_lang)


    # Telefon raqamini so'rash
    phone_keyboard = get_phone_button(selected_lang)
    text = i18n.get_text("ask_phone", selected_lang)
    await bot.send_message(user_id, text, reply_markup=phone_keyboard)

#==========================================================================================#



# =============================================================================
# Yordamchi FUNKSIYALAR
# =============================================================================
def to_cyrillic(text):
    """ Lotin harflarini kirillchaga o‘zgartiradi."""
    
    conversion = {
        'a': 'а', 'b': 'б', 'd': 'д', 'e': 'е', 'f': 'ф', 'g': 'г', 'h': 'ҳ',
        'i': 'и', 'j': 'ж', 'k': 'к', 'l': 'л', 'm': 'м', 'n': 'н', 'o': 'о',
        'p': 'п', 'q': 'қ', 'r': 'р', 's': 'с', 't': 'т', 'u': 'у', 'v': 'в',
        'x': 'х', 'y': 'й', 'z': 'з', "'": 'ъ', 'ch': 'ч', 'sh': 'ш',
        'ya': 'я', 'yu': 'ю', 'yo': 'ё'
    }
    result = ''
    i = 0
    while i < len(text):
        if i < len(text) - 1 and text[i:i+2].lower() in conversion:
            result += conversion[text[i:i+2].lower()]
            i += 2
        elif text[i].lower() in conversion:
            result += conversion[text[i].lower()]
            i += 1
        else:
            result += text[i]
            i += 1
    return result
# END: to_cyrillic

def get_user_session(user_id):
    """Foydalanuvchi sessiyasini bazadan olish"""
    with get_db_connection() as db:
        cursor = db.cursor()
        cursor.execute("SELECT session_string FROM users WHERE user_id = ?", (user_id,))
        return cursor.fetchone()
#END: get_user_sesion

async def safe_send_message(chat_id, text):
    """
    FUNKSIYA: safe_send_message
    Vazifasi: Xabar yuborishda xatolik yuz bersa, xatolik tafsilotlarini logga yozib, foydalanuvchiga umumiy yoki batafsil xabar yuboradi.
    
    Parametrlar:
      - chat_id: Xabar yuboriladigan chat ID.
      - text: Yuboriladigan xabar.
      - show_error_details (bool): Agar True bo'lsa, foydalanuvchiga texnik xatolik tafsilotlari ham yuboriladi.
      - detailed_error_message (str): Agar belgilansa, xatolik yuz berganda shu xabar yuboriladi.
      - reply_markup: Qo'shimcha tugmalar yoki markup (agar kerak bo'lsa).
    """
    try:
        await bot.send_message(chat_id, text)
    except TelegramAPIError as e:
        # Xatolik tafsilotini logga yozamiz
        logging.error(f"Xabar yuborishda xatolik: {e}")
        # Foydalanuvchiga umumiy xabar yuboramiz
        try:
            await bot.send_message(chat_id, "Xabar yuborishda xatolik yuz berdi. Iltimos, keyinroq urinib ko'ring.")
        except Exception:
            pass
# END: safe_send_message


async def get_telethon_client(user_id):
    """Telethon clientni olish: agar faol klient mavjud bo'lsa, uni qaytaramiz,
       aks holda, bazadan session_string olib, connect() orqali tekshiramiz."""
    if user_id in active_clients:
        return active_clients[user_id]

    with get_db_connection() as db:
        cursor = db.cursor()
        cursor.execute("SELECT session_string FROM users WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()

    if row:
        session_string = row[0]
        client = TelegramClient(StringSession(session_string), TELETHON_API_ID, TELETHON_API_HASH)

        # interaktiv rejimga tushmaslik uchun start() o‘rniga connect() dan foydalanamiz
        await client.connect()

        # endi tekshiramiz, agar foydalanuvchi authorized bo‘lmasa, None qaytaramiz
        if not await client.is_user_authorized():
            await client.disconnect()
            return None

        # sessiya yaroqli bo‘lsa, clientni saqlaymiz
        active_clients[user_id] = client
        return client

    # Umuman session_string topilmadi
    return None


def get_user_name(user_id):
    cursor.execute("SELECT name FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if row:
        return row[0]
    return "Foydalanuvchi"
# END: get_user_name

async def delete_user_account(user_id, message=None):
   
    # Ma’lumotlar bazasidan o'chirish
    cursor.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
    db.commit()

    # Faol Telethon klientini topamiz va chiqamiz
    client = active_clients.get(user_id)
    if client:
        try:
            await client.log_out()      # Telegram akkauntidan chiqish
            await client.disconnect()   # Klientni to'liq uzish
        except Exception as e:
            print(f"Foydalanuvchini chiqish paytida xatolik: {e}")
        finally:
            active_clients.pop(user_id, None)


    # Qidiruv ro'yxatidan va vaqtinchalik ma'lumotlardan tozalaymiz
    searching_users.pop(user_id, None)  # Agar user_id mavjud bo‘lsa, olib tashlaydi, bo‘lmasa hech narsa qilmaydi

    temp_data.pop(user_id, None)

    if message:
        user_language = get_user_language(message.from_user.id)  
        # text = i18n.get_text("deleted_successfully", user_language)
        text = "Hisobingiz o‘chirildi. Bot xizmatlarini qayta ishlatish uchun /start bosing." if temp_data[user_id]["language"] == "uz" else "Ваш аккаунт удален. Чтобы снова использовать сервисы бота, нажмите /start."
        await message.reply(text, reply_markup=types.ReplyKeyboardRemove())
# END: delete_user_account


async def start_bot_client():
    """
    FUNKSIYA: start_bot_client
    Vazifasi: Bot uchun Telethon clientini ishga tushiradi.
    
    Bu funksiya yagona bot_client obyekti uchun start() metodini chaqiradi,
    shunda Telethon orqali Telegram bilan aloqani o‘rnatadi.
    
    Qaytargan qiymat: Hech narsa qaytarmaydi, faqat async tarzda Telegram clientini ishga tushiradi.
    """
    await bot_client.start()
# END: start_bot_client


# 🔹 Foydalanuvchini akkauntidan chiqib ketgan yoki yo‘qligini tekshirish
async def check_user_session_valid(user_id: int) -> bool:
    """
    Foydalanuvchi sessiyasi haqiqiy (botdan chiqmagan) bo'lsa, True qaytaradi.
    Agar sessiya tugagan yoki foydalanuvchi bloklangan bo'lsa, False qaytaradi.
    """
    client = await get_telethon_client(user_id)  # Sizda mavjud funksiya
    if not client:
        # Umuman ro'yxatdan o'tmagan yoki session_string yo'q
        return False
    
    try:
        me = await client.get_me()
        if not me:
            # Foydalanuvchi session_string buzilgan yoki o'chgan bo'lishi mumkin
            return False
    except UserDeactivatedBanError:
        # Telegram tomonidan bloklangan yoki deaktivatsiya qilingan
        return False
    except Exception as e:
        # Kutilmagan xatoliklar
        print(f"check_user_session_valid xatosi: {e}")
        return False

    # Agar yuqoridagi xatoliklar bo'lmasa, sessiya ishlayapti
    return True


# 🔹 Bot ishga tushganda tekshirishni boshlash
async def on_startup(_):
    asyncio.create_task(check_user_session_valid())
#END: on_startup


# =============================================================================
 #Foydalanuvchi ro'yxatdn o'tish qismi
# =============================================================================

@dp.message_handler(content_types=types.ContentType.CONTACT)
async def process_phone_number(message: types.Message):
    if message.contact and message.contact.user_id == message.from_user.id:
        user_id = message.from_user.id
        phone_number = message.contact.phone_number

        # Telefon raqamni bazaga saqlash
        with get_db_connection() as db:
            cursor = db.cursor()
            cursor.execute(
                "UPDATE users SET phone_number = ? WHERE user_id = ?",
                (phone_number, user_id)
            )
            db.commit()

        # Telethon klientini yaratamiz
        client = TelegramClient(StringSession(), TELETHON_API_ID, TELETHON_API_HASH)

        try:
            await client.connect()
            if not client.is_connected():
                print("❌ Telethon client ulana olmadi!")
                await message.answer("❌ Bot Telegramga ulanganiga ishonch hosil qiling!")
                return
            if not await client.is_user_authorized():
                # print("🚀  kod yuboriladi.")
                await client.send_code_request(phone_number)
                # print(f"✅ Kod yuborildi: {sent}")

                temp_data[user_id] = {
                    "state": "awaiting_code",
                    "client": client,
                    "phone_number": phone_number,
                    "language": get_user_language(user_id)
                }

                user_language = get_user_language(user_id)
                text = i18n.get_text("write_vercode", user_language)
                await message.answer(text)
            else:
                # print("⚠️ Foydalanuvchi allaqachon tizimga kirgan!")
                await message.answer("⚠️ Siz allaqachon tizimga kirdingiz.")
        except Exception as e:
            logging.error(f"❌ Xatolik kod yuborishda: {e}")
            # print(f"❌ Xatolik: {e}")
            await message.answer("❌ Kod yuborishda muammo yuz berdi. Iltimos, qayta urinib ko‘ring.")

    else:
        await message.answer("❗ Iltimos, pastdagi tugmadan foydalanib raqamingizni yuboring.", reply_markup=get_phone_button("uz"))  



def save_user_session(user_id, phone_number, session_string):
    with get_db_connection() as db:
        cursor = db.cursor()
        cursor.execute("""
            INSERT INTO users (user_id, phone_number, session_string)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET session_string = excluded.session_string
        """, (user_id, phone_number, session_string))
        db.commit()


@dp.message_handler(lambda message: message.from_user.id in temp_data and temp_data[message.from_user.id].get("state") == "awaiting_code")
async def handle_code(message: types.Message):
    user_id = message.from_user.id
    code = message.text
    client = temp_data[user_id]["client"]
    phone_number = temp_data[user_id]["phone_number"]

    try:
        await client.sign_in(phone_number, code.replace('.', ''))
        save_user_session(user_id, phone_number, client.session.save())
        text = "✅ Ro‘yxatdan o‘tish muvaffaqiyatli yakunlandi!" if temp_data[user_id]["language"] == "uz" else "✅ Регистрация успешно завершена!"
        await message.answer(text, reply_markup=ReplyKeyboardRemove())
        del temp_data[user_id]
    except SessionPasswordNeededError:
        temp_data[user_id] = {  
            "state": "awaiting_password",
            "client": client,
            "phone_number": phone_number,
            "language": get_user_language(user_id)
        }
        text = "🔒 Ikki bosqichli parol talab qilinmoqda. Iltimos, parolni kiriting:" if temp_data[user_id]["language"] == "uz" else "🔒 Требуется двухэтапный пароль. Пожалуйста, введите пароль:"
        await message.answer(text)
    except Exception as e:
        logging.error(f"Xatolik: {e}")
        await message.answer("Kod noto‘g‘ri, iltimos qayta urinib ko‘ring.")


@dp.message_handler(lambda message: message.from_user.id in temp_data and temp_data[message.from_user.id].get("state") == "awaiting_password")
async def handle_password(message: types.Message):
    user_id = message.from_user.id
    password = message.text
    client = temp_data[user_id]["client"]
    phone_number = temp_data[user_id]["phone_number"]
    
    try:
        await client.sign_in(password=password)
        save_user_session(user_id, phone_number, client.session.save())
        text = "✅ Ro‘yxatdan o‘tish muvaffaqiyatli yakunlandi!" if temp_data[user_id]["language"] == "uz" else "✅ Регистрация успешно завершена!"
        await message.answer(text, reply_markup=ReplyKeyboardRemove())
        del temp_data[user_id]
    except Exception as e:
        logging.error(f"Xatolik: {e}")
        await message.answer("Parol noto‘g‘ri, iltimos qayta urinib ko‘ring.")
#===================================register========================================#


# =============================================================================
  #Funksiyalar
# =============================================================================
async def set_commands(bot: Bot):
    commands = [
        BotCommand(command="start", description="Botni ishga tushirish"),
        BotCommand(command="lang", description="Tilni o'zgartirish"),
        BotCommand(command="help", description="Yordam"),
        BotCommand(command="get", description="Guruhlar ro'yxatini ko'rish"),
        BotCommand(command="sendmessage", description="Xabarni saqlash"),
        BotCommand(command="show", description="Saqlangan xabarni ko'rish"),
        BotCommand(command="delete", description="Saqlangan xabarni o'chirish"),
        BotCommand(command="search", description="Guruhlardan qidirish"),
        BotCommand(command="stop", description="Hisobni o'chirish"),
        BotCommand(command="admin", description="Admin bilan aloqa"),
    ]
    await bot.set_my_commands(commands)
#===================================commands========================================#

@dp.message_handler(commands=['get'])
async def get_groups(message: types.Message):
    user_id = message.from_user.id

    # Sessiyani tekshirish
    if not await check_user_session_valid(user_id):
        await message.answer("Sizning sessiyangiz tugagan yoki bloklangansiz. Qayta ro‘yxatdan o‘ting.")
        return

    client = await get_telethon_client(user_id)
    if client:
        dialogs = await client.get_dialogs()
        groups = [dialog for dialog in dialogs if dialog.is_group]
        if groups:
            user_language = get_user_language(message.from_user.id)  
            text = i18n.get_text("followed_groups", user_language)
            response = text
            for group in groups:
                response += f"- {group.title} (ID: `{group.id}`)\n"
            await message.answer(response)
        else:
            user_language = get_user_language(message.from_user.id)  
            text = i18n.get_text("no_group", user_language)
            await message.reply(text)
    else:
        user_language = get_user_language(message.from_user.id)  
        text = i18n.get_text("not_register", user_language)
        await message.answer(text)
#END: /get

@dp.message_handler(commands=['sendmessage'])
async def sendmessage(message: types.Message):
    user_id = message.from_user.id

    # Sessiyani tekshirish
    if not await check_user_session_valid(user_id):
        await message.answer("Sizning sessiyangiz tugagan yoki bloklangansiz. Qayta ro‘yxatdan o‘ting.")
        return

    if not message.reply_to_message:
        user_language = get_user_language(message.from_user.id)  
        text = i18n.get_text("do_reply", user_language)
        await message.reply(text)
        return

    client = await get_telethon_client(user_id)
    
    if client:
        reply_message = message.reply_to_message
        with get_db_connection() as db:
            cursor = db.cursor()
            cursor.execute(
                "INSERT INTO posts (user_id, message_id, chat_id) VALUES (?, ?, ?)",
                (user_id, reply_message.message_id, message.chat.id)
            )
            db.commit()
        user_language = get_user_language(message.from_user.id)  
        text = i18n.get_text("saved_successfully", user_language)
        await message.answer(text)

        # Xabar yuborish jarayoni
        dialogs = await client.get_dialogs()
        groups = [dialog for dialog in dialogs if dialog.is_group]
        
        if groups:
            user_language = get_user_language(message.from_user.id)  
            text = i18n.get_text("started_sending", user_language)
            progress_message = await message.answer(text)
            for idx, group in enumerate(groups, start=1):
                try:
                    await client.send_message(group.id, reply_message.text)  # Faqat matn yuboriladi
                    progress_text = i18n.get_text("sending_status", user_language).format(
                        idx=idx,
                        total_groups=len(groups),
                        group_title=group.title
                    )

                    await progress_message.edit_text(progress_text)
                    await asyncio.sleep(send_delay)
                except FloodWaitError as e:
                    flood_text = i18n.get_text("flood_wait", user_language).format(seconds=e.seconds)
                    await message.answer(flood_text)
                    await asyncio.sleep(e.seconds)
                except Exception as e:
                    logging.error(f"Xatolik {group.title} uchun: {e}")
                    error_text = i18n.get_text("sending_error", user_language).format(group_title=group.title)
                    await message.answer(error_text)

            # Xabar tugagach, uni o‘chirish
            try:
                await bot.delete_message(message.chat.id, progress_message.message_id)
            except Exception as e:
                logging.error(f"Xabarni o‘chirishda xatolik: {e}")
    else:
        user_language = get_user_language(message.from_user.id)  
        text = i18n.get_text("not_register", user_language)
        await message.reply(text)   
#END: /sendmessage

@dp.message_handler(commands=['show'])
async def show(message: types.Message):
    user_id = message.from_user.id

    # Sessiyani tekshirish
    if not await check_user_session_valid(user_id):
        await message.answer("Sizning sessiyangiz tugagan yoki bloklangansiz. Qayta ro‘yxatdan o‘ting.")
        return
    
    cursor.execute("SELECT message_id, chat_id FROM posts WHERE user_id = ? ORDER BY id DESC LIMIT 1", (user_id,))
    post = cursor.fetchone()
    if post:
        text = i18n.get_text(
            "saved_message",
            user_language,
            message_id=post[0],
            group_id=post[1]
        )
        await message.reply(text)
    else:
        user_language = get_user_language(message.from_user.id)  
        text = i18n.get_text("netu_msg", user_language)
        await message.answer(text)
#END: /show

@dp.message_handler(commands=['delete'])
async def delete_post(message: types.Message):
    user_id = message.from_user.id

    # Sessiyani tekshirish
    if not await check_user_session_valid(user_id):
        await message.answer("Sizning sessiyangiz tugagan yoki bloklangansiz. Qayta ro‘yxatdan o‘ting.")
        return

    with get_db_connection() as db:
         cursor = db.cursor()
         cursor.execute(
             "DELETE FROM posts WHERE user_id = ? AND id = (SELECT MAX(id) FROM posts WHERE user_id = ?)",
             (user_id, user_id)
         )
         db.commit()
    user_language = get_user_language(message.from_user.id)  
    text = i18n.get_text("deleted_msg", user_language)
    await message.answer(text)
#END: /delete

#===========================================statistika==============================================#
# Statistika olish uchun yangi komanda
@dp.message_handler(commands=['stats'])
async def get_statistics(message: types.Message):
    user_id = message.from_user.id
    if user_id != ADMIN_ID:
        await message.reply("⛔ Bu buyruq faqat admin uchun.")
        return

    total_users = get_total_users()
    monthly_users = get_monthly_users()
    daily_users = get_daily_users()
    
    stats_text = (
        f"📊 **Statistika:**\n\n"
        f"👥 Umumiy foydalanuvchilar: {total_users}\n"
        f"📅 Shu oyda ro'yxatdan o'tganlar: {monthly_users}\n"
        f"📆 Bugun ro'yxatdan o'tganlar: {daily_users}\n"
    )
    
    await message.answer(stats_text)
#END: statistika

@dp.message_handler(commands=['help'])
async def help_command(message: types.Message):
    user_language = get_user_language(message.from_user.id)  
    text = i18n.get_text("help_message", user_language)
    await message.answer(
        text,
        parse_mode="Markdown"
    )
#END: /help
    
@dp.message_handler(commands=['admin'])
async def admin_command(message: types.Message):
    user_language = get_user_language(message.from_user.id)  
    text = i18n.get_text("admin_msg", user_language)
    admin_text = (text)
    await message.answer(admin_text)
#END: /admin

@dp.message_handler(commands=['stop'])
async def stop_account(message: types.Message):
    user_id = message.from_user.id

    # Agar foydalanuvchi qidiruv jarayonida bo'lsa, uni belgilaymiz
    if user_id in searching_users:
        user_language = get_user_language(message.from_user.id)  
        text = i18n.get_text("in_searching_process", user_language)
        sent_message = await message.reply(text)
        temp_data[user_id]["stop_after_search"] = True  # Qidiruv tugaganidan keyin hisobni o'chirish
        temp_data[user_id]["delete_message_id"] = sent_message.message_id  # Xabar ID sini saqlaymiz
        return
    
    await delete_user_account(user_id, message)

    # await message.answer(text)

async def finish_search_for_user(user_id):
    # """ Qidiruv tugaganda, agar foydalanuvchi stop bergan bo‘lsa, hisobni o‘chiradi """
    searching_users.discard(user_id)
    
    if temp_data.get(user_id, {}).get("stop_after_search"):
        # Avval xabarni o‘chirib tashlaymiz
        message_id = temp_data[user_id].get("delete_message_id")
        if message_id:
            try:
                await bot.delete_message(user_id, message_id)  # Xabarni o‘chiramiz
            except Exception as e:
                print(f"Xabarni o‘chirishda xatolik: {e}")

#END: /stop

@dp.message_handler(commands=['start'])
async def start_command(message: types.Message):
    user_id = message.from_user.id

    # Avval DB dan foydalanuvchi ma'lumotlarini olamiz
    with get_db_connection() as db:
        cursor = db.cursor()
        cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        user = cursor.fetchone()

    # Agar foydalanuvchi ro'yxatda bo'lsa va session mavjud bo'lsa
    if user:
        # Agar session yaroqsiz bo'lsa
        if not await check_user_session_valid(user_id):
            # Yaroqsiz sessiyani yangilaymiz yoki o'chirib qo'yamiz
            with get_db_connection() as db:
                cursor = db.cursor()
                cursor.execute("UPDATE users SET session_string = NULL WHERE user_id = ?", (user_id,))
                db.commit()
            # Ro'yxatdan o'tish jarayonini boshlash uchun til tanlash qismini ko'rsatamiz
            temp_data[user_id] = {"state": "awaiting_language"}
            keyboard = get_language_inline_keyboard()
            text = "Sizning akkauntingizdagi ma'lumotlar eskirgan. Iltimos, qayta ro'yhatdan o'ting" if temp_data[user_id]["language"] == "uz" else "Информация в вашем аккаунте устарела. Пожалуйста, зарегистрируйтесь еще раз."
            await message.answer("Sizning sessiyangiz tugagan. Iltimos, tilni tanlang:\nВыберите язык:", reply_markup=keyboard)
            # Bu yerda return qilmasak, quyidagi kodlar ham qayta ro'yxatdan o'tishga o'tilmaydi
            return
        else:
            # Agar session yaroqli bo'lsa, odatiy xush kelibsiz xabarini yuboramiz
            user_language = get_user_language(user_id)
            text = i18n.get_text("welcome_back", user_language)
            await message.answer(text)
            await help_command(message)
            return
    else:
        # Agar foydalanuvchi ro'yxatda bo'lmasa, til tanlash orqali ro'yxatdan o'tishni boshlaymiz
        temp_data[user_id] = {"state": "awaiting_language"}
        keyboard = get_language_inline_keyboard()
        await message.answer("Tilni tanlang:\nВыберите язык:", reply_markup=keyboard)




# @dp.message_handler(commands=['start'])
# async def start_command(message: types.Message):
#     user_id = message.from_user.id

#     # Sessiyani tekshirish
#     if not await check_user_session_valid(user_id):
#         await message.answer("Sizning sessiyangiz tugagan yoki bloklangansiz. Qayta ro‘yxatdan o‘ting.")
#         return

#     # Agar foydalanuvchi qidiruv jarayonida bo'lsa, tozalash
#     searching_users.pop(user_id, None)
#     temp_data.pop(user_id, None)

#     with get_db_connection() as db:
#         cursor = db.cursor()
#         cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
#         user = cursor.fetchone()


#     if user and user[2]:  # Agar foydalanuvchi bazada bo'lsa
#         user_language = get_user_language(user_id)
#         text = i18n.get_text("welcome_back", user_language)
#         await message.answer(text)
#         await help_command(message)
#     else:
#         # Yangi foydalanuvchilar uchun til tanlash
#         temp_data[user_id] = {"state": "awaiting_language"}
#         keyboard = get_language_inline_keyboard()
#         await message.answer("Tilni tanlang:\nВыберите язык:", reply_markup=keyboard)
#END: /start

#=================================search======================================#
# "❌ Bekor qilish" tugmasi
cancel_button = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="❌ Bekor qilish")]],
    resize_keyboard=True
)

@dp.message_handler(commands=['search'])
async def search_command(message: types.Message):
    user_id = message.from_user.id

    # Sessiyani tekshirish
    if not await check_user_session_valid(user_id):
        await message.answer("Sizning sessiyangiz tugagan yoki bloklangansiz. Qayta ro‘yxatdan o‘ting.")
        return

    if user_id in searching_users:
        user_language = get_user_language(message.from_user.id)  
        text = i18n.get_text("bekor", user_language)
        await message.reply(text)
        return
    
    searching_users[user_id] = True
    temp_data[user_id] = {'state': 'waiting_words'}
    user_language = get_user_language(message.from_user.id)  
    text = i18n.get_text("two_words", user_language)
    await message.reply(text, reply_markup=cancel_button)

@dp.message_handler(lambda message: message.from_user.id in searching_users)
async def handle_search_flow(message: types.Message):
    user_id = message.from_user.id
    state = temp_data.get(user_id, {}).get('state')

    if state == 'waiting_words':
        words = message.text.strip().split()
        if len(words) != 2:
            user_language = get_user_language(message.from_user.id)  
            text = i18n.get_text("probel", user_language)
            await message.reply(text)
            return

        client = await get_telethon_client(user_id)
        if not client:
            searching_users.discard(user_id)
            user_language = get_user_language(message.from_user.id)  
            text = i18n.get_text("not_register", user_language)
            await message.reply(text, reply_markup=ReplyKeyboardMarkup())
            return

        groups = [d for d in (await client.get_dialogs()) if d.is_group]
        if not groups:
            searching_users.discard(user_id)
            user_language = get_user_language(message.from_user.id)  
            text = i18n.get_text("no_group", user_language)
            await message.reply(text)
            return

        temp_data[user_id].update({'words': words, 'groups': groups, 'state': 'waiting_groups'})
        groups_list = "\n".join([f"{idx + 1}. {group.title}" for idx, group in enumerate(groups)])
        text = i18n.get_text("group_selection_prompt", user_language, groups_list=groups_list)
        await message.reply(text)


    elif state == 'waiting_groups':
        try:
            indices = [int(n.strip()) - 1 for n in message.text.split(',')]
            groups = temp_data[user_id]['groups']
            if any(i < 0 or i >= len(groups) for i in indices):
                user_language = get_user_language(message.from_user.id)  
                text = i18n.get_text("incorrect", user_language)
                await message.reply(text)
                return

            user_language = get_user_language(message.from_user.id)  
            text = i18n.get_text("searching", user_language)
            search_msg = await message.reply(text)
            words = temp_data[user_id]['words']
            
            # So‘zlarni Telegram qidiruv formatiga moslash
            search_query = f'"{words[0]}" "{words[1]}"'

            client = await get_telethon_client(user_id)
            for group in [groups[i] for i in indices]:
                messages = []
                
                # Qidiruvni optimallashtirish
                async for msg in client.iter_messages(group, search=search_query, limit=10):
                    if not searching_users.get(user_id, False):
                        user_language = get_user_language(message.from_user.id)  
                        text = i18n.get_text("canceled_search", user_language)
                        await message.reply(text, reply_markup=ReplyKeyboardRemove())
                        return  

                    if msg.text:
                        messages.append((msg.text, msg.id))
                        if len(messages) >= 5:
                            break
                
                if messages:
                    response = i18n.get_text("search_results", user_language, group_title=group.title)
                    for i, (msg_text, msg_id) in enumerate(messages, 1):
                        message_link = f"https://t.me/c/{str(group.id)[4:]}/{msg_id}"
                        response += i18n.get_text(
                            "search_result_item",
                            user_language,
                            index=i,
                            short_msg=msg_text[:50],
                            message_link=message_link
                        )
                    await message.reply(response, parse_mode="Markdown", disable_web_page_preview=True)

            await bot.delete_message(chat_id=message.chat.id, message_id=search_msg.message_id)
            user_language = get_user_language(message.from_user.id)  
            text = i18n.get_text("finished_search", user_language)
            await message.reply(text, reply_markup=ReplyKeyboardRemove())                    

        except ValueError:
            user_language = get_user_language(message.from_user.id)  
            text = i18n.get_text("incorrect_format", user_language)
            await message.reply(text)
            return

        del searching_users[user_id]
        del temp_data[user_id]
#END: /search

@dp.message_handler(lambda message: message.text == "❌ Bekor qilish")
async def cancel_search(message: types.Message):
    user_id = message.from_user.id
    if user_id in searching_users:
        del searching_users[user_id]  # Foydalanuvchini qidiruv ro‘yxatidan olib tashlaymiz
        del temp_data[user_id]
        user_language = get_user_language(message.from_user.id)  
        text = i18n.get_text("canceled_search", user_language)
        await message.reply(text, reply_markup=ReplyKeyboardRemove())
    else:
        user_language = get_user_language(message.from_user.id)  
        text = i18n.get_text("not_in_search", user_language)
        await message.reply(text)
#END: /cancel
# =============================================================================#
async def send_periodic_message(client, user_id):
    """
    Bu funksiya ma'lumotlar bazasidagi postlarni muntazam ravishda barcha guruhlarga yuborishga urunadi 
    va progress xabarlarni foydalanuvchi bilan bot o'rtasidagi chatga yuboradi.
    """
    while True:
        cursor.execute("SELECT id, message_id, chat_id FROM posts WHERE user_id = ?", (user_id,))
        posts = cursor.fetchall()
        for post in posts:
            post_id, message_id, chat_id = post
            dialogs = await client.get_dialogs()
            groups = [dialog for dialog in dialogs if dialog.is_group]
            if groups:
                user_language = get_user_language(user_id)
                # Boshlanish xabari bot orqali yuboriladi
                text = i18n.get_text("started_sending", user_language)
                progress_message = await bot.send_message(user_id, text)
                for idx, group in enumerate(groups, start=1):
                    try:
                        # Xabarni olish: asl nusxani olish yoki forward qilish mumkin.
                        message_obj = await client.get_messages(chat_id, ids=message_id)
                        # Forward qilish misoli:
                        await client.forward_messages(group.id, message_obj, from_peer=chat_id)
                        
                        # progress_text = i18n.get_text(
                        #     "sending_status",
                        #     user_language,
                        #     idx=idx,
                        #     total_groups=len(groups),
                        #     group_title=group.title
                        # )

                        progress_text = i18n.get_text("message_sent", user_language).format(
                            idx=idx,
                            total_groups=len(groups),
                            group_title=group.title
                        )

                        # Bot orqali progress xabari yangilanadi
                        await bot.edit_message_text(
                            progress_text, 
                            chat_id=user_id, 
                            message_id=progress_message.message_id
                        )
                        await asyncio.sleep(send_delay)
                    except FloodWaitError as e:
                        flood_text = i18n.get_text("flood_wait", user_language).format(seconds=e.seconds)
                        await bot.send_message(user_id, flood_text)
                        await asyncio.sleep(e.seconds)
                    except Exception as e:
                        error_text = i18n.get_text("sending_error", user_language).format(group_title=group.title)
                        await bot.send_message(user_id, error_text)
                user_language = get_user_language(user_id)
                text = i18n.get_text("all_sent", user_language)
                await bot.edit_message_text(
                    text, 
                    chat_id=user_id, 
                    message_id=progress_message.message_id
                )
        await asyncio.sleep(2400)  # 50 daqiqa kutish


async def start_telethon_client(user_id, session_string):
    client = TelegramClient(StringSession(session_string), TELETHON_API_ID, TELETHON_API_HASH)
    await client.start()
    # Foydalanuvchining faol klientini saqlaymiz
    active_clients[user_id] = client
    # Faqat periodic message yuborish vazifasini qo'shamiz
    asyncio.create_task(send_periodic_message(client, user_id))
#END: avtomtik xabar yuborish

async def run_telethon():
    cursor.execute("SELECT user_id, session_string FROM users")
    users = cursor.fetchall()
    for user in users:
        user_id, session_string = user
        await start_telethon_client(user_id, session_string)

async def shutdown(dispatcher: Dispatcher):
    await dispatcher.storage.close()
    await dispatcher.storage.wait_closed()
    await bot_client.disconnect()

# =============================================================================
# MAIN FUNKSIYA: Bot va Telethon jarayonlarini ishga tushiradi.

async def main():
    # Ma'lumotlar bazasi strukturasini tekshirish
    with get_db_connection() as db:
        cursor = db.cursor()
        # Asosiy jadval
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER UNIQUE,
                phone_number TEXT,
                session_string TEXT,
                language TEXT DEFAULT 'uz',
                registered_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        db.commit()
    
    await set_commands(bot)
    await bot_client.start()
    
    try:
        await dp.start_polling()
    finally:
        await shutdown(dp)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot to'xtatildi")
