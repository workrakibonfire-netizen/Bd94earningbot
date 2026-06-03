import os
import sqlite3
import logging
import datetime
import http.server
import socketserver
import threading
import asyncio
import json
import re
from contextlib import contextmanager
from dotenv import load_dotenv
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

# Marketplace configuration matrices
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

CAT_MAP = {
    "📺 YouTube": "📺 YouTube",
    "📢 Telegram": "📢 Telegram",
    "📘 Facebook": "📘 Facebook",
    "📝 Sign Up": "📝 Sign Up",
    "📊 Survey": "📊 Survey",
    "📧 Gmail Account": "📧 Gmail Account",
    "📱 Mobile Apps": "📱 Mobile Apps",
    "🎵 TikTok": "🎵 TikTok"
}

# Dummy placeholder handlers to satisfy handler maps at the end
async def handle_force_join_callback(update: Update, context: ContextTypes.DEFAULT_TYPE): pass
async def handle_wizard_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE): pass
async def handle_browse_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE): pass
async def handle_browse_finances_and_tickets_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE): pass
async def handle_admin_review_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE): pass
async def handle_redirect_job_callback(update: Update, context: ContextTypes.DEFAULT_TYPE): pass
async def handle_regex_routing(update: Update, context: ContextTypes.DEFAULT_TYPE): pass
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE): pass
async def handle_text_messages(update: Update, context: ContextTypes.DEFAULT_TYPE): pass

# =====================================================================
# SQLITE CONCURRENCY MANAGEMENT & TRANSACTION ENGINE
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
        logger.error(f"Database transaction failure - rolled back: {e}", exc_info=True)
        raise e
    finally:
        conn.close()

# =====================================================================
# SYSTEM KEY/VALUE CONFIGURATION REGISTRY
# =====================================================================
def get_setting(key: str, default: str) -> str:
    try:
        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()
            cursor.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
            conn.commit()
            cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
            row = cursor.fetchone()
            if row is not None:
                return row[0]
            cursor.execute("INSERT INTO settings (key, value) VALUES (?, ?)", (key, str(default)))
            conn.commit()
            return str(default)
    except Exception as e:
        logger.error(f"Error accessing system settings: {e}")
        return str(default)

def set_setting(key: str, value: str):
    with db_transaction() as conn:
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))

