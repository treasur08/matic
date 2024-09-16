import os
from datetime import datetime, timedelta
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters, CallbackContext, ConversationHandler
from telegram.error import BadRequest, TelegramError, RetryAfter
import sqlite3
import asyncio
import requests
import http.server
import socketserver
import re
import threading
ADD_TASK, ADD_TASK_PROOF = range(2)

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = {5991907369, 1234567890, 987654321}
CHANNEL_USERNAMES = ["@gamesgero"]
CHANNEL_JOIN_LINKS = ["https://t.me/gamesgero"]


class Database:
    def __init__(self):
        self.conn = sqlite3.connect('bot_database.db')
        self.create_tables()

    def create_tables(self):  
        with self.conn:  
            self.conn.execute("""  
            CREATE TABLE IF NOT EXISTS users (  
                id INTEGER PRIMARY KEY,  
                username TEXT,  
                first_name TEXT,  
                last_name TEXT,  
                referral_link TEXT,  
                referrer_id INTEGER,  
                verified INTEGER DEFAULT 0,  
                matic_balance INTEGER DEFAULT 0,  
                matic_wallet TEXT,  
                last_claim TIMESTAMP,  
                double_mine_active INTEGER DEFAULT 0,  
                double_mine_enabled INTEGER DEFAULT 0,  
                time_speed_enabled INTEGER DEFAULT 0          
            )""")  
            
            self.conn.execute("""  
            CREATE TABLE IF NOT EXISTS referrals (  
                id INTEGER PRIMARY KEY AUTOINCREMENT,  
                referrer_id INTEGER,  
                referred_id INTEGER  
            )""")  

            # Add 'timestamp' column to make sure it's included correctly  
            self.conn.execute('''  
            CREATE TABLE IF NOT EXISTS new_referrals (  
                referral_id INTEGER PRIMARY KEY AUTOINCREMENT,  
                referrer_id INTEGER,  
                referred_id INTEGER,  
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,  
                FOREIGN KEY (referrer_id) REFERENCES users(id),  
                FOREIGN KEY (referred_id) REFERENCES users(id)  
            )''')  

            # We need to check if the old referrals table has a 'timestamp' column   
            # before copying data from it.  

            try:  
                # Copy data from old referrals table to new referrals table  
                self.conn.execute('''  
                INSERT INTO new_referrals (referrer_id, referred_id, timestamp)  
                SELECT referrer_id, referred_id, CURRENT_TIMESTAMP FROM referrals  
                ''')  
            except sqlite3.OperationalError:  
                print("The column 'timestamp' does not exist in the 'referrals' table.")  
            
            # Drop the old referrals table  
            self.conn.execute('DROP TABLE IF EXISTS referrals')  

            # Rename the new referrals table to the old table name  
            self.conn.execute('ALTER TABLE new_referrals RENAME TO referrals')  

            self.conn.execute("""  
            CREATE TABLE IF NOT EXISTS tasks (  
                id INTEGER PRIMARY KEY AUTOINCREMENT,  
                photo_file_id TEXT,  
                description TEXT  
            )""")  
            
            self.conn.execute("""  
            CREATE TABLE IF NOT EXISTS task_proofs (  
                id INTEGER PRIMARY KEY AUTOINCREMENT,  
                user_id INTEGER,  
                photo_file_id TEXT,  
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP  
            )""")  
            
            self.conn.execute("""  
            CREATE TABLE IF NOT EXISTS task_completions (  
                id INTEGER PRIMARY KEY AUTOINCREMENT,  
                user_id INTEGER  
            )""")

    def deduct_matic_balance(self, user_id, amount):
        with self.conn:
            cursor = self.conn.cursor()
            cursor.execute("SELECT matic_balance FROM users WHERE id = ?", (user_id,))
            current_balance = cursor.fetchone()[0]

            if current_balance >= amount:
                self.conn.execute("UPDATE users SET matic_balance = matic_balance - ? WHERE id = ?", (amount, user_id))
                print(f"Deducted {amount} MATIC coins from user {user_id}")
            else:
                print("Insufficient MATIC balance to perform deduction.")

    def add_user(self, user_id, username, first_name, last_name, referral_link, referrer_id):
        with self.conn:
            self.conn.execute("""
            INSERT OR IGNORE INTO users (id, username, first_name, last_name, referral_link, referrer_id)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (user_id, username, first_name, last_name, referral_link, referrer_id))
            if referrer_id:
                self.conn.execute("""
                INSERT INTO referrals (referrer_id, referred_id)
                VALUES (?, ?)""",
                (referrer_id, user_id))

    def is_user_verified(self, user_id):
        cursor = self.conn.cursor()
        cursor.execute("SELECT verified FROM users WHERE id = ?", (user_id,))
        result = cursor.fetchone()
        return result and result[0] == 1

    def verify_user(self, user_id):
        with self.conn:
            
            cursor = self.conn.cursor()
            cursor.execute("SELECT verified FROM users WHERE id = ?", (user_id,))
            result = cursor.fetchone()
            
            if result and result[0] == 1:
                return  # User is already verified, do nothing
            
            # Otherwise, update user verification status
            self.conn.execute("UPDATE users SET verified = 1 WHERE id = ?", (user_id,))

            # Check if this is the first verification
            cursor.execute("SELECT matic_balance FROM users WHERE id = ?", (user_id,))
            current_balance = cursor.fetchone()[0]
            if current_balance == 0:
                # If user has 0 MATIC balance, reward them with 3 MATIC
                self.conn.execute("UPDATE users SET matic_balance = matic_balance + 3 WHERE id = ?", (user_id,))

    def update_wallet_address(self, user_id, address):
        with self.conn:
            self.conn.execute("UPDATE users SET matic_wallet = ? WHERE id = ?", (address, user_id))
    
    def get_all_users(self):
        cursor = self.conn.cursor()
        cursor.execute("SELECT id FROM users")
        return [row[0] for row in cursor.fetchall()]


    def get_user_data(self, user_id):
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        result = cursor.fetchone()

        if result:
            return {
                'id': result[0],
                'username': result[1],
                'first_name': result[2],
                'last_name': result[3],
                'referral_link': result[4],
                'referrer_id': result[5],
                'verified': result[6],
                'matic_balance': result[7],
                'matic_wallet': result[8],
                'last_claim': result[9],
                'double_mine_active': result[10],
                'time_speed_enabled': result[11],  # Adjust based on your schema
                'double_mine_enabled': result[12]   # Adjust based on your schema
            }
        else:
            return None

    def get_user_matic_balance(self, user_id):
        cursor = self.conn.cursor()
        cursor.execute("SELECT matic_balance FROM users WHERE id = ?", (user_id,))
        result = cursor.fetchone()
        return result[0] if result else 0

    def update_matic_balance(self, user_id, amount):
        with self.conn:
            self.conn.execute("UPDATE users SET matic_balance = matic_balance + ? WHERE id = ?", (amount, user_id))

    def add_referral(self, referrer_id, referred_id):
        with self.conn:
            self.conn.execute("INSERT INTO referrals (referrer_id, referred_id) VALUES (?, ?)", (referrer_id, referred_id))

    def get_referral_count(self, user_id):
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id = ?", (user_id,))
        result = cursor.fetchone()
        return result[0] if result else 0
    
    def get_referrer_id(self, user_id):
        cursor = self.conn.cursor()
        cursor.execute("SELECT referrer_id FROM users WHERE id = ?", (user_id,))
        result = cursor.fetchone()
        return result[0] if result else None

    def reward_referrer(self, referrer_id, amount):
        with self.conn:
            self.conn.execute("UPDATE users SET matic_balance = matic_balance + ? WHERE id = ?", (amount, referrer_id))


    def get_last_claim_time(self, user_id):
        cursor = self.conn.cursor()
        cursor.execute("SELECT last_claim FROM users WHERE id = ?", (user_id,))
        result = cursor.fetchone()
        if result and result[0]:
            try:
                return datetime.strptime(result[0], '%Y-%m-%d %H:%M:%S.%f')
            except ValueError:
                return datetime.strptime(result[0], '%Y-%m-%d %H:%M:%S')
        return None
    def get_total_users(self):
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM users")
        result = cursor.fetchone()
        return result[0] if result else 0

    def update_last_claim_time(self, user_id):
        with self.conn:
            self.conn.execute("UPDATE users SET last_claim = ? WHERE id = ?", (datetime.now(), user_id))

    def add_task_proof(self, user_id, task_proof):
        with self.conn:
            self.conn.execute("INSERT INTO tasks (user_id, task_proof) VALUES (?, ?)", (user_id, task_proof))
        
    

    def user_has_joined_channels(self, user_id):
        cursor = self.conn.cursor()
        cursor.execute("SELECT verified FROM users WHERE id = ?", (user_id,))
        result = cursor.fetchone()
        return result and result[0] == 1

    def update_user_info(self, user_id, first_name, last_name, username):
        with self.conn:
            self.conn.execute("""
            UPDATE users
            SET first_name = ?, last_name = ?, username = ?
            WHERE id = ?
            """, (first_name, last_name, username, user_id))

    def get_tasks(self):
        cursor = self.conn.cursor()
        cursor.execute("SELECT photo_file_id, description FROM tasks")
        return cursor.fetchall()

    def clear_task_proofs(self):
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM task_proofs WHERE id IN (SELECT id FROM task_proofs ORDER BY id LIMIT 15)")
        self.conn.commit()

    
    def update_claim_time(self, user_id, time_delta):
        with self.conn:
            cursor = self.conn.cursor()
            cursor.execute("SELECT last_claim FROM users WHERE id = ?", (user_id,))
            last_claim_time = cursor.fetchone()[0]

            if last_claim_time:
                # Convert the string to a datetime object
                last_claim_time = datetime.strptime(last_claim_time, '%Y-%m-%d %H:%M:%S.%f')
                new_claim_time = last_claim_time + time_delta
            else:
                new_claim_time = datetime.now() + time_delta

            # Convert the new_claim_time back to a string before storing it in the database
            new_claim_time_str = new_claim_time.strftime('%Y-%m-%d %H:%M:%S.%f')

            self.conn.execute("UPDATE users SET last_claim = ? WHERE id = ?", (new_claim_time_str, user_id))
            print(f"Updated claim time for user {user_id} to {new_claim_time_str}")

    def activate_double_mine(self, user_id):
        with self.conn:
            cursor = self.conn.cursor()
            cursor.execute("SELECT matic_balance FROM users WHERE id = ?", (user_id,))
            current_balance = cursor.fetchone()[0]
    def enable_time_speed(self, user_id):
        with self.conn:
            self.conn.execute("UPDATE users SET time_speed_enabled = 1 WHERE id = ?", (user_id,))

    def enable_double_mine(self, user_id):
        with self.conn:
            self.conn.execute("UPDATE users SET double_mine_enabled = 1 WHERE id = ?", (user_id,))
    def save_task(self, photo_file_id, description):
        with self.conn:
            self.conn.execute("DELETE FROM tasks")
            self.conn.execute("DELETE FROM task_completions")
            self.conn.execute("INSERT INTO tasks (photo_file_id, description) VALUES (?, ?)", (photo_file_id, description))
    def save_task_proof(self, user_id, photo_file_id):
        with self.conn:
            self.conn.execute("INSERT INTO task_proofs (user_id, photo_file_id, timestamp) VALUES (?, ?, ?)", (user_id, photo_file_id, datetime.now()))
    def save_task_completion(self, user_id):
        with self.conn:
            self.conn.execute("INSERT INTO task_completions (user_id) VALUES (?)", (user_id,))
    def has_user_completed_task(self, user_id):
        cursor = self.conn.cursor()
        cursor.execute("SELECT 1 FROM task_completions WHERE user_id = ?", (user_id,))
        return cursor.fetchone() is not None
    def get_task_proofs(self):
        cursor = self.conn.cursor()
        cursor.execute("SELECT user_id, photo_file_id FROM task_proofs LIMIT 15")
        return cursor.fetchall()
    # Add this method to your Database class

    def get_task_proof_date(self, user_id):
        cursor = self.conn.cursor()
        cursor.execute("SELECT timestamp FROM task_proofs WHERE user_id = ? ORDER BY id DESC LIMIT 1", (user_id,))
        result = cursor.fetchone()
        return result[0] if result else None
    
    def get_latest_instruction(self):
        cursor = self.conn.cursor()
        cursor.execute("SELECT description FROM tasks ORDER BY id DESC LIMIT 1")
        result = cursor.fetchone()
        return result[0] if result else "No instructions available."

    def update_instruction(self, new_instruction):
        self.conn.execute("INSERT INTO tasks (description) VALUES (?)", (new_instruction,))
        self.conn.commit()

    def get_user_with_most_referrals(self):
        cursor = self.conn.cursor()
        cursor.execute("""
        SELECT referrer_id, COUNT(referred_id) as referral_count
        FROM referrals
        GROUP BY referrer_id
        ORDER BY referral_count DESC
        LIMIT 1
        """)
        result = cursor.fetchone()
        if result:
            return result[0], result[1]  # Return the user_id and the referral count
        return None, 0

db = Database()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    referrer_id = context.args[0] if context.args else None

    db.add_user(user.id, user.username, user.first_name, user.last_name, f'https://t.me/matic_airdbot?start={user.id}', referrer_id)
    if db.is_user_verified(user.id):
        main_menu_keyboard = [
            [KeyboardButton("Mine Matic 🔨"), KeyboardButton("Wallet 💰")],     
            [KeyboardButton("Exchange 🏦"), KeyboardButton("Invite 👥")],
            [KeyboardButton("Profile 👤"), KeyboardButton("Settings ⚙️")],
            [KeyboardButton("About 🤔"), KeyboardButton("Boosters 🚀")],
            [KeyboardButton("Tasks 🪙"), KeyboardButton("MATIC Giveaways 🎁")]
        ]
        reply_markup = ReplyKeyboardMarkup(main_menu_keyboard, resize_keyboard=True)
        await update.message.reply_text(f"Welcome Back {user.first_name}, don't forget to mine and invite friends 🔨", reply_markup=reply_markup)
        context.user_data['awaiting_captcha'] = False
    else:
        keyboard = [
            [InlineKeyboardButton("🔗 Join Channel", url=CHANNEL_JOIN_LINKS[0])],
            [InlineKeyboardButton("✔ Subscribed", callback_data='subscribed')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(f"Welcome {user.first_name} to <b>MATIC MINING BOT</b> \nPlease join all the channels below and click the \"Subscribed Button\" to continue", reply_markup=reply_markup, parse_mode="HTML")
        if referrer_id:
            referrer = db.get_user_data(referrer_id)
            if referrer:
                await update.message.reply_text(f"You have been referred by {referrer['first_name']}")

async def subscribed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id

    not_joined_channels = []

    for channel in CHANNEL_USERNAMES:
        try:
            chat_member = await context.bot.get_chat_member(chat_id=channel, user_id=user_id)
            if chat_member.status not in ['member', 'administrator', 'creator']:
                not_joined_channels.append(channel)
        except Exception as e:
            print(f"Error checking membership for {channel}: {e}")
            not_joined_channels.append(channel)

    if not not_joined_channels:
        keyboard = [[KeyboardButton("Cancel")]]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        caption = "Please send your MATIC wallet address and get 3 MATIC free\n\n (Check your Trust Wallet, Telegram wallet or another trusted wallet for your MATIC address)\n\nYou can submit anytime you want, Click on Cancel to proceed:"
        photo_file = open('airdrop.png', 'rb')

        if update.message:
            await update.message.reply_photo(photo=photo_file, caption=caption, reply_markup=reply_markup)
        else:
            await context.bot.send_photo(chat_id=query.message.chat_id, photo=photo_file, caption=caption, reply_markup=reply_markup)

        context.user_data['awaiting_address'] = True
    else:
        channels_not_joined = "\n".join([channel for channel in not_joined_channels])
        await query.answer(text=f"Sorry, you need to join all the channels first! You have not joined:\n{channels_not_joined}", show_alert=True)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        response = requests.get("https://matic-bot-vhqj.onrender.com")
        print(f"Pinged the web server. Response: {response.status_code}")
    except requests.RequestException as e:
        print(f"Failed to ping the web server: {e}")
    if update.message is None:
        # Handle case where there's no message (e.g., callback query, edited message, etc.)
        return
    user = update.message.from_user
    user_id = update.message.from_user.id
    text = update.message.text
    step = context.user_data.get('broadcast_step')
    
    if step == 'text_broadcast':
        message_text = update.message.text
        # Retrieve the stored message ID
        broadcast_message_id = context.user_data.get('broadcast_message_id')

        if broadcast_message_id:
            try:
                # Delete the old message using the message ID
                await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=broadcast_message_id)
            except Exception as e:
                print(f"Failed to delete old message: {e}")

        if message_text == "Broadcast 🎙":
            delete_button = [[InlineKeyboardButton("❌", callback_data='delete_message')]]
            delete_markup = InlineKeyboardMarkup(delete_button)
            await update.message.reply_text("NOTE: You cannot use 'Broadcast 🎙' as broadcast text.\n\nPlease restart the process or use the \"❌\" ", reply_markup=delete_markup)
        else:
            # Send the broadcast message logic here
            await update.message.reply_text("Broadcasting your text...")
            await broadcast_to_all_users(update, context, message_text)  # Send to all users

        context.user_data['broadcast_step'] = None  # Reset step after broadcast
        context.user_data.pop('broadcast_message_id', None)


    elif step == 'image_caption':
        broadcast_message_id = context.user_data.get('broadcast_message_id')

        if update.message.photo:  # Check if the user sent a photo
            if broadcast_message_id:
                try:
                    await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=broadcast_message_id)
                except Exception as e:
                    print(f"Failed to delete old message: {e}")

            # Process the new photo and caption
            photo = update.message.photo[-1]  # Get the highest resolution photo
            caption = update.message.caption or ''

            await update.message.reply_text("Broadcasting your image and caption to all users...")

            await broadcast_image_with_caption_to_all_users(context, photo, caption)

            context.user_data.pop('broadcast_step', None)
            context.user_data.pop('broadcast_message_id', None)
        else:
            delete_button = [[InlineKeyboardButton("❌", callback_data='delete_message')]]
            delete_markup = InlineKeyboardMarkup(delete_button)
            await update.message.reply_text("Please send an image with a caption.", reply_markup=delete_markup)


    if step == 'awaiting_image':
        delete_button = [[InlineKeyboardButton("❌", callback_data='delete_message')]]
        delete_markup = InlineKeyboardMarkup(delete_button)
        if update.message.photo:
            # Store the photo for broadcasting
            context.user_data['broadcast_photo'] = update.message.photo[-1].file_id
            await update.message.reply_text("Image received. Please send the text you want to broadcast.", reply_markup=delete_markup)
            context.user_data['broadcast_step'] = 'awaiting_text_for_image'
        else:
            await update.message.reply_text("Please send an image.", reply_markup=delete_markup)

    elif step == 'awaiting_text_for_image':
        delete_button = [[InlineKeyboardButton("❌", callback_data='delete_message')]]
        delete_markup = InlineKeyboardMarkup(delete_button)
        if text:
            # Store the text for broadcasting
            context.user_data['broadcast_text'] = text
            await update.message.reply_text("Text received. Please send the button placeholder and link\n\nEG:\n (Join my Group, https://t.me/link).", reply_markup=delete_markup)
            context.user_data['broadcast_step'] = 'awaiting_button'
        else:
            await update.message.reply_text("Please send some text.")

    elif step == 'awaiting_text':
    
        broadcast_message_id = context.user_data.get('broadcast_message_id')

        if text:  # Check if text is provided
            if broadcast_message_id:
                try:
                    # Delete the old message using the message ID
                    await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=broadcast_message_id)
                except Exception as e:
                    print(f"Failed to delete old message: {e}")

            # Store the text for broadcasting
            context.user_data['broadcast_text'] = text
            context.user_data['broadcast_step'] = 'awaiting_button_for_text'

            # Send a prompt to the user for the button placeholder and link
            reply_markup = InlineKeyboardMarkup(
                [[InlineKeyboardButton('❌', callback_data='delete_message')]]
            )
            await update.message.reply_text(
                "Text received. Please send the button placeholder and link\n\nEG:\n (Join my Group, https://t.me/link).",
                reply_markup=reply_markup
            )
        else:
            # Prompt the user to send text
            await update.message.reply_text("Please send some text.")


    elif step == 'awaiting_button_for_text':
        # Expecting button placeholder and link for text + button broadcast
        if ',' in text:
            # Parse the placeholder and link
            placeholder, link = text.split(',', 1)
            link = link.strip()

            # Check if the link is valid (starts with http://, https://, or tg://msg_url?url=)
            if link.startswith('http://') or link.startswith('https://') or link.startswith('tg://msg_url?url='):
                context.user_data['broadcast_button'] = {'text': placeholder.strip(), 'url': link}
                await update.message.reply_text("Button details received. Broadcasting your text and button to all users...")
                
                # Call the broadcast function
                text = context.user_data['broadcast_text']
                button = context.user_data['broadcast_button']
                await broadcast_text_button_to_all_users(context, text, button)
                
                context.user_data.clear()
            else:
                await update.message.reply_text("Invalid link format. Please provide a valid link starting with 'http://', 'https://', or 'tg://msg_url?url='.")
        else:
            await update.message.reply_text("Please provide the button placeholder and link in the format: 'Placeholder, https://link'  or 'tg://msg_url?url='.")

    elif step == 'awaiting_button':
        # Expecting button placeholder and link for image + text + button
        if ',' in text:
            # Parse the placeholder and link
            placeholder, link = text.split(',', 1)
            link = link.strip()

            # Check if the link is valid (starts with http://, https://, or tg://msg_url?url=)
            if link.startswith('http://') or link.startswith('https://') or link.startswith('tg://msg_url?url='):
                context.user_data['broadcast_button'] = {'text': placeholder.strip(), 'url': link}
                await update.message.reply_text("Button details received.\n\nBroadcasting your image, text, and button to all users...")
                
                # Call the broadcast function
                photo = context.user_data['broadcast_photo']
                caption = context.user_data['broadcast_text']
                button = context.user_data['broadcast_button']
                await broadcast_img_text_button_to_all_users(context, photo, caption, button)
                
                context.user_data.clear()
            else:
                await update.message.reply_text("Invalid link format. Please provide a valid link starting with 'http://', 'https://', or 'tg://msg_url?url='.")
        else:
            await update.message.reply_text("Please provide the button placeholder and link in the format: 'Placeholder, https://link'  or 'tg://msg_url?url='.")


    if 'awaiting_address' in context.user_data and context.user_data['awaiting_address']:
        if 40 <= len(text) <= 46:
            was_verified = db.is_user_verified(user.id)  # Check if user was already verified
            db.update_wallet_address(user.id, text)

            if not was_verified:
                db.verify_user(user.id)
                db.update_matic_balance(user.id, 3)
                await update.message.reply_text("Wallet address updated and you have been rewarded with 3 MATIC coins.")
                referrer_id = db.get_referrer_id(user.id)
                if referrer_id:
                    db.reward_referrer(referrer_id, 5)  # Reward the referrer with 5 MATIC
                    referrer = db.get_user_data(referrer_id)
                    if referrer:
                        await context.bot.send_message(chat_id=referrer_id, text=f"You have successfully referred {user.first_name} to mine on MATIC MINER BOT 🚀, you have received 5 MATIC coins")
            else:
                await update.message.reply_text("Wallet address updated.")

            context.user_data['awaiting_address'] = False

            main_menu_keyboard = [
                [KeyboardButton("Mine Matic 🔨"), KeyboardButton("Wallet 💰")],
                [KeyboardButton("Exchange 🏦"), KeyboardButton("Invite 👥")],
                [KeyboardButton("Profile 👤"), KeyboardButton("Settings ⚙️")],
                [KeyboardButton("About 🤔"), KeyboardButton("Boosters 🚀")],
                [KeyboardButton("Tasks 🪙"), KeyboardButton("MATIC Giveaways 🎁")]
            ]
            reply_markup = ReplyKeyboardMarkup(main_menu_keyboard, resize_keyboard=True)
            await update.message.reply_text("Welcome to the main menu:", reply_markup=reply_markup)
        else:
            await update.message.reply_text("Invalid MATIC wallet address. Please try again.")

    if 'awaiting_time_speed' in context.user_data and context.user_data['awaiting_time_speed']:
        db.deduct_matic_balance(user.id, 20)
        db.update_claim_time(user.id, timedelta(hours=-6))  # Speed up claim time by 6 hours (24 - 18)
        db.enable_time_speed(user.id)  # Mark Time Speed as enabled in the database
        await update.message.reply_text("Your daily claim time has been speeded up by 5hrs")
    elif 'awaiting_double_mine' in context.user_data and context.user_data['awaiting_double_mine']:
        db.deduct_matic_balance(user.id, 20)
        db.activate_double_mine(user.id)
        db.enable_double_mine(user.id)  # Mark Double Mine as enabled in the database
        await update.message.reply_text("Double Mine activated. You will now receive double rewards.")

        context.user_data.pop('awaiting_time_speed', None)
        return

    elif 'awaiting_double_mine' in context.user_data and context.user_data['awaiting_double_mine']:
        if text == "Yes, deduct and proceed":
            db.deduct_matic_balance(user.id, 20)  # Deduct 20 MATIC coins
            db.activate_double_mine(user.id)
            await update.message.reply_text("Double Mine activated. You will now receive double rewards.")
        elif text == "Cancel":
            await update.message.reply_text("Operation cancelled.")
        else:
            await update.message.reply_text("Invalid response. Please choose 'Yes, deduct and proceed' or 'Cancel'.")

        context.user_data.pop('awaiting_double_mine', None)
        return
    elif text == "Swap 🔄":
        await update.message.reply_text("This feature would be available to Top earners 🏆.")
    elif text == "Withdraw 🏦":
        matic_balance = db.get_user_matic_balance(user_id)
        if matic_balance < 200:
            await update.message.reply_text("You need at least 200 MATIC coins to withdraw.")
        else:
            context.user_data['awaiting_withdrawal_amount'] = True
            await update.message.reply_text("Please enter the amount you want to withdraw (numbers only).")
    elif 'awaiting_withdrawal_amount' in context.user_data and context.user_data['awaiting_withdrawal_amount']:
        try:
            amount = int(text)
            matic_balance = db.get_user_matic_balance(user_id)
            if amount >= 60 and amount <= matic_balance:
                db.update_matic_balance(user_id, -amount)
                del context.user_data['awaiting_withdrawal_amount']
                await update.message.reply_text(f"Withdrawal of {amount} MATIC would be processed shortly. Keep earning on MATIC!")
            else:
                await update.message.reply_text("Please enter a valid amount that you have in your balance and is above 60 MATIC.")
        except ValueError:
            await update.message.reply_text("Please enter a valid number.")

    elif text == "Mine Matic 🔨":
        await handle_mine_matic(update, context)
    elif text == "Wallet 💰":
        await handle_wallet(update, context)
    elif text == "Exchange 🏦":
        await handle_exchange(update,context)
    elif text == "Invite 👥":
        await handle_invite(update, context)
    elif text == "Profile 👤":
        await handle_profile(update, context)
    elif text == "Settings ⚙️":
        await handle_settings(update, context)
    elif text == "About 🤔":
        await handle_about(update, context)
    elif text == "Boosters 🚀":
        await handle_boosters(update, context)
    elif text == "Tasks 🪙":
        await handle_tasks(update, context)
    elif text == "MATIC Giveaways 🎁":
        await handle_giveaways(update, context)
    elif text == "Edit Address":
        await handle_edit_address(update, context)
    elif text == "Join Channels":
        await handle_join_channels(update, context)
    elif text == "Time Speed ⏲":
        await handle_time_speed(update, context)
    elif text == "Double Mine (x2)":
        await handle_double_mine(update, context)
    elif text == "Back":
        await handle_back(update, context)
    elif text == "Done Task ✔":
            await done_task(update, context)
            return ADD_TASK_PROOF
    elif user_id in ADMIN_IDS:
            if text == "Total users":
                total_users = db.get_total_users()
                await update.message.reply_text(f"Total users: {total_users}")

            elif text == "Add Task":
                await add_task(update, context)
                return ADD_TASK

            elif text == "Task Proof":
                 await handle_task_proof(update, context)

            elif text == "👨‍💼 Menu":
                 await admin_menu(update, context)

            elif text == "Clear Proofs💨":
                await handle_clear_task_proofs(update, context)
            
            elif text == "Top Ref 🏆":
                await most_referrals(update, context)

            elif text == "Broadcast 🎙":  
                await broadcast_command(update, context) 

            else:
                await update.message.reply_text("Unauthorized")
    else:
        await update.message.reply_text("❕")
    
async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    broadcast_message_id = context.user_data.get('broadcast_message_id')
    previous_message_id = context.user_data.get('previous_message_id')

    # Delete the old broadcast keyboard message if it exists
    if broadcast_message_id:
        try:
            await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=broadcast_message_id)
        except Exception as e:
            print(f"Failed to delete old broadcast keyboard message: {e}")

    # Delete the user's previous message if it exists
    if previous_message_id:
        try:
            await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=previous_message_id)
        except Exception as e:
            print(f"Failed to delete user's previous message: {e}")

    # Send the broadcast keyboard and store its message ID
    sent_message = await update.message.reply_text("Broadcast Menu:", reply_markup=broadcast_keyboard())
    context.user_data['broadcast_message_id'] = sent_message.message_id

    # Store the ID of the user's current message to delete it later
    context.user_data['previous_message_id'] = update.message.message_id

async def broadcast_to_all_users(update: Update, context, text):
    # Fetch all user IDs from the database
    all_users = db.get_all_users()
    sent_count = 0
    failed_count = 0

    for user_id in all_users:
        try:
            # Fetch user data to get the first name
            user_data = db.get_user_data(user_id)
            
            # Check if user_data exists and has a first_name
            if user_data and 'first_name' in user_data and user_data['first_name']:
                first_name_upper = user_data['first_name'].upper()  # Convert first name to uppercase
            else:
                first_name_upper = 'USER'  # Default value if first_name is not found

            # Replace {username} with the user's first name in uppercase
            personalized_text = text.replace('{user}', first_name_upper)

            # Send the personalized text message to each user
            await context.bot.send_message(chat_id=user_id, text=personalized_text)
            sent_count += 1
        except Exception as e:
            print(f"Failed to send message to {user_id}: {str(e).splitlines()[0]}")
            failed_count += 1

    # Notify admin after broadcasting to all users
    await update.message.reply_text(
        f"Broadcast completed. Sent to {sent_count} users, failed to send to {failed_count} users."
    )


async def broadcast_image_with_caption_to_all_users(context, photo, caption):
    all_users = db.get_all_users()
    admin_user_id = 5991907369
    success_count = 0
    failure_count = 0

    for user_id in all_users:
        try:
            # Fetch user data to get the first name
            user_data = db.get_user_data(user_id)
            
            # Check if user_data exists and has a first_name
            if user_data and 'first_name' in user_data and user_data['first_name']:
                first_name_upper = user_data['first_name'].upper()  # Convert first name to uppercase
            else:
                first_name_upper = 'USER'  # Default value if first_name is not found
            
            # Replace {username} with the user's first name in uppercase
            personalized_caption = caption.replace('{user}', first_name_upper)

            # Send photo to each user with personalized caption
            await context.bot.send_photo(chat_id=user_id, photo=photo.file_id, caption=personalized_caption)
            success_count += 1
        except Exception as e:
            print(f"Failed to send photo to {user_id}: {str(e).splitlines()[0]}")
            failure_count += 1

    # Send confirmation message to admin
    confirmation_message = (
        f"Broadcast completed.\n"
        f"Successfully sent to {success_count} users.\n"
        f"Failed to send to {failure_count} users."
    )
    await context.bot.send_message(chat_id=admin_user_id, text=confirmation_message)


async def broadcast_img_text_button_to_all_users(context, photo, caption, button):
    all_users = db.get_all_users()
    admin_user_id = 5991907369
    error_messages = set()  # Use a set to collect unique error messages
    error_occurred = False

    for user_id in all_users:
        try:
            # Fetch user data to get the first name
            user_data = db.get_user_data(user_id)

            # Check if user_data exists and has a first_name
            if user_data and 'first_name' in user_data and user_data['first_name']:
                first_name_upper = user_data['first_name'].upper()  # Convert first name to uppercase
            else:
                first_name_upper = 'USER'  # Default value if first_name is not found
            
            # Replace {username} with the user's first name in uppercase
            personalized_caption = caption.replace('{user}', first_name_upper)

            await context.bot.send_photo(
                chat_id=user_id,
                photo=photo,
                caption=personalized_caption,
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton(button['text'], url=button['url'])]]
                )
            )
        except Exception as e:
            error_occurred = True
            error_message = f"Failed to send image with caption to {user_id}: {str(e).splitlines()[0]}"
            print(error_message)

            # Add unique error messages to the set
            error_messages.add(str(e).splitlines()[0])

    if error_occurred:
        # Send an aggregated error message to the admin
        aggregated_error_message = "Failed to send text with button to all users:\n" + "\n".join(error_messages)
        await context.bot.send_message(chat_id=admin_user_id, text=aggregated_error_message)
    else:
        confirmation_message = "Broadcast completed successfully to all users."
        await context.bot.send_message(chat_id=admin_user_id, text=confirmation_message)


async def broadcast_text_button_to_all_users(context, text, button):
    all_users = db.get_all_users()
    admin_user_id = 5991907369
    error_occurred = False  # Initialize the error flag

    for user_id in all_users:
        try:
            # Fetch user data to get the first name
            user_data = db.get_user_data(user_id)

            # Check if user_data exists and has a first_name
            if user_data and 'first_name' in user_data and user_data['first_name']:
                first_name_upper = user_data['first_name'].upper()  # Convert first name to uppercase
            else:
                first_name_upper = 'USER'  # Default value if first_name is not found
            
            # Replace {username} with the user's first name in uppercase
            personalized_text = text.replace('{user}', first_name_upper)

            await context.bot.send_message(
                chat_id=user_id,
                text=personalized_text,
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton(button['text'], url=button['url'])]]
                )
            )
        except Exception as e:
            error_occurred = True  # Set the flag to True if an error occurs
            error_message = f"Failed to send text with button to {user_id}: {str(e).splitlines()[0]}"
            print(error_message)

    # Check if any error occurred
    if error_occurred:
        await context.bot.send_message(chat_id=admin_user_id, text="Failed to send message to some users")
    else:
        confirmation_message = "Broadcast completed successfully to all users."
        await context.bot.send_message(chat_id=admin_user_id, text=confirmation_message)
async def handle_time_speed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    user_id = user.id

    # Check if user has already enabled Time Speed
    user_data = context.user_data.get(user_id, {})
    if user_data.get('time_speed_enabled'):
        await update.message.reply_text("You have already enabled Time Speed.")
        return

    # Ask the user if they want to proceed
    reply_markup = ReplyKeyboardMarkup([[KeyboardButton("Yes, deduct and proceed"), KeyboardButton("Cancel")]], resize_keyboard=True)
    await update.message.reply_text("Do you want to proceed? The bot is about to deduct 20 MATIC coins to speed up your daily claim time from 24 hours to 18 hours.", reply_markup=reply_markup)

    # Set the awaiting_time_speed context
    context.user_data['awaiting_time_speed'] = True

async def handle_double_mine(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    user_id = user.id

    # Check if user has already enabled Double Mine
    user_data = context.user_data.get(user_id, {})
    if user_data.get('double_mine_enabled'):
        await update.message.reply_text("You have already enabled Double Mine.")
        return

    # Ask the user if they want to proceed
    reply_markup = ReplyKeyboardMarkup([[KeyboardButton("Yes, deduct and proceed"), KeyboardButton("Cancel")]], resize_keyboard=True)
    await update.message.reply_text("Do you want to proceed? The bot is about to deduct 20 MATIC coins to double your mining rewards for a limited time.", reply_markup=reply_markup)

    # Set the awaiting_double_mine context
    context.user_data['awaiting_double_mine'] = True

async def handle_clear_task_proofs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db.clear_task_proofs()
    await update.message.reply_text("Cleared the first 15 task proofs.")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    main_menu_keyboard = [
            [KeyboardButton("Mine Matic 🔨"), KeyboardButton("Wallet 💰")],
            [KeyboardButton("Exchange 🏦"), KeyboardButton("Invite 👥")],
            [KeyboardButton("Profile 👤"), KeyboardButton("Settings ⚙️")],
            [KeyboardButton("About 🤔"), KeyboardButton("Boosters 🚀")],
            [KeyboardButton("Tasks 🪙"), KeyboardButton("MATIC Giveaways 🎁")]
        ]
    reply_markup = ReplyKeyboardMarkup(main_menu_keyboard, resize_keyboard=True)
    await update.message.reply_text("Cancelled. Returning to main menu.", reply_markup=reply_markup)
    return


async def handle_edit_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    keyboard = [[KeyboardButton("Cancel")]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text("Please send your new MATIC wallet address:", reply_markup=reply_markup)

    context.user_data['awaiting_address'] = True

async def handle_join_channels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🔗 Join Channel", url=CHANNEL_JOIN_LINKS[0])]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Ensure you are in all the channels:", reply_markup=reply_markup)

async def handle_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    main_menu_keyboard = [
        [KeyboardButton("Mine Matic 🔨"), KeyboardButton("Wallet 💰")],
        [KeyboardButton("Exchange 🏦"), KeyboardButton("Invite 👥")],
        [KeyboardButton("Profile 👤"), KeyboardButton("Settings ⚙️")],
        [KeyboardButton("About 🤔"), KeyboardButton("Boosters 🚀")],
        [KeyboardButton("Tasks 🪙"), KeyboardButton("MATIC Giveaways 🎁")]
    ]
    reply_markup = ReplyKeyboardMarkup(main_menu_keyboard, resize_keyboard=True)
    await update.message.reply_text("Main Menu:", reply_markup=reply_markup)

async def handle_mine_matic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    not_joined_channels = []

    for channel in CHANNEL_USERNAMES:
        try:
            chat_member = await context.bot.get_chat_member(chat_id=channel, user_id=user.id)
            if chat_member.status not in ['member', 'administrator', 'creator']:
                not_joined_channels.append(channel)
        except Exception as e:
            print(f"Error checking membership for {channel}: {e}")
            not_joined_channels.append(channel)

    if not_joined_channels:
        channels_not_joined = "\n".join([channel for channel in not_joined_channels])
        await update.message.reply_text(f"Please join all channels from the Settings ⚙️ to use this feature. You have not joined:\n{channels_not_joined}")
        return

    last_claim_time = db.get_last_claim_time(user.id)
    if last_claim_time:
        time_since_last_claim = datetime.now() - last_claim_time
        time_left = timedelta(hours=24) - time_since_last_claim
        if time_left > timedelta(0):
            hours, remainder = divmod(time_left.seconds, 3600)
            minutes, seconds = divmod(remainder, 60)
            await update.message.reply_text(f"You can mine in the next {hours} hours and {minutes} minutes.")
            return

    db.update_matic_balance(user.id, 1)
    db.update_last_claim_time(user.id)
    await update.message.reply_text("You have successfully claimed 1 MATIC.")


async def handle_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    balance = db.get_user_matic_balance(user.id)
    await update.message.reply_text(f"Your MATIC wallet balance is {balance} MATIC.\n\n\nKeep mining MATIC on the bot to increase your chances of withdrawal before the airdrop ends 🛠🔨")

async def handle_exchange(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    user_id = user.id
    balance = db.get_user_matic_balance(user.id)

    if balance < 200:
        await update.message.reply_text("You need at least 200 MATIC to access the exchange features.")
        return

    exchange_keyboard = [
        [KeyboardButton("Swap 🔄"), KeyboardButton("Withdraw 🏦")],
        [KeyboardButton("Back")]
    ]
    reply_markup = ReplyKeyboardMarkup(exchange_keyboard, resize_keyboard=True)
    await update.message.reply_text("Exchange Menu:", reply_markup=reply_markup)

async def handle_invite(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    not_joined_channels = []
    user_id = update.effective_user.id

    for channel in CHANNEL_USERNAMES:
        try:
            chat_member = await context.bot.get_chat_member(chat_id=channel, user_id=user.id)
            if chat_member.status not in ['member', 'administrator', 'creator']:
                not_joined_channels.append(channel)
        except Exception as e:
            print(f"Error checking membership for {channel}: {e}")
            not_joined_channels.append(channel)

    if not_joined_channels:
        channels_not_joined = "\n".join([channel for channel in not_joined_channels])
        await update.message.reply_text(f"Please join all channels from the Settings ⚙️ to use this feature. You have not joined:\n{channels_not_joined}")
        return
    referral_link = f"https://t.me/matic_airdbot?start={user.id}"
    referral_count = db.get_referral_count(user.id)
    await update.message.reply_text(f"Invite your friends using this link: {referral_link}\n\nKeep referring your friends to stand a chance to participate in the $2000 giveaway \nYou earn 5 MATIC coins for every referral that mines MATIC on the bot through your link. \n\n No of Referrals 👥 : {referral_count}")


async def handle_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    user_data = db.get_user_data(user.id)

    if user_data:

        await update.message.reply_text(f"<b>MATIC PROFILE INFORMATION:</b>\n\n <b>▪️Username:</b> {user_data['username']}\n\n<b>▪️First Name:</b> {user_data['first_name']}\n\n<b>▪️Last Name:</b> {user_data['last_name']}\n\n<b>▪️MATIC Balance:</b> {user_data['matic_balance']}\n\n<b>▪️Wallet Address:</b> <code>{user_data['matic_wallet']}</code>", parse_mode="HTML")
    else:
        await update.message.reply_text("User data not found.")


async def handle_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    settings_keyboard = [
        [KeyboardButton("Edit Address"), KeyboardButton("Join Channels")],
        [KeyboardButton("Back")]
    ]
    reply_markup = ReplyKeyboardMarkup(settings_keyboard, resize_keyboard=True)
    await update.message.reply_text("Settings Menu:", reply_markup=reply_markup)

async def handle_about(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("This Bot allows you to mine MATIC tokens by completing tasks, inviting friends, and more!\n\nKeep mining and also stand a chance of participating in the $2000 Giveaway!")

async def handle_boosters(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    user_id = user.id
    not_joined_channels = []

    for channel in CHANNEL_USERNAMES:
        try:
            chat_member = await context.bot.get_chat_member(chat_id=channel, user_id=user.id)
            if chat_member.status not in ['member', 'administrator', 'creator']:
                not_joined_channels.append(channel)
        except Exception as e:
            print(f"Error checking membership for {channel}: {e}")
            not_joined_channels.append(channel)

    if not_joined_channels:
        channels_not_joined = "\n".join([channel for channel in not_joined_channels])
        await update.message.reply_text(f"Please join all channels from the Settings ⚙️ to use this feature. You have not joined:\n{channels_not_joined}")
        return

    # Check if user has at least 20 MATIC coins
    matic_balance = db.get_user_matic_balance(user_id)
    if matic_balance < 20:
        await update.message.reply_text("You need at least 20 MATIC coins to use boosters.")
        return

    # Ask the user to choose an option
    boosters_keyboard = [
        [KeyboardButton("Time Speed ⏲"), KeyboardButton("Double Mine (x2)")],
        [KeyboardButton("Back")]
    ]
    reply_markup = ReplyKeyboardMarkup(boosters_keyboard, resize_keyboard=True)
    await update.message.reply_text("Boosters Menu:", reply_markup=reply_markup)



async def handle_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tasks = db.get_tasks()
    user_id = update.effective_user.id
    not_joined_channels = []

    print(f"User ID: {user_id}")
    print(f"CHANNEL_USERNAMES: {CHANNEL_USERNAMES}")

    for channel in CHANNEL_USERNAMES:
        try:
            chat_member = await context.bot.get_chat_member(chat_id=channel, user_id=user_id)
            print(f"Chat member status for {channel}: {chat_member.status}")
            if chat_member.status not in ['member', 'administrator', 'creator']:
                not_joined_channels.append(channel)
        except Exception as e:
            print(f"Error checking membership for {channel}: {e}")
            not_joined_channels.append(channel)

    if not_joined_channels:
        channels_not_joined = "\n".join([channel for channel in not_joined_channels])
        await update.message.reply_text(f"Please join all channels from the Settings ⚙️ to use this feature. You have not joined:\n{channels_not_joined}")
        return

    if not tasks:
        await update.message.reply_text("There are no tasks available, check back later.")
        return

    for task in tasks:
        photo_file_id = task[0]
        description = task[1]
        try:
            await update.message.reply_photo(photo=photo_file_id, caption=description)
        except BadRequest as e:
            print(f"Error sending photo with file_id {photo_file_id}: {e}")

    tasks_keyboard = [[KeyboardButton("Done Task ✔"), KeyboardButton("Back")]]
    reply_markup = ReplyKeyboardMarkup(tasks_keyboard, resize_keyboard=True)
    user = update.message.from_user
    user_id = update.effective_user.id
    referral_link = f"https://t.me/matic_airdbot?start={user.id}"
    await update.message.reply_text(f"<b>Task Instructions</b>:\n\n📝Follow the instructions\n📝Share your invite link to your Whatsapp/Telegram Status/Story\n📝Copy the write up below 👇 by clicking on it\n<code>Looking for a way to mine free MATIC tokens? use my referral link to mine free MATIC tokens and stand a chance in participating in the $2000 giveaway \n\n {referral_link} </code>\n📝Click on done task and send screenshot of Task Done ✔", reply_markup=reply_markup, parse_mode="HTML")

async def handle_task_proof(update: Update, context: ContextTypes.DEFAULT_TYPE):
    task_proofs = db.get_task_proofs()
    if not task_proofs:
        await update.message.reply_text("No task proofs submitted yet.")
        return

    for user_id, photo_file_id in task_proofs:
        await update.message.reply_photo(photo=photo_file_id, caption=f"Proof submitted by user <code>{user_id}</code>", parse_mode="HTML")
    clear_button = [[KeyboardButton("Clear Proofs💨"), KeyboardButton("👨‍💼 Menu")]]
    reply_markup = ReplyKeyboardMarkup(clear_button, resize_keyboard=True)
    await update.message.reply_text("End of task proofs.", reply_markup=reply_markup)



async def handle_giveaways(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    referral_count = db.get_referral_count(user.id)
    if referral_count < 30:
        await update.message.reply_text("You need to refer at least 30 people to participate the $2000 giveaways.")
        return
    await update.message.reply_text("Join the giveaway channel here: [https://t.me/maticgiveaways]")

def admin_keyboard():
    keyboard = [
        [KeyboardButton("Total users")],
        [KeyboardButton("Add Task")],
        [KeyboardButton("Task Proof")],
        [KeyboardButton("Top Ref 🏆")],
        [KeyboardButton("Broadcast 🎙")],
        [KeyboardButton("Back")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

async def admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id in ADMIN_IDS:
        await update.message.reply_text("Back to Admin menu 👨‍💼", reply_markup=admin_keyboard())
    else:
        await update.message.reply_text("You are not authorized to use this command.")

async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id in ADMIN_IDS:
        await update.message.reply_text("Admin Menu:", reply_markup=admin_keyboard())
    else:
        await update.message.reply_text("You are not authorized to use this command.")

def broadcast_keyboard():  
    keyboard = [  
        [InlineKeyboardButton("IMAGE + CAPTION", callback_data='broadcast_image_caption')],  
        [InlineKeyboardButton("TEXT", callback_data='broadcast_text')],  
        [InlineKeyboardButton("IMG, TEXT + BUTTON", callback_data='broadcast_img_text_button')],  
        [InlineKeyboardButton("TEXT + BUTTON", callback_data='broadcast_text_button')]  
    ]  
    return InlineKeyboardMarkup(keyboard)  

async def handle_button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()  # Acknowledge the callback to prevent timeout

    # Create a delete button to append to each message
    delete_button = [[InlineKeyboardButton("❌", callback_data='delete_message')]]
    delete_markup = InlineKeyboardMarkup(delete_button)

    if query.data == 'broadcast_image_caption':
        message = await query.edit_message_text(
            "Please send the image and caption.",
            reply_markup=delete_markup
        )
        context.user_data['broadcast_step'] = 'image_caption'
        context.user_data['broadcast_message_id'] = message.message_id
    elif query.data == 'broadcast_text':
        message = await query.edit_message_text(
            "Please send the text you want to broadcast.",
            reply_markup=delete_markup
        )
        context.user_data['broadcast_step'] = 'text_broadcast'
        context.user_data['broadcast_message_id'] = message.message_id
    elif query.data == 'broadcast_img_text_button':
        message = await query.edit_message_text(
            "Fristly, send the image you want to broadcast.",
            reply_markup=delete_markup
        )
        context.user_data['broadcast_step'] = 'awaiting_image'
        context.user_data['broadcast_message_id'] = message.message_id
    elif query.data == 'broadcast_text_button':
        message = await query.edit_message_text(
            "Please send the text.",
            reply_markup=delete_markup
        )
        context.user_data['broadcast_step'] = 'awaiting_text'
        context.user_data['broadcast_message_id'] = message.message_id
    # Handle delete button action
    elif query.data == 'delete_message':
        await query.delete_message()  # Delete the message
        context.user_data.clear()  # Clear all user data
        await update.effective_chat.send_message("Operation Ended")
 

async def add_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[KeyboardButton("Cancel"), KeyboardButton("👨‍💼 Menu")]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text("Please send the task picture with a caption.", reply_markup=reply_markup)
    return ADD_TASK

async def save_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo = update.message.photo[-1]
    caption = update.message.caption
    db.save_task(photo.file_id, caption)
    await update.message.reply_text("Task added successfully!", reply_markup=admin_keyboard())
    all_users = db.get_all_users()
    for user_id in all_users:
        try:
            await context.bot.send_message(chat_id=user_id, text="A new task has been posted, ensure you do it and get paid.")
        except RetryAfter as e:
            await asyncio.sleep(e.retry_after)
            await context.bot.send_message(chat_id=user_id, text="A new task has been posted, ensure you do it and get paid.")
        except TelegramError:
            # You can handle specific TelegramError if needed
            pass


async def done_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if db.has_user_completed_task(user_id):
        await update.message.reply_text("You had earlier completed the current task, kindly wait for a new one")
        return ConversationHandler.END
    keyboard = [[KeyboardButton("Cancel")]]
    markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text("Please send a screenshot of the completed task.", reply_markup=markup)
    return ADD_TASK_PROOF

async def save_task_proof(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo = update.message.photo[-1]
    user_id = update.message.from_user.id

    db.save_task_proof(user_id, photo.file_id)
    db.save_task_completion(user_id)
    main_menu_keyboard = [
                [KeyboardButton("Mine Matic 🔨"), KeyboardButton("Wallet 💰")],
                [KeyboardButton("Exchange 🏦"), KeyboardButton("Invite 👥")],
                [KeyboardButton("Profile 👤"), KeyboardButton("Settings ⚙️")],
                [KeyboardButton("About 🤔"), KeyboardButton("Boosters 🚀")],
                [KeyboardButton("Tasks 🪙"), KeyboardButton("MATIC Giveaways 🎁")]
            ]
    markup = ReplyKeyboardMarkup(main_menu_keyboard, resize_keyboard=True)
    await update.message.reply_text("Task proof submitted successfully!",reply_markup=markup)
    return ConversationHandler.END

add_task_conv_handler = ConversationHandler(
    entry_points=[MessageHandler(filters.Text('Add Task'), add_task)],
    states={
        ADD_TASK: [MessageHandler(filters.PHOTO & filters.CAPTION, save_task)]
    },
    fallbacks=[CommandHandler('cancel', cancel)]
)

add_task_proof_conv_handler = ConversationHandler(
    entry_points=[MessageHandler(filters.Text('Done Task ✔'), done_task)],
    states={
        ADD_TASK_PROOF: [MessageHandler(filters.PHOTO, save_task_proof)]
    },
    fallbacks=[CommandHandler('cancel', cancel)]
)

async def appv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id not in ADMIN_IDS:
        await update.message.reply_text("You are not authorized to use this command.")
        return

    if len(context.args) != 1:
        await update.message.reply_text("Usage: /appv <user_ids>")
        return

    # Extract user IDs from the argument
    user_ids = re.findall(r'\d+', context.args[0])
    if not user_ids:
        await update.message.reply_text("No valid user IDs found.")
        return

    for user_id in user_ids:
        user_id = int(user_id)

        # Add 10 MATIC to user's balance
        db.update_matic_balance(user_id, 10)

        # Get the date of the task proof submission
        proof_date = db.get_task_proof_date(user_id)
        if proof_date:
            try:
                proof_date = datetime.strptime(proof_date, '%Y-%m-%d %H:%M:%S.%f').strftime('%Y-%m-%d')
            except ValueError:
                await update.message.reply_text(f"Error: Invalid date format retrieved from database for user {user_id}.")
                continue

        # Send confirmation message
        await context.bot.send_message(
            chat_id=user_id,
            text=f"The task you applied for, posted on {proof_date}, has been approved ✔. You have received 10 MATIC coins."
        )

        await update.message.reply_text(f"Approved task proof for user {user_id}.")

    await update.message.reply_text("Task proofs approved for the specified users.")

async def dispv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id not in ADMIN_IDS:
        await update.message.reply_text("You are not authorized to use this command.")
        return

    if len(context.args) != 1:
        await update.message.reply_text("Usage: /dispv <user_ids>")
        return

    # Extract user IDs from the argument
    user_ids = re.findall(r'\d+', context.args[0])
    if not user_ids:
        await update.message.reply_text("No valid user IDs found.")
        return

    for user_id in user_ids:
        user_id = int(user_id)

        # Send disapproval message
        await context.bot.send_message(
            chat_id=user_id,
            text="Your task was Disapproved ❌, please perform the task next time."
        )

        await update.message.reply_text(f"Disapproved task proof for user {user_id}.")

    await update.message.reply_text("Task proofs disapproved for the specified users.")

async def most_referrals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id, referral_count = db.get_user_with_most_referrals()
    if user_id:
        await update.message.reply_text(f"User with ID {user_id} has the most referrals: {referral_count}")
    else:
        await update.message.reply_text("No referrals found.")

def main():
    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("admin", admin))
    application.add_handler(CommandHandler("appv", appv))
    application.add_handler(CommandHandler("dispv", dispv))
    application.add_handler(add_task_conv_handler)
    application.add_handler(add_task_proof_conv_handler)

    application.add_handler(CallbackQueryHandler(subscribed, pattern="subscribed"))
    application.add_handler(CallbackQueryHandler(handle_button_click))
    message_handler = MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    photo_handler = MessageHandler(filters.PHOTO, handle_message) 


    application.add_handler(MessageHandler(filters.Text("Cancel"), cancel))
    application.add_handler(message_handler)
    application.add_handler(photo_handler)

    application.run_polling()

def run_web_server():
    port = int(os.environ.get('PORT', 5000))
    handler = http.server.SimpleHTTPRequestHandler
    with socketserver.TCPServer(("", port), handler) as httpd:
        print(f"Serving at port {port}")
        httpd.serve_forever()

if __name__ == '__main__':
    # Run the web server in a separate thread
    server_thread = threading.Thread(target=run_web_server)
    server_thread.start()

    # Run the bot
    main()
