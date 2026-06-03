import os
import sqlite3
import logging
import datetime
import http.server
import socketserver
import threading
import asyncio
import json
import time
import traceback
from contextlib import contextmanager
from dotenv import load_dotenv
import telegram
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)

# Load environment variables
load_dotenv()

# Logging configuration
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Core variables configuration
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "8079009018"))
DATABASE = "database.db"

MARKETPLACE_CONFIG = {
    "📺 YouTube": ["Subscribe", "Comment", "Watch Video (1-5 Minutes)", "Watch Video (1-10 Minutes)"],
    "📢 Telegram": ["Join Group", "Join Channel", "Join Bot", "Gleam Offer"],
    "📘 Facebook": ["Profile Follow", "Page Follow", "Join Group", "Watch Video", "New Facebook Account"],
    "📝 Sign Up": ["Simple Signup", "Complex Signup"],
    "📊 Survey": ["Up To 10 Questions"],
    "📧 Gmail Account": ["New Gmail Account", "Old Gmail Account"],
    "📱 Mobile Apps": ["Download Only", "Download + Create Account"],
    "🎵 TikTok": ["Follow", "Like", "Comment", "Share", "Watch Video"]
}

DEFAULT_MIN_RATES = {
    "📺 YouTube": {"Subscribe": 3, "Comment": 2, "Watch Video (1-5 Minutes)": 3, "Watch Video (1-10 Minutes)": 5},
    "📢 Telegram": {"Join Group": 3, "Join Channel": 3, "Join Bot": 3, "Gleam Offer": 4},
    "📘 Facebook": {"Profile Follow": 3, "Page Follow": 3, "Join Group": 3, "Watch Video": 3, "New Facebook Account": 8},
    "📝 Sign Up": {"Simple Signup": 6, "Complex Signup": 10},
    "📊 Survey": {"Up To 10 Questions": 8},
    "📧 Gmail Account": {"New Gmail Account": 8, "Old Gmail Account": 10},
    "📱 Mobile Apps": {"Download Only": 5, "Download + Create Account": 10},
    "🎵 TikTok": {"Follow": 3, "Like": 2, "Comment": 2, "Share": 2, "Watch Video": 3}
}

# =====================================================================
# RENDER HOSTING KEEP-ALIVE SERVER (SELF-RECOVERING)
# =====================================================================
def run_web_server():
    class HealthHandler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header('Content-type', 'text/plain; charset=utf-8')
            self.end_headers()
            self.wfile.write(b"OK - BD94 Enterprise Level Engine Active")
        def log_message(self, format, *args):
            return

    port = int(os.getenv("PORT", "3000"))
    socketserver.TCPServer.allow_reuse_address = True
    
    while True:
        try:
            with socketserver.TCPServer(("0.0.0.0", port), HealthHandler) as server:
                logger.info(f"Keep-alive server bound to port {port}")
                server.serve_forever()
        except Exception as e:
            logger.critical(f"Keep-alive web server crashed: {e}. Restarting in 5s...")
            time.sleep(5)

# =====================================================================
# SQLITE CONCURRENCY & TRANSACTION ENGINE
# =====================================================================
@contextmanager
def db_transaction():
    conn = sqlite3.connect(DATABASE, check_same_thread=False, timeout=60.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    try:
        conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.commit()
    except Exception as e:
        try:
            conn.rollback()
        except sqlite3.Error:
            pass
        logger.error(f"Database transaction failure: {e}", exc_info=True)
        raise e
    finally:
        conn.close()

# =====================================================================
# SYSTEM KEY/VALUE REGISTRY & ROLE-BASED ACCESS CONTROL (RBAC)
# =====================================================================
def get_setting(key: str, default: str) -> str:
    try:
        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()
            cursor.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
            conn.commit()
            row = cursor.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
            if row is not None:
                return row[0]
            cursor.execute("INSERT INTO settings (key, value) VALUES (?, ?)", (key, str(default)))
            conn.commit()
            return str(default)
    except Exception:
        return str(default)

def set_setting(key: str, value: str):
    with db_transaction() as conn:
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))

def get_admin_role(user_id: int) -> str:
    if user_id == ADMIN_ID:
        return 'super_admin'
    try:
        with sqlite3.connect(DATABASE) as conn:
            row = conn.execute("SELECT role FROM admin_roles WHERE user_id = ?", (user_id,)).fetchone()
            if row: return row[0]
    except Exception: pass
    return None

def is_super_admin(user_id: int) -> bool:
    return get_admin_role(user_id) == 'super_admin'

def is_sub_admin(user_id: int) -> bool:
    return get_admin_role(user_id) in ['super_admin', 'sub_admin']

