# 🤖 Telegram Task Management Bot

A comprehensive Telegram bot for assigning and tracking tasks in group chats with automatic reminders and follow-ups.

## ✨ Features

- **Task Assignment**: Create tasks and assign them to specific users
- **Scheduling**: Support for one-time and daily recurring tasks
- **Automatic Reminders**: Bot mentions assigned users at scheduled times
- **Follow-up System**: Re-asks if users don't respond or say "no" after 5 minutes
- **Admin Controls**: Only authorized admins can create/manage tasks
- **Persistent Storage**: SQLite database for reliable task storage

## 🚀 Quick Deployment on Railway

[![Deploy on Railway](https://railway.app/button.svg)](https://railway.app/template/your-template-id)

## 📋 Commands

### Admin Commands
- `/createtask @username [description] [time] [frequency]` - Create a new task
- `/tasks` - List all active tasks
- `/removetask [task_id]` - Remove a task
- `/help` - Show help message

### User Commands
- Reply "yes" or "no" when asked about task completion

## 🛠️ Local Development

1. Clone the repository:
```bash
git clone https://github.com/yourusername/telegram-task-bot.git
cd telegram-task-bot
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Set environment variables:
```bash
export BOT_TOKEN="your_bot_token_here"
export ADMIN_IDS="123456789,987654321"
```

4. Run the bot:
```bash
python task_bot.py
```

## 🔧 Configuration

### Environment Variables

- `BOT_TOKEN`: Your Telegram bot token from @BotFather
- `ADMIN_IDS`: Comma-separated list of Telegram user IDs who can manage tasks

### Getting Your User ID

Message [@userinfobot](https://t.me/userinfobot) on Telegram to get your user ID.

## 📖 Usage Examples

Create a daily task:
```
/createtask @john Clean the office 09:00 daily
```

Create a one-time task:
```
/createtask @jane Submit weekly report 17:30 once
```

List all tasks:
```
/tasks
```

Remove a task:
```
/removetask 5
```

## 🔒 Security

- Bot token is kept secure through environment variables
- Only authorized admins can create/manage tasks
- Database is local to the deployment instance

## 📄 License

This project is open source and available under the [MIT License](LICENSE).

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## 📞 Support

If you encounter any issues, please create an issue in this repository or contact the maintainers.