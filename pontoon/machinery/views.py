import json
import logging
import xml.etree.ElementTree as ET

from urllib.parse import quote

import requests

from sacremoses import MosesDetokenizer

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.paginator import EmptyPage, Paginator
from django.http import JsonResponse
from django.shortcuts import render
from django.template.loader import get_template
from django.utils.datastructures import MultiValueDictKeyError

from pontoon.base import utils
from pontoon.base.models import Entity, Locale, Project, Translation
from pontoon.machinery.utils import (
    get_concordance_search_data,
    get_google_translate_data,
    get_translation_memory_data,
)

from .openai_service import OpenAIService


log = logging.getLogger(__name__)


def machinery(request):
    locale = utils.get_project_locale_from_request(request, Locale.objects) or "en-GB"

    return render(
        request,
        "machinery/machinery.html",
        {
            "locale": Locale.objects.get(code=locale),
            "locales": Locale.objects.all(),
            "is_google_translate_supported": bool(settings.GOOGLE_TRANSLATE_API_KEY),
            "is_microsoft_translator_supported": bool(
                settings.MICROSOFT_TRANSLATOR_API_KEY
            ),
            "is_systran_translate_supported": bool(settings.SYSTRAN_TRANSLATE_API_KEY),
        },
    )


def translation_memory(request):
    """Get translations from internal translations memory."""
    try:
        text = request.GET["text"]
        locale = Locale.objects.get(code=request.GET["locale"])
        pk = request.GET.get("pk", None)

        if pk is not None:
            pk = int(pk)

    except (Locale.DoesNotExist, MultiValueDictKeyError, ValueError) as e:
        return JsonResponse(
            {"status": False, "message": f"Bad Request: {e}"},
            status=400,
        )

    data = get_translation_memory_data(text, locale, pk)
    return JsonResponse(data, safe=False)


def concordance_search(request):
    """Search for translations in the internal translations memory."""
    try:
        text = request.GET["text"]
        locale = Locale.objects.get(code=request.GET["locale"])
        page_results_limit = int(request.GET.get("limit", 100))
        page = int(request.GET.get("page", 1))
    except (Locale.DoesNotExist, MultiValueDictKeyError, ValueError) as e:
        return JsonResponse(
            {"status": False, "message": f"Bad Request: {e}"},
            status=400,
        )

    paginator = Paginator(get_concordance_search_data(text, locale), page_results_limit)

    try:
        data = paginator.page(page)
    except EmptyPage:
        return JsonResponse({"results": [], "has_next": False})

    # ArrayAgg (used in get_concordance_search_data()) does not support using
    # distinct=True in combination with ordering, so we need to do one of them
    # manually - after pagination, to reduce the number of rows processed.
    projects = Project.objects.order_by("disabled", "-priority", "name").values_list(
        "name", flat=True
    )
    for r in data.object_list:
        r["project_names"] = [p for p in projects if p in r["project_names"]]

    return JsonResponse(
        {"results": data.object_list, "has_next": data.has_next()}, safe=False
    )


@login_required(redirect_field_name="", login_url="/403")
def microsoft_translator(request):
    """Get translation from Microsoft machine translation service."""
    try:
        text = request.GET["text"]
        locale_code = request.GET["locale"]

        if not locale_code:
            raise ValueError("Locale code is empty")

        api_key = settings.MICROSOFT_TRANSLATOR_API_KEY
        if not api_key:
            raise ValueError("Missing api key")

    except (MultiValueDictKeyError, ValueError) as e:
        return JsonResponse(
            {"status": False, "message": f"Bad Request: {e}"},
            status=400,
        )

    url = "https://api.cognitive.microsofttranslator.com/translate"
    headers = {"Ocp-Apim-Subscription-Key": api_key, "Content-Type": "application/json"}
    payload = {
        "api-version": "3.0",
        "from": "en",
        "to": locale_code,
        "textType": "html",
    }
    body = [{"Text": text}]

    r = None
    try:
        r = requests.post(url, params=payload, headers=headers, json=body)
        r.raise_for_status()

        root = json.loads(r.content)

        if "error" in root:
            log.error(f"Microsoft Translator error: {root}")
            return JsonResponse(
                {"status": False, "message": f"Bad Request: {root}"},
                status=400,
            )

        return JsonResponse({"translation": root[0]["translations"][0]["text"]})

    except requests.exceptions.RequestException as e:
        return JsonResponse(
            {"status": False, "message": f"{e}"},
            status=r.status_code if r is not None else 500,
        )


@login_required(redirect_field_name="", login_url="/403")
def google_translate(request):
    """Get translation from Google machine translation service."""
    try:
        text = request.GET["text"]
        locale = Locale.objects.get(code=request.GET["locale"])

        if not locale.google_translate_code:
            raise ValueError("Locale code not supported")

    except (Locale.DoesNotExist, MultiValueDictKeyError, ValueError) as e:
        return JsonResponse(
            {"status": False, "message": f"Bad Request: {e}"},
            status=400,
        )

    data = get_google_translate_data(text, locale)

    if not data["status"]:
        return JsonResponse(data, status=400)

    return JsonResponse(data)


