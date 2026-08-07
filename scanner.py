"""
scanner.py — Tier3 Scanner (100% gratuito, fuera de TradingView)

Corre en un loop infinito: cada CHECK_INTERVAL_MINUTES revisa toda la watchlist
contra la API pública de Binance (sin API key, sin límites de suscripción),
calcula el mismo Score de Confluencia que tu indicador de Pine, y envía una
alerta a Telegram solo cuando una moneda CRUZA el umbral (no en cada ciclo).

Uso:
    python scanner.py

Detener: Ctrl+C
"""
import argparse
import json
import logging
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests

import config
import indicators as ind
import bot_commands

BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"
BITGET_KLINES_URL = "https://api.bitget.com/api/v2/spot/market/candles"
MEXC_KLINES_URL   = "https://api.mexc.com/api/v3/klines"
KUCOIN_KLINES_URL = "https://api.kucoin.com/api/v1/market/candles"
BYBIT_KLINES_URL  = "https://api.bybit.com/v5/market/kline"
TELEGRAM_URL = "https://api.telegram.org/bot{token}/sendMessage"

# ── Logging a archivo y consola ────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler(config.LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("tier3scanner")

# Lock compartido entre el hilo de comandos y el hilo principal del scan.
# Evita que ambos lean/escriban runtime_settings.json al mismo tiempo.
_cmd_lock = threading.Lock()


# ── Validador de símbolo (compartido por scan y hilo de comandos) ─────────────
def _validate_symbol(symbol: str):
    try:
        _, exch = fetch_klines(symbol, config.SCAN_TIMEFRAME, 5)
        return True, exch
    except Exception:
        return False, None


# ── Estado persistente (para no repetir alertas en cada ciclo) ────────────────
def load_state() -> dict:
    path = Path(config.STATE_FILE)
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_state(state: dict):
    Path(config.STATE_FILE).write_text(json.dumps(state, indent=2), encoding="utf-8")


# ── Caché de qué exchange tiene cada símbolo (para no reprobar Binance cada ciclo) ──
def load_exchange_cache() -> dict:
    path = Path(config.EXCHANGE_CACHE_FILE)
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_exchange_cache(cache: dict):
    Path(config.EXCHANGE_CACHE_FILE).write_text(json.dumps(cache, indent=2), encoding="utf-8")


# ── Telegram ────────────────────────────────────────────────────────────────
def send_telegram(message: str):
    if config.TELEGRAM_BOT_TOKEN == "TU_TOKEN_AQUI" or config.TELEGRAM_CHAT_ID == "TU_CHAT_ID_AQUI":
        log.warning("Telegram no configurado (revisa config.py) — mensaje no enviado: %s", message)
        return
    url = TELEGRAM_URL.format(token=config.TELEGRAM_BOT_TOKEN)
    try:
        r = requests.post(url, data={
            "chat_id": config.TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML",
        }, timeout=15)
        if r.status_code != 200:
            log.error("Telegram respondió %s: %s", r.status_code, r.text[:300])
    except requests.RequestException as e:
        log.error("Error enviando a Telegram: %s", e)


# ── Traducción de temporalidad al formato de cada exchange ────────────────────
def _to_bitget_interval(tf: str) -> str:
    mapping = {
        "1m": "1min", "3m": "3min", "5m": "5min", "15m": "15min", "30m": "30min",
        "1h": "1h", "2h": "2h", "4h": "4h", "6h": "6h", "12h": "12h",
        "1d": "1day", "3d": "3day", "1w": "1week", "1M": "1M",
    }
    return mapping.get(tf, tf)


def _to_mexc_interval(tf: str) -> str:
    mapping = {
        "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
        "1h": "60m", "4h": "4h", "8h": "8h", "1d": "1d", "1w": "1W", "1M": "1M",
    }
    return mapping.get(tf, tf)


def _normalize_df(rows, columns=("open_time", "open", "high", "low", "close", "volume")) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=list(columns))
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)
    return df.sort_values("open_time").reset_index(drop=True)


