/** Placeholder body for page modules that a page agent has not built yet. */
import type { LucideIcon } from 'lucide-react';
import type { ReactNode } from 'react';
import { EmptyState } from './EmptyState';
import { GlassPanel } from './GlassPanel';
import { SectionHeader } from './SectionHeader';

export interface PagePlaceholderProps {
  title: string;
  kicker?: string;
  icon: LucideIcon;
  color?: string;
  description: ReactNode;
  children?: ReactNode;
}

export function PagePlaceholder({ title, kicker, icon, color = '#22D3EE', description, children }: PagePlaceholderProps) {
  return (
    <div className="space-y-5">
      <SectionHeader as="h1" size="lg" title={title} kicker={kicker} />
      {children}
      <GlassPanel glow={color} accentTop>
        <EmptyState icon={icon} color={color} title={`${title} is on its way`} hint={description} />
      </GlassPanel>
    </div>
  );
}
