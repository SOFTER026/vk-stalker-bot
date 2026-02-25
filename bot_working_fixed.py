import asyncio
import json
import threading
import time
import re
import requests
import os
import glob
import shutil
from vk_api import VkApi
from telegram import Bot
from telegram.ext import Application, CommandHandler, MessageHandler, filters

# === Настройки ===
# Используем переменные окружения или значения по умолчанию
VK_TOKEN = os.getenv("VK_TOKEN", "vk1.a.rT7BeOZf16PoBnTqPXfCykzORxkcoqNN09ouOizsk9kkR1_dEn6F6zrjvwYx5GtLbC4JetQKFhuSkhK6bZDZeQQoScIBci3crLxdXHD6SA7ER49eVWqVYtZgmwL8q3kzMiXDIYgjYE9yAESPV3_Se8RKNbxBMUpdyqUbJD42-oc0hS0ehJACdwZenSH3HfJpvTRzS5Tfpo3CyQ7M2Gp0BQ")
TG_TOKEN = os.getenv("TG_TOKEN", "7714581543:AAH37GYnskh7ypztwSPzlLhVvW6dVqhNyzM")
DATABASE_FILE = "database.json"  # Базовый файл (будет переопределяться)

# === Работа с базой данных ===
def get_database_file(user_id):
    """Получить имя файла базы данных для конкретного пользователя"""
    return f"database_{user_id}.json"

def migrate_old_database():
    """Автоматическая миграция данных из старой базы в новые"""
    old_db_file = "database.json"
    
    if not os.path.exists(old_db_file):
        print("Старая база данных не найдена, миграция не требуется")
        return
    
    try:
        # Загружаем старую базу
        with open(old_db_file, 'r', encoding='utf-8') as f:
            old_db = json.load(f)
        
        if "users" not in old_db:
            print("Старая база пуста, миграция не требуется")
            return
        
        # Мигрируем каждого пользователя
        migrated_count = 0
        for user_id, user_data in old_db["users"].items():
            new_db_file = get_database_file(user_id)
            
            # Проверяем существует ли новая база
            if os.path.exists(new_db_file):
                # Загружаем существующую базу
                try:
                    with open(new_db_file, 'r', encoding='utf-8') as f:
                        existing_db = json.load(f)
                    
                    # Проверяем есть ли уже данные для этого пользователя
                    if user_id in existing_db["users"]:
                        print(f"⚠️ Пользователь {user_id} уже существует в новой базе с именем: {existing_db['users'][user_id]['name']}")
                        print(f"📝 Старые данные: {user_data['name']}")
                        print("🔄 Пропускаю миграцию для сохранения существующих данных")
                        continue
                    else:
                        print(f"📝 База для пользователя {user_id} существует, но пользователь отсутствует. Добавляю...")
                        
                except Exception as e:
                    print(f"Ошибка чтения существующей базы {new_db_file}: {e}")
                    print("🔄 Создаю новую базу...")
            
            # Создаем/обновляем базу для пользователя
            new_db = {"users": {user_id: user_data}}
            
            # Сохраняем новую базу
            if save_database(new_db, user_id):
                print(f"✅ Мигрированы данные пользователя {user_id} ({user_data['name']})")
                migrated_count += 1
            else:
                print(f"❌ Ошибка миграции пользователя {user_id}")
        
        if migrated_count > 0:
            print(f"✅ Миграция завершена. Перенесено {migrated_count} пользователей")
            
            # Создаем резервную копию старой базы
            try:
                import shutil
                shutil.move(old_db_file, f"{old_db_file}.migrated")
                print(f"Старая база переименована в {old_db_file}.migrated")
            except:
                pass
        else:
            print("Миграция не требуется - все пользователи уже имеют новые базы")
            
    except Exception as e:
        print(f"Ошибка миграции: {e}")

