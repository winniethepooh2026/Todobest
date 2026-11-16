"use client";

import { Button } from "@/components/ui/button";

const CONSENT_KEY = "noki-cookie-consent-v1";

export default function CookiesPage() {
  function resetConsent() {
    localStorage.removeItem(CONSENT_KEY);
    window.dispatchEvent(new Event("noki-cookie-consent"));
  }

  return (
    <>
      <h1>Политика cookies</h1>
      <p>Редакция от 14 сентября 2026 года.</p>
      <h2>Необходимые cookies</h2>
      <p>
        Noki использует HttpOnly cookies доступа и обновления сессии,
        CSRF-cookie, временный OAuth-cookie и временный cookie подтверждения второго фактора. Они нужны для входа и защиты
        запросов и не отключаются через баннер.
      </p>
      <h2>Аналитические cookies</h2>
      <p>
        Аналитика отключена по умолчанию для всех регионов. Яндекс Метрика и её
        сетевой скрипт загружаются только после выбора «Разрешить аналитику».
        Отказ не ограничивает функции продукта.
      </p>
      <h2>Изменение выбора</h2>
      <p>
        Выбор хранится только в этом браузере. Его можно отозвать в любой момент
        — после этого Noki снова покажет consent-баннер.
      </p>
      <Button type="button" variant="outline" onClick={resetConsent}>
        Изменить выбор аналитики
      </Button>
    </>
  );
}