# =====================================================================
# DATABASE SCHEMA INITIALIZATION & AUTO-MIGRATIONS
# =====================================================================
def init_db():
    with sqlite3.connect(DATABASE) as conn:
        cursor = conn.cursor()
        
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            join_date TEXT,
            referrals INTEGER DEFAULT 0,
            pending_reward INTEGER DEFAULT 0,
            earned_reward INTEGER DEFAULT 0,
            referrer_id INTEGER DEFAULT 0,
            deposit_balance INTEGER DEFAULT 0,
            earnings_balance INTEGER DEFAULT 0,
            pending_balance INTEGER DEFAULT 0,
            total_withdrawn INTEGER DEFAULT 0,
            total_deposited INTEGER DEFAULT 0,
            status TEXT DEFAULT 'active',
            level INTEGER DEFAULT 1,
            completed_tasks INTEGER DEFAULT 0,
            total_earned INTEGER DEFAULT 0,
            last_active TEXT
        )""")
        
        cursor.execute("PRAGMA table_info(users)")
        u_cols = [c[1] for c in cursor.fetchall()]
        migrations = {
            "deposit_balance": "INTEGER DEFAULT 0",
            "earnings_balance": "INTEGER DEFAULT 0",
            "pending_balance": "INTEGER DEFAULT 0",
            "total_withdrawn": "INTEGER DEFAULT 0",
            "total_deposited": "INTEGER DEFAULT 0",
            "status": "TEXT DEFAULT 'active'",
            "level": "INTEGER DEFAULT 1",
            "completed_tasks": "INTEGER DEFAULT 0",
            "total_earned": "INTEGER DEFAULT 0",
            "username": "TEXT",
            "join_date": "TEXT",
            "last_active": "TEXT"
        }
        for field, definition in migrations.items():
            if field not in u_cols:
                cursor.execute(f"ALTER TABLE users ADD COLUMN {field} {definition}")
                
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS withdrawals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount INTEGER,
            method TEXT,
            number TEXT,
            status TEXT DEFAULT 'pending',
            admin_note TEXT,
            created_at TEXT
        )""")
        
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS payment_methods (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            method_name TEXT UNIQUE,
            account_number TEXT,
            payment_type TEXT,
            status TEXT DEFAULT 'enabled'
        )""")
        
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS deposits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount INTEGER,
            method_name TEXT,
            transaction_id TEXT UNIQUE,
            screenshot_file_id TEXT,
            status TEXT DEFAULT 'pending',
            admin_note TEXT,
            created_at TEXT
        )""")
        
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            creator_id INTEGER,
            title TEXT,
            description TEXT,
            link TEXT,
            proof_requirements TEXT,
            reward_amount INTEGER,
            total_slots INTEGER,
            filled_slots INTEGER DEFAULT 0,
            total_budget INTEGER,
            status TEXT DEFAULT 'pending_approval',
            created_at TEXT,
            category TEXT,
            task_type TEXT,
            tutorial_image TEXT,
            time_limit TEXT,
            expires_at TEXT
        )""")
        
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS task_submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER,
            worker_id INTEGER,
            proof_text TEXT,
            proof_screenshot TEXT,
            status TEXT DEFAULT 'pending',
            admin_note TEXT,
            created_at TEXT,
            UNIQUE(task_id, worker_id)
        )""")
        
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS support_tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            subject TEXT,
            status TEXT DEFAULT 'open',
            created_at TEXT
        )""")
        
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS support_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket_id INTEGER,
            sender_id INTEGER,
            message_text TEXT,
            attachment_file_id TEXT,
            created_at TEXT
        )""")
        
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS wallet_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount INTEGER,
            balance_type TEXT,
            action_type TEXT,
            reference_id TEXT,
            created_at TEXT
        )""")
        
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS daily_bonus_claims (
            user_id INTEGER,
            claim_date TEXT,
            PRIMARY KEY(user_id, claim_date)
        )""")
        
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS admin_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_id INTEGER,
            action_type TEXT,
            details TEXT,
            created_at TEXT
        )""")
        
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_achievements (
            user_id INTEGER,
            achievement_name TEXT,
            unlocked_at TEXT,
            PRIMARY KEY(user_id, achievement_name)
        )""")
        
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS scheduled_broadcasts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_type TEXT,
            text_payload TEXT,
            file_id TEXT,
            scheduled_at TEXT,
            status TEXT DEFAULT 'pending'
        )""")
        
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            message TEXT,
            is_read INTEGER DEFAULT 0,
            created_at TEXT
        )""")
        
        cursor.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
        conn.commit()

def log_admin_activity(admin_id, action_type, details):
    try:
        with db_transaction() as conn:
            now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            conn.execute("""
                INSERT INTO admin_logs (admin_id, action_type, details, created_at)
                VALUES (?, ?, ?, ?)
            """, (admin_id, action_type, details, now_str))
    except Exception as e:
        logger.error(f"Error compiling admin activity logs: {e}")

def evaluate_user_achievements(user_id, conn):
    cursor = conn.cursor()
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    cursor.execute("SELECT deposit_balance, earnings_balance, referrals, completed_tasks, total_earned, level FROM users WHERE user_id = ?", (user_id,))
    user_data = cursor.fetchone()
    if not user_data:
        return
        
    _, _, referrals, completed_tasks, total_earned, current_level = user_data
    
    achievements = []
    if completed_tasks >= 1:
        achievements.append("🏆 First Task Completed")
    if total_earned >= 100:
        achievements.append("🏆 Earned 100 Tk")
    if completed_tasks >= 50:
        achievements.append("🏆 Completed 50 Tasks")
    if referrals >= 10:
        achievements.append("🏆 Referred 10 Users")
        
    for ach in achievements:
        cursor.execute("SELECT COUNT(*) FROM user_achievements WHERE user_id = ? AND achievement_name = ?", (user_id, ach))
        if cursor.fetchone()[0] == 0:
            cursor.execute("INSERT INTO user_achievements (user_id, achievement_name, unlocked_at) VALUES (?, ?, ?)", (user_id, ach, now_str))
            cursor.execute("INSERT INTO user_notifications (user_id, message, created_at) VALUES (?, ?, ?)", 
                           (user_id, f"🎉 নতুন অ্যাচিভমেন্ট আনলক হয়েছে: {ach}!", now_str))
            
            new_level = current_level + 1
            cursor.execute("UPDATE users SET level = ? WHERE user_id = ?", (new_level, user_id))

