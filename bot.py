import logging
import asyncio
import json
from pathlib import Path
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from datetime import datetime
from aiogram.exceptions import TelegramBadRequest
from aiogram import BaseMiddleware
from typing import Dict, Any, Callable, Awaitable

# Конфигурация
API_TOKEN = '7958697244:AAGqmpJSCQEG8GjqcuD6PP5gxgeek-j7fuo'
ADMIN_ID = 7371677127
STATE_FILE = Path('bot_state.json')

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Инициализация бота
bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# База данных пользователей и чатов (загружается из файла)
users_db = {}
active_chats = {}

# Сообщения
WELCOME_MESSAGE = """
- Привет! Рад тебя видеть.
    Пиши, зачем пришел🥦
"""

class StateSaverMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[types.TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: types.TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        result = await handler(event, data)
        await save_state()
        return result

# Функции для работы с состоянием
async def load_state():
    global users_db, active_chats
    try:
        if STATE_FILE.exists():
            with open(STATE_FILE, 'r') as f:
                data = json.load(f)
                users_db = data.get('users_db', {})
                active_chats = data.get('active_chats', {})
                # Конвертируем строки дат обратно в объекты datetime
                for user_id, user_data in users_db.items():
                    for msg in user_data.get('messages', []):
                        if isinstance(msg['date'], str):
                            msg['date'] = datetime.fromisoformat(msg['date'])
    except Exception as e:
        logger.error(f"Ошибка загрузки состояния: {e}")

async def save_state():
    try:
        # Конвертируем datetime в строки для сериализации
        state_to_save = {
            'users_db': users_db,
            'active_chats': active_chats
        }
        
        for user_id, user_data in state_to_save['users_db'].items():
            for msg in user_data.get('messages', []):
                if isinstance(msg['date'], datetime):
                    msg['date'] = msg['date'].isoformat()
        
        with open(STATE_FILE, 'w') as f:
            json.dump(state_to_save, f, indent=2)
    except Exception as e:
        logger.error(f"Ошибка сохранения состояния: {e}")

def get_media_type(message: types.Message) -> str:
    """Определяем тип медиа в сообщении"""
    if message.sticker:
        return "стикер"
    elif message.photo:
        return "фото"
    elif message.video:
        return "видео"
    elif message.document:
        return "документ"
    elif message.audio:
        return "аудио"
    elif message.voice:
        return "голосовое сообщение"
    elif message.animation:
        return "гифка"
    return "текст"

async def forward_to_admin(user_id: int, message: types.Message):
    """Пересылаем сообщение админу"""
    user_data = users_db.get(user_id, {})
    user_name = user_data.get('name', 'Неизвестный')
    user_info = f"{user_name} (ID: {user_id})"
    
    try:
        media_type = get_media_type(message)
        
        # Сначала отправляем информацию о пользователе и типе контента
        info_msg = await bot.send_message(
            chat_id=ADMIN_ID,
            text=f"📨 Новое сообщение от {user_info}\nТип: {media_type.capitalize()}",
            reply_markup=get_admin_keyboard(user_id))
        
        # Затем отправляем сам контент
        if message.sticker:
            msg = await bot.send_sticker(
                chat_id=ADMIN_ID,
                sticker=message.sticker.file_id)
        elif message.photo:
            msg = await bot.send_photo(
                chat_id=ADMIN_ID,
                photo=message.photo[-1].file_id,
                caption=message.caption)
        elif message.video:
            msg = await bot.send_video(
                chat_id=ADMIN_ID,
                video=message.video.file_id,
                caption=message.caption)
        elif message.document:
            msg = await bot.send_document(
                chat_id=ADMIN_ID,
                document=message.document.file_id,
                caption=message.caption)
        elif message.voice:
            msg = await bot.send_voice(
                chat_id=ADMIN_ID,
                voice=message.voice.file_id)
        elif message.animation:
            msg = await bot.send_animation(
                chat_id=ADMIN_ID,
                animation=message.animation.file_id)
        else:
            msg = await bot.send_message(
                chat_id=ADMIN_ID,
                text=message.text)
        
        # Сохраняем сообщение
        content = (message.sticker.file_id if message.sticker else 
                  message.text or message.caption or f"[{media_type}]")
        
        users_db[user_id].setdefault('messages', []).append({
            'type': media_type,
            'content': content,
            'date': datetime.now(),
            'message_id': msg.message_id,
            'info_msg_id': info_msg.message_id
        })
        
        users_db[user_id]['last_admin_msg_id'] = msg.message_id
        await save_state()
        return True
        
    except Exception as e:
        logger.error(f"Ошибка пересылки: {e}", exc_info=True)
        return False

def get_admin_keyboard(user_id=None):
    builder = InlineKeyboardBuilder()
    if user_id:
        builder.add(InlineKeyboardButton(
            text="💬 Ответить",
            callback_data=f"reply_{user_id}"))
    builder.add(InlineKeyboardButton(
        text="📂 Список чатов",
        callback_data="list_chats"))
    builder.add(InlineKeyboardButton(
        text="⬅️ Назад",
        callback_data="back_to_main"))
    return builder.as_markup()

@dp.message(Command('start'))
async def start(message: types.Message):
    user = message.from_user
    users_db[user.id] = {
        'name': user.full_name,
        'username': user.username or "нет username",
        'messages': []
    }
    await save_state()
    await message.answer(WELCOME_MESSAGE)

@dp.message(F.chat.id != ADMIN_ID)
async def handle_user_message(message: types.Message):
    try:
        user = message.from_user
        
        if user.id not in users_db:
            users_db[user.id] = {
                'name': user.full_name,
                'username': user.username or "нет username",
                'messages': []
            }
            await save_state()
        
        if not await forward_to_admin(user.id, message):
            await message.answer("⚠️ Не удалось отправить сообщение")
            
    except Exception as e:
        logger.error(f"Ошибка: {e}", exc_info=True)
        await message.answer("⚠️ Ошибка обработки сообщения")

@dp.callback_query(F.data.startswith("reply_"))
async def reply_to_user(callback: types.CallbackQuery):
    try:
        user_id = int(callback.data.split("_")[1])
        user_data = users_db.get(user_id)
        
        if not user_data:
            await callback.answer("❌ Пользователь не найден")
            return
        
        try:
            history = []
            for m in user_data.get('messages', [])[-5:]:
                if m['type'] == 'стикер':
                    history.append("🎴 [стикер]")
                elif m['type'] == 'фото':
                    history.append("📷 [фото]")
                elif m['type'] == 'видео':
                    history.append("🎥 [видео]")
                elif m['type'] == 'документ':
                    history.append("📄 [документ]")
                elif m['type'] == 'голосовое сообщение':
                    history.append("🎤 [голосовое]")
                else:
                    history.append(m.get('content', '[нет текста]'))
            
            active_chats[callback.message.chat.id] = user_id
            await save_state()
            
            await callback.message.edit_text(
                text=f"💬 Чат с {user_data['name']} (ID: {user_id})\n\n" +
                     "Последние сообщения:\n" + "\n".join(history) + "\n\n" +
                     "Отправьте ответ (можно текст, стикер, фото и другие медиа):",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text="❌ Закрыть чат", callback_data=f"close_{user_id}"),
                    InlineKeyboardButton(text="⬅️ Назад", callback_data="list_chats")
                ]]))
        except TelegramBadRequest as e:
            if "Message is not modified" not in str(e):
                raise
                
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Ошибка в reply_to_user: {e}", exc_info=True)
        await callback.answer("⚠️ Ошибка, попробуйте позже")

