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
        except OSError as e:
            if e.errno == 98: 
                logger.warning(f"Port {port} in use. Forcing recovery in 10s...")
                time.sleep(10)
            else:
                logger.critical(f"Keep-alive web server OS error: {e}. Restarting in 5s...")
                time.sleep(5)
        except Exception as e:
            logger.critical(f"Keep-alive web server crashed: {e}. Restarting in 5s...")
            time.sleep(5)

# =====================================================================
# SQLITE CONCURRENCY & TRANSACTION ENGINE (AUTO-RECONNECT)
# =====================================================================
@contextmanager
def db_transaction(retries=5, delay=0.5):
    """Provides exclusive write access with automatic retry for DB Locks."""
    for attempt in range(retries):
        conn = sqlite3.connect(DATABASE, check_same_thread=False, timeout=60.0)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
            return  
        except sqlite3.OperationalError as e:
            conn.rollback()
            if "locked" in str(e) and attempt < retries - 1:
                logger.warning(f"Database locked. Retrying in {delay}s (Attempt {attempt+1}/{retries})...")
                time.sleep(delay)
                continue
            logger.error(f"Database operational error: {e}", exc_info=True)
            raise e
        except Exception as e:
            conn.rollback()
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
        
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS submission_reviews (
            submission_id INTEGER PRIMARY KEY,
            rejected_by INTEGER,
            rejection_reason TEXT,
            rejection_time TEXT,
            finalized_by TEXT,
            finalized_time TEXT,
            history_logs TEXT
        )""")
        
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS creator_warnings (
            user_id INTEGER PRIMARY KEY,
            warning_count INTEGER DEFAULT 0,
            updated_at TEXT
        )""")

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

def check_and_expire_tasks():
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with db_transaction() as conn:
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
    except Exception as e: 
        logger.error(f"Task expiration error: {e}")

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
        "dep_method_id", "amount", "method", "number", "support_edit_field",
        "task_flow_step"
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
        if isinstance(context.error, (telegram.error.NetworkError, telegram.error.TimedOut)):
            logger.warning("Network timeout ignored. Bot is auto-reconnecting...")
            return

        tb_list = traceback.format_exception(None, context.error, context.error.__traceback__)
        tb_string = "".join(tb_list)
        logger.error(f"Traceback:\n{tb_string}")
        
        if update and isinstance(update, Update) and update.effective_message:
            await update.effective_message.reply_text("⚠️ An internal system error occurred, but the bot is still running safely.")
    except Exception as e:
        logger.error(f"Error handler failed: {e}")

# =====================================================================
# FORCE JOIN SECURE MEMBERSHIP PIPELINE (MULTIPLE REQUIRED CHANNELS)
# =====================================================================
async def check_membership_status(bot, user_id) -> bool:
    if is_super_admin(user_id): return True
    channel_id = get_setting("force_join_chat", "@bd94earning")
    
    if channel_id.startswith("http") or channel_id.startswith("t.me"):
        channel_id = "@" + channel_id.strip("/").split("/")[-1]

    additional_channel = "@bd94earnings"

    try:
        member1 = await bot.get_chat_member(chat_id=channel_id, user_id=user_id)
        if member1.status not in ["member", "administrator", "creator"]:
            return False
            
        member2 = await bot.get_chat_member(chat_id=additional_channel, user_id=user_id)
        if member2.status in ["member", "administrator", "creator"]:
            return True
    except telegram.error.BadRequest as e:
        logger.error(f"Force Join Bad Request: {e}. Check bot administrative permissions.")
    except telegram.error.Forbidden as e:
        logger.error(f"Force Join Forbidden: {e}. Bot blocked.")
    except Exception as e:
        logger.error(f"Force Join Status Failed: {e}")
    return False

def get_force_join_keyboard():
    channel_val = get_setting("force_join_chat", "@bd94earning")
    
    if channel_val.startswith("@"):
        url = f"https://t.me/{channel_val[1:]}"
    elif channel_val.startswith("http"):
        url = channel_val
    else:
        url = get_setting("force_join_link", "https://t.me/bd94earning")

    additional_url = "https://t.me/bd94earnings"

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 Join Channel 1", url=url)],
        [InlineKeyboardButton("📢 Join Channel 2 (BD94 Earnings)", url=additional_url)],
        [InlineKeyboardButton("✅ Verify Join", callback_data="check_force_join_gate")]
    ])

async def complete_user_registration(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int, referrer_id: int = 0):
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    username = update.effective_user.username or f"user_{user_id}"
    
    if referrer_id == 0:
        referrer_id = context.user_data.get("pending_referrer_id", 0)

    is_new_user = False
    ref_reward = int(get_setting("ref_reward", "20"))

    try:
        with db_transaction() as conn:
            cursor = conn.cursor()
            if cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,)).fetchone() is None:
                cursor.execute("INSERT INTO users (user_id, username, join_date, referrer_id, last_active) VALUES (?, ?, ?, ?, ?)", (user_id, username, now_str, referrer_id, now_str))
                is_new_user = True
                if referrer_id != 0:
                    cursor.execute("UPDATE users SET referrals = referrals + 1, pending_reward = pending_reward + ? WHERE user_id = ?", (ref_reward, referrer_id))
    except Exception as e:
        logger.error(f"Database error during user registration: {e}")
        raise e

    if is_new_user and referrer_id != 0:
        notification_text = (
            "🎉 অভিনন্দন!\n\n"
            "আপনার রেফার লিংকের মাধ্যমে ১ জন নতুন সদস্য যোগ দিয়েছে।\n\n"
            f"⏳ পেন্ডিং বোনাস: {ref_reward} টাকা\n\n"
            "রেফার করা সদস্যকে কাজ সম্পন্ন করে প্রথম সফল Withdrawal করতে হবে।\n\n"
            f"Withdrawal সম্পন্ন হলে আপনার Pending Bonus Successful Bonus-এ রূপান্তরিত হবে এবং {ref_reward} টাকা Wallet Balance-এ যোগ হবে।\n\n"
            "📢 আপনার রেফার করা সদস্যকে কাজ করতে ও Withdrawal সম্পন্ন করতে উৎসাহিত করুন।"
        )
        try:
            await context.bot.send_message(chat_id=referrer_id, text=notification_text)
        except telegram.error.Forbidden:
            pass
        except Exception as e:
            logger.error(f"Failed to send referral notification to {referrer_id}: {e}")

    context.user_data["is_verified_session"] = True
    if "pending_referrer_id" in context.user_data:
        del context.user_data["pending_referrer_id"]

    await process_welcome_access(update, context)

async def check_membership_gated(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user_id = update.effective_user.id
    if context.user_data.get("is_verified_session"): return True
    
    is_joined = await check_membership_status(context.bot, user_id)
    if is_joined:
        context.user_data["is_verified_session"] = True
        return True
        
    warn = "📢 বট ব্যবহার করতে হলে প্রথমে আমাদের চ্যানেলে যোগ দিন।"
    markup = get_force_join_keyboard()
    try:
        if update.callback_query: 
            await update.callback_query.message.reply_text(warn, reply_markup=markup)
        elif update.message: 
            await update.message.reply_text(warn, reply_markup=markup)
    except Exception as e:
        logger.error(f"Failed to send Force Join UI: {e}")
    return False

# =====================================================================
# NAVIGATION & UI 
# =====================================================================
async def show_main_menu(update: Update, msg_text: str):
    keyboard = [
        ["📋 Job", "👥 Referral"],
        ["👤 Profile", "💳 Wallet"],
        ["🎁 Bonus", "📞 Support"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    if update.callback_query: await update.callback_query.message.reply_text(msg_text, reply_markup=reply_markup)
    elif update.message: await update.message.reply_text(msg_text, reply_markup=reply_markup)

async def show_wallet_menu(update: Update, msg_text: str):
    keyboard = [["📥 Deposit", "📤 Withdraw"], ["📜 Deposit History", "📜 Withdraw History"], ["📊 Transaction History"], ["🔙 Back"]]
    await update.message.reply_text(msg_text, reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))

async def show_tasks_menu(update: Update, msg_text: str):
    keyboard = [
        ["🔎 Find Job", "➕ Create Job"],
        ["📌 My Posted Tasks", "📌 My Submitted Tasks"],
        ["🔙 Back"]
    ]
    await update.message.reply_text(msg_text, reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))

async def show_support_menu(update: Update, msg_text: str):
    keyboard = [
        ["📞 Live Support"],
        ["📩 Contact Support"],
        ["🔙 Back"]
    ]
    await update.message.reply_text(msg_text, reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))

async def process_welcome_access(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = "🎉 BD94 Earning Bot এ স্বাগতম\n\n🚀 কাজ শুরু করুন\n📋 Job করে টাকা উপার্জন করুন\n👥 Referral দিয়ে Bonus নিন"
    if update.callback_query: await update.callback_query.message.reply_text(welcome_text)
    else: await update.message.reply_text(welcome_text)
    await show_main_menu(update, "প্রধান মেনু:")

# =====================================================================
# CORE FUNCTIONS (SECURE ONBOARDING)
# =====================================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not verify_anti_spam_cooldown(user_id, context): return
    
    referrer_id = 0
    if context.args:
        try:
            val = int(context.args[0])
            if val != user_id: referrer_id = val
        except ValueError: pass
            
    user_exists = False
    try:
        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()
            if cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,)).fetchone():
                user_exists = True
                conn.execute("UPDATE users SET last_active = ? WHERE user_id = ?", (datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), user_id))
    except Exception as e:
        logger.error(f"Start DB Error: {e}")

    check_and_expire_tasks()

    if is_super_admin(user_id):
        if not user_exists:
            await complete_user_registration(update, context, user_id, referrer_id)
        else:
            context.user_data["is_verified_session"] = True
            await process_welcome_access(update, context)
        return

    if not user_exists:
        context.user_data["pending_referrer_id"] = referrer_id

    is_joined = await check_membership_status(context.bot, user_id)
    
    if not is_joined:
        warn = "📢 বট ব্যবহার করতে হলে প্রথমে আমাদের চ্যানেলে যোগ দিন।"
        markup = get_force_join_keyboard()
        await update.message.reply_text(warn, reply_markup=markup)
        return 
        
    if not user_exists:
        await complete_user_registration(update, context, user_id, referrer_id)
    else:
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
            [InlineKeyboardButton("⚙️ Settings", callback_data="ad_nav_settings"), InlineKeyboardButton("👑 Admin Mgmt", callback_data="ad_nav_admins")],
            [InlineKeyboardButton("⚖ Disputed Proofs", callback_data="ad_nav_disputes")],
            [InlineKeyboardButton("⚙️ Support Management", callback_data="ad_nav_supp_mgmt")]
        ])
        msg = "👑 **Super Admin Dashboard**\n\nSelect a system module:"
    else:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("💸 Audit Withdrawals", callback_data="ad_fn_p_w")],
            [InlineKeyboardButton("📋 Audit Tasks", callback_data="ad_nav_tasks")],
            [InlineKeyboardButton("⚖ Disputed Proofs", callback_data="ad_nav_disputes")]
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
        ref_token = cat_name.split()[-1]
        row.append(InlineKeyboardButton(cat_name, callback_data=f"browse_cat_{ref_token}"))
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

