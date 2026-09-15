from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from itertools import groupby
from os.path import basename, join
from tempfile import TemporaryDirectory

from moz.l10n.model import Id as L10nId
from moz.l10n.resource import parse_resource

from django.core.files import File
from django.db.models import Q, prefetch_related_objects
from django.utils import timezone

from pontoon.actionlog.models import ActionLog
from pontoon.base.models import (
    ChangedEntityLocale,
    Entity,
    Locale,
    Project,
    Resource as DbResource,
    Translation,
    User,
)
from pontoon.checks.libraries import run_checks
from pontoon.checks.utils import are_blocking_checks, get_failed_checks_db_objects
from pontoon.sync.core.stats import update_stats
from pontoon.sync.core.translations_from_repo import (
    Updates,
    build_translation,
    translations_equal,
    write_db_updates,
)
from pontoon.sync.formats import RepoTranslation, as_repo_translations


class UploadError(Exception):
    """The uploaded file could not be imported; nothing was written to the database."""


class UploadConflictError(Exception):
    """A concurrent change modified translations targeted by the upload."""


@dataclass
class UploadResult:
    """
    Summary of an uploaded file import:
    - `updated`: translations added or replaced
    - `unchanged`: translations identical to the current approved, pretranslated or
      fuzzy one
    - `undefined_keys`: keys of translations with no matching entity in Pontoon
    """

    updated: int = 0
    unchanged: int = 0
    undefined_keys: list[L10nId] = field(default_factory=list)

    @property
    def undefined(self) -> int:
        return len(self.undefined_keys)


def parse_uploaded_file(
    locale: Locale, db_res: DbResource, upload: File
) -> dict[L10nId, RepoTranslation]:
    """Translations in an uploaded file, keyed by entity key."""
    with TemporaryDirectory() as root:
        file_path = join(root, basename(db_res.path))
        with open(file_path, "wb") as file:
            for chunk in upload.chunks():
                file.write(chunk)
        try:
            l10n_res = parse_resource(
                file_path,
                gettext_plurals=locale.cldr_plurals_list(),
                gettext_skip_obsolete=True,
            )
        except Exception as error:
            raise UploadError(f"Could not parse uploaded file: {error}") from error
    upload_translations = {rt.key: rt for rt in as_repo_translations(l10n_res)}
    if not upload_translations:
        raise UploadError("No translations found in uploaded file.")
    return upload_translations


def entity_ids(db_res: DbResource) -> dict[L10nId, int]:
    """Ids of the resource's current entities, keyed by entity key."""
    return {
        tuple(key): id
        for id, key in Entity.objects.filter(resource=db_res, obsolete=False)
        .values_list("id", "key")
        .iterator()
    }


def parse_upload_for_entities(
    locale: Locale, db_res: DbResource, upload: File
) -> tuple[dict[L10nId, RepoTranslation], dict[L10nId, int], list[L10nId]]:
    """Uploaded translations with a matching entity, the entity ids, and the other keys."""
    upload_translations = parse_uploaded_file(locale, db_res, upload)
    entities = entity_ids(db_res)
    undefined_keys = [key for key in upload_translations if key not in entities]
    for key in undefined_keys:
        del upload_translations[key]
    return upload_translations, entities, undefined_keys


def import_uploaded_file(
    project: Project,
    locale: Locale,
    db_res: DbResource,
    upload: File,
    user: User,
) -> UploadResult:
    """Update translations in the database from an uploaded file."""
    result = UploadResult()
    upload_translations, entities, result.undefined_keys = parse_upload_for_entities(
        locale, db_res, upload
    )

    current_translations = (
        Translation.objects.filter(
            entity__resource=db_res, entity__obsolete=False, locale=locale
        )
        .filter(Q(approved=True) | Q(pretranslated=True) | Q(fuzzy=True))
        .values_list("entity__key", "value", "properties", "fuzzy")
        .iterator()
    )
    for key, value, properties, fuzzy in current_translations:
        rt = upload_translations.get(tuple(key), None)
        if (
            rt is not None
            and (rt.fuzzy or not fuzzy)
            and translations_equal(rt.value, rt.properties, value, properties)
        ):
            del upload_translations[rt.key]
            result.unchanged += 1

    updates: Updates = {
        (entities[key], locale.pk): rt for key, rt in upload_translations.items()
    }
    result.updated = len(updates)
    if updates:
        now = timezone.now()
        # write_db_updates() removes entries from `updates` as it processes them
        update_keys = list(updates)
        write_db_updates(project, updates, user, now)
        update_stats(project)
        ChangedEntityLocale.objects.bulk_create(
            (
                ChangedEntityLocale(entity_id=entity_id, locale_id=locale_id, when=now)
                for entity_id, locale_id in update_keys
            ),
            ignore_conflicts=True,
        )
    return result


