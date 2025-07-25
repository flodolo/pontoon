import ftl from '@fluent/dedent';
import { createMemoryHistory } from 'history';
import React, { useContext } from 'react';
import { act } from 'react-dom/test-utils';

import { createReduxStore, mountComponentWithStore } from '~/test/store';
import { editMessageEntry, parseEntry } from '~/utils/message';

import {
  EditorActions,
  EditorData,
  EditorProvider,
  EditorResult,
} from './Editor';
import { EntityView, EntityViewProvider } from './EntityView';
import { Locale } from './Locale';
import { Location, LocationProvider } from './Location';

function mountSpy(Spy, format, translation) {
  const history = createMemoryHistory({
    initialEntries: [`/sl/pro/all/?string=42`],
  });

  const initialState = {
    entities: {
      entities: [
        {
          pk: 42,
          format,
          key: ['key'],
          original: 'key = test',
          translation: { string: translation, errors: [], warnings: [] },
          project: { contact: '' },
          comment: '',
        },
        {
          pk: 13,
          format: 'po',
          key: ['plural'],
          original:
            '.input {$n :number}\n.match $n\none {{orig one}}\n* {{orig other}}',
          translation: {
            string:
              '.input {$n :number}\n.match $n\none {{trans one}}\n* {{trans other}}',
            errors: [],
            warnings: [],
          },
          project: { contact: '' },
          comment: '',
        },
      ],
    },
    otherlocales: { translations: [] },
    user: {
      isAuthenticated: true,
      settings: { forceSuggestions: true },
      username: 'Franck',
    },
  };
  const store = createReduxStore(initialState);

  const Wrapper = () => (
    <LocationProvider history={history}>
      <Locale.Provider value={{ code: 'sl', cldrPlurals: [1, 2, 3, 5] }}>
        <EntityViewProvider>
          <EditorProvider>
            <Spy />
          </EditorProvider>
        </EntityViewProvider>
      </Locale.Provider>
    </LocationProvider>
  );
  return mountComponentWithStore(Wrapper, store, {}, history);
}

