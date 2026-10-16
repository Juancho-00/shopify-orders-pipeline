"""
Escritura de archivos ("sinks" = destinos de los datos).

    atomic.py   Escritura atómica compartida (temporal + renombrar) y JSON atómico
    jsonl.py    JSON Lines (un pedido por línea) para la zona cruda
    tabular.py  CSV (para sistemas) y Excel (para personas)

Todo se escribe de forma atómica: primero a un archivo temporal y al final se renombra,
así nunca queda un archivo a medias si algo falla.
"""