def load_database(user_id):
    """Загрузка базы данных с защитой от ошибок"""
    if user_id is None:
        raise ValueError("user_id обязателен для load_database")
    
    db_file = get_database_file(user_id)
    
    try:
        # Проверяем существование файла
        if not os.path.exists(db_file):
            print(f"Создаю новую базу данных для пользователя {user_id}")
            return {"users": {}}
        
        # Создаем резервную копию
        try:
            import shutil
            shutil.copy2(db_file, f"{db_file}.backup")
        except:
            pass
        
        # Загружаем базу данных
        with open(db_file, 'r', encoding='utf-8') as f:
            db = json.load(f)
        
        # Проверяем структуру
        if "users" not in db:
            db = {"users": {}}
        
        # Обновляем существующих пользователей, добавляя недостающие поля
        for uid, user_data in db["users"].items():
            # Проверяем обязательные поля
            if not isinstance(user_data, dict):
                print(f"Восстанавливаю поврежденные данные для пользователя {uid}")
                user_data = {
                    "name": f"User {uid}",
                    "vk_user_id": uid,
                    "last_post_id": None,
                    "last_online_status": False,
                    "monitoring": True,
                    "notifications": True,
                    "total_online_time": 0,
                    "last_online_time": None,
                    "last_offline_time": None
                }
                db["users"][uid] = user_data
                continue
            
            # Добавляем недостающие поля для основного пользователя
            required_fields = {
                "notifications": True,
                "total_online_time": 0,
                "last_online_time": None,
                "last_offline_time": None,
                "monitoring": True
            }
            
            for field, default_value in required_fields.items():
                if field not in user_data:
                    user_data[field] = default_value
                    print(f"Добавлено поле {field} для пользователя {uid}")
            
            # Добавляем поля для дополнительных пользователей
            if "additional_users" in user_data:
                for i, add_user in enumerate(user_data["additional_users"]):
                    if not isinstance(add_user, dict):
                        print(f"Удаляю поврежденного дополнительного пользователя {i}")
                        user_data["additional_users"].pop(i)
                        continue
                    
                    for field, default_value in required_fields.items():
                        if field not in add_user:
                            add_user[field] = default_value
                            print(f"Добавлено поле {field} для доп. пользователя {i}")
        
        return db
        
    except json.JSONDecodeError as e:
        print(f"Ошибка JSON в базе данных пользователя {user_id}: {e}")
        # Восстанавливаем из резервной копии
        try:
            with open(f"{db_file}.backup", 'r', encoding='utf-8') as f:
                db = json.load(f)
            save_database(db, user_id)
            print(f"База данных восстановлена из резервной копии для пользователя {user_id}")
            return db
        except:
            print(f"Создаю новую базу данных для пользователя {user_id} из-за ошибки")
            return {"users": {}}
    except Exception as e:
        print(f"Критическая ошибка загрузки базы данных пользователя {user_id}: {e}")
        return {"users": {}}

