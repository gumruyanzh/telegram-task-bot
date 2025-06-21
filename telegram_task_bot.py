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
        """Calculate the next run time for a task."""
        now = datetime.now()
        time_parts = scheduled_time.split(":")
        hour, minute = int(time_parts[0]), int(time_parts[1])
        
        if frequency == "once":
            # Schedule for today if time hasn't passed, otherwise tomorrow
            next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if next_run <= now:
                next_run += timedelta(days=1)
        elif frequency == "daily":
            # Schedule for today if time hasn't passed, otherwise tomorrow
            next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if next_run <= now:
                next_run += timedelta(days=1)
        else:
            # Default to once
            next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if next_run <= now:
                next_run += timedelta(days=1)
                
        return next_run
        
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

**Time format:** Use 24-hour format (e.g., 14:30) or 12-hour with AM/PM (e.g., 2:30PM)
**Frequency options:** once, daily

Need help? Use /help for detailed instructions!
        """
        await update.message.reply_text(welcome_message, parse_mode='Markdown')
        
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /help command."""
        help_text = """
📋 **Task Management Bot Help**

**Creating Tasks:**
`/createtask @john Clean office 09:00 daily`
`/createtask @jane Submit report 17:30 once`

**Managing Tasks:**
• `/tasks` - View all active tasks with their IDs
• `/removetask 5` - Remove task with ID 5

**Task Responses:**
When you're mentioned for a task, simply reply:
• "yes" - Task completed ✅
• "no" - Task not completed ❌

**Time Formats:**
• 24-hour: 09:00, 17:30, 23:45
• 12-hour: 9:00AM, 5:30PM, 11:45PM

**Frequency Options:**
• `once` - One-time task
• `daily` - Repeats every day at the specified time

**Admin Features:**
Only authorized admins can create and remove tasks.

**Automatic Follow-ups:**
If you don't respond or say "no", the bot will ask again after 5 minutes.
        """
        await update.message.reply_text(help_text, parse_mode='Markdown')
        
    async def create_task_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /createtask command."""
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
            f"**Task ID:** {task_id}\n"
            f"**Assignee:** @{username}\n"
            f"**Description:** {description}\n"
            f"**Time:** {parsed_time}\n"
            f"**Frequency:** {frequency}\n"
            f"**Next run:** {next_run.strftime('%Y-%m-%d %H:%M')}",
            parse_mode='Markdown'
        )
        
    async def list_tasks_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /tasks command."""
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
            
        message = "📋 **Active Tasks:**\n\n"
        
        for task in tasks:
            task_id, title, username, time, freq, next_run, active = task
            next_run_dt = datetime.fromisoformat(next_run) if next_run else "Not scheduled"
            
            if isinstance(next_run_dt, datetime):
                next_run_str = next_run_dt.strftime('%Y-%m-%d %H:%M')
            else:
                next_run_str = str(next_run_dt)
                
            message += f"**ID {task_id}:** {title}\n"
            message += f"👤 @{username} | ⏰ {time} | 🔄 {freq}\n"
            message += f"📅 Next: {next_run_str}\n\n"
            
        await update.message.reply_text(message, parse_mode='Markdown')
        
    async def remove_task_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /removetask command."""
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
            f"**Task:** {title}\n"
            f"**Was assigned to:** @{username}",
            parse_mode='Markdown'
        )
        
    async def handle_task_response(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle user responses to task completion queries."""
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
        
        conn.commit()
        conn.close()
        
        # Remove from pending responses
        del self.pending_responses[pending_key]
        
        # Send confirmation
        if message_text == 'yes':
            await update.message.reply_text(
                f"✅ Great! Task completed: {task_info['title']}"
            )
            # Update next run for recurring tasks
            await self._update_next_run(task_id, task_info['frequency'])
        else:
            await update.message.reply_text(
                f"❌ Task not completed: {task_info['title']}\n"
                "I'll ask again in 5 minutes."
            )
            # Schedule follow-up in 5 minutes
            await self._schedule_followup(task_info, 5)
            
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
        
    async def _schedule_followup(self, task_info: Dict, minutes: int) -> None:
        """Schedule a follow-up reminder for incomplete tasks."""
        # In a production environment, you might want to use a proper job queue
        # For this example, we'll use asyncio.sleep
        await asyncio.sleep(minutes * 60)
        
        # Re-ask the task completion question
        chat_id = task_info['chat_id']
        username = task_info['assignee_username']
        title = task_info['title']
        
        try:
            await self.application.bot.send_message(
                chat_id=chat_id,
                text=f"🔔 Follow-up reminder:\n\n@{username}, have you completed the task: **{title}**?\n\nPlease reply with 'yes' or 'no'.",
                parse_mode='Markdown'
            )
            
            # Add back to pending responses
            pending_key = f"{task_info['assignee_user_id']}_{chat_id}"
            self.pending_responses[pending_key] = task_info
            
        except Exception as e:
            logger.error(f"Failed to send follow-up message: {e}")
            
    async def check_scheduled_tasks(self) -> None:
        """Check for tasks that need to be executed now."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        now = datetime.now()
        
        cursor.execute('''
            SELECT id, title, assignee_username, assignee_user_id, chat_id, 
                   scheduled_time, frequency
            FROM tasks 
            WHERE is_active = 1 AND next_run <= ?
        ''', (now,))
        
        due_tasks = cursor.fetchall()
        conn.close()
        
        for task in due_tasks:
            task_id, title, username, user_id, chat_id, time, frequency = task
            
            # Send task reminder
            try:
                message = f"⏰ **Task Reminder**\n\n@{username}, it's time for your task:\n\n**{title}**\n\nHave you completed it? Please reply with 'yes' or 'no'."
                
                await self.application.bot.send_message(
                    chat_id=chat_id,
                    text=message,
                    parse_mode='Markdown'
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
                
                # Schedule follow-up if no response
                asyncio.create_task(self._schedule_followup(self.pending_responses[pending_key], 5))
                
            except Exception as e:
                logger.error(f"Failed to send task reminder: {e}")
                
    def _run_schedule(self) -> None:
        """Run the schedule checker in a separate thread."""
        while True:
            schedule.run_pending()
            time.sleep(60)  # Check every minute
            
    async def _periodic_task_check(self) -> None:
        """Periodic task checker that runs every minute."""
        while True:
            try:
                await self.check_scheduled_tasks()
            except Exception as e:
                logger.error(f"Error in periodic task check: {e}")
            await asyncio.sleep(60)  # Wait 1 minute
            
    def run(self) -> None:
        """Start the bot."""
        # Create application
        self.application = Application.builder().token(self.token).build()
        
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
        
        # Start periodic task checker
        asyncio.create_task(self._periodic_task_check())
        
        # Start the bot
        logger.info("Starting Task Management Bot...")
        self.application.run_polling(allowed_updates=Update.ALL_TYPES)


def main():
    """Main function to run the bot."""
    # Configuration for Railway deployment
    BOT_TOKEN = os.getenv('BOT_TOKEN', 'YOUR_BOT_TOKEN_HERE')
    
    # Admin user IDs from environment variable (comma-separated)
    # You can get your user ID by messaging @userinfobot on Telegram
    ADMIN_IDS_STR = os.getenv('ADMIN_IDS', '123456789,987654321')
    
    try:
        # Parse comma-separated admin IDs
        ADMIN_IDS = [int(id.strip()) for id in ADMIN_IDS_STR.split(',') if id.strip().isdigit()]
        if not ADMIN_IDS:
            ADMIN_IDS = [123456789]  # Fallback
    except (ValueError, AttributeError):
        logger.error("Invalid ADMIN_IDS format. Using default.")
        ADMIN_IDS = [123456789]
    
    # Validate configuration
    if BOT_TOKEN == 'YOUR_BOT_TOKEN_HERE':
        logger.error("Please set your bot token in the BOT_TOKEN environment variable or modify the code.")
        return
        
    if 123456789 in ADMIN_IDS:
        logger.warning("Please replace the example admin IDs with real Telegram user IDs.")
        
    # Create and run bot
    bot = TaskBot(token=BOT_TOKEN, admin_ids=ADMIN_IDS)
    bot.run()


if __name__ == '__main__':
    main()
