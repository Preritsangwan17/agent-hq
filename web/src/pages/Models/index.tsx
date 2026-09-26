/** Models — foundation placeholder; a page agent replaces this module (default export only). */
import { Cpu as PageIcon } from 'lucide-react';
import { PagePlaceholder } from '@/components';

export default function Models() {
  return (
    <PagePlaceholder
      title="Models"
      kicker="Leaderboard"
      icon={PageIcon}
      color="#F59E0B"
      description="Local model leaderboard, memory bar and broken-model reasons (phase b)."
    />
  );
}
