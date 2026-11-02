"""Pruebas de las garantías de seguridad de herramienta.py.

Cada prueba crea un HOME falso en una carpeta temporal, con su propio Escritorio,
Descargas y Organizado, y una copia de la herramienta con su config.json. Así nunca
se toca ningún archivo real. Solo usan la biblioteca estándar:

    /usr/bin/python3 -m unittest discover -s tests -v
"""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
PY = shutil.which("python3") or "/usr/bin/python3"


class Entorno(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.home = self.tmp / "home"
        self.app = self.tmp / "app"
        for d in ("Desktop", "Downloads", "Documents/Organizado"):
            (self.home / d).mkdir(parents=True)
        self.app.mkdir()
        for f in ("herramienta.py", "extraer.py", "rasgos.py", "catalogo.py", "entrenar.py",
                  "busqueda.py", "mcp_servidor.py", "pdf_texto.swift"):
            if not (RAIZ / f).exists():
                continue
            shutil.copy2(RAIZ / f, self.app)
        if (RAIZ / "bin" / "pdf_texto").exists():
            # Reutiliza el binario ya compilado para no recompilar en cada prueba
            shutil.copytree(RAIZ / "bin", self.app / "bin", copy_function=shutil.copy2)
        self.config = json.loads((RAIZ / "config.json").read_text(encoding="utf-8"))
        self.guardar_config()
        self.desc = self.home / "Downloads"
        self.dest = self.home / "Documents" / "Organizado"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def guardar_config(self, **cambios):
        self.config.update(cambios)
        (self.app / "config.json").write_text(json.dumps(self.config), encoding="utf-8")

    def correr(self, *args, simulacro=False, agente=True, carpeta=None):
        env = {"HOME": str(self.home), "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
               "ORGANIZADOR_EJECUCION": "prueba",
               "ORGANIZADOR_SIMULACRO": "1" if simulacro else "0",
               "ORGANIZADOR_AGENTE": "1" if agente else "0"}
        if carpeta:
            env["ORGANIZADOR_CARPETA"] = str(carpeta)
        return subprocess.run([PY, "-I", str(self.app / "herramienta.py"), *map(str, args)],
                              capture_output=True, text=True, env=env, timeout=120)

    def archivo(self, ruta: Path, contenido="hola"):
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text(contenido, encoding="utf-8")
        return ruta

    def etiquetas(self, p: Path):
        r = subprocess.run(["xattr", "-p", "com.apple.metadata:_kMDItemUserTags", str(p)],
                           capture_output=True)
        return r.returncode == 0


class TestMover(Entorno):
    def test_mueve_a_la_categoria_y_lo_registra(self):
        f = self.archivo(self.desc / "factura.pdf")
        r = self.correr("mover", "--destino", "Finanzas/Facturas 2026", f)
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertFalse(f.exists())
        self.assertTrue((self.dest / "Finanzas/Facturas 2026/factura.pdf").exists())
        registro = (self.app / "registro_local/movimientos.jsonl").read_text(encoding="utf-8")
        self.assertIn("factura.pdf", registro)

    def test_pone_etiqueta_de_finder(self):
        f = self.archivo(self.desc / "receta.pdf")
        self.correr("mover", "--destino", "Salud", f)
        self.assertTrue(self.etiquetas(self.dest / "Salud/receta.pdf"))

    def test_nunca_sobrescribe(self):
        self.archivo(self.dest / "Trabajo/informe.pdf", "original")
        f = self.archivo(self.desc / "informe.pdf", "nuevo")
        r = self.correr("mover", "--destino", "Trabajo", f)
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertEqual((self.dest / "Trabajo/informe.pdf").read_text(), "original")
        self.assertEqual((self.dest / "Trabajo/informe (2).pdf").read_text(), "nuevo")

    def test_simulacro_no_mueve_nada(self):
        f = self.archivo(self.desc / "foto.jpg")
        r = self.correr("mover", "--destino", "Imagenes", f, simulacro=True)
        self.assertIn("[SIMULACRO]", r.stdout)
        self.assertTrue(f.exists())
        self.assertFalse((self.dest / "Imagenes").exists())
        self.assertFalse((self.app / "registro_local/movimientos.jsonl").exists())


class TestLimites(Entorno):
    def test_rechaza_archivos_fuera_de_los_origenes(self):
        f = self.archivo(self.home / "Documents" / "privado.txt")
        r = self.correr("mover", "--destino", "Otros", f)
        self.assertNotEqual(r.returncode, 0)
        self.assertTrue(f.exists())

    def test_rechaza_archivos_dentro_de_subcarpetas(self):
        f = self.archivo(self.desc / "proyecto" / "datos.csv")
        r = self.correr("mover", "--destino", "Otros", f)
        self.assertNotEqual(r.returncode, 0)
        self.assertTrue(f.exists())

    def test_rechaza_destinos_que_escapan(self):
        f = self.archivo(self.desc / "a.txt")
        for destino in ("../fuera", "Otros/../../fuera", ".oculta", "A/B/C"):
            r = self.correr("mover", "--destino", destino, f)
            self.assertNotEqual(r.returncode, 0, destino)
        self.assertTrue(f.exists())

    def test_no_toca_ocultos_excluidos_ni_descargas_incompletas(self):
        for nombre in (".secreto", "Piloto", "video.mp4.crdownload"):
            f = self.archivo(self.desc / nombre)
            r = self.correr("mover", "--destino", "Otros", f)
            self.assertNotEqual(r.returncode, 0, nombre)
            self.assertTrue(f.exists(), nombre)
        listado = self.correr("listar").stdout
        self.assertNotIn(".secreto", listado)
        self.assertNotIn("crdownload", listado)

    def test_renombrar_nunca_toca_archivos(self):
        f = self.archivo(self.desc / "contrato.pdf")
        r = self.correr("renombrar", "--nuevo-nombre", "otro.pdf", f)
        self.assertNotEqual(r.returncode, 0)
        self.assertTrue(f.exists())

    def test_renombrar_no_pisa_una_carpeta_existente(self):
        (self.desc / "Nueva carpeta").mkdir()
        (self.desc / "Fotos").mkdir()
        r = self.correr("renombrar", "--nuevo-nombre", "Fotos", self.desc / "Nueva carpeta")
        self.assertNotEqual(r.returncode, 0)
        self.assertTrue((self.desc / "Nueva carpeta").exists())

    def test_proyecto_protegido_no_se_mueve(self):
        self.guardar_config(proteger_proyectos=True)
        p = self.desc / "mi_repo"
        (p / ".git").mkdir(parents=True)
        r = self.correr("mover", "--destino", "Proyectos", p)
        self.assertNotEqual(r.returncode, 0)
        self.assertTrue(p.exists())

    def test_mover_carpetas_desactivado(self):
        self.guardar_config(mover_carpetas=False)
        (self.desc / "cosas").mkdir()
        r = self.correr("mover", "--destino", "Otros", self.desc / "cosas")
        self.assertNotEqual(r.returncode, 0)

    def test_el_agente_no_puede_deshacer(self):
        r = self.correr("deshacer", agente=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("solo para uso manual", r.stdout)


class TestCarpetaEspecifica(Entorno):
    def test_rechaza_carpetas_no_permitidas(self):
        repo = self.home / "Documents" / "repo"
        (repo / ".git").mkdir(parents=True)
        (repo / "sub").mkdir()
        oculta = self.home / ".config"
        oculta.mkdir()
        for c in (self.home, self.home / "Library", oculta, repo, repo / "sub", self.tmp):
            c.mkdir(exist_ok=True)
            r = self.correr("validar", carpeta=c)
            self.assertNotEqual(r.returncode, 0, c)

    def test_organiza_en_su_propio_lugar(self):
        uni = self.home / "Documents" / "Universidad"
        f = self.archivo(uni / "tarea1_algebra.txt")
        r = self.correr("mover", "--destino", "Algebra", f, carpeta=uni)
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertTrue((uni / "Algebra/tarea1_algebra.txt").exists())
        # La categoría creada queda marcada y ya no se puede mover
        r = self.correr("mover", "--destino", "Otros", uni / "Algebra", carpeta=uni)
        self.assertNotEqual(r.returncode, 0)


class TestRevisarYDeshacer(Entorno):
    def test_revisar_guarda_el_motivo(self):
        f = self.archivo(self.desc / "app.dmg")
        self.correr("revisar", "--motivo", "instalador viejo", f)
        carpeta = self.dest / self.config["carpeta_revisar"]
        self.assertTrue((carpeta / "app.dmg").exists())
        self.assertIn("instalador viejo", (carpeta / "LEEME - motivos.txt").read_text(encoding="utf-8"))

    def test_deshacer_devuelve_movimientos_y_renombrados(self):
        f = self.archivo(self.desc / "boleto.pdf")
        (self.desc / "untitled folder").mkdir()
        self.correr("mover", "--destino", "Viajes", f)
        self.correr("renombrar", "--nuevo-nombre", "Recibos", self.desc / "untitled folder")
        r = self.correr("deshacer", agente=False)
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertTrue(f.exists())
        self.assertTrue((self.desc / "untitled folder").exists())
        self.assertFalse((self.desc / "Recibos").exists())


class TestProyectos(Entorno):
    def crear_proyecto(self):
        p = self.desc / "analisis"
        (p / ".git").mkdir(parents=True)
        (p / ".git" / "config").write_text(f"[core]\n\tworktree = {p}\n")
        self.archivo(p / "main.py", f'DATOS = "{p}/datos.csv"\nOTRO = "{p}2/x.csv"\nREL = "../fuera.csv"\n')
        return p

    def test_ajusta_rutas_al_mover_y_deshacer_las_restaura(self):
        p = self.crear_proyecto()
        original = (p / "main.py").read_text()
        r = self.correr("mover", "--destino", "Proyectos", p)
        self.assertEqual(r.returncode, 0, r.stdout)
        nuevo = self.dest / "Proyectos" / "analisis"
        codigo = (nuevo / "main.py").read_text()
        self.assertIn(f'"{nuevo}/datos.csv"', codigo)
        self.assertIn(f'"{p}2/x.csv"', codigo, "una ruta parecida no se debe tocar")
        self.assertIn(str(nuevo), (nuevo / ".git/config").read_text())
        self.assertIn("AVISO", r.stdout, "las rutas relativas que salen se avisan")

        self.correr("deshacer", agente=False)
        self.assertEqual((p / "main.py").read_text(), original)

    def test_sin_ajuste_de_rutas_no_edita_nada(self):
        self.guardar_config(ajustar_rutas_proyectos=False)
        p = self.crear_proyecto()
        original = (p / "main.py").read_text()
        self.correr("mover", "--destino", "Proyectos", p)
        self.assertEqual((self.dest / "Proyectos/analisis/main.py").read_text(), original)


class TestLectura(Entorno):
    def test_detecta_duplicados_exactos(self):
        self.archivo(self.desc / "cv.pdf", "mismo")
        self.archivo(self.desc / "cv (1).pdf", "mismo")
        self.archivo(self.desc / "otro.pdf", "distinto")
        r = self.correr("listar", "--duplicados")
        self.assertIn("DUPLICADOS EXACTOS: 1 grupos", r.stdout)

    def test_no_lee_archivos_sensibles(self):
        f = self.archivo(self.desc / "llave.pem", "-----BEGIN PRIVATE KEY----- SECRETO")
        r = self.correr("vistazo", f)
        self.assertNotIn("SECRETO", r.stdout)
        self.assertIn("[POSIBLE SENSIBLE]", self.correr("listar").stdout)

    def test_respeta_leer_contenido_falso(self):
        self.guardar_config(leer_contenido=False)
        f = self.archivo(self.desc / "notas.txt", "contenido privado")
        self.assertNotIn("contenido privado", self.correr("vistazo", f).stdout)

    def test_vistazo_limita_caracteres(self):
        f = self.archivo(self.desc / "largo.txt", "x" * 5000)
        extracto = self.correr("vistazo", f).stdout.split("EXTRACTO:", 1)[1]
        self.assertLessEqual(len(extracto.strip()), self.config["max_caracteres_vistazo"])

    @unittest.skipUnless(shutil.which("sips") and shutil.which("swiftc"), "requiere macOS con swiftc")
    def test_pdf_escaneado_se_lee_con_ocr(self):
        # Imagen con texto -> PDF sin capa de texto, como un escaneo
        html = self.tmp / "t.html"
        html.write_text("<h1 style='font-size:60px'>FACTURA ELECTRONICA 2026</h1>")
        png = self.tmp / "t.png"
        subprocess.run(["qlmanage", "-t", "-s", "1200", "-o", str(self.tmp), str(html)],
                       capture_output=True)
        miniatura = self.tmp / "t.html.png"
        if not miniatura.exists():
            self.skipTest("no se pudo generar la imagen de prueba")
        miniatura.rename(png)
        pdf = self.desc / "scan001.pdf"
        subprocess.run(["sips", "-s", "format", "pdf", str(png), "--out", str(pdf)], capture_output=True)
        r = self.correr("vistazo", pdf)
        self.assertIn("[OCR]", r.stdout)
        self.assertIn("FACTURA", r.stdout.upper())


if __name__ == "__main__":
    unittest.main()
