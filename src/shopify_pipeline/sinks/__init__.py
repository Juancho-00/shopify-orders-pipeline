"""
Destinos (sinks) de los datos extraídos.

Un sink recibe un iterable de registros y devuelve cuántos escribió. El extractor no
sabe a dónde van los datos: para cambiar de destino basta con agregar un sink nuevo.
"""

from shopify_pipeline.sinks.base import Sink
from shopify_pipeline.sinks.jsonl import JsonlSink, write_jsonl

__all__ = ["JsonlSink", "Sink", "write_jsonl"]
