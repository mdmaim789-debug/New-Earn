"""
Telegram Bot System - Complete Implementation
Production-ready bot with referral system, ad earnings, withdrawals & admin panel
"""

import os
import logging
import asyncio
import sqlite3
import datetime
import uuid
import json
from typing import Dict, List, Optional, Tuple
from enum import Enum
from dataclasses import dataclass

# Third-party imports
from dotenv import load_dotenv
from telegram import (
    Update, 
    InlineKeyboardButton, 
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton
)
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

# ==================== CONFIGURATION ====================
class Config:
    """Configuration settings for the bot"""
    
    # Bot settings
    BOT_TOKEN = os.getenv("BOT_TOKEN", "8339289686:AAFEziEnXjpaq9RGNJQVas1vyPEl6jiHORk")
    ADMIN_IDS = json.loads(os.getenv("ADMIN_IDS", "[633765043,6375918223]"))
    
    # Database
    DB_PATH = os.getenv("DB_PATH", "bot_database.db")
    
    # Financial settings
    AD_EARNING_RATE = float(os.getenv("AD_EARNING_RATE", "5.0"))  # Per ad
    REFERRAL_BONUS = float(os.getenv("REFERRAL_BONUS", "10.0"))  # Per referral
    MINIMUM_WITHDRAWAL = float(os.getenv("MINIMUM_WITHDRAWAL", "100.0"))
    DAILY_EARNING_LIMIT = float(os.getenv("DAILY_EARNING_LIMIT", "50.0"))
    
    # Security
    AD_COOLDOWN_SECONDS = int(os.getenv("AD_COOLDOWN_SECONDS", "60"))
    MAX_ADS_PER_DAY = int(os.getenv("MAX_ADS_PER_DAY", "10"))
    
    # Payment methods (Bangladesh)
    PAYMENT_METHODS = ["bKash", "Nagad", "Rocket"]
    
    # Messages (Bangla + English)
    MESSAGES = {
        "welcome": "🎉 স্বাগতম! আপনার অ্যাকাউন্ট তৈরি করা হয়েছে।\nWelcome! Your account has been created.",
        "menu": "📱 **মেইন মেনু**\nMain Menu",
        "balance": "💰 আপনার ব্যালেন্স: {balance} টাকা",
        "earnings": "📊 আজকের আয়: {today_earned} টাকা\nমোট আয়: {total_earned} টাকা",
        "referral_link": "🤝 আপনার রেফারেল লিংক:\n`{ref_link}`",
        "referral_stats": "👥 রেফারেল স্ট্যাটস:\nমোট রেফারেল: {total}\nএকটিভ রেফারেল: {active}\nরেফারেল আয়: {earnings} টাকা",
        "withdraw_minimum": "⚠️ ন্যূনতম উত্তোলনের পরিমাণ: {amount} টাকা",
        "withdraw_success": "✅ উত্তোলন রিকোয়েস্ট সাবমিট করা হয়েছে। অ্যাডমিন অনুমোদনের জন্য অপেক্ষা করুন।",
        "admin_panel": "🔧 **অ্যাডমিন প্যানেল**\nAdmin Panel",
        "ad_watched": "🎬 বিজ্ঞাপন দেখা সম্পন্ন!\nআপনি পেয়েছেন: {amount} টাকা",
        "daily_limit_reached": "⏳ আজকের আয়ের লিমিট শেষ হয়েছে। আগামীকাল আবার চেষ্টা করুন।"
    }

