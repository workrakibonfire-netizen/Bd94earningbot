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

# Load local environment variables if available
load_dotenv()

# Logging configuration
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Config variables from environment
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "8079009018"))
DATABASE = "database.db"

# =====================================================================
# SYSTEM CATEGORY & PRICING TYPE CONFIGURATIONS
# =====================================================================
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

# =====================================================================
# SQLITE CONCURRENCY MANAGEMENT & TRANSACTION ENGINE
# =====================================================================
@contextmanager
def db_transaction():
    """
    Context manager providing exclusive write access via BEGIN IMMEDIATE.
    Guarantees absolute atomicity under multiple simultaneous async write loops.
    """
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

# =====================================================================
# SYSTEM WIDE ADMINISTRATIVE ACTIVITY TRACKING RECORDERS
# =====================================================================
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

# =====================================================================
# SYSTEM ACHIEVEMENTS MONITOR ENGINE LOGICS
# =====================================================================
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

# =====================================================================
# AUTOMATIC DYNAMIC RETRACTION & BACKGROUND BROADCAST PIPELINES
# =====================================================================
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
# SECURITY LAYER ANTI-SPAM CONTROL REGISTERS
# =====================================================================
def verify_anti_spam_cooldown(user_id, context, limit_seconds=1) -> bool:
    now = datetime.datetime.now()
    last_time = context.user_data.get("_last_msg_timestamp")
    if last_time:
        delta = (now - last_time).total_seconds()
        if delta < limit_seconds:
            return False
    context.user_data["_last_msg_timestamp"] = now
    return True

# =====================================================================
# NAVIGATION SCHEMAS INTERFACES
# =====================================================================
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

# =====================================================================
# CHANNELS FORCE JOIN VERIFICATION INTERFACES
# =====================================================================
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

async def is_verified_inline(query, context) -> bool:
    """Fixed: Removed trailing syntax error comma from the if constraint logic statement."""
    user_id = query.from_user.id
    if user_id == ADMIN_ID or context.user_data.get("is_verified_session"):
        return True
    try:
        member = await context.bot.get_chat_member(chat_id="@bd94earning", user_id=user_id)
        if member.status in ["member", "administrator", "creator"]:
            context.user_data["is_verified_session"] = True
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

# =====================================================================
# FUNCTIONAL PATHWAYS CONTROLLERS
# =====================================================================
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

# =====================================================================
# THE SEARCH FILTERS & AD-HOC MICRO TASK MARKETPLACE CONTROLLERS
# =====================================================================
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

