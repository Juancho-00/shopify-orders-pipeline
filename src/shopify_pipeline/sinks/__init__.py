"""
Escritura de archivos ("sinks" = destinos de los datos).

    jsonl.py    JSON Lines (un pedido por línea) para la zona cruda
    tabular.py  CSV (para sistemas) y Excel (para personas)

Ambos escriben de forma atómica: primero a un archivo temporal y al final lo renombran,
así nunca queda un archivo a medias si algo falla.
"""