# ── Binance ─────────────────────────────────────────────────────────────────
def fetch_klines_binance(symbol: str, interval: str, limit: int) -> pd.DataFrame:
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    r = requests.get(BINANCE_KLINES_URL, params=params, timeout=15)
    if r.status_code == 400:
        raise ValueError(f"Símbolo no existe en Binance: {symbol}")
    r.raise_for_status()
    raw = r.json()
    if not raw:
        raise ValueError("Respuesta vacía de Binance")
    rows = [[k[0], k[1], k[2], k[3], k[4], k[5]] for k in raw]
    return _normalize_df(rows)


# ── Bitget ──────────────────────────────────────────────────────────────────
def fetch_klines_bitget(symbol: str, interval: str, limit: int) -> pd.DataFrame:
    params = {"symbol": symbol, "granularity": _to_bitget_interval(interval), "limit": min(limit, 1000)}
    r = requests.get(BITGET_KLINES_URL, params=params, timeout=15)
    r.raise_for_status()
    j = r.json()
    if j.get("code") != "00000":
        raise ValueError(f"Bitget: {j.get('msg', 'error desconocido')}")
    raw = j.get("data", [])
    if not raw:
        raise ValueError("Respuesta vacía de Bitget (símbolo probablemente no existe)")
    rows = [[int(k[0]), k[1], k[2], k[3], k[4], k[5]] for k in raw]
    return _normalize_df(rows)


# ── MEXC ────────────────────────────────────────────────────────────────────
def fetch_klines_mexc(symbol: str, interval: str, limit: int) -> pd.DataFrame:
    params = {"symbol": symbol, "interval": _to_mexc_interval(interval), "limit": min(limit, 1000)}
    r = requests.get(MEXC_KLINES_URL, params=params, timeout=15)
    r.raise_for_status()
    raw = r.json()
    if not raw or isinstance(raw, dict):
        raise ValueError(f"Respuesta inválida de MEXC: {raw}")
    rows = [[k[0], k[1], k[2], k[3], k[4], k[5]] for k in raw]
    return _normalize_df(rows)


# ── KuCoin ──────────────────────────────────────────────────────────────────
def _to_kucoin_symbol(symbol: str) -> str:
    """Convierte 'BTCUSDT' -> 'BTC-USDT' para la API de KuCoin."""
    if symbol.endswith("USDT"):
        return symbol[:-4] + "-USDT"
    return symbol


def _to_kucoin_interval(tf: str) -> str:
    mapping = {
        "1m": "1min",  "3m": "3min",  "5m": "5min", "15m": "15min", "30m": "30min",
        "1h": "1hour", "2h": "2hour", "4h": "4hour",  "6h": "6hour",  "8h": "8hour",
        "12h": "12hour", "1d": "1day", "1w": "1week",
        # 45m no soportado por KuCoin
    }
    return mapping.get(tf, "")


def fetch_klines_kucoin(symbol: str, interval: str, limit: int) -> pd.DataFrame:
    kc_interval = _to_kucoin_interval(interval)
    if not kc_interval:
        raise ValueError(f"KuCoin no soporta el timeframe: {interval}")
    kc_symbol = _to_kucoin_symbol(symbol)
    params = {"symbol": kc_symbol, "type": kc_interval}
    r = requests.get(KUCOIN_KLINES_URL, params=params, timeout=15)
    r.raise_for_status()
    j = r.json()
    if str(j.get("code")) != "200000":
        raise ValueError(f"KuCoin: {j.get('msg', 'error desconocido')}")
    raw = j.get("data", [])
    if not raw:
        raise ValueError("Respuesta vacía de KuCoin (símbolo probablemente no existe)")
    # KuCoin devuelve: [timestamp_seg, open, close, high, low, volume, amount] — orden DESCENDENTE
    # _normalize_df espera: open_time(ms), open, high, low, close, volume
    rows = [[int(k[0]) * 1000, k[1], k[3], k[4], k[2], k[5]] for k in raw]
    rows = rows[::-1]        # de descendente a ascendente
    rows = rows[-limit:]     # respetar el límite solicitado
    return _normalize_df(rows)


# ── Bybit ───────────────────────────────────────────────────────────────────
def _to_bybit_interval(tf: str) -> str:
    mapping = {
        "1m": "1",  "3m": "3",   "5m": "5",   "15m": "15",  "30m": "30",
        "45m": "45",  # Bybit soporta 45m nativamente
        "1h": "60",  "2h": "120", "4h": "240", "6h": "360",  "12h": "720",
        "1d": "D",  "1w": "W",   "1M": "M",
    }
    return mapping.get(tf, "")


