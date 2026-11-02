"""Pruebas del clasificador local, el catálogo SQLite y la orden 'auto'.

Usan el mismo HOME falso que test_herramienta.py. La prueba de entrenamiento
necesita scikit-learn (en .venv o en el Python que corre las pruebas) y se
salta si no está.
"""
import json
import os
import sqlite3
import subprocess
import sys
import unittest
from pathlib import Path

from test_herramienta import RAIZ, Entorno

sys.path.insert(0, str(RAIZ))
from rasgos import Modelo, grupo, rasgos  # noqa: E402


def python_con_sklearn():
    for py in (RAIZ / ".venv" / "bin" / "python", Path(sys.executable)):
        if py.exists() and subprocess.run([str(py), "-c", "import sklearn"], capture_output=True).returncode == 0:
            return str(py)
    return None


class TestRasgos(unittest.TestCase):
    def test_reconoce_patrones(self):
        self.assertIn("patron:captura", rasgos("Captura de pantalla 2026-10-12 a la(s) 5.15.18 p. m..png"))
        self.assertIn("patron:rfc", rasgos("Acuse.XAXX010101000.38.2026.pdf"))
        self.assertIn("patron:uuid", rasgos("12345678-ABCD-4EF0-9ABC-1234567890AB.pdf"))
        self.assertIn("ext:pdf", rasgos("factura.PDF"))
        self.assertIn("dir", rasgos("Proyecto.v2", es_dir=True))

    def test_ignora_acentos_mayusculas_y_digitos(self):
        self.assertEqual(rasgos("Análisis_2026.pdf"), rasgos("analisis_1999.pdf"))

    def test_agrupa_versiones_del_mismo_archivo(self):
        self.assertEqual(grupo("cv.pdf"), grupo("cv (1).pdf"))
        self.assertEqual(grupo("tesis_v2.docx"), grupo("Tesis final.docx"))
        self.assertNotEqual(grupo("cv.pdf"), grupo("cv.docx"))


class TestModelo(unittest.TestCase):
    def test_suma_pesos_y_softmax(self):
        m = Modelo({"clases": ["A", "B"], "sesgo": [0.0, 0.0], "umbral": 0.8,
                    "pesos": {"ext:pdf": [2.0, -2.0], "ext:png": [-2.0, 2.0]}})
        clase, p = m.predecir("x.pdf")
        self.assertEqual(clase, "A")
        self.assertAlmostEqual(p, 1 / (1 + pow(2.718281828459045, -4)), places=6)
        self.assertAlmostEqual(sum(m.probabilidades(rasgos("x.png"))), 1.0)
        self.assertEqual(m.predecir("x.png")[0], "B")

    def test_modelo_corrupto_no_rompe(self):
        self.assertIsNone(Modelo.cargar(Path("/no/existe.json")))


class EntornoModelo(Entorno):
    def poner_modelo(self, umbral=0.8):
        """Modelo de juguete: los .png van a Capturas de pantalla, los .pdf a Finanzas/Facturas."""
        datos = {"clases": ["Capturas de pantalla", "Finanzas/Facturas"], "sesgo": [0.0, 0.0],
                 "umbral": umbral, "pesos": {"ext:png": [3.0, -3.0], "ext:pdf": [-3.0, 3.0]}}
        (self.app / "registro_local").mkdir(exist_ok=True)
        (self.app / "registro_local" / "modelo.json").write_text(json.dumps(datos))


class TestAuto(EntornoModelo):
    def test_listar_muestra_sugerencias(self):
        self.poner_modelo()
        self.archivo(self.desc / "foto.png")
        salida = self.correr("listar").stdout
        self.assertIn("SUGERENCIA: Capturas de pantalla", salida)
        self.assertIn("[ALTA CONFIANZA]", salida)

    def test_auto_mueve_solo_lo_seguro(self):
        self.poner_modelo()
        png = self.archivo(self.desc / "foto.png")
        txt = self.archivo(self.desc / "notas.txt")          # sin rasgos conocidos: 50/50
        llave = self.archivo(self.desc / "llave.pem")         # sensible: nunca automático
        r = self.correr("auto")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertTrue((self.dest / "Capturas de pantalla/foto.png").exists())
        self.assertFalse(png.exists())
        self.assertTrue(txt.exists())
        self.assertTrue(llave.exists())
        registro = (self.app / "registro_local/movimientos.jsonl").read_text()
        self.assertIn("clasificador local", registro)

    def test_auto_deja_posibles_duplicados_al_agente(self):
        self.poner_modelo()
        self.archivo(self.dest / "Finanzas/Facturas/factura.pdf", "ya estaba")
        f = self.archivo(self.desc / "factura.pdf")
        self.correr("auto")
        self.assertTrue(f.exists())

    def test_auto_respeta_el_simulacro_y_el_umbral(self):
        self.poner_modelo()
        f = self.archivo(self.desc / "foto.png")
        self.correr("auto", simulacro=True)
        self.assertTrue(f.exists())
        self.poner_modelo(umbral=1.01)
        self.correr("auto")
        self.assertTrue(f.exists())

    def test_auto_se_puede_deshacer(self):
        self.poner_modelo()
        f = self.archivo(self.desc / "foto.png")
        self.correr("auto")
        self.correr("deshacer", agente=False)
        self.assertTrue(f.exists())

    def test_sin_modelo_auto_falla_y_listar_sigue_igual(self):
        f = self.archivo(self.desc / "foto.png")
        self.assertNotEqual(self.correr("auto").returncode, 0)
        self.assertNotIn("SUGERENCIA", self.correr("listar").stdout)
        self.assertTrue(f.exists())

    def test_usar_falso_desactiva_el_clasificador(self):
        self.poner_modelo()
        self.config["clasificador"]["usar"] = False
        self.guardar_config()
        self.archivo(self.desc / "foto.png")
        self.assertNotIn("SUGERENCIA", self.correr("listar").stdout)

    def test_no_se_usa_en_modo_carpeta(self):
        self.poner_modelo()
        uni = self.home / "Documents" / "Universidad"
        self.archivo(uni / "foto.png")
        self.assertNotIn("SUGERENCIA", self.correr("listar", carpeta=uni).stdout)