@dataclass
class FailedCheck:
    """An uploaded translation left out because it fails checks."""

    key: L10nId
    errors: list[str]
    warnings: list[str]

    @classmethod
    def from_check_results(
        cls, key: L10nId, results: dict[str, list[str]]
    ) -> "FailedCheck":
        """The key and the messages of a `run_checks()` result, split by severity."""
        return cls(
            key=key,
            errors=[m for g, ms in results.items() if g.endswith("Errors") for m in ms],
            warnings=[
                m for g, ms in results.items() if g.endswith("Warnings") for m in ms
            ],
        )


def translations_by_entity(
    locale: Locale, entity_ids: Iterable[int], *, include_rejected: bool
) -> dict[int, list[Translation]]:
    """The locale's translations of the given entities, keyed by entity id."""
    translations = Translation.objects.filter(entity_id__in=entity_ids, locale=locale)
    if not include_rejected:
        translations = translations.filter(rejected=False)
    return {
        entity_id: list(txs)
        for entity_id, txs in groupby(
            translations.order_by("entity_id").iterator(),
            key=lambda tx: tx.entity_id,
        )
    }


# The translation fields used to make a decision on how to treat
# imported translations and to detect concurrent changes.
REVIEW_FIELDS = ("approved", "pretranslated", "fuzzy", "rejected", "active")


def read_state(translations: list[Translation]) -> dict[int, tuple[bool, ...]]:
    """The review state of each translation, keyed by translation id."""
    return {tx.pk: tuple(getattr(tx, f) for f in REVIEW_FIELDS) for tx in translations}


@dataclass
class PendingChange:
    """
    Changes staged for one entity, applied only once its checks are known:
    - `new`: a translation to create, if the upload matches none Pontoon has
    - `match`: the translation the upload matches, if Pontoon already has it
    - `match_action`: the action to log for `match`, if any
    - `reject_ids`: ids of the translations to reject
    - `deactivate_ids`: ids of the translations to leave in place, but deactivate
    - `read_state`: the review state of each of the entity's translations the change
      was decided on, as read, keyed by translation id
    - `check_results`: the `run_checks()` result of the uploaded translation
    """

    key: L10nId
    read_state: dict[int, tuple[bool, ...]]
    new: Translation | None = None
    match: Translation | None = None
    match_action: str | None = None
    reject_ids: list[int] = field(default_factory=list)
    deactivate_ids: list[int] = field(default_factory=list)
    check_results: dict[str, list[str]] = field(default_factory=dict)

    @property
    def translation(self) -> Translation:
        """The row holding the uploaded translation, whether created or matched."""
        return self.new or self.match


def lock_read_translations(applied: list[PendingChange]) -> None:
    """
    Lock the translations used to make a decision on the staged changes and
    check that none was changed since it was read.

    Waiting for the lock also waits for any concurrent transaction on these rows to
    commit, so their state as re-read here is the one the changes are written over.

    Raises `UploadConflictError` if the review state of any of them differs from the
    one read, or if one was deleted.
    """
    expected = {pk: state for p in applied for pk, state in p.read_state.items()}
    if not expected:
        return
    locked = (
        Translation.objects.select_for_update()
        .filter(pk__in=expected)
        .values_list("pk", *REVIEW_FIELDS)
    )
    current = {pk: state for pk, *state in locked}
    if len(current) != len(expected) or any(
        tuple(current[pk]) != state for pk, state in expected.items()
    ):
        raise UploadConflictError()


