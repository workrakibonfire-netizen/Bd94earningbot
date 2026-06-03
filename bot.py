import os
import sqlite3
import logging
import datetime
import http.server
import socketserver
import threading
import asyncio
import json
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
# SYSTEM MINIMUM REWARD RATES CONFIGURATION
# =====================================================================
MIN_RATES = {
    "Telegram": {
        "Join Group": 2,
        "Join Channel": 2,
        "Join Bot": 3,
        "Gleam Offer": 3
    },
    "YouTube": {
        "Subscribe": 3,
        "Comment": 2,
        "Watch Video (1-5 Minutes)": 3,
        "Watch Video (1-10 Minutes)": 5
    },
    "Facebook": {
        "Profile Follow": 3,
        "Page Follow": 3,
        "Join Group": 3,
        "Watch Video": 4,
        "New Facebook Account": 8
    },
    "TikTok": {
        "Follow": 3,
        "Watch + Like + Comment + Share": 3
    },
    "Gmail Account": {
        "New Gmail Account": 8,
        "Old Gmail Account": 10
    },
    "Mobile Apps": {
        "Download Only": 5,
        "Download + Create Account": 10
    },
    "Survey": {
        "Up To 10 Questions": 8
    },
    "Sign Up": {
        "Simple Sign Up": 6,
        "Complex Sign Up": 10
    }
}

# =====================================================================
# SQLITE CONCURRENCY & TRANSACTION CONTEXT MANAGER
# =====================================================================
@contextmanager
def db_transaction():
    conn = sqlite3.connect(DATABASE, check_same_thread=False, timeout=30.0)
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
# DATABASE SCHEMA INITIALIZATION & MIGRATIONS
# =====================================================================
def init_db():
    with sqlite3.connect(DATABASE) as conn:
        cursor = conn.cursor()
        
        # users table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            balance INTEGER DEFAULT 0,
            referrals INTEGER DEFAULT 0,
            pending_reward INTEGER DEFAULT 0,
            earned_reward INTEGER DEFAULT 0,
            referrer_id INTEGER DEFAULT 0,
            deposit_balance INTEGER DEFAULT 0,
            earnings_balance INTEGER DEFAULT 0,
            pending_balance INTEGER DEFAULT 0
        )""")
        
        cursor.execute("PRAGMA table_info(users)")
        columns = [col[1] for col in cursor.fetchall()]
        for col_name in ["deposit_balance", "earnings_balance", "pending_balance"]:
            if col_name not in columns:
                cursor.execute(f"ALTER TABLE users ADD COLUMN {col_name} INTEGER DEFAULT 0")
                
        # withdrawals table
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
        
        # payment_methods table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS payment_methods (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            method_name TEXT,
            account_number TEXT,
            payment_type TEXT,
            transaction_required INTEGER DEFAULT 1,
            screenshot_required INTEGER DEFAULT 1,
            status TEXT DEFAULT 'active'
        )""")
        
        # deposits table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS deposits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount INTEGER,
            method_id INTEGER,
            transaction_id TEXT UNIQUE,
            screenshot_file_id TEXT,
            status TEXT DEFAULT 'pending',
            admin_note TEXT,
            created_at TEXT
        )""")
        
        cursor.execute("PRAGMA table_info(deposits)")
        dep_columns = [col[1] for col in cursor.fetchall()]
        if "screenshot_file_id" not in dep_columns:
            cursor.execute("ALTER TABLE deposits ADD COLUMN screenshot_file_id TEXT")
        
        # tasks table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            creator_id INTEGER,
            title TEXT,
            description TEXT,
            proof_requirements TEXT,
            reward_amount INTEGER,
            total_slots INTEGER,
            filled_slots INTEGER DEFAULT 0,
            total_budget INTEGER,
            status TEXT DEFAULT 'active',
            created_at TEXT,
            category TEXT,
            task_type TEXT,
            tutorial_image TEXT,
            time_limit TEXT,
            expires_at TEXT
        )""")
        
        cursor.execute("PRAGMA table_info(tasks)")
        task_cols = [col[1] for col in cursor.fetchall()]
        migrations = {
            "category": "TEXT",
            "task_type": "TEXT",
            "tutorial_image": "TEXT",
            "time_limit": "TEXT",
            "expires_at": "TEXT"
        }
        for field, f_type in migrations.items():
            if field not in task_cols:
                cursor.execute(f"ALTER TABLE tasks ADD COLUMN {field} {f_type}")
        
        # task_submissions table
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
        
        # wallet_transactions table
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
        
        # notifications table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            message TEXT,
            is_read INTEGER DEFAULT 0,
            created_at TEXT
        )""")
        
        # daily_bonus_claims table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS daily_bonus_claims (
            user_id INTEGER,
            claim_date TEXT,
            PRIMARY KEY(user_id, claim_date)
        )""")
        conn.commit()

# =====================================================================
# AUTOMATIC BACKGROUND EXPIRATION ENGINE
# =====================================================================
def check_and_expire_tasks(conn=None):
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    should_close = False
    if conn is None:
        conn = sqlite3.connect(DATABASE, timeout=20.0)
        should_close = True
        
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, creator_id, reward_amount, total_slots, filled_slots, total_budget 
            FROM tasks WHERE status = 'active' AND expires_at <= ?
        """, (now_str,))
        expired_jobs = cursor.fetchall()
        
        for job in expired_jobs:
            task_id, creator_id, reward_amount, total_slots, filled_slots, total_budget = job
            unused_slots = total_slots - filled_slots
            
            cursor.execute("UPDATE tasks SET status = 'expired' WHERE id = ?", (task_id,))
            
            if unused_slots > 0:
                refund_amount = int(unused_slots * reward_amount * 1.1)
                cursor.execute("UPDATE users SET deposit_balance = deposit_balance + ? WHERE user_id = ?", (refund_amount, creator_id))
                
                cursor.execute("""
                    INSERT INTO wallet_transactions (user_id, amount, balance_type, action_type, reference_id, created_at)
                    VALUES (?, ?, 'deposit_balance', 'Task Expired Refund', ?, ?)
                """, (creator_id, refund_amount, str(task_id), now_str))
                
                logger.info(f"Task #{task_id} EXPIRED. Refunded {refund_amount} Tk to creator {creator_id}.")
    except Exception as e:
        logger.error(f"Error executing task expiration engine loops: {e}")
    finally:
        if should_close:
            conn.commit()
            conn.close()

# =====================================================================
# RENDER KEEP-ALIVE HTTP INFRASTRUCTURE
# =====================================================================
def run_web_server():
    class HealthHandler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header('Content-type', 'text/plain; charset=utf-8')
            self.end_headers()
            self.wfile.write(b"OK - BD94 Core Engines Active")
        def log_message(self, format, *args):
            return

    port = int(os.getenv("PORT", "3000"))
    socketserver.TCPServer.allow_reuse_address = True
    try:
        with socketserver.TCPServer(("0.0.0.0", port), HealthHandler) as server:
            logger.info(f"Starting keep-alive server on port {port}")
            server.serve_forever()
    except Exception as e:
        logger.error(f"Keep-Alive daemon failed: {e}")

# =====================================================================
# CORE UTILITIES
# =====================================================================
def save_user(user_id, referrer_id=0):
    with db_transaction() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
        if cursor.fetchone() is None:
            cursor.execute("""
                INSERT INTO users (user_id, balance, referrals, pending_reward, earned_reward, referrer_id, deposit_balance, earnings_balance, pending_balance)
                VALUES (?, 0, 0, 0, 0, ?, 0, 0, 0)
            """, (user_id, referrer_id))
            if referrer_id != 0:
                cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (referrer_id,))
                if cursor.fetchone():
                    cursor.execute("""
                        UPDATE users 
                        SET referrals = referrals + 1, pending_reward = pending_reward + 20 
                        WHERE user_id = ?
                    """, (referrer_id,))

def add_wallet_transaction(user_id, amount, balance_type, action_type, reference_id=""):
    with db_transaction() as conn:
        created_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute("""
            INSERT INTO wallet_transactions (user_id, amount, balance_type, action_type, reference_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (user_id, amount, balance_type, action_type, str(reference_id), created_at))

