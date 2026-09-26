/** Activity — foundation placeholder; a page agent replaces this module (default export only). */
import { SquareTerminal as PageIcon } from 'lucide-react';
import { PagePlaceholder } from '@/components';

export default function Activity() {
  return (
    <PagePlaceholder
      title="Activity"
      kicker="Terminal"
      icon={PageIcon}
      color="#A3E635"
      description="A virtualised JetBrains Mono terminal of every event with agent filters and a run drawer."
    />
  );
}
