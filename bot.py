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
# NEW TASK BROADCASTER ENGINE 
# =====================================================================
async def broadcast_new_task_notification(context: ContextTypes.DEFAULT_TYPE, task_id: int):
    """Automatically broadcast dynamic target alerts to all bot active users on new task launch."""
    try:
        with sqlite3.connect(DATABASE) as conn:
            task = conn.execute("SELECT title, reward_amount, category FROM tasks WHERE id = ?", (task_id,)).fetchone()
            users = conn.execute("SELECT user_id FROM users WHERE status='active'").fetchall()
            
        if not task: return
        title, reward, category = task
        
        notification_text = (
            f"🔔 **New Premium Task Available!**\n\n"
            f"📌 **Task Title:** {title}\n"
            f"📂 **Category:** {category}\n"
            f"💰 **Reward Amount:** {reward} Tk\n\n"
            f"🚀 **How to Start?**\n"
            f"Click here: /view_task_{task_id} to view details and submit proof right away!"
        )
        
        for (uid,) in users:
            try:
                await context.bot.send_message(chat_id=uid, text=notification_text, parse_mode="Markdown")
                await asyncio.sleep(0.04)
            except Exception:
                continue
    except Exception as e:
        logger.error(f"Failed to auto-broadcast task notification: {e}")

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
        warn = "📢 েবট ব্যবহার করতে হলে প্রথমে আমাদের চ্যানেলে যোগ দিন।"
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
# REGEX ROUTING SYSTEM (DYNAMIC FIXES)
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
        
        # Explicit dynamic custom formatted string handling
        proof_display = ""
        try:
            parsed_proofs = json.loads(proof_reqs) if proof_reqs else []
            if isinstance(parsed_proofs, list) and len(parsed_proofs) > 0:
                for idx, prf in enumerate(parsed_proofs, 1):
                    p_name = prf.get('name', f'Requirement {idx}')
                    p_type = prf.get('type', 'Text/Image')
                    proof_display += f"⚠️ **Proof {idx}:** {p_name} ({p_type})\n"
            else:
                proof_display = f"⚠️ **Required Proof:**\n{proof_reqs}"
        except Exception:
            if proof_reqs:
                proof_display = f"⚠️ **Required Proof:**\n{proof_reqs}"
            else:
                proof_display = "⚠️ **Required Proof:** Not explicitly provided."

        out_msg = (
            f"📋 **Task Details**\n\n"
            f"🆔 Task ID: #{t_id}\n"
            f"📌 Title: {title}\n"
            f"📂 Category: {category}\n"
            f"💎 Reward: {reward} Tk\n"
            f"👥 Slots Left: {slots_left}\n\n"
            f"📝 Instructions:\n{description}\n\n"
            f"🔗 Target Link: {link}\n\n"
            f"{proof_display}"
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
        
    if text == "🔙 Back" or text == "⬅️ Back":
        if admin_state:
            safe_clear_state(context)
            await admin(update, context)
            return
        safe_clear_state(context)
        if withdraw_state or deposit_state:
            with sqlite3.connect(DATABASE) as conn:
                row = conn.execute("SELECT deposit_balance, earnings_balance, pending_balance FROM users WHERE user_id = ?", (user_id,)).fetchone()
                if row:
                    await show_wallet_menu(update, f"💳 **Wallet Dashboard**\n📥 Deposit: {row[0]} Tk\n💰 Earnings: {row[1]} Tk\n⏳ Pending: {row[2]} Tk")
                else:
                    await show_main_menu(update, "🔙 Returned to main menu.")
                return
        await show_main_menu(update, "🔙 Returned to main menu.")
        return

    if support_edit_field:
        if not is_super_admin(user_id): return
        set_setting(support_edit_field, text)
        await update.message.reply_text(f"✅ Field `{support_edit_field}` successfully updated!")
        safe_clear_state(context)
        await admin(update, context)
        return

    # --- ADMIN / CREATOR ACTION INTERCEPT ROUTING ---
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
                        return await update.message.reply_text("❌ Submission already finalized or invalid.")
                    
                    t_id, w_id, _, c_id, t_title, reward = row
                    conn.execute("UPDATE task_submissions SET status = 'rejected' WHERE id = ?", (s_id,))
                    conn.execute("UPDATE users SET pending_balance = CASE WHEN pending_balance >= ? THEN pending_balance - ? ELSE 0 END WHERE user_id = ?", (reward, reward, w_id))
                    conn.execute("INSERT OR REPLACE INTO submission_reviews (submission_id, rejected_by, rejection_reason, rejection_time, history_logs) VALUES (?, ?, ?, ?, ?)", (s_id, user_id, text, now_str, "Submitted -> Rejected By Creator"))
                
                await update.message.reply_text(f"❌ Worker Submission #{s_id} successfully Rejected. Forwarded automatically to Admin Queue.")
                
                try:
                    rej_notif = (
                        f"❌ **Task Rejected By Employer!**\n\n"
                        f"📋 **Task:** {t_title}\n"
                        f"⚠️ **Reason/Karon:** {text}\n\n"
                        f"💡 Solution: Request processed. Please do the task correctly again if applicable."
                    )
                    await context.bot.send_message(chat_id=w_id, text=rej_notif, parse_mode="Markdown")
                except Exception:
                    pass
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
                    if not row or row[0] != 'pending_approval':
                        safe_clear_state(context)
                        return await update.message.reply_text("❌ Task already processed.")
                    
                    c_id, budget = row[1], row[2]
                    conn.execute("UPDATE tasks SET status = 'rejected' WHERE id = ?", (t_id,))
                    conn.execute("UPDATE users SET deposit_balance = deposit_balance + ? WHERE user_id = ?", (budget, c_id))
                    conn.execute("INSERT INTO wallet_transactions (user_id, amount, balance_type, action_type, reference_id, created_at) VALUES (?, ?, 'deposit_balance', 'Admin Task Rejected Refund', ?, ?)", (c_id, budget, str(t_id), now_str))
                
                await update.message.reply_text(f"🛑 Task #{t_id} rejected. Budget {budget} Tk refunded to Creator.")
                try:
                    await context.bot.send_message(chat_id=c_id, text=f"🛑 Your posted task ID #{t_id} was rejected by Admin.\n⚠️ Reason: {text}\n💰 Full budget has been refunded to your wallet.")
                except Exception: pass
                safe_clear_state(context)
            except Exception as e:
                logger.error(f"Admin reject task error: {e}")
            return

    # --- TASK SUBMISSION PROOF CAPTURING ---
    if submission_state == "AWAITING_PROOF_INPUT":
        t_id = context.user_data.get("sub_task_id")
        # Save proof text temporarily inside context state
        context.user_data["worker_submitted_proof_text"] = text
        context.user_data["task_submission_step"] = "AWAITING_SCREENSHOT_OR_CONFIRM"
        
        # Display dynamic instruction requirements clearly before finishing step
        await update.message.reply_text("✍️ Written Proof captured successfully!\n\n📸 Now send the requested screenshot proof image, or type /skip if the task doesn't require an image proof:")
        return

    # Standard navigational mapping
    if text == "📋 Job":
        await show_tasks_menu(update, "📋 Job Menu Options:")
    elif text == "🔎 Find Job":
        await find_jobs_start(update, context)
    elif text == "➕ Create Job":
        await init_job_wizard(update, context)
    elif text == "💳 Wallet":
        with sqlite3.connect(DATABASE) as conn:
            row = conn.execute("SELECT deposit_balance, earnings_balance, pending_balance FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if row:
            await show_wallet_menu(update, f"💳 **Wallet Dashboard**\n\n📥 Deposit Balance: {row[0]} Tk\n💰 Earnings Balance: {row[1]} Tk\n⏳ Pending Review: {row[2]} Tk")
    elif text == "📞 Support":
        await show_support_menu(update, "📞 Support Channel Gateway:")
    else:
        # Default text backup responses
        await update.message.reply_text("💡 Base menu choice not identified. Please use keyboard buttons.")

# =====================================================================
# CALLBACK QUEUES QUERY & ROUTERS ENGINE
# =====================================================================
async def admin_fin_chat_sub_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    await query.answer()

    # OWNER SUBMISSIONS ACTIONS MANAGER
    if data.startswith("own_sub_app_"):
        s_id = int(data.split("_")[-1])
        try:
            with db_transaction() as conn:
                row = conn.execute("SELECT s.task_id, s.worker_id, s.status, t.creator_id, t.reward_amount, t.title FROM task_submissions s JOIN tasks t ON s.task_id = t.id WHERE s.id = ?", (s_id,)).fetchone()
                if not row or row[2] != 'pending':
                    return await query.message.reply_text("❌ Submission already resolved.")
                
                t_id, w_id, _, c_id, reward, t_title = row
                if c_id != user_id:
                    return await query.message.reply_text("❌ Access Violation.")
                
                conn.execute("UPDATE task_submissions SET status = 'approved' WHERE id = ?", (s_id,))
                conn.execute("UPDATE tasks SET filled_slots = filled_slots + 1 WHERE id = ?", (t_id,))
                conn.execute("UPDATE users SET pending_balance = CASE WHEN pending_balance >= ? THEN pending_balance - ? ELSE 0 END, earnings_balance = earnings_balance + ? WHERE user_id = ?", (reward, reward, reward, w_id))
                conn.execute("INSERT INTO wallet_transactions (user_id, amount, balance_type, action_type, reference_id, created_at) VALUES (?, ?, 'earnings_balance', 'Task Completed Reward', ?, ?)", (w_id, reward, str(t_id), now_str))
                
                # Auto check achievements update
                evaluate_user_achievements(w_id, conn)
                
            await query.message.edit_reply_markup(reply_markup=None)
            await query.message.reply_text(f"✅ Submission #{s_id} successfully Approved!")
            try:
                await context.bot.send_message(chat_id=w_id, text=f"🎉 Congratulations! Your submission for task '{t_title}' has been approved.\n💰 Amount {reward} Tk added to your Earnings Balance.")
            except Exception: pass
        except Exception as e:
            logger.error(f"Error approving entry: {e}")

    elif data.startswith("own_sub_rej_"):
        s_id = int(data.split("_")[-1])
        context.user_data["admin_context_state"] = {"action": "OWNER_MANDATORY_REJECT_REASON", "sub_id": s_id}
        await query.message.reply_text("📝 **Mandatory Rejection Reason:**\nPlease write down why you are rejecting this worker's proof submission:")

    # --- WORKER COMMENCING START TASK ENGINE ---
    elif data.startswith("br_start_task_"):
        t_id = int(data.split("_")[-1])
        with sqlite3.connect(DATABASE) as conn:
            task = conn.execute("SELECT id, title, proof_requirements FROM tasks WHERE id = ?", (t_id,)).fetchone()
            existing = conn.execute("SELECT id FROM task_submissions WHERE task_id = ? AND worker_id = ?", (t_id, user_id)).fetchone()
            
        if existing:
            return await query.message.reply_text("❌ You have already submitted proof for this task.")
            
        context.user_data["sub_task_id"] = t_id
        context.user_data["task_submission_step"] = "AWAITING_PROOF_INPUT"
        
        await query.message.reply_text(
            f"🚀 **Task Initialized Successfully!**\n"
            f"📌 Task Title: {task[1]}\n\n"
            f"✍️ Please type your username or required details as requested in task proof requirements:"
        )

# =====================================================================
# FALLBACK CAPTURING SCREENSHOT PROOF STREAMS
# =====================================================================
async def fallback_attachment_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    submission_state = context.user_data.get("task_submission_step")
    
    if submission_state == "AWAITING_SCREENSHOT_OR_CONFIRM":
        t_id = context.user_data.get("sub_task_id")
        proof_text = context.user_data.get("worker_submitted_proof_text", "No typed notes provided.")
        photo_id = None
        
        if update.message.photo:
            photo_id = update.message.photo[-1].file_id
            
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        try:
            with db_transaction() as conn:
                task = conn.execute("SELECT creator_id, title, reward_amount FROM tasks WHERE id = ?", (t_id,)).fetchone()
                if not task:
                    safe_clear_state(context)
                    return await update.message.reply_text("❌ Base task matching error.")
                
                c_id, title, reward = task
                conn.execute(
                    "INSERT INTO task_submissions (task_id, worker_id, proof_text, proof_screenshot, status, created_at) VALUES (?, ?, ?, ?, 'pending', ?)",
                    (t_id, user_id, proof_text, photo_id, now_str)
                )
                conn.execute("UPDATE users SET pending_balance = pending_balance + ? WHERE user_id = ?", (reward, user_id))
                
            await update.message.reply_text("✅ **Proof Submitted Successfully!**\nYour work has been forwarded to the employer for review.", reply_markup=ReplyKeyboardMarkup([["📋 Job", "👤 Profile"], ["💳 Wallet"]], resize_keyboard=True))
            
            # Forward alert notification card automatically to employer
            try:
                alert_markup = InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ Review Submission", callback_data=f"own_sub_review_gateway_click")]
                ])
                await context.bot.send_message(
                    chat_id=c_id, 
                    text=f"📥 **New Task Submission Alert!**\n\nUser has completed your task ID #{t_id} ({title}).\nUse command /manage_task_{t_id} to review and approve/reject proofs immediately.",
                    reply_markup=alert_markup
                )
            except Exception:
                pass
            safe_clear_state(context)
        except sqlite3.IntegrityError:
            await update.message.reply_text("❌ Proof already submitted previously.")
            safe_clear_state(context)
        except Exception as e:
            logger.error(f"Task finish error submission: {e}")
            await update.message.reply_text("❌ Submission process failed.")

# =====================================================================
# HOOKING PIPELINES STREAMS & MAIN APP INITIALIZATION
# =====================================================================
def main():
    init_db()
    
    # Run server threads natively
    web_thread = threading.Thread(target=run_web_server, daemon=True)
    web_thread.start()
    
    if not TOKEN:
        logger.critical("Bot token variable configuration missing. Shutting engine down.")
        return

    app = Application.builder().token(TOKEN).build()
    
    # Basic core commands registration
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin))
    
    # Core navigation callback triggers
    app.add_handler(CallbackQueryHandler(admin_fin_chat_sub_callbacks, pattern=r'^(own_sub_|br_start_task_)'))
    
    # Core regular expression layout routing parameters
    app.add_handler(MessageHandler(filters.Regex(r'^\\/(viewtask|view_task_|manage_task_|view_sub_)\\d+'), handle_regex_routing))
    
    # Main dynamic buttons text controller router 
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, buttons))
    
    # Attachment fallback engine stream capture pipe
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE | filters.Regex(r'^/skip$'), fallback_attachment_handler))
    
    # Global systems exception handler engine
    app.add_error_handler(global_error_handler)
    
    logger.info("BD94 Premium Earning Bot Core Loop Operational.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()