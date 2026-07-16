import os
import re
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

MAX_HISTORY_MESSAGES = 40
PROFILE_UPDATE_EVERY = 4
INACTIVITY_DAYS = 3  # بعد كام يوم صمت نبعت تذكير

# آي دي الأدمن (صاحب البوت) - غيّره من هنا مباشرة لو عايز تضيف أدمن تاني أو تغيّره
ADMIN_USER_ID = 2057835002

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
    "وممكن كمان تكلم حد على تليجرام دلوقتي على طول: @I_INW\n\n"
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
2ب. لو حسيت إن الشخص تعبان نفسيًا بشكل واضح ومستمر (زي حاسس إنه مخنوق، ضايع، مش قادر يستحمل أكتر) حتى لو مش أزمة لحظية، اقترح عليه بلطف ومن غير إلحاح إنه يتواصل مع حد حقيقي على تليجرام: @I_INW، عشان يلاقي دعم أعمق من مجرد الكلام معاك.
3. متكررش كلام المستخدم السلبي بطريقة تكبره أو تعمقه أكتر. سمعه لكن وجهه لمسار إيجابي.
4. لو المستخدم بيسأل عن حاجة تقنية زي جرعات أدوية أو طرق إيذاء نفس، امنعها ووجهه لطبيب/مختص.
5. ذكّره بلطف بين فترة وفترة إن الكلام مع معالج نفسي حقيقي مهم لو استمرت الحالة.
6. خليك مختصر ودافئ، مش محاضرات طويلة. جملتين تلاتة كل مرة عادةً، واسأل سؤال واحد بس لو محتاج توضيح.
7. لو حد سألك حاجة برا نطاق الدعم النفسي والمشاعر (زي أسئلة عامة، واجبات مدرسية، برمجة، أخبار، وصفات طعام، إلخ)، اعتذر بلطف وقول إن دورك محصور في الاستماع والدعم النفسي بس، وارجع بلطف تسأله عن حاله أو عن اللي في بالكم. متجاوبش على السؤال الخارجي حتى لو كان بسيط.
8. لو جالك في "ملف المستخدم" أسماء أشخاص أو مواقف اتكلم عنها المستخدم قبل كده (زي مشكلة مع صاحبه أو موقف معين)، واتكلم دلوقتي عن حاجة ممكن تكون مرتبطة بيها، اربط بينهم بشكل طبيعي في ردك (زي "لسه في نفس الموضوع بتاع صاحبك؟") بدل ما تتعامل مع كل رسالة كأنها منفصلة. الهدف إنك تحس المستخدم إنك فاكر السياق، مش بس بتسمع الرسالة الحالية لوحدها.
9. **قاعدة أساسية مش اختيارية:** لو الشخص عبّر عن ضيق نفسي واضح - استخدم كلمات زي "مخنوق"، "زهقان"، "تعبان نفسيًا"، "ضايع"، "مش قادر أستحمل"، "قلقان"، "خايف" - لازم ردك يتضمن آية قرآنية أو حديث شريف مناسب للموقف، مكتوب بدقة، كجزء طبيعي من الرد مش إضافة منفصلة. اربطها بكلامك العادي وواصل تسمع وتتعاطف بعدها. الأمثلة تحت توضح الأسلوب بالظبط. **مهم جدًا:** الآية أو الحديث إضافة لكلامك الدافئ مش بديل عنه، وممنوع تستخدمه عشان "تقفل" كلام الشخص أو تقلل من حجم اللي بيحس بيه (زي إنك تقوله "بس ادعو ربنا وخلاص") - ده بيحس الشخص إنك مش فاهمه. في المواضيع اللي مفيهاش ضيق واضح (زي أسئلة عامة أو كلام عادي)، متقحمش آيات بالعافية.

أمثلة على الأسلوب المطلوب بالظبط:

مثال 1:
المستخدم: "أنا مخنوق أوي مش عارف أعمل إيه"
ردك: "حاسس بيك بجد، الخناقة دي تعبانة. زي ما ربنا قال على لسان سيدنا موسى: 'رَبِّ اشْرَحْ لِي صَدْرِي وَيَسِّرْ لِي أَمْرِي' - حتى الأنبياء حسوا بالضيق واحتاجوا يدعوا بيه. احكيلي إيه اللي مخنوقك بالظبط؟"