# =====================================================================
# FORCE JOIN VALIDATION SYSTEM SECURITY GATEWAYS
# =====================================================================
def get_force_join_keyboard():
    keyboard = [
        [InlineKeyboardButton("🚀 চ্যানেলে যোগ দিন", url="https://t.me/bd94earning")],
        [InlineKeyboardButton("✅ আমি জয়েন করেছি", callback_data="check_force_join")]
    ]
    return InlineKeyboardMarkup(keyboard)

async def send_force_join_screen(update: Update, context: ContextTypes.DEFAULT_TYPE, is_retry=False):
    text = (
        "❌ আপনি এখনও চ্যানেলে যোগ দেননি।\n\n"
        "প্রথমে চ্যানেলে Join করুন তারপর আবার \"আমি জয়েন করেছি\" বাটনে চাপ দিন।"
    ) if is_retry else (
        "📢 বট ব্যবহার করার আগে আমাদের অফিসিয়াল চ্যানেলে যোগ দিন।\n\n"
        "🎁 চ্যানেলে নিয়মিত নতুন কাজ, আপডেট এবং বোনাস দেওয়া হয়।"
    )
    if update.callback_query:
        await update.callback_query.message.reply_text(text, reply_markup=get_force_join_keyboard())
    elif update.message:
        await update.message.reply_text(text, reply_markup=get_force_join_keyboard())