# =====================================================================
# THE SECURE SYSTEM CREATE JOB INTEGRATED WIZARD IMPLEMENTATION
# =====================================================================
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
        "💼 **নতুন কাজ তৈরি করার উইজার্ড (AjkerKaj-Style Setup)**\n\n👇 প্রথমে কাজের জন্য সঠিক ক্যাটাগরি নির্বাচন করুন:",
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
                        UPDATE users SET balance = balance + 20, earnings_balance = earnings_balance + 20,
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
            cursor.execute("UPDATE users SET balance = balance + ?, earnings_balance = earnings_balance + ? WHERE user_id = ?", (amount, amount, user_id))
        await update.message.reply_text(f"❌ উইথড্রাল রিকোয়েস্ট #{req_id} বাতিল করা হয়েছে। ফান্ড রিফান্ড সফল।")
        try:
            await context.bot.send_message(chat_id=user_id, text=f"❌ **আপনার উইথড্রাল রিকোয়েস্টটি বাতিল করা হয়েছে!**\n\nঅনুরোধ আইডি: #{req_id}\n💬 কারণ: {reason}\n💰 টাকা আপনার আর্নিংস ওয়ালেটে রিফান্ড করা হয়েছে।")
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
            await context.bot.send_message(chat_id=user_id, text=f"✅ **আপনার ডিপোজিট সফলভাবে অ্যাপ্রুভ করা হয়েছে!**\n\nডিপোজিট আইডি: #{dep_id}\n💰 পরিমাণ: {amount} Tk আপনার Deposit Balance এ যোগ করা হয়েছে।")
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
# WORKER ACTION FLOW SUBSYSTEM HANDLERS 
# =====================================================================
async def view_task_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    try:
        task_id = int(text.replace("/view_task_", "").strip())
    except ValueError: return
    
    with sqlite3.connect(DATABASE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, creator_id, title, description, link, proof_requirements, reward_amount, total_slots, filled_slots, status FROM tasks WHERE id = ?", (task_id,))
        task = cursor.fetchone()
        if not task:
            await update.message.reply_text("❌ এই টাস্ক আইডিটি সিস্টেমে পাওয়া যায়নি।")
            return
        cursor.execute("SELECT status FROM task_submissions WHERE task_id = ? AND worker_id = ?", (task_id, update.effective_user.id))
        prior_sub = cursor.fetchone()
        
    status_txt = "❌ Already Submitted" if prior_sub else "✅ Available to Work"
    if task[9] != 'active' or task[8] >= task[7]: status_txt = "🔒 Closed / Expired"
    
    out = f"📋 **টাস্ক বিস্তারিত বিবরণী [ID: #{task[0]}]**\n\n📌 শিরোনাম: {task[2]}\n💰 কাজের রিওয়ার্ড: {task[6]} Tk\n👥 স্লট খালি: {task[8]} / {task[7]}\n📊 অবস্থা: {status_txt}\n\n🔗 লিংক: {task[4]}\n\n📝 কাজের নিয়মাবলি:\n{task[3]}\n\n📋 প্রমাণের প্রয়োজনীয়তা:\n"
    try:
        proofs = json.loads(task[5])
        for idx, prf in enumerate(proofs):
            out += f"   {idx+1}. {prf['name']} ({'টেক্সট প্রুফ' if prf['type']=='text' else 'স্ক্রিনশট প্রুফ'})\n"
    except Exception:
        out += f"{task[5]}\n"
        
    if not prior_sub and task[9] == 'active' and task[8] < task[7] and task[1] != update.effective_user.id:
        out += f"\n👉 কাজটি সম্পন্ন করে প্রুফ জমা দিতে ক্লিক করুন: /submit_proof_{task[0]}"
    await update.message.reply_text(out, parse_mode="Markdown")

async def submit_proof_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    try:
        task_id = int(text.replace("/submit_proof_", "").strip())
    except ValueError: return
    
    with sqlite3.connect(DATABASE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, creator_id, status, total_slots, filled_slots FROM tasks WHERE id = ?", (task_id,))
        task = cursor.fetchone()
        if not task or task[2] != 'active' or task[4] >= task[3]:
            await update.message.reply_text("❌ এই টাস্কটি সক্রিয় নেই বা স্লট পূর্ণ হয়ে গেছে।")
            return
        if task[1] == user_id:
            await update.message.reply_text("❌ নিজের পোস্টে নিজে কাজ জমা দেওয়া সম্ভব নয়।")
            return
        cursor.execute("SELECT id FROM task_submissions WHERE task_id = ? AND worker_id = ?", (task_id, user_id))
        if cursor.fetchone():
            await update.message.reply_text("❌ আপনি ইতিমধ্যেই এই কাজের প্রুফ একবার সাবমিট করেছেন।")
            return
            
    context.user_data.clear()
    context.user_data["sub_task_id"] = task_id
    context.user_data["task_submission_step"] = "entering_proof_text_fields"
    await update.message.reply_text(f"📝 টাস্ক #{task_id} এর কাজের প্রমাণসমূহ (Text Proof Requirements) এখানে বিস্তারিত লিখে পাঠান:", reply_markup=ReplyKeyboardMarkup([["❌ Cancel"]], resize_keyboard=True))

async def manage_task_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    try:
        task_id = int(text.replace("/manage_task_", "").strip())
    except ValueError: return
    
    with sqlite3.connect(DATABASE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, creator_id, title, reward_amount, filled_slots, total_slots FROM tasks WHERE id = ?", (task_id,))
        task = cursor.fetchone()
        if not task or task[1] != user_id:
            await update.message.reply_text("❌ অ্যাক্সেস ডিনাইড!")
            return
        cursor.execute("SELECT id, worker_id, status FROM task_submissions WHERE task_id = ? AND status = 'pending'", (task_id,))
        subs = cursor.fetchall()
        
    out = f"🛠️ **টাস্ক ম্যানেজমেন্ট প্যানেল: #{task[0]}**\n💎 টাইটেল: {task[2]}\n💰 প্রতি কাজের রিওয়ার্ড: {task[3]} Tk\n👥 স্লট ধারণক্ষমতা: {task[4]}/{task[5]}\n\n"
    if not subs:
        out += "📥 এই টাস্কটির জন্য বর্তমানে কোনো ওয়ার্কার প্রুফ রিভিউ অপেক্ষমান নেই।"
    else:
        out += f"📥 পেন্ডিং সাবমিশনসমূহ ({len(subs)}):\n\n"
        for s in subs:
            out += f"📎 প্রুফ আইডি দেখতে ক্লিক করুন: /view_sub_{s[0]} | ইউজার আইডি: {s[1]}\n"
    await update.message.reply_text(out)

async def view_submission_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    try:
        sub_id = int(text.replace("/view_sub_", "").strip())
    except ValueError: return
    
    with sqlite3.connect(DATABASE) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT s.id, s.task_id, s.worker_id, s.proof_text, s.proof_screenshot, s.status, t.creator_id, t.title 
            FROM task_submissions s JOIN tasks t ON s.task_id = t.id WHERE s.id = ?
        """, (sub_id,))
        sub = cursor.fetchone()
        
    if not sub or sub[6] != user_id:
        await update.message.reply_text("❌ এই সাবমিশনটি দেখার অনুমতি আপনার নেই।")
        return
        
    out = f"🗳️ **ওয়ার্কার সাবমিশন ভেরিফিকেশন [Sub ID: #{sub[0]}]**\n📌 টাস্ক আইডি: #{sub[1]} - {sub[7]}\n👥 ওয়ার্কার প্রোফাইল আইডি: {sub[2]}\n📊 রিভিউ স্ট্যাটাস: {sub[5]}\n\n💬 জমাকৃত টেক্সট প্রুফ:\n{sub[3]}\n\n"
    if sub[5] == 'pending':
        out += f"👉 এই কাজটি অনুমোদন করতে ক্লিক: /approve_sub_{sub[0]}\n👉 এটি বাতিল বা রিজেক্ট করতে ক্লিক: /reject_sub_{sub[0]}"
               
    if sub[4]:
        try:
            await update.message.reply_photo(photo=sub[4], caption=out)
            return
        except Exception: pass
    await update.message.reply_text(out)

async def approve_submission_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    try:
        sub_id = int(text.replace("/approve_sub_", "").strip())
    except ValueError: return

    try:
        with db_transaction() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT s.task_id, s.worker_id, s.status, t.creator_id, t.reward_amount 
                FROM task_submissions s JOIN tasks t ON s.task_id = t.id WHERE s.id = ?
            """, (sub_id,))
            row = cursor.fetchone()
            if not row or row[3] != user_id:
                await update.message.reply_text("❌ অ্যাক্সেস ডিনাইড বা অবৈধ আইডি!")
                return
            if row[2] != 'pending':
                await update.message.reply_text(f"❌ এটি ইতিমধ্যে রিভিউ করা হয়েছে। স্ট্যাটাস: {row[2]}")
                return
            t_id, worker_id, _, _, reward = row
            cursor.execute("UPDATE task_submissions SET status = 'approved' WHERE id = ?", (sub_id,))
            cursor.execute("UPDATE users SET earnings_balance = earnings_balance + ?, total_earned = total_earned + ?, completed_tasks = completed_tasks + 1 WHERE user_id = ?", (reward, reward, worker_id))
            evaluate_user_achievements(worker_id, conn)
            
            conn.execute("""
                INSERT INTO wallet_transactions (user_id, amount, balance_type, action_type, reference_id, created_at)
                VALUES (?, ?, 'earnings_balance', 'Task Approved', ?, ?)
            """, (worker_id, reward, f"Sub-{sub_id}", datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            
        await update.message.reply_text(f"✅ সফলভাবে সাবমিটকৃত কাজ #{sub_id} অনুমোদন করা হয়েছে। ওয়ার্কারকে ব্যালেন্স পাঠানো হয়েছে।")
        try:
            await context.bot.send_message(chat_id=worker_id, text=f"🎉 **অভিনন্দন!**\n\nআপনার টাস্ক সাবমিশন (ID: #{sub_id}) সফলভাবে Approved হয়েছে।\n💰 Reward Added: ৳{reward} আপনার ওয়ালেটে যোগ হয়েছে।")
        except Exception: pass
    except Exception as e:
        logger.error(f"Error approving task worker completion entry: {e}")

async def reject_submission_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    try:
        sub_id = int(text.replace("/reject_sub_", "").strip())
    except ValueError: return
    
    with sqlite3.connect(DATABASE) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT s.id, s.status, t.creator_id 
            FROM task_submissions s JOIN tasks t ON s.task_id = t.id WHERE s.id = ?
        """, (sub_id,))
        row = cursor.fetchone()
    if not row or row[2] != user_id:
        await update.message.reply_text("❌ অ্যাক্সেস ডিনাইড!")
        return
    if row[1] != 'pending':
        await update.message.reply_text("❌ এই সাবমিশনটি ইতিমধ্যে প্রসেস করা হয়েছে।")
        return
        
    context.user_data.clear()
    context.user_data["admin_context_state"] = {"action": "MANDATORY_REJECT_REASON_SUBMISSION", "sub_id": sub_id}
    await update.message.reply_text(f"❌ সাবমিশন #{sub_id} রিজেক্ট করার উইজার্ড।\n\nওয়ার্কার কি কারণে কাজটি ভুল করেছে তার স্পষ্ট একটি কারণ (Reject Reason) এখানে লিখে মেসেজ পাঠান:")

# =====================================================================
# INTERFACE DRIVEN DYNAMIC TEXT INPUT FIELD MACHINE (TEXT MESSAGES INTERCEPTOR)
# =====================================================================
async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_membership_gated(update, context):
        return
        
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
    await process_scheduled_broadcast_loops(context)

    if text == "❌ Cancel":
        context.user_data.clear()
        await show_main_menu(update, "❌ সেশন বাতিল করা হয়েছে। মূল ড্যাশবোর্ডে ফেরত আসা হয়েছে।")
        return

    if text == "🔙 Back":
        context.user_data.clear()
        if withdraw_state or deposit_state:
            with sqlite3.connect(DATABASE) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT deposit_balance, earnings_balance, pending_balance FROM users WHERE user_id = ?", (user_id,))
                r = cursor.fetchone()
            msg = f"💳 **ওয়ালেট ব্যালেন্স স্টেটমেন্ট ক্যাশ ড্যাশবোর্ড**\n\n📥 Deposit Balance: {r[0]} Tk\n💰 Earning Balance: {r[1]} Tk\n⏳ Pending Balance: {r[2]} Tk"
            await show_wallet_menu(update, msg)
        elif wizard_state or ticket_state or submission_state:
            await show_tasks_menu(update, "📝 টাস্ক ও জব সেটিংস ড্যাশবোর্ড:")
        else:
            await show_main_menu(update, "🔙 মূল মেনুতে ফেরত যাওয়া হলো।")
        return

    if admin_state:
        action = admin_state.get("action")
        if action == "MANDATORY_REJECT_REASON_SUBMISSION":
            sub_id = admin_state.get("sub_id")
            try:
                with db_transaction() as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        SELECT s.task_id, s.worker_id, s.status, t.title 
                        FROM task_submissions s JOIN tasks t ON s.task_id = t.id WHERE s.id = ?
                    """, (sub_id,))
                    row = cursor.fetchone()
                    if not row or row[2] != 'pending':
                        await update.message.reply_text("❌ এই সাবমিশনটি ইতিমধ্যে প্রসেস করা হয়েছে বা协同 সিস্টেমে নেই।")
                        context.user_data.clear()
                        return
                    t_id, worker_id, _, t_title = row
                    cursor.execute("UPDATE task_submissions SET status = 'rejected', admin_note = ? WHERE id = ?", (text, sub_id))
                    cursor.execute("UPDATE tasks SET filled_slots = CASE WHEN filled_slots > 0 THEN filled_slots - 1 ELSE 0 END WHERE id = ?", (t_id,))
                
                log_admin_activity(ADMIN_ID, "Task Submission Rejected", f"Submission ID: {sub_id} for user {worker_id}. Reason: {text}")
                context.user_data.clear()
                await update.message.reply_text(f"❌ Worker Submission #{sub_id} চূড়ান্তভাবে রিজেক্ট করা হয়েছে এবং নোটিফিকেশন পাঠানো হয়েছে।")
                try:
                    await context.bot.send_message(
                        chat_id=worker_id,
                        text=f"❌ **আপনার Task Rejected হয়েছে।**\n\n📌 টাস্ক টাইটেল: {t_title}\n💬 কারণ: {text}"
                    )
                except Exception: pass
            except Exception as e:
                logger.error(f"Error inside processing mandatory text rejection statements fields: {e}")
            return

        elif action == "ADMIN_MANUAL_USER_SEARCH_INPUT":
            try:
                target_uid = int(text)
                with sqlite3.connect(DATABASE) as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT user_id, referrals, deposit_balance, earnings_balance, pending_balance, status, level FROM users WHERE user_id = ?", (target_uid,))
                    u = cursor.fetchone()
                if not u:
                    await update.message.reply_text("❌ এই ইউজার আইডিটি বটের ডাটাবেস নেটওয়ার্কে খুঁজে পাওয়া যায়নি। আবার আইডি দিন:")
                    return
                context.user_data["admin_managed_target_uid"] = target_uid
                msg = f"👤 **ইউজার প্রোফাইল বিবরণী [ID: {u[0]}]**\n\n📊 স্ট্যাটাস: {u[5]} | লেভেল: {u[6]}\n👥 মোট রেফারের সংখ্যা: {u[1]} জন\n📥 Deposit Balance: {u[2]} Tk\n💰 Earning Balance: {u[3]} Tk\n⏳ Pending Balance: {u[4]} Tk"
                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🚫 Ban User", callback_data=f"ad_user_ban_{target_uid}"), InlineKeyboardButton("🟢 Unban User", callback_data=f"ad_user_unban_{target_uid}")],
                    [InlineKeyboardButton("✏️ Edit Deposit Bal", callback_data=f"ad_bal_edit_deposit_balance"), InlineKeyboardButton("✏️ Edit Earning Bal", callback_data=f"ad_bal_edit_earnings_balance")],
                    [InlineKeyboardButton("🔙 ব্যাক টু কন্ট্রোল প্যানেল", callback_data="admin_nav_users")]
                ])
                await update.message.reply_text(msg, reply_markup=keyboard)
            except ValueError:
                await update.message.reply_text("❌ ইউজার আইডি অবশ্যই সংখ্যা হতে হবে! পুনরায় সঠিক আইডি টাইপ করুন:")
            return

        elif action == "ADMIN_EDIT_BALANCE_VALUE_INPUT":
            t_uid = context.user_data.get("admin_managed_target_uid")
            b_field = admin_state.get("field")
            try:
                new_val = int(text)
                with db_transaction() as conn:
                    conn.execute(f"UPDATE users SET {b_field} = ? WHERE user_id = ?", (new_val, t_uid))
                log_admin_activity(ADMIN_ID, "Manual Balance Adjustment", f"Admin modified user {t_uid} field {b_field} to value {new_val}")
                await update.message.reply_text(f"✅ সফলভাবে ইউজার {t_uid} এর {b_field} কলাম পরিবর্তন করে {new_val} Tk নির্ধারণ করা হয়েছে।")
                context.user_data.clear()
            except ValueError:
                await update.message.reply_text("❌ ব্যালেন্সের মান অবশ্যই একটি পূর্ণসংখ্যা হতে হবে! পুনরায় টাইপ করুন:")
            return

        elif action == "ADMIN_GATEWAY_ADD_NUMBER_CAPTURE":
            g_name = admin_state.get("gateway_name")
            g_type = admin_state.get("gateway_type")
            with db_transaction() as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO payment_methods (method_name, account_number, payment_type, status)
                    VALUES (?, ?, ?, 'enabled')
                """, (g_name, text, g_type))
            log_admin_activity(ADMIN_ID, "Gateway Configured", f"Admin modified gate {g_name} toward number {text}")
            await update.message.reply_text(f"✅ সফলভাবে {g_name} ({g_type}) পেমেন্ট মেথড নম্বর `{text}` সিস্টেমে সচল করা হয়েছে।")
            context.user_data.clear()
            return

        elif action == "ADMIN_TICKET_LIVE_REPLY_TEXT_INPUT":
            t_id = admin_state.get("ticket_id")
            try:
                with db_transaction() as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT user_id FROM support_tickets WHERE id = ?", (t_id,))
                    usr = cursor.fetchone()
                    if usr:
                        cursor.execute("INSERT INTO support_messages (ticket_id, sender_id, message_text, created_at) VALUES (?, ?, ?, ?)", (t_id, ADMIN_ID, text, now_str))
                await update.message.reply_text(f"✅ টিকিট #{t_id} এ আপনার রিপ্লাই সফলভাবে পাঠানো হয়েছে।")
                context.user_data.clear()
                if usr:
                    try:
                        await context.bot.send_message(chat_id=usr[0], text=f"📨 **سাপোর্ট টিকিট লাইভ চ্যাট আপডেট!**\n\nআপনার ওপেন টিকিট #{t_id} এ সাপোর্ট টিম থেকে উত্তর এসেছে:\n\n💬 {text}")
                    except Exception: pass
            except Exception as e:
                logger.error(f"Error forwarding administrative reply string logs: {e}")
            return

    if ticket_state == "ENTERING_TICKET_SUBJECT":
        if len(text) < 4:
            await update.message.reply_text("⚠️ টিকিটের বিষয়বস্তু আরেকটু বিস্তারিত লিখুন (নূন্যতম ৪ অক্ষর):")
            return
        context.user_data["active_ticket_subject"] = text
        context.user_data["ticket_wizard_step"] = "ENTERING_TICKET_NET_MESSAGE"
        await update.message.reply_text("💬 এবার আপনার সমস্যাটি বিস্তারিত লিখে পাঠান। আপনি চাইলে একটি স্ক্রিনশটও আপলোড করতে পারেন:")
        return

    elif ticket_state == "ENTERING_TICKET_NET_MESSAGE":
        subj = context.user_data.get("active_ticket_subject")
        try:
            with db_transaction() as conn:
                cursor = conn.cursor()
                cursor.execute("INSERT INTO support_tickets (user_id, subject, created_at) VALUES (?, ?, ?)", (user_id, subj, now_str))
                t_id = cursor.lastrowid
                cursor.execute("INSERT INTO support_messages (ticket_id, sender_id, message_text, created_at) VALUES (?, ?, ?, ?)", (t_id, user_id, text, now_str))
            context.user_data.clear()
            await show_tasks_menu(update, f"✅ আপনার সাপোর্ট টিকিট রেফারেন্স অ্যাকাউন্ট সফলভাবে জেনারেট হয়েছে! টিকিট আইডি: #{t_id}\nঅ্যাডমিন দ্রুত আপনার মেসেজ রিভিউ করে রিপ্লাই প্রদান করবেন।")
            try:
                await context.bot.send_message(chat_id=ADMIN_ID, text=f"📨 **নতুন সাপোর্ট টিকিট ওপেন হয়েছে!**\n\nটিকিট আইডি: #{t_id}\nইউজার: {user_id}\nবিষয়: {subj}\nবার্তালগ: {text}")
            except Exception: pass
        except Exception as e:
            logger.error(f"Support routing channels structural execution errors: {e}")
        return

    elif ticket_state == "LIVE_CHAT_REPLY_MESSAGE_ENTRY":
        t_id = context.user_data.get("active_chat_ticket_id")
        with db_transaction() as conn:
            conn.execute("INSERT INTO support_messages (ticket_id, sender_id, message_text, created_at) VALUES (?, ?, ?, ?)", (t_id, user_id, text, now_str))
            conn.execute("UPDATE support_tickets SET status='open' WHERE id=?", (t_id,))
        context.user_data.clear()
        await show_tasks_menu(update, "✅ আপনার বার্তাটি সফলভাবে বায়ার/সাপোর্ট টিম প্যানেলে ফরওয়ার্ড করা হয়েছে।")
        try:
            await context.bot.send_message(chat_id=ADMIN_ID, text=f"💬 **টিকিট #{t_id} এ ইউজারের নতুন মেসেজ এসেছে:**\n\n👤 ইউজার: {user_id}\n💬 বার্তা: {text}")
        except Exception: pass
        return

    if wizard_state:
        wizard = context.user_data["job_wizard"]
        if wizard_state == "TITLE_ENTRY_PHASE":
            if len(text) < 5:
                await update.message.reply_text("⚠️ শিরোনাম অত্যন্ত ছোট! নূন্যতম ৫ অক্ষরের শিরোনাম টাইপ করুন:")
                return
            wizard["title"] = text
            wizard["step"] = "DESC_ENTRY_PHASE"
            await update.message.reply_text("📄 **ধাপ ৪**: এবার কাজের সম্পূর্ণ বিবরণ (Detailed Steps Description) সুন্দর করে মেসেজে লিখে পাঠান:")
            return

        elif wizard_state == "DESC_ENTRY_PHASE":
            if len(text) < 10:
                await update.message.reply_text("⚠️ বিবরণ অত্যন্ত সংক্ষিপ্ত! কাজের নিয়মাবলি পরিষ্কার করতে নূন্যতম ১০ অক্ষরের বিবরণ দিন:")
                return
            wizard["description"] = text
            wizard["step"] = "LINK_ENTRY_PHASE"
            await update.message.reply_text("🔗 **ধাপ ৫**: কাজের নির্দিষ্ট লিংক (Target URL Link / Username) এখানে সাবমিট করুন:")
            return

        elif wizard_state == "LINK_ENTRY_PHASE":
            if len(text) < 3:
                await update.message.reply_text("⚠️ কাজের সঠিক লিংকটি টাইপ করে পাঠান:")
                return
            wizard["link"] = text
            wizard["step"] = "PROOFS_NAME_ENTRY"
            await update.message.reply_text("📋 **ধাপ ৬**: প্রুফ রিকোয়ারমেন্ট সেটআপ।\n\n👇 ১ম প্রুফের নাম কি হবে তা লিখে পাঠান (যেমন: Username, Profile Link, Screenshot):")
            return

        elif wizard_state == "PROOFS_NAME_ENTRY":
            if len(text) < 2:
                await update.message.reply_text("⚠️ সঠিক প্রুফের বিবরণী লেবেল টাইপ করুন:")
                return
            wizard["current_proof_label_name"] = text
            wizard["step"] = "PROOFS_TYPE_BUTTONS_SELECT"
            keyboard = [
                [InlineKeyboardButton("📝 Text Proof", callback_data="wz_p_t_text")],
                [InlineKeyboardButton("📸 Screenshot Proof", callback_data="wz_p_t_photo")]
            ]
            await update.message.reply_text(f"📌 প্রুফের নাম: **{text}**\n\n👇 ওয়ার্কাররা এই প্রমাণটি কিভাবে বটের মাধ্যমে সাবমিট করবে? ধরণ সিলেক্ট করুন:", reply_markup=InlineKeyboardMarkup(keyboard))
            return

        elif wizard_state == "WORKERS_LIMIT_QUANTITY_INPUT":
            try:
                qty = int(text)
                if qty < 10: raise ValueError
            except ValueError:
                await update.message.reply_text("⚠️ ভুল ইনপুট! নূন্যতম ১০ জন ওয়ার্কার প্রয়োজন। সঠিক সংখ্যা টাইপ করুন (যেমন: ৫০):")
                return
            wizard["workers"] = qty
            wizard["step"] = "REWARD_PRICE_VALUE_SETTING"
            
            cat = wizard.get("category")
            t_type = wizard.get("task_type")
            floor_rate = DEFAULT_MIN_RATES.get(cat, {}).get(t_type, 3)
            wizard["floor_rate"] = floor_rate
            
            await update.message.reply_text(f"💰 **ধাপ ৮**: প্রতি কাজের জন্য ওয়ার্কারকে কত টাকা রিওয়ার্ড দিতে চান তার পরিমাণ লিখুন।\n\n⚠️ আপনার সিলেক্ট করা কাজের নূন্যতম ফ্লোর রেট রেটিং হচ্ছে: **{floor_rate} Tk** (এর কম দিতে পারবেন না):")
            return

        elif wizard_state == "REWARD_PRICE_VALUE_SETTING":
            try:
                reward_val = int(text)
                floor = wizard.get("floor_rate", 3)
                if reward_val < floor: raise ValueError
            except ValueError:
                await update.message.reply_text(f"❌ রেট প্রদেয় ফ্লোর প্রাইস এর নিচে রাখা সম্ভব নয়! নূন্যতম **{wizard.get('floor_rate')} Tk** বা তার বেশি সংখ্যা টাইপ করুন:")
                return
            wizard["reward_amount"] = reward_val
            wizard["step"] = "TIME_LIMIT_SELECTION_BUTTONS"
            keyboard = [
                [InlineKeyboardButton("📅 1 Day", callback_data="wz_l_1"), InlineKeyboardButton("📅 3 Days", callback_data="wz_l_3")],
                [InlineKeyboardButton("📅 7 Days", callback_data="wz_l_7")]
            ]
            await update.message.reply_text("📅 **ধাপ ৯**: ওয়ার্কাররা সর্বোচ্চ কতদিনের মধ্যে কাজটি সম্পন্ন করার সুযোগ পাবে? টাইম লিমিট বাটন সিলেক্ট করুন:", reply_markup=InlineKeyboardMarkup(keyboard))
            return

    if deposit_state == "ENTERING_RECHARGE_AMOUNT_RAW":
        try:
            amt = int(text)
            if amt < 50: raise ValueError
        except ValueError:
            await update.message.reply_text("❌ সর্বনিম্ন ডিপোজিট ৫০ টাকা! অনুগ্রহ করে ৫০ বা তার বেশি সঠিক অংকের টাকা টাইপ করুন:")
            return
        context.user_data["dep_amount"] = amt
        context.user_data["deposit_step"] = "ENTERING_TRANSACTION_ID_RAW"
        await update.message.reply_text("🔢 টাকা পাঠানোর পর আপনার ট্রানজেকশন আইডি (Transaction ID / TxID) এখানে টাইপ করে লিখে পাঠান:", reply_markup=ReplyKeyboardMarkup([["❌ Cancel"]], resize_keyboard=True))
        return

    elif deposit_state == "ENTERING_TRANSACTION_ID_RAW":
        if len(text) < 4:
            await update.message.reply_text("❌ ট্রানজেকশন আইডি সঠিক নয়! আবার টাইপ করুন:")
            return
        context.user_data["dep_txid"] = text
        context.user_data["deposit_step"] = "ATTACHING_VERIFICATION_SCREENSHOT"
        await update.message.reply_text("📸 সফল লেনদেনের প্রমাণ হিসেবে স্ক্রিনশট ফাইল (Screenshot Image Photo) এখানে আপলোড করে দিন:")
        return

    if current_step == "step_1":
        if text in ["150 Tk", "300 Tk", "500 Tk", "1000 Tk"]:
            amount = int(text.split()[0])
            with sqlite3.connect(DATABASE) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT earnings_balance FROM users WHERE user_id = ?", (user_id,))
                user_bal = cursor.fetchone()[0] or 0
            if user_bal < amount:
                await update.message.reply_text(f"❌ দুঃখিত, আপনার উইথড্রযোগ্য Earnings Balance পর্যাপ্ত নয়! বর্তমান ব্যালেন্স: {user_bal} Tk")
                return
            context.user_data["amount"] = amount
            context.user_data["withdraw_step"] = "step_2"
            keyboard = [["📱 bKash", "📱 Nagad"], ["🔙 Back"]]
            await update.message.reply_text(f"💰 আপনি {amount} Tk উইথড্র করতে চেয়েছেন।\n📱 পেমেন্ট মেথড নির্বাচন করুন:", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))
        return

    elif current_step == "step_2":
        if text in ["📱 bKash", "📱 Nagad"]:
            context.user_data["method"] = text
            context.user_data["withdraw_step"] = "step_3"
            await update.message.reply_text(f"💳 পেমেন্ট মেথড: {text}\n📞 আপনার পার্সোনাল একাউন্ট নম্বরটি লিখে পাঠান:", reply_markup=ReplyKeyboardMarkup([["❌ Cancel"]], resize_keyboard=True))
        return

    elif current_step == "step_3":
        if len(text) < 11:
            await update.message.reply_text("❌ ভুল নম্বর! সঠিক ১১ ডিজিটের মোবাইল নম্বরটি আবার লিখে পাঠান:")
            return
        context.user_data["number"] = text
        context.user_data["withdraw_step"] = "step_4"
        keyboard = [["✅ Continue"], ["🔙 Back", "❌ Cancel"]]
        await update.message.reply_text(f"🔍 **উইথড্রাল রিকোয়েস্ট সামারি**\n\n💰 উইথড্র পরিমাণ: {context.user_data.get('amount')} Tk\n📱 মেথড: {context.user_data.get('method')}\n📞 অ্যাকাউন্ট নং: {text}\n\nঅনুরোধটি চূড়ান্ত করতে '✅ Continue' বাটন ক্লিক করুন।", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))
        return

    elif current_step == "step_4" and text == "✅ Continue":
        amount = context.user_data.get("amount")
        method = context.user_data.get("method")
        number = context.user_data.get("number")
        
        try:
            with db_transaction() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT earnings_balance FROM users WHERE user_id = ?", (user_id,))
                user_bal = cursor.fetchone()[0] or 0
                if user_bal < amount:
                    await update.message.reply_text("❌ পর্যাপ্ত ব্যালেন্স নেই। উইথড্র রিকোয়েস্ট বাতিল করা হয়েছে।")
                    context.user_data.clear()
                    return
                cursor.execute("UPDATE users SET earnings_balance = earnings_balance - ?, total_withdrawn = total_withdrawn + ? WHERE user_id = ?", (amount, amount, user_id))
                cursor.execute("INSERT INTO withdrawals (user_id, amount, method, number, status, created_at) VALUES (?, ?, ?, ?, 'pending', ?)", (user_id, amount, method, number, now_str))
                req_id = cursor.lastrowid
                
            context.user_data.clear()
            await show_main_menu(update, f"✅ উইথড্রাল অনুরোধ সফলভাবে সাবমিট করা হয়েছে! রিকোয়েস্ট আইডি: #{req_id}\nঅ্যাডমিন ভেরিফাই করে দ্রুত আপনার নম্বরে টাকা পাঠিয়ে দেবে।")
            try:
                await context.bot.send_message(chat_id=ADMIN_ID, text=f"📥 **নতুন উইথড্রাল রিকোয়েস্ট!**\n\nরিকোয়েস্ট আইডি: #{req_id}\nইউজার আইডি: {user_id}\n💰 পরিমাণ: {amount} Tk\n📱 মেথড: {method}\n📞 অ্যাকাউন্ট: {number}")
            except Exception: pass
        except Exception as e:
            logger.error(f"Error inside saving withdrawal state machine channels: {e}")
        return

    if text == "📊 Dashboard":
        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT deposit_balance, earnings_balance, pending_balance, referrals FROM users WHERE user_id = ?", (user_id,))
            r = cursor.fetchone()
        await update.message.reply_text(
            f"📊 **ইউজার ড্যাশবোর্ড স্ট্যাটাস**\n\n👤 ইউজার আইডি: {user_id}\n📥 Deposit Balance: {r[0] if r else 0} Tk\n💰 Earning Balance: {r[1] if r else 0} Tk\n⏳ Pending Balance: {r[2] if r else 0} Tk\n👥 মোট সফল রেফারেল: {r[3] if r else 0} জন"
        )
    elif text == "📝 Tasks":
        await show_tasks_menu(update, "📝 টাস্ক ও জব সেটিংস ড্যাশবোর্ড মেনু:")
    elif text == "🔍 Find Job":
        await find_jobs_start(update, context)
    elif text == "➕ Create Job":
        await init_job_wizard(update, context)
    elif text == "💳 Wallet":
        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT deposit_balance, earnings_balance, pending_balance, total_withdrawn, total_deposited FROM users WHERE user_id = ?", (user_id,))
            r = cursor.fetchone()
        wallet_text = (
            f"💳 **সিকিউর ওয়ালেট ব্যালেন্স স্টেটমেন্ট ড্যাশবোর্ড**\n\n📥 Deposit Balance: {r[0]} Tk\n💰 Earning Balance: {r[1]} Tk\n⏳ Pending Balance: {r[2]} Tk\n\n📊 **সর্বমোট ওয়ালেট পরিসংখ্যান বিবরণী:**\n📈 মোট ডিপোজিট সম্পন্ন: {r[4]} Tk\n📉 মোট উইথড্রয়াল সম্পন্ন: {r[3]} Tk\n\nনিচের সাব-মেনু থেকে আপনার অ্যাকশন নির্বাচন করুন:"
        )
        await show_wallet_menu(update, wallet_text)
    elif text == "📥 Deposit":
        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, method_name, account_number, payment_type FROM payment_methods WHERE status='enabled'")
            rows = cursor.fetchall()
        if not rows:
            await update.message.reply_text("❌ দুঃখিত, পেমেন্ট গেটওয়ে চ্যানেলগুলো বর্তমানে সাময়িকভাবে বন্ধ আছে।")
            return
        context.user_data.clear()
        context.user_data["deposit_step"] = "SELECTING_PAYMENT_GATEWAY_METHOD"
        keyboard = [[InlineKeyboardButton(f"📱 {r[1]} ({r[3]})", callback_data=f"dp_g_mth_{r[0]}")] for r in rows]
        await update.message.reply_text("📥 ব্যালেন্স রিচার্জ করার জন্য নিচের যেকোনো একটি সক্রিয় গেটওয়ে বাটন সিলেক্ট করুন:", reply_markup=InlineKeyboardMarkup(keyboard))
    elif text == "📤 Withdraw":
        min_withdraw = int(get_setting("min_withdraw", "150"))
        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT earnings_balance FROM users WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
        balance = row[0] if row else 0
        if balance < min_withdraw:
            await update.message.reply_text(f"❌ দুঃখিত, আপনার ব্যালেন্স পর্যাপ্ত নয়! নূন্যতম উইথড্রয়াল লিমিট {min_withdraw} Tk।")
            return
        await show_withdraw_amounts(update, context)
    elif text == "📜 Deposit History":
        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, amount, method_name, status FROM deposits WHERE user_id = ? ORDER BY id DESC LIMIT 5", (user_id,))
            rows = cursor.fetchall()
        if not rows:
            await update.message.reply_text("📜 কোনো ডিপোজিট হিস্ট্রি রেকর্ড পাওয়া যায়নি।")
            return
        hist = "📥 **ডিপোজিট হিস্ট্রি লেজার স্টেটমেন্ট**\n\n"
        for r in rows:
            ico = "⏳" if r[3] == "pending" else "✅" if r[3] == "approved" else "❌"
            hist += f"ডিপোজিট আইডি #{r[0]} - {r[1]} Tk মেথড: {r[2]} ({ico} {r[3]})\n"
        await update.message.reply_text(hist)
    elif text == "📜 Withdraw History":
        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, amount, method, status FROM withdrawals WHERE user_id = ? ORDER BY id DESC LIMIT 5", (user_id,))
            rows = cursor.fetchall()
        if not rows:
            await update.message.reply_text("📜 কোনো উইথড্রয়াল হিস্ট্রি রেকর্ড পাওয়া যায়নি।")
            return
        hist = "📤 **উইথড্রয়াল হিস্ট্রি লেজার স্টেটমেন্ট**\n\n"
        for r in rows:
            ico = "⏳" if r[3] == "pending" else "✅" if r[3] == "approved" else "❌"
            hist += f"উইথড্র রিকোয়েস্ট #{r[0]} - {r[1]} Tk মেথড: {r[2]} ({ico} {r[3]})\n"
        await update.message.reply_text(hist)
    elif text == "📊 Transaction History":
        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT amount, balance_type, action_type, created_at FROM wallet_transactions WHERE user_id = ? ORDER BY id DESC LIMIT 10", (user_id,))
            rows = cursor.fetchall()
        if not rows:
            await update.message.reply_text("📊 হিসাব খাতার কোনো লেনদেন রেকর্ড পাওয়া যায়নি।")
            return
        out = "📊 **হিসাব খাতা লেজার বিবরণী (সর্বশেষ ১০টি ট্রানজেকশন):**\n\n"
        for r in rows:
            sign = "+" if r[0] > 0 else ""
            out += f"📅 [{r[3]}]\n💥 টাইপ: {r[2]} ({r[1]})\n💰 পরিমাণ: {sign}{r[0]} Tk\n------------------------\n"
        await update.message.reply_text(out)
    elif text == "👤 Profile":
        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT username, join_date, level, completed_tasks, referrals, total_earned, earnings_balance, deposit_balance FROM users WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
        if row:
            uname, j_date, lvl, comp, refs, tot_earn, earn_b, dep_b = row
            prof_txt = (
                f"👤 **BD94 আর্নিং প্রোফাইল ড্যাশবোর্ড**\n\n🆔 ইউজার আইডি: `{user_id}`\n👤 ইউজারনেম: @{uname}\n📅 জয়েনিং ডেট: {j_date}\n\n🏆 কারেন্ট লেভেল: Level {lvl}\n✅ সম্পন্নকৃত টাস্ক: {comp} টি\n👥 মোট রেফারেল সংখ্যা: {refs} জন\n\n📈 সর্বমোট লাইফটাইম আয়: {tot_earn} Tk\n💰 Earnings Balance: {earn_b} Tk\n📥 Deposit Balance: {dep_b} Tk"
            )
            keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔔 নোটিফিকেশন হিস্ট্রি", callback_data="user_notifications_history_nav")]])
            await update.message.reply_text(prof_txt, reply_markup=keyboard, parse_mode="Markdown")
    elif text == "📌 My Posted Tasks":
        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, title, reward_amount, filled_slots, total_slots, status FROM tasks WHERE creator_id = ? ORDER BY id DESC", (user_id,))
            rows = cursor.fetchall()
        if not rows:
            await update.message.reply_text("📝 আপনার পোস্ট করা কোনো কাজের রেকর্ড ডাটাবেসে পাওয়া যায়নি।")
            return
        text_out = "🛠️ **আপনার পোস্ট করা কাজের তালিকা:**\n\n"
        for r in rows:
            status_lbl = "⏰ Expired" if r[5] == 'expired' else r[5]
            text_out += f"🆔 কাজ ম্যানেজ করতে ক্লিক: /manage_task_{r[0]}\n📌 টাইটেল: {r[1]}\n💰 রিওয়ার্ড: {r[2]} Tk | স্লট: {r[3]}/{r[4]} | স্ট্যাটাস: {status_lbl}\n------------------------\n"
        await update.message.reply_text(text_out)
    elif text == "📌 My Submitted Tasks":
        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT s.id, s.task_id, t.title, t.reward_amount, s.status 
                FROM task_submissions s JOIN tasks t ON s.task_id = t.id 
                WHERE s.worker_id = ? ORDER BY s.id DESC LIMIT 15
            """, (user_id,))
            rows = cursor.fetchall()
        if not rows:
            await update.message.reply_text("📜 আপনার সম্পন্ন করা কোনো কাজের প্রুফ সাবমিশন রেকর্ড নেই।")
            return
        text_out = "🗳️ **আপনার জমাকৃত কাজের প্রুফ ও বর্তমান অবস্থা:**\n\n"
        for r in rows:
            status_ico = "⏳" if r[4] == "pending" else "✅" if r[4] == "approved" else "❌"
            text_out += f"প্রুফ আইডি: #{r[0]} | টাস্ক আইডি: #{r[1]}\n💎 টাইটেল: {r[2]}\n💰 পেমেন্ট: {r[3]} Tk | রিভিউ স্ট্যাটাস: {status_ico} {r[4]}\n------------------------\n"
        await update.message.reply_text(text_out)
    elif text == "🎁 Bonus":
        await update.message.reply_text("🧧 ডেইলি রিওয়ার্ড বোনাস ক্লেইম অপশনটি এখন '📝 Tasks' সাব-মেনু ড্যাশবোর্ডে স্থানান্তর করা হয়েছে।")
    elif text == "🧧 Daily Bonus":
        today_date = datetime.datetime.now().strftime("%Y-%m-%d")
        daily_bonus_amt = int(get_setting("daily_bonus", "2"))
        try:
            with db_transaction() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM task_submissions WHERE worker_id = ? AND status = 'approved'", (user_id,))
                approved_tasks_count = cursor.fetchone()[0]
                
                if approved_tasks_count == 0:
                    await update.message.reply_text("❌ Daily Bonus পেতে হলে আগে অন্তত ১টি টাস্ক সফলভাবে Complete করতে হবে।")
                    return
                
                cursor.execute("SELECT COUNT(*) FROM daily_bonus_claims WHERE user_id = ? AND claim_date = ?", (user_id, today_date))
                if cursor.fetchone()[0] > 0:
                    await update.message.reply_text("❌ আপনি আজকের Daily Bonus ইতিমধ্যে সংগ্রহ করেছেন।")
                    return
                
                cursor.execute("INSERT INTO daily_bonus_claims (user_id, claim_date) VALUES (?, ?)", (user_id, today_date))
                cursor.execute("UPDATE users SET balance = balance + ?, earnings_balance = earnings_balance + ? WHERE user_id = ?", (daily_bonus_amt, daily_bonus_amt, user_id))
                cursor.execute("""
                    INSERT INTO wallet_transactions (user_id, amount, balance_type, action_type, reference_id, created_at)
                    VALUES (?, ?, 'earnings_balance', 'Daily Bonus', 'BONUS', ?)
                """, (user_id, daily_bonus_amt, now_str))
            await update.message.reply_text(f"🎁 **Daily Bonus Claimed!**\n\n💰 Reward: {daily_bonus_amt} Tk\n✅ Added to Earnings Balance")
        except sqlite3.IntegrityError:
            await update.message.reply_text("❌ আপনি আজকের Daily Bonus ইতিমধ্যে সংগ্রহ করেছেন।")
        except Exception:
            await update.message.reply_text("❌ টেকনিক্যাল সমস্যার কারণে বোনাস প্রসেস করা যায়নি।")
        return
    elif text == "📞 Support":
        context.user_data.clear()
        context.user_data["ticket_wizard_step"] = "ENTERING_TICKET_SUBJECT"
        await update.message.reply_text("📞 **লাইভ চ্যাট সাপোর্ট সিস্টেম**\n\n💬 একটি নতুন সাপোর্ট টিকিট খোলার জন্য প্রথমে আপনার সমস্যার সংক্ষেপ বিষয়বস্তু (Subject) লিখে মেসেজ পাঠান:", reply_markup=ReplyKeyboardMarkup([["❌ Cancel"]], resize_keyboard=True))
    else:
        if not current_step and not dep_step and not task_step and not sub_step and not review_step and not wizard_state and not ticket_state and not admin_state:
            await show_main_menu(update, "❓ ভুল কম্যান্ড নির্বাচন! অনুগ্রহ করে বাটন ব্যবহার করুন:")

