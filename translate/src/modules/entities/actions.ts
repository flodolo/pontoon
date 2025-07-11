import {
  Entity,
  EntitySiblings,
  fetchEntities,
  fetchSiblingEntities,
} from '~/api/entity';
import { EntityTranslation } from '~/api/translation';
import { logUXAction } from '~/api/uxaction';
import { Location } from '~/context/Location';
import { updateStats } from '~/modules/stats/actions';
import type { AppDispatch } from '~/store';

export const RECEIVE_ENTITIES = 'entities/RECEIVE';
export const REQUEST_ENTITIES = 'entities/REQUEST';
export const RESET_ENTITIES = 'entities/RESET';
export const UPDATE_ENTITIES = 'entities/UPDATE';
export const RECEIVE_ENTITY_SIBLINGS = 'entities/RECEIVE_SIBLINGS';

/** Indicate that entities are currently being fetched.  */
type RequestAction = {
  type: typeof REQUEST_ENTITIES;
};

/** Update entities to a new set.  */
type ReceiveAction = {
  type: typeof RECEIVE_ENTITIES;
  entities: Entity[];
  hasMore: boolean;
};

/** Update the siblings of an entity.  */
type ReceiveSiblingsAction = {
  type: typeof RECEIVE_ENTITY_SIBLINGS;
  siblings: EntitySiblings;
  entity: number;
};

type ResetAction = {
  type: typeof RESET_ENTITIES;
};

/** Update the active translation of an entity.  */
type UpdateAction = {
  type: typeof UPDATE_ENTITIES;
  entity: number;
  translation: EntityTranslation;
};

export type Action =
  | ReceiveAction
  | ReceiveSiblingsAction
  | RequestAction
  | ResetAction
  | UpdateAction;

export const resetEntities = (): ResetAction => ({ type: RESET_ENTITIES });

export const updateEntityTranslation = (
  entity: number,
  translation: EntityTranslation,
): UpdateAction => ({ type: UPDATE_ENTITIES, entity, translation });

/** Fetch entities and their translation.  */
export const getEntities =
  (location: Location, page: number) => async (dispatch: AppDispatch) => {
    dispatch({ type: REQUEST_ENTITIES });

    const content = await fetchEntities(location, page);
    const {
      search,
      search_exclude_source_strings,
      search_identifiers,
      search_match_case,
      search_match_whole_word,
      search_rejected_translations,
    } = location;

    if (search) {
      logUXAction(
        'Load: String list with search parameter',
        'Search Options Statistics',
        {
          search_exclude_source_strings: search_exclude_source_strings,
          search_identifiers: search_identifiers,
          search_match_case: search_match_case,
          search_match_whole_word: search_match_whole_word,
          search_rejected_translations: search_rejected_translations,
        },
      );
    }

    if (content.entities) {
      dispatch({
        type: RECEIVE_ENTITIES,
        entities: content.entities,
        hasMore: content.has_next,
      });
      dispatch(updateStats(content.stats));
    }
  };

export const getSiblingEntities =
  (entity: number, locale: string) => async (dispatch: AppDispatch) => {
    const siblings = await fetchSiblingEntities(entity, locale);
    if (siblings) {
      dispatch({ type: RECEIVE_ENTITY_SIBLINGS, siblings, entity });
    }
  };
