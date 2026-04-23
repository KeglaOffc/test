import os
import re

def fix_file(filename):
    # Определяем полный путь к файлу относительно папки, где лежит этот скрипт
    base_path = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(base_path, filename)
    
    if not os.path.exists(file_path):
        print(f"⚠️ Файл {filename} не найден в {base_path}, пропускаю.")
        return

    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    print(f"⚙️ Обработка {filename}...")

    # 1. Исправляем parse_mode на HTML
    content = content.replace('parse_mode="Markdown"', 'parse_mode="HTML"')
    content = content.replace("parse_mode='Markdown'", 'parse_mode="HTML"')

    # 2. Исправляем незакрытые теги <b> (заменяем второе вхождение на </b>)
    # Ищет <b>текст<b> и делает <b>текст</b>
    content = re.sub(r'<b>([^<]+)<b>', r'<b>\1</b>', content)

    # 3. Переводим Markdown жирный (**) и код (`) в HTML
    # Заменяем жирный текст **текст** на <b>текст</b>
    content = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', content)
    # Заменяем `текст` на <code>текст</code>
    content = re.sub(r'`(.*?)`', r'<code>\1</code>', content)

    # 4. Специфичные фиксы для lottery.py
    if filename == 'lottery.py':
        # Исправляем запрос к несуществующей таблице
        content = content.replace(
            'SELECT user_id FROM user_lottery_tickets WHERE lottery_id = ?',
            'SELECT user_id FROM lottery_tickets WHERE lottery_type = ?'
        )
        # Удаляем дубли логгера
        logger_pattern = r"logging\.basicConfig\(level=logging\.INFO\)\nlogger = logging\.getLogger\(__name__\)"
        loggers = re.findall(logger_pattern, content)
        if len(loggers) > 1:
            content = content.replace(loggers[0], "", 1)
        
        # Чистим мусор в конце файла
        content = re.sub(r'conn\.commit\(\) если я.*', 'conn.commit()', content)

    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print(f"✅ Файл {filename} исправлен!")

if __name__ == "__main__":
    # Исправляем сразу оба файла, где чаще всего ошибки с parse_mode
    fix_file('lottery.py')
    fix_file('admin.py')
    print("\n🚀 Готово! Теперь можешь запускать бота.")