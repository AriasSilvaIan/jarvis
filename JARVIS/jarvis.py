 
import sqlite3
import time
import hashlib
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
import threading
import queue

from datetime import datetime, timezone
from urllib.parse import urlparse

# CONFIGURACION
DB = "jarvis_memory.db"
INTERVAL = 3600  # Una hora
MAX_ITEMS_PER_FEED = 15
MAX_RESPONSE_BYTES = 1_000_000

FEEDS = [
    "https://blog.python.org/feeds/posts/default?alt=rss",
]

commands = queue.Queue()
stop_event = threading.Event()


def connect_db():
    db = sqlite3.connect(DB)
    db.execute("""
        CREATE TABLE IF NOT EXISTS knowledge (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            summary TEXT,
            url TEXT NOT NULL,
            source TEXT NOT NULL,
            discovered_at TEXT NOT NULL
        )
    """)
    db.commit()
    return db


def valid_feed_url(url):
    parsed = urlparse(url)
    return parsed.scheme == "https" and bool(parsed.hostname)


def fetch_feed(url):
    if not valid_feed_url(url):
        print("JARVIS: Fuente rechazada.")
        return []

    request = urllib.request.Request(
        url,
        headers={"User-Agent": "JARVIS-Research/0.2"}
    )

    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            data = response.read(MAX_RESPONSE_BYTES + 1)

        if len(data) > MAX_RESPONSE_BYTES:
            print("JARVIS: Fuente demasiado grande.")
            return []

        root = ET.fromstring(data)
        items = []

        for entry in root.findall(".//item")[:MAX_ITEMS_PER_FEED]:
            title = entry.findtext("title", default="Sin titulo")
            summary = entry.findtext("description", default="")
            link = entry.findtext("link", default="")
            items.append((title, summary, link))

        atom_ns = "{http://www.w3.org/2005/Atom}"

        if not items:
            for entry in root.findall(f".//{atom_ns}entry"):
                title = entry.findtext(
                    f"{atom_ns}title", default="Sin titulo"
                )
                summary = entry.findtext(
                    f"{atom_ns}summary", default=""
                )
                link_node = entry.find(f"{atom_ns}link")
                link = (
                    link_node.get("href", "")
                    if link_node is not None else ""
                )
                items.append((title, summary, link))

                if len(items) >= MAX_ITEMS_PER_FEED:
                    break

        return [
            (title.strip(), summary[:2000], link)
            for title, summary, link in items
            if title.strip() and valid_feed_url(link)
        ]

    except (
        urllib.error.URLError,
        TimeoutError,
        ET.ParseError,
        OSError,
        ValueError
    ) as error:
        print(f"JARVIS: Error al consultar fuente: {error}")
        return []


def research_once(db):
    print("\nJARVIS: Iniciando investigacion...")
    saved = 0

    for feed_url in FEEDS:
        if stop_event.is_set():
            break

        entries = fetch_feed(feed_url)

        for title, summary, link in entries:
            item_id = hashlib.sha256(
                link.encode("utf-8")
            ).hexdigest()

            cursor = db.execute("""
                INSERT OR IGNORE INTO knowledge
                (id, title, summary, url, source, discovered_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                item_id,
                title,
                summary,
                link,
                urlparse(feed_url).hostname,
                datetime.now(timezone.utc).isoformat()
            ))

            if cursor.rowcount:
                saved += 1
                print(f"JARVIS: Nuevo conocimiento: {title}")

    db.commit()
    print(f"JARVIS: Investigacion terminada. Nuevos registros: {saved}")


def research_worker():
    # La conexion SQLite pertenece a este hilo.
    db = connect_db()

    try:
        while not stop_event.is_set():
            research_once(db)

            # Espera una hora, pero puede interrumpirse al cerrar.
            if stop_event.wait(INTERVAL):
                break
    finally:
        db.close()


def show_knowledge():
    # Conexion propia para el hilo principal.
    db = connect_db()

    try:
        rows = db.execute("""
            SELECT title, url, discovered_at
            FROM knowledge
            ORDER BY discovered_at DESC
            LIMIT 10
        """).fetchall()

        if not rows:
            print("JARVIS: Todavia no hay conocimientos guardados.")
            return

        for title, url, date in rows:
            print(f"\n- {title}\n  {url}\n  Guardado: {date}")
    finally:
        db.close()


def listen_commands():
    while not stop_event.is_set():
        try:
            command = input(
                "\nJARVIS | investigar / memoria / salir: "
            ).strip().lower()
            commands.put(command)

            if command == "salir":
                break

        except (EOFError, KeyboardInterrupt):
            commands.put("salir")
            break


def main():
    connect_db().close()

    print("JARVIS 0.2 - Sistema autonomo iniciado.")
    print("JARVIS: Investigare al arrancar y cada hora.")
    print("JARVIS: Puedes consultar la memoria mientras trabajo.")

    worker = threading.Thread(
        target=research_worker,
        name="JARVIS-Research",
        daemon=True
    )
    worker.start()

    listener = threading.Thread(
        target=listen_commands,
        name="JARVIS-Commands",
        daemon=True
    )
    listener.start()

    try:
        while not stop_event.is_set():
            try:
                command = commands.get(timeout=0.5)
            except queue.Empty:
                continue

            if command == "salir":
                print("JARVIS: Cerrando sistemas...")
                stop_event.set()

            elif command == "memoria":
                show_knowledge()

            elif command == "investigar":
                print(
                    "JARVIS: La investigacion automatica ya esta activa. "
                    "No iniciare otra para evitar consultas simultaneas."
                )

            elif command:
                print("JARVIS: Comando desconocido.")

    finally:
        stop_event.set()
        worker.join(timeout=20)
        print("JARVIS: Sesion finalizada.")


if __name__ == "__main__":
    main()
