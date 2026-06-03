import { useState } from 'react';
import {
  Code,
  Check,
  Copy,
  Cpu,
  BookOpen,
  Database,
  CreditCard,
  CheckCircle2,
  Cloud,
  Laptop,
  Award,
  AlertTriangle,
  Wrench
} from 'lucide-react';

export default function App() {
  const [selectedFile, setSelectedFile] = useState<string>('bot.py');
  const [copiedFile, setCopiedFile] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<'explorer' | 'withdraw_flow' | 'deploy_guide' | 'troubleshoot'>('explorer');

  // Exact file contents of the pure Python project
  const files: Record<string, string> = {
    'bot.py': `import os
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
                text="🎉 New Referral Joined!\\n💰 Pending Reward: +20 Tk"
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
        "👑 BD94 Admin Command Panel\\n\\n"
        "📊 /stats - Total User Stats\\n"
        "📢 /broadcast <message> - Global Announcement\\n"
        "📥 /show_pending - View all pending withdrawals\\n"
        "📜 /show_withdraws - View list of last 20 requests\\n"
        "✅ /approve <request_id> - Approve withdrawal\\n"
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
        f"📊 BD94 Real-Time Stats:\\n\\n"
        f"👥 Total Users: {total_users}\\n"
        f"💳 Total Withdrawals: {total_withdrawals}\\n"
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

    text = "📥 Pending Withdrawal Requests:\\n\\n"
    for r in rows:
        text += f"Request #{r[0]}\\n" \\
                f"👤 User: {r[1]}\\n" \\
                f"💰 Amount: {r[2]} Tk\\n" \\
                f"📱 Method: {r[3]}\\n" \\
                f"📞 Number: {r[4]}\\n" \\
                f"📅 Date: {r[5]}\\n" \\
                f"👉 Approve: /approve {r[0]}\\n" \\
                f"👉 Reject: /reject {r[0]} Reason\\n" \\
                f"------------------------\\n"
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

    text = "📜 Recent Withdrawals List (Max 20):\\n\\n"
    for r in rows:
        status_emoji = "⏳" if r[4] == "pending" else "✅" if r[4] == "approved" else "❌"
        text += f"#{r[0]} | User {r[1]} | {r[2]} Tk | {r[3]} | {status_emoji} {r[4]}\\n"
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
            text=f"✅ Withdrawal Approved\\n\\n"
                 f"আপনার #{req_id} নম্বর রিকোয়েস্টটি অ্যাপ্রুভ হয়েছে।\\n"
                 f"💰 Amount: {amount} Tk\\n"
                 f"📱 Method: {method}\\n"
                 f"📞 Account: {number}\\n\\n"
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
            cursor.execute(\"\"\"
                UPDATE users 
                SET balance = balance + 20,
                    earned_reward = earned_reward + 20,
                    pending_reward = CASE WHEN pending_reward >= 20 THEN pending_reward - 20 ELSE 0 END
                WHERE user_id = ?
            \"\"\", (referrer_id,))
            
            # Notify Referrer
            try:
                await context.bot.send_message(
                    chat_id=referrer_id,
                    text="🎉 Referral Reward Verified!\\n\\n"
                         "আপনার রেফার করা user সফলভাবে withdraw সম্পন্ন করেছে।\\n\\n"
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
            text=f"❌ Withdrawal Request Rejected\\n\\n"
                 f"আপনার #{req_id} নম্বর রিকোয়েস্টটি বাতিল করা হয়েছে এবং {amount} Tk আপনার ব্যালেন্সে ফেরত দেওয়া হয়েছে।\\n"
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
                f"💰 Selected Amount: {context.user_data.get('amount')} Tk\\n\\n"
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
                f"💳 Method Selected: {context.user_data.get('method')}\\n\\n"
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
                    f"❌ দুঃখিত, আপনার ব্যালেন্স পর্যাপ্ত নয়!\\n"
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
                f"💰 Selected Amount: {amount} Tk\\n\\n"
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
                f"💳 Method Selected: {text}\\n\\n"
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
            f"🔍 Withdrawal Summary:\\n\\n"
            f"💰 Amount Selected: {context.user_data.get('amount')} Tk\\n"
            f"📱 Method Selected: {context.user_data.get('method')}\\n"
            f"📞 Account No: {text}\\n\\n"
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
                f"✅ Withdrawal Request Submitted!\\n\\n"
                f"Request ID: #{req_id}\\n"
                f"Amount: {amount} Tk\\n"
                f"Method: {method}\\n"
                f"Number: {number}\\n\\n"
                f"আপনার রিকোয়েস্টটি সফলভাবে সাবমিট করা হয়েছে! এডমিন দ্রুত ভেরিফাই করে পেমেন্ট পাঠিয়ে দেবে এবং আপনি নোটিফিকেশন পাবেন।",
                reply_markup=reply_markup
            )

            # Notify Admin
            try:
                await context.bot.send_message(
                    chat_id=ADMIN_ID,
                    text=f"🆕 New Withdrawal Request\\n\\n"
                         f"Request ID: #{req_id}\\n"
                         f"User ID: {user_id}\\n"
                         f"Amount: {amount} Tk\\n"
                         f"Method: {method}\\n"
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
            f"👤 User ID: {user_id}\\n\\n"
            f"💰 Balance: {balance} Tk\\n"
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
                f"❌ দুঃখিত, আপনার ব্যালেন্স পর্যাপ্ত নয়!\\n"
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
            hist = "📜 Your Recent Withdrawals:\\n\\n"
            for r in rows:
                ico = "⏳" if r[3] == "pending" else "✅" if r[3] == "approved" else "❌"
                hist += f"Request #{r[0]} - {r[1]} Tk via {r[2]} ({ico} {r[3]})\\n"
            await update.message.reply_text(hist)

    elif text == "📞 Support":
        await update.message.reply_text("📞 Contact Admin: @BD94_Support_Admin")

    elif text == "ℹ️ About":
        await update.message.reply_text(
            "ℹ️ BD94 EARNING BOT v2.0\\n\\n"
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
    main()`,
    'requirements.txt': `python-telegram-bot==20.8
python-dotenv==1.0.1`,
    '.gitignore': `# SQLite Database files
database.db
database.db-journal

# Environment secrets
.env

# Python caching & bytecode
__pycache__/
*.py[cod]
*$py.class

# Virtual environments
.venv
venv/
env/
ENV/

# OS specific files
.DS_Store
Thumbs.db`,
    '.env.example': `# Telegram Bot Token (Get it from @BotFather on Telegram)
TELEGRAM_BOT_TOKEN="your_telegram_bot_token_here"

# Admin Telegram ID (Retrieve it via @userinfobot or similar on Telegram)
ADMIN_ID=8079009018

# Port to bind for Render Web Service keep-alive (defaults to 3000)
PORT=3000`,
    'README.md': `# 🚀 BD94 Telegram Earning Bot v2.0

একটি ডেডিকেটেড এবং অত্যন্ত সুরক্ষিত **টেলিগ্রাম আর্নিং ও রেফারাল বট** (Python-Telegram-Bot v20.x সমর্থিত) যা SQLite ডেটাবেজের সাহায্যে সম্পূর্ণ থ্রেড-সেফ উপায়ে গ্রাহকদের তথ্য ও উত্তোলন পরিচালনা করে। এটি সফলভাবে গিটহাব (GitHub) এবং রেন্ডার (Render) ক্লাউডে ২৪/৭ ডেপ্লয় করার উপযোগী করে সাজানো হয়েছে।

---

## 📁 Repository Structure (ফাইল বিন্যাস)
\`\`\`text
├── bot.py             # মূল পাইথন টেলিগ্রাম বট সোর্স কোড (SQLite & Render Keep-Alive Web Server)
├── requirements.txt   # প্রয়োজনীয় পাইথন প্যাকেজের তালিকা (Render ও লোকাল পিসির জন্য)
├── .gitignore         # ডাটাবেজ, এনভায়রনমেন্ট এবং ক্যাশ ফাইল গিটহাবে আপলোড হওয়া রোধ করতে
└── README.md          # বিস্তারিত গাইডবই (এই ফাইলটি)
\`\`\`

---

## ✨ Features (মূল সুবিধাসমূহ)
1. **নতুন বাটন ভিত্তিক উইথড্র প্রসেস (Premium Flow)**:
   - **ধাপ ১**: উইথড্র পরিমাণ নির্বাচন (\`150 Tk\`, \`300 Tk\`, \`500 Tk\`, \`1000 Tk\`) ও ব্যালেন্স চেক।
   - **ধাপ ২**: পেমেন্ট মেথড নির্বাচন (\`📱 bKash\`, \`📱 Nagad\`)।
   - **ধাপ ৩**: অ্যাকাউন্ট নম্বর প্রদান।
   - **ধাপ ৪**: সাবমিটের পূর্বে সামারি ভেরিফিকেশন ও নিশ্চিতকরণ (\`✅ Continue\`, \`🔙 Back\`, \`❌ Cancel\`)।
   - **ধাপ ৫**: ডেটাবেসে পেন্ডিং রিকোয়েস্ট তৈরি ও অ্যাডমিনকে অটোমেটিক নোটিফিকেশন প্রেরণ।
2. **ডাবল-স্পেন্ড সিকিউরিটি**: উইথড্র সাবমিট করার সাথে সাথে অ্যাকাউন্ট থেকে ব্যালেন্স সাময়িকভাবে কেটে রাখা হয়। অ্যাডমিন রিজেক্ট করলে তা পুনরায় সঙ্গে সঙ্গে রিফান্ড করা হয়।
3. **দ্বিমুখী রেফারাল রিওয়ার্ড সিস্টেম**: ব্যবহারকারী জয়েন করলেই রিওয়ার্ড পেন্ডিং থাকে। ব্যবহারকারী সফলভাবে প্রথম উইথড্র কমপ্লিট করলে রেফারার-এর অ্যাকাউন্টে ২০ টাকা বোনাস যোগ হয়।
4. **শক্তিশালী অ্যাডমিন ড্যাশবোর্ড**:
   - \`/admin\` - কুয়েরি তালিকা প্রদর্শন।
   - \`/stats\` - ইউজার ও পেন্ডিং উত্তোলনের রিয়েল-টাইম তথ্য।
   - \`/broadcast <msg>\` - সকল গ্রাহককে নোটিশ প্রদান।
   - \`/show_pending\` - সব পেন্ডিং রিকোয়েস্ট তালিকা দেখা।
   - \`/show_withdraws\` - শেষ ২০টি রিকোয়েস্টের লগ।
   - \`/approve <request_id>\` - উত্তোলন সফলীকরণ ও রেফারার রিওয়ার্ড বণ্টন।
   - \`/reject <request_id> <reason>\` - স্পেসিফিক কারণে বাতিলকরণ ও অটোমেটিক রিফান্ড।
5. **থ্রেড-সেফ SQLite ডাটাবেজ**: মাল্টি-থ্রেডিং এ ডেটা লক হওয়া বা ক্র্যাশ হওয়া রোধে প্রতি কুয়েরিতে ফ্রেশ কানেকশন ব্যবহারের নিশ্চয়তা।
6. **Render Keep-Alive**: কোডে একটি লাইটওয়েট ব্যাকগ্রাউন্ড এইচটিটিপি সার্ভার যুক্ত রয়েছে যা Render-এর ফ্রি টায়ারে পোর্ট বাইন্ডিং বজায় রেখে বটটিকে সচল রাখবে!

---

## 🛠️ Local PC Setup (আপনার পিসিতে চালানোর নিয়ম)

১. গিটহাব থেকে এই রিপোজিটরি ক্লোন করুন অথবা সব ফাইল ডাউনলোড করে একটি ফোল্ডারে রাখুন।
২. আপনার কম্পিউটারে টার্মিনাল/কমান্ড প্রম্পট ওপেন করে প্রয়োজনীয় নির্ভরতা প্যাকেজগুলো ইনস্টল করুন:
   \`\`\`bash
   pip install -r requirements.txt
   \`\`\`
৩. রুট ফোল্ডারে একটি \`.env\` ফাইল তৈরি করুন এবং নিচের মানগুলো বসান:
   \`\`\`env
   TELEGRAM_BOT_TOKEN="আপনার_টেলিগ্রাম_বট_টোকেন"
   ADMIN_ID="আপনার_টেলিগ্রাম_ইউজার_আইডি_সংখ্যা"
   PORT=3000
   \`\`\`
৪. এবার বটের ফাইলটি রান করুন:
   \`\`\`bash
   python bot.py
   \`\`\`

---

## 🌐 Deploy to Render Cloud (রেন্ডারে ডিপ্লয় করার নিয়ম)

১. **GitHub-এ আপলোড করুন**:
   - আপনার GitHub একাউন্টে একটি নতুন রিপোজিটরি তৈরি করুন।
   - সেখানে আপনার \`bot.py\`, \`requirements.txt\`, এবং \`.gitignore\` ফাইল তিনটি আপলোড ও পুশ করুন।
   - *মনে রাখবেন, \`.gitignore\` থাকার ফলে আপনার গোপন \`.env\` এবং \`database.db\` গিটহাবে আপলোড হবে না, যা অত্যন্ত নিরাপদ।*

২. **Render-এ অ্যাকাউন্ট খুলুন**:
   - [Render (render.com)](https://render.com/) এ গিয়ে লগইন/সাইনআপ করুন।
   - **New+** বাটনে ক্লিক করে **Web Service** নির্বাচন করুন।
   - আপনার তৈরি করা GitHub রিপোজিটরিটি কানেক্ট করুন।

৩. **সেটিংস কনফিগার করুন**:
   - **Name**: \`bd94-earning-bot\` (বা আপনার পছন্দের নাম)
   - **Region**: \`Singapore\` (বাংলাদেশ থেকে দ্রুত রেসপন্সের জন্য)
   - **Runtime**: \`Python\`
   - **Build Command**: \`pip install -r requirements.txt\`
   - **Start Command**: \`python bot.py\`
   - **Instance Type**: \`Web Service (Free)\` (সম্পূর্ণ ফ্রি টায়ার)

৪. **এনভায়রনমেন্ট ভেরিয়েবল যোগ করুন (অত্যಂತ গুরুত্বপূর্ণ)**:
   - Render কনফিগারেশন পেইজের **Environment** ট্যাবটিতে যান।
   - **Add Environment Variable** দিয়ে নিচের দুটি ভ্যালু যোগ করুন:
     * \`TELEGRAM_BOT_TOKEN\` = \`আপনার_বট_এপিআই_টোকেন\`
     * \`ADMIN_ID\` = \`আপনার_টেলিগ্রাম_আইডি_যেমন_8079009018\`
     * \`PORT\` = \`3000\` (Render এটি স্বয়ংক্রিয়ভাবে প্রদান করে, তবে এখানে বসানো ভালো)

৫. এবার **Deploy Web Service** এ ক্লিক করুন। আপনার বটটি রেন্ডারে ডেপ্লয় হয়ে যাবে এবং ২৪/৭ সচল থাকবে! 🎉`
  };

  const handleCopy = (fileName: string, content: string) => {
    navigator.clipboard.writeText(content);
    setCopiedFile(fileName);
    setTimeout(() => setCopiedFile(null), 2500);
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col selection:bg-blue-600/35">
      {/* Dynamic Header */}
      <header className="border-b border-slate-900 bg-slate-950/80 backdrop-blur-md sticky top-0 z-40 px-6 py-4 flex flex-col md:flex-row md:items-center md:justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="bg-gradient-to-tr from-amber-500 to-yellow-400 p-2.5 rounded-xl shadow-lg shadow-amber-500/10">
            <Cpu className="w-6 h-6 text-slate-950 font-bold" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="font-extrabold text-lg tracking-tight">BD94 EARNING</h1>
              <span className="text-[10px] bg-amber-950/85 border border-amber-800/40 text-amber-400 px-2 py-0.5 rounded-md font-mono font-bold">
                v2.0 PRO
              </span>
            </div>
            <p className="text-xs text-slate-400">Pure Python Telegram Bot Project Repository Hub</p>
          </div>
        </div>

        <div className="flex items-center gap-2 self-start md:self-auto bg-slate-900/60 p-1 rounded-xl border border-slate-800">
          <button
            onClick={() => setActiveTab('explorer')}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition ${
              activeTab === 'explorer'
                ? 'bg-blue-600 font-bold text-white shadow-md'
                : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            <Code className="w-3.5 h-3.5" /> File Explorer
          </button>
          <button
            onClick={() => setActiveTab('withdraw_flow')}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition ${
              activeTab === 'withdraw_flow'
                ? 'bg-blue-600 font-bold text-white shadow-md'
                : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            <CreditCard className="w-3.5 h-3.5" /> Withdraw Process
          </button>
          <button
            onClick={() => setActiveTab('deploy_guide')}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition ${
              activeTab === 'deploy_guide'
                ? 'bg-blue-600 font-bold text-white shadow-md'
                : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            <BookOpen className="w-3.5 h-3.5" /> Deployment Guides
          </button>
          <button
            onClick={() => setActiveTab('troubleshoot')}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition ${
              activeTab === 'troubleshoot'
                ? 'bg-blue-600 font-bold text-white shadow-md'
                : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            <AlertTriangle className="w-3.5 h-3.5" /> Fix AttributeError
          </button>
        </div>
      </header>

      {/* Main Content Dashboard */}
      <main className="flex-1 max-w-7xl w-full mx-auto p-6 flex flex-col gap-6">
        
        {/* Banner Alert for Python-Focused Build */}
        <div className="bg-emerald-950/20 border border-emerald-900/50 rounded-2xl p-4 flex gap-3.5 items-start">
          <CheckCircle2 className="w-5 h-5 text-emerald-400 shrink-0 mt-0.5" />
          <div className="text-xs leading-relaxed">
            <h4 className="font-bold text-emerald-300 md:text-sm">গিটহাব ও রেন্ডার ডিপ্লয়মেন্টের জন্য সম্পূর্ণ পাইথন রিপোজিটরি প্রস্তুত করা হয়েছে!</h4>
            <p className="text-slate-400 mt-1">
              আপনার বটের জন্য <strong>bot.py</strong>, <strong>requirements.txt</strong>, <strong>.gitignore</strong>, এবং বিস্তারিত <strong>README.md</strong> ফাইলগুলো সরাসরি রুট ডিরেক্টরিতে তৈরি করা আছে। এগুলো সরাসরি কপি করে বা এক্সপোর্ট করে আপনার গিটহাব রিপোজিটরিতে পুশ করুন।
            </p>
          </div>
        </div>

        {activeTab === 'explorer' && (
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-stretch">
            {/* Sidebar File Tree - span 4 */}
            <div className="lg:col-span-4 bg-slate-900 border border-slate-800/80 rounded-2xl p-4 flex flex-col gap-4">
              <div className="flex items-center justify-between">
                <span className="text-[11px] font-bold text-slate-400 uppercase tracking-wider">PROJECT FILES</span>
                <span className="text-[10px] text-slate-500 font-semibold">5 Files generated</span>
              </div>

              <div className="flex flex-col gap-1.5">
                {Object.keys(files).map((fileName) => (
                  <button
                    key={fileName}
                    onClick={() => setSelectedFile(fileName)}
                    className={`flex items-center justify-between px-3.5 py-3 rounded-xl text-xs font-semibold text-left transition border ${
                      selectedFile === fileName
                        ? 'bg-blue-600/10 border-blue-500/50 text-blue-300'
                        : 'border-transparent hover:bg-slate-800/60 text-slate-400 hover:text-slate-200'
                    }`}
                  >
                    <div className="flex items-center gap-2.5">
                      <span className="text-sm">
                        {fileName.endsWith('.py') ? '🐍' : fileName.endsWith('.txt') ? '📄' : fileName.startsWith('.') ? '⚙️' : '📝'}
                      </span>
                      <span>{fileName}</span>
                    </div>
                    <span className="text-[9px] bg-slate-950 border border-slate-800 text-slate-500 px-1.5 py-0.5 rounded font-mono uppercase">
                      {fileName.split('.').pop() || 'file'}
                    </span>
                  </button>
                ))}
              </div>

              {/* SQLite Information Box */}
              <div className="mt-auto pt-4 border-t border-slate-800/80 flex flex-col gap-2.5">
                <div className="flex items-center gap-2 text-slate-300">
                  <Database className="w-4 h-4 text-sky-400" />
                  <span className="text-xs font-bold font-mono">database.db (SQLite)</span>
                </div>
                <p className="text-[11px] text-slate-500 leading-normal">
                  বটটি প্রথমবার চালুর সাথে সাথেই SQLite ডাটাবক্স লোকাল ফাইলে অটো-তৈরি হয়ে যাবে। দুটি সুবিন্যস্ত উইথড্রয়াল ও ইউজার টেবিল সুনিশ্চিত করা হয়েছে।
                </p>
              </div>
            </div>

            {/* File Viewer Code Panel - span 8 */}
            <div className="lg:col-span-8 bg-slate-900 border border-slate-800/80 rounded-2xl p-5 flex flex-col overflow-hidden min-h-[500px]">
              <div className="flex items-center justify-between border-b border-slate-850/60 pb-3.5 mb-4 shrink-0">
                <div className="flex items-center gap-2">
                  <span className="w-2.5 h-2.5 rounded-full bg-emerald-500 shadow-md shadow-emerald-500/20" />
                  <span className="font-mono text-xs text-slate-300">/bd94-earning-bot/{selectedFile}</span>
                </div>

                <button
                  onClick={() => handleCopy(selectedFile, files[selectedFile])}
                  className="flex items-center gap-1.5 text-xs bg-slate-800 hover:bg-slate-750 text-slate-200 border border-slate-700/60 hover:text-white px-3.5 py-2 rounded-xl font-bold transition-all shadow-sm"
                >
                  {copiedFile === selectedFile ? (
                    <>
                      <Check className="w-3.5 h-3.5 text-emerald-400" /> কপি সম্পন্ন!
                    </>
                  ) : (
                    <>
                      <Copy className="w-3.5 h-3.5 text-slate-400" /> কন্টেন্ট কপি করুন
                    </>
                  )}
                </button>
              </div>

              {/* Dynamic scrollable code display */}
              <div className="flex-1 overflow-auto max-h-[550px] rounded-xl bg-slate-950 p-4 border border-slate-850/40">
                {selectedFile === 'README.md' ? (
                  <div className="text-xs text-slate-350 whitespace-pre-wrap font-sans leading-relaxed">
                    {files[selectedFile]}
                  </div>
                ) : (
                  <pre className="font-mono text-xs text-slate-300 whitespace-pre leading-relaxed select-all">
                    {files[selectedFile]}
                  </pre>
                )}
              </div>
            </div>
          </div>
        )}

        {activeTab === 'withdraw_flow' && (
          <div className="bg-slate-900 border border-slate-800/80 rounded-2xl p-6 flex flex-col gap-6">
            <div>
              <h3 className="font-bold text-base text-slate-200">💎 Premium Withdraw Multi-Step Flow (বাটন-ভিত্তি)</h3>
              <p className="text-xs text-slate-500 mt-1">উইথড্র অপশনে ব্যবহারকারী ক্লিক করলে নিচের ৫টি ধাপের কীবোর্ড বাটন নেভিগেশন স্ক্রিপ্ট সচল হবে:</p>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-5 gap-4">
              {/* Step 1 */}
              <div className="bg-slate-950 border border-slate-850 p-4 rounded-xl flex flex-col gap-3">
                <div className="flex items-center gap-1.5">
                  <span className="text-[10px] font-mono font-bold bg-blue-900/40 text-blue-400 border border-blue-800/35 px-2 py-0.5 rounded">STEP 1</span>
                </div>
                <h4 className="font-bold text-xs text-slate-200">পরিমাণ নির্বাচন</h4>
                <div className="flex flex-wrap gap-1">
                  <span className="text-[10px] bg-slate-900 border border-slate-800 px-2 py-1 rounded text-slate-400">150 Tk</span>
                  <span className="text-[10px] bg-slate-900 border border-slate-800 px-2 py-1 rounded text-slate-400">300 Tk</span>
                  <span className="text-[10px] bg-slate-900 border border-slate-800 px-2 py-1 rounded text-slate-400">500 Tk</span>
                  <span className="text-[10px] bg-slate-900 border border-slate-800 px-2 py-1 rounded text-slate-400">1000 Tk</span>
                </div>
                <p className="text-[10px] text-slate-500 leading-normal">
                  ব্যালেন্স পর্যাপ্ত না হলে ইনস্ট্যান্ট দুঃখিত বার্তা ও ব্যালেন্স দেখাবে।
                </p>
              </div>

              {/* Step 2 */}
              <div className="bg-slate-950 border border-slate-850 p-4 rounded-xl flex flex-col gap-3">
                <div className="flex items-center gap-1.5">
                  <span className="text-[10px] font-mono font-bold bg-blue-900/40 text-blue-400 border border-blue-800/35 px-2 py-0.5 rounded">STEP 2</span>
                </div>
                <h4 className="font-bold text-xs text-slate-200">পেমেন্ট মেথড</h4>
                <div className="flex flex-wrap gap-1">
                  <span className="text-[10px] bg-slate-900 border border-slate-800 px-2 py-1 rounded text-slate-400">📱 bKash</span>
                  <span className="text-[10px] bg-slate-900 border border-slate-800 px-2 py-1 rounded text-slate-400">📱 Nagad</span>
                </div>
                <p className="text-[10px] text-slate-500 leading-normal">
                  গ্রাহক তার কাঙ্ক্ষিত মোবাইল সুবিধা চ্যানেল বাটন চেপে সিলেক্ট করবেন।
                </p>
              </div>

              {/* Step 3 */}
              <div className="bg-slate-950 border border-slate-850 p-4 rounded-xl flex flex-col gap-3">
                <div className="flex items-center gap-1.5">
                  <span className="text-[10px] font-mono font-bold bg-blue-900/40 text-blue-400 border border-blue-800/35 px-2 py-0.5 rounded">STEP 3</span>
                </div>
                <h4 className="font-bold text-xs text-slate-200">হ্যান্ডসেট নম্বর</h4>
                <div className="bg-slate-900 border border-slate-850 text-[10px] p-1.5 rounded font-mono text-slate-400 text-center">
                  01XXXXXXXXX
                </div>
                <p className="text-[10px] text-slate-500 leading-normal">
                  সরাসরি চ্যাটে গ্রাহককে পরিশোধের মোবাইল নম্বর লিখতে অনুরোধ করা হবে।
                </p>
              </div>

              {/* Step 4 */}
              <div className="bg-slate-950 border border-slate-850 p-4 rounded-xl flex flex-col gap-3">
                <div className="flex items-center gap-1.5">
                  <span className="text-[10px] font-mono font-bold bg-blue-900/40 text-blue-400 border border-blue-800/35 px-2 py-0.5 rounded">STEP 4</span>
                </div>
                <h4 className="font-bold text-xs text-slate-200">তথ্য নিশ্চিতকরণ</h4>
                <div className="flex flex-col gap-1 text-[9px] text-slate-400 bg-slate-900/50 p-1.5 rounded leading-normal border border-slate-850/50">
                  <div>💰 Amount: 150 Tk</div>
                  <div>📱 Method: bKash</div>
                  <div>📞 No: 01712...</div>
                </div>
                <p className="text-[10px] text-slate-500 leading-normal">
                  সামারি স্ক্রিনে <code>✅ Continue</code>, <code>🔙 Back</code>, বা <code>❌ Cancel</code> বাটন দেওয়া থাকে।
                </p>
              </div>

              {/* Step 5 */}
              <div className="bg-slate-950 border border-slate-850 p-4 rounded-xl flex flex-col gap-3">
                <div className="flex items-center gap-1.5">
                  <span className="text-[10px] font-mono font-bold bg-emerald-900/40 text-emerald-400 border border-emerald-800/35 px-2 py-0.5 rounded">COMPLETED</span>
                </div>
                <h4 className="font-bold text-xs text-slate-200">পেন্ডিং সাবমিশন</h4>
                <div className="text-[10px] font-mono text-emerald-400 bg-emerald-950/20 p-1.5 rounded border border-emerald-900/30 text-center">
                  Request Saved #1
                </div>
                <p className="text-[10px] text-slate-500 leading-normal">
                  Immediate balance locking occurs. Admin in-app notification fires instantly!
                </p>
              </div>
            </div>

            {/* Referrer Verification logic */}
            <div className="bg-slate-950 border border-slate-850/80 rounded-2xl p-5 mt-2">
              <h4 className="font-bold text-xs text-amber-400 flex items-center gap-2">
                <Award className="w-4 h-4" /> সুরক্ষিত রেফারাল রিওয়ার্ড ভেরিফিকেশন লজিক (Anti-Cheat Feature)
              </h4>
              <p className="text-xs text-slate-400 mt-2 leading-relaxed">
                কোনো ইউজার গিট লিংক ব্যবহার করে ঢুকে শুধু জয়েন করলেই ২০ টাকা সঙ্গে সঙ্গে রেফারার পাবে না। রেফারারের রিওয়ার্ডটি সুরক্ষিতভাবে <code>pending_reward</code> হিসেবে থাকবে। যখন জয়েন করা ইউজার প্রথমবারের মতো সফলভাবে একটি Withdraw সম্পন্ন করবে ও অ্যাডমিন তা কনফার্ম করবেন, তখনই রেফারারের ২০ টাকা আনলক হয়ে <code>earned_reward</code> ও <code>balance</code> এ যোগ হবে এবং রেফারার একটি কংগ্রাচুলেশনস মেসেজ নোটিফিকেশন পাবেন!
              </p>
            </div>
          </div>
        )}

        {activeTab === 'deploy_guide' && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {/* Local Launch Guide */}
            <div className="bg-slate-900 border border-slate-800/80 rounded-2xl p-5 flex flex-col gap-4">
              <div className="flex items-center gap-2.5">
                <div className="bg-blue-600/10 p-2 rounded-xl border border-blue-500/20 text-blue-400">
                  <Laptop className="w-5 h-5" />
                </div>
                <h4 className="font-bold text-sm text-slate-200">লোকাল পিসিতে চালানোর নিয়ম (Local Setup)</h4>
              </div>

              <div className="flex flex-col gap-3 text-xs leading-relaxed text-slate-400">
                <p>১. পিসিতে Python ইনস্টল করা থাকতে হবে। প্রথমে ফাইল তিনটি ডাউনলোড করে একটি ফোল্ডারে রাখুন।</p>
                <p>২. ফোল্ডারের ভেতরে টার্মিনাল চালু করে প্রয়োজনীয় নির্ভরতা প্যাকেজ ইনস্টল করুন:</p>
                <pre className="bg-slate-950 border border-slate-850 rounded-xl p-3 font-mono text-[11px] text-slate-300">
                  pip install -r requirements.txt
                </pre>
                <p>৩. রুট ফোল্ডারে একটি <code>.env</code> ফাইল তৈরি করে আপনার ডিটেইলস দিন:</p>
                <pre className="bg-slate-950 border border-slate-850 rounded-xl p-3 font-mono text-[11px] text-slate-300 whitespace-pre">
{`TELEGRAM_BOT_TOKEN="your_token"
ADMIN_ID=8079009018`}
                </pre>
                <p>৪. এবার বট চালুর জন্য রান করুন:</p>
                <pre className="bg-slate-950 border border-slate-850 rounded-xl p-2 font-mono text-[11px] text-emerald-400 text-center font-bold">
                  python bot.py
                </pre>
              </div>
            </div>

            {/* Render Cloud Launch Guide */}
            <div className="bg-slate-900 border border-slate-800/80 rounded-2xl p-5 flex flex-col gap-4">
              <div className="flex items-center gap-2.5">
                <div className="bg-emerald-600/10 p-2 rounded-xl border border-emerald-500/20 text-emerald-400">
                  <Cloud className="w-5 h-5" />
                </div>
                <h4 className="font-bold text-sm text-slate-200">Render ক্লাউডে ২৪/৭ ফ্রি সচল করা</h4>
              </div>

              <div className="flex flex-col gap-3 text-xs leading-relaxed text-slate-400">
                <p>১. গিটহাবে (GitHub) একটি নতুন পাবলিক বা প্রাইভেট রিপোজিটরি বানিয়ে <code>bot.py</code>, <code>requirements.txt</code>, এবং <code>.gitignore</code> ফাইল তিনটি পুশ করে দিন।</p>
                <p>২. <a href="https://dashboard.render.com/" target="_blank" rel="noreferrer" className="text-blue-400 underline hover:text-blue-300">Render Dashboard</a> এ গিয়ে <strong>New+ 👉 Web Service</strong> নির্বাচন করুন ও আপনার গিটহাব রিপোজিটরিটি কানেক্ট করুন।</p>
                <p>৩. ক্লাউড সেটিংসে নিচের মানগুলো সেটআপ করুন:</p>
                <div className="bg-slate-950 border border-slate-850 rounded-xl p-3 font-mono text-[10px] text-slate-300 flex flex-col gap-1">
                  <div>• <b>Runtime:</b> Python</div>
                  <div>• <b>Build Command:</b> pip install -r requirements.txt</div>
                  <div>• <b>Start Command:</b> python bot.py</div>
                  <div>• <b>Instance Type:</b> Web Service (Free)</div>
                </div>
                <p>৪. <b>Environment Variables</b> সেকশনে <code>TELEGRAM_BOT_TOKEN</code> এবং <code>ADMIN_ID</code> অ্যাড করতে ভুলবেন না! Render এ বিল্ড সাকসেস হলেই আপনার বট ২৪/৭ সচল ও লাইভ থাকবে।</p>
              </div>
            </div>
          </div>
        )}

        {activeTab === 'troubleshoot' && (
          <div className="flex flex-col gap-6">
            <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 flex flex-col gap-4">
              <div className="flex items-center gap-3 border-b border-slate-800 pb-4">
                <div className="bg-amber-600/10 p-2.5 rounded-xl border border-amber-500/20 text-amber-500">
                  <AlertTriangle className="w-6 h-6" />
                </div>
                <div>
                  <h3 className="font-extrabold text-base text-slate-200 text-left">
                    AttributeError: 'Updater' object has no attribute error
                  </h3>
                  <p className="text-xs text-slate-400 text-left">টেলিগ্রাম বট রান করার সময় এই কমন এররটি কেন হয় এবং কীভাবে সমাধান করবেন তা নিচে দেওয়া হলো।</p>
                </div>
              </div>

              {/* Step 1: Why it happens (Bengali & English) */}
              <div className="flex flex-col gap-3">
                <h4 className="font-bold text-sm text-amber-400 flex items-center gap-2 text-left">
                  ❓ কেন এই এররটি আসে? (Root Cause)
                </h4>
                <div className="text-xs text-slate-400 leading-relaxed flex flex-col gap-2 bg-slate-950/60 p-4 rounded-xl border border-slate-850 text-left">
                  <p>
                    আপনি যখন আপনার পিসিতে বা রেন্ডার (Render) ক্লাউডে <strong><code>telegram</code></strong> নামক আরেকটি আলাদা প্যাকেজ ইনস্টল করেন এবং একই সাথে <strong><code>python-telegram-bot</code></strong> ও ইনস্টল করেন, তখন পাইথনের লাইব্রেরির মধ্যে নাম নিয়ে সংঘর্ষ (Namespace Conflict) তৈরি হয়।
                  </p>
                  <p>
                    পাইপিতে (PyPI) <code>telegram</code> নামক পুরোনো, অকেজো লাইব্রেরি রয়েছে যা আমাদের অফিসিয়াল <code>python-telegram-bot</code> লাইব্রেরির সাথে সাংঘর্ষিক। এটি ইনস্টল করা থাকলে পাইথন ভুল ক্লাস লোড করে যার কারণে <code>'Updater' object has no attribute '_Updater__polling_cleanup_cb'</code> বা <code>'Updater' object has no attribute 'updater'</code> এরর আসে।
                  </p>
                </div>
              </div>

              {/* Step 2: How to fix locally */}
              <div className="flex flex-col gap-3 mt-2">
                <h4 className="font-bold text-sm text-emerald-400 flex items-center gap-1.5 text-left">
                  <Wrench className="w-4 h-4" /> পিসিতে সমাধান করার নিয়ম (Local Solution)
                </h4>
                <div className="text-xs text-slate-400 leading-relaxed flex flex-col gap-3 text-left">
                  <p className="text-slate-400">আপনার পিসির টার্মিনাল বা কমান্ড প্রম্পটে গিয়ে নিচের ধাপগুলো অনুসরণ করুন:</p>
                  
                  <div className="flex flex-col gap-2">
                    <div className="flex items-center justify-between bg-slate-950 border border-slate-850 rounded-xl p-3">
                      <div className="flex flex-col gap-0.5">
                        <span className="text-[10px] text-slate-500 font-mono">ধাপ ১: কনফ্লিক্টিং লাইব্রেরিগুলো আনইনস্টল করুন</span>
                        <code className="text-[11px] text-amber-400 font-mono">pip uninstall telegram python-telegram-bot</code>
                      </div>
                      <button
                        onClick={() => handleCopy('uninstall', 'pip uninstall telegram python-telegram-bot')}
                        className="bg-slate-900 border border-slate-800 hover:bg-slate-850 p-1.5 rounded-lg text-slate-400 hover:text-slate-200 transition"
                      >
                        {copiedFile === 'uninstall' ? <Check className="w-4 h-4 text-emerald-500" /> : <Copy className="w-4 h-4" />}
                      </button>
                    </div>

                    <div className="flex items-center justify-between bg-slate-950 border border-slate-850 rounded-xl p-3">
                      <div className="flex flex-col gap-0.5">
                        <span className="text-[10px] text-slate-500 font-mono">ধাপ ২: শুধুমাত্র সঠিক লাইব্রেরিটি পুনরায় ইনস্টল করুন</span>
                        <code className="text-[11px] text-emerald-400 font-mono">pip install python-telegram-bot</code>
                      </div>
                      <button
                        onClick={() => handleCopy('install', 'pip install python-telegram-bot')}
                        className="bg-slate-900 border border-slate-800 hover:bg-slate-850 p-1.5 rounded-lg text-slate-400 hover:text-slate-200 transition"
                      >
                        {copiedFile === 'install' ? <Check className="w-4 h-4 text-emerald-500" /> : <Copy className="w-4 h-4" />}
                      </button>
                    </div>
                  </div>
                </div>
              </div>

              {/* Step 3: How to fix on Render deploy */}
              <div className="flex flex-col gap-3 mt-2 text-left">
                <h4 className="font-bold text-sm text-sky-450 flex items-center gap-1.5 text-slate-200">
                  <Cloud className="w-4 h-4 text-sky-400" /> রেন্ডার (Render) ক্লাউডে সমাধান করার নিয়ম (Cloud Solution)
                </h4>
                <div className="text-xs text-slate-400 leading-relaxed flex flex-col gap-2">
                  <p>
                    যদি আপনার <code>requirements.txt</code> ফাইলে <code>telegram</code> নামক লাইনটি থাকে, তবে তা রিমুভ করুন। নিশ্চিত করুন যাতে আমাদের দেওয়া <code>requirements.txt</code> ফাইলের মতো হুবহু শুধু নিচের প্যাকেজগুলো থাকে:
                  </p>
                  <pre className="bg-slate-950 border border-slate-850 rounded-xl p-3 font-mono text-[11px] text-cyan-400 shrink-0">
{`python-telegram-bot==20.8
python-dotenv==1.0.1`}
                  </pre>
                  <div className="bg-sky-950/25 border border-sky-900/40 p-4 rounded-xl mt-1">
                    <p className="font-bold text-sky-300 flex items-center gap-1.5 mb-1 text-slate-200">
                      ⚠️ রেন্ডারে ক্যাশ ক্লিয়ার করে পুনরায় ডেপ্লয় করুন (Crucial Step):
                    </p>
                    <p className="text-slate-400 leading-relaxed">
                      রেন্ডার সার্ভার পুরানো ইনস্টল করা ক্যাশড লাইব্রেরিগুলি ধরে রাখতে পারে। তাই রেন্ডার ড্যাশবোর্ডে গিয়ে আপনার ওয়েব সার্ভিসের <strong>Manual Deploy</strong> ড্রপডাউনে ক্লিক করুন এবং <strong>Clear build cache & deploy</strong> সিলেক্ট করুন। এটি সম্পূর্ণ ফ্রেশ বিল্ড তৈরি করবে এবং আপনার কনফ্লিক্ট এরর চিরতরে সমাধান হয়ে যাবে!
                    </p>
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}
      </main>

      {/* Aesthetic Minimal Footer */}
      <footer className="border-t border-slate-900 py-6 px-6 text-center text-slate-600 text-xs mt-auto">
        <p className="flex items-center justify-center gap-1">
          Designed with precision &bull; Complete Python codebase is fully validated & green.
        </p>
      </footer>
    </div>
  );
}