def fetch_klines_bybit(symbol: str, interval: str, limit: int) -> pd.DataFrame:
    bybit_interval = _to_bybit_interval(interval)
    if not bybit_interval:
        raise ValueError(f"Bybit no soporta el timeframe: {interval}")
    params = {
        "category": "spot",
        "symbol": symbol,
        "interval": bybit_interval,
        "limit": min(limit, 1000),
    }
    r = requests.get(BYBIT_KLINES_URL, params=params, timeout=15)
    r.raise_for_status()
    j = r.json()
    if j.get("retCode") != 0:
        raise ValueError(f"Bybit: {j.get('retMsg', 'error desconocido')}")
    raw = j.get("result", {}).get("list", [])
    if not raw:
        raise ValueError("Respuesta vacía de Bybit (símbolo probablemente no existe)")
    # Bybit: [startTime(ms), open, high, low, close, volume, turnover] — orden DESCENDENTE
    rows = [[int(k[0]), k[1], k[2], k[3], k[4], k[5]] for k in raw]
    rows = rows[::-1]  # de descendente a ascendente
    return _normalize_df(rows)


FETCHERS = {
    "binance": fetch_klines_binance,
    "bitget":  fetch_klines_bitget,
    "mexc":    fetch_klines_mexc,
    "kucoin":  fetch_klines_kucoin,
    "bybit":   fetch_klines_bybit,
}
EXCHANGE_ORDER = ["binance", "bitget", "mexc", "kucoin", "bybit"]


def fetch_klines(symbol: str, interval: str, limit: int, exchange_hint: str | None = None, retries: int = 1):
    """
    Intenta obtener velas probando exchanges en orden (Binance -> Bitget -> MEXC),
    con reintentos por exchange. Si exchange_hint viene dado (de una corrida anterior),
    lo prueba primero para ahorrar tiempo. Devuelve (DataFrame, nombre_exchange_usado).
    """
    order = [exchange_hint] + [e for e in EXCHANGE_ORDER if e != exchange_hint] if exchange_hint else EXCHANGE_ORDER
    last_err = None
    for exchange in order:
        fetcher = FETCHERS.get(exchange)
        if not fetcher:
            continue
        for attempt in range(retries):
            try:
                df = fetcher(symbol, interval, limit)
                return df, exchange
            except Exception as e:
                last_err = e
                time.sleep(1.0 * (attempt + 1))
        # se agotaron los reintentos en este exchange -> probar el siguiente
    raise RuntimeError(f"{symbol} no encontrado en Binance/Bitget/MEXC: {last_err}")


def _timeframe_to_seconds(tf: str) -> int:
    """Convierte '1h', '4h', '1d', etc. a segundos."""
    unit = tf[-1]
    try:
        num = int(tf[:-1])
    except ValueError:
        return 3600
    mult = {"m": 60, "h": 3600, "d": 86400, "w": 604800, "M": 2592000}
    return num * mult.get(unit, 3600)