async def check_membership_gated(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user_id = update.effective_user.id
    if user_id == ADMIN_ID:
        return True
    if context.user_data.get("is_verified"):
        return True
        
    try:
        member = await context.bot.get_chat_member(chat_id="@bd94earning", user_id=user_id)
        if member.status in ["member", "administrator", "creator"]:
            context.user_data["is_verified"] = True
            return True
        else:
            await send_force_join_screen(update, context)
            return False
    except Exception as e:
        logger.warning(f"Force Join check configuration alert (Bot might not be admin in channel): {e}")
        # Fallback message requirement mapping safely
        fallback_msg = "⚠️ আমাদের অফিসিয়াল চ্যানেল ভেরিফিকেশন সিস্টেমে সাময়িক কারিগরি সমস্যা হচ্ছে। অনুগ্রহ করে কিছুক্ষণ পর চেষ্টা করুন।"
        if update.callback_query:
            await update.callback_query.message.reply_text(fallback_msg)
        else:
            await update.message.reply_text(fallback_msg)
        return False

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
        logger.warning(f"Inline hook validation mapping protection alert: {e}")
    await query.message.reply_text("📢 বট ব্যবহার করার আগে আমাদের অফিসিয়াল চ্যানেলে যোগ দিন: @bd94earning")
    return False

async def process_welcome_access(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = (
        "🎉 BD94 Earning Bot এ স্বাগতম\n\n"
        "💰 Deposit করে আয় শুরু করুন\n"
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
# CORE TELEGRAM HANDLERS
# =====================================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    check_and_expire_tasks()
    
    if referrer_id != 0:
        try:
            await context.bot.send_message(
                chat_id=referrer_id,
                text="🎉 আপনার রেফারেল লিংকের মাধ্যমে একজন নতুন মেম্বার জয়েন করেছেন!\n💰 পেন্ডিং রিওয়ার্ড: +২০ টাকা"
            )
        except Exception:
            pass

    # Gated Force Join Layer Verification on Start
    if user_id != ADMIN_ID and not context.user_data.get("is_verified"):
        try:
            member = await context.bot.get_chat_member(chat_id="@bd94earning", user_id=user_id)
            if member.status in ["member", "administrator", "creator"]:
                context.user_data["is_verified"] = True
            else:
                await send_force_join_screen(update, context)
                return
        except Exception as e:
            logger.warning(f"Force Join check failure on start handler command: {e}")
            await update.message.reply_text("⚠️ আমাদের অফিসিয়াল চ্যানেল ভেরিফিকেশন সিস্টেমে সাময়িক কারিগরি সমস্যা হচ্ছে। অনুগ্রহ করে কিছুক্ষণ পর চেষ্টা করুন।")
            return
            
    await process_welcome_access(update, context)

async def show_main_menu(update: Update, msg_text: str):
    keyboard = [
        ["📊 Dashboard", "📝 Tasks"],
        ["💳 Wallet", "👤 Profile"],
        ["👥 Referral", "📞 Support"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
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

async def show_withdraw_amounts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["withdraw_step"] = "step_1"
    keyboard = [
        ["150 Tk", "300 Tk"],
        ["500 Tk", "1000 Tk"],
        ["🔙 Back"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text("💳 উইথড্র করার পরিমাণ নির্বাচন করুন:", reply_markup=reply_markup)

async def show_tasks_menu(update: Update, msg_text: str):
    keyboard = [
        ["🔍 Find Jobs", "➕ Create Job"],
        ["📌 My Posted Tasks", "📌 My Submitted Tasks"],
        ["🧧 Daily Bonus", "🔙 Back"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(msg_text, reply_markup=reply_markup)

# =====================================================================
# ADMIN PANEL HANDLERS
# =====================================================================
async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Access Denied!")
        return
    await update.message.reply_text(
        "👑 BD94 Admin Control Dashboard\n\n"
        "/stats - Real-time statistics counters\n"
        "/broadcast <message> - Global announcement push\n"
        "/show_pending - View all pending worker payout requests\n"
        "/show_withdraws - Audit listing of last 20 payout entries\n\n"
        "⚙️ Gateway Management:\n"
        "/payment_methods - View configurations\n"
        "/add_payment_method Name|Number|Type\n"
        "/delete_payment_method <id>\n\n"
        "💵 Deposit Audits:\n"
        "/show_deposits - Audit listings of pending deposits with captures\n"
        "/approve_deposit <id> - Approve funding allocation\n"
        "/reject_deposit <id> <reason> - Void deposit ticket"
    )

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Access Denied!")
        return
    check_and_expire_tasks()
    with sqlite3.connect(DATABASE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM users")
        total_users = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM withdrawals")
        total_withdrawals = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM withdrawals WHERE status='pending'")
        pending_withdrawals = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM deposits WHERE status='pending'")
        pending_deposits = cursor.fetchone()[0]
    await update.message.reply_text(
        f"📊 BD94 Real-Time Statistics:\n\n"
        f"👥 Total Users: {total_users}\n"
        f"💳 Total Withdrawals Counter: {total_withdrawals}\n"
        f"⏳ Pending Payout Audits: {pending_withdrawals}\n"
        f"📥 Pending Funding Approvals: {pending_deposits}"
    )

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Access Denied!")
        return
    if not context.args:
        await update.message.reply_text("ব্যবহার নিয়ম: /broadcast আপনার বার্তা")
        return
    message = "📢 গ্লোবাল অ্যানাউন্সমেন্ট:\n\n" + " ".join(context.args)
    with sqlite3.connect(DATABASE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM users")
        rows = cursor.fetchall()
    sent = 0
    for r in rows:
        try:
            await context.bot.send_message(chat_id=r[0], text=message)
            sent += 1
            await asyncio.sleep(0.05)
        except Exception:
            pass
    await update.message.reply_text(f"✅ সফলভাবে {sent} জন ইউজারের কাছে নোটিফিকেশন ব্রডকাস্ট করা হয়েছে।")

async def show_pending(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Access Denied!")
        return
    with sqlite3.connect(DATABASE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, user_id, amount, method, number, created_at FROM withdrawals WHERE status='pending' ORDER BY id ASC")
        rows = cursor.fetchall()
    if not rows:
        await update.message.reply_text("📥 No pending withdrawal requests.")
        return
    text = "📥 Pending Worker Payout Requests:\n\n"
    for r in rows:
        text += f"Request #{r[0]}\n👤 User ID: {r[1]}\n💰 Payout Amount: {r[2]} Tk\n📱 Gateway Method: {r[3]}\n📞 Account Reference line: {r[4]}\n📅 Date Logs: {r[5]}\n👉 Approve: /approve {r[0]}\n👉 Reject: /reject {r[0]} Reason\n------------------------\n"
    await update.message.reply_text(text)

async def show_withdraws(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Access Denied!")
        return
    with sqlite3.connect(DATABASE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, user_id, amount, method, status FROM withdrawals ORDER BY id DESC LIMIT 20")
        rows = cursor.fetchall()
    if not rows:
        await update.message.reply_text("📜 No withdrawals record found.")
        return
    text = "📜 Recent Withdrawals List (Max 20 Entries):\n\n"
    for r in rows:
        status_emoji = "⏳" if r[4] == "pending" else "✅" if r[4] == "approved" else "❌"
        text += f"#{r[0]} | User ID: {r[1]} | {r[2]} Tk | {r[3]} | {status_emoji} {r[4]}\n"
    await update.message.reply_text(text)

async def approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Access Denied!")
        return
    if not context.args:
        await update.message.reply_text("ব্যবহার নিয়ম: /approve <request_id>")
        return
    try:
        req_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ ID অবশ্যই একটি সংখ্যা হতে হবে!")
        return

    try:
        with db_transaction() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT user_id, amount, status, method, number FROM withdrawals WHERE id = ?", (req_id,))
            row = cursor.fetchone()
            if not row:
                await update.message.reply_text("❌ এই Request ID খুঁজে পাওয়া যায়নি!")
                return
            user_id, amount, status, method, number = row
            if status != "pending":
                await update.message.reply_text(f"❌ রিকোয়েস্টটি ইতিপূর্বে {status} করা হয়েছে!")
                return

            cursor.execute("UPDATE withdrawals SET status = 'approved' WHERE id = ?", (req_id,))
            
            cursor.execute("SELECT COUNT(*) FROM withdrawals WHERE user_id = ? AND status = 'approved' AND id != ?", (user_id, req_id))
            prev_approved = cursor.fetchone()[0]

            if prev_approved == 0:
                cursor.execute("SELECT referrer_id FROM users WHERE user_id = ?", (user_id,))
                ref_row = cursor.fetchone()
                if ref_row and ref_row[0] != 0:
                    referrer_id = ref_row[0]
                    cursor.execute("""
                        UPDATE users 
                        SET balance = balance + 20,
                            earnings_balance = earnings_balance + 20,
                            earned_reward = earned_reward + 20,
                            pending_reward = CASE WHEN pending_reward >= 20 THEN pending_reward - 20 ELSE 0 END
                        WHERE user_id = ?
                    """, (referrer_id,))
                    
                    conn.execute("""
                        INSERT INTO wallet_transactions (user_id, amount, balance_type, action_type, reference_id, created_at)
                        VALUES (?, 20, 'earnings_balance', 'Referral Reward', ?, ?)
                    """, (referrer_id, f"Ref-{user_id}", datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")))

            conn.execute("""
                INSERT INTO wallet_transactions (user_id, amount, balance_type, action_type, reference_id, created_at)
                VALUES (?, ?, 'earnings_balance', 'Withdrawal Approved', ?, ?)
            """, (user_id, -amount, str(req_id), datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")))

        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"✅ উইথড্রাল রিকোয়েস্ট অ্যাপ্রুভড!\n\nআপনার #{req_id} নম্বর উইথড্রাল রিকোয়েস্টটি সফলভাবে সম্পন্ন হয়েছে।\n💰 পরিমাণ: {amount} Tk\n📱 মেথড: {method}"
            )
        except Exception:
            pass
        await update.message.reply_text(f"✅ Payout request reference #{req_id} marked as fully approved.")
    except Exception as e:
        logger.error(f"Error executing approve payout execution: {e}")
        await update.message.reply_text("❌ Verification tracking operation failed safely under concurrency lock.")

async def reject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Access Denied!")
        return
    if len(context.args) < 2:
        await update.message.reply_text("ব্যবহার নিয়ম: /reject <request_id> <reason>")
        return
    try:
        req_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ ID অবশ্যই একটি সংখ্যা হতে হবে!")
        return
    reason = " ".join(context.args[1:])

    try:
        with db_transaction() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT user_id, amount, status FROM withdrawals WHERE id = ?", (req_id,))
            row = cursor.fetchone()
            if not row:
                await update.message.reply_text("❌ এই Request ID খুঁজে পাওয়া যায়নি!")
                return
            user_id, amount, status = row
            if status != "pending":
                await update.message.reply_text(f"❌ রিকোয়েস্টটি ইতিপূর্বে {status} করা হয়েছে!")
                return

            cursor.execute("UPDATE withdrawals SET status = 'rejected', admin_note = ? WHERE id = ?", (reason, req_id))
            cursor.execute("UPDATE users SET balance = balance + ?, earnings_balance = earnings_balance + ? WHERE user_id = ?", (amount, amount, user_id))
            
            conn.execute("""
                INSERT INTO wallet_transactions (user_id, amount, balance_type, action_type, reference_id, created_at)
                VALUES (?, ?, 'earnings_balance', 'Withdrawal Rejected', ?, ?)
            """, (user_id, amount, str(req_id), datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")))

        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"❌ উইথড্রাল রিকোয়েস্ট বাতিল করা হয়েছে!\n\nঅনুরোধ আইডি: #{req_id}\n💬 কারণ: {reason}\n💰 আপনার উইথড্রকৃত {amount} Tk ওয়ালেটে রিফান্ড করা হয়েছে।"
            )
        except Exception:
            pass
        await update.message.reply_text(f"❌ Request #{req_id} rejected cleanly, funds returned atomically.")
    except Exception as e:
        logger.error(f"Error in execution of reject withdrawal payload: {e}")
        await update.message.reply_text("❌ Payout cancellation failed.")

# =====================================================================
# PAYMENT CONFIGURATION PATHS
# =====================================================================
async def payment_methods(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Access Denied!")
        return
    with sqlite3.connect(DATABASE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, method_name, account_number, payment_type, status FROM payment_methods")
        rows = cursor.fetchall()
    if not rows:
        await update.message.reply_text("📱 কোনো পেমেন্ট মেথড কনফিগার করা নেই।")
        return
    text = "📱 active Gateways Configurations:\n\n"
    for r in rows:
        text += f"ID: {r[0]} | {r[1]} ({r[3]}) | No: {r[2]} | Status: {r[4]}\n"
    await update.message.reply_text(text)

async def add_payment_method(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Access Denied!")
        return
    raw_text = " ".join(context.args)
    if "|" not in raw_text:
        await update.message.reply_text("নিয়ম: /add_payment_method Name|Number|Type")
        return
    data = raw_text.split("|")
    if len(data) < 3:
        await update.message.reply_text("❌ Invalid fields count structure configuration.")
        return
    name, number, p_type = data[0].strip(), data[1].strip(), data[2].strip()
    with db_transaction() as conn:
        conn.execute(
            "INSERT INTO payment_methods (method_name, account_number, payment_type) VALUES (?, ?, ?)",
            (name, number, p_type)
        )
    await update.message.reply_text(f"✅ গেটওয়ে চ্যানেল '{name}' সফলভাবে যুক্ত করা হয়েছে।")

async def delete_payment_method(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Access Denied!")
        return
    if not context.args:
        await update.message.reply_text("নিয়ম: /delete_payment_method <id>")
        return
    try:
        m_id = int(context.args[0])
    except ValueError:
        return
    with db_transaction() as conn:
        conn.execute("DELETE FROM payment_methods WHERE id = ?", (m_id,))
    await update.message.reply_text(f"🗑️ পেমেন্ট গেটওয়ে আইডি #{m_id} রিমুভ করা হয়েছে।")

# =====================================================================
# AUDITED DEPOSIT AUDIT DISPATCH ENGINE
# =====================================================================
async def show_deposits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Access Denied!")
        return
        
    with sqlite3.connect(DATABASE) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT d.id, d.user_id, d.amount, m.method_name, d.transaction_id, d.status, d.created_at, d.screenshot_file_id 
            FROM deposits d JOIN payment_methods m ON d.method_id = m.id 
            WHERE d.status='pending' ORDER BY d.id DESC
        """)
        rows = cursor.fetchall()
        
    if not rows:
        await update.message.reply_text("📥 No pending funding deposit tickets available.")
        return
        
    await update.message.reply_text(f"📊 সর্বমোট {len(rows)} টি ডিপোজিট রিকোয়েস্ট রিভিউ এর অপেক্ষায় রয়েছে (Newest First):")
    
    for r in rows:
        caption_text = (
            f"📥 Pending Deposit Audit Ticket\n\n"
            f"Deposit ID: #{r[0]}\n"
            f"User ID: {r[1]}\n"
            f"Amount: {r[2]} Tk\n"
            f"Method: {r[3]}\n"
            f"TxID: {r[4]}\n"
            f"Status: {r[5]}\n"
            f"Date Logs: {r[6]}\n\n"
            f"👉 Approve: /approve_deposit {r[0]}\n"
            f"👉 Reject: /reject_deposit {r[0]} Reason"
        )
        if r[7]:
            try:
                await context.bot.send_photo(chat_id=ADMIN_ID, photo=r[7], caption=caption_text)
            except Exception:
                await update.message.reply_text(caption_text + "\n\n⚠️ Screenshot asset lookup failure on server layers.")
        else:
            await update.message.reply_text(caption_text + "\n\n⚠️ Warning: No screenshot capture asset logged on this ticket.")

async def approve_deposit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Access Denied!")
        return
    if not context.args:
        await update.message.reply_text("নিয়ম: /approve_deposit <deposit_id>")
        return
    try:
        dep_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ ID structure parsing allocation exception.")
        return

    try:
        with db_transaction() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT user_id, amount, status FROM deposits WHERE id = ?", (dep_id,))
            row = cursor.fetchone()
            if not row:
                await update.message.reply_text("❌ Deposit ticket ID reference mismatch.")
                return
            user_id, amount, status = row
            if status != "pending":
                await update.message.reply_text(f"❌ Security override protection block: Ticket already processed. Status: {status}")
                return
            
            cursor.execute("UPDATE deposits SET status = 'approved' WHERE id = ?", (dep_id,))
            cursor.execute("UPDATE users SET deposit_balance = deposit_balance + ? WHERE user_id = ?", (amount, user_id))
            
            conn.execute("""
                INSERT INTO wallet_transactions (user_id, amount, balance_type, action_type, reference_id, created_at)
                VALUES (?, ?, 'deposit_balance', 'Deposit Approved', ?, ?)
            """, (user_id, amount, str(dep_id), datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            
        logger.info(f"Deposit ticket #{dep_id} APPROVED. {amount} Tk loaded to user {user_id} deposit balance registry.")
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"✅ ডিপোজিট সফলভাবে অ্যাপ্রুভ করা হয়েছে!\n\nডিপোজিট আইডি: #{dep_id}\n💰 পরিমাণ: {amount} Tk MNIST আপনার Deposit Balance এ যুক্ত করা হয়েছে যা দিয়ে আপনি কাজ পোস্ট করতে পারবেন।"
            )
        except Exception:
            pass
        await update.message.reply_text(f"✅ Deposit Request reference ticket #{dep_id} marked as fully approved.")
    except Exception as e:
        logger.error(f"Error inside approve deposit workflow layer: {e}")
        await update.message.reply_text("❌ Processing pipeline transaction lock exclusion failure.")

async def reject_deposit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Access Denied!")
        return
    if len(context.args) < 2:
        await update.message.reply_text("নিয়ম: /reject_deposit <deposit_id> <reason>")
        return
    try:
        dep_id = int(context.args[0])
    except ValueError:
        return
    reason = " ".join(context.args[1:])
    try:
        with db_transaction() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT user_id, amount, status FROM deposits WHERE id = ?", (dep_id,))
            row = cursor.fetchone()
            if not row:
                await update.message.reply_text("❌ Deposit ticket lookup error.")
                return
            user_id, amount, status = row
            if status != "pending":
                await update.message.reply_text("❌ Ticket is not pending review.")
                return
            cursor.execute("UPDATE deposits SET status = 'rejected', admin_note = ? WHERE id = ?", (reason, dep_id))
            logger.info(f"Deposit #{dep_id} REJECTED for profile {user_id}. Reason: {reason}")
            
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"❌ আপনার ডিপোজিট রিকোয়েস্টটি রিজেক্ট করা হয়েছে!\n\nআইডি: #{dep_id}\n💬 কারণ: {reason}"
            )
        except Exception:
            pass
        await update.message.reply_text(f"❌ Deposit target index ticket #{dep_id} flagged as rejected safely.")
    except Exception as e:
        logger.error(f"Error in reject deposit workflow: {e}")

# =====================================================================
# SYSTEM CORE MESSAGE TEXT PATTERNS ROUTER
# =====================================================================
async def handle_regex_routing(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_membership_gated(update, context):
        return
    text = update.message.text.strip()
    check_and_expire_tasks()
    
    if text.startswith("/view_task_"):
        await view_task_handler(update, context)
    elif text.startswith("/submit_proof_"):
        await submit_proof_start(update, context)
    elif text.startswith("/manage_task_"):
        await manage_task_handler(update, context)
    elif text.startswith("/view_sub_"):
        await view_submission_handler(update, context)
    elif text.startswith("/approve_sub_"):
        await approve_submission_cmd(update, context)
    elif text.startswith("/reject_sub_"):
        await reject_submission_cmd(update, context)

# =====================================================================
# REDESIGN: FIND JOBS NESTED BROWSING CATEGORY & PAGINATION ENGINE
# =====================================================================
async def find_jobs_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    counts = {cat: 0 for cat in MIN_RATES.keys()}
    with sqlite3.connect(DATABASE) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT category, COUNT(*) FROM tasks 
            WHERE status = 'active' AND expires_at > ? AND filled_slots < total_slots AND creator_id != ?
            GROUP BY category
        """, (now_str, user_id))
        for cat, cnt in cursor.fetchall():
            if cat in counts:
                counts[cat] = cnt

    summary_text = (
        f"🔍 **সব উপলব্ধ কাজসমূহ (Find Jobs Hub)**\n\n"
        f"📢 Telegram Jobs ({counts['Telegram']})\n"
        f"▶️ YouTube Jobs ({counts['YouTube']})\n"
        f"📘 Facebook Jobs ({counts['Facebook']})\n"
        f"🎵 TikTok Jobs ({counts['TikTok']})\n"
        f"📧 Gmail Jobs ({counts['Gmail Account']})\n"
        f"📱 Mobile Apps Jobs ({counts['Mobile Apps']})\n"
        f"📊 Survey Jobs ({counts['Survey']})\n"
        f"📝 Sign Up Jobs ({counts['Sign Up']})\n\n"
        f"👇 কাজের ক্যাটাগরি নির্বাচন করুন:"
    )

    keyboard = [
        [InlineKeyboardButton("📢 Telegram", callback_data="browse_cat_Telegram"), InlineKeyboardButton("▶️ YouTube", callback_data="browse_cat_YouTube")],
        [InlineKeyboardButton("📘 Facebook", callback_data="browse_cat_Facebook"), InlineKeyboardButton("🎵 TikTok", callback_data="browse_cat_TikTok")],
        [InlineKeyboardButton("📧 Gmail", callback_data="browse_cat_Gmail Account"), InlineKeyboardButton("📱 Mobile Apps", callback_data="browse_cat_Mobile Apps")],
        [InlineKeyboardButton("📊 Survey", callback_data="browse_cat_Survey"), InlineKeyboardButton("📝 Sign Up", callback_data="browse_cat_Sign Up")]
    ]
    
    if update.callback_query:
        await update.callback_query.message.edit_text(summary_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    else:
        await update.message.reply_text(summary_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def handle_browse_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not await is_verified_inline(query, context):
        return
        
    await query.answer()
    data = query.data
    user_id = query.from_user.id
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    check_and_expire_tasks()

    if data == "browse_back_cats":
        await find_jobs_start(update, context)
        return

    if data.startswith("browse_cat_"):
        cat = data.replace("browse_cat_", "").strip()
        task_types = MIN_RATES.get(cat, {})
        type_counts = {t: 0 for t in task_types.keys()}
        
        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT task_type, COUNT(*) FROM tasks 
                WHERE category = ? AND status = 'active' AND expires_at > ? AND filled_slots < total_slots AND creator_id != ?
                GROUP BY task_type
            """, (cat, now_str, user_id))
            for t_type, cnt in cursor.fetchall():
                if t_type in type_counts:
                    type_counts[t_type] = cnt
                    
        text_out = f"📁 ক্যাটাগরি: **{cat}**\n\n👇 কাজের সাব-টাইপ নির্বাচন করুন (টাস্ক সংখ্যা সহ):"
        keyboard = []
        for t_type, cnt in type_counts.items():
            keyboard.append([InlineKeyboardButton(f"{t_type} ({cnt})", callback_data=f"browse_type_{cat}||{t_type}")])
        keyboard.append([InlineKeyboardButton("🔙 প্রধান মেনু", callback_data="browse_back_cats")])
        
        await query.message.edit_text(text_out, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        return

    elif data.startswith("browse_type_") or data.startswith("browse_page_"):
        if data.startswith("browse_type_"):
            parts = data.replace("browse_type_", "").split("||")
            cat = parts[0]
            t_type = parts[1]
            page = 1
        else:
            parts = data.replace("browse_page_", "").split("||")
            cat = parts[0]
            t_type = parts[1]
            page = int(parts[2])
            
        limit = 5
        offset = (page - 1) * limit
        
        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COUNT(*) FROM tasks 
                WHERE category = ? AND task_type = ? AND status = 'active' AND expires_at > ? AND filled_slots < total_slots AND creator_id != ?
            """, (cat, t_type, now_str, user_id))
            total_tasks = cursor.fetchone()[0]
            
            cursor.execute("""
                SELECT id, title, reward_amount, total_slots, filled_slots, description, expires_at FROM tasks 
                WHERE category = ? AND task_type = ? AND status = 'active' AND expires_at > ? AND filled_slots < total_slots AND creator_id != ?
                ORDER BY id DESC LIMIT ? OFFSET ?
            """, (cat, t_type, now_str, user_id, limit, offset))
            tasks_list = cursor.fetchall()
            
        if not tasks_list:
            await query.message.edit_text(
                f"❌ এই মুহূর্তে **{t_type}** এর অধীনে কোনো সক্রিয় কাজ নেই।", 
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে যান", callback_data=f"browse_cat_{cat}")]])
            )
            return
            
        text_out = f"🔍 **উপলব্ধ কাজের তালিকা ({t_type}) - পেজ {page}**\n\n"
        for tk in tasks_list:
            t_id, title, reward, total_s, filled_s, desc, exp_at = tk
            slots_left = total_s - filled_s
            
            try:
                exp_dt = datetime.datetime.strptime(exp_at, "%Y-%m-%d %H:%M:%S")
                delta = exp_dt - datetime.datetime.now()
                hours_left = max(0, int(delta.total_seconds() / 3600))
                time_str = f"{hours_left} ঘণ্টা" if hours_left > 0 else "কিছু সময়"
            except Exception:
                time_str = "নির্দিষ্ট সময়"
                
            short_desc = desc[:60] + "..." if len(desc) > 60 else desc
            
            text_out += f"🆔 কাজ ওপেন করুন: /view_task_{t_id}\n" \
                        f"💎 শিরোনাম: **{title}**\n" \
                        f"💰 রিওয়ার্ড: {reward} Tk | 👥 বাকি স্লট: {slots_left} জন\n" \
                        f"⏰ অবশিষ্ট সময়: {time_str}\n" \
                        f"📝 সংক্ষিপ্ত বিবরণ: {short_desc}\n" \
                        f"------------------------\n"
                        
        nav_buttons = []
        if page > 1:
            nav_buttons.append(InlineKeyboardButton("⬅️ পূর্ববর্তী", callback_data=f"browse_page_{cat}||{t_type}||{page-1}"))
        if offset + limit < total_tasks:
            nav_buttons.append(InlineKeyboardButton("পরবর্তী ➡️", callback_data=f"browse_page_{cat}||{t_type}||{page+1}"))
            
        keyboard = []
        if nav_buttons:
            keyboard.append(nav_buttons)
        keyboard.append([InlineKeyboardButton("🔙 কাজের ধরণের তালিকা", callback_data=f"browse_cat_{cat}")])
        
        await query.message.edit_text(text_out, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        return

# =====================================================================
# AJERKAJ-STYLE MULTI-STEP INLINE DRIVEN WIZARD PROCESSING LOGIC 
# =====================================================================
async def start_job_wizard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    context.user_data["job_wizard"] = {"step": "CATEGORY", "proofs": []}
    
    categories = ["📢 Telegram", "▶️ YouTube", "📘 Facebook", "🎵 TikTok", "📧 Gmail Account", "📱 Mobile Apps", "📊 Survey", "📝 Sign Up"]
    keyboard = []
    row = []
    for cat in categories:
        row.append(InlineKeyboardButton(cat, callback_data=f"wiz_cat_{cat.split()[-1]}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
        
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("💼 **নতুন কাজ পোস্ট করার উইজার্ড (AjkerKaj-Style)**\n\n👇 প্রথমে নিচের ক্যাটাগরিগুলো থেকে আপনার কাজের সঠিক ক্যাটাগরি সিলেক্ট করুন:", reply_markup=reply_markup)

async def handle_wizard_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not await is_verified_inline(query, context):
        return
        
    await query.answer()
    data = query.data
    user_id = query.from_user.id
    
    wizard = context.user_data.get("job_wizard")
    if not wizard:
        await query.message.reply_text("❌ সেশন টাইমআউট বা রিসেট হয়েছে। দয়া করে নতুন করে কাজ পোস্ট করার বাটনটি চাপুন।")
        return

    if data.startswith("wiz_cat_"):
        cat_clean = data.replace("wiz_cat_", "").strip()
        mapping = {"Telegram": "Telegram", "YouTube": "YouTube", "Facebook": "Facebook", "TikTok": "TikTok", "Account": "Gmail Account", "Apps": "Mobile Apps", "Survey": "Survey", "Up": "Sign Up"}
        selected_cat = mapping.get(cat_clean, cat_clean)
        wizard["category"] = selected_cat
        wizard["step"] = "TASK_TYPE"
        
        types = list(MIN_RATES.get(selected_cat, {}).keys())
        keyboard = []
        for t in types:
            keyboard.append([InlineKeyboardButton(f"🔗 {t}", callback_data=f"wiz_type_{t[:20]}")])
            
        await query.message.edit_text(f"📁 ক্যাটাগরি: **{selected_cat}** নির্বাচন করা হয়েছে।\n\n👇 এবার এই ক্যাটাগরির অধীনে কাজের ধরণ বা সাব-টাইপ সিলেক্ট করুন:", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    elif data.startswith("wiz_type_"):
        type_prefix = data.replace("wiz_type_", "").strip()
        selected_cat = wizard.get("category")
        types = list(MIN_RATES.get(selected_cat, {}).keys())
        
        target_type = None
        for t in types:
            if t.startswith(type_prefix):
                target_type = t
                break
        if not target_type:
            target_type = types[0]
            
        wizard["task_type"] = target_type
        wizard["step"] = "TITLE"
        
        await query.message.delete()
        await context.bot.send_message(
            chat_id=user_id,
            text=f"📊 ক্যাটাগরি: {selected_cat} | সাব-টাইপ: **{target_type}**\n\n📝 **ধাপ ৩**: এবার আপনার কাজের একটি আকর্ষণীয় ও স্পষ্ট শিরোনাম (Title) লিখে মেসেজে টাইপ করে পাঠান:",
            reply_markup=ReplyKeyboardMarkup([["❌ Cancel"]], resize_keyboard=True)
        )
        return

    elif data.startswith("wiz_proof_"):
        p_type = data.replace("wiz_proof_", "").strip()
        current_proof_name = wizard.get("current_proof_name")
        
        wizard["proofs"].append({"name": current_proof_name, "type": p_type})
        
        keyboard = []
        if len(wizard["proofs"]) < 3:
            keyboard.append([InlineKeyboardButton("➕ আরও প্রুফ যোগ করুন", callback_data="wiz_action_moreproof")])
        keyboard.append([InlineKeyboardButton("➡️ পরবর্তী ধাপে যান", callback_data="wiz_action_nextimage")])
        
        await query.message.edit_text(
            f"✅ প্রুফ সফলভাবে সংরক্ষিত!\n📌 প্রুফ নম্বর #{len(wizard['proofs'])}: {current_proof_name} ({'টেক্সট প্রুফ' if p_type == 'text' else 'স্ক্রিনশট প্রুফ'})\n\n"
            f"👇 আপনি কি কাজের প্রমাণের জন্য আরও কোনো রিকোয়ারমেন্ট যোগ করতে চান? (সর্বোচ্চ ৩টি):",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    elif data == "wiz_action_moreproof":
        wizard["step"] = "PROOF_NAME"
        await query.message.delete()
        await context.bot.send_message(chat_id=user_id, text=f"📋 প্রুফ নম্বর #{len(wizard['proofs']) + 1} এর নাম লিখুন (যেমন: Username, Profile Link, Screenshot):", reply_markup=ReplyKeyboardMarkup([["❌ Cancel"]], resize_keyboard=True))
        return

    elif data == "wiz_action_nextimage":
        wizard["step"] = "TUTORIAL_IMAGE"
        await query.message.delete()
        keyboard = [[InlineKeyboardButton("⏭ Skip", callback_data="wiz_skip_image")]]
        await context.bot.send_message(chat_id=user_id, text="📷 **ধাপ ৬**: ওয়ার্কারদের কাজ বোঝানোর সুবিধার্থে কোনো টিউটোরিয়াল ছবি থাকলে তা আপলোড করুন। না থাকলে সরাসরি '⏭ Skip' বাটনে চাপুন:", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    elif data == "wiz_skip_image":
        wizard["tutorial_image"] = ""
        wizard["step"] = "WORKERS"
        await query.message.edit_text("👥 **ধাপ ७**: এই কাজটি সর্বমোট কতজন ওয়ার্কারকে দিয়ে করাতে চান তার সংখ্যা টাইপ করে লিখে পাঠান (নূন্যতম ১০ জন):")
        return

    elif data.startswith("wiz_time_"):
        days = data.replace("wiz_time_", "").strip()
        wizard["time_limit"] = f"{days} Days"
        wizard["step"] = "PREVIEW"
        
        cat = wizard.get("category")
        t_type = wizard.get("task_type")
        title = wizard.get("title")
        desc = wizard.get("description")
        workers = wizard.get("workers")
        
        default_rate = MIN_RATES.get(cat, {}).get(t_type, 2)
        wizard["reward_amount"] = default_rate
        
        subtotal = default_rate * workers
        fee = int(subtotal * 0.10)
        total_budget = subtotal + fee
        wizard["total_budget"] = total_budget
        
        proof_text_summary = ""
        for idx, p in enumerate(wizard["proofs"]):
            proof_text_summary += f"   {idx+1}. {p['name']} ({'📝 Text' if p['type']=='text' else '📸 Screenshot'})\n"
            
        preview_msg = (
            f"📊 **কাজের চূড়ান্ত রিভিউ ও ইনভয়েস (Preview Dashboard)**\n\n"
            f"📁 ক্যাটাগরি: {cat}\n"
            f"🔗 কাজের ধরণ: {t_type}\n"
            f"📌 শিরোনাম: {title}\n"
            f"📄 বিবরণ: {desc}\n"
            f"📋 প্রুফ রিকোয়ারমেন্টস:\n{proof_text_summary}"
            f"👥 মোট ওয়ার্কার স্লট: {workers} জন\n"
            f"💰 প্রতি ওয়ার্কার পেমেন্ট: {default_rate} Tk\n"
            f"📅 সময়সীমা: {days} দিন\n\n"
            f"💵 কাজের মোট বাজেট: {subtotal} Tk\n"
            f"⚡ প্ল্যাটফর্ম প্রসেসিং ফি (10%): {fee} Tk\n"
            f"💳 সর্বমোট প্রদেয় ব্যালেন্স: **{total_budget} Tk**\n\n"
            f"পোস্টটি নিশ্চিত করতে নিচের বাটনে চাপুন।"
        )
        
        keyboard = [
            [InlineKeyboardButton("✅ Publish Job", callback_data="wiz_action_publish")],
            [InlineKeyboardButton("❌ Cancel", callback_data="wiz_action_cancel")]
        ]
        await query.message.delete()
        
        if wizard.get("tutorial_image"):
            try:
                await context.bot.send_photo(chat_id=user_id, photo=wizard.get("tutorial_image"), caption=preview_msg, reply_markup=InlineKeyboardMarkup(keyboard))
                return
            except Exception: pass
        await context.bot.send_message(chat_id=user_id, text=preview_msg, reply_markup=InlineKeyboardMarkup(keyboard))
        return

    elif data == "wiz_action_publish":
        budget = wizard.get("total_budget")
        try:
            with db_transaction() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT deposit_balance FROM users WHERE user_id = ?", (user_id,))
                dep_balance = cursor.fetchone()[0] or 0
                
                if dep_balance < budget:
                    await context.bot.send_message(
                        chat_id=user_id,
                        text=f"❌ **দুঃখিত, আপনার পর্যাপ্ত ডিপোজিট ব্যালেন্স নেই!**\n\nপ্রয়োজনীয় বাজেট: {budget} Tk\nআপনার ব্যালেন্স: {dep_balance} Tk"
                    )
                    context.user_data.clear()
                    return
                    
                cursor.execute("UPDATE users SET deposit_balance = deposit_balance - ? WHERE user_id = ?", (budget, user_id))
                created_dt = datetime.datetime.now()
                created_str = created_dt.strftime("%Y-%m-%d %H:%M:%S")
                
                days_limit = int(wizard.get("time_limit").split()[0])
                expires_dt = created_dt + datetime.timedelta(days=days_limit)
                expires_str = expires_dt.strftime("%Y-%m-%d %H:%M:%S")
                
                proofs_json = json.dumps(wizard.get("proofs"))
                
                cursor.execute("""
                    INSERT INTO tasks (creator_id, title, description, proof_requirements, reward_amount, total_slots, filled_slots, total_budget, status, created_at, category, task_type, tutorial_image, time_limit, expires_at)
                    VALUES (?, ?, ?, ?, ?, ?, 0, ?, 'active', ?, ?, ?, ?, ?, ?)
                """, (user_id, wizard.get("title"), wizard.get("description"), proofs_json, wizard.get("reward_amount"), wizard.get("workers"), budget, created_str, wizard.get("category"), wizard.get("task_type"), wizard.get("tutorial_image"), wizard.get("time_limit"), expires_str))
                
                inserted_task_id = cursor.lastrowid
                conn.execute("""
                    INSERT INTO wallet_transactions (user_id, amount, balance_type, action_type, reference_id, created_at)
                    VALUES (?, ?, 'deposit_balance', 'Task Created', ?, ?)
                """, (user_id, -budget, str(inserted_task_id), created_str))
                
            context.user_data.clear()
            await show_tasks_menu(update, f"🎉 **অভিনন্দন! আপনার কাজটি সফলভাবে লাইভ পাবলিশ করা হয়েছে।**\n\n🆔 টাস্ক আইডি: #{inserted_task_id}")
        except Exception as e:
            logger.error(f"Critical error publishing task: {e}")
        return

    elif data == "wiz_action_cancel":
        context.user_data.clear()
        await query.message.delete()
        await show_main_menu(update, "❌ আপনার টাস্ক উইজার্ড সেশনটি বাতিল করা হয়েছে।")
        return

# =====================================================================
# FORCE JOIN CALLBACK HANDLER CAPABILITIES LOGIC
# =====================================================================
async def handle_force_join_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    if user_id == ADMIN_ID:
        context.user_data["is_verified"] = True
        await query.message.delete()
        await process_welcome_access(update, context)
        return

    bot_is_admin = True
    is_joined = False
    try:
        member = await context.bot.get_chat_member(chat_id="@bd94earning", user_id=user_id)
        if member.status in ["member", "administrator", "creator"]:
            is_joined = True
    except Exception as e:
        logger.warning(f"Force join status checkpoint warning log statement: {e}")
        bot_is_admin = False

    if is_joined:
        context.user_data["is_verified"] = True
        await query.message.delete()
        await process_welcome_access(update, context)
    else:
        if not bot_is_admin:
            await query.message.reply_text("⚠️ আমাদের অফিসিয়াল চ্যানেল ভেরিফিকেশন সিস্টেমে সাময়িক কারিগরি সমস্যা হচ্ছে। অনুগ্রহ করে কিছুক্ষণ পর চেষ্টা করুন।")
            return
        await query.message.delete()
        await send_force_join_screen(update, context, is_retry=True)

# =====================================================================
# OVERRIDE REGULAR MODIFIED INTERACTION ROUTER IN TEXT PATTERNS
# =====================================================================
async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_membership_gated(update, context):
        return
        
    text = update.message.text
    user_id = update.effective_user.id
    current_step = context.user_data.get("withdraw_step")
    dep_step = context.user_data.get("deposit_step")
    wizard_step = context.user_data.get("job_wizard", {}).get("step") if context.user_data.get("job_wizard") else None

    check_and_expire_tasks()

    if text == "❌ Cancel":
        context.user_data.clear()
        await show_main_menu(update, "❌ সেশন ক্লিয়ার করে মূল মেনুতে ফেরত আসা হয়েছে।")
        return

    if text == "🔙 Back":
        context.user_data.clear()
        await show_main_menu(update, "মেনুতে ব্যাক করা হলো।")
        return

    # Multi-step creation texts wizard capture intercepting
    if wizard_step:
        wizard = context.user_data["job_wizard"]
        if wizard_step == "TITLE":
            if len(text.strip()) < 5:
                await update.message.reply_text("⚠️ শিরোনাম অত্যন্ত ছোট! নূন্যতম ৫ অক্ষরের শিরোনাম টাইপ করুন:")
                return
            wizard["title"] = text.strip()
            wizard["step"] = "DESCRIPTION"
            await update.message.reply_text("📄 **ধাপ ৪**: এবার কাজের সম্পূর্ণ বিবরণ (Detailed Description) সুন্দর করে মেসেজে লিখে পাঠান:")
            return
        elif wizard_step == "DESCRIPTION":
            if len(text.strip()) < 10:
                await update.message.reply_text("⚠️ বিবরণ অত্যন্ত ছোট! নূন্যতম ১০ অক্ষরের বিস্তারিত বিবরণ লিখে পাঠান:")
                return
            wizard["description"] = text.strip()
            wizard["step"] = "PROOF_NAME"
            await update.message.reply_text("📋 **ধাপ ৫**: কাজের প্রমাণ যাচাইয়ের জন্য প্রুф সেটআপ।\n\n👇 ১ম প্রুফের নাম কি হবে তা লিখে পাঠান (যেমন: Username, Screenshot):")
            return
        elif wizard_step == "PROOF_NAME":
            if len(text.strip()) < 2:
                await update.message.reply_text("⚠️ সঠিক প্রুফের নাম টাইপ করুন:")
                return
            wizard["current_proof_name"] = text.strip()
            wizard["step"] = "PROOF_TYPE"
            keyboard = [[InlineKeyboardButton("📝 Text Proof", callback_data="wiz_proof_text")],[InlineKeyboardButton("📸 Screenshot Proof", callback_data="wiz_proof_photo")]]
            await update.message.reply_text(f"📌 প্রুফের নাম: **{text.strip()}**\n\n👇 সাবমিশন ধরণ সিলেক্ট করুন:", reply_markup=InlineKeyboardMarkup(keyboard))
            return
        elif wizard_step == "WORKERS":
            try:
                workers_cnt = int(text.strip())
                if workers_cnt < 10: raise ValueError
            except ValueError:
                await update.message.reply_text("⚠️ ভুল ইনপুট! নূন্যতম ১০ জন ওয়ার্কার প্রয়োজন। সঠিক সংখ্যা টাইপ করুন (যেমন: 25):")
                return
            wizard["workers"] = workers_cnt
            wizard["step"] = "TIME_LIMIT"
            keyboard = [[InlineKeyboardButton("📅 1 Day", callback_data="wiz_time_1"), InlineKeyboardButton("📅 3 Days", callback_data="wiz_time_3")],[InlineKeyboardButton("📅 7 Days", callback_data="wiz_time_7")]]
            await update.message.reply_text("📅 **ধাপ ৯**: ওয়ার্কাররা সর্বোচ্চ কতদিনের মধ্যে কাজটি সম্পন্ন করার সুযোগ পাবে?", reply_markup=InlineKeyboardMarkup(keyboard))
            return

    # Dynamic deposit sequences
    if dep_step == "dep_step_2":
        try:
            amount = int(text.replace(" Tk", "").strip())
            if amount <= 0: raise ValueError
        except ValueError:
            await update.message.reply_text("❌ সঠিক পরিমাণ টাইপ করুন:")
            return
        context.user_data["dep_amount"] = amount
        context.user_data["deposit_step"] = "dep_step_3"
        await update.message.reply_text(f"💰 পরিমাণ: {amount} Tk\n\nলেনদেনের ট্রানজেকশন আইডি (TxID) লিখে পাঠান:", reply_markup=ReplyKeyboardMarkup([["❌ Cancel"]], resize_keyboard=True))
        return
    elif dep_step == "dep_step_3":
        if len(text.strip()) < 4:
            await update.message.reply_text("❌ সঠিক ট্রানজেকশন আইডি দিন:")
            return
        context.user_data["dep_txid"] = text.strip()
        context.user_data["deposit_step"] = "dep_step_4"
        await update.message.reply_text("📸 সফল পেমেন্টের স্ক্রিনশট ফাইল ইমেজ আকারে এখানে সেন্ড করুন:", reply_markup=ReplyKeyboardMarkup([["❌ Cancel"]], resize_keyboard=True))
        return

    # Withdrawal sequences
    if current_step == "step_1":
        if text in ["150 Tk", "300 Tk", "500 Tk", "1000 Tk"]:
            amount = int(text.split()[0])
            with sqlite3.connect(DATABASE) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT earnings_balance FROM users WHERE user_id = ?", (user_id,))
                user_bal = cursor.fetchone()[0] or 0
            if user_bal < amount:
                await update.message.reply_text(f"❌ উইথড্রযোগ্য ব্যালেন্স পর্যাপ্ত নয়! বর্তমান Earnings Balance: {user_bal} Tk")
                return
            context.user_data["amount"] = amount
            context.user_data["withdraw_step"] = "step_2"
            keyboard = [["📱 bKash", "📱 Nagad"], ["🔙 Back"]]
            await update.message.reply_text(f"💰 পরিমাণ: {amount} Tk\n📱 পেমেন্ট গেটওয়ে সিলেক্ট করুন:", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))
        return
    elif current_step == "step_2":
        if text in ["📱 bKash", "📱 Nagad"]:
            context.user_data["method"] = text
            context.user_data["withdraw_step"] = "step_3"
            await update.message.reply_text(f"💳 মেথড: {text}\n📞 আপনার অ্যাকাউন্ট নম্বর লিখে পাঠান:", reply_markup=ReplyKeyboardMarkup([["❌ Cancel"]], resize_keyboard=True))
        return
    elif current_step == "step_3":
        if len(text.strip()) < 8:
            await update.message.reply_text("❌ সঠিক একাউন্ট নম্বর দিন:")
            return
        context.user_data["number"] = text.strip()
        context.user_data["withdraw_step"] = "step_4"
        keyboard = [["✅ Continue"], ["🔙 Back", "❌ Cancel"]]
        await update.message.reply_text(f"🔍 উইথড্রাল সামারি:\n💰 পরিমাণ: {context.user_data.get('amount')} Tk\n📱 মেথড: {context.user_data.get('method')}\n📞 অ্যাকাউন্ট: {text.strip()}\n\nনিশ্চিত করতে '✅ Continue' চাপুন।", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))
        return
    elif current_step == "step_4":
        if text == "✅ Continue":
            amount = context.user_data.get("amount")
            method = context.user_data.get("method")
            number = context.user_data.get("number")
            try:
                with db_transaction() as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT earnings_balance FROM users WHERE user_id = ?", (user_id,))
                    user_bal = cursor.fetchone()[0] or 0
                    if user_bal < amount:
                        await update.message.reply_text("❌ ব্যালেন্স পর্যাপ্ত নয়!")
                        return
                    cursor.execute("UPDATE users SET balance = CASE WHEN balance >= ? THEN balance - ? ELSE 0 END, earnings_balance = earnings_balance - ? WHERE user_id = ?", (amount, amount, amount, user_id))
                    created_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    cursor.execute("INSERT INTO withdrawals (user_id, amount, method, number, status, created_at) VALUES (?, ?, ?, ?, 'pending', ?)", (user_id, amount, method, number, created_at))
                    req_id = cursor.lastrowid
                context.user_data.clear()
                await show_main_menu(update, f"✅ উইথড্রাল রিকোয়েস্ট সফলভাবে সাবমিট হয়েছে! আইডি: #{req_id}")
            except Exception: pass
        return

    # --- Standard Key Buttons Router Paths ---
    if text == "📊 Dashboard":
        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT deposit_balance, earnings_balance, pending_balance, referrals FROM users WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
        await update.message.reply_text(f"📊 **ইউজার ড্যাশবোর্ড স্ট্যাটাস**\n\n👤 ইউজার আইডি: {user_id}\n📥 ডিপোজিট ব্যালেন্স: {row[0] if row else 0} Tk\n💰 আর্নিংস ব্যালেন্স: {row[1] if row else 0} Tk\n⏳ পেন্ডিং ব্যালেন্স: {row[2] if row else 0} Tk\n👥 মোট সফল রেফারেল: {row[3] if row else 0} জন")

    elif text == "📝 Tasks":
        await show_tasks_menu(update, "📝 মাইক্রো-টাস্ক মার্কেটপ্লেস মেনু:")

    elif text == "➕ Create Job":
        await start_job_wizard(update, context)

    elif text == "🔍 Find Jobs":
        await find_jobs_start(update, context)

    elif text == "📌 My Posted Tasks":
        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, title, reward_amount, filled_slots, total_slots, status FROM tasks WHERE creator_id = ? ORDER BY id DESC", (user_id,))
            rows = cursor.fetchall()
        if not rows:
            await update.message.reply_text("📝 আপনার পোস্ট করা কোনো কাজের রেকর্ড পাওয়া যায়নি।")
            return
        text_out = "🛠️ **আপনার পোস্ট করা কাজের তালিকা**\n\n"
        for r in rows:
            text_out += f"🆔 কাজ ম্যানেজ করতে: /manage_task_{r[0]}\n💎 টাইটেল: {r[1]}\n💰 বায়ার রিওয়ার্ড: {r[2]} Tk | স্লট: {r[3]}/{r[4]} | স্ট্যাটাস: {r[5]}\n------------------------\n"
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
            await update.message.reply_text("📜 আপনার সম্পন্ন করা কোনো কাজের প্রুফ সাবমিশন হিস্ট্রি নেই।")
            return
        text_out = "🗳️ **আপনার জমাকৃত কাজের প্রুফ এবং স্ট্যাটাস**\n\n"
        for r in rows:
            status_ico = "⏳" if r[4] == "pending" else "✅" if r[4] == "approved" else "❌"
            text_out += f"প্রুফ আইডি: #{r[0]} | টাস্ক আইডি: #{r[1]}\n💎 টাইটেল: {r[2]}\n💰 আয়: {r[3]} Tk | স্ট্যাটাস: {status_ico} {r[4]}\n------------------------\n"
        await update.message.reply_text(text_out)

    elif text == "💳 Wallet":
        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT deposit_balance, earnings_balance FROM users WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
        await show_wallet_menu(update, f"💳 **সিকিউর ওয়ালেট সেন্টার**\n\n📥 ডিপোজিট ব্যালেন্স: {row[0] if row else 0} Tk\n💰 আর্নিংস ব্যালেন্স: {row[1] if row else 0} Tk")

    elif text == "📥 Deposit":
        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, method_name, account_number, payment_type FROM payment_methods WHERE status='active'")
            rows = cursor.fetchall()
        if not rows:
            await update.message.reply_text("❌ ডিপোজিট চ্যানেল সাময়িকভাবে বন্ধ আছে।")
            return
        context.user_data.clear()
        context.user_data["deposit_step"] = "dep_step_1"
        keyboard = [[f"📱 {r[1]} ({r[3]})"] for r in rows]
        keyboard.append(["🔙 Back"])
        await update.message.reply_text("📥 টাকা পাঠানোর মেথডটি সিলেক্ট করুন:", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))

    elif text == "📤 Withdraw":
        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT earnings_balance FROM users WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
        balance = row[0] if row else 0
        if balance < 150:
            await update.message.reply_text(f"❌ সর্বনিম্ন উইথড্রয়াল লিমিট ১৫০ টাকা। আপনার ব্যালেন্স আছে: {balance} Tk")
            return
        await show_withdraw_amounts(update, context)

    elif text == "📜 Deposit History":
        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT d.id, d.amount, m.method_name, d.status FROM deposits d JOIN payment_methods m ON d.method_id = m.id WHERE d.user_id = ? ORDER BY d.id DESC LIMIT 5", (user_id,))
            rows = cursor.fetchall()
        if not rows:
            await update.message.reply_text("📜 কোনো ডিপোজিট রেকর্ড হিস্ট্রি পাওয়া যায়নি।")
            return
        hist = "📥 **ডিপোজিট হিস্ট্রি ট্র্যাক**\n\n"
        for r in rows:
            ico = "⏳" if r[3] == "pending" else "✅" if r[3] == "approved" else "❌"
            hist += f"ডিপোজিট #{r[0]} - {r[1]} Tk মেথড: {r[2]} ({ico} {r[3]})\n"
        await update.message.reply_text(hist)

    elif text == "📜 Withdraw History":
        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, amount, method, status FROM withdrawals WHERE user_id = ? ORDER BY id DESC LIMIT 5", (user_id,))
            rows = cursor.fetchall()
        if not rows:
            await update.message.reply_text("📜 কোনো উইথড্রয়াল হিস্ট্রি পাওয়া যায়নি।")
            return
        hist = "📜 **উইথড্রয়াল হিস্ট্রি ট্র্যাক**\n\n"
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
            await update.message.reply_text("📊 কোনো ট্রানজেকশন লেজার হিস্ট্রি পাওয়া যায়নি।")
            return
        out = "📊 **হিসাব খাতা লেজার বিবরণী (সর্বশেষ ১০টি)**\n\n"
        for r in rows:
            sign = "+" if r[0] > 0 else ""
            out += f"📅 [{r[3]}]\n💥 টাইপ: {r[2]} ({r[1]})\n💰 পরিমাণ: {sign}{r[0]} Tk\n------------------------\n"
        await update.message.reply_text(out)

    elif text == "👤 Profile":
        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT earnings_balance, deposit_balance, referrals FROM users WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
        await update.message.reply_text(f"👤 **ইউজার প্রোফাইল ডিটেইলস**\n\nইউজার আইডি: {user_id}\n💰 Earnings Balance: {row[0] if row else 0} Tk\n📥 Deposit Balance: {row[1] if row else 0} Tk\n👥 মোট ডিরেক্ট রেফারেল: {row[2] if row else 0} জন")

    elif text == "👥 Referral":
        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT referrals, pending_reward, earned_reward FROM users WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
        referrals, pending_reward, earned_reward = row if row else (0, 0, 0)
        bot_username = "Bd94earningbot"
        await update.message.reply_text(f"👥 **রেফার এন্ড আর্ন নেটওয়ার্ক**\n\n🔗 আপনার ইউনিক রেফারেল লিংক:\nhttps://t.me/{bot_username}?start={user_id}\n\n✅ ভেরিফাইড রেফারেল সংখ্যা: {earned_reward // 20} জন\n⏳ মোট অর্জিত রেফার বোনাস: {earned_reward} Tk")

    elif text == "🧧 Daily Bonus":
        today_date = datetime.datetime.now().strftime("%Y-%m-%d")
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
                cursor.execute("UPDATE users SET balance = balance + 2, earnings_balance = earnings_balance + 2 WHERE user_id = ?", (user_id,))
                
                created_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                cursor.execute("""
                    INSERT INTO wallet_transactions (user_id, amount, balance_type, action_type, reference_id, created_at)
                    VALUES (?, 2, 'earnings_balance', 'Daily Bonus', 'BONUS', ?)
                """, (user_id, created_at))
                
            await update.message.reply_text("🎁 Daily Bonus Claimed!\n\n💰 Reward: 2 Tk\n✅ Added to Earnings Balance")
        except sqlite3.IntegrityError:
            await update.message.reply_text("❌ আপনি আজকের Daily Bonus ইতিমধ্যে সংগ্রহ করেছেন।")
        except Exception:
            await update.message.reply_text("❌ টেকনিক্যাল সমস্যার কারণে বোনাস প্রসেস করা যায়নি।")
        return

# =====================================================================
# INTERCEPT ROUTER REGULAR CORE REGISTRATIONS
# =====================================================================
def main():
    if not TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN environment variable is not defined!")
    
    init_db()
    
    web_thread = threading.Thread(target=run_web_server, daemon=True)
    web_thread.start()
    
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())

    app = Application.builder().token(TOKEN).build()
    
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
    
    # Specific verification check mapping handler
    app.add_handler(CallbackQueryHandler(handle_force_join_callback, pattern=r'^check_force_join$'))
    app.add_handler(CallbackQueryHandler(handle_wizard_callbacks, pattern=r'^wiz_'))
    app.add_handler(CallbackQueryHandler(handle_browse_callbacks, pattern=r'^browse_'))
    
    app.add_handler(MessageHandler(filters.Regex(r'^\/(view_task_|submit_proof_|manage_task_|view_sub_|approve_sub_|reject_sub_)\d+'), handle_regex_routing))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, buttons))

    print("BD94 Marketplace Online [Force Join Module Active]...")
    app.run_polling()

if __name__ == "__main__":
    main()