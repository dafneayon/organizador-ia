#!/usr/bin/env python3
"""Servidor MCP del Organizador IA: Claude Desktop (o Claude Code) pregunta por tus documentos.

Implementa el Model Context Protocol sobre stdio (JSON-RPC 2.0, un mensaje por línea)
sin dependencias, porque el SDK oficial pide Python 3.10+ y macOS trae 3.9.

Herramientas (todas de solo lectura):
- buscar_documentos: búsqueda híbrida (palabras clave + significado) en el índice.
- leer_documento: texto indexado de UN documento que está en el índice (nada más del disco).
- estado_indice: cuántos documentos hay y de qué categorías.

Configuración en Claude Desktop (claude_desktop_config.json):
    "mcpServers": {"organizador": {"command": "<carpeta>/.venv/bin/python",
                                   "args": ["<carpeta>/mcp_servidor.py"]}}
"""
import json
import sys
import traceback
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))
import busqueda  # noqa: E402

VERSION_PROTOCOLO = "2025-06-18"
VERSIONES = {"2024-11-05", "2025-03-26", "2025-06-18"}

HERRAMIENTAS = [
    {
        "name": "buscar_documentos",
        "description": (
            "Busca en los documentos personales organizados del usuario (PDF, Word, facturas CFDI, "
            "tesis, papers, certificados...). Combina palabras clave y significado, en español o inglés. "
            "Devuelve los documentos más relevantes con su ruta, carpeta y un fragmento. "
            "Úsala antes de responder cualquier pregunta sobre los archivos del usuario. "
            "Si no aparece lo que buscas, reformula: usa sinónimos, nombres propios o el otro idioma "
            "(muchos documentos académicos están en inglés)."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "consulta": {"type": "string", "description": "Pregunta o palabras a buscar"},
                "k": {"type": "integer", "minimum": 1, "maximum": 10, "default": 5,
                      "description": "Número de documentos"},
                "categoria": {"type": "string",
                              "description": "Opcional: limitar a una carpeta, p. ej. 'Finanzas' o 'Academico/Tesis'"},
            },
            "required": ["consulta"],
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "leer_documento",
        "description": "Texto completo (hasta un límite) de un documento devuelto por buscar_documentos.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ruta": {"type": "string", "description": "Ruta exacta tal como la dio buscar_documentos"},
                "max_caracteres": {"type": "integer", "minimum": 200, "maximum": 20000, "default": 6000},
            },
            "required": ["ruta"],
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "estado_indice",
        "description": "Cuántos documentos hay indexados y en qué categorías.",
        "inputSchema": {"type": "object", "properties": {}},
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
]

_buscador = None


def buscador():
    global _buscador
    if _buscador is None:
        _buscador = busqueda.Buscador()
    return _buscador


def texto(t, error=False):
    return {"content": [{"type": "text", "text": t}], "isError": error}


def llamar(nombre, args):
    if nombre == "buscar_documentos":
        consulta = str(args.get("consulta", "")).strip()
        if not consulta:
            return texto("Falta 'consulta'.", True)
        k = max(1, min(10, int(args.get("k", 5))))
        res = buscador().buscar(consulta, k, categoria=args.get("categoria") or None)
        if not res:
            return texto("Sin resultados. Puede que el índice esté vacío: el usuario debe correr 'organizador indexar'.")
        return texto(json.dumps(res, ensure_ascii=False, indent=1))
    if nombre == "leer_documento":
        doc = buscador().documento(str(args.get("ruta", "")),
                                   max(200, min(20000, int(args.get("max_caracteres", 6000)))))
        if doc is None:
            return texto("Ese documento no está en el índice. Solo se pueden leer rutas devueltas por buscar_documentos.", True)
        return texto(json.dumps(doc, ensure_ascii=False))
    if nombre == "estado_indice":
        return texto(json.dumps(buscador().estado(), ensure_ascii=False))
    return None


def responder(msg):
    """Respuesta JSON-RPC para un mensaje, o None si es una notificación."""
    metodo, mid, params = msg.get("method"), msg.get("id"), msg.get("params") or {}
    if mid is None:
        return None  # notificaciones (p. ej. notifications/initialized): no llevan respuesta
    if metodo == "initialize":
        pedida = params.get("protocolVersion")
        resultado = {"protocolVersion": pedida if pedida in VERSIONES else VERSION_PROTOCOLO,
                     "capabilities": {"tools": {}},
                     "serverInfo": {"name": "organizador-ia", "version": "0.3.0"},
                     "instructions": "Documentos personales del usuario, organizados por el Organizador IA. "
                                     "Busca primero con buscar_documentos y cita la ruta de cada documento que uses."}
    elif metodo == "ping":
        resultado = {}
    elif metodo == "tools/list":
        resultado = {"tools": HERRAMIENTAS}
    elif metodo == "tools/call":
        try:
            resultado = llamar(params.get("name"), params.get("arguments") or {})
        except Exception as e:
            traceback.print_exc(file=sys.stderr)
            resultado = texto(f"Error interno: {e}", True)
        if resultado is None:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": f"Herramienta desconocida: {params.get('name')}"}}
    else:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"Método no soportado: {metodo}"}}
    return {"jsonrpc": "2.0", "id": mid, "result": resultado}


def main():
    for linea in sys.stdin:
        linea = linea.strip()
        if not linea:
            continue
        try:
            msg = json.loads(linea)
        except ValueError:
            r = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "JSON no válido"}}
        else:
            r = responder(msg)
        if r is not None:
            sys.stdout.write(json.dumps(r, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
