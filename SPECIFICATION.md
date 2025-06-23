# Telegram Task Management Bot - Technical Specification

## 📋 Overview

A professional Telegram bot for managing tasks in group chats with private reminder notifications and public completion announcements.

## 🎯 Core Features

### Task Management
- **Create Tasks**: Assign tasks to any group member with scheduled reminders
- **Time Zones**: All times in PST/PDT (Pacific Time) for user convenience
- **Frequencies**: Support for one-time (`once`) and recurring (`daily`) tasks
- **Task Tracking**: Complete database of all tasks with status tracking

### Smart Reminder System
- **Private Notifications**: Task reminders sent via direct messages
- **Group Announcements**: Task completions announced in the group
- **Persistent Reminders**: Automatic follow-ups every 2 minutes until completion
- **Smart Limits**: Maximum 30 reminders per task to prevent spam

### User Experience
- **Username-based Assignment**: Assign tasks to any group member (not just admins)
- **Interactive Responses**: YES/NO buttons for easy task completion
- **User Tracking**: Automatic user ID tracking for private messaging
- **Professional UI**: Clean, informative messages with emoji indicators

## 🏗️ System Architecture

### Database Schema

#### Tasks Table
```sql
CREATE TABLE tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    assignee_id INTEGER NOT NULL,
    assignee_username TEXT NOT NULL,
    description TEXT NOT NULL,
    scheduled_time TEXT NOT NULL,
    frequency TEXT NOT NULL,
    is_done INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### Reminders Table
```sql
CREATE TABLE reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL,
    reminder_count INTEGER DEFAULT 0,
    last_reminder TIMESTAMP,
    FOREIGN KEY (task_id) REFERENCES tasks(id)
);
```

#### Users Table
```sql
CREATE TABLE users (
    id INTEGER PRIMARY KEY,
    username TEXT NOT NULL,
    first_name TEXT,
    last_name TEXT,
    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(id, username)
);
```

### Technology Stack
- **Language**: Python 3.11+
- **Framework**: python-telegram-bot v20+
- **Database**: SQLite3 (built-in)
- **Timezone**: pytz for PST/PDT handling
- **Job Scheduling**: APScheduler (via telegram-bot JobQueue)
- **Deployment**: Railway.app

## 🔧 Bot Commands

### Public Commands
| Command | Description | Example |
|---------|-------------|---------|
| `/start` | Welcome message and bot introduction | `/start` |
| `/help` | Comprehensive help documentation | `/help` |
| `/time` | Show current PST time | `/time` |
| `/tasks` | List all active tasks in the group | `/tasks` |

### Admin Commands
| Command | Description | Example |
|---------|-------------|---------|
| `/createtask` | Create new task assignment | `/createtask @john Clean office 09:00 daily` |
| `/removetask` | Remove task by ID | `/removetask 5` |
| `/debug` | System status and diagnostics | `/debug` |
| `/test` | Manually trigger reminder system | `/test` |
| `/testtask` | Create immediate test task | `/testtask @john Test task` |

## 🔄 Workflow

### Task Creation Flow
1. Admin runs `/createtask @username description time frequency`
2. System validates time format and frequency
3. Task stored in database with PST time
4. Confirmation sent to group with private reminder note

### Reminder Flow
1. JobQueue checks for due tasks every 2 minutes
2. For due tasks:
   - Attempt private message to assigned user
   - Fallback to group message if private fails
   - Create reminder record in database
3. User responds with YES/NO buttons
4. System processes response and updates database

### Completion Flow
1. User clicks "YES" button on reminder
2. Task marked as completed in database
3. All reminders for that task deleted
4. Completion announcement sent to group
5. No further reminders sent

### Follow-up Flow
1. User clicks "NO" or doesn't respond
2. Reminder count incremented
3. Next reminder scheduled for 2 minutes later
4. Process repeats until completion or max reminders reached

## 📊 Data Flow

```
Group Chat → Bot Command → Database → JobQueue → Private Message → User Response → Database Update → Group Announcement
```

## 🛡️ Security & Permissions

### Admin Authorization
- Admin user IDs stored in environment variables
- Only admins can create, remove, and debug tasks
- All users can view tasks and respond to their assignments

### User Validation
- Username-based task assignment
- Response validation (only assigned user can respond)
- Automatic user tracking for private messaging

### Data Protection
- SQLite database with ACID compliance
- Graceful error handling for failed operations
- Automatic cleanup of completed task reminders

## 🌐 Deployment

### Environment Variables
```bash
BOT_TOKEN=your_telegram_bot_token
ADMIN_IDS=123456789,987654321
```

### Dependencies
```
python-telegram-bot[job-queue]>=20.0,<21.0
pytz>=2023.3
```

### Platform Requirements
- Python 3.11+
- SQLite3 support
- Persistent file storage for database
- Network access for Telegram API

## 📈 Performance Specifications

### Scalability
- **Concurrent Groups**: Supports multiple group chats
- **Task Volume**: Efficient handling of hundreds of tasks
- **User Tracking**: Automatic user database management
- **Memory Usage**: Lightweight SQLite database

### Reliability
- **Error Handling**: Comprehensive exception management
- **Fallback Systems**: Group messaging when private fails
- **Data Persistence**: All data survives bot restarts
- **Logging**: Detailed logging for debugging and monitoring

## 🔧 Configuration

### Time Settings
- **Timezone**: America/Los_Angeles (PST/PDT)
- **Reminder Interval**: 120 seconds (2 minutes)
- **Max Reminders**: 30 per task
- **Time Tolerance**: ±2 minutes for reminder matching

### Message Settings
- **Private Reminders**: Preferred delivery method
- **Group Fallbacks**: When private messaging fails
- **Completion Announcements**: Always in group chat
- **Button Timeouts**: No expiration on task response buttons

## 🚀 Future Enhancements

### Planned Features
- Task categories and priorities
- Custom reminder intervals
- Task delegation and reassignment
- Advanced scheduling (specific dates, weekly patterns)
- Task completion statistics and reporting
- Integration with external calendar systems

### Scalability Improvements
- PostgreSQL database option for larger deployments
- Redis caching for high-traffic scenarios
- Webhook-based deployment option
- Multi-language support

## 📝 API Documentation

### Internal Methods

#### Task Management
- `_track_user(user)`: Store user information for private messaging
- `_get_user_id_by_username(username)`: Retrieve user ID from database
- `_send_task_reminder(context, chat_id, assignee_id, username, description, task_id)`: Send reminder with fallback logic

#### Time Handling
- `get_pst_now()`: Get current PST/PDT time
- `get_utc_now()`: Get current UTC time
- `pst_to_utc(pst_time)`: Convert PST to UTC for storage
- `utc_to_pst(utc_time)`: Convert UTC to PST for display

#### Database Operations
- `init_db()`: Initialize database schema with migration support
- Safe schema modifications that preserve existing data
- Automatic table creation with IF NOT EXISTS clauses

## 🔍 Monitoring & Debugging

### Logging Levels
- **INFO**: Normal operations, task creation/completion
- **WARNING**: Failed private messages, fallback to group
- **ERROR**: Database errors, API failures
- **DEBUG**: User tracking, detailed flow information

### Health Checks
- Database connectivity validation
- Telegram API response monitoring
- JobQueue execution tracking
- User interaction success rates

## 📋 Maintenance

### Regular Tasks
- Database cleanup of old completed tasks
- User table maintenance for inactive users
- Log rotation and cleanup
- Performance monitoring

### Backup Strategy
- SQLite database file backup
- Environment configuration backup
- Deployment configuration versioning

---

**Version**: 2.0.0  
**Last Updated**: 2025-06-23  
**Author**: AI Assistant  
**License**: MIT 