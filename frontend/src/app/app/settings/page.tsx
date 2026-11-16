"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Check,
  Copy,
  KeyRound,
  Loader2,
  MailWarning,
  MapPin,
  MonitorSmartphone,
  Pencil,
  ShieldCheck,
  Trash2,
} from "lucide-react";
import { FormEvent, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { toast } from "sonner";

import { MobileMenuButton } from "@/components/layout/mobile-menu-button";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { UserAvatar } from "@/components/ui/user-avatar";
import {
  api,
  createApiToken,
  getApiTokens,
  googleLoginUrl,
  revokeApiToken,
} from "@/lib/api";
import type { ApiTokenCreated, User } from "@/lib/types";
import { formatError } from "@/lib/utils";

interface UserSession {
  id: string;
  user_agent: string | null;
  ip_address: string | null;
  created_at: string;
  last_seen_at: string | null;
  expires_at: string;
  current: boolean;
}

function sessionDevice(agent: string | null): string {
  if (!agent) return "Неизвестное устройство";
  const browser = agent.includes("Edg/") ? "Edge" : agent.includes("Firefox/") ? "Firefox" : agent.includes("Chrome/") ? "Chrome" : agent.includes("Safari/") ? "Safari" : "Браузер";
  const system = agent.includes("Android") ? "Android" : agent.includes("iPhone") || agent.includes("iPad") ? "iOS" : agent.includes("Windows") ? "Windows" : agent.includes("Mac OS") ? "macOS" : agent.includes("Linux") ? "Linux" : "устройство";
  return `${browser} · ${system}`;
}

const MAX_BIO_LENGTH = 280;
const MAX_TOKEN_NAME_LENGTH = 80;

export default function SettingsPage() {
  const queryClient = useQueryClient();
  const router = useRouter();
  const { data: user } = useQuery({
    queryKey: ["me"],
    queryFn: () => api.get<User>("/users/me"),
  });

  const {
    data: tokens,
    isLoading: tokensLoading,
    refetch: refetchTokens,
  } = useQuery({
    queryKey: ["api-tokens"],
    queryFn: getApiTokens,
  });

  const { data: sessions, isLoading: sessionsLoading } = useQuery({
    queryKey: ["sessions"],
    queryFn: () => api.get<UserSession[]>("/auth/sessions"),
  });
  const [revokingSessionId, setRevokingSessionId] = useState<string | null>(null);

  async function revokeSession(session: UserSession) {
    setRevokingSessionId(session.id);
    try {
      await api.delete(`/auth/sessions/${session.id}`);
      if (session.current) {
        router.replace("/login");
        router.refresh();
      } else {
        await queryClient.invalidateQueries({ queryKey: ["sessions"] });
        toast.success("Сеанс завершён");
      }
    } catch (error) {
      toast.error(formatError(error));
    } finally {
      setRevokingSessionId(null);
    }
  }

  const [totpPassword, setTotpPassword] = useState("");
  const [totpSetup, setTotpSetup] = useState<{ secret: string; otpauth_uri: string } | null>(null);
  const [totpCode, setTotpCode] = useState("");
  const [recoveryCodes, setRecoveryCodes] = useState<string[] | null>(null);
  const [totpLoading, setTotpLoading] = useState(false);

  async function startTotp(event: FormEvent) {
    event.preventDefault();
    setTotpLoading(true);
    try {
      const result = await api.post<{ secret: string; otpauth_uri: string }>(
        "/auth/totp/setup", { password: totpPassword },
      );
      setTotpSetup(result);
      setTotpPassword("");
    } catch (error) {
      toast.error(formatError(error));
    } finally {
      setTotpLoading(false);
    }
  }

  async function confirmTotp(event: FormEvent) {
    event.preventDefault();
    setTotpLoading(true);
    try {
      const result = await api.post<{ recovery_codes: string[] }>(
        "/auth/totp/confirm", { code: totpCode },
      );
      setRecoveryCodes(result.recovery_codes);
      setTotpSetup(null);
      setTotpCode("");
      toast.success("Двухфакторная защита включена");
    } catch (error) {
      toast.error(formatError(error));
    } finally {
      setTotpLoading(false);
    }
  }

  async function disableTotp(event: FormEvent) {
    event.preventDefault();
    setTotpLoading(true);
    try {
      await api.post("/auth/totp/disable", { code: totpCode });
      router.replace("/login");
      router.refresh();
    } catch (error) {
      toast.error(formatError(error));
    } finally {
      setTotpLoading(false);
    }
  }

  const [oldPassword, setOldPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [passwordLoading, setPasswordLoading] = useState(false);
  const [timezoneLoading, setTimezoneLoading] = useState(false);
  const [verificationLoading, setVerificationLoading] = useState(false);
  const [reauthLoading, setReauthLoading] = useState(false);
  const [googleReauth, setGoogleReauth] = useState(false);
  const browserTimezone = Intl.DateTimeFormat().resolvedOptions().timeZone;

  const [editingName, setEditingName] = useState(false);
  const [nameDraft, setNameDraft] = useState("");
  const [nameLoading, setNameLoading] = useState(false);

  const [bioDraft, setBioDraft] = useState("");
  const [bioLoading, setBioLoading] = useState(false);
  const [bioTouched, setBioTouched] = useState(false);

  const [createTokenName, setCreateTokenName] = useState("");
  const [createTokenScope, setCreateTokenScope] = useState<"read" | "write">(
    "write",
  );
  const [createTokenDays, setCreateTokenDays] = useState("90");
  const [createTokenLoading, setCreateTokenLoading] = useState(false);
  const [createTokenError, setCreateTokenError] = useState<string | null>(null);
  const [createdToken, setCreatedToken] = useState<ApiTokenCreated | null>(
    null,
  );
  const [revokingId, setRevokingId] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const [confirmRevokeId, setConfirmRevokeId] = useState<string | null>(null);
  const [revokeConfirmName, setRevokeConfirmName] = useState("");
  const [deleteEmail, setDeleteEmail] = useState("");
  const [deletingAccount, setDeletingAccount] = useState(false);

  async function deleteAccount(event: FormEvent) {
    event.preventDefault();
    setDeletingAccount(true);
    try {
      await api.delete("/users/me", { email: deleteEmail });
      router.replace("/");
      router.refresh();
    } catch (error) {
      toast.error(formatError(error));
    } finally {
      setDeletingAccount(false);
    }
  }

  const [lastSyncedUser, setLastSyncedUser] = useState<User | null>(null);
  if (user && lastSyncedUser !== user) {
    setLastSyncedUser(user);
    if (!editingName) setNameDraft(user.name);
    if (!bioTouched) setBioDraft(user.bio ?? "");
  }

  const sortedTokens = useMemo(
    () =>
      tokens
        ? [...tokens].sort(
            (a, b) =>
              new Date(b.created_at).getTime() -
              new Date(a.created_at).getTime(),
          )
        : [],
    [tokens],
  );

  async function commitName() {
    const trimmed = nameDraft.trim();
    if (!trimmed || trimmed === user?.name) {
      setEditingName(false);
      return;
    }
    setNameLoading(true);
    try {
      await api.patch<User>("/users/me", { name: trimmed });
      await queryClient.invalidateQueries({ queryKey: ["me"] });
      setEditingName(false);
      toast.success("Имя обновлено");
    } catch (error) {
      toast.error(formatError(error));
    } finally {
      setNameLoading(false);
    }
  }

  function submitName(event: FormEvent) {
    event.preventDefault();
    void commitName();
  }

  async function saveBio() {
    setBioLoading(true);
    try {
      await api.patch<User>("/users/me", { bio: bioDraft.trim() });
      await queryClient.invalidateQueries({ queryKey: ["me"] });
      setBioTouched(false);
      toast.success("Описание обновлено");
    } catch (error) {
      toast.error(formatError(error));
    } finally {
      setBioLoading(false);
    }
  }

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get("password_setup") === "ready") {
      queueMicrotask(() => {
        setGoogleReauth(true);
      });
      params.delete("password_setup");
      const query = params.toString();
      window.history.replaceState(
        window.history.state,
        "",
        `${window.location.pathname}${query ? `?${query}` : ""}${window.location.hash}`,
      );
    }
  }, []);

  async function changePassword(event: FormEvent) {
    event.preventDefault();
    setPasswordLoading(true);
    try {
      await api.post<{ message: string }>("/users/me/change-password", {
        old_password: user?.has_password ? oldPassword : null,
        new_password: newPassword,
        new_password_confirm: confirm,
      });
      setOldPassword("");
      setNewPassword("");
      setConfirm("");
      await queryClient.invalidateQueries({ queryKey: ["me"] });
      toast.success("Пароль изменён");
    } catch (error) {
      toast.error(formatError(error));
    } finally {
      setPasswordLoading(false);
    }
  }

  async function updateTimezone() {
    setTimezoneLoading(true);
    try {
      await api.patch<User>("/users/me", { timezone: browserTimezone });
      await queryClient.invalidateQueries({ queryKey: ["me"] });
      toast.success("Часовой пояс обновлён");
    } catch (error) {
      toast.error(formatError(error));
    } finally {
      setTimezoneLoading(false);
    }
  }

  async function sendVerificationEmail() {
    setVerificationLoading(true);
    try {
      await api.post<{ message: string }>("/auth/send-verification-email");
      toast.success("Письмо для подтверждения отправлено");
    } catch (error) {
      toast.error(formatError(error));
    } finally {
      setVerificationLoading(false);
    }
  }

  function initiateGoogleReauth() {
    setReauthLoading(true);
    window.location.href = googleLoginUrl("set_password");
  }

  async function submitCreateToken(event: FormEvent) {
    event.preventDefault();
    const trimmedName = createTokenName.trim();
    if (!trimmedName) {
      setCreateTokenError("Укажите название токена");
      return;
    }
    if (trimmedName.length > MAX_TOKEN_NAME_LENGTH) {
      setCreateTokenError("Название слишком длинное");
      return;
    }
    const expiresInDays = Math.max(
      1,
      Math.min(365, Number(createTokenDays) || 90),
    );

    setCreateTokenLoading(true);
    setCreateTokenError(null);
    try {
      const created = await createApiToken({
        name: trimmedName,
        scopes: [createTokenScope],
        expires_in_days: expiresInDays,
      });
      setCreatedToken(created);
      setCreateTokenName("");
      setCreateTokenScope("write");
      setCreateTokenDays("90");
      await refetchTokens();
      toast.success("Токен создан");
    } catch (error) {
      const message = formatError(error);
      setCreateTokenError(message);
      toast.error(message);
    } finally {
      setCreateTokenLoading(false);
    }
  }

  async function handleRevoke() {
    if (!confirmRevokeId) return;
    const expected = revokeConfirmName.trim();
    const token = sortedTokens.find((item) => item.id === confirmRevokeId);
    if (!token || expected !== token.name) {
      toast.error("Введите точное название токена");
      return;
    }

    setRevokingId(confirmRevokeId);
    try {
      await revokeApiToken(confirmRevokeId);
      await refetchTokens();
      toast.success("Токен отозван");
      setConfirmRevokeId(null);
      setRevokeConfirmName("");
    } catch (error) {
      toast.error(formatError(error));
    } finally {
      setRevokingId(null);
    }
  }

  async function copyCreatedToken() {
    if (!createdToken?.token) return;
    await navigator.clipboard.writeText(createdToken.token);
    setCopied(true);
    toast.success("Токен скопирован");
    setTimeout(() => setCopied(false), 2000);
  }

  function maskPrefix(prefix: string) {
    if (!prefix) return "";
    return prefix.length > 8 ? `${prefix.slice(0, 8)}...` : prefix;
  }

  return (
    <div className="mx-auto max-w-3xl px-6 py-12 md:px-10 md:py-16">
      <div className="flex items-center gap-2 md:hidden mb-4">
        <MobileMenuButton />
        <span className="text-sm font-medium">Настройки</span>
      </div>
      <p className="text-sm text-muted-foreground">Аккаунт</p>
      <h1 className="mt-1 text-3xl font-semibold tracking-[-0.035em]">
        Settings
      </h1>

      <section className="mt-10 rounded-2xl border bg-card p-6">
        {user ? (
          <div className="flex flex-col gap-5 sm:flex-row sm:items-start">
            <UserAvatar
              user={user}
              size="xl"
              tone="subtle"
              className="shrink-0"
            />
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                {editingName ? (
                  <form
                    onSubmit={submitName}
                    className="flex items-center gap-2"
                  >
                    <Input
                      autoFocus
                      value={nameDraft}
                      onChange={(event) => setNameDraft(event.target.value)}
                      onBlur={() => void commitName()}
                      minLength={2}
                      maxLength={80}
                      className="h-8 w-56"
                      disabled={nameLoading}
                    />
                    {nameLoading ? (
                      <Loader2 className="size-4 shrink-0 animate-spin text-muted-foreground" />
                    ) : null}
                  </form>
                ) : (
                  <button
                    type="button"
                    onClick={() => setEditingName(true)}
                    className="group/name flex items-center gap-1.5 truncate text-lg font-semibold"
                  >
                    <span className="truncate">{user.name}</span>
                    <Pencil className="size-3.5 shrink-0 text-muted-foreground opacity-0 transition group-hover/name:opacity-100" />
                  </button>
                )}
                <Badge
                  variant={user.google_connected ? "default" : "secondary"}
                >
                  {user.google_connected ? "Google" : "Локальный аккаунт"}
                </Badge>
              </div>
              <p className="mt-1 truncate text-sm text-muted-foreground">
                {user.email}
              </p>

              {!user.email_verified ? (
                <div className="mt-4 flex flex-col gap-3 rounded-xl border border-amber-300 bg-amber-50 p-4 text-amber-950 sm:flex-row sm:items-center sm:justify-between dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-100">
                  <div className="flex items-start gap-3">
                    <MailWarning className="mt-0.5 size-5 shrink-0" />
                    <div>
                      <p className="text-sm font-medium">
                        Email не подтверждён
                      </p>
                      <p className="mt-1 text-xs leading-5 opacity-80">
                        Подтвердите адрес, чтобы не потерять доступ к аккаунту.
                      </p>
                    </div>
                  </div>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    className="shrink-0 bg-background"
                    onClick={sendVerificationEmail}
                    disabled={verificationLoading}
                  >
                    {verificationLoading ? (
                      <Loader2 className="size-3.5 animate-spin" />
                    ) : null}
                    Отправить письмо
                  </Button>
                </div>
              ) : null}

              <div className="mt-4 space-y-2">
                <Label htmlFor="bio">О себе</Label>
                <Textarea
                  id="bio"
                  value={bioDraft}
                  onChange={(event) => {
                    setBioTouched(true);
                    setBioDraft(event.target.value.slice(0, MAX_BIO_LENGTH));
                  }}
                  placeholder="Пара слов о себе, роль, интересы…"
                  rows={2}
                  className="resize-none"
                />
                <div className="flex items-center justify-between">
                  <span className="text-xs text-muted-foreground">
                    {bioDraft.length}/{MAX_BIO_LENGTH}
                  </span>
                  {bioTouched && bioDraft.trim() !== (user.bio ?? "") ? (
                    <Button
                      type="button"
                      size="sm"
                      onClick={saveBio}
                      disabled={bioLoading}
                    >
                      {bioLoading ? (
                        <Loader2 className="size-3.5 animate-spin" />
                      ) : null}
                      Сохранить
                    </Button>
                  ) : null}
                </div>
              </div>
            </div>
          </div>
        ) : (
          <div className="flex items-center gap-5">
            <Skeleton className="size-20 rounded-full" />
            <div className="flex-1">
              <Skeleton className="h-6 w-40" />
              <Skeleton className="mt-2 h-4 w-56" />
            </div>
          </div>
        )}
      </section>

      <section className="mt-6 rounded-2xl border bg-card">
        <div className="flex items-start gap-3 border-b p-6">
          <div className="flex size-9 items-center justify-center rounded-lg bg-neutral-100 dark:bg-neutral-800">
            <KeyRound className="size-4" />
          </div>
          <div className="flex-1">
            <h2 className="font-medium">API-токены</h2>
            <p className="mt-1 text-sm leading-6 text-muted-foreground">
              Создавайте персональные токены для интеграций. Токен действует от
              вашего имени и не расширяет права. Сохраняйте его сразу: повторно
              увидеть полное значение нельзя.
            </p>

            {createdToken ? (
              <div className="mt-4 rounded-lg border border-emerald-200 bg-emerald-50 p-4 text-sm dark:border-emerald-900/60 dark:bg-emerald-950/40">
                <div className="flex items-center justify-between gap-2">
                  <div>
                    <div className="font-medium text-emerald-900 dark:text-emerald-200">
                      Новый токен создан
                    </div>
                    <div className="mt-1 break-all font-mono text-xs text-emerald-800 dark:text-emerald-300">
                      {createdToken.token}
                    </div>
                  </div>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    onClick={copyCreatedToken}
                  >
                    {copied ? (
                      <Check className="size-3.5" />
                    ) : (
                      <Copy className="size-3.5" />
                    )}
                  </Button>
                </div>
                <p className="mt-2 text-xs text-emerald-800 dark:text-emerald-300">
                  Скопируйте токен сейчас. После закрытия страницы получить его
                  значение нельзя.
                </p>
                <div className="mt-3">
                  <Button
                    type="button"
                    size="sm"
                    variant="ghost"
                    onClick={() => setCreatedToken(null)}
                  >
                    Закрыть
                  </Button>
                </div>
              </div>
            ) : (
              <form
                onSubmit={submitCreateToken}
                className="mt-4 max-w-lg space-y-3"
              >
                <div className="space-y-2">
                  <Label htmlFor="token-name">Название</Label>
                  <Input
                    id="token-name"
                    value={createTokenName}
                    onChange={(event) =>
                      setCreateTokenName(
                        event.target.value.slice(0, MAX_TOKEN_NAME_LENGTH),
                      )
                    }
                    placeholder="Например: Внешний сервис"
                    required
                  />
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div className="space-y-2">
                    <Label htmlFor="token-scope">Доступ</Label>
                    <select
                      id="token-scope"
                      value={createTokenScope}
                      onChange={(event) =>
                        setCreateTokenScope(
                          event.target.value as "read" | "write",
                        )
                      }
                      className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                    >
                      <option value="read">чтение</option>
                      <option value="write">запись</option>
                    </select>
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="token-days">Срок (дней)</Label>
                    <Input
                      id="token-days"
                      type="number"
                      min={1}
                      max={365}
                      value={createTokenDays}
                      onChange={(event) =>
                        setCreateTokenDays(event.target.value)
                      }
                    />
                  </div>
                </div>
                {createTokenError ? (
                  <p className="text-sm text-red-600 dark:text-red-400">
                    {createTokenError}
                  </p>
                ) : null}
                <Button type="submit" disabled={createTokenLoading}>
                  {createTokenLoading ? (
                    <Loader2 className="mr-2 size-3.5 animate-spin" />
                  ) : null}
                  Создать токен
                </Button>
              </form>
            )}
          </div>
        </div>

        <div className="p-6">
          <div className="flex items-center justify-between">
            <div>
              <h3 className="text-sm font-medium">Активные токены</h3>
              <p className="text-xs text-muted-foreground">
                {sortedTokens.length} {pluralizeToken(sortedTokens.length)}
              </p>
            </div>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => refetchTokens()}
              disabled={tokensLoading}
            >
              {tokensLoading ? (
                <Loader2 className="mr-2 size-3.5 animate-spin" />
              ) : null}
              Обновить
            </Button>
          </div>

          <div className="mt-4 space-y-2">
            {tokensLoading ? (
              Array.from({ length: 2 }).map((_, index) => (
                <Skeleton key={index} className="h-16 w-full" />
              ))
            ) : sortedTokens.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                Пока нет активных токенов.
              </p>
            ) : (
              sortedTokens.map((token) => (
                <div
                  key={token.id}
                  className="flex flex-col gap-2 rounded-lg border p-3 sm:flex-row sm:items-center sm:justify-between"
                >
                  <div className="min-w-0">
                    <div className="text-sm font-medium">{token.name}</div>
                    <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                      <span className="font-mono">
                        {maskPrefix(token.prefix)}
                      </span>
                      <span>•</span>
                      <span>{token.scopes.join(", ")}</span>
                      <span>•</span>
                      <span>
                        до{" "}
                        {new Date(token.expires_at).toLocaleDateString("ru-RU")}
                      </span>
                      {token.last_used_at ? (
                        <>
                          <span>•</span>
                          <span>
                            Последний вход:{" "}
                            {new Date(token.last_used_at).toLocaleString(
                              "ru-RU",
                            )}
                          </span>
                        </>
                      ) : null}
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      className="text-red-600 hover:text-red-600 dark:text-red-400"
                      disabled={revokingId === token.id}
                      onClick={() => {
                        setConfirmRevokeId(token.id);
                        setRevokeConfirmName("");
                      }}
                    >
                      {revokingId === token.id ? (
                        <Loader2 className="mr-2 size-3.5 animate-spin" />
                      ) : (
                        <Trash2 className="mr-2 size-3.5" />
                      )}
                      Отозвать
                    </Button>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      </section>

      <section className="mt-6 rounded-2xl border bg-card">
        <div className="flex items-start gap-3 border-b p-6">
          <div className="flex size-9 items-center justify-center rounded-lg bg-neutral-100 dark:bg-neutral-800">
            <ShieldCheck className="size-4" />
          </div>
          <div>
            <h2 className="font-medium">Двухфакторная защита</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Код приложения аутентификации потребуется при каждом новом входе.
              {user?.is_platform_admin && !user.totp_enabled
                ? " Для административных действий сначала включите 2FA."
                : null}
            </p>
          </div>
        </div>
        <div className="p-6">
          {recoveryCodes ? (
            <div className="max-w-lg space-y-4">
              <p className="text-sm font-medium">Сохраните резервные коды сейчас</p>
              <p className="text-sm text-muted-foreground">Каждый код работает один раз. После закрытия страницы их нельзя посмотреть снова.</p>
              <div className="grid grid-cols-2 gap-2 rounded-lg bg-muted p-4 font-mono text-sm">
                {recoveryCodes.map((code) => <span key={code}>{code}</span>)}
              </div>
              <Button onClick={() => {
                setRecoveryCodes(null);
                void queryClient.invalidateQueries({ queryKey: ["me"] });
                void queryClient.invalidateQueries({ queryKey: ["sessions"] });
              }}>Коды сохранены — продолжить</Button>
            </div>
          ) : user?.totp_enabled ? (
            <form onSubmit={disableTotp} className="max-w-md space-y-3">
              <Badge variant="secondary">Включена</Badge>
              <p className="text-sm text-muted-foreground">Для отключения введите код приложения или резервный код. Все сеансы будут завершены.</p>
              <Label htmlFor="totp-disable-code">Код подтверждения</Label>
              <Input id="totp-disable-code" value={totpCode} onChange={(event) => setTotpCode(event.target.value)} autoComplete="one-time-code" required />
              <Button type="submit" variant="outline" disabled={totpLoading}>Отключить 2FA</Button>
            </form>
          ) : totpSetup ? (
            <form onSubmit={confirmTotp} className="max-w-lg space-y-4">
              <p className="text-sm">Добавьте ключ в приложение аутентификации и введите шестизначный код.</p>
              <div className="break-all rounded-lg bg-muted p-3 font-mono text-sm">{totpSetup.secret}</div>
              <a href={totpSetup.otpauth_uri} className="text-sm underline">Открыть в приложении</a>
              <div className="space-y-2">
                <Label htmlFor="totp-confirm-code">Код приложения</Label>
                <Input id="totp-confirm-code" value={totpCode} onChange={(event) => setTotpCode(event.target.value)} inputMode="numeric" autoComplete="one-time-code" required />
              </div>
              <Button type="submit" disabled={totpLoading}>Подтвердить и включить</Button>
            </form>
          ) : user?.has_password ? (
            <form onSubmit={startTotp} className="max-w-md space-y-3">
              <p className="text-sm text-muted-foreground">Для настройки подтвердите текущий пароль.</p>
              <Label htmlFor="totp-password">Пароль</Label>
              <Input id="totp-password" type="password" autoComplete="current-password" value={totpPassword} onChange={(event) => setTotpPassword(event.target.value)} required />
              <Button type="submit" disabled={totpLoading}>Настроить 2FA</Button>
            </form>
          ) : (
            <p className="text-sm text-muted-foreground">Сначала задайте пароль ниже, затем включите двухфакторную защиту.</p>
          )}
        </div>
      </section>

      <section className="mt-6 rounded-2xl border bg-card">
        <div className="flex items-start gap-3 border-b p-6">
          <div className="flex size-9 items-center justify-center rounded-lg bg-neutral-100 dark:bg-neutral-800">
            <MonitorSmartphone className="size-4" />
          </div>
          <div className="flex-1">
            <h2 className="font-medium">Активные устройства</h2>
            <p className="mt-1 text-sm leading-6 text-muted-foreground">
              Завершите сеанс, если не узнаёте устройство. Доступ на нём прекратится сразу.
            </p>
          </div>
        </div>
        <div className="divide-y">
          {sessionsLoading ? (
            <div className="p-6"><Skeleton className="h-12 w-full" /></div>
          ) : sessions?.length ? sessions.map((session) => (
            <div key={session.id} className="flex flex-wrap items-center justify-between gap-3 p-5 sm:px-6">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2 text-sm font-medium">
                  {sessionDevice(session.user_agent)}
                  {session.current ? <Badge variant="secondary">Это устройство</Badge> : null}
                </div>
                <p className="mt-1 text-xs text-muted-foreground">
                  IP: {session.ip_address ?? "неизвестен"} · Последняя активность: {new Date(session.last_seen_at ?? session.created_at).toLocaleString("ru-RU")}
                </p>
              </div>
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={revokingSessionId !== null}
                onClick={() => void revokeSession(session)}
              >
                {revokingSessionId === session.id ? <Loader2 className="mr-2 size-4 animate-spin" /> : null}
                {session.current ? "Выйти" : "Завершить"}
              </Button>
            </div>
          )) : (
            <p className="p-6 text-sm text-muted-foreground">Активных сеансов нет.</p>
          )}
        </div>
      </section>

      <section className="mt-6 rounded-2xl border bg-card">
        <div className="flex items-start gap-3 border-b p-6">
          <div className="flex size-9 items-center justify-center rounded-lg bg-neutral-100 dark:bg-neutral-800">
            <MapPin className="size-4" />
          </div>
          <div className="flex-1">
            <h2 className="font-medium">Часовой пояс</h2>
            <p className="mt-1 text-sm leading-6 text-muted-foreground">
              В базе дедлайны хранятся в UTC, а в интерфейсе показываются в
              вашем часовом поясе.
            </p>
            <div className="mt-4 flex flex-col gap-3 rounded-lg bg-neutral-50 p-4 sm:flex-row sm:items-center sm:justify-between dark:bg-neutral-800">
              <div>
                <div className="text-sm font-medium">
                  {user?.timezone ?? "UTC"}
                </div>
                <div className="mt-0.5 text-xs text-muted-foreground">
                  Браузер определил: {browserTimezone}
                </div>
              </div>
              {user?.timezone === browserTimezone ? (
                <span className="inline-flex items-center gap-1.5 text-xs text-emerald-700 dark:text-emerald-400">
                  <Check className="size-3.5" />
                  Актуально
                </span>
              ) : (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={updateTimezone}
                  disabled={timezoneLoading}
                >
                  {timezoneLoading ? (
                    <Loader2 className="size-3.5 animate-spin" />
                  ) : null}
                  Использовать браузерный
                </Button>
              )}
            </div>
          </div>
        </div>

        <div className="flex items-start gap-3 p-6">
          <div className="flex size-9 items-center justify-center rounded-lg bg-neutral-100 dark:bg-neutral-800">
            <KeyRound className="size-4" />
          </div>
          <div className="flex-1">
            <h2 className="font-medium">Сменить пароль</h2>
            <p className="mt-1 text-sm leading-6 text-muted-foreground">
              {user?.has_password
                ? "Для подтверждения потребуется текущий пароль."
                : googleReauth
                  ? "Личность подтверждена через Google. Теперь задайте локальный пароль для входа по email."
                  : "У этого аккаунта пока нет локального пароля: вход выполняется через Google. Перед созданием пароля подтвердите личность через Google."}
            </p>
            {user?.has_password === false && !googleReauth ? (
              <Button
                variant="outline"
                size="sm"
                className="mt-3"
                onClick={initiateGoogleReauth}
                disabled={reauthLoading}
              >
                {reauthLoading ? (
                  <Loader2 className="size-4 animate-spin" />
                ) : null}
                Подтвердить через Google и установить пароль
              </Button>
            ) : null}
            {user?.has_password ||
            (user?.has_password === false && googleReauth) ? (
              <form
                onSubmit={changePassword}
                className="mt-5 max-w-md space-y-4"
              >
                {user.has_password ? (
                  <div className="space-y-2">
                    <Label htmlFor="old-password">Старый пароль</Label>
                    <Input
                      id="old-password"
                      type="password"
                      autoComplete="current-password"
                      value={oldPassword}
                      onChange={(event) => setOldPassword(event.target.value)}
                      required
                    />
                  </div>
                ) : null}
                <div className="space-y-2">
                  <Label htmlFor="new-password">Новый пароль</Label>
                  <Input
                    id="new-password"
                    type="password"
                    autoComplete="new-password"
                    value={newPassword}
                    onChange={(event) => setNewPassword(event.target.value)}
                    minLength={12}
                    maxLength={128}
                    required
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="confirm-password">
                    Повторите новый пароль
                  </Label>
                  <Input
                    id="confirm-password"
                    type="password"
                    autoComplete="new-password"
                    value={confirm}
                    onChange={(event) => setConfirm(event.target.value)}
                    minLength={12}
                    maxLength={128}
                    required
                  />
                </div>
                <Button type="submit" disabled={passwordLoading}>
                  {passwordLoading ? (
                    <Loader2 className="size-4 animate-spin" />
                  ) : null}
                  Сохранить пароль
                </Button>
              </form>
            ) : null}
          </div>
        </div>
      </section>

      <section className="mt-8 rounded-2xl border border-red-200 bg-card p-5 dark:border-red-900">
        <h2 className="font-medium text-red-700 dark:text-red-400">
          Опасная зона
        </h2>
        <p className="mt-2 text-sm text-muted-foreground">
          В{" "}
          <Link href="/app/trash" className="underline">
            корзине
          </Link>{" "}
          можно восстановить удалённые пространства, команды, доски, страницы и
          задачи. Удаление аккаунта анонимизирует профиль и отзывает все сессии
          и API-токены.
        </p>
        <form
          onSubmit={deleteAccount}
          className="mt-5 flex max-w-lg flex-col gap-3 sm:flex-row"
        >
          <Input
            type="email"
            value={deleteEmail}
            onChange={(event) => setDeleteEmail(event.target.value)}
            placeholder={user?.email ?? "Ваш email"}
            required
          />
          <Button
            variant="destructive"
            disabled={
              deletingAccount ||
              deleteEmail.toLowerCase() !== user?.email.toLowerCase()
            }
          >
            Удалить аккаунт
          </Button>
        </form>
        <div className="mt-4 flex flex-wrap gap-3 text-xs text-muted-foreground">
          <Link href="/legal/terms" className="underline">
            Условия
          </Link>
          <Link href="/legal/privacy" className="underline">
            Конфиденциальность
          </Link>
          <Link href="/legal/cookies" className="underline">
            Cookies
          </Link>
          <Link href="/legal/subprocessors" className="underline">
            Субпроцессоры
          </Link>
        </div>
      </section>

      {confirmRevokeId !== null ? (
        <Dialog
          open={confirmRevokeId !== null}
          onOpenChange={(open) => {
            if (!open) {
              setConfirmRevokeId(null);
              setRevokeConfirmName("");
            }
          }}
        >
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
            <div className="absolute inset-0 bg-black/50" />
            <div className="relative w-full max-w-md rounded-xl border bg-card p-6 shadow-lg">
              <h3 className="text-lg font-semibold">Отозвать токен</h3>
              <p className="mt-2 text-sm text-muted-foreground">
                Это действие нельзя отменить. После отзыва интеграция перестанет
                получать доступ к API.
              </p>
              <div className="mt-4 space-y-2">
                <Label htmlFor="revoke-confirm-name">
                  Введите название токена для подтверждения
                </Label>
                <Input
                  id="revoke-confirm-name"
                  value={revokeConfirmName}
                  onChange={(event) => setRevokeConfirmName(event.target.value)}
                  placeholder={
                    confirmRevokeId
                      ? (sortedTokens.find(
                          (item) => item.id === confirmRevokeId,
                        )?.name ?? "Название токена")
                      : "Название токена"
                  }
                />
              </div>
              <div className="mt-6 flex items-center justify-end gap-2">
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => {
                    setConfirmRevokeId(null);
                    setRevokeConfirmName("");
                  }}
                  disabled={revokingId !== null}
                >
                  Отмена
                </Button>
                <Button
                  type="button"
                  variant="destructive"
                  onClick={handleRevoke}
                  disabled={revokingId !== null}
                >
                  {revokingId ? (
                    <Loader2 className="mr-2 size-3.5 animate-spin" />
                  ) : null}
                  Отозвать
                </Button>
              </div>
            </div>
          </div>
        </Dialog>
      ) : null}
    </div>
  );
}

function pluralizeToken(count: number) {
  if (count % 10 === 1 && count % 100 !== 11) return "токен";
  if ([2, 3, 4].includes(count % 10) && ![12, 13, 14].includes(count % 100))
    return "токена";
  return "токенов";
}
