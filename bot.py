import os
import random
import asyncio
import sqlite3
import logging
from datetime import datetime, timezone, timedelta, time as dtime
from zoneinfo import ZoneInfo
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
CAIRO_TZ = ZoneInfo("Africa/Cairo")

genai.configure(api_key=GEMINI_API_KEY)
GEMINI_MODEL_NAME = "gemini-3.1-flash-lite"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MAX_HISTORY_MESSAGES = 20
PROFILE_UPDATE_EVERY = 8
INACTIVITY_DAYS = 3  # بعد كام يوم صمت نبعت تذكير

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
أنت مساعد داعم نفسيًا (Companion) اسمه "أنيس"، بيتكلم مع المستخدم بعامية مصرية طبيعية جدًا، زي ما صاحب مقرّب بيكلمك مش زي شات بوت رسمي.
دورك إنك تسمع، تتعاطف، وتساعد الشخص يرتب أفكاره ومشاعره - مش إنك تكون بديل عن معالج نفسي مرخّص.

أسلوب الكلام:
- اتكلم عامية مصرية حقيقية زي كلام الناس بالظبط، مش عربي فصحى ومش عامية متكلفة. استخدم كلمات زي "طب"، "يعني"، "بجد"، "معلش" في مكانها الطبيعي.
- تجنب الجمل الرسمية أو اللي شكلها "رد بوت" زي "أنا هنا لمساعدتك" أو "يسعدني أن أساعدك" - ده بيحس الناس إنهم بيكلموا آلة.
- ماتكررش نفس الجمل الترحيبية أو التطمينية كل شوية، خليك متنوع زي أي حد بيتكلم عادي.
- لو حد سألك صراحة "إنت بوت؟" أو "إنت AI؟" أو أي سؤال مباشر عن طبيعتك، قوله الحقيقة بصراحة ووضوح - إنك مساعد ذكاء اصطناعي - من غير ما تدّعي إنك إنسان حقيقي. الصدق هنا أهم من أي حاجة تانية.