# ==================== DATABASE MODELS ====================
class Database:
    """Database manager for the bot"""
    
    def __init__(self, db_path: str = Config.DB_PATH):
        self.db_path = db_path
        self.init_database()
    
    def init_database(self):
        """Initialize database with all tables"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Users table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER UNIQUE NOT NULL,
                username TEXT,
                referral_code TEXT UNIQUE NOT NULL,
                referred_by INTEGER,
                balance REAL DEFAULT 0.0,
                total_earned REAL DEFAULT 0.0,
                total_withdrawn REAL DEFAULT 0.0,
                joined_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_banned INTEGER DEFAULT 0,
                FOREIGN KEY (referred_by) REFERENCES users(id)
            )
        ''')
        
        # Earnings table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS earnings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                amount REAL NOT NULL,
                type TEXT NOT NULL, -- 'ad', 'referral', 'bonus'
                description TEXT,
                earned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        ''')
        
        # Withdrawals table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS withdrawals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                amount REAL NOT NULL,
                method TEXT NOT NULL,
                mobile_number TEXT NOT NULL,
                status TEXT DEFAULT 'pending', -- 'pending', 'approved', 'rejected', 'paid'
                transaction_id TEXT,
                requested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                processed_at TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        ''')
        
        # Ads table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS ads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT,
                earnings REAL NOT NULL,
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # User ads table (to track watched ads)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_ads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                ad_id INTEGER NOT NULL,
                watched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (ad_id) REFERENCES ads(id)
            )
        ''')
        
        # Daily limits table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS daily_limits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                date DATE NOT NULL,
                ads_watched INTEGER DEFAULT 0,
                earned_today REAL DEFAULT 0.0,
                FOREIGN KEY (user_id) REFERENCES users(id),
                UNIQUE(user_id, date)
            )
        ''')
        
        # Settings table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS settings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT UNIQUE NOT NULL,
                value TEXT NOT NULL
            )
        ''')
        
        # Insert default settings if not exists
        default_settings = [
            ('ad_earning_rate', str(Config.AD_EARNING_RATE)),
            ('referral_bonus', str(Config.REFERRAL_BONUS)),
            ('minimum_withdrawal', str(Config.MINIMUM_WITHDRAWAL)),
            ('daily_earning_limit', str(Config.DAILY_EARNING_LIMIT)),
            ('max_ads_per_day', str(Config.MAX_ADS_PER_DAY)),
            ('ad_cooldown', str(Config.AD_COOLDOWN_SECONDS))
        ]
        
        for key, value in default_settings:
            cursor.execute('INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)', (key, value))
        
        # Insert sample ads if none exist
        cursor.execute('SELECT COUNT(*) FROM ads')
        if cursor.fetchone()[0] == 0:
            sample_ads = [
                ('📱 Mobile App Review', 'Watch this 30-second ad about new mobile app', Config.AD_EARNING_RATE),
                ('🛍️ E-commerce Offer', 'Special discount offer for online shopping', Config.AD_EARNING_RATE),
                ('🎮 Game Promotion', 'Try this new exciting mobile game', Config.AD_EARNING_RATE)
            ]
            for title, desc, earnings in sample_ads:
                cursor.execute('INSERT INTO ads (title, description, earnings) VALUES (?, ?, ?)', 
                             (title, desc, earnings))
        
        conn.commit()
        conn.close()
    
    def get_connection(self):
        """Get database connection"""
        return sqlite3.connect(self.db_path)
    
    # User operations
    def register_user(self, telegram_id: int, username: str, referred_by: int = None) -> bool:
        """Register a new user"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Generate unique referral code
        referral_code = f"REF{telegram_id}{uuid.uuid4().hex[:6].upper()}"
        
        try:
            cursor.execute('''
                INSERT INTO users (telegram_id, username, referral_code, referred_by)
                VALUES (?, ?, ?, ?)
            ''', (telegram_id, username, referral_code, referred_by))
            
            # If referred by someone, give referral bonus
            if referred_by:
                self.add_referral_earning(referred_by, telegram_id)
            
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False
        finally:
            conn.close()
    
    def get_user(self, telegram_id: int) -> Optional[Dict]:
        """Get user by Telegram ID"""
        conn = self.get_connection()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM users WHERE telegram_id = ?', (telegram_id,))
        row = cursor.fetchone()
        conn.close()
        
        return dict(row) if row else None
    
    def update_balance(self, telegram_id: int, amount: float) -> bool:
        """Update user balance"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                UPDATE users 
                SET balance = balance + ?, total_earned = total_earned + ?
                WHERE telegram_id = ? AND is_banned = 0
            ''', (amount, amount, telegram_id))
            
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()
    
    # Referral operations
    def add_referral_earning(self, referrer_id: int, referred_id: int):
        """Add referral earnings to referrer"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Get referral bonus amount
        cursor.execute('SELECT value FROM settings WHERE key = "referral_bonus"')
        bonus = float(cursor.fetchone()[0])
        
        # Add to referrer's balance
        cursor.execute('''
            UPDATE users 
            SET balance = balance + ?, total_earned = total_earned + ?
            WHERE telegram_id = ?
        ''', (bonus, bonus, referrer_id))
        
        # Record the earning
        cursor.execute('''
            INSERT INTO earnings (user_id, amount, type, description)
            VALUES ((SELECT id FROM users WHERE telegram_id = ?), ?, 'referral', ?)
        ''', (referrer_id, bonus, f"Referral: {referred_id}"))
        
        conn.commit()
        conn.close()
    
    def get_referral_stats(self, telegram_id: int) -> Dict:
        """Get referral statistics for user"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Get user ID first
        cursor.execute('SELECT id FROM users WHERE telegram_id = ?', (telegram_id,))
        user = cursor.fetchone()
        
        if not user:
            return {"total": 0, "active": 0, "earnings": 0}
        
        user_id = user[0]
        
        # Count total referrals
        cursor.execute('SELECT COUNT(*) FROM users WHERE referred_by = ?', (user_id,))
        total = cursor.fetchone()[0]
        
        # Count active referrals (users who have earned something)
        cursor.execute('''
            SELECT COUNT(DISTINCT u.id) 
            FROM users u
            JOIN earnings e ON u.id = e.user_id
            WHERE u.referred_by = ?
        ''', (user_id,))
        active = cursor.fetchone()[0]
        
        # Calculate referral earnings
        cursor.execute('''
            SELECT COALESCE(SUM(amount), 0)
            FROM earnings 
            WHERE user_id = ? AND type = 'referral'
        ''', (user_id,))
        earnings = cursor.fetchone()[0] or 0
        
        conn.close()
        
        return {
            "total": total,
            "active": active,
            "earnings": earnings
        }
    
    # Ad operations
    def can_watch_ad(self, telegram_id: int) -> Tuple[bool, str]:
        """Check if user can watch ad"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        today = datetime.date.today().isoformat()
        
        # Get user ID
        cursor.execute('SELECT id FROM users WHERE telegram_id = ?', (telegram_id,))
        user = cursor.fetchone()
        
        if not user:
            return False, "User not found"
        
        user_id = user[0]
        
        # Check daily limits
        cursor.execute('''
            SELECT ads_watched, earned_today 
            FROM daily_limits 
            WHERE user_id = ? AND date = ?
        ''', (user_id, today))
        
        limit = cursor.fetchone()
        
        # Get settings
        cursor.execute('SELECT key, value FROM settings WHERE key IN ("max_ads_per_day", "daily_earning_limit")')
        settings = {row[0]: float(row[1]) for row in cursor.fetchall()}
        
        if limit:
            ads_watched, earned_today = limit
            if ads_watched >= settings['max_ads_per_day']:
                return False, "Daily ad limit reached"
            if earned_today >= settings['daily_earning_limit']:
                return False, "Daily earning limit reached"
        
        # Check cooldown
        cursor.execute('''
            SELECT MAX(watched_at) 
            FROM user_ads ua
            JOIN ads a ON ua.ad_id = a.id
            WHERE ua.user_id = ?
        ''', (user_id,))
        
        last_watched = cursor.fetchone()[0]
        if last_watched:
            last_time = datetime.datetime.fromisoformat(last_watched)
            cooldown = datetime.timedelta(seconds=Config.AD_COOLDOWN_SECONDS)
            if datetime.datetime.now() - last_time < cooldown:
                return False, f"Wait {Config.AD_COOLDOWN_SECONDS} seconds between ads"
        
        conn.close()
        return True, ""
    
    def record_ad_watch(self, telegram_id: int, ad_id: int, amount: float):
        """Record ad watch and update earnings"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        today = datetime.date.today().isoformat()
        
        # Get user ID
        cursor.execute('SELECT id FROM users WHERE telegram_id = ?', (telegram_id,))
        user_id = cursor.fetchone()[0]
        
        # Update daily limits
        cursor.execute('''
            INSERT INTO daily_limits (user_id, date, ads_watched, earned_today)
            VALUES (?, ?, 1, ?)
            ON CONFLICT(user_id, date) 
            DO UPDATE SET 
                ads_watched = ads_watched + 1,
                earned_today = earned_today + ?
        ''', (user_id, today, amount, amount))
        
        # Record ad watch
        cursor.execute('''
            INSERT INTO user_ads (user_id, ad_id)
            VALUES (?, ?)
        ''', (user_id, ad_id))
        
        # Update user balance
        cursor.execute('''
            UPDATE users 
            SET balance = balance + ?, total_earned = total_earned + ?
            WHERE telegram_id = ?
        ''', (amount, amount, telegram_id))
        
        # Record earning
        cursor.execute('''
            INSERT INTO earnings (user_id, amount, type, description)
            VALUES (?, ?, 'ad', 'Ad watch')
        ''', (user_id, amount))
        
        conn.commit()
        conn.close()
    
    def get_available_ads(self) -> List[Dict]:
        """Get list of available ads"""
        conn = self.get_connection()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM ads WHERE is_active = 1')
        ads = [dict(row) for row in cursor.fetchall()]
        conn.close()
        
        return ads
    
    # Withdrawal operations
    def create_withdrawal(self, telegram_id: int, amount: float, method: str, mobile: str) -> bool:
        """Create withdrawal request"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Check minimum withdrawal
        cursor.execute('SELECT value FROM settings WHERE key = "minimum_withdrawal"')
        min_withdrawal = float(cursor.fetchone()[0])
        
        if amount < min_withdrawal:
            return False
        
        # Check balance
        cursor.execute('SELECT balance FROM users WHERE telegram_id = ?', (telegram_id,))
        balance = cursor.fetchone()[0]
        
        if amount > balance:
            return False
        
        # Deduct from balance
        cursor.execute('''
            UPDATE users 
            SET balance = balance - ?
            WHERE telegram_id = ?
        ''', (amount, telegram_id))
        
        # Create withdrawal record
        cursor.execute('''
            INSERT INTO withdrawals (user_id, amount, method, mobile_number)
            VALUES ((SELECT id FROM users WHERE telegram_id = ?), ?, ?, ?)
        ''', (telegram_id, amount, method, mobile))
        
        conn.commit()
        conn.close()
        return True
    
    def get_withdrawals(self, status: str = None) -> List[Dict]:
        """Get withdrawals, optionally filtered by status"""
        conn = self.get_connection()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        if status:
            cursor.execute('''
                SELECT w.*, u.telegram_id, u.username 
                FROM withdrawals w
                JOIN users u ON w.user_id = u.id
                WHERE w.status = ?
                ORDER BY w.requested_at DESC
            ''', (status,))
        else:
            cursor.execute('''
                SELECT w.*, u.telegram_id, u.username 
                FROM withdrawals w
                JOIN users u ON w.user_id = u.id
                ORDER BY w.requested_at DESC
            ''')
        
        withdrawals = [dict(row) for row in cursor.fetchall()]
        conn.close()
        
        return withdrawals
    
    def update_withdrawal_status(self, withdrawal_id: int, status: str, transaction_id: str = None):
        """Update withdrawal status"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            UPDATE withdrawals 
            SET status = ?, transaction_id = ?, processed_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (status, transaction_id, withdrawal_id))
        
        # If rejected, return money to user
        if status == 'rejected':
            cursor.execute('''
                UPDATE users 
                SET balance = balance + (
                    SELECT amount FROM withdrawals WHERE id = ?
                )
                WHERE id = (SELECT user_id FROM withdrawals WHERE id = ?)
            ''', (withdrawal_id, withdrawal_id))
        
        conn.commit()
        conn.close()
    
    # Admin operations
    def get_all_users(self, limit: int = 100) -> List[Dict]:
        """Get all users"""
        conn = self.get_connection()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT * FROM users 
            ORDER BY joined_date DESC 
            LIMIT ?
        ''', (limit,))
        
        users = [dict(row) for row in cursor.fetchall()]
        conn.close()
        
        return users
    
    def get_system_stats(self) -> Dict:
        """Get system statistics"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        stats = {}
        
        # Total users
        cursor.execute('SELECT COUNT(*) FROM users')
        stats['total_users'] = cursor.fetchone()[0]
        
        # Active users today
        today = datetime.date.today().isoformat()
        cursor.execute('SELECT COUNT(DISTINCT user_id) FROM daily_limits WHERE date = ?', (today,))
        stats['active_today'] = cursor.fetchone()[0] or 0
        
        # Total earnings
        cursor.execute('SELECT COALESCE(SUM(total_earned), 0) FROM users')
        stats['total_earnings'] = cursor.fetchone()[0] or 0
        
        # Total withdrawals
        cursor.execute('SELECT COALESCE(SUM(amount), 0) FROM withdrawals WHERE status = "approved"')
        stats['total_withdrawals'] = cursor.fetchone()[0] or 0
        
        # Pending withdrawals
        cursor.execute('SELECT COALESCE(SUM(amount), 0) FROM withdrawals WHERE status = "pending"')
        stats['pending_withdrawals'] = cursor.fetchone()[0] or 0
        
        conn.close()
        return stats
    
    def update_setting(self, key: str, value: str):
        """Update system setting"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT OR REPLACE INTO settings (key, value)
            VALUES (?, ?)
        ''', (key, value))
        
        conn.commit()
        conn.close()
    
    def get_setting(self, key: str, default: str = None) -> str:
        """Get system setting"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT value FROM settings WHERE key = ?', (key,))
        result = cursor.fetchone()
        conn.close()
        
        return result[0] if result else default