# =====================================================================
# REGEX ROUTING SYSTEM
# =====================================================================
async def view_task_by_id_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, task_id: int):
    user_id = update.effective_user.id
    try:
        with sqlite3.connect(DATABASE) as conn:
            task = conn.execute(
                "SELECT id, creator_id, title, description, link, proof_requirements, reward_amount, total_slots, filled_slots, status, category, tutorial_image FROM tasks WHERE id = ?", 
                (task_id,)
            ).fetchone()
            
        if not task:
            if update.callback_query: return await update.callback_query.answer("❌ Task not found.", show_alert=True)
            return await update.message.reply_text("❌ Task not found.")
            
        t_id, creator_id, title, description, link, proof_reqs, reward, total_slots, filled_slots, status, category, tutorial_image = task
        slots_left = max(0, total_slots - filled_slots)
        
        proof1, proof2 = "Not specified", "Not specified"
        try:
            parsed_proofs = json.loads(proof_reqs) if proof_reqs else []
            if len(parsed_proofs) > 0:
                proof1 = f"{parsed_proofs[0].get('name', 'Proof 1')} ({parsed_proofs[0].get('type', 'Text')})"
            if len(parsed_proofs) > 1:
                proof2 = f"{parsed_proofs[1].get('name', 'Proof 2')} ({parsed_proofs[1].get('type', 'Photo')})"
        except Exception:
            if proof_reqs: proof1 = str(proof_reqs)

        out_msg = (
            f"📋 **Task Details**\n\n"
            f"🆔 Task ID: #{t_id}\n"
            f"📌 Title: {title}\n"
            f"📂 Category: {category}\n"
            f"💎 Reward: {reward} Tk\n"
            f"👥 Slots Left: {slots_left}\n\n"
            f"📝 Instructions:\n{description}\n\n"
            f"🔗 Target Link: {link}\n\n"
            f"📸 Required Proof 1: {proof1}\n"
            f"📸 Required Proof 2: {proof2}"
        )
        
        kbd = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Start Task", callback_data=f"br_start_task_{t_id}")],
            [InlineKeyboardButton("🔙 Back", callback_data="browse_back_cats")]
        ])
        
        if update.callback_query:
            if tutorial_image:
                try: return await update.callback_query.message.reply_photo(photo=tutorial_image, caption=out_msg, reply_markup=kbd, parse_mode="Markdown")
                except Exception: pass
            return await update.callback_query.message.reply_text(out_msg, reply_markup=kbd, parse_mode="Markdown")
        else:
            if tutorial_image:
                try: return await update.message.reply_photo(photo=tutorial_image, caption=out_msg, reply_markup=kbd, parse_mode="Markdown")
                except Exception: pass
            return await update.message.reply_text(out_msg, reply_markup=kbd, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error executing view_task for ID {task_id}: {e}")
        if update.message: await update.message.reply_text("❌ Task details unavailable.")

async def handle_regex_routing(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    
    if text.startswith("/viewtask"):
        try:
            task_id = int(text.replace("/viewtask", "").strip())
            return await view_task_by_id_handler(update, context, task_id)
        except ValueError:
            return await update.message.reply_text("❌ Task not found.")
            
    elif text.startswith("/view_task_"):
        try:
            task_id = int(text.replace("/view_task_", "").strip())
            return await view_task_by_id_handler(update, context, task_id)
        except ValueError:
            return await update.message.reply_text("❌ Task not found.")
            
    elif text.startswith("/manage_task_"):
        try: t_id = int(text.split("_")[-1])
        except: return
        with sqlite3.connect(DATABASE) as conn:
            task = conn.execute("SELECT id, creator_id, title, reward_amount, filled_slots, total_slots FROM tasks WHERE id = ?", (t_id,)).fetchone()
            if not task or task[1] != update.effective_user.id: return await update.message.reply_text("❌ Access Denied.")
            subs = conn.execute("SELECT id, worker_id FROM task_submissions WHERE task_id = ? AND status = 'pending'", (t_id,)).fetchall()
        out = f"🛠️ **Task #{t_id}**\nTitle: {task[2]}\nSlots: {task[4]}/{task[5]}\n\n"
        if not subs: out += "📥 No pending worker proofs."
        else:
            out += f"📥 Pending Proofs ({len(subs)}):\n"
            for s in subs: out += f"Proof Card: /view_sub_{s[0]} | Worker ID: {s[1]}\n"
        await update.message.reply_text(out)
        
    elif text.startswith("/view_sub_"):
        try: s_id = int(text.split("_")[-1])
        except: return
        with sqlite3.connect(DATABASE) as conn:
            sub = conn.execute("SELECT s.id, s.task_id, s.worker_id, s.proof_text, s.proof_screenshot, s.status, t.creator_id, t.title FROM task_submissions s JOIN tasks t ON s.task_id = t.id WHERE s.id = ?", (s_id,)).fetchone()
        if not sub or sub[6] != update.effective_user.id: return
        out = f"🗳️ **Review Worker Sub #{sub[0]}**\nTask #{sub[1]} - {sub[7]}\nWorker ID: {sub[2]}\nStatus: {sub[5]}\n\n💬 Written Proof:\n{sub[3]}\n\n"
        
        kbd = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Approve", callback_data=f"own_sub_app_{sub[0]}"),
             InlineKeyboardButton("❌ Reject", callback_data=f"own_sub_rej_{sub[0]}")]
        ])
        if sub[4]:
            try: return await update.message.reply_photo(sub[4], caption=out, reply_markup=kbd)
            except: pass
        await update.message.reply_text(out, reply_markup=kbd)

