# main.py
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import requests
import asyncio
import logging
import io

logging.basicConfig(level=logging.INFO)

# توکن و کلیدها مستقیماً داخل کد
TOKEN = "8379881886:AAFu_3B6WOSrvMSnnptb3PrPV3I691KRMzo"
CEREBRAS_API_KEY = "csk-vx2xvc6cmv9th995m9xmh5edm9ynj8xvxpkjt9656y8942jc"
ELEVENLABS_API_KEY = "0119f8a151a7bf2bebaf23ab0961b27c588d76c66cd28834bf745bb0cf964f03"

CEREBRAS_URL = "https://api.cerebras.ai/v1/chat/completions"
ELEVENLABS_URL = "https://api.elevenlabs.io/v1/text-to-speech/EXAVITQu4vr4xnSDxMaL"

HEADERS_CEREBRAS = {"Authorization": f"Bearer {CEREBRAS_API_KEY}", "Content-Type": "application/json"}
HEADERS_ELEVEN = {"xi-api-key": ELEVENLABS_API_KEY, "Content-Type": "application/json"}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "سلام! من یک دستیار هوشمند با صدای واقعی فارسی هستم\n"
        "هر چی بنویسی، برات می‌خونم!\n"
        "مثلاً: «سلام چطوری؟»"
    )

def text_to_voice(text: str):
    try:
        payload = {
            "text": text,
            "model_id": "eleven_multilingual_v2",
            "voice_settings": {"stability": 0.75, "similarity_boost": 0.9}
        }
        response = requests.post(ELEVENLABS_URL, headers=HEADERS_ELEVEN, json=payload, timeout=30)
        if response.status_code == 200 and len(response.content) > 10000:
            return io.BytesIO(response.content)
    except Exception as e:
        print(f"Voice error: {e}")
    return None

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_msg = update.message.text.strip()

    payload = {
        "model": "llama3.1-8b",
        "messages": [
            {"role": "system", "content": "تو یک دستیار مودب و دقیق هستی. پاسخ‌ها را کوتاه و به فارسی بده."},
            {"role": "user", "content": user_msg}
        ],
        "max_tokens": 200
    }
    try:
        resp = requests.post(CEREBRAS_URL, headers=HEADERS_CEREBRAS, json=payload, timeout=30)
        ai_reply = resp.json()['choices'][0]['message']['content'].strip() if resp.status_code == 200 else "مشکل پیش اومد."
    except:
        ai_reply = "نمی‌تونم جواب بدم."

    await update.message.reply_text(ai_reply)

    voice = await asyncio.to_thread(text_to_voice, ai_reply)
    if voice:
        voice.seek(0)
        await update.message.reply_voice(voice=voice, caption="صدای پاسخ")

async def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("بات روی Render فعال شد!")
    await app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
