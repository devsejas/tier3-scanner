# Tier3 Scanner — 100% gratuito, fuera de TradingView

Escanea tu watchlist contra la API pública de Binance (sin API key, sin límites
de suscripción) usando el mismo Score de Confluencia de tu indicador de Pine
(EMA + ADX/DMI + RSI/MACD + filtro de liquidez y volatilidad), y te avisa por
Telegram solo cuando una moneda **cruza** el umbral — no en cada ciclo.

## 1. Instalar

Necesitas **Python 3.9+**. Verifica con:
```bash
python3 --version
```

Instala las dependencias:
```bash
pip install -r requirements.txt
```

## 2. Configurar Telegram

1. En Telegram, habla con **@BotFather** → `/newbot` → sigue los pasos → copia el **token**.
2. Envíale cualquier mensaje a tu bot nuevo (para que exista una conversación).
3. Visita en el navegador:
   `https://api.telegram.org/bot<TU_TOKEN>/getUpdates`
   (reemplaza `<TU_TOKEN>` por el token real, pegado justo después de "bot", sin espacios ni `< >`)
4. Copia el número que aparece dentro de `"chat": { "id": ... }` — ese es tu `chat_id`.
5. Abre `config.py` y pega ambos valores:
   ```python
   TELEGRAM_BOT_TOKEN = "123456789:AAHxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
   TELEGRAM_CHAT_ID = "987654321"
   ```

## 3. Ajustar tu watchlist y parámetros

Todo está en `config.py`:
- `TICKERS`: lista de símbolos de Binance (formato `SYMBOLUSDT`). Sin límite de 20 como en TradingView.
- `SCAN_TIMEFRAME` / `HTF_TIMEFRAME`: temporalidades de escaneo y de tendencia superior.
- `SCORE_MIN`, `ADX_MIN`, `ADX_MAX`, `VOL_MIN_MULT`, `ATR_PCT_MIN`: mismos parámetros que tu Pine Script.
- `CHECK_INTERVAL_MINUTES`: cada cuánto escanea (configurado en 15 min).

## 4. Correr el scanner

```bash
python scanner.py
```

Vas a ver en la consola un resumen de cada ciclo, ordenado por Score Long, y
recibirás un mensaje de Telegram apenas una moneda cruce el umbral. Para
detenerlo: `Ctrl+C`.

Se generan dos archivos automáticamente:
- `scanner.log` — historial completo de logs
- `scanner_state.json` — memoria de qué alertas ya se dispararon (evita spam)

## 5. Dejarlo corriendo 24/7

### ⭐ Opción A — GitHub Actions (recomendada: gratis, sin PC ni VPS)

GitHub ejecuta el script por ti cada 15 minutos en sus propios servidores.
No necesitas tu PC encendida ni pagar nada, siempre que el repositorio sea
**público** (en repos privados también funciona, pero con 2000 minutos
gratis al mes, que igual alcanzan de sobra para esto).

**Pasos:**

1. Crea un repositorio nuevo en GitHub (público) y sube esta carpeta completa
   (incluye `.github/workflows/scanner.yml`, ya viene armado).
   ```bash
   cd tier3_scanner
   git init
   git add .
   git commit -m "Tier3 Scanner"
   git branch -M main
   git remote add origin https://github.com/TU_USUARIO/tier3-scanner.git
   git push -u origin main
   ```

2. **⚠️ Importante — repo público:** deja `config.py` con los placeholders
   (`TU_TOKEN_AQUI` / `TU_CHAT_ID_AQUI`), **nunca subas tu token real** en el
   código. Las credenciales van como "Secrets" (paso siguiente), que están
   encriptados y no se ven en el repo.

3. En GitHub: **Settings → Secrets and variables → Actions → New repository secret**
   - Nombre: `TELEGRAM_BOT_TOKEN` → valor: tu token real
   - Nombre: `TELEGRAM_CHAT_ID` → valor: tu chat_id real

4. Ve a la pestaña **Actions** del repo y confirma que el workflow "Tier3
   Scanner" está habilitado. Puedes correrlo manualmente ahí mismo con
   "Run workflow" para probarlo antes de esperar los 15 min.

5. Listo — a partir de ahora corre solo, cada 15 minutos, sin depender de tu
   PC. El propio workflow guarda `scanner_state.json` de vuelta al repo para
   no repetirte la misma alerta en cada ejecución.

**Nota:** GitHub puede pausar automáticamente los workflows programados si el
repositorio no tiene actividad (commits) por 60 días. Si eso pasa, basta con
entrar a la pestaña Actions y reactivarlo con un clic, o hacer cualquier commit.

### Opción B — Tu PC (Windows/Mac)
Simplemente deja la terminal abierta con `python scanner.py` corriendo. Si
cierras la terminal, se detiene. Para que sobreviva a un cierre de sesión:

**Windows (Programador de Tareas):**
1. Abre "Programador de tareas" → Crear tarea básica
2. Desencadenador: "Al iniciar sesión"
3. Acción: Iniciar un programa → selecciona `python.exe` → en "Argumentos" pon la ruta de `scanner.py`

**Mac/Linux (con `screen` o `tmux`, para que siga corriendo aunque cierres la terminal):**
```bash
screen -S tier3scanner
python3 scanner.py
# Presiona Ctrl+A luego D para "desconectarte" sin detenerlo
# Para volver a verlo: screen -r tier3scanner
```

### Opción C — VPS / Raspberry Pi (si prefieres tener control total)
Usa un servicio de `systemd` para que arranque solo y se reinicie si falla:

```ini
# /etc/systemd/system/tier3scanner.service
[Unit]
Description=Tier3 Scanner
After=network.target

[Service]
Type=simple
WorkingDirectory=/ruta/a/tier3_scanner
ExecStart=/ruta/a/tier3_scanner/venv/bin/python /ruta/a/tier3_scanner/scanner.py
Restart=always
RestartSec=10
Environment=TELEGRAM_BOT_TOKEN=tu_token
Environment=TELEGRAM_CHAT_ID=tu_chat_id

[Install]
WantedBy=multi-user.target
```

Luego:
```bash
sudo systemctl daemon-reload
sudo systemctl enable tier3scanner
sudo systemctl start tier3scanner
sudo journalctl -u tier3scanner -f   # ver logs en vivo
```

## Notas

- La API pública de Binance no requiere key para leer klines, pero sí tiene
  límites de peso por IP (muy generosos, ~1200 req/min). Con 20 tickers cada
  15 min estás muy por debajo de ese límite.
- Si un símbolo no existe en Binance (par deslistado, memecoin muy nueva,
  etc.), el scanner lo salta y sigue con el resto — revisa `scanner.log` para
  ver esos casos puntuales.
- Los umbrales y pesos son exactamente los mismos que tu script de Pine, así
  que los resultados deberían ser consistentes con lo que ves en TradingView
  (pequeñas diferencias de precio en tiempo real son normales entre fuentes).
