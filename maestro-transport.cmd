@echo off
cd /d "C:\Users\there\Projects\Maestro\maestro-protocol"
node scripts/transport-service.mjs >> "%TEMP%\maestro-transport.log" 2>&1
