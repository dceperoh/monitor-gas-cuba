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

# Telegram (desde Secrets de GitHub)
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# GitHub Gist (desde Secrets de GitHub)
GIST_ID = os.getenv("GIST_ID")
GIST_TOKEN = os.getenv("GIST_TOKEN")
GIST_FILENAME = "estado_monitor_gas.json"

# Palabras clave
PALABRA_SIN_STOCK = "sin existencias"
PALABRA_CON_STOCK = "disponible"

# ============================================================
# GIST: LEER Y ESCRIBIR ESTADO
# ============================================================
def leer_estado_gist():
    """Lee el estado desde la Gist de GitHub."""
    if not GIST_ID or not GIST_TOKEN:
        print("⚠️ Faltan GIST_ID o GIST_TOKEN, usando estado por defecto")
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
        data = r.json()
        contenido = data["files"][GIST_FILENAME]["content"]
        estado = json.loads(contenido)
        print(f"📥 Estado leído de Gist: {estado}")
        return estado
    except Exception as e:
        print(f"❌ Error leyendo Gist: {e}")
        return {"disponibilidad": "desconocido", "cantidad": None,
                "ultima_verificacion": None, "ultima_notificacion": None}


def guardar_estado_gist(estado):
    """Guarda el estado en la Gist de GitHub."""
    if not GIST_ID or not GIST_TOKEN:
        print("⚠️ Faltan GIST_ID o GIST_TOKEN, no se puede guardar")
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
        print(f"💾 Estado guardado en Gist: {estado}")
        return True
    except Exception as e:
        print(f"❌ Error guardando Gist: {e}")
        return False


# ============================================================
# TELEGRAM
# ============================================================
def enviar_telegram(mensaje):
    """Envía un mensaje a Telegram a todos los chat IDs configurados."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ Faltan TELEGRAM_TOKEN o TELEGRAM_CHAT_ID")
        return False

    chat_ids = [cid.strip() for cid in TELEGRAM_CHAT_ID.split(",") if cid.strip()]
    exito = True

    for chat_id in chat_ids:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            payload = {
                "chat_id": chat_id,
                "text": mensaje,
                "parse_mode": "HTML",
                "disable_web_page_preview": False,
            }
            resp = requests.post(url, json=payload, timeout=15)
            if resp.status_code != 200:
                print(f"❌ Error Telegram ({chat_id}): {resp.status_code} - {resp.text}")
                exito = False
            else:
                print(f"✅ Mensaje enviado a {chat_id}")
        except Exception as e:
            print(f"❌ Excepción al enviar a {chat_id}: {e}")
            exito = False
        time.sleep(0.5)

    return exito


# ============================================================
# SCRAPING: VERIFICAR DISPONIBILIDAD
# ============================================================
def verificar_disponibilidad():
    """Verifica la página del producto y devuelve (estado, descripcion, cantidad)."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }

    try:
        resp = requests.get(URL_PRODUCTO, headers=headers, timeout=30)
        resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        return "error", f"Error de conexión: {e}", None

    soup = BeautifulSoup(resp.text, "html.parser")

    # 1. Buscar bloque de stock de WooCommerce
    stock_element = soup.find(class_="stock")

    if stock_element:
        texto_stock = stock_element.get_text(" ", strip=True).lower()
        print(f"📄 Texto de stock: '{texto_stock}'")

        if PALABRA_SIN_STOCK in texto_stock:
            return "sin_stock", "Sin existencias", 0

        if PALABRA_CON_STOCK in texto_stock:
            numeros = re.findall(r"\d+", texto_stock)
            cantidad = int(numeros[0]) if numeros else None
            return "con_stock", "Disponible", cantidad

    # 2. Fallback: buscar en toda la página
    texto_completo = soup.get_text(" ", strip=True).lower()

    if PALABRA_SIN_STOCK in texto_completo:
        return "sin_stock", "Sin existencias", 0

    if PALABRA_CON_STOCK in texto_completo:
        numeros = re.findall(r"(\d+)\s*disponible", texto_completo)
        cantidad = int(numeros[0]) if numeros else None
        return "con_stock", "Disponible", cantidad

    return "desconocido", "No se pudo determinar", None


# ============================================================
# MENSAJE
# ============================================================
def formatear_mensaje(cantidad):
    """Formatea el mensaje de alerta para Telegram."""
    if cantidad and cantidad > 0:
        cabecera = f"📦 <b>Cantidad detectada:</b> {cantidad} cilindro(s)"
    else:
        cabecera = "📦 <b>Estado:</b> Disponible"

    return (
        f"🚨 <b>¡CILINDROS DE GAS DISPONIBLES!</b> 🚨\n\n"
        f"{cabecera}\n"
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
    print("=" * 50)
    print("🔍 MONITOR DE DISPONIBILIDAD - GONIO GAS")
    print("=" * 50)

    # 1. Leer estado anterior
    estado_anterior = leer_estado_gist()
    estado_previo = estado_anterior.get("disponibilidad", "desconocido")
    print(f"📊 Estado anterior: {estado_previo}")

    # 2. Verificar disponibilidad actual
    nuevo_estado, descripcion, cantidad = verificar_disponibilidad()
    print(f"📊 Estado nuevo: {nuevo_estado} ({descripcion})")

    # 3. Determinar si hay que notificar
    ahora = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
    debe_notificar = (
        nuevo_estado == "con_stock"
        and estado_previo != "con_stock"
    )

    # 4. Guardar estado actualizado
    estado_nuevo = {
        "disponibilidad": nuevo_estado,
        "cantidad": cantidad,
        "descripcion": descripcion,
        "ultima_verificacion": ahora,
        "ultima_notificacion": (
            ahora if debe_notificar
            else estado_anterior.get("ultima_notificacion")
        ),
    }
    guardar_estado_gist(estado_nuevo)

    # 5. Enviar notificación si procede
    if debe_notificar:
        print("🎉 ¡CAMBIO DETECTADO! Enviando notificación...")
        enviar_telegram(formatear_mensaje(cantidad))
    elif nuevo_estado == "con_stock":
        print("ℹ️ Sigue disponible pero ya se notificó antes. Sin spam.")
    elif nuevo_estado == "sin_stock":
        print("😴 Sin existencias. Nada que hacer.")
    else:
        print(f"⚠️ Estado desconocido: {descripcion}")

    print("=" * 50)
    return 0


if __name__ == "__main__":
    exit(main())