# =====================================================================
# ADMIN DECISION COMMANDS PIPELINE (APPROVE / REJECT ROUTERS)
# =====================================================================
async def handle_admin_commands(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_sub_admin(user_id): return
    
    text = update.message.text.strip()
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Withdrawal Commands
    if text.startswith("/approve ") or text.startswith("/reject "):
        parts = text.split(maxsplit=2)
        cmd = parts[0]
        if len(parts) < 2: return await update.message.reply_text("⚠️ Format: /approve {id} or /reject {id} {reason}")
        try: req_id = int(parts[1])
        except: return await update.message.reply_text("❌ Invalid Request ID.")
        
        with sqlite3.connect(DATABASE) as conn:
            req = conn.execute("SELECT user_id, amount, status FROM withdrawals WHERE id = ?", (req_id,)).fetchone()
        if not req: return await update.message.reply_text("❌ Withdrawal Request not found.")
        w_uid, amount, current_status = req
        
        if current_status != "pending":
            return await update.message.reply_text(f"❌ Already processed. Current status: {current_status}")
            
        if cmd == "/approve":
            with db_transaction() as conn:
                conn.execute("UPDATE withdrawals SET status = 'approved' WHERE id = ?", (req_id,))
                conn.execute("INSERT INTO wallet_transactions (user_id, amount, balance_type, action_type, reference_id, created_at) VALUES (?, ?, 'earnings_balance', 'Withdraw Approved', ?, ?)", (w_uid, -amount, str(req_id), now_str))
                
                # Check and pay Referral Bonus dynamically if first withdrawal completion criteria hit
                ref_check = conn.execute("SELECT referrer_id, referral_paid FROM users WHERE user_id = ?", (w_uid,)).fetchone()
                if ref_check and ref_check[0] != 0 and ref_check[1] == 0:
                    r_id = ref_check[0]
                    ref_reward = int(get_setting("ref_reward", "20"))
                    conn.execute("UPDATE users SET pending_reward = CASE WHEN pending_reward >= ? THEN pending_reward - ? ELSE 0 END, earned_reward = earned_reward + ?, earnings_balance = earnings_balance + ? WHERE user_id = ?", (ref_reward, ref_reward, ref_reward, ref_reward, r_id))
                    conn.execute("UPDATE users SET referral_paid = 1 WHERE user_id = ?", (w_uid,))
                    conn.execute("INSERT INTO wallet_transactions (user_id, amount, balance_type, action_type, reference_id, created_at) VALUES (?, ?, 'earnings_balance', 'Referral Commission Paid', ?, ?)", (r_id, ref_reward, str(w_uid), now_str))
                    try: await context.bot.send_message(chat_id=r_id, text=f"💰 **Referral Commission Active!**\nYour referral completed their first withdrawal. +{ref_reward} Tk added to your Earnings Balance.")
                    except: pass
            
            await update.message.reply_text(f"✅ Withdrawal #{req_id} Approved.")
            try: await context.bot.send_message(chat_id=w_uid, text=f"✅ Your withdrawal request #{req_id} for {amount} Tk has been approved and dispatched successfully.")
            except: pass
            
        elif cmd == "/reject":
            reason = parts[2] if len(parts) > 2 else "Violated Platform Terms."
            with db_transaction() as conn:
                conn.execute("UPDATE withdrawals SET status = 'rejected', admin_note = ? WHERE id = ?", (reason, req_id))
                conn.execute("UPDATE users SET earnings_balance = earnings_balance + ? WHERE user_id = ?", (amount, w_uid))
                conn.execute("INSERT INTO wallet_transactions (user_id, amount, balance_type, action_type, reference_id, created_at) VALUES (?, ?, 'earnings_balance', 'Withdraw Rejected Refund', ?, ?)", (w_uid, amount, str(req_id), now_str))
            await update.message.reply_text(f"❌ Withdrawal #{req_id} Rejected. Funds rolled back to user.")
            try: await context.bot.send_message(chat_id=w_uid, text=f"❌ Your withdrawal request #{req_id} was rejected.\nReason: {reason}\nFunds returned to your balance.")
            except: pass

    # Task Approval Commands
    elif text.startswith("/approve_task ") or text.startswith("/reject_task "):
        parts = text.split(maxsplit=2)
        cmd = parts[0]
        if len(parts) < 2: return

        try: t_id = int(parts[1])
        except: return
        
        with sqlite3.connect(DATABASE) as conn:
            task = conn.execute("SELECT status, creator_id, title, total_budget FROM tasks WHERE id = ?", (t_id,)).fetchone()
        if not task or task[0] != 'pending_approval': return
        
        if cmd == "/approve_task":
            with db_transaction() as conn:
                conn.execute("UPDATE tasks SET status = 'active' WHERE id = ?", (t_id,))
            await update.message.reply_text(f"✅ Task #{t_id} is now Active.")
            try: await context.bot.send_message(chat_id=task[1], text=f"🎉 Your task #{t_id} is approved and live!")
            except: pass
        elif cmd == "/reject_task":
            reason = parts[2] if len(parts) > 2 else "Does not meet requirements."
            with db_transaction() as conn:
                conn.execute("UPDATE tasks SET status = 'rejected' WHERE id = ?", (t_id,))
                conn.execute("UPDATE users SET deposit_balance = deposit_balance + ? WHERE user_id = ?", (task[3], task[1]))
            await update.message.reply_text(f"❌ Task #{t_id} Rejected. Budget refunded to creator.")
            try: await context.bot.send_message(chat_id=task[1], text=f"❌ Your task #{t_id} was rejected.\nReason: {reason}\nFunds refunded.")
            except: pass

    # Deposit Manual Auditing Commands
    elif text.startswith("/approve_deposit ") or text.startswith("/reject_deposit "):
        if not is_super_admin(user_id): return
        parts = text.split(maxsplit=2)
        cmd = parts[0]
        try: d_id = int(parts[1])
        except: return
        
        with sqlite3.connect(DATABASE) as conn:
            dep = conn.execute("SELECT user_id, amount, status FROM deposits WHERE id = ?", (d_id,)).fetchone()
        if not dep or dep[2] != 'pending': return
        d_uid, amount, _ = dep
        
        if cmd == "/approve_deposit":
            with db_transaction() as conn:
                conn.execute("UPDATE deposits SET status = 'approved' WHERE id = ?", (d_id,))
                conn.execute("UPDATE users SET deposit_balance = deposit_balance + ?, total_deposited = total_deposited + ? WHERE user_id = ?", (amount, amount, d_uid))
                conn.execute("INSERT INTO wallet_transactions (user_id, amount, balance_type, action_type, reference_id, created_at) VALUES (?, ?, 'deposit_balance', 'Deposit Approved', ?, ?)", (d_uid, amount, str(d_id), now_str))
            await update.message.reply_text(f"✅ Deposit #{d_id} Approved.")
            try: await context.bot.send_message(chat_id=d_uid, text=f"✅ Your deposit of {amount} Tk was approved!")
            except: pass
        elif cmd == "/reject_deposit":
            reason = parts[2] if len(parts) > 2 else "Invalid TxID verification match."
            with db_transaction() as conn:
                conn.execute("UPDATE deposits SET status = 'rejected', admin_note = ? WHERE id = ?", (reason, d_id))
            await update.message.reply_text(f"❌ Deposit #{d_id} Rejected.")
            try: await context.bot.send_message(chat_id=d_uid, text=f"❌ Your deposit request was rejected.\nReason: {reason}")
            except: pass

    # Disputed Queue Escalation Arbitration Commands
    elif text.startswith("/dispute_app ") or text.startswith("/dispute_rej "):
        parts = text.split(maxsplit=1)
        cmd = parts[0]
        try: s_id = int(parts[1])
        except: return
        
        with sqlite3.connect(DATABASE) as conn:
            sub = conn.execute("SELECT s.task_id, s.worker_id, s.status, t.reward_amount, t.creator_id FROM task_submissions s JOIN tasks t ON s.task_id = t.id WHERE s.id = ?", (s_id,)).fetchone()
        if not sub or sub[2] != 'rejected': 
            return await update.message.reply_text("❌ Proof submission context is not locked in a rejected dispute state.")
            
        t_id, w_id, _, reward, c_id = sub
        
        if cmd == "/dispute_app":
            with db_transaction() as conn:
                conn.execute("UPDATE task_submissions SET status = 'approved' WHERE id = ?", (s_id,))
                conn.execute("UPDATE users SET earnings_balance = earnings_balance + ?, total_earned = total_earned + ?, completed_tasks = completed_tasks + 1 WHERE user_id = ?", (reward, reward, w_id))
                conn.execute("INSERT INTO wallet_transactions (user_id, amount, balance_type, action_type, reference_id, created_at) VALUES (?, ?, 'earnings_balance', 'Dispute Overruled Approved', ?, ?)", (w_id, reward, f"Disp-{s_id}", now_str))
                conn.execute("UPDATE submission_reviews SET finalized_by = 'Admin Override', finalized_time = ?, history_logs = history_logs || ' -> Admin Overruled Approved' WHERE submission_id = ?", (now_str, s_id))
                evaluate_user_achievements(w_id, conn)
            await update.message.reply_text(f"⚖ Dispute overruled! Submission #{s_id} Approved for Worker. Earnings paid successfully.")
            try: await context.bot.send_message(chat_id=w_id, text=f"🎉 **Dispute Resolved!**\nAdmin approved your submission for Task #{t_id} after manual audit. Reward added.")
            except: pass
            
        elif cmd == "/dispute_rej":
            with db_transaction() as conn:
                conn.execute("UPDATE submission_reviews SET finalized_by = 'Admin Finalized', finalized_time = ?, history_logs = history_logs || ' -> Admin Sustained Rejection' WHERE submission_id = ?", (now_str, s_id))
                
                # Check warning points threshold criteria loops for malicious task creators or scam workers
                conn.execute("INSERT OR IGNORE INTO creator_warnings (user_id, warning_count, updated_at) VALUES (?, 0, ?)", (c_id, now_str))
                conn.execute("UPDATE creator_warnings SET warning_count = warning_count + 1, updated_at = ? WHERE user_id = ?", (now_str, c_id))
                
            await update.message.reply_text(f"⚖ Dispute sustained! Rejection confirmed for Submission #{s_id}. Task creator warning count incremented.")
            try: await context.bot.send_message(chat_id=w_id, text=f"❌ **Dispute Closed.**\nAdmin sustained the rejection for Task #{t_id} after audit. Verification proof was invalid.")
            except: pass

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
    support_edit_field = context.user_data.get("support_edit_field")

    check_and_expire_tasks()

    if text == "❌ Cancel":
        safe_clear_state(context)
        await show_main_menu(update, "❌ Action cancelled. Returning to main menu.")
        return

    if text in ["🔙 Back", "⬅️ Back"]:
        if admin_state:
            safe_clear_state(context)
            await admin(update, context)
            return
        safe_clear_state(context)
        if withdraw_state or deposit_state:
            with sqlite3.connect(DATABASE) as conn:
                row = conn.execute("SELECT deposit_balance, earnings_balance, pending_balance FROM users WHERE user_id = ?", (user_id,)).fetchone()
            if row: await show_wallet_menu(update, f"💳 **Wallet Dashboard**\n📥 Deposit: {row[0]} Tk\n💰 Earnings: {row[1]} Tk\n⏳ Pending: {row[2]} Tk")
        else:
            await show_main_menu(update, "🔙 Returned to main menu.")
        return

    if support_edit_field:
        if not is_super_admin(user_id): return
        set_setting(support_edit_field, text)
        await update.message.reply_text(f"✅ Field `{support_edit_field}` successfully updated!")
        safe_clear_state(context)
        await admin(update, context)
        return

    if admin_state:
        action = admin_state.get("action")
        
        if action == "SUPPORT_TICKET_ADMIN_REPLY_INPUT":
            t_id = admin_state.get("ticket_id")
            try:
                with db_transaction() as conn:
                    row = conn.execute("SELECT user_id FROM support_tickets WHERE id = ?", (t_id,)).fetchone()
                    if row:
                        target_user = row[0]
                        conn.execute("INSERT INTO support_messages (ticket_id, sender_id, message_text, created_at) VALUES (?, ?, ?, ?)", (t_id, user_id, text, now_str))
                        conn.execute("UPDATE support_tickets SET status = 'Answered' WHERE id = ?", (t_id,))
                
                if row:
                    user_push_msg = (
                        f"📩 **Support Reply**\n\n"
                        f"🎫 Ticket ID: #{t_id}\n\n"
                        f"💬 {text}"
                    )
                    try:
                        await context.bot.send_message(chat_id=target_user, text=user_push_msg)
                        await update.message.reply_text(f"✅ Reply delivered successfully to User {target_user} for Ticket #{t_id}.")
                    except Exception:
                        await update.message.reply_text(f"⚠️ Reply saved to DB but delivery failed (User blocked bot).")
                else:
                    await update.message.reply_text("❌ Ticket not found in database.")
                safe_clear_state(context)
            except Exception as e:
                logger.error(f"Admin support reply processing error: {e}")
            return

        elif action == "OWNER_MANDATORY_REJECT_REASON":
            s_id = admin_state.get("sub_id")
            try:
                with db_transaction() as conn:
                    row = conn.execute("SELECT s.task_id, s.worker_id, s.status, t.creator_id, t.title, t.reward_amount FROM task_submissions s JOIN tasks t ON s.task_id = t.id WHERE s.id = ?", (s_id,)).fetchone()
                    if not row or row[2] != 'pending': 
                        safe_clear_state(context)
                        return await update.message.reply_text("❌ Submission finalized already.")
                    
                    t_id, w_id, _, c_id, t_title, reward = row
                    conn.execute("UPDATE task_submissions SET status = 'rejected' WHERE id = ?", (s_id,))
                    conn.execute("UPDATE users SET pending_balance = CASE WHEN pending_balance >= ? THEN pending_balance - ? ELSE 0 END WHERE user_id = ?", (reward, reward, w_id))
                    conn.execute("INSERT OR REPLACE INTO submission_reviews (submission_id, rejected_by, rejection_reason, rejection_time, history_logs) VALUES (?, ?, ?, ?, ?)",
                                 (s_id, user_id, text, now_str, "Submitted -> Rejected"))
                    
                await update.message.reply_text(f"❌ Worker Submission #{s_id} marked as Rejected. Forwarded automatically to Disputed Queue.")
                try:
                    rej_notif = (
                        f"❌ **Task Rejected**\n\n"
                        f"📋 Task: {t_title}\n"
                        f"Reason: {text}\n"
                        f"Pending Balance adjusted successfully."
                    )
                    await context.bot.send_message(chat_id=w_id, text=rej_notif)
                except Exception: pass
                safe_clear_state(context)
            except Exception as e:
                logger.error(f"Owner rejection process failure: {e}")
            return

        elif action == "ADMIN_REJECT_TASK_REASON":
            if not is_sub_admin(user_id): return
            t_id = admin_state.get("task_id")
            try:
                with db_transaction() as conn:
                    row = conn.execute("SELECT status, creator_id, total_budget FROM tasks WHERE id = ?", (t_id,)).fetchone()
                    if not row or row[0] != 'pending_approval': return await update.message.reply_text("❌ Already processed.")
                    conn.execute("UPDATE tasks SET status = 'rejected' WHERE id = ?", (t_id,))
                    conn.execute("UPDATE users SET deposit_balance = deposit_balance + ? WHERE user_id = ?", (row[2], row[1]))
                    conn.execute("INSERT INTO wallet_transactions (user_id, amount, balance_type, action_type, reference_id, created_at) VALUES (?, ?, 'deposit_balance', 'Task Rejected Refund', ?, ?)", (row[1], row[2], str(t_id), now_str))
                
                safe_clear_state(context)
                await update.message.reply_text(f"❌ Task Rejected\nReason: {text}")
                try: await context.bot.send_message(chat_id=row[1], text=f"❌ Your Task #{t_id} was rejected.\nReason: {text}\nFunds refunded to deposit balance.")
                except: pass
            except Exception as e:
                logger.error(f"Task reject error: {e}")
            return
            
        elif action == "BROADCAST_AWAITING_CONTENT":
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

        elif action == "ADMIN_ADD_METHOD_NAME":
            if not is_super_admin(user_id): return
            if len(text) < 2: return await update.message.reply_text("⚠️ Name too short. Try again:")
            admin_state["method_name"] = text
            admin_state["action"] = "ADMIN_ADD_METHOD_NUMBER"
            return await update.message.reply_text(f"✅ Name set to: {text}\n\n📞 Now send the Account Number:")
            
        elif action == "ADMIN_ADD_METHOD_NUMBER":
            if not is_super_admin(user_id): return
            if len(text) < 5: return await update.message.reply_text("⚠️ Number too short. Try again:")
            admin_state["method_number"] = text
            admin_state["action"] = "ADMIN_ADD_METHOD_TYPE"
            return await update.message.reply_text(f"✅ Number set to: {text}\n\n⚙️ Finally, send the Account Type (e.g., Personal, Agent, Merchant):")
            
        elif action == "ADMIN_ADD_METHOD_TYPE":
            if not is_super_admin(user_id): return
            m_name = admin_state.get("method_name")
            m_num = admin_state.get("method_number")
            try:
                with db_transaction() as conn:
                    conn.execute("INSERT INTO payment_methods (method_name, account_number, payment_type, status) VALUES (?, ?, ?, 'enabled')", (m_name, m_num, text))
                log_admin_activity(user_id, "Added Payment Method", f"{m_name} ({text}) - {m_num}")
                await update.message.reply_text(f"🎉 **Success!**\nPayment Method '{m_name}' has been added and is instantly available in the Deposit section.")
                safe_clear_state(context)
            except Exception as e:
                logger.error(f"Failed to add method: {e}")
                await update.message.reply_text("❌ Error saving to database.")
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
                
            try:
                user_info = update.effective_user
                user_full_name = user_info.full_name if user_info.full_name else "Unknown"
                
                with sqlite3.connect(DATABASE) as conn:
                    admin_rows = conn.execute("SELECT user_id FROM admin_roles WHERE role IN ('super_admin', 'sub_admin')").fetchall()
                
                admin_ids_set = {ADMIN_ID}
                for (a_id,) in admin_rows:
                    admin_ids_set.add(int(a_id))
                
                withdraw_notif_text = (
                    f"📤 **New Withdrawal Request**\n\n"
                    f"🆔 Withdraw ID: #{req_id}\n"
                    f"👤 User ID: {user_id}\n"
                    f"👤 Name: {user_full_name}\n"
                    f"💰 Amount: {amount} Tk\n"
                    f"🏦 Method: {method}\n"
                    f"📱 Number: `{number}`\n"
                    f"🕒 Time: {now_str}\n\n"
                    f"✅ Approve: /approve {req_id}\n"
                    f"❌ Reject: /reject {req_id} REASON"
                )
                
                for target_admin in admin_ids_set:
                    try:
                        await context.bot.send_message(chat_id=target_admin, text=withdraw_notif_text, parse_mode="Markdown")
                    except Exception as notif_err:
                        logger.error(f"Failed sending withdraw notification to Admin {target_admin}: {notif_err}")
            except Exception as outer_notif_err:
                logger.error(f"Withdrawal admin alert mapping failed: {outer_notif_err}")

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

    # --- SUBMISSIONS TEXT INPUT LOGIC ---
    if submission_state == "entering_proof_text_fields":
        if len(text) < 4: return await update.message.reply_text("⚠️ Proof too short. Detail it:")
        context.user_data["worker_submitted_proof_text"] = text
        
        context.user_data["task_submission_step"] = "entering_proof_text_fields_two"
        await update.message.reply_text("📝 Proof #2: Enter your remaining text credentials (or type 'Skip'):")
        return

    elif submission_state == "entering_proof_text_fields_two":
        context.user_data["worker_submitted_proof_text"] = context.user_data.get("worker_submitted_proof_text", "") + " | Proof 2: " + text
        context.user_data["task_submission_step"] = "uploading_photo_attachment_proof"
        await update.message.reply_text("📸 Upload Screenshot proof as Image (or type 'Skip' if only text required):")
        return
        
    elif submission_state == "uploading_photo_attachment_proof" and text.lower() == "skip":
        task_id = context.user_data.get("sub_task_id")
        proof_text = context.user_data.get("worker_submitted_proof_text")
        
        try:
            with db_transaction() as conn:
                task_data = conn.execute("SELECT creator_id, title, reward_amount FROM tasks WHERE id = ?", (task_id,)).fetchone()
                if not task_data:
                    return await update.message.reply_text("❌ Task context mismatch error.")
                
                c_id, t_title, reward = task_data
                conn.execute(
                    "INSERT INTO task_submissions (task_id, worker_id, proof_text, proof_screenshot, status, created_at) VALUES (?, ?, ?, '', 'pending', ?)", 
                    (task_id, user_id, proof_text, now_str)
                )
                conn.execute("UPDATE tasks SET filled_slots = filled_slots + 1 WHERE id = ?", (task_id,))
                conn.execute("UPDATE users SET pending_balance = pending_balance + ? WHERE user_id = ?", (reward, user_id))
            
            try:
                w_info = update.effective_user
                w_name = w_info.full_name if w_info.full_name else f"Worker_{user_id}"
                owner_notif = (
                    f"📥 **New Submission Received**\n\n"
                    f"👤 Worker: {w_name}\n"
                    f"🆔 Worker ID: `{user_id}`\n"
                    f"📋 Task: {t_title}\n"
                    f"💰 Reward: {reward} Tk\n\n"
                    f"Review card: /view_sub_{task_id}"
                )
                await context.bot.send_message(chat_id=c_id, text=owner_notif)
            except Exception: pass

            safe_clear_state(context)
            await show_main_menu(update, "✅ Proof Submitted Successfully! Your reward has been added to Pending Balance.")
        except Exception as e:
            logger.error(f"Proof submission text execution drop: {e}")
            await update.message.reply_text("❌ Error or already submitted.")
        return

    # --- MAIN MENU NAVIGATION CLICKS ---
    if text == "📋 Job":
        safe_clear_state(context)
        await show_tasks_menu(update, "📋 **টাস্ক মেনু:**\n\nনিচের অপশন থেকে আপনার পছন্দের কাজটি বেছে নিন:")
        return
    elif text == "🔎 Find Job": await find_jobs_start(update, context)
    elif text == "➕ Create Job": await init_job_wizard(update, context)
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
    elif text == "💳 Wallet":
        with sqlite3.connect(DATABASE) as conn:
            row = conn.execute("SELECT deposit_balance, earnings_balance, pending_balance, total_withdrawn, total_deposited FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if row: await show_wallet_menu(update, f"💳 **Wallet**\n📥 Dep: {row[0]} Tk | 💰 Earn: {row[1]} Tk | ⏳ Pend: {row[2]} Tk\n\n📊 Total Deposited: {row[4]} Tk\n📉 Total Withdrawn: {row[3]} Tk")
    elif text == "📥 Deposit":
        with sqlite3.connect(DATABASE) as conn:
            rows = conn.execute("SELECT id, method_name, account_number, payment_type FROM payment_methods WHERE status='enabled'").fetchall()
        if not rows: 
            user_msg = (
                "⏳ বর্তমানে কোনো Payment Method যুক্ত নেই।\n"
                "Admin-কে Notification পাঠানো হয়েছে।\n"
                "কিছুক্ষণ পর আবার চেষ্টা করুন।"
            )
            await update.message.reply_text(user_msg)
            
            user_info = update.effective_user
            u_name = user_info.full_name if user_info.full_name else f"User_{user_id}"
            
            admin_alert = (
                "🚨 **Payment Method Missing Alert**\n\n"
                "একজন User Deposit করতে চেয়েছে কিন্তু কোনো Payment Method পাওয়া যায়নি।\n"
                "দ্রুত Payment Method Add করুন।\n\n"
                f"👤 **User Name:** {u_name}\n"
                f"🆔 **User ID:** `{user_id}`\n"
                f"🕒 **Time:** {now_str}"
            )
            try:
                await context.bot.send_message(chat_id=ADMIN_ID, text=admin_alert, parse_mode="Markdown")
            except Exception:
                pass
            return
            
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
        try:
            with sqlite3.connect(DATABASE) as conn:
                row = conn.execute("SELECT username, join_date, level, completed_tasks, referrals, total_earned, earnings_balance, deposit_balance FROM users WHERE user_id = ?", (user_id,)).fetchone()
            if row:
                uname, j_date, lvl, comp, refs, tot_earn, earn_b, dep_b = row
                await update.message.reply_text(
                    f"👤 **Profile Dashboard**\n\n🆔 ID: `{user_id}`\n👤 @{uname}\n📅 Join: {j_date}\n\n🏆 Lvl: {lvl}\n✅ Tasks: {comp}\n👥 Refs: {refs}\n\n📈 Lifetime: {tot_earn} Tk\n💰 Earn: {earn_b} Tk\n📥 Dep: {dep_b} Tk", 
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔔 Notifications", callback_data="user_notifications_history_nav")]]), 
                    parse_mode="Markdown"
                )
            else:
                await update.message.reply_text("❌ Profile data not found. Please click /start to initialize your account.")
        except Exception as e:
            logger.error(f"Profile loading error for {user_id}: {e}")
            await update.message.reply_text("⚠️ Failed to load profile due to a system error. Please try again.")
            
    elif text == "👥 Referral":
        bot_info = await context.bot.get_me()
        ref_link = f"https://t.me/{bot_info.username}?start={user_id}"
        ref_reward = int(get_setting("ref_reward", "20"))
        
        with sqlite3.connect(DATABASE) as conn:
            r = conn.execute("SELECT referrals FROM users WHERE user_id = ?", (user_id,)).fetchone()
            total_refs = r[0] if r else 0
            
            s = conn.execute("SELECT COUNT(*) FROM users WHERE referrer_id = ? AND referral_paid = 1", (user_id,)).fetchone()
            successful_refs = s[0] if s else 0

        pending = max(0, (total_refs - successful_refs) * ref_reward)
        earned = successful_refs * ref_reward

        msg = (
            f"👥 **Referral System Dashboard**\n\n"
            f"🔗 Your Referral Link:\n`{ref_link}`\n\n"
            f"📊 Total Referrals: {total_refs}\n"
            f"✅ Successful Referrals: {successful_refs}\n"
            f"⏳ Pending Reward: {pending} Tk\n"
            f"💰 Earned Reward: {earned} Tk\n\n"
            f"⚠️ **Terms:**\n"
            f"1. Reward ({ref_reward} Tk) is credited only after referred user completes their *First Successful Withdrawal*.\n"
            f"2. Abuse leads to immediate ban."
        )
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
        
    elif text == "📞 Support":
        safe_clear_state(context)
        await show_support_menu(update, "📞 **Support Menu**\n\nনিচের যেকোনো একটি অপশন সিলেক্ট করুন:")
        return

    elif text == "📞 Live Support":
        safe_clear_state(context)
        context.user_data["ticket_wizard_step"] = "ENTERING_TICKET_SUBJECT"
        await update.message.reply_text(
            "📞 **Live Support**\n\nআপনি কোন সমস্যার জন্য যোগাযোগ করতে চান?\nসংক্ষেপে আপনার সমস্যার শিরোনাম লিখুন।\n\n"
            "Example:\n- Deposit Problem\n- Withdrawal Problem\n- Task Issue", 
            reply_markup=ReplyKeyboardMarkup([["❌ Cancel"]], resize_keyboard=True)
        )
        return

    elif text == "📩 Contact Support":
        s_text = get_setting("supp_contact_text", "আমাদের সাথে সরাসরি যোগাযোগ করতে নিচের বাটনে ক্লিক করুন।")
        b_name = get_setting("supp_btn_name", "Telegram Admin")
        tg_user = get_setting("supp_tg_user", "bd94admin")
        wa_num = get_setting("supp_wa_num", "8801700000000")
        c_link = get_setting("supp_contact_link", "https://t.me/bd94earning")

        kbd = [
            [InlineKeyboardButton(b_name, url=c_link)],
            [InlineKeyboardButton("💬 Telegram Profile", url=f"https://t.me/{tg_user}")],
            [InlineKeyboardButton("💬 WhatsApp Chat", url=f"https://wa.me/{wa_num}")]
        ]
        await update.message.reply_text(s_text, reply_markup=InlineKeyboardMarkup(kbd))
        return
    
    elif ticket_state == "ENTERING_TICKET_SUBJECT":
        if len(text) < 3: 
            return await update.message.reply_text("⚠️ শিরোনামটি অত্যন্ত সংক্ষিপ্ত। দয়া করে একটু বিস্তারিত লিখুন:")
        context.user_data["active_ticket_subject"] = text
        context.user_data["ticket_wizard_step"] = "ENTERING_TICKET_NET_MESSAGE"
        await update.message.reply_text("📝 এখন আপনার সমস্যাটি বিস্তারিত লিখুন।\n\nপ্রয়োজনে ছবি/স্ক্রিনশটও পাঠাতে পারবেন Sob-kichu.")
        return

    elif ticket_state == "ENTERING_TICKET_NET_MESSAGE":
        subj = context.user_data.get("active_ticket_subject")
        try:
            with db_transaction() as conn:
                cursor = conn.cursor()
                cursor.execute("INSERT INTO support_tickets (user_id, subject, created_at) VALUES (?, ?, ?)", (user_id, subj, now_str))
                t_id = cursor.lastrowid
                cursor.execute("INSERT INTO support_messages (ticket_id, sender_id, message_text, created_at) VALUES (?, ?, ?, ?)", (t_id, user_id, text, now_str))
            
            await update.message.reply_text(
                f"✅ আপনার সাপোর্ট টিকিট সফলভাবে জমা হয়েছে।\n\n🎫 Ticket ID: #{t_id}\n\nআমাদের টিম যত দ্রুত সম্ভব আপনার সাথে যোগাযোগ করবে।",
                reply_markup=ReplyKeyboardMarkup([["🔙 Back"]], resize_keyboard=True)
            )
            
            user_info = update.effective_user
            username_str = f"@{user_info.username}" if user_info.username else "No Username"
            admin_msg = (
                f"📞 **New Support Ticket**\n\n"
                f"🎫 Ticket ID: `#{t_id}`\n"
                f"👤 User ID: `{user_id}`\n"
                f"📛 Name: {user_info.full_name}\n"
                f"🔗 Username: {username_str}\n\n"
                f"📌 Subject:\n{subj}\n\n"
                f"📝 Message:\n{text}"
            )
            admin_kbd = InlineKeyboardMarkup([[InlineKeyboardButton("💬 Reply", callback_data=f"ad_supp_reply_{t_id}")]])
            try: await context.bot.send_message(chat_id=ADMIN_ID, text=admin_msg, parse_mode="Markdown", reply_markup=admin_kbd)
            except: pass
            safe_clear_state(context)
        except Exception as e:
            logger.error(f"Support text submission err: {e}")
        return

    elif wizard_state == "TITLE_ENTRY_PHASE":
        if len(text) < 5: return await update.message.reply_text("⚠️ Title too short:")
        context.user_data["job_wizard"]["title"] = text
        context.user_data["job_wizard"]["step"] = "DESC_ENTRY_PHASE"
        await update.message.reply_text("📄 Send Detailed Description:")
    elif wizard_state == "DESC_ENTRY_PHASE":
        context.user_data["job_wizard"]["description"] = text
        context.user_data["job_wizard"]["step"] = "LINK_ENTRY_PHASE"
        await update.message.reply_text("🔗 Send Target URL/Link:")
    elif wizard_state == "LINK_ENTRY_PHASE":
        context.user_data["job_wizard"]["link"] = text
        context.user_data["job_wizard"]["step"] = "PROOFS_NAME_ENTRY"
        await update.message.reply_text("📋 Name of 1st Proof Required (e.g. Username, Screenshot):")
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
        await update.message.reply_text(f"💰 Reward per worker (Min {floor_rate} Tk):")
    elif wizard_state == "REWARD_PRICE_VALUE_SETTING":
        try:
            val = int(text)
            if val < context.user_data["job_wizard"].get("floor_rate", 3): raise ValueError
        except: return await update.message.reply_text("❌ Below minimum floor rate:")
        context.user_data["job_wizard"]["reward_amount"] = val
        context.user_data["job_wizard"]["step"] = "TIME_LIMIT_SELECTION_BUTTONS"
        await update.message.reply_text("📅 Time Limit:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("1 Day", callback_data="wz_l_1"), InlineKeyboardButton("3 Days", callback_data="wz_l_3")], [InlineKeyboardButton("7 Days", callback_data="wz_l_7")]]))

# =====================================================================
# MEDIA INGESTION & DOCUMENT PROOF HANDLING (ANTI-DROP PIPELINE)
# =====================================================================
async def handle_incoming_media_proofs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_membership_gated(update, context): return
    user_id = update.effective_user.id
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    deposit_state = context.user_data.get("deposit_step")
    submission_state = context.user_data.get("task_submission_step")
    admin_state = context.user_data.get("admin_context_state")
    wizard_state = context.user_data.get("job_wizard", {}).get("step") if context.user_data.get("job_wizard") else None

    # Resolve photo file object natively
    if update.message.photo: file_id = update.message.photo[-1].file_id
    elif update.message.document and update.message.document.mime_type.startswith("image/"): file_id = update.message.document.file_id
    else: return

    # Admin Module Broadcast Content Capture Channel
    if admin_state and admin_state.get("action") == "BROADCAST_AWAITING_CONTENT":
        if not is_super_admin(user_id): return
        safe_clear_state(context)
        asyncio.create_task(run_broadcast(update.message, context, user_id))
        return

    # Job Creation Tutorial Image Pipeline Catch
    if wizard_state == "TUTORIAL_IMAGE_UPLOAD":
        context.user_data["job_wizard"]["tutorial_image"] = file_id
        context.user_data["job_wizard"]["step"] = "WORKERS_LIMIT_QUANTITY_INPUT"
        return await update.message.reply_text("📸 Tutorial Image attached successfully!\n\n👥 How many workers are required? (Min 10):")

    # Financial Deposit Module Proof Capture
    if deposit_state == "ATTACHING_VERIFICATION_SCREENSHOT":
        amt = context.user_data.get("dep_amount")
        txid = context.user_data.get("dep_txid")
        m_name = context.user_data.get("dep_method_name")
        
        try:
            with db_transaction() as conn:
                cursor = conn.cursor()
                cursor.execute("INSERT INTO deposits (user_id, amount, method_name, transaction_id, screenshot_file_id, status, created_at) VALUES (?, ?, ?, ?, ?, 'pending', ?)", (user_id, amt, m_name, txid, file_id, now_str))
                d_id = cursor.lastrowid
                
            safe_clear_state(context)
            await show_main_menu(update, f"✅ Deposit Request #{d_id} submitted successfully! Awaiting verification.")
            
            # Send Notification Alert To Global Admin Interface Natively
            user_info = update.effective_user
            user_full_name = user_info.full_name if user_info.full_name else "Unknown"
            
            admin_alert_msg = (
                f"📥 **New Deposit Log Awaiting Audit**\n\n"
                f"🆔 Deposit ID: #{d_id}\n"
                f"👤 User: {user_full_name} (ID: {user_id})\n"
                f"💰 Amount: {amt} Tk\n"
                f"🏦 Method: {m_name}\n"
                f"🔢 TxID: `{txid}`\n"
                f"🕒 Time: {now_str}\n\n"
                f"👉 Approve: `/approve_deposit {d_id}`\n"
                f"👉 Reject: `/reject_deposit {d_id} REASON`"
            )
            try: await context.bot.send_photo(chat_id=ADMIN_ID, photo=file_id, caption=admin_alert_msg, parse_mode="Markdown")
            except: pass
        except sqlite3.IntegrityError:
            await update.message.reply_text("❌ This Transaction ID (TxID) has already been submitted or utilized.")
        except Exception as e:
            logger.error(f"Deposit media flow error: {e}")
        return

    # Task Submission Final Image Proof Capture Pipeline channel Router
    if submission_state == "uploading_photo_attachment_proof":
        task_id = context.user_data.get("sub_task_id")
        proof_text = context.user_data.get("worker_submitted_proof_text", "")
        
        try:
            with db_transaction() as conn:
                cursor = conn.cursor()
                task_data = cursor.execute("SELECT creator_id, title, reward_amount FROM tasks WHERE id = ?", (task_id,)).fetchone()
                if not task_data: return await update.message.reply_text("❌ Task context tracking error.")
                c_id, t_title, reward = task_data
                
                cursor.execute("INSERT INTO task_submissions (task_id, worker_id, proof_text, proof_screenshot, status, created_at) VALUES (?, ?, ?, ?, 'pending', ?)", (task_id, user_id, proof_text, file_id, now_str))
                cursor.execute("UPDATE tasks SET filled_slots = filled_slots + 1 WHERE id = ?", (task_id,))
                cursor.execute("UPDATE users SET pending_balance = pending_balance + ? WHERE user_id = ?", (reward, user_id))
            
            w_info = update.effective_user
            w_name = w_info.full_name if w_info.full_name else f"Worker_{user_id}"
            owner_notif = (
                f"📥 **New Submission Received**\n\n"
                f"👤 Worker: {w_name}\n"
                f"🆔 Worker ID: `{user_id}`\n"
                f"📋 Task: {t_title}\n"
                f"💰 Reward: {reward} Tk\n\n"
                f"Review card: /view_sub_{task_id}"
            )
            try: await context.bot.send_photo(chat_id=c_id, photo=file_id, caption=owner_notif)
            except: pass

            safe_clear_state(context)
            await show_main_menu(update, "✅ Proof Submitted Successfully! Your reward has been added to Pending Balance.")
        except Exception as e:
            logger.error(f"Task tracking proof drop error: {e}")
            await update.message.reply_text("❌ Error processing proof attachment (Already Submitted).")
        return

# =====================================================================
# CALLBACK MACROS & NAVIGATION INTERCEPTORS
# =====================================================================
async def handle_force_join_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    try:
        is_joined = await check_membership_status(context.bot, user_id)
        if is_joined:
            context.user_data["is_verified_session"] = True
            await query.message.delete()
            
            with sqlite3.connect(DATABASE) as conn:
                exists = conn.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,)).fetchone()
            
            if not exists:
                await complete_user_registration(update, context, user_id)
            else:
                await process_welcome_access(update, context)
        else:
            await query.answer("❌ You haven't joined all required channels yet! Please join first.", show_alert=True)
    except Exception as e:
        logger.error(f"Error in handle_force_join_callback: {e}")
        await query.answer("⚠️ System error while verifying. Please try again later.", show_alert=True)

async def handle_admin_nav(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data.replace("ad_nav_", "")
    user_id = query.from_user.id
    
    safe_clear_state(context)
    
    if not is_super_admin(user_id) and data not in ["main", "tasks", "disputes"]:
        return await query.message.edit_text("❌ Privilege Escalation Blocked: Super Admin only.")

    if data == "users":
        context.user_data["admin_context_state"] = {"action": "ADMIN_MANUAL_USER_SEARCH_INPUT"}
        await query.message.edit_text("👥 **User Management**\n\nSend Telegram User ID:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Dashboard", callback_data="ad_nav_main")]]))
    elif data == "finances":
        kbd = [
            [InlineKeyboardButton("Pending Withdrawals", callback_data="ad_fn_p_w"), InlineKeyboardButton("Pending Deposits", callback_data="ad_fn_p_d")],
            [InlineKeyboardButton("Payment Methods", callback_data="ad_fn_methods"), InlineKeyboardButton("➕ Add Method", callback_data="ad_fn_add_method")],
            [InlineKeyboardButton("🔙 Back to Dashboard", callback_data="ad_nav_main")]
        ]
        await query.message.edit_text("💰 **Finances Module**", reply_markup=InlineKeyboardMarkup(kbd))
    elif data == "tasks":
        if not is_sub_admin(user_id): return
        with sqlite3.connect(DATABASE) as conn:
            rows = conn.execute("SELECT id, title FROM tasks WHERE status='pending_approval' ORDER BY id").fetchall()
        out = "⏳ **Pending Tasks:**\n\n"
        for r in rows: out += f"ID: #{r[0]} | {r[1]}\nApprove: /approve_task {r[0]}\nReject: /reject_task {r[0]} Reason\n\n"
        if not rows: out = "⏳ No pending tasks."
        await query.message.edit_text(out, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="ad_nav_main")]]))
    
    elif data == "disputes":
        if not is_sub_admin(user_id): return
        with sqlite3.connect(DATABASE) as conn:
            disputes = conn.execute("""
                SELECT s.id, s.worker_id, s.task_id, t.creator_id, s.proof_text, r.rejection_reason, r.history_logs 
                FROM task_submissions s 
                JOIN tasks t ON s.task_id = t.id 
                JOIN submission_reviews r ON s.id = r.submission_id 
                WHERE s.status = 'rejected'
            """).fetchall()
        
        out = "⚖ **Disputed Proofs Queue**\n\n"
        for disp in disputes:
            out += (
                f"🎫 Submission ID: #{disp[0]}\n"
                f"👤 Worker ID: `{disp[1]}` | Task ID: #{disp[2]}\n"
                f"👑 Owner ID: `{disp[3]}`\n"
                f"💬 Worker Text: {disp[4]}\n"
                f"❌ Rejection Reason: {disp[5]}\n"
                f"📜 Review History: {disp[6]}\n"
                f"👉 Decision Commands:\n"
                f"🟢 Approve Worker: `/dispute_app {disp[0]}`\n"
                f"🔴 Keep Rejected: `/dispute_rej {disp[0]}`\n\n"
                f"------------------------\n"
            )
        if not disputes: out = "⚖ Disputed Proofs Queue is empty."
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
    elif data == "supp_mgmt":
        kbd = [
            [InlineKeyboardButton("✅ Contact Support Edit", callback_data="ad_spm_contact_text")],
            [InlineKeyboardButton("✅ Telegram Edit", callback_data="ad_spm_tg_user")],
            [InlineKeyboardButton("✅ WhatsApp Edit", callback_data="ad_spm_wa_num")],
            [InlineKeyboardButton("✅ Contact Button Edit", callback_data="ad_spm_btn_name")],
            [InlineKeyboardButton("✅ Support Message Edit", callback_data="ad_spm_contact_link")],
            [InlineKeyboardButton("🔙 Back", callback_data="ad_nav_main")]
        ]
        await query.message.edit_text("⚙️ **Support Management Section**\nSelect an option to edit configuration:", reply_markup=InlineKeyboardMarkup(kbd))
    elif data == "main":
        await admin(update, context)

