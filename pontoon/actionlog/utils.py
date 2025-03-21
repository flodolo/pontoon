from pontoon.actionlog.models import ActionLog


def log_action(
    action_type,
    user,
    is_implicit_action=False,
    translation=None,
    entity=None,
    locale=None,
    tm_entries=None,
):
    """Save a new action in the database.

    :arg string action_type:
        The type of action that was performed.
        See models.ActionLog.ActionType for choices.
    :arg User user: The User who performed the action.
    :arg Translation translation: The Translation the action was performed on.
    :arg Entity entity:
        The Entity the action was performed on.
        Only used for the "translation:deleted", "tm_entries:deleted" and "comment:added" actions.
    :arg Locale locale:
        The Locale the action was performed on.
        Only used for the "translation:deleted", "tm_entries:deleted" and "comment:added" actions.
    :arg list tm_entries: A list of TranslationMemoryEntries the action was performed on.

    :returns: None
    """
    action = ActionLog(
        action_type=action_type,
        performed_by=user,
        translation=translation,
        entity=entity,
        locale=locale,
        is_implicit_action=is_implicit_action,
    )
    action.save()

    if tm_entries:
        action.tm_entries.set(tm_entries)
