import os
import re
import io
import random
import asyncio
import threading
import psycopg2
import requests
from psycopg2.extras import RealDictCursor
import logging
from datetime import datetime, timezone, timedelta, time as dtime
from zoneinfo import ZoneInfo
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import google.generativeai as genai
from openai import OpenAI
import anthropic
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatPermissions
from telegram.ext import (
    ApplicationBuilder, ContextTypes, MessageHandler,
    CommandHandler, CallbackQueryHandler, filters,
)

# ---------- الإعدادات ----------
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
GEMINI_API_KEYS = [GEMINI_API_KEY] + [
    k for k in [
        os.environ.get("GEMINI_API_KEY_2", ""),
        os.environ.get("GEMINI_API_KEY_3", ""),
        os.environ.get("GEMINI_API_KEY_4", ""),
    ] if k
]
DATABASE_URL = os.environ["DATABASE_URL"]
CAIRO_TZ = ZoneInfo("Africa/Cairo")

# Dahl Inference (اختياري) - احتياطي أخير + بيساعد في فهم الوقت في التذكير
DAHL_API_KEY = os.environ.get("DAHL_API_KEY", "")
DAHL_BASE_URL = "https://inference.dahl.global/v1"
DAHL_MODEL_NAME = "MiniMaxAI/MiniMax-M2.7"

# Groq (اختياري) - احتياطي أول لو Gemini خلصت الكوتة بتاعته، شركة موثوقة وسريعة جدًا
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GROQ_MODEL_NAME = "openai/gpt-oss-120b"

# Claude (اختياري) - بيبقى الأساسي لو المفتاح موجود، أعلى جودة في الفهم والأسلوب
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL_NAME = "claude-sonnet-5"

genai.configure(api_key=GEMINI_API_KEY)

dahl_client = OpenAI(api_key=DAHL_API_KEY, base_url=DAHL_BASE_URL) if DAHL_API_KEY else None
groq_client = OpenAI(api_key=GROQ_API_KEY, base_url=GROQ_BASE_URL) if GROQ_API_KEY else None
claude_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None
GEMINI_MODEL_NAME = "gemini-3.1-flash-lite"  # الأسرع، رجعناله عشان البطء

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MAX_HISTORY_MESSAGES = 40
PROFILE_UPDATE_EVERY = 4
INACTIVITY_DAYS = 3  # بعد كام يوم صمت نبعت تذكير

# آي دي الأدمن (صاحب البوت) - غيّره من هنا مباشرة لو عايز تضيف أدمن تاني أو تغيّره
ADMIN_USER_ID = 2057835002

# قناة الاشتراك الإجباري (اختياري) - سيبها فاضية "" لو عايز توقف الميزة دي
REQUIRED_CHANNEL = "@VIPKIU"

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
- **ممنوع نهائيًا** ألفاظ رسمية أو خدماتية بتتنافر مع العامية زي "يا فندم"، "حضرتك"، "تحت أمرك"، "تفضل"، "نتشرف بخدمتك" - دي كلام مكاتب وخدمة عملاء، مش كلام صاحب. استخدم بدالها أسلوب صاحبك القريب زي "يا صاحبي"، "يا نجم"، أو حتى بدون أي لقب خالص.
- **خليك حنين جدًا ومتفهم بعمق، مش مجرد "بتسمع وترد".** لما حد يحكيلك حاجة، ماتكتفيش برد عام زي "حاسس بيك" وخلاص - ادخل في تفاصيل اللي قاله فعلاً، اعكس مشاعره بكلامك، واوريه إنك فاهم بالظبط هو حاسس بإيه ولية. الهدف إن الشخص يحس إنه بيتكلم مع حد فاهمه لحد جوه، مش مع رد جاهز.

مثال:
المستخدم: "تعبت من إني دايمًا اللي بحاول في العلاقة وهو مش بيرد نفس الجهد"
رد ضعيف (تجنبه): "حاسس بيك، العلاقات صعبة أحيانًا."
رد قوي (المطلوب): "ده تعب حقيقي، إنك تفضل تدي وتدي وتحس إن التاني مش بيبادلك بنفس القد ده بيخلي حد يحس بالوحدة حتى وهو في علاقة. من امتى وانت حاسس بالإحساس ده؟"
- ماتكررش نفس الجمل الترحيبية أو التطمينية كل شوية، خليك متنوع زي أي حد بيتكلم عادي.
- لو حد سألك صراحة "إنت بوت؟" أو "إنت AI؟" أو أي سؤال مباشر عن طبيعتك، قوله الحقيقة بصراحة ووضوح - إنك مساعد ذكاء اصطناعي - من غير ما تدّعي إنك إنسان حقيقي. الصدق هنا أهم من أي حاجة تانية. **بس ده بس لما يُسأل مباشرة** - متكررش التعريف بنفسك ("أنا أنيس، مساعد ذكاء اصطناعي...") في كل رسالة أو حتى في نفس الرسالة مرتين، ده بيحس المستخدم إنك بتقرا من سكريبت جاهز. رد بشكل طبيعي ومختلف كل مرة حسب سياق الكلام، من غير عبارات ثابتة بتتكرر.
- خليك مرن وطبيعي في الدفء: لو حد قالك "بحبك" كرد فعل عادي وودّي، رد بشكل طبيعي (زي "وأنا كمان بحبك يا صاحبي" أو حاجة شبه كده) - ده جزء من كلام الناس العادي ومفيهوش أي حاجة غريبة. **بس** متبتديش إنت بألفاظ حب أو دلع رومانسي من نفسك (زي "يا حبيبي/حبيبتي" بمعنى عاطفي، "يا بطيطة"، "يا خلبوث")، ومتصعّدش الكلام لأسلوب غزل أو علاقة عاطفية حتى لو المستخدم حاول يجرك لكده - رد بخفة دم وودّ طبيعي، مش برومانسية.

قواعد أساسية لازم تتبعها دايمًا:
1. متشخصش أي حالة نفسية للمستخدم (زي اكتئاب، قلق، اضطراب...) حتى لو حسيت إنها كده. اوصف الشعور من غير ما تحط تسمية طبية.
2. لو حسيت إن الشخص في خطر (أفكار إيذاء نفس، انتحار)، وجهه فورًا للخط الساخن ولخصوصية شخص يثق فيه، وابقى هادي وداعم مش مستجوب.
2ب. لو حسيت إن الشخص تعبان نفسيًا بشكل واضح ومستمر (زي حاسس إنه مخنوق، ضايع، مش قادر يستحمل أكتر) حتى لو مش أزمة لحظية، اقترح عليه بلطف ومن غير إلحاح إنه يتواصل مع حد حقيقي على تليجرام: @I_INW، عشان يلاقي دعم أعمق من مجرد الكلام معاك.
3. متكررش كلام المستخدم السلبي بطريقة تكبره أو تعمقه أكتر. سمعه لكن وجهه لمسار إيجابي.
4. لو المستخدم بيسأل عن حاجة تقنية زي جرعات أدوية أو طرق إيذاء نفس، امنعها ووجهه لطبيب/مختص.
5. ذكّره بلطف بين فترة وفترة إن الكلام مع معالج نفسي حقيقي مهم لو استمرت الحالة.
6. **خليك مختصر جدًا، مش محاضرات طويلة.** جملتين تلاتة كل مرة عادةً، واسأل سؤال واحد بس لو محتاج توضيح. **ركّز على الموضوع اللي المستخدم بيتكلم فيه دلوقتي بس** - ممنوع تدخل مواضيع تانية أو تفتح أكتر من نقطة في نفس الرد حتى لو حسيت إنها مرتبطة، ده بيخلي الرد مزدحم ومربك. رد على قد حجم كلامه بالظبط، مش أكتر.

مثال:
المستخدم: "تعبت من المذاكرة"
رد ضعيف (تجنبه): "المذاكرة فعلاً متعبة، وده طبيعي خصوصًا مع الضغط. عمومًا لازم تاخد بريكات كل شوية وتنظم وقتك كويس، وميرضيش كمان تاكل صح وتنام كفاية عشان تقدر تركز، وأي حاجة تانية حاسس إنها بتضايقك ممكن نتكلم فيها كمان."
رد قوي (المطلوب): "فاهمك، المذاكرة بتاخد منك مجهود كبير. تعبان منها إزاي بالظبط - من الكم، ولا من إنك مش قادر تركز؟"
7. **قاعدة صارمة ومفيهاش استثناء:** لو حد طلب حاجة برا نطاق الدعم النفسي والمشاعر - زي أسئلة عامة، واجبات مدرسية، برمجة، أخبار، وصفات طعام، **ترشيح أغاني أو أفلام أو مسلسلات**، أو أي طلب محتوى ترفيهي - اعتذر بلطف في جملة أو اتنين بس، وارجع على طول تسأله عن حاله. **ممنوع تمامًا** إنك تفصّل أو تقترح أو تدّي قائمة أو تتفاعل مع الطلب بأي شكل حتى لو "بس عشان تجاوبه بسرعة" أو "حاجة بسيطة". لو حسيت إنك بتكتب قائمة أو أسماء أغاني/أفلام/منتجات، وقف فورًا - ده معناه إنك خرجت عن دورك.

مثال:
المستخدم: "هات اغاني هاني شاكر واليسا"
ردك: "الموضوع ده مش تخصصي للأسف 😅 أنا هنا بس عشان أسمعك وأدعمك نفسيًا. عامل إيه النهاردة؟"
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

DAILY_FORTUNES = [
    "🌞 طاقة النهاردة: يوم كويس لتصفية دماغك من حاجة كانت مضايقاك، خد نفس عميق وابدأ خفيف.",
    "🌙 طاقة النهاردة: ممكن تحس بشوية تعب، ده وقت مناسب تاخد بريك بدل ما تكمل بالعافية.",
    "✨ طاقة النهاردة: فرصة كويسة إنك تبتدي حاجة كنت مؤجلها، حتى لو خطوة صغيرة.",
    "🌿 طاقة النهاردة: يوم مناسب للصفا مع نفسك، ابعد شوية عن الضوضا اللي حواليك.",
    "🔥 طاقة النهاردة: حماسك ممكن يكون عالي، استغله في حاجة تفرحك مش تتعبك.",
    "🌤️ طاقة النهاردة: خليك رحيم مع نفسك أكتر من العادي، مش كل يوم لازم يبقى مثالي.",
    "💫 طاقة النهاردة: فرصة كويسة تتواصل مع حد افتقدته، مكالمة بسيطة ممكن تفرق.",
    "🌊 طاقة النهاردة: لو حاسس بضغط، جرب تأجل قرار مهم لبكرة بدل ما تاخده وانت متضايق.",
    "🍃 طاقة النهاردة: يوم كويس للامتنان، فكر في حاجة صغيرة كنت شاكر عليها.",
    "🌸 طاقة النهاردة: مسموح تقول 'لأ' النهاردة من غير ما تحس بالذنب.",
]