def check_and_expire_tasks(conn=None):
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    should_close = False
    if conn is None:
        conn = sqlite3.connect(DATABASE, timeout=30.0)
        should_close = True
        
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, creator_id, reward_amount, total_slots, filled_slots 
            FROM tasks WHERE status = 'active' AND expires_at <= ?
        """, (now_str,))
        expired_jobs = cursor.fetchall()
        
        for job in expired_jobs:
            t_id, c_id, reward, tot, fill = job
            unused = tot - fill
            
            cursor.execute("UPDATE tasks SET status = 'expired' WHERE id = ?", (t_id,))
            if unused > 0:
                refund = int(unused * reward * 1.1)
                cursor.execute("UPDATE users SET deposit_balance = deposit_balance + ? WHERE user_id = ?", (refund, c_id))
                cursor.execute("""
                    INSERT INTO wallet_transactions (user_id, amount, balance_type, action_type, reference_id, created_at)
                    VALUES (?, ?, 'deposit_balance', 'Task Expired Refund', ?, ?)
                """, (c_id, refund, str(t_id), now_str))
                logger.info(f"Task #{t_id} auto-expired. Refunded {refund} Tk to creator {c_id}")
    except Exception as e:
        logger.error(f"Error handling automated background task expiration queries: {e}")
    finally:
        if should_close:
            conn.commit()
            conn.close()

async def process_scheduled_broadcast_loops(context: ContextTypes.DEFAULT_TYPE):
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, message_type, text_payload, file_id FROM scheduled_broadcasts WHERE status='pending' AND scheduled_at <= ?", (now_str,))
            items = cursor.fetchall()
            if not items:
                return
                
            cursor.execute("SELECT user_id FROM users WHERE status='active'")
            all_users = [u[0] for u in cursor.fetchall()]
            
        for b_id, m_type, payload, file_id in items:
            with db_transaction() as conn:
                conn.execute("UPDATE scheduled_broadcasts SET status='completed' WHERE id=?", (b_id,))
                
            success, failure = 0, 0
            for uid in all_users:
                try:
                    if m_type == "text":
                        await context.bot.send_message(chat_id=uid, text=payload, parse_mode="Markdown")
                    elif m_type == "photo":
                        await context.bot.send_photo(chat_id=uid, photo=file_id, caption=payload, parse_mode="Markdown")
                    elif m_type == "video":
                        await context.bot.send_video(chat_id=uid, video=file_id, caption=payload, parse_mode="Markdown")
                    success += 1
                    await asyncio.sleep(0.04)
                except Exception:
                    failure += 1
                    
            log_admin_activity(ADMIN_ID, "Scheduled Broadcast Completed", f"Broadcast ID: {b_id} delivered to {success} users. Failures: {failure}")
    except Exception as e:
        logger.error(f"Exception triggered during background scheduled broadcast loops processing: {e}")

# =====================================================================
# RENDER HOSTING KEEP-ALIVE SERVER ALLOCATIONS (FIXED PORT BINDING)
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
    try:
        with socketserver.TCPServer(("0.0.0.0", port), HealthHandler) as server:
            logger.info(f"Web server successfully started on port {port}")
            server.serve_forever()
    except Exception as e:
        logger.error(f"Keep-alive web port allocator failure alert: {e}")

def verify_anti_spam_cooldown(user_id, context, limit_seconds=1) -> bool:
    now = datetime.datetime.now()
    last_time = context.user_data.get("_last_msg_timestamp")
    if last_time:
        delta = (now - last_time).total_seconds()
        if delta < limit_seconds:
            return False
    context.user_data["_last_msg_timestamp"] = now
    return True

async def show_main_menu(update: Update, msg_text: str):
    keyboard = [
        ["🏠 হোম", "🔍 Find Job"],
        ["➕ Create Job", "💳 Wallet"],
        ["👤 Profile", "👥 Referral"],
        ["🎁 Bonus", "📞 Support"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    if update.callback_query:
        await update.callback_query.message.reply_text(msg_text, reply_markup=reply_markup)
    elif update.message:
        await update.message.reply_text(msg_text, reply_markup=reply_markup)

async def show_wallet_menu(update: Update, msg_text: str):
    keyboard = [
        ["📥 Deposit", "📤 Withdraw"],
        ["📜 Deposit History", "📜 Withdraw History"],
        ["📊 Transaction History"],
        ["🔙 Back"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(msg_text, reply_markup=reply_markup)

async def show_tasks_menu(update: Update, msg_text: str):
    keyboard = [
        ["🔍 Find Job", "➕ Create Job"],
        ["📌 My Posted Tasks", "📌 My Submitted Tasks"],
        ["🧧 Daily Bonus", "🔙 Back"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(msg_text, reply_markup=reply_markup)

def get_force_join_keyboard():
    keyboard = [
        [InlineKeyboardButton("🚀 Join Channel", url="https://t.me/bd94earning")],
        [InlineKeyboardButton("✅ Continue", callback_data="check_force_join_gate")]
    ]
    return InlineKeyboardMarkup(keyboard)

async def check_membership_gated(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user_id = update.effective_user.id
    if user_id == ADMIN_ID:
        return True
    if context.user_data.get("is_verified_session") is True:
        return True
        
    try:
        member = await context.bot.get_chat_member(chat_id="@bd94earning", user_id=user_id)
        if member.status in ["member", "administrator", "creator"]:
            context.user_data["is_verified_session"] = True
            return True
    except Exception as e:
        logger.warning(f"Force Join configuration warning: {e}")
        return True
        
    warn_text = (
        "📢 বট ব্যবহার করতে হলে প্রথমে আমাদের অফিসিয়াল চ্যানেলে যোগ দিন।\n\n"
        "🎁 চ্যানেলে নিয়মিত নতুন কাজ, আপডেট এবং বোনাস দেওয়া হয়।"
    )
    if update.callback_query:
        await update.callback_query.message.reply_text(warn_text, reply_markup=get_force_join_keyboard())
    elif update.message:
        await update.message.reply_text(warn_text, reply_markup=get_force_join_keyboard())
    return False

# FIX: Removed the trailing comma syntax error from here
async def is_verified_inline(query, context) -> bool:
    user_id = query.from_user.id
    if user_id == ADMIN_ID or context.user_data.get("is_verified"):
        return True
    try:
        member = await context.bot.get_chat_member(chat_id="@bd94earning", user_id=user_id)
        if member.status in ["member", "administrator", "creator"]:
            context.user_data["is_verified"] = True
            return True
    except Exception as e:
        logger.warning(f"Inline protection fault tracing: {e}")
    await query.message.reply_text("📢 বট ব্যবহার করার আগে আমাদের অফিসিয়াল চ্যানেলে যোগ দিন: @bd94earning")
    return False

async def process_welcome_access(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = (
        "🎉 BD94 Earning Bot এ স্বাগতম\n\n"
        "🚀 কাজ শুরু করুন\n"
        "📋 Job করে টাকা উপার্জন করুন\n"
        "👥 Referral দিয়ে Bonus নিন\n"
        "🎁 Daily Bonus Claim করুন\n\n"
        "নিচের মেনু থেকে একটি অপশন নির্বাচন করুন।"
    )
    if update.callback_query:
        await update.callback_query.message.reply_text(welcome_text)
    else:
        await update.message.reply_text(welcome_text)
    await show_main_menu(update, "প্রধান মেনু:")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not verify_anti_spam_cooldown(user_id, context):
        return
        
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    username = update.effective_user.username or f"user_{user_id}"
    
    referrer_id = 0
    if context.args:
        try:
            referrer_id = int(context.args[0])
            if referrer_id == user_id:
                referrer_id = 0
        except ValueError:
            pass
            
    with db_transaction() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
        if cursor.fetchone() is None:
            cursor.execute("""
                INSERT INTO users (user_id, username, join_date, referrals, pending_reward, earned_reward, referrer_id, deposit_balance, earnings_balance, pending_balance, status, level, completed_tasks, total_earned, last_active)
                VALUES (?, ?, ?, 0, 0, 0, ?, 0, 0, 0, 'active', 1, 0, 0, ?)
            """, (user_id, username, now_str, referrer_id, now_str))
            if referrer_id != 0:
                cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (referrer_id,))
                if cursor.fetchone():
                    cursor.execute("UPDATE users SET referrals = referrals + 1, pending_reward = pending_reward + 20 WHERE user_id = ?", (referrer_id,))
        else:
            conn.execute("UPDATE users SET last_active = ? WHERE user_id = ?", (now_str, user_id))

    check_and_expire_tasks()
    await process_scheduled_broadcast_loops(context)

    is_joined = True
    if user_id != ADMIN_ID:
        try:
            member = await context.bot.get_chat_member(chat_id="@bd94earning", user_id=user_id)
            if member.status not in ["member", "administrator", "creator"]:
                is_joined = False
        except Exception:
            pass

    if not is_joined:
        await check_membership_gated(update, context)
        return
        
    context.user_data["is_verified_session"] = True
    await process_welcome_access(update, context)

async def find_jobs_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    check_and_expire_tasks()
    
    counts = {cat: 0 for cat in MARKETPLACE_CONFIG.keys()}
    with sqlite3.connect(DATABASE) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT category, COUNT(*) FROM tasks 
            WHERE status = 'active' AND expires_at > ? AND filled_slots < total_slots AND creator_id != ?
            AND id NOT IN (SELECT task_id FROM task_submissions WHERE worker_id = ?)
            GROUP BY category
        """, (now_str, user_id, user_id))
        for cat, cnt in cursor.fetchall():
            if cat in counts:
                counts[cat] = cnt
                
    summary_text = "🔍 **সব উপলব্ধ কাজের ক্যাটাগরি (Find Job Engine)**\n\n"
    keyboard = []
    row_btn = []
    
    for cat_name, cnt in counts.items():
        summary_text += f"{cat_name} ({cnt})\n"
        ref_token = cat_name.split()[-1]
        row_btn.append(InlineKeyboardButton(cat_name, callback_data=f"br_cat_{ref_token}"))
        if len(row_btn) == 2:
            keyboard.append(row_btn)
            row_btn = []
    if row_btn:
        keyboard.append(row_btn)
        
    summary_text += "\n👇 কাজ ব্রাউজ করার জন্য ক্যাটাগরি সিলেক্ট করুন:"
    if update.callback_query:
        await update.callback_query.message.edit_text(summary_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    else:
        await update.message.reply_text(summary_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def init_job_wizard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    context.user_data["job_wizard"] = {"step": "CATEGORY_SELECT", "proofs_config": []}
    
    keyboard = []
    row = []
    for cat in MARKETPLACE_CONFIG.keys():
        row.append(InlineKeyboardButton(cat, callback_data=f"wz_cat_{cat.split()[-1]}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
        
    await update.message.reply_text(
        "💼 **নতুন কাজ তৈরি করার উইজার্যান্ড (AjkerKaj-Style Setup)**\n\n👇 প্রথমে কাজের জন্য সঠিক ক্যাটাগরি নির্বাচন করুন:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# =====================================================================
# FIXED/RESTORED ADMINISTRATIVE CAPABILITIES FUNCTIONS
# =====================================================================
async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Access Denied!")
        return
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 Users Management", callback_data="admin_nav_users"), InlineKeyboardButton("📋 Pending Tasks", callback_data="admin_nav_tasks")],
        [InlineKeyboardButton("💳 Audit Deposits", callback_data="admin_nav_deposits"), InlineKeyboardButton("💸 Audit Withdrawals", callback_data="admin_nav_withdrawals")],
        [InlineKeyboardButton("📨 Support Tickets", callback_data="admin_nav_support"), InlineKeyboardButton("📊 System Analytics", callback_data="admin_nav_analytics")]
    ])
    await update.message.reply_text("👑 **BD94 Admin Control Panel Dashboard**\n\n👇 অ্যাকশন নির্বাচন করুন:", reply_markup=keyboard)

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    check_and_expire_tasks()
    with sqlite3.connect(DATABASE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM users")
        tot_u = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM deposits WHERE status='approved'")
        tot_d = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM withdrawals WHERE status='approved'")
        tot_w = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM tasks WHERE status='pending_approval'")
        p_tsk = cursor.fetchone()[0]
    await update.message.reply_text(
        f"📊 **BD94 Core Quick Metrics Stats:**\n\n"
        f"👥 মোট ইউজার: {tot_u} জন\n"
        f"📥 সফল ডিপোজিট: {tot_d} টি\n"
        f"💸 সফল উইথড্র: {tot_w} টি\n"
        f"⏳ অপেক্ষমান টাস্ক: {p_tsk} টি"
    )

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    if not context.args:
        await update.message.reply_text("ব্যবহার নিয়ম: /broadcast আপনার বার্তা")
        return
    message = "📢 **গ্লোবাল নোটিফিকেশন ব্রডকাস্ট**\n\n" + " ".join(context.args)
    with sqlite3.connect(DATABASE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM users WHERE status='active'")
        rows = cursor.fetchall()
    sent = 0
    for r in rows:
        try:
            await context.bot.send_message(chat_id=r[0], text=message)
            sent += 1
            await asyncio.sleep(0.05)
        except Exception: pass
    await update.message.reply_text(f"✅ সফলভাবে {sent} জন সচল মেম্বারকে ব্রডকাস্ট মেসেজ পাঠানো হয়েছে।")

async def show_pending(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    with sqlite3.connect(DATABASE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, user_id, amount, method, number, created_at FROM withdrawals WHERE status='pending' ORDER BY id ASC")
        rows = cursor.fetchall()
    if not rows:
        await update.message.reply_text("📥 কোনো পেন্ডিং উইথড্রয়াল রিকোয়েস্ট নেই।")
        return
    text = "📥 **পেন্ডিং উইথড্রয়াল তালিকা:**\n\n"
    for r in rows:
        text += f"ID: #{r[0]} | ইউজার: {r[1]}\n💰 পরিমাণ: {r[2]} Tk | মেথড: {r[3]}\n📞 নম্বর: `{r[4]}`\n📅 ডেট: {r[5]}\n✅ এপ্রুভ: /approve {r[0]}\n❌ রিজেক্ট: /reject {r[0]} Reason\n------------------------\n"
    await update.message.reply_text(text)

async def show_withdraws(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    with sqlite3.connect(DATABASE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, user_id, amount, method, status FROM withdrawals ORDER BY id DESC LIMIT 20")
        rows = cursor.fetchall()
    if not rows:
        await update.message.reply_text("📜 কোনো উইথড্র রেকর্ড নেই।")
        return
    text = "📜 **সর্বশেষ ২০টি উইথড্র রিকোয়েস্ট লগ:**\n\n"
    for r in rows:
        ico = "⏳" if r[4] == "pending" else "✅" if r[4] == "approved" else "❌"
        text += f"#{r[0]} | User: {r[1]} | {r[2]} Tk | {r[3]} | {ico} {r[4]}\n"
    await update.message.reply_text(text)

async def approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    if not context.args:
        await update.message.reply_text("ব্যবহার নিয়ম: /approve <request_id>")
        return
    try:
        req_id = int(context.args[0])
        with db_transaction() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT user_id, amount, status, method, number FROM withdrawals WHERE id = ?", (req_id,))
            row = cursor.fetchone()
            if not row or row[2] != 'pending':
                await update.message.reply_text("❌ অবৈধ বা ইতিমধ্যে প্রসেসকৃত রিকোয়েস্ট আইডি।")
                return
            user_id, amount, status, method, number = row
            cursor.execute("UPDATE withdrawals SET status = 'approved' WHERE id = ?", (req_id,))
            cursor.execute("UPDATE users SET total_withdrawn = total_withdrawn + ? WHERE user_id = ?", (amount, user_id))
            
            cursor.execute("SELECT COUNT(*) FROM withdrawals WHERE user_id = ? AND status = 'approved' AND id != ?", (user_id, req_id))
            if cursor.fetchone()[0] == 0:
                cursor.execute("SELECT referrer_id FROM users WHERE user_id = ?", (user_id,))
                ref_row = cursor.fetchone()
                if ref_row and ref_row[0] != 0:
                    referrer_id = ref_row[0]
                    cursor.execute("""
                        UPDATE users SET deposit_balance = deposit_balance + 20, earnings_balance = earnings_balance + 20,
                        earned_reward = earned_reward + 20, pending_reward = CASE WHEN pending_reward >= 20 THEN pending_reward - 20 ELSE 0 END
                        WHERE user_id = ?
                    """, (referrer_id,))
                    cursor.execute("""
                        INSERT INTO wallet_transactions (user_id, amount, balance_type, action_type, reference_id, created_at)
                        VALUES (?, 20, 'earnings_balance', 'Referral Reward Payout', ?, ?)
                    """, (referrer_id, str(user_id), datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
                    try:
                        await context.bot.send_message(chat_id=referrer_id, text=f"🎉 অভিনন্দন! আপনার রেফারে জয়েনকৃত ইউজার সফল উইথড্র করায় ২০ টাকা বোনাস যোগ হয়েছে।")
                    except Exception: pass
        await update.message.reply_text(f"✅ উইথড্রাল রিকোয়েস্ট #{req_id} সফলভাবে অ্যাপ্রুভ হয়েছে।")
        try:
            await context.bot.send_message(chat_id=user_id, text=f"✅ **আপনার উইথড্রাল সফলভাবে সম্পন্ন হয়েছে!**\n\nআইডি: #{req_id}\n💰 পরিমাণ: {amount} Tk\n📱 মেথড: {method}\n📞 অ্যাকাউন্ট: {number}")
        except Exception: pass
    except Exception as e:
        logger.error(f"Error in payout approval system route: {e}")

async def reject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    if len(context.args) < 2:
        await update.message.reply_text("ব্যবহার নিয়ম: /reject <request_id> <reason>")
        return
    try:
        req_id = int(context.args[0])
        reason = " ".join(context.args[1:])
        with db_transaction() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT user_id, amount, status FROM withdrawals WHERE id = ?", (req_id,))
            row = cursor.fetchone()
            if not row or row[2] != 'pending': return
            user_id, amount, status = row
            cursor.execute("UPDATE withdrawals SET status = 'rejected', admin_note = ? WHERE id = ?", (reason, req_id))
            cursor.execute("UPDATE users SET deposit_balance = deposit_balance + ?, earnings_balance = earnings_balance + ? WHERE user_id = ?", (amount, amount, user_id))
        await update.message.reply_text(f"❌ উইথড্রাল রিকোয়েস্ট #{req_id} বাতিল করা হয়েছে। ফান্ড রিфান্ড সফল।")
        try:
            await context.bot.send_message(chat_id=user_id, text=f"❌ **আপনার উইথড্রাল রিকোয়েস্টটি বাতিল করা হয়েছে!**\n\nঅনুরোধ আইডি: #{req_id}\n💬 কারণ: {reason}\n💰 টাকা আপনার ওয়ালেটে রিফান্ড করা হয়েছে।")
        except Exception: pass
    except Exception as e: logger.error(f"Error rejecting withdrawal: {e}")

async def payment_methods(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    with sqlite3.connect(DATABASE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, method_name, account_number, payment_type, status FROM payment_methods")
        rows = cursor.fetchall()
    if not rows:
        await update.message.reply_text("📱 কোনো পেমেন্ট গেটওয়ে অ্যাড করা নেই।")
        return
    text = "📱 **সিস্টেম গেটওয়ে তালিকা:**\n\n"
    for r in rows:
        text += f"ID: {r[0]} | {r[1]} ({r[3]}) | No: {r[2]} | Status: {r[4]}\n"
    await update.message.reply_text(text)

async def add_payment_method(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    raw_text = " ".join(context.args)
    if "|" not in raw_text:
        await update.message.reply_text("নিয়ম: /add_payment_method Name|Number|Type")
        return
    data = raw_text.split("|")
    if len(data) < 3: return
    name, number, p_type = data[0].strip(), data[1].strip(), data[2].strip()
    with db_transaction() as conn:
        conn.execute("INSERT OR REPLACE INTO payment_methods (method_name, account_number, payment_type, status) VALUES (?, ?, ?, 'enabled')", (name, number, p_type))
    await update.message.reply_text(f"✅ সফলভাবে পেমেন্ট মেথড '{name}' যুক্ত করা হয়েছে।")

async def delete_payment_method(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    if not context.args: return
    try:
        m_id = int(context.args[0])
        with db_transaction() as conn:
            conn.execute("DELETE FROM payment_methods WHERE id = ?", (m_id,))
        await update.message.reply_text(f"🗑️ গেটওয়ে আইডি #{m_id} সফলভাবে মুছে ফেলা হয়েছে।")
    except ValueError: pass

async def show_deposits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    with sqlite3.connect(DATABASE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, user_id, amount, method_name, transaction_id, status, created_at, screenshot_file_id FROM deposits WHERE status='pending' ORDER BY id DESC")
        rows = cursor.fetchall()
    if not rows:
        await update.message.reply_text("📥 কোনো পেন্ডিং ডিপোজিট রিকোয়েস্ট নেই।")
        return
    await update.message.reply_text(f"📊 সর্বমোট {len(rows)} টি ডিপোজিট টিকিট পেন্ডিং আছে:")
    for r in rows:
        caption = f"📥 **ডিপোজিট ভেরিফিকেশন টিকিট**\n\nDeposit ID: #{r[0]}\nইউজার আইডি: {r[1]}\nপরিমাণ: {r[2]} Tk\nমেথড: {r[3]}\nTxID: `{r[4]}`\nতারিখ: {r[6]}\n\n✅ এপ্রুভ: /approve_deposit {r[0]}\n❌ রিজেক্ট: /reject_deposit {r[0]} Reason"
        if r[7]:
            try:
                await context.bot.send_photo(chat_id=ADMIN_ID, photo=r[7], caption=caption)
                continue
            except Exception: pass
        await update.message.reply_text(caption)

async def approve_deposit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    if not context.args: return
    try:
        dep_id = int(context.args[0])
        with db_transaction() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT user_id, amount, status FROM deposits WHERE id = ?", (dep_id,))
            row = cursor.fetchone()
            if not row or row[2] != 'pending':
                await update.message.reply_text("❌ অবৈধ বা ইতিমধ্যে প্রসেসকৃত ডিপোজিট আইডি।")
                return
            user_id, amount, _ = row
            cursor.execute("UPDATE deposits SET status = 'approved' WHERE id = ?", (dep_id,))
            cursor.execute("UPDATE users SET deposit_balance = deposit_balance + ?, total_deposited = total_deposited + ? WHERE user_id = ?", (amount, amount, user_id))
            cursor.execute("""
                INSERT INTO wallet_transactions (user_id, amount, balance_type, action_type, reference_id, created_at)
                VALUES (?, ?, 'deposit_balance', 'Deposit Approved', ?, ?)
            """, (user_id, amount, str(dep_id), datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        await update.message.reply_text(f"✅ ডিপোজিট আইডি #{dep_id} অ্যাপ্রুভড সম্পন্ন।")
        try:
            await context.bot.send_message(chat_id=user_id, text=f"✅ **আপনার ডিপোজিট সফলভাবে অ্যাপ্রুভ করা হয়েছে!**\n\nডিপোজিট আইডি: #{dep_id}\n💰 পরিমাণ: {amount} Tk আপনার Deposit Balance 에 যোগ করা হয়েছে।")
        except Exception: pass
    except ValueError: pass

async def reject_deposit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    if len(context.args) < 2: return
    try:
        dep_id = int(context.args[0])
        reason = " ".join(context.args[1:])
        with db_transaction() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT user_id, status FROM deposits WHERE id = ?", (dep_id,))
            row = cursor.fetchone()
            if not row or row[1] != 'pending': return
            cursor.execute("UPDATE deposits SET status = 'rejected', admin_note = ? WHERE id = ?", (reason, dep_id))
        await update.message.reply_text(f"❌ ডিপোজিট #{dep_id} রিজেক্ট করা হয়েছে।")
        try:
            await context.bot.send_message(chat_id=row[0], text=f"❌ **আপনার ডিপোজিট রিকোয়েস্টটি বাতিল করা হয়েছে!**\n\nআইডি: #{dep_id}\n💬 কারণ: {reason}")
        except Exception: pass
    except ValueError: pass

# =====================================================================
# THE APPLICATION CONFIGURATION MAIN SYSTEM RUNNER (FIXED FOR DEPLOYMENT)
# =====================================================================
def main():
    # 1. Initialize database schemas completely
    init_db()
    
    # 2. Start the Render web health check-alive daemon server thread
    web_thread = threading.Thread(target=run_web_server, daemon=True)
    web_thread.start()
    
    # 3. Formulate the core bot engine application object
    if not TOKEN:
        logger.error("CRITICAL EXCEPTION: TELEGRAM_BOT_TOKEN missing in environment configuration.")
        return
        
    app = Application.builder().token(TOKEN).build()
    
    # Registering core routing pathways handlers completely
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("broadcast", broadcast))
    app.add_handler(CommandHandler("pending", show_pending))
    app.add_handler(CommandHandler("withdraws", show_withdraws))
    app.add_handler(CommandHandler("approve", approve))
    app.add_handler(CommandHandler("reject", reject))
    app.add_handler(CommandHandler("payment_methods", payment_methods))
    app.add_handler(CommandHandler("add_payment_method", add_payment_method))
    app.add_handler(CommandHandler("delete_payment_method", delete_payment_method))
    app.add_handler(CommandHandler("deposits", show_deposits))
    app.add_handler(CommandHandler("approve_deposit", approve_deposit))
    app.add_handler(CommandHandler("reject_deposit", reject_deposit))
    
    # Callback queries filters routers maps logic engine mapping
    app.add_handler(CallbackQueryHandler(handle_force_join_callback, pattern=r'^check_force_join_gate$'))
    app.add_handler(CallbackQueryHandler(handle_wizard_callbacks, pattern=r'^wz_'))
    app.add_handler(CallbackQueryHandler(handle_browse_callbacks, pattern=r'^br_'))
    app.add_handler(CallbackQueryHandler(handle_browse_finances_and_tickets_callbacks, pattern=r'^(dp_|supp_|admin_nav_|ad_bal_|ad_user_|user_n)'))
    app.add_handler(CallbackQueryHandler(handle_admin_review_callbacks, pattern=r'^ad_'))
    app.add_handler(CallbackQueryHandler(handle_redirect_job_callback, pattern=r'^redirect_job_'))
    
    # Catch-all regex and structural messaging content filters registry logic
    app.add_handler(MessageHandler(filters.Regex(r'^\/(view_task_|submit_proof_|manage_task_|view_sub_|approve_sub_|reject_sub_|final_approve_sub_|final_reject_sub_)\d+'), handle_regex_routing))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_messages))
    
    logger.info("BD94 Earning Bot Engine fully functional. Starting long polling...")
    app.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()