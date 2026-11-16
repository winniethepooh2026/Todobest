import {
  ArrowRight,
  Check,
  CheckCircle2,
  ChevronRight,
  Circle,
  Clock3,
  Columns3,
  FileText,
  Layers3,
  MessageSquare,
  Sparkles,
  Users,
  Zap,
} from "lucide-react";
import Image from "next/image";
import Link from "next/link";

const benefits = [
  {
    icon: Columns3,
    title: "Задачи не теряются",
    description:
      "Доски, статусы, исполнители и сроки дают команде один понятный ритм работы.",
  },
  {
    icon: FileText,
    title: "Контекст всегда рядом",
    description:
      "Решения, брифы и заметки живут рядом с задачами, а не в десятке разрозненных чатов.",
  },
  {
    icon: Users,
    title: "Легко начать вместе",
    description:
      "Создайте пространство, пригласите команду и начните работу без долгой настройки.",
  },
];

const steps = [
  ["01", "Создайте пространство", "Для компании, команды или личного проекта."],
  ["02", "Добавьте команду", "Разделите работу по продуктам или направлениям."],
  [
    "03",
    "Запустите первую доску",
    "Перенесите текущие задачи и пригласите коллег.",
  ],
];

function ProductPreview() {
  const columns = [
    {
      title: "Запланировано",
      tone: "bg-neutral-400",
      cards: [
        ["NOK-12", "Собрать обратную связь", "Сегодня"],
        ["NOK-14", "Подготовить новый экран", "Чт"],
      ],
    },
    {
      title: "В работе",
      tone: "bg-amber-400",
      cards: [
        ["NOK-09", "Запустить лендинг", "Сегодня"],
        ["NOK-11", "Проверить onboarding", "Пт"],
      ],
    },
    {
      title: "Готово",
      tone: "bg-emerald-500",
      cards: [["NOK-07", "Подключить почту", "Готово"]],
    },
  ];

  return (
    <div className="relative mx-auto mt-16 max-w-6xl px-3 sm:px-6">
      <div className="absolute -inset-10 -z-10 rounded-[4rem] bg-[radial-gradient(circle_at_center,rgba(99,102,241,0.16),transparent_64%)] blur-2xl" />
      <div className="overflow-hidden rounded-2xl border border-white/70 bg-white/90 shadow-[0_30px_100px_-35px_rgba(15,23,42,0.38)] ring-1 ring-black/5 backdrop-blur dark:border-white/10 dark:bg-neutral-950/90 dark:ring-white/10">
        <div className="flex h-11 items-center gap-2 border-b px-4">
          <span className="size-2.5 rounded-full bg-red-400/80" />
          <span className="size-2.5 rounded-full bg-amber-400/80" />
          <span className="size-2.5 rounded-full bg-emerald-400/80" />
          <span className="ml-4 rounded-md bg-neutral-100 px-3 py-1 text-[10px] text-neutral-500 dark:bg-neutral-900">
            noki.click/app
          </span>
        </div>
        <div className="grid min-h-[390px] grid-cols-[72px_1fr] sm:grid-cols-[210px_1fr]">
          <aside className="border-r bg-neutral-50/80 p-3 sm:p-4 dark:bg-neutral-950">
            <div className="flex items-center gap-2 font-semibold">
              <Image src="/noki-mark.svg" alt="" width={24} height={24} />
              <span className="hidden sm:inline">Noki</span>
            </div>
            <div className="mt-8 space-y-2 text-xs">
              {["Мои задачи", "План на день"].map((item, index) => (
                <div
                  key={item}
                  className={`flex items-center gap-2 rounded-lg px-2 py-2 ${index === 0 ? "bg-white shadow-sm dark:bg-neutral-900" : "text-neutral-500"}`}
                >
                  {index === 0 ? (
                    <CheckCircle2 className="size-4" />
                  ) : (
                    <Clock3 className="size-4" />
                  )}
                  <span className="hidden sm:inline">{item}</span>
                </div>
              ))}
            </div>
            <div className="mt-8 hidden sm:block">
              <p className="px-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-neutral-400">
                Продукт
              </p>
              <div className="mt-3 space-y-1 text-xs text-neutral-600 dark:text-neutral-400">
                <div className="flex items-center gap-2 rounded-lg bg-neutral-100 px-2 py-2 font-medium text-neutral-950 dark:bg-neutral-900 dark:text-white">
                  <Columns3 className="size-3.5" /> Разработка
                </div>
                <div className="flex items-center gap-2 px-2 py-2">
                  <FileText className="size-3.5" /> План запуска
                </div>
                <div className="flex items-center gap-2 px-2 py-2">
                  <FileText className="size-3.5" /> Исследования
                </div>
              </div>
            </div>
          </aside>
          <div className="min-w-0 bg-white p-4 sm:p-6 dark:bg-neutral-950">
            <div className="flex items-center justify-between gap-3">
              <div>
                <p className="text-[10px] font-medium uppercase tracking-[0.16em] text-neutral-400">
                  Доска
                </p>
                <h2 className="mt-1 text-lg font-semibold sm:text-xl">
                  Разработка продукта
                </h2>
              </div>
              <div className="hidden items-center -space-x-2 sm:flex">
                {["АК", "МР", "ДИ"].map((name) => (
                  <span
                    key={name}
                    className="grid size-8 place-items-center rounded-full border-2 border-white bg-neutral-900 text-[9px] font-semibold text-white dark:border-neutral-950 dark:bg-neutral-100 dark:text-neutral-900"
                  >
                    {name}
                  </span>
                ))}
              </div>
            </div>
            <div className="mt-6 grid gap-3 md:grid-cols-3">
              {columns.map((column) => (
                <div
                  key={column.title}
                  className="min-w-0 rounded-xl bg-neutral-50 p-2.5 dark:bg-neutral-900/70"
                >
                  <div className="flex items-center gap-2 px-1 pb-2 text-[11px] font-medium">
                    <span className={`size-2 rounded-full ${column.tone}`} />
                    {column.title}
                    <span className="ml-auto text-neutral-400">
                      {column.cards.length}
                    </span>
                  </div>
                  <div className="space-y-2">
                    {column.cards.map(([key, title, due]) => (
                      <div
                        key={key}
                        className="rounded-lg border bg-white p-3 shadow-sm dark:bg-neutral-950"
                      >
                        <p className="text-[10px] text-neutral-400">{key}</p>
                        <p className="mt-2 text-xs font-medium leading-5">
                          {title}
                        </p>
                        <div className="mt-4 flex items-center justify-between text-[9px] text-neutral-400">
                          <span className="flex items-center gap-1">
                            <Circle className="size-2.5" /> Задача
                          </span>
                          <span>{due}</span>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function LandingPage() {
  return (
    <main className="min-h-screen overflow-hidden bg-[#fbfbfa] text-neutral-950 dark:bg-neutral-950 dark:text-neutral-50">
      <header className="sticky top-0 z-30 border-b border-black/5 bg-[#fbfbfa]/85 backdrop-blur-xl dark:border-white/10 dark:bg-neutral-950/85">
        <nav className="mx-auto flex h-16 max-w-7xl items-center justify-between px-5 sm:px-8">
          <Link
            href="/"
            className="flex items-center gap-2 text-lg font-semibold tracking-tight"
          >
            <Image
              src="/noki-mark.svg"
              alt=""
              width={28}
              height={28}
              priority
            />
            Noki
          </Link>
          <div className="hidden items-center gap-7 text-sm text-neutral-600 md:flex dark:text-neutral-400">
            <Link
              href="#product"
              className="transition hover:text-neutral-950 dark:hover:text-white"
            >
              Возможности
            </Link>
            <Link
              href="#start"
              className="transition hover:text-neutral-950 dark:hover:text-white"
            >
              Как начать
            </Link>
            <Link
              href="/register"
              className="transition hover:text-neutral-950 dark:hover:text-white"
            >
              Начать бесплатно
            </Link>
          </div>
          <div className="flex items-center gap-2">
            <Link
              href="/login"
              className="hidden rounded-lg px-3 py-2 text-sm font-medium text-neutral-600 transition hover:bg-black/5 sm:inline-flex dark:text-neutral-300 dark:hover:bg-white/10"
            >
              Войти
            </Link>
            <Link
              href="/register"
              className="inline-flex h-9 items-center gap-1.5 rounded-lg bg-neutral-950 px-3.5 text-sm font-medium text-white transition hover:bg-neutral-800 dark:bg-white dark:text-neutral-950 dark:hover:bg-neutral-200"
            >
              Попробовать бесплатно <ArrowRight className="size-3.5" />
            </Link>
          </div>
        </nav>
      </header>

      <section className="relative px-5 pb-24 pt-20 text-center sm:px-8 sm:pt-28">
        <div className="pointer-events-none absolute left-1/2 top-[-18rem] -z-0 size-[42rem] -translate-x-1/2 rounded-full bg-indigo-200/40 blur-3xl dark:bg-indigo-950/25" />
        <div className="relative mx-auto max-w-4xl">
          <div className="mx-auto inline-flex items-center gap-2 rounded-full border border-black/10 bg-white/70 px-3 py-1.5 text-xs font-medium text-neutral-600 shadow-sm backdrop-blur dark:border-white/10 dark:bg-white/5 dark:text-neutral-300">
            <Sparkles className="size-3.5 text-indigo-500" />
            Задачи и знания команды — в одном месте
          </div>
          <h1 className="mt-7 text-balance text-5xl font-semibold leading-[0.98] tracking-[-0.055em] sm:text-6xl md:text-8xl">
            Работайте вместе.
            <span className="block text-neutral-400 dark:text-neutral-500">
              Без рабочего хаоса.
            </span>
          </h1>
          <p className="mx-auto mt-7 max-w-2xl text-balance text-lg leading-8 text-neutral-600 sm:text-xl dark:text-neutral-400">
            Noki объединяет задачи, доски и документы, чтобы команда понимала,
            что делать сейчас и где найти нужный контекст.
          </p>
          <div className="mt-9 flex flex-col items-center justify-center gap-4 sm:flex-row">
            <Link
              href="/register"
              className="inline-flex h-12 items-center gap-2 rounded-xl bg-neutral-950 px-6 text-sm font-semibold text-white shadow-lg shadow-neutral-950/15 transition hover:-translate-y-0.5 hover:bg-neutral-800 dark:bg-white dark:text-neutral-950 dark:shadow-white/10 dark:hover:bg-neutral-200"
            >
              Создать пространство <ArrowRight className="size-4" />
            </Link>
            <span className="flex items-center gap-2 text-sm text-neutral-500 dark:text-neutral-400">
              <Check className="size-4 text-emerald-600" /> Бесплатно ·
              настройка за 2 минуты
            </span>
          </div>
        </div>
        <ProductPreview />
      </section>

      <section
        id="product"
        className="border-y bg-white px-5 py-24 sm:px-8 dark:bg-neutral-950"
      >
        <div className="mx-auto max-w-6xl">
          <div className="max-w-2xl">
            <p className="text-sm font-semibold text-indigo-600 dark:text-indigo-400">
              Один рабочий контур
            </p>
            <h2 className="mt-3 text-balance text-3xl font-semibold tracking-[-0.04em] sm:text-5xl">
              Всё необходимое команде. Ничего лишнего.
            </h2>
          </div>
          <div className="mt-12 grid gap-4 md:grid-cols-3">
            {benefits.map(({ icon: Icon, title, description }) => (
              <article
                key={title}
                className="group rounded-2xl border bg-[#fbfbfa] p-6 transition hover:-translate-y-1 hover:shadow-xl hover:shadow-black/5 dark:bg-neutral-900/60"
              >
                <div className="grid size-11 place-items-center rounded-xl border bg-white shadow-sm dark:bg-neutral-950">
                  <Icon className="size-5" />
                </div>
                <h3 className="mt-8 text-lg font-semibold">{title}</h3>
                <p className="mt-3 text-sm leading-6 text-neutral-500 dark:text-neutral-400">
                  {description}
                </p>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section id="start" className="px-5 py-24 sm:px-8">
        <div className="mx-auto grid max-w-6xl gap-14 lg:grid-cols-[0.8fr_1.2fr] lg:items-start">
          <div className="lg:sticky lg:top-28">
            <div className="grid size-12 place-items-center rounded-2xl bg-indigo-600 text-white shadow-lg shadow-indigo-600/20">
              <Zap className="size-5" />
            </div>
            <h2 className="mt-6 text-3xl font-semibold tracking-[-0.04em] sm:text-5xl">
              От регистрации до первой задачи — несколько минут.
            </h2>
            <p className="mt-5 max-w-lg text-base leading-7 text-neutral-500 dark:text-neutral-400">
              Встроенный онбординг проведёт по структуре Noki и сразу откроет
              готовую рабочую доску.
            </p>
          </div>
          <div className="divide-y border-y">
            {steps.map(([number, title, description]) => (
              <div
                key={number}
                className="grid grid-cols-[48px_1fr_auto] items-center gap-4 py-7 sm:grid-cols-[70px_1fr_auto]"
              >
                <span className="font-mono text-xs text-neutral-400">
                  {number}
                </span>
                <div>
                  <h3 className="font-semibold">{title}</h3>
                  <p className="mt-1 text-sm text-neutral-500 dark:text-neutral-400">
                    {description}
                  </p>
                </div>
                <ChevronRight className="size-4 text-neutral-300" />
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="px-5 pb-24 sm:px-8">
        <div className="mx-auto grid max-w-6xl gap-4 rounded-3xl bg-neutral-950 p-6 text-white sm:p-10 md:grid-cols-[1fr_auto] md:items-center dark:bg-white dark:text-neutral-950">
          <div>
            <p className="text-sm text-neutral-400 dark:text-neutral-600">
              Готовы навести порядок?
            </p>
            <h2 className="mt-2 text-3xl font-semibold tracking-[-0.04em] sm:text-4xl">
              Соберите работу команды в Noki.
            </h2>
            <div className="mt-5 flex flex-wrap gap-x-5 gap-y-2 text-sm text-neutral-400 dark:text-neutral-600">
              <span className="flex items-center gap-1.5">
                <Layers3 className="size-4" /> Пространства
              </span>
              <span className="flex items-center gap-1.5">
                <MessageSquare className="size-4" /> Комментарии
              </span>
              <span className="flex items-center gap-1.5">
                <CheckCircle2 className="size-4" /> Задачи и сроки
              </span>
            </div>
          </div>
          <Link
            href="/register"
            className="mt-4 inline-flex h-12 items-center justify-center gap-2 rounded-xl bg-white px-6 text-sm font-semibold text-neutral-950 transition hover:bg-neutral-200 md:mt-0 dark:bg-neutral-950 dark:text-white dark:hover:bg-neutral-800"
          >
            Начать бесплатно <ArrowRight className="size-4" />
          </Link>
        </div>
      </section>

      <footer className="border-t px-5 py-8 sm:px-8">
        <div className="mx-auto flex max-w-6xl flex-col gap-5 text-sm text-neutral-500 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-2 font-medium text-neutral-800 dark:text-neutral-200">
            <Image src="/noki-mark.svg" alt="" width={22} height={22} /> Noki
          </div>
          <div className="flex flex-wrap gap-x-5 gap-y-2">
            <Link href="/legal/terms">Условия</Link>
            <Link href="/legal/privacy">Конфиденциальность</Link>
            <a href="mailto:support@noki.click">Поддержка</a>
          </div>
        </div>
      </footer>
    </main>
  );
}
