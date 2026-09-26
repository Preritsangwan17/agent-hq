/** Settings — foundation placeholder; a page agent replaces this module (default export only). */
import { Settings as PageIcon } from 'lucide-react';
import { PagePlaceholder } from '@/components';

export default function Settings() {
  return (
    <PagePlaceholder
      title="Settings"
      kicker="Rules & safety"
      icon={PageIcon}
      color="#8B95A7"
      description="Rules, autonomy & mode, budget, schedules, sources, profile & facts, security."
    />
  );
}
