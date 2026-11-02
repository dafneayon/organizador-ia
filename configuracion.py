"""Carga la configuración: config.json y, encima, config.local.json si existe.

config.json trae los valores por defecto y se sube al repositorio.
config.local.json es opcional, solo vive en tu Mac (.gitignore) y sirve para tus
ajustes personales, por ejemplo carpetas propias que el organizador no debe tocar.
Las claves de config.local.json reemplazan a las de config.json; los objetos
anidados (como "clasificador") se combinan clave por clave.
"""
import json
from pathlib import Path


def fusionar(base: dict, encima: dict) -> dict:
    for k, v in encima.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            fusionar(base[k], v)
        else:
            base[k] = v
    return base


def cargar(carpeta: Path) -> dict:
    carpeta = Path(carpeta)
    config = json.loads((carpeta / "config.json").read_text(encoding="utf-8"))
    local = carpeta / "config.local.json"
    if local.exists():
        fusionar(config, json.loads(local.read_text(encoding="utf-8")))
    return config
