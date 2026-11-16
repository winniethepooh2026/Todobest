"use client";

import { Button } from "@/components/ui/button";
import { Menu } from "lucide-react";
import { useSidebar } from "@/components/layout/app-shell";

export function MobileMenuButton() {
  const { setMobileOpen } = useSidebar();

  return (
    <Button
      variant="outline"
      size="icon"
      onClick={() => setMobileOpen(true)}
      aria-label="Открыть меню"
      className="md:hidden"
    >
      <Menu className="size-4" />
    </Button>
  );
}
