@echo off
title BoxCutter
echo.
echo  Starting BoxCutter...
echo  Open http://localhost:5000 in your browser if it doesn't open automatically.
echo  Press Ctrl+C to stop the server.
echo.
python "%~dp0..\..\app.py"
pause
