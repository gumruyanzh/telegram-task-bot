# 🤖 Telegram Task Management Bot

A professional Telegram bot for managing tasks in group chats with private reminder notifications and public completion announcements.

## ✨ Key Features

- 📱 **Private Reminders** - Task reminders sent via DM
- 📢 **Group Announcements** - Completions announced publicly  
- ⏰ **PST Timezone** - All times in Pacific Time
- 🔄 **Smart Persistence** - Reminds every 2 minutes until completion
- 👥 **Any User Assignment** - Assign tasks to any group member
- 🛡️ **Data Safety** - Zero data loss on updates

## 🚀 Quick Start

### For Users
1. Add the bot to your Telegram group
2. Use `/help` to see all available commands
3. Start a private chat with the bot to receive DM reminders

### For Admins
```bash
# Create a task
/createtask @username Clean office 09:00 daily

# View all tasks
/tasks

# Remove a task
/removetask 5
```

## 📋 Commands

| Command | Description | Who Can Use |
|---------|-------------|-------------|
| `/help` | Show comprehensive help | Everyone |
| `/time` | Current PST time | Everyone |
| `/tasks` | List all tasks | Everyone |
| `/createtask` | Create new task | Admins only |
| `/removetask` | Remove task | Admins only |

## 🏗️ How It Works

1. **Create Task** → Admin assigns task with time/frequency
2. **Private Reminder** → Bot DMs user when task is due
3. **User Response** → Click YES (done) or NO (not done)
4. **Group Announcement** → Completion announced to group
5. **Follow-ups** → If NO, reminds every 2 minutes (max 30 times)

## 🔧 Setup & Deployment

### Environment Variables
```bash
BOT_TOKEN=your_telegram_bot_token_from_botfather
ADMIN_IDS=123456789,987654321  # Comma-separated admin user IDs
```

### Deploy on Railway
1. Fork this repository
2. Connect to Railway
3. Set environment variables
4. Deploy automatically

### Local Development
```bash
pip install -r requirements.txt
export BOT_TOKEN="your_token"
export ADMIN_IDS="your_user_id"
python task_bot.py
```

## 📊 Database

Uses SQLite3 with automatic schema management:
- **Tasks** - All task information and status
- **Reminders** - Tracking follow-up reminders  
- **Users** - User ID tracking for private messaging

**Data Safety**: All updates preserve existing data with safe migrations.

## 📖 Documentation

- **[Technical Specification](SPECIFICATION.md)** - Complete system documentation
- **[Commands Reference](SPECIFICATION.md#-bot-commands)** - All available commands
- **[Workflow Details](SPECIFICATION.md#-workflow)** - How the system works

## 🛡️ Security & Privacy

- Only admins can create/remove tasks
- Users can only respond to their assigned tasks
- Private reminders protect user privacy
- Secure database with ACID compliance

## 🔄 Version History

- **v2.0.0** - Private messaging, user tracking, PST timezone
- **v1.0.0** - Basic task management and reminders

## 📝 License

MIT License - See [LICENSE](LICENSE) for details.

## 🆘 Support

- Use `/help` in your group for command reference
- Check [SPECIFICATION.md](SPECIFICATION.md) for technical details
- Contact your group administrators for assistance

---

**Made with ❤️ for productive teams**