async def handle_admin_sub_nav(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    user_id = query.from_user.id
    await query.answer()
    
    if data.startswith("ad_spm_"):
        field_map = {
            "ad_spm_contact_text": "supp_contact_text",
            "ad_spm_tg_user": "supp_tg_user",
            "ad_spm_wa_num": "supp_wa_num",
            "ad_spm_btn_name": "supp_btn_name",
            "ad_spm_contact_link": "supp_contact_link"
        }
        target_field = field_map.get(data)
        if target_field:
            context.user_data["support_edit_field"] = target_field
            await query.message.reply_text(f"✏️ Send new value for `{target_field}`:")
            await query.message.delete()
        return

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
        
    elif data == "ad_fn_methods":
        if not is_super_admin(user_id): return
        with sqlite3.connect(DATABASE) as conn:
            rows = conn.execute("SELECT id, method_name, account_number, payment_type FROM payment_methods").fetchall()
        out = "📱 **Configured Payment Methods:**\n\n"
        for r in rows: out += f"ID: #{r[0]} | {r[1]} ({r[3]})\n📞 No: `{r[2]}`\n🗑️ Delete: /del_method {r[0]}\n\n"
        kbd = [[InlineKeyboardButton("➕ Add New Method", callback_data="ad_fn_add_method")], [InlineKeyboardButton("🔙 Back", callback_data="ad_nav_finances")]]
        await query.message.edit_text(out if rows else "No payment methods configured.", reply_markup=InlineKeyboardMarkup(kbd))
        
    elif data == "ad_fn_add_method":
        if not is_super_admin(user_id): return
        context.user_data["admin_context_state"] = {"action": "ADMIN_ADD_METHOD_NAME"}
        await query.message.edit_text("📱 **Add New Payment Method**\n\nSend the Gateway Name (e.g., bKash, Nagad, Rocket):", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="ad_nav_finances")]]))
    
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

    elif data.startswith("ad_task_app_"):
        if not is_sub_admin(user_id): return
        t_id = int(data.split("_")[-1])
        with db_transaction() as conn:
            row = conn.execute("SELECT status, creator_id, title, category, reward_amount, total_slots FROM tasks WHERE id = ?", (t_id,)).fetchone()
            if not row or row[0] != 'pending_approval': 
                return await query.message.edit_text("❌ Not found or already processed.")
            conn.execute("UPDATE tasks SET status = 'active' WHERE id = ?", (t_id,))
        
        status, creator_id, title, category, reward, workers = row
        await query.message.edit_reply_markup(reply_markup=None)
        if query.message.caption:
            await query.message.edit_caption(caption=f"✅ Task Approved Successfully\nTask ID: #{t_id}", parse_mode="Markdown")
        else:
            await query.message.edit_text(f"✅ Task Approved Successfully\nTask ID: #{t_id}", parse_mode="Markdown")
            
        creator_msg = (
            "🎉 অভিনন্দন!\n\n"
            "আপনার টাস্ক অনুমোদিত হয়েছে।\n\n"
            f"📋 Task ID: #{t_id}\n"
            f"📌 Title: {title}\n\n"
            "✅ আপনার টাস্ক এখন লাইভ হয়েছে এবং Worker-দের জন্য উপলব্ধ।\n\n"
            "Good luck!"
        )
        try: await context.bot.send_message(chat_id=creator_id, text=creator_msg)
        except: pass

        broadcast_msg = (
            f"📢 **New Task Available**\n\n"
            f"📋 **Title:** {title}\n"
            f"💰 **Reward:** {reward} Tk\n"
            f"📂 **Category:** {category}\n"
            f"👥 **Slots:** {workers}\n\n"
            f"🚀 Start Working Now"
        )
        
        async def broadcast_approved_task_async(bot, alert_text):
            try:
                with sqlite3.connect(DATABASE) as db_conn:
                    all_users = db_conn.execute("SELECT user_id FROM users WHERE status='active'").fetchall()
                for (uid,) in all_users:
                    try: await bot.send_message(chat_id=uid, text=alert_text)
                    except: pass
            except Exception as e:
                logger.error(f"Task broadcast failure: {e}")
                
        context.application.create_task(broadcast_approved_task_async(context.bot, broadcast_msg))

    elif data.startswith("ad_task_rej_"):
        if not is_sub_admin(user_id): return
        t_id = int(data.split("_")[-1])
        await query.message.edit_reply_markup(reply_markup=None)
        context.user_data["admin_context_state"] = {"action": "ADMIN_REJECT_TASK_REASON", "task_id": t_id}
        await query.message.reply_text(f"❌ Rejecting Task #{t_id}\nSend the reason why:")

    elif data.startswith("own_sub_app_"):
        s_id = int(data.split("_")[-1])
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            with db_transaction() as conn:
                sub_row = conn.execute("SELECT s.task_id, s.worker_id, s.status, t.reward_amount, t.creator_id FROM task_submissions s JOIN tasks t ON s.task_id = t.id WHERE s.id = ?", (s_id,)).fetchone()
                if not sub_row or sub_row[2] != 'pending' or sub_row[4] != user_id:
                    return await query.message.reply_text("❌ Already finalized or Access Denied.")
                
                t_id, w_id, _, reward, _ = sub_row
                conn.execute("UPDATE task_submissions SET status = 'approved' WHERE id = ?", (s_id,))
                conn.execute("UPDATE users SET pending_balance = CASE WHEN pending_balance >= ? THEN pending_balance - ? ELSE 0 END, earnings_balance = earnings_balance + ?, total_earned = total_earned + ?, completed_tasks = completed_tasks + 1 WHERE user_id = ?", (reward, reward, reward, reward, w_id))
                conn.execute("INSERT INTO wallet_transactions (user_id, amount, balance_type, action_type, reference_id, created_at) VALUES (?, ?, 'earnings_balance', 'Task Approved', ?, ?)", (w_id, reward, f"Sub-{s_id}", now_str))
                conn.execute("INSERT OR REPLACE INTO submission_reviews (submission_id, finalized_by, finalized_time, history_logs) VALUES (?, 'Owner', ?, 'Submitted -> Approved')", (s_id, now_str))
                evaluate_user_achievements(w_id, conn)
                
            await query.message.edit_reply_markup(reply_markup=None)
            await query.message.reply_text(f"✅ Submission #{s_id} approved successfully.")
            try: 
                app_msg = (
                    f"✅ **Task Approved**\n\n"
                    f"💰 Reward Added Successfully"
                )
                await context.bot.send_message(chat_id=w_id, text=app_msg)
            except: pass
        except Exception as e: logger.error(f"Owner approve crash block: {e}")

    elif data.startswith("own_sub_rej_"):
        s_id = int(data.split("_")[-1])
        with sqlite3.connect(DATABASE) as conn:
            sub_row = conn.execute("SELECT s.status, t.creator_id FROM task_submissions s JOIN tasks t ON s.task_id = t.id WHERE s.id = ?", (s_id,)).fetchone()
            if not sub_row or sub_row[0] != 'pending' or sub_row[1] != user_id:
                return await update.message.reply_text("❌ Cannot request rejection reason.")
        
        context.user_data["admin_context_state"] = {"action": "OWNER_MANDATORY_REJECT_REASON", "sub_id": s_id}
        await query.message.reply_text("❌ Mandatorily enter the Rejection Reason for this proof:")

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

    elif data.startswith("ad_supp_reply_"):
        t_id = int(data.split("_")[-1])
        context.user_data["admin_context_state"] = {"action": "SUPPORT_TICKET_ADMIN_REPLY_INPUT", "ticket_id": t_id}
        await query.message.reply_text(f"📝 Write your reply for Ticket #{t_id}:")

    elif data == "user_notifications_history_nav":
        with sqlite3.connect(DATABASE) as conn:
            notifs = conn.execute("SELECT message, created_at FROM user_notifications WHERE user_id = ? ORDER BY id DESC LIMIT 10", (query.from_user.id,)).fetchall()
        out = "🔔 **Recent System Notifications:**\n\n"
        for n in notifs: out += f"📅 {n[1]}\n📣 {n[0]}\n------------------------\n"
        if not notifs: out = "🔔 No notification logs found."
        await query.message.reply_text(out)

