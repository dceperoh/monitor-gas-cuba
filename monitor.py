import os
import re
import json
import time
from datetime import datetime, timezone

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

# Palabras clave
PALABRAS_SIN_STOCK = ["esto_no_existe_jamas"]
PALABRAS_CON_STOCK = ["disponible", "añadir al carrito", "añadir a la cesta", "in stock"]

# Headers de navegador real
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/121.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
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
# SCRAPING CON RESOLUCIÓN DE CHALLENGE
# ============================================================
def descargar_html_real(url):
    """
    Hace una petición, detecta si hay un challenge de cookie JS,
    extrae la cookie y vuelve a pedir con ella.
    Devuelve el HTML real o None.
    """
    session = requests.Session()
    session.headers.update(HEADERS)

    print(f"🌐 Petición 1 → {url}")
    try:
        r = session.get(url, timeout=30, allow_redirects=True)
    except Exception as e:
        print(f"❌ Error en petición 1: {e}")
        return None

    print(f"   Status: {r.status_code} | Tamaño: {len(r.text)} | Server: {r.headers.get('Server')}")

    # ¿Es un challenge de cookie?
    if "document.cookie" in r.text and len(r.text) < 5000:
        print("🔐 Challenge de cookie detectado. Extrayendo cookie...")

        # Buscar: document.cookie = 'nombre=valor; ...'
        matches = re.findall(
            r"document\.cookie\s*=\s*['\"]([^'\"]+)['\"]",
            r.text
        )
        if not matches:
            print("❌ No se pudo extraer la cookie del challenge")
            return None

        for cookie_string in matches:
            # cookie_string ejemplo: "dhd2=39e416...; max-age=86400; path=/; domain=goniogas.com"
            partes = [p.strip() for p in cookie_string.split(";")]
            if not partes:
                continue
            nombre_valor = partes[0]
            if "=" not in nombre_valor:
                continue
            nombre, valor = nombre_valor.split("=", 1)
            nombre = nombre.strip()
            valor = valor.strip()
            print(f"🍪 Cookie extraída: {nombre}={valor}")

            # Asignar la cookie al dominio correcto
            session.cookies.set(nombre, valor, domain="goniogas.com", path="/")

        # Esperar un poco como haría un navegador
        time.sleep(3)

        print(f"🌐 Petición 2 → {url} (con cookie)")
        try:
            r2 = session.get(url, timeout=30, allow_redirects=True)
        except Exception as e:
            print(f"❌ Error en petición 2: {e}")
            return None

        print(f"   Status: {r2.status_code} | Tamaño: {len(r2.text)} | Server: {r2.headers.get('Server')}")

        # ¿Sigue siendo challenge?
        if "document.cookie" in r2.text and len(r2.text) < 5000:
            print("❌ Segundo challenge detectado. No se pudo resolver.")
            return None

        return r2.text

    # No era challenge, devolvemos lo que tenemos
    return r.text


