import logging
import asyncio
import random
import json
import os
import re
import shutil
import time
from datetime import timedelta
from typing import Dict, List, Optional
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, types, F, Router
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, FSInputFile
from aiogram.enums import ParseMode, ChatAction
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

from cerebras.cloud.sdk import Cerebras
import instaloader

class BotStorage:
    @staticmethod
    def load_json(file_path: str, default: dict) -> dict:
        if os.path.exists(file_path):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except:
                return default
        return default

    @staticmethod
    def save_json(file_path: str, data: dict):
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)

class ConfigManager:
    def __init__(self, path="config.json"):
        self.path = path
        self.data = BotStorage.load_json(path, {
            "model": "zai-glm-4.7",
            "prompt": "Ты — Джарвис, ироничный ассистент S010lvloon. Отвечай кратко и по-человечески.",
            "rules": "Правила не установлены.",
            "context_size": 10,
            "notes": {"#news": "Вот свежие новости: [ссылка]"}
        })

    def get(self, key): return self.data.get(key)
    def set(self, key, value):
        self.data[key] = value
        BotStorage.save_json(self.path, self.data)

class HistoryManager:
    def __init__(self, path="history.json"):
        self.path = path
        self.data = BotStorage.load_json(path, {})

    def add_msg(self, key: str, role: str, content: str, limit: int):
        if key not in self.data: self.data[key] = []
        self.data[key].append({"role": role, "content": content})
        self.data[key] = self.data[key][-limit:]
        BotStorage.save_json(self.path, self.data)

    def get_history(self, key: str): return self.data.get(key, [])

class AIProcessor:
    def __init__(self, api_keys: List[str], config: ConfigManager):
        self.clients = [Cerebras(api_key=key) for key in api_keys if key]
        self.config = config

    async def chat(self, messages: List[Dict]) -> Optional[str]:
        random.shuffle(self.clients)
        current_model = self.config.get("model")
        for client in self.clients:
            try:
                full_msgs = [{"role": "system", "content": self.config.get("prompt")}] + messages
                response = await asyncio.to_thread(
                    client.chat.completions.create,
                    model=current_model,
                    messages=full_msgs
                )
                return response.choices[0].message.content
            except Exception as e:
                logging.error(f"AI Error: {e}")
                continue
        return None

class InstaDownloader:
    def __init__(self):
        self.L = instaloader.Instaloader(
            download_pictures=False,
            download_videos=True,
            download_video_thumbnails=False,
            download_geotags=False,
            download_comments=False,
            save_metadata=False
        )

    async def download_video(self, url: str) -> Optional[str]:
        try:
            shortcode = url.split("/")[-2] if url.endswith("/") else url.split("/")[-1]
            if "?" in shortcode: shortcode = shortcode.split("?")[0]
            target_dir = f"temp_{shortcode}_{int(time.time())}"
            def sync_download():
                post = instaloader.Post.from_shortcode(self.L.context, shortcode)
                self.L.download_post(post, target=target_dir)
                for file in os.listdir(target_dir):
                    if file.endswith(".mp4"):
                        return os.path.join(target_dir, file)
                return None
            return await asyncio.to_thread(sync_download)
        except Exception as e:
            logging.error(f"Instaloader Error: {e}")
            return None

class AdminStates(StatesGroup):
    waiting_auth = State()
    menu = State()
    editing_prompt = State()
    editing_model = State()
    adding_note_key = State()
    adding_note_val = State()

router = Router()
AI_TRIGGER = r"(?i)^(джарвис|jarvis|/ai|sai|s2)\b"
INSTA_RE = r"(https?://(?:www\.)?instagram\.com/(?:p|reels|reel)/([^/?#&]+))"
insta = InstaDownloader()

@router.message(Command("start"))
async def start_handler(msg: Message):
    await msg.answer("🤖 Джарвис на связи.")

@router.message(F.text.startswith("#"))
async def notes_handler(msg: Message, config: ConfigManager):
    notes = config.get("notes")
    cmd = msg.text.split()[0].lower()
    if cmd in notes:
        await msg.reply(notes[cmd])

@router.message(F.text.regexp(INSTA_RE))
async def instagram_handler(msg: Message):
    await msg.bot.send_chat_action(msg.chat.id, ChatAction.UPLOAD_VIDEO)
    match = re.search(INSTA_RE, msg.text)
    url = match.group(1)
    wait_msg = await msg.reply("⏳ Загружаю...")
    file_path = await insta.download_video(url)
    if file_path and os.path.exists(file_path):
        try:
            await msg.reply_video(FSInputFile(file_path), caption="🎬 Готово")
            await wait_msg.delete()
        except Exception:
            await wait_msg.edit_text("❌ Ошибка отправки")
        finally:
            shutil.rmtree(os.path.dirname(file_path), ignore_errors=True)
    else:
        await wait_msg.edit_text("❌ Не удалось скачать")