# =====================================================================
# DATABASE MIGRATIONS
# =====================================================================
def init_db():
    with sqlite3.connect(DATABASE) as conn:
        cursor = conn.cursor()
        
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS admin_roles (
            user_id INTEGER PRIMARY KEY,
            role TEXT DEFAULT 'sub_admin',
            added_by INTEGER,
            created_at TEXT
        )""")
        
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY, username TEXT, join_date TEXT, referrals INTEGER DEFAULT 0,
            pending_reward INTEGER DEFAULT 0, earned_reward INTEGER DEFAULT 0, referrer_id INTEGER DEFAULT 0,
            deposit_balance INTEGER DEFAULT 0, earnings_balance INTEGER DEFAULT 0, pending_balance INTEGER DEFAULT 0,
            total_withdrawn INTEGER DEFAULT 0, total_deposited INTEGER DEFAULT 0, status TEXT DEFAULT 'active',
            level INTEGER DEFAULT 1, completed_tasks INTEGER DEFAULT 0, total_earned INTEGER DEFAULT 0,
            last_active TEXT, referral_paid INTEGER DEFAULT 0
        )""")
        
        cursor.execute("PRAGMA table_info(users)")
        u_cols = [c[1] for c in cursor.fetchall()]
        if "referral_paid" not in u_cols:
            cursor.execute("ALTER TABLE users ADD COLUMN referral_paid INTEGER DEFAULT 0")
                
        cursor.execute("CREATE TABLE IF NOT EXISTS withdrawals (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, amount INTEGER, method TEXT, number TEXT, status TEXT DEFAULT 'pending', admin_note TEXT, created_at TEXT)")
        cursor.execute("CREATE TABLE IF NOT EXISTS payment_methods (id INTEGER PRIMARY KEY AUTOINCREMENT, method_name TEXT UNIQUE, account_number TEXT, payment_type TEXT, status TEXT DEFAULT 'enabled')")
        cursor.execute("CREATE TABLE IF NOT EXISTS deposits (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, amount INTEGER, method_name TEXT, transaction_id TEXT UNIQUE, screenshot_file_id TEXT, status TEXT DEFAULT 'pending', admin_note TEXT, created_at TEXT)")
        cursor.execute("CREATE TABLE IF NOT EXISTS tasks (id INTEGER PRIMARY KEY AUTOINCREMENT, creator_id INTEGER, title TEXT, description TEXT, link TEXT, proof_requirements TEXT, reward_amount INTEGER, total_slots INTEGER, filled_slots INTEGER DEFAULT 0, total_budget INTEGER, status TEXT DEFAULT 'pending_approval', created_at TEXT, category TEXT, task_type TEXT, tutorial_image TEXT, time_limit TEXT, expires_at TEXT)")
        cursor.execute("CREATE TABLE IF NOT EXISTS task_submissions (id INTEGER PRIMARY KEY AUTOINCREMENT, task_id INTEGER, worker_id INTEGER, proof_text TEXT, proof_screenshot TEXT, status TEXT DEFAULT 'pending', admin_note TEXT, created_at TEXT, UNIQUE(task_id, worker_id))")
        cursor.execute("CREATE TABLE IF NOT EXISTS support_tickets (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, subject TEXT, status TEXT DEFAULT 'open', created_at TEXT)")
        cursor.execute("CREATE TABLE IF NOT EXISTS support_messages (id INTEGER PRIMARY KEY AUTOINCREMENT, ticket_id INTEGER, sender_id INTEGER, message_text TEXT, attachment_file_id TEXT, created_at TEXT)")
        cursor.execute("CREATE TABLE IF NOT EXISTS wallet_transactions (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, amount INTEGER, balance_type TEXT, action_type TEXT, reference_id TEXT, created_at TEXT)")
        cursor.execute("CREATE TABLE IF NOT EXISTS daily_bonus_claims (user_id INTEGER, claim_date TEXT, PRIMARY KEY(user_id, claim_date))")
        cursor.execute("CREATE TABLE IF NOT EXISTS admin_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, admin_id INTEGER, action_type TEXT, details TEXT, target_user INTEGER DEFAULT 0, created_at TEXT)")
        cursor.execute("CREATE TABLE IF NOT EXISTS user_achievements (user_id INTEGER, achievement_name TEXT, unlocked_at TEXT, PRIMARY KEY(user_id, achievement_name))")
        cursor.execute("CREATE TABLE IF NOT EXISTS scheduled_broadcasts (id INTEGER PRIMARY KEY AUTOINCREMENT, message_type TEXT, text_payload TEXT, file_id TEXT, scheduled_at TEXT, status TEXT DEFAULT 'pending')")
        cursor.execute("CREATE TABLE IF NOT EXISTS user_notifications (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, message TEXT, is_read INTEGER DEFAULT 0, created_at TEXT)")
        cursor.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
        
        # High-Performance Indexes
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_withdrawals_status ON withdrawals(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_deposits_status ON deposits(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_submissions_task ON task_submissions(task_id, worker_id)")
        
        conn.commit()

def log_admin_activity(admin_id, action_type, details, target_user=0):
    try:
        with db_transaction() as conn:
            now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            conn.execute("INSERT INTO admin_logs (admin_id, action_type, details, target_user, created_at) VALUES (?, ?, ?, ?, ?)", (admin_id, action_type, details, target_user, now_str))
    except Exception as e:
        logger.error(f"Error logging admin: {e}")

def evaluate_user_achievements(user_id, conn):
    cursor = conn.cursor()
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    user_data = cursor.execute("SELECT deposit_balance, earnings_balance, referrals, completed_tasks, total_earned, level FROM users WHERE user_id = ?", (user_id,)).fetchone()
    if not user_data: return
    _, _, referrals, completed_tasks, total_earned, current_level = user_data
    achievements = []
    if completed_tasks >= 1: achievements.append("🏆 First Task Completed")
    if total_earned >= 100: achievements.append("🏆 Earned 100 Tk")
    if completed_tasks >= 50: achievements.append("🏆 Completed 50 Tasks")
    if referrals >= 10: achievements.append("🏆 Referred 10 Users")
    for ach in achievements:
        if cursor.execute("SELECT COUNT(*) FROM user_achievements WHERE user_id = ? AND achievement_name = ?", (user_id, ach)).fetchone()[0] == 0:
            cursor.execute("INSERT INTO user_achievements (user_id, achievement_name, unlocked_at) VALUES (?, ?, ?)", (user_id, ach, now_str))
            cursor.execute("INSERT INTO user_notifications (user_id, message, created_at) VALUES (?, ?, ?)", (user_id, f"🎉 Achievement Unlocked: {ach}!", now_str))
            cursor.execute("UPDATE users SET level = ? WHERE user_id = ?", (current_level + 1, user_id))

def check_and_expire_tasks(conn=None):
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    should_close = False
    if conn is None:
        conn = sqlite3.connect(DATABASE, timeout=30.0)
        should_close = True
    try:
        cursor = conn.cursor()
        expired_jobs = cursor.execute("SELECT id, creator_id, reward_amount, total_slots, filled_slots FROM tasks WHERE status = 'active' AND expires_at <= ?", (now_str,)).fetchall()
        for job in expired_jobs:
            t_id, c_id, reward, tot, fill = job
            unused = tot - fill
            cursor.execute("UPDATE tasks SET status = 'expired' WHERE id = ?", (t_id,))
            if unused > 0:
                refund = int(unused * reward * 1.1)
                cursor.execute("UPDATE users SET deposit_balance = deposit_balance + ? WHERE user_id = ?", (refund, c_id))
                cursor.execute("INSERT INTO wallet_transactions (user_id, amount, balance_type, action_type, reference_id, created_at) VALUES (?, ?, 'deposit_balance', 'Task Expired Refund', ?, ?)", (c_id, refund, str(t_id), now_str))
    except Exception as e: pass
    finally:
        if should_close:
            conn.commit()
            conn.close()

def verify_anti_spam_cooldown(user_id, context, limit_seconds=1) -> bool:
    now = datetime.datetime.now()
    last_time = context.user_data.get("_last_msg_timestamp")
    if last_time and (now - last_time).total_seconds() < limit_seconds:
        return False
    context.user_data["_last_msg_timestamp"] = now
    return True

# =====================================================================
# SECURE STATE MANAGEMENT
# =====================================================================
def safe_clear_state(context: ContextTypes.DEFAULT_TYPE):
    keys_to_remove = [
        "withdraw_step", "deposit_step", "job_wizard", "ticket_wizard_step", 
        "admin_context_state", "task_submission_step", "sub_task_id", 
        "worker_submitted_proof_text", "active_ticket_subject", 
        "active_chat_ticket_id", "dep_amount", "dep_txid", "dep_method_name", 
        "dep_method_id", "amount", "method", "number"
    ]
    for k in keys_to_remove:
        if k in context.user_data:
            del context.user_data[k]

# =====================================================================
# GLOBAL ERROR HANDLER
# =====================================================================
async def global_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(msg="Exception while handling an update:", exc_info=context.error)
    try:
        tb_list = traceback.format_exception(None, context.error, context.error.__traceback__)
        tb_string = "".join(tb_list)
        logger.error(f"Traceback:\n{tb_string}")
        if isinstance(update, Update) and update.effective_message:
            await update.effective_message.reply_text("⚠️ An unexpected system error occurred.")
    except Exception as e:
        logger.error(f"Error handler failed: {e}")

# =====================================================================
# NAVIGATION & UI
# =====================================================================
async def show_main_menu(update: Update, msg_text: str):
    keyboard = [
        ["🔍 Find Job", "➕ Create Job"],
        ["💳 Wallet", "👤 Profile"],
        ["👥 Referral", "🎁 Bonus"],
        ["📞 Support"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    if update.callback_query: await update.callback_query.message.reply_text(msg_text, reply_markup=reply_markup)
    elif update.message: await update.message.reply_text(msg_text, reply_markup=reply_markup)

async def show_wallet_menu(update: Update, msg_text: str):
    keyboard = [["📥 Deposit", "📤 Withdraw"], ["📜 Deposit History", "📜 Withdraw History"], ["📊 Transaction History"], ["🔙 Back"]]
    await update.message.reply_text(msg_text, reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))

async def show_tasks_menu(update: Update, msg_text: str):
    keyboard = [["🔍 Find Job", "➕ Create Job"], ["📌 My Posted Tasks", "📌 My Submitted Tasks"], ["🔙 Back"]]
    await update.message.reply_text(msg_text, reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))

def get_force_join_keyboard():
    channel = get_setting("force_join_chat", "https://t.me/bd94earning")
    return InlineKeyboardMarkup([[InlineKeyboardButton("🚀 Join Channel", url=channel)], [InlineKeyboardButton("✅ Continue", callback_data="check_force_join_gate")]])

async def check_membership_gated(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user_id = update.effective_user.id
    if is_super_admin(user_id) or context.user_data.get("is_verified_session"): return True
    channel = get_setting("force_join_chat", "@bd94earning")
    try:
        member = await context.bot.get_chat_member(chat_id=channel, user_id=user_id)
        if member.status in ["member", "administrator", "creator"]:
            context.user_data["is_verified_session"] = True
            return True
    except: pass
    warn = "📢 বট ব্যবহার করতে হলে প্রথমে আমাদের চ্যানেলে যোগ দিন।"
    markup = get_force_join_keyboard()
    if update.callback_query: await update.callback_query.message.reply_text(warn, reply_markup=markup)
    elif update.message: await update.message.reply_text(warn, reply_markup=markup)
    return False

async def is_verified_inline(query, context) -> bool:
    user_id = query.from_user.id
    if is_super_admin(user_id) or context.user_data.get("is_verified_session"): return True
    channel = get_setting("force_join_chat", "@bd94earning")
    try:
        member = await context.bot.get_chat_member(chat_id=channel, user_id=user_id)
        if member.status in ["member", "administrator", "creator"]:
            context.user_data["is_verified_session"] = True
            return True
    except: pass
    await query.message.reply_text(f"📢 বট ব্যবহারের আগে চ্যানেলে যোগ দিন: {channel}")
    return False

async def process_welcome_access(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = "🎉 BD94 Earning Bot এ স্বাগতম\n\n🚀 কাজ শুরু করুন\n📋 Job করে টাকা উপার্জন করুন\n👥 Referral দিয়ে Bonus নিন"
    if update.callback_query: await update.callback_query.message.reply_text(welcome_text)
    else: await update.message.reply_text(welcome_text)
    await show_main_menu(update, "প্রধান মেনু:")

# =====================================================================
# CORE FUNCTIONS
# =====================================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not verify_anti_spam_cooldown(user_id, context): return
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    username = update.effective_user.username or f"user_{user_id}"
    
    referrer_id = 0
    if context.args:
        try:
            val = int(context.args[0])
            if val != user_id: referrer_id = val
        except ValueError: pass
            
    with db_transaction() as conn:
        cursor = conn.cursor()
        if cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,)).fetchone() is None:
            cursor.execute("INSERT INTO users (user_id, username, join_date, referrer_id, last_active) VALUES (?, ?, ?, ?, ?)", (user_id, username, now_str, referrer_id, now_str))
            if referrer_id != 0:
                ref_reward = int(get_setting("ref_reward", "20"))
                cursor.execute("UPDATE users SET referrals = referrals + 1, pending_reward = pending_reward + ? WHERE user_id = ?", (ref_reward, referrer_id))
        else:
            conn.execute("UPDATE users SET last_active = ? WHERE user_id = ?", (now_str, user_id))

    check_and_expire_tasks()
    if not is_super_admin(user_id):
        try:
            member = await context.bot.get_chat_member(chat_id=get_setting("force_join_chat", "@bd94earning"), user_id=user_id)
            if member.status not in ["member", "administrator", "creator"]:
                return await check_membership_gated(update, context)
        except: return await check_membership_gated(update, context)
            
    context.user_data["is_verified_session"] = True
    await process_welcome_access(update, context)

# =====================================================================
# ADMIN DASHBOARD & BROADCAST ENGINE (RBAC INTEGRATED)
# =====================================================================
async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    role = get_admin_role(user_id)
    if not role: return
    safe_clear_state(context)
    
    if role == 'super_admin':
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("👥 Users", callback_data="ad_nav_users"), InlineKeyboardButton("📊 Analytics", callback_data="ad_nav_stats")],
            [InlineKeyboardButton("💰 Finances", callback_data="ad_nav_finances"), InlineKeyboardButton("📋 Tasks", callback_data="ad_nav_tasks")],
            [InlineKeyboardButton("🎫 Support", callback_data="ad_nav_support"), InlineKeyboardButton("📢 Broadcast", callback_data="ad_nav_broadcast")],
            [InlineKeyboardButton("⚙️ Settings", callback_data="ad_nav_settings"), InlineKeyboardButton("👑 Admin Mgmt", callback_data="ad_nav_admins")]
        ])
        msg = "👑 **Super Admin Dashboard**\n\nSelect a system module:"
    else:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("💸 Audit Withdrawals", callback_data="ad_fn_p_w")],
            [InlineKeyboardButton("📋 Audit Tasks", callback_data="ad_nav_tasks")]
        ])
        msg = "🛡️ **Moderator Dashboard**\n\nYou have restricted access. Review tasks and withdrawals below:"

    if update.callback_query: await update.callback_query.message.edit_text(msg, reply_markup=keyboard)
    else: await update.message.reply_text(msg, reply_markup=keyboard)

async def run_broadcast(msg: telegram.Message, context: ContextTypes.DEFAULT_TYPE, admin_id: int):
    with sqlite3.connect(DATABASE) as conn: users = conn.execute("SELECT user_id FROM users WHERE status='active'").fetchall()
    success, fail = 0, 0
    prog = await context.bot.send_message(chat_id=admin_id, text=f"🚀 Broadcast started to {len(users)} users...")
    for (uid,) in users:
        try:
            await msg.copy(chat_id=uid)
            success += 1
        except Exception: fail += 1
        await asyncio.sleep(0.04)
    await prog.edit_text(f"✅ **Broadcast Complete**\nSent: {success} | Failed: {fail}")
    log_admin_activity(admin_id, "System Broadcast", f"Sent to {success} users.")

# =====================================================================
# WORKER ACTION & WIZARDS
# =====================================================================
async def find_jobs_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    check_and_expire_tasks()
    counts = {cat: 0 for cat in MARKETPLACE_CONFIG.keys()}
    with sqlite3.connect(DATABASE) as conn:
        for cat, cnt in conn.execute("SELECT category, COUNT(*) FROM tasks WHERE status = 'active' AND expires_at > ? AND filled_slots < total_slots AND creator_id != ? AND id NOT IN (SELECT task_id FROM task_submissions WHERE worker_id = ?) GROUP BY category", (now_str, user_id, user_id)).fetchall():
            if cat in counts: counts[cat] = cnt
    txt = "🔍 **Find Job Engine**\n\n"
    kbd, row = [], []
    for cat_name, cnt in counts.items():
        txt += f"{cat_name} ({cnt})\n"
        row.append(InlineKeyboardButton(cat_name, callback_data=f"br_cat_{cat_name.split()[-1]}"))
        if len(row) == 2: kbd.append(row); row = []
    if row: kbd.append(row)
    if update.callback_query: await update.callback_query.message.edit_text(txt, reply_markup=InlineKeyboardMarkup(kbd), parse_mode="Markdown")
    else: await update.message.reply_text(txt, reply_markup=InlineKeyboardMarkup(kbd), parse_mode="Markdown")

