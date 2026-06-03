import React, { useState, useEffect, useRef } from 'react';
import { 
  Bot, 
  Send, 
  Code, 
  BookOpen, 
  Copy, 
  Check, 
  RefreshCw, 
  Play, 
  FileCode, 
  Sparkles, 
  Book, 
  ExternalLink,
  Smartphone,
  CheckCheck,
  AlertCircle,
  Cpu,
  Bookmark
} from 'lucide-react';

// Static template contracts for Telegram Bots in Python
const TEMPLATES: Record<string, Record<string, string>> = {
  'python-telegram-bot': {
    welcome: `import os
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# Logging setup - terminal debugging এ এটি খুব কাজের
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/start কমান্ড হ্যান্ডলার"""
    user_name = update.effective_user.first_name
    await update.message.reply_text(
        f"আসসালামু আলাইকুম {user_name}! আমি আপনার তৈরি চমৎকার টেলিগ্রাম বট।\\n"
        "আমি সঠিকভাবে কাজ করছি! আরও অপশন দেখতে /help দিন।"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/help কমান্ড হ্যান্ডলার"""
    await update.message.reply_text(
        "আপনাকে সাহায্য করতে নিচে কিছু কমান্ড দেওয়া হলো:\\n"
        "/start - বট চালু করুন\\n"
        "/help - সাহায্য নির্দেশিকা দেখুন"
    )

if __name__ == '__main__':
    # .env ফাইল বা এনভায়রনমেন্ট থেকে টোকেন নিরাপদে সংগ্রহ করা হচ্ছে
    TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    if not TOKEN:
        # টোকেন না থাকলে ক্র্যাশ করার হাত থেকে বাঁচতে সতর্কীকরণ মেসেজ
        raise ValueError("TELEGRAM_BOT_TOKEN environment variable not set! Please check your credentials.")
    
    # বট অ্যাপ্লিকেশন বিল্ড করা হচ্ছে
    app = ApplicationBuilder().token(TOKEN).build()
    
    # আমাদের ফাংশনগুলোকে কমান্ডের সাথে যুক্ত করা হচ্ছে
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    
    print("বটটি সফলভাবে চালু হয়েছে! নিষ্ক্রিয় করতে Ctrl+C চাপুন।")
    app.run_polling()`,
    inline: `import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes

logging.basicConfig(level=logging.INFO)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ইনলাইন বাটন সহ একটি মেসেজ পাঠানো"""
    keyboard = [
        [
            InlineKeyboardButton("🎯 ওয়েবসাইট", url="https://google.com"),
            InlineKeyboardButton("📊 কোর্স ফি", callback_data='fee')
        ],
        [
            InlineKeyboardButton("📞 যোগাযোগ", callback_data='contact')
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text('দয়া করে নিচের যেকোনো একটি অপশন ক্লিক করুন:', reply_markup=reply_markup)

async def handle_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """বাটনের ক্লিকের পর রেসপন্স হ্যান্ডেল করা"""
    query = update.callback_query
    await query.answer() # বাটন ক্লিক রিকনফর্ম করার জন্য এটি দরকার
    
    if query.data == 'fee':
        await query.edit_message_text(text="সবোর্চ্চ ডিসকাউন্টে পাইথন কোর্সের ফি মাত্র ৩,০০০ টাকা!")
    elif query.data == 'contact':
        await query.edit_message_text(text="আমাদের হেল্পলাইন: support@mybot.com")

if __name__ == '__main__':
    TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    app = ApplicationBuilder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_button))
    
    print("বাটন বট রান করছে...")
    app.run_polling()`,
    form: `import os
import logging
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ConversationHandler,
    ContextTypes
)

logging.basicConfig(level=logging.INFO)

# স্টেট ডিফাইন (স্টেপ ম্যানেজমেন্টের জন্য নম্বর)
NAME, PHONE = range(2)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """রেজিস্ট্রেশন শুরু করা"""
    await update.message.reply_text("আসসালামু আলাইকুম! রেজিস্ট্রেশন প্রক্রিয়া শুরু হলো।\\nআপনার সম্পূর্ণ নামটি লিখুন:")
    return NAME

async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """নাম সংগ্রহ করা"""
    context.user_data['full_name'] = update.message.text
    await update.message.reply_text("চমৎকার! এবার আপনার সচল মোবাইল নম্বর দিন:")
    return PHONE

async def get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """নম্বর সংগ্রহ এবং সমাপ্তি"""
    phone = update.message.text
    name = context.user_data['full_name']
    
    await update.message.reply_text(
        f"ধন্যবাদ! আপনার তথ্য সংরক্ষিত হয়েছে:\\n"
        f"👤 নাম: {name}\\n"
        f"📞 ফোন: {phone}\\n\\n"
        "রেজিস্ট্রেশন সফল সমাপ্ত!"
    )
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """প্রক্রিয়া বাতিল করা"""
    await update.message.reply_text("রেজিস্ট্রেশন প্রক্রিয়া বাতিল করা হয়েছে।")
    return ConversationHandler.END

if __name__ == '__main__':
    TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    app = ApplicationBuilder().token(TOKEN).build()
    
    # কনভারসেশন হ্যান্ডলার ডিক্লেয়ারেশন
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_phone)]
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    
    app.add_handler(conv_handler)
    print("কনভারসেশন বট রানিং...")
    app.run_polling()`
  },
  'pyTelegramBotAPI': {
    welcome: `import os
import telebot

# টোকেন লোড করা হচ্ছে
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN variable is not configured!")

bot = telebot.TeleBot(TOKEN)

@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_name = message.from_user.first_name
    bot.reply_to(
        message, 
        f"আসসালামু আলাইকুম {user_name}! আমি telebot (pyTelegramBotAPI) লাইব্রেরি দিয়ে তৈরি বট।\\n"
        "নতুন কোনো কমান্ড যোগ করতে এডিটরটি ব্যবহার করুন।"
    )

@bot.message_handler(commands=['help'])
def send_help(message):
    bot.send_message(
        message.chat.id,
        "আমি আপনাকে সাহায্য করতে সর্বদা প্রস্তুত!\\n/start - শুরু করুন\\n/help - সাহায্য দেখুন"
    )

if __name__ == '__main__':
    print("Telebot চালু হয়েছে, লুপ পোলিং চালু হচ্ছে...")
    bot.infinity_polling()`,
    inline: `import os
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
bot = telebot.TeleBot(TOKEN)

@bot.message_handler(commands=['start'])
def send_welcome(message):
    # ইনলাইন কিবোর্ড বাটন তৈরি
    markup = InlineKeyboardMarkup()
    markup.row_width = 2
    markup.add(
        InlineKeyboardButton("📚 কোর্স সমুহ", callback_data="courses"),
        InlineKeyboardButton("📌 সাপোর্ট গ্রুপ", callback_data="support")
    )
    bot.send_message(message.chat.id, "নিচের অপশনগুলো এক্সপ্লোর করুন:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    # ক্লিক রিসিভ করা ও কনফার্ম করা
    bot.answer_callback_query(call.id)
    
    if call.data == "courses":
        bot.send_message(call.message.chat.id, "আমাদের পাইথন ল্যাব ও মোবাইল অ্যাপ ডেভেলপমেন্ট কোর্স চালু আছে।")
    elif call.data == "support":
        bot.send_message(call.message.chat.id, "আমাদের অফিসিয়াল সাপোর্ট টেলিগ্রাম লিঙ্কে জয়েন করুন: @mysupport_group")

if __name__ == '__main__':
    print("বাটন হ্যান্ডলার চালু হয়েছে...")
    bot.infinity_polling()`,
    form: `import os
import telebot

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
bot = telebot.TeleBot(TOKEN)

# ইউজার ডেটা সংরক্ষণের জন্য ডিকশনারি
user_dict = {}

class User:
    def __init__(self, name):
        self.name = name
        self.phone = None

@bot.message_handler(commands=['start'])
def start_form(message):
    msg = bot.reply_to(message, "রেজিস্ট্রেশন শুরু হলো।\\nঅনুগ্রহ করে আপনার নামটি লিখুন:")
    # পরবর্তী স্টেপ ফাংশন ট্র্যাকিং করা
    bot.register_next_step_handler(msg, process_name_step)

def process_name_step(message):
    try:
        chat_id = message.chat.id
        name = message.text
        user = User(name)
        user_dict[chat_id] = user
        
        msg = bot.reply_to(message, "চমৎকার! এবার আপনার সচল ফোন নম্বর দিন:")
        bot.register_next_step_handler(msg, process_phone_step)
    except Exception as e:
        bot.reply_to(message, 'দুঃখিত, কোনো একটি সমস্যা হয়েছে!')

def process_phone_step(message):
    try:
        chat_id = message.chat.id
        phone = message.text
        user = user_dict[chat_id]
        user.phone = phone
        
        bot.send_message(
            chat_id,
            f"ধন্যবাদ! রেজিস্ট্রেশন সম্পন্ন হয়েছে:\\n👤 নাম: {user.name}\\n📞 ফোন: {user.phone}"
        )
    except Exception as e:
        bot.reply_to(message, 'দুঃখিত, কোনো একটি সমস্যা হয়েছে!')

if __name__ == '__main__':
    print("স্টেপ ফরম বট তৈরি চালু হচ্ছে...")
    bot.infinity_polling()`
  }
};

