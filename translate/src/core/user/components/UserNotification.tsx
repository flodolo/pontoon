import classNames from 'classnames';
import parse from 'html-react-parser';
import React, { useEffect, useRef, useState } from 'react';
import ReactTimeAgo from 'react-time-ago';

import { Linkify } from '~/core/linkify';

import './UserNotification.css';

type Props = {
  notification: Record<string, any>;
};

const Suggestion = ({ date, date_iso, description }: Props['notification']) => (
  <div className='item-content'>
    <span
      className='description'
      // We can safely use description as it is generated by the code.
      dangerouslySetInnerHTML={{ __html: description.content }}
    />

    <ReactTimeAgo
      className='timeago'
      date={new Date(date_iso)}
      title={`${date} UTC`}
    />
  </div>
);

const Comment = ({
  actor,
  date,
  date_iso,
  description,
  target,
  verb,
}: Props['notification']) => (
  <div className='item-content'>
    <span className='actor'>{actor.anchor}</span>

    <span className='verb'>
      <a href={target.url}>{verb}</a>
    </span>

    <span className='target'>{target.anchor}</span>

    <ReactTimeAgo
      className='timeago'
      date={new Date(date_iso)}
      title={`${date} UTC`}
    />

    <div className='message trim'>
      <Linkify properties={{ target: '_blank', rel: 'noopener noreferrer' }}>
        {
          /* We can safely parse description as it is
           *  sanitized when coming from the DB. See:
           *    - pontoon.base.forms.AddCommentForm(}
           *    - pontoon.base.forms.HtmlField()
           */
          parse(description.content)
        }
      </Linkify>
    </div>
  </div>
);

const Other = ({
  actor,
  date,
  date_iso,
  description,
  target,
  verb,
}: Props['notification']) => (
  <div className='item-content'>
    <span className='actor'>
      <a href={actor.url}>{actor.anchor}</a>
    </span>

    <span className='verb'>{verb}</span>

    {!target ? null : (
      <span className='target'>
        <a href={target.url}>{target.anchor}</a>
      </span>
    )}

    <ReactTimeAgo
      className='timeago'
      date={new Date(date_iso)}
      title={`${date} UTC`}
    />

    {description ? (
      <div
        className='message'
        // We can safely use description as it is either generated
        // by the code or sanitized when coming from the DB. See:
        //   - pontoon.projects.forms.NotificationsForm()
        //   - pontoon.base.forms.HtmlField()
        dangerouslySetInnerHTML={{ __html: description.content }}
      />
    ) : null}
  </div>
);

/**
 * Renders a single notification in the notifications menu.
 */
export function UserNotification({
  notification,
}: Props): React.ReactElement<'li'> {
  const [markAsRead, setMarkAsRead] = useState(false);
  const mounted = useRef(false);

  const { description, id, level, unread, verb } = notification;

  useEffect(() => {
    if (mounted.current) setMarkAsRead(true);
    else mounted.current = true;
  }, [unread]);

  const content = description?.content;
  const isSuggestion =
    (typeof content === 'string' &&
      content.startsWith('Unreviewed suggestions')) ||
    verb === 'has reviewed suggestions';
  const isComment: boolean = description?.is_comment ?? false;

  const className = classNames(
    'user-notification',
    isSuggestion && 'suggestion',
    unread ? 'unread' : markAsRead && 'read',
  );

  return (
    <li className={className} data-id={id} data-level={level}>
      {isSuggestion ? (
        <Suggestion {...notification} />
      ) : isComment ? (
        <Comment {...notification} />
      ) : (
        <Other {...notification} />
      )}
    </li>
  );
}