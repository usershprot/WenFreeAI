from telethon import functions
import asyncio
import re
import requests
from telethon import TelegramClient, events
from telethon.errors import FloodWaitError

# =========================
API_ID = 37368606
API_HASH = "b9b485bba1728c4a87b18d263c286e95"

HH_API_URL = "https://max1mapp.online/api/chat/v2"
HH_ADMIN_KEY = "luchshemu-truvun"

CHANNEL_USERNAME = "Wewinfree"
CHAT_USERNAME = "WeWinChat"
# =========================

import requests
import re

async def search_internet(query):
    try:
        url = "https://lite.duckduckgo.com/lite/"
        response = requests.post(url, data={"q": query}, timeout=5)

        matches = re.findall(r'<a rel="nofollow" class="result-link".*?>(.*?)</a>', response.text)

        if matches:
            clean = re.sub("<.*?>", "", matches[0])
            return clean

    except Exception as e:
        print("❌ Ошибка поиска:", e)

    return None

client = TelegramClient("session_bot", API_ID, API_HASH)

processed_posts = set()


def is_giveaway_post(text: str) -> bool:
    if not text:
        return False

    text_upper = text.upper()

    if "🎁 РОЗЫГРЫШ" not in text_upper:
        return False

    keywords = ["АНАГРАММА", "ЗАГАДКА", "КВИЗ", "ПРИМЕР", "ЭМОДЗИ"]

    return any(word in text_upper for word in keywords)


async def get_ai_answer(text: str):
    headers = {
        "Authorization": f"Bearer {HH_ADMIN_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": "google/gemini-2.5-flash",
        "messages": [
            {
                "role": "system",
                "content": (
                    "Это розыгрыш. "
                    "Если анаграмма — собери слово. "
                    "Если загадка — дай ответ. "
                    "Если квиз — дай правильный ответ. "
                    "Если пример — реши его. "
                    "Если эмодзи — отправь только нужный эмодзи. "
                    "Отправь только ответ без пояснений."
                )
            },
            {"role": "user", "content": text}
        ],
        "temperature": 0
    }

    loop = asyncio.get_event_loop()

    try:
        response = await loop.run_in_executor(
            None,
            lambda: requests.post(
                HH_API_URL,
                json=payload,
                headers=headers,
                timeout=60
            )
        )

        if response.status_code == 200:
            data = response.json()
            answer = data["choices"][0]["message"]["content"].strip()
            answer = re.split(r"\n", answer)[0]
            return answer

    except Exception as e:
        print("❌ Ошибка запроса к API:", e)

    return None

import re
from telethon import events

WATCH_BOT = "giftchannelsbot"
WIN_TEXT = "ПОЗДРАВЛЯЕМ"
NOTIFY_USER = "truvun"


@client.on(events.NewMessage(from_users=WATCH_BOT))
async def win_notifier(event):
    text = event.raw_text

    if not text:
        return

    if WIN_TEXT in text:
        print("🏆 Победа обнаружена!")

        # ищем ссылку на чек
        match = re.search(r"https://t\.me/CryptoBot\?start=\S+", text)

        notify_message = "🏆 ВЫ ВЫИГРАЛИ!\n\n"

        if match:
            link = match.group(0)
            notify_message += f"💰 Чек:\n{link}"

        await client.send_message(NOTIFY_USER, notify_message)

        print("📩 Уведомление отправлено @truvun")

import asyncio

BOT_USERNAME = "giftchannelsbot"
WIN_TEXT = "ПОЗДРАВЛЯЕМ"

async def solve_giveaway(task_text):

    tried_answers = set()

    while True:
        print("🤖 Генерирую ответ...")

        answer = await get_ai_answer(task_text)

        if not answer:
            print("⚠ AI не дал ответ")
            await asyncio.sleep(3)
            continue

        answer = answer.strip()

        # чтобы не отправлять один и тот же ответ
        if answer in tried_answers:
            print("♻ Уже пробовали:", answer)
            await asyncio.sleep(2)
            continue

        tried_answers.add(answer)

        await client.send_message(BOT_USERNAME, answer)
        print("📤 Отправлено:", answer)

        # ждём 6 секунд
        await asyncio.sleep(6)

        messages = await client.get_messages(BOT_USERNAME, limit=5)

        win_detected = False
        someone_won = False
        wrong_answer = False

        for msg in messages:
            if not msg.text:
                continue

            text = msg.text

            if WIN_TEXT in text:
                win_detected = True

            if "победил" in text.lower():
                someone_won = True

            if "неверн" in text.lower():
                wrong_answer = True

        if win_detected:
            print("🏆 МЫ ПОБЕДИЛИ!")
            break

        if someone_won:
            print("❌ Кто-то уже выиграл")
            break

        if wrong_answer:
            print("❌ Ответ неверный, пробуем другой")
            continue

        print("🔁 Нет победы, пробуем новый ответ...")


@client.on(events.NewMessage(chats=CHANNEL_USERNAME))
async def handler(event):

    if not event.message.post:
        return

    post_id = event.message.id

    if post_id in processed_posts:
        return

    text = event.message.text
    if not text:
        return

    if not is_giveaway_post(text):
        print("⛔ Не розыгрыш — пропуск")
        return

    processed_posts.add(post_id)

    print("🎁 Найден розыгрыш! Решаю...")

    answer = await get_ai_answer(text)

    if not answer:
        print("❌ Ответ не получен")
        return

    try:
        await asyncio.sleep(0.1)

        channel = await client.get_entity(CHANNEL_USERNAME)

        result = await client(
            functions.messages.GetDiscussionMessageRequest(
                peer=channel,
                msg_id=post_id
            )
        )

        if not result.messages:
            print("❌ Обсуждение не найдено")
            return

        discussion_msg = result.messages[0]

        await client.send_message(
            discussion_msg.peer_id,
            answer,
            reply_to=discussion_msg.id
        )

        print(f"🏆 Ответ отправлен под постом: {answer}")

    except FloodWaitError as e:
        print(f"⏳ FloodWait {e.seconds} сек")
        await asyncio.sleep(e.seconds)

    except Exception as e:
        print(f"❌ Ошибка отправки: {e}")

# =========================
# ЗАПУСК БОТА
# =========================

async def main():
    print("🚀 Бот запущен и ждёт розыгрыши...")
    await client.start()
    print("✅ Авторизация успешна")
    await client.run_until_disconnected()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("⛔ Бот остановлен вручную")
