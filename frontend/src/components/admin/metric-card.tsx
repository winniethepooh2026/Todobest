export function MetricCard({
  label,
  value,
  caption,
  icon: Icon,
}: {
  label: string;
  value: React.ReactNode;
  caption?: React.ReactNode;
  icon: React.ElementType;
}) {
  return (
    <div className="rounded-2xl border bg-card p-5">
      <div className="flex items-center justify-between">
        <span className="text-sm text-muted-foreground">{label}</span>
        <Icon className="size-4 text-neutral-400" />
      </div>
      <div className="mt-6 text-2xl font-semibold tracking-tight">{value}</div>
      {caption ? (
        <div className="mt-1 text-xs text-muted-foreground">{caption}</div>
      ) : null}
    </div>
  );
}
