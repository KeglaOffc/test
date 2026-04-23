#!/usr/bin/env python3
"""
Скрипт для жесткой остановки бота.
Использует PID из файла bot.pid для принудительного завершения процесса.
"""

import os
import sys
import signal
import psutil
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

def get_process_info(pid):
    """Получает информацию о процессе по PID"""
    try:
        process = psutil.Process(pid)
        return {
            'name': process.name(),
            'cmdline': ' '.join(process.cmdline()),
            'create_time': process.create_time(),
            'status': process.status()
        }
    except psutil.NoSuchProcess:
        return None
    except Exception as e:
        logger.error(f"Ошибка при получении информации о процессе {pid}: {e}")
        return None

def kill_process_tree(pid, timeout=5):
    """
    Останавливает процесс и все его дочерние процессы.
    Сначала пробует graceful shutdown, затем force kill.
    """
    try:
        parent = psutil.Process(pid)
        children = parent.children(recursive=True)
        
        logger.info(f"Остановка процесса {pid} и {len(children)} дочерних процессов...")
        
        # Пробуем graceful shutdown
        parent.terminate()
        for child in children:
            try:
                child.terminate()
            except psutil.NoSuchProcess:
                pass
        
        # Ждем завершения
        gone, alive = psutil.wait_procs([parent] + children, timeout=timeout)
        
        # Если остались живые процессы, убиваем force
        for p in alive:
            try:
                logger.warning(f"Force kill процесса {p.pid}")
                p.kill()
            except psutil.NoSuchProcess:
                pass
        
        return len(alive) == 0
        
    except psutil.NoSuchProcess:
        logger.warning(f"Процесс {pid} уже не существует")
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
        return 1
    
    # Читаем PID
    try:
        with open(pid_file, 'r') as f:
            pid = int(f.read().strip())
    except Exception as e:
        logger.error(f"[ERROR] Не удалось прочитать PID из файла: {e}")
        return 1
    
    logger.info(f"[INFO] Найден PID бота: {pid}")
    
    # Проверяем, существует ли процесс
    process_info = get_process_info(pid)
    if not process_info:
        logger.warning(f"[WARNING] Процесс {pid} не найден. Возможно, бот уже остановлен.")
        try:
            os.remove(pid_file)
            logger.info(f"[INFO] Удален файл {pid_file}")
        except Exception as e:
            logger.warning(f"[WARNING] Не удалось удалить файл {pid_file}: {e}")
        return 0
    
    # Проверяем, что это действительно наш бот
    if 'python' in process_info['name'].lower() and ('start.py' in process_info['cmdline'] or 'casino' in process_info['cmdline']):
        logger.info(f"[INFO] Подтверждено: процесс {pid} является ботом")
        logger.info(f"[INFO] Команда запуска: {process_info['cmdline']}")
    else:
        logger.warning(f"[WARNING] Процесс {pid} не похож на бота")
        logger.warning(f"[WARNING] Имя процесса: {process_info['name']}")
        logger.warning(f"[WARNING] Команда: {process_info['cmdline']}")
        
        # Спрашиваем подтверждение
        response = input("Продолжить остановку? (y/N): ").strip().lower()
        if response != 'y':
            logger.info("[INFO] Остановка отменена пользователем")
            return 0
    
    # Останавливаем процесс
    logger.info(f"[STOP] Остановка процесса {pid}...")
    
    if kill_process_tree(pid):
        logger.info(f"[SUCCESS] Процесс {pid} успешно остановлен")
        
        # Удаляем файл PID
        try:
            os.remove(pid_file)
            logger.info(f"[CLEANUP] Удален файл {pid_file}")
        except Exception as e:
            logger.warning(f"[WARNING] Не удалось удалить файл {pid_file}: {e}")
        
        return 0
    else:
        logger.error(f"[FAILED] Не удалось остановить процесс {pid}")
        return 1

if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        logger.info("\n[INFO] Остановка скрипта по Ctrl+C")
        sys.exit(1)
    except Exception as e:
        logger.critical(f"[CRITICAL] Непредвиденная ошибка: {e}", exc_info=True)
        sys.exit(1)