def verificar_disponibilidad():
    """Devuelve (estado, descripcion, cantidad)."""
    html = descargar_html_real(URL_PRODUCTO)
    if not html:
        return "error", "No se pudo descargar HTML", None

    soup = BeautifulSoup(html, "html.parser")

    # ----- ESTRATEGIA 1: <p class="stock ..."> -----
    stock_el = soup.find("p", class_="stock") or soup.find(class_="stock")

    if stock_el:
        texto_stock = stock_el.get_text(" ", strip=True)
        clases = " ".join(stock_el.get("class", []))
        print(f"🎯 <p class='stock'> encontrado:")
        print(f"   Texto: '{texto_stock}'")
        print(f"   Clases: '{clases}'")

        if "out-of-stock" in clases:
            return "sin_stock", "Sin existencias", 0
        if "in-stock" in clases:
            numeros = re.findall(r"\d+", texto_stock)
            cantidad = int(numeros[0]) if numeros else None
            return "con_stock", texto_stock, cantidad

    # ----- ESTRATEGIA 2: por texto en el bloque stock -----
    if stock_el:
        texto_lower = stock_el.get_text(" ", strip=True).lower()
        for p in PALABRAS_SIN_STOCK:
            if p in texto_lower:
                return "sin_stock", "Sin existencias", 0
        m = re.search(r"(\d+)\s*disponible", texto_lower)
        if m:
            return "con_stock", texto_lower, int(m.group(1))

    # ----- ESTRATEGIA 3: por regex en el HTML -----
    m = re.search(
        r'<p[^>]*class="[^"]*stock[^"]*out-of-stock[^"]*"[^>]*>([^<]*)</p>',
        html, re.IGNORECASE
    )
    if m:
        return "sin_stock", m.group(1).strip(), 0

    m = re.search(
        r'<p[^>]*class="[^"]*stock[^"]*in-stock[^"]*"[^>]*>([^<]*)</p>',
        html, re.IGNORECASE
    )
    if m:
        texto = m.group(1).strip()
        nums = re.findall(r"\d+", texto)
        cantidad = int(nums[0]) if nums else None
        return "con_stock", texto, cantidad

    # ----- ESTRATEGIA 4: texto global -----
    texto_plano = soup.get_text(" ", strip=True).lower()
    if "sin existencias" in texto_plano:
        return "sin_stock", "Sin existencias (texto global)", 0

    m = re.search(r"(\d+)\s*disponibles?", texto_plano)
    if m:
        return "con_stock", f"{m.group(1)} disponibles", int(m.group(1))

    if "añadir al carrito" in texto_plano or "añadir a la cesta" in texto_plano:
        return "con_stock", "Botón de compra presente", None

    # Diagnóstico: guardar HTML para inspección
    with open("debug_html.html", "w", encoding="utf-8") as f:
        f.write(html)
    print("💾 HTML guardado en debug_html.html para inspección")

    return "desconocido", "No se pudo determinar el estado", None


# ============================================================
# MENSAJE
# ============================================================
def formatear_mensaje(cantidad, descripcion):
    if cantidad and cantidad > 0:
        cantidad_txt = f"<b>{cantidad}</b> cilindro(s)"
    elif cantidad == 0:
        cantidad_txt = "<b>0</b>"
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

    # Notificar si hay stock (cambio o recordatorio cada 30 min)
    notificar = False
    motivo = ""

    if nuevo_estado == "con_stock":
        if estado_previo != "con_stock":
            notificar = True
            motivo = "¡Cambio a disponible!"
        else:
            ultima = estado_anterior.get("ultima_notificacion")
            if ultima:
                try:
                    t_ultima = datetime.strptime(ultima, "%Y-%m-%d %H:%M:%S UTC").replace(tzinfo=timezone.utc)
                    t_ahora = datetime.now(timezone.utc)
                    minutos = (t_ahora - t_ultima).total_seconds() / 60
                    if minutos >= 30:
                        notificar = True
                        motivo = f"Recordatorio: sigue disponible ({int(minutos)} min)"
                except Exception:
                    notificar = True
                    motivo = "Re-notificando"
            else:
                notificar = True
                motivo = "Primera detección con stock"

    estado_nuevo = {
        "disponibilidad": nuevo_estado,
        "cantidad": cantidad,
        "descripcion": descripcion,
        "ultima_verificacion": ahora,
        "ultima_notificacion": ahora if notificar else estado_anterior.get("ultima_notificacion"),
    }
    guardar_estado_gist(estado_nuevo)

    if notificar:
        print(f"🎉 {motivo} → Enviando a Telegram...")
        enviar_telegram(formatear_mensaje(cantidad, descripcion))
    elif nuevo_estado == "sin_stock":
        print("😴 Sin existencias. Nada que hacer.")
    elif nuevo_estado == "con_stock":
        print("ℹ️ Sigue disponible. Ya se notificó hace <30 min.")
    else:
        print(f"⚠️ Estado desconocido: {descripcion}")

    print("=" * 60)
    return 0


if __name__ == "__main__":
    exit(main())