# ==================== BOT HANDLERS ====================
class TelegramBot:
    """Main Telegram bot handler"""
    
    def __init__(self):
        self.db = Database()
        self.application = None
    
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        user = update.effective_user
        telegram_id = user.id
        username = user.username or user.first_name
        
        # Extract referral code from deep link
        referred_by = None
        if context.args:
            try:
                # Extract referrer's Telegram ID from referral code
                ref_code = context.args[0]
                conn = self.db.get_connection()
                cursor = conn.cursor()
                cursor.execute('SELECT telegram_id FROM users WHERE referral_code = ?', (ref_code,))
                result = cursor.fetchone()
                if result:
                    referred_by = result[0]
                conn.close()
            except:
                pass
        
        # Register user if not exists
        user_data = self.db.get_user(telegram_id)
        if not user_data:
            self.db.register_user(telegram_id, username, referred_by)
            user_data = self.db.get_user(telegram_id)
        
        # Send welcome message
        welcome_msg = Config.MESSAGES["welcome"]
        if user_data['is_banned']:
            await update.message.reply_text("🚫 আপনার অ্যাকাউন্ট বন্ধ করা হয়েছে।\nYour account has been banned.")
            return
        
        await update.message.reply_text(welcome_msg)
        await self.show_main_menu(update, context)
    
    async def show_main_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show main menu with inline keyboard"""
        keyboard = [
            [
                InlineKeyboardButton("🎁 Earn Money", callback_data="earn_money"),
                InlineKeyboardButton("👥 Refer & Earn", callback_data="referral")
            ],
            [
                InlineKeyboardButton("💰 My Account", callback_data="my_account"),
                InlineKeyboardButton("💸 Withdraw", callback_data="withdraw")
            ],
            [
                InlineKeyboardButton("📞 Support", callback_data="support"),
                InlineKeyboardButton("🔧 Admin", callback_data="admin_panel")
            ]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if update.callback_query:
            await update.callback_query.edit_message_text(
                text=Config.MESSAGES["menu"],
                reply_markup=reply_markup
            )
        else:
            await update.message.reply_text(
                text=Config.MESSAGES["menu"],
                reply_markup=reply_markup
            )
    
    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle callback queries"""
        query = update.callback_query
        await query.answer()
        
        data = query.data
        
        if data == "earn_money":
            await self.show_earn_menu(update, context)
        elif data == "referral":
            await self.show_referral_info(update, context)
        elif data == "my_account":
            await self.show_account_info(update, context)
        elif data == "withdraw":
            await self.show_withdraw_menu(update, context)
        elif data == "support":
            await self.show_support(update, context)
        elif data == "admin_panel":
            await self.show_admin_panel(update, context)
        elif data == "watch_ad":
            await self.watch_ad(update, context)
        elif data == "back_to_menu":
            await self.show_main_menu(update, context)
        elif data.startswith("withdraw_"):
            method = data.split("_")[1]
            context.user_data["withdraw_method"] = method
            await query.edit_message_text(
                text=f"💸 উত্তোলন পদ্ধতি: {method}\n\nমোবাইল নম্বর দিন:\nEnter mobile number:"
            )
        elif data.startswith("admin_"):
            await self.handle_admin_callback(update, context)
    
    async def show_earn_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show earn money menu"""
        telegram_id = update.effective_user.id
        can_watch, reason = self.db.can_watch_ad(telegram_id)
        
        keyboard = []
        if can_watch:
            keyboard.append([InlineKeyboardButton("📺 Watch Ad", callback_data="watch_ad")])
        
        keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data="back_to_menu")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        status_msg = "✅ আপনি এখন বিজ্ঞাপন দেখতে পারেন" if can_watch else f"⏳ {reason}"
        
        await update.callback_query.edit_message_text(
            text=f"🎁 **Earn Money**\n\n{status_msg}\n\nপ্রতি বিজ্ঞাপনে আয়: {Config.AD_EARNING_RATE} টাকা",
            reply_markup=reply_markup
        )
    
    async def watch_ad(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle ad watching"""
        telegram_id = update.effective_user.id
        
        # Check if can watch ad
        can_watch, reason = self.db.can_watch_ad(telegram_id)
        if not can_watch:
            await update.callback_query.edit_message_text(
                text=f"⏳ {reason}\n\n⬅️ Back to menu",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ Back", callback_data="earn_money")]
                ])
            )
            return
        
        # Get available ads
        ads = self.db.get_available_ads()
        if not ads:
            await update.callback_query.edit_message_text(
                text="📭 কোন বিজ্ঞাপন নেই\nNo ads available",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ Back", callback_data="earn_money")]
                ])
            )
            return
        
        # Select random ad
        import random
        ad = random.choice(ads)
        
        # Record ad watch
        self.db.record_ad_watch(telegram_id, ad['id'], ad['earnings'])
        
        # Show success message
        await update.callback_query.edit_message_text(
            text=f"🎬 **{ad['title']}**\n\n{ad['description']}\n\n{Config.MESSAGES['ad_watched'].format(amount=ad['earnings'])}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🎁 Watch Another", callback_data="watch_ad")],
                [InlineKeyboardButton("⬅️ Back to Menu", callback_data="back_to_menu")]
            ])
        )
    
    async def show_referral_info(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show referral information"""
        telegram_id = update.effective_user.id
        user = self.db.get_user(telegram_id)
        
        if not user:
            await update.callback_query.edit_message_text(
                text="User not found",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ Back", callback_data="back_to_menu")]
                ])
            )
            return
        
        # Get referral link
        bot_username = context.bot.username
        ref_link = f"https://t.me/{bot_username}?start={user['referral_code']}"
        
        # Get referral stats
        stats = self.db.get_referral_stats(telegram_id)
        
        message = f"{Config.MESSAGES['referral_link'].format(ref_link=ref_link)}\n\n"
        message += f"{Config.MESSAGES['referral_stats'].format(**stats)}\n\n"
        message += f"রেফারেল বোনাস: {Config.REFERRAL_BONUS} টাকা প্রতি রেফারেল"
        
        keyboard = [
            [InlineKeyboardButton("⬅️ Back", callback_data="back_to_menu")]
        ]
        
        await update.callback_query.edit_message_text(
            text=message,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    async def show_account_info(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show account information"""
        telegram_id = update.effective_user.id
        user = self.db.get_user(telegram_id)
        
        if not user:
            await update.callback_query.edit_message_text(
                text="User not found",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ Back", callback_data="back_to_menu")]
                ])
            )
            return
        
        # Get today's earnings
        today = datetime.date.today().isoformat()
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT earned_today FROM daily_limits WHERE user_id = ? AND date = ?', 
                      (user['id'], today))
        today_earned = cursor.fetchone()
        today_earned = today_earned[0] if today_earned else 0
        conn.close()
        
        message = f"👤 **Account Info**\n\n"
        message += f"Username: @{user['username'] or 'N/A'}\n"
        message += f"Joined: {user['joined_date'][:10]}\n\n"
        message += f"💰 Balance: {user['balance']:.2f} টাকা\n"
        message += f"📊 Today's Earnings: {today_earned:.2f} টাকা\n"
        message += f"🏦 Total Earned: {user['total_earned']:.2f} টাকা\n"
        message += f"💸 Total Withdrawn: {user['total_withdrawn']:.2f} টাকা"
        
        keyboard = [
            [InlineKeyboardButton("⬅️ Back", callback_data="back_to_menu")]
        ]
        
        await update.callback_query.edit_message_text(
            text=message,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    async def show_withdraw_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show withdrawal menu"""
        telegram_id = update.effective_user.id
        user = self.db.get_user(telegram_id)
        
        if not user:
            await update.callback_query.edit_message_text(
                text="User not found",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ Back", callback_data="back_to_menu")]
                ])
            )
            return
        
        min_withdrawal = float(self.db.get_setting('minimum_withdrawal', Config.MINIMUM_WITHDRAWAL))
        
        message = f"💸 **Withdraw Money**\n\n"
        message += f"💰 Available Balance: {user['balance']:.2f} টাকা\n"
        message += f"📋 Minimum Withdrawal: {min_withdrawal:.2f} টাকা\n\n"
        message += "পেমেন্ট মেথড নির্বাচন করুন:\nSelect payment method:"
        
        keyboard = []
        for method in Config.PAYMENT_METHODS:
            keyboard.append([InlineKeyboardButton(f"{method}", callback_data=f"withdraw_{method.lower()}")])
        
        keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data="back_to_menu")])
        
        await update.callback_query.edit_message_text(
            text=message,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    async def handle_withdraw_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle withdrawal input (mobile and amount)"""
        user_id = update.effective_user.id
        
        if "withdraw_method" not in context.user_data:
            await update.message.reply_text("Please select payment method first from menu.")
            return
        
        text = update.message.text.strip()
        method = context.user_data["withdraw_method"]
        
        if "withdraw_mobile" not in context.user_data:
            # First message should be mobile number
            if not text.isdigit() or len(text) != 11:
                await update.message.reply_text("❌ Invalid mobile number. Please enter 11-digit mobile number:")
                return
            
            context.user_data["withdraw_mobile"] = text
            await update.message.reply_text("💵 উত্তোলনের পরিমাণ দিন:\nEnter withdrawal amount:")
        
        elif "withdraw_amount" not in context.user_data:
            # Second message should be amount
            try:
                amount = float(text)
                min_withdrawal = float(self.db.get_setting('minimum_withdrawal', Config.MINIMUM_WITHDRAWAL))
                
                if amount < min_withdrawal:
                    await update.message.reply_text(
                        Config.MESSAGES["withdraw_minimum"].format(amount=min_withdrawal)
                    )
                    return
                
                user = self.db.get_user(user_id)
                if amount > user['balance']:
                    await update.message.reply_text("❌ Insufficient balance")
                    return
                
                # Create withdrawal request
                success = self.db.create_withdrawal(
                    user_id, amount, method.capitalize(), context.user_data["withdraw_mobile"]
                )
                
                if success:
                    await update.message.reply_text(Config.MESSAGES["withdraw_success"])
                    
                    # Notify admins
                    stats = self.db.get_system_stats()
                    for admin_id in Config.ADMIN_IDS:
                        try:
                            await context.bot.send_message(
                                admin_id,
                                f"🆕 New Withdrawal Request\n\n"
                                f"User: @{user['username'] or 'N/A'}\n"
                                f"Amount: {amount} টাকা\n"
                                f"Method: {method}\n"
                                f"Mobile: {context.user_data['withdraw_mobile']}\n\n"
                                f"Total Pending: {stats['pending_withdrawals'] + amount} টাকা"
                            )
                        except:
                            pass
                else:
                    await update.message.reply_text("❌ Withdrawal failed")
                
                # Clear withdrawal data
                context.user_data.pop("withdraw_method", None)
                context.user_data.pop("withdraw_mobile", None)
                
            except ValueError:
                await update.message.reply_text("❌ Invalid amount. Please enter a number:")
    
    async def show_support(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show support information"""
        support_info = """
📞 **Support & Contact**

For any issues or questions:

📧 Email: support@example.com
👨‍💻 Admin: @admin_username

📋 Rules:
1. No fraudulent activities
2. One account per person
3. Follow Telegram guidelines

⚠️ Note: Never share your password or OTP with anyone.
        """
        
        keyboard = [
            [InlineKeyboardButton("⬅️ Back", callback_data="back_to_menu")]
        ]
        
        await update.callback_query.edit_message_text(
            text=support_info,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    # ==================== ADMIN PANEL ====================
    async def show_admin_panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show admin panel"""
        telegram_id = update.effective_user.id
        
        if telegram_id not in Config.ADMIN_IDS:
            await update.callback_query.edit_message_text(
                text="⛔ Access Denied",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ Back", callback_data="back_to_menu")]
                ])
            )
            return
        
        stats = self.db.get_system_stats()
        
        message = f"{Config.MESSAGES['admin_panel']}\n\n"
        message += f"📊 System Stats:\n"
        message += f"• Total Users: {stats['total_users']}\n"
        message += f"• Active Today: {stats['active_today']}\n"
        message += f"• Total Earnings: {stats['total_earnings']:.2f} টাকা\n"
        message += f"• Total Withdrawn: {stats['total_withdrawals']:.2f} টাকা\n"
        message += f"• Pending Withdrawals: {stats['pending_withdrawals']:.2f} টাকা\n\n"
        message += "Select option:"
        
        keyboard = [
            [
                InlineKeyboardButton("👥 Users", callback_data="admin_users"),
                InlineKeyboardButton("💸 Withdrawals", callback_data="admin_withdrawals")
            ],
            [
                InlineKeyboardButton("⚙️ Settings", callback_data="admin_settings"),
                InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast")
            ],
            [
                InlineKeyboardButton("📊 Stats", callback_data="admin_stats"),
                InlineKeyboardButton("🎬 Manage Ads", callback_data="admin_ads")
            ],
            [InlineKeyboardButton("⬅️ Back", callback_data="back_to_menu")]
        ]
        
        await update.callback_query.edit_message_text(
            text=message,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    async def handle_admin_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle admin panel callbacks"""
        query = update.callback_query
        data = query.data
        
        if data == "admin_users":
            await self.show_admin_users(update, context)
        elif data == "admin_withdrawals":
            await self.show_admin_withdrawals(update, context)
        elif data == "admin_settings":
            await self.show_admin_settings(update, context)
        elif data == "admin_stats":
            await self.show_admin_stats(update, context)
        elif data == "admin_ads":
            await self.show_admin_ads(update, context)
        elif data == "admin_broadcast":
            await query.edit_message_text(
                text="📢 Broadcast Message\n\nSend the message you want to broadcast:"
            )
            context.user_data["awaiting_broadcast"] = True
        elif data.startswith("withdraw_action_"):
            parts = data.split("_")
            action = parts[2]
            withdraw_id = int(parts[3])
            
            if action == "approve":
                self.db.update_withdrawal_status(withdraw_id, "approved")
                await query.answer("Withdrawal approved")
            elif action == "reject":
                self.db.update_withdrawal_status(withdraw_id, "rejected")
                await query.answer("Withdrawal rejected")
            
            await self.show_admin_withdrawals(update, context)
        elif data == "admin_back":
            await self.show_admin_panel(update, context)
    
    async def show_admin_users(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show admin users list"""
        users = self.db.get_all_users(limit=20)
        
        message = "👥 **Users List**\n\n"
        for i, user in enumerate(users[:10], 1):
            status = "🚫" if user['is_banned'] else "✅"
            message += f"{i}. @{user['username'] or 'N/A'} - {user['balance']:.2f} টাকা {status}\n"
        
        if len(users) > 10:
            message += f"\n... and {len(users) - 10} more users"
        
        keyboard = [
            [InlineKeyboardButton("⬅️ Back", callback_data="admin_back")]
        ]
        
        await update.callback_query.edit_message_text(
            text=message,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    async def show_admin_withdrawals(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show admin withdrawals list"""
        withdrawals = self.db.get_withdrawals("pending")
        
        if not withdrawals:
            message = "📭 No pending withdrawals"
            keyboard = [[InlineKeyboardButton("⬅️ Back", callback_data="admin_back")]]
        else:
            message = "💸 **Pending Withdrawals**\n\n"
            for i, wd in enumerate(withdrawals[:5], 1):
                status_emoji = {
                    "pending": "⏳",
                    "approved": "✅",
                    "rejected": "❌"
                }.get(wd['status'], "❓")
                
                message += f"{i}. @{wd['username'] or 'N/A'}\n"
                message += f"   Amount: {wd['amount']:.2f} টাকা\n"
                message += f"   Method: {wd['method']} ({wd['mobile_number']})\n"
                message += f"   Date: {wd['requested_at'][:16]}\n"
                
                if wd['status'] == 'pending':
                    message += f"   [Approve] [Reject]\n\n"
                else:
                    message += f"   Status: {status_emoji} {wd['status']}\n\n"
            
            keyboard = []
            for wd in withdrawals[:3]:  # Show buttons for first 3
                row = [
                    InlineKeyboardButton(f"✅ {wd['id']}", callback_data=f"withdraw_action_approve_{wd['id']}"),
                    InlineKeyboardButton(f"❌ {wd['id']}", callback_data=f"withdraw_action_reject_{wd['id']}")
                ]
                keyboard.append(row)
            
            keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data="admin_back")])
        
        await update.callback_query.edit_message_text(
            text=message,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    async def show_admin_settings(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show admin settings"""
        settings = {
            "Ad Earning Rate": self.db.get_setting('ad_earning_rate', Config.AD_EARNING_RATE),
            "Referral Bonus": self.db.get_setting('referral_bonus', Config.REFERRAL_BONUS),
            "Minimum Withdrawal": self.db.get_setting('minimum_withdrawal', Config.MINIMUM_WITHDRAWAL),
            "Daily Earning Limit": self.db.get_setting('daily_earning_limit', Config.DAILY_EARNING_LIMIT),
            "Max Ads Per Day": self.db.get_setting('max_ads_per_day', Config.MAX_ADS_PER_DAY),
            "Ad Cooldown (seconds)": self.db.get_setting('ad_cooldown', Config.AD_COOLDOWN_SECONDS)
        }
        
        message = "⚙️ **System Settings**\n\n"
        for key, value in settings.items():
            message += f"{key}: {value}\n"
        
        message += "\nTo change settings, use command:\n"
        message += "/set <key> <value>\n"
        message += "Example: /set ad_earning_rate 10"
        
        keyboard = [
            [InlineKeyboardButton("⬅️ Back", callback_data="admin_back")]
        ]
        
        await update.callback_query.edit_message_text(
            text=message,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    async def show_admin_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show detailed admin stats"""
        stats = self.db.get_system_stats()
        
        # Get recent withdrawals
        withdrawals = self.db.get_withdrawals()
        recent_withdrawals = withdrawals[:5]
        
        message = "📊 **Detailed Statistics**\n\n"
        message += f"👥 Total Users: {stats['total_users']}\n"
        message += f"📈 Active Today: {stats['active_today']}\n"
        message += f"💰 Total Earnings: {stats['total_earnings']:.2f} টাকা\n"
        message += f"💸 Total Withdrawn: {stats['total_withdrawals']:.2f} টাকা\n"
        message += f"⏳ Pending Withdrawals: {stats['pending_withdrawals']:.2f} টাকা\n\n"
        
        message += "📋 Recent Withdrawals:\n"
        for wd in recent_withdrawals:
            status_emoji = {"pending": "⏳", "approved": "✅", "rejected": "❌"}.get(wd['status'], "❓")
            message += f"• {status_emoji} {wd['amount']:.2f} টাকা - @{wd['username'] or 'N/A'}\n"
        
        keyboard = [
            [InlineKeyboardButton("🔄 Refresh", callback_data="admin_stats")],
            [InlineKeyboardButton("⬅️ Back", callback_data="admin_back")]
        ]
        
        await update.callback_query.edit_message_text(
            text=message,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    async def show_admin_ads(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show admin ads management"""
        ads = self.db.get_available_ads()
        
        message = "🎬 **Manage Ads**\n\n"
        for ad in ads:
            status = "✅ Active" if ad['is_active'] else "❌ Inactive"
            message += f"📺 {ad['title']}\n"
            message += f"   {ad['description']}\n"
            message += f"   Earnings: {ad['earnings']} টাকা\n"
            message += f"   Status: {status}\n\n"
        
        message += "To add new ad, use command:\n"
        message += "/add_ad <title> | <description> | <earnings>\n"
        message += "Example: /add_ad New Product | Watch this video | 10"
        
        keyboard = [
            [InlineKeyboardButton("⬅️ Back", callback_data="admin_back")]
        ]
        
        await update.callback_query.edit_message_text(
            text=message,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    async def handle_admin_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle admin commands"""
        telegram_id = update.effective_user.id
        
        if telegram_id not in Config.ADMIN_IDS:
            await update.message.reply_text("⛔ Access Denied")
            return
        
        text = update.message.text.strip()
        command = text.split()[0].lower()
        
        if command == "/set" and len(context.args) >= 2:
            key = context.args[0]
            value = " ".join(context.args[1:])
            
            valid_keys = [
                'ad_earning_rate', 'referral_bonus', 'minimum_withdrawal',
                'daily_earning_limit', 'max_ads_per_day', 'ad_cooldown'
            ]
            
            if key in valid_keys:
                self.db.update_setting(key, value)
                await update.message.reply_text(f"✅ Setting updated: {key} = {value}")
            else:
                await update.message.reply_text(f"❌ Invalid key. Valid keys: {', '.join(valid_keys)}")
        
        elif command == "/add_ad" and len(context.args) >= 3:
            try:
                # Parse ad data
                ad_data = " ".join(context.args).split("|")
                if len(ad_data) < 3:
                    raise ValueError
                
                title = ad_data[0].strip()
                description = ad_data[1].strip()
                earnings = float(ad_data[2].strip())
                
                # Add to database
                conn = self.db.get_connection()
                cursor = conn.cursor()
                cursor.execute('INSERT INTO ads (title, description, earnings) VALUES (?, ?, ?)',
                             (title, description, earnings))
                conn.commit()
                conn.close()
                
                await update.message.reply_text(f"✅ Ad added: {title}")
            except:
                await update.message.reply_text("❌ Invalid format. Use: /add_ad title | description | earnings")
        
        elif command == "/broadcast" and len(context.args) >= 1:
            message = " ".join(context.args)
            await self.send_broadcast(update, context, message)
    
    async def send_broadcast(self, update: Update, context: ContextTypes.DEFAULT_TYPE, message: str):
        """Send broadcast message to all users"""
        telegram_id = update.effective_user.id
        
        if telegram_id not in Config.ADMIN_IDS:
            return
        
        users = self.db.get_all_users()
        total = len(users)
        success = 0
        
        await update.message.reply_text(f"📢 Broadcasting to {total} users...")
        
        for user in users:
            try:
                await context.bot.send_message(
                    chat_id=user['telegram_id'],
                    text=f"📢 **Announcement**\n\n{message}"
                )
                success += 1
                await asyncio.sleep(0.1)  # Rate limiting
            except:
                continue
        
        await update.message.reply_text(f"✅ Broadcast sent to {success}/{total} users")
    
    async def handle_broadcast_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle broadcast message from admin"""
        telegram_id = update.effective_user.id
        
        if telegram_id not in Config.ADMIN_IDS:
            return
        
        if context.user_data.get("awaiting_broadcast"):
            message = update.message.text
            context.user_data.pop("awaiting_broadcast", None)
            await self.send_broadcast(update, context, message)
    
    # ==================== SETUP & RUN ====================
    def setup_handlers(self):
        """Setup bot handlers"""
        # Command handlers
        self.application.add_handler(CommandHandler("start", self.start))
        
        # Admin commands
        self.application.add_handler(MessageHandler(
            filters.TEXT & filters.Regex(r'^/(set|add_ad|broadcast)'),
            self.handle_admin_command
        ))
        
        # Callback query handler
        self.application.add_handler(CallbackQueryHandler(self.handle_callback))
        
        # Message handlers
        self.application.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            self.handle_withdraw_input
        ))
        
        # Broadcast message handler
        self.application.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            self.handle_broadcast_message
        ))
    
    def run(self):
        """Run the bot"""
        if not Config.BOT_TOKEN:
            print("❌ Error: BOT_TOKEN not found in environment variables")
            print("Please create a .env file with BOT_TOKEN=your_token_here")
            return
        
        # Create application
        self.application = Application.builder().token(Config.BOT_TOKEN).build()
        
        # Setup handlers
        self.setup_handlers()
        
        # Start bot
        print("🤖 Bot is starting...")
        print(f"👑 Admin IDs: {Config.ADMIN_IDS}")
        
        self.application.run_polling(allowed_updates=Update.ALL_TYPES)

# ==================== DEPLOYMENT GUIDE ====================
"""
DEPLOYMENT GUIDE

1. REQUIREMENTS:
   Python 3.8+
   Required packages: python-telegram-bot, python-dotenv

2. SETUP INSTRUCTIONS:

   a) Install dependencies:
      pip install python-telegram-bot python-dotenv

   b) Create .env file:
      BOT_TOKEN=your_bot_token_from_botfather
      ADMIN_IDS=[123456789, 987654321]
      DB_PATH=bot_database.db

   c) Run the bot:
      python bot.py

3. DEPLOYMENT OPTIONS:

   Option A: VPS (DigitalOcean, AWS, GCP)
      - Install Python and dependencies
      - Use systemd service to run bot
      - Setup firewall rules

   Option B: Railway/Render (Cloud)
      - Push code to GitHub
      - Connect repository
      - Add environment variables
      - Deploy

4. BOT COMMANDS:

   User Commands:
      /start - Start the bot
   
   Admin Commands:
      /set <key> <value> - Change settings
      /add_ad <title> | <desc> | <earnings> - Add new ad
      /broadcast <message> - Broadcast message

5. SECURITY:
   - Keep .env file secure
   - Regular database backups
   - Monitor bot logs
   - Update dependencies regularly

6. SCALABILITY SUGGESTIONS:
   - Switch to PostgreSQL for production
   - Add Redis for caching
   - Implement webhook instead of polling
   - Add monitoring (Prometheus/Grafana)
   - Use Docker containers
"""

# ==================== MAIN EXECUTION ====================
if __name__ == "__main__":
    # Setup logging
    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        level=logging.INFO
    )
    
    # Run bot
    bot = TelegramBot()
    bot.run()
