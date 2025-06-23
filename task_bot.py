#!/usr/bin/env python3
"""
Telegram Task Management Bot (Clean Rewrite)
- Admins can create tasks for users.
- When a task is due, the assignee gets a message with YES/NO buttons.
- If YES: mark as done, stop all reminders for that task/user.
- If NO or no response: remind every 2 minutes, up to a max.
- After YES, no further reminders for that task/user, ever.
"""
import os
import sqlite3
import logging
from datetime import datetime, timedelta
from typing import List
import pytz

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, ContextTypes, filters, MessageHandler
)

# --- CONFIG ---
DB_PATH = "tasks.db"
REMINDER_INTERVAL = 120  # seconds (2 minutes)
MAX_REMINDERS = 30

# --- TIMEZONE SETUP ---
PST = pytz.timezone('America/Los_Angeles')  # This handles PST/PDT automatically
UTC = pytz.timezone('UTC')

def get_pst_now():
    """Get current time in PST/PDT"""
    return datetime.now(PST)

def get_utc_now():
    """Get current time in UTC"""
    return datetime.now(UTC)

def pst_to_utc(pst_time):
    """Convert PST time to UTC for database storage"""
    if isinstance(pst_time, str):
        # Parse time string (HH:MM) and add today's date in PST
        time_parts = pst_time.split(':')
        hour, minute = int(time_parts[0]), int(time_parts[1])
        pst_now = get_pst_now()
        pst_dt = pst_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        # If the time has already passed today, schedule for tomorrow
        if pst_dt <= pst_now:
            pst_dt += timedelta(days=1)
    else:
        pst_dt = pst_time
    
    return pst_dt.astimezone(UTC)

def utc_to_pst(utc_time):
    """Convert UTC time to PST for display"""
    if isinstance(utc_time, str):
        utc_dt = UTC.localize(datetime.fromisoformat(utc_time.replace('Z', '')))
    else:
        if utc_time.tzinfo is None:
            utc_dt = UTC.localize(utc_time)
        else:
            utc_dt = utc_time
    
    return utc_dt.astimezone(PST)

# --- LOGGING ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- DATABASE ---
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            assignee_id INTEGER NOT NULL,
            assignee_username TEXT NOT NULL,
            description TEXT NOT NULL,
            scheduled_time TEXT NOT NULL,
            frequency TEXT NOT NULL,
            is_done INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            reminder_count INTEGER DEFAULT 0,
            last_reminder TIMESTAMP,
            FOREIGN KEY (task_id) REFERENCES tasks(id)
        )
    ''')
    # Add users table to track user IDs by username
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            username TEXT NOT NULL,
            first_name TEXT,
            last_name TEXT,
            last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(id, username)
        )
    ''')
    conn.commit()
    conn.close()

