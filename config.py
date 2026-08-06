"""
config.py — Configuración del Tier3 Scanner.

Las credenciales de Telegram se leen de variables de entorno (TELEGRAM_BOT_TOKEN,
TELEGRAM_CHAT_ID) si existen; si no, usa los valores de abajo. Esto permite:
  - Correrlo localmente rellenando los valores de abajo directamente, O
  - Correrlo en GitHub Actions usando "Secrets" del repo (recomendado si el
    repo es público — NUNCA subas tu token real a un repo público).
"""
import os

# ── Telegram ──────────────────────────────────────────────────────────────────
# 1. Habla con @BotFather en Telegram -> /newbot -> copia el token
# 2. Escríbele algo a tu bot, luego visita:
#    https://api.telegram.org/bot<TU_TOKEN>/getUpdates
#    y copia el "id" que aparece dentro de "chat"
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "TU_TOKEN_AQUI")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "TU_CHAT_ID_AQUI")

# ── Watchlist (símbolos, formato SYMBOLUSDT) ────────────────────────────────────
# El scanner prueba automáticamente Binance -> Bitget -> MEXC por cada símbolo,
# así que no importa en cuál de los 3 exchanges esté listada la moneda.
TICKERS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "WLDUSDT", "JASMYUSDT",
    "PEPEUSDT", "LINKUSDT", "ONDOUSDT", "FETUSDT", "NILUSDT",
    "RIFUSDT", "FILUSDT", "JTOUSDT", "SEIUSDT", "LITUSDT",
    "LINEAUSDT", "BTTUSDT", "FLOWUSDT", "SPELLUSDT", "REEFUSDT", "ENAUSDT",
    "GMTUSDT", "BIOUSDT", "OKBUSDT", "KSMUSDT", "ILVUSDT", "HBARUSDT",
    "PORTALUSDT", "TRXUSDT", "QNTUSDT", "CAKEUSDT", "SUNUSDT", "RUNEUSDT",
    "PYTHUSDT", "CROUSDT", "VETUSDT", "TAOUSDT", "NEARUSDT", "RLCUSDT",
    "ICPUSDT", "INITUSDT", "TRACUSDT", "CGPTUSDT", "AIOZUSDT", "DODOUSDT",
    "PENGUUSDT", "AAVEUSDT", "PENDLEUSDT",
]

# ── Temporalidades ──────────────────────────────────────────────────────────────
# Valores válidos de Binance: 1m,3m,5m,15m,30m,1h,2h,4h,6h,8h,12h,1d,3d,1w,1M
SCAN_TIMEFRAME = "1h"
HTF_TIMEFRAME = "1d"
HTF_EMA_LENGTH = 50
USE_HTF_FILTER = True

# ── Score de Confluencia (mismos pesos que tu script de Pine) ─────────────────
W_TREND = 35
W_ADX = 30
W_MOMENTUM = 35
W_BONUS_ADX = 10
SCORE_MIN = 70

ADX_MIN = 20
ADX_MAX = 48

VOL_MIN_MULT = 0.8   # volumen actual >= promedio(20) * este múltiplo
ATR_PCT_MIN = 25     # percentil mínimo de ATR (filtro anti-chop / baja volatilidad)

# ── Gestión de riesgo para el SL/TP que se muestra en la alerta ────────────────
# Mismo enfoque que tu script de Pine: SL/TP dimensionados por ATR, no por % fijo.
ATR_SL_MULT = 1.5    # distancia del Stop Loss = ATR * este múltiplo
TP_RR = 2.5          # Take Profit = distancia del SL * este ratio riesgo/beneficio

# ── Scanner ──────────────────────────────────────────────────────────────────
CHECK_INTERVAL_MINUTES = 5
KLINES_LIMIT = 300           # velas históricas por request (suficiente para EMA55, ADX14, etc.)
REQUEST_DELAY_SECONDS = 0.3  # pausa entre símbolos para no saturar la API de Binance

# ── Comandos de Telegram (hilo independiente) ─────────────────────────────────
COMMAND_POLL_SECONDS = 60

# ── Heartbeat de Telegram ─────────────────────────────────────────────────────
# Si es True, envía un mensaje silencioso al inicio de cada ciclo de scan
# para confirmar que el scanner está vivo y corriendo.
# Útil para detectar cuando GitHub Actions se retrasa o se detiene.
HEARTBEAT_ENABLED = True

STATE_FILE = "scanner_state.json"
EXCHANGE_CACHE_FILE = "exchange_cache.json"
LOG_FILE = "scanner.log"

# ── Configuración controlable desde el bot de Telegram (/add, /remove, /timeframe) ──
# Estos archivos guardan los cambios hechos vía comandos de Telegram, y tienen
# prioridad sobre TICKERS y SCAN_TIMEFRAME de arriba una vez que existen.
SETTINGS_FILE = "runtime_settings.json"
TELEGRAM_OFFSET_FILE = "telegram_offset.json"
