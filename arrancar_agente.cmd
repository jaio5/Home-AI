@echo off
REM Las manos del companero en este PC.
REM
REM Deja esto corriendo en el Windows y el cerebro, este donde este, podra ver
REM tu pantalla, cambiar el volumen, poner musica y abrir tus juegos.
REM
REM La ficha sale de secretos.env; no hay que exportar nada a mano.

cd /d "%~dp0tools"
title Companero de IA - agente
python -u agente_pc.py
pause
