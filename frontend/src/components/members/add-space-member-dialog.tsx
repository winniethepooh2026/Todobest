"use client";

import { useQueryClient } from "@tanstack/react-query";
import { Loader2, UserPlus } from "lucide-react";
import { FormEvent, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api } from "@/lib/api";
import type { Invitation, SpaceRole } from "@/lib/types";
import { formatError } from "@/lib/utils";

export function AddSpaceMemberDialog({
  spaceId,
  currentUserRole,
}: {
  spaceId: string;
  currentUserRole: SpaceRole;
}) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<SpaceRole>("member");
  const [loading, setLoading] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    try {
      const invitation = await api.post<Invitation>(
        `/spaces/${spaceId}/invitations`,
        {
          email,
          role,
        },
      );
      await queryClient.invalidateQueries({
        queryKey: ["space-members", spaceId],
      });
      setEmail("");
      setRole("member");
      setOpen(false);
      await queryClient.invalidateQueries({
        queryKey: ["invitations", spaceId],
      });
      toast.success("Приглашение отправлено");
      if (navigator.clipboard)
        void navigator.clipboard.writeText(invitation.invitation_url ?? "");
    } catch (error) {
      toast.error(formatError(error));
    } finally {
      setLoading(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button>
          <UserPlus className="size-4" />
          Добавить участника
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Пригласить в Space</DialogTitle>
          <DialogDescription>
            Письмо придёт и новому, и существующему пользователю. Ссылка также
            копируется в буфер обмена.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="space-y-5">
          <div className="space-y-2">
            <Label htmlFor={`member-email-${spaceId}`}>Email</Label>
            <Input
              id={`member-email-${spaceId}`}
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              placeholder="member@example.com"
              autoFocus
              required
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor={`member-role-${spaceId}`}>Роль</Label>
            <select
              id={`member-role-${spaceId}`}
              value={role}
              onChange={(event) => setRole(event.target.value as SpaceRole)}
              className="flex h-9 w-full rounded-lg border border-input bg-background px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <option value="member">Участник</option>
              <option value="admin">Администратор</option>
              {currentUserRole === "owner" ? (
                <option value="owner">Владелец</option>
              ) : null}
            </select>
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setOpen(false)}
            >
              Отмена
            </Button>
            <Button type="submit" disabled={loading}>
              {loading ? <Loader2 className="size-4 animate-spin" /> : null}
              Пригласить
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
