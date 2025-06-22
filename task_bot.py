#!/usr/bin/env python3
"""
Telegram Task Management Bot
A comprehensive bot for assigning and tracking tasks in Telegram groups.

Author: AI Assistant
Requirements: python-telegram-bot, schedule, sqlite3 (built-in)
"""

import os
import sqlite3
import logging
import asyncio
import schedule
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from threading import Thread

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters
)

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Pacific Time Zone setup - simplified approach
def get_pst_now() -> datetime:
    """Get current time in PST (UTC-8) or PDT (UTC-7)."""
    utc_now = datetime.utcnow()
    # Simple PST offset (this handles most cases)
    pst_offset = timedelta(hours=-8)  # PST is UTC-8
    return utc_now + pst_offset

def pst_datetime_to_utc(year: int, month: int, day: int, hour: int, minute: int) -> datetime:
    """Convert PST date/time to UTC for database storage."""
    pst_time = datetime(year, month, day, hour, minute)
    # Convert PST to UTC (add 8 hours)
    return pst_time + timedelta(hours=8)

def utc_to_pst_display(utc_time) -> str:
    """Convert UTC time to PST for display."""
    try:
        if isinstance(utc_time, str):
            utc_dt = datetime.fromisoformat(utc_time.replace('Z', ''))
        else:
            utc_dt = utc_time
        
        # Convert UTC to PST (subtract 8 hours)
        pst_dt = utc_dt - timedelta(hours=8)
        return pst_dt.strftime('%Y-%m-%d %H:%M PST')
    except:
        return "Not scheduled"

class TaskBot:
    def __init__(self, token: str, admin_ids: List[int], db_path: str = "tasks.db"):
        """
        Initialize the Task Management Bot.
        
        Args:
            token: Telegram Bot Token from BotFather
            admin_ids: List of Telegram user IDs who can manage tasks
            db_path: Path to SQLite database file
        """
        self.token = token
        self.admin_ids = admin_ids
        self.db_path = db_path
        self.application = None
        self.pending_responses: Dict[str, Dict] = {}  # Track pending task responses
        
        # Initialize database
        self._init_database()
        
        # Start background task checker
        self._start_background_checker()
        
    def _init_database(self) -> None:
        """Initialize SQLite database with required tables."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Tasks table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                assignee_username TEXT NOT NULL,
                assignee_user_id INTEGER,
                chat_id INTEGER NOT NULL,
                created_by INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                scheduled_time TEXT NOT NULL,
                frequency TEXT NOT NULL,
                is_active BOOLEAN DEFAULT 1,
                last_run TIMESTAMP,
                next_run TIMESTAMP
            )
        ''')
        
        # Task responses table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS task_responses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER,
                user_id INTEGER,
                chat_id INTEGER,
                response TEXT,
                responded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (task_id) REFERENCES tasks (id)
            )
        ''')
        
        # Pending reminders table for 5-minute follow-ups
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS pending_reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER,
                user_id INTEGER,
                username TEXT,
                chat_id INTEGER,
                task_title TEXT,
                frequency TEXT,
                next_reminder TIMESTAMP,
                reminder_count INTEGER DEFAULT 0,
                max_reminders INTEGER DEFAULT 12,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (task_id) REFERENCES tasks (id)
            )
        ''')
        
        conn.commit()
        conn.close()
        
    def _is_admin(self, user_id: int) -> bool:
        """Check if user is authorized to manage tasks."""
        return user_id in self.admin_ids
        
    def _get_user_by_username(self, username: str, chat_id: int) -> Optional[int]:
        """
        Get user ID from username by checking chat members.
        Note: This is a simplified version. In production, you might want to
        maintain a user cache or use a different approach.
        """
        # Remove @ if present
        username = username.lstrip('@')
        return None  # Placeholder - would need chat member enumeration
        
    def _parse_time(self, time_str: str) -> Optional[str]:
        """
        Parse time string into a standardized format.
        Supports formats like "14:30", "2:30pm", "14:30:00"
        """
        try:
            # Try different time formats
            for fmt in ["%H:%M", "%I:%M%p", "%H:%M:%S", "%I:%M:%S%p"]:
                try:
                    parsed_time = datetime.strptime(time_str.upper(), fmt)
                    return parsed_time.strftime("%H:%M")
                except ValueError:
                    continue
            return None
        except Exception:
            return None
            
    def _calculate_next_run(self, scheduled_time: str, frequency: str) -> datetime:
        """Calculate the next run time for a task in PST."""
        now_pst = get_pst_now()
        time_parts = scheduled_time.split(":")
        hour, minute = int(time_parts[0]), int(time_parts[1])
        
        if frequency == "once":
            # Schedule for today if time hasn't passed, otherwise tomorrow (in PST)
            next_run_pst = now_pst.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if next_run_pst <= now_pst:
                next_run_pst += timedelta(days=1)
        elif frequency == "daily":
            # Schedule for today if time hasn't passed, otherwise tomorrow (in PST)
            next_run_pst = now_pst.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if next_run_pst <= now_pst:
                next_run_pst += timedelta(days=1)
        else:
            # Default to once
            next_run_pst = now_pst.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if next_run_pst <= now_pst:
                next_run_pst += timedelta(days=1)
        
        # Convert to UTC for database storage (add 8 hours)
        return next_run_pst + timedelta(hours=8)
        
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /start command."""
        welcome_message = """
🤖 **Task Management Bot**

I help you assign and track tasks in your group!

**Admin Commands:**
• `/createtask @username [description] [time] [frequency]` - Create a new task
• `/tasks` - List all active tasks
• `/removetask [task_id]` - Remove a task
• `/help` - Show this help message

**For regular users:**
• Simply respond "yes" or "no" when asked about task completion

        **Time format:** Use 24-hour format (e.g., 14:30) or 12-hour with AM/PM (e.g., 2:30PM) - all times are in PST
**Frequency options:** once, daily

Need help? Use /help for detailed instructions!
        """
        await update.message.reply_text(welcome_message, parse_mode='Markdown')
        
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /help command."""
        if not update.message:
            return
            
        help_text = """📋 Task Management Bot Help

