"""Pruebas del extractor de texto, el índice de búsqueda y el servidor MCP.

Corren con el Python del sistema (sin fastembed), así que la búsqueda usa solo
palabras clave: es el modo que existe en cualquier Mac. La parte de embeddings
se mide con evals/evaluar_busqueda.py.
"""
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

from test_herramienta import RAIZ, Entorno

sys.path.insert(0, str(RAIZ))
import extraer  # noqa: E402


class TestExtraer(Entorno):
    def office(self, nombre, partes):
        p = self.tmp / nombre
        with zipfile.ZipFile(p, "w") as z:
            for ruta, xml in partes.items():
                z.writestr(ruta, xml)
        return p

    def test_docx(self):
        p = self.office("a.docx", {"word/document.xml": "<w:p><w:t>Contrato</w:t></w:p><w:p><w:t>de renta</w:t></w:p>"})
        self.assertEqual(extraer.extraer(p, 1000), "Contrato de renta")

    def test_pptx_en_orden_de_diapositiva(self):
        p = self.office("a.pptx", {"ppt/slides/slide10.xml": "<a:t>diez</a:t>",
                                   "ppt/slides/slide2.xml": "<a:t>dos</a:t>",
                                   "ppt/slides/_rels/slide2.xml.rels": "<x>no</x>"})
        self.assertEqual(extraer.extraer(p, 1000), "dos diez")

    def test_cfdi_saca_los_atributos(self):
        p = RAIZ / "evals" / "corpus" / "Finanzas" / "Facturas" / "factura_cfdi_farmacia.xml"
        t = extraer.extraer(p, 2000)
        for dato in ("Factura electrónica CFDI", "Total: 360.00", "FARMACIAS GUADALAJARA", "amoxicilina", "UUID"):
            self.assertIn(dato, t)

    def test_nunca_lee_sensibles(self):
        for ext in (".key", ".cer", ".pem"):
            p = self.archivo(self.tmp / ("efirma" + ext), "SECRETO")
            self.assertEqual(extraer.extraer(p, 100), "")


class EntornoIndice(Entorno):
    def setUp(self):
        super().setUp()
        self.archivo(self.dest / "Finanzas/Facturas/recibo_luz.txt",
                     "Comisión Federal de Electricidad. Total a pagar $612.00 MXN.")
        self.archivo(self.dest / "Academico/Tesis/metodologia.md", "Modelos de mezcla gaussiana con BIC.")
        # Nada de esto se debe indexar:
        self.archivo(self.dest / "Personal e Identidad/Claves y certificados/notas.txt", "clave secreta electricidad")
        self.archivo(self.dest / "Personal e Identidad/efirma.key", "llave privada")
        self.archivo(self.dest / self.config["carpeta_revisar"] / "copia_recibo.txt", "Electricidad copia")
        (self.dest / "Proyectos/repo/.git").mkdir(parents=True)
        self.archivo(self.dest / "Proyectos/repo/README.md", "electricidad dentro de un proyecto")
        self.archivo(self.dest / "Datos y Codigo/datos.csv", "electricidad,1,2")

    def busqueda(self, *args):
        env = {"HOME": str(self.home), "PATH": os.environ.get("PATH", "/usr/bin:/bin")}
        return subprocess.run(["/usr/bin/python3", "-I", str(self.app / "busqueda.py"), *args],
                              capture_output=True, text=True, env=env, timeout=120)

    def buscar(self, consulta):
        r = self.busqueda("buscar", consulta, "--json", "--modo", "bm25")
        self.assertEqual(r.returncode, 0, r.stderr)
        return [x["nombre"] for x in json.loads(r.stdout)] if r.stdout.strip().startswith("[") else []


