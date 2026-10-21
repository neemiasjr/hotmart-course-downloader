@echo off
rem Inicia o Hotmart Course Downloader (Windows).
rem Prepara o ambiente virtual, instala dependencias quando o requirements.txt
rem muda, confere o FFmpeg e executa o hotmark.py.
setlocal
chcp 65001 >nul
cd /d "%~dp0"

set "PYTHON=.venv\Scripts\python.exe"
set "CARIMBO=.venv\.requirements.sha256"

"%PYTHON%" -c "import sys" >nul 2>&1
if not errorlevel 1 goto :dependencias

set "PY_SISTEMA="
py -3 -c "import sys; sys.exit(sys.version_info < (3, 8))" >nul 2>&1 && set "PY_SISTEMA=py -3"
if not defined PY_SISTEMA (
    python -c "import sys; sys.exit(sys.version_info < (3, 8))" >nul 2>&1 && set "PY_SISTEMA=python"
)
if not defined PY_SISTEMA (
    echo.
    echo ERRO: Python 3.8+ nao encontrado.
    echo Instale em https://www.python.org/downloads/ marcando "Add python.exe to PATH".
    goto :falha
)
echo Criando ambiente virtual em .venv...
%PY_SISTEMA% -m venv .venv || goto :falha
if exist "%CARIMBO%" del "%CARIMBO%"

:dependencias
"%PYTHON%" -c "import hashlib, os, sys; h = hashlib.sha256(open('requirements.txt', 'rb').read()).hexdigest(); c = os.path.join('.venv', '.requirements.sha256'); sys.exit(0 if os.path.isfile(c) and open(c).read().strip() == h else 1)"
if not errorlevel 1 goto :ffmpeg
echo Instalando dependencias (requirements.txt)...
"%PYTHON%" -m pip install --disable-pip-version-check -q -r requirements.txt
if errorlevel 1 (
    echo.
    echo ERRO: Falha ao instalar as dependencias. Verifique a internet e tente de novo.
    goto :falha
)
"%PYTHON%" -c "import hashlib, os; open(os.path.join('.venv', '.requirements.sha256'), 'w').write(hashlib.sha256(open('requirements.txt', 'rb').read()).hexdigest())"

:ffmpeg
where ffmpeg >nul 2>&1 && where ffprobe >nul 2>&1 && goto :config
echo.
echo ERRO: FFmpeg nao encontrado (necessario para baixar os videos).
echo Instale com:  winget install Gyan.FFmpeg
echo Depois feche esta janela e rode o iniciar.bat de novo.
goto :falha

:config
if exist config_cursos.py goto :executar
echo.
echo ERRO: config_cursos.py nao encontrado. Veja o README para configurar seus cursos.
goto :falha

:executar
"%PYTHON%" hotmark.py %*
echo.
pause
exit /b 0

:falha
echo.
pause
exit /b 1
