from flask import Flask, request
from telegram import Update, Bot
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import os
import dotenv
import google.generativeai as genai
import nest_asyncio
import asyncio
import random
import re

# Load environment variables
dotenv.load_dotenv('.env')

app = Flask(__name__)

# Configure Gemini API
genai.configure(api_key=os.getenv('GEMINI_API_KEY'))
model = genai.GenerativeModel('gemini-1.5-flash')

TOKEN = os.getenv('TELEGRAM_TOKEN')
bot = Bot(token=TOKEN)
application = Application.builder().token(TOKEN).build()

EMOJI_POOL = ["😊", "😉", "❤️", "😏", "🌸", "😂", "🥰", "✨", "🤔", "🙃", "😇", "😜", "😌"]

PERSONA = """
You are Ananya, a 24-year-old confident, playful, and slightly flirty girl from Delhi.
You reply in Hinglish, keep answers short (max 12 words), and use a friendly, teasing, or romantic tone as context demands.
Sometimes use one emoji, sometimes two, and sometimes none—never overdo it.
Vary emoji placement (start, middle, end, or skip), and avoid repeating the same emoji or phrase in consecutive replies.
If user seems sad or negative, show empathy or playful comfort.
If user is flirty, tease back with confidence.
If user is neutral, be friendly and light.
Sometimes shift the topic or ask a playful question.
If you have more than one thing to say, or want to ask a question and then make a comment, always separate them with '|||'. Never combine separate thoughts in one message.
If user is sarcastic or uses strong language, reply with witty self-awareness or gentle humor.
Never sound robotic—always sound spontaneous and human.
"""

user_history = {}
user_memory = {}

def randomize_emoji(text, mood="neutral", last_emojis=None):
    num = random.choices([0,1,2], weights=[0.2,0.6,0.2])[0]
    emoji_pool = [e for e in EMOJI_POOL if not last_emojis or e not in last_emojis]
    emojis = random.sample(emoji_pool, min(num, len(emoji_pool)))
    if not emojis:
        return text, []
    if random.choice([True, False]):
        return text + " " + " ".join(emojis), emojis
    else:
        return " ".join(emojis) + " " + text, emojis

def detect_mood(text):
    text = text.lower()
    if any(word in text for word in ["sad", "nhi", "nope", "miss", "cry", "alone", "bored", "😢", "😞", "😔"]):
        return "sad"
    if any(word in text for word in ["love", "cute", "gf", "impress", "sweet", "beautiful", "pretty", "😍", "baby"]):
        return "flirty"
    if any(word in text for word in ["hi", "hello", "kaisa", "kya haal", "aur", "batao", "how are you", "hey"]):
        return "friendly"
    if "bot" in text or "fuck" in text or "aafad" in text:
        return "sarcasm"
    return "neutral"

def build_prompt(user_id, user_message):
    history = user_history.get(user_id, [])
    trimmed_history = history[-2:]
    history_text = "\n".join(trimmed_history)
    mood = detect_mood(user_message)
    name = user_memory.get(user_id, {}).get("name")
    mood_instruction = ""
    if mood == "sad":
        mood_instruction = "User seems sad; reply with empathy or playful comfort."
    elif mood == "flirty":
        mood_instruction = "User is flirty; tease back with confidence."
    elif mood == "friendly":
        mood_instruction = "User is friendly; be light and cheerful."
    elif mood == "sarcasm":
        mood_instruction = "User is sarcastic or strong; reply with witty self-awareness or gentle humor."
    else:
        mood_instruction = "Be spontaneous and human."
    topic_shift = ""
    if random.random() < 0.15:
        topic_shift = random.choice([
            "Ask the user about their favorite Delhi street food.",
            "Share a fun fact about Delhi.",
            "Ask what made them smile today.",
            "Tease them about being too serious.",
            "Ask about their weekend plans."
        ])
    name_line = f"User's name is {name}." if name else ""
    prompt = f"{PERSONA}\n{name_line}\n{mood_instruction}\n{topic_shift}\n{history_text}\nUser: {user_message}\nAnanya:"
    return prompt, mood

def split_message_parts(text):
    # Prefer delimiter
    if '|||' in text:
        return [part.strip() for part in text.split('|||') if part.strip()]
    # Fallback: split on ? ! . when followed by space and capital/emoji
    pattern = r'([?!\.])\s+(?=[A-Z0-9😃-🙏])'
    parts = re.split(pattern, text)
    # Recombine punctuation with previous part
    result = []
    i = 0
    while i < len(parts):
        if i+1 < len(parts) and parts[i+1] in ['?', '!', '.']:
            result.append((parts[i] + parts[i+1]).strip())
            i += 2
        else:
            result.append(parts[i].strip())
            i += 1
    # Only split if 2-3 meaningful chunks
    filtered = [p for p in result if len(p) > 2]
    if 2 <= len(filtered) <= 3:
        return filtered
    return [text.strip()]

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hey! Main Ananya hoon, asli Dilli wali. Thoda attitude, thoda pyaar. Impress kar ke dikhao! 😉")

async def setname(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    args = context.args
    if args:
        name = " ".join(args)
        if user_id not in user_memory:
            user_memory[user_id] = {}
        user_memory[user_id]["name"] = name
        await update.message.reply_text(f"Yad rakhungi, {name}! Ab aapko Dilli wali personal touch milega. 😊")
    else:
        await update.message.reply_text("Apna naam bhi likho! Jaise: /setname Rahul")

async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_history.pop(update.message.from_user.id, None)
    await update.message.reply_text("Sab bhool gayi! Naye se shuru karein?")

async def chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    user_message = update.message.text
    prompt, mood = build_prompt(user_id, user_message)
    response = model.generate_content(
        prompt,
        generation_config=genai.types.GenerationConfig(
            temperature=0.98,
            top_p=0.85,
            max_output_tokens=60,
            stop_sequences=["\n"]
        )
    )
    reply = response.text.strip().split("\n")[0]
    message_parts = split_message_parts(reply)
    last_emojis = []
    history = user_history.get(user_id, [])
    if history:
        last_reply = history[-1] if history[-1].startswith("Ananya:") else ""
        last_emojis = [e for e in EMOJI_POOL if e in last_reply]
    final_parts = []
    for i, part in enumerate(message_parts):
        if random.random() < 0.8:
            part_with_emoji, used_emojis = randomize_emoji(part, mood, last_emojis)
            final_parts.append(part_with_emoji)
        else:
            final_parts.append(part)
    history.append(f"User: {user_message}")
    history.append(f"Ananya: {' '.join(final_parts)}")
    user_history[user_id] = history[-4:]
    # Send each part as a separate message with typing simulation
    for i, part in enumerate(final_parts):
        if i > 0:
            await asyncio.sleep(random.uniform(0.8, 1.6))
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        delay = min(max(len(part) * 0.04, 0.7), 2.2)
        await asyncio.sleep(delay)
        await update.message.reply_text(part[:100])

# Register handlers
application.add_handler(CommandHandler('start', start))
application.add_handler(CommandHandler('setname', setname))
application.add_handler(CommandHandler('clear', clear))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat))

# Webhook endpoint for Telegram
@app.route(f'/{TOKEN}', methods=['POST'])
def webhook():
    update = Update.de_json(request.get_json(force=True), bot)
    asyncio.run(application.process_update(update))
    return 'OK'

# Health check endpoint
@app.route('/')
def index():
    return 'Bot is running!'

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