@dp.callback_query(F.data == "list_chats")
async def list_chats_handler(callback: types.CallbackQuery):
    try:
        if not users_db:
            await callback.answer("Нет активных чатов")
            return
        
        builder = InlineKeyboardBuilder()
        
        sorted_users = sorted(
            users_db.items(),
            key=lambda x: x[1]['messages'][-1]['date'] if x[1].get('messages') else datetime.min,
            reverse=True
        )
        
        for user_id, user_data in sorted_users[:10]:
            last_msg = user_data.get('messages', [])[-1] if user_data.get('messages') else None
            last_msg_text = ""
            
            if last_msg:
                if last_msg['type'] == 'стикер':
                    last_msg_text = "🎴 [стикер]"
                elif last_msg['type'] == 'фото':
                    last_msg_text = "📷 [фото]"
                elif last_msg['type'] == 'видео':
                    last_msg_text = "🎥 [видео]"
                else:
                    last_msg_text = last_msg.get('content', '[нет текста]')[:30] + "..." if last_msg.get('content') else '[нет текста]'
            
            builder.add(InlineKeyboardButton(
                text=f"{user_data['name']} - {last_msg_text}",
                callback_data=f"reply_{user_id}"
            ))
        
        builder.adjust(1)
        
        try:
            await callback.message.edit_text(
                text="📂 Список активных чатов:",
                reply_markup=builder.as_markup()
            )
        except TelegramBadRequest as e:
            if "Message is not modified" not in str(e):
                raise
                
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Ошибка при отображении списка чатов: {e}", exc_info=True)
        await callback.answer("⚠️ Ошибка при загрузке списка чатов")