# --- BOT CLASS ---
class TaskBot:
    def __init__(self, token: str, admin_ids: List[int]):
        self.token = token
        self.admin_ids = admin_ids
        self.application = None
        init_db()

    def _is_admin(self, user_id: int) -> bool:
        return user_id in self.admin_ids

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.message:
            return
        
        # Track the user
        await self._track_user(update.effective_user)
        
        await update.message.reply_text(
            "Welcome! Admins can create tasks with /createtask @username description time frequency (e.g. /createtask @john Take out trash 14:00 daily).\n\n"
            "Commands:\n"
            "/createtask - Create a new task\n"
            "/tasks - List all tasks\n"
            "/removetask - Remove a task\n"
            "/debug - Show debug info (admin only)\n"
            "/test - Test reminders (admin only)\n"
            "/testtask - Create a test task (admin only)\n"
            "/time - Show current PST time\n\n"
            "⏰ All times are in PST (Pacific Time)\n\n"
            "💡 **Tip:** I'll send task reminders privately to you. Task completions will be announced in the group."
        )

    async def debug(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.message or not update.effective_user:
            return
        
        # Track the user
        await self._track_user(update.effective_user)
        
        user_id = update.effective_user.id
        if not self._is_admin(user_id):
            await update.message.reply_text("❌ Only admins can use debug.")
            return
        
        pst_now = get_pst_now()
        utc_now = get_utc_now()
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        
        # Get all tasks
        c.execute('''SELECT id, chat_id, assignee_username, description, scheduled_time, frequency, is_done FROM tasks''')
        tasks = c.fetchall()
        
        # Get all reminders
        c.execute('''SELECT task_id, reminder_count, last_reminder FROM reminders''')
        reminders = c.fetchall()
        
        # Get tracked users
        c.execute('''SELECT username, id, first_name FROM users ORDER BY last_seen DESC LIMIT 10''')
        users = c.fetchall()
        
        conn.close()
        
        msg = f"🐛 Debug Info\n\n"
        msg += f"PST time: {pst_now.strftime('%Y-%m-%d %H:%M:%S %Z')}\n"
        msg += f"UTC time: {utc_now.strftime('%Y-%m-%d %H:%M:%S %Z')}\n\n"
        msg += f"Tasks ({len(tasks)}):\n"
        for task in tasks:
            task_id, chat_id, username, desc, sched_time, freq, is_done = task
            status = "✅ Done" if is_done else "⏳ Pending"
            msg += f"ID {task_id}: @{username} - {desc[:30]}...\n"
            msg += f"  Time: {sched_time} PST ({freq}) - {status}\n"
        
        msg += f"\nReminders ({len(reminders)}):\n"
        for task_id, count, last_reminder in reminders:
            msg += f"Task {task_id}: {count} reminders, last: {last_reminder}\n"
        
        msg += f"\nTracked Users ({len(users)}):\n"
        for username, user_id, first_name in users:
            msg += f"@{username} (ID: {user_id}, {first_name})\n"
        
        await update.message.reply_text(msg)

    async def test(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.message or not update.effective_user:
            return
        
        # Track the user
        await self._track_user(update.effective_user)
        
        user_id = update.effective_user.id
        if not self._is_admin(user_id):
            await update.message.reply_text("❌ Only admins can use test.")
            return
        
        await update.message.reply_text("🧪 Testing reminder system...")
        await self.send_reminders(context)
        await update.message.reply_text("✅ Reminder test completed. Check logs for details.")

    async def testtask(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.message or not update.effective_user:
            return
        
        # Track the user
        await self._track_user(update.effective_user)
        
        user_id = update.effective_user.id
        if not self._is_admin(user_id):
            await update.message.reply_text("❌ Only admins can use testtask.")
            return
        
        if len(context.args) < 1:
            await update.message.reply_text("❌ Usage: /testtask @username [description]")
            return
            
        username = context.args[0].lstrip('@')
        description = " ".join(context.args[1:]) if len(context.args) > 1 else "Test task"
        
        # Create task for current PST time + 1 minute
        pst_now = get_pst_now()
        test_time = pst_now + timedelta(minutes=1)
        time_str = test_time.strftime("%H:%M")
        
        # Use placeholder ID for any user
        assignee_id = 0  # Placeholder - we'll mention by username instead
            
        # Save task (store the PST time string, conversion to UTC happens in reminder logic)
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''
            INSERT INTO tasks (chat_id, assignee_id, assignee_username, description, scheduled_time, frequency)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (update.effective_chat.id, assignee_id, username, description, time_str, "once"))
        task_id = c.lastrowid
        conn.commit()
        conn.close()
        
        logger.info(f"Created test task {task_id} for @{username} at {time_str} PST")
        await update.message.reply_text(
            f"🧪 Test task created!\n\n"
            f"Task ID: {task_id}\n"
            f"Assignee: @{username}\n"
            f"Description: {description}\n"
            f"Time: {time_str} PST (in 1 minute)\n"
            f"Current PST time: {pst_now.strftime('%H:%M:%S')}\n\n"
            f"You should get a **private reminder** in about 1-2 minutes!"
        )

    async def time(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.message:
            return
        
        # Track the user
        await self._track_user(update.effective_user)
        
        pst_now = get_pst_now()
        utc_now = get_utc_now()
        await update.message.reply_text(
            f"⏰ Current Time\n\n"
            f"PST: {pst_now.strftime('%H:%M:%S %Z')}\n"
            f"Date: {pst_now.strftime('%Y-%m-%d')}\n"
            f"UTC: {utc_now.strftime('%H:%M:%S %Z')}\n\n"
            f"To create a task for now, use: {pst_now.strftime('%H:%M')}\n"
            f"To create a task for +5 min, use: {(pst_now + timedelta(minutes=5)).strftime('%H:%M')}\n\n"
            f"💡 All times are in PST (Pacific Time)"
        )

    async def createtask(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.message or not update.effective_user:
            return
        
        # Track the user
        await self._track_user(update.effective_user)
        
        user_id = update.effective_user.id
        if not self._is_admin(user_id):
            await update.message.reply_text("❌ Only admins can create tasks.")
            return
        if len(context.args) < 4:
            await update.message.reply_text("❌ Usage: /createtask @username description time frequency\n⏰ Time should be in PST (e.g., 14:00)")
            return
        username = context.args[0].lstrip('@')
        time_str = context.args[-2]
        frequency = context.args[-1].lower()
        description = " ".join(context.args[1:-2])
        # Validate time
        try:
            datetime.strptime(time_str, "%H:%M")
        except ValueError:
            await update.message.reply_text("❌ Time must be in HH:MM 24-hour format (PST).")
            return
        if frequency not in ["once", "daily"]:
            await update.message.reply_text("❌ Frequency must be 'once' or 'daily'.")
            return
        
        # For now, we'll store the username and use 0 as placeholder for user_id
        # The bot will still work by mentioning @username in messages
        assignee_id = 0  # Placeholder - we'll mention by username instead
        
        # Save task
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''
            INSERT INTO tasks (chat_id, assignee_id, assignee_username, description, scheduled_time, frequency)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (update.effective_chat.id, assignee_id, username, description, time_str, frequency))
        task_id = c.lastrowid
        conn.commit()
        conn.close()
        logger.info(f"Created task {task_id} for @{username} at {time_str} PST")
        await update.message.reply_text(f"✅ Task created for @{username}: {description} at {time_str} PST ({frequency})\nTask ID: {task_id}\n\n💡 **Note:** Reminders will be sent privately to @{username}. Completion will be announced in this group.")

    async def tasks(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.message or not update.effective_chat:
            return
        
        # Track the user
        await self._track_user(update.effective_user)
        
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''SELECT id, assignee_username, description, scheduled_time, frequency, is_done FROM tasks WHERE chat_id = ?''', (update.effective_chat.id,))
        rows = c.fetchall()
        conn.close()
        if not rows:
            await update.message.reply_text("No tasks found.")
            return
        msg = "Tasks:\n"
        for row in rows:
            status = "✅" if row[5] else "⏳"
            msg += f"ID {row[0]}: @{row[1]} - {row[2]} at {row[3]} PST ({row[4]}) {status}\n"
        await update.message.reply_text(msg)

    async def removetask(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.message or not update.effective_user:
            return
        
        # Track the user
        await self._track_user(update.effective_user)
        
        user_id = update.effective_user.id
        if not self._is_admin(user_id):
            await update.message.reply_text("❌ Only admins can remove tasks.")
            return
        if not context.args:
            await update.message.reply_text("❌ Usage: /removetask task_id")
            return
        try:
            task_id = int(context.args[0])
        except ValueError:
            await update.message.reply_text("❌ Task ID must be a number.")
            return
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('DELETE FROM tasks WHERE id = ?', (task_id,))
        c.execute('DELETE FROM reminders WHERE task_id = ?', (task_id,))
        conn.commit()
        conn.close()
        await update.message.reply_text(f"✅ Task {task_id} removed.")

    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        if not query:
            return
        await query.answer()
        
        # Track the user responding
        await self._track_user(query.from_user)
        
        data = query.data
        if not data or not data.startswith("task_"):
            return
        parts = data.split('_')
        if len(parts) < 3:
            return
        try:
            task_id = int(parts[1])
            response = parts[2]
        except (ValueError, IndexError):
            await query.edit_message_text("❌ Invalid response data.")
            return
        
        # Get the task details to check if this user can respond
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('SELECT assignee_username, is_done, chat_id, description FROM tasks WHERE id = ?', (task_id,))
        row = c.fetchone()
        if not row:
            await query.edit_message_text("❌ Task not found.")
            conn.close()
            return
            
        assignee_username, is_done, original_chat_id, task_description = row
        
        # Check if task is already done
        if is_done:
            await query.edit_message_text("✅ This task is already completed.")
            conn.close()
            return
        
        # Check if the responding user matches the assigned username
        responding_user = query.from_user
        if responding_user.username and responding_user.username.lower() != assignee_username.lower():
            await query.edit_message_text(f"❌ This task is assigned to @{assignee_username}, not you.")
            conn.close()
            return
        
        # If user doesn't have a username but we still want to allow responses
        # (some users might not have usernames set)
        if not responding_user.username:
            await query.edit_message_text(f"❌ Please set a Telegram username to respond to tasks. This task is for @{assignee_username}.")
            conn.close()
            return
            
        if response == "yes":
            c.execute('UPDATE tasks SET is_done = 1 WHERE id = ?', (task_id,))
            c.execute('DELETE FROM reminders WHERE task_id = ?', (task_id,))
            await query.edit_message_text("✅ Task marked as complete! You will not be reminded again.")
            
            # Send completion message to the original group
            try:
                await context.bot.send_message(
                    chat_id=original_chat_id,
                    text=f"✅ **Task Completed**\n\n@{assignee_username} has completed: {task_description}"
                )
                logger.info(f"Sent completion notification to group {original_chat_id}")
            except Exception as e:
                logger.error(f"Failed to send completion message to group: {e}")
            
            logger.info(f"Task {task_id} marked as complete by @{responding_user.username}")
        elif response == "no":
            # Increment reminder count and schedule next
            c.execute('SELECT reminder_count FROM reminders WHERE task_id = ?', (task_id,))
            row = c.fetchone()
            if row:
                count = row[0] + 1
                c.execute('UPDATE reminders SET reminder_count = ?, last_reminder = ? WHERE task_id = ?', (count, get_utc_now(), task_id))
            else:
                count = 1
                c.execute('INSERT INTO reminders (task_id, reminder_count, last_reminder) VALUES (?, ?, ?)', (task_id, count, get_utc_now()))
            await query.edit_message_text("📝 Task not completed. I will remind you again in 2 minutes.")
            logger.info(f"Task {task_id} marked as not done by @{responding_user.username}, will remind again")
        conn.commit()
        conn.close()

    async def send_reminders(self, context: ContextTypes.DEFAULT_TYPE):
        utc_now = get_utc_now()
        pst_now = get_pst_now()
        logger.info(f"=== REMINDER CHECK START ===")
        logger.info(f"Current PST time: {pst_now.strftime('%Y-%m-%d %H:%M:%S %Z')}")
        logger.info(f"Current UTC time: {utc_now.strftime('%Y-%m-%d %H:%M:%S %Z')}")
        
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        
        # Get all tasks that are not done
        c.execute('''SELECT id, chat_id, assignee_id, assignee_username, description, scheduled_time, frequency FROM tasks WHERE is_done = 0''')
        tasks = c.fetchall()
        logger.info(f"Found {len(tasks)} active tasks")
        
        for task in tasks:
            task_id, chat_id, assignee_id, username, description, sched_time, freq = task
            logger.info(f"--- Checking Task {task_id} ---")
            logger.info(f"Task: @{username} - {description}")
            logger.info(f"Scheduled time: {sched_time} PST")
            logger.info(f"Frequency: {freq}")
            
            # Check if it's time to remind (compare PST times)
            current_pst_time = pst_now.strftime("%H:%M")
            logger.info(f"Current PST time: {current_pst_time}")
            
            try:
                sched_hour, sched_min = map(int, sched_time.split(':'))
                current_hour, current_min = pst_now.hour, pst_now.minute
                
                # Check if current time is within 2 minutes of scheduled time
                time_diff = abs((current_hour * 60 + current_min) - (sched_hour * 60 + sched_min))
                time_match = time_diff <= 2
                
                logger.info(f"Time difference: {time_diff} minutes")
                logger.info(f"Time match (within 2 min): {time_match}")
                
                if time_match:
                    logger.info(f"✅ Time matches for task {task_id}!")
                    
                    # Check if already reminded recently (using UTC for consistency)
                    c.execute('SELECT last_reminder, reminder_count FROM reminders WHERE task_id = ?', (task_id,))
                    row = c.fetchone()
                    
                    should_remind = True
                    reason = ""
                    
                    if row:
                        last_reminder, reminder_count = row
                        logger.info(f"Existing reminder record: count={reminder_count}, last={last_reminder}")
                        
                        if reminder_count >= MAX_REMINDERS:
                            should_remind = False
                            reason = f"Max reminders reached ({reminder_count}/{MAX_REMINDERS})"
                        elif last_reminder:
                            try:
                                last_dt = datetime.fromisoformat(last_reminder)
                                if last_dt.tzinfo is None:
                                    last_dt = UTC.localize(last_dt)
                                seconds_since = (utc_now - last_dt).total_seconds()
                                logger.info(f"Seconds since last reminder: {seconds_since}")
                                if seconds_since < REMINDER_INTERVAL:
                                    should_remind = False
                                    reason = f"Too soon since last reminder ({seconds_since}s < {REMINDER_INTERVAL}s)"
                            except ValueError as e:
                                logger.error(f"Invalid date format: {last_reminder}, error: {e}")
                    else:
                        logger.info("No existing reminder record - first time")
                    
                    if should_remind:
                        logger.info(f"🚀 SENDING REMINDER for task {task_id}")
                        try:
                            await self._send_task_reminder(context, chat_id, assignee_id, username, description, task_id)
                            # Update reminders table
                            if row:
                                new_count = (reminder_count or 0) + 1
                                c.execute('UPDATE reminders SET last_reminder = ?, reminder_count = ? WHERE task_id = ?', 
                                        (utc_now, new_count, task_id))
                                logger.info(f"Updated reminder count to {new_count}")
                            else:
                                c.execute('INSERT INTO reminders (task_id, reminder_count, last_reminder) VALUES (?, ?, ?)', 
                                        (task_id, 1, utc_now))
                                logger.info(f"Created new reminder record")
                        except Exception as e:
                            logger.error(f"Failed to send/record reminder: {e}")
                    else:
                        logger.info(f"❌ Not sending reminder: {reason}")
                else:
                    logger.info(f"❌ Time doesn't match for task {task_id}")
                    
            except Exception as e:
                logger.error(f"Error processing task {task_id}: {e}")
        
        # Send follow-up reminders for tasks with NO or no response
        logger.info(f"--- CHECKING FOLLOW-UP REMINDERS ---")
        c.execute('''SELECT r.task_id, t.chat_id, t.assignee_id, t.assignee_username, t.description, r.reminder_count, r.last_reminder FROM reminders r JOIN tasks t ON r.task_id = t.id WHERE t.is_done = 0 AND r.reminder_count < ?''', (MAX_REMINDERS,))
        follow_ups = c.fetchall()
        logger.info(f"Found {len(follow_ups)} tasks needing follow-up reminders")
        
        for row in follow_ups:
            task_id, chat_id, assignee_id, username, description, reminder_count, last_reminder = row
            logger.info(f"Follow-up check for task {task_id}: count={reminder_count}, last={last_reminder}")
            
            if last_reminder:
                try:
                    last_dt = datetime.fromisoformat(last_reminder)
                    if last_dt.tzinfo is None:
                        last_dt = UTC.localize(last_dt)
                    seconds_since = (utc_now - last_dt).total_seconds()
                    logger.info(f"Seconds since last follow-up: {seconds_since}")
                    
                    if seconds_since >= REMINDER_INTERVAL:
                        logger.info(f"🚀 SENDING FOLLOW-UP reminder for task {task_id}")
                        await self._send_task_reminder(context, chat_id, assignee_id, username, description, task_id)
                        c.execute('UPDATE reminders SET last_reminder = ?, reminder_count = ? WHERE task_id = ?', 
                                (utc_now, reminder_count + 1, task_id))
                    else:
                        logger.info(f"❌ Too soon for follow-up ({seconds_since}s < {REMINDER_INTERVAL}s)")
                except ValueError as e:
                    logger.error(f"Invalid date format for task {task_id}: {last_reminder}, error: {e}")
        
        conn.commit()
        conn.close()
        logger.info(f"=== REMINDER CHECK END ===")

    async def _track_user(self, user):
        """Track user information for private messaging"""
        if not user or not user.username:
            return
        
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''
            INSERT OR REPLACE INTO users (id, username, first_name, last_name, last_seen)
            VALUES (?, ?, ?, ?, ?)
        ''', (user.id, user.username.lower(), user.first_name, user.last_name, get_utc_now()))
        conn.commit()
        conn.close()
        logger.debug(f"Tracked user @{user.username} (ID: {user.id})")

    async def _get_user_id_by_username(self, username):
        """Get user ID by username from our database"""
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('SELECT id FROM users WHERE username = ?', (username.lower(),))
        row = c.fetchone()
        conn.close()
        return row[0] if row else None

    async def _send_task_reminder(self, context, chat_id, assignee_id, username, description, task_id):
        keyboard = [
            [
                InlineKeyboardButton("✅ YES", callback_data=f"task_{task_id}_yes"),
                InlineKeyboardButton("❌ NO", callback_data=f"task_{task_id}_no")
            ]
        ]
        markup = InlineKeyboardMarkup(keyboard)
        
        # Try to get user ID from our database
        user_id_to_dm = await self._get_user_id_by_username(username)
        
        # Try to send a direct message first
        reminder_sent_privately = False
        if user_id_to_dm:
            try:
                await context.bot.send_message(
                    chat_id=user_id_to_dm,
                    text=f"⏰ **Task Reminder**\n\nYou have a task due: {description}\n\nHave you completed it?",
                    reply_markup=markup
                )
                logger.info(f"Successfully sent private reminder for task {task_id} to @{username}")
                reminder_sent_privately = True
            except Exception as e:
                logger.warning(f"Failed to send private message to @{username}: {e}")
        
        # If private message failed or user ID not found, send to group with a note
        if not reminder_sent_privately:
            try:
                bot_username = context.bot.username if hasattr(context.bot, 'username') else "this bot"
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"⏰ **Private Task Reminder**\n\n@{username}, you have a task due: {description}\n\nHave you completed it?\n\n💡 *I tried to send this privately, but couldn't reach you. Please start a chat with @{bot_username} to receive private reminders.*",
                    reply_markup=markup
                )
                logger.info(f"Sent group reminder for task {task_id} to @{username} (private message failed)")
            except Exception as e:
                logger.error(f"Failed to send reminder for task {task_id}: {e}")

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.message:
            return
        
        # Track the user
        await self._track_user(update.effective_user)
        
        help_text = """📋 **Task Management Bot Help**

**📝 Creating Tasks:**
• `/createtask @username description time frequency`
• Example: `/createtask @john Clean office 09:00 daily`
• Example: `/createtask @jane Submit report 17:30 once`

**⏰ Time & Frequency:**
• Time format: 24-hour PST (09:00, 17:30, 23:45)
• Frequency: `once` (one-time) or `daily` (repeats daily)
• All times are in Pacific Time (PST/PDT)

**📋 Managing Tasks:**
• `/tasks` - View all active tasks with their IDs
• `/removetask 5` - Remove task with ID 5
• `/time` - Show current PST time

**🔔 Task Responses:**
When you get a task reminder:
• ✅ **YES** - Task completed (stops all reminders)
• ❌ **NO** - Task not completed (reminds again in 2 minutes)

**👥 How Reminders Work:**
• **Private reminders** sent to you via DM
• **Group announcements** when tasks are completed
• Automatic follow-ups every 2 minutes until completed
• Maximum 30 reminders per task

**🔧 Admin Commands:**
• `/debug` - Show system status and tracked users
• `/test` - Manually trigger reminder system
• `/testtask @username` - Create test task for immediate testing

**💡 Tips:**
• Start a private chat with the bot to receive DM reminders
• Only assigned users can respond to their tasks
• Task completions are announced in the group
• Use `/time` to see current PST time for scheduling

**🆘 Need Help?**
Contact your group administrators for task management assistance."""
        
        await update.message.reply_text(help_text, parse_mode='Markdown')

    def run(self):
        self.application = Application.builder().token(self.token).build()
        self.application.add_handler(CommandHandler("start", self.start))
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(CommandHandler("createtask", self.createtask))
        self.application.add_handler(CommandHandler("tasks", self.tasks))
        self.application.add_handler(CommandHandler("removetask", self.removetask))
        self.application.add_handler(CommandHandler("debug", self.debug))
        self.application.add_handler(CommandHandler("test", self.test))
        self.application.add_handler(CommandHandler("testtask", self.testtask))
        self.application.add_handler(CommandHandler("time", self.time))
        self.application.add_handler(CallbackQueryHandler(self.handle_callback))
        # Run reminders every 2 minutes
        self.application.job_queue.run_repeating(self.send_reminders, interval=REMINDER_INTERVAL, first=5)
        logger.info("Bot started.")
        self.application.run_polling()

# --- MAIN ---
def main():
    BOT_TOKEN = os.getenv('BOT_TOKEN', 'PASTE_YOUR_BOT_TOKEN_HERE')
    ADMIN_IDS = os.getenv('ADMIN_IDS', '123456789').split(',')
    ADMIN_IDS = [int(x.strip()) for x in ADMIN_IDS if x.strip().isdigit()]
    if BOT_TOKEN == 'PASTE_YOUR_BOT_TOKEN_HERE':
        print("Please set your BOT_TOKEN in the environment or in the code.")
        return
    bot = TaskBot(token=BOT_TOKEN, admin_ids=ADMIN_IDS)
    bot.run()

if __name__ == '__main__':
    main()
