import { cva, type VariantProps } from "class-variance-authority";
import * as React from "react";

import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center rounded-md px-2 py-0.5 text-[11px] font-medium",
  {
    variants: {
      variant: {
        default: "bg-neutral-900 text-white dark:bg-neutral-100 dark:text-neutral-950",
        secondary: "bg-neutral-100 text-neutral-600 dark:bg-neutral-800 dark:text-neutral-300",
        outline: "border bg-transparent text-neutral-600 dark:text-neutral-400 dark:border-neutral-700",
        warning: "bg-amber-50 text-amber-700 dark:bg-amber-950 dark:text-amber-300",
      },
    },
    defaultVariants: { variant: "secondary" },
  },
);

export function Badge({
  className,
  variant,
  ...props
}: React.HTMLAttributes<HTMLSpanElement> &
  VariantProps<typeof badgeVariants>) {
  return (
    <span className={cn(badgeVariants({ variant }), className)} {...props} />
  );
}