def run_staged_checks(
    pending: list[PendingChange], db_res: DbResource, locale: Locale
) -> None:
    """
    Run the quality checks on each staged translation, recording them on its
    `PendingChange` as `check_results`.

    Checks run before anything is written, so that a translation failing them
    can be left out, keeping the translation it would have replaced in place.

    The results are kept in memory rather than read back from the database
    after the write, as `run_checks()` also reports checks from libraries that
    `bulk_run_checks()` does not store.
    """
    if not pending:
        return

    entities = {
        entity.pk: entity
        for entity in Entity.objects.filter(
            pk__in={p.translation.entity_id for p in pending}
        )
    }
    if db_res.format == DbResource.Format.DTD:
        # compare-locales needs the other entities of the resource as a reference,
        # and reloads them for each check unless they are cached on `db_res`.
        prefetch_related_objects([db_res], "entities")

    for p in pending:
        entity = entities[p.translation.entity_id]
        entity.resource = db_res
        p.check_results = run_checks(entity, locale.code, p.translation.string, False)


def write_changes(
    project: Project,
    user: User,
    now: datetime,
    applied: list[PendingChange],
    *,
    match_fields: tuple[str, ...],
    mark_changed: bool,
) -> None:
    """
    Write the staged changes to the database, along with their check results,
    action log entries and stats. Must run inside a transaction.

    `match_fields` are the only fields saved for matched translations.
    `mark_changed` marks the written translations as changed for sync.

    Raises `UploadConflictError` if any translation the changes were decided on was
    reviewed or deleted after this import read it, and that change was committed first.
    """
    from pontoon.checks.models import Error, Warning

    lock_read_translations(applied)

    reject_ids = [pk for p in applied for pk in p.reject_ids]
    deactivate_ids = [pk for p in applied for pk in p.deactivate_ids]
    matched = [p.match for p in applied if p.match is not None]
    created = [p.new for p in applied if p.new is not None]

    actions: list[ActionLog] = []
    # Rejections and deactivations must be written before translations are activated,
    # to keep a single active translation per entity and locale.
    if reject_ids:
        rejected = Translation.objects.filter(pk__in=reject_ids)
        actions.extend(
            ActionLog(
                action_type=ActionLog.ActionType.TRANSLATION_REJECTED,
                created_at=now,
                performed_by=user,
                translation=tx,
                is_implicit_action=True,
            )
            for tx in rejected
        )
        # Only approved translations have TM entries, so there are none to remove here.
        rejected.update(
            active=False,
            rejected=True,
            rejected_user=user,
            rejected_date=now,
            pretranslated=False,
            fuzzy=False,
        )
    if deactivate_ids:
        Translation.objects.filter(pk__in=deactivate_ids).update(active=False)
    if matched:
        Translation.objects.bulk_update(matched, list(match_fields))
    if created:
        Translation.objects.bulk_create(created)

    actions.extend(
        ActionLog(
            action_type=ActionLog.ActionType.TRANSLATION_CREATED,
            created_at=now,
            performed_by=user,
            translation=tx,
        )
        for tx in created
    )
    actions.extend(
        ActionLog(
            action_type=p.match_action,
            created_at=now,
            performed_by=user,
            translation=p.match,
        )
        for p in applied
        if p.match is not None and p.match_action is not None
    )
    if actions:
        ActionLog.objects.bulk_create(actions)

    # Failed checks must be stored before stats are updated (bug 1521606).
    matched_ids = [tx.pk for tx in matched]
    if matched_ids:
        # The checks stored for a matched translation were run when it was written, and
        # may predate a change to the source string or to the checks themselves. Only
        # the results just computed describe it, so the stored ones are replaced.
        Warning.objects.filter(translation_id__in=matched_ids).delete()
        Error.objects.filter(translation_id__in=matched_ids).delete()
    warnings, errors = [], []
    for p in applied:
        if p.check_results:
            p_warnings, p_errors = get_failed_checks_db_objects(
                p.translation, p.check_results
            )
            warnings += p_warnings
            errors += p_errors
    if warnings:
        Warning.objects.bulk_create(warnings)
    if errors:
        Error.objects.bulk_create(errors)

    if created:
        # bulk_create() skips Translation.save(), which would do this
        created[0].update_latest_translation()

    changed_pks = [tx.pk for tx in created + matched]
    if changed_pks or reject_ids:
        update_stats(project)
        if mark_changed:
            Translation.objects.filter(
                pk__in=reject_ids + changed_pks
            ).bulk_mark_changed()


