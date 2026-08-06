"""
bot_commands.py — Comandos de Telegram para controlar el scanner a distancia.

Como el scanner no corre 24/7 escuchando (solo se despierta cada
CHECK_INTERVAL_MINUTES), los comandos que envíes se procesan en el
SIGUIENTE ciclo, no al instante — puede tardar hasta ese intervalo en
responderte.

Comandos soportados (escríbelos directo en el chat con tu bot):
  /tickers                — lista los tickers actuales
  /add SYMBOL [SYMBOL2..] — agrega uno o más tickers (valida que existan antes)
  /remove SYMBOL [...]    — quita uno o más tickers
  /timeframe 1h           — cambia la temporalidad de escaneo
  /status                 — muestra la configuración actual
  /help                   — lista de comandos
"""
import json
from pathlib import Path

import requests

import config

VALID_TIMEFRAMES = ["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d"]
GET_UPDATES_URL = "https://api.telegram.org/bot{token}/getUpdates"


# ── Configuración en tiempo real (tickers / temporalidad) ─────────────────────
def load_settings() -> dict:
    path = Path(config.SETTINGS_FILE)
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("tickers") and data.get("timeframe"):
                return data
        except Exception:
            pass
    # Primera vez -> partir de los valores por defecto de config.py
    settings = {"tickers": list(config.TICKERS), "timeframe": config.SCAN_TIMEFRAME}
    save_settings(settings)
    return settings


def save_settings(settings: dict):
    Path(config.SETTINGS_FILE).write_text(json.dumps(settings, indent=2, ensure_ascii=False), encoding="utf-8")


# ── Offset de Telegram (para no reprocesar el mismo mensaje dos veces) ────────
def load_offset() -> int:
    path = Path(config.TELEGRAM_OFFSET_FILE)
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8")).get("offset", 0)
        except Exception:
            return 0
    return 0


def save_offset(offset: int):
    Path(config.TELEGRAM_OFFSET_FILE).write_text(json.dumps({"offset": offset}), encoding="utf-8")


def _fetch_updates(offset: int):
    if config.TELEGRAM_BOT_TOKEN == "TU_TOKEN_AQUI":
        return []
    url = GET_UPDATES_URL.format(token=config.TELEGRAM_BOT_TOKEN)
    try:
        r = requests.get(url, params={"offset": offset + 1, "timeout": 0}, timeout=15)
        r.raise_for_status()
        return r.json().get("result", [])
    except Exception:
        return []


def _normalize_symbol(sym: str) -> str:
    sym = sym.strip().upper()
    return sym if sym.endswith("USDT") else sym + "USDT"


def process_commands(send_reply_fn, validate_symbol_fn) -> dict:
    """
    Revisa mensajes nuevos de Telegram, ejecuta los comandos encontrados, y
    devuelve la configuración (tickers/timeframe) ya actualizada para usar
    en este ciclo de escaneo.

    send_reply_fn(text)              -> envía un mensaje de vuelta al chat.
    validate_symbol_fn(symbol)       -> (existe: bool, exchange: str|None).
      Se usa para confirmar que un ticker nuevo realmente existe en algún
      exchange antes de agregarlo a la watchlist.
    """
    settings = load_settings()
    offset = load_offset()
    updates = _fetch_updates(offset)

    for update in updates:
        offset = max(offset, update.get("update_id", offset))
        msg = update.get("message") or update.get("edited_message")
        if not msg:
            continue
        chat_id = str(msg.get("chat", {}).get("id", ""))
        text = (msg.get("text") or "").strip()

        # Seguridad: solo se procesan comandos que vengan del chat_id configurado
        if chat_id != str(config.TELEGRAM_CHAT_ID) or not text.startswith("/"):
            continue

        parts = text.split()
        cmd = parts[0].lower().split("@")[0]  # soporta "/add@tu_bot" también
        args = parts[1:]

        if cmd == "/help":
            send_reply_fn(
                "<b>Comandos disponibles:</b>\n"
                "/tickers — ver lista actual\n"
                "/add SYMBOL [SYMBOL2 ...] — agregar tickers\n"
                "/remove SYMBOL [SYMBOL2 ...] — quitar tickers\n"
                "/timeframe 1h — cambiar temporalidad ("
                + ", ".join(VALID_TIMEFRAMES) + ")\n"
                "/status — ver configuración actual\n\n"
                f"⏱ Los cambios se aplican en el próximo ciclo (máx. {config.CHECK_INTERVAL_MINUTES} min)."
            )

        elif cmd == "/tickers":
            lst = ", ".join(settings["tickers"]) or "(vacío)"
            send_reply_fn(f"📋 <b>{len(settings['tickers'])} tickers:</b>\n{lst}")

        elif cmd == "/status":
            send_reply_fn(
                "⚙️ <b>Configuración actual</b>\n"
                f"Tickers: {len(settings['tickers'])}\n"
                f"Temporalidad: {settings['timeframe']}\n"
                f"Score mínimo: {config.SCORE_MIN}\n"
                f"HTF: {'activo (' + config.HTF_TIMEFRAME + ')' if config.USE_HTF_FILTER else 'desactivado'}"
            )

        elif cmd == "/add":
            if not args:
                send_reply_fn("Uso: /add SYMBOL [SYMBOL2 ...]  (ej: /add ARBUSDT)")
            else:
                added, failed, dup = [], [], []
                for raw in args:
                    sym = _normalize_symbol(raw)
                    if sym in settings["tickers"]:
                        dup.append(sym)
                        continue
                    ok, exch = validate_symbol_fn(sym)
                    if ok:
                        settings["tickers"].append(sym)
                        added.append(f"{sym} ({exch})")
                    else:
                        failed.append(sym)
                save_settings(settings)
                reply_lines = []
                if added:
                    reply_lines.append("✅ Agregado: " + ", ".join(added))
                if dup:
                    reply_lines.append("ℹ️ Ya estaban en la lista: " + ", ".join(dup))
                if failed:
                    reply_lines.append("❌ No encontrado en Binance/Bitget/MEXC: " + ", ".join(failed))
                send_reply_fn("\n".join(reply_lines) or "No hubo cambios.")

        elif cmd == "/remove":
            if not args:
                send_reply_fn("Uso: /remove SYMBOL [SYMBOL2 ...]")
            else:
                removed, not_found = [], []
                for raw in args:
                    sym = _normalize_symbol(raw)
                    if sym in settings["tickers"]:
                        settings["tickers"].remove(sym)
                        removed.append(sym)
                    else:
                        not_found.append(sym)
                save_settings(settings)
                reply_lines = []
                if removed:
                    reply_lines.append("🗑 Quitado: " + ", ".join(removed))
                if not_found:
                    reply_lines.append("ℹ️ No estaban en la lista: " + ", ".join(not_found))
                send_reply_fn("\n".join(reply_lines) or "No hubo cambios.")

        elif cmd == "/timeframe":
            if not args or args[0] not in VALID_TIMEFRAMES:
                send_reply_fn(f"Uso: /timeframe VALOR — válidos: {', '.join(VALID_TIMEFRAMES)}")
            else:
                settings["timeframe"] = args[0]
                save_settings(settings)
                send_reply_fn(f"⏱ Temporalidad de escaneo cambiada a {args[0]}")

        else:
            send_reply_fn(f"Comando no reconocido: {cmd}\nEscribe /help para ver la lista completa.")

    if updates:
        save_offset(offset)

    return settings
