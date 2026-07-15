import os
import sqlite3
import logging
from datetime import datetime, timezone
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import google.generativeai as genai
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, ContextTypes, MessageHandler,
    CommandHandler, CallbackQueryHandler, filters,
)

# ---------- الإعدادات ----------
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
DB_PATH = os.environ.get("DB_PATH", "bot_data.db")

genai.configure(api_key=GEMINI_API_KEY)
GEMINI_MODEL_NAME = "gemini-3.5-flash"  # موديل مجاني وسريع، مناسب للمحادثة

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MAX_HISTORY_MESSAGES = 20
PROFILE_UPDATE_EVERY = 8

CRISIS_KEYWORDS = [
    "انتحار", "هقتل نفسي", "عايز اموت", "مش عايز اعيش",
    "هموت نفسي", "مفيش فايدة من حياتي", "هاذي نفسي",
]

CRISIS_MESSAGE = (
    "أنا حاسس إن اللي بتمر بيه صعب جدًا، وحابب أقولك إنك مش لوحدك في الموضوع ده. 💙\n\n"
    "لو بتفكر في إيذاء نفسك دلوقتي، محتاج تكلم حد متخصص فورًا:\n"
    "📞 الخط الساخن للصحة النفسية (وزارة الصحة المصرية):\n"
    "08008880700 (من أي خط أرضي - مجاني)\n"
    "0220816831 (من أي موبايل)\n"
    "📞 المجلس القومي للصحة النفسية: 20818102\n\n"
    "الخطوط دي شغالة طول اليوم وبسرية تامة. ممكن كمان تكلم حد قريب منك تثق فيه دلوقتي.\n"
    "أنا هنا أفضل أسمعك، بس مهم جدًا تكلم حد متخصص كمان."
)

BASE_SYSTEM_PROMPT = """
أنت مساعد داعم نفسيًا (Companion) اسمه "أنيس"، بيتكلم مع المستخدم بالعربي (لهجة مصرية بسيطة ودافية).
دورك إنك تسمع، تتعاطف، وتساعد الشخص يرتب أفكاره ومشاعره - مش إنك تكون بديل عن معالج نفسي مرخّص.

قواعد أساسية لازم تتبعها دايمًا:
1. متشخصش أي حالة نفسية للمستخدم (زي اكتئاب، قلق، اضطراب...) حتى لو حسيت إنها كده. اوصف الشعور من غير ما تحط تسمية طبية.
2. لو حسيت إن الشخص في خطر (أفكار إيذاء نفس، انتحار)، وجهه فورًا للخط الساخن ولخصوصية شخص يثق فيه، وابقى هادي وداعم مش مستجوب.
3. متكررش كلام المستخدم السلبي بطريقة تكبره أو تعمقه أكتر. سمعه لكن وجهه لمسار إيجابي.
4. لو المستخدم بيسأل عن حاجة تقنية زي جرعات أدوية أو طرق إيذاء نفس، امنعها ووجهه لطبيب/مختص.
5. ذكّره بلطف بين فترة وفترة إن الكلام مع معالج نفسي حقيقي مهم لو استمرت الحالة.
6. خليك مختصر ودافئ، مش محاضرات طويلة. جملتين تلاتة كل مرة عادةً، واسأل سؤال واحد بس لو محتاج توضيح.
7. لو حد سألك حاجة برا نطاق الدعم النفسي (زي أسئلة عامة)، جاوب بشكل طبيعي وودود.
8. استخدم أي معلومات عن المستخدم (اسمه، مواضيعه المتكررة) اللي هتيجيلك في سياق "ملف المستخدم" عشان ردك يكون شخصي أكتر، من غير ما تكرر المعلومات دي بشكل غريب أو متكلف.
"""