class TestIndice(EntornoIndice):
    def test_indexa_solo_lo_permitido(self):
        r = self.busqueda("indexar")
        self.assertEqual(r.returncode, 0, r.stderr)
        estado = json.loads(self.busqueda("estado").stdout)
        self.assertEqual(estado["documentos"], 2)
        self.assertEqual(self.buscar("electricidad"), ["recibo_luz.txt"])

    def test_ignora_acentos_y_mayusculas(self):
        self.busqueda("indexar")
        self.assertEqual(self.buscar("COMISION electrica federal")[:1], ["recibo_luz.txt"])
        self.assertEqual(self.buscar("gaussiana"), ["metodologia.md"])

    def test_tambien_busca_por_nombre_y_carpeta(self):
        self.busqueda("indexar")
        self.assertEqual(self.buscar("recibo luz")[:1], ["recibo_luz.txt"])
        self.assertEqual(self.buscar("tesis")[:1], ["metodologia.md"])

    def test_es_incremental_y_quita_lo_borrado(self):
        self.busqueda("indexar")
        self.assertIn("0 documento(s) nuevos", self.busqueda("indexar").stderr)
        self.archivo(self.dest / "Academico/Tesis/metodologia.md", "Ahora habla de k-means.")
        self.assertIn("1 documento(s) nuevos", self.busqueda("indexar").stderr)
        self.assertEqual(self.buscar("gaussiana"), [])
        (self.dest / "Finanzas/Facturas/recibo_luz.txt").unlink()
        self.assertIn("1 quitados", self.busqueda("indexar").stderr)
        self.assertEqual(self.buscar("electricidad"), [])

    def test_sin_resultados_no_falla(self):
        self.busqueda("indexar")
        self.assertEqual(self.buscar("xilofono"), [])
        self.assertEqual(self.buscar("de la el"), [])  # solo palabras vacías


class TestMCP(EntornoIndice):
    def conversar(self, mensajes):
        env = {"HOME": str(self.home), "PATH": os.environ.get("PATH", "/usr/bin:/bin")}
        entrada = "\n".join(m if isinstance(m, str) else json.dumps(m) for m in mensajes) + "\n"
        r = subprocess.run(["/usr/bin/python3", "-I", str(self.app / "mcp_servidor.py")],
                           input=entrada, capture_output=True, text=True, env=env, timeout=120)
        return [json.loads(l) for l in r.stdout.splitlines() if l.strip()]

    def llamar(self, i, nombre, args):
        return {"jsonrpc": "2.0", "id": i, "method": "tools/call", "params": {"name": nombre, "arguments": args}}

    def test_flujo_completo(self):
        self.busqueda("indexar")
        ruta = str(self.dest / "Finanzas/Facturas/recibo_luz.txt")
        r = self.conversar([
            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "prueba"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            self.llamar(3, "buscar_documentos", {"consulta": "electricidad"}),
            self.llamar(4, "leer_documento", {"ruta": ruta}),
            self.llamar(5, "estado_indice", {}),
        ])
        self.assertEqual([m["id"] for m in r], [1, 2, 3, 4, 5], "las notificaciones no llevan respuesta")
        self.assertEqual(r[0]["result"]["protocolVersion"], "2025-06-18")
        self.assertIn("tools", r[0]["result"]["capabilities"])
        herramientas = {t["name"] for t in r[1]["result"]["tools"]}
        self.assertEqual(herramientas, {"buscar_documentos", "leer_documento", "estado_indice"})
        resultados = json.loads(r[2]["result"]["content"][0]["text"])
        self.assertEqual(resultados[0]["ruta"], ruta)
        self.assertIn("$612.00", json.loads(r[3]["result"]["content"][0]["text"])["texto"])
        self.assertEqual(json.loads(r[4]["result"]["content"][0]["text"])["documentos"], 2)

    def test_solo_lee_documentos_del_indice(self):
        self.busqueda("indexar")
        secreto = str(self.dest / "Personal e Identidad/Claves y certificados/notas.txt")
        for ruta in (secreto, "/etc/passwd", str(self.app / "config.json")):
            r = self.conversar([self.llamar(1, "leer_documento", {"ruta": ruta})])
            self.assertTrue(r[0]["result"]["isError"], ruta)
            self.assertNotIn("clave secreta", r[0]["result"]["content"][0]["text"])

    def test_errores_de_protocolo(self):
        r = self.conversar(["{no es json", {"jsonrpc": "2.0", "id": 7, "method": "resources/list"},
                            self.llamar(8, "borrar_todo", {}),
                            self.llamar(9, "buscar_documentos", {"consulta": ""})])
        self.assertEqual(r[0]["error"]["code"], -32700)
        self.assertEqual(r[1]["error"]["code"], -32601)
        self.assertEqual(r[2]["error"]["code"], -32602)
        self.assertTrue(r[3]["result"]["isError"])

    def test_indice_vacio_responde_con_ayuda(self):
        r = self.conversar([self.llamar(1, "buscar_documentos", {"consulta": "luz"})])
        self.assertIn("organizador indexar", r[0]["result"]["content"][0]["text"])
