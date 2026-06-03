import os
import sqlite3
import logging
import datetime
import http.server
import socketserver
import threading
import asyncio
import re
from contextlib import contextmanager
from dotenv import load_dotenv
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
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
# SQLITE CONCURRENCY & TRANSACTION CONTEXT MANAGER
# =====================================================================
@contextmanager
def db_transaction():
    """
    Guarantees exclusive write access via BEGIN IMMEDIATE.
    Prevents sqlite3.OperationalError: database is locked.
    Automatically handles commits, rollbacks, and clean close.
    """
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
        
        # Dynamic check for newly added tracking balances columns
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
            created_at TEXT
        )""")
        
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
        
        # wallet_transactions ledger table
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
# RENDER KEEP-ALIVE SERVER INFRASTRUCTURE
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
            logger.info(f"Starting web server on port {port} for Render keep-alive...")
            server.serve_forever()
    except Exception as e:
        logger.error(f"Keep-Alive web server failed: {e}")

# =====================================================================
# CORE SYSTEM DATABASE HELPERS
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
    
    if referrer_id != 0:
        try:
            await context.bot.send_message(
                chat_id=referrer_id,
                text="🎉 New Referral Joined!\n💰 Pending Reward: +20 Tk"
            )
        except Exception as e:
            logger.error(f"Failed to notify referrer: {e}")
            
    await show_main_menu(update, "🎉 Welcome to BD94 MICRO-TASK MARKETPLACE!")

async def show_main_menu(update: Update, msg_text: str):
    keyboard = [
        ["📊 Dashboard", "📝 Tasks"],
        ["💳 Wallet", "🔔 Notifications"],
        ["👤 Profile", "👥 Referral"],
        ["📞 Support"]
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
    await update.message.reply_text("💳 Withdraw Amount নির্বাচন করুন:", reply_markup=reply_markup)

async def show_tasks_menu(update: Update, msg_text: str):
    keyboard = [
        ["📌 Available Tasks", "➕ Post New Task"],
        ["📌 My Posted Tasks", "📌 My Submitted Tasks"],
        ["🧧 Daily Bonus", "🔙 Back"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(msg_text, reply_markup=reply_markup)

# =====================================================================
# ADMIN PANEL PANEL COMMANDTIER
# =====================================================================
async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Access Denied!")
        return
    await update.message.reply_text(
        "👑 BD94 Admin Command Panel\n\n"
        "📊 /stats - Total User Stats\n"
        "📢 /broadcast <message> - Global Announcement\n"
        "📥 /show_pending - View all pending withdrawals\n"
        "📜 /show_withdraws - View list of last 20 requests\n"
        "✅ /approve <request_id> - Approve withdrawal\n"
        "❌ /reject <request_id> <reason> - Reject withdrawal\n\n"
        "⚙️ Wallet & Deposit Controls:\n"
        "📱 /payment_methods - View current methods\n"
        "➕ /add_payment_method <Name>|<Number>|<Type>\n"
        "✏️ /edit_payment_method <ID>|<New Number>\n"
        "🗑️ /delete_payment_method <ID>\n"
        "📥 /show_deposits - View all pending deposits\n"
        "✅ /approve_deposit <deposit_id> - Approve deposit\n"
        "❌ /reject_deposit <deposit_id> <reason> - Reject deposit"
    )

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Access Denied!")
        return
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
        f"📊 BD94 Real-Time Stats:\n\n"
        f"👥 Total Users: {total_users}\n"
        f"💳 Total Withdrawals: {total_withdrawals}\n"
        f"⏳ Pending Withdraws: {pending_withdrawals}\n"
        f"📥 Pending Deposits: {pending_deposits}"
    )

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Access Denied!")
        return
    if not context.args:
        await update.message.reply_text("ব্যবহার নিয়ম: /broadcast আপনার বার্তা")
        return
    message = " ".join(context.args)
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
    await update.message.reply_text(f"✅ Message successfully broadcast to {sent} users!")

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
    text = "📥 Pending Withdrawal Requests:\n\n"
    for r in rows:
        text += f"Request #{r[0]}\n👤 User: {r[1]}\n💰 Amount: {r[2]} Tk\n📱 Method: {r[3]}\n📞 Number: {r[4]}\n📅 Date: {r[5]}\n👉 Approve: /approve {r[0]}\n👉 Reject: /reject {r[0]} Reason\n------------------------\n"
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
    text = "📜 Recent Withdrawals List (Max 20):\n\n"
    for r in rows:
        status_emoji = "⏳" if r[4] == "pending" else "✅" if r[4] == "approved" else "❌"
        text += f"#{r[0]} | User {r[1]} | {r[2]} Tk | {r[3]} | {status_emoji} {r[4]}\n"
    await update.message.reply_text(text)

# =====================================================================
# ATOMIC CORE REVIEW MODERATIONS (ADMIN CHANNELS)
# =====================================================================
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
                        INSERT INTO notifications (user_id, message, created_at)
                        VALUES (?, ?, ?)
                    """, (referrer_id, f"🎉 Received 20 Tk Referral Reward for User ID {user_id}!", datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")))

            conn.execute("""
                INSERT INTO wallet_transactions (user_id, amount, balance_type, action_type, reference_id, created_at)
                VALUES (?, ?, 'earnings_balance', 'Withdrawal Approved', ?, ?)
            """, (user_id, -amount, str(req_id), datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")))

            conn.execute("""
                INSERT INTO notifications (user_id, message, created_at)
                VALUES (?, ?, ?)
            """, (user_id, f"💸 Payout request #{req_id} of {amount} Tk was approved!", datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")))

        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"✅ Withdrawal Approved\n\nYour #{req_id} payout request was approved.\n💰 Amount: {amount} Tk\n📱 Method: {method}"
            )
        except Exception:
            pass
        await update.message.reply_text(f"✅ Request #{req_id} has been successfully approved.")
    except Exception as e:
        logger.error(f"Error in approve withdrawal: {e}")
        await update.message.reply_text("❌ Verification transaction failed.")

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
                text=f"❌ Withdrawal Request Rejected\n\nRequest #{req_id} was rejected.\n💬 Reason: {reason}"
            )
        except Exception:
            pass
        await update.message.reply_text(f"❌ Request #{req_id} rejected, funds refunded safely.")
    except Exception as e:
        logger.error(f"Error in reject withdrawal: {e}")
        await update.message.reply_text("❌ Rejection processing failed.")

# =====================================================================
# GATEWAY & PAYMENT SETTINGS (ADMIN ROUTERS)
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
        await update.message.reply_text("📱 No methods found.")
        return
    text = "📱 Current Payment Methods:\n\n"
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
        await update.message.reply_text("❌ Invalid layout configuration.")
        return
    name, number, p_type = data[0].strip(), data[1].strip(), data[2].strip()
    with db_transaction() as conn:
        conn.execute(
            "INSERT INTO payment_methods (method_name, account_number, payment_type) VALUES (?, ?, ?)",
            (name, number, p_type)
        )
    await update.message.reply_text(f"✅ Method '{name}' successfully injected.")

async def edit_payment_method(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Access Denied!")
        return
    raw_text = " ".join(context.args)
    if "|" not in raw_text:
        await update.message.reply_text("নিয়ম: /edit_payment_method ID|NewNumber")
        return
    data = raw_text.split("|")
    try:
        m_id = int(data[0].strip())
        new_no = data[1].strip()
    except Exception:
        await update.message.reply_text("❌ Structural parsing error.")
        return
    with db_transaction() as conn:
        conn.execute("UPDATE payment_methods SET account_number = ? WHERE id = ?", (new_no, m_id))
    await update.message.reply_text(f"✅ Method ID #{m_id} config adjusted.")

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
    await update.message.reply_text(f"🗑️ Method ID #{m_id} removed completely.")

async def show_deposits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Access Denied!")
        return
    with sqlite3.connect(DATABASE) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT d.id, d.user_id, d.amount, m.method_name, d.transaction_id, d.status, d.created_at 
            FROM deposits d JOIN payment_methods m ON d.method_id = m.id 
            WHERE d.status='pending' ORDER BY d.id ASC
        """)
        rows = cursor.fetchall()
    if not rows:
        await update.message.reply_text("📥 No pending deposit records active.")
        return
    text = "📥 Pending Deposits List:\n\n"
    for r in rows:
        text += f"Deposit ID: #{r[0]}\n👤 User: {r[1]}\n💰 Amount: {r[2]} Tk\n📱 Method: {r[3]}\n🔢 TxID: {r[4]}\n📅 Date: {r[6]}\n👉 Approve: /approve_deposit {r[0]}\n👉 Reject: /reject_deposit {r[0]} Reason\n------------------------\n"
    await update.message.reply_text(text)

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
        await update.message.reply_text("❌ ID structure must be an integer.")
        return

    try:
        with db_transaction() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT user_id, amount, status FROM deposits WHERE id = ?", (dep_id,))
            row = cursor.fetchone()
            if not row:
                await update.message.reply_text("❌ Deposit ID not found.")
                return
            user_id, amount, status = row
            if status != "pending":
                await update.message.reply_text(f"❌ Deposit query verification returns layout state: {status}.")
                return
            
            cursor.execute("UPDATE deposits SET status = 'approved' WHERE id = ?", (dep_id,))
            cursor.execute("UPDATE users SET deposit_balance = deposit_balance + ? WHERE user_id = ?", (amount, user_id))
            
            conn.execute("""
                INSERT INTO wallet_transactions (user_id, amount, balance_type, action_type, reference_id, created_at)
                VALUES (?, ?, 'deposit_balance', 'Deposit Approved', ?, ?)
            """, (user_id, amount, str(dep_id), datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            
            conn.execute("""
                INSERT INTO notifications (user_id, message, created_at)
                VALUES (?, ?, ?)
            """, (user_id, f"✅ Your deposit request #{dep_id} of {amount} Tk has been approved!", datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")))

        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"✅ Deposit Approved!\n\nDeposit request #{dep_id} approved.\n💰 Amount: {amount} Tk added to your Deposit Balance."
            )
        except Exception:
            pass
        await update.message.reply_text(f"✅ Deposit Request #{dep_id} marked as approved.")
    except Exception as e:
        logger.error(f"Error in approve deposit: {e}")
        await update.message.reply_text("❌ Deposit activation failed safely.")

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
                await update.message.reply_text("❌ Deposit reference ID missing.")
                return
            user_id, amount, status = row
            if status != "pending":
                await update.message.reply_text("❌ Target not pending.")
                return
            cursor.execute("UPDATE deposits SET status = 'rejected', admin_note = ? WHERE id = ?", (reason, dep_id))
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"❌ Deposit Request Rejected\n\nRequest #{dep_id} cancelled.\n💬 Reason: {reason}"
            )
        except Exception:
            pass
        await update.message.reply_text(f"❌ Deposit ID #{dep_id} flagged as rejected.")
    except Exception as e:
        logger.error(f"Error in reject deposit: {e}")

# =====================================================================
# REGEX INTERCEPT ROUTING INTERFACE (PHASE 2 WORKFLOW TUNNELS)
# =====================================================================
async def handle_regex_routing(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
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

async def view_task_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    try:
        task_id = int(text.replace("/view_task_", "").strip())
    except ValueError:
        return
    with sqlite3.connect(DATABASE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, creator_id, title, description, proof_requirements, reward_amount, total_slots, filled_slots, status FROM tasks WHERE id = ?", (task_id,))
        task = cursor.fetchone()
        if not task:
            await update.message.reply_text("❌ Task matching ID target missing.")
            return
        cursor.execute("SELECT status FROM task_submissions WHERE task_id = ? AND worker_id = ?", (task_id, user_id))
        prior_submission = cursor.fetchone()
    status_txt = "❌ Already Submitted" if prior_submission else "✅ Available to Work"
    if task[8] != "active" or task[7] >= task[6]:
        status_txt = "🔒 Slots Full / Closed"
    out = f"📋 Task Overview Details [ID: #{task[0]}]\n\n💎 Title: {task[2]}\n💰 Worker Reward Price: {task[5]} Tk\n👥 Capacity slots: {task[7]} / {task[6]}\n📊 Status Tracking: {status_txt}\n\n📝 Description:\n{task[3]}\n\n📋 Proof Demands Required:\n{task[4]}\n\n"
    if not prior_submission and task[8] == "active" and task[7] < task[6] and task[1] != user_id:
        out += f"👉 Submit Proof: /submit_proof_{task[0]}"
    else:
        out += "⚠️ Work access blocked or processing done for profile."
    await update.message.reply_text(out)

async def submit_proof_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    try:
        task_id = int(text.replace("/submit_proof_", "").strip())
    except ValueError:
        return
    with sqlite3.connect(DATABASE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, creator_id, status, total_slots, filled_slots FROM tasks WHERE id = ?", (task_id,))
        task = cursor.fetchone()
        if not task or task[2] != "active" or task[4] >= task[3]:
            await update.message.reply_text("❌ Task inactive or capacity full.")
            return
        if task[1] == user_id:
            await update.message.reply_text("❌ Self-submission constraint violation.")
            return
        cursor.execute("SELECT id FROM task_submissions WHERE task_id = ? AND worker_id = ?", (task_id, user_id))
        if cursor.fetchone():
            await update.message.reply_text("❌ Previous submission execution trace found.")
            return
    context.user_data.clear()
    context.user_data["sub_task_id"] = task_id
    context.user_data["task_submission_step"] = "entering_proof"
    keyboard = [["❌ Cancel"]]
    await update.message.reply_text(f"📝 Task #{task_id} proof inputs required. Write textual proofs directly into message field:", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))

async def manage_task_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    try:
        task_id = int(text.replace("/manage_task_", "").strip())
    except ValueError:
        return
    with sqlite3.connect(DATABASE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, creator_id, title, reward_amount, filled_slots, total_slots FROM tasks WHERE id = ?", (task_id,))
        task = cursor.fetchone()
        if not task or task[1] != user_id:
            await update.message.reply_text("❌ Control lookup violation across target ID.")
            return
        cursor.execute("SELECT id, worker_id, status FROM task_submissions WHERE task_id = ? AND status = 'pending'", (task_id,))
        subs = cursor.fetchall()
    out = f"🛠️ Managing Task Panel: #{task[0]}\n💎 Title: {task[2]}\n💰 Reward Price: {task[3]} Tk\n👥 Capacity filled: {task[4]}/{task[5]}\n\n"
    if not subs:
        out += "📥 No workflows awaiting tracking clearance currently."
    else:
        out += f"📥 Pending Submissions For Review ({len(subs)}):\n\n"
        for s in subs:
            out += f"Submission ID: /view_sub_{s[0]} | Worker Profile ID: {s[1]}\n"
    await update.message.reply_text(out)

async def view_submission_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    try:
        sub_id = int(text.replace("/view_sub_", "").strip())
    except ValueError:
        return
    with sqlite3.connect(DATABASE) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT s.id, s.task_id, s.worker_id, s.proof_text, s.proof_screenshot, s.status, t.creator_id, t.title 
            FROM task_submissions s JOIN tasks t ON s.task_id = t.id 
            WHERE s.id = ?
        """, (sub_id,))
        sub = cursor.fetchone()
    if not sub or sub[6] != user_id:
        await update.message.reply_text("❌ Ownership mapping mismatch error.")
        return
    out = f"🗳️ Work Submission Verification [Sub ID: #{sub[0]}]\n📌 Task: #{sub[1]} - {sub[7]}\n👥 Worker Account ID: {sub[2]}\n📊 Current Review Status: {sub[5]}\n\n💬 Submitted Text Proof:\n{sub[3]}\n\n"
    if sub[5] == "pending":
        out += f"👉 Approve: /approve_sub_{sub[0]}\n👉 Reject: /reject_sub_{sub[0]}"
    if sub[4]:
        try:
            await update.message.reply_photo(photo=sub[4], caption=out)
        except Exception:
            await update.message.reply_text(out)
    else:
        await update.message.reply_text(out)

async def approve_submission_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    try:
        sub_id = int(text.replace("/approve_sub_", "").strip())
    except ValueError:
        return

    try:
        with db_transaction() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT s.id, s.task_id, s.worker_id, s.status, t.creator_id, t.reward_amount 
                FROM task_submissions s JOIN tasks t ON s.task_id = t.id 
                WHERE s.id = ?
            """, (sub_id,))
            row = cursor.fetchone()
            if not row or row[4] != user_id:
                await update.message.reply_text("❌ Request target lookup mapping failure.")
                return
            if row[3] != "pending":
                await update.message.reply_text("❌ Record status state already shifted from pending.")
                return
            t_id, worker_id, reward = row[1], row[2], row[5]
            cursor.execute("UPDATE task_submissions SET status = 'approved' WHERE id = ?", (sub_id,))
            cursor.execute("UPDATE users SET balance = balance + ?, earnings_balance = earnings_balance + ? WHERE user_id = ?", (reward, reward, worker_id))
            
            conn.execute("""
                INSERT INTO wallet_transactions (user_id, amount, balance_type, action_type, reference_id, created_at)
                VALUES (?, ?, 'earnings_balance', 'Task Approved', ?, ?)
            """, (worker_id, reward, f"Sub-{sub_id}", datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            
            conn.execute("""
                INSERT INTO notifications (user_id, message, created_at)
                VALUES (?, ?, ?)
            """, (worker_id, f"✅ Your proof for Task #{t_id} was approved! +{reward} Tk received.", datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")))

        await update.message.reply_text(f"✅ Submission #{sub_id} marked approved, earnings systematically routed.")
    except Exception as e:
        logger.error(f"Error in approve submission: {e}")
        await update.message.reply_text("❌ Approval transaction locked out.")

async def reject_submission_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    try:
        sub_id = int(text.replace("/reject_sub_", "").strip())
    except ValueError:
        return
    with sqlite3.connect(DATABASE) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT s.id, s.status, t.creator_id 
            FROM task_submissions s JOIN tasks t ON s.task_id = t.id 
            WHERE s.id = ?
        """, (sub_id,))
        row = cursor.fetchone()
    if not row or row[2] != user_id:
        await update.message.reply_text("❌ Action validation access dropped.")
        return
    if row[1] != "pending":
        await update.message.reply_text("❌ State execution line completed prior.")
        return
    context.user_data.clear()
    context.user_data["review_sub_id"] = sub_id
    context.user_data["task_review_step"] = "entering_rejection_reason"
    await update.message.reply_text(f"❌ Rejecting task submission sequence #{sub_id}. Input processing rejection reason text into message window:")

# =====================================================================
# SYSTEM CORE REACTION ENGINE CONTROLS (THE DIALOG NAVIGATION RUNNER)
# =====================================================================
async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id
    current_step = context.user_data.get("withdraw_step")
    dep_step = context.user_data.get("deposit_step")
    task_step = context.user_data.get("task_wizard_step")
    sub_step = context.user_data.get("task_submission_step")
    review_step = context.user_data.get("task_review_step")

    if text == "❌ Cancel":
        context.user_data.clear()
        await show_main_menu(update, "❌ Session dropped. Menu initialized.")
        return

    if text == "🔙 Back":
        context.user_data.clear()
        if current_step or dep_step:
            with sqlite3.connect(DATABASE) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT deposit_balance, earnings_balance FROM users WHERE user_id = ?", (user_id,))
                row = cursor.fetchone()
            await show_wallet_menu(update, f"💳 Wallet Center Balance Summary:\n\n📥 Deposit Balance: {row[0] if row else 0} Tk\n💰 Earnings Balance: {row[1] if row else 0} Tk")
        elif task_step or sub_step or review_step:
            await show_tasks_menu(update, "📝 Marketplace Options Dashboard:")
        else:
            await show_main_menu(update, "🔙 Context reset back to start index.")
        return

    # --- Phase 1: Deposit Processing Flows ---
    if dep_step == "dep_step_1":
        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, method_name, account_number, payment_type FROM payment_methods WHERE status='active'")
            methods = cursor.fetchall()
        selected_method = None
        for m in methods:
            if text.startswith(f"📱 {m[1]}"):
                selected_method = m
                break
        if selected_method:
            context.user_data["dep_method_id"] = selected_method[0]
            context.user_data["dep_method_name"] = selected_method[1]
            context.user_data["dep_acc_number"] = selected_method[2]
            context.user_data["dep_pay_type"] = selected_method[3]
            context.user_data["deposit_step"] = "dep_step_2"
            keyboard = [["150 Tk", "300 Tk"], ["500 Tk", "1000 Tk"], ["🔙 Back"]]
            await update.message.reply_text(f"📥 Gateway Selected: {selected_method[1]}\n📞 Target Number: `{selected_method[2]}`\n\nInput amount or use keyboard selections:", parse_mode="Markdown", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))
        else:
            await update.message.reply_text("❌ Select clean gateway match option.")
        return

    elif dep_step == "dep_step_2":
        try:
            amount = int(text.replace(" Tk", "").strip())
            if amount <= 0: raise ValueError
        except ValueError:
            await update.message.reply_text("❌ Input structural parsing failed, select realistic positive value:")
            return
        context.user_data["dep_amount"] = amount
        context.user_data["deposit_step"] = "dep_step_3"
        keyboard = [["🔙 Back", "❌ Cancel"]]
        await update.message.reply_text(f"💰 Registered Amount: {amount} Tk\n\nEnter reference Transaction ID (TxID):", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))
        return

    elif dep_step == "dep_step_3":
        if len(text.strip()) < 4:
            await update.message.reply_text("❌ Input verification fails minimum sequence count constraint:")
            return
        context.user_data["dep_txid"] = text.strip()
        context.user_data["deposit_step"] = "dep_step_4"
        keyboard = [["🔙 Back", "❌ Cancel"]]
        await update.message.reply_text("📸 Send clear screenshot confirmation capture payload asset via image message attachment:", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))
        return

    # --- Phase 1: Payout/Withdrawal State Process Line ---
    if current_step == "step_1":
        if text in ["150 Tk", "300 Tk", "500 Tk", "1000 Tk"]:
            amount = int(text.split()[0])
            with sqlite3.connect(DATABASE) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT earnings_balance FROM users WHERE user_id = ?", (user_id,))
                user_bal = cursor.fetchone()[0] or 0
            if user_bal < amount:
                await update.message.reply_text(f"❌ Balance verification criteria error. Total accessible balance metrics: {user_bal} Tk")
                return
            context.user_data["amount"] = amount
            context.user_data["withdraw_step"] = "step_2"
            keyboard = [["📱 bKash", "📱 Nagad"], ["🔙 Back"]]
            await update.message.reply_text(f"💰 Selected: {amount} Tk\n\nSelect payout route destination:", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))
        else:
            await update.message.reply_text("❌ Choose matching numeric choice layout.")
        return

    elif current_step == "step_2":
        if text in ["📱 bKash", "📱 Nagad"]:
            context.user_data["method"] = text
            context.user_data["withdraw_step"] = "step_3"
            keyboard = [["🔙 Back", "❌ Cancel"]]
            await update.message.reply_text(f"💡 Route: {text}\n\nType target payment account interface number line:", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))
        return

    elif current_step == "step_3":
        if len(text.strip()) < 8:
            await update.message.reply_text("❌ Account interface sequencing metrics look invalid.")
            return
        context.user_data["number"] = text.strip()
        context.user_data["withdraw_step"] = "step_4"
        keyboard = [["✅ Continue"], ["🔙 Back", "❌ Cancel"]]
        await update.message.reply_text(f"🔍 Payout Invoice Overview Verification Summary:\n\n💰 Selected Out: {context.user_data.get('amount')} Tk\n📱 Routing: {context.user_data.get('method')}\n📞 Target Account Reference Line: {text.strip()}\n\nTap confirmation execution logic button down below:", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))
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
                        await update.message.reply_text("❌ Atomic state validation evaluation error. Balance changed prior.")
                        return
                    cursor.execute("UPDATE users SET balance = CASE WHEN balance >= ? THEN balance - ? ELSE 0 END, earnings_balance = earnings_balance - ? WHERE user_id = ?", (amount, amount, amount, user_id))
                    created_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    cursor.execute("INSERT INTO withdrawals (user_id, amount, method, number, status, created_at) VALUES (?, ?, ?, ?, 'pending', ?)", (user_id, amount, method, number, created_at))
                    req_id = cursor.lastrowid
                context.user_data.clear()
                await show_main_menu(update, f"✅ Payout execution tracking ticket generated cleanly: #{req_id}")
            except Exception as e:
                logger.error(f"Error saving withdrawal structural: {e}")
                await update.message.reply_text("❌ Concurrency validation failed safely.")
        return

    # --- Phase 2: Employer Task Creation Steps Wizard Line ---
    if task_step == "title":
        if len(text.strip()) < 5:
            await update.message.reply_text("❌ Title metric too small. Retype accurately:")
            return
        context.user_data["w_title"] = text.strip()
        context.user_data["task_wizard_step"] = "desc"
        await update.message.reply_text("📝 Enter description instructions for workers clearly:")
        return

    elif task_step == "desc":
        if len(text.strip()) < 10:
            await update.message.reply_text("❌ Instructions require realistic description context. Retry:")
            return
        context.user_data["w_desc"] = text.strip()
        context.user_data["task_wizard_step"] = "proof"
        await update.message.reply_text("📋 Detail exact validation proof items text workers must provide:")
        return

    elif task_step == "proof":
        if len(text.strip()) < 5:
            await update.message.reply_text("❌ Validation requirement formatting invalid. Re-enter:")
            return
        context.user_data["w_proof"] = text.strip()
        context.user_data["task_wizard_step"] = "reward"
        await update.message.reply_text("💰 Set individual work price payout reward integer (e.g., 10):")
        return

    elif task_step == "reward":
        try:
            reward = int(text.strip())
            if reward <= 0: raise ValueError
        except ValueError:
            await update.message.reply_text("❌ Integer scaling pricing required. Positive values sequence execution only:")
            return
        context.user_data["w_reward"] = reward
        context.user_data["task_wizard_step"] = "slots"
        await update.message.reply_text("👥 Total worker allocation quantity count capacity limit slots:")
        return

    elif task_step == "slots":
        try:
            slots = int(text.strip())
            if slots <= 0: raise ValueError
        except ValueError:
            await update.message.reply_text("❌ Quantity metrics scaling execution parameter error:")
            return
        reward = context.user_data.get("w_reward")
        subtotal = reward * slots
        fee = int(subtotal * 0.10)
        total_budget = subtotal + fee
        context.user_data["w_slots"] = slots
        context.user_data["w_budget"] = total_budget
        context.user_data["task_wizard_step"] = "confirm"
        keyboard = [["✅ Confirm & Post"], ["❌ Cancel"]]
        await update.message.reply_text(f"📊 Task Posting Calculation Processing Architecture:\n\n📌 Job: {context.user_data.get('w_title')}\n💰 Unit Pricing: {reward} Tk\n👥 Volume slots count: {slots}\n\n💵 Subtotal Net Value: {subtotal} Tk\n⚡ Network Processing System Fee (10%): {fee} Tk\n💳 Total Deductible Cost Structure: {total_budget} Tk\n\nTap initialization validation tracking block link below to post task online:", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))
        return

    elif task_step == "confirm":
        if text == "✅ Confirm & Post":
            budget = context.user_data.get("w_budget")
            try:
                with db_transaction() as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT deposit_balance FROM users WHERE user_id = ?", (user_id,))
                    dep_b = cursor.fetchone()[0] or 0
                    if dep_b < budget:
                        await show_tasks_menu(update, f"❌ Dynamic accounting coverage check fails. Target: {budget} Tk, accessible matching assets: {dep_b} Tk")
                        context.user_data.clear()
                        return
                    cursor.execute("UPDATE users SET deposit_balance = deposit_balance - ? WHERE user_id = ?", (budget, user_id))
                    created_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    cursor.execute("""
                        INSERT INTO tasks (creator_id, title, description, proof_requirements, reward_amount, total_slots, total_budget, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (user_id, context.user_data.get("w_title"), context.user_data.get("w_desc"), context.user_data.get("w_proof"), context.user_data.get("w_reward"), context.user_data.get("w_slots"), budget, created_at))
                    task_id = cursor.lastrowid
                    conn.execute("""
                        INSERT INTO wallet_transactions (user_id, amount, balance_type, action_type, reference_id, created_at)
                        VALUES (?, ?, 'deposit_balance', 'Task Created', ?, ?)
                    """, (user_id, -budget, str(task_id), created_at))
                context.user_data.clear()
                await show_tasks_menu(update, f"🎉 Dynamic marketplace task allocation matching successful. Task verification tracking ticket: #{task_id}")
            except Exception as e:
                logger.error(f"Error posting dynamic structural task system block: {e}")
                await update.message.reply_text("❌ Processing allocation pipeline failure.")
        return

    # --- Phase 2: Worker Proof Text Input ---
    if sub_step == "entering_proof":
        if len(text.strip()) < 5:
            await update.message.reply_text("❌ Verification metadata proof entry looks sparse. Expand text details:")
            return
        context.user_data["sub_proof_text"] = text.strip()
        context.user_data["task_submission_step"] = "uploading_photo"
        keyboard = [["❌ Cancel"]]
        await update.message.reply_text("📸 Send a clear screenshot context image or attachment dummy structure to complete task loop validation pipeline:", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))
        return

    # --- Phase 2: Employer Review Disapproval Reason Note Catch ---
    if review_step == "entering_rejection_reason":
        req_id = context.user_data.get("review_sub_id")
        reason = text.strip()
        if len(reason) < 3:
            await update.message.reply_text("❌ Input validation error context statement string size too low.")
            return
        try:
            with db_transaction() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT s.task_id, s.worker_id, t.reward_amount 
                    FROM task_submissions s JOIN tasks t ON s.task_id = t.id 
                    WHERE s.id = ? AND s.status = 'pending'
                """, (req_id,))
                row = cursor.fetchone()
                if not row:
                    await show_tasks_menu(update, "❌ Task submission sequence mismatch or processing already completed by external execution threads.")
                    context.user_data.clear()
                    return
                t_id, worker_id, reward = row
                cursor.execute("UPDATE task_submissions SET status = 'rejected', admin_note = ? WHERE id = ?", (reason, req_id))
                cursor.execute("UPDATE tasks SET filled_slots = CASE WHEN filled_slots > 0 THEN filled_slots - 1 ELSE 0 END WHERE id = ?", (t_id,))
                
                conn.execute("""
                    INSERT INTO notifications (user_id, message, created_at)
                    VALUES (?, ?, ?)
                """, (worker_id, f"❌ Your verification submission for Task #{t_id} was rejected. Reason: {reason}", datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            context.user_data.clear()
            await show_tasks_menu(update, f"❌ Submission verification tracking index #{req_id} rejected cleanly. Notification dispatched.")
        except Exception as e:
            logger.error(f"Rejection structural state transaction block update failure: {e}")
        return

    # =====================================================================
    # PHASE 2: DAILY BONUS SYSTEM CLAIM HANDLER
    # =====================================================================
    if text == "🧧 Daily Bonus" or text == "🎁 Bonus":
        today_date = datetime.datetime.now().strftime("%Y-%m-%d")
        try:
            with db_transaction() as conn:
                cursor = conn.cursor()
                
                # Rule 1: Validate worker has at least 1 verified approved work submission
                cursor.execute("""
                    SELECT COUNT(*) FROM task_submissions 
                    WHERE worker_id = ? AND status = 'approved'
                """, (user_id,))
                approved_tasks_count = cursor.fetchone()[0]
                
                if approved_tasks_count == 0:
                    await update.message.reply_text("❌ Daily Bonus পেতে হলে আগে অন্তত ১টি টাস্ক সফলভাবে Complete করতে হবে।")
                    return
                
                # Rule 2: Ensure calendar day limit claim restriction is intact
                cursor.execute("""
                    SELECT COUNT(*) FROM daily_bonus_claims 
                    WHERE user_id = ? AND claim_date = ?
                """, (user_id, today_date))
                already_claimed = cursor.fetchone()[0]
                
                if already_claimed > 0:
                    await update.message.reply_text("❌ আপনি আজকের Daily Bonus ইতিমধ্যে সংগ্রহ করেছেন।")
                    return
                
                # Rule 3: Write claims atomically across unique constraints checks
                cursor.execute("""
                    INSERT INTO daily_bonus_claims (user_id, claim_date) 
                    VALUES (?, ?)
                """, (user_id, today_date))
                
                cursor.execute("""
                    UPDATE users 
                    SET balance = balance + 2, 
                        earnings_balance = earnings_balance + 2 
                    WHERE user_id = ?
                """, (user_id,))
                
                created_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                cursor.execute("""
                    INSERT INTO wallet_transactions (user_id, amount, balance_type, action_type, reference_id, created_at)
                    VALUES (?, 2, 'earnings_balance', 'Daily Bonus', 'BONUS', ?)
                """, (user_id, created_at))
                
                cursor.execute("""
                    INSERT INTO notifications (user_id, message, is_read, created_at)
                    VALUES (?, '🎁 Daily Bonus Claimed! +2 Tk Added.', 0, ?)
                """, (user_id, created_at))
                
            await update.message.reply_text(
                "🎁 Daily Bonus Claimed!\n\n"
                "💰 Reward: 2 Tk\n"
                "✅ Added to Earnings Balance"
            )
        except sqlite3.IntegrityError:
            await update.message.reply_text("❌ আপনি আজকের Daily Bonus ইতিমধ্যে সংগ্রহ করেছেন।")
        except Exception as e:
            logger.error(f"Daily bonus validation transactional error trace: {e}", exc_info=True)
            await update.message.reply_text("❌ Technical error matching claim profile.")
        return

    # --- Structural Key Buttons Direct Text Routers Layout ---
    if text == "📊 Dashboard":
        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT deposit_balance, earnings_balance, pending_balance, referrals FROM users WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
        await update.message.reply_text(f"📊 Live Accounting Metrics:\n\n👤 Profile ID: {user_id}\n📥 Deposit Pool Balance: {row[0] if row else 0} Tk\n💰 Earnings Pool Balance: {row[1] if row else 0} Tk\n⏳ Operations Pending: {row[2] if row else 0} Tk\n👥 Networking Referrals Count: {row[3] if row else 0}")

    elif text == "📝 Tasks":
        await show_tasks_menu(update, "📝 Active Task Marketplace Interface Hub:")

    elif text == "➕ Post New Task":
        context.user_data.clear()
        context.user_data["task_wizard_step"] = "title"
        keyboard = [["❌ Cancel"]]
        await update.message.reply_text("➕ Task creation processing stream online.\n\nEnter clear Title name label for your posting ticket:", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))

    elif text == "📌 Available Tasks":
        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, title, reward_amount, total_slots, filled_slots FROM tasks 
                WHERE status = 'active' AND filled_slots < total_slots AND creator_id != ?
                ORDER BY id DESC LIMIT 15
            """, (user_id,))
            rows = cursor.fetchall()
        if not rows:
            await update.message.reply_text("📌 No available micro-task campaigns currently waiting coverage processing inputs.")
            return
        text_out = "📌 Active Micro-Tasks Marketplace Open Listings:\n\n"
        for r in rows:
            text_out += f"🆔 View Campaign Details: /view_task_{r[0]}\n💎 Title: {r[1]}\n💰 Payout Price Reward: {r[2]} Tk | Volume: {r[4]}/{r[3]}\n------------------------\n"
        await update.message.reply_text(text_out)

    elif text == "📌 My Posted Tasks":
        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, title, reward_amount, filled_slots, total_slots, status FROM tasks WHERE creator_id = ? ORDER BY id DESC", (user_id,))
            rows = cursor.fetchall()
        if not rows:
            await update.message.reply_text("📝 Profile history trace registers no historical task allocations posted.")
            return
        text_out = "🛠️ Your Posted Campaigns Index Logs:\n\n"
        for r in rows:
            text_out += f"🆔 Manage Task Controls: /manage_task_{r[0]}\n💎 Label Name: {r[1]}\n💰 Cost Reward Scale: {r[2]} Tk | Volume Filled: {r[3]}/{r[4]} | State: {r[5]}\n------------------------\n"
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
            await update.message.reply_text("📜 No historical work entries submission records associated to your active profile ID.")
            return
        text_out = "🗳️ Your Job Completion Tracking History:\n\n"
        for r in rows:
            status_ico = "⏳" if r[4] == "pending" else "✅" if r[4] == "approved" else "❌"
            text_out += f"Submission Tracker Ticket ID: #{r[0]} | Campaign Reference: #{r[1]}\n💎 Job: {r[2]}\n💰 Expected Income Value: {r[3]} Tk | Review State: {status_ico} {r[4]}\n------------------------\n"
        await update.message.reply_text(text_out)

    elif text == "🔔 Notifications":
        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT message, created_at FROM notifications WHERE user_id = ? ORDER BY id DESC LIMIT 10", (user_id,))
            rows = cursor.fetchall()
            cursor.execute("UPDATE notifications SET is_read = 1 WHERE user_id = ?", (user_id,))
            conn.commit()
        if not rows:
            await update.message.reply_text("🔔 Notification parsing check return clean slate.")
            return
        text_out = "🔔 Dynamic Profile System Notifications Log:\n\n"
        for r in rows:
            text_out += f"📅 [{r[1]}]\n💬 {r[0]}\n------------------------\n"
        await update.message.reply_text(text_out)

    elif text == "💳 Wallet":
        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT deposit_balance, earnings_balance FROM users WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
        await show_wallet_menu(update, f"💳 Welcome to your Secure Wallet Center\n\n📥 Deposit Balance: {row[0] if row else 0} Tk\n💰 Earnings Balance: {row[1] if row else 0} Tk\n\nSelect an option from sub-menu below:")

    elif text == "📥 Deposit":
        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, method_name, account_number, payment_type FROM payment_methods WHERE status='active'")
            rows = cursor.fetchall()
        if not rows:
            await update.message.reply_text("❌ No available deposit channels enabled by management.")
            return
        context.user_data.clear()
        context.user_data["deposit_step"] = "dep_step_1"
        keyboard = [[f"📱 {r[1]} ({r[3]})"] for r in rows]
        keyboard.append(["🔙 Back"])
        await update.message.reply_text("📥 Choose routing processing interface option:", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))

    elif text == "📤 Withdraw":
        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT earnings_balance FROM users WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
        balance = row[0] if row else 0
        if balance < 150:
            await update.message.reply_text(f"❌ Payout threshold check fails. Min: 150 Tk, Balance: {balance} Tk")
            return
        await show_withdraw_amounts(update, context)

    elif text == "📜 Deposit History":
        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT d.id, d.amount, m.method_name, d.status FROM deposits d JOIN payment_methods m ON d.method_id = m.id WHERE d.user_id = ? ORDER BY d.id DESC LIMIT 5", (user_id,))
            rows = cursor.fetchall()
        if not rows:
            await update.message.reply_text("📜 No deposit operations tracked under profile historical logs.")
            return
        hist = "📥 Recent Deposits Ledger Processing States:\n\n"
        for r in rows:
            ico = "⏳" if r[3] == "pending" else "✅" if r[3] == "approved" else "❌"
            hist += f"Deposit Ticket #{r[0]} - {r[1]} Tk via {r[2]} ({ico} {r[3]})\n"
        await update.message.reply_text(hist)

    elif text == "📜 Withdraw History" or text == "📜 History":
        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, amount, method, status FROM withdrawals WHERE user_id = ? ORDER BY id DESC LIMIT 5", (user_id,))
            rows = cursor.fetchall()
        if not rows:
            await update.message.reply_text("📜 Payout database indexing return empty dataset arrays.")
            return
        hist = "📜 Recent Withdrawals Execution Output Summary:\n\n"
        for r in rows:
            ico = "⏳" if r[3] == "pending" else "✅" if r[3] == "approved" else "❌"
            hist += f"Request Tracker Ticket ID: #{r[0]} - {r[1]} Tk via {r[2]} ({ico} {r[3]})\n"
        await update.message.reply_text(hist)

    elif text == "📊 Transaction History":
        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT amount, balance_type, action_type, created_at FROM wallet_transactions WHERE user_id = ? ORDER BY id DESC LIMIT 10", (user_id,))
            rows = cursor.fetchall()
        if not rows:
            await update.message.reply_text("📊 Double accounting audit trace records empty matching values.")
            return
        out = "📊 Double-Entry Accounting Activity Logs:\n\n"
        for r in rows:
            sign = "+" if r[0] > 0 else ""
            out += f"📅 [{r[3]}]\n💥 Action Trigger: {r[2]} ({r[1]})\n💰 Delta Offset: {sign}{r[0]} Tk\n------------------------\n"
        await update.message.reply_text(out)

    elif text == "👤 Profile":
        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT earnings_balance, deposit_balance, referrals FROM users WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
        await update.message.reply_text(f"👤 Core Account Specifications:\n\nUser Profile Identity Reference: {user_id}\n💰 Earnings Ledger Asset Pool: {row[0] if row else 0} Tk\n📥 Task Factory Injection Capital Balance: {row[1] if row else 0} Tk\n👥 Distribution Network Direct Members Size: {row[2] if row else 0}")

    elif text == "👥 Referral":
        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT referrals, pending_reward, earned_reward FROM users WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
        referrals, pending_reward, earned_reward = row if row else (0, 0, 0)
        bot_username = "Bd94earningbot"
        await update.message.reply_text(f"👥 Your Referral Link:\nhttps://t.me/{bot_username}?start={user_id}\n\n✅ Verified Conversion: {earned_reward // 20}\n⏳ Pending Verification: {pending_reward // 20}\n\n💰 Harvested Reward Balance: {earned_reward} Tk\n⏳ Allocation Lock Pending Audit: {pending_reward} Tk")

    elif text == "📞 Support":
        await update.message.reply_text("📞 Direct routing interface to help desks system admin tier: @BD94_Support_Admin")
    else:
        if not current_step and not dep_step and not task_step and not sub_step and not review_step:
            await show_main_menu(update, "❓ Command interface configuration parse mismatch error. Choose alternative options keyboard items:")

# =====================================================================
# ASYNC MEDIA ATTACHMENTS FILTER (CAPTURE ENGINE FOR SCREENSHOT PROOFS)
# =====================================================================
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    dep_step = context.user_data.get("deposit_step")
    sub_step = context.user_data.get("task_submission_step")
    user_id = update.effective_user.id
    
    if dep_step == "dep_step_4":
        photo_file_id = update.message.photo[-1].file_id
        amount = context.user_data.get("dep_amount")
        m_id = context.user_data.get("dep_method_id")
        m_name = context.user_data.get("dep_method_name")
        txid = context.user_data.get("dep_txid")
        created_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            with db_transaction() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO deposits (user_id, amount, method_id, transaction_id, screenshot_file_id, status, created_at) VALUES (?, ?, ?, ?, ?, 'pending', ?)",
                    (user_id, amount, m_id, txid, photo_file_id, created_at)
                )
                dep_id = cursor.lastrowid
            context.user_data.clear()
            await show_main_menu(update, f"✅ Deposit application processing ticket submitted for manual audit indexing cleanly. Ticket Reference ID: #{dep_id}")
            try:
                await context.bot.send_message(chat_id=ADMIN_ID, text=f"📥 Notification - Verification Incoming:\n\nTicket Reference Tracker ID: #{dep_id}\nUser Account Line: {user_id}\nClaimed Asset Transfer Volume: {amount} Tk\nUnique Reference Code TxID: {txid}")
            except Exception:
                pass
        except sqlite3.IntegrityError:
            await update.message.reply_text("❌ Input validation error constraints collision tracking logic trace detects reference code duplicate execution error.")
        return

    elif sub_step == "uploading_photo":
        photo_file_id = update.message.photo[-1].file_id
        task_id = context.user_data.get("sub_task_id")
        proof_text = context.user_data.get("sub_proof_text")
        created_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            with db_transaction() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT creator_id, total_slots, filled_slots, status FROM tasks WHERE id = ?", (task_id,))
                task_data = cursor.fetchone()
                if not task_data or task_data[3] != "active" or task_data[2] >= task_data[1]:
                    await show_tasks_menu(update, "❌ Allocation constraint logic check fails. Maximum concurrent work submissions cap threshold passed.")
                    context.user_data.clear()
                    return
                cursor.execute("""
                    INSERT INTO task_submissions (task_id, worker_id, proof_text, proof_screenshot, status, created_at)
                    VALUES (?, ?, ?, ?, 'pending', ?)
                """, (task_id, user_id, proof_text, photo_file_id, created_at))
                cursor.execute("UPDATE tasks SET filled_slots = filled_slots + 1 WHERE id = ?", (task_id,))
            context.user_data.clear()
            await show_tasks_menu(update, f"✅ Your proof has been submitted successfully to the employer.")
            try:
                await context.bot.send_message(chat_id=task_data[0], text=f"🔔 Notification: Verification incoming on active running campaign index template ID: #{task_id}. Access via structural reference: /manage_task_{task_id}")
            except Exception:
                pass
        except sqlite3.IntegrityError:
            await update.message.reply_text("❌ Duplicate task execution trace pattern mismatch entry.")
            context.user_data.clear()
        return

# =====================================================================
# SYSTEM MAIN ENGINE ROUTINE ENTRYBOOTSTRAPPER
# =====================================================================
def main():
    if not TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN environment variable is not defined!")
    
    # Init or safely auto-migrate sqlite schemes
    init_db()
    
    # Launch keep-alive thread bind daemon
    web_thread = threading.Thread(target=run_web_server, daemon=True)
    web_thread.start()
    
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())

    app = Application.builder().token(TOKEN).build()
    
    # Registration framework handlers mapper
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
    app.add_handler(CommandHandler("edit_payment_method", edit_payment_method))
    app.add_handler(CommandHandler("delete_payment_method", delete_payment_method))
    app.add_handler(CommandHandler("show_deposits", show_deposits))
    app.add_handler(CommandHandler("approve_deposit", approve_deposit))
    app.add_handler(CommandHandler("reject_deposit", reject_deposit))
    
    # Matching exact command sequences filters for tasks
    app.add_handler(MessageHandler(filters.Regex(r'^\/(view_task_|submit_proof_|manage_task_|view_sub_|approve_sub_|reject_sub_)\d+'), handle_regex_routing))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, buttons))

    print("BD94 Marketplace Platform Engine Online [Production Deploy Ready]...")
    app.run_polling()

if __name__ == "__main__":
    main()