@login_required(redirect_field_name="", login_url="/403")
def gpt_transform(request):
    """
    Transforms and returns text using GPT-4 based on specified characteristics like rephrasing or changing formality, by fetching English text, its machine translation, desired transformation characteristic, and target language from the request.
    """
    try:
        english_text = request.GET.get("english_text")
        translated_text = request.GET.get("translated_text")
        characteristic = request.GET.get("characteristic")
        target_language_name = request.GET.get("locale")

        service = OpenAIService()
        transformed_text = service.get_translation(
            english_text, translated_text, characteristic, target_language_name
        )

        return JsonResponse({"translation": transformed_text})

    except Exception as e:
        return JsonResponse({"status": False, "message": str(e)}, status=400)


@login_required(redirect_field_name="", login_url="/403")
def systran_translate(request):
    """Get translations from SYSTRAN machine translation service."""
    try:
        text = request.GET["text"]
        locale_code = request.GET["locale"]

        if not locale_code:
            raise ValueError("Locale code is empty")

        locale = Locale.objects.filter(systran_translate_code=locale_code).first()

        api_key = settings.SYSTRAN_TRANSLATE_API_KEY
        if not api_key:
            raise ValueError("Missing api key")

    except (Locale.DoesNotExist, MultiValueDictKeyError, ValueError) as e:
        return JsonResponse(
            {"status": False, "message": f"Bad Request: {e}"},
            status=400,
        )

    url = "https://api-translate.systran.net/translation/text/translate"

    payload = {
        "key": api_key,
        "input": text,
        "source": "en",
        "target": locale_code,
        "profile": locale.systran_translate_profile,
        "format": "text",
    }

    r = None
    try:
        r = requests.post(url, params=payload)
        r.raise_for_status()

        root = json.loads(r.content)

        if "error" in root:
            log.error(f"SYSTRAN error: {root}")
            return JsonResponse(
                {"status": False, "message": f"Bad Request: {root}"},
                status=400,
            )

        return JsonResponse({"translation": root["outputs"][0]["output"]})

    except requests.exceptions.RequestException as e:
        return JsonResponse(
            {"status": False, "message": f"{e}"},
            status=r.status_code if r is not None else 500,
        )


def caighdean(request):
    """Get translation from Caighdean machine translation service."""
    try:
        entityid = int(request.GET["id"])
        entity = Entity.objects.get(id=entityid)
    except (Entity.DoesNotExist, MultiValueDictKeyError, ValueError) as e:
        return JsonResponse(
            {"status": False, "message": f"Bad Request: {e}"},
            status=400,
        )

    try:
        text = entity.translation_set.get(locale__code="gd", approved=True).string
    except Translation.DoesNotExist:
        return JsonResponse({})

    url = "https://cadhan.com/api/intergaelic/3.0"

    data = {
        "teacs": text,
        "foinse": "gd",
    }

    r = None
    try:
        r = requests.post(url, data=data)
        r.raise_for_status()

        root = json.loads(r.content)
        tokens = [x[1] for x in root]
        translation = (
            MosesDetokenizer().detokenize(tokens, return_str=True).replace("\\n", "\n")
        )

        return JsonResponse({"original": text, "translation": translation})

    except requests.exceptions.RequestException as e:
        return JsonResponse(
            {"status": False, "message": f"{e}"},
            status=r.status_code if r is not None else 500,
        )


def microsoft_terminology(request):
    """Get translations from Microsoft Terminology Service."""
    try:
        text = request.GET["text"]
        locale_code = request.GET["locale"]

        if not locale_code:
            raise ValueError("Locale code is empty")

    except (MultiValueDictKeyError, ValueError) as e:
        return JsonResponse(
            {"status": False, "message": f"Bad Request: {e}"},
            status=400,
        )

    obj = {}
    url = "https://api.terminology.microsoft.com/Terminology.svc"
    headers = {
        "SOAPAction": (
            '"http://api.terminology.microsoft.com/terminology/Terminology/GetTranslations"'
        ),
        "Content-Type": "text/xml; charset=utf-8",
    }
    payload = {
        "text": quote(text.encode("utf-8")),
        "to": locale_code,
        "max_result": 5,
    }
    template = get_template("machinery/microsoft_terminology.jinja")

    payload = template.render(payload)

    r = None
    try:
        r = requests.post(url, data=payload, headers=headers)
        r.raise_for_status()

        translations = []
        namespaces = {"a": "https://api.terminology.microsoft.com/terminology"}
        root = ET.fromstring(r.content)
        results = root.find(
            ".//{http://api.terminology.microsoft.com/terminology}GetTranslationsResult"
        )

        if results is not None:
            for translation in results:
                translations.append(
                    {
                        "source": translation.find("a:OriginalText", namespaces).text,
                        "target": translation.find(
                            ".//a:TranslatedText", namespaces
                        ).text,
                    }
                )

            obj["translations"] = translations
        return JsonResponse(obj)

    except requests.exceptions.RequestException as e:
        return JsonResponse(
            {"status": False, "message": f"{e}"},
            status=r.status_code if r is not None else 500,
        )