def save_database(data, user_id):
    """Сохранение базы данных с защитой от ошибок"""
    if user_id is None:
        raise ValueError("user_id обязателен для save_database")
    
    db_file = get_database_file(user_id)
    
    try:
        # Валидация данных перед сохранением
        if not isinstance(data, dict) or "users" not in data:
            print("Ошибка: неверная структура данных")
            return False
        
        # Проверяем каждого пользователя
        for uid, user_data in data["users"].items():
            if not isinstance(user_data, dict):
                print(f"Ошибка: неверные данные пользователя {uid}")
                return False
            
            # Проверяем обязательные поля
            required_fields = ["name", "vk_user_id", "last_online_status", "monitoring"]
            for field in required_fields:
                if field not in user_data:
                    print(f"Ошибка: отсутствует поле {field} у пользователя {uid}")
                    return False
        
        # Создаем временную копию для атомарного сохранения
        temp_file = f"{db_file}.tmp"
        with open(temp_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        # Атомарно заменяем основной файл
        if os.path.exists(db_file):
            shutil.copy2(db_file, f"{db_file}.old")
        shutil.move(temp_file, db_file)
        
        # Удаляем старую копию если все успешно
        if os.path.exists(f"{db_file}.old"):
            os.remove(f"{db_file}.old")
        
        return True
        
    except Exception as e:
        print(f"Ошибка сохранения базы данных пользователя {user_id}: {e}")
        # Восстанавливаем из старой копии если есть
        try:
            if os.path.exists(f"{db_file}.old"):
                shutil.move(f"{db_file}.old", db_file)
                print(f"База данных восстановлена из предыдущей версии для пользователя {user_id}")
        except:
            pass
        return False

def save_database_old(data):
    """Старая функция сохранения для обратной совместимости"""
    try:
        with open(DATABASE_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except:
        return False

# === Состояния регистрации ===
registration_states = {}

# === Команды бота ===
async def start_command(update, context):
    user_id = str(update.effective_user.id)
    print(f"Получена команда /start от пользователя {user_id}")
    
    db = load_database(user_id)
    
    if user_id in db["users"]:
        user_data = db["users"][user_id]
        total_users = 1
        if "additional_users" in user_data:
            total_users += len(user_data["additional_users"])
        
        welcome_text = f"""🤖 Добро пожаловать обратно!

Отслеживаю пользователей: {total_users}

👤 Основной пользователь: {user_data['name']}
"""
        
        if "additional_users" in user_data:
            for i, add_user in enumerate(user_data["additional_users"], 1):
                welcome_text += f"👥 Дополнительный {i}: {add_user['name']}\n"
        
        welcome_text += "\nИспользуйте команды для управления:"
        welcome_text += "\n• /add - добавить пользователя"
        welcome_text += "\n• /status - показать статус"
        welcome_text += "\n• /help - помощь"
        
        await update.message.reply_text(welcome_text)
        return
    else:
        # Красивое приветствие с инструкцией для незарегистрированных
        welcome_text = """🤖 Добро пожаловать в VK Monitor Bot!

Этот бот поможет вам отслеживать онлайн статус пользователей ВКонтакте.

📋 Как добавить пользователя для отслеживания:

📱 Введите ID вручную:
- Перейдите по ссылке на сайт для определения ID пользователя https://regvk.com/id/ 
- Введите адрес страницы пользователя и нажмите `Определить ID` 
- Скопируйте только цифры ID пользователя и вставьте сюда.

🔍 Примеры ID:
- `123456789`
- `535450971`"""
        
    await update.message.reply_text(welcome_text)
    registration_states[user_id] = {"step": "waiting_vk_id", "command": "start"}

async def add_command(update, context):
    user_id = str(update.effective_user.id)
    print(f"Получена команда /add от пользователя {user_id}")
    
    db = load_database(user_id)
    
    if user_id not in db["users"]:
        await update.message.reply_text("Вы еще не зарегистрированы. Используйте /start для первого пользователя")
        return
    
    add_text = """➕ Добавление нового пользователя

📱 Введите ID вручную:
- Перейдите по ссылке на сайт для определения ID пользователя https://regvk.com/id/ 
- Введите адрес страницы пользователя и нажмите `Определить ID` 
- Скопируйте только цифры ID пользователя и вставьте сюда.

⏳ Ожидаю ваш ID..."""
    
    await update.message.reply_text(add_text)
    registration_states[user_id] = {"step": "waiting_vk_id", "command": "add"}

async def handle_message(update, context):
    user_id = str(update.effective_user.id)
    message_text = update.message.text.lower().strip()
    
    if user_id not in registration_states:
        await update.message.reply_text("Сначала используйте команду /start, /add или /remove")
        return
    
    state = registration_states[user_id]
    
    # Обработка подтверждения удаления единственного пользователя
    if state["step"] == "confirm_remove_single":
        if message_text == "yes":
            # Удаляем пользователя
            db = load_database(user_id)
            user_to_remove = state["user_to_remove"]
            
            if user_to_remove["type"] == "main":
                del db["users"][user_id]
            else:
                # Удаляем дополнительного пользователя
                if "additional_users" in db["users"][user_id]:
                    db["users"][user_id]["additional_users"] = [
                        user for user in db["users"][user_id]["additional_users"] 
                        if user["vk_user_id"] != user_to_remove["vk_user_id"]
                    ]
            
            save_database(db, user_id)
            del registration_states[user_id]
            
            success_text = f"""✅ Пользователь удален из отслеживания!

❌ Удален: {user_to_remove['name']} (ID: {user_to_remove['vk_user_id']})

🔄 Для добавления нового пользователя используйте /start"""
            
            await update.message.reply_text(success_text)
        elif message_text == "no":
            del registration_states[user_id]
            await update.message.reply_text("✅ Операция удаления отменена")
        else:
            await update.message.reply_text("❌ Неверный ввод. Отправьте `yes` или `no`")
        return
    
    # Обработка выбора пользователя для удаления
    if state["step"] == "waiting_remove_choice":
        users_list = state["users_list"]
        
        # Проверяем, является ли ввод числом
        if message_text.isdigit():
            choice = int(message_text)
            if 1 <= choice <= len(users_list):
                user_to_remove = users_list[choice - 1]
                db = load_database(user_id)
                
                if user_to_remove["type"] == "main":
                    # Удаляем основного пользователя
                    if "additional_users" in db["users"][user_id] and len(db["users"][user_id]["additional_users"]) > 0:
                        # Делаем первого дополнительного основным
                        new_main = db["users"][user_id]["additional_users"].pop(0)
                        
                        old_main_name = db["users"][user_id]["name"]
                        old_main_id = db["users"][user_id]["vk_user_id"]
                        
                        db["users"][user_id]["name"] = new_main["name"]
                        db["users"][user_id]["vk_user_id"] = new_main["vk_user_id"]
                        db["users"][user_id]["last_online_status"] = new_main.get("last_online_status", False)
                        db["users"][user_id]["last_online_time"] = new_main.get("last_online_time")
                        db["users"][user_id]["last_offline_time"] = new_main.get("last_offline_time")
                        db["users"][user_id]["total_online_time"] = new_main.get("total_online_time", 0)
                        db["users"][user_id]["monitoring"] = new_main.get("monitoring", True)
                        
                        save_database(db, user_id)
                        del registration_states[user_id]
                        
                        success_text = f"""✅ Основной пользователь изменен!

❌ Удален: {old_main_name} (ID: {old_main_id})
👤 Новый основной: {new_main['name']} (ID: {new_main['vk_user_id']})

📊 Всего отслеживаю: {len(db['users'][user_id]['additional_users']) + 1} пользователей"""
                        
                        await update.message.reply_text(success_text)
                    else:
                        # Удаляем единственного пользователя
                        del db["users"][user_id]
                        save_database(db, user_id)
                        del registration_states[user_id]
                        
                        success_text = f"""✅ Пользователь удален из отслеживания!

❌ Удален: {user_to_remove['name']} (ID: {user_to_remove['vk_user_id']})

🔄 Для добавления нового пользователя используйте /start"""
                        
                        await update.message.reply_text(success_text)
                else:
                    # Удаляем дополнительного пользователя
                    if "additional_users" in db["users"][user_id]:
                        db["users"][user_id]["additional_users"] = [
                            user for user in db["users"][user_id]["additional_users"] 
                            if user["vk_user_id"] != user_to_remove["vk_user_id"]
                        ]
                        save_database(db, user_id)
                        del registration_states[user_id]
                        
                        total_users = len(db["users"][user_id]["additional_users"]) + 1
                        
                        success_text = f"""✅ Пользователь удален из отслеживания!

❌ Удален: {user_to_remove['name']} (ID: {user_to_remove['vk_user_id']})

📊 Всего отслеживаю: {total_users} пользователей"""
                        
                        await update.message.reply_text(success_text)
            else:
                await update.message.reply_text(f"❌ Неверный номер. Выберите число от 1 до {len(users_list)}")
        else:
            await update.message.reply_text("❌ Введите номер пользователя для удаления или /cancel для отмены")
        return
    
    if state["step"] == "waiting_vk_id":
        await update.message.reply_text("🔍 Проверяю ID...")
        
        # Проверяем, является ли введенный текст ID
        if message_text.isdigit():
            vk_user_id = message_text
            await update.message.reply_text(f"✅ Получен ID: {vk_user_id}")
        else:
            await update.message.reply_text("❌ Ошибка: введите только цифры ID")
            await update.message.reply_text("🔍 Пример: 123456789")
            return
        
        await update.message.reply_text("🔍 Проверяю профиль...")
        
        # Проверяем доступность профиля и получаем реальные данные
        try:
            user_info = vk.users.get(user_ids=vk_user_id, fields="online,first_name,last_name")[0]
            real_name = f"{user_info.get('first_name', '')} {user_info.get('last_name', '')}".strip()
            
            # Если реальное имя пустое, используем ID как имя
            if not real_name:
                real_name = f"User {vk_user_id}"
            
            await update.message.reply_text(f"✅ Профиль найден: {real_name}")
            
        except Exception as e:
            error_text = f"""❌ Ошибка: не удалось найти пользователя с ID {vk_user_id}

🔍 Возможные причины:
• Неверный ID пользователя
• Пользователь удален или заблокирован
• Временные проблемы с сервисом

💡 Попробуйте:
1. Проверить правильность ID
2. Отправить другой ID
3. Попробовать позже

🔄 Ожидаю вашу следующую попытку..."""
            await update.message.reply_text(error_text)
            return
        
        db = load_database(user_id)
        
        if state["command"] == "start":
            # Первая регистрация - создаем структуру для одного пользователя
            db["users"][user_id] = {
                "name": real_name,
                "vk_user_id": vk_user_id,
                "last_post_id": None,
                "last_online_status": False,
                "monitoring": True,
                "notifications": True,
                "total_online_time": 0,  # ← Добавляем общее время онлайна
                "last_online_time": None,  # ← Добавляем время последнего входа
                "last_offline_time": None  # ← Добавляем время последнего выхода
            }
            
            success_text = f"""✅ Отлично! Начинаю отслеживание {real_name}

👤 Пользователь: {real_name}
🆔 ID: {vk_user_id}

📋 Что будет отслеживаться:
• ✅ Онлайн статус (появление/выход из сети)

Используйте команды для управления:
• /add - добавить ещё одного пользователя
• /remove - перестать отслеживать пользователя
• /status_main - показать статус
• /help - помощь"""
            
            await update.message.reply_text(success_text)
            # Удаляем состояние регистрации после успешного добавления
            del registration_states[user_id]
            
        elif state["command"] == "add":
            # Добавление дополнительного пользователя
            if "additional_users" not in db["users"][user_id]:
                db["users"][user_id]["additional_users"] = []
            
            # Проверяем на дубликаты
            existing_user = None
            for user in db["users"][user_id]["additional_users"]:
                if user["vk_user_id"] == vk_user_id:
                    existing_user = user
                    break
            
            if existing_user:
                error_text = f"""⚠️ Вы уже отслеживаете этого пользователя!

👤 Пользователь: {existing_user['name']}
🆔 ID: {existing_user['vk_user_id']}

💡 Для добавления нового пользователя:
1. Отправьте другой ID
2. Используйте /add для повторной попытки

🔄 Ожидаю вашу следующую попытку..."""
                await update.message.reply_text(error_text)
                # НЕ удаляем состояние регистрации
                return
            
            # Добавляем нового пользователя с реальным именем
            new_user = {
                "name": real_name,
                "vk_user_id": vk_user_id,
                "last_post_id": None,
                "last_online_status": False,
                "monitoring": True,
                "notifications": True,
                "total_online_time": 0,  # ← Добавляем общее время онлайна
                "last_online_time": None,  # ← Добавляем время последнего входа
                "last_offline_time": None  # ← Добавляем время последнего выхода
            }
            
            db["users"][user_id]["additional_users"].append(new_user)
            save_database(db, user_id)
            
            del registration_states[user_id]
            
            total_users = len(db["users"][user_id]["additional_users"]) + 1
            
            success_text = f"""✅ Добавлен новый пользователь!

👤 Пользователь: {real_name}
🆔 ID: {vk_user_id}

📊 Всего отслеживаю: {total_users} пользователей

📋 Что будет отслеживаться у {real_name}:
• ✅ Онлайн статус

Используйте команды для управления:
• /add - добавить ещё одного пользователя
• /remove - перестать отслеживать пользователя
• /status_main - показать статус
• /help - помощь"""
            
            await update.message.reply_text(success_text)
        
        save_database(db, user_id)

async def status_command(update, context):
    """Команда перенаправления на status_main"""
    await status_main_command(update, context)

async def status_main_command(update, context):
    """Показать статистику основного пользователя"""
    user_id = str(update.effective_user.id)
    db = load_database(user_id)
    
    if user_id not in db["users"]:
        error_msg = "Вы не зарегистрированы. Используйте /start"
        await update.message.reply_text(error_msg)
        return
    
    user_data = db["users"][user_id]
    
    # Получаем время онлайна из базы данных
    user_stats = get_user_stats(user_data)
    
    # Формируем статистику
    stats_text = f"""📊 Статистика основного пользователя: {user_data['name']}

{user_stats}

💬 Дополнительные команды:
• /status_all - статистика всех пользователей
• /add - добавить нового пользователя
• /help - помощь"""
    
    await update.message.reply_text(stats_text)

async def status_all_command(update, context):
    """Показать статистику всех пользователей"""
    user_id = str(update.effective_user.id)
    db = load_database(user_id)
    
    if user_id not in db["users"]:
        error_msg = "Вы не зарегистрированы. Используйте /start"
        await update.message.reply_text(error_msg)
        return
    
    user_data = db["users"][user_id]
    
    all_stats_text = "📊 Статистика всех пользователей:\n\n"
    
    # Основной пользователь
    main_user = user_data
    main_stats = get_user_stats(main_user)
    all_stats_text += f"👤 Основной пользователь:\n{main_stats}\n\n"
    
    # Дополнительные пользователи
    if "additional_users" in user_data:
        for i, add_user in enumerate(user_data["additional_users"], 1):
            add_stats = get_user_stats(add_user)
            all_stats_text += f"👥 Дополнительный {i}:\n{add_stats}\n\n"
    
    all_stats_text += """💬 Дополнительные команды:
• /status_main - статистика основного пользователя
• /status_all - статистика всех пользователей
• /add - добавить нового пользователя
• /help - помощь"""
    
    await update.message.reply_text(all_stats_text)

def get_user_stats(user_data):
    """Получить статистику одного пользователя"""
    last_online_time = user_data.get('last_online_time')
    last_offline_time = user_data.get('last_offline_time')
    total_online_time = user_data.get('total_online_time', 0)
    
    stats_text = f"🆔 ID: {user_data['vk_user_id']}"
    
    if last_online_time:
        stats_text += f"\n🟢 Последний вход: {last_online_time}"
    else:
        stats_text += f"\n🟢 Последний вход: Нет данных"
    
    if last_offline_time:
        stats_text += f"\n🔴 Последний выход: {last_offline_time}"
    else:
        stats_text += f"\n🔴 Последний выход: Нет данных"
    
    # Показываем время онлайна всегда, даже если 0
    hours = total_online_time // 3600
    minutes = (total_online_time % 3600) // 60
    stats_text += f"\n⏰ Всего онлайн сегодня: {hours}ч {minutes}мин"
    
    return stats_text

async def help_command(update, context):
    help_text = """🤖 VK Monitor Bot - Справка

📋 Что умеет бот:
- ✅ Отслеживать онлайн статус пользователей ВК
- ✅ Уведомлять о появлении/выходе из сети
- ✅ Работать с несколькими пользователями одновременно
- ✅ Сохранять время онлайна и показывать статистику
- ✅ Прекращать отслеживание пользователей

⚡ Команды бота:

🚀 /start - Начать отслеживание первого пользователя
   • Показывает подробную инструкцию по получению ID
   • Автоматически получает имя из VK
   • Начинает мониторинг онлайн статуса

➕ /add - Добавить еще одного пользователя
   • Для уже зарегистрированных пользователей
   • Позволяет отслеживать неограниченное количество людей
   • Проверяет на дубликаты

➖ /remove - Перестать отслеживать пользователя
   • Показывает список всех отслеживаемых пользователей
   • Позволяет выбрать конкретного пользователя для удаления
   • Удаляет пользователя из базы данных

📊 /status_main - Статистика основного пользователя
   • Показывает детальную статистику основного пользователя
   • Время последнего входа и выхода из сети
   • Общее время онлайна за сегодня

📊 /status_all - Статистика всех пользователей
   • Показывает статистику по всем пользователям
   • Сравнительная информация по времени онлайна
   • Удобное сравнение пользователей

🔔 /on - Включить уведомления
   • Включает уведомления о входе/выходе из сети
   • Получайте мгновенные сообщения о статусе

🔇 /off - Выключить уведомления (тихий режим)
   • Выключает уведомления
   • Продолжает собирать статистику в фоне
   • Никаких сообщений о статусе

❓ /help - Показать это сообщение

🔍 Как получить ID пользователя:

1. Перейдите по ссылке на сайт для определения ID пользователя https://regvk.com/id/ 
2. Введите адрес страницы пользователя и нажмите `Определить ID` 
3. Скопируйте только цифры ID пользователя и вставьте сюда.

💡 Советы:
- ID всегда состоит только из цифр
- Обычно 7-9 цифр
- У каждого пользователя уникальный ID

🎯 Начало работы:
1. Используйте `/start` для первого пользователя
2. Введите ID пользователя ВК
3. Бот автоматически получит имя и начнет отслеживание
4. Добавляйте других пользователей через `/add`
5. Удаляйте пользователей через `/remove`

💬 Нужна помощь?
Используйте команду /help для просмотра этого сообщения"""
    
    await update.message.reply_text(help_text)

async def remove_command(update, context):
    """Команда для прекращения отслеживания пользователя"""
    user_id = str(update.effective_user.id)
    print(f"Получена команда /remove от пользователя {user_id}")
    
    db = load_database(user_id)
    
    if user_id not in db["users"]:
        await update.message.reply_text("Вы еще не зарегистрированы. Используйте /start")
        return
    
    user_data = db["users"][user_id]
    
    # Формируем список всех отслеживаемых пользователей
    users_list = []
    
    # Основной пользователь
    users_list.append({"name": user_data['name'], "vk_user_id": user_data['vk_user_id'], "type": "main"})
    
    # Дополнительные пользователи
    if "additional_users" in user_data:
        for add_user in user_data["additional_users"]:
            users_list.append({"name": add_user['name'], "vk_user_id": add_user['vk_user_id'], "type": "additional"})
    
    if len(users_list) == 1:
        # Если только один пользователь, предлагаем удалить его с подтверждением
        only_user = users_list[0]
        remove_text = f"""⚠️ У вас всего один отслеживаемый пользователь:

👤 {only_user['name']} (ID: {only_user['vk_user_id']})

Вы уверены, что хотите перестать его отслеживать?

Отправьте:
• `yes` - для подтверждения удаления
• `no` - для отмены

⚠️ Внимание: после удаления все данные о пользователе будут утеряны!"""
        
        await update.message.reply_text(remove_text)
        registration_states[user_id] = {
            "step": "confirm_remove_single", 
            "command": "remove",
            "user_to_remove": only_user
        }
        return
    
    # Если несколько пользователей, показываем список для выбора
    remove_text = "➖ Выберите пользователя для прекращения отслеживания:\n\n"
    
    for i, user in enumerate(users_list, 1):
        user_icon = "👤" if user["type"] == "main" else "👥"
        remove_text += f"{i}. {user_icon} {user['name']} (ID: {user['vk_user_id']})\n"
    
    remove_text += f"""
💡 Отправьте номер пользователя (1-{len(users_list)}) для выбора

Или используйте:
• /remove main - удалить основного пользователя
• /cancel - отменить операцию"""
    
    await update.message.reply_text(remove_text)
    registration_states[user_id] = {
        "step": "waiting_remove_choice", 
        "command": "remove",
        "users_list": users_list
    }

async def remove_main_command(update, context):
    """Удалить основного пользователя"""
    user_id = str(update.effective_user.id)
    db = load_database(user_id)
    
    if user_id not in db["users"]:
        await update.message.reply_text("Вы не зарегистрированы. Используйте /start")
        return
    
    user_data = db["users"][user_id]
    
    # Проверяем, есть ли дополнительные пользователи
    if "additional_users" in user_data and len(user_data["additional_users"]) > 0:
        # Если есть дополнительные пользователи, делаем первого основным
        new_main = user_data["additional_users"].pop(0)
        
        # Сохраняем данные старого основного пользователя
        old_main_name = user_data["name"]
        old_main_id = user_data["vk_user_id"]
        
        # Делаем нового основным
        user_data["name"] = new_main["name"]
        user_data["vk_user_id"] = new_main["vk_user_id"]
        user_data["last_online_status"] = new_main.get("last_online_status", False)
        user_data["last_online_time"] = new_main.get("last_online_time")
        user_data["last_offline_time"] = new_main.get("last_offline_time")
        user_data["total_online_time"] = new_main.get("total_online_time", 0)
        user_data["monitoring"] = new_main.get("monitoring", True)
        
        save_database(db, user_id)
        
        success_text = f"""✅ Основной пользователь изменен!

❌ Удален: {old_main_name} (ID: {old_main_id})
👤 Новый основной: {new_main['name']} (ID: {new_main['vk_user_id']})

📊 Всего отслеживаю: {len(user_data['additional_users']) + 1} пользователей"""
        
        await update.message.reply_text(success_text)
    else:
        # Если это единственный пользователь, удаляем полностью
        del db["users"][user_id]
        save_database(db, user_id)
        
        success_text = f"""✅ Пользователь удален из отслеживания!

❌ Удален: {user_data['name']} (ID: {user_data['vk_user_id']})

🔄 Для добавления нового пользователя используйте /start"""
        
        await update.message.reply_text(success_text)

async def on_command(update, context):
    """Включить уведомления"""
    user_id = str(update.effective_user.id)
    db = load_database(user_id)
    
    if user_id not in db["users"]:
        await update.message.reply_text("Вы не зарегистрированы. Используйте /start")
        return
    
    db["users"][user_id]["notifications"] = True
    save_database(db, user_id)
    
    await update.message.reply_text("🔔 Уведомления включены")

async def off_command(update, context):
    """Выключить уведомления (тихий режим)"""
    user_id = str(update.effective_user.id)
    db = load_database(user_id)
    
    if user_id not in db["users"]:
        await update.message.reply_text("Вы не зарегистрированы. Используйте /start")
        return
    
    db["users"][user_id]["notifications"] = False
    save_database(db, user_id)
    
    await update.message.reply_text("🔇 Уведомления выключены (тихий режим)")

async def cancel_command(update, context):
    """Отменить текущую операцию"""
    user_id = str(update.effective_user.id)
    
    if user_id in registration_states:
        del registration_states[user_id]
        await update.message.reply_text("✅ Операция отменена")
    else:
        await update.message.reply_text("Нет активных операций для отмены")

# === Мониторинг ===
def monitor_vk_sync():
    """Синхронная функция мониторинга с защитой от ошибок"""
    print("Мониторинг запущен...")
    
    while True:
        try:
            # Получаем список всех файлов баз данных
            import glob
            db_files = glob.glob("database_*.json")
            
            for db_file in db_files:
                try:
                    # Извлекаем user_id из имени файла
                    user_id = db_file.replace("database_", "").replace(".json", "")
                    
                    # Загружаем базу данных конкретного пользователя
                    db = load_database(user_id)
                    
                    if user_id not in db["users"]:
                        continue
                    
                    user_data = db["users"][user_id]
                    
                    if not user_data.get("monitoring", True):
                        continue
                    
                    try:
                        # Защищенный запрос к VK API с таймаутом
                        user_info = None
                        max_retries = 3
                        
                        for attempt in range(max_retries):
                            try:
                                user_info = vk.users.get(user_ids=user_data["vk_user_id"], fields="online")[0]
                                break  # Успешный запрос
                            except Exception as api_error:
                                print(f"Попытка {attempt + 1}/{max_retries} VK API для {user_data['name']} (пользователь {user_id}): {api_error}")
                                if attempt < max_retries - 1:
                                    time.sleep(2)  # Пауза между попытками
                                else:
                                    print(f"Не удалось получить данные для {user_data['name']} (пользователь {user_id}) после {max_retries} попыток")
                                    continue
                        
                        if not user_info:
                            continue
                        
                        current_online = bool(user_info.get('online', False))
                        user_name = user_data["name"]
                        
                        if current_online != user_data["last_online_status"]:
                            # Отправляем уведомление ТОЛЬКО если включены
                            if user_data.get("notifications", True):
                                try:
                                    loop = asyncio.new_event_loop()
                                    asyncio.set_event_loop(loop)
                                    if current_online:
                                        loop.run_until_complete(bot.send_message(user_id, f"{user_name} появился в сети! 🟢"))
                                    else:
                                        loop.run_until_complete(bot.send_message(user_id, f"{user_name} вышел из сети 🔴"))
                                    loop.close()
                                except Exception as msg_error:
                                    print(f"Ошибка отправки сообщения пользователю {user_id}: {msg_error}")
                            else:
                                print(f"Тихий режим: {user_name} {'появился в сети' if current_online else 'вышел из сети'} (пользователь {user_id}, уведомление не отправлено)")
                            
                            print(f"{user_name} {'появился в сети' if current_online else 'вышел из сети'} (пользователь {user_id})")
                            
                            # Обновляем статус и время в свежей базе
                            fresh_db = load_database(user_id)
                            current_time = time.strftime("%Y-%m-%d %H:%M:%S")
                            
                            # Обновляем время онлайна
                            if current_online:
                                fresh_db["users"][user_id]["last_online_time"] = current_time
                                # Увеличиваем общее время онлайна
                                total_online_time = fresh_db["users"][user_id].get("total_online_time", 0)
                                fresh_db["users"][user_id]["total_online_time"] = total_online_time + 300  # +5 минут
                            else:
                                fresh_db["users"][user_id]["last_offline_time"] = current_time
                            
                            fresh_db["users"][user_id]["last_online_status"] = current_online
                            
                            # Защищенное сохранение
                            if not save_database(fresh_db, user_id):
                                print(f"Ошибка сохранения данных мониторинга для пользователя {user_id}")
                        
                        # Обновляем время входа для онлайн пользователей без времени
                        fresh_db = load_database(user_id)
                        current_time = time.strftime("%Y-%m-%d %H:%M:%S")
                        fresh_db["users"][user_id]["last_online_time"] = current_time
                        save_database(fresh_db, user_id)
                    
                    except Exception as e:
                        print(f"Ошибка при проверке пользователя {user_data['vk_user_id']} (пользователь {user_id}): {e}")
                        continue
                
                except Exception as e:
                    print(f"Ошибка обработки файла базы {db_file}: {e}")
                    continue
            
        except Exception as e:
            print(f"Общая ошибка мониторинга: {e}")
        
        time.sleep(5)

async def monitor_vk():
    """Асинхронная функция мониторинга"""
    await monitor_vk_sync()

# === Настройка ботов ===
bot = Bot(token=TG_TOKEN)
vk_session = VkApi(token=VK_TOKEN)
vk = vk_session.get_api()

# === Основная функция ===
def main():
    """Основная функция бота"""
    print("Запускаем бота...")
    
    # Автоматическая миграция данных из старой базы
    migrate_old_database()
    
    # Создаем VK сессию
    vk_session = VkApi(token=VK_TOKEN)
    global vk
    vk = vk_session.get_api()
    
    # Создаем Telegram бота
    global bot
    bot = Bot(token=TG_TOKEN)
    
    # Создаем приложение
    app = Application.builder().token(TG_TOKEN).build()
    
    # Добавляем обработчики
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("add", add_command))
    app.add_handler(CommandHandler("remove", remove_command))
    app.add_handler(CommandHandler("remove_main", remove_main_command))
    app.add_handler(CommandHandler("cancel", cancel_command))
    app.add_handler(CommandHandler("on", on_command))
    app.add_handler(CommandHandler("off", off_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("status_main", status_main_command))
    app.add_handler(CommandHandler("status_all", status_all_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Добавляем обработчик ошибок
    async def error_handler(update, context):
        print(f"Ошибка при обработке обновления {update}: {context.error}")
        if update and update.message:
            try:
                await update.message.reply_text("Произошла ошибка. Попробуйте снова.")
            except:
                pass
    
    app.add_error_handler(error_handler)
    
    print("Обработчики добавлены")
    
    # Отправляем уведомление о запуске
    try:
        # Получаем список всех файлов баз данных
        import glob
        db_files = glob.glob("database_*.json")
        
        for db_file in db_files:
            try:
                # Извлекаем user_id из имени файла
                user_id = db_file.replace("database_", "").replace(".json", "")
                asyncio.run(bot.send_message(user_id, "🚀 Бот запущен и готов к работе!"))
                print(f"Отправлено уведомление о запуске пользователю {user_id}")
            except Exception as e:
                print(f"Не удалось отправить уведомление пользователю {user_id}: {e}")
    except Exception as e:
        print(f"Не удалось загрузить базы данных для уведомлений: {e}")
    
    print("Запускаем приложение...")
    
    # Запускаем мониторинг в отдельном потоке
    monitor_thread = threading.Thread(target=monitor_vk_sync, daemon=True)
    monitor_thread.start()
    print("Мониторинг запущен в фоне")
    
    # Запускаем бота
    try:
        app.run_polling(drop_pending_updates=True)
    except Exception as e:
        print(f"Ошибка запуска бота: {e}")
        print("Проблема может быть связана с прокси или SSL. Попробуйте:")
        print("1. Отключить VPN/прокси")
        print("2. Проверить интернет соединение")
        print("3. Перезапустить бота через несколько минут")

# === Запуск ===
if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Бот остановлен")
    except Exception as e:
        print(f"Ошибка: {e}")