قواعد أساسية لازم تتبعها دايمًا:
1. متشخصش أي حالة نفسية للمستخدم (زي اكتئاب، قلق، اضطراب...) حتى لو حسيت إنها كده. اوصف الشعور من غير ما تحط تسمية طبية.
2. لو حسيت إن الشخص في خطر (أفكار إيذاء نفس، انتحار)، وجهه فورًا للخط الساخن ولخصوصية شخص يثق فيه، وابقى هادي وداعم مش مستجوب.
3. متكررش كلام المستخدم السلبي بطريقة تكبره أو تعمقه أكتر. سمعه لكن وجهه لمسار إيجابي.
4. لو المستخدم بيسأل عن حاجة تقنية زي جرعات أدوية أو طرق إيذاء نفس، امنعها ووجهه لطبيب/مختص.
5. ذكّره بلطف بين فترة وفترة إن الكلام مع معالج نفسي حقيقي مهم لو استمرت الحالة.
6. خليك مختصر ودافئ، مش محاضرات طويلة. جملتين تلاتة كل مرة عادةً، واسأل سؤال واحد بس لو محتاج توضيح.
7. لو حد سألك حاجة برا نطاق الدعم النفسي والمشاعر (زي أسئلة عامة، واجبات مدرسية، برمجة، أخبار، وصفات طعام، إلخ)، اعتذر بلطف وقول إن دورك محصور في الاستماع والدعم النفسي بس، وارجع بلطف تسأله عن حاله أو عن اللي في بالكم. متجاوبش على السؤال الخارجي حتى لو كان بسيط.
8. استخدم أي معلومات عن المستخدم (اسمه، مواضيعه المتكررة) اللي هتيجيلك في سياق "ملف المستخدم" عشان ردك يكون شخصي أكتر، من غير ما تكرر المعلومات دي بشكل غريب أو متكلف.
"""

# محتوى ثابت لتمارين ولعبة تغيير المود (من غير الحاجة لاتصال إنترنت وقت التشغيل)
JOKES = [
    "واحد سأل صاحبه: إنت بتحب القطط ولا الكلاب؟ قاله: بحب الفلوس 😂",
    "ليه الكمبيوتر راح الدكتور؟ عشان كان عنده فيروس 🖥️😅",
    "واحد قال لصاحبه: عارف إن أغلى حاجة في الدنيا هي الوقت؟ قاله: لأ ده الوقت مجاني، بس بينفد بسرعة 😄",
    "مرة واحد بيتعلم يسبح في المطبخ.. عشان لو غرق يلاقي أكل جنبه 😂",
]

GRATEFUL_PROMPT = (
    "تعالى نجرب حاجة بسيطة تهون عليك 🌿\n"
    "قولّي 3 حاجات - كبيرة أو صغيرة - إنت شاكر عليها النهاردة أو حصلت معاك وعجبتك.\n"
    "ابدأ بأي حاجة تيجي في بالك، مفيش إجابة غلط."
)

GROUNDING_TEXT = (
    "طيب خلينا نعمل تمرين بسيط اسمه 5-4-3-2-1، بيساعد لما تحس إنك متوتر أو دماغك مشتتة:\n\n"
    "👀 5 حاجات شايفها حواليك دلوقتي\n"
    "✋ 4 حاجات تقدر تلمسها\n"
    "👂 3 حاجات سامعها\n"
    "👃 2 ريحة قدرت تشمها\n"
    "👅 1 حاجة تقدر تدوقها\n\n"
    "خد وقتك، وقولّي لما تخلص أو حتى لو عايز تحكيلي إيه اللي شفته."
)

MOTIVATIONAL_QUOTES = [
    "كل يوم بتعدّيه بمشاعرك دي، إنت بتثبت إنك أقوى مما تتخيل. 🌱",
    "مفيش حد بيبقى قوي طول الوقت، وده طبيعي جدًا. المهم إنك مكملش لوحدك. 💙",
    "خطوة صغيرة النهاردة أحسن من مفيش خطوة خالص. 🌤️",
    "مشاعرك مش عبء على حد، هي جزء منك وليها الحق تتسمع. 🤍",
    "بكرة يوم جديد، وإنت مسموح تاخد وقتك عشان توصله. ✨",
]

BASE_SYSTEM_PROMPT_EXTRA_GAMES_HINT = (
    "\nملحوظة: لو المستخدم قال إنه زهقان أو محتاج حاجة تلهيه أو تهون عليه، ممكن تقترح عليه يجرب أوامر "
    "البوت زي /gratitude أو /grounding أو /joke."
)
BASE_SYSTEM_PROMPT += BASE_SYSTEM_PROMPT_EXTRA_GAMES_HINT


# ================= قاعدة البيانات =================

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _add_column_if_missing(conn, table, column, coltype):
    cols = [r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")


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
    # أعمدة إضافية لميزات التفاعل التلقائي (check-in / تذكير / ملخص أسبوعي)
    _add_column_if_missing(conn, "users", "private_chat_id", "INTEGER")
    _add_column_if_missing(conn, "users", "last_active_at", "TEXT")
    _add_column_if_missing(conn, "users", "last_reminder_at", "TEXT")
    conn.commit()
    conn.close()


def ensure_user(user_id: int, private_chat_id: int = None):
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE chat_id = ?", (user_id,)).fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO users (chat_id, name, profile_summary, message_count, created_at, private_chat_id, last_active_at) "
            "VALUES (?, '', '', 0, ?, ?, ?)",
            (user_id, datetime.now(timezone.utc).isoformat(), private_chat_id, datetime.now(timezone.utc).isoformat()),
        )
    elif private_chat_id is not None:
        conn.execute("UPDATE users SET private_chat_id = ? WHERE chat_id = ?", (private_chat_id, user_id))
    conn.commit()
    conn.close()


def touch_last_active(user_id: int):
    conn = get_db()
    conn.execute(
        "UPDATE users SET last_active_at = ? WHERE chat_id = ?",
        (datetime.now(timezone.utc).isoformat(), user_id),
    )
    conn.commit()
    conn.close()


def save_message(user_id: int, role: str, content: str):
    conn = get_db()
    conn.execute(
        "INSERT INTO messages (chat_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
        (user_id, role, content, datetime.now(timezone.utc).isoformat()),
    )
    if role == "user":
        conn.execute(
            "UPDATE users SET message_count = message_count + 1 WHERE chat_id = ?",
            (user_id,),
        )
    conn.commit()
    conn.close()


def get_recent_messages(user_id: int, limit: int = MAX_HISTORY_MESSAGES):
    conn = get_db()
    rows = conn.execute(
        "SELECT role, content FROM messages WHERE chat_id = ? ORDER BY id DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()
    conn.close()
    rows = list(reversed(rows))
    return [{"role": r["role"], "content": r["content"]} for r in rows]


def get_user_profile(user_id: int):
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE chat_id = ?", (user_id,)).fetchone()
    conn.close()
    return row


def update_user_profile(user_id: int, profile_summary: str):
    conn = get_db()
    conn.execute("UPDATE users SET profile_summary = ? WHERE chat_id = ?", (profile_summary, user_id))
    conn.commit()
    conn.close()


def set_user_name(user_id: int, name: str):
    conn = get_db()
    conn.execute("UPDATE users SET name = ? WHERE chat_id = ?", (name, user_id))
    conn.commit()
    conn.close()


def save_mood(user_id: int, score: int):
    conn = get_db()
    conn.execute(
        "INSERT INTO moods (chat_id, score, timestamp) VALUES (?, ?, ?)",
        (user_id, score, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    conn.close()


def get_moods(user_id: int, limit: int = 30):
    conn = get_db()
    rows = conn.execute(
        "SELECT score, timestamp FROM moods WHERE chat_id = ? ORDER BY id DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()
    conn.close()
    return list(reversed(rows))


def get_all_private_users():
    """كل المستخدمين اللي بدأوا شات خاص مع البوت (عشان نبعتلهم رسائل تلقائية)."""
    conn = get_db()
    rows = conn.execute(
        "SELECT chat_id, name, private_chat_id, last_active_at, last_reminder_at FROM users WHERE private_chat_id IS NOT NULL"
    ).fetchall()
    conn.close()
    return rows


def mark_reminder_sent(user_id: int):
    conn = get_db()
    conn.execute(
        "UPDATE users SET last_reminder_at = ? WHERE chat_id = ?",
        (datetime.now(timezone.utc).isoformat(), user_id),
    )
    conn.commit()
    conn.close()


def contains_crisis_keyword(text: str) -> bool:
    text_lower = text.lower()
    return any(keyword in text_lower for keyword in CRISIS_KEYWORDS)


BOT_MENTION_WORDS = ["أنيس", "انيس", "aneesbot", "anees"]


def message_mentions_bot(text: str) -> bool:
    text_lower = text.lower()
    return any(word.lower() in text_lower for word in BOT_MENTION_WORDS)


# ================= Gemini =================

def call_gemini(system_prompt: str, history: list) -> str:
    model = genai.GenerativeModel(model_name=GEMINI_MODEL_NAME, system_instruction=system_prompt)
    gemini_history = []
    for m in history[:-1]:
        role = "user" if m["role"] == "user" else "model"
        gemini_history.append({"role": role, "parts": [m["content"]]})
    chat = model.start_chat(history=gemini_history)
    last_message = history[-1]["content"]
    response = chat.send_message(last_message)
    return response.text


def build_personalized_system_prompt(user_id: int) -> str:
    user = get_user_profile(user_id)
    extra = ""
    if user and user["name"]:
        extra += f"\nاسم المستخدم: {user['name']}."
    if user and user["profile_summary"]:
        extra += f"\nملاحظات عن المستخدم من محادثات سابقة: {user['profile_summary']}"
    return BASE_SYSTEM_PROMPT + extra


def maybe_update_profile(user_id: int):
    user = get_user_profile(user_id)
    if not user or user["message_count"] % PROFILE_UPDATE_EVERY != 0:
        return
    history = get_recent_messages(user_id, limit=30)
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
            update_user_profile(user_id, summary)
    except Exception as e:
        logger.error(f"Profile update error: {e}")


# ================= أوامر البوت الأساسية =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    is_private = update.effective_chat.type == "private"
    ensure_user(user_id, private_chat_id=update.effective_chat.id if is_private else None)
    await update.message.reply_text(
        "أهلاً بيك 💙 أنا أنيس.\n"
        "ملحوظة مهمة: أنا مساعد ذكاء اصطناعي مش بديل عن معالج نفسي متخصص، لو محتاج مساعدة عاجلة كلم مختص فورًا.\n\n"
        "قولّي إسمك إيه؟"
    )


async def mood_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[
        InlineKeyboardButton("😞 1", callback_data="mood_1"),
        InlineKeyboardButton("🙁 2", callback_data="mood_2"),
        InlineKeyboardButton("😐 3", callback_data="mood_3"),
        InlineKeyboardButton("🙂 4", callback_data="mood_4"),
        InlineKeyboardButton("😄 5", callback_data="mood_5"),
    ]]
    await update.message.reply_text("إزاي حاسس النهاردة من 1 لـ 5؟", reply_markup=InlineKeyboardMarkup(keyboard))


async def mood_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    score = int(query.data.split("_")[1])
    save_mood(user_id, score)
    quote = random.choice(MOTIVATIONAL_QUOTES)
    await query.edit_message_text(
        f"تمام، سجلت مزاجك النهاردة: {score}/5 🙏\n\n"
        f"┏━━━━━━━━━━━━━┓\n{quote}\n┗━━━━━━━━━━━━━┛\n\n"
        f"تقدر تشوف تطور مزاجك بـ /chart"
    )


async def chart_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    moods = get_moods(user_id)
    if len(moods) < 2:
        await update.message.reply_text("لسه معنديش بيانات كفاية عشان أرسملك تطور مزاجك. سجّل مزاجك كل يوم بـ /mood 🙂")
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
    chart_path = f"/tmp/mood_chart_{user_id}.png"
    plt.savefig(chart_path)
    plt.close()
    with open(chart_path, "rb") as f:
        await update.message.reply_photo(photo=f, caption="ده تطور مزاجك آخر فترة 📊")


# ================= تمارين ولعبة تغيير المود =================

async def games_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🌬️ تمرين تنفس", callback_data="game_breathe")],
        [InlineKeyboardButton("🌿 تمرين امتنان", callback_data="game_gratitude")],
        [InlineKeyboardButton("🧘 تمرين تهدئة (5-4-3-2-1)", callback_data="game_grounding")],
        [InlineKeyboardButton("😄 نكتة تهون عليك", callback_data="game_joke")],
    ]
    await update.message.reply_text("عايز نعمل إيه دلوقتي؟", reply_markup=InlineKeyboardMarkup(keyboard))


async def games_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    choice = query.data
    if choice == "game_breathe":
        await run_breathing_exercise(update, context, use_query=True)
    elif choice == "game_gratitude":
        await query.message.reply_text(GRATEFUL_PROMPT)
    elif choice == "game_grounding":
        await query.message.reply_text(GROUNDING_TEXT)
    elif choice == "game_joke":
        await query.message.reply_text(random.choice(JOKES))


async def gratitude_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(GRATEFUL_PROMPT)


async def grounding_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(GROUNDING_TEXT)


async def joke_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(random.choice(JOKES))


async def run_breathing_exercise(update: Update, context: ContextTypes.DEFAULT_TYPE, use_query: bool = False):
    send = update.callback_query.message.reply_text if use_query else update.message.reply_text
    await send("خلينا ناخد نفس مع بعض 🌬️ اتبعني:")
    await asyncio.sleep(1)
    await send("شهيق ببطء من الأنف... 4 ثواني 🫁")
    await asyncio.sleep(4)
    await send("احبس نفسك... 4 ثواني ⏸️")
    await asyncio.sleep(4)
    await send("زفير ببطء من بقك... 6 ثواني 💨")
    await asyncio.sleep(6)
    await send("تمام جدًا 🙌 كرر الدورة دي 3-4 مرات لوحدك بنفس الإيقاع، هتحس بفرق حقيقي.")


async def breathe_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await run_breathing_exercise(update, context, use_query=False)


# ================= مهام مجدولة: check-in يومي / تذكير / ملخص أسبوعي =================

async def daily_checkin_job(context: ContextTypes.DEFAULT_TYPE):
    for user in get_all_private_users():
        name_part = f" يا {user['name']}" if user["name"] else ""
        try:
            await context.bot.send_message(
                chat_id=user["private_chat_id"],
                text=f"صباح الخير{name_part} ☀️ إزاي حاسس النهاردة؟ لو حابب سجل مزاجك بـ /mood",
            )
        except Exception as e:
            logger.error(f"Check-in send error for {user['chat_id']}: {e}")


async def inactivity_reminder_job(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now(timezone.utc)
    for user in get_all_private_users():
        if not user["last_active_at"]:
            continue
        last_active = datetime.fromisoformat(user["last_active_at"])
        days_silent = (now - last_active).days
        already_reminded_recently = False
        if user["last_reminder_at"]:
            last_reminder = datetime.fromisoformat(user["last_reminder_at"])
            already_reminded_recently = (now - last_reminder).days < INACTIVITY_DAYS
        if days_silent >= INACTIVITY_DAYS and not already_reminded_recently:
            name_part = f" يا {user['name']}" if user["name"] else ""
            try:
                await context.bot.send_message(
                    chat_id=user["private_chat_id"],
                    text=f"افتقدناك{name_part} 💙 عامل إيه؟ لو حابب تحكيلي عن أخبارك أنا هنا.",
                )
                mark_reminder_sent(user["chat_id"])
            except Exception as e:
                logger.error(f"Reminder send error for {user['chat_id']}: {e}")


async def weekly_summary_job(context: ContextTypes.DEFAULT_TYPE):
    if datetime.now(CAIRO_TZ).weekday() != 6:  # 6 = الأحد
        return
    for user in get_all_private_users():
        moods = get_moods(user["chat_id"], limit=7)
        if not moods:
            continue
        scores = [m["score"] for m in moods]
        avg = sum(scores) / len(scores)
        name_part = f" يا {user['name']}" if user["name"] else ""
        try:
            await context.bot.send_message(
                chat_id=user["private_chat_id"],
                text=(
                    f"ملخص أسبوعك{name_part} 📊\n"
                    f"سجّلت مزاجك {len(scores)} مرة، ومتوسط مزاجك كان {avg:.1f}/5.\n"
                    f"شوف تفاصيل أكتر بـ /chart 💙"
                ),
            )
        except Exception as e:
            logger.error(f"Weekly summary send error for {user['chat_id']}: {e}")


# ================= الرسائل العادية =================

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    is_group = update.effective_chat.type in ("group", "supergroup")
    is_private = update.effective_chat.type == "private"
    user_text = update.message.text or ""

    if is_group:
        replied_to_bot = (
            update.message.reply_to_message is not None
            and update.message.reply_to_message.from_user is not None
            and update.message.reply_to_message.from_user.id == context.bot.id
        )
        if not (message_mentions_bot(user_text) or replied_to_bot):
            return

    user_id = update.effective_user.id
    ensure_user(user_id, private_chat_id=update.effective_chat.id if is_private else None)
    touch_last_active(user_id)

    user = get_user_profile(user_id)
    if is_private and user and not user["name"] and user["message_count"] == 0 and len(user_text.split()) <= 4:
        set_user_name(user_id, user_text.strip())
        await update.message.reply_text(f"تشرفت بيك يا {user_text.strip()} 💙 احكيلي، عايز تتكلم عن إيه؟")
        save_message(user_id, "user", user_text)
        return

    if contains_crisis_keyword(user_text):
        await update.message.reply_text(CRISIS_MESSAGE)

    save_message(user_id, "user", user_text)
    history = get_recent_messages(user_id)

    try:
        reply_text = call_gemini(build_personalized_system_prompt(user_id), history)
    except Exception as e:
        logger.error(f"Error calling Gemini API: {e}")
        reply_text = "معلش، حصلت مشكلة تقنية بسيطة. جرب تاني كمان شوية 🙏"

    save_message(user_id, "assistant", reply_text)
    maybe_update_profile(user_id)

    await update.message.reply_text(reply_text)


def main():
    init_db()
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("mood", mood_command))
    app.add_handler(CommandHandler("chart", chart_command))
    app.add_handler(CommandHandler("games", games_command))
    app.add_handler(CommandHandler("gratitude", gratitude_command))
    app.add_handler(CommandHandler("grounding", grounding_command))
    app.add_handler(CommandHandler("joke", joke_command))
    app.add_handler(CommandHandler("breathe", breathe_command))

    app.add_handler(CallbackQueryHandler(mood_callback, pattern="^mood_"))
    app.add_handler(CallbackQueryHandler(games_callback, pattern="^game_"))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # المهام المجدولة (محتاجة: pip install "python-telegram-bot[job-queue]")
    job_queue = app.job_queue
    job_queue.run_daily(daily_checkin_job, time=dtime(hour=9, minute=0, tzinfo=CAIRO_TZ))
    job_queue.run_daily(inactivity_reminder_job, time=dtime(hour=18, minute=0, tzinfo=CAIRO_TZ))
    job_queue.run_daily(weekly_summary_job, time=dtime(hour=20, minute=0, tzinfo=CAIRO_TZ))

    logger.info("Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