async def handle_browse_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if data.startswith("br_start_task_"):
        t_id = int(data.split("_")[-1])
        context.user_data["sub_task_id"] = t_id
        
        if "task_flow_step" not in context.user_data:
            context.user_data["task_flow_step"] = "step_details_summary"
            
        if context.user_data["task_flow_step"] == "step_details_summary":
            context.user_data["task_flow_step"] = "step_ask_proof_one"
            kbd = InlineKeyboardMarkup([[InlineKeyboardButton("Next ➡️", callback_data=f"br_start_task_{t_id}")]])
            await query.message.reply_text("📋 **Step 1: Task Verification Complete**\nClick Next to submit Proof #1.", reply_markup=kbd)
            return
            
        elif context.user_data["task_flow_step"] == "step_ask_proof_one":
            context.user_data["task_submission_step"] = "entering_proof_text_fields"
            await query.message.delete()
            await context.bot.send_message(
                chat_id=user_id,
                text=f"📝 **Step 2: Submit Required Text Proof #1:**",
                reply_markup=ReplyKeyboardMarkup([["❌ Cancel"]], resize_keyboard=True)
            )
            return

    if data == "browse_back_cats":
        await find_jobs_start(update, context)
        return

    if data.startswith("browse_cat_") or data.startswith("br_cat_"):
        cat_suffix = data.split("_")[-1].strip()
        selected_cat = None
        for k in MARKETPLACE_CONFIG.keys():
            if k.endswith(cat_suffix):
                selected_cat = k
                break
                
        types = MARKETPLACE_CONFIG.get(selected_cat, [])
        type_counts = {t: 0 for t in types}
        
        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT task_type, COUNT(*) FROM tasks 
                WHERE category = ? AND status = 'active' AND expires_at > ? AND filled_slots < total_slots AND creator_id != ?
                AND id NOT IN (SELECT task_id FROM task_submissions WHERE worker_id = ?)
                GROUP BY task_type
            """, (selected_cat, now_str, user_id, user_id))
            for t_type, cnt in cursor.fetchall():
                if t_type in type_counts:
                    type_counts[t_type] = cnt
                    
        text_out = f"📁 Category: **{selected_cat}**\n\n👇 Available tasks by type:"
        keyboard = []
        for t_type, cnt in type_counts.items():
            keyboard.append([InlineKeyboardButton(f"{t_type} ({cnt})", callback_data=f"br_typ_{selected_cat.split()[-1]}||{t_type[:15]}")])
        keyboard.append([InlineKeyboardButton("🔙 Back to Categories", callback_data="browse_back_cats")])
        await query.message.edit_text(text_out, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        return

    elif data.startswith("br_typ_") or data.startswith("br_pag_"):
        if data.startswith("br_typ_"):
            parts = data.replace("br_typ_", "").split("||")
            cat_p = parts[0]
            typ_p = parts[1]
            page = 1
        else:
            parts = data.replace("br_pag_", "").split("||")
            cat_p = parts[0]
            typ_p = parts[1]
            page = int(parts[2])
            
        selected_cat, selected_type = None, None
        for k, v in MARKETPLACE_CONFIG.items():
            if k.endswith(cat_p):
                selected_cat = k
                for t in v:
                    if t.startswith(typ_p):
                        selected_type = t
                        break
                break
                
        limit = 5
        offset = (page - 1) * limit
        
        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COUNT(*) FROM tasks 
                WHERE category = ? AND task_type = ? AND status = 'active' AND expires_at > ? AND filled_slots < total_slots AND creator_id != ?
                AND id NOT IN (SELECT task_id FROM task_submissions WHERE worker_id = ?)
            """, (selected_cat, selected_type, now_str, user_id, user_id))
            total_tasks = cursor.fetchone()[0]
            
            cursor.execute("""
                SELECT id, title, reward_amount, total_slots, filled_slots, description, expires_at FROM tasks 
                WHERE category = ? AND task_type = ? AND status = 'active' AND expires_at > ? AND filled_slots < total_slots AND creator_id != ?
                AND id NOT IN (SELECT task_id FROM task_submissions WHERE worker_id = ?)
                ORDER BY id DESC LIMIT ? OFFSET ?
            """, (selected_cat, selected_type, now_str, user_id, user_id, limit, offset))
            tasks_list = cursor.fetchall()
            
        if not tasks_list:
            await query.message.edit_text(
                f"❌ No active tasks for **{selected_type}**.", 
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data=f"browse_cat_{selected_cat.split()[-1]}")]])
            )
            return
            
        text_out = f"🔍 **Find Job ({selected_type}) - Page {page}**\n\n"
        for tk in tasks_list:
            t_id, title, reward, total_s, filled_s, desc, exp_at = tk
            slots_left = total_s - filled_s
            short_desc = desc[:60] + "..." if len(desc) > 60 else desc
            text_out += f"🆔 Open Task: /view_task_{t_id}\n💎 Title: **{title}**\n💰 Reward: {reward} Tk | 👥 Slots left: {slots_left}\n📝 Details: {short_desc}\n------------------------\n"
                        
        nav_buttons = []
        if page > 1:
            nav_buttons.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"br_pag_{selected_cat.split()[-1]}||{selected_type[:15]}||{page-1}"))
        if offset + limit < total_tasks:
            nav_buttons.append(InlineKeyboardButton("Next ➡️", callback_data=f"br_pag_{selected_cat.split()[-1]}||{selected_type[:15]}||{page+1}"))
            
        keyboard = []
        if nav_buttons: keyboard.append(nav_buttons)
        keyboard.append([InlineKeyboardButton("🔙 Back", callback_data=f"browse_cat_{selected_cat.split()[-1]}")])
        await query.message.edit_text(text_out, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

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
        await context.bot.send_message(user_id, f"📊 Type: **{t_typ}**\n📝 Send Title:", reply_markup=ReplyKeyboardMarkup([["❌ Cancel"]], resize_keyboard=True))
    elif data.startswith("wz_p_t_"):
        p_type = data.split("wz_p_t_")[-1]
        wizard["proofs_config"].append({"name": wizard["current_proof_label_name"], "type": p_type})
        kbd = [[InlineKeyboardButton("➡️ Next", callback_data="wz_act_goto_tutorial_image_step")]]
        if len(wizard["proofs_config"]) < 3: kbd.insert(0, [InlineKeyboardButton("➕ Add Another", callback_data="wz_act_add_more_proof_items")])
        await query.message.edit_text(f"✅ Proof #{len(wizard['proofs_config'])} saved.\nAdd more?", reply_markup=InlineKeyboardMarkup(kbd))
    elif data == "wz_act_add_more_proof_items":
        wizard["step"] = "PROOFS_NAME_ENTRY"
        await query.message.delete()
        await context.bot.send_message(user_id, f"📋 Name of Proof #{len(wizard['proofs_config']) + 1}:")
    elif data == "wz_act_goto_tutorial_image_step":
        wizard["step"] = "TUTORIAL_IMAGE_UPLOAD"
        await query.message.delete()
        await context.bot.send_message(user_id, "📷 Upload Tutorial Image (or click Skip):", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⏭ Skip", callback_data="wz_skp_tutorial_img_upload")]]))
    elif data == "wz_skp_tutorial_img_upload":
        wizard["tutorial_image"], wizard["step"] = "", "WORKERS_LIMIT_QUANTITY_INPUT"
        await query.message.edit_text("👥 How many workers? (Min 10):")
    elif data.startswith("wz_l_"):
        days = int(data.split("_")[-1])
        wizard["time_limit"], wizard["step"] = f"{days} Days", "INVOICE_PREVIEW"
        subtotal = wizard["reward_amount"] * wizard["workers"]
        fee = int(subtotal * (int(get_setting("platform_fee", "10")) / 100))
        wizard["total_budget"] = subtotal + fee
        msg = f"📊 **Invoice Preview**\n\nTitle: {wizard['title']}\nWorkers: {wizard['workers']}\nReward: {wizard['reward_amount']} Tk\n\n💵 Budget: {subtotal} Tk\n⚡ Fee: {fee} Tk\n💳 Total: **{wizard['total_budget']} Tk**"
        await query.message.delete()
        kbd = InlineKeyboardMarkup([[InlineKeyboardButton("✅ All Done", callback_data="wz_act_publish")], [InlineKeyboardButton("❌ Cancel", callback_data="wz_act_cancel_wizard_pipeline")]])
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
            
            admin_caption = (
                f"⚙️ **New Task Awaiting Approval!**\n\n"
                f"🆔 Task ID: `#{t_id}`\n"
                f"👤 Creator ID: `{user_id}`\n"
                f"📌 Title: {wizard['title']}\n"
                f"👥 Workers: {wizard['workers']}\n"
                f"💰 Reward: {wizard['reward_amount']} Tk\n"
                f"💵 Total Budget: {budget} Tk"
            )
            admin_kbd = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Approve", callback_data=f"ad_task_app_{t_id}"),
                 InlineKeyboardButton("❌ Reject", callback_data=f"ad_task_rej_{t_id}")]
            ])
            try:
                if wizard.get("tutorial_image"):
                    await context.bot.send_photo(chat_id=ADMIN_ID, photo=wizard["tutorial_image"], caption=admin_caption, parse_mode="Markdown")
                else:
                    await context.bot.send_message(chat_id=ADMIN_ID, text=admin_caption, parse_mode="Markdown", reply_markup=admin_kbd)
            except Exception: pass
            
            safe_clear_state(context)
            await context.bot.send_message(user_id, "🎉 **Task Submitted Successfully!**\nYour task has been sent to the review team. You will be notified instantly upon approval.")
        except Exception as e:
            logger.error(f"Task wizard publication dropped: {e}")
            await context.bot.send_message(user_id, "❌ System execution error during publication saving.")
        return
        
    elif data == "wz_act_cancel_wizard_pipeline":
        safe_clear_state(context)
        await query.message.delete()
        await context.bot.send_message(user_id, "❌ Creation cancelled.")

