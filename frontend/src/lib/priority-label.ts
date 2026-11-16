import type { TaskPriority } from "@/lib/types";

export const priorityLabel: Record<TaskPriority, string> = {
  none: "Без приоритета",
  low: "Низкий",
  medium: "Средний",
  high: "Высокий",
  urgent: "Срочный",
};