QURAN_VERSES = [
    "📖 \"إِنَّ مَعَ الْعُسْرِ يُسْرًا\" (الشرح: 6)",
    "📖 \"وَبَشِّرِ الصَّابِرِينَ\" (البقرة: 155)",
    "📖 \"فَاذْكُرُونِي أَذْكُرْكُمْ\" (البقرة: 152)",
    "📖 \"لَا يُكَلِّفُ اللَّهُ نَفْسًا إِلَّا وُسْعَهَا\" (البقرة: 286)",
    "📖 \"وَمَن يَتَوَكَّلْ عَلَى اللَّهِ فَهُوَ حَسْبُهُ\" (الطلاق: 3)",
    "📖 \"أَلَا بِذِكْرِ اللَّهِ تَطْمَئِنُّ الْقُلُوبُ\" (الرعد: 28)",
]

HADITHS = [
    "🕌 قال ﷺ: \"الدُّعَاءُ هُوَ الْعِبَادَةُ\" (رواه أبو داود والترمذي)",
    "🕌 قال ﷺ: \"تَبَسُّمُكَ فِي وَجْهِ أَخِيكَ صَدَقَةٌ\" (رواه الترمذي)",
    "🕌 قال ﷺ: \"مَنْ لَا يَرْحَمِ النَّاسَ لَا يَرْحَمْهُ اللَّهُ\" (متفق عليه)",
    "🕌 قال ﷺ: \"إِنَّ اللَّهَ رَفِيقٌ يُحِبُّ الرِّفْقَ فِي الْأَمْرِ كُلِّهِ\" (متفق عليه)",
    "🕌 قال ﷺ: \"الْمُؤْمِنُ الْقَوِيُّ خَيْرٌ وَأَحَبُّ إِلَى اللَّهِ مِنَ الْمُؤْمِنِ الضَّعِيفِ\" (رواه مسلم)",
]

SALAWAT = [
    "🤍 اللهم صلِّ وسلم على سيدنا محمد وعلى آله وصحبه أجمعين 🤍",
    "🤍 صلّوا على النبي ﷺ.. \"مَنْ صَلَّى عَلَيَّ صَلَاةً صَلَّى اللَّهُ عَلَيْهِ بِهَا عَشْرًا\"",
    "🤍 اللهم صلِّ على سيدنا محمد كما صليت على سيدنا إبراهيم",
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


# ================= قاعدة البيانات (Postgres) =================

def get_db():
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    return conn


def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        chat_id BIGINT PRIMARY KEY,
        name TEXT,
        profile_summary TEXT DEFAULT '',
        message_count INTEGER DEFAULT 0,
        created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS messages (
        id SERIAL PRIMARY KEY,
        chat_id TEXT,
        role TEXT,
        content TEXT,
        timestamp TEXT
    );
    CREATE TABLE IF NOT EXISTS moods (
        id SERIAL PRIMARY KEY,
        chat_id TEXT,
        score INTEGER,
        timestamp TEXT
    );
    """)
    # أعمدة إضافية لميزات التفاعل التلقائي (check-in / تذكير / ملخص أسبوعي)
    cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS private_chat_id BIGINT")
    cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_active_at TEXT")
    cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_reminder_at TEXT")
    cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS style TEXT DEFAULT 'warm'")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS banned_users (
        user_id BIGINT PRIMARY KEY,
        banned_at TEXT
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS journal_entries (
        id SERIAL PRIMARY KEY,
        chat_id BIGINT,
        content TEXT,
        timestamp TEXT
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS future_messages (
        id SERIAL PRIMARY KEY,
        user_id BIGINT,
        private_chat_id BIGINT,
        content TEXT,
        deliver_at TEXT,
        delivered BOOLEAN DEFAULT FALSE
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS group_members (
        group_chat_id TEXT,
        user_id BIGINT,
        display_name TEXT,
        PRIMARY KEY (group_chat_id, user_id)
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS active_groups (
        group_chat_id BIGINT PRIMARY KEY,
        title TEXT,
        last_seen TEXT
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS whispers (
        id SERIAL PRIMARY KEY,
        sender_id BIGINT,
        sender_name TEXT,
        target_id BIGINT,
        content TEXT,
        created_at TEXT,
        seen BOOLEAN DEFAULT FALSE
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS group_roles (
        group_chat_id BIGINT,
        user_id BIGINT,
        role TEXT,
        PRIMARY KEY (group_chat_id, user_id)
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS group_warnings (
        group_chat_id BIGINT,
        user_id BIGINT,
        count INTEGER DEFAULT 0,
        PRIMARY KEY (group_chat_id, user_id)
    )
    """)
    conn.commit()
    cur.close()
    conn.close()


def ensure_user(user_id: int, private_chat_id: int = None):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE chat_id = %s", (user_id,))
    row = cur.fetchone()
    if row is None:
        cur.execute(
            "INSERT INTO users (chat_id, name, profile_summary, message_count, created_at, private_chat_id, last_active_at) "
            "VALUES (%s, '', '', 0, %s, %s, %s)",
            (user_id, datetime.now(timezone.utc).isoformat(), private_chat_id, datetime.now(timezone.utc).isoformat()),
        )
    elif private_chat_id is not None:
        cur.execute("UPDATE users SET private_chat_id = %s WHERE chat_id = %s", (private_chat_id, user_id))
    conn.commit()
    cur.close()
    conn.close()


def touch_last_active(user_id: int):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "UPDATE users SET last_active_at = %s WHERE chat_id = %s",
        (datetime.now(timezone.utc).isoformat(), user_id),
    )
    conn.commit()
    cur.close()
    conn.close()


def save_message(user_id, role: str, content: str):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO messages (chat_id, role, content, timestamp) VALUES (%s, %s, %s, %s)",
        (str(user_id), role, content, datetime.now(timezone.utc).isoformat()),
    )
    # عداد الرسايل بتاع الملف الشخصي بيتحدث بس لو ده مستخدم حقيقي (شات خاص)، مش مفتاح جروب مركّب
    if role == "user" and not str(user_id).startswith("group:"):
        cur.execute(
            "UPDATE users SET message_count = message_count + 1 WHERE chat_id = %s",
            (user_id,),
        )
    conn.commit()
    cur.close()
    conn.close()


def get_recent_messages(user_id, limit: int = MAX_HISTORY_MESSAGES):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT role, content FROM messages WHERE chat_id = %s ORDER BY id DESC LIMIT %s",
        (str(user_id), limit),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    rows = list(reversed(rows))
    return [{"role": r["role"], "content": r["content"]} for r in rows]


def get_user_profile(user_id: int):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE chat_id = %s", (user_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row


def update_user_profile(user_id: int, profile_summary: str):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE users SET profile_summary = %s WHERE chat_id = %s", (profile_summary, user_id))
    conn.commit()
    cur.close()
    conn.close()


def set_user_name(user_id: int, name: str):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE users SET name = %s WHERE chat_id = %s", (name, user_id))
    conn.commit()
    cur.close()
    conn.close()


def set_user_style(user_id: int, style: str):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE users SET style = %s WHERE chat_id = %s", (style, user_id))
    conn.commit()
    cur.close()
    conn.close()


def save_mood(user_id: int, score: int):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO moods (chat_id, score, timestamp) VALUES (%s, %s, %s)",
        (str(user_id), score, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    cur.close()
    conn.close()


def get_moods(user_id: int, limit: int = 30):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT score, timestamp FROM moods WHERE chat_id = %s ORDER BY id DESC LIMIT %s",
        (str(user_id), limit),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return list(reversed(rows))


def get_mood_streak(user_id: int) -> int:
    """بيحسب عدد الأيام المتتالية اللي المستخدم سجّل فيها مزاجه (لغاية النهاردة أو أمبارح)."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT DISTINCT timestamp FROM moods WHERE chat_id = %s ORDER BY timestamp DESC",
        (str(user_id),),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()

    if not rows:
        return 0

    days = sorted({datetime.fromisoformat(r["timestamp"]).date() for r in rows}, reverse=True)
    today = datetime.now(timezone.utc).date()

    if days[0] not in (today, today - timedelta(days=1)):
        return 0  # آخر تسجيل كان قبل بكرة، السلسلة اتكسرت

    streak = 1
    for i in range(1, len(days)):
        if (days[i - 1] - days[i]).days == 1:
            streak += 1
        else:
            break
    return streak


def streak_badge(streak: int) -> str:
    if streak >= 30:
        return "🏆"
    if streak >= 14:
        return "💎"
    if streak >= 7:
        return "🔥"
    if streak >= 3:
        return "✨"
    return ""


def get_all_private_users():
    """كل المستخدمين اللي بدأوا شات خاص مع البوت (عشان نبعتلهم رسائل تلقائية)."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT chat_id, name, private_chat_id, last_active_at, last_reminder_at FROM users WHERE private_chat_id IS NOT NULL"
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def mark_reminder_sent(user_id: int):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "UPDATE users SET last_reminder_at = %s WHERE chat_id = %s",
        (datetime.now(timezone.utc).isoformat(), user_id),
    )
    conn.commit()
    cur.close()
    conn.close()


def get_setting(key: str, default: str = "on") -> str:
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT value FROM settings WHERE key = %s", (key,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row["value"] if row else default


def set_setting(key: str, value: str):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
        (key, value),
    )
    conn.commit()
    cur.close()
    conn.close()


def get_total_users_count() -> int:
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) as c FROM users")
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row["c"]


def get_total_messages_count() -> int:
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) as c FROM messages")
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row["c"]