# ================= قاعدة البيانات =================

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        chat_id INTEGER PRIMARY KEY,
        name TEXT,
        profile_summary TEXT DEFAULT '',
        message_count INTEGER DEFAULT 0,
        created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id INTEGER,
        role TEXT,
        content TEXT,
        timestamp TEXT
    );
    CREATE TABLE IF NOT EXISTS moods (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id INTEGER,
        score INTEGER,
        timestamp TEXT
    );
    """)
    conn.commit()
    conn.close()


def ensure_user(chat_id: int):
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE chat_id = ?", (chat_id,)).fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO users (chat_id, name, profile_summary, message_count, created_at) VALUES (?, '', '', 0, ?)",
            (chat_id, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
    conn.close()


def save_message(chat_id: int, role: str, content: str):
    conn = get_db()
    conn.execute(
        "INSERT INTO messages (chat_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
        (chat_id, role, content, datetime.now(timezone.utc).isoformat()),
    )
    if role == "user":
        conn.execute(
            "UPDATE users SET message_count = message_count + 1 WHERE chat_id = ?",
            (chat_id,),
        )
    conn.commit()
    conn.close()


def get_recent_messages(chat_id: int, limit: int = MAX_HISTORY_MESSAGES):
    conn = get_db()
    rows = conn.execute(
        "SELECT role, content FROM messages WHERE chat_id = ? ORDER BY id DESC LIMIT ?",
        (chat_id, limit),
    ).fetchall()
    conn.close()
    rows = list(reversed(rows))
    return [{"role": r["role"], "content": r["content"]} for r in rows]


def get_user_profile(chat_id: int):
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE chat_id = ?", (chat_id,)).fetchone()
    conn.close()
    return row


def update_user_profile(chat_id: int, profile_summary: str):
    conn = get_db()
    conn.execute(
        "UPDATE users SET profile_summary = ? WHERE chat_id = ?",
        (profile_summary, chat_id),
    )
    conn.commit()
    conn.close()


def set_user_name(chat_id: int, name: str):
    conn = get_db()
    conn.execute("UPDATE users SET name = ? WHERE chat_id = ?", (name, chat_id))
    conn.commit()
    conn.close()


def save_mood(chat_id: int, score: int):
    conn = get_db()
    conn.execute(
        "INSERT INTO moods (chat_id, score, timestamp) VALUES (?, ?, ?)",
        (chat_id, score, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    conn.close()


def get_moods(chat_id: int, limit: int = 30):
    conn = get_db()
    rows = conn.execute(
        "SELECT score, timestamp FROM moods WHERE chat_id = ? ORDER BY id DESC LIMIT ?",
        (chat_id, limit),
    ).fetchall()
    conn.close()
    return list(reversed(rows))


def contains_crisis_keyword(text: str) -> bool:
    text_lower = text.lower()
    return any(keyword in text_lower for keyword in CRISIS_KEYWORDS)


# ================= Gemini: توليد الرد =================

def call_gemini(system_prompt: str, history: list) -> str:
    """history هي قايمة dicts فيها role و content (بنفس شكل رسائل Claude)."""
    model = genai.GenerativeModel(
        model_name=GEMINI_MODEL_NAME,
        system_instruction=system_prompt,
    )
    # Gemini بيستخدم "user" و "model" بدل "user" و "assistant"
    gemini_history = []
    for m in history[:-1]:
        role = "user" if m["role"] == "user" else "model"
        gemini_history.append({"role": role, "parts": [m["content"]]})

    chat = model.start_chat(history=gemini_history)
    last_message = history[-1]["content"]
    response = chat.send_message(last_message)
    return response.text


# ================= تحديث الملف الشخصي بالذكاء الاصطناعي =================

def build_personalized_system_prompt(chat_id: int) -> str:
    user = get_user_profile(chat_id)
    extra = ""
    if user and user["name"]:
        extra += f"\nاسم المستخدم: {user['name']}."
    if user and user["profile_summary"]:
        extra += f"\nملاحظات عن المستخدم من محادثات سابقة: {user['profile_summary']}"
    return BASE_SYSTEM_PROMPT + extra


def maybe_update_profile(chat_id: int):
    user = get_user_profile(chat_id)
    if not user or user["message_count"] % PROFILE_UPDATE_EVERY != 0:
        return

    history = get_recent_messages(chat_id, limit=30)
    if not history:
        return

    convo_text = "\n".join(f"{m['role']}: {m['content']}" for m in history)
    try:
        model = genai.GenerativeModel(
            model_name=GEMINI_MODEL_NAME,
            system_instruction=(
                "لخّص المستخدم من المحادثة دي في 2-3 جمل بس: اسمه لو قاله، "
                "المواضيع أو المشاعر المتكررة عنده، وأي حاجة مهمة تساعد في دعمه بشكل شخصي أكتر. "
                "رد بالملخص مباشرة من غير مقدمات."
            ),
        )
        response = model.generate_content(convo_text)
        summary = response.text.strip()
        if summary:
            update_user_profile(chat_id, summary)
    except Exception as e:
        logger.error(f"Profile update error: {e}")


# ================= أوامر البوت =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    ensure_user(chat_id)
    await update.message.reply_text(
        "أهلاً بيك 💙 أنا أنيس، هنا أسمعك وأساعدك ترتب أفكارك.\n"
        "ملحوظة مهمة: أنا مش بديل عن معالج نفسي متخصص، لو محتاج مساعدة عاجلة كلم مختص فورًا.\n\n"
        "قولّي إسمك إيه عشان أعرف أكلمك بيه؟"
    )


async def mood_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [
            InlineKeyboardButton("😞 1", callback_data="mood_1"),
            InlineKeyboardButton("🙁 2", callback_data="mood_2"),
            InlineKeyboardButton("😐 3", callback_data="mood_3"),
            InlineKeyboardButton("🙂 4", callback_data="mood_4"),
            InlineKeyboardButton("😄 5", callback_data="mood_5"),
        ]
    ]
    await update.message.reply_text(
        "إزاي حاسس النهاردة من 1 لـ 5؟",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def mood_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    score = int(query.data.split("_")[1])
    save_mood(chat_id, score)
    await query.edit_message_text(f"تمام، سجلت مزاجك النهاردة: {score}/5 🙏\nتقدر تشوف تطور مزاجك بـ /chart")


async def chart_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    moods = get_moods(chat_id)
    if len(moods) < 2:
        await update.message.reply_text(
            "لسه معنديش بيانات كفاية عشان أرسملك تطور مزاجك. سجّل مزاجك كل يوم بـ /mood 🙂"
        )
        return

    dates = [datetime.fromisoformat(m["timestamp"]).strftime("%m-%d %H:%M") for m in moods]
    scores = [m["score"] for m in moods]

    plt.figure(figsize=(8, 4))
    plt.plot(dates, scores, marker="o", color="#5B8FF9", linewidth=2)
    plt.ylim(0.5, 5.5)
    plt.yticks([1, 2, 3, 4, 5])
    plt.xticks(rotation=45, ha="right")
    plt.title("تطور مزاجك بمرور الوقت")
    plt.tight_layout()

    chart_path = f"/tmp/mood_chart_{chat_id}.png"
    plt.savefig(chart_path)
    plt.close()

    with open(chart_path, "rb") as f:
        await update.message.reply_photo(photo=f, caption="ده تطور مزاجك آخر فترة 📊")


# ================= الرسائل العادية =================

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_text = update.message.text
    ensure_user(chat_id)

    user = get_user_profile(chat_id)
    if user and not user["name"] and user["message_count"] == 0 and len(user_text.split()) <= 4:
        set_user_name(chat_id, user_text.strip())
        await update.message.reply_text(f"تشرفت بيك يا {user_text.strip()} 💙 احكيلي، عايز تتكلم عن إيه؟")
        save_message(chat_id, "user", user_text)
        return

    if contains_crisis_keyword(user_text):
        await update.message.reply_text(CRISIS_MESSAGE)

    save_message(chat_id, "user", user_text)
    history = get_recent_messages(chat_id)

    try:
        reply_text = call_gemini(build_personalized_system_prompt(chat_id), history)
    except Exception as e:
        logger.error(f"Error calling Gemini API: {e}")
        reply_text = "معلش، حصلت مشكلة تقنية بسيطة. جرب تاني كمان شوية 🙏"

    save_message(chat_id, "assistant", reply_text)
    maybe_update_profile(chat_id)

    await update.message.reply_text(reply_text)


def main():
    init_db()
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("mood", mood_command))
    app.add_handler(CommandHandler("chart", chart_command))
    app.add_handler(CallbackQueryHandler(mood_callback, pattern="^mood_"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info("Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
