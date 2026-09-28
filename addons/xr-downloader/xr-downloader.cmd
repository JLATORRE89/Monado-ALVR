@echo off
py -3 "%~dp0xr_downloader.py" %*
exit /b %errorlevel%
