import os
import sqlite3
import logging
import datetime
import http.server
import socketserver
import threading
from dotenv import load_dotenv
from telegram import Update, ReplyKeyboardMarkup
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

# SQLite Database Initialization
def init_db():
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        balance INTEGER DEFAULT 0,
        referrals INTEGER DEFAULT 0,
        pending_reward INTEGER DEFAULT 0,
        earned_reward INTEGER DEFAULT 0,
        referrer_id INTEGER DEFAULT 0
    )
    """)
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
    )
    """)
    conn.commit()
    conn.close()

# Start lightweight HTTP Server for Render keep-alive
def run_web_server():
    class HealthHandler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header('Content-type', 'text/plain; charset=utf-8')
            self.end_headers()
            self.wfile.write(b"OK - BD94 bot active")

        def log_message(self, format, *args):
            return

    port = int(os.getenv("PORT", "3000"))
    try:
        # Allow immediate socket reuse
        socketserver.TCPServer.allow_reuse_address = True
        server = socketserver.TCPServer(("0.0.0.0", port), HealthHandler)
        logger.info(f"Starting web server on port {port} for Render container Keep-Alive...")
        server.serve_forever()
    except Exception as e:
        logger.error(f"Keep-Alive web server failed: {e}")

# Database helper functions
def save_user(user_id, referrer_id=0):
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
    if cursor.fetchone() is None:
        # Register new user
        cursor.execute(
            "INSERT INTO users (user_id, balance, referrals, pending_reward, earned_reward, referrer_id) VALUES (?, 0, 0, 0, 0, ?)",
            (user_id, referrer_id)
        )
        # Process Referrer details if exists
        if referrer_id != 0:
            cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (referrer_id,))
            if cursor.fetchone():
                cursor.execute(
                    "UPDATE users SET referrals = referrals + 1, pending_reward = pending_reward + 20 WHERE user_id = ?",
                    (referrer_id,)
                )
        conn.commit()
    conn.close()

# Start Command Handler
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

    await show_main_menu(update, "🎉 Welcome to BD94 EARNING!")

