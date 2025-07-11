import logging
import operator
import re

from functools import reduce

from fluent.syntax import FluentParser, FluentSerializer

from django.db.models import CharField, Value as V
from django.db.models.functions import Concat

from pontoon.base.models import Entity, Locale, TranslatedResource, User
from pontoon.machinery.utils import (
    get_google_translate_data,
    get_translation_memory_data,
)
from pontoon.pretranslation import AUTHORS

from .transformer import ApplyPretranslation


log = logging.getLogger(__name__)

parser = FluentParser()
serializer = FluentSerializer()


def get_pretranslation(
    entity: Entity, locale: Locale, preserve_placeables: bool = False
) -> tuple[str, User] | None:
    """
    Get pretranslations for the entity-locale pair using internal translation memory and
    Google's machine translation.

    For Fluent strings, uplift SelectExpressions, serialize Placeables as TextElements
    and then only pretranslate TextElements. Set the most frequent TextElement
    pretranslation author as the author of the entire pretranslation.

    :arg Entity entity: the Entity object
    :arg Locale locale: the Locale object
    :arg boolean preserve_placeables

    :returns: None, or a tuple consisting of:
        - a pretranslation of the entity
        - a user (representing TM or GT service)
    """
    source = entity.string
    services = {k: User.objects.get(email=email) for k, email in AUTHORS.items()}

    if entity.resource.format == "ftl":
        entry = parser.parse_entry(source)
        pretranslate = ApplyPretranslation(
            locale, entry, get_pretranslated_data, preserve_placeables
        )

        try:
            pretranslate.visit(entry)
        except ValueError as e:
            log.info(f"Fluent pretranslation error: {e}")
            return None

        pretranslation = serializer.serialize_entry(entry)

        # Parse and serialize pretranslation again in order to assure cannonical style
        parsed_pretranslation = parser.parse_entry(pretranslation)
        pretranslation = serializer.serialize_entry(parsed_pretranslation)

        authors = [services[service] for service in pretranslate.services]
        author = max(set(authors), key=authors.count) if authors else services["tm"]

        return (pretranslation, author)

    # For now, disable pretranslation for plural gettext messages.
    # https://github.com/mozilla/pontoon/issues/3694
    elif entity.resource.format == "po" and ".match" in source:
        return None

    else:
        pretranslation, service = get_pretranslated_data(
            source, locale, preserve_placeables
        )
        if pretranslation is None:
            return None
        return (pretranslation, services[service])


def get_pretranslated_data(source: str, locale: Locale, preserve_placeables: bool):
    # Empty strings and strings containing whitespace only do not need translation
    if re.search("^\\s*$", source):
        return source, "tm"

    # Try to get matches from Translation Memory
    tm_response = get_translation_memory_data(text=source, locale=locale)
    tm_perfect = [t for t in tm_response if int(t["quality"]) == 100]
    if tm_perfect:
        return tm_perfect[0]["target"], "tm"

    # Fetch from Google Translate
    elif locale.google_translate_code:
        gt_response = get_google_translate_data(
            text=source, locale=locale, preserve_placeables=preserve_placeables
        )
        if gt_response["status"]:
            return gt_response["translation"], "gt"

    return None, None


def update_changed_instances(tr_filter, tr_dict, translations):
    """
    Update the latest activity and stats for changed TranslatedResources
    """
    tr_filter = tuple(tr_filter)
    # Combine all generated filters with an OK operator.
    # `operator.ior` is the '|' Python operator, which turns into a logical OR
    # when used between django ORM query objects.
    tr_query = reduce(operator.ior, tr_filter)

    translatedresources = TranslatedResource.objects.filter(tr_query).annotate(
        locale_resource=Concat(
            "locale_id", V("-"), "resource_id", output_field=CharField()
        )
    )

    translatedresources.calculate_stats()

    for tr in translatedresources:
        index = tr_dict[tr.locale_resource]
        translation = translations[index]
        translation.update_latest_translation()