describe('<EditorProvider>', () => {
  it('provides a simple non-Fluent value', () => {
    let editor, result;
    const Spy = () => {
      editor = useContext(EditorData);
      result = useContext(EditorResult);
      return null;
    };
    mountSpy(Spy, 'simple', 'message');
    expect(editor).toMatchObject({
      sourceView: false,
      initial: { id: 'key', value: { type: 'message', pattern: ['message'] } },
      fields: [
        {
          id: '',
          keys: [],
          labels: [],
          name: '',
          handle: { current: { value: 'message' } },
        },
      ],
    });
    expect(result).toMatchObject([{ name: '', keys: [], value: 'message' }]);
  });

  it('provides a simple Fluent value', () => {
    let editor, result;
    const Spy = () => {
      editor = useContext(EditorData);
      result = useContext(EditorResult);
      return null;
    };
    mountSpy(Spy, 'ftl', 'key = message');
    expect(editor).toMatchObject({
      sourceView: false,
      initial: { id: 'key', value: { type: 'message', pattern: ['message'] } },
      fields: [
        {
          id: '',
          keys: [],
          labels: [],
          name: '',
          handle: { current: { value: 'message' } },
        },
      ],
    });
    expect(result).toMatchObject([{ name: '', keys: [], value: 'message' }]);
  });

  it('provides a rich Fluent value', () => {
    let editor, result;
    const Spy = () => {
      editor = useContext(EditorData);
      result = useContext(EditorResult);
      return null;
    };
    const source = ftl`
      key =
          { $var ->
              [one] ONE
             *[other] OTHER
          }

      `;
    mountSpy(Spy, 'ftl', source);

    const entry = parseEntry('ftl', source);
    const fields = editMessageEntry(entry).map((field) => ({
      ...field,
      handle: { current: { value: field.handle.current.value } },
    }));
    expect(editor).toMatchObject({ sourceView: false, initial: entry, fields });
    expect(result).toMatchObject([
      { name: '', keys: [{ type: 'literal', value: 'one' }], value: 'ONE' },
      { name: '', keys: [{ type: '*', value: 'other' }], value: 'OTHER' },
    ]);
  });

  it('provides a forced source Fluent value', () => {
    let editor, result;
    const Spy = () => {
      editor = useContext(EditorData);
      result = useContext(EditorResult);
      return null;
    };
    const source = '## comment\n';
    mountSpy(Spy, 'ftl', source);

    expect(editor).toMatchObject({
      sourceView: true,
      initial: {
        id: 'key',
        value: { type: 'message', pattern: ['## comment\n'] },
      },
      fields: [
        {
          handle: { current: { value: '## comment' } },
          id: '',
          keys: [],
          labels: [],
          name: '',
        },
      ],
    });
    expect(result).toMatchObject([{ name: '', keys: [], value: '## comment' }]);
  });

  it('updates state on entity change', () => {
    let editor, result, location, entity;
    const Spy = () => {
      editor = useContext(EditorData);
      result = useContext(EditorResult);
      location = useContext(Location);
      entity = useContext(EntityView).entity;
      return null;
    };
    const wrapper = mountSpy(Spy, 'simple', 'translated');

    act(() => location.push({ entity: 13 }));
    wrapper.update();

    expect(editor).toMatchObject({
      initial: parseEntry('po', entity.translation.string),
      fields: [
        { handle: { current: { value: 'trans one' } } },
        { handle: { current: { value: 'trans other' } } },
      ],
    });
    expect(result).toMatchObject([
      { value: 'trans one' },
      { value: 'trans other' },
    ]);
  });

  it('clears a rich Fluent value', () => {
    let editor, actions;
    const Spy = () => {
      editor = useContext(EditorData);
      actions = useContext(EditorActions);
      return null;
    };
    const source = ftl`
      key =
          { $var ->
              [one] ONE
             *[other] OTHER
          }
      `;
    const wrapper = mountSpy(Spy, 'ftl', source);
    act(() => actions.clearEditor());
    wrapper.update();

    expect(editor).toMatchObject({
      sourceView: false,
      fields: [
        {
          handle: { current: { value: '' } },
          id: '|one',
          keys: [{ type: 'literal', value: 'one' }],
          labels: [{ label: 'one', plural: true }],
          name: '',
        },
        {
          handle: { current: { value: '' } },
          id: '|other',
          keys: [{ type: '*', value: 'other' }],
          labels: [{ label: 'other', plural: true }],
          name: '',
        },
      ],
    });
  });

  it('sets editor from history', () => {
    let editor, result, actions;
    const Spy = () => {
      editor = useContext(EditorData);
      result = useContext(EditorResult);
      actions = useContext(EditorActions);
      return null;
    };
    const wrapper = mountSpy(Spy, 'ftl', `key = VALUE\n`);

    const source = ftl`
      key =
          { $var ->
              [one] ONE
             *[other] OTHER
          }
      `;
    act(() => actions.setEditorFromHistory(source));
    wrapper.update();

    expect(editor).toMatchObject({
      sourceView: false,
      fields: [
        {
          handle: { current: { value: 'ONE' } },
          id: '|one',
          keys: [{ type: 'literal', value: 'one' }],
          labels: [{ label: 'one', plural: true }],
          name: '',
        },
        {
          handle: { current: { value: 'OTHER' } },
          id: '|other',
          keys: [{ type: '*', value: 'other' }],
          labels: [{ label: 'other', plural: true }],
          name: '',
        },
      ],
    });
    expect(result).toMatchObject([
      { keys: [{ type: 'literal', value: 'one' }], name: '', value: 'ONE' },
      { keys: [{ type: '*', value: 'other' }], name: '', value: 'OTHER' },
    ]);
  });

  it('toggles Fluent source view', () => {
    let editor, result, actions;
    const Spy = () => {
      editor = useContext(EditorData);
      result = useContext(EditorResult);
      actions = useContext(EditorActions);
      return null;
    };
    const source = ftl`
      key =
          { $var ->
              [one] ONE
             *[other] OTHER
          }
      `;
    const wrapper = mountSpy(Spy, 'ftl', source);
    act(() => actions.toggleSourceView());
    wrapper.update();

    expect(editor).toMatchObject({
      sourceView: true,
      fields: [
        {
          handle: { current: { value: source } },
          id: '',
          keys: [],
          labels: [],
          name: '',
        },
      ],
    });
    expect(result).toMatchObject([{ keys: [], name: '', value: source }]);

    act(() => actions.toggleSourceView());
    wrapper.update();

    expect(editor).toMatchObject({ fields: [{}, {}], sourceView: false });
    expect(result).toMatchObject([
      { keys: [{ type: 'literal', value: 'one' }], name: '', value: 'ONE' },
      { keys: [{ type: '*', value: 'other' }], name: '', value: 'OTHER' },
    ]);
  });
});