Creating Tasks:
/createtask @john Clean office 09:00 daily
/createtask @jane Submit report 17:30 once

Managing Tasks:
• /tasks - View all active tasks with their IDs
• /removetask 5 - Remove task with ID 5

Task Responses:
When you're mentioned for a task, simply reply:
• "yes" - Task completed ✅
• "no" - Task not completed ❌

Time Formats:
• 24-hour: 09:00, 17:30, 23:45 (PST)
• 12-hour: 9:00AM, 5:30PM, 11:45PM (PST)

Frequency Options:
• once - One-time task
• daily - Repeats every day at the specified time

Admin Features:
Only authorized admins can create and remove tasks.

Automatic Follow-ups:
If you don't respond or say "no", the bot will ask again after 5 minutes.

Note: All times are in Pacific Standard Time (PST/PDT)."""
        
        await update.message.reply_text(help_text)
        
    async def create_task_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /createtask command."""
        if not update.message or not update.effective_user:
            return
            
        user_id = update.effective_user.id
        
        # Check if user is admin
        if not self._is_admin(user_id):
            await update.message.reply_text("❌ Only admins can create tasks.")
            return
            
        # Parse command arguments
        if len(context.args) < 4:
            await update.message.reply_text(
                "❌ Usage: /createtask @username [task description] [time] [frequency]\n"
                "Example: /createtask @john Clean office 09:00 daily"
            )
            return
            
        username = context.args[0]
        time_str = context.args[-2]
        frequency = context.args[-1].lower()
        description = " ".join(context.args[1:-2])
        
        # Validate inputs
        if not username.startswith('@'):
            await update.message.reply_text("❌ Username must start with @")
            return
            
        username = username[1:]  # Remove @
        
        # Validate time format
        parsed_time = self._parse_time(time_str)
        if not parsed_time:
            await update.message.reply_text(
                "❌ Invalid time format. Use HH:MM (24-hour) or HH:MMAM/PM"
            )
            return
            
        # Validate frequency
        if frequency not in ['once', 'daily']:
            await update.message.reply_text(
                "❌ Frequency must be 'once' or 'daily'"
            )
            return
            
        # Calculate next run time
        next_run = self._calculate_next_run(parsed_time, frequency)
        
        # Save task to database
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO tasks (title, assignee_username, chat_id, created_by, 
                             scheduled_time, frequency, next_run)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (description, username, update.effective_chat.id, user_id, 
              parsed_time, frequency, next_run))
        
        task_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        await update.message.reply_text(
            f"✅ Task created successfully!\n\n"
            f"Task ID: {task_id}\n"
            f"Assignee: @{username}\n"
            f"Description: {description}\n"
            f"Time: {parsed_time} PST\n"
            f"Frequency: {frequency}\n"
            f"Next run: {utc_to_pst_display(next_run)}"
        )
        
    async def list_tasks_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /tasks command."""
        if not update.message or not update.effective_chat:
            return
            
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT id, title, assignee_username, scheduled_time, frequency, 
                   next_run, is_active
            FROM tasks 
            WHERE chat_id = ? AND is_active = 1
            ORDER BY next_run
        ''', (update.effective_chat.id,))
        
        tasks = cursor.fetchall()
        conn.close()
        
        if not tasks:
            await update.message.reply_text("📝 No active tasks found.")
            return
            
        message = "📋 Active Tasks:\n\n"
        
        for task in tasks:
            task_id, title, username, time, freq, next_run, active = task
            
            if next_run:
                next_run_str = utc_to_pst_display(next_run)
            else:
                next_run_str = "Not scheduled"
                
            message += f"ID {task_id}: {title}\n"
            message += f"👤 @{username} | ⏰ {time} PST | 🔄 {freq}\n"
            message += f"📅 Next: {next_run_str}\n\n"
            
        await update.message.reply_text(message)
        
    async def remove_task_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /removetask command."""
        if not update.message or not update.effective_user or not update.effective_chat:
            return
            
        user_id = update.effective_user.id
        
        # Check if user is admin
        if not self._is_admin(user_id):
            await update.message.reply_text("❌ Only admins can remove tasks.")
            return
            
        if not context.args:
            await update.message.reply_text("❌ Usage: /removetask [task_id]")
            return
            
        try:
            task_id = int(context.args[0])
        except ValueError:
            await update.message.reply_text("❌ Task ID must be a number.")
            return
            
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Check if task exists and belongs to this chat
        cursor.execute('''
            SELECT title, assignee_username FROM tasks 
            WHERE id = ? AND chat_id = ? AND is_active = 1
        ''', (task_id, update.effective_chat.id))
        
        task = cursor.fetchone()
        
        if not task:
            await update.message.reply_text("❌ Task not found or already removed.")
            conn.close()
            return
            
        # Mark task as inactive
        cursor.execute('''
            UPDATE tasks SET is_active = 0 WHERE id = ?
        ''', (task_id,))
        
        conn.commit()
        conn.close()
        
        title, username = task
        await update.message.reply_text(
            f"✅ Task removed successfully!\n\n"
            f"Task: {title}\n"
            f"Was assigned to: @{username}"
        )
        
    async def handle_task_response(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle user responses to task completion queries."""
        if not update.message or not update.effective_user or not update.effective_chat:
            return
            
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
        message_text = update.message.text.lower().strip()
        
        # Check if this is a response to a pending task
        pending_key = f"{user_id}_{chat_id}"
        
        if pending_key not in self.pending_responses:
            return  # Not a task response
            
        if message_text not in ['yes', 'no']:
            return  # Not a valid response
            
        # Get pending task info
        task_info = self.pending_responses[pending_key]
        task_id = task_info['task_id']
        
        # Save response to database
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO task_responses (task_id, user_id, chat_id, response)
            VALUES (?, ?, ?, ?)
        ''', (task_id, user_id, chat_id, message_text))
        
        # Remove from pending responses
        del self.pending_responses[pending_key]
        
        if message_text == 'yes':
            # Task completed - remove any pending reminders
            cursor.execute('''
                DELETE FROM pending_reminders 
                WHERE task_id = ? AND user_id = ? AND chat_id = ?
            ''', (task_id, user_id, chat_id))
            
            await update.message.reply_text(
                f"✅ Great! Task completed: {task_info['title']}"
            )
            # Update next run for recurring tasks
            await self._update_next_run(task_id, task_info['frequency'])
            
        else:  # message_text == 'no'
            # Task not completed - set up persistent 5-minute reminders
            next_reminder_utc = datetime.utcnow() + timedelta(minutes=5)
            
            cursor.execute('''
                INSERT OR REPLACE INTO pending_reminders 
                (task_id, user_id, username, chat_id, task_title, frequency, next_reminder, reminder_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, 1)
            ''', (task_id, user_id, task_info['assignee_username'], chat_id, 
                  task_info['title'], task_info['frequency'], next_reminder_utc))
            
            await update.message.reply_text(
                f"❌ Task not completed: {task_info['title']}\n"
                "💡 I'll remind you again in 5 minutes until it's done!"
            )
            
        conn.commit()
        conn.close()
            
    async def _update_next_run(self, task_id: int, frequency: str) -> None:
        """Update next run time for recurring tasks."""
        if frequency != 'daily':
            # Mark one-time tasks as inactive
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('UPDATE tasks SET is_active = 0 WHERE id = ?', (task_id,))
            conn.commit()
            conn.close()
            return
            
        # Calculate next run for daily tasks
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('SELECT scheduled_time FROM tasks WHERE id = ?', (task_id,))
        result = cursor.fetchone()
        
        if result:
            scheduled_time = result[0]
            next_run = self._calculate_next_run(scheduled_time, 'daily')
            
            cursor.execute('''
                UPDATE tasks SET next_run = ?, last_run = CURRENT_TIMESTAMP 
                WHERE id = ?
            ''', (next_run, task_id))
            
        conn.commit()
        conn.close()
            
    async def check_scheduled_tasks(self) -> None:
        """Check for tasks that need to be executed now."""
        # Don't run if application isn't set up yet
        if not self.application:
            return
            
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        now_utc = datetime.utcnow()  # Get current UTC time for comparison
        
        # Check for scheduled tasks that are due
        cursor.execute('''
            SELECT id, title, assignee_username, assignee_user_id, chat_id, 
                   scheduled_time, frequency
            FROM tasks 
            WHERE is_active = 1 AND next_run <= ?
        ''', (now_utc,))
        
        due_tasks = cursor.fetchall()
        
        # Process due tasks
        for task in due_tasks:
            task_id, title, username, user_id, chat_id, time, frequency = task
            await self._send_task_reminder(task_id, title, username, user_id, chat_id, frequency)
            
        # Check for pending 5-minute reminders
        cursor.execute('''
            SELECT id, task_id, user_id, username, chat_id, task_title, 
                   frequency, reminder_count, max_reminders
            FROM pending_reminders 
            WHERE next_reminder <= ?
        ''', (now_utc,))
        
        due_reminders = cursor.fetchall()
        
        # Process due reminders
        for reminder in due_reminders:
            (reminder_id, task_id, user_id, username, chat_id, 
             task_title, frequency, reminder_count, max_reminders) = reminder
             
            if reminder_count >= max_reminders:
                # Max reminders reached, stop reminding
                cursor.execute('DELETE FROM pending_reminders WHERE id = ?', (reminder_id,))
                try:
                    await self.application.bot.send_message(
                        chat_id=chat_id,
                        text=f"⏰ Final Notice\n\n@{username}, I've reminded you {max_reminders} times about:\n{task_title}\n\nI'll stop reminding you now. Please complete when possible! 😊"
                    )
                except Exception as e:
                    logger.error(f"Failed to send final reminder: {e}")
            else:
                # Send reminder and schedule next one
                await self._send_followup_reminder(reminder_id, task_id, username, user_id, 
                                                 chat_id, task_title, frequency, reminder_count)
        
        conn.commit()
        conn.close()
        
    async def _send_task_reminder(self, task_id: int, title: str, username: str, 
                                user_id: int, chat_id: int, frequency: str) -> None:
        """Send initial task reminder."""
        try:
            message = f"⏰ Task Reminder\n\n@{username}, it's time for your task:\n\n{title}\n\nHave you completed it? Please reply with 'yes' or 'no'."
            
            await self.application.bot.send_message(
                chat_id=chat_id,
                text=message
            )
            
            # Add to pending responses
            pending_key = f"{user_id}_{chat_id}" if user_id else f"unknown_{chat_id}"
            self.pending_responses[pending_key] = {
                'task_id': task_id,
                'title': title,
                'assignee_username': username,
                'assignee_user_id': user_id,
                'chat_id': chat_id,
                'frequency': frequency
            }
            
            # Set up automatic 5-minute reminder if no response
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            next_reminder_utc = datetime.utcnow() + timedelta(minutes=5)
            
            cursor.execute('''
                INSERT OR REPLACE INTO pending_reminders 
                (task_id, user_id, username, chat_id, task_title, frequency, next_reminder, reminder_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, 0)
            ''', (task_id, user_id, username, chat_id, title, frequency, next_reminder_utc))
            
            conn.commit()
            conn.close()
            
        except Exception as e:
            logger.error(f"Failed to send task reminder: {e}")
            
    async def _send_followup_reminder(self, reminder_id: int, task_id: int, username: str, 
                                    user_id: int, chat_id: int, task_title: str, 
                                    frequency: str, reminder_count: int) -> None:
        """Send follow-up reminder and schedule next one."""
        try:
            # Choose message based on reminder count
            if reminder_count == 0:
                message = f"🔔 Reminder\n\n@{username}, you haven't responded yet about:\n{task_title}\n\nPlease reply 'yes' or 'no'"
            elif reminder_count < 3:
                message = f"🔔 Follow-up #{reminder_count + 1}\n\n@{username}, still waiting for your response about:\n{task_title}\n\nPlease reply 'yes' or 'no'"
            elif reminder_count < 6:
                message = f"⚠️ Persistent Reminder\n\n@{username}, this is reminder #{reminder_count + 1} for:\n{task_title}\n\nPlease complete and reply 'yes', or 'no' if you need help!"
            else:
                message = f"🚨 Urgent Reminder #{reminder_count + 1}\n\n@{username}, this task needs attention:\n{task_title}\n\nPlease respond 'yes' or 'no' - I'll keep reminding every 5 minutes!"
            
            await self.application.bot.send_message(
                chat_id=chat_id,
                text=message
            )
            
            # Add back to pending responses
            pending_key = f"{user_id}_{chat_id}"
            self.pending_responses[pending_key] = {
                'task_id': task_id,
                'title': task_title,
                'assignee_username': username,
                'assignee_user_id': user_id,
                'chat_id': chat_id,
                'frequency': frequency
            }
            
            # Schedule next reminder
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            next_reminder_utc = datetime.utcnow() + timedelta(minutes=5)
            new_count = reminder_count + 1
            
            cursor.execute('''
                UPDATE pending_reminders 
                SET next_reminder = ?, reminder_count = ?
                WHERE id = ?
            ''', (next_reminder_utc, new_count, reminder_id))
            
            conn.commit()
            conn.close()
            
        except Exception as e:
            logger.error(f"Failed to send follow-up reminder: {e}")

    async def _clear_user_reminders(self, user_id: int, chat_id: int) -> None:
        """Clear all pending reminders for a user when they respond yes."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            DELETE FROM pending_reminders 
            WHERE user_id = ? AND chat_id = ?
        ''', (user_id, chat_id))
        
        conn.commit()
        conn.close()
            
    def _start_background_checker(self) -> None:
        """Start background thread for checking scheduled tasks."""
        def background_loop():
            """Run the background task checker."""
            while True:
                try:
                    # Create new event loop for this thread
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    
                    # Run the async function
                    loop.run_until_complete(self.check_scheduled_tasks())
                    loop.close()
                    
                except Exception as e:
                    logger.error(f"Error in background task check: {e}")
                
                # Wait 60 seconds before next check
                time.sleep(60)
        
        # Start background thread
        background_thread = Thread(target=background_loop, daemon=True)
        background_thread.start()
        logger.info("Background task checker started")
            
    async def _periodic_task_check(self) -> None:
        """Periodic task checker that runs every minute."""
        while True:
            try:
                await self.check_scheduled_tasks()
            except Exception as e:
                logger.error(f"Error in periodic task check: {e}")
            await asyncio.sleep(60)  # Check every minute for both tasks and reminders
            
    def run(self) -> None:
        """Start the bot."""
        # Create application
        self.application = Application.builder().token(self.token).build()
        
        # Add error handler
        async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
            """Handle errors."""
            error_message = str(context.error)
            
            if "Conflict: terminated by other getUpdates request" in error_message:
                logger.warning("Another bot instance is running. This is normal during deployments.")
                # Don't log this as an error since it's expected during deployments
                return
            
            logger.error(f"Exception while handling an update: {context.error}")
            
        self.application.add_error_handler(error_handler)
        
        # Add handlers
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(CommandHandler("createtask", self.create_task_command))
        self.application.add_handler(CommandHandler("tasks", self.list_tasks_command))
        self.application.add_handler(CommandHandler("removetask", self.remove_task_command))
        
        # Handler for task responses (yes/no messages)
        self.application.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_task_response)
        )
        
        # Start the bot
        logger.info("Starting Task Management Bot...")
        self.application.run_polling(
            allowed_updates=Update.ALL_TYPES,
            stop_signals=None  # Let Railway handle process management
        )


def main():
    """Main function to run the bot."""
    print("🤖 TELEGRAM TASK BOT STARTING...")
    print("=== ENVIRONMENT DEBUG ===")
    
    # Check environment variables
    bot_token_env = os.getenv('BOT_TOKEN')
    admin_ids_env = os.getenv('ADMIN_IDS')
    
    print(f"BOT_TOKEN found in env: {bot_token_env is not None}")
    print(f"ADMIN_IDS found in env: {admin_ids_env is not None}")
    
    if bot_token_env:
        print(f"BOT_TOKEN length: {len(bot_token_env)}")
        print("✅ Using environment variables")
        BOT_TOKEN = bot_token_env
        
        # Parse admin IDs
        try:
            if admin_ids_env:
                ADMIN_IDS = [int(id.strip()) for id in admin_ids_env.split(',') if id.strip().isdigit()]
            else:
                ADMIN_IDS = [123456789]  # Default fallback
        except:
            ADMIN_IDS = [123456789]  # Error fallback
            
    else:
        print("⚠️ Environment variables not found - using hardcoded values")
        # HARDCODED VALUES - REPLACE THESE WITH YOUR ACTUAL VALUES
        BOT_TOKEN = "7812504300:AAEuRtWbG2IUcfKAPYdg1ZBThd5mKlWJPWI"
        ADMIN_IDS = [1948521794,5738520540]  # Replace with your actual Telegram user ID
        
        # Validation check
        if BOT_TOKEN == "PASTE_YOUR_BOT_TOKEN_HERE":
            print("❌ ERROR: Please replace PASTE_YOUR_BOT_TOKEN_HERE with your actual bot token!")
            print("Get your bot token from @BotFather on Telegram")
            print("Your token should look like: 123456789:ABCdefGHIjklMNOpqrsTUVwxyz")
            return
            
        if 123456789 in ADMIN_IDS:
            print("⚠️ WARNING: Please replace 123456789 with your actual Telegram user ID")
            print("Get your user ID from @userinfobot on Telegram")
    
    print("========================")
    print(f"Starting bot with token length: {len(BOT_TOKEN)}")
    print(f"Admin IDs: {ADMIN_IDS}")
    
    # Create and run bot
    try:
        bot = TaskBot(token=BOT_TOKEN, admin_ids=ADMIN_IDS)
        bot.run()
    except Exception as e:
        logger.error(f"Failed to start bot: {e}")
        print(f"❌ Bot failed to start: {e}")
        print("Please check your bot token and network connection")


if __name__ == '__main__':
    main()