def get_active_today_count() -> int:
    conn = get_db()
    cur = conn.cursor()
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    cur.execute("SELECT COUNT(*) as c FROM users WHERE last_active_at >= %s", (today_start,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row["c"]


def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_USER_ID


async def is_subscribed_to_required_channel(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> bool:
    if not REQUIRED_CHANNEL:
        return True
    try:
        member = await context.bot.get_chat_member(REQUIRED_CHANNEL, user_id)
        return member.status not in ("left", "kicked")
    except Exception as e:
        logger.error(f"Subscription check failed: {e}")
        return True  # لو حصل خطأ في الفحص نفسه، منمنعش المستخدم عشان مشكلة تقنية


def ban_user(user_id: int):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO banned_users (user_id, banned_at) VALUES (%s, %s) ON CONFLICT (user_id) DO NOTHING",
        (user_id, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    cur.close()
    conn.close()


def unban_user(user_id: int):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM banned_users WHERE user_id = %s", (user_id,))
    conn.commit()
    cur.close()
    conn.close()


def is_user_banned(user_id: int) -> bool:
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM banned_users WHERE user_id = %s", (user_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row is not None


def save_journal_entry(user_id: int, content: str):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO journal_entries (chat_id, content, timestamp) VALUES (%s, %s, %s)",
        (user_id, content, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    cur.close()
    conn.close()


def get_journal_entries(user_id: int, limit: int = 5):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT content, timestamp FROM journal_entries WHERE chat_id = %s ORDER BY id DESC LIMIT %s",
        (user_id, limit),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def save_future_message(user_id: int, private_chat_id: int, content: str, deliver_at: str):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO future_messages (user_id, private_chat_id, content, deliver_at, delivered) "
        "VALUES (%s, %s, %s, %s, FALSE)",
        (user_id, private_chat_id, content, deliver_at),
    )
    conn.commit()
    cur.close()
    conn.close()


def get_due_future_messages():
    conn = get_db()
    cur = conn.cursor()
    now = datetime.now(timezone.utc).isoformat()
    cur.execute("SELECT * FROM future_messages WHERE delivered = FALSE AND deliver_at <= %s", (now,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def mark_future_message_delivered(msg_id: int):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE future_messages SET delivered = TRUE WHERE id = %s", (msg_id,))
    conn.commit()
    cur.close()
    conn.close()


def upsert_group_member(group_chat_id: int, user_id: int, display_name: str):
    """بيسجل اسم الشخص في الجروب ده بس - من غير أي تفاصيل شخصية أو محادثات."""
    if not display_name:
        return
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO group_members (group_chat_id, user_id, display_name) VALUES (%s, %s, %s) "
        "ON CONFLICT (group_chat_id, user_id) DO UPDATE SET display_name = EXCLUDED.display_name",
        (str(group_chat_id), user_id, display_name),
    )
    conn.commit()
    cur.close()
    conn.close()


def get_group_member_names(group_chat_id: int, exclude_user_id: int = None, limit: int = 50):
    conn = get_db()
    cur = conn.cursor()
    if exclude_user_id is not None:
        cur.execute(
            "SELECT display_name FROM group_members WHERE group_chat_id = %s AND user_id != %s LIMIT %s",
            (str(group_chat_id), exclude_user_id, limit),
        )
    else:
        cur.execute(
            "SELECT display_name FROM group_members WHERE group_chat_id = %s LIMIT %s",
            (str(group_chat_id), limit),
        )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [r["display_name"] for r in rows]


def upsert_active_group(group_chat_id: int, title: str):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO active_groups (group_chat_id, title, last_seen) VALUES (%s, %s, %s) "
        "ON CONFLICT (group_chat_id) DO UPDATE SET title = EXCLUDED.title, last_seen = EXCLUDED.last_seen",
        (group_chat_id, title, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    cur.close()
    conn.close()


def get_all_active_groups():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT group_chat_id, title FROM active_groups")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows




# كلمات تستدعي تنبيه الأدمن (رقابة محتوى أساسية - قائمة قابلة للتوسيع)
FLAGGED_WORDS = ["كس", "طيز", "زبر", "لبوة", "شرموطة", "متناك", "خول"]


def contains_flagged_word(text: str) -> bool:
    text_norm = normalize_arabic(text)
    return any(normalize_arabic(w) in text_norm for w in FLAGGED_WORDS)


# تتبع تكرار المخالفات في الذاكرة (بيتصفر لو البوت اتقفل، وده مقبول لأداة مكافحة سبام)
FLAG_HISTORY = {}  # user_id -> [timestamps]
LAST_ALERT_SENT = {}  # user_id -> timestamp آخر تنبيه اتبعت للأدمن
AUTO_BAN_THRESHOLD = 5     # عدد المخالفات المتكررة قبل الحظر التلقائي
AUTO_BAN_WINDOW_SECONDS = 600  # خلال كام ثانية (10 دقايق)
ALERT_COOLDOWN_SECONDS = 20    # منمنعش تنبيهات متكررة لنفس الشخص أسرع من كده


def register_flag_event(user_id: int) -> int:
    """يسجل مخالفة جديدة ويرجع عدد المخالفات الحالية خلال النافذة الزمنية."""
    now = datetime.now(timezone.utc).timestamp()
    history = FLAG_HISTORY.setdefault(user_id, [])
    history.append(now)
    FLAG_HISTORY[user_id] = [t for t in history if now - t <= AUTO_BAN_WINDOW_SECONDS]
    return len(FLAG_HISTORY[user_id])


def should_send_alert(user_id: int) -> bool:
    now = datetime.now(timezone.utc).timestamp()
    last = LAST_ALERT_SENT.get(user_id, 0)
    if now - last < ALERT_COOLDOWN_SECONDS:
        return False
    LAST_ALERT_SENT[user_id] = now
    return True


async def notify_admin_flagged_message(context: ContextTypes.DEFAULT_TYPE, update: Update):
    if ADMIN_USER_ID == 0:
        return
    sender = update.effective_user
    sender_name = sender.full_name or sender.username or str(sender.id)
    chat_label = "جروب" if update.effective_chat.type in ("group", "supergroup") else "شات خاص"

    flag_count = register_flag_event(sender.id)

    # لو تكرر المخالفة كتير خلال وقت قصير، نحظره أوتوماتيك من غير ما ننتظر الأدمن
    if flag_count >= AUTO_BAN_THRESHOLD:
        ban_user(sender.id)
        try:
            await context.bot.send_message(
                chat_id=ADMIN_USER_ID,
                text=(
                    f"🚫 اتحظر أوتوماتيك ({chat_label})\n"
                    f"من: {sender_name} (آيدي: {sender.id})\n"
                    f"كرر لفظ مخل {flag_count} مرات خلال دقايق قليلة.\n"
                    f"آخر رسالة: \"{update.message.text}\"\n\n"
                    f"لو حابب تفك الحظر: /unban {sender.id}"
                ),
            )
        except Exception as e:
            logger.error(f"Failed to notify admin about auto-ban: {e}")
        return

    # منمنعش تنبيهات متكررة جدًا لنفس الشخص (Rate limit)
    if not should_send_alert(sender.id):
        return

    keyboard = [[
        InlineKeyboardButton("🚫 حظر", callback_data=f"modban_{sender.id}"),
        InlineKeyboardButton("✅ تجاهل", callback_data=f"modignore_{sender.id}"),
    ]]
    try:
        await context.bot.send_message(
            chat_id=ADMIN_USER_ID,
            text=(
                f"⚠️ رسالة فيها لفظ مخل ({chat_label})\n"
                f"من: {sender_name} (آيدي: {sender.id})\n"
                f"قال: \"{update.message.text}\"\n"
                f"({flag_count} مخالفة خلال آخر 10 دقايق)"
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
    try:
        if action == "modban":
            ban_user(target_id)
            await query.edit_message_text(query.message.text + "\n\n🚫 تم الحظر.")
        else:
            await query.edit_message_text(query.message.text + "\n\n✅ اتجاهلت.")
    except Exception as e:
        logger.error(f"Moderation callback error: {e}")
        # حتى لو فشل تعديل الرسالة (زي لو ضغطت الزرار مرتين)، الحظر يكون اتنفذ فعليًا
        if action == "modban":
            ban_user(target_id)


def contains_crisis_keyword(text: str) -> bool:
    text_lower = text.lower()
    return any(keyword in text_lower for keyword in CRISIS_KEYWORDS)


BOT_MENTION_WORDS = ["أنيس", "انيس", "aneesbot", "anees"]


def message_mentions_bot(text: str) -> bool:
    text_lower = text.lower()
    return any(word.lower() in text_lower for word in BOT_MENTION_WORDS)


# ================= Gemini =================

_gemini_lock = threading.Lock()


def _call_gemini_raw(system_prompt: str, history: list) -> str:
    model = genai.GenerativeModel(model_name=GEMINI_MODEL_NAME, system_instruction=system_prompt)
    gemini_history = []
    for m in history[:-1]:
        role = "user" if m["role"] == "user" else "model"
        gemini_history.append({"role": role, "parts": [m["content"]]})
    chat = model.start_chat(history=gemini_history)
    last_message = history[-1]["content"]
    response = chat.send_message(last_message)
    return response.text


def call_gemini(system_prompt: str, history: list) -> str:
    """بيلف على كل مفاتيح Gemini المتاحة، من غير ما يقفل الطلبات ورا بعض (عشان السرعة مع أكتر من مستخدم)."""
    last_error = None
    for i, key in enumerate(GEMINI_API_KEYS):
        with _gemini_lock:
            genai.configure(api_key=key)
        try:
            result = _call_gemini_raw(system_prompt, history)
            with _gemini_lock:
                genai.configure(api_key=GEMINI_API_KEY)
            return result
        except Exception as e:
            last_error = e
            is_quota_error = "429" in str(e) or "quota" in str(e).lower()
            if not is_quota_error:
                with _gemini_lock:
                    genai.configure(api_key=GEMINI_API_KEY)
                raise
            logger.info(f"Gemini key {i + 1} quota exceeded, trying next key")
    with _gemini_lock:
        genai.configure(api_key=GEMINI_API_KEY)
    raise last_error


def call_dahl_chat(system_prompt: str, history: list) -> str:
    if dahl_client is None:
        raise RuntimeError("Dahl مش متظبط (مفيش DAHL_API_KEY)")
    messages = [{"role": "system", "content": system_prompt}]
    for m in history:
        messages.append({"role": m["role"], "content": m["content"]})
    response = dahl_client.chat.completions.create(
        model=DAHL_MODEL_NAME,
        messages=messages,
        max_tokens=500,
    )
    return response.choices[0].message.content


def call_groq_chat(system_prompt: str, history: list) -> str:
    if groq_client is None:
        raise RuntimeError("Groq مش متظبط (مفيش GROQ_API_KEY)")
    messages = [{"role": "system", "content": system_prompt}]
    for m in history:
        messages.append({"role": m["role"], "content": m["content"]})
    response = groq_client.chat.completions.create(
        model=GROQ_MODEL_NAME,
        messages=messages,
        max_tokens=500,
    )
    return response.choices[0].message.content


def call_claude(system_prompt: str, history: list) -> str:
    if claude_client is None:
        raise RuntimeError("Claude مش متظبط (مفيش ANTHROPIC_API_KEY)")
    messages = [{"role": m["role"], "content": m["content"]} for m in history]
    response = claude_client.messages.create(
        model=CLAUDE_MODEL_NAME,
        system=system_prompt,
        messages=messages,
        max_tokens=500,
    )
    return "".join(block.text for block in response.content if block.type == "text")


def clean_ai_response(text: str) -> str:
    """شبكة أمان: نشيل أي أثر لتفكير داخلي (<think>...</think>) لو الموديل سرّبه بالغلط."""
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r"<thinking>.*?</thinking>", "", cleaned, flags=re.DOTALL | re.IGNORECASE)
    return cleaned.strip()


async def call_ai_race(system_prompt: str, history: list) -> str:
    """Claude هو الأساسي (أعلى جودة). لو فشل أو مش متظبط، نجرب Gemini، بعدين Groq، وآخر حل Dahl."""
    if claude_client is not None:
        try:
            return await asyncio.to_thread(call_claude, system_prompt, history)
        except Exception as e:
            logger.error(f"Claude failed: {e}")

    try:
        return await asyncio.to_thread(call_gemini, system_prompt, history)
    except Exception as e:
        logger.error(f"Gemini failed: {e}")

    if groq_client is not None:
        try:
            return await asyncio.to_thread(call_groq_chat, system_prompt, history)
        except Exception as e:
            logger.error(f"Groq failed: {e}")

    if dahl_client is not None:
        return await asyncio.to_thread(call_dahl_chat, system_prompt, history)

    raise RuntimeError("كل مزودي الذكاء الاصطناعي فشلوا")


STYLE_PROMPTS = {
    "warm": "",  # الأسلوب الافتراضي، مفيش إضافة
    "fun": "\nأسلوب إضافي مطلوب: خليك مرح أكتر من العادي، استخدم إيموجي وخفة دم أكتر، من غير ما تقلل من جدية المشاعر لو الموضوع فعلاً صعب.",
    "calm": "\nأسلوب إضافي مطلوب: خليك هادي جدًا وبطيء الإيقاع في كلامك، جمل قصيرة ومريحة، وابعد عن أي حماس زيادة أو إيموجي كتير.",
}


def build_personalized_system_prompt(user_id: int) -> str:
    user = get_user_profile(user_id)
    extra = ""
    if user and user["name"]:
        extra += f"\nاسم المستخدم: {user['name']}."
    if user and user["profile_summary"]:
        extra += f"\nملاحظات عن المستخدم من محادثات سابقة: {user['profile_summary']}"
    if user and user["style"]:
        extra += STYLE_PROMPTS.get(user["style"], "")
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

    if context.args and context.args[0].startswith("whisper_"):
        try:
            _, target_id_str, origin_chat_id_str = context.args[0].split("_", 2)
            context.user_data["whisper_target"] = int(target_id_str)
            context.user_data["whisper_origin_chat"] = int(origin_chat_id_str)
            await update.message.reply_text("تمام، اكتب الهمس اللي عايز تبعته 🤫")
            return
        except ValueError:
            pass

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
    streak = get_mood_streak(user_id)
    badge = streak_badge(streak)
    streak_line = f"\n{badge} بقالك {streak} يوم متتالي بتسجل مزاجك! استمر كده" if streak >= 2 else ""
    await query.edit_message_text(
        f"تمام، سجلت مزاجك النهاردة: {score}/5 🙏{streak_line}\n\n"
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


async def start_fortune(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(random.choice(DAILY_FORTUNES))


async def style_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[
        InlineKeyboardButton("💙 دافئ (الافتراضي)", callback_data="style_warm"),
        InlineKeyboardButton("😄 مرح", callback_data="style_fun"),
    ], [
        InlineKeyboardButton("🌙 هادئ", callback_data="style_calm"),
    ]]
    await update.effective_message.reply_text(
        "عايزني أتكلم معاك بأسلوب إيه؟", reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def style_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    style = query.data.split("_", 1)[1]
    user_id = update.effective_user.id
    set_user_style(user_id, style)
    labels = {"warm": "دافئ 💙", "fun": "مرح 😄", "calm": "هادئ 🌙"}
    await query.edit_message_text(f"تمام، هبقى أكلمك بأسلوب {labels.get(style, style)} من دلوقتي 🙌")


# ================= يوميات خاصة =================

JOURNAL_PROMPTS = [
    "إيه أكتر حاجة فرحتك النهاردة؟",
    "إيه اللي كان صعب عليك النهاردة؟",
    "لو تقدر تغيّر حاجة واحدة في يومك، هتغيّر إيه؟",
    "إيه حاجة اتعلمتها عن نفسك النهاردة؟",
    "مين حد أثّر فيك بشكل كويس النهاردة؟",
]


async def start_journal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["journal_awaiting"] = True
    question = random.choice(JOURNAL_PROMPTS)
    await update.effective_message.reply_text(f"📔 وقت اليوميات:\n{question}")


async def journal_history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    entries = get_journal_entries(user_id, limit=5)
    if not entries:
        await update.effective_message.reply_text("لسه معملتش أي يوميات، ابدأ بكلمة \"يومياتي\" 📔")
        return
    lines = ["📔 آخر يومياتك:\n"]
    for e in entries:
        date_str = datetime.fromisoformat(e["timestamp"]).strftime("%d/%m")
        lines.append(f"🗓️ {date_str}: {e['content'][:100]}")
    await update.effective_message.reply_text("\n".join(lines))


async def try_handle_journal_flow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not context.user_data.get("journal_awaiting"):
        return False
    context.user_data["journal_awaiting"] = False
    text = update.message.text or ""
    save_journal_entry(update.effective_user.id, text)
    await update.message.reply_text("تمام، اتسجلت 📔 تقدر تشوف يومياتك القديمة بكلمة \"يومياتي القديمة\"")
    return True


def parse_duration(text: str, units_pattern: str):
    """بيرجع (amount, unit) - لو مفيش رقم صريح (زي 'بعد سنة')، بيفترض 1."""
    match = re.search(rf"(?:بعد\s*)?(\d+)\s*({units_pattern})", text)
    if match:
        return int(match.group(1)), match.group(2)
    match = re.search(rf"(?:بعد\s*)?({units_pattern})", text)
    if match:
        return 1, match.group(1)
    return None, None


# ================= رسالة لنفسك في المستقبل =================

FUTURE_UNITS_PATTERN = "يوم|أيام|ايام|أسبوع|اسبوع|اسابيع|أسابيع|شهر|شهور|أشهر|سنة|سنه|سنين"
FUTURE_UNIT_TO_SECONDS = {
    "يوم": 86400, "أيام": 86400, "ايام": 86400,
    "أسبوع": 604800, "اسبوع": 604800, "اسابيع": 604800, "أسابيع": 604800,
    "شهر": 2592000, "شهور": 2592000, "أشهر": 2592000,
    "سنة": 31536000, "سنه": 31536000, "سنين": 31536000,
}


async def start_future_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["future_state"] = "awaiting_message"
    await update.effective_message.reply_text("اكتب الرسالة اللي عايز تبعتها لنفسك في المستقبل 📬")


async def try_handle_future_message_flow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    state = context.user_data.get("future_state")
    text = (update.message.text or "").strip()

    if state == "awaiting_message":
        context.user_data["future_message_content"] = text
        context.user_data["future_state"] = "awaiting_time"
        await update.message.reply_text(
            "تمام، وامتى تحب توصلك؟ اكتب زي \"بعد شهر\" أو \"بعد سنة\" أو \"بعد أسبوعين\""
        )
        return True

    if state == "awaiting_time":
        amount, unit = parse_duration(text, FUTURE_UNITS_PATTERN)
        if amount is None:
            await update.message.reply_text(
                "معلش مفهمتش الوقت 🙏 اكتبه زي \"بعد شهر\" أو \"بعد سنة\" أو \"بعد أسبوع\""
            )
            return True
        seconds = amount * FUTURE_UNIT_TO_SECONDS[unit]
        deliver_at = (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()
        content = context.user_data.get("future_message_content", "")

        save_future_message(update.effective_user.id, update.effective_chat.id, content, deliver_at)

        context.user_data["future_state"] = None
        context.user_data["future_message_content"] = None
        await update.message.reply_text(f"تمام ✅ هبعتلك الرسالة دي بعد {amount} {unit}")
        return True

    return False


async def future_messages_delivery_job(context: ContextTypes.DEFAULT_TYPE):
    for msg in get_due_future_messages():
        try:
            await context.bot.send_message(
                chat_id=msg["private_chat_id"],
                text=f"📬 رسالة من نفسك في الماضي:\n\n{msg['content']}",
            )
            mark_future_message_delivered(msg["id"])
        except Exception as e:
            logger.error(f"Future message delivery failed: {e}")


# ================= دعم في مواضيع محددة =================

SPECIALIZED_TOPICS = {
    "علاقات": "علاقات المستخدم (صداقة، حب، عيلة)",
    "ثقة بالنفس": "الثقة بالنفس وتقدير الذات",
    "ثقتي بنفسي": "الثقة بالنفس وتقدير الذات",
    "ضغط دراسي": "الضغط الدراسي والامتحانات",
    "ضغط الدراسة": "الضغط الدراسي والامتحانات",
    "امتحانات": "الضغط الدراسي والامتحانات",
}


async def start_specialized_topic(update: Update, context: ContextTypes.DEFAULT_TYPE, topic_desc: str):
    prompt = (
        f"المستخدم عايز يتكلم تحديدًا عن موضوع: {topic_desc}. "
        "ابدأ بسؤال دافئ ومفتوح يفتحله المجال يتكلم عن الموضوع ده تحديدًا، بأسلوبك المعتاد وبعامية مصرية."
    )
    try:
        result = clean_ai_response(
            await call_ai_race(prompt, [{"role": "user", "content": f"عايز أتكلم عن {topic_desc}"}])
        )
    except Exception as e:
        logger.error(f"Specialized topic failed: {e}")
        result = "احكيلي، إيه اللي في بالك في الموضوع ده؟"
    await update.effective_message.reply_text(result)


async def start_topic_relationships(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start_specialized_topic(update, context, SPECIALIZED_TOPICS["علاقات"])


async def start_topic_confidence(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start_specialized_topic(update, context, SPECIALIZED_TOPICS["ثقة بالنفس"])


async def start_topic_study(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start_specialized_topic(update, context, SPECIALIZED_TOPICS["ضغط دراسي"])


# ================= همسة (تتكتب في الخاص، وترجع للجروب بزرار كشف) =================

def store_whisper(sender_id: int, sender_name: str, target_id: int, content: str) -> int:
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO whispers (sender_id, sender_name, target_id, content, created_at) "
        "VALUES (%s, %s, %s, %s, %s) RETURNING id",
        (sender_id, sender_name, target_id, content, datetime.now(timezone.utc).isoformat()),
    )
    whisper_id = cur.fetchone()["id"]
    conn.commit()
    cur.close()
    conn.close()
    return whisper_id


def get_whisper(whisper_id: int):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM whispers WHERE id = %s", (whisper_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row


def mark_whisper_seen(whisper_id: int):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE whispers SET seen = TRUE WHERE id = %s", (whisper_id,))
    conn.commit()
    cur.close()
    conn.close()


def delete_old_whispers(older_than_hours: int = 24) -> int:
    conn = get_db()
    cur = conn.cursor()
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=older_than_hours)).isoformat()
    cur.execute("DELETE FROM whispers WHERE created_at < %s", (cutoff,))
    deleted_count = cur.rowcount
    conn.commit()
    cur.close()
    conn.close()
    return deleted_count


# ================= رتب وإدارة الجروب =================

ROLE_RANK = {"owner": 100, "co_owner": 80, "manager": 60, "vip": 50, "admin": 40}
ROLE_LABELS_AR = {
    "owner": "مالك", "co_owner": "أساسي", "manager": "مدير", "admin": "أدمن", "vip": "مميز",
}
ROLE_NAME_TO_KEY = {
    "مالك": "owner",
    "اساسي": "co_owner", "أساسي": "co_owner",
    "مدير": "manager", "ميد": "manager",
    "ادمن": "admin", "أدمن": "admin",
    "مميز": "vip",
}


def set_group_role(group_chat_id: int, user_id: int, role: str):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO group_roles (group_chat_id, user_id, role) VALUES (%s, %s, %s) "
        "ON CONFLICT (group_chat_id, user_id) DO UPDATE SET role = EXCLUDED.role",
        (group_chat_id, user_id, role),
    )
    conn.commit()
    cur.close()
    conn.close()


def remove_group_role(group_chat_id: int, user_id: int):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM group_roles WHERE group_chat_id = %s AND user_id = %s", (group_chat_id, user_id))
    conn.commit()
    cur.close()
    conn.close()


def get_group_role(group_chat_id: int, user_id: int):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT role FROM group_roles WHERE group_chat_id = %s AND user_id = %s", (group_chat_id, user_id))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row["role"] if row else None


def get_all_group_roles(group_chat_id: int):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT user_id, role FROM group_roles WHERE group_chat_id = %s", (group_chat_id,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def get_user_rank(group_chat_id: int, user_id: int) -> int:
    if is_admin(user_id):
        return ROLE_RANK["owner"]
    role = get_group_role(group_chat_id, user_id)
    return ROLE_RANK.get(role, 0)


def increment_warning(group_chat_id: int, user_id: int) -> int:
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO group_warnings (group_chat_id, user_id, count) VALUES (%s, %s, 1) "
        "ON CONFLICT (group_chat_id, user_id) DO UPDATE SET count = group_warnings.count + 1 "
        "RETURNING count",
        (group_chat_id, user_id),
    )
    count = cur.fetchone()["count"]
    conn.commit()
    cur.close()
    conn.close()
    return count


def reset_warnings(group_chat_id: int, user_id: int):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM group_warnings WHERE group_chat_id = %s AND user_id = %s", (group_chat_id, user_id))
    conn.commit()
    cur.close()
    conn.close()


def get_warning_count(group_chat_id: int, user_id: int) -> int:
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT count FROM group_warnings WHERE group_chat_id = %s AND user_id = %s", (group_chat_id, user_id))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row["count"] if row else 0


async def try_handle_whisper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """في الجروب: رد على حد واكتب "همس" بس، من غير أي محتوى - المحتوى بيتكتب في الخاص بعدين."""
    text = (update.message.text or "").strip()
    is_group = update.effective_chat.type in ("group", "supergroup")

    if not is_group or update.message.reply_to_message is None:
        return False
    if text not in ("انوسة", "أنوسة", "انانيس", "ننوس"):
        return False

    target_user = update.message.reply_to_message.from_user
    if target_user is None or target_user.is_bot:
        return False

    sender = update.effective_user
    if sender.id == target_user.id:
        await update.message.reply_text("مينفعش تبعت همس لنفسك 😄")
        return True

    bot_username = context.bot.username
    # بنشفّر آيدي الشخص المقصود + آيدي الجروب في اللينك، عشان لما يبعت الهمس في الخاص نعرف نرجعها فين
    deep_link = f"https://t.me/{bot_username}?start=whisper_{target_user.id}_{update.effective_chat.id}"
    keyboard = [[InlineKeyboardButton("📩 ابعت همس في الخاص", url=deep_link)]]
    msg = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"🤫 دوس الزرار عشان تبعت همس لـ {target_user.full_name}",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    # نمسح رسالة الدعوة دي بعد شوية عشان تفضل نضيفة، من غير ما تأثر لو المسح فشل
    context.job_queue.run_once(
        lambda ctx: ctx.bot.delete_message(chat_id=msg.chat_id, message_id=msg.message_id),
        when=60,
    )
    return True


async def try_handle_whisper_compose(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """في الخاص: لو المستخدم جاي من زرار الهمس، الرسالة الجاية منه هي محتوى الهمس."""
    target_id = context.user_data.get("whisper_target")
    origin_chat_id = context.user_data.get("whisper_origin_chat")
    if target_id is None or origin_chat_id is None:
        return False

    content = (update.message.text or "").strip()
    if not content:
        await update.message.reply_text("ابعت نص الهمس (كتابة عادية بس، مش صورة أو صوت أو ستيكر) 🙏")
        return True  # مسحناش الحالة، فلسه مستنيين نص الهمس

    context.user_data["whisper_target"] = None
    context.user_data["whisper_origin_chat"] = None

    sender = update.effective_user
    sender_name = sender.full_name or sender.username or "حد ما"

    try:
        target_chat = await context.bot.get_chat(target_id)
        target_name = target_chat.full_name or target_chat.first_name or "حد"
    except Exception:
        target_name = "حد في الجروب"

    whisper_id = store_whisper(sender.id, sender_name, target_id, content)
    keyboard = [[InlineKeyboardButton("🔓 اضغط تشوف الهمس", callback_data=f"whisper_{whisper_id}")]]
    # منشن حقيقي بيبعت إشعار للطرفين (الراسل والمستقبِل)
    sender_mention = f'<a href="tg://user?id={sender.id}">{sender_name}</a>'
    target_mention = f'<a href="tg://user?id={target_id}">{target_name}</a>'

    try:
        await context.bot.send_message(
            chat_id=origin_chat_id,
            text=f"🤫 همس جديد من {sender_mention} لـ {target_mention}",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML",
        )
        await update.message.reply_text("تم إرسال الهمس ✅")
        try:
            await update.message.delete()  # نمسح نص الهمس من الشات الخاص بينا كمان
        except Exception:
            pass
    except Exception as e:
        logger.error(f"Whisper delivery failed: {e}")
        await update.message.reply_text("حصلت مشكلة في إرسال الهمس، جرب تاني 🙏")

    return True


async def whisper_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    whisper_id = int(query.data.split("_", 1)[1])
    whisper = get_whisper(whisper_id)

    if whisper is None:
        await query.answer("الهمس ده خلص أو مش موجود 🙅‍♂️", show_alert=True)
        return

    clicker_id = update.effective_user.id
    if clicker_id not in (whisper["target_id"], whisper["sender_id"]):
        await query.answer("الهمس ده مش ليك 🙅‍♂️", show_alert=True)
        return

    # لو المستقبِل هو اللي بيفتحها أول مرة، نبلّغ الراسل إنها اتشافت
    if clicker_id == whisper["target_id"] and clicker_id != whisper["sender_id"] and not whisper["seen"]:
        mark_whisper_seen(whisper["id"])
        sender_profile = get_user_profile(whisper["sender_id"])
        if sender_profile and sender_profile["private_chat_id"]:
            try:
                target_chat = await context.bot.get_chat(whisper["target_id"])
                target_name = target_chat.full_name or target_chat.first_name or "الشخص"
            except Exception:
                target_name = "الشخص"
            try:
                await context.bot.send_message(
                    chat_id=sender_profile["private_chat_id"],
                    text=f"👀 {target_name} شاف الهمس اللي بعتّه له",
                )
            except Exception as e:
                logger.error(f"Failed to notify whisper sender: {e}")

    await query.answer(f"🤫 {whisper['sender_name']}:\n{whisper['content']}", show_alert=True)


# ================= مساعدة: قائمة الأوامر =================

HELP_TEXT = (
    "🤖 حاجات تقدر تكتبها لأنيس:\n\n"
    "💬 دعم نفسي: اتكلم عادي أو جرب \"علاقات\"، \"ثقة بالنفس\"، \"ضغط دراسي\"\n"
    "🎮 تسلية: فزورة، مثل، سؤال، نكتة\n"
    "🧘 تمارين: تهدئة، امتنان، تمرين تنفس\n"
    "📊 مزاج: /mood لتسجيله، /chart لتطوره\n"
    "📔 يومياتي - يوميات يومية\n"
    "⏰ فكرني - تذكير بوقت تحدده\n"
    "📬 رسالة للمستقبل - تتبعتلك بعد فترة\n"
    "🔮 فألي - طاقة اليوم\n"
    "🎭 تحليلي - تحليل شخصيتك\n"
    "🎨 /style - تختار أسلوب أنيس (دافئ/مرح/هادئ)\n"
    "🤫 همس (رد على رسالة حد واكتب \"انوسة\" أو \"ننوس\" بس) - هتوديك في الخاص تبعتله رسالة سرية\n\n"
    "👑 إدارة الجروب (لأصحاب الرتب بس):\n"
    "/setrole [رد] مالك/أساسي/مدير/أدمن/مميز - تعيين رتبة\n"
    "/unrole [رد] - إزالة الرتبة\n"
    "/roles - عرض كل الرتب في الجروب\n"
    "/ban [رد] - حظر\n"
    "/unbangroup <آيدي> - فك الحظر\n"
    "/mute [رد] - كتم\n"
    "/unmute [رد] - فك الكتم\n"
    "/warn [رد] - إنذار (3 إنذارات = حظر تلقائي)\n"
    "/warnings [رد] - عدد الإنذارات\n"
    "/resetwarns [رد] - تصفير الإنذارات\n"
)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(HELP_TEXT)



async def start_gratitude(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(GRATEFUL_PROMPT)


async def start_grounding(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(GROUNDING_TEXT)


PERSONALITY_MIN_MESSAGES = 8


async def start_personality_analysis(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    history = get_recent_messages(user_id, limit=50)
    user_messages = [m for m in history if m["role"] == "user"]
    if len(user_messages) < PERSONALITY_MIN_MESSAGES:
        await update.effective_message.reply_text(
            "لسه محتاج تتكلم معايا شوية أكتر عشان أقدر أحللك صح 🙂 كلمني كام مرة تانية وجرب تاني بكلمة \"تحليلي\""
        )
        return

    await update.effective_message.reply_text("ثانية بس بحلل شخصيتك... 🔍")
    convo_text = "\n".join(f"{m['role']}: {m['content']}" for m in history)
    analysis_prompt = (
        "بناءً على المحادثة دي بس، اعمل تحليل شخصية خفيف وممتع للمستخدم (زي بطاقة شخصية للمشاركة مع الأصحاب). "
        "اكتب بالعامية المصرية، وخليك بالتنسيق ده بالظبط من غير أي تغيير:\n\n"
        "🎭 شخصيتك: [لقب مبتكر وممتع بكلمتين أو تلاتة]\n\n"
        "✨ أبرز صفاتك:\n- [صفة 1]\n- [صفة 2]\n- [صفة 3]\n\n"
        "🌱 حاجة تقدر تشتغل عليها:\n[نصيحة قصيرة ولطيفة]\n\n"
        "💬 جملة بتوصفك:\n\"[جملة قصيرة زي شعار]\"\n\n"
        "خلي التحليل كله إيجابي ولطيف ومبني فعلاً على اللي اتقال في المحادثة، مش عام أو مبتذل."
    )
    try:
        result = clean_ai_response(
            await call_ai_race(analysis_prompt, [{"role": "user", "content": convo_text}])
        )
    except Exception as e:
        logger.error(f"Personality analysis failed: {e}")
        await update.effective_message.reply_text("معلش، حصلت مشكلة تقنية بسيطة. جرب تاني كمان شوية 🙏")
        return

    await update.effective_message.reply_text(
        f"┏━━━━━━━━━━━━━┓\n{result}\n┗━━━━━━━━━━━━━┛\n\n📸 تقدر تعمل Screenshot وتبعتها لصحابك!"
    )


async def analyze_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start_personality_analysis(update, context)


# كلمات طبيعية تفتح اللعبة من غير ما تكتب / أوامر - المطابقة بتكون للنص كامل (بعد شيل المسافات)
# ================= تذكير شخصي (فكّرني) =================

REMINDER_UNITS_PATTERN = "دقيقة|دقايق|دقيقه|ساعة|ساعه|ساعات|يوم|أيام|ايام"
UNIT_TO_SECONDS = {
    "دقيقة": 60, "دقايق": 60, "دقيقه": 60,
    "ساعة": 3600, "ساعه": 3600, "ساعات": 3600,
    "يوم": 86400, "أيام": 86400, "ايام": 86400,
}


def parse_time_with_dahl(text: str) -> int | None:
    """لو الـ Regex العادي فشل، نستخدم Dahl (موديل ذكاء اصطناعي) يفهم الوقت من كلام طبيعي."""
    if dahl_client is None:
        return None
    try:
        response = dahl_client.chat.completions.create(
            model=DAHL_MODEL_NAME,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "المستخدم بيكتب بالعامية المصرية إمتى عايز تذكير. "
                        "رد بالثواني بس (رقم صحيح)، من غير أي كلام تاني. "
                        "مثال: 'بكرة الصبح' يعني حوالي 43200 ثانية (12 ساعة). "
                        "لو مش فاهم الوقت خالص، رد بـ 0."
                    ),
                },
                {"role": "user", "content": text},
            ],
            max_tokens=20,
        )
        raw = response.choices[0].message.content.strip()
        seconds = int(re.sub(r"[^\d]", "", raw) or 0)
        return seconds if seconds > 0 else None
    except Exception as e:
        logger.error(f"Dahl time parsing error: {e}")
        return None


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
        amount, unit = parse_duration(text, REMINDER_UNITS_PATTERN)
        if amount is not None:
            seconds = amount * UNIT_TO_SECONDS[unit]
            time_desc = f"{amount} {unit}"
        else:
            # الـ Regex العادي فشل، نجرب Dahl يفهم الصيغة الطبيعية (زي "بكرة الصبح")
            seconds = parse_time_with_dahl(text)
            if seconds is None:
                await update.message.reply_text(
                    "معلش مفهمتش الوقت 🙏 اكتبه زي كده: \"بعد 10 دقايق\" أو \"بعد 3 ساعات\" أو \"بعد يوم\""
                )
                return True
            time_desc = text

        message = context.user_data.get("remind_message", "")

        context.job_queue.run_once(
            send_reminder_job,
            when=seconds,
            data={"chat_id": update.effective_chat.id, "message": message},
        )

        context.user_data["remind_state"] = None
        context.user_data["remind_message"] = None
        await update.message.reply_text(f"تمام ✅ هفكرك بـ \"{message}\" ({time_desc})")
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
    "تحليلي": start_personality_analysis, "حللني": start_personality_analysis, "شخصيتي": start_personality_analysis,
    "فألي": start_fortune, "طاقتي": start_fortune, "توقعاتي": start_fortune,
    "يومياتي": start_journal, "يوميات": start_journal,
    "يومياتي القديمة": journal_history_command,
    "رسالة للمستقبل": start_future_message, "رساله للمستقبل": start_future_message,
    "علاقات": start_topic_relationships,
    "ثقة بالنفس": start_topic_confidence, "ثقتي بنفسي": start_topic_confidence,
    "ضغط دراسي": start_topic_study, "ضغط الدراسة": start_topic_study, "امتحانات": start_topic_study,
    "مساعدة": help_command, "الاوامر": help_command, "الأوامر": help_command,
}


async def maybe_start_game_by_trigger(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    text_norm = (update.message.text or "").strip()
    handler = GAME_TRIGGERS.get(text_norm)
    if handler is None:
        return False
    # لو كان في تدفق تاني مستني إجابة (لعبة/تذكير/يوميات/رسالة مستقبل)، نلغيه ونبدأ الحاجة الجديدة
    context.user_data["awaiting"] = None
    context.user_data["awaiting_data"] = None
    context.user_data["journal_awaiting"] = False
    context.user_data["future_state"] = None
    context.user_data["remind_state"] = None
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


async def hourly_religious_message_job(context: ContextTypes.DEFAULT_TYPE):
    content_pool = QURAN_VERSES + HADITHS + SALAWAT
    message = random.choice(content_pool)
    for group in get_all_active_groups():
        try:
            await context.bot.send_message(chat_id=group["group_chat_id"], text=message)
        except Exception as e:
            logger.error(f"Hourly religious message failed for group {group['group_chat_id']}: {e}")


async def cleanup_old_whispers_job(context: ContextTypes.DEFAULT_TYPE):
    deleted = delete_old_whispers(older_than_hours=24)
    if deleted:
        logger.info(f"Deleted {deleted} old whisper(s)")


# ================= تنبيه قبل الأذان =================

PRAYER_NAMES_AR = {
    "Fajr": "الفجر", "Dhuhr": "الظهر", "Asr": "العصر", "Maghrib": "المغرب", "Isha": "العشاء",
}
PRAYER_REMINDER_MINUTES_BEFORE = 10


def fetch_prayer_times_today() -> dict:
    """بيجيب مواقيت الصلاة النهاردة للقاهرة من موقع Aladhan (مجاني، من غير مفتاح)."""
    url = "https://api.aladhan.com/v1/timingsByCity"
    params = {"city": "Cairo", "country": "Egypt", "method": 5}
    response = requests.get(url, params=params, timeout=15)
    response.raise_for_status()
    data = response.json()["data"]["timings"]
    return {name: data[name] for name in PRAYER_NAMES_AR}


async def send_prayer_reminder(context: ContextTypes.DEFAULT_TYPE, prayer_name_ar: str):
    text = f"🕌 أذان {prayer_name_ar} قرّب (بعد {PRAYER_REMINDER_MINUTES_BEFORE} دقايق تقريبًا)، استعدوا للصلاة 🤍"
    for group in get_all_active_groups():
        try:
            await context.bot.send_message(chat_id=group["group_chat_id"], text=text)
        except Exception as e:
            logger.error(f"Prayer reminder failed for group {group['group_chat_id']}: {e}")


async def prayer_reminder_job(context: ContextTypes.DEFAULT_TYPE):
    """بتشتغل مرة كل دقيقة، وتبعت التنبيه لما نكون قربنا من وقت أي صلاة بعشر دقايق."""
    now = datetime.now(CAIRO_TZ)
    cache = context.bot_data.get("prayer_times_cache")

    if not cache or cache.get("date") != now.date():
        try:
            timings = await asyncio.to_thread(fetch_prayer_times_today)
            context.bot_data["prayer_times_cache"] = {"date": now.date(), "timings": timings, "notified": set()}
            cache = context.bot_data["prayer_times_cache"]
        except Exception as e:
            logger.error(f"Fetching prayer times failed: {e}")
            return

    for prayer_key, prayer_name_ar in PRAYER_NAMES_AR.items():
        if prayer_key in cache["notified"]:
            continue
        time_str = cache["timings"][prayer_key].split(" ")[0]  # "HH:MM" من غير أي توقيت زيادة
        hour, minute = map(int, time_str.split(":"))
        prayer_dt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        reminder_dt = prayer_dt - timedelta(minutes=PRAYER_REMINDER_MINUTES_BEFORE)

        if reminder_dt <= now < prayer_dt:
            await send_prayer_reminder(context, prayer_name_ar)
            cache["notified"].add(prayer_key)


# ================= الرسائل العادية =================

def get_context_key(user_id: int, chat_id: int, is_group: bool) -> str:
    """مفتاح منفصل للمحادثة الجماعية عشان ذاكرة الشات الخاص متتسربش للجروب."""
    return f"group:{chat_id}:{user_id}" if is_group else str(user_id)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        await _handle_message_inner(update, context)
    except Exception as e:
        logger.error(f"Unhandled error in handle_message: {e}")
        try:
            await update.message.reply_text("معلش، حصلت مشكلة تقنية بسيطة. جرب تاني كمان شوية 🙏")
        except Exception:
            pass


async def _handle_message_inner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    is_group = update.effective_chat.type in ("group", "supergroup")
    is_private = update.effective_chat.type == "private"
    user_text = update.message.text or ""
    user_id = update.effective_user.id

    # همس: بتشتغل جوه الجروب من غير ما تحتاج تنادي على البوت بالاسم
    if await try_handle_whisper(update, context):
        return

    # أوامر إدارة الجروب بالعربي (رفع/نزل/حظر/كتم/انذار) - من غير ما تنادي على البوت بالاسم
    if await try_handle_group_admin_trigger(update, context):
        return

    # همس: المستخدم جاي من الزرار وبيكتب محتوى الهمس في الخاص
    if is_private and await try_handle_whisper_compose(update, context):
        return

    if is_group:
        upsert_active_group(update.effective_chat.id, update.effective_chat.title or "")
        replied_msg = update.message.reply_to_message
        is_reply_to_whisper_msg = (
            replied_msg is not None
            and replied_msg.text is not None
            and replied_msg.text.startswith("🤫 همس جديد من")
        )
        replied_to_bot = (
            replied_msg is not None
            and replied_msg.from_user is not None
            and replied_msg.from_user.id == context.bot.id
            and not is_reply_to_whisper_msg
        )
        if not (message_mentions_bot(user_text) or replied_to_bot):
            return

        # اشتراك إجباري - بنستثني حالات الأزمة عشان السلامة أهم من أي حاجة
        if not contains_crisis_keyword(user_text) and not await is_subscribed_to_required_channel(context, user_id):
            keyboard = [[InlineKeyboardButton("📢 اشترك في القناة", url=f"https://t.me/{REQUIRED_CHANNEL.lstrip('@')}")]]
            await update.message.reply_text(
                "لازم تكون مشترك في القناة الأول عشان تقدر تكلمني 🙏",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
            return

    # مستخدم محظور: نتجاهله تمامًا
    if is_user_banned(user_id):
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

    # يوميات لسه مستنية النص
    if await try_handle_journal_flow(update, context):
        return

    # رسالة للمستقبل لسه في نص التدفق
    if await try_handle_future_message_flow(update, context):
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
        # اسم المتكلم الحالي (بياناته هو بس، مش معلومات حد تاني)
        speaker_profile = get_user_profile(user_id)
        speaker_name = (
            speaker_profile["name"] if speaker_profile and speaker_profile["name"]
            else (update.effective_user.first_name or "")
        )
        upsert_group_member(update.effective_chat.id, user_id, speaker_name)

        known_names = get_group_member_names(update.effective_chat.id, exclude_user_id=user_id)
        names_line = f"\nأعضاء تانيين معروفين في الجروب ده: {', '.join(known_names)}." if known_names else ""

        system_prompt = BASE_SYSTEM_PROMPT + (
            "\n\nملحوظة مهمة جدًا: إنت دلوقتي بترد جوه جروب فيه أكتر من شخص بيشوفوا الرد. "
            "ممنوع تمامًا تكشف أو تلمّح لأي معلومة شخصية أو خاصة اتقالت لك في شات خاص (Private) مع أي حد، "
            "حتى لو كانت معروفة عندك. استخدم بس اللي بيتقال دلوقتي في الجروب نفسه لمحتوى الكلام.\n"
            f"اسم اللي بيكلمك دلوقتي: {speaker_name or 'مش معروف'}."
            f"{names_line}\n"
            "الأسامي دي بس للتعرف الاجتماعي (إنك تعرف إن الاسم ده عضو حقيقي في الجروب وتتعامل معاه طبيعي لو اتذكر)، "
            "**ممنوع تمامًا** تختلق أو تفترض أي تفاصيل شخصية عن أي عضو غير اسمه - متقولش حاجة عن مشاعره أو مشاكله أو أي حاجة اتقالت في الخاص."
        )

    try:
        reply_text = clean_ai_response(await call_ai_race(system_prompt, history))
    except Exception as e:
        logger.error(f"Error calling Gemini API: {e}")
        reply_text = "معلش، حصلت مشكلة تقنية بسيطة. جرب تاني كمان شوية 🙏"

    save_message(context_key, "assistant", reply_text)
    if is_private:
        maybe_update_profile(user_id)

    await update.message.reply_text(reply_text)


# ================= أوامر إدارة الجروب =================

async def _get_target_and_check(update: Update, context: ContextTypes.DEFAULT_TYPE, required_role_rank: int = 0):
    """بيرجع (target_user, actor_rank, target_rank) أو None لو فيه مشكلة (وبيبعت رسالة الخطأ بنفسه)."""
    if update.effective_chat.type not in ("group", "supergroup"):
        await update.message.reply_text("الأمر ده يشتغل جوه الجروبات بس 🙏")
        return None
    if update.message.reply_to_message is None:
        await update.message.reply_text("لازم ترد (Reply) على رسالة الشخص اللي عايز تنفذ عليه الأمر")
        return None

    target_user = update.message.reply_to_message.from_user
    if target_user is None or target_user.is_bot:
        await update.message.reply_text("مينفعش تنفذ الأمر ده على بوت 🙏")
        return None

    chat_id = update.effective_chat.id
    actor_id = update.effective_user.id
    actor_rank = get_user_rank(chat_id, actor_id)
    target_rank = get_user_rank(chat_id, target_user.id)

    if actor_rank < required_role_rank:
        await update.message.reply_text("مالكش صلاحية كفاية تعمل الأمر ده 🙅‍♂️")
        return None
    if actor_rank <= target_rank:
        await update.message.reply_text("الشخص ده رتبته أعلى منك أو زيك، مينفعش تنفذ عليه الأمر ده")
        return None

    return target_user, actor_rank, target_rank


async def _perform_setrole(update: Update, context: ContextTypes.DEFAULT_TYPE, target_user, role: str):
    chat_id = update.effective_chat.id
    actor_id = update.effective_user.id
    actor_rank = get_user_rank(chat_id, actor_id)
    target_rank = get_user_rank(chat_id, target_user.id)
    new_role_rank = ROLE_RANK[role]

    if actor_rank <= target_rank:
        await update.message.reply_text("الشخص ده رتبته أعلى منك أو زيك بالفعل")
        return
    if not is_admin(actor_id) and new_role_rank >= actor_rank:
        await update.message.reply_text("مينفعش تدي رتبة أعلى من رتبتك إنت أو زيها")
        return

    set_group_role(chat_id, target_user.id, role)
    await update.message.reply_text(f"تمام ✅ {target_user.full_name} بقى {ROLE_LABELS_AR[role]}")


async def setrole_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type not in ("group", "supergroup"):
        await update.message.reply_text("الأمر ده يشتغل جوه الجروبات بس 🙏")
        return
    if update.message.reply_to_message is None:
        await update.message.reply_text("رد (Reply) على رسالة الشخص واكتب: /setrole مدير (مثلاً)")
        return
    if not context.args:
        await update.message.reply_text("اكتب الرتبة: مالك / أساسي / مدير / أدمن / مميز")
        return

    role_input = context.args[0]
    role = ROLE_NAME_TO_KEY.get(role_input)
    if role is None:
        await update.message.reply_text("رتبة مش معروفة. اختار من: مالك / أساسي / مدير / أدمن / مميز")
        return

    target_user = update.message.reply_to_message.from_user
    if target_user is None or target_user.is_bot:
        await update.message.reply_text("مينفعش تدي رتبة لبوت 🙏")
        return

    await _perform_setrole(update, context, target_user, role)


async def unrole_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result = await _get_target_and_check(update, context, required_role_rank=ROLE_RANK["manager"])
    if result is None:
        return
    target_user, _, _ = result
    remove_group_role(update.effective_chat.id, target_user.id)
    await update.message.reply_text(f"تمام ✅ اتشالت كل الرتب من {target_user.full_name}")


async def roles_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type not in ("group", "supergroup"):
        await update.message.reply_text("الأمر ده يشتغل جوه الجروبات بس 🙏")
        return
    roles = get_all_group_roles(update.effective_chat.id)
    if not roles:
        await update.message.reply_text("مفيش رتب متعينة في الجروب ده لسه")
        return
    lines = ["👥 رتب الجروب:\n"]
    for row in sorted(roles, key=lambda r: -ROLE_RANK.get(r["role"], 0)):
        lines.append(f"- {ROLE_LABELS_AR.get(row['role'], row['role'])}: آيدي {row['user_id']}")
    await update.message.reply_text("\n".join(lines))


async def ban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result = await _get_target_and_check(update, context, required_role_rank=ROLE_RANK["admin"])
    if result is None:
        return
    target_user, _, _ = result
    try:
        await context.bot.ban_chat_member(update.effective_chat.id, target_user.id)
        await update.message.reply_text(f"🚫 اتحظر {target_user.full_name} من الجروب")
    except Exception as e:
        logger.error(f"Ban failed: {e}")
        await update.message.reply_text("مقدرتش أنفذ الحظر - تأكد إن البوت أدمن وعنده صلاحية حظر الأعضاء")


async def unban_group_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type not in ("group", "supergroup"):
        await update.message.reply_text("الأمر ده يشتغل جوه الجروبات بس 🙏")
        return
    if not context.args:
        await update.message.reply_text("استخدمه كده: /unbangroup <آيدي الشخص>")
        return
    try:
        target_id = int(context.args[0])
        await context.bot.unban_chat_member(update.effective_chat.id, target_id, only_if_banned=True)
        await update.message.reply_text("تمام ✅ اتفك الحظر")
    except Exception as e:
        logger.error(f"Unban failed: {e}")
        await update.message.reply_text("مقدرتش أفك الحظر، تأكد من الآيدي")


async def mute_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result = await _get_target_and_check(update, context, required_role_rank=ROLE_RANK["admin"])
    if result is None:
        return
    target_user, _, _ = result
    try:
        await context.bot.restrict_chat_member(
            update.effective_chat.id, target_user.id,
            permissions=ChatPermissions(can_send_messages=False),
        )
        await update.message.reply_text(f"🔇 اتكتم {target_user.full_name}")
    except Exception as e:
        logger.error(f"Mute failed: {e}")
        await update.message.reply_text("مقدرتش أنفذ الكتم - تأكد إن البوت أدمن وعنده صلاحية تقييد الأعضاء")


async def unmute_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result = await _get_target_and_check(update, context, required_role_rank=ROLE_RANK["admin"])
    if result is None:
        return
    target_user, _, _ = result
    try:
        await context.bot.restrict_chat_member(
            update.effective_chat.id, target_user.id,
            permissions=ChatPermissions(
                can_send_messages=True, can_send_audios=True, can_send_documents=True,
                can_send_photos=True, can_send_videos=True, can_send_other_messages=True,
            ),
        )
        await update.message.reply_text(f"🔊 اتفك الكتم عن {target_user.full_name}")
    except Exception as e:
        logger.error(f"Unmute failed: {e}")
        await update.message.reply_text("مقدرتش أفك الكتم")


WARN_LIMIT = 3


async def warn_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result = await _get_target_and_check(update, context, required_role_rank=ROLE_RANK["admin"])
    if result is None:
        return
    target_user, _, _ = result
    chat_id = update.effective_chat.id
    count = increment_warning(chat_id, target_user.id)

    if count >= WARN_LIMIT:
        reset_warnings(chat_id, target_user.id)
        try:
            await context.bot.ban_chat_member(chat_id, target_user.id)
            await update.message.reply_text(
                f"⚠️ {target_user.full_name} وصل لـ {WARN_LIMIT} إنذارات واتحظر تلقائيًا 🚫"
            )
        except Exception as e:
            logger.error(f"Auto-ban after warnings failed: {e}")
            await update.message.reply_text(f"⚠️ {target_user.full_name} وصل للحد الأقصى بس مقدرتش أحظره تلقائيًا")
    else:
        await update.message.reply_text(f"⚠️ إنذار لـ {target_user.full_name} ({count}/{WARN_LIMIT})")


async def warnings_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type not in ("group", "supergroup"):
        await update.message.reply_text("الأمر ده يشتغل جوه الجروبات بس 🙏")
        return
    if update.message.reply_to_message is None:
        await update.message.reply_text("رد على رسالة الشخص عشان أشوفلك عدد إنذاراته")
        return
    target_user = update.message.reply_to_message.from_user
    count = get_warning_count(update.effective_chat.id, target_user.id)
    await update.message.reply_text(f"⚠️ {target_user.full_name} عنده {count}/{WARN_LIMIT} إنذارات")


async def resetwarns_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result = await _get_target_and_check(update, context, required_role_rank=ROLE_RANK["admin"])
    if result is None:
        return
    target_user, _, _ = result
    reset_warnings(update.effective_chat.id, target_user.id)
    await update.message.reply_text(f"تمام ✅ اتصفرت إنذارات {target_user.full_name}")


async def try_handle_group_admin_trigger(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """أوامر إدارة بالعربي: رد على رسالة الشخص واكتب "رفع مدير" أو "حظر" أو "كتم" أو "انذار" وهكذا."""
    if update.effective_chat.type not in ("group", "supergroup"):
        return False
    if update.message.reply_to_message is None:
        return False

    text = (update.message.text or "").strip()

    if text.startswith("رفع "):
        role_word = text[len("رفع "):].strip()
        role = ROLE_NAME_TO_KEY.get(role_word)
        if role is None:
            return False
        target_user = update.message.reply_to_message.from_user
        if target_user is None or target_user.is_bot:
            await update.message.reply_text("مينفعش تدي رتبة لبوت 🙏")
            return True
        await _perform_setrole(update, context, target_user, role)
        return True

    if text in ("نزل", "نزل الرتبة", "شيل الرتبة"):
        target_user = update.message.reply_to_message.from_user
        if target_user is None or target_user.is_bot:
            return False
        actor_rank = get_user_rank(update.effective_chat.id, update.effective_user.id)
        target_rank = get_user_rank(update.effective_chat.id, target_user.id)
        if actor_rank <= target_rank:
            await update.message.reply_text("الشخص ده رتبته أعلى منك أو زيك")
            return True
        remove_group_role(update.effective_chat.id, target_user.id)
        await update.message.reply_text(f"تمام ✅ اتشالت كل الرتب من {target_user.full_name}")
        return True

    if text == "حظر":
        await ban_command(update, context)
        return True

    if text == "كتم":
        await mute_command(update, context)
        return True

    if text in ("فك كتم", "فك الكتم"):
        await unmute_command(update, context)
        return True

    if text in ("انذار", "إنذار"):
        await warn_command(update, context)
        return True

    return False


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
        "/togglereminder — تشغيل/إيقاف تذكير الغياب\n"
        "/banlist — عرض كل المحظورين\n"
        "/unban <آيدي> — فك الحظر عن حد\n\n"
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


async def unban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("الأمر ده متاح للأدمن بس 🙏")
        return
    if not context.args:
        await update.message.reply_text(
            "استخدمه كده: /unban <رقم الآيدي>\n"
            "لو نسيت الآيدي، استخدم /banlist عشان تشوف كل المحظورين"
        )
        return
    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("لازم تبعت رقم آيدي صحيح 🙏")
        return
    unban_user(target_id)
    await update.message.reply_text(f"تمام ✅ اتفك الحظر عن {target_id}")


async def banlist_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("الأمر ده متاح للأدمن بس 🙏")
        return
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT user_id, banned_at FROM banned_users ORDER BY banned_at DESC")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    if not rows:
        await update.message.reply_text("مفيش حد محظور دلوقتي 👍")
        return
    lines = ["🚫 المحظورين حاليًا:\n"]
    for row in rows:
        lines.append(f"- {row['user_id']}")
    lines.append("\nلفك الحظر: /unban <الآيدي>")
    await update.message.reply_text("\n".join(lines))


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
    app.add_handler(CommandHandler("analyze", analyze_command))
    app.add_handler(CommandHandler("fortune", start_fortune))
    app.add_handler(CommandHandler("style", style_command))
    app.add_handler(CommandHandler("journal", start_journal))
    app.add_handler(CommandHandler("journalhistory", journal_history_command))
    app.add_handler(CommandHandler("futuremessage", start_future_message))
    app.add_handler(CommandHandler("help", help_command))

    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("broadcast", broadcast_command))
    app.add_handler(CommandHandler("unban", unban_command))
    app.add_handler(CommandHandler("setrole", setrole_command))
    app.add_handler(CommandHandler("unrole", unrole_command))
    app.add_handler(CommandHandler("roles", roles_command))
    app.add_handler(CommandHandler("ban", ban_command))
    app.add_handler(CommandHandler("unbangroup", unban_group_command))
    app.add_handler(CommandHandler("mute", mute_command))
    app.add_handler(CommandHandler("unmute", unmute_command))
    app.add_handler(CommandHandler("warn", warn_command))
    app.add_handler(CommandHandler("warnings", warnings_command))
    app.add_handler(CommandHandler("resetwarns", resetwarns_command))
    app.add_handler(CommandHandler("banlist", banlist_command))
    app.add_handler(CommandHandler("togglecheckin", toggle_checkin_command))
    app.add_handler(CommandHandler("togglereminder", toggle_reminder_command))
    app.add_handler(CommandHandler("remind", remind_command))

    app.add_handler(CallbackQueryHandler(mood_callback, pattern="^mood_"))
    app.add_handler(CallbackQueryHandler(games_callback, pattern="^game_"))
    app.add_handler(CallbackQueryHandler(trivia_callback, pattern="^trivia_"))
    app.add_handler(CallbackQueryHandler(moderation_callback, pattern="^mod(ban|ignore)_"))
    app.add_handler(CallbackQueryHandler(style_callback, pattern="^style_"))
    app.add_handler(CallbackQueryHandler(whisper_callback, pattern="^whisper_"))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # المهام المجدولة (محتاجة: pip install "python-telegram-bot[job-queue]")
    job_queue = app.job_queue
    job_queue.run_daily(daily_checkin_job, time=dtime(hour=9, minute=0, tzinfo=CAIRO_TZ))
    job_queue.run_daily(inactivity_reminder_job, time=dtime(hour=18, minute=0, tzinfo=CAIRO_TZ))
    job_queue.run_daily(weekly_summary_job, time=dtime(hour=20, minute=0, tzinfo=CAIRO_TZ))
    job_queue.run_daily(future_messages_delivery_job, time=dtime(hour=10, minute=0, tzinfo=CAIRO_TZ))
    job_queue.run_repeating(hourly_religious_message_job, interval=7200, first=60)
    job_queue.run_daily(cleanup_old_whispers_job, time=dtime(hour=4, minute=0, tzinfo=CAIRO_TZ))
    job_queue.run_repeating(prayer_reminder_job, interval=60, first=10)

    logger.info("Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
