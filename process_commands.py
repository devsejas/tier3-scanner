"""
process_commands.py — Solo procesa comandos de Telegram, sin escanear.

Se llama desde GitHub Actions ANTES del scan completo para que
/add, /remove y /timeframe respondan en la misma corrida, sin
esperar a que terminen los 49 tickers.
"""
import sys
import logging
import scanner   # reutiliza send_telegram y _validate_symbol

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

import bot_commands
import config

log = logging.getLogger("cmd-processor")

if config.TELEGRAM_BOT_TOKEN in ("TU_TOKEN_AQUI", "") or \
   config.TELEGRAM_CHAT_ID in ("TU_CHAT_ID_AQUI", ""):
    log.warning("Telegram no configurado — sin comandos que procesar.")
    sys.exit(0)

log.info("Procesando comandos de Telegram pendientes...")
settings = bot_commands.process_commands(scanner.send_telegram, scanner._validate_symbol)
log.info("Listo — %d tickers, timeframe=%s", len(settings["tickers"]), settings["timeframe"])
