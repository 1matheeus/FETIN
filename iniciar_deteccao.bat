@echo off
title AeroScan - Deteccao de Focos
cd /d "%~dp0"
echo Iniciando o AeroScan...
echo (a janela da webcam pode demorar alguns segundos para abrir)
echo.
"%~dp0venv\Scripts\python.exe" drone\detectar_foco.py --sem-gps
echo.
echo ============================================
echo Sessao encerrada. Feche esta janela ou pressione uma tecla.
echo ============================================
pause >nul
