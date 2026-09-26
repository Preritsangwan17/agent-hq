/** Inbox — foundation placeholder; a page agent replaces this module (default export only). */
import { Inbox as PageIcon } from 'lucide-react';
import { PagePlaceholder } from '@/components';

export default function Inbox() {
  return (
    <PagePlaceholder
      title="Inbox"
      kicker="Replies"
      icon={PageIcon}
      color="#60A5FA"
      description="Classified replies with notify-only locks and interview/offer banners (phase d)."
    />
  );
}