# Show Main Menu keyboard
async def show_main_menu(update: Update, msg_text: str):
    keyboard = [
        ["👤 Profile", "💰 Balance"],
        ["👥 Referral", "🎁 Bonus"],
        ["💳 Withdraw", "📜 History"],
        ["📞 Support", "ℹ️ About"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(msg_text, reply_markup=reply_markup)

# Show withdrawal amount options (Step 1)
async def show_withdraw_amounts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["withdraw_step"] = "step_1"
    keyboard = [
        ["150 Tk", "300 Tk"],
        ["500 Tk", "1000 Tk"],
        ["🔙 Back"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(
        "💳 Withdraw Amount নির্বাচন করুন:",
        reply_markup=reply_markup
    )

# Admin Panel command
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
        "❌ /reject <request_id> <reason> - Reject withdrawal and refund"
    )

# Stats command
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Access Denied!")
        return

    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users")
    total_users = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM withdrawals")
    total_withdrawals = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM withdrawals WHERE status='pending'")
    pending_withdrawals = cursor.fetchone()[0]
    conn.close()

    await update.message.reply_text(
        f"📊 BD94 Real-Time Stats:\n\n"
        f"👥 Total Users: {total_users}\n"
        f"💳 Total Withdrawals: {total_withdrawals}\n"
        f"⏳ Pending Requests: {pending_withdrawals}"
    )

# Broadcast command
async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Access Denied!")
        return

    if not context.args:
        await update.message.reply_text("ব্যবহার নিয়ম: /broadcast আপনার বার্তা")
        return

    message = " ".join(context.args)
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users")
    rows = cursor.fetchall()
    conn.close()

    sent = 0
    for r in rows:
        try:
            await context.bot.send_message(chat_id=r[0], text=message)
            sent += 1
        except Exception:
            pass

    await update.message.reply_text(f"✅ message successfully broadcast to {sent} users!")

# Show Pending withdrawals command
async def show_pending(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Access Denied!")
        return

    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute("SELECT id, user_id, amount, method, number, created_at FROM withdrawals WHERE status='pending' ORDER BY id ASC")
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        await update.message.reply_text("📥 No pending withdrawal requests.")
        return

    text = "📥 Pending Withdrawal Requests:\n\n"
    for r in rows:
        text += f"Request #{r[0]}\n" \
                f"👤 User: {r[1]}\n" \
                f"💰 Amount: {r[2]} Tk\n" \
                f"📱 Method: {r[3]}\n" \
                f"📞 Number: {r[4]}\n" \
                f"📅 Date: {r[5]}\n" \
                f"👉 Approve: /approve {r[0]}\n" \
                f"👉 Reject: /reject {r[0]} Reason\n" \
                f"------------------------\n"
    await update.message.reply_text(text)

# Show recent withdrawals list
async def show_withdraws(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Access Denied!")
        return

    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute("SELECT id, user_id, amount, method, status FROM withdrawals ORDER BY id DESC LIMIT 20")
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        await update.message.reply_text("📜 No withdrawals record found.")
        return

    text = "📜 Recent Withdrawals List (Max 20):\n\n"
    for r in rows:
        status_emoji = "⏳" if r[4] == "pending" else "✅" if r[4] == "approved" else "❌"
        text += f"#{r[0]} | User {r[1]} | {r[2]} Tk | {r[3]} | {status_emoji} {r[4]}\n"
    await update.message.reply_text(text)

# Approve Withdrawal process
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

    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, amount, status, method, number FROM withdrawals WHERE id = ?", (req_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        await update.message.reply_text("❌ এই Request ID খুঁজে পাওয়া যায়নি!")
        return

    user_id, amount, status, method, number = row
    if status != "pending":
        conn.close()
        await update.message.reply_text(f"❌ রিকোয়েস্টটি ইতিপূর্বে {status} করা হয়েছে!")
        return

    # Approve Request
    cursor.execute("UPDATE withdrawals SET status = 'approved' WHERE id = ?", (req_id,))

    # Notify User
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=f"✅ Withdrawal Approved\n\n"
                 f"আপনার #{req_id} নম্বর রিকোয়েস্টটি অ্যাপ্রুভ হয়েছে।\n"
                 f"💰 Amount: {amount} Tk\n"
                 f"📱 Method: {method}\n"
                 f"📞 Account: {number}\n\n"
                 f"আপনার একাউন্ট ব্যালেন্স থেকে টাকা কেটে নেওয়া হয়েছে।"
        )
    except Exception as e:
        logger.error(f"Failed to notify user: {e}")

    # Check database to see if this is the user's first approved withdrawal
    cursor.execute(
        "SELECT COUNT(*) FROM withdrawals WHERE user_id = ? AND status = 'approved' AND id != ?",
        (user_id, req_id)
    )
    prev_approved = cursor.fetchone()[0]

    if prev_approved == 0:
        # First successful withdrawal! Reward Referrer
        cursor.execute("SELECT referrer_id FROM users WHERE user_id = ?", (user_id,))
        ref_row = cursor.fetchone()
        if ref_row and ref_row[0] != 0:
            referrer_id = ref_row[0]
            
            # Update referrer rewards: move 20 Tk from pending to earned reward & add to their balance
            cursor.execute("""
                UPDATE users 
                SET balance = balance + 20,
                    earned_reward = earned_reward + 20,
                    pending_reward = CASE WHEN pending_reward >= 20 THEN pending_reward - 20 ELSE 0 END
                WHERE user_id = ?
            """, (referrer_id,))
            
            # Notify Referrer
            try:
                await context.bot.send_message(
                    chat_id=referrer_id,
                    text="🎉 Referral Reward Verified!\n\n"
                         "আপনার রেফার করা user সফলভাবে withdraw সম্পন্ন করেছে।\n\n"
                         "💰 Reward Added: 20 Tk"
                )
            except Exception as e:
                logger.error(f"Failed to notify referrer: {e}")

    conn.commit()
    conn.close()
    await update.message.reply_text(f"✅ Request #{req_id} অ্যাপ্রুভ করা হয়েছে এবং রেফারাল রিওয়ার্ড আপডেট করা হয়েছে।")

# Reject withdrawal and Refund balance
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

    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, amount, status FROM withdrawals WHERE id = ?", (req_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        await update.message.reply_text("❌ এই Request ID খুঁজে পাওয়া যায়নি!")
        return

    user_id, amount, status = row
    if status != "pending":
        conn.close()
        await update.message.reply_text(f"❌ রিকোয়েস্টটি ইতিপূর্বে {status} করা হয়েছে!")
        return

    # Reject withdrawal inside DB
    cursor.execute("UPDATE withdrawals SET status = 'rejected', admin_note = ? WHERE id = ?", (reason, req_id))
    # Refund balance to User
    cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
    conn.commit()
    conn.close()

    # Notify User of Rejection & Refund
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=f"❌ Withdrawal Request Rejected\n\n"
                 f"আপনার #{req_id} নম্বর রিকোয়েস্টটি বাতিল করা হয়েছে এবং {amount} Tk আপনার ব্যালেন্সে ফেরত দেওয়া হয়েছে।\n"
                 f"💬 Reason: {reason}"
        )
    except Exception as e:
        logger.error(f"Failed to notify user: {e}")

    await update.message.reply_text(f"❌ Request #{req_id} বাতিল করা হয়েছে এবং ব্যালেন্স রিফান্ড করা হয়েছে।")

# Handle Custom Buttons Click & Text messages
async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id
    current_step = context.user_data.get("withdraw_step")

    # Global Cancel validation for steps
    if text == "❌ Cancel":
        context.user_data.clear()
        await show_main_menu(update, "❌ আপনার উইথড্র সেশন বাতিল করা হয়েছে এবং ক্লিয়ার করা হয়েছে।")
        return

    # Global Back validation for sequential tracking
    if text == "🔙 Back":
        if current_step == "step_1":
            context.user_data.clear()
            await show_main_menu(update, "মেনুতে ফেরত যাওয়া হলো।")
            return
        elif current_step == "step_2":
            await show_withdraw_amounts(update, context)
            return
        elif current_step == "step_3":
            context.user_data["withdraw_step"] = "step_2"
            keyboard = [
                ["📱 bKash", "📱 Nagad"],
                ["🔙 Back"]
            ]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            await update.message.reply_text(
                f"💰 Selected Amount: {context.user_data.get('amount')} Tk\n\n"
                f"📱 Payment Method নির্বাচন করুন:",
                reply_markup=reply_markup
            )
            return
        elif current_step == "step_4":
            context.user_data["withdraw_step"] = "step_3"
            keyboard = [
                ["🔙 Back", "❌ Cancel"]
            ]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            await update.message.reply_text(
                f"💳 Method Selected: {context.user_data.get('method')}\n\n"
                f"📞 এখন আপনার {context.user_data.get('method')} নম্বর লিখে পাঠান:",
                reply_markup=reply_markup
            )
            return
        else:
            context.user_data.clear()
            await show_main_menu(update, "মেনুতে ব্যাক করা হলো।")
            return

    # --- Step 1 Processing: Amount Selection ---
    if current_step == "step_1":
        if text in ["150 Tk", "300 Tk", "500 Tk", "1000 Tk"]:
            amount = int(text.split()[0])
            
            # Fetch user balance
            conn = sqlite3.connect(DATABASE)
            cursor = conn.cursor()
            cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
            user_b = cursor.fetchone()
            conn.close()
            user_bal = user_b[0] if user_b else 0

            if user_bal < amount:
                await update.message.reply_text(
                    f"❌ দুঃখিত, আপনার ব্যালেন্স পর্যাপ্ত নয়!\n"
                    f"আপনার বর্তমান ব্যালেন্স: {user_bal} Tk"
                )
                return

            context.user_data["amount"] = amount
            context.user_data["withdraw_step"] = "step_2"
            keyboard = [
                ["📱 bKash", "📱 Nagad"],
                ["🔙 Back"]
            ]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            await update.message.reply_text(
                f"💰 Selected Amount: {amount} Tk\n\n"
                f"📱 Payment Method নির্বাচন করুন:",
                reply_markup=reply_markup
            )
            return
        else:
            await update.message.reply_text("❌ অনুগ্রহ করে নিচের কীবোর্ড থেকে সঠিক পরিমাণ সিলেক্ট করুন বা '🔙 Back' দিন।")
            return

    # --- Step 2 Processing: Payment Method Selection ---
    elif current_step == "step_2":
        if text in ["📱 bKash", "📱 Nagad"]:
            context.user_data["method"] = text
            context.user_data["withdraw_step"] = "step_3"
            keyboard = [
                ["🔙 Back", "❌ Cancel"]
            ]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            await update.message.reply_text(
                f"💳 Method Selected: {text}\n\n"
                f"📞 এখন আপনার {text} নম্বর লিখে পাঠান:",
                reply_markup=reply_markup
            )
            return
        else:
            await update.message.reply_text("❌ অনুগ্রহ করে নিচের কীবোর্ড থেকে মেথড সিলেক্ট করুন বা '🔙 Back' দিন।")
            return

    # --- Step 3 Processing: Number input ---
    elif current_step == "step_3":
        # Any text input here acts as the payment number
        context.user_data["number"] = text
        context.user_data["withdraw_step"] = "step_4"
        keyboard = [
            ["✅ Continue"],
            ["🔙 Back", "❌ Cancel"]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await update.message.reply_text(
            f"🔍 Withdrawal Summary:\n\n"
            f"💰 Amount Selected: {context.user_data.get('amount')} Tk\n"
            f"📱 Method Selected: {context.user_data.get('method')}\n"
            f"📞 Account No: {text}\n\n"
            f"অনুরোধটি চূড়ান্ত করতে '✅ Continue' বাটন ক্লিক করুন বা সংশোধন করতে '🔙 Back' দিন।",
            reply_markup=reply_markup
        )
        return

    # --- Step 4 Processing: Confirmation Submission ---
    elif current_step == "step_4":
        if text == "✅ Continue":
            amount = context.user_data.get("amount")
            method = context.user_data.get("method")
            number = context.user_data.get("number")

            if not amount or not method or not number:
                context.user_data.clear()
                await show_main_menu(update, "❌ অপশন সমুহ অসম্পূর্ণ হওয়ার জন্য মেইন মেনুতে ফেরত পাঠানো হলো।")
                return

            conn = sqlite3.connect(DATABASE)
            cursor = conn.cursor()
            cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
            user_b = cursor.fetchone()
            user_bal = user_b[0] if user_b else 0

            if user_bal < amount:
                conn.close()
                context.user_data.clear()
                await show_main_menu(update, f"❌ পর্যাপ্ত ব্যালেন্স নেই! আপনার ব্যালেন্স: {user_bal} Tk")
                return

            # Deduct balance immediately (pre-spend locked)
            cursor.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (amount, user_id))

            # Store Withdrawal request
            created_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute(
                "INSERT INTO withdrawals (user_id, amount, method, number, status, created_at) VALUES (?, ?, ?, ?, 'pending', ?)",
                (user_id, amount, method, number, created_at)
            )
            req_id = cursor.lastrowid
            conn.commit()
            conn.close()

            # Clear session states
            context.user_data.clear()

            # Confirm to User
            keyboard = [
                ["👤 Profile", "💰 Balance"],
                ["👥 Referral", "🎁 Bonus"],
                ["💳 Withdraw", "📜 History"],
                ["📞 Support", "ℹ️ About"]
            ]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            await update.message.reply_text(
                f"✅ Withdrawal Request Submitted!\n\n"
                f"Request ID: #{req_id}\n"
                f"Amount: {amount} Tk\n"
                f"Method: {method}\n"
                f"Number: {number}\n\n"
                f"আপনার রিকোয়েস্টটি সফলভাবে সাবমিট করা হয়েছে! এডমিন দ্রুত ভেরিফাই করে পেমেন্ট পাঠিয়ে দেবে এবং আপনি নোটিফিকেশন পাবেন।",
                reply_markup=reply_markup
            )

            # Notify Admin
            try:
                await context.bot.send_message(
                    chat_id=ADMIN_ID,
                    text=f"🆕 New Withdrawal Request\n\n"
                         f"Request ID: #{req_id}\n"
                         f"User ID: {user_id}\n"
                         f"Amount: {amount} Tk\n"
                         f"Method: {method}\n"
                         f"Number: {number}"
                )
            except Exception as e:
                logger.error(f"Failed to notify admin of request #{req_id}: {e}")
            return
        else:
            await update.message.reply_text("❌ অনুগ্রহ করে '✅ Continue' সিলেক্ট করুন অথবা সংশোধনের জন্য '🔙 Back' দিন।")
            return

    # --- Standard Main Menu Controls ---
    if text == "👤 Profile":
        conn = sqlite3.connect(DATABASE)
        cursor = conn.cursor()
        cursor.execute("SELECT balance, referrals FROM users WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        conn.close()
        balance = row[0] if row else 0
        referrals = row[1] if row else 0

        await update.message.reply_text(
            f"👤 User ID: {user_id}\n\n"
            f"💰 Balance: {balance} Tk\n"
            f"👥 Referrals: {referrals}"
        )

    elif text == "💰 Balance":
        conn = sqlite3.connect(DATABASE)
        cursor = conn.cursor()
        cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        conn.close()
        balance = row[0] if row else 0
        await update.message.reply_text(f"💰 Current Balance: {balance} Tk")

    elif text == "👥 Referral":
        conn = sqlite3.connect(DATABASE)
        cursor = conn.cursor()
        cursor.execute("SELECT referrals, pending_reward, earned_reward FROM users WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        conn.close()

        if row:
            referrals, pending_reward, earned_reward = row
        else:
            referrals, pending_reward, earned_reward = 0, 0, 0

        bot_username = "Bd94earningbot"

        await update.message.reply_text(
            f"👥 Your Referral Link:\n"
            f"https://t.me/{bot_username}?start={user_id}\n\n"
            f"✅ Verified Referral: {earned_reward // 20}\n"
            f"⏳ Pending Referral: {pending_reward // 20}\n\n"
            f"💰 Verified Referral Balance: {earned_reward} Tk\n"
            f"⏳ Pending Referral Balance: {pending_reward} Tk\n\n"
            f"⚠️ রেফার রিওয়ার্ড নিয়মাবলী\n\n"
            f"🎁 প্রতি সফল রেফারে রিওয়ার্ড: ২০ টাকা\n\n"
            f"✅ আপনি যাকে রেফার করেছেন, তিনি সফলভাবে একটি উইথড্র সম্পন্ন করলে তবেই আপনার ২০ টাকার রিওয়ার্ড নিশ্চিত হবে।\n\n"
            f"⏳ ততক্ষণ পর্যন্ত রিওয়ার্ডটি Pending Reward হিসেবে থাকবে।"
        )

    elif text == "🎁 Bonus":
        await update.message.reply_text("🎁 Bonus System Coming Soon")

    elif text == "💳 Withdraw":
        # Check if user balance meets minimum withdraw criteria first
        conn = sqlite3.connect(DATABASE)
        cursor = conn.cursor()
        cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        conn.close()
        balance = row[0] if row else 0

        if balance < 150:
            await update.message.reply_text(
                f"❌ দুঃখিত, আপনার ব্যালেন্স পর্যাপ্ত নয়!\n"
                f"সর্বনিম্ন উইথড্র ১৫০ টাকা। আপনার বর্তমান ব্যালেন্স: {balance} Tk"
            )
            return

        await show_withdraw_amounts(update, context)

    elif text == "📜 History":
        conn = sqlite3.connect(DATABASE)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, amount, method, status FROM withdrawals WHERE user_id = ? ORDER BY id DESC LIMIT 5",
            (user_id,)
        )
        rows = cursor.fetchall()
        conn.close()

        if not rows:
            await update.message.reply_text("📜 No History Found")
        else:
            hist = "📜 Your Recent Withdrawals:\n\n"
            for r in rows:
                ico = "⏳" if r[3] == "pending" else "✅" if r[3] == "approved" else "❌"
                hist += f"Request #{r[0]} - {r[1]} Tk via {r[2]} ({ico} {r[3]})\n"
            await update.message.reply_text(hist)

    elif text == "📞 Support":
        await update.message.reply_text("📞 Contact Admin: @BD94_Support_Admin")

    elif text == "ℹ️ About":
        await update.message.reply_text(
            "ℹ️ BD94 EARNING BOT v2.0\n\n"
            "এটি একটি বিশ্বস্ত ও নির্ভরযোগ্য রেফারাল ব্যালেন্স আর্নিং প্ল্যাটফর্ম যা থ্রেড-সেফ SQLite ডাটাবেস ও পাইথন টেলিগ্রাম বট ফ্রেমওয়ার্ক দিয়ে পরিচালিত।"
        )
    else:
        await show_main_menu(update, "❓ অনুগ্রহ করে নিচের কীবোর্ড থেকে একটি সঠিক অপশন নির্বাচন করুন।")

# Main Bootstrapper
def main():
    # Verify environment values are supplied
    if not TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN environment variable is not defined!")

    # Initialize Sqlite tables
    init_db()

    # Start Render Port-Binding HTTP Web Server daemon
    web_thread = threading.Thread(target=run_web_server, daemon=True)
    web_thread.start()

    # Init Telegram Bot application
    app = Application.builder().token(TOKEN).build()

    # Register handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("broadcast", broadcast))
    app.add_handler(CommandHandler("show_pending", show_pending))
    app.add_handler(CommandHandler("show_withdraws", show_withdraws))
    app.add_handler(CommandHandler("approve", approve))
    app.add_handler(CommandHandler("reject", reject))

    # Catch message text inputs for custom button flows
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            buttons
        )
    )

    print("BD94 Telegram Earning Bot is up and running...")
    app.run_polling()

if __name__ == "__main__":
    main()
