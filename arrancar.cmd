@echo off
REM El companero entero en este PC: oye, piensa, habla y anima la cara.
REM
REM   arrancar.cmd          la cara llama por WiFi
REM   arrancar.cmd COM3     la cara va por cable USB

cd /d "%~dp0tools"
title Companero de IA
python -u buddy_pc.py %1
pause
