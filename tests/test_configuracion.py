"""Pruebas de configuracion.py: config.local.json se aplica encima de config.json."""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from test_herramienta import RAIZ

sys.path.insert(0, str(RAIZ))
from configuracion import cargar, fusionar  # noqa: E402


class TestConfiguracion(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        shutil.copy2(RAIZ / "config.json", self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_sin_local_es_igual_a_config_json(self):
        self.assertEqual(cargar(self.tmp), json.loads((RAIZ / "config.json").read_text(encoding="utf-8")))

    def test_local_reemplaza_listas_y_combina_objetos(self):
        (self.tmp / "config.local.json").write_text(json.dumps(
            {"excluir_nombres": ["MiCarpeta"], "clasificador": {"auto_mover": False}}))
        c = cargar(self.tmp)
        self.assertEqual(c["excluir_nombres"], ["MiCarpeta"])
        self.assertFalse(c["clasificador"]["auto_mover"])
        self.assertIn("precision_objetivo", c["clasificador"], "las demás claves del objeto se conservan")
        self.assertIn("categorias", c)

    def test_el_ejemplo_es_valido(self):
        shutil.copy2(RAIZ / "config.local.example.json", self.tmp / "config.local.json")
        self.assertIn("MyProjectFolder", cargar(self.tmp)["excluir_nombres"])

    def test_fusionar_no_mezcla_tipos(self):
        self.assertEqual(fusionar({"a": {"b": 1}}, {"a": 2}), {"a": 2})


if __name__ == "__main__":
    unittest.main()