@router.business_message(F.text.regexp(AI_TRIGGER))
@router.message(F.text.regexp(AI_TRIGGER))
async def ai_handler(msg: Message, ai: AIProcessor, history: HistoryManager, config: ConfigManager):
    user_key = f"{msg.chat.id}_{msg.from_user.id}"
    query = re.sub(AI_TRIGGER, "", msg.text, flags=re.IGNORECASE).strip()
    if not query: return
    if not msg.business_connection_id:
        await msg.bot.send_chat_action(msg.chat.id, ChatAction.TYPING)
    history.add_msg(user_key, "user", query, config.get("context_size"))
    response = await ai.chat(history.get_history(user_key))
    if response:
        history.add_msg(user_key, "assistant", response, config.get("context_size"))
        if msg.business_connection_id:
            await msg.bot.edit_message_text(business_connection_id=msg.business_connection_id, chat_id=msg.chat.id, message_id=msg.message_id, text=response)
        else:
            await msg.reply(response)

@router.message(Command("S2HFHF"))
async def admin_start(msg: Message, state: FSMContext):
    await msg.answer("🔑 Пароль:")
    await state.set_state(AdminStates.waiting_auth)

@router.message(AdminStates.waiting_auth)
async def admin_auth(msg: Message, state: FSMContext, config: ConfigManager):
    if msg.text == os.getenv("ADMIN_PASSWORD", "import"):
        await state.set_state(AdminStates.menu)
        await show_admin_menu(msg, config)
    else:
        await state.clear()

async def show_admin_menu(msg: Message, config: ConfigManager):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🤖 Модель: {config.get('model')}", callback_data="set_model")],
        [InlineKeyboardButton(text="📝 Промт", callback_data="set_prompt")],
        [InlineKeyboardButton(text="📌 Управление Заметками", callback_data="manage_notes")],
        [InlineKeyboardButton(text="❌ Выход", callback_data="exit")]
    ])
    await msg.answer("⚙️ Панель управления:", reply_markup=kb)

@router.callback_query(F.data == "manage_notes", AdminStates.menu)
async def manage_notes(call: CallbackQuery, config: ConfigManager):
    notes = config.get("notes")
    text = "📌 <b>Твои заметки:</b>\n\n"
    buttons = []
    for k in notes.keys():
        buttons.append([
            InlineKeyboardButton(text=f"❌ {k}", callback_data=f"del_note_{k}")
        ])
    buttons.append([InlineKeyboardButton(text="➕ Добавить заметку", callback_data="add_note")])
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")])
    
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await call.message.edit_text(text + "Нажми на заметку, чтобы удалить её.", reply_markup=kb)

@router.callback_query(F.data.startswith("del_note_"))
async def delete_note(call: CallbackQuery, config: ConfigManager):
    note_key = call.data.replace("del_note_", "")
    notes = config.get("notes")
    if note_key in notes:
        del notes[note_key]
        config.set("notes", notes)
        await call.answer(f"Заметка {note_key} удалена")
        await manage_notes(call, config)

@router.callback_query(F.data == "add_note")
async def add_note_step1(call: CallbackQuery, state: FSMContext):
    await call.message.edit_text("Введи ключ заметки (например, #news):")
    await state.set_state(AdminStates.adding_note_key)

@router.message(AdminStates.adding_note_key)
async def add_note_step2(msg: Message, state: FSMContext):
    if not msg.text.startswith("#"):
        return await msg.answer("Ошибка: заметка должна начинаться с символа #")
    await state.update_data(new_note_key=msg.text.lower())
    await msg.answer("Введи текст или ссылку для этой заметки:")
    await state.set_state(AdminStates.adding_note_val)

@router.message(AdminStates.adding_note_val)
async def add_note_final(msg: Message, state: FSMContext, config: ConfigManager):
    data = await state.get_data()
    notes = config.get("notes")
    notes[data['new_note_key']] = msg.text
    config.set("notes", notes)
    await msg.answer(f"✅ Заметка {data['new_note_key']} успешно создана!")
    await state.set_state(AdminStates.menu)
    await show_admin_menu(msg, config)

@router.callback_query(F.data == "back_to_menu")
async def back_menu(call: CallbackQuery, state: FSMContext, config: ConfigManager):
    await state.set_state(AdminStates.menu)
    await call.message.delete()
    await show_admin_menu(call.message, config)

@router.callback_query(F.data == "exit")
async def exit_adm(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.delete()

async def main():
    load_dotenv()
    # Твой новый токен
    token = "8506339952:AAFcCDcPzrx1GTksDOH14cPtza0pKW11g20"
    
    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    cfg = ConfigManager()
    hist = HistoryManager()
    
    keys = [
        os.getenv("CEREBRAS_API_KEY"), 
        "csk-mymvy3hvw89x95m4y8v8kxk2kvehd2m2jemvnewe6dypncfx", 
        "csk-th8wnt28nc9tfcck6mjjmfkn4wf2f9j43v4mfe4rd3cmrcv8", 
        "csk-yk8mfekexj5n96ej8m65y32ympcfw556n5y4rhf8xyywy5m2", 
        "csk-de9cetwd8p6x65rftx395kmjrc9j5fwj6848tck5md9rftth"
    ]
    
    ai = AIProcessor(api_keys=keys, config=cfg)
    dp.include_router(router)
    
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot, config=cfg, history=hist, ai=ai)

if __name__ == "__main__":
    asyncio.run(main())
