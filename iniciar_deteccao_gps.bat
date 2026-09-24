@echo off
setlocal enabledelayedexpansion
title AeroScan - Deteccao de Focos (GPS do iPhone)
cd /d "%~dp0"
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

set "PY=%~dp0venv\Scripts\python.exe"
set "ARQ_IP=%~dp0.ultimo_ip_gps.txt"

echo ============================================
echo   AeroScan - Deteccao de Focos
echo ============================================
echo.

if not exist "%PY%" (
    echo [ERRO] Nao encontrei o ambiente virtual em venv\
    echo Crie com: python -m venv venv
    echo Depois:   venv\Scripts\pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

rem Sem os pesos do detector de rostos nenhuma foto e salva (LGPD, falha fechada)
if not exist "drone\modelos_dnn\res10_300x300_ssd_iter_140000.caffemodel" (
    echo [AVISO] Os pesos do detector de rostos nao estao instalados.
    echo Sem eles a IA roda, mas NENHUMA foto e salva.
    set /p BAIXAR="Baixar agora (~10 MB, precisa de internet)? [S/N]: "
    if /i "!BAIXAR!"=="S" "%PY%" drone\instalar_modelo_dnn.py
    echo.
)

rem ---- IP do iPhone (muda a cada rede) ----
set "ULTIMO="
if exist "%ARQ_IP%" set /p ULTIMO=<"%ARQ_IP%"

echo No iPhone: abra o GPS2IP Lite, ligue "Enable GPS2IP Lite" e leia o
echo "iPhone Server IP" e a "Port" na tela do app (iPhone e PC na MESMA rede).
echo.
if defined ULTIMO echo Ultimo IP usado: !ULTIMO!
set "IP="
set /p IP="IP do iPhone (Enter = ultimo IP, 0 = rodar sem o GPS do iPhone): "
if not defined IP set "IP=!ULTIMO!"

if "!IP!"=="0" set "IP="
if not defined IP goto :sem_iphone

set "PORTA="
set /p PORTA="Porta (Enter = 11123): "
if not defined PORTA set "PORTA=11123"

echo.
echo Testando conexao com !IP!:!PORTA! ...
"%PY%" -c "import socket,sys; socket.create_connection((sys.argv[1], int(sys.argv[2])), timeout=4)" !IP! !PORTA! >nul 2>&1
if errorlevel 1 (
    echo.
    echo [AVISO] Nao consegui conectar em !IP!:!PORTA!.
    echo Confira: GPS2IP aberto na tela com "Enable GPS2IP Lite" ligado,
    echo iPhone e PC na mesma rede Wi-Fi, e o IP/porta mostrados no app.
    set "CONT="
    set /p CONT="Continuar mesmo assim, sem o GPS do iPhone? [S/N]: "
    if /i not "!CONT!"=="S" (
        echo.
        pause
        exit /b 1
    )
    goto :sem_iphone
)

> "%ARQ_IP%" echo !IP!
echo Conectou! Abrindo a camera com o GPS do iPhone...
echo (a janela da webcam pode demorar alguns segundos para abrir)
echo.
"%PY%" -u drone\detectar_foco.py --gps-rede !IP!:!PORTA! --sem-rede
goto :fim

:sem_iphone
echo.
echo Rodando SEM o GPS do iPhone: a localizacao vira a do Wi-Fi do Windows,
echo que erra ~1-2 km (pode cair no bairro vizinho).
echo.
"%PY%" -u drone\detectar_foco.py

:fim
echo.
echo ============================================
echo Sessao encerrada. Feche esta janela ou pressione uma tecla.
echo ============================================
pause >nul
