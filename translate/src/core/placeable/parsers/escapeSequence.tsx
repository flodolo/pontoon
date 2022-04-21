import * as React from 'react';
import { Localized } from '@fluent/react';

/**
 * Marks the escape character "\".
 */
const escapeSequence = {
  rule: '\\',
  tag: (x: string): React.ReactElement<React.ElementType> => {
    return (
      <Localized id='placeable-parser-escapeSequence' attrs={{ title: true }}>
        <mark className='placeable' title='Escape sequence' dir='ltr'>
          {x}
        </mark>
      </Localized>
    );
  },
};

export default escapeSequence;