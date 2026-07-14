@echo off
cd /d C:\projects\APSParcer\client
echo Building GQ-Builder...
C:\projects\APSParcer\.venv\Scripts\pyinstaller.exe aps_parser.spec --clean --noconfirm
if %errorlevel% == 0 (
    echo SUCCESS! Exe rebuilt.
) else (
    echo BUILD FAILED. Error: %errorlevel%
)
pause
