/** Needs Prerit — foundation placeholder; a page agent replaces this module (default export only). */
import { HandHelping as PageIcon } from 'lucide-react';
import { PagePlaceholder } from '@/components';

export default function Needs() {
  return (
    <PagePlaceholder
      title="Needs Prerit"
      kicker="Your lane"
      icon={PageIcon}
      color="#FB923C"
      description="Pre-filled packs, decisions and alerts — each completable in under two minutes."
    />
  );
}
