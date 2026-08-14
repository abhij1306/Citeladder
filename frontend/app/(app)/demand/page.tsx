import { DemandProjection } from '@/components/demand/demand-projection';
import { TooltipProvider } from '@/components/ui/tooltip';

export default function DemandPage() {
  return (
    <TooltipProvider>
      <DemandProjection />
    </TooltipProvider>
  );
}
