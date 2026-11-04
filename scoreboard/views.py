from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, HttpResponseBadRequest
from django.views.decorators.http import require_POST, require_GET
from django.views.decorators.csrf import csrf_exempt
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from .models import Match  # Asumiendo que existe el modelo Match
import json
import base64
from io import BytesIO
import qrcode

# NUEVO: para guardar archivos
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
import os
import uuid

# Overlay para transmisiones (Larix): último estado completo del partido
from django.core.cache import cache
from django.views.decorators.clickjacking import xframe_options_sameorigin

LIVE_CACHE_KEY = "scoreboard_live_{code}"


def _live_state(match):
    """
    Estado más reciente del partido para el overlay.
    Usa el último payload enviado por el panel de control (incluye puntos del
    game actual, que no se guardan en la base) y, si no hay, el de la base.
    """
    data = match.as_payload()
    cached = cache.get(LIVE_CACHE_KEY.format(code=match.code))
    if isinstance(cached, dict):
        data.update(cached)
    return data


DEFAULT_EDITION = "4ta Edición"


def _clean_label(value):
    """'6ta-damas' / '6ta_damas' -> '6ta damas' (se muestra en mayúsculas por CSS)."""
    return (value or "").replace("-", " ").replace("_", " ").strip()[:40]


def overlay(request, match, category=""):
    """Versión overlay del marcador (fondo transparente) para Larix / OBS."""
    category = _clean_label(request.GET.get("cat") or category)
    edition = _clean_label(request.GET.get("ed")) or DEFAULT_EDITION
    return render(
        request,
        "scoreboard/overlay.html",
        {
            "match": match,
            "initial_state": _live_state(match),
            "category": category,
            "edition": edition,
        },
    )


@xframe_options_sameorigin  # permite verlo dentro del simulador (mismo sitio)
def overlay_page(request, code, category=""):
    """
    /overlay/<code>/  y  /overlay/<code>/<categoria>/
    URL sin parámetros '?', más segura para cargar en Larix.
    """
    match = get_object_or_404(Match, code=code)
    return overlay(request, match, category)


def overlay_preview(request, code, category=""):
    """Simulador 9:16 (1080x1920) del overlay sobre una cancha, para probar en la compu."""
    match = get_object_or_404(Match, code=code)
    overlay_url = f"/overlay/{match.code}/"
    if category:
        overlay_url += f"{category}/"
    query = request.META.get("QUERY_STRING", "")
    if query:
        overlay_url += f"?{query}"
    return render(
        request,
        "scoreboard/overlay_preview.html",
        {"match": match, "overlay_url": overlay_url},
    )


@require_GET
def live_state(request, code):
    """Estado en vivo para el overlay (fallback por polling si cae el WebSocket)."""
    match = get_object_or_404(Match, code=code)
    return JsonResponse(_live_state(match))


def index(request):
    return render(request, "scoreboard/index.html")


def new_match(request):
    m = Match.objects.create()
    return redirect("choose_mode", code=m.code)


def choose_mode(request, code):
    """
    Pantalla para elegir modalidad del partido:
    - 3 sets
    - 2 sets + super tie-break
    """
    match = get_object_or_404(Match, code=code)

    if request.method == "POST":
        mode = request.POST.get("mode", "3_sets")
        match.mode = mode
        match.save()
        return redirect("control", code=match.code)

    return render(request, "scoreboard/choose_mode.html", {"match": match})


