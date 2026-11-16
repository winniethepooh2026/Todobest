"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import type { Invitation } from "@/lib/types";
import { toast } from "sonner";
import { formatError } from "@/lib/utils";

export function PendingInvitations({ spaceId }: { spaceId: string }) {
  const client = useQueryClient();
  const query = useQuery({ queryKey: ["invitations", spaceId], queryFn: () => api.get<Invitation[]>(`/spaces/${spaceId}/invitations`) });
  const pending = (query.data ?? []).filter((item) => !item.accepted_at && !item.revoked_at && new Date(item.expires_at) > new Date());
  async function revoke(id: string) { try { await api.delete(`/invitations/${id}`); await client.invalidateQueries({ queryKey: ["invitations", spaceId] }); toast.success("Приглашение отозвано"); } catch (error) { toast.error(formatError(error)); } }
  if (!pending.length) return null;
  return <section className="mt-6 rounded-2xl border bg-card p-5"><h2 className="font-medium">Ожидают ответа</h2><div className="mt-3 divide-y">{pending.map((item) => <div key={item.id} className="flex items-center justify-between gap-4 py-3"><div><p className="text-sm font-medium">{item.email ?? "Приглашение по ссылке"}</p><p className="text-xs text-muted-foreground">{item.team_id ? "Team + Space" : "Space"} · {item.role}</p></div><Button size="sm" variant="outline" onClick={() => revoke(item.id)}>Отозвать</Button></div>)}</div></section>;
}
