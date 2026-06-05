import os
import sys
import logging
import sqlite3
import threading
import http.server
import socketserver
from teletele.ext import updater, commands  # আপনার ব্যবহৃত সঠিক লাইব্রেরি অনুযায়ী ইম্পোর্ট অ্যাডজাস্ট করুন
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, MessageHandler, Filters, CallbackContext, ConversationHandler

# Logging Setup
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Constants & Configurations
ADMIN_ID = 123456789  # আপনার আসল এডমিন আইডি এখানে বসান
DB_FILE = "bot_database.db"
PORT = int(os.environ.get("PORT", 8080))

# States for Conversation Handlers
(
    WAITING_TASK_TITLE, WAITING_TASK_DESC, WAITING_PROOF_TYPE, WAITING_TASK_RATE, WAITING_TASK_SLOTS,
    WAITING_SUBMISSION_PROOF, WAITING_REJECTION_REASON
) = range(7)

# ---------------- Database Initialization with WAL Mode ----------------
def get_db_connection():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL;")  # SQLite লক প্রটেকশন
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Users Table
    cursor.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        balance REAL DEFAULT 0.0,
        pending_balance REAL DEFAULT 0.0,
        warnings INTEGER DEFAULT 0
    )''')
    
    # Tasks Table
    cursor.execute('''CREATE TABLE IF NOT EXISTS tasks (
        task_id INTEGER PRIMARY KEY AUTOINCREMENT,
        creator_id INTEGER,
        category TEXT,
        title TEXT,
        description TEXT,
        proof_type TEXT, -- 'text' (ইউজার আইডি) অথবা 'photo' (স্ক্রিনশট)
        rate REAL,
        slots INTEGER,
        status TEXT DEFAULT 'pending' -- pending, approved, completed
    )''')
    
    # Submissions Table
    cursor.execute('''CREATE TABLE IF NOT EXISTS submissions (
        sub_id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id INTEGER,
        worker_id INTEGER,
        proof_data TEXT, -- Text proof or File ID
        status TEXT DEFAULT 'pending', -- pending, approved, rejected, disputed
        rejection_reason TEXT
    )''')
    
    conn.commit()
    conn.close()

init_db()

# ---------------- Self-Recovering Health Check Web Server for Render ----------------
def start_health_check_server():
    class HealthCheckHandler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-type", "text/plain")
            self.end_headers()
            self.wfile.write(b"Bot is alive and running!")

    class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
        allow_reuse_address = True

    try:
        server = ThreadedTCPServer(("0.0.0.0", PORT), HealthCheckHandler)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        logger.info(f"Health check server started on port {PORT}")
    except Exception as e:
        logger.error(f"Failed to start health check server: {e}")

# ---------------- Helper Functions (Broadcast & State) ----------------
def broadcast_new_task(context: CallbackContext, task_category, rate, slots):
    """ নতুন টাস্ক অ্যাড হওয়ার সাথে সাথে সমস্ত একটিভ ইউজারকে অটো-ব্রডকাস্ট করে """
    conn = get_db_connection()
    users = conn.execute("SELECT user_id FROM users").fetchall()
    conn.close()
    
    text = (
        f"🔔 **New Task Added!**\n\n"
        f"📂 Category: {task_category}\n"
        f"💰 Rate: {rate} USDT\n"
        f"👥 Available Slots: {slots}\n\n"
        f"👉 বটের 'Find Job' অপশনে গিয়ে এখনই কাজটি সম্পন্ন করুন!"
    )
    
    for user in users:
        try:
            context.bot.send_message(chat_id=user['user_id'], text=text, parse_mode='Markdown')
        except Exception:
            continue  # যদি কোনো ইউজার বট ব্লক করে থাকে

# ---------------- Bot Commands & Menu ----------------
def start(update: Update, context: CallbackContext):
    user = update.effective_user
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", (user.id, user.username))
    conn.commit()
    conn.close()
    
    keyboard = [
        [InlineKeyboardButton("🔍 Find Job", callback_data="find_job")],
        [InlineKeyboardButton("➕ Post Task", callback_data="post_task")],
        [InlineKeyboardButton("💼 My Dashboard", callback_data="dashboard")]
    ]
    if user.id == ADMIN_ID:
        keyboard.append([InlineKeyboardButton("👑 Admin Panel", callback_data="admin_panel")])
        
    update.message.reply_text(
        f"হ্যালো {user.first_name}! আমাদের মাইক্রোজব বটে স্বাগতম।",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ---------------- Find Job & Dynamic Proof Submission Flow ----------------
def find_job_handler(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    
    # ক্যাটাগরি সিলেকশন (ডিমো হিসেবে ২ টি দেওয়া হলো)
    keyboard = [
        [InlineKeyboardButton("📱 Telegram Job", callback_data="cat_Telegram")],
        [InlineKeyboardButton("🎥 YouTube Job", callback_data="cat_YouTube")]
    ]
    query.edit_message_text("একটি ক্যাটাগরি সিলেক্ট করুন:", reply_markup=InlineKeyboardMarkup(keyboard))

def show_tasks_by_category(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    category = query.data.split('_')[1]
    
    conn = get_db_connection()
    tasks = conn.execute("SELECT * FROM tasks WHERE category = ? AND slots > 0 AND status = 'approved'", (category,)).fetchall()
    conn.close()
    
    if not tasks:
        query.edit_message_text(f"দুঃখিত, {category} ক্যাটাগরিতে এই মুহূর্তে কোনো কাজ খালি নেই।")
        return
        
    keyboard = []
    for task in tasks:
        keyboard.append([InlineKeyboardButton(f"{task['title']} - {task['rate']} USDT", callback_data=f"view_task_{task['task_id']}")])
        
    query.edit_message_text("যেকোনো একটি টাস্কের ওপর চাপ দিয়ে ডিটেইলস দেখুন:", reply_markup=InlineKeyboardMarkup(keyboard))

def view_task_details(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    task_id = query.data.split('_')[2]
    
    conn = get_db_connection()
    task = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
    conn.close()
    
    text = (
        f"📋 **Task:** {task['title']}\n"
        f"📝 **Description:** {task['description']}\n"
        f"💰 **Rate:** {task['rate']} USDT\n"
        f"👥 **Slots Left:** {task['slots']}\n"
    )
    
    context.user_data['current_submit_task_id'] = task_id
    context.user_data['proof_type'] = task['proof_type']
    
    keyboard = [[InlineKeyboardButton("🚀 Start/Next (Submit Work)", callback_data="start_submit_flow")]]
    query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    return WAITING_SUBMISSION_PROOF

def ask_for_proof(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    
    proof_type = context.user_data.get('proof_type')
    task_id = context.user_data.get('current_submit_task_id')
    
    conn = get_db_connection()
    task = conn.execute("SELECT description FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
    conn.close()
    
    # ডায়নামিক প্রুফ চেকিং লজিক
    if proof_type == "text":
        query.edit_message_text("👉 ক্রিয়েটর প্রুফ হিসেবে লেখা চেয়েছে। অনুগ্রহ করে আপনার ইউজার আইডি দিন:")
    else:
        query.edit_message_text("👉 ক্রিয়েটর প্রুফ হিসেবে ছবি চেয়েছে। আপনি যে কাজ করেছেন ওটার স্ক্রিনশট দিন:")
        
    return WAITING_SUBMISSION_PROOF

def handle_submission_proof(update: Update, context: CallbackContext):
    proof_type = context.user_data.get('proof_type')
    task_id = context.user_data.get('current_submit_task_id')
    worker_id = update.effective_user.id
    
    if proof_type == "text" and update.message.text:
        proof_data = update.message.text
    elif proof_type == "photo" and update.message.photo:
        proof_data = update.message.photo[-1].file_id
    else:
        # ভুল ফরম্যাট দিলে সতর্ক করা হবে
        expected = "আপনার ইউজার আইডি (লেখা)" if proof_type == "text" else "কাজের স্ক্রিনশট (ছবি)"
        update.message.reply_text(f"❌ ভুল প্রুফ ফরম্যাট! দয়া করে {expected} দিন।")
        return WAITING_SUBMISSION_PROOF
        
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # সাবমিশন ডাটা সংরক্ষণ
    cursor.execute("INSERT INTO submissions (task_id, worker_id, proof_data, status) VALUES (?, ?, ?, 'pending')",
                   (task_id, worker_id, proof_data))
    
    # পেন্ডিং ব্যালেন্স আপডেট
    task_rate = cursor.execute("SELECT rate FROM tasks WHERE task_id = ?", (task_id,)).fetchone()['rate']
    cursor.execute("UPDATE users SET pending_balance = pending_balance + ? WHERE user_id = ?", (task_rate, worker_id))
    
    # ক্রিয়েটরকে নোটিফাই করার জন্য টাস্ক ক্রিয়েটর আইডি নেওয়া
    creator_id = cursor.execute("SELECT creator_id FROM tasks WHERE task_id = ?", (task_id,)).fetchone()['creator_id']
    
    conn.commit()
    conn.close()
    
    update.message.reply_text("✅ আপনার প্রুফ সফলভাবে জমা হয়েছে! ক্রিয়েটর রিভিউ করার পর আপনার মেইন ব্যালেন্সে টাকা যুক্ত হবে।")
    
    # ক্রিয়েটরকে নোটিফিকেশন পাঠানো
    try:
        keyboard = [[InlineKeyboardButton("📊 Review Submissions", callback_data=f"creator_review_{task_id}")]]
        context.bot.send_message(chat_id=creator_id, text="📥 আপনার একটি টাস্কে নতুন প্রুফ জমা পড়েছে!", reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception:
        pass
        
    return ConversationHandler.END

# ---------------- Creator Review & Rejection Logic (Disputed Queue) ----------------
def creator_review_sub(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    task_id = query.data.split('_')[2]
    
    conn = get_db_connection()
    sub = conn.execute("SELECT * FROM submissions WHERE task_id = ? AND status = 'pending' LIMIT 1", (task_id,)).fetchone()
    conn.close()
    
    if not sub:
        query.edit_message_text("সবগুলো সাবমিশন অলরেডি রিভিউ করা শেষ!")
        return
        
    context.user_data['current_review_sub_id'] = sub['sub_id']
    
    text = f"⚙️ **Worker ID:** {sub['worker_id']}\n💬 **Proof Submitted:** See below"
    query.message.reply_text(text, parse_mode='Markdown')
    
    # প্রুফ ডেটা টেক্সট নাকি স্ক্রিনশট তা চেক করে পাঠানো
    if len(sub['proof_data']) > 30:  # সাধারণত Telegram File ID বড় হয়, তাই এটিকে ফটো হিসেবে ধরা হচ্ছে
        context.bot.send_photo(chat_id=update.effective_chat.id, photo=sub['proof_data'])
    else:
        context.bot.send_message(chat_id=update.effective_chat.id, text=f"📄 Text Proof: `{sub['proof_data']}`", parse_mode='Markdown')
        
    keyboard = [
        [InlineKeyboardButton("✅ Approve", callback_data=f"c_approve_{sub['sub_id']}")],
        [InlineKeyboardButton("❌ Reject", callback_data=f"c_reject_{sub['sub_id']}")]
    ]
    context.bot.send_message(chat_id=update.effective_chat.id, text="আপনি কি এই কাজটি অ্যাপ্রুভ করবেন নাকি রিজেক্ট?", reply_markup=InlineKeyboardMarkup(keyboard))

def creator_approve(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    sub_id = query.data.split('_')[2]
    
    conn = get_db_connection()
    cursor = conn.cursor()
    sub = cursor.execute("SELECT * FROM submissions WHERE sub_id = ?", (sub_id,)).fetchone()
    task = cursor.execute("SELECT * FROM tasks WHERE task_id = ?", (sub['task_id'],)).fetchone()
    
    # স্ট্যাটাস আপডেট ও ব্যালেন্স মেইন একাউন্টে ট্রান্সফার
    cursor.execute("UPDATE submissions SET status = 'approved' WHERE sub_id = ?", (sub_id,))
    cursor.execute("UPDATE users SET pending_balance = pending_balance - ?, balance = balance + ? WHERE user_id = ?", (task['rate'], task['rate'], sub['worker_id']))
    cursor.execute("UPDATE tasks SET slots = slots - 1 WHERE task_id = ?", (sub['task_id'],))
    
    # যদি সব স্লট শেষ হয়ে যায়
    if task['slots'] <= 1:
        cursor.execute("UPDATE tasks SET status = 'completed' WHERE task_id = ?", (sub['task_id'],))
        
    conn.commit()
    conn.close()
    
    query.edit_message_text("✅ সাবমিশনটি সফলভাবে অ্যাপ্রুভ করা হয়েছে এবং কর্মীকে পেমেন্ট দেওয়া হয়েছে।")
    try:
        context.bot.send_message(chat_id=sub['worker_id'], text=f"🎉 অভিনন্দন! আপনার একটি টাস্ক অ্যাপ্রুভ হয়েছে এবং {task['rate']} USDT মেইন ব্যালেন্সে যুক্ত হয়েছে।")
    except Exception:
        pass

def creator_reject_start(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    sub_id = query.data.split('_')[2]
    context.user_data['reject_sub_id'] = sub_id
    
    query.edit_message_text("📝 রিজেক্ট করার একটি স্পষ্ট কারণ (Rejection Reason) লিখুন যা ওয়ার্কার এবং এডমিন দেখতে পাবে:")
    return WAITING_REJECTION_REASON

def creator_reject_save(update: Update, context: CallbackContext):
    reason = update.message.text
    sub_id = context.user_data.get('reject_sub_id')
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    sub = cursor.execute("SELECT * FROM submissions WHERE sub_id = ?", (sub_id,)).fetchone()
    task = cursor.execute("SELECT * FROM tasks WHERE task_id = ?", (sub['task_id'],)).fetchone()
    
    # সাবমিশন সরাসরি Disputed Queue-তে পাঠানো এবং রিজেকশন কারণ সেট করা
    cursor.execute("UPDATE submissions SET status = 'disputed', rejection_reason = ? WHERE sub_id = ?", (reason, sub_id))
    
    conn.commit()
    conn.close()
    
    update.message.reply_text("🛑 সাবমিশনটি রিজেক্ট করে অ্যাডমিন রিভিউ প্যানেলে (Disputed Queue) পাঠানো হয়েছে।")
    
    # ওয়ার্কারকে নোটিফাই করা
    try:
        context.bot.send_message(chat_id=sub['worker_id'], text=f"⚠️ আপনার সাবমিশনটি ক্রিয়েটর রিজেক্ট করেছে।\nকারণ: {reason}\n\nএটি এখন অ্যাডমিন রিভিউতে আছে।")
    except Exception:
        pass
        
    # অ্যাডমিন প্যানেলে অ্যালার্ট পাঠানো
    try:
        keyboard = [[InlineKeyboardButton("⚖️ Open Disputed Queue", callback_data="admin_disputes")]]
        context.bot.send_message(chat_id=ADMIN_ID, text="🚨 একটি নতুন টাস্ক সাবমিশন রিজেক্ট করা হয়েছে এবং বিবাদ (Dispute) তৈরি হয়েছে!", reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception:
        pass
        
    return ConversationHandler.END

# ---------------- Admin Disputed Review & Warning/Refund System ----------------
def admin_show_disputes(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    
    if update.effective_user.id != ADMIN_ID:
        query.edit_message_text("❌ আপনার এই কমান্ড ব্যবহারের অনুমতি নেই।")
        return
        
    conn = get_db_connection()
    disputed = conn.execute("SELECT * FROM submissions WHERE status = 'disputed' LIMIT 1").fetchone()
    conn.close()
    
    if not disputed:
        query.edit_message_text("✅ এই মুহূর্তে কোনো ডিস্পিউট বা অমীমাংসিত ঝামেলা নেই।")
        return
        
    text = (
        f"👑 **Admin Dispute Review Panel**\n\n"
        f"🆔 Submission ID: {disputed['sub_id']}\n"
        f"👷 Worker ID: {disputed['worker_id']}\n"
        f"❌ Creator Reason: {disputed['rejection_reason']}\n\n"
        f"অ্যাডমিন একশন সিলেক্ট করুন:"
    )
    
    keyboard = [
        [InlineKeyboardButton("🏅 Worker is Innocent (Approve & Warn Creator)", callback_data=f"a_verdict_worker_{disputed['sub_id']}")],
        [InlineKeyboardButton("👎 Worker is Fake (Confirm Reject & Keep Pending)", callback_data=f"a_verdict_fake_{disputed['sub_id']}")]
    ]
    query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

def admin_verdict_handler(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    
    action = query.data.split('_')[2]
    sub_id = query.data.split('_')[3]
    
    conn = get_db_connection()
    cursor = conn.cursor()
    sub = cursor.execute("SELECT * FROM submissions WHERE sub_id = ?", (sub_id,)).fetchone()
    task = cursor.execute("SELECT * FROM tasks WHERE task_id = ?", (sub['task_id'],)).fetchone()
    
    if action == "worker":
        # কর্মী নির্দোষ হলে: অ্যাপ্রুভ এবং ক্রিয়েটরকে ওয়ার্নিং দেওয়া
        cursor.execute("UPDATE submissions SET status = 'approved' WHERE sub_id = ?", (sub_id))
        cursor.execute("UPDATE users SET pending_balance = pending_balance - ?, balance = balance + ? WHERE user_id = ?", (task['rate'], task['rate'], sub['worker_id']))
        cursor.execute("UPDATE tasks SET slots = slots - 1 WHERE task_id = ?", (sub['task_id'],))
        cursor.execute("UPDATE users SET warnings = warnings + 1 WHERE user_id = ?", (task['creator_id'],))
        
        conn.commit()
        query.edit_message_text("⚖️ রায় সম্পন্ন: কর্মীকে টাকা রিফান্ড করা হয়েছে এবং ফেক রিজেক্ট করার জন্য ক্রিয়েটরকে ১ টি ওয়ার্নিং দেওয়া হয়েছে।")
        
        try:
            context.bot.send_message(chat_id=sub['worker_id'], text="✅ অ্যাডমিন আপনার ডিস্পিউটটি রিভিউ করেছে। আপনি নির্দোষ প্রমাণিত হয়েছেন এবং আপনার ব্যালেন্স যুক্ত হয়েছে!")
            context.bot.send_message(chat_id=task['creator_id'], text="⚠️ অ্যাডমিন আপনার রিজেকশন বাতিল করেছে। ভুল রিজেক্ট করার অপরাধে আপনাকে ১টি Warning দেওয়া হলো।")
        except Exception:
            pass
            
    elif action == "fake":
        # কর্মী ভুল কাজ বা স্প্যাম করলে: পেন্ডিং ব্যালেন্স কেটে নেওয়া
        cursor.execute("UPDATE submissions SET status = 'rejected' WHERE sub_id = ?", (sub_id))
        cursor.execute("UPDATE users SET pending_balance = pending_balance - ? WHERE user_id = ?", (task['rate'], sub['worker_id']))
        
        conn.commit()
        query.edit_message_text("⚖️ রায় সম্পন্ন: কর্মীর দাবি ভুয়া প্রমাণিত হয়েছে এবং রিজেকশন কনফার্ম করা হয়েছে।")
        
        try:
            context.bot.send_message(chat_id=sub['worker_id'], text="❌ অ্যাডমিন রিভিউ অনুযায়ী আপনার কাজ সঠিক ছিল না। আপনার পেন্ডিং ব্যালেন্স বাতিল করা হয়েছে।")
        except Exception:
            pass
            
    conn.close()

# ---------------- Dummy Task Creation Flow with Broadcast Call ----------------
def admin_approve_task_simulation(task_id, context: CallbackContext):
    """ ডেমো বা সিমুলেশন ফাংশন: যখন কোনো টাস্ক অ্যাপ্রুভ বা সাকসেসফুলি অ্যাড হবে """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE tasks SET status = 'approved' WHERE task_id = ?", (task_id,))
    task = cursor.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
    conn.commit()
    conn.close()
    
    # অটো পাইলট ব্রডকাস্ট কল করা হলো
    broadcast_new_task(context, task['category'], task['rate'], task['slots'])

# ---------------- Main Function ----------------
def main():
    # Render এর জন্য পোর্ট বাইন্ডিং ও হেলথ চেক অন করা
    start_health_check_server()
    
    # আপনার আসল বট টোকেন দিয়ে এখানে রিপ্লেস করুন
    BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        logger.error("Please set the BOT_TOKEN environment variable.")
        sys.exit(1)
        
    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher

    # Handler Configuration
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CallbackQueryHandler(find_job_handler, pattern="^find_job$"))
    dp.add_handler(CallbackQueryHandler(show_tasks_by_category, pattern="^cat_"))
    dp.add_handler(CallbackQueryHandler(admin_show_disputes, pattern="^admin_disputes$"))
    dp.add_handler(CallbackQueryHandler(admin_verdict_handler, pattern="^a_verdict_"))
    dp.add_handler(CallbackQueryHandler(creator_approve, pattern="^c_approve_"))

    # Submission Form Handler
    sub_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(view_task_details, pattern="^view_task_")],
        states={
            WAITING_SUBMISSION_PROOF: [
                CallbackQueryHandler(ask_for_proof, pattern="^start_submit_flow$"),
                MessageHandler(Filters.text | Filters.photo, handle_submission_proof)
            ]
        },
        fallbacks=[]
    )
    
    # Rejection Reason Handler
    reject_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(creator_reject_start, pattern="^c_reject_")],
        states={
            WAITING_REJECTION_REASON: [MessageHandler(Filters.text & ~Filters.command, creator_reject_save)]
        },
        fallbacks=[]
    )
    
    dp.add_handler(sub_conv)
    dp.add_handler(reject_conv)

    # Bot Start (Polling for Render Hosting Deployment)
    updater.start_polling()
    logger.info("Bot started successfully. Waiting for updates...")
    updater.idle()

if __name__ == '__main__':
    main()