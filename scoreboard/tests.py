import json

from django.core.cache import cache
from django.test import TestCase

from .models import Match


class OverlayTests(TestCase):
    def setUp(self):
        cache.clear()
        self.match = Match.objects.create(
            code="6tadamas",
            team_a="Pérez / Gómez",
            team_b="López / Díaz",
            set1_a=6,
            set1_b=4,
            current_set=2,
        )

    def test_viewer_sin_overlay_no_cambia(self):
        resp = self.client.get("/ver/6tadamas/")
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "scoreboard/viewer.html")
        self.assertTemplateNotUsed(resp, "scoreboard/overlay.html")

    def test_overlay_usa_template_transparente(self):
        resp = self.client.get("/ver/6tadamas/?overlay=1")
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "scoreboard/overlay.html")
        html = resp.content.decode()
        self.assertIn("background: transparent !important", html)
        self.assertIn('name="viewport"', html)
        self.assertNotIn("css/style.css", html)  # no hereda el fondo azul
        self.assertIn("Pérez / Gómez", html)

    def test_overlay_otro_valor_muestra_vista_normal(self):
        resp = self.client.get("/ver/6tadamas/?overlay=0")
        self.assertTemplateUsed(resp, "scoreboard/viewer.html")

    def test_overlay_codigo_inexistente_404(self):
        resp = self.client.get("/ver/noexiste/?overlay=1")
        self.assertEqual(resp.status_code, 404)

    def test_live_sin_actualizaciones_devuelve_base(self):
        data = self.client.get("/api/6tadamas/live/").json()
        self.assertEqual(data["team_a"], "Pérez / Gómez")
        self.assertEqual(data["sets"][0], {"a": 6, "b": 4})

    def test_live_incluye_puntos_del_game_tras_update(self):
        payload = {
            "payload": {
                "team_a": "Pérez / Gómez",
                "team_b": "López / Díaz",
                "current_set": 2,
                "sets": [{"a": 6, "b": 4}, {"a": 2, "b": 1}, {"a": 0, "b": 0}],
                "current_game": {"mode": "regular", "a": 30, "b": 15},
                "finished": False,
                "winner": None,
                "sponsors": [],
                "showPoints": True,
            }
        }
        resp = self.client.post(
            "/api/6tadamas/update/",
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)

        data = self.client.get("/api/6tadamas/live/").json()
        self.assertEqual(data["current_game"], {"mode": "regular", "a": 30, "b": 15})
        self.assertEqual(data["sets"][1], {"a": 2, "b": 1})

        # La vista normal y el endpoint state siguen igual
        state = self.client.get("/api/6tadamas/state/").json()
        self.assertNotIn("current_game", state)
        self.assertEqual(self.client.get("/ver/6tadamas/").status_code, 200)
