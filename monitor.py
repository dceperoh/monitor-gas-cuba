import os
import re
import json
import time
import requests
from bs4 import BeautifulSoup

# ============================================================
# CONFIGURACIÓN
# ============================================================
URL_PRODUCTO = "https://goniogas.com/producto/cilindro-de-gas-de-10kg/"
URL_COMPRA = "https://goniogas.com/checkout/?add-to-cart=108"

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

GIST_ID = os.getenv("GIST_ID")
GIST_TOKEN = os.getenv("GIST_TOKEN")
GIST_FILENAME = "estado_monitor_gas.json"

# Palabras clave (en minúsculas)
PALABRAS_SIN_STOCK = ["sin existencias", "agotado", "out of stock", "no disponible"]
PALABRAS_CON_STOCK = ["disponible", "añadir al carrito", "añadir a la cesta", "in stock"]

# Headers que imitan a un navegador real
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/121.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
}


# ============================================================
# GIST
# ============================================================
def leer_estado_gist():
    if not GIST_ID or not GIST_TOKEN:
        return {"disponibilidad": "desconocido", "cantidad": None,
                "ultima_verificacion": None, "ultima_notificacion": None}
    url = f"https://api.github.com/gists/{GIST_ID}"
    headers = {
        "Authorization": f"Bearer {GIST_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    try:
        r = requests.get(url, headers=headers, timeout=20)
        r.raise_for_status()
        estado = json.loads(r.json()["files"][GIST_FILENAME]["content"])
        print(f"📥 Estado leído de Gist: {estado}")
        return estado
    except Exception as e:
        print(f"❌ Error leyendo Gist: {e}")
        return {"disponibilidad": "desconocido", "cantidad": None,
                "ultima_verificacion": None, "ultima_notificacion": None}


def guardar_estado_gist(estado):
    if not GIST_ID or not GIST_TOKEN:
        return False
    url = f"https://api.github.com/gists/{GIST_ID}"
    headers = {
        "Authorization": f"Bearer {GIST_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    payload = {
        "files": {
            GIST_FILENAME: {
                "content": json.dumps(estado, indent=2, ensure_ascii=False)
            }
        }
    }
    try:
        r = requests.patch(url, headers=headers, json=payload, timeout=20)
        r.raise_for_status()
        print(f"💾 Estado guardado en Gist")
        return True
    except Exception as e:
        print(f"❌ Error guardando Gist: {e}")
        return False


# ============================================================
# TELEGRAM
# ============================================================
def enviar_telegram(mensaje):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ Faltan TELEGRAM_TOKEN o TELEGRAM_CHAT_ID")
        return False
    chat_ids = [c.strip() for c in TELEGRAM_CHAT_ID.split(",") if c.strip()]
    ok = True
    for cid in chat_ids:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            payload = {
                "chat_id": cid,
                "text": mensaje,
                "parse_mode": "HTML",
                "disable_web_page_preview": False,
            }
            resp = requests.post(url, json=payload, timeout=15)
            if resp.status_code == 200:
                print(f"✅ Telegram → {cid}")
            else:
                print(f"❌ Telegram error ({cid}): {resp.status_code} {resp.text}")
                ok = False
        except Exception as e:
            print(f"❌ Excepción Telegram ({cid}): {e}")
            ok = False
        time.sleep(0.5)
    return ok


# ============================================================
# SCRAPING (mejorado con múltiples estrategias)
# ============================================================
def verificar_disponibilidad():
    """Devuelve (estado, descripcion, cantidad)."""
    for intento in range(3):
        try:
            r = requests.get(URL_PRODUCTO, headers=HEADERS, timeout=30)
            print(f"🌐 Status: {r.status_code} | Tamaño: {len(r.text)} bytes | Server: {r.headers.get('Server')}")
            if r.status_code == 200:
                break
        except Exception as e:
            print(f"⚠️ Intento {intento+1}/3 falló: {e}")
            time.sleep(3)
    else:
        return "error", "No se pudo conectar tras 3 intentos", None

    html = r.text
    soup = BeautifulSoup(html, "html.parser")

    # ----- ESTRATEGIA 1: buscar <p class="stock ..."> -----
    stock_el = soup.find("p", class_="stock")
    if not stock_el:
        stock_el = soup.find(class_="stock")

    texto_stock = ""
    if stock_el:
        texto_stock = stock_el.get_text(" ", strip=True)
        clases = " ".join(stock_el.get("class", []))
        print(f"🎯 <p class='stock'> encontrado:")
        print(f"   Texto: '{texto_stock}'")
        print(f"   Clases: '{clases}'")

        # out-of-stock detectado por clase
        if "out-of-stock" in clases:
            return "sin_stock", "Sin existencias", 0
        if "in-stock" in clases:
            # Extraer cantidad
            numeros = re.findall(r"\d+", texto_stock)
            cantidad = int(numeros[0]) if numeros else None
            return "con_stock", texto_stock, cantidad

    # ----- ESTRATEGIA 2: por texto -----
    texto_lower = texto_stock.lower()
    for p in PALABRAS_SIN_STOCK:
        if p in texto_lower:
            return "sin_stock", "Sin existencias", 0

    # Buscar "N disponible(s)" en el bloque de stock
    m = re.search(r"(\d+)\s*disponible", texto_lower)
    if m:
        return "con_stock", texto_stock, int(m.group(1))

    # ----- ESTRATEGIA 3: buscar en todo el HTML el <p class="stock"> -----
    m = re.search(r'<p[^>]*class="[^"]*stock[^"]*out-of-stock[^"]*"[^>]*>([^<]*)</p>', html, re.IGNORECASE)
    if m:
        return "sin_stock", m.group(1).strip(), 0

    m = re.search(r'<p[^>]*class="[^"]*stock[^"]*in-stock[^"]*"[^>]*>([^<]*)</p>', html, re.IGNORECASE)
    if m:
        texto = m.group(1).strip()
        nums = re.findall(r"\d+", texto)
        cantidad = int(nums[0]) if nums else None
        return "con_stock", texto, cantidad

    # ----- ESTRATEGIA 4: fallback al texto completo -----
    texto_plano = soup.get_text(" ", strip=True).lower()
    if "sin existencias" in texto_plano:
        return "sin_stock", "Sin existencias (detectado en texto global)", 0

    # Buscar "N disponibles" en toda la página
    m = re.search(r"(\d+)\s*disponibles?", texto_plano)
    if m:
        return "con_stock", f"{m.group(1)} disponibles", int(m.group(1))

    # Si vemos "añadir al carrito/añadir a la cesta" cerca del producto, asumimos stock
    if "añadir al carrito" in texto_plano or "añadir a la cesta" in texto_plano:
        return "con_stock", "Botón de compra presente", None

    return "desconocido", "No se pudo determinar el estado", None


# ============================================================
# MENSAJE
# ============================================================
def formatear_mensaje(cantidad, descripcion):
    if cantidad and cantidad > 0:
        cantidad_txt = f"<b>{cantidad}</b> cilindro(s)"
    elif cantidad == 0:
        cantidad_txt = "<b>0</b> (sin stock)"
    else:
        cantidad_txt = "(cantidad no especificada)"

    return (
        f"🚨 <b>¡CILINDROS DE GAS DISPONIBLES!</b> 🚨\n\n"
        f"📦 <b>Disponibilidad:</b> {cantidad_txt}\n"
        f"📝 <b>Detalle:</b> {descripcion}\n"
        f"💰 <b>Precio:</b> 25,00 €\n"
        f"📍 <b>Punto:</b> La Coronela – Calle 222 e/23 y 25 – La Lisa\n\n"
        f"🛒 <b>COMPRAR AHORA:</b>\n"
        f'<a href="{URL_COMPRA}">➡️ Añadir al carrito y pagar</a>\n\n'
        f"⏰ ¡Corre, que vuelan!"
    )


# ============================================================
# MAIN
# ============================================================
def main():
    print("=" * 60)
    print("🔍 MONITOR DE DISPONIBILIDAD - GONIO GAS")
    print(f"🕐 {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}")
    print("=" * 60)

    estado_anterior = leer_estado_gist()
    estado_previo = estado_anterior.get("disponibilidad", "desconocido")
    print(f"📊 Estado anterior: {estado_previo}")

    nuevo_estado, descripcion, cantidad = verificar_disponibilidad()
    print(f"📊 Estado nuevo: {nuevo_estado}")
    print(f"📝 Descripción: {descripcion}")
    print(f"🔢 Cantidad: {cantidad}")

    ahora = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())

    # Notificar SIEMPRE que haya stock (no solo al cambiar)
    # pero evitar spam: notificar si hay stock Y (cambió de estado O pasó >30 min)
    notificar = False
    motivo = ""

    if nuevo_estado == "con_stock":
        if estado_previo != "con_stock":
            notificar = True
            motivo = "¡Cambio a disponible!"
        else:
            # Ya estaba disponible; notificar de nuevo solo si pasaron >30 min
            # desde la última notificación
            ultima = estado_anterior.get("ultima_notificacion")
            if ultima:
                try:
                    from datetime import datetime, timezone
                    t_ultima = datetime.strptime(ultima, "%Y-%m-%d %H:%M:%S UTC").replace(tzinfo=timezone.utc)
                    t_ahora = datetime.now(timezone.utc)
                    minutos = (t_ahora - t_ultima).total_seconds() / 60
                    if minutos >= 30:
                        notificar = True
                        motivo = f"Recordatorio: sigue disponible ({int(minutos)} min desde última alerta)"
                except Exception as e:
                    print(f"⚠️ No se pudo calcular tiempo: {e}")
                    notificar = True
                    motivo = "Re-notificando (no se pudo verificar tiempo)"
            else:
                notificar = True
                motivo = "Primera detección con stock"

    # Guardar estado
    estado_nuevo = {
        "disponibilidad": nuevo_estado,
        "cantidad": cantidad,
        "descripcion": descripcion,
        "ultima_verificacion": ahora,
        "ultima_notificacion": ahora if notificar else estado_anterior.get("ultima_notificacion"),
    }
    guardar_estado_gist(estado_nuevo)

    # Enviar notificación
    if notificar:
        print(f"🎉 {motivo} → Enviando a Telegram...")
        enviar_telegram(formatear_mensaje(cantidad, descripcion))
    elif nuevo_estado == "sin_stock":
        print("😴 Sin existencias. Nada que hacer.")
    elif nuevo_estado == "con_stock":
        print("ℹ️ Sigue disponible. Ya se notificó hace <30 min. Sin spam.")
    else:
        print(f"⚠️ Estado desconocido: {descripcion}")

    print("=" * 60)
    return 0


if __name__ == "__main__":
    exit(main())
