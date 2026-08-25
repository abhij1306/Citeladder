import {
  BarChart3,
  Briefcase,
  Building2,
  Check,
  Eye,
  FileText,
  GitBranch,
  GraduationCap,
  Landmark,
  Lock,
  Newspaper,
  Search,
  ShieldCheck,
  ShoppingCart,
  TrendingUp,
  Zap,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';

import type { IconKey } from '@/lib/marketing-content/landing';

/**
 * Resolves the landing content's string icon keys to lucide components, so the
 * content module stays pure data and the sections share one icon vocabulary.
 */
export const LANDING_ICONS: Record<IconKey, LucideIcon> = {
  collect: Search,
  analyze: BarChart3,
  improve: Zap,
  verify: TrendingUp,
  education: GraduationCap,
  commerce: ShoppingCart,
  services: Briefcase,
  saas: Building2,
  media: Newspaper,
  finance: Landmark,
  isolation: Lock,
  provenance: ShieldCheck,
  correction: Check,
  versioned: GitBranch,
  ask: Search,
  prove: FileText,
  see: Eye,
};
