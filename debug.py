import requests
from bs4 import BeautifulSoup

URL = "https://goniogas.com/producto/cilindro-de-gas-de-10kg/"

headers = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
}

r = requests.get(URL, headers=headers, timeout=30)
print(f"Status code: {r.status_code}")
print(f"Content-Length: {len(r.text)}")
print(f"Content-Type: {r.headers.get('Content-Type')}")
print(f"Server: {r.headers.get('Server')}")
print(f"CF-Ray: {r.headers.get('CF-Ray')}")
print("=" * 60)

soup = BeautifulSoup(r.text, "html.parser")

# Buscar la clase "stock"
stock = soup.find(class_="stock")
print(f"Elemento con class='stock': {stock}")
if stock:
    print(f"Texto dentro: '{stock.get_text(strip=True)}'")
    print(f"Clases: {stock.get('class')}")

# Buscar variaciones
print("=" * 60)
print("Buscando 'out-of-stock' en HTML:")
print("out-of-stock" in r.text)
print("Buscando 'in-stock' en HTML:")
print("in-stock" in r.text)
print("Buscando 'Sin existencias':")
print("Sin existencias" in r.text)
print("Buscando 'Disponible':")
print("Disponible" in r.text)

print("=" * 60)
print("Primeros 2000 caracteres del HTML:")
print(r.text[:2000])