@dataclass
class PretranslationUploadResult:
    """
    Summary of an uploaded pretranslation file import:
    - `created`: number of pretranslations added for strings with
      no pretranslation or fuzzy translation
    - `replaced`: number of pretranslations replacing a previous,
      different pretranslation or fuzzy translation
    - `converted`: number of existing translations made the
      active pretranslation, as they match the uploaded translation
    - `unchanged`: number of translations identical to the current pretranslation
    - `skipped`: number of strings left untouched, because they have
      an approved translation or are marked as fuzzy in the uploaded file
    - `failed_checks`: keys of the strings left untouched because the uploaded
      translation fails checks, with the errors and warnings reported for each of them
    - `undefined_keys`: keys of translations with no matching entity in Pontoon
    """

    created: int = 0
    replaced: int = 0
    converted: int = 0
    unchanged: int = 0
    skipped: int = 0
    failed_checks: list[FailedCheck] = field(default_factory=list)
    undefined_keys: list[L10nId] = field(default_factory=list)


def import_uploaded_pretranslations(
    project: Project,
    locale: Locale,
    db_res: DbResource,
    upload: File,
    user: User,
) -> PretranslationUploadResult:
    """
    Store translations from an uploaded file in the database as pretranslations.

    Strings with an approved translation are skipped, so that reviewed translations are
    never replaced. Unlike the built-in pretranslation, strings with unreviewed
    suggestions are pretranslated: a suggestion matching the uploaded translation is
    marked as a pretranslation, keeping its original author, while other suggestions are
    kept as they are. A previous, different pretranslation or fuzzy translation is
    rejected, and a matching one is made the active pretranslation.

    Translations marked as fuzzy in the uploaded file are skipped.

    Uploaded translations that fail any quality check are left out, so that a broken
    translation never replaces a good one. A new pretranslation is not stored, a
    matching one is not converted, and the previous translation stays in place.

    Raises `UploadConflictError` if a translation of a targeted string was reviewed or
    deleted after this import read it, and that change was committed first.

    This does not reuse `update_db_translations()`, which has the same overall shape,
    but makes a different call at nearly every decision point:

    |                    | Sync from repo        | Pretranslation upload           |
    | ------------------ | --------------------- | ------------------------------- |
    | Approved           | replaced              | entity skipped                  |
    | Rejects others     | all                   | only pretranslated or fuzzy     |
    | Fuzzy in upload    | stored as fuzzy       | skipped                         |
    | Checks             | after write           | before write, failures dropped  |
    | TM entries         | created               | none                            |
    """
    result = PretranslationUploadResult()
    upload_translations, entities, result.undefined_keys = parse_upload_for_entities(
        locale, db_res, upload
    )
    current = translations_by_entity(
        locale, [entities[key] for key in upload_translations], include_rejected=False
    )

    now = timezone.now()
    pending: list[PendingChange] = []
    for key, rt in upload_translations.items():
        entity_id = entities[key]
        translations = current.get(entity_id, [])
        if rt.fuzzy or any(tx.approved for tx in translations):
            result.skipped += 1
            continue

        match = next(
            (
                tx
                for tx in translations
                if translations_equal(rt.value, rt.properties, tx.value, tx.properties)
            ),
            None,
        )
        if match is not None and match.pretranslated and match.active:
            result.unchanged += 1
            continue

        change = PendingChange(
            key=key, read_state=read_state(translations), match=match
        )
        for tx in translations:
            if tx is match:
                continue
            if tx.pretranslated or tx.fuzzy:
                change.reject_ids.append(tx.pk)
            elif tx.active:
                change.deactivate_ids.append(tx.pk)

        if match is None:
            change.new = build_translation(rt, entity_id, locale.pk, user, now)
            change.new.pretranslated = True
            change.new.active = True
        pending.append(change)

    run_staged_checks(pending, db_res, locale)

    applied: list[PendingChange] = []
    for p in pending:
        if are_blocking_checks(p.check_results, ignore_warnings=False):
            result.failed_checks.append(
                FailedCheck.from_check_results(p.key, p.check_results)
            )
        else:
            applied.append(p)

    for p in applied:
        if p.match is not None:
            result.converted += 1
            p.match.pretranslated = True
            p.match.fuzzy = False
            p.match.active = True
        elif p.reject_ids:
            result.replaced += 1
        else:
            result.created += 1

    write_changes(
        project,
        user,
        now,
        applied,
        match_fields=("active", "fuzzy", "pretranslated"),
        mark_changed=True,
    )
    return result