# ── Cálculo del Score de Confluencia (réplica del Pine Script) ────────────────
def compute_metrics(df: pd.DataFrame, df_htf: pd.DataFrame | None, scan_timeframe: str = None) -> dict:
    scan_timeframe = scan_timeframe or config.SCAN_TIMEFRAME
    close = df["close"]
    volume = df["volume"]

    ema_fast = ind.ema(close, 21)
    ema_slow = ind.ema(close, 55)
    trend_up = bool(ema_fast.iloc[-1] > ema_slow.iloc[-1] and close.iloc[-1] > ema_fast.iloc[-1])
    trend_down = bool(ema_fast.iloc[-1] < ema_slow.iloc[-1] and close.iloc[-1] < ema_fast.iloc[-1])

    adx, plus_di, minus_di = ind.dmi(df, 14)
    adx_val = adx.iloc[-1]
    adx_sano = bool(config.ADX_MIN <= adx_val <= config.ADX_MAX)
    adx_rising = bool(adx.iloc[-1] > adx.iloc[-2])
    di_bull = bool(plus_di.iloc[-1] > minus_di.iloc[-1])
    di_bear = bool(minus_di.iloc[-1] > plus_di.iloc[-1])

    rsi_val = ind.rsi(close, 14).iloc[-1]
    _, _, hist = ind.macd(close, 12, 26, 9)
    hist_val = hist.iloc[-1]
    momentum_bull = bool(rsi_val > 50 and hist_val > 0)
    momentum_bear = bool(rsi_val < 50 and hist_val < 0)

    # ── Liquidez ──
    # La última vela suele estar aún en formación (no cerrada), así que su volumen
    # acumulado hasta ahora es solo una fracción del que tendrá al cerrar. Comparar
    # ese valor parcial contra el promedio de velas completas casi siempre da "NO",
    # sin importar qué tan líquido sea el activo. Por eso lo proyectamos según
    # cuánto tiempo lleva abierta la vela, y comparamos contra el promedio de las
    # 20 velas anteriores YA CERRADAS (sin incluir la actual en el promedio).
    interval_sec = _timeframe_to_seconds(scan_timeframe)
    last_open_ms = df["open_time"].iloc[-1]
    now_ms = time.time() * 1000
    elapsed_sec = max((now_ms - last_open_ms) / 1000, 0)
    elapsed_frac = min(max(elapsed_sec / interval_sec, 0.05), 1.0)  # mínimo 5% para no dividir por ~0

    current_vol = volume.iloc[-1]
    projected_vol = current_vol / elapsed_frac  # volumen estimado si la vela cerrara ahora

    closed_window = volume.iloc[-21:-1]  # 20 velas previas, todas ya cerradas
    avg_vol = closed_window.mean() if len(closed_window) > 0 else np.nan
    liquidez_ok = bool(projected_vol >= avg_vol * config.VOL_MIN_MULT) if not np.isnan(avg_vol) else False

    atr14 = ind.atr(df, 14)
    atr_pct = ind.percentrank(atr14, 100).iloc[-1]
    vola_ok = bool(atr_pct >= config.ATR_PCT_MIN) if not np.isnan(atr_pct) else False

    score_long = (
        (config.W_TREND if trend_up else 0)
        + (config.W_ADX if (adx_sano and di_bull) else 0)
        + (config.W_MOMENTUM if momentum_bull else 0)
        + (config.W_BONUS_ADX if (adx_rising and di_bull) else 0)
    )
    score_short = (
        (config.W_TREND if trend_down else 0)
        + (config.W_ADX if (adx_sano and di_bear) else 0)
        + (config.W_MOMENTUM if momentum_bear else 0)
        + (config.W_BONUS_ADX if (adx_rising and di_bear) else 0)
    )

    htf_bull, htf_bear = True, True  # por defecto no bloquean si el filtro está desactivado
    if config.USE_HTF_FILTER and df_htf is not None and len(df_htf) > config.HTF_EMA_LENGTH:
        htf_ema = ind.ema(df_htf["close"], config.HTF_EMA_LENGTH)
        htf_bull = bool(df_htf["close"].iloc[-1] > htf_ema.iloc[-1])
        htf_bear = bool(df_htf["close"].iloc[-1] < htf_ema.iloc[-1])

    long_hit = score_long >= config.SCORE_MIN and liquidez_ok and vola_ok and htf_bull
    short_hit = score_short >= config.SCORE_MIN and liquidez_ok and vola_ok and htf_bear

    return {
        "price": float(close.iloc[-1]),
        "score_long": int(score_long),
        "score_short": int(score_short),
        "adx": float(adx_val) if not np.isnan(adx_val) else 0.0,
        "atr": float(atr14.iloc[-1]) if not np.isnan(atr14.iloc[-1]) else 0.0,
        "atr_pct": float(atr_pct) if not np.isnan(atr_pct) else 0.0,
        "liquidez_ok": liquidez_ok,
        "vola_ok": vola_ok,
        "htf_bull": htf_bull,
        "htf_bear": htf_bear,
        "long_hit": bool(long_hit),
        "short_hit": bool(short_hit),
    }


