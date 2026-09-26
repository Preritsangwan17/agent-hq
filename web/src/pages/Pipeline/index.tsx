/** Pipeline — foundation placeholder; a page agent replaces this module (default export only). */
import { SquareKanban as PageIcon } from 'lucide-react';
import { PagePlaceholder } from '@/components';

export default function Pipeline() {
  return (
    <PagePlaceholder
      title="Pipeline"
      kicker="Kanban"
      icon={PageIcon}
      color="#A78BFA"
      description="Columns from Found to Offer with a collapsed Filtered lane, pay on every card, pay sort/filter and audited display-only drag."
    />
  );
}
