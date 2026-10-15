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

# Enlaces directos al carrito para cada variación
URL_COMPRA_RECARGA = (
    "https://goniogas.com/checkout/?add-to-cart=108&variation_id=7551&quantity=1"
)
URL_COMPRA_COMPLETO = (
    "https://goniogas.com/checkout/?add-to-cart=108&variation_id=7552&quantity=1"
)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

GIST_ID = os.getenv("GIST_ID")
GIST_TOKEN = os.getenv("GIST_TOKEN")
GIST_FILENAME = "estado_monitor_gas.json"

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
        return {"disponibilidad": "desconocido", "variaciones": {},
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
        return {"disponibilidad": "desconocido", "variaciones": {},
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
                "disable_web_page_preview": True,
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
    session = requests.Session()
    session.headers.update(HEADERS)
    print(f"🌐 Petición 1 → {url}")
    try:
        r = session.get(url, timeout=30, allow_redirects=True)
    except Exception as e:
        print(f"❌ Error en petición 1: {e}")
        return None

    print(f"   Status: {r.status_code} | Tamaño: {len(r.text)} | Server: {r.headers.get('Server')}")

    if "document.cookie" in r.text and len(r.text) < 5000:
        print("🔐 Challenge de cookie detectado. Extrayendo cookie...")
        matches = re.findall(r"document\.cookie\s*=\s*['\"]([^'\"]+)['\"]", r.text)
        if not matches:
            print("❌ No se pudo extraer la cookie del challenge")
            return None
        for cookie_string in matches:
            partes = [p.strip() for p in cookie_string.split(";")]
            if not partes:
                continue
            nombre_valor = partes[0]
            if "=" not in nombre_valor:
                continue
            nombre, valor = nombre_valor.split("=", 1)
            print(f"🍪 Cookie extraída: {nombre.strip()}={valor.strip()}")
            session.cookies.set(nombre.strip(), valor.strip(), domain="goniogas.com", path="/")
        time.sleep(3)
        print(f"🌐 Petición 2 → {url} (con cookie)")
        try:
            r2 = session.get(url, timeout=30, allow_redirects=True)
        except Exception as e:
            print(f"❌ Error en petición 2: {e}")
            return None
        print(f"   Status: {r2.status_code} | Tamaño: {len(r2.text)} | Server: {r2.headers.get('Server')}")
        if "document.cookie" in r2.text and len(r2.text) < 5000:
            print("❌ Segundo challenge detectado. No se pudo resolver.")
            return None
        return r2.text

    return r.text


# ============================================================
# EXTRACCIÓN DEL JSON DE VARIACIONES
# ============================================================
def extraer_variaciones(html):
    """
    Extrae el JSON de data-product_variations que WooCommerce
    embebe en el HTML del producto. Devuelve una lista de dicts.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Buscar el form de variaciones
    form = soup.find("form", class_="variations_form")
    if not form:
        print("⚠️ No se encontró el form de variaciones")
        return []

    data_json = form.get("data-product_variations")
    if not data_json:
        print("⚠️ No se encontró data-product_variations")
        return []

    try:
        variaciones = json.loads(data_json)
        print(f"✅ Se encontraron {len(variaciones)} variaciones")
        return variaciones
    except json.JSONDecodeError as e:
        print(f"❌ Error parseando JSON de variaciones: {e}")
        return []


def analizar_variaciones(variaciones):
    """
    Analiza cada variación y devuelve un dict:
    {
      "Recarga": {"id": 7551, "precio": 42, "stock": True/False, "cantidad": N},
      "Cilindro completo": {"id": 7552, "precio": 70, "stock": True/False, "cantidad": N}
    }
    """
    resultado = {}
    for v in variaciones:
        attrs = v.get("attributes", {})
        nombre_variacion = attrs.get("attribute_tipo-de-compra", "Desconocida")
        var_id = v.get("variation_id")
        precio = v.get("display_price", 0)
        is_in_stock = v.get("is_in_stock", False)
        max_qty = v.get("max_qty")

        # Intentar extraer cantidad de disponibilidad del availability_html
        avail_html = v.get("availability_html", "")
        cantidad = None
        if avail_html:
            # Buscar patrones como "5 disponibles" o "5 in stock"
            match = re.search(r"(\d+)\s*(?:disponible|in stock|units?)", avail_html, re.IGNORECASE)
            if match:
                cantidad = int(match.group(1))
            elif "in-stock" in avail_html.lower():
                cantidad = None  # Disponible pero sin número

        resultado[nombre_variacion] = {
            "id": var_id,
            "precio": precio,
            "stock": bool(is_in_stock),
            "cantidad": cantidad,
            "max_qty": max_qty,
        }
        estado = "✅ CON STOCK" if is_in_stock else "❌ SIN STOCK"
        print(f"   - {nombre_variacion} (ID {var_id}, {precio}€): {estado}")

    return resultado


# ============================================================
# MENSAJES
# ============================================================
def construir_mensaje(variaciones_data):
    """
    Construye el mensaje de Telegram con las variaciones
    que tienen stock y sus enlaces de compra.
    """
    recarga = variaciones_data.get("Recarga", {})
    completo = variaciones_data.get("Cilindro completo", {})

    # Estados
    recarga_stock = recarga.get("stock", False)
    completo_stock = completo.get("stock", False)

    if not recarga_stock and not completo_stock:
        return None  # Sin stock, no enviar

    # Encabezado
    msg = "🚨 <b>¡CILINDROS DE GAS DISPONIBLES!</b> 🚨\n\n"
    msg += "<b>📦 Estado actual:</b>\n"

    # Recarga
    if recarga_stock:
        cant_txt = f" ({recarga['cantidad']} disp.)" if recarga.get("cantidad") else ""
        msg += f"✅ <b>Recarga</b> (42€){cant_txt}\n"
    else:
        msg += f"❌ <b>Recarga</b> (42€): Sin stock\n"

    # Cilindro completo
    if completo_stock:
        cant_txt = f" ({completo['cantidad']} disp.)" if completo.get("cantidad") else ""
        msg += f"✅ <b>Cilindro completo</b> (70€){cant_txt}\n"
    else:
        msg += f"❌ <b>Cilindro completo</b> (70€): Sin stock\n"

    msg += "\n"

    # Enlaces de compra (solo si hay stock)
    if recarga_stock:
        msg += (
            "🛒 <b>COMPRAR RECARGA (42€):</b>\n"
            f'<a href="{URL_COMPRA_RECARGA}">➡️ Añadir Recarga al carrito</a>\n\n'
        )

    if completo_stock:
        msg += (
            "🛒 <b>COMPRAR CILINDRO COMPLETO (70€):</b>\n"
            f'<a href="{URL_COMPRA_COMPLETO}">➡️ Añadir Cilindro completo al carrito</a>\n\n'
        )

    msg += "📍 <b>Punto:</b> La Coronela – Calle 222 e/23 y 25 – La Lisa\n"
    msg += "💰 <b>Precio:</b> 42€ (Recarga) / 70€ (Cilindro completo)\n"
    msg += "⏰ ¡Corre, que vuelan!"

    return msg


# ============================================================
# MAIN
# ============================================================
def main():
    print("=" * 60)
    print("🔍 MONITOR DE DISPONIBILIDAD - GONIO GAS (v2 VARIACIONES)")
    print(f"🕐 {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}")
    print("=" * 60)

    # 1. Leer estado anterior
    estado_anterior = leer_estado_gist()
    variaciones_previas = estado_anterior.get("variaciones", {})
    print(f"📊 Estado anterior: {variaciones_previas}")

    # 2. Descargar HTML
    html = descargar_html_real(URL_PRODUCTO)
    if not html:
        print("❌ No se pudo descargar el HTML")
        return 1

    # 3. Extraer y analizar variaciones
    variaciones = extraer_variaciones(html)
    if not variaciones:
        # Fallback: comprobar el <p class="stock"> general
        soup = BeautifulSoup(html, "html.parser")
        stock_el = soup.find("p", class_="stock")
        if stock_el:
            texto = stock_el.get_text(" ", strip=True)
            clases = " ".join(stock_el.get("class", []))
            print(f"⚠️ Fallback: texto de stock general = '{texto}' | clases='{clases}'")
        return 1

    data_actual = analizar_variaciones(variaciones)

    # 4. Determinar si hay stock de alguna
    recarga_stock = data_actual.get("Recarga", {}).get("stock", False)
    completo_stock = data_actual.get("Cilindro completo", {}).get("stock", False)
    hay_stock = recarga_stock or completo_stock

    # 5. Leer estados anteriores
    recarga_previo = variaciones_previas.get("Recarga", {}).get("stock", False)
    completo_previo = variaciones_previas.get("Cilindro completo", {}).get("stock", False)

    ahora = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())

    # 6. Decidir si notificar
    notificar = False
    motivo = ""

    if hay_stock:
        # ¿Cambió alguno de sin_stock a con_stock?
        if (recarga_stock and not recarga_previo) or (completo_stock and not completo_previo):
            notificar = True
            motivo = "¡Cambio a disponible!"
        else:
            # Recordatorio cada 10 min
            ultima = estado_anterior.get("ultima_notificacion")
            if ultima:
                try:
                    t_ultima = datetime.strptime(ultima, "%Y-%m-%d %H:%M:%S UTC").replace(tzinfo=timezone.utc)
                    minutos = (datetime.now(timezone.utc) - t_ultima).total_seconds() / 60
                    if minutos >= 10:
                        notificar = True
                        motivo = f"Recordatorio ({int(minutos)} min)"
                except Exception:
                    notificar = True
                    motivo = "Re-notificando"
            else:
                notificar = True
                motivo = "Primera detección con stock"

    # 7. Guardar estado
    estado_nuevo = {
        "disponibilidad": "con_stock" if hay_stock else "sin_stock",
        "variaciones": {
            "Recarga": data_actual.get("Recarga", {}),
            "Cilindro completo": data_actual.get("Cilindro completo", {}),
        },
        "ultima_verificacion": ahora,
        "ultima_notificacion": ahora if notificar else estado_anterior.get("ultima_notificacion"),
    }
    guardar_estado_gist(estado_nuevo)

    # 8. Enviar Telegram
    if notificar:
        mensaje = construir_mensaje(data_actual)
        if mensaje:
            print(f"🎉 {motivo} → Enviando a Telegram...")
            enviar_telegram(mensaje)
        else:
            print("⚠️ Se detectó stock pero no se pudo construir el mensaje")
    elif hay_stock:
        print("ℹ️ Sigue disponible. Ya se notificó hace <10 min.")
    else:
        print("😴 Sin existencias en ninguna variación. Nada que hacer.")

    print("=" * 60)
    return 0


if __name__ == "__main__":
    exit(main())