class TestCatalogo(Entorno):
    def escribir_registro(self, filas):
        reg = self.app / "registro_local" / "movimientos.jsonl"
        reg.parent.mkdir(exist_ok=True)
        reg.write_text("".join(json.dumps(f) + "\n" for f in filas))

    def construir(self):
        env = dict(os.environ, HOME=str(self.home))
        r = subprocess.run([sys.executable, "-I", str(self.app / "catalogo.py")],
                           capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        return sqlite3.connect(self.app / "registro_local" / "catalogo.db")

    def mov(self, nombre, destino, motivo="", ejecucion="20261001-100000"):
        return {"ejecucion": ejecucion, "origen": str(self.desc / nombre),
                "destino": str(self.dest / destino / nombre), "motivo": motivo}

    def test_etiquetas_y_exclusiones(self):
        filas = [self.mov(f"paper{i}.pdf", "Academico/Papers") for i in range(5)]
        filas += [self.mov("raro.pdf", "Academico/Rara"),                        # subcarpeta con 1 ejemplo
                  self.mov("dup.pdf", self.config["carpeta_revisar"], "duplicado"),
                  self.mov("foto.png", "Imagenes", "clasificador local (0.97)"),
                  {"ejecucion": "20261001-100000", "origen": str(self.desc / "untitled folder"),
                   "destino": str(self.desc / "Recibos"), "motivo": "renombrado"},
                  {"ejecucion": "20261001-100000", "tipo": "edicion", "archivo": "/x", "respaldo": "/y"}]
        self.escribir_registro(filas)
        con = self.construir()
        tipos = dict(con.execute("SELECT tipo, COUNT(*) FROM movimientos GROUP BY tipo"))
        self.assertEqual(tipos, {"mover": 7, "revisar": 1, "renombrar": 1})
        self.assertEqual(con.execute("SELECT COUNT(*) FROM ediciones").fetchone()[0], 1)
        etiquetas = dict(con.execute("SELECT nombre, etiqueta FROM v_entrenamiento"))
        self.assertEqual(etiquetas["paper0.pdf"], "Academico/Papers")
        self.assertEqual(etiquetas["raro.pdf"], "Academico", "una subcarpeta rara se colapsa a su categoría")
        self.assertNotIn("dup.pdf", etiquetas)
        self.assertNotIn("foto.png", etiquetas, "lo que movió el clasificador no se reaprende")
        self.assertEqual(len(etiquetas), 6)

    def test_registro_vacio(self):
        con = self.construir()
        self.assertEqual(con.execute("SELECT COUNT(*) FROM movimientos").fetchone()[0], 0)


@unittest.skipUnless(python_con_sklearn(), "requiere scikit-learn")
class TestEntrenar(TestCatalogo):
    def test_entrena_exporta_y_predice_igual_que_sklearn(self):
        filas = []
        palabras = ["luz", "agua", "gas", "renta", "cine", "super", "farmacia", "taxi",
                    "hotel", "vuelo", "libro", "curso"]
        for w in palabras:
            filas.append(self.mov(f"Captura de pantalla {w}.png", "Capturas de pantalla"))
            filas.append(self.mov(f"factura {w}.pdf", "Finanzas/Facturas"))
            filas.append(self.mov(f"script_{w}.py", "Datos y Codigo/Scripts"))
        self.escribir_registro(filas)
        env = dict(os.environ, HOME=str(self.home))
        r = subprocess.run([python_con_sklearn(), str(self.app / "entrenar.py")],
                           capture_output=True, text=True, env=env, timeout=600)
        # entrenar.py comprueba internamente que su predicción coincide con scikit-learn
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        m = Modelo.cargar(self.app / "registro_local" / "modelo.json")
        self.assertEqual(m.predecir("Captura de pantalla 2026-11-01.png")[0], "Capturas de pantalla")
        self.assertEqual(m.predecir("otro_script.py")[0], "Datos y Codigo/Scripts")
        self.assertTrue((self.app / "registro_local" / "reporte_modelo.md").exists())

    def test_rechaza_datos_sin_variedad(self):
        filas = [self.mov(f"factura_{i}.pdf", "Finanzas") for i in range(20)]
        filas += [self.mov(f"foto_{i}.png", "Imagenes") for i in range(20)]
        self.escribir_registro(filas)
        env = dict(os.environ, HOME=str(self.home))
        r = subprocess.run([python_con_sklearn(), str(self.app / "entrenar.py")],
                           capture_output=True, text=True, env=env, timeout=600)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("Muy pocos archivos distintos", r.stderr)
        self.assertFalse((self.app / "registro_local" / "modelo.json").exists())


if __name__ == "__main__":
    unittest.main()
