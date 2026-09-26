/** Analytics — foundation placeholder; a page agent replaces this module (default export only). */
import { ChartColumn as PageIcon } from 'lucide-react';
import { PagePlaceholder } from '@/components';

export default function Analytics() {
  return (
    <PagePlaceholder
      title="Analytics"
      kicker="Trends"
      icon={PageIcon}
      color="#F472B6"
      description="Funnel, pay histogram and pay by country (Recharts)."
    />
  );
}