# =====================================================================
# SYSTEM APPLICATION BOOTSTRAPPING ENGINE 
# =====================================================================
def main():
    init_db()
    
    # Run Health Checks HTTP Server inside background thread context separation loops 
    threading.Thread(target=run_web_server, daemon=True).start()
    
    # Initialize long-polling execution context mapping natively
    app = Application.builder().token(TOKEN).build()
    
    # Context Error Pipelines Registrations
    app.add_error_handler(global_error_handler)
    
    # Command Pipeline Core Dispatches mapping
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin))
    
    # Action Interception Pipelines
    app.add_handler(CallbackQueryHandler(handle_force_join_callback, pattern="^check_force_join_gate$"))
    app.add_handler(CallbackQueryHandler(handle_admin_nav, pattern="^ad_nav_"))
    app.add_handler(CallbackQueryHandler(handle_admin_sub_nav, pattern="^(ad_fn_|ad_set_|ad_adm_|ad_task_|own_sub_|ad_spm_)"))
    app.add_handler(CallbackQueryHandler(admin_fin_chat_sub_callbacks, pattern="^(dp_g_mth_|supp_|ad_chat_|ad_bal_|user_notifications_)"))
    app.add_handler(CallbackQueryHandler(handle_browse_callbacks, pattern="^(br_|browse_)"))
    app.add_handler(CallbackQueryHandler(handle_wizard_callbacks, pattern="^wz_"))
    
    # Command & Review interceptor
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex(r"^/(approve|reject|dispute_app|dispute_rej|approve_task|reject_task|approve_deposit|reject_deposit)"), handle_admin_commands))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex(r"^/(viewtask|view_task_|manage_task_|view_sub_)"), handle_regex_routing))
    
    # Main Interceptor Engines Routing Mapping Channel
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, buttons))
    app.add_handler(MessageHandler(filters.PHOTO | (filters.Document.IMAGE), handle_incoming_media_proofs))
    
    logger.info("BD94 Earning Bot Engine fully initialized. Initiating Polling execution loops...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()