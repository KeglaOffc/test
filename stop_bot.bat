@echo off
echo ============================================
echo ОСТАНОВКА КАЗИНО-БОТА
echo ============================================
echo.

python hard_stop_simple.py

if %errorlevel% == 0 (
    echo.
    echo [SUCCESS] Бот успешно остановлен!
) else (
    echo.
    echo [ERROR] Не удалось остановить бота.
    echo Проверьте логи в bot_stop.log
)

echo.
pause