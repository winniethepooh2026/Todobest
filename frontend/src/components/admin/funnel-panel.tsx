import { Panel, PanelEmpty } from "@/components/admin/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { formatCount, formatPct } from "@/lib/format";
import type { AdminFunnelStep } from "@/lib/types";

export function FunnelPanel({
  steps,
  loading,
}: {
  steps: AdminFunnelStep[] | undefined;
  loading: boolean;
}) {
  const maxCount = Math.max(1, steps?.[0]?.count ?? 0);

  return (
    <Panel title="Воронка онбординга">
      {loading || !steps ? (
        <Skeleton className="h-40" />
      ) : steps.length === 0 ? (
        <PanelEmpty>Нет данных.</PanelEmpty>
      ) : (
        <div className="flex flex-col gap-3">
          {steps.map((step, index) => {
            const widthPct = (step.count / maxCount) * 100;
            const prevCount = index > 0 ? steps[index - 1].count : null;
            const fromPrevPct =
              prevCount && prevCount > 0 ? (step.count / prevCount) * 100 : null;

            return (
              <div key={step.label} className="flex items-center gap-3">
                <div className="w-40 shrink-0 truncate text-xs text-muted-foreground md:w-48">
                  {step.label}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="relative isolate h-8 overflow-hidden rounded-lg bg-neutral-100 dark:bg-neutral-800">
                    <div
                      className="absolute inset-y-0 left-0 rounded-lg bg-neutral-900 transition-[width] duration-500 dark:bg-neutral-100"
                      style={{ width: `${widthPct}%` }}
                    />
                    <span className="absolute inset-y-0 left-3 z-10 flex items-center text-xs font-medium text-white mix-blend-difference">
                      {formatCount(step.count)}
                    </span>
                  </div>
                </div>
                <div className="w-12 shrink-0 text-right text-xs text-muted-foreground">
                  {fromPrevPct !== null ? formatPct(fromPrevPct) : null}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </Panel>
  );
}