async def init_job_wizard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    safe_clear_state(context)
    context.user_data["job_wizard"] = {"step": "CATEGORY_SELECT", "proofs_config": []}
    kbd, row = [], []
    for cat in MARKETPLACE_CONFIG.keys():
        row.append(InlineKeyboardButton(cat, callback_data=f"wz_cat_{cat.split()[-1]}"))
        if len(row) == 2: kbd.append(row); row = []
    if row: kbd.append(row)
    await update.message.reply_text("💼 **Job Creation Wizard**\n\n👇 Select a Category:", reply_markup=InlineKeyboardMarkup(kbd))

async def view_task_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    try: task_id = int(update.message.text.strip().replace("/view_task_", ""))
    except: return
    with sqlite3.connect(DATABASE) as conn:
        task = conn.execute("SELECT id, creator_id, title, description, link, proof_requirements, reward_amount, total_slots, filled_slots, status FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not task: return await update.message.reply_text("❌ Task not found.")
        prior_sub = conn.execute("SELECT status FROM task_submissions WHERE task_id = ? AND worker_id = ?", (task_id, user_id)).fetchone()
    status_txt = "❌ Already Submitted" if prior_sub else "✅ Available to Work"
    if task[9] != 'active' or task[8] >= task[7]: status_txt = "🔒 Closed / Expired"
    out = f"📋 **Task ID: #{task[0]}**\n📌 Title: {task[2]}\n💰 Reward: {task[6]} Tk\n👥 Slots: {task[8]}/{task[7]}\n📊 Status: {status_txt}\n\n🔗 Link: {task[4]}\n📝 Instructions:\n{task[3]}\n\n📋 Proof Required:\n"
    try:
        for idx, prf in enumerate(json.loads(task[5])): out += f"   {idx+1}. {prf['name']} ({'Text' if prf['type']=='text' else 'Screenshot'})\n"
    except: out += f"{task[5]}\n"
    if not prior_sub and task[9] == 'active' and task[8] < task[7] and task[1] != user_id:
        out += f"\n👉 Click to Submit: /submit_proof_{task[0]}"
    await update.message.reply_text(out, parse_mode="Markdown")

async def submit_proof_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    try: task_id = int(update.message.text.strip().replace("/submit_proof_", ""))
    except: return
    with sqlite3.connect(DATABASE) as conn:
        task = conn.execute("SELECT id, creator_id, status, total_slots, filled_slots FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not task or task[2] != 'active' or task[4] >= task[3] or task[1] == user_id: return await update.message.reply_text("❌ Task unavailable.")
        if conn.execute("SELECT id FROM task_submissions WHERE task_id = ? AND worker_id = ?", (task_id, user_id)).fetchone(): return await update.message.reply_text("❌ Already submitted.")
    safe_clear_state(context)
    context.user_data["sub_task_id"] = task_id
    context.user_data["task_submission_step"] = "entering_proof_text_fields"
    await update.message.reply_text(f"📝 Task #{task_id}: Send your text proofs now:", reply_markup=ReplyKeyboardMarkup([["❌ Cancel"]], resize_keyboard=True))

# =====================================================================
# MAIN MESSAGES ROUTER (TEXT INTERCEPTOR)
# =====================================================================
async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_membership_gated(update, context): return
    text = update.message.text.strip()
    user_id = update.effective_user.id
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    withdraw_state = context.user_data.get("withdraw_step")
    deposit_state = context.user_data.get("deposit_step")
    wizard_state = context.user_data.get("job_wizard", {}).get("step") if context.user_data.get("job_wizard") else None
    ticket_state = context.user_data.get("ticket_wizard_step")
    admin_state = context.user_data.get("admin_context_state")
    submission_state = context.user_data.get("task_submission_step")

    check_and_expire_tasks()

    if text == "❌ Cancel":
        safe_clear_state(context)
        await show_main_menu(update, "❌ Action cancelled. Returning to main menu.")
        return

    if text == "🔙 Back":
        if admin_state:
            safe_clear_state(context)
            await admin(update, context)
            return
        safe_clear_state(context)
        if withdraw_state or deposit_state:
            with sqlite3.connect(DATABASE) as conn:
                row = conn.execute("SELECT deposit_balance, earnings_balance, pending_balance FROM users WHERE user_id = ?", (user_id,)).fetchone()
            if row: await show_wallet_menu(update, f"💳 **Wallet Dashboard**\n📥 Deposit: {row[0]} Tk\n💰 Earnings: {row[1]} Tk\n⏳ Pending: {row[2]} Tk")
        elif wizard_state or ticket_state or submission_state:
            await show_tasks_menu(update, "📝 Task Dashboard:")
        else:
            await show_main_menu(update, "🔙 Returned to main menu.")
        return

    # --- ADMIN BROADCAST & STATES ---
    if admin_state:
        action = admin_state.get("action")
        if action == "BROADCAST_AWAITING_CONTENT":
            if not is_super_admin(user_id): return
            safe_clear_state(context)
            asyncio.create_task(run_broadcast(update.message, context, user_id))
            return
        
        elif action == "ADMIN_MANUAL_USER_SEARCH_INPUT":
            if not is_super_admin(user_id): return
            try:
                target_uid = int(text)
                with sqlite3.connect(DATABASE) as conn:
                    u = conn.execute("SELECT user_id, referrals, deposit_balance, earnings_balance, pending_balance, status, level FROM users WHERE user_id = ?", (target_uid,)).fetchone()
                if not u: return await update.message.reply_text("❌ User not found.")
                context.user_data["admin_managed_target_uid"] = target_uid
                msg = f"👤 **User [ID: {u[0]}]**\nStatus: {u[5]} | Lvl: {u[6]}\nRef: {u[1]}\nDep: {u[2]} Tk\nEarn: {u[3]} Tk\nPend: {u[4]} Tk"
                kbd = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🚫 Ban", callback_data=f"ad_user_ban_{target_uid}"), InlineKeyboardButton("🟢 Unban", callback_data=f"ad_user_unban_{target_uid}")],
                    [InlineKeyboardButton("✏️ Edit Dep", callback_data=f"ad_bal_edit_deposit_balance"), InlineKeyboardButton("✏️ Edit Earn", callback_data=f"ad_bal_edit_earnings_balance")],
                    [InlineKeyboardButton("🔙 Back", callback_data="ad_nav_users")]
                ])
                await update.message.reply_text(msg, reply_markup=kbd)
            except: await update.message.reply_text("❌ Invalid ID.")
            return

        elif action == "ADMIN_EDIT_BALANCE_VALUE_INPUT":
            if not is_super_admin(user_id): return
            t_uid = context.user_data.get("admin_managed_target_uid")
            b_field = admin_state.get("field")
            try:
                new_val = int(text)
                with db_transaction() as conn:
                    conn.execute(f"UPDATE users SET {b_field} = ? WHERE user_id = ?", (new_val, t_uid))
                await update.message.reply_text(f"✅ {b_field} updated to {new_val} Tk.")
                log_admin_activity(user_id, "Edited Balance", f"Set {b_field} to {new_val}", target_user=t_uid)
                safe_clear_state(context)
            except: await update.message.reply_text("❌ Invalid amount.")
            return

        elif action == "ADMIN_EDIT_SETTING":
            if not is_super_admin(user_id): return
            s_key = admin_state.get("setting_key")
            set_setting(s_key, text)
            log_admin_activity(user_id, "Changed Setting", f"{s_key} = {text}")
            await update.message.reply_text(f"✅ Setting `{s_key}` updated to: {text}")
            safe_clear_state(context)
            return

        elif action == "ADMIN_ADD_ADMIN":
            if not is_super_admin(user_id): return
            try:
                n_id = int(text)
                with db_transaction() as conn:
                    exists = conn.execute("SELECT user_id FROM users WHERE user_id = ?", (n_id,)).fetchone()
                    if not exists: return await update.message.reply_text("❌ User must use the bot first before being an admin.")
                    conn.execute("INSERT OR IGNORE INTO admin_roles (user_id, role, added_by, created_at) VALUES (?, 'sub_admin', ?, ?)", (n_id, user_id, now_str))
                log_admin_activity(user_id, "Added Sub Admin", f"Promoted {n_id}", target_user=n_id)
                await update.message.reply_text(f"✅ Sub Admin {n_id} added successfully.")
                safe_clear_state(context)
            except: await update.message.reply_text("❌ Invalid ID or DB Error.")
            return

        elif action == "ADMIN_REM_ADMIN":
            if not is_super_admin(user_id): return
            try:
                n_id = int(text)
                if n_id == ADMIN_ID: return await update.message.reply_text("❌ Cannot remove Root Admin.")
                with db_transaction() as conn:
                    conn.execute("DELETE FROM admin_roles WHERE user_id = ?", (n_id,))
                log_admin_activity(user_id, "Removed Sub Admin", f"Demoted {n_id}", target_user=n_id)
                await update.message.reply_text(f"✅ Sub Admin {n_id} removed successfully.")
                safe_clear_state(context)
            except: await update.message.reply_text("❌ Invalid ID.")
            return
            
        elif action == "MANDATORY_REJECT_REASON_SUBMISSION":
            if not is_sub_admin(user_id): return
            sub_id = admin_state.get("sub_id")
            try:
                with db_transaction() as conn:
                    row = conn.execute("SELECT s.task_id, s.worker_id, s.status, t.title, t.creator_id FROM task_submissions s JOIN tasks t ON s.task_id = t.id WHERE s.id = ?", (sub_id,)).fetchone()
                    if not row or row[2] != 'pending': return await update.message.reply_text("❌ Already processed.")
                    t_id, w_id, _, t_title, c_id = row
                    conn.execute("UPDATE task_submissions SET status = 'rejected', admin_note = ? WHERE id = ?", (text, sub_id))
                    conn.execute("UPDATE tasks SET filled_slots = CASE WHEN filled_slots > 0 THEN filled_slots - 1 ELSE 0 END WHERE id = ?", (t_id,))
                
                safe_clear_state(context)
                log_admin_activity(user_id, "Rejected Task Sub", f"Sub #{sub_id} rejected. Reason: {text}", target_user=w_id)
                await update.message.reply_text(f"❌ Submission #{sub_id} Rejected.")
                try: await context.bot.send_message(chat_id=w_id, text=f"❌ Your submission for '{t_title}' was rejected.\nReason: {text}")
                except: pass
                try: await context.bot.send_message(chat_id=c_id, text=f"📊 **Task Update:**\nA submission for your task '{t_title}' was rejected by moderators.")
                except: pass
            except: pass
            return

    # --- WITHDRAWALS ---
    if withdraw_state == "step_1" and text in ["150 Tk", "300 Tk", "500 Tk", "1000 Tk"]:
        amount = int(text.split()[0])
        with sqlite3.connect(DATABASE) as conn:
            row = conn.execute("SELECT earnings_balance FROM users WHERE user_id = ?", (user_id,)).fetchone()
            user_bal = row[0] if row else 0
        if user_bal < amount: return await update.message.reply_text(f"❌ Insufficient Earnings! Balance: {user_bal} Tk")
        context.user_data["amount"] = amount
        context.user_data["withdraw_step"] = "step_2"
        await update.message.reply_text(f"💰 Amount: {amount} Tk\n📱 Select Method:", reply_markup=ReplyKeyboardMarkup([["📱 bKash", "📱 Nagad"], ["🔙 Back"]], resize_keyboard=True))
        return

    elif withdraw_state == "step_2" and text in ["📱 bKash", "📱 Nagad"]:
        context.user_data["method"] = text
        context.user_data["withdraw_step"] = "step_3"
        await update.message.reply_text(f"💳 Method: {text}\n📞 Enter Account Number:", reply_markup=ReplyKeyboardMarkup([["❌ Cancel"]], resize_keyboard=True))
        return

    elif withdraw_state == "step_3":
        if len(text) < 11: return await update.message.reply_text("❌ Invalid number! Send correct 11-digit number:")
        context.user_data["number"] = text
        context.user_data["withdraw_step"] = "step_4"
        await update.message.reply_text(f"🔍 **Summary**\nWithdraw: {context.user_data.get('amount')} Tk\nMethod: {context.user_data.get('method')}\nNumber: {text}\n\nClick '✅ Continue'", reply_markup=ReplyKeyboardMarkup([["✅ Continue"], ["🔙 Back", "❌ Cancel"]], resize_keyboard=True))
        return

    elif withdraw_state == "step_4" and text == "✅ Continue":
        amount, method, number = context.user_data.get("amount"), context.user_data.get("method"), context.user_data.get("number")
        try:
            with db_transaction() as conn:
                cursor = conn.cursor()
                row = cursor.execute("SELECT earnings_balance FROM users WHERE user_id = ?", (user_id,)).fetchone()
                user_bal = row[0] if row else 0
                if user_bal < amount: return await update.message.reply_text("❌ Insufficient balance.")
                cursor.execute("UPDATE users SET earnings_balance = earnings_balance - ?, total_withdrawn = total_withdrawn + ? WHERE user_id = ?", (amount, amount, user_id))
                cursor.execute("INSERT INTO withdrawals (user_id, amount, method, number, status, created_at) VALUES (?, ?, ?, ?, 'pending', ?)", (user_id, amount, method, number, now_str))
                req_id = cursor.lastrowid
            safe_clear_state(context)
            await show_main_menu(update, f"✅ Withdraw Request #{req_id} Submitted successfully!")
        except Exception as e: logger.error(f"Withdraw err: {e}")
        return

    # --- DEPOSITS ---
    if deposit_state == "ENTERING_RECHARGE_AMOUNT_RAW":
        try:
            amt = int(text)
            if amt < 50: raise ValueError
        except: return await update.message.reply_text("❌ Minimum 50 Tk required.")
        context.user_data["dep_amount"] = amt
        context.user_data["deposit_step"] = "ENTERING_TRANSACTION_ID_RAW"
        await update.message.reply_text("🔢 Send your Transaction ID (TxID):", reply_markup=ReplyKeyboardMarkup([["❌ Cancel"]], resize_keyboard=True))
        return

    elif deposit_state == "ENTERING_TRANSACTION_ID_RAW":
        if len(text) < 4: return await update.message.reply_text("❌ Invalid TxID.")
        context.user_data["dep_txid"] = text
        context.user_data["deposit_step"] = "ATTACHING_VERIFICATION_SCREENSHOT"
        await update.message.reply_text("📸 Upload Screenshot proof as Image:")
        return

    # --- SUBMISSIONS ---
    if submission_state == "entering_proof_text_fields":
        if len(text) < 4: return await update.message.reply_text("⚠️ Proof too short. Detail it:")
        context.user_data["worker_submitted_proof_text"] = text
        context.user_data["task_submission_step"] = "uploading_photo_attachment_proof"
        await update.message.reply_text("📸 Upload Screenshot proof as Image (or type 'Skip' if only text required):")
        return
        
    elif submission_state == "uploading_photo_attachment_proof" and text.lower() == "skip":
        task_id = context.user_data.get("sub_task_id")
        proof_text = context.user_data.get("worker_submitted_proof_text")
        try:
            with db_transaction() as conn:
                conn.execute("INSERT INTO task_submissions (task_id, worker_id, proof_text, proof_screenshot, status, created_at) VALUES (?, ?, ?, '', 'pending', ?)", (task_id, user_id, proof_text, now_str))
                conn.execute("UPDATE tasks SET filled_slots = filled_slots + 1 WHERE id = ?", (task_id,))
            safe_clear_state(context)
            await show_main_menu(update, "✅ Proof Submitted!")
        except: await update.message.reply_text("❌ Already submitted.")
        return

    # --- MAIN MENU CLICKS ---
    if text == "🔍 Find Job": await find_jobs_start(update, context)
    elif text == "➕ Create Job": await init_job_wizard(update, context)
    elif text == "💳 Wallet":
        with sqlite3.connect(DATABASE) as conn:
            row = conn.execute("SELECT deposit_balance, earnings_balance, pending_balance, total_withdrawn, total_deposited FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if row: await show_wallet_menu(update, f"💳 **Wallet**\n📥 Dep: {row[0]} Tk | 💰 Earn: {row[1]} Tk | ⏳ Pend: {row[2]} Tk\n\n📊 Total Deposited: {row[4]} Tk\n📉 Total Withdrawn: {row[3]} Tk")
    elif text == "📥 Deposit":
        with sqlite3.connect(DATABASE) as conn:
            rows = conn.execute("SELECT id, method_name, account_number, payment_type FROM payment_methods WHERE status='enabled'").fetchall()
        if not rows: return await update.message.reply_text("❌ No gateways available.")
        safe_clear_state(context)
        context.user_data["deposit_step"] = "SELECTING_PAYMENT_GATEWAY_METHOD"
        await update.message.reply_text("📥 Select Gateway:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(f"📱 {r[1]} ({r[3]})", callback_data=f"dp_g_mth_{r[0]}")] for r in rows]))
    elif text == "📤 Withdraw":
        min_w = int(get_setting("min_withdraw", "150"))
        with sqlite3.connect(DATABASE) as conn:
            row = conn.execute("SELECT earnings_balance FROM users WHERE user_id = ?", (user_id,)).fetchone()
            balance = row[0] if row else 0
        if balance < min_w: return await update.message.reply_text(f"❌ Minimum Withdraw is {min_w} Tk.")
        await update.message.reply_text("💸 Amount:", reply_markup=ReplyKeyboardMarkup([["150 Tk", "300 Tk"], ["500 Tk", "1000 Tk"], ["🔙 Back"]], resize_keyboard=True))
        context.user_data["withdraw_step"] = "step_1"
    elif text == "📜 Deposit History":
        with sqlite3.connect(DATABASE) as conn:
            rows = conn.execute("SELECT id, amount, method_name, status FROM deposits WHERE user_id = ? ORDER BY id DESC LIMIT 5", (user_id,)).fetchall()
        if not rows: return await update.message.reply_text("📜 No deposit records.")
        out = "📥 **Deposit History**\n\n"
        for r in rows: out += f"#{r[0]} - {r[1]} Tk via {r[2]} ({'⏳' if r[3]=='pending' else '✅' if r[3]=='approved' else '❌'} {r[3]})\n"
        await update.message.reply_text(out)
    elif text == "📜 Withdraw History":
        with sqlite3.connect(DATABASE) as conn:
            rows = conn.execute("SELECT id, amount, method, status FROM withdrawals WHERE user_id = ? ORDER BY id DESC LIMIT 5", (user_id,)).fetchall()
        if not rows: return await update.message.reply_text("📜 No withdraw records.")
        out = "📤 **Withdraw History**\n\n"
        for r in rows: out += f"#{r[0]} - {r[1]} Tk via {r[2]} ({'⏳' if r[3]=='pending' else '✅' if r[3]=='approved' else '❌'} {r[3]})\n"
        await update.message.reply_text(out)
    elif text == "📊 Transaction History":
        with sqlite3.connect(DATABASE) as conn:
            rows = conn.execute("SELECT amount, balance_type, action_type, created_at FROM wallet_transactions WHERE user_id = ? ORDER BY id DESC LIMIT 10", (user_id,)).fetchall()
        if not rows: return await update.message.reply_text("📊 No transactions.")
        out = "📊 **Recent Ledger:**\n\n"
        for r in rows: out += f"📅 {r[3]}\n💥 {r[2]} | {'+' if r[0]>0 else ''}{r[0]} Tk\n"
        await update.message.reply_text(out)
    elif text == "👤 Profile":
        with sqlite3.connect(DATABASE) as conn:
            uname, j_date, lvl, comp, refs, tot_earn, earn_b, dep_b = conn.execute("SELECT username, join_date, level, completed_tasks, referrals, total_earned, earnings_balance, deposit_balance FROM users WHERE user_id = ?", (user_id,)).fetchone()
        await update.message.reply_text(f"👤 **Profile Dashboard**\n\n🆔 ID: `{user_id}`\n👤 @{uname}\n📅 Join: {j_date}\n\n🏆 Lvl: {lvl}\n✅ Tasks: {comp}\n👥 Refs: {refs}\n\n📈 Lifetime: {tot_earn} Tk\n💰 Earn: {earn_b} Tk\n📥 Dep: {dep_b} Tk", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔔 Notifications", callback_data="user_notifications_history_nav")]]), parse_mode="Markdown")
    
    elif text == "👥 Referral":
        bot_info = await context.bot.get_me()
        ref_link = f"https://t.me/{bot_info.username}?start={user_id}"
        with sqlite3.connect(DATABASE) as conn:
            r = conn.execute("SELECT referrals, pending_reward, earned_reward FROM users WHERE user_id = ?", (user_id,)).fetchone()
        refs, pending, earned = r if r else (0, 0, 0)
        ref_reward = get_setting("ref_reward", "20")
        msg = f"👥 **Referral System Dashboard**\n\n🔗 Your Referral Link:\n`{ref_link}`\n\n📊 Total Referrals: {refs}\n⏳ Pending Reward: {pending} Tk\n💰 Earned Reward: {earned} Tk\n\n⚠️ **Terms:**\n1. Reward ({ref_reward} Tk) is credited only after referred user completes their *First Successful Withdrawal*.\n2. Abuse leads to immediate ban."
        await update.message.reply_text(msg, parse_mode="Markdown")
        
    elif text in ["🎁 Bonus", "🧧 Daily Bonus"]:
        today_date = datetime.datetime.now().strftime("%Y-%m-%d")
        daily_bonus_amt = int(get_setting("daily_bonus", "2"))
        try:
            with db_transaction() as conn:
                cursor = conn.cursor()
                if cursor.execute("SELECT COUNT(*) FROM task_submissions WHERE worker_id = ? AND status = 'approved'", (user_id,)).fetchone()[0] == 0:
                    return await update.message.reply_text("❌ You must complete at least one approved task before claiming the daily bonus.")
                if cursor.execute("SELECT COUNT(*) FROM daily_bonus_claims WHERE user_id = ? AND claim_date = ?", (user_id, today_date)).fetchone()[0] > 0: return await update.message.reply_text("❌ Already claimed today.")
                cursor.execute("INSERT INTO daily_bonus_claims (user_id, claim_date) VALUES (?, ?)", (user_id, today_date))
                cursor.execute("UPDATE users SET earnings_balance = earnings_balance + ?, total_earned = total_earned + ? WHERE user_id = ?", (daily_bonus_amt, daily_bonus_amt, user_id))
                cursor.execute("INSERT INTO wallet_transactions (user_id, amount, balance_type, action_type, reference_id, created_at) VALUES (?, ?, 'earnings_balance', 'Daily Bonus', 'BONUS', ?)", (user_id, daily_bonus_amt, now_str))
            await update.message.reply_text(f"🎁 **Daily Bonus Claimed!**\n💰 +{daily_bonus_amt} Tk added to Earnings.")
        except sqlite3.IntegrityError: await update.message.reply_text("❌ Already claimed.")
        except Exception: await update.message.reply_text("❌ Error processing bonus.")
        
    elif text == "📌 My Posted Tasks":
        with sqlite3.connect(DATABASE) as conn:
            rows = conn.execute("SELECT id, title, reward_amount, filled_slots, total_slots, status FROM tasks WHERE creator_id = ? ORDER BY id DESC", (user_id,)).fetchall()
        if not rows: return await update.message.reply_text("📝 No posted tasks.")
        out = "🛠️ **My Posted Tasks:**\n\n"
        for r in rows: out += f"🆔 Manage: /manage_task_{r[0]}\n📌 {r[1]}\n💰 {r[2]} Tk | Slots: {r[3]}/{r[4]} | {'⏰ Expired' if r[5]=='expired' else r[5]}\n------------------------\n"
        await update.message.reply_text(out)
    elif text == "📌 My Submitted Tasks":
        with sqlite3.connect(DATABASE) as conn:
            rows = conn.execute("SELECT s.id, s.task_id, t.title, t.reward_amount, s.status FROM task_submissions s JOIN tasks t ON s.task_id = t.id WHERE s.worker_id = ? ORDER BY s.id DESC LIMIT 15", (user_id,)).fetchall()
        if not rows: return await update.message.reply_text("📜 No submissions.")
        out = "🗳️ **My Submissions:**\n\n"
        for r in rows: out += f"Proof #{r[0]} | Task #{r[1]}\n💎 {r[2]}\n💰 {r[3]} Tk | {'⏳' if r[4]=='pending' else '✅' if r[4]=='approved' else '❌'} {r[4]}\n------------------------\n"
        await update.message.reply_text(out)
    elif text == "📞 Support":
        safe_clear_state(context)
        context.user_data["ticket_wizard_step"] = "ENTERING_TICKET_SUBJECT"
        await update.message.reply_text("📞 **Live Chat Support**\n\n💬 Send the Subject Title for your ticket:", reply_markup=ReplyKeyboardMarkup([["❌ Cancel"]], resize_keyboard=True))
    
    # --- WIZARD TEXT ROUTERS ---
    elif ticket_state == "ENTERING_TICKET_SUBJECT":
        if len(text) < 4: return await update.message.reply_text("⚠️ Subject too short:")
        context.user_data["active_ticket_subject"] = text
        context.user_data["ticket_wizard_step"] = "ENTERING_TICKET_NET_MESSAGE"
        await update.message.reply_text("💬 Write your full message (you can also upload an image):")
    elif ticket_state == "ENTERING_TICKET_NET_MESSAGE":
        subj = context.user_data.get("active_ticket_subject")
        with db_transaction() as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT INTO support_tickets (user_id, subject, created_at) VALUES (?, ?, ?)", (user_id, subj, now_str))
            t_id = cursor.lastrowid
            cursor.execute("INSERT INTO support_messages (ticket_id, sender_id, message_text, created_at) VALUES (?, ?, ?, ?)", (t_id, user_id, text, now_str))
        safe_clear_state(context)
        await show_tasks_menu(update, f"✅ Ticket Created: #{t_id}")
    elif ticket_state == "LIVE_CHAT_REPLY_MESSAGE_ENTRY":
        t_id = context.user_data.get("active_chat_ticket_id")
        with db_transaction() as conn:
            conn.execute("INSERT INTO support_messages (ticket_id, sender_id, message_text, created_at) VALUES (?, ?, ?, ?)", (t_id, user_id, text, now_str))
            conn.execute("UPDATE support_tickets SET status='open' WHERE id=?", (t_id,))
        safe_clear_state(context)
        await show_tasks_menu(update, "✅ Reply Sent.")
    
    elif wizard_state == "TITLE_ENTRY_PHASE":
        if len(text) < 5: return await update.message.reply_text("⚠️ Title too short:")
        context.user_data["job_wizard"]["title"] = text
        context.user_data["job_wizard"]["step"] = "DESC_ENTRY_PHASE"
        await update.message.reply_text("📄 Step 4: Send Detailed Description:")
    elif wizard_state == "DESC_ENTRY_PHASE":
        context.user_data["job_wizard"]["description"] = text
        context.user_data["job_wizard"]["step"] = "LINK_ENTRY_PHASE"
        await update.message.reply_text("🔗 Step 5: Send Target URL/Link:")
    elif wizard_state == "LINK_ENTRY_PHASE":
        context.user_data["job_wizard"]["link"] = text
        context.user_data["job_wizard"]["step"] = "PROOFS_NAME_ENTRY"
        await update.message.reply_text("📋 Step 6: Name of 1st Proof Required (e.g. Username, Screenshot):")
    elif wizard_state == "PROOFS_NAME_ENTRY":
        context.user_data["job_wizard"]["current_proof_label_name"] = text
        context.user_data["job_wizard"]["step"] = "PROOFS_TYPE_BUTTONS_SELECT"
        await update.message.reply_text(f"📌 Proof: {text}\nSelect Type:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📝 Text", callback_data="wz_p_t_text")], [InlineKeyboardButton("📸 Screenshot", callback_data="wz_p_t_photo")]]))
    elif wizard_state == "WORKERS_LIMIT_QUANTITY_INPUT":
        try:
            qty = int(text)
            if qty < 10: raise ValueError
        except: return await update.message.reply_text("⚠️ Min 10 workers:")
        context.user_data["job_wizard"]["workers"] = qty
        context.user_data["job_wizard"]["step"] = "REWARD_PRICE_VALUE_SETTING"
        cat = context.user_data["job_wizard"].get("category")
        t_type = context.user_data["job_wizard"].get("task_type")
        floor_rate = DEFAULT_MIN_RATES.get(cat, {}).get(t_type, 3)
        context.user_data["job_wizard"]["floor_rate"] = floor_rate
        await update.message.reply_text(f"💰 Step 8: Reward per worker (Min {floor_rate} Tk):")
    elif wizard_state == "REWARD_PRICE_VALUE_SETTING":
        try:
            val = int(text)
            if val < context.user_data["job_wizard"].get("floor_rate", 3): raise ValueError
        except: return await update.message.reply_text("❌ Below minimum floor rate:")
        context.user_data["job_wizard"]["reward_amount"] = val
        context.user_data["job_wizard"]["step"] = "TIME_LIMIT_SELECTION_BUTTONS"
        await update.message.reply_text("📅 Step 9: Time Limit:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("1 Day", callback_data="wz_l_1"), InlineKeyboardButton("3 Days", callback_data="wz_l_3")], [InlineKeyboardButton("7 Days", callback_data="wz_l_7")]]))

# =====================================================================
# CALLBACK MACROS & ADMIN NAVIGATION
# =====================================================================
async def handle_force_join_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        member = await context.bot.get_chat_member(chat_id=get_setting("force_join_chat", "@bd94earning"), user_id=query.from_user.id)
        if member.status in ["member", "administrator", "creator"]:
            context.user_data["is_verified_session"] = True
            await query.message.delete()
            await process_welcome_access(update, context)
        else: await query.answer("❌ Please join first!", show_alert=True)
    except:
        context.user_data["is_verified_session"] = True
        await query.message.delete()
        await process_welcome_access(update, context)

async def handle_admin_nav(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data.replace("ad_nav_", "")
    user_id = query.from_user.id
    
    safe_clear_state(context)
    
    if not is_super_admin(user_id) and data not in ["main", "tasks"]:
        return await query.message.edit_text("❌ Privilege Escalation Blocked: Super Admin only.")

    if data == "users":
        context.user_data["admin_context_state"] = {"action": "ADMIN_MANUAL_USER_SEARCH_INPUT"}
        await query.message.edit_text("👥 **User Management**\n\nSend Telegram User ID:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Dashboard", callback_data="ad_nav_main")]]))
    elif data == "finances":
        kbd = [
            [InlineKeyboardButton("Pending Withdrawals", callback_data="ad_fn_p_w"), InlineKeyboardButton("Pending Deposits", callback_data="ad_fn_p_d")],
            [InlineKeyboardButton("Payment Methods", callback_data="ad_fn_methods")],
            [InlineKeyboardButton("🔙 Back to Dashboard", callback_data="ad_nav_main")]
        ]
        await query.message.edit_text("💰 **Finances Module**", reply_markup=InlineKeyboardMarkup(kbd))
    elif data == "tasks":
        if not is_sub_admin(user_id): return
        with sqlite3.connect(DATABASE) as conn:
            rows = conn.execute("SELECT id, title FROM tasks WHERE status='pending_approval' ORDER BY id").fetchall()
        out = "⏳ **Pending Tasks:**\n\n"
        for r in rows: out += f"ID: #{r[0]} | {r[1]}\nApprove: /approve_task {r[0]}\n\n"
        if not rows: out = "⏳ No pending tasks."
        await query.message.edit_text(out, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="ad_nav_main")]]))
    elif data == "support":
        with sqlite3.connect(DATABASE) as conn:
            rows = conn.execute("SELECT id, user_id, subject FROM support_tickets WHERE status='open' ORDER BY id").fetchall()
        kbd = [[InlineKeyboardButton(f"🎟️ Reply #{r[0]}", callback_data=f"ad_chat_op_{r[0]}")] for r in rows]
        kbd.append([InlineKeyboardButton("🔙 Back", callback_data="ad_nav_main")])
        await query.message.edit_text("📨 **Open Tickets:**\n" if rows else "📨 No open tickets.", reply_markup=InlineKeyboardMarkup(kbd))
    elif data == "broadcast":
        context.user_data["admin_context_state"] = {"action": "BROADCAST_AWAITING_CONTENT"}
        await query.message.edit_text("📢 **Broadcast Module**\n\nSend Text, Photo, Video, or Document now:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="ad_nav_main")]]))
    elif data == "settings":
        kbd = [
            [InlineKeyboardButton("Set Daily Bonus", callback_data="ad_set_dbonus"), InlineKeyboardButton("Set Ref Reward", callback_data="ad_set_ref")],
            [InlineKeyboardButton("Set Min Withdraw", callback_data="ad_set_minw"), InlineKeyboardButton("Set Force Join", callback_data="ad_set_fj")],
            [InlineKeyboardButton("🔙 Back to Dashboard", callback_data="ad_nav_main")]
        ]
        await query.message.edit_text(f"⚙️ **Settings**\nBonus: {get_setting('daily_bonus', '2')}\nRef: {get_setting('ref_reward', '20')}\nMin W/D: {get_setting('min_withdraw', '150')}\nForce: {get_setting('force_join_chat', '@bd94earning')}", reply_markup=InlineKeyboardMarkup(kbd))
    elif data == "admins":
        with sqlite3.connect(DATABASE) as conn:
            rows = conn.execute("SELECT user_id, role, added_by FROM admin_roles").fetchall()
        out = "👑 **Sub Admins:**\n" + "\n".join([f"ID: {r[0]} | By: {r[2]}" for r in rows]) if rows else "👑 **Sub Admins:**\nNo sub admins found."
        kbd = [[InlineKeyboardButton("➕ Add Sub Admin", callback_data="ad_adm_add"), InlineKeyboardButton("➖ Remove Sub Admin", callback_data="ad_adm_rem")], [InlineKeyboardButton("🔙 Back", callback_data="ad_nav_main")]]
        await query.message.edit_text(out, reply_markup=InlineKeyboardMarkup(kbd))
    elif data == "stats":
        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()
            tot_u = cursor.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            tot_d = cursor.execute("SELECT COUNT(*) FROM deposits WHERE status='approved'").fetchone()[0]
            tot_w = cursor.execute("SELECT COUNT(*) FROM withdrawals WHERE status='approved'").fetchone()[0]
        await query.message.edit_text(f"📊 **Analytics**\nUsers: {tot_u}\nDep: {tot_d}\nW/D: {tot_w}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="ad_nav_main")]]))
    elif data == "main":
        await admin(update, context)

async def handle_admin_sub_nav(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    user_id = query.from_user.id
    await query.answer()
    
    if data == "ad_fn_p_w":
        if not is_sub_admin(user_id): return
        with sqlite3.connect(DATABASE) as conn:
            rows = conn.execute("SELECT id, user_id, amount, method, number FROM withdrawals WHERE status='pending'").fetchall()
        out = "📥 **Pending Withdrawals:**\n\n"
        for r in rows: out += f"#{r[0]} | User: {r[1]} | {r[2]} Tk\n{r[3]}: `{r[4]}`\nApprove: /approve {r[0]}\nReject: /reject {r[0]} reason\n\n"
        kbd = [[InlineKeyboardButton("🔙 Back", callback_data="ad_nav_main" if not is_super_admin(user_id) else "ad_nav_finances")]]
        await query.message.edit_text(out if rows else "No pending withdrawals.", reply_markup=InlineKeyboardMarkup(kbd))
    
    elif data == "ad_fn_p_d":
        if not is_super_admin(user_id): return
        with sqlite3.connect(DATABASE) as conn:
            rows = conn.execute("SELECT id, user_id, amount, method_name, transaction_id FROM deposits WHERE status='pending'").fetchall()
        out = "📥 **Pending Deposits:**\n\n"
        for r in rows: out += f"#{r[0]} | User: {r[1]} | {r[2]} Tk\nMethod: {r[3]} | TxID: `{r[4]}`\nApprove: /approve_deposit {r[0]}\nReject: /reject_deposit {r[0]} reason\n\n"
        await query.message.edit_text(out if rows else "No pending deposits.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="ad_nav_finances")]]))
    
    elif data == "ad_set_dbonus":
        context.user_data["admin_context_state"] = {"action": "ADMIN_EDIT_SETTING", "setting_key": "daily_bonus"}
        await query.message.edit_text("Send new Daily Bonus Amount:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="ad_nav_settings")]]))
    elif data == "ad_set_ref":
        context.user_data["admin_context_state"] = {"action": "ADMIN_EDIT_SETTING", "setting_key": "ref_reward"}
        await query.message.edit_text("Send new Referral Reward Amount:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="ad_nav_settings")]]))
    elif data == "ad_set_minw":
        context.user_data["admin_context_state"] = {"action": "ADMIN_EDIT_SETTING", "setting_key": "min_withdraw"}
        await query.message.edit_text("Send new Minimum Withdraw Amount:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="ad_nav_settings")]]))
    elif data == "ad_set_fj":
        context.user_data["admin_context_state"] = {"action": "ADMIN_EDIT_SETTING", "setting_key": "force_join_chat"}
        await query.message.edit_text("Send new Force Join Channel (e.g. @bd94earning or link):", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="ad_nav_settings")]]))
    
    elif data == "ad_adm_add":
        context.user_data["admin_context_state"] = {"action": "ADMIN_ADD_ADMIN"}
        await query.message.edit_text("Send User ID to add as Sub Admin:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="ad_nav_admins")]]))
    elif data == "ad_adm_rem":
        context.user_data["admin_context_state"] = {"action": "ADMIN_REM_ADMIN"}
        await query.message.edit_text("Send User ID to remove Sub Admin privilege:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="ad_nav_admins")]]))

async def admin_fin_chat_sub_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    await query.answer()
    
    if data.startswith("dp_g_mth_"):
        m_id = int(data.replace("dp_g_mth_", "").strip())
        with sqlite3.connect(DATABASE) as conn: gate = conn.execute("SELECT method_name, account_number, payment_type FROM payment_methods WHERE id = ?", (m_id,)).fetchone()
        if not gate: return
        context.user_data["dep_method_id"], context.user_data["dep_method_name"], context.user_data["deposit_step"] = m_id, gate[0], "ENTERING_RECHARGE_AMOUNT_RAW"
        await query.message.reply_text(f"📱 **{gate[0]} ({gate[2]})**\n📞 No: `{(gate[1])}`\n\nSend amount deposited:", parse_mode="Markdown")
        await query.message.delete()
        
    elif data == "supp_ticket_open_wizard":
        safe_clear_state(context)
        context.user_data["ticket_wizard_step"] = "ENTERING_TICKET_SUBJECT"
        await query.message.reply_text("📋 **New Ticket**\nSubject:", reply_markup=ReplyKeyboardMarkup([["❌ Cancel"]], resize_keyboard=True))

    elif data == "supp_ticket_browse_history":
        with sqlite3.connect(DATABASE) as conn: rows = conn.execute("SELECT id, subject, status FROM support_tickets WHERE user_id = ? ORDER BY id DESC", (query.from_user.id,)).fetchall()
        if not rows: return await query.message.reply_text("📜 No history.")
        kbd = [[InlineKeyboardButton(f"💬 Chat #{r[0]}", callback_data=f"supp_chat_open_{r[0]}")] for r in rows]
        await query.message.reply_text("📜 History:", reply_markup=InlineKeyboardMarkup(kbd))

    elif data.startswith("supp_chat_open_") or data.startswith("ad_chat_op_"):
        t_id = int(data.split("_")[-1])
        with sqlite3.connect(DATABASE) as conn:
            tick = conn.execute("SELECT subject, status FROM support_tickets WHERE id = ?", (t_id,)).fetchone()
            msgs = conn.execute("SELECT sender_id, message_text, created_at FROM support_messages WHERE ticket_id = ? ORDER BY id ASC", (t_id,)).fetchall()
        out = f"💬 **Ticket #{t_id}**\n\n"
        for m in msgs: out += f"👤 {'Admin' if is_super_admin(m[0]) else 'User'} [{m[2]}]:\n💬 {m[1]}\n\n"
        pref = "ad_tk_" if "ad_chat" in data else "supp_"
        kbd = []
        if tick[1] == 'open': kbd.extend([[InlineKeyboardButton("📝 Reply", callback_data=f"{pref}reply_tk_{t_id}")], [InlineKeyboardButton("🔒 Close", callback_data=f"{pref}close_tk_{t_id}")]])
        kbd.append([InlineKeyboardButton("🔙 Back", callback_data="ad_nav_support" if "ad_chat" in data else "supp_ticket_browse_history")])
        await query.message.reply_text(out, reply_markup=InlineKeyboardMarkup(kbd))

    elif data.startswith("ad_tk_reply_tk_") or data.startswith("supp_reply_tk_"):
        t_id = int(data.split("_")[-1])
        context.user_data["active_chat_ticket_id"] = t_id
        if "ad_tk" in data: context.user_data["admin_context_state"] = {"action": "ADMIN_TICKET_LIVE_REPLY_TEXT_INPUT", "ticket_id": t_id}
        else: context.user_data["ticket_wizard_step"] = "LIVE_CHAT_REPLY_MESSAGE_ENTRY"
        await query.message.reply_text(f"📝 Reply to #{t_id}:")
        
    elif data.startswith("ad_tk_close_tk_") or data.startswith("supp_close_tk_"):
        t_id = int(data.split("_")[-1])
        with db_transaction() as conn: conn.execute("UPDATE support_tickets SET status='closed' WHERE id=?", (t_id,))
        await query.message.reply_text(f"🔒 Ticket #{t_id} closed.")
        
    elif data.startswith("ad_bal_edit_"):
        b_field = data.replace("ad_bal_edit_", "").strip()
        context.user_data["admin_context_state"] = {"action": "ADMIN_EDIT_BALANCE_VALUE_INPUT", "field": b_field}
        await query.message.reply_text(f"✏️ Send new {b_field}:")

# =====================================================================
# SLASH COMMAND ADMIN ACTIONS (RBAC SECURED)
# =====================================================================
async def approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin_id = update.effective_user.id
    if not is_sub_admin(admin_id) or not context.args: return
    try:
        req_id = int(context.args[0])
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with db_transaction() as conn:
            cursor = conn.cursor()
            row = cursor.execute("SELECT user_id, amount, status, method, number FROM withdrawals WHERE id = ?", (req_id,)).fetchone()
            if not row or row[2] != 'pending': return await update.message.reply_text("❌ Invalid/Processed request.")
            user_id, amount, status, method, number = row
            cursor.execute("UPDATE withdrawals SET status = 'approved' WHERE id = ?", (req_id,))
            cursor.execute("UPDATE users SET total_withdrawn = total_withdrawn + ? WHERE user_id = ?", (amount, user_id))
            
            # Referral logic
            u_info = cursor.execute("SELECT referrer_id, referral_paid FROM users WHERE user_id = ?", (user_id,)).fetchone()
            if u_info and u_info[0] != 0 and u_info[1] == 0:
                ref_id = u_info[0]
                ref_amt = int(get_setting("ref_reward", "20"))
                cursor.execute("UPDATE users SET referral_paid = 1 WHERE user_id = ?", (user_id,))
                cursor.execute("UPDATE users SET earnings_balance = earnings_balance + ?, earned_reward = earned_reward + ?, pending_reward = CASE WHEN pending_reward >= ? THEN pending_reward - ? ELSE 0 END WHERE user_id = ?", (ref_amt, ref_amt, ref_amt, ref_amt, ref_id))
                cursor.execute("INSERT INTO wallet_transactions (user_id, amount, balance_type, action_type, reference_id, created_at) VALUES (?, ?, 'earnings_balance', 'Referral Reward', ?, ?)", (ref_id, ref_amt, str(user_id), now_str))
                try: await context.bot.send_message(chat_id=ref_id, text=f"🎉 **Referral Reward!**\nYour referred user completed their first withdrawal! You received {ref_amt} Tk.")
                except: pass
                
        log_admin_activity(admin_id, "Approved Withdrawal", f"Req #{req_id}", target_user=user_id)
        await update.message.reply_text(f"✅ Withdrawal #{req_id} approved.")
        try: await context.bot.send_message(chat_id=user_id, text=f"✅ Withdrawal Approved!\n#{req_id} | {amount} Tk | {method} | `{number}`", parse_mode="Markdown")
        except: pass
    except Exception as e: logger.error(f"Approval err: {e}")

async def reject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin_id = update.effective_user.id
    if not is_sub_admin(admin_id) or len(context.args) < 2: return
    try:
        req_id, reason = int(context.args[0]), " ".join(context.args[1:])
        with db_transaction() as conn:
            row = conn.execute("SELECT user_id, amount, status FROM withdrawals WHERE id = ?", (req_id,)).fetchone()
            if not row or row[2] != 'pending': return
            conn.execute("UPDATE withdrawals SET status = 'rejected', admin_note = ? WHERE id = ?", (reason, req_id))
            conn.execute("UPDATE users SET earnings_balance = earnings_balance + ? WHERE user_id = ?", (row[1], row[0]))
        log_admin_activity(admin_id, "Rejected Withdrawal", f"Req #{req_id}, Reason: {reason}", target_user=row[0])
        await update.message.reply_text(f"❌ Withdrawal #{req_id} rejected. Refunded.")
        try: await context.bot.send_message(chat_id=row[0], text=f"❌ Withdrawal Rejected!\n#{req_id} | Reason: {reason}\nFunds refunded to Earnings.")
        except: pass
    except: pass

async def approve_deposit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin_id = update.effective_user.id
    if not is_super_admin(admin_id) or not context.args: return
    try:
        dep_id = int(context.args[0])
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with db_transaction() as conn:
            row = conn.execute("SELECT user_id, amount, status FROM deposits WHERE id = ?", (dep_id,)).fetchone()
            if not row or row[2] != 'pending': return
            conn.execute("UPDATE deposits SET status = 'approved' WHERE id = ?", (dep_id,))
            conn.execute("UPDATE users SET deposit_balance = deposit_balance + ?, total_deposited = total_deposited + ? WHERE user_id = ?", (row[1], row[1], row[0]))
            conn.execute("INSERT INTO wallet_transactions (user_id, amount, balance_type, action_type, reference_id, created_at) VALUES (?, ?, 'deposit_balance', 'Deposit Approved', ?, ?)", (row[0], row[1], str(dep_id), now_str))
        log_admin_activity(admin_id, "Approved Deposit", f"Dep #{dep_id}", target_user=row[0])
        await update.message.reply_text(f"✅ Deposit #{dep_id} Approved.")
        try: await context.bot.send_message(chat_id=row[0], text=f"✅ Deposit #{dep_id} Approved! +{row[1]} Tk added to Deposit Balance.")
        except: pass
    except: pass

async def reject_deposit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin_id = update.effective_user.id
    if not is_super_admin(admin_id) or len(context.args) < 2: return
    try:
        dep_id, reason = int(context.args[0]), " ".join(context.args[1:])
        with db_transaction() as conn:
            row = conn.execute("SELECT user_id, status FROM deposits WHERE id = ?", (dep_id,)).fetchone()
            if not row or row[1] != 'pending': return
            conn.execute("UPDATE deposits SET status = 'rejected', admin_note = ? WHERE id = ?", (reason, dep_id))
        log_admin_activity(admin_id, "Rejected Deposit", f"Dep #{dep_id}, Reason: {reason}", target_user=row[0])
        await update.message.reply_text(f"❌ Deposit #{dep_id} Rejected.")
        try: await context.bot.send_message(chat_id=row[0], text=f"❌ Deposit #{dep_id} Rejected.\nReason: {reason}")
        except: pass
    except: pass

async def approve_task_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin_id = update.effective_user.id
    if not is_sub_admin(admin_id) or not context.args: return
    try:
        t_id = int(context.args[0])
        with db_transaction() as conn:
            row = conn.execute("SELECT status, creator_id FROM tasks WHERE id = ?", (t_id,)).fetchone()
            if not row or row[0] != 'pending_approval': return await update.message.reply_text("❌ Not found/Already active.")
            conn.execute("UPDATE tasks SET status = 'active' WHERE id = ?", (t_id,))
        log_admin_activity(admin_id, "Approved Task", f"Task #{t_id} made live.", target_user=row[1])
        await update.message.reply_text(f"✅ Task #{t_id} Approved.")
        try: await context.bot.send_message(chat_id=row[1], text=f"✅ Your Task #{t_id} is now Live!")
        except: pass
    except: pass

async def payment_methods(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_super_admin(update.effective_user.id): return
    with sqlite3.connect(DATABASE) as conn: rows = conn.execute("SELECT id, method_name, account_number, payment_type FROM payment_methods").fetchall()
    out = "📱 **Methods:**\n" + "\n".join([f"#{r[0]} | {r[1]} ({r[3]}) | `{r[2]}`" for r in rows])
    await update.message.reply_text(out if rows else "No methods setup.")

async def add_payment_method(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_super_admin(update.effective_user.id): return
    data = " ".join(context.args).split("|")
    if len(data) < 3: return await update.message.reply_text("/add_payment_method Name|Number|Type")
    with db_transaction() as conn: conn.execute("INSERT INTO payment_methods (method_name, account_number, payment_type) VALUES (?, ?, ?)", (data[0].strip(), data[1].strip(), data[2].strip()))
    await update.message.reply_text("✅ Added.")

# =====================================================================
# MEDIA CAPTURE HANDLERS (UPLOADS & BROADCASTS)
# =====================================================================
async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    admin_state = context.user_data.get("admin_context_state")
    if admin_state and admin_state.get("action") == "BROADCAST_AWAITING_CONTENT":
        if not is_super_admin(user_id): return
        safe_clear_state(context)
        asyncio.create_task(run_broadcast(update.message, context, user_id))
        return

    if not update.message.photo: return
    photo_file_id = update.message.photo[-1].file_id
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    dep_step = context.user_data.get("deposit_step")
    if dep_step == "ATTACHING_VERIFICATION_SCREENSHOT":
        amount, txid, m_name = context.user_data.get("dep_amount"), context.user_data.get("dep_txid"), context.user_data.get("dep_method_name")
        with db_transaction() as conn: conn.execute("INSERT INTO deposits (user_id, amount, method_name, transaction_id, screenshot_file_id, status, created_at) VALUES (?, ?, ?, ?, ?, 'pending', ?)", (user_id, amount, m_name, txid, photo_file_id, now_str))
        safe_clear_state(context)
        await show_main_menu(update, "✅ Deposit Submitted for review.")
        return

    sub_step = context.user_data.get("task_submission_step")
    if sub_step == "uploading_photo_attachment_proof":
        task_id, proof_text = context.user_data.get("sub_task_id"), context.user_data.get("worker_submitted_proof_text")
        try:
            with db_transaction() as conn:
                conn.execute("INSERT INTO task_submissions (task_id, worker_id, proof_text, proof_screenshot, status, created_at) VALUES (?, ?, ?, ?, 'pending', ?)", (task_id, user_id, proof_text, photo_file_id, now_str))
                conn.execute("UPDATE tasks SET filled_slots = filled_slots + 1 WHERE id = ?", (task_id,))
            safe_clear_state(context)
            await show_main_menu(update, "✅ Proof Submitted!")
        except: await update.message.reply_text("❌ Already submitted.")
        return
    
    ticket_step = context.user_data.get("ticket_wizard_step")
    if ticket_step == "ENTERING_TICKET_NET_MESSAGE":
        subj = context.user_data.get("active_ticket_subject")
        with db_transaction() as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT INTO support_tickets (user_id, subject, created_at) VALUES (?, ?, ?)", (user_id, subj, now_str))
            t_id = cursor.lastrowid
            cursor.execute("INSERT INTO support_messages (ticket_id, sender_id, message_text, attachment_file_id, created_at) VALUES (?, ?, ?, ?, ?)", (t_id, user_id, update.message.caption or "Photo", photo_file_id, now_str))
        safe_clear_state(context)
        await show_tasks_menu(update, f"✅ Ticket #{t_id} Created.")
        return
    
    wizard_step = context.user_data.get("job_wizard", {}).get("step")
    if wizard_step == "TUTORIAL_IMAGE_UPLOAD":
        context.user_data["job_wizard"]["tutorial_image"] = photo_file_id
        context.user_data["job_wizard"]["step"] = "WORKERS_LIMIT_QUANTITY_INPUT"
        await update.message.reply_text("👥 Step 7: How many workers? (Min 10):")

async def handle_wizard_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer(); data = query.data; user_id = query.from_user.id
    wizard = context.user_data.get("job_wizard")
    if not wizard and data.startswith("wz_"): return await query.message.reply_text("❌ Session expired.")
    
    if data.startswith("wz_cat_"):
        cat_p = data.split("_")[-1]
        cat = next((k for k in MARKETPLACE_CONFIG.keys() if k.endswith(cat_p)), None)
        wizard["category"], wizard["step"] = cat, "TASK_TYPE_SELECTION_PHASE"
        kbd = [[InlineKeyboardButton(f"🔗 {t}", callback_data=f"wz_typ_{t[:20]}")] for t in MARKETPLACE_CONFIG.get(cat, [])]
        await query.message.edit_text(f"📁 Category: **{cat}**\nSelect sub-type:", reply_markup=InlineKeyboardMarkup(kbd))
    elif data.startswith("wz_typ_"):
        typ_p = data.split("wz_typ_")[-1]
        t_typ = next((t for t in MARKETPLACE_CONFIG.get(wizard["category"], []) if t.startswith(typ_p)), None)
        wizard["task_type"], wizard["step"] = t_typ, "TITLE_ENTRY_PHASE"
        await query.message.delete()
        await context.bot.send_message(user_id, f"📊 Type: **{t_typ}**\n📝 Step 3: Send Title:", reply_markup=ReplyKeyboardMarkup([["❌ Cancel"]], resize_keyboard=True))
    elif data.startswith("wz_p_t_"):
        p_type = data.split("wz_p_t_")[-1]
        wizard["proofs_config"].append({"name": wizard["current_proof_label_name"], "type": p_type})
        kbd = [[InlineKeyboardButton("➡️ Next", callback_data="wz_act_goto_tutorial_image_step")]]
        if len(wizard["proofs_config"]) < 3: kbd.insert(0, [InlineKeyboardButton("➕ Add Another", callback_data="wz_act_add_more_proof_items")])
        await query.message.edit_text(f"✅ Proof #{len(wizard['proofs_config'])} saved.\nAdd more?", reply_markup=InlineKeyboardMarkup(kbd))
    elif data == "wz_act_add_more_proof_items":
        wizard["step"] = "PROOFS_NAME_ENTRY"
        await query.message.delete()
        await context.bot.send_message(user_id, f"📋 Step 6: Name of Proof #{len(wizard['proofs_config']) + 1}:")
    elif data == "wz_act_goto_tutorial_image_step":
        wizard["step"] = "TUTORIAL_IMAGE_UPLOAD"
        await query.message.delete()
        await context.bot.send_message(user_id, "📷 Step 6: Upload Tutorial Image (or click Skip):", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⏭ Skip", callback_data="wz_skp_tutorial_img_upload")]]))
    elif data == "wz_skp_tutorial_img_upload":
        wizard["tutorial_image"], wizard["step"] = "", "WORKERS_LIMIT_QUANTITY_INPUT"
        await query.message.edit_text("👥 Step 7: How many workers? (Min 10):")
    elif data.startswith("wz_l_"):
        days = int(data.split("_")[-1])
        wizard["time_limit"], wizard["step"] = f"{days} Days", "INVOICE_PREVIEW"
        subtotal = wizard["reward_amount"] * wizard["workers"]
        fee = int(subtotal * (int(get_setting("platform_fee", "10")) / 100))
        wizard["total_budget"] = subtotal + fee
        prfs = "".join([f"   {i+1}. {p['name']} ({p['type']})\n" for i, p in enumerate(wizard["proofs_config"])])
        msg = f"📊 **Invoice Preview**\n\nTitle: {wizard['title']}\nWorkers: {wizard['workers']}\nReward: {wizard['reward_amount']} Tk\n\n💵 Budget: {subtotal} Tk\n⚡ Fee: {fee} Tk\n💳 Total: **{wizard['total_budget']} Tk**"
        await query.message.delete()
        kbd = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Submit", callback_data="wz_act_publish")], [InlineKeyboardButton("❌ Cancel", callback_data="wz_act_cancel_wizard_pipeline")]])
        if wizard.get("tutorial_image"):
            try: return await context.bot.send_photo(user_id, photo=wizard["tutorial_image"], caption=msg, reply_markup=kbd)
            except: pass
        await context.bot.send_message(user_id, msg, reply_markup=kbd)
    elif data == "wz_act_publish":
        budget = wizard["total_budget"]
        try:
            with db_transaction() as conn:
                cursor = conn.cursor()
                row = cursor.execute("SELECT deposit_balance FROM users WHERE user_id = ?", (user_id,)).fetchone()
                dep_bal = row[0] if row else 0
                if dep_bal < budget:
                    safe_clear_state(context)
                    return await context.bot.send_message(user_id, f"❌ Insufficient Deposit Balance!\nBudget: {budget} Tk | Balance: {dep_bal} Tk")
                cursor.execute("UPDATE users SET deposit_balance = deposit_balance - ? WHERE user_id = ?", (budget, user_id))
                now = datetime.datetime.now()
                exp = now + datetime.timedelta(days=int(wizard["time_limit"].split()[0]))
                cursor.execute("INSERT INTO tasks (creator_id, title, description, link, proof_requirements, reward_amount, total_slots, total_budget, status, created_at, category, task_type, tutorial_image, time_limit, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending_approval', ?, ?, ?, ?, ?, ?)",
                               (user_id, wizard["title"], wizard["description"], wizard["link"], json.dumps(wizard["proofs_config"]), wizard["reward_amount"], wizard["workers"], budget, now.strftime("%Y-%m-%d %H:%M:%S"), wizard["category"], wizard["task_type"], wizard["tutorial_image"], wizard["time_limit"], exp.strftime("%Y-%m-%d %H:%M:%S")))
                t_id = cursor.lastrowid
                cursor.execute("INSERT INTO wallet_transactions (user_id, amount, balance_type, action_type, reference_id, created_at) VALUES (?, ?, 'deposit_balance', 'Task Pending', ?, ?)", (user_id, -budget, str(t_id), now.strftime("%Y-%m-%d %H:%M:%S")))
            safe_clear_state(context)
            await show_tasks_menu(update, f"🎉 Task Submitted for Approval!\nID: #{t_id}")
        except Exception as e: logger.error(f"Publish Err: {e}")
    elif data == "wz_act_cancel_wizard_pipeline":
        safe_clear_state(context)
        await query.message.delete()
        await show_main_menu(update, "❌ Cancelled.")

async def handle_regex_routing(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.startswith("/view_task_"): await view_task_handler(update, context)
    elif text.startswith("/submit_proof_"): await submit_proof_start(update, context)
    elif text.startswith("/manage_task_"):
        try: t_id = int(text.split("_")[-1])
        except: return
        with sqlite3.connect(DATABASE) as conn:
            task = conn.execute("SELECT id, creator_id, title, reward_amount, filled_slots, total_slots FROM tasks WHERE id = ?", (t_id,)).fetchone()
            if not task or task[1] != update.effective_user.id: return await update.message.reply_text("❌ Access Denied.")
            subs = conn.execute("SELECT id, worker_id FROM task_submissions WHERE task_id = ? AND status = 'pending'", (t_id,)).fetchall()
        out = f"🛠️ **Task #{t_id}**\nTitle: {task[2]}\nSlots: {task[4]}/{task[5]}\n\n"
        if not subs: out += "📥 No pending submissions."
        else:
            out += f"📥 Pending ({len(subs)}):\n"
            for s in subs: out += f"Proof: /view_sub_{s[0]} | Worker: {s[1]}\n"
        await update.message.reply_text(out)
    elif text.startswith("/view_sub_"):
        try: s_id = int(text.split("_")[-1])
        except: return
        with sqlite3.connect(DATABASE) as conn:
            sub = conn.execute("SELECT s.id, s.task_id, s.worker_id, s.proof_text, s.proof_screenshot, s.status, t.creator_id, t.title FROM task_submissions s JOIN tasks t ON s.task_id = t.id WHERE s.id = ?", (s_id,)).fetchone()
        if not sub or sub[6] != update.effective_user.id: return
        out = f"🗳️ **Review Sub #{sub[0]}**\nTask #{sub[1]} - {sub[7]}\nWorker: {sub[2]}\nStatus: {sub[5]}\n\n💬 Text:\n{sub[3]}\n\n"
        if sub[5] == 'pending': out += f"👉 Approve: /approve_sub_{sub[0]}\n👉 Reject: /reject_sub_{sub[0]}"
        if sub[4]:
            try: return await update.message.reply_photo(sub[4], caption=out)
            except: pass
        await update.message.reply_text(out)
    
    # SUB ADMIN: TASK APPROVALS
    elif text.startswith("/approve_sub_"):
        try: s_id = int(text.split("_")[-1])
        except: return
        admin_id = update.effective_user.id
        if not is_sub_admin(admin_id): return
        try:
            now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with db_transaction() as conn:
                cursor = conn.cursor()
                row = cursor.execute("SELECT s.task_id, s.worker_id, s.status, t.creator_id, t.reward_amount, t.title FROM task_submissions s JOIN tasks t ON s.task_id = t.id WHERE s.id = ?", (s_id,)).fetchone()
                if not row or row[2] != 'pending': return
                cursor.execute("UPDATE task_submissions SET status = 'approved' WHERE id = ?", (s_id,))
                cursor.execute("UPDATE users SET earnings_balance = earnings_balance + ?, total_earned = total_earned + ?, completed_tasks = completed_tasks + 1 WHERE user_id = ?", (row[4], row[4], row[1]))
                cursor.execute("INSERT INTO wallet_transactions (user_id, amount, balance_type, action_type, reference_id, created_at) VALUES (?, ?, 'earnings_balance', 'Task Approved', ?, ?)", (row[1], row[4], f"Sub-{s_id}", now_str))
                evaluate_user_achievements(row[1], conn)
                
            log_admin_activity(admin_id, "Approved Task Sub", f"Sub #{s_id} for Task #{row[0]}", target_user=row[1])
            await update.message.reply_text(f"✅ Sub #{s_id} Approved.")
            try: await context.bot.send_message(chat_id=row[1], text=f"🎉 **Task Approved!**\nYour submission for '{row[5]}' was approved.\nReward Added: {row[4]} Tk")
            except: pass
            try: await context.bot.send_message(chat_id=row[3], text=f"📊 **Task Update:**\nA worker successfully completed your task: '{row[5]}'.")
            except: pass
        except: pass
        
    # SUB ADMIN: TASK REJECTIONS
    elif text.startswith("/reject_sub_"):
        try: s_id = int(text.split("_")[-1])
        except: return
        if not is_sub_admin(update.effective_user.id): return
        with sqlite3.connect(DATABASE) as conn:
            row = conn.execute("SELECT s.status FROM task_submissions s WHERE s.id = ?", (s_id,)).fetchone()
            if not row or row[0] != 'pending': return
        safe_clear_state(context)
        context.user_data["admin_context_state"] = {"action": "MANDATORY_REJECT_REASON_SUBMISSION", "sub_id": s_id}
        await update.message.reply_text(f"❌ Rejecting Sub #{s_id}\nSend the reason why:")

# =====================================================================
# BOOTSTRAPPER & ROBUST POLLING
# =====================================================================
def main():
    if not TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN error!")
    
    init_db()
    get_setting("min_withdraw", "150")
    get_setting("platform_fee", "10")
    get_setting("daily_bonus", "2")
    
    # Daemon Keep-Alive for Render
    web_thread = threading.Thread(target=run_web_server, daemon=True)
    web_thread.start()
    
    try: asyncio.get_event_loop()
    except: asyncio.set_event_loop(asyncio.new_event_loop())

    app = Application.builder().token(TOKEN).build()
    
    # Critical System Crash Protector
    app.add_error_handler(global_error_handler)
    
    # Setup Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin))
    app.add_handler(CommandHandler("approve", approve))
    app.add_handler(CommandHandler("reject", reject))
    app.add_handler(CommandHandler("approve_deposit", approve_deposit))
    app.add_handler(CommandHandler("reject_deposit", reject_deposit))
    app.add_handler(CommandHandler("approve_task", approve_task_cmd))
    app.add_handler(CommandHandler("payment_methods", payment_methods))
    app.add_handler(CommandHandler("add_payment_method", add_payment_method))
    
    app.add_handler(CallbackQueryHandler(handle_force_join_callback, pattern=r'^check_force_join_gate$'))
    app.add_handler(CallbackQueryHandler(handle_admin_nav, pattern=r'^ad_nav_'))
    app.add_handler(CallbackQueryHandler(handle_admin_sub_nav, pattern=r'^ad_(fn|set|adm)_'))
    app.add_handler(CallbackQueryHandler(handle_wizard_callbacks, pattern=r'^wz_'))
    app.add_handler(CallbackQueryHandler(admin_fin_chat_sub_callbacks, pattern=r'^(dp_g_mth_|supp_|ad_chat_|ad_tk_|ad_bal_)'))
    
    app.add_handler(MessageHandler(filters.Regex(r'^\/(view_task_|submit_proof_|manage_task_|view_sub_|approve_sub_|reject_sub_)\d+'), handle_regex_routing))
    app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO | filters.Document.ALL, handle_media))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, buttons))

    print("BD94 Enhanced Platform (RBAC + Render Secure) Booted.")
    
    # INFINITE POLLING RECOVERY (Prevents Deployment Drops)
    while True:
        try:
            logger.info("Starting bot polling...")
            app.run_polling(drop_pending_updates=True, close_loop=False)
        except telegram.error.NetworkError as e:
            logger.error(f"Network error in polling: {e}. Sleeping 10s...")
            time.sleep(10)
        except Exception as e:
            logger.critical(f"Fatal polling crash: {e}. Restarting bot core in 15s...")
            time.sleep(15)

if __name__ == "__main__":
    main()