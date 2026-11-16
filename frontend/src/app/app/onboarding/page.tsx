"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowRight,
  Columns3,
  FileText,
  Layers3,
  Loader2,
  Sparkles,
  Users,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api } from "@/lib/api";
import { generateBoardKey } from "@/lib/board-key";
import { ONBOARDING_SKIPPED_KEY } from "@/lib/onboarding";
import type {
  NavigationBoard,
  NavigationSpace,
  PageDocument,
  Space,
  Team,
  User,
} from "@/lib/types";
import { cn, formatError } from "@/lib/utils";

type Step = "welcome" | "space" | "team" | "first-thing";
const STEPS: Step[] = ["welcome", "space", "team", "first-thing"];

export default function OnboardingPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { data: user } = useQuery({
    queryKey: ["me"],
    queryFn: () => api.get<User>("/users/me"),
  });
  const { data: navigation, isLoading: navigationLoading } = useQuery({
    queryKey: ["navigation"],
    queryFn: () => api.get<NavigationSpace[]>("/navigation"),
  });

  const [step, setStep] = useState<Step>("welcome");
  const [spaceName, setSpaceName] = useState("Моё пространство");
  const [spaceId, setSpaceId] = useState<string | null>(null);
  const [teamName, setTeamName] = useState("Основная команда");
  const [teamId, setTeamId] = useState<string | null>(null);
  const [kind, setKind] = useState<"board" | "page">("board");
  const [resourceName, setResourceName] = useState("Первые задачи");
  const [boardKey, setBoardKey] = useState("");
  const [loading, setLoading] = useState(false);

  const generatedKey = useMemo(
    () => generateBoardKey(resourceName),
    [resourceName],
  );

  // Onboarding only makes sense before the first Space exists. Only bounce on
  // the welcome step: once the wizard itself creates a Space, `navigation`
  // refetches non-empty and this must not kick the user back out mid-flow.
  const alreadyOnboarded =
    step === "welcome" && !navigationLoading && !!navigation?.length;

  useEffect(() => {
    if (alreadyOnboarded) router.replace("/app");
  }, [alreadyOnboarded, router]);

  if (alreadyOnboarded) return null;

  async function createSpace(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    try {
      const space = await api.post<Space>("/spaces", { name: spaceName });
      await queryClient.invalidateQueries({ queryKey: ["navigation"] });
      setSpaceId(space.id);
      setStep("team");
    } catch (error) {
      toast.error(formatError(error));
    } finally {
      setLoading(false);
    }
  }

  async function createTeam(event: FormEvent) {
    event.preventDefault();
    if (!spaceId) return;
    setLoading(true);
    try {
      const team = await api.post<Team>(`/spaces/${spaceId}/teams`, {
        name: teamName,
      });
      await queryClient.invalidateQueries({ queryKey: ["navigation"] });
      setTeamId(team.id);
      setStep("first-thing");
    } catch (error) {
      toast.error(formatError(error));
    } finally {
      setLoading(false);
    }
  }

  async function createFirstThing(event: FormEvent) {
    event.preventDefault();
    if (!teamId) return;
    setLoading(true);
    try {
      if (kind === "board") {
        const board = await api.post<NavigationBoard>(
          `/teams/${teamId}/boards`,
          { name: resourceName, key: (boardKey || generatedKey).toUpperCase() },
        );
        await queryClient.invalidateQueries({ queryKey: ["navigation"] });
        router.push(`/app/boards/${board.id}`);
      } else {
        const page = await api.post<PageDocument>(`/teams/${teamId}/pages`, {
          title: resourceName,
        });
        await queryClient.invalidateQueries({ queryKey: ["navigation"] });
        router.push(`/app/pages/${page.id}?new=1`);
      }
    } catch (error) {
      toast.error(formatError(error));
      setLoading(false);
    }
  }

  const stepIndex = STEPS.indexOf(step);

  return (
    <div className="mx-auto flex min-h-[calc(100vh-4rem)] max-w-2xl flex-col justify-center px-4 py-10 sm:px-6 sm:py-16">
      <div className="rounded-3xl border bg-card p-6 shadow-[0_24px_70px_-40px_rgba(0,0,0,0.45)] sm:p-10">
        <div className="mb-2 flex items-center justify-between text-xs text-muted-foreground">
          <span>Быстрая настройка</span>
          <span>
            Шаг {stepIndex + 1} из {STEPS.length}
          </span>
        </div>
        <div className="mb-8 flex items-center gap-2">
          {STEPS.map((candidate, index) => (
            <span
              key={candidate}
              className={cn(
                "h-1.5 flex-1 rounded-full transition-colors",
                index <= stepIndex
                  ? "bg-neutral-900 dark:bg-neutral-100"
                  : "bg-neutral-200 dark:bg-neutral-800",
              )}
            />
          ))}
        </div>

        {step === "welcome" ? (
          <div>
            <div className="flex size-12 items-center justify-center rounded-2xl bg-neutral-900 text-white dark:bg-neutral-100 dark:text-neutral-950">
              <Sparkles className="size-6" />
            </div>
            <h1 className="mt-6 text-3xl font-semibold tracking-[-0.035em]">
              Добро пожаловать, {user?.name.split(" ")[0] ?? ""}
            </h1>
            <p className="mt-3 text-sm leading-6 text-muted-foreground">
              За пару минут настроим первое рабочее пространство и создадим
              готовую доску для задач.
            </p>
            <ul className="mt-6 space-y-4">
              {[
                {
                  icon: Layers3,
                  title: "Пространство",
                  text: "ваша организация или отдельный проект",
                },
                {
                  icon: Users,
                  title: "Команда",
                  text: "направление со своими задачами и документами",
                },
                {
                  icon: Columns3,
                  title: "Доска или страница",
                  text: "задачи на канбан-доске или знания в документе",
                },
              ].map(({ icon: Icon, title, text }) => (
                <li key={title} className="flex items-start gap-3">
                  <div className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-neutral-100 dark:bg-neutral-800">
                    <Icon className="size-4" />
                  </div>
                  <div className="text-sm leading-6">
                    <span className="font-medium">{title}</span>{" "}
                    <span className="text-muted-foreground">— {text}</span>
                  </div>
                </li>
              ))}
            </ul>
            <Button
              size="lg"
              className="mt-8 w-full"
              onClick={() => setStep("space")}
            >
              Настроить Noki
              <ArrowRight className="size-4" />
            </Button>
            <button
              type="button"
              onClick={() => {
                localStorage.setItem(ONBOARDING_SKIPPED_KEY, "1");
                router.push("/app");
              }}
              className="mt-4 w-full text-center text-xs text-muted-foreground underline-offset-4 hover:underline"
            >
              Пропустить и настроить позже
            </button>
          </div>
        ) : null}

        {step === "space" ? (
          <div>
            <div className="flex size-12 items-center justify-center rounded-2xl bg-neutral-100 dark:bg-neutral-800">
              <Layers3 className="size-6" />
            </div>
            <h1 className="mt-6 text-2xl font-semibold tracking-[-0.035em]">
              Назовите пространство
            </h1>
            <p className="mt-2 text-sm leading-6 text-muted-foreground">
              Это может быть название компании, команды или личного проекта. Его
              всегда можно изменить позже.
            </p>
            <form onSubmit={createSpace} className="mt-6 space-y-5">
              <div className="space-y-2">
                <Label htmlFor="onboarding-space">Название пространства</Label>
                <Input
                  id="onboarding-space"
                  value={spaceName}
                  onChange={(event) => setSpaceName(event.target.value)}
                  placeholder="Моя команда"
                  maxLength={80}
                  autoFocus
                  required
                />
              </div>
              <Button
                type="submit"
                size="lg"
                className="w-full"
                disabled={loading}
              >
                {loading ? <Loader2 className="size-4 animate-spin" /> : null}
                Продолжить
                {!loading ? <ArrowRight className="size-4" /> : null}
              </Button>
            </form>
          </div>
        ) : null}

        {step === "team" ? (
          <div>
            <div className="flex size-12 items-center justify-center rounded-2xl bg-neutral-100 dark:bg-neutral-800">
              <Users className="size-6" />
            </div>
            <h1 className="mt-6 text-2xl font-semibold tracking-[-0.035em]">
              Как называется команда?
            </h1>
            <p className="mt-2 text-sm leading-6 text-muted-foreground">
              В ней будут жить задачи и документы. Коллег можно пригласить после
              настройки.
            </p>
            <form onSubmit={createTeam} className="mt-6 space-y-5">
              <div className="space-y-2">
                <Label htmlFor="onboarding-team">Название команды</Label>
                <Input
                  id="onboarding-team"
                  value={teamName}
                  onChange={(event) => setTeamName(event.target.value)}
                  placeholder="Основная команда"
                  maxLength={80}
                  autoFocus
                  required
                />
              </div>
              <Button
                type="submit"
                size="lg"
                className="w-full"
                disabled={loading}
              >
                {loading ? <Loader2 className="size-4 animate-spin" /> : null}
                Продолжить
                {!loading ? <ArrowRight className="size-4" /> : null}
              </Button>
            </form>
          </div>
        ) : null}

        {step === "first-thing" ? (
          <div>
            <div className="flex size-12 items-center justify-center rounded-2xl bg-neutral-100 dark:bg-neutral-800">
              {kind === "board" ? (
                <Columns3 className="size-6" />
              ) : (
                <FileText className="size-6" />
              )}
            </div>
            <h1 className="mt-6 text-2xl font-semibold tracking-[-0.035em]">
              С чего начнём?
            </h1>
            <p className="mt-2 text-sm leading-6 text-muted-foreground">
              Можно создать оба позже — выберите то, с чего удобнее начать.
            </p>

            <div className="mt-6 grid grid-cols-2 gap-3">
              <button
                type="button"
                onClick={() => setKind("board")}
                className={cn(
                  "rounded-xl border p-4 text-left transition",
                  kind === "board"
                    ? "border-neutral-900 bg-neutral-50 dark:border-neutral-100 dark:bg-neutral-900"
                    : "hover:border-neutral-300 dark:hover:border-neutral-700",
                )}
              >
                <Columns3 className="size-5" />
                <div className="mt-3 text-sm font-medium">Доска задач</div>
                <div className="mt-1 text-xs text-muted-foreground">
                  Канбан для работы команды
                </div>
              </button>
              <button
                type="button"
                onClick={() => setKind("page")}
                className={cn(
                  "rounded-xl border p-4 text-left transition",
                  kind === "page"
                    ? "border-neutral-900 bg-neutral-50 dark:border-neutral-100 dark:bg-neutral-900"
                    : "hover:border-neutral-300 dark:hover:border-neutral-700",
                )}
              >
                <FileText className="size-5" />
                <div className="mt-3 text-sm font-medium">Страница</div>
                <div className="mt-1 text-xs text-muted-foreground">
                  Документ для планов и знаний
                </div>
              </button>
            </div>

            <form onSubmit={createFirstThing} className="mt-6 space-y-5">
              <div className="space-y-2">
                <Label htmlFor="onboarding-resource">
                  {kind === "board" ? "Название доски" : "Название страницы"}
                </Label>
                <Input
                  id="onboarding-resource"
                  value={resourceName}
                  onChange={(event) => setResourceName(event.target.value)}
                  placeholder={
                    kind === "board"
                      ? "Product Development"
                      : "Стратегия продукта"
                  }
                  maxLength={kind === "board" ? 100 : 200}
                  autoFocus
                  required
                />
              </div>
              {kind === "board" ? (
                <div className="space-y-2">
                  <Label htmlFor="onboarding-board-key">
                    Код из 2–5 латинских букв
                  </Label>
                  <Input
                    id="onboarding-board-key"
                    value={boardKey || generatedKey}
                    onChange={(event) =>
                      setBoardKey(
                        event.target.value
                          .toUpperCase()
                          .replace(/[^A-Z]/g, "")
                          .slice(0, 5),
                      )
                    }
                    placeholder="DEV"
                    minLength={2}
                    maxLength={5}
                    pattern="[A-Z]{2,5}"
                    required
                    className="font-mono uppercase"
                  />
                </div>
              ) : null}
              <Button
                type="submit"
                size="lg"
                className="w-full"
                disabled={loading}
              >
                {loading ? <Loader2 className="size-4 animate-spin" /> : null}
                Создать и перейти
                {!loading ? <ArrowRight className="size-4" /> : null}
              </Button>
            </form>
          </div>
        ) : null}
      </div>
    </div>
  );
}