def format_price(p: float) -> str:
    if p < 0.01:
        return f"{p:.8f}"
    if p < 1:
        return f"{p:.5f}"
    if p < 100:
        return f"{p:.4f}"
    return f"{p:,.2f}"


# ── Hilo independiente: procesa comandos de Telegram sin bloquear el scan ─────
def _command_processor_loop():
    """
    Corre en segundo plano cada COMMAND_POLL_SECONDS (default 60 s).
    Procesa /add, /remove, /timeframe, /status, /help de forma inmediata,
    sin necesidad de esperar a que termine el ciclo de scan completo.
    """
    log.info("Hilo de comandos iniciado — polling cada %ds", config.COMMAND_POLL_SECONDS)
    while True:
        try:
            with _cmd_lock:
                bot_commands.process_commands(send_telegram, _validate_symbol)
        except Exception as e:
            log.error("Error en hilo de comandos: %s", e)
        time.sleep(config.COMMAND_POLL_SECONDS)


# ── Un ciclo completo de escaneo ───────────────────────────────────────────────
def send_telegram_silent(message: str):
    """Igual que send_telegram pero sin sonido (disable_notification=True)."""
    if config.TELEGRAM_BOT_TOKEN in ("TU_TOKEN_AQUI", "") or \
       config.TELEGRAM_CHAT_ID in ("TU_CHAT_ID_AQUI", ""):
        return
    url = TELEGRAM_URL.format(token=config.TELEGRAM_BOT_TOKEN)
    try:
        requests.post(url, data={
            "chat_id": config.TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML",
            "disable_notification": "true",
        }, timeout=10)
    except Exception:
        pass


def run_scan():
    state = load_state()
    exchange_cache = load_exchange_cache()
    results = []

    # Procesa comandos de Telegram pendientes (/add, /remove, /timeframe…).
    with _cmd_lock:
        settings = bot_commands.process_commands(send_telegram, _validate_symbol)
    tickers = settings["tickers"]
    scan_tf = settings["timeframe"]

    # Heartbeat: mensaje silencioso al inicio (sin sonido).
    # Permite saber que GitHub Actions está corriendo aunque no haya señales.
    cycle_count = state.get("_cycle_count", 0) + 1
    state["_cycle_count"] = cycle_count
    
    interval = getattr(config, "HEARTBEAT_INTERVAL_CYCLES", 12)
    if config.HEARTBEAT_ENABLED and (cycle_count % interval) == 1:
        ts = datetime.now(timezone.utc).astimezone().strftime("%H:%M")
        send_telegram_silent(
            f"🔄 <b>Scanner activo</b> — {ts} (Ciclo {cycle_count})\n"
            f"Escaneando {len(tickers)} tickers en {scan_tf}"
        )

    for symbol in tickers:
        try:
            hint = exchange_cache.get(symbol)
            df_scan, used_exchange = fetch_klines(symbol, scan_tf, config.KLINES_LIMIT, exchange_hint=hint)
            exchange_cache[symbol] = used_exchange  # recordar para el próximo ciclo (evita reprobar exchanges)

            df_htf = None
            if config.USE_HTF_FILTER:
                # ya sabemos en qué exchange está -> se pide directo ahí, sin recorrer los 3 de nuevo
                df_htf, _ = fetch_klines(symbol, config.HTF_TIMEFRAME, config.HTF_EMA_LENGTH + 20, exchange_hint=used_exchange)

            m = compute_metrics(df_scan, df_htf, scan_timeframe=scan_tf)
            results.append({"symbol": symbol, "exchange": used_exchange, **m})

            prev = state.get(symbol, {"long": False, "short": False})
            entry = m["price"]
            atr = m["atr"]

            if m["long_hit"] and not prev.get("long"):
                sl = entry - atr * config.ATR_SL_MULT
                tp = entry + atr * config.ATR_SL_MULT * config.TP_RR
                send_telegram(
                    f"🟢 <b>LONG {symbol}</b> <i>({used_exchange}, {scan_tf})</i>\n"
                    f"Score: {m['score_long']}/100 | ADX: {m['adx']:.1f} | Volatilidad: {m['atr_pct']:.0f}%\n"
                    f"Entrada: {format_price(entry)}\n"
                    f"SL: {format_price(sl)}\n"
                    f"TP: {format_price(tp)}"
                )
                log.info("ALERTA LONG %s [%s] (score=%s)", symbol, used_exchange, m["score_long"])

            if m["short_hit"] and not prev.get("short"):
                sl = entry + atr * config.ATR_SL_MULT
                tp = entry - atr * config.ATR_SL_MULT * config.TP_RR
                send_telegram(
                    f"🔴 <b>SHORT {symbol}</b> <i>({used_exchange}, {scan_tf})</i>\n"
                    f"Score: {m['score_short']}/100 | ADX: {m['adx']:.1f} | Volatilidad: {m['atr_pct']:.0f}%\n"
                    f"Entrada: {format_price(entry)}\n"
                    f"SL: {format_price(sl)}\n"
                    f"TP: {format_price(tp)}"
                )
                log.info("ALERTA SHORT %s [%s] (score=%s)", symbol, used_exchange, m["score_short"])

            state[symbol] = {"long": m["long_hit"], "short": m["short_hit"]}

        except Exception as e:
            log.error("Error procesando %s: %s", symbol, e)

        time.sleep(config.REQUEST_DELAY_SECONDS)

    save_state(state)
    save_exchange_cache(exchange_cache)
    print_summary(results)


