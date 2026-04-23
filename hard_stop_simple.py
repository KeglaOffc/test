#!/usr/bin/env python3
"""
Скрипт для жесткой остановки бота.
Использует PID из файла bot.pid для принудительного завершения процесса.
Простая версия без зависимостей.
"""

import os
import sys
import signal
import time
import logging

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('bot_stop.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

def check_process_exists(pid):
    """Проверяет существование процесса по PID"""
    try:
        # Для Windows используем tasklist
        if os.name == 'nt':
            result = os.system(f'tasklist /FI "PID eq {pid}" >nul 2>&1')
            return result == 0
        else:
            # Для Unix систем
            os.kill(pid, 0)
            return True
    except (OSError, ProcessLookupError):
        return False

def get_process_info(pid):
    """Получает базовую информацию о процессе"""
    try:
        if os.name == 'nt':
            # Для Windows используем tasklist с выводом информации
            import subprocess
            result = subprocess.run(['tasklist', '/FI', f'PID eq {pid}', '/FO', 'CSV'], 
                                    capture_output=True, text=True)
            if result.returncode == 0 and str(pid) in result.stdout:
                lines = result.stdout.strip().split('\n')
                if len(lines) > 1:
                    parts = lines[1].split('","')
                    if len(parts) > 0:
                        return {
                            'name': parts[0].strip('"'),
                            'exists': True
                        }
        return {'exists': check_process_exists(pid)}
    except Exception as e:
        logger.warning(f"Не удалось получить информацию о процессе {pid}: {e}")
        return {'exists': check_process_exists(pid)}

def kill_process(pid):
    """Останавливает процесс"""
    try:
        if os.name == 'nt':
            # Для Windows используем taskkill
            result = os.system(f'taskkill /F /PID {pid} >nul 2>&1')
            return result == 0
        else:
            # Для Unix систем
            os.kill(pid, signal.SIGTERM)
            time.sleep(2)
            if check_process_exists(pid):
                os.kill(pid, signal.SIGKILL)
            return True
    except Exception as e:
        logger.error(f"Ошибка при остановке процесса {pid}: {e}")
        return False

def main():
    """Основная функция скрипта остановки"""
    logger.info("=" * 60)
    logger.info("[STOP] ЗАПУСК СКРИПТА ОСТАНОВКИ БОТА")
    logger.info("=" * 60)
    
    # Проверяем существование файла PID
    pid_file = 'bot.pid'
    if not os.path.exists(pid_file):
        logger.error(f"[ERROR] Файл {pid_file} не найден. Бот, возможно, не запущен.")
        logger.info("[INFO] Попробуйте запустить бота сначала: python start.py")
        return 1
    
    # Читаем PID
    try:
        with open(pid_file, 'r') as f:
            pid = int(f.read().strip())
    except Exception as e:
        logger.error(f"[ERROR] Не удалось прочитать PID из файла: {e}")
        logger.info("[INFO] Файл может быть поврежден. Удалите его вручную и перезапустите бота.")
        return 1
    
    logger.info(f"[INFO] Найден PID бота: {pid}")
    
    # Проверяем, существует ли процесс
    process_info = get_process_info(pid)
    if not process_info['exists']:
        logger.warning(f"[WARNING] Процесс {pid} не найден. Возможно, бот уже остановлен.")
        logger.info(f"[INFO] Удаляю файл {pid_file}...")
        try:
            os.remove(pid_file)
            logger.info(f"[SUCCESS] Файл {pid_file} удален")
        except Exception as e:
            logger.warning(f"[WARNING] Не удалось удалить файл {pid_file}: {e}")
        return 0
    
    logger.info(f"[INFO] Процесс {pid} найден")
    if 'name' in process_info:
        logger.info(f"[INFO] Имя процесса: {process_info['name']}")
    
    # Останавливаем процесс
    logger.info(f"[STOP] Остановка процесса {pid}...")
    
    if kill_process(pid):
        logger.info(f"[SUCCESS] Процесс {pid} успешно остановлен")
        
        # Удаляем файл PID
        try:
            os.remove(pid_file)
            logger.info(f"[CLEANUP] Удален файл {pid_file}")
        except Exception as e:
            logger.warning(f"[WARNING] Не удалось удалить файл {pid_file}: {e}")
        
        logger.info("[INFO] Бот успешно остановлен!")
        return 0
    else:
        logger.error(f"[FAILED] Не удалось остановить процесс {pid}")
        logger.info("[INFO] Возможно, у вас недостаточно прав. Попробуйте запустить от имени администратора.")
        return 1

if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        logger.info("\n[INFO] Остановка скрипта по Ctrl+C")
        sys.exit(1)
    except Exception as e:
        logger.critical(f"[CRITICAL] Непредвиденная ошибка: {e}")
        logger.info("[INFO] Попробуйте остановить бота вручную через диспетчер задач")
        sys.exit(1)