# =====================================================================
# THE STRUCTURAL CONTROL PANEL ROOT HUB ROUTINES MAPPER
# =====================================================================
def main():
    if not TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN environment variable is not defined!")
    
    init_db()
    
    get_setting("min_withdraw", "150")
    get_setting("platform_fee", "10")
    get_setting("daily_bonus", "2")
    
    web_thread = threading.Thread(target=run_web_server, daemon=True)
    web_thread.start()
    
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())

    app = Application.builder().token(TOKEN).build()
    
    # Handlers configuration arrays mapping pathways
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("broadcast", broadcast))
    app.add_handler(CommandHandler("show_pending", show_pending))
    app.add_handler(CommandHandler("show_withdraws", show_withdraws))
    app.add_handler(CommandHandler("approve", approve))
    app.add_handler(CommandHandler("reject", reject))
    app.add_handler(CommandHandler("payment_methods", payment_methods))
    app.add_handler(CommandHandler("add_payment_method", add_payment_method))
    app.add_handler(CommandHandler("delete_payment_method", delete_payment_method))
    app.add_handler(CommandHandler("show_deposits", show_deposits))
    app.add_handler(CommandHandler("approve_deposit", approve_deposit))
    app.add_handler(CommandHandler("reject_deposit", reject_deposit))
    app.add_handler(CommandHandler("show_pending_tasks", show_pending_tasks))
    app.add_handler(CommandHandler("approve_task", approve_task_cmd))
    
    # Fix: Hook explicitly registered to address the NameError/SyntaxError bugs safely
    app.add_handler(CallbackQueryHandler(handle_force_join_callback, pattern=r'^check_force_join_gate$'))
    app.add_handler(CallbackQueryHandler(handle_wizard_callbacks, pattern=r'^wz_'))
    app.add_handler(CallbackQueryHandler(handle_browse_callbacks, pattern=r'^br_'))
    app.add_handler(CallbackQueryHandler(handle_browse_finances_and_tickets_callbacks, pattern=r'^(dp_|supp_|admin_nav_|ad_bal_|ad_user_|user_n)'))
    app.add_handler(CallbackQueryHandler(handle_admin_review_callbacks, pattern=r'^ad_'))
    app.add_handler(CallbackQueryHandler(handle_redirect_job_callback, pattern=r'^redirect_job_'))
    
    app.add_handler(MessageHandler(filters.Regex(r'^\/(view_task_|submit_proof_|manage_task_|view_sub_|approve_sub_|reject_sub_|final_approve_sub_|final_reject_sub_)\d+'), handle_regex_routing))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, buttons))

    print("BD94 Enterprise Grade Architectural Platform Online Hub Successfully Booted.")
    app.run_polling()

if __name__ == "__main__":
    main()