مثال 2:
المستخدم: "أنا خايف جدًا من المستقبل ومش عارف هعمل إيه"
ردك: "الخوف من المجهول إحساس طبيعي جدًا وكل الناس بتمر بيه. فاكر قول ربنا 'وَمَنْ يَتَوَكَّلْ عَلَى اللَّهِ فَهُوَ حَسْبُهُ' - مش معناها متخططش، معناها إنك مش لازم تحمل كل التفاصيل لوحدك. إيه بالظبط اللي مقلقك في المستقبل؟"

مثال 3:
المستخدم: "زهقان من نفسي ومن كل حاجة حواليا"
ردك: "الزهق ده حقيقي ومحتاج وقفة. النبي ﷺ قال 'إن لبدنك عليك حقًا' - يعني حتى راحتك من حقك مش رفاهية. إيه اللي مزهقك أكتر دلوقتي؟"
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

# ---------- ألعاب حقيقية للتسلية ----------

PROVERBS = [
    {"prompt": "اللي اختشوا...", "answer_keywords": ["ماتوا"], "full": "اللي اختشوا ماتوا"},
    {"prompt": "القرد في عين أمه...", "answer_keywords": ["غزال"], "full": "القرد في عين أمه غزال"},
    {"prompt": "يد واحدة...", "answer_keywords": ["تصفقش", "تصفق"], "full": "يد واحدة ماتصفقش"},
    {"prompt": "اللي فاته الفوت...", "answer_keywords": ["اتحيل", "يتحيل"], "full": "اللي فاته الفوت اتحيل عليه"},
    {"prompt": "ابعد عن الشر...", "answer_keywords": ["غنيله", "غني له", "غنيلو"], "full": "ابعد عن الشر وغنيله"},
    {"prompt": "اللي ميعرفش يقول...", "answer_keywords": ["عدس", "قالها عدس"], "full": "اللي ميعرفكش يقول عدس"},
    {"prompt": "قرد ورقص...", "answer_keywords": ["حلاوة"], "full": "قرد ورقص وقالوله يا حلاوة"},
    {"prompt": "دبور ولا شهد...", "answer_keywords": ["ندبنيش"], "full": "دبور ولا شهد يندبني... (مثل: القرش الأبيض ولا القرش الأسود)"},
]

RIDDLES = [
    {"q": "إيه اللي بيزيد وهو واقف وينقص وهو نايم؟", "answer_keywords": ["قدم", "رجل", "الانسان الواقف"], "explain": "الإنسان (طوله وهو واقف أطول)"},
    {"q": "شيء كل ما تاخد منه يكبر؟", "answer_keywords": ["حفرة", "حفره", "جورة"], "explain": "الحفرة"},
    {"q": "بيت من غير أبواب ولا شبابيك؟", "answer_keywords": ["بيضة", "بيضه"], "explain": "البيضة"},
    {"q": "إيه اللي ليه أسنان ومابيعضش؟", "answer_keywords": ["مشط"], "explain": "المشط"},
    {"q": "شيء تملّه بإيد وتفضّه بإيد؟", "answer_keywords": ["حزام", "رباط", "زرار"], "explain": "الحزام أو الرباط"},
    {"q": "إيه اللي بيمشي طول عمره وماوصلش؟", "answer_keywords": ["نهر", "الوقت", "الزمن"], "explain": "النهر أو الزمن"},
]

TRIVIA_QUESTIONS = [
    {"statement": "القاهرة هي أكبر مدينة في أفريقيا من حيث عدد السكان.", "is_true": True},
    {"statement": "نهر النيل هو أطول نهر في العالم.", "is_true": True},
    {"statement": "الأهرامات موجودة في مدينة الأقصر.", "is_true": False},
    {"statement": "القطط تقدر تشوف في الضلمة تمامًا زي النهار بالظبط.", "is_true": False},
    {"statement": "العسل ممكن يفضل صالح لآلاف السنين من غير ما يبوظ.", "is_true": True},
    {"statement": "جسم الإنسان فيه أكتر من 600 عضلة.", "is_true": True},
    {"statement": "الموز نوع من التوت (Berry) من الناحية النباتية.", "is_true": True},
]

