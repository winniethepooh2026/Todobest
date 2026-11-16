import { Panel, PanelEmpty } from "@/components/admin/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { formatCount } from "@/lib/format";
import type { AdminRegistrationPoint } from "@/lib/types";

function formatDay(value: string): string {
  return new Date(value).toLocaleDateString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
  });
}

export function RegistrationsPanel({
  points,
  loading,
}: {
  points: AdminRegistrationPoint[] | undefined;
  loading: boolean;
}) {
  const total = points?.reduce((sum, point) => sum + point.count, 0) ?? 0;
  const maxCount = Math.max(1, ...(points?.map((point) => point.count) ?? [0]));

  return (
    <Panel
      title="Регистрации за 30 дней"
      action={
        points && points.length > 0 ? (
          <span className="text-xs text-muted-foreground">
            всего {formatCount(total)}
          </span>
        ) : null
      }
    >
      {loading || !points ? (
        <Skeleton className="h-40" />
      ) : points.length === 0 ? (
        <PanelEmpty>Нет данных.</PanelEmpty>
      ) : (
        <div className="flex h-40 items-end gap-[3px]">
          {points.map((point) => (
            <div
              key={point.date}
              title={`${formatDay(point.date)}: ${formatCount(point.count)}`}
              className="min-h-1 flex-1 rounded-t bg-neutral-900 transition-[height] hover:bg-neutral-600 dark:bg-neutral-100 dark:hover:bg-neutral-300"
              style={{ height: `${Math.max(4, (point.count / maxCount) * 100)}%` }}
            />
          ))}
        </div>
      )}
    </Panel>
  );
}