def print_summary(results: list[dict]):
    if not results:
        return
    results_sorted = sorted(results, key=lambda r: r["score_long"], reverse=True)
    ts = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")
    log.info("── Resumen del ciclo (%s) ──", ts)
    header = f"{'TICKER':<12}{'EXCH':<9}{'PRECIO':>14}{'SC.LONG':>9}{'SC.SHORT':>10}{'ADX':>7}  LIQ VOLA HTF"
    log.info(header)
    for r in results_sorted:
        flag = "🟢" if r["long_hit"] else "🔴" if r["short_hit"] else "  "
        log.info(
            f"{r['symbol']:<12}{r.get('exchange','?'):<9}{format_price(r['price']):>14}{r['score_long']:>9}{r['score_short']:>10}"
            f"{r['adx']:>7.1f}   {'OK' if r['liquidez_ok'] else 'NO'}  "
            f"{'OK' if r['vola_ok'] else 'NO'}  "
            f"{'A' if r['htf_bull'] else 'B'}  {flag}"
        )


# ── Loop principal ─────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Tier3 Scanner")
    parser.add_argument("--once", action="store_true",
                         help="Corre un solo escaneo y termina (para cron / GitHub Actions). "
                              "Sin esta bandera, corre en loop infinito (para PC/VPS).")
    args = parser.parse_args()

    if args.once:
        # Cargamos settings antes del log para mostrar el conteo real
        # (puede diferir de config.TICKERS si el usuario usó /add o /remove via Telegram)
        _startup_settings = bot_commands.load_settings()
        log.info(
            "Tier3 Scanner — ejecución única (--once), %d tickers, timeframe %s",
            len(_startup_settings["tickers"]),
            _startup_settings["timeframe"],
        )
        run_scan()
        return

    log.info("Tier3 Scanner iniciado — %d tickers, cada %d min, timeframe %s (HTF %s)",
              len(config.TICKERS), config.CHECK_INTERVAL_MINUTES, config.SCAN_TIMEFRAME,
              config.HTF_TIMEFRAME if config.USE_HTF_FILTER else "desactivado")

    # ── Hilo de comandos: procesa /add, /remove, etc. cada COMMAND_POLL_SECONDS ──
    cmd_thread = threading.Thread(target=_command_processor_loop, name="cmd-poller", daemon=True)
    cmd_thread.start()
    log.info("Hilo de comandos activo — responderá comandos de Telegram en ~%ds", config.COMMAND_POLL_SECONDS)

    while True:
        cycle_start = time.time()
        try:
            run_scan()
        except Exception as e:
            log.error("Error inesperado en el ciclo de escaneo: %s", e)

        elapsed = time.time() - cycle_start
        sleep_for = max(5, config.CHECK_INTERVAL_MINUTES * 60 - elapsed)
        log.info("Ciclo completado en %.1fs. Próximo escaneo en %.0f min.", elapsed, sleep_for / 60)
        time.sleep(sleep_for)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("Scanner detenido por el usuario.")
