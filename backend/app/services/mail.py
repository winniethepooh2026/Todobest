from __future__ import annotations

import html
import logging
from dataclasses import dataclass
from typing import Any, Literal

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)
MailKind = Literal[
    "verify_email",
    "reset_password",
    "invitation",
    "new_login",
    "invoice",
    "export_ready",
    "account_notice",
]


@dataclass(frozen=True, slots=True)
class RenderedMail:
    subject: str
    text: str
    html: str


def _layout(title: str, body: str, action_label: str | None, action_url: str | None) -> str:
    action = ""
    if action_label and action_url:
        action = (
            f'<p style="margin:28px 0"><a href="{html.escape(action_url, quote=True)}" '
            'style="background:#171717;color:#fff;padding:12px 18px;border-radius:8px;'
            f'text-decoration:none">{html.escape(action_label)}</a></p>'
        )
    return (
        '<!doctype html><html><body style="font-family:Arial,sans-serif;color:#171717;'
        'max-width:600px;margin:auto;padding:32px">'
        f'<h1 style="font-size:24px">{html.escape(title)}</h1>{body}{action}'
        '<p style="color:#737373;font-size:13px">Noki · командная работа без лишнего шума</p>'
        "</body></html>"
    )


def render_mail(kind: MailKind, context: dict[str, Any]) -> RenderedMail:
    name = str(context.get("name") or "").strip()
    greeting = f"Здравствуйте, {name}!" if name else "Здравствуйте!"
    url = str(context.get("action_url") or "")
    if kind == "verify_email":
        title = "Подтвердите email"
        detail = "Подтвердите адрес, чтобы не потерять доступ к аккаунту. Ссылка действует 24 часа."
        label = "Подтвердить email"
    elif kind == "reset_password":
        title = "Сброс пароля"
        detail = "По вашему адресу запросили новый пароль. Ссылка одноразовая и скоро истечёт."
        label = "Задать новый пароль"
    elif kind == "invitation":
        title = "Вас пригласили в Noki"
        detail = f"Примите приглашение в {context.get('target_name', 'команду')}."
        label = "Принять приглашение"
    elif kind == "new_login":
        title = "Новый вход в Noki"
        detail = (
            f"Выполнен новый вход: {context.get('when', '')} · "
            f"{context.get('ip', 'unknown IP')} · "
            f"{str(context.get('device') or 'Неизвестное устройство')[:160]}."
        )
        label = "Проверить настройки"
    elif kind == "invoice":
        title = str(context.get("title") or "Документ от Noki")
        detail = str(context.get("detail") or "Ваш чек или инвойс готов.")
        label = "Открыть документ"
    elif kind == "export_ready":
        title = "Экспорт Space готов"
        detail = "Архив доступен для скачивания 7 дней."
        label = "Скачать экспорт"
    else:
        title = "Попытка регистрации в Noki"
        detail = "Кто-то указал этот email при регистрации. Ваш существующий аккаунт не изменён."
        label = "Войти в Noki"
    text = f"{greeting}\n\n{detail}" + (f"\n\n{url}" if url else "") + "\n\nNoki"
    body = f"<p>{html.escape(greeting)}</p><p>{html.escape(detail)}</p>"
    return RenderedMail(title, text, _layout(title, body, label if url else None, url or None))


def send_mail(
    *, recipient: str, kind: MailKind, context: dict[str, Any], idempotency_key: str
) -> str:
    api_key = settings.resend_api_key.get_secret_value()
    if not api_key:
        raise RuntimeError("RESEND_API_KEY is not configured")
    rendered = render_mail(kind, context)
    payload: dict[str, Any] = {
        "from": settings.mail_from,
        "to": [recipient],
        "subject": rendered.subject,
        "text": rendered.text,
        "html": rendered.html,
    }
    if settings.mail_reply_to:
        payload["reply_to"] = settings.mail_reply_to
    with httpx.Client(timeout=15.0) as client:
        response = client.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Idempotency-Key": idempotency_key[:256],
            },
            json=payload,
        )
    response.raise_for_status()
    message_id = response.json().get("id")
    if not isinstance(message_id, str) or not message_id:
        raise RuntimeError("Resend returned no message id")
    return message_id


def enqueue_mail(
    *, recipient: str, kind: MailKind, context: dict[str, Any], idempotency_key: str
) -> bool:
    try:
        from app.worker.tasks import send_mail_task

        result = send_mail_task.apply_async(
            kwargs={
                "recipient": recipient,
                "kind": kind,
                "context": context,
                "idempotency_key": idempotency_key,
            },
            queue=settings.mail_queue,
        )
        logger.info("Queued %s mail task_id=%s", kind, result.id)
        return True
    except Exception:
        logger.exception("Could not enqueue %s mail", kind)
        return False
