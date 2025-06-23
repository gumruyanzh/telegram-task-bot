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

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, ContextTypes, filters, MessageHandler
)

# --- CONFIG ---
DB_PATH = "tasks.db"
REMINDER_INTERVAL = 120  # seconds (2 minutes)
MAX_REMINDERS = 30

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
        await update.message.reply_text(
            "Welcome! Admins can create tasks with /createtask @username description time frequency (e.g. /createtask @john Take out trash 14:00 daily)."
        )

    async def createtask(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.message or not update.effective_user:
            return
        user_id = update.effective_user.id
        if not self._is_admin(user_id):
            await update.message.reply_text("❌ Only admins can create tasks.")
            return
        if len(context.args) < 4:
            await update.message.reply_text("❌ Usage: /createtask @username description time frequency")
            return
        username = context.args[0].lstrip('@')
        time_str = context.args[-2]
        frequency = context.args[-1].lower()
        description = " ".join(context.args[1:-2])
        # Validate time
        try:
            datetime.strptime(time_str, "%H:%M")
        except ValueError:
            await update.message.reply_text("❌ Time must be in HH:MM 24-hour format.")
            return
        if frequency not in ["once", "daily"]:
            await update.message.reply_text("❌ Frequency must be 'once' or 'daily'.")
            return
        # Get user id from username (must be in chat)
        chat = update.effective_chat
        assignee_id = None
        async for member in chat.get_administrators():
            if member.user.username and member.user.username.lower() == username.lower():
                assignee_id = member.user.id
        if not assignee_id:
            await update.message.reply_text(f"❌ User @{username} not found in this chat (must be an admin for demo).")
            return
        # Save task
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''
            INSERT INTO tasks (chat_id, assignee_id, assignee_username, description, scheduled_time, frequency)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (chat.id, assignee_id, username, description, time_str, frequency))
        task_id = c.lastrowid
        conn.commit()
        conn.close()
        await update.message.reply_text(f"✅ Task created for @{username}: {description} at {time_str} ({frequency})\nTask ID: {task_id}")

    async def tasks(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
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
            msg += f"ID {row[0]}: @{row[1]} - {row[2]} at {row[3]} ({row[4]}) {status}\n"
        await update.message.reply_text(msg)

    async def removetask(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.message or not update.effective_user:
            return
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
        await query.answer()
        data = query.data
        if not data.startswith("task_"):
            return
        parts = data.split('_')
        task_id = int(parts[1])
        response = parts[2]
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('SELECT is_done FROM tasks WHERE id = ?', (task_id,))
        row = c.fetchone()
        if not row or row[0]:
            await query.edit_message_text("This task is already completed or does not exist.")
            conn.close()
            return
        if response == "yes":
            c.execute('UPDATE tasks SET is_done = 1 WHERE id = ?', (task_id,))
            c.execute('DELETE FROM reminders WHERE task_id = ?', (task_id,))
            await query.edit_message_text("✅ Task marked as complete! You will not be reminded again.")
        elif response == "no":
            # Increment reminder count and schedule next
            c.execute('SELECT reminder_count FROM reminders WHERE task_id = ?', (task_id,))
            row = c.fetchone()
            if row:
                count = row[0] + 1
                c.execute('UPDATE reminders SET reminder_count = ?, last_reminder = ? WHERE task_id = ?', (count, datetime.utcnow(), task_id))
            else:
                count = 1
                c.execute('INSERT INTO reminders (task_id, reminder_count, last_reminder) VALUES (?, ?, ?)', (task_id, count, datetime.utcnow()))
            await query.edit_message_text("📝 Task not completed. I will remind you again in 2 minutes.")
        conn.commit()
        conn.close()

    async def send_reminders(self, context: ContextTypes.DEFAULT_TYPE):
        now = datetime.utcnow()
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        # Get all tasks that are not done
        c.execute('''SELECT id, chat_id, assignee_id, assignee_username, description, scheduled_time, frequency FROM tasks WHERE is_done = 0''')
        tasks = c.fetchall()
        for task in tasks:
            task_id, chat_id, assignee_id, username, description, sched_time, freq = task
            # Check if it's time to remind
            # Only send if it's the right time (or for daily, if not already reminded today)
            now_time = now.strftime("%H:%M")
            if sched_time == now_time:
                # Check if already reminded in last 2 minutes
                c.execute('SELECT last_reminder, reminder_count FROM reminders WHERE task_id = ?', (task_id,))
                row = c.fetchone()
                if row:
                    last_reminder, reminder_count = row
                    if reminder_count >= MAX_REMINDERS:
                        continue
                    if last_reminder:
                        last_dt = datetime.fromisoformat(last_reminder)
                        if (now - last_dt).total_seconds() < REMINDER_INTERVAL:
                            continue
                # Send reminder
                await self._send_task_reminder(context, chat_id, assignee_id, username, description, task_id)
                # Update reminders table
                if row:
                    c.execute('UPDATE reminders SET last_reminder = ?, reminder_count = ? WHERE task_id = ?', (now, (reminder_count or 0) + 1, task_id))
                else:
                    c.execute('INSERT INTO reminders (task_id, reminder_count, last_reminder) VALUES (?, ?, ?)', (task_id, 1, now))
        # Now, send follow-up reminders for tasks with NO or no response
        c.execute('''SELECT r.task_id, t.chat_id, t.assignee_id, t.assignee_username, t.description, r.reminder_count, r.last_reminder FROM reminders r JOIN tasks t ON r.task_id = t.id WHERE t.is_done = 0 AND r.reminder_count < ?''', (MAX_REMINDERS,))
        for row in c.fetchall():
            task_id, chat_id, assignee_id, username, description, reminder_count, last_reminder = row
            if last_reminder:
                last_dt = datetime.fromisoformat(last_reminder)
                if (now - last_dt).total_seconds() >= REMINDER_INTERVAL:
                    await self._send_task_reminder(context, chat_id, assignee_id, username, description, task_id)
                    c.execute('UPDATE reminders SET last_reminder = ?, reminder_count = ? WHERE task_id = ?', (now, reminder_count + 1, task_id))
        conn.commit()
        conn.close()

    async def _send_task_reminder(self, context, chat_id, assignee_id, username, description, task_id):
        keyboard = [
            [
                InlineKeyboardButton("✅ YES", callback_data=f"task_{task_id}_yes"),
                InlineKeyboardButton("❌ NO", callback_data=f"task_{task_id}_no")
            ]
        ]
        markup = InlineKeyboardMarkup(keyboard)
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"@{username}, it's time for your task: {description}\nHave you completed it?",
                reply_markup=markup
            )
        except Exception as e:
            logger.error(f"Failed to send reminder: {e}")

    def run(self):
        self.application = Application.builder().token(self.token).build()
        self.application.add_handler(CommandHandler("start", self.start))
        self.application.add_handler(CommandHandler("createtask", self.createtask))
        self.application.add_handler(CommandHandler("tasks", self.tasks))
        self.application.add_handler(CommandHandler("removetask", self.removetask))
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
