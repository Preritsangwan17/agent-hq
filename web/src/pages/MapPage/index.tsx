/** Map — foundation placeholder; a page agent replaces this module (default export only). */
import { Earth as PageIcon } from 'lucide-react';
import { PagePlaceholder } from '@/components';

export default function MapPage() {
  return (
    <PagePlaceholder
      title="Map"
      kicker="World"
      icon={PageIcon}
      color="#2DD4BF"
      description="An offline glowing world map (d3-geo + world-atlas) with pins sized by pay."
    />
  );
}