@dataclass
class SuggestionUploadResult:
    """
    Summary of an uploaded suggestion file import:
    - `created`: number of suggestions added
    - `restored`: number of rejected translations matching the upload that were
      un-rejected, becoming pending suggestions again
    - `unchanged`: number of uploaded translations that the string already has as an
      unrejected translation, in any review state
    - `failed_checks`: keys of the strings left untouched because the uploaded
      translation has errors, with the errors and warnings reported for each of them
    - `undefined_keys`: keys of translations with no matching entity in Pontoon
    """

    created: int = 0
    restored: int = 0
    unchanged: int = 0
    failed_checks: list[FailedCheck] = field(default_factory=list)
    undefined_keys: list[L10nId] = field(default_factory=list)


def import_uploaded_suggestions(
    project: Project,
    locale: Locale,
    db_res: DbResource,
    upload: File,
    user: User,
) -> SuggestionUploadResult:
    """
    Store translations from an uploaded file in the database as unreviewed suggestions.

    Nothing already in Pontoon is replaced or rejected: every uploaded translation is
    stored as a suggestion, unless the string already has an unrejected translation
    with the same value, whether approved, pretranslated or unreviewed. The fuzzy flag
    of the uploaded file is ignored, the translation is stored as a plain suggestion.

    A rejected translation matching the upload is un-rejected instead of suggested
    again, so that a translation rejected by mistake can be re-proposed.

    Uploaded translations reported with errors are left out, as the editor rejects them
    as well. Translations with warnings are stored, with their warnings, as a reviewer
    can still accept them.

    Raises `UploadConflictError` if a translation of a targeted string was reviewed or
    deleted after this import read it, and that change was committed first.
    """
    result = SuggestionUploadResult()
    upload_translations, entities, result.undefined_keys = parse_upload_for_entities(
        locale, db_res, upload
    )
    # Rejected translations are read as well, to be restored rather than duplicated.
    current = translations_by_entity(
        locale, [entities[key] for key in upload_translations], include_rejected=True
    )

    now = timezone.now()
    pending: list[PendingChange] = []
    for key, rt in upload_translations.items():
        entity_id = entities[key]
        translations = current.get(entity_id, [])
        matches = [
            tx
            for tx in translations
            if translations_equal(rt.value, rt.properties, tx.value, tx.properties)
        ]
        if any(not tx.rejected for tx in matches):
            result.unchanged += 1
            continue

        change = PendingChange(key=key, read_state=read_state(translations))
        if matches:
            # Restore the rejected translation, keeping its author and date.
            change.match = max(matches, key=lambda tx: tx.date)
            change.match.rejected = False
            change.match.unrejected_user = user
            change.match.unrejected_date = now
            change.match_action = ActionLog.ActionType.TRANSLATION_UNREJECTED
            suggestion = change.match
        else:
            change.new = build_translation(rt, entity_id, locale.pk, user, now)
            suggestion = change.new

        # The suggestion is the active translation of its string unless another
        # unrejected translation takes precedence.
        others = [
            tx for tx in translations if tx is not change.match and not tx.rejected
        ]
        suggestion.active = not any(
            tx.approved or tx.pretranslated or tx.fuzzy or tx.date > suggestion.date
            for tx in others
        )
        if suggestion.active:
            change.deactivate_ids = [tx.pk for tx in others if tx.active]
        pending.append(change)

    run_staged_checks(pending, db_res, locale)

    applied: list[PendingChange] = []
    for p in pending:
        if are_blocking_checks(p.check_results, ignore_warnings=True):
            result.failed_checks.append(
                FailedCheck.from_check_results(p.key, p.check_results)
            )
        else:
            applied.append(p)
    result.restored = sum(1 for p in applied if p.match is not None)
    result.created = len(applied) - result.restored

    write_changes(
        project,
        user,
        now,
        applied,
        match_fields=("active", "rejected", "unrejected_user", "unrejected_date"),
        mark_changed=False,
    )
    return result
