/** Agents — foundation placeholder; a page agent replaces this module (default export only). */
import { Bot as PageIcon } from 'lucide-react';
import { PagePlaceholder } from '@/components';

export default function Agents() {
  return (
    <PagePlaceholder
      title="Agents"
      kicker="Manager"
      icon={PageIcon}
      color="#E879F9"
      description="Agent manager and the Add Agent wizard (adapter → identity → capabilities → schedule → live test)."
    />
  );
}