BASE_SYSTEM_PROMPT_EXTRA_GAMES_HINT = (
    "\nملحوظة: لو المستخدم قال إنه زهقان أو محتاج حاجة تلهيه أو تهون عليه، ممكن تقترح عليه يجرب أوامر "
    "البوت زي /gratitude أو /grounding أو /joke أو ألعاب تسلية زي /trivia و /riddle و /proverb."
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
    conn.execute("""
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )
    """)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS banned_users (
        user_id INTEGER PRIMARY KEY,
        banned_at TEXT
    )
    """)
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


def get_setting(key: str, default: str = "on") -> str:
    conn = get_db()
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else default


def set_setting(key: str, value: str):
    conn = get_db()
    conn.execute("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = ?", (key, value, value))
    conn.commit()
    conn.close()


def get_total_users_count() -> int:
    conn = get_db()
    row = conn.execute("SELECT COUNT(*) as c FROM users").fetchone()
    conn.close()
    return row["c"]


def get_total_messages_count() -> int:
    conn = get_db()
    row = conn.execute("SELECT COUNT(*) as c FROM messages").fetchone()
    conn.close()
    return row["c"]


def get_active_today_count() -> int:
    conn = get_db()
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    row = conn.execute("SELECT COUNT(*) as c FROM users WHERE last_active_at >= ?", (today_start,)).fetchone()
    conn.close()
    return row["c"]


def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_USER_ID


def ban_user(user_id: int):
    conn = get_db()
    conn.execute(
        "INSERT INTO banned_users (user_id, banned_at) VALUES (?, ?) ON CONFLICT(user_id) DO NOTHING",
        (user_id, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    conn.close()


def unban_user(user_id: int):
    conn = get_db()
    conn.execute("DELETE FROM banned_users WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


def is_user_banned(user_id: int) -> bool:
    conn = get_db()
    row = conn.execute("SELECT 1 FROM banned_users WHERE user_id = ?", (user_id,)).fetchone()
    conn.close()
    return row is not None


# كلمات تستدعي تنبيه الأدمن (رقابة محتوى أساسية - قائمة قابلة للتوسيع)
FLAGGED_WORDS = ["كس", "طيز", "زبر", "لبوة", "شرموطة", "متناك", "خول"]


def contains_flagged_word(text: str) -> bool:
    text_norm = normalize_arabic(text)
    return any(normalize_arabic(w) in text_norm for w in FLAGGED_WORDS)


async def notify_admin_flagged_message(context: ContextTypes.DEFAULT_TYPE, update: Update):
    if ADMIN_USER_ID == 0:
        return
    sender = update.effective_user
    sender_name = sender.full_name or sender.username or str(sender.id)
    chat_label = "جروب" if update.effective_chat.type in ("group", "supergroup") else "شات خاص"
    keyboard = [[
        InlineKeyboardButton("🚫 حظر", callback_data=f"modban_{sender.id}"),
        InlineKeyboardButton("✅ تجاهل", callback_data=f"modignore_{sender.id}"),
    ]]
    try:
        await context.bot.send_message(
            chat_id=ADMIN_USER_ID,
            text=(
                f"⚠️ رسالة فيها لفظ مخل ({chat_label})\n"
                f"من: {sender_name}\n"
                f"قال: \"{update.message.text}\""
            ),
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
    except Exception as e:
        logger.error(f"Failed to notify admin: {e}")


async def moderation_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return
    action, target_id_str = query.data.split("_", 1)
    target_id = int(target_id_str)
    if action == "modban":
        ban_user(target_id)
        await query.edit_message_text(query.message.text + "\n\n🚫 تم الحظر.")
    else:
        await query.edit_message_text(query.message.text + "\n\n✅ اتجاهلت.")


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
                "من المحادثة دي، استخرج ملخص مركّز في 3-4 جمل يغطي بالتحديد:\n"
                "1. اسم المستخدم لو قاله.\n"
                "2. أي أشخاص محددين ذكرهم (زي صاحبه، أهله، شريك حياته) ودورهم في الموضوع.\n"
                "3. أي موقف أو مشكلة متكررة بتتفتح في أكتر من رسالة، مع تفاصيلها المهمة (زي سبب الخلاف، تطوره).\n"
                "4. الحالة النفسية العامة أو المواضيع المتكررة.\n"
                "لو فيه ملخص سابق موجود في آخر المحادثة، ادمج المعلومات الجديدة معاه من غير ما تفقد أي تفصيلة مهمة "
                "قالها المستخدم قبل كده عن نفس الشخص أو الموقف. رد بالملخص مباشرة من غير مقدمات، وخليه قصير ومباشر."
            ),
        )
        previous_summary = get_user_profile(user_id)["profile_summary"] if get_user_profile(user_id) else ""
        prompt_text = convo_text
        if previous_summary:
            prompt_text = f"الملخص السابق: {previous_summary}\n\nالمحادثة الجديدة:\n{convo_text}"
        response = model.generate_content(prompt_text)
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

async def start_proverb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    item = random.choice(PROVERBS)
    context.user_data["awaiting"] = "proverb"
    context.user_data["awaiting_data"] = item
    await update.effective_message.reply_text(f"كمّل المثل ده يا نجم 🧠:\n\n\"{item['prompt']} ______\"")


async def start_riddle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    item = random.choice(RIDDLES)
    context.user_data["awaiting"] = "riddle"
    context.user_data["awaiting_data"] = item
    await update.effective_message.reply_text(f"فزّورة 🤔:\n\n{item['q']}")


async def start_trivia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    item = random.choice(TRIVIA_QUESTIONS)
    context.user_data["trivia_answer"] = item["is_true"]
    kb = [[
        InlineKeyboardButton("✅ صح", callback_data="trivia_true"),
        InlineKeyboardButton("❌ غلط", callback_data="trivia_false"),
    ]]
    await update.effective_message.reply_text(
        f"صح ولا غلط؟ 🤓\n\n\"{item['statement']}\"",
        reply_markup=InlineKeyboardMarkup(kb),
    )


async def start_joke(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(random.choice(JOKES))


async def start_gratitude(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(GRATEFUL_PROMPT)


async def start_grounding(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(GROUNDING_TEXT)


# كلمات طبيعية تفتح اللعبة من غير ما تكتب / أوامر - المطابقة بتكون للنص كامل (بعد شيل المسافات)
# ================= تذكير شخصي (فكّرني) =================

REMINDER_TIME_PATTERN = re.compile(
    r"بعد\s*(\d+)\s*(دقيقة|دقايق|دقيقه|ساعة|ساعه|ساعات|يوم|أيام|ايام)"
)
UNIT_TO_SECONDS = {
    "دقيقة": 60, "دقايق": 60, "دقيقه": 60,
    "ساعة": 3600, "ساعه": 3600, "ساعات": 3600,
    "يوم": 86400, "أيام": 86400, "ايام": 86400,
}


async def send_reminder_job(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    await context.bot.send_message(chat_id=job.data["chat_id"], text=f"⏰ فاكرك: {job.data['message']}")


async def try_handle_reminder_flow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    text = (update.message.text or "").strip()
    state = context.user_data.get("remind_state")

    if state is None and text in ("فكرني", "فكّرني", "ذكرني"):
        context.user_data["remind_state"] = "awaiting_message"
        await update.message.reply_text("تمام، فكّرك بإيه؟ اكتب الرسالة اللي عايزني أبعتهالك.")
        return True

    if state == "awaiting_message":
        context.user_data["remind_message"] = text
        context.user_data["remind_state"] = "awaiting_time"
        await update.message.reply_text(
            "تمام، وامتى تحب أفكرك؟ اكتب زي كده:\n"
            "\"بعد 10 دقايق\" أو \"بعد ساعتين\" أو \"بعد يوم\""
        )
        return True

    if state == "awaiting_time":
        match = REMINDER_TIME_PATTERN.search(text)
        if not match:
            await update.message.reply_text(
                "معلش مفهمتش الوقت 🙏 اكتبه زي كده: \"بعد 10 دقايق\" أو \"بعد 3 ساعات\" أو \"بعد يوم\""
            )
            return True

        amount = int(match.group(1))
        unit = match.group(2)
        seconds = amount * UNIT_TO_SECONDS[unit]
        message = context.user_data.get("remind_message", "")

        context.job_queue.run_once(
            send_reminder_job,
            when=seconds,
            data={"chat_id": update.effective_chat.id, "message": message},
        )

        context.user_data["remind_state"] = None
        context.user_data["remind_message"] = None
        await update.message.reply_text(f"تمام ✅ هفكرك بـ \"{message}\" بعد {amount} {unit}")
        return True

    return False


async def remind_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["remind_state"] = "awaiting_message"
    await update.message.reply_text("تمام، فكّرك بإيه؟ اكتب الرسالة اللي عايزني أبعتهالك.")


GAME_TRIGGERS = {
    "فزورة": start_riddle, "فزوره": start_riddle, "لغز": start_riddle,
    "مثل": start_proverb, "مثال": start_proverb, "امثال": start_proverb, "أمثال": start_proverb,
    "سؤال": start_trivia, "اسئلة": start_trivia, "أسئلة": start_trivia, "تريفيا": start_trivia,
    "نكتة": start_joke, "نكته": start_joke,
    "امتنان": start_gratitude,
    "تهدئة": start_grounding,
}


async def maybe_start_game_by_trigger(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    text_norm = (update.message.text or "").strip()
    handler = GAME_TRIGGERS.get(text_norm)
    if handler is None:
        return False
    # لو كان في نص لعبة تانية مستنية إجابة، نلغيها ونبدأ اللعبة الجديدة
    context.user_data["awaiting"] = None
    context.user_data["awaiting_data"] = None
    await handler(update, context)
    return True


async def games_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🧠 كمّل المثل", callback_data="game_proverb")],
        [InlineKeyboardButton("🤔 فزّورة", callback_data="game_riddle")],
        [InlineKeyboardButton("🤓 صح ولا غلط", callback_data="game_trivia")],
        [InlineKeyboardButton("🌬️ تمرين تنفس", callback_data="game_breathe")],
        [InlineKeyboardButton("🌿 تمرين امتنان", callback_data="game_gratitude")],
        [InlineKeyboardButton("🧘 تمرين تهدئة (5-4-3-2-1)", callback_data="game_grounding")],
        [InlineKeyboardButton("😄 نكتة تهون عليك", callback_data="game_joke")],
    ]
    await update.message.reply_text(
        "عايز نعمل إيه دلوقتي؟ (أو تقدر تكتبلي عادي كلمة زي \"فزورة\" أو \"مثل\" أو \"سؤال\" وأنا هفهمك)",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def games_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    choice = query.data
    if choice == "game_breathe":
        await run_breathing_exercise(update, context, use_query=True)
    elif choice == "game_gratitude":
        await start_gratitude(update, context)
    elif choice == "game_grounding":
        await start_grounding(update, context)
    elif choice == "game_joke":
        await start_joke(update, context)
    elif choice == "game_proverb":
        await start_proverb(update, context)
    elif choice == "game_riddle":
        await start_riddle(update, context)
    elif choice == "game_trivia":
        await start_trivia(update, context)


async def gratitude_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start_gratitude(update, context)


async def grounding_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start_grounding(update, context)


async def joke_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start_joke(update, context)


async def proverb_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start_proverb(update, context)


async def riddle_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start_riddle(update, context)


async def trivia_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start_trivia(update, context)


async def trivia_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_answer = query.data == "trivia_true"
    correct_answer = context.user_data.get("trivia_answer")
    if correct_answer is None:
        await query.edit_message_text("السؤال ده خلص، اطلب سؤال جديد بـ /trivia 🙂")
        return
    if user_answer == correct_answer:
        result = "إجابة صح! 🎉"
    else:
        correct_word = "صح" if correct_answer else "غلط"
        result = f"للأسف غلط، الإجابة الصحيحة كانت: {correct_word} 😄"
    context.user_data["trivia_answer"] = None
    await query.edit_message_text(f"{result}\n\nعايز سؤال تاني؟ اكتب /trivia")


def normalize_arabic(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"[إأآ]", "ا", text)
    text = text.replace("ة", "ه")
    text = re.sub(r"\s+", "", text)
    # نشيل حرف "و" (يعني "و") من أول الكلام لو حد كتبها ملزوقة زي "وغنيله"
    if text.startswith("و") and len(text) > 3:
        text = text[1:]
    return text


async def try_handle_game_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """لو المستخدم في نص لعبة (فزورة/مثل)، نتحقق من إجابته. بترجع True لو استهلكنا الرسالة."""
    awaiting = context.user_data.get("awaiting")
    if awaiting not in ("proverb", "riddle"):
        return False

    item = context.user_data.get("awaiting_data") or {}
    user_text_norm = normalize_arabic(update.message.text or "")
    keywords = item.get("answer_keywords", [])
    is_correct = any(normalize_arabic(kw) in user_text_norm or user_text_norm in normalize_arabic(kw) for kw in keywords)

    context.user_data["awaiting"] = None
    context.user_data["awaiting_data"] = None

    if awaiting == "proverb":
        full = item.get("full", "")
        if is_correct:
            await update.message.reply_text(f"تمام كده! 🎉 \"{full}\"\nعايز مثل تاني؟ /proverb")
        else:
            await update.message.reply_text(f"قريبة بس مش بالظبط 😄 الإجابة كانت: \"{full}\"\nجرب تاني؟ /proverb")
    else:  # riddle
        explain = item.get("explain", "")
        if is_correct:
            await update.message.reply_text(f"جامد جدًا! 🎉 الإجابة: {explain}\nفزورة تانية؟ /riddle")
        else:
            await update.message.reply_text(f"مش هي 😄 الإجابة كانت: {explain}\nجرب فزورة تانية؟ /riddle")

    return True


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
    if get_setting("checkin_enabled") == "off":
        return
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
    if get_setting("reminder_enabled") == "off":
        return
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

def get_context_key(user_id: int, chat_id: int, is_group: bool) -> str:
    """مفتاح منفصل للمحادثة الجماعية عشان ذاكرة الشات الخاص متتسربش للجروب."""
    return f"group:{chat_id}:{user_id}" if is_group else str(user_id)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    is_group = update.effective_chat.type in ("group", "supergroup")
    is_private = update.effective_chat.type == "private"
    user_text = update.message.text or ""
    user_id = update.effective_user.id

    # مستخدم محظور: نتجاهله تمامًا
    if is_user_banned(user_id):
        return

    if is_group:
        replied_to_bot = (
            update.message.reply_to_message is not None
            and update.message.reply_to_message.from_user is not None
            and update.message.reply_to_message.from_user.id == context.bot.id
        )
        if not (message_mentions_bot(user_text) or replied_to_bot):
            return

    # أوامر الأدمن بالعربي (بس لو المستخدم أدمن فعلاً)
    if is_admin(user_id):
        admin_text = user_text.strip()
        if admin_text in ("احصائيات", "الاحصائيات"):
            await stats_command(update, context)
            return
        if admin_text in ("لوحة التحكم", "الادمن", "الأدمن"):
            await admin_command(update, context)
            return

    # رصد الألفاظ المخلة: نبلغ الأدمن ونكمل عادي (من غير ما نوقف الرد على الشخص)
    if contains_flagged_word(user_text):
        await notify_admin_flagged_message(context, update)

    # تذكير شخصي (فكرني...)
    if await try_handle_reminder_flow(update, context):
        return

    # لو المستخدم كتب كلمة زي "فزورة"/"مثل"/"سؤال" عادي (من غير أوامر)، ابدأ اللعبة على طول
    if await maybe_start_game_by_trigger(update, context):
        return

    # لو المستخدم في نص لعبة فزورة/مثل، نتحقق من إجابته
    if await try_handle_game_answer(update, context):
        return

    ensure_user(user_id, private_chat_id=update.effective_chat.id if is_private else None)
    if is_private:
        touch_last_active(user_id)

    user = get_user_profile(user_id)
    if (
        is_private and user and not user["name"] and user["message_count"] == 0
        and len(user_text.split()) <= 4 and not message_mentions_bot(user_text)
    ):
        set_user_name(user_id, user_text.strip())
        await update.message.reply_text(f"تشرفت بيك يا {user_text.strip()} 💙 احكيلي، عايز تتكلم عن إيه؟")
        save_message(user_id, "user", user_text)
        return

    if contains_crisis_keyword(user_text):
        await update.message.reply_text(CRISIS_MESSAGE)

    # مفتاح الذاكرة: خاص = ملف المستخدم الشخصي، جروب = سياق منفصل تمامًا معزول عن أي حاجة خاصة
    context_key = get_context_key(user_id, update.effective_chat.id, is_group)
    save_message(context_key, "user", user_text)
    history = get_recent_messages(context_key)

    if is_private:
        system_prompt = build_personalized_system_prompt(user_id)
    else:
        system_prompt = BASE_SYSTEM_PROMPT + (
            "\n\nملحوظة مهمة جدًا: إنت دلوقتي بترد جوه جروب فيه أكتر من شخص بيشوفوا الرد. "
            "ممنوع تمامًا تكشف أو تلمّح لأي معلومة شخصية أو خاصة اتقالت لك في شات خاص (Private) مع أي حد، "
            "حتى لو كانت معروفة عندك. تعامل مع كل حد في الجروب وكأنك بتكلمه لأول مرة، واستخدم بس اللي بيتقال دلوقتي في الجروب نفسه."
        )

    try:
        reply_text = call_gemini(system_prompt, history)
    except Exception as e:
        logger.error(f"Error calling Gemini API: {e}")
        reply_text = "معلش، حصلت مشكلة تقنية بسيطة. جرب تاني كمان شوية 🙏"

    save_message(context_key, "assistant", reply_text)
    if is_private:
        maybe_update_profile(user_id)

    await update.message.reply_text(reply_text)


# ================= أوامر الأدمن =================

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("الأمر ده متاح للأدمن بس 🙏")
        return
    checkin_status = "شغال ✅" if get_setting("checkin_enabled") == "on" else "مقفول ⛔"
    reminder_status = "شغال ✅" if get_setting("reminder_enabled") == "on" else "مقفول ⛔"
    await update.message.reply_text(
        "🔧 لوحة تحكم الأدمن:\n\n"
        "/stats — إحصائيات البوت\n"
        "/broadcast <رسالة> — بث رسالة لكل المستخدمين\n"
        "/togglecheckin — تشغيل/إيقاف رسالة الصباح اليومية\n"
        "/togglereminder — تشغيل/إيقاف تذكير الغياب\n\n"
        f"حالة Check-in اليومي: {checkin_status}\n"
        f"حالة تذكير الغياب: {reminder_status}"
    )


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("الأمر ده متاح للأدمن بس 🙏")
        return
    total_users = get_total_users_count()
    total_messages = get_total_messages_count()
    active_today = get_active_today_count()
    await update.message.reply_text(
        "📊 إحصائيات أنيس:\n\n"
        f"👥 إجمالي المستخدمين: {total_users}\n"
        f"💬 إجمالي الرسائل: {total_messages}\n"
        f"🟢 نشطين النهاردة: {active_today}"
    )


async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("الأمر ده متاح للأدمن بس 🙏")
        return
    message_text = " ".join(context.args) if context.args else ""
    if not message_text:
        await update.message.reply_text("استخدمه كده: /broadcast الرسالة اللي عايز تبعتها")
        return
    users = get_all_private_users()
    sent, failed = 0, 0
    for user in users:
        try:
            await context.bot.send_message(chat_id=user["private_chat_id"], text=message_text)
            sent += 1
        except Exception as e:
            logger.error(f"Broadcast failed for {user['chat_id']}: {e}")
            failed += 1
    await update.message.reply_text(f"تم البث ✅\nوصلت لـ {sent} حد" + (f"، فشلت لـ {failed}" if failed else ""))


async def toggle_checkin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("الأمر ده متاح للأدمن بس 🙏")
        return
    current = get_setting("checkin_enabled")
    new_value = "off" if current == "on" else "on"
    set_setting("checkin_enabled", new_value)
    await update.message.reply_text(f"Check-in اليومي بقى: {'شغال ✅' if new_value == 'on' else 'مقفول ⛔'}")


async def toggle_reminder_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("الأمر ده متاح للأدمن بس 🙏")
        return
    current = get_setting("reminder_enabled")
    new_value = "off" if current == "on" else "on"
    set_setting("reminder_enabled", new_value)
    await update.message.reply_text(f"تذكير الغياب بقى: {'شغال ✅' if new_value == 'on' else 'مقفول ⛔'}")


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
    app.add_handler(CommandHandler("proverb", proverb_command))
    app.add_handler(CommandHandler("riddle", riddle_command))
    app.add_handler(CommandHandler("trivia", trivia_command))

    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("broadcast", broadcast_command))
    app.add_handler(CommandHandler("togglecheckin", toggle_checkin_command))
    app.add_handler(CommandHandler("togglereminder", toggle_reminder_command))
    app.add_handler(CommandHandler("remind", remind_command))

    app.add_handler(CallbackQueryHandler(mood_callback, pattern="^mood_"))
    app.add_handler(CallbackQueryHandler(games_callback, pattern="^game_"))
    app.add_handler(CallbackQueryHandler(trivia_callback, pattern="^trivia_"))
    app.add_handler(CallbackQueryHandler(moderation_callback, pattern="^mod(ban|ignore)_"))

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
