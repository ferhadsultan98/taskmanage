import asyncio
from telegram import Bot
from firebase_admin import credentials, db, initialize_app
from datetime import datetime
import time
import threading

# Firebase konfiqurasiyası
cred = credentials.Certificate('serviceAccountKey.json')
initialize_app(cred, {
    'databaseURL': 'https://test-463d2-default-rtdb.firebaseio.com'
})

# Telegram konfiqurasiyası
TELEGRAM_TOKEN = '7776707741:AAHbTy4eIGVApTNwvgTXgzDsLfclyzdHnMI'
CHAT_ID = '775053589'
bot = Bot(token=TELEGRAM_TOKEN)

# Son göndərilən bildirişləri izləmək üçün
last_notifications = {}

async def send_telegram_message(message):
    """Telegram'a mesaj göndər"""
    for attempt in range(3):  # 3 dəfə cəhd et
        try:
            await bot.send_message(chat_id=CHAT_ID, text=message)
            return
        except Exception as e:
            print(f"Telegram xətası (cəhd {attempt+1}): {e}")
            await asyncio.sleep(2 ** attempt)  # Eksponensial geri çəkilmə
    print("Telegram mesajı göndərilmədi.")

def get_time_remaining(due_timestamp):
    """Tapşırığa qalan vaxtı hesabla"""
    now = int(time.time() * 1000)
    diff = due_timestamp - now
    if diff <= 0:
        return "Vaxt bitdi"
    hours = diff // (1000 * 60 * 60)
    minutes = (diff % (1000 * 60 * 60)) // (1000 * 60)
    return f"{hours} saat {minutes} dəqiqə"

async def check_tasks():
    """Tapşırıqları yoxla və bildiriş göndər"""
    try:
        tasks_ref = db.reference('tasks')
        tasks = tasks_ref.get() or {}
        
        # Gündəlik xülasə (gecə yarısı)
        current_time = datetime.now()
        if current_time.hour == 0 and current_time.minute == 0:
            active_tasks = [task for task_id, task in tasks.items() if not task.get('completed', False)]
            message = "📋 Gündəlik Tapşırıq Xülasəsi:\n\n"
            if active_tasks:
                for task_id, task in tasks.items():
                    if not task.get('completed', False):
                        message += f"📌 {task['title']}\n⏰ {task['time']} ({task['date']})\n🕒 Qalan vaxt: {get_time_remaining(task['dueDateTime'])}\n\n"
            else:
                message += "Aktiv tapşırıq yoxdur."
            await send_telegram_message(message)
            await asyncio.sleep(60)  # Təkrar xülasənin qarşısını almaq üçün
        
        # Hər 30 dəqiqədə aktiv tapşırıq sayını bildir
        if current_time.minute in [0, 30]:
            active_tasks = [task for task_id, task in tasks.items() if not task.get('completed', False)]
            message = f"📊 Aktiv tapşırıq sayı: {len(active_tasks)}"
            await send_telegram_message(message)
        
        # Saatlıq xatırlatmalar
        for task_id, task in tasks.items():
            if task.get('completed', False) or task['dueDateTime'] <= int(time.time() * 1000):
                continue
            time_until_due = task['dueDateTime'] - int(time.time() * 1000)
            if time_until_due > 0 and time_until_due <= 24 * 60 * 60 * 1000:
                notification_key = f"{task_id}_{time_until_due // (1000 * 60 * 60)}"
                if notification_key not in last_notifications:
                    message = f"⏰ Xatırlatma: '{task['title']}' tapşırığına {get_time_remaining(task['dueDateTime'])} qaldı!\nTəsvir: {task.get('description', 'Təsvir yoxdur')}"
                    await send_telegram_message(message)
                    last_notifications[notification_key] = True
    except Exception as e:
        print(f"Tapşırıq yoxlanışında xəta: {e}")
        await send_telegram_message(f"⚠️ Xəta baş verdi: {e}")

def listen_for_task_changes():
    """Firebase'dəki tapşırıq dəyişikliklərini dinlə"""
    tasks_ref = db.reference('tasks')
    
    def handle_task_event(event):
        try:
            task_id = event.path.split('/')[-1]
            task_data = event.data
            if task_data is None:
                asyncio.run_coroutine_threadsafe(
                    send_telegram_message(f"🗑️ Tapşırıq silindi: {task_id}"), 
                    asyncio.get_event_loop()
                )
                return
            if event.event_type in ['put', 'patch'] and len(event.path.split('/')) == 2:
                task = task_data
                if 'createdAt' in task and task.get('completed', False) is False:
                    message = f"➕ Yeni tapşırıq əlavə edildi:\n📌 {task['title']}\n⏰ {task['time']} ({task['date']})\nTəsvir: {task.get('description', 'Təsvir yoxdur')}\n🕒 Qalan vaxt: {get_time_remaining(task['dueDateTime'])}"
                    asyncio.run_coroutine_threadsafe(
                        send_telegram_message(message), 
                        asyncio.get_event_loop()
                    )
                elif 'completed' in task and task['completed']:
                    message = f"✅ Tapşırıq tamamlandı: {task['title']}"
                    asyncio.run_coroutine_threadsafe(
                        send_telegram_message(message), 
                        asyncio.get_event_loop()
                    )
                elif 'completed' in task and not task['completed']:
                    message = f"🔄 Tapşırıq aktiv edildi: {task['title']}"
                    asyncio.run_coroutine_threadsafe(
                        send_telegram_message(message), 
                        asyncio.get_event_loop()
                    )
        except Exception as e:
            print(f"Dinləyici xətası: {e}")
            asyncio.run_coroutine_threadsafe(
                send_telegram_message(f"⚠️ Dinləyici xətası: {e}"), 
                asyncio.get_event_loop()
            )
    
    tasks_ref.listen(handle_task_event)

async def main():
    """Əsas funksiya: tapşırıq yoxlaması və dinləyici"""
    threading.Thread(target=listen_for_task_changes, daemon=True).start()
    
    while True:
        try:
            await check_tasks()
            await asyncio.sleep(60)
        except Exception as e:
            print(f"Əsas döngü xətası: {e}")
            await send_telegram_message(f"⚠️ Əsas döngü xətası: {e}")
            await asyncio.sleep(60)  # Xətadan sonra yenidən cəhd et

if __name__ == "__main__":
    asyncio.run(main())