def viewer(request, code):
    """Vista pública del marcador."""
    match = get_object_or_404(Match, code=code)

    # /ver/<code>/?overlay=1 → versión overlay para transmisiones
    if request.GET.get("overlay") == "1":
        return overlay(request, match)

    qr_data_uri = None
    try:
        viewer_url = request.build_absolute_uri(f"/ver/{match.code}/")
        qr = qrcode.QRCode(box_size=6, border=2)
        qr.add_data(viewer_url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = BytesIO()
        img.save(buf, format="PNG")
        qr_b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        qr_data_uri = f"data:image/png;base64,{qr_b64}"
    except Exception:
        qr_data_uri = None

    return render(
        request,
        "scoreboard/viewer.html",
        {"match": match, "qr_data_uri": qr_data_uri},
    )


def control(request, code):
    """Panel de control (operador del partido)."""
    match = get_object_or_404(Match, code=code)

    # Generar QR del viewer
    qr_data_uri = None
    try:
        viewer_url = request.build_absolute_uri(f"/ver/{match.code}/")
        qr = qrcode.QRCode(box_size=6, border=2)
        qr.add_data(viewer_url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = BytesIO()
        img.save(buf, format="PNG")
        qr_b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        qr_data_uri = f"data:image/png;base64,{qr_b64}"
    except Exception:
        qr_data_uri = None

    super_tb = match.check_super_tiebreak()  # Asumiendo que esta función existe en el modelo

    return render(
        request,
        "scoreboard/control.html",
        {"match": match, "qr_data_uri": qr_data_uri, "super_tiebreak": super_tb},
    )


@csrf_exempt
@require_POST
def update_scores(request, code):
    """
    Recibe actualización del control.html (JSON) → guarda en BD → envía por WebSocket.
    """
    match = get_object_or_404(Match, code=code)
    try:
        # Parsear el cuerpo de la petición (JSON)
        if request.content_type and "application/json" in request.content_type:
            data = json.loads(request.body.decode("utf-8"))
        else:
            # Usar request.POST.dict() como fallback si no es JSON
            data = request.POST.dict()

        # ⭐ Extraer el 'payload' interno (que envía control.html), o usar 'data' si no está anidado
        payload = data.get("payload") or data

        # Actualizar campos básicos
        if "team_a" in payload:
            match.team_a = payload["team_a"]
        if "team_b" in payload:
            match.team_b = payload["team_b"]
        if "a1_last" in payload:
            match.a1_last = payload["a1_last"]
        if "a2_last" in payload:
            match.a2_last = payload["a2_last"]
        if "b1_last" in payload:
            match.b1_last = payload["b1_last"]
        if "b2_last" in payload:
            match.b2_last = payload["b2_last"]
        if "a1_full" in payload:
            match.a1_full = payload["a1_full"]
        if "a2_full" in payload:
            match.a2_full = payload["a2_full"]
        if "b1_full" in payload:
            match.b1_full = payload["b1_full"]
        if "b2_full" in payload:
            match.b2_full = payload["b2_full"]
        if "current_set" in payload:
            try:
                match.current_set = int(payload["current_set"])
            except ValueError:
                pass

        # Sets
        sets_data = payload.get("sets")
        if isinstance(sets_data, list):
            def v(i, side):
                try:
                    val = sets_data[i].get(side, 0)
                    return int(val) if val else 0
                except Exception:
                    return 0

            match.set1_a, match.set1_b = v(0, "a"), v(0, "b")
            match.set2_a, match.set2_b = v(1, "a"), v(1, "b")
            match.set3_a, match.set3_b = v(2, "a"), v(2, "b")

        # ⭐ SPONSORS: ahora vienen como lista de URLs (strings)
        sp = payload.get("sponsors")
        if isinstance(sp, list):
            match.sponsors = sp

        # Puntos a mostrar
        if "showPoints" in payload:
            match.show_points = payload["showPoints"]

        match.save()

        # Armar payload WS
        out = match.as_payload()
        cg = payload.get("current_game") or {}

        out["current_game"] = {
            "mode": cg.get("mode", "regular"),
            "a": cg.get("a", 0),
            "b": cg.get("b", 0),
        }

        # Información de partido finalizado
        finished = payload.get("finished")
        winner = payload.get("winner")
        out["finished"] = bool(finished)
        out["winner"] = winner or ""
        out["show_points"] = match.show_points

        # Guardar último estado completo para el overlay (no toca la base)
        try:
            cache.set(LIVE_CACHE_KEY.format(code=match.code), out, None)
        except Exception:
            pass

        # Broadcast WebSocket
        layer = get_channel_layer()
        async_to_sync(layer.group_send)(
            f"match_{match.code}",
            {"type": "match_update", "payload": out},
        )

        return JsonResponse({"ok": True, "match": out})
    except Exception as e:
        return HttpResponseBadRequest(str(e))


@require_GET
def get_state(request, code):
    """Devuelve el estado actual del partido (para viewer.html si entra antes del WS)."""
    match = get_object_or_404(Match, code=code)
    try:
        out = match.as_payload()
        return JsonResponse(out)
    except Exception as e:
        return HttpResponseBadRequest(str(e))


# ⚠️ NUEVO: endpoint para subir sponsors
@csrf_exempt
@require_POST
def upload_sponsor(request):
    """
    Recibe un archivo 'file' (imagen), lo guarda en /media/sponsors/
    y devuelve {"url": "/media/sponsors/xxx.png"}
    """
    file = request.FILES.get("file")
    if not file:
        return JsonResponse({"error": "Falta archivo 'file'"}, status=400)

    # Extensión segura
    ext = os.path.splitext(file.name)[1].lower()
    if ext not in [".png", ".jpg", ".jpeg", ".webp"]:
        ext = ".png"

    filename = f"{uuid.uuid4()}{ext}"
    path = os.path.join("sponsors", filename)

    default_storage.save(path, ContentFile(file.read()))
    url = f"/media/{path}"

    return JsonResponse({"url": url})