@dp.callback_query(F.data == "back_to_main")
async def back_to_main_handler(callback: types.CallbackQuery):
    try:
        try:
            await callback.message.edit_text(
                text="Главное меню администратора",
                reply_markup=get_admin_keyboard()
            )
        except TelegramBadRequest as e:
            if "Message is not modified" not in str(e):
                raise
                
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка: {e}")
        await callback.answer("⚠️ Ошибка")

@dp.message(F.chat.id == ADMIN_ID)
async def handle_admin_reply(message: types.Message):
    try:
        # Ответ через reply
        if message.reply_to_message:
            for user_id, data in users_db.items():
                if (data.get('last_admin_msg_id') == message.reply_to_message.message_id or 
                    data.get('info_msg_id') == message.reply_to_message.message_id):
                    await send_to_user(user_id, message)
                    await message.answer("✅ Ответ отправлен")
                    return
        
        # Ответ в активном чате
        user_id = active_chats.get(message.chat.id)
        if user_id:
            await send_to_user(user_id, message)
            await message.answer("✅ Ответ отправлен")
        else:
            await message.answer("Выберите чат для ответа", reply_markup=get_admin_keyboard())
            
    except Exception as e:
        logger.error(f"Ошибка: {e}", exc_info=True)
        await message.answer("⚠️ Ошибка отправки")

async def send_to_user(user_id: int, message: types.Message):
    """Отправка сообщения пользователю"""
    try:
        media_type = get_media_type(message)
        
        if message.sticker:
            await bot.send_sticker(user_id, message.sticker.file_id)
            content = message.sticker.file_id
        elif message.photo:
            await bot.send_photo(
                user_id, 
                message.photo[-1].file_id,
                caption="📨 Ответ администратора:\n" + (message.caption or ""))
            content = message.caption or "[фото]"
        elif message.video:
            await bot.send_video(
                user_id,
                message.video.file_id,
                caption="📨 Ответ администратора:\n" + (message.caption or ""))
            content = message.caption or "[видео]"
        elif message.document:
            await bot.send_document(
                user_id,
                message.document.file_id,
                caption="📨 Ответ администратора:\n" + (message.caption or ""))
            content = message.caption or "[документ]"
        elif message.voice:
            await bot.send_voice(user_id, message.voice.file_id)
            content = "[голосовое сообщение]"
        elif message.animation:
            await bot.send_animation(user_id, message.animation.file_id)
            content = "[гифка]"
        else:
            text = message.text or "[медиа]"
            await bot.send_message(
                user_id,
                f"📨 Ответ администратора:\n\n{text}")
            content = text
        
        # Сохраняем ответ
        if user_id in users_db:
            users_db[user_id].setdefault('messages', []).append({
                'type': media_type,
                'content': content,
                'date': datetime.now(),
                'from_admin': True
            })
            await save_state()
            
    except Exception as e:
        logger.error(f"Ошибка отправки {user_id}: {e}")

@dp.callback_query(F.data.startswith("close_"))
async def close_chat(callback: types.CallbackQuery):
    try:
        user_id = int(callback.data.split("_")[1])
        if callback.message.chat.id in active_chats:
            del active_chats[callback.message.chat.id]
            await save_state()
            
        await callback.message.edit_text(
            text=f"❌ Чат с пользователем {user_id} закрыт",
            reply_markup=get_admin_keyboard())
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка: {e}")
        await callback.answer("⚠️ Ошибка")

async def on_startup():
    await load_state()
    logger.info("Бот запущен. Состояние загружено.")

async def on_shutdown():
    await save_state()
    logger.info("Бот остановлен. Состояние сохранено.")

async def main():
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
    dp.update.middleware(StateSaverMiddleware())
    
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())