interface Message {
  id: number;
  sender: 'user' | 'bot';
  text: string;
  time: string;
}

export default function App() {
  const [library, setLibrary] = useState<'python-telegram-bot' | 'pyTelegramBotAPI'>('python-telegram-bot');
  const [botType, setBotType] = useState<'welcome' | 'inline' | 'form' | 'custom'>('custom');
  const [prompt, setPrompt] = useState<string>('আমার এই কোডটি সুন্দর করে সাজাও, SQLite টেবিল ইনিশিয়েলাইজেশন ঠিক করো এবং ইউজার ডাটাবেজ ট্র্যাক করো।');
  const [currentCode, setCurrentCode] = useState<string>(`from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)
import os
import sqlite3
import logging

# ডেটাবেস সংযোগ স্থাপন
# check_same_thread=False একাধিক থ্রেড থেকে নিরাপদ অ্যাক্সেস নিশ্চিত করে
conn = sqlite3.connect("database.db", check_same_thread=False)
cur = conn.cursor()

# কাস্টম লগিং কনফিগারেশন
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# বট টোকেন ও এডমিন আইডি কনফিগারেশন 
TOKEN = "8988076515:AAFzIJRGskC3wYQr-yeQW7jmJu6Fs_hwzzY"
ADMIN_ID = 8079009018

# SQLite ডেটাবেস টেবিল তৈরি (যদি আগে থেকে না থাকে)
cur.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    balance INTEGER DEFAULT 0,
    referrals INTEGER DEFAULT 0,
    pending_reward INTEGER DEFAULT 0,
    earned_reward INTEGER DEFAULT 0,
    referrer_id INTEGER DEFAULT 0
)
""")

# উইথড্রয়াল ডাটাবেস টেবিল
cur.execute("""
CREATE TABLE IF NOT EXISTS withdrawals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    amount INTEGER,
    method TEXT,
    number TEXT,
    status TEXT DEFAULT 'pending'
)
""")
conn.commit()

def load_users():
    """SQLite ডেটাবেস থেকে সব ইউনিক ব্যবহারকারীর আইডি তালিকা লোড করা"""
    try:
        temp_cur = conn.cursor()
        temp_cur.execute("SELECT user_id FROM users")
        return set(row[0] for row in temp_cur.fetchall())
    except Exception as e:
        logger.error(f"Error loading users: {e}")
        return set()

def save_user(user_id, referrer_id=0):
    """নতুন ব্যবহারকারীর ডেটাবেস এন্ট্রি করা এবং রেফারার ট্র্যাক করা"""
    temp_cur = conn.cursor()
    temp_cur.execute(  
        "SELECT user_id FROM users WHERE user_id=?",  
        (user_id,)  
    )  

    if temp_cur.fetchone() is None:  
        # নতুন ইউজার যুক্ত করা
        temp_cur.execute(  
            """  
            INSERT INTO users  
            (user_id, balance, referrals, pending_reward, earned_reward, referrer_id)  
            VALUES (?, 0, 0, 0, 0, ?)  
            """,  
            (user_id, referrer_id)  
        )  

        # রেফারার বোনাস ম্যানেজমেন্ট
        if referrer_id != 0:  
            temp_cur.execute(  
                "SELECT user_id FROM users WHERE user_id=?",  
                (referrer_id,)  
            )  
            if temp_cur.fetchone():  
                temp_cur.execute(  
                    """  
                    UPDATE users  
                    SET referrals = referrals + 1,  
                        pending_reward = pending_reward + 20  
                    WHERE user_id=?  
                    """,  
                    (referrer_id,)  
                )  

        conn.commit()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/start কমান্ড হ্যান্ডলার - রেফারেন্স চেক করে এবং কাস্টম কীবোর্ড দেখায়"""
    user_id = update.effective_user.id  
    referrer_id = 0  

    if context.args:  
        try:  
            referrer_id = int(context.args[0])  
            if referrer_id == user_id:  
                referrer_id = 0  
        except ValueError:  
            referrer_id = 0  

    save_user(user_id, referrer_id)  

    if referrer_id != 0:  
        try:
            await context.bot.send_message(  
                chat_id=referrer_id,  
                text="🎉 New Referral Joined!\\n💰 Pending Reward: +20 Tk"  
            )  
        except Exception as e:
            logger.error(f"Referrer message delivery failed: {e}")

    await show_main_menu(update, "🎉 Welcome to BD94 EARNING!")

async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """এডমিন প্যানেল ভিউ"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Access Denied!")
        return

    await update.message.reply_text(  
        "👑 Admin Panel\\n\\n"  
        "/stats - User Count\\n"  
        "/broadcast <message> - Send Message\\n"  
        "/approve <request_id> - Approve withdrawal\\n"  
        "/reject <request_id> [optional message] - Reject withdrawal"  
    )

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """সব ইউজারের তালিকা গণনা"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Access Denied!")
        return

    users = load_users()  
    await update.message.reply_text(  
        f"📊 Total Users: {len(users)}"  
    )

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """বিজ্ঞপ্তি সব ইউজারের কাছে ব্রডকাস্ট করা"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Access Denied!")
        return

    if not context.args:  
        await update.message.reply_text(  
            "Usage:\\n/broadcast Your Message"  
        )  
        return  

    message = " ".join(context.args)  
    users = load_users()  
    sent = 0  

    for user_id in users:  
        try:  
            await context.bot.send_message(  
                chat_id=int(user_id),  
                text=message  
            )  
            sent += 1  
        except Exception:  
            pass  

    await update.message.reply_text(  
        f"✅ Message sent to {sent} users"  
    )

async def approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """এডমিন দ্বারা উইথড্রয়াল রিকোয়েস্ট অ্যাপ্রুভ হ্যান্ডলার"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Access Denied!")
        return

    if not context.args:
        await update.message.reply_text("ব্যবহার নিয়ম: /approve <request_id>")
        return

    try:
        req_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ আইডি অবশ্যই একটি সংখ্যা হতে হবে!")
        return

    temp_cur = conn.cursor()
    temp_cur.execute("SELECT user_id, amount, status, method, number FROM withdrawals WHERE id = ?", (req_id,))
    row = temp_cur.fetchone()
    if not row:
        await update.message.reply_text("❌ এই Request ID খুঁজে পাওয়া যায়নি!")
        return

    user_id, amount, status, method, number = row
    if status != "pending":
        await update.message.reply_text(f"❌ রিকোয়েস্টটি ইতিপূর্বে {status} করা হয়েছে!")
        return

    # রিকোয়েস্ট অ্যাপ্রুভ স্ট্যাটাস আপডেট
    temp_cur.execute("UPDATE withdrawals SET status = 'approved' WHERE id = ?", (req_id,))

    # ইউজারকে নোটিফিকেশন পাঠানো
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=f"🎉 Withdrawal Approved\\n\\n"
                 f"আপনার #{req_id} নম্বর রিকোয়েস্টটি অ্যাপ্রুভ হয়েছে।\\n"
                 f"💰 Amount: {amount} Tk\\n"
                 f"📱 Method: {method}\\n"
                 f"📞 Account: {number}\\n\\n"
                 f"আপনার একাউন্ট ব্যালেন্স থেকে টাকা কেটে নেওয়া হয়েছে।"
        )
    except Exception as e:
        logger.error(f"Failed to notify user: {e}")

    # যাকে রেফার করেছেন তার প্রথম উইথড্র কিনা যাচাই করুন
    temp_cur.execute(
        "SELECT COUNT(*) FROM withdrawals WHERE user_id = ? AND status = 'approved' AND id != ?",
        (user_id, req_id)
    )
    prev_approved = temp_cur.fetchone()[0]

    if prev_approved == 0:
        # এটিই প্রথম সফল উইথড্র
        temp_cur.execute("SELECT referrer_id FROM users WHERE user_id = ?", (user_id,))
        ref_row = temp_cur.fetchone()
        if ref_row and ref_row[0] != 0:
            referrer_id = ref_row[0]
            
            # রেফারারের পেন্ডিং বোনাস কমে যাবে এবং আর্নড ব্যালেন্সে যোগ হবে
            temp_cur.execute("""
                UPDATE users 
                SET balance = balance + 20,
                    earned_reward = earned_reward + 20,
                    pending_reward = CASE WHEN pending_reward >= 20 THEN pending_reward - 20 ELSE 0 END
                WHERE user_id = ?
            """, (referrer_id,))
            
            # রেফারারকে অভিনন্দন মেসেজ পাঠানো
            try:
                await context.bot.send_message(
                    chat_id=referrer_id,
                    text="🎉 Referral Reward Verified!\\n"
                         "আপনার রেফার করা user সফলভাবে withdraw সম্পন্ন করেছে।\\n"
                         "💰 Reward Added: 20 Tk"
                )
            except Exception as e:
                logger.error(f"Failed to notify referrer: {e}")

    conn.commit()
    await update.message.reply_text(f"✅ Request #{req_id} অ্যাপ্রুভ করা হয়েছে এবং রেফারাল রিওয়ার্ড আপডেট করা হয়েছে।")

async def reject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """এডমিন দ্বারা উইথড্রয়াল রিকোয়েস্ট রিজেক্ট এবং রিফান্ড হ্যান্ডলার"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Access Denied!")
        return

    if not context.args:
        await update.message.reply_text("ব্যবহার নিয়ম: /reject <request_id> [ঐচ্ছিক কারণ]")
        return

    try:
        req_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ আইডি অবশ্যই একটি সংখ্যা হতে হবে!")
        return

    custom_reject_msg = " ".join(context.args[1:]) if len(context.args) > 1 else "কোনো নির্দিষ্ট কারণ দর্শানো হয়নি।"

    temp_cur = conn.cursor()
    temp_cur.execute("SELECT user_id, amount, status FROM withdrawals WHERE id = ?", (req_id,))
    row = temp_cur.fetchone()
    if not row:
        await update.message.reply_text("❌ এই Request ID খুঁজে পাওয়া যায়নি!")
        return

    user_id, amount, status = row
    if status != "pending":
        await update.message.reply_text(f"❌ রিকোয়েস্টটি ইতিপূর্বে {status} করা হয়েছে!")
        return

    # রিজেক্ট করা এবং ব্যালেন্স রিফান্ড করা
    temp_cur.execute("UPDATE withdrawals SET status = 'rejected' WHERE id = ?", (req_id,))
    temp_cur.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
    conn.commit()

    # ইউজারকে ব্যালেন্স রিফান্ডের নোটিফিকেশন পাঠানো
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=f"❌ Withdrawal Request Rejected\\n\\n"
                 f"আপনার #{req_id} নম্বর রিকোয়েস্টটি বাতিল করা হয়েছে এবং {amount} Tk আপনার ব্যালেন্সে ফেরত দেওয়া হয়েছে।\\n"
                 f"💬 Reason: {custom_reject_msg}"
        )
    except Exception as e:
        logger.error(f"Failed to notify user: {e}")

    await update.message.reply_text(f"❌ Request #{req_id} বাতিল করা হয়েছে এবং ব্যালেন্স রিফান্ড করা হয়েছে।")

async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """কাস্টম কিবোর্ড বাটন ক্লিকের ট্রিগার অ্যাকশনসমূহ"""
    text = update.message.text
    user_id = update.effective_user.id
    temp_cur = conn.cursor()

    # ইউজার যদি বর্তমান স্টেপে পেমেন্ট নম্বর ইনপুট দেয়
    if context.user_data.get("withdraw_step") == "awaiting_number":
        if text == "🔙 Back" or text == "❌ Cancel":
            context.user_data.pop("withdraw_step", None)
            return await show_withdraw_amounts(update, context)

        # নাম্বার ইনপুট সেভ করুন
        context.user_data["number"] = text
        context.user_data["withdraw_step"] = "awaiting_confirm"

        keyboard = [
            ["✅ Continue"],
            ["🔙 Back", "❌ Cancel"]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await update.message.reply_text(
            f"💰 Amount Selected: {context.user_data.get('amount')}\\n"
            f"📱 Method Selected: {context.user_data.get('method')}\\n"
            f"📞 Account No: {text}\\n\\n"
            f"অনুরোধটি চূড়ান্ত করতে '✅ Continue' বাটন ক্লিক করুন বা সংশোধন করতে '🔙 Back' দিন।",
            reply_markup=reply_markup
        )
        return

    if text == "👤 Profile":  
        temp_cur.execute(  
            "SELECT balance, referrals FROM users WHERE user_id=?",  
            (user_id,)  
        )  
        data = temp_cur.fetchone()  
        balance = data[0] if data else 0
        referrals = data[1] if data else 0

        await update.message.reply_text(  
            f"👤 User ID: {user_id}\\n\\n"  
            f"💰 Balance: {balance} Tk\\n"  
            f"👥 Referrals: {referrals}"  
        )  

    elif text == "💰 Balance":  
        temp_cur.execute(  
            "SELECT balance FROM users WHERE user_id=?",  
            (user_id,)  
        )  
        data = temp_cur.fetchone()  
        balance = data[0] if data else 0
        await update.message.reply_text(f"💰 Current Balance: {balance} Tk")  

    elif text == "👥 Referral":  
        temp_cur.execute(  
            "SELECT referrals, pending_reward, earned_reward FROM users WHERE user_id=?",  
            (user_id,)  
        )  
        data = temp_cur.fetchone()  

        if data:  
            referrals = data[0]  
            pending_reward = data[1]  
            earned_reward = data[2]  
        else:  
            referrals = 0  
            pending_reward = 0  
            earned_reward = 0  

        bot_username = "Bd94earningbot"  

        await update.message.reply_text(  
            f"👥 Your Referral Link:\\n"  
            f"https://t.me/{bot_username}?start={user_id}\\n\\n"  
            f"✅ Verified Referral: {earned_reward // 20}\\n"  
            f"⏳ Pending Referral: {pending_reward // 20}\\n\\n"  
            f"💰 Verified Referral Balance: {earned_reward} Tk\\n"  
            f"⏳ Pending Referral Balance: {pending_reward} Tk\\n\\n"  
            f"⚠️ রেফার রিওয়ার্ড নিয়মাবলী\\n\\n"  
            f"🎁 প্রতি সফল রেফারে রিওয়ার্ড: ২০ টাকা\\n\\n"  
            f"✅ আপনি যাকে রেফার করেছেন, তিনি সফলভাবে একটি উইথড্র সম্পন্ন করলে তবেই আপনার ২০ টাকার রিওয়ার্ড নিশ্চিত হবে।\\n\\n"  
            f"⏳ ততক্ষণ পর্যন্ত রিওয়ার্ডটি Pending Reward হিসেবে থাকবে।"  
        )  

    elif text == "🎁 Bonus":  
        await update.message.reply_text(  
            "🎁 Bonus System Coming Soon"  
        )  
        
    elif text == "💳 Withdraw":
        await show_withdraw_amounts(update, context)

    elif text in ["150 Tk", "300 Tk", "500 Tk", "1000 Tk"]:
        # ব্যালেন্স পর্যাপ্ত কিনা রিকোয়েস্টের শুরুতেই ফিজিক্যাল চেক
        req_amount = int(text.split()[0])
        temp_cur.execute("SELECT balance FROM users WHERE user_id=?", (user_id,))
        row = temp_cur.fetchone()
        user_bal = row[0] if row else 0

        if user_bal < req_amount:
            await update.message.reply_text(
                f"❌ দুঃখিত, আপনার ব্যালেন্স পর্যাপ্ত নয়!\\n"
                f"আপনার বর্তমান ব্যালেন্স: {user_bal} Tk"
            )
            return

        context.user_data["amount"] = text
        keyboard = [
            ["📱 bKash", "📱 Nagad"],
            ["🔙 Back"]
        ]
        reply_markup = ReplyKeyboardMarkup(
            keyboard,
            resize_keyboard=True
        )
        await update.message.reply_text(
            f"💰 Amount Selected: {text}\\n\\n"
            f"📱 Payment Method নির্বাচন করুন:",
            reply_markup=reply_markup
        )

    elif text in ["📱 bKash", "📱 Nagad"]:
        if "amount" not in context.user_data:
            await update.message.reply_text("প্রথমে অনুগ্রহ করে উইথড্র করার পরিমাণটি সিলেক্ট করুন।")
            return await show_withdraw_amounts(update, context)

        context.user_data["method"] = text
        context.user_data["withdraw_step"] = "awaiting_number"

        keyboard = [
            ["🔙 Back", "❌ Cancel"]
        ]
        reply_markup = ReplyKeyboardMarkup(
            keyboard,
            resize_keyboard=True
        )
        await update.message.reply_text(
            f"💳 Method Selected: {text}\\n\\n"
            f"📞 এখন আপনার {text} নাম্বার লিখে পাঠান।",
            reply_markup=reply_markup
        ) 

    elif text == "✅ Continue":
        amount_str = context.user_data.get("amount")
        method = context.user_data.get("method")
        number = context.user_data.get("number")

        if not amount_str or not method or not number:
            await update.message.reply_text("❌ কোনো একটি ধাপ অসম্পূর্ণ রয়েছে! অনুগ্রহ করে নতুন করে সাবমিট করুন।")
            context.user_data.clear()
            return await show_main_menu(update, "মেনুতে ফিরিয়ে নেওয়া হলো।")

        amount = int(amount_str.split()[0])

        # ব্যালেন্স পুনরায় চেক করে তৎক্ষণাৎ ডেবিট করা হচ্ছে (ডাবল স্পেন্ড প্রিভেন্ট করতে)
        temp_cur.execute("SELECT balance FROM users WHERE user_id=?", (user_id,))
        row = temp_cur.fetchone()
        user_bal = row[0] if row else 0

        if user_bal < amount:
            await update.message.reply_text(
                f"❌ দুঃখিত, আপনার ব্যালেন্স পর্যাপ্ত নয়!\\n"
                f"আপনার বর্তমান ব্যালেন্স: {user_bal} Tk"
            )
            context.user_data.clear()
            return await show_main_menu(update, "হোম মেনু:")

        # ব্যালেন্স কর্তন করুন
        temp_cur.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (amount, user_id))

        # ডেটাবেসে পেন্ডিং রিকোয়েস্ট সেভ
        temp_cur.execute(
            """
            INSERT INTO withdrawals (user_id, amount, method, number, status)
            VALUES (?, ?, ?, ?, 'pending')
            """,
            (user_id, amount, method, number)
        )
        req_id = temp_cur.lastrowid
        conn.commit()

        # স্টেট ক্লিয়ার করা
        context.user_data.clear()

        # ইউজারকে রিকোয়েস্ট সাবমিটের নিশ্চিতকরণ বার্তা প্রদর্শন
        await update.message.reply_text(
            f"✅ Withdrawal Request Submitted!\\n\\n"
            f"Request ID: #{req_id}\\n"
            f"Amount: {amount} Tk\\n"
            f"Method: {method}\\n"
            f"Number: {number}\\n\\n"
            f"আপনার রিকোয়েস্টটি সফলভাবে সাবমিট করা হয়েছে! এডমিন দ্রুত ভেরিফাই করে পেমেন্ট পাঠিয়ে দেবে এবং আপনি নোটিফিকেশন পাবেন।",
            reply_markup=ReplyKeyboardMarkup([  
                ["👤 Profile", "💰 Balance"],  
                ["👥 Referral", "🎁 Bonus"],  
                ["💳 Withdraw", "📜 History"],  
                ["📞 Support", "ℹ️ About"]  
            ], resize_keyboard=True)
        )

        # এডমিনকে নতুন উইথড্রয়াল আর্লার্ট পাঠানো
        try:
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=f"👑 New Withdrawal Request!\\n\\n"
                     f"Request ID: #{req_id}\\n"
                     f"User ID: {user_id}\\n"
                     f"Amount: {amount} Tk\\n"
                     f"Method: {method}\\n"
                     f"Number: {number}\\n\\n"
                     f"অ্যাপ্রুভ করতে ক্লিক / টাইপ করুন:\\n"
                     f"/approve {req_id}\\n\\n"
                     f"বাতিল করতে ও রিফান্ড দিতে:\\n"
                     f"/reject {req_id} [কারণ]"
            )
        except Exception as e:
            logger.error(f"Failed to notify admin of new request: {e}")

    elif text == "🔙 Back" or text == "❌ Cancel":
        # পূর্ববর্তী কনটেক্সটের ভিত্তিতে ধাপে ধাপে ফিরে যাওয়ার ব্যাক-ট্র্যাকিং হ্যান্ডলার
        if "number" in context.user_data or context.user_data.get("withdraw_step") == "awaiting_confirm":
            # নাম্বার পপ ব্যাক করে মেথড সিলেকশনে ফিরে যান
            context.user_data.pop("number", None)
            context.user_data["withdraw_step"] = "awaiting_number"
            keyboard = [
                ["🔙 Back", "❌ Cancel"]
            ]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            await update.message.reply_text(
                f"💳 Method Selected: {context.user_data.get('method')}\\n\\n"
                f"📞 এখন আপনার {context.user_data.get('method')} নাম্বার পুনরায় লিখে পাঠান।",
                reply_markup=reply_markup
            )
        elif "method" in context.user_data or context.user_data.get("withdraw_step") == "awaiting_number":
            # মেথড ক্লিয়ার করে অ্যামাউন্ট সিলেকশনে ফিরে যান
            context.user_data.pop("method", None)
            context.user_data.pop("withdraw_step", None)
            await show_withdraw_amounts(update, context)
        elif "amount" in context.user_data:
            # অ্যামাউন্ট ক্লিয়ার করে মেইন মেনুতে ফেরত যান
            context.user_data.clear()
            await show_main_menu(update, "মেনুতে ফেরত যাওয়া হলো।")
        else:
            context.user_data.clear()
            await show_main_menu(update, "মেনুতে ফেরত যাওয়া হলো।")

    elif text == "📜 History":  
        temp_cur.execute(
            "SELECT id, amount, method, status FROM withdrawals WHERE user_id = ? ORDER BY id DESC LIMIT 5",
            (user_id,)
        )
        rows = temp_cur.fetchall()
        if not rows:
            await update.message.reply_text("📜 No History Found")  
        else:
            hist = "📜 Your Recent Withdrawals:\\n\\n"
            for r in rows:
                ico = "⏳" if r[3] == "pending" else "✅" if r[3] == "approved" else "❌"
                hist += f"Request #{r[0]} - {r[1]} Tk via {r[2]} ({ico} {r[3]})\\n"
            await update.message.reply_text(hist)

    elif text == "📞 Support":  
        await update.message.reply_text(  
            "📞 Contact Admin: @BD94_Support_Admin"  
        )  

    elif text == "ℹ️ About":  
        await update.message.reply_text(  
            "ℹ️ BD94 EARNING BOT v2.0\\n\\n"
            "এটি একটি বিশ্বস্ত ও নির্ভরযোগ্য রেফারাল ব্যালেন্স আর্নিং প্ল্যাটফর্ম যা থ্রেড-সেফ SQLite ডাটাবেস ও পাইথন টেলিগ্রাম বট ফ্রেমওয়ার্ক দিয়ে পরিচালিত।"
        )

async def show_withdraw_amounts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """উইথড্র করার পরিমাণ সিলেকশন কিবোর্ড"""
    keyboard = [
        ["150 Tk", "300 Tk"],
        ["500 Tk", "1000 Tk"],
        ["🔙 Back"]
    ]
    reply_markup = ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True
    )
    await update.message.reply_text(
        "💳 Withdraw Amount নির্বাচন করুন:",
        reply_markup=reply_markup
    )

async def show_main_menu(update: Update, msg_text: str):
    """প্রধান মেনু কিবোর্ড প্রদর্শন"""
    keyboard = [  
        ["👤 Profile", "💰 Balance"],  
        ["👥 Referral", "🎁 Bonus"],  
        ["💳 Withdraw", "📜 History"],  
        ["📞 Support", "ℹ️ About"]  
    ]  
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(msg_text, reply_markup=reply_markup)

# অ্যাপ্লিকেশন রানার লাইফ সাইকেল
app = Application.builder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("admin", admin))
app.add_handler(CommandHandler("stats", stats))
app.add_handler(CommandHandler("broadcast", broadcast))
app.add_handler(CommandHandler("approve", approve))
app.add_handler(CommandHandler("reject", reject))

app.add_handler(
    MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        buttons
    )
)

print("Bot running...")
app.run_polling()`);
  const [generatedCode, setGeneratedCode] = useState<string>('');
  const [generatedGuide, setGeneratedGuide] = useState<string>('');
  const [copiedCode, setCopiedCode] = useState<boolean>(false);
  const [isGenerating, setIsGenerating] = useState<boolean>(false);
  const [selectedRepoFile, setSelectedRepoFile] = useState<string>('bot.py');
  
  // Simulation states
  const [simulatedMessages, setSimulatedMessages] = useState<Message[]>([
    { id: 1, sender: 'bot', text: 'আসসালামু আলাইকুম! আপনার টেলিগ্রাম বটের জন্য সম্পূর্ণ গিটহাব রিপোজিটরি স্ট্রাকচার তৈরি করা হয়েছে। কোড রান বা ডিপ্লয় করার আগে নিচের চ্যাটে টেস্ট করুন! 😊', time: '12:00 PM' }
  ]);
  const [simulationInput, setSimulationInput] = useState<string>('');
  const [isSimulating, setIsSimulating] = useState<boolean>(false);
  const [activeTab, setActiveTab] = useState<'code' | 'guide'>('code');

  const getRepositoryFiles = () => {
    const code = generatedCode || currentCode;
    const requirements = `python-telegram-bot==20.8
python-dotenv==1.0.1`;
    const gitignore = `# Render & Python environment ignore rules
database.db
database.db-journal
.env
.venv
venv/
env/
__pycache__/
*.py[cod]
*$py.class
.DS_Store`;
    
    const readmeDescription = generatedGuide 
      ? generatedGuide 
      : `### BD94 Telegram Earning Bot v2.0
      
আপনার রেফারেল এবং উইথড্রয়াল লজিকসহ SQLite সমর্থিত সুন্দর টেলিগ্রাম বটের GitHub ডিপ্লয়মেন্ট ফোল্ডার।

- **bot.py**: মূল বটের ফাইল (সুরক্ষিত environment ভেরিয়েবল এবং Render লাইভ-সার্ভার ইন্টিগ্রেশন সহ)।
- **requirements.txt**: রেন্ডার ও পিসির জন্য দরকারি প্যাকেজ।
- **.gitignore**: সুরক্ষার জন্য ফাইল ও ডাটাবেজ ইগনোর করা।`;

    const readme = `# 🚀 BD94 Telegram Earning Bot - GitHub Repository

ডিজিটাল রেফারেল আর্নিং বটটি সফলভাবে GitHub এবং Render ডেভলপমেন্টের উপযোগী করে সাজানো হয়েছে। 

## 📁 রিপোজিটরি ফাইল স্ট্রাকচার:
\`\`\`text
├── bot.py             # মূল টেলিগ্রাম বট কোড (SQLite & Render Web Server লাইভ-সার্পোট সহ)
├── requirements.txt   # নির্ভরতা প্যাকেজ তালিকা (Render বা স্থানীয় পিসির জন্য)
├── .gitignore         # সুরক্ষার জন্য ডেটাবেজ ও এনভায়রনমেন্ট ফাইল ইগনোর
└── README.md          # এই চমৎকার রিডমি গাইড
\`\`\`

---

## 🛠️ সিস্টেমের মূল বৈশিষ্ট্যসমূহ:
1. **সুরক্ষিত এপিআই টোকেন**: হার্ডকোডেড টোকেন রিমুভ করে \`os.getenv("TELEGRAM_BOT_TOKEN")\` এর মাধ্যমে নিরাপদ কনফিগারেশন করা হয়েছে।
2. **SQLite ডাটাবেজ সমর্থন**: ব্যবহারকারীর তথ্য ও উইথড্রয়াল প্রসেস সুরক্ষিত থ্রেড-সেফ SQLite ডাটাবেজে সংরক্ষিত থাকে।
3. **Render ২৪/৭ লাইভ সচলতা**: কোডে একটি লাইটওয়েট ব্যাকগ্রাউন্ড ওযেব-সার্ভার যুক্ত করা হয়েছে যা Render-এর ফ্রি টায়ারে পোর্ট বাইন্ডিং বজায় রেখে বটটিকে সচল রাখবে!
4. **রেফারেল এবং উইথড্রয়াল লজিক অক্ষুণ্ণ**: নিখুঁতভাবে রেফারেল রিওয়ার্ড বণ্টন, পেন্ডিং বোনাস ও অ্যাডমিন কন্ট্রোল নিশ্চিত করা হয়েছে।

---

## 💻 স্থানীয় পিসিতে চালুর নিয়ম (Local PC Setup Guide):
১. এই ডিপোজিটরির সব ফাইল (যেমন \`bot.py\`, \`requirements.txt\`, এবং \`.gitignore\`) একটি ফোল্ডারে ডাউনলোড করুন।
২. টার্মিনালে নিচের কমান্ডের সাহায্যে প্যাকেজগুলো ইনস্টল করুন:
   \`\`\`bash
   pip install -r requirements.txt
   \`\`\`
৩. আপনার প্রজেক্টের রুট ফোল্ডারে একটি \`.env\` ফাইল তৈরি করুন এবং আপনার টোকেন ও অ্যাডমিন আইডি দিন:
   \`\`\`env
   TELEGRAM_BOT_TOKEN="your_bot_token_here"
   ADMIN_ID=8079009018
   \`\`\`
৪. বট রান করুন:
   \`\`\`bash
   python bot.py
   \`\`\`

---

## 🌐 Render এ সম্পূর্ণ ফ্রি ডিপ্লয় করার নিয়ম (Render Deployment Details):

১. **GitHub রিপোজিটরি তৈরি করুন**:
   - github.com এ গিয়ে একটি নতুন পাবলিক/প্রাইভেট রিপোজিটরি তৈরি করুন।
   - সেখানে \`bot.py\`, \`requirements.txt\`, এবং \`.gitignore\` ফাইলগুলো পুশ করুন।

২. **Render-এ কনফিগার করুন**:
   - [Render Dashboard (dashboard.render.com)](https://dashboard.render.com/) এ যান।
   - **New+** বাটন ক্লিক করে **Web Service** সিলেক্ট করুন এবং আপনার GitHub এর কানেক্ট করুন।
   - নিম্নলিখিত সেটিংস দিন:
     - **Name**: \`bd94-earning-bot\`
     - **Runtime**: \`Python\`
     - **Build Command**: \`pip install -r requirements.txt\`
     - **Start Command**: \`python bot.py\`
     - **Instance Type**: \`Web Service (Free)\` (সম্পূর্ণ ফ্রি টায়ার)

৩. **এনভায়রনমেন্ট ভেরিয়েবল সেট আপ করুন (অত্যಂತ গুরুত্বপূর্ণ)**:
   Render এর Dashboard-এর **Environment** ট্যাবে গিয়ে নিচের দুইটি কী (Key) এবং সেগুলোর মান (Value) এড করুন:
   - \`TELEGRAM_BOT_TOKEN\` = \`আপনার_টেলিগ্রাম_বট_টোকেন\`
   - \`ADMIN_ID\` = \`আপনার_টেলিগ্রাম_আইডি_যেমন: 8079009018\`

ব্যাস! আপনার টেলিগ্রাম স্পন্সরড আর্নিং বটটি Render ক্লাউডে সফলভাবে ডেপ্লয় হয়ে যাবে। 🎉

---
### 📖 সাজানো ও বাগ-ফিক্স সমাচার:
\${readmeDescription}
`;

    return {
      'bot.py': code,
      'requirements.txt': requirements,
      '.gitignore': gitignore,
      'README.md': readme
    };
  };

  const chatBottomRef = useRef<HTMLDivElement>(null);

  // Set default initial template code on startup/library switch
  useEffect(() => {
    if (botType !== 'custom') {
      const templateText = TEMPLATES[library]?.[botType] || '';
      setCurrentCode(templateText);
    }
  }, [library, botType]);

  // Handle template selection
  const handleTemplateLoad = (type: 'welcome' | 'inline' | 'form') => {
    setBotType(type);
    setCurrentCode(TEMPLATES[library][type]);
    setPrompt('');
  };

  // Scroll to bottom of chat
  useEffect(() => {
    chatBottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [simulatedMessages, isSimulating]);

  // Copy code utility
  const copyToClipboard = () => {
    const files = getRepositoryFiles();
    const codeToCopy = files[selectedRepoFile] || currentCode;
    navigator.clipboard.writeText(codeToCopy);
    setCopiedCode(true);
    setTimeout(() => setCopiedCode(false), 2000);
  };

  // call REST API endpoint to optimize or generate bot code
  const handleGenerateCode = async () => {
    setIsGenerating(true);
    try {
      const response = await fetch('/api/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          prompt: prompt || 'Optimize code structure, add comprehensive Bangla/Bengali comments, use robust env configuration, and detail how to run.',
          currentCode,
          library,
          botType
        })
      });

      const data = await response.json();
      if (response.ok) {
        // Extract code block and text from response
        const fullResponseText = data.text || '';
        
        // Simple code block regex extractor
        const codeBlockRegex = /```python\n([\s\S]*?)```/;
        const match = fullResponseText.match(codeBlockRegex);

        if (match && match[1]) {
          setGeneratedCode(match[1].trim());
          // Remove code block from guide representation to create clean text
          const cleanGuideText = fullResponseText.replace(codeBlockRegex, '\n*(কোডটি উপরে ডেডিকেটেড কোড উইন্ডোতে রয়েছে, অনুগ্রহ করে কোড ট্যাবে কপি করুন)*\n');
          setGeneratedGuide(cleanGuideText);
        } else {
          setGeneratedCode(currentCode); // fallback
          setGeneratedGuide(fullResponseText);
        }
        setActiveTab('code');

        // Append automation message to simulated Telegram
        setSimulatedMessages(prev => [
          ...prev, 
          { 
            id: Date.now(), 
            sender: 'bot', 
            text: `✨ নতুন বটের সংস্করণ তৈরি সম্পন্ন হয়েছে! এই নতুন লজিক টেস্ট করার জন্য চ্যাটের নিচে টেস্ট করুন। নতুন ফিচার অনুযায়ী এটি কাজ করবে।`, 
            time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) 
          }
        ]);
      } else {
        alert('কোড সাজাতে সমস্যা হয়েছে: ' + (data.error || 'Server internal error'));
      }
    } catch (err: any) {
      alert('Error querying server: ' + err.message);
    } finally {
      setIsGenerating(false);
    }
  };

  // call REST simulation endpoint to emulate responses
  const handleSendMessage = async (customMessage?: string) => {
    const messageToSend = customMessage || simulationInput;
    if (!messageToSend.trim()) return;

    if (!customMessage) {
      setSimulationInput('');
    }

    const timeString = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    const userMsg: Message = { id: Date.now(), sender: 'user', text: messageToSend, time: timeString };

    setSimulatedMessages(prev => [...prev, userMsg]);
    setIsSimulating(true);

    try {
      const botCodeContext = generatedCode || currentCode;
      
      const response = await fetch('/api/simulate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          userMessage: messageToSend,
          botCode: botCodeContext,
          botType,
          library,
          chatHistory: simulatedMessages.slice(-8) // Send recent message chain context
        })
      });

      const data = await response.json();
      if (response.ok) {
        setSimulatedMessages(prev => [
          ...prev,
          { 
            id: Date.now() + 1, 
            sender: 'bot', 
            text: data.text || 'কোনো প্রতিক্রিয়া পাওয়া যায়নি।', 
            time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) 
          }
        ]);
      } else {
        setSimulatedMessages(prev => [
          ...prev,
          { id: Date.now() + 1, sender: 'bot', text: '⚠️ সিমুলেশন সার্ভার কানেক্ট করা যায়নি। কোডে কোনো সিনট্যাক্স ভুল আছে কিনা যাচাই করুন।', time: timeString }
        ]);
      }
    } catch (err: any) {
      setSimulatedMessages(prev => [
        ...prev,
        { id: Date.now() + 1, sender: 'bot', text: '⚠️ সংযোগ করতে সমস্যা হয়েছে। আবার চেষ্টা করুন।', time: timeString }
      ]);
    } finally {
      setIsSimulating(false);
    }
  };

  // Clean whole current workspace to start fresh
  const handleClearWorkspace = () => {
    if (window.confirm("আপনি কি নতুন করে খালি স্ক্রিপ্ট থেকে শুরু করতে চান?")) {
      setBotType('custom');
      setCurrentCode('# নিজের টেলিগ্রাম বটের পাইথন কোড এখানে পেস্ট করুন...\n\n');
      setPrompt('');
      setGeneratedCode('');
      setGeneratedGuide('');
      setSimulatedMessages([
        { id: Date.now(), sender: 'bot', text: 'ক্লিন করা হয়েছে! আপনার নিজের কোড পেস্ট করে আমাদের বলুন কি পরিবর্তন বা ফিক্স করতে চান। 😊', time: 'Just details' }
      ]);
    }
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col font-sans" id="app-root">
      
      {/* Premium Elegant Header */}
      <header className="border-b border-slate-800 bg-slate-900/65 backdrop-blur py-5 px-6 sticky top-0 z-50 shadow-md flex flex-wrap items-center justify-between gap-4" id="app-header">
        <div className="flex items-center gap-3">
          <div className="p-2 bg-blue-600 rounded-xl shadow-lg shadow-blue-500/20" id="brand-logo-container">
            <Bot className="w-8 h-8 text-white animate-pulse" />
          </div>
          <div>
            <h1 className="text-xl font-extrabold tracking-tight bg-gradient-to-r from-blue-400 via-sky-300 to-indigo-400 bg-clip-text text-transparent flex items-center gap-2">
              Telegram Bot Python Lab <span className="text-xs bg-cyan-950 text-cyan-400 border border-cyan-800/60 px-2 py-0.5 rounded-full font-sans">বাংলা</span>
            </h1>
            <p className="text-xs text-slate-400 font-medium mt-0.5">
              পাইথন দিয়ে সহজে টেলিগ্রাম বট সাজানো, এরর হ্যান্ডেল ও লাইভ প্রিভিউতে টেস্ট করার চমৎকার পরিবেশ।
            </p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <a 
            href="https://core.telegram.org/bots/api" 
            target="_blank" 
            rel="noopener noreferrer" 
            className="flex items-center gap-1.5 text-xs text-slate-400 hover:text-white bg-slate-800 hover:bg-slate-700 transition px-3.5 py-2 rounded-lg border border-slate-700/80 font-medium"
            id="tg-doc-link"
          >
            Telegram Bot API <ExternalLink className="w-3.5 h-3.5" />
          </a>
          <button
            onClick={() => handleTemplateLoad('welcome')}
            className="flex items-center gap-1.5 text-xs text-blue-400 hover:text-white bg-blue-950/45 hover:bg-blue-600 px-3.5 py-2 rounded-lg border border-blue-800/50 transition font-semibold"
            id="reset-lab-btn"
          >
            <RefreshCw className="w-3.5 h-3.5" /> রিস্টার্ট ল্যাব
          </button>
        </div>
      </header>

      {/* Main Core Layout: Grid Layout */}
      <main className="flex-1 max-w-7xl w-full mx-auto p-4 md:p-6 grid grid-cols-1 lg:grid-cols-12 gap-6" id="main-content-workspace">
        
        {/* Left Control and Inputs Column: Grid span 7 */}
        <div className="lg:col-span-7 flex flex-col gap-6" id="left-column">
          
          {/* Card 1: Select Python Library & Direct Template Loaders */}
          <div className="bg-slate-900 border border-slate-800/90 rounded-2xl p-5 shadow-sm" id="control-panel-settings">
            <h2 className="text-sm font-bold text-slate-300 flex items-center gap-2 uppercase tracking-wider mb-4 border-b border-slate-800/80 pb-2">
              <Cpu className="w-4 h-4 text-blue-400" /> ১. লাইব্রেরি ও প্রিসেট নির্বাচন
            </h2>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label className="block text-xs font-semibold text-slate-400 mb-2">পছন্দের পাইথন ফ্রেমওয়ার্ক:</label>
                <div className="grid grid-cols-2 gap-2" id="framework-selectors">
                  <button
                    onClick={() => setLibrary('python-telegram-bot')}
                    className={`px-3 py-2.5 rounded-xl border text-xs font-semibold flex items-center justify-center gap-2 transition ${
                      library === 'python-telegram-bot' 
                        ? 'bg-blue-600/15 border-blue-500 text-blue-300 shadow-md shadow-blue-500/5' 
                        : 'bg-slate-800/40 border-slate-700 hover:bg-slate-800 text-slate-400'
                    }`}
                  >
                    🐍 python-telegram-bot (Async)
                  </button>
                  <button
                    onClick={() => setLibrary('pyTelegramBotAPI')}
                    className={`px-3 py-2.5 rounded-xl border text-xs font-semibold flex items-center justify-center gap-2 transition ${
                      library === 'pyTelegramBotAPI' 
                        ? 'bg-blue-600/15 border-blue-500 text-blue-300 shadow-md shadow-blue-500/5' 
                        : 'bg-slate-800/40 border-slate-700 hover:bg-slate-800 text-slate-400'
                    }`}
                  >
                    📡 pyTelegramBotAPI (telebot)
                  </button>
                </div>
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-400 mb-2">রেডি-মেড ব্লুপ্রিন্ট লোড করুন:</label>
                <div className="grid grid-cols-3 gap-2" id="blueprint-buttons">
                  <button
                    onClick={() => handleTemplateLoad('welcome')}
                    className={`px-2.5 py-2 rounded-xl text-center text-xs font-semibold border transition ${
                      botType === 'welcome'
                        ? 'bg-indigo-600/15 border-indigo-500 text-indigo-300'
                        : 'bg-slate-850 border-slate-800 text-slate-400 hover:bg-slate-800'
                    }`}
                    title="বেসিক কমান্ড ও স্বাগতম হ্যান্ডলার"
                  >
                    👋 স্বাগতম বট
                  </button>
                  <button
                    onClick={() => handleTemplateLoad('inline')}
                    className={`px-2.5 py-2 rounded-xl text-center text-xs font-semibold border transition ${
                      botType === 'inline'
                        ? 'bg-indigo-600/15 border-indigo-500 text-indigo-300'
                        : 'bg-slate-850 border-slate-800 text-slate-400 hover:bg-slate-800'
                    }`}
                    title="ইনলাইন বাটন ক্লিক হ্যান্ডলিং"
                  >
                    🎯 বাটন মেনু
                  </button>
                  <button
                    onClick={() => handleTemplateLoad('form')}
                    className={`px-2.5 py-2 rounded-xl text-center text-xs font-semibold border transition ${
                      botType === 'form'
                        ? 'bg-indigo-600/15 border-indigo-500 text-indigo-300'
                        : 'bg-slate-850 border-slate-800 text-slate-400 hover:bg-slate-800'
                    }`}
                    title="স্টেপ-বাই-স্টেপ কনভারসেশন বা স্টেট মেশিন"
                  >
                    📝 ইউজার ফরম
                  </button>
                </div>
              </div>
            </div>
          </div>

          {/* Card 2: Main Code Editor & AI Customization Prompt */}
          <div className="bg-slate-900 border border-slate-800/90 rounded-2xl flex flex-col flex-1 shadow-sm overflow-hidden min-h-[500px]" id="editor-card-container">
            
            {/* Header of code editor */}
            <div className="bg-slate-950 px-5 py-3 border-b border-slate-800/80 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <FileCode className="w-4.5 h-4.5 text-sky-400" />
                <span className="text-xs font-bold tracking-wide uppercase text-slate-300">
                  {library === 'python-telegram-bot' ? 'bot.py (Asynchronous API)' : 'bot.py (TeleBot Sync API)'}
                </span>
                {botType === 'custom' && (
                  <span className="text-[10px] bg-amber-950 font-bold text-amber-500 border border-amber-800/30 px-2 py-0.5 rounded">Custom</span>
                )}
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={handleClearWorkspace}
                  className="text-slate-500 hover:text-slate-300 text-xs px-2.5 py-1 rounded hover:bg-slate-900 border border-transparent hover:border-slate-800 transition"
                  id="clear-workspace-btn"
                  title="কোড খালি করুন"
                >
                  নতুন স্ক্রিপ্ট
                </button>
                <span className="text-[10px] text-slate-500 border border-slate-850 bg-slate-900 px-2 py-0.5 rounded font-mono">Python 3.10+</span>
              </div>
            </div>

            {/* Python Textarea container */}
            <div className="relative flex-1 bg-slate-950/45 p-1" id="textarea-frame">
              <textarea
                value={currentCode}
                onChange={(e) => {
                  setCurrentCode(e.target.value);
                  setBotType('custom');
                }}
                className="w-full h-full min-h-[300px] lg:min-h-[380px] bg-transparent text-slate-200 p-4 font-mono text-sm leading-relaxed focus:outline-none focus:ring-0 resize-none whitespace-pre overflow-auto scrollbar-thin scrollbar-thumb-slate-800"
                placeholder="# আপনার পাইথন বট স্ক্রিপ্টটি এখানে লিখুন / পেস্ট করুন..."
                spellCheck="false"
                id="python-code-textarea"
              />
            </div>

            {/* AI Enhancement Input form wrapper */}
            <div className="bg-slate-950/80 p-5 border-t border-slate-800" id="ai-input-form-box">
              <div className="flex items-start gap-3">
                <div className="p-2 bg-gradient-to-br from-indigo-500 to-purple-600 rounded-xl mt-1 shrink-0" id="smart-spark-logo">
                  <Sparkles className="w-4 h-4 text-white" />
                </div>
                <div className="flex-1">
                  <label className="block text-xs font-bold text-slate-300 mb-1.5 flex items-center justify-between">
                    <span>বটে নতুন ফিচার যোগ করুন বা সমস্যা সমাধান করুন:</span>
                    <span className="text-[10px] text-slate-500 font-normal">আমাদের বিশেষজ্ঞ AI আপনার জন্য কোডটি নিখুঁতভাবে রি-কনফিগার করবে।</span>
                  </label>
                  <textarea
                    value={prompt}
                    onChange={(e) => setPrompt(e.target.value)}
                    rows={2}
                    className="w-full bg-slate-900 text-slate-200 border border-slate-800 rounded-xl px-3.5 py-2 text-xs leading-relaxed focus:outline-none focus:border-indigo-500/80 transition"
                    placeholder="উদাহরণ: একটি নতুন /register কমান্ড যোগ করো যা ব্যবহারকারীর ফোন নম্বর নিবে, অথবা সব উত্তরের ভাষা বাংলা করে সাজাও..."
                    id="ai-instructions-prompt"
                  />
                </div>
              </div>

              {/* Perform Formatting & Clean Action */}
              <div className="flex justify-end items-center gap-3 mt-4" id="submit-action-row">
                <span className="text-[11px] text-indigo-400 font-medium bg-indigo-950/30 border border-indigo-900/40 px-3 py-1 rounded-lg">
                  💡 বটের সিকিউরিটি ও লগার অটো-কনফিগার করা হবে।
                </span>
                <button
                  onClick={handleGenerateCode}
                  disabled={isGenerating}
                  className={`px-5 py-2.5 rounded-xl text-xs font-bold font-sans flex items-center gap-2 shadow-lg hover:shadow-indigo-550/15 text-white transition-all cursor-pointer ${
                    isGenerating 
                      ? 'bg-slate-850 text-slate-500 border border-slate-800' 
                      : 'bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 border border-indigo-500/40'
                  }`}
                  id="arrange-code-big-btn"
                >
                  {isGenerating ? (
                    <>
                      <RefreshCw className="w-4 h-4 animate-spin text-indigo-400" />
                      বটের কোড প্রসেস হচ্ছে...
                    </>
                  ) : (
                    <>
                      <Sparkles className="w-4 h-4 text-indigo-200" />
                      ✨ Clean & Structure Code
                    </>
                  )}
                </button>
              </div>
            </div>
          </div>
        </div>

        {/* Right Output Workspace Panel: Renders Output Codes & simulated Sandbox Chat Screen (cols 5) */}
        <div className="lg:col-span-5 flex flex-col gap-6" id="right-column">
          
          {/* Section 1: Telegram Live App Simulator (Sandbox) */}
          <div className="bg-slate-900 border border-slate-800/90 rounded-2xl flex flex-col h-[520px] shadow-xl overflow-hidden" id="telegram-simulator-box">
            
            {/* Simulated Desktop Header of Telegram App */}
            <div className="bg-slate-850 px-4 py-3 border-b border-indigo-900/20 flex items-center justify-between shrink-0" id="sim-header">
              <div className="flex items-center gap-3">
                <div className="relative" id="profile-avatar">
                  <div className="w-9 h-9 bg-gradient-to-tr from-sky-400 to-blue-600 rounded-full flex items-center justify-center font-bold text-white tracking-wider text-xs shadow-inner">
                    {botType === 'welcome' ? 'WB' : botType === 'inline' ? 'BB' : botType === 'form' ? 'FB' : 'CB'}
                  </div>
                  <div className="absolute -bottom-0.5 -right-0.5 w-3 h-3 bg-emerald-500 rounded-full border-2 border-slate-850" title="Bot is Active" />
                </div>
                <div>
                  <h3 className="text-xs font-bold text-slate-100 flex items-center gap-1">
                    My Custom Bot <span className="text-[9px] bg-blue-950 text-blue-400 border border-blue-800/45 px-1.5 py-0.2 rounded font-sans uppercase font-bold">Bot</span>
                  </h3>
                  <div className="text-[10px] text-emerald-400 font-medium flex items-center gap-1">
                    <span className="w-1.5 h-1.5 bg-emerald-400 rounded-full animate-ping" />
                    simulated active • online
                  </div>
                </div>
              </div>
              <div className="flex items-center gap-1.5" id="sim-info-pills">
                <span className="text-[10px] bg-slate-900 text-slate-400 px-2 py-0.5 rounded-full font-semibold border border-slate-800 flex items-center gap-1">
                  <Smartphone className="w-3 h-3" /> Sandbox Mode
                </span>
              </div>
            </div>

            {/* Chat Messages Frame representing bubbles */}
            <div className="flex-1 bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-slate-900 via-slate-950 to-slate-950 p-4 overflow-y-auto scrollbar-thin flex flex-col gap-3" id="chats-display-window">
              {simulatedMessages.map((msg) => (
                <div 
                  key={msg.id} 
                  className={`flex flex-col max-w-[85%] ${msg.sender === 'user' ? 'ml-auto items-end' : 'mr-auto items-start'}`}
                  id={`chat-msg-${msg.id}`}
                >
                  <div 
                    className={`p-3 rounded-2xl text-xs leading-relaxed shadow-md whitespace-pre-wrap ${
                      msg.sender === 'user' 
                        ? 'bg-blue-600 text-white rounded-tr-none' 
                        : 'bg-slate-800 text-slate-100 rounded-tl-none border border-slate-755/50'
                    }`}
                  >
                    {msg.text}
                  </div>
                  
                  {/* Message bubble metadata info link */}
                  <div className="flex items-center gap-1.5 mt-1 px-1 text-[9px] text-slate-500 font-medium">
                    <span>{msg.time}</span>
                    {msg.sender === 'user' && <CheckCheck className="w-3.5 h-3.5 text-blue-400" />}
                  </div>
                </div>
              ))}
              
              {/* Bot thinking placeholder status */}
              {isSimulating && (
                <div className="mr-auto flex items-center gap-2 bg-slate-800/60 border border-slate-755/20 p-3 rounded-2xl rounded-tl-none text-xs text-slate-400 font-medium shadow-md">
                  <div className="flex space-x-1 items-center py-1">
                    <div className="w-1.5 h-1.5 bg-sky-400 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                    <div className="w-1.5 h-1.5 bg-sky-400 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                    <div className="w-1.5 h-1.5 bg-sky-400 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
                  </div>
                  <span className="text-[10px] text-slate-400 ml-1">বট উত্তর টাইপ করছে...</span>
                </div>
              )}
              <div ref={chatBottomRef} />
            </div>

            {/* Quick Helper Test Command buttons wrapper */}
            <div className="bg-slate-950/75 px-4 py-2 border-t border-slate-850 flex flex-wrap items-center gap-1.5 shrink-0" id="quick-test-triggers">
              <span className="text-[10px] text-slate-500 font-bold mr-1.5">কমান্ড টেস্ট:</span>
              <button
                onClick={() => handleSendMessage('/start')}
                className="text-[10px] bg-slate-900 border border-slate-800 hover:border-slate-700 hover:bg-slate-800 text-slate-300 font-bold px-2.5 py-1 rounded-md transition"
              >
                /start 🚀
              </button>
              <button
                onClick={() => handleSendMessage('/help')}
                className="text-[10px] bg-slate-900 border border-slate-800 hover:border-slate-700 hover:bg-slate-800 text-slate-300 font-bold px-2.5 py-1 rounded-md transition"
              >
                /help 📘
              </button>
              {botType === 'inline' && (
                <>
                  <button
                    onClick={() => handleSendMessage('fee')}
                    className="text-[10px] bg-indigo-950/45 border border-indigo-900/60 hover:bg-indigo-900 text-indigo-300 font-semibold px-2.5 py-1 rounded-md transition"
                  >
                    📊 কোর্সবোতাম ক্লিক
                  </button>
                  <button
                    onClick={() => handleSendMessage('contact')}
                    className="text-[10px] bg-indigo-950/45 border border-indigo-900/60 hover:bg-indigo-900 text-indigo-300 font-semibold px-2.5 py-1 rounded-md transition"
                  >
                    📞 যোগাযোগক্লিক
                  </button>
                </>
              )}
              <button
                onClick={() => setSimulatedMessages([{ id: Date.now(), sender: 'bot', text: 'চ্যাট ইতিহাস নতুন করে ক্লিন করা হয়েছে। এখন আপনার বটের নতুন কোড টেস্ট শুরু করুন!', time: 'Sim' }])}
                className="ml-auto text-[9px] text-slate-500 hover:text-slate-300 font-semibold"
                title="চ্যাট ক্লিন করুন"
              >
                ক্লিন চ্যাট
              </button>
            </div>

            {/* Bottom text Input Area */}
            <div className="bg-slate-900 p-3 border-t border-slate-800 shrink-0" id="sim-input-box">
              <form 
                onSubmit={(e) => {
                  e.preventDefault();
                  handleSendMessage();
                }} 
                className="flex items-center gap-2"
              >
                <input
                  type="text"
                  value={simulationInput}
                  onChange={(e) => setSimulationInput(e.target.value)}
                  placeholder="বটকে টেস্ট করতে মেসেজ বা কমান্ড (/start) লিখুন..."
                  className="flex-1 bg-slate-950 border border-slate-800 rounded-xl px-3.5 py-2 text-xs text-slate-200 focus:outline-none focus:border-blue-500/80 transition"
                  id="sim-chat-input-input"
                />
                <button
                  type="submit"
                  className="p-2.5 bg-blue-600 hover:bg-blue-500 text-white rounded-xl shadow shadow-blue-600/30 transition cursor-pointer"
                  id="send-sim-msg-btn"
                >
                  <Send className="w-3.5 h-3.5" />
                </button>
              </form>
            </div>
          </div>

          {/* Section 2: GitHub Repository Explorer & Deployment Guides */}
          <div className="bg-slate-900 border border-slate-800/90 rounded-2xl p-5 flex flex-col flex-1 shadow-sm shrink-0 min-h-[420px]" id="output-documentation-card">
            
            <div className="flex items-center justify-between border-b border-slate-800 pb-3 mb-4" id="output-tabs-row">
              <div className="flex items-center gap-1.5" id="github-repo-title">
                <Code className="w-4 h-4 text-sky-400" />
                <span className="text-xs font-bold uppercase tracking-wider text-slate-300">
                  📁 GitHub Repository Builder
                </span>
                <span className="text-[9px] bg-emerald-950 text-emerald-400 border border-emerald-800/35 px-2 py-0.5 rounded font-mono font-bold">
                  Deploy-Ready
                </span>
              </div>

              <div className="flex items-center gap-2">
                <button
                  onClick={copyToClipboard}
                  className="flex items-center gap-1.5 text-[11px] bg-slate-800 hover:bg-slate-700 hover:text-white px-3 py-1.5 rounded-xl text-slate-350 font-bold transition border border-slate-700/60"
                  id="copy-to-clipboard-btn"
                >
                  {copiedCode ? (
                    <>
                      <Check className="w-3.5 h-3.5 text-emerald-400" /> কপি হয়েছে!
                    </>
                  ) : (
                    <>
                      <Copy className="w-3.5 h-3.5 text-slate-400" /> Copy Selected
                    </>
                  )}
                </button>
              </div>
            </div>

            {/* Layout representation with left sidebar for Files Tree and right side for actual content */}
            <div className="grid grid-cols-1 md:grid-cols-12 gap-4 flex-1 min-h-[300px]" id="github-repo-layout">
              
              {/* Left File Tree Sidebar: Grid span 4 */}
              <div className="md:col-span-4 flex flex-col gap-2.5 bg-slate-950 p-3.5 rounded-xl border border-slate-850/65" id="repo-file-tree">
                <span className="text-[10px] font-bold text-slate-500 uppercase tracking-wider block px-1.5">FILES EXPLORER</span>
                
                <div className="flex flex-col gap-1 mt-1">
                  
                  {/* File 1: bot.py */}
                  <button
                    onClick={() => setSelectedRepoFile('bot.py')}
                    className={`flex items-center justify-between px-3 py-2 rounded-lg text-xs font-semibold text-left transition ${
                      selectedRepoFile === 'bot.py'
                        ? 'bg-blue-600/15 border border-blue-500/40 text-blue-300'
                        : 'border border-transparent hover:bg-slate-900 text-slate-400 hover:text-slate-200'
                    }`}
                  >
                    <span className="flex items-center gap-2">
                      <span className="text-amber-400 font-bold font-sans">🐍</span>
                      <span>bot.py</span>
                    </span>
                    <span className="text-[9px] bg-slate-900 border border-slate-800 text-slate-400 px-1 py-0.2 rounded font-mono">Py</span>
                  </button>

                  {/* File 2: requirements.txt */}
                  <button
                    onClick={() => setSelectedRepoFile('requirements.txt')}
                    className={`flex items-center justify-between px-3 py-2 rounded-lg text-xs font-semibold text-left transition ${
                      selectedRepoFile === 'requirements.txt'
                        ? 'bg-blue-600/15 border border-blue-500/40 text-blue-300'
                        : 'border border-transparent hover:bg-slate-900 text-slate-400 hover:text-slate-200'
                    }`}
                  >
                    <span className="flex items-center gap-2">
                      <span className="text-sky-400 font-bold font-sans">📄</span>
                      <span>requirements.txt</span>
                    </span>
                    <span className="text-[9px] bg-slate-900 border border-slate-800 text-slate-400 px-1 py-0.2 rounded font-mono">Txt</span>
                  </button>

                  {/* File 3: .gitignore */}
                  <button
                    onClick={() => setSelectedRepoFile('.gitignore')}
                    className={`flex items-center justify-between px-3 py-2 rounded-lg text-xs font-semibold text-left transition ${
                      selectedRepoFile === '.gitignore'
                        ? 'bg-blue-600/15 border border-blue-500/40 text-blue-300'
                        : 'border border-transparent hover:bg-slate-900 text-slate-400 hover:text-slate-200'
                    }`}
                  >
                    <span className="flex items-center gap-2">
                      <span className="text-slate-400 font-mono text-sm leading-none">⚙️</span>
                      <span>.gitignore</span>
                    </span>
                    <span className="text-[9px] bg-slate-900 border border-slate-800 text-slate-400 px-1 py-0.2 rounded font-mono">Git</span>
                  </button>

                  {/* File 4: README.md */}
                  <button
                    onClick={() => setSelectedRepoFile('README.md')}
                    className={`flex items-center justify-between px-3 py-2 rounded-lg text-xs font-semibold text-left transition ${
                      selectedRepoFile === 'README.md'
                        ? 'bg-blue-600/15 border border-blue-500/40 text-blue-300'
                        : 'border border-transparent hover:bg-slate-900 text-slate-400 hover:text-slate-200'
                    }`}
                  >
                    <span className="flex items-center gap-2">
                      <span className="text-emerald-400 font-bold">📝</span>
                      <span>README.md</span>
                    </span>
                    <span className="text-[9px] bg-slate-900 border border-slate-800 text-slate-400 px-1 py-0.2 rounded font-mono font-bold">Doc</span>
                  </button>

                </div>

                <div className="mt-auto pt-3 border-t border-slate-900 text-[10px] text-slate-500 font-medium px-1">
                  💡 গিটহাবে এই স্ট্রাকচারে ফাইলগুলো পুশ করে রেন্ডারে ইন্টিগ্রেট করুন।
                </div>
              </div>

              {/* Right File Content Display: Grid span 8 */}
              <div className="md:col-span-8 flex flex-col bg-slate-950 p-4 rounded-xl border border-slate-850/65 overflow-hidden" id="repo-file-content">
                <div className="flex items-center justify-between border-b border-slate-900 pb-2 mb-3 shrink-0">
                  <span className="font-mono text-xs text-slate-400 flex items-center gap-1.5 gray-800">
                    <span className="w-2 h-2 rounded-full bg-emerald-500" />
                    /bd94-earning-bot/{selectedRepoFile}
                  </span>
                  <span className="text-[10px] text-slate-500 font-medium font-sans">
                    {selectedRepoFile === 'bot.py' ? 'Python Source Code' : selectedRepoFile === 'README.md' ? 'Deployment Guide' : 'Config File'}
                  </span>
                </div>

                <div className="flex-1 overflow-auto text-xs font-medium max-h-[350px] scrollbar-thin" id="output-tab-contents">
                  {selectedRepoFile === 'README.md' ? (
                    <div className="whitespace-pre-wrap leading-relaxed text-slate-350 px-1 font-sans text-xs">
                      {getRepositoryFiles()['README.md']}
                    </div>
                  ) : (
                    <pre className="bg-transparent font-mono text-xs text-slate-300 whitespace-pre leading-relaxed select-text overflow-x-auto">
                      {getRepositoryFiles()[selectedRepoFile as keyof ReturnType<typeof getRepositoryFiles>] || ''}
                    </pre>
                  )}
                </div>
              </div>

            </div>
          </div>

          {/* Quick Cheat Sheet References / Copy formulas */}
          <div className="bg-slate-900 border border-slate-800/95 rounded-2xl p-5 shadow-sm" id="cheat-sheet-box">
            <h3 className="text-xs font-bold text-slate-300 uppercase tracking-wider mb-3 flex items-center gap-2">
              <Bookmark className="w-4 h-4 text-emerald-400" /> টেলিগ্রাম বট ডেভলপমেন্ট চিটশিট (Cheat sheet)
            </h3>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-slate-400 text-[11px] leading-relaxed">
              <div className="bg-slate-950/50 p-3 rounded-xl border border-slate-850">
                <span className="font-bold text-emerald-300 block mb-1">১) পিসিতে ডিপেনডেন্সি ইন্সটল করা:</span>
                <code className="bg-slate-950 p-1.5 rounded block text-[10px] text-slate-300 select-all font-mono">
                  pip install python-telegram-bot --upgrade
                </code>
                <span className="text-[9px] text-slate-500 block mt-1">pyTelegramBotAPI এর জন্য: pip install pyTelegramBotAPI</span>
              </div>
              <div className="bg-slate-950/50 p-3 rounded-xl border border-slate-850">
                <span className="font-bold text-emerald-300 block mb-1">২) .env ফাইলে টোকেন সেটআপ:</span>
                <p className="text-slate-400 text-[10px]">পিসির প্রজেক্ট ফোল্ডারে <code>.env</code> ফাইল তৈরি করে লিখুন:</p>
                <code className="bg-slate-950 p-1.5 rounded block text-[10px] text-slate-300 select-all mt-1 font-mono">
                  TELEGRAM_BOT_TOKEN="YOUR_BOT_TOKEN"
                </code>
              </div>
            </div>
          </div>

        </div>
      </main>

      {/* Styled Footer */}
      <footer className="mt-auto border-t border-slate-900 bg-slate-950 py-5 text-center text-xs text-slate-500 font-medium" id="app-footer">
        © 2026 Telegram Bot Python Assistant. Powered by Gemini 3.5. Crafted to build professional and beautiful Python scripts.
      </footer>
    </div>
  );
}
