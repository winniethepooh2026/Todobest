from __future__ import annotations

import base64
import binascii
import ipaddress
import os
import re
from email.utils import parseaddr
from functools import lru_cache
from pathlib import Path
from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import (
    AliasChoices,
    Field,
    SecretStr,
    computed_field,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL

INSECURE_JWT_SECRET = "replace-this-with-a-random-secret-at-least-64-characters-long"
MAIL_SENDER_DOMAIN = "noki.click"
S3_BUCKET_PATTERN = re.compile(r"^(?!\d{1,3}(?:\.\d{1,3}){3}$)[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")
POSTGRES_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")
POSTGRES_COMPONENT_FIELDS = frozenset(
    {
        "postgres_host",
        "postgres_port",
        "postgres_db",
        "postgres_user",
        "postgres_password",
    }
)


def _url_origin(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise ValueError("must be an HTTP(S) origin without credentials, path, query, or fragment")
    # Accessing port validates malformed/out-of-range values.
    _ = parsed.port
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}".rstrip("/")


def is_loopback_host(hostname: str | None) -> bool:
    if hostname is None:
        return False
    normalized = hostname.rstrip(".").casefold()
    if normalized == "localhost" or normalized.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        hide_input_in_errors=True,
    )

    app_name: str = "Noki API"
    environment: Literal["development", "test", "production"] = "development"
    api_v1_prefix: str = "/api/v1"
    public_api_v1_prefix: str = "/api/public/v1"
    expected_db_revision: str = "0026_totp"

    postgres_host: str = "127.0.0.1"
    postgres_port: int = Field(default=5432, ge=1, le=65535)
    postgres_db: str = "noki"
    postgres_user: str = "noki"
    postgres_password: SecretStr = SecretStr("noki_dev_password")
    # Backwards-compatible advanced override. New deployments should use the
    # POSTGRES_* fields above so the password has a single source of truth.
    database_url_override: SecretStr = Field(
        default=SecretStr(""),
        validation_alias=AliasChoices("DATABASE_URL", "database_url"),
        repr=False,
        exclude=True,
    )
    database_ssl_ca_file: Path | None = None
    redis_url: str = "redis://localhost:6379/0"
    db_pool_size: int = Field(default=10, ge=1, le=100)
    db_max_overflow: int = Field(default=20, ge=0, le=200)
    db_pool_timeout: float = Field(default=30.0, gt=0, le=300)
    redis_socket_timeout: float = Field(default=5.0, gt=0, le=60)
    redis_connect_timeout: float = Field(default=5.0, gt=0, le=60)
    redis_max_connections: int = Field(default=50, ge=5, le=1000)

    jwt_secret: str = INSECURE_JWT_SECRET
    data_encryption_key: str = ""
    jwt_algorithm: Literal["HS256"] = "HS256"
    jwt_issuer: str = "noki-api"
    jwt_audience: str = "noki-web"
    access_token_minutes: int = Field(default=15, ge=1, le=60)
    refresh_token_days: int = Field(default=30, ge=1, le=90)
    max_jwt_bytes: int = Field(default=4096, ge=512, le=16_384)

    backend_url: str = "http://localhost:8000"
    frontend_url: str = "http://localhost:3000"
    cors_origins: str = "http://localhost:3000"
    trusted_hosts: str = "localhost,127.0.0.1,testserver,noki.test"

    cookie_secure: bool = False
    cookie_domain: str | None = None
    cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    access_cookie_name: str = "noki_access"
    refresh_cookie_name: str = "noki_refresh"
    csrf_cookie_name: str = "noki_csrf"
    oauth_state_cookie_name: str = "noki_oauth_state"

    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/api/v1/auth/google/callback"
    public_registration_enabled: bool = True
    resend_api_key: SecretStr = SecretStr("")
    mail_from: str = "Noki <no-reply@noki.click>"
    mail_reply_to: str = ""
    mail_queue: str = "mail"
    email_verification_ttl_hours: int = Field(default=24, ge=1, le=168)
    password_reset_ttl_minutes: int = Field(default=30, ge=5, le=1440)
    invitation_ttl_days: int = Field(default=7, ge=1, le=30)
    export_dir: Path = Path("storage/exports")

    # Avatar objects are kept in a private S3/S3-compatible bucket. Empty
    # values disable avatar import without affecting authentication.
    aws_access_key_id: str = ""
    aws_secret_access_key: SecretStr = SecretStr("")
    aws_storage_bucket_name: str = ""
    aws_s3_endpoint_url: str = ""
    aws_s3_region_name: str = "us-east-1"
    avatar_source_max_bytes: int = Field(
        default=2 * 1024 * 1024,
        ge=1024,
        le=5 * 1024 * 1024,
    )
    avatar_source_max_pixels: int = Field(default=4_000_000, ge=1, le=20_000_000)
    avatar_source_max_dimension: int = Field(default=4096, ge=128, le=8192)
    avatar_output_size: int = Field(default=128, ge=64, le=512)
    avatar_output_max_bytes: int = Field(default=128 * 1024, ge=1024, le=1024 * 1024)
    avatar_refresh_days: int = Field(default=7, ge=1, le=90)
    avatar_download_timeout_seconds: float = Field(default=10.0, gt=0, le=30)
    avatar_malware_scan_mode: Literal["required", "disabled-for-testing"] = "required"
    clamav_unix_socket: Path | None = Path("/run/clamav/clamd.ctl")
    clamav_host: str = "127.0.0.1"
    clamav_port: int = Field(default=3310, ge=1, le=65535)
    clamav_timeout_seconds: float = Field(default=10.0, gt=0, le=60)

    upload_dir: Path = Path("storage/images")
    max_image_bytes: int = Field(default=25 * 1024 * 1024, ge=1, le=100 * 1024 * 1024)
    max_image_width: int = Field(default=720, ge=1, le=8192)
    upload_max_pixels: int = Field(default=20_000_000, ge=1, le=100_000_000)
    upload_max_height: int = Field(default=8192, ge=1, le=100_000)
    upload_max_total_bytes: int = Field(
        default=512 * 1024 * 1024,
        ge=1,
        le=100 * 1024 * 1024 * 1024,
    )
    upload_max_files_per_user: int = Field(default=1000, ge=1, le=1_000_000)
    min_upload_free_bytes: int = Field(
        default=1024 * 1024 * 1024,
        ge=0,
        le=1024 * 1024 * 1024 * 1024,
    )
    max_request_bytes: int = Field(default=3 * 1024 * 1024, ge=1024, le=100 * 1024 * 1024)
    request_timeout_seconds: float = Field(default=30.0, gt=0, le=300)

    max_columns_per_board: int = 10
    max_page_chars: int = 200_000
    max_text_node_chars: int = 20_000
    max_page_json_bytes: int = 2 * 1024 * 1024

    login_rate_limit_attempts: int = Field(default=10, ge=1, le=10_000)
    login_rate_limit_window_seconds: int = Field(default=300, ge=1, le=86_400)
    register_rate_limit_attempts: int = Field(default=5, ge=1, le=10_000)
    register_rate_limit_window_seconds: int = Field(default=3600, ge=1, le=86_400)
    mail_recipient_rate_limit_attempts: int = Field(default=3, ge=1, le=100)
    mail_rate_limit_window_seconds: int = Field(default=3600, ge=60, le=86_400)
    invitation_mail_actor_rate_limit_attempts: int = Field(default=20, ge=1, le=1000)
    export_rate_limit_attempts: int = Field(default=3, ge=1, le=100)
    oauth_rate_limit_attempts: int = Field(default=20, ge=1, le=10_000)
    oauth_rate_limit_window_seconds: int = Field(default=300, ge=1, le=86_400)
    refresh_rate_limit_attempts: int = Field(default=60, ge=1, le=10_000)
    refresh_rate_limit_window_seconds: int = Field(default=60, ge=1, le=86_400)
    upload_rate_limit_attempts: int = Field(default=20, ge=1, le=10_000)
    upload_ip_rate_limit_attempts: int = Field(default=60, ge=1, le=10_000)
    upload_rate_limit_window_seconds: int = Field(default=60, ge=1, le=86_400)
    avatar_read_rate_limit_attempts: int = Field(default=600, ge=1, le=10_000)
    avatar_read_rate_limit_window_seconds: int = Field(default=60, ge=1, le=3600)
    password_change_rate_limit_attempts: int = Field(default=5, ge=1, le=100)
    password_change_rate_limit_window_seconds: int = Field(
        default=3600,
        ge=60,
        le=86_400,
    )
    public_api_ip_rate_limit_requests: int = Field(default=1200, ge=1, le=100_000)
    public_api_token_rate_limit_requests: int = Field(default=600, ge=1, le=100_000)
    public_api_rate_limit_window_seconds: int = Field(default=60, ge=1, le=3600)
    password_work_queue_timeout_seconds: float = Field(default=2.0, gt=0, le=30)
    max_sessions_per_user: int = Field(default=20, ge=1, le=1000)

    @field_validator("cookie_domain", mode="before")
    @classmethod
    def empty_cookie_domain_to_none(cls, value: object) -> object:
        return None if value == "" else value

    @field_validator("database_ssl_ca_file", mode="before")
    @classmethod
    def empty_database_ca_to_none(cls, value: object) -> object:
        return None if value == "" else value

    @field_validator("postgres_host")
    @classmethod
    def validate_postgres_host(cls, value: str) -> str:
        normalized = value.strip()
        if normalized != value:
            raise ValueError("POSTGRES_HOST must not contain surrounding whitespace")
        if normalized.startswith("[") or normalized.endswith("]"):
            if not (normalized.startswith("[") and normalized.endswith("]")):
                raise ValueError("POSTGRES_HOST has mismatched IPv6 brackets")
            try:
                parsed_ip = ipaddress.ip_address(normalized[1:-1])
            except ValueError as exc:
                raise ValueError("POSTGRES_HOST contains an invalid bracketed IP address") from exc
            if parsed_ip.version != 6:
                raise ValueError("POSTGRES_HOST brackets are allowed only for IPv6")
            normalized = normalized[1:-1]
        if (
            not normalized
            or len(normalized) > 253
            or any(character.isspace() for character in normalized)
            or any(character in normalized for character in "/@?#")
        ):
            raise ValueError("POSTGRES_HOST must be a hostname or IP address")
        return normalized

    @field_validator("postgres_db", "postgres_user")
    @classmethod
    def validate_postgres_identifier(cls, value: str) -> str:
        if not POSTGRES_IDENTIFIER_PATTERN.fullmatch(value):
            raise ValueError(
                "PostgreSQL database and role names must be 1-63 ASCII identifier characters"
            )
        return value

    @field_validator("postgres_password", mode="before")
    @classmethod
    def validate_postgres_password(cls, value: object) -> object:
        secret = value.get_secret_value() if isinstance(value, SecretStr) else value
        if not isinstance(secret, str):
            return value
        if len(secret) > 1024 or any(character in secret for character in "\0\r\n"):
            raise ValueError("POSTGRES_PASSWORD contains invalid characters")
        return value

    @field_validator("clamav_unix_socket", mode="before")
    @classmethod
    def empty_clamav_socket_to_none(cls, value: object) -> object:
        return None if value == "" else value

    @field_validator(
        "aws_access_key_id",
        "aws_storage_bucket_name",
        "aws_s3_endpoint_url",
        "aws_s3_region_name",
    )
    @classmethod
    def reject_surrounding_whitespace(cls, value: str) -> str:
        if (
            len(value) > 2048
            or value != value.strip()
            or any(character.isspace() or not character.isascii() for character in value)
        ):
            raise ValueError("AWS setting contains invalid characters")
        return value

    @field_validator("aws_secret_access_key", mode="before")
    @classmethod
    def validate_aws_secret_access_key(cls, value: object) -> object:
        secret = value.get_secret_value() if isinstance(value, SecretStr) else value
        if not isinstance(secret, str):
            return value
        if (
            len(secret) > 2048
            or secret != secret.strip()
            or any(character.isspace() or not character.isascii() for character in secret)
        ):
            raise ValueError("AWS secret access key contains invalid characters")
        return value

    @field_validator(
        "jwt_secret",
        "jwt_issuer",
        "jwt_audience",
        "access_cookie_name",
        "refresh_cookie_name",
        "csrf_cookie_name",
        "oauth_state_cookie_name",
    )
    @classmethod
    def reject_blank_security_values(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("security setting cannot be blank")
        return normalized

    @computed_field
    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @computed_field
    @property
    def trusted_host_list(self) -> list[str]:
        return [host.strip().lower() for host in self.trusted_hosts.split(",") if host.strip()]

    @property
    def database_url(self) -> str:
        override = self.database_url_override.get_secret_value()
        if override:
            return override
        return URL.create(
            drivername="postgresql+asyncpg",
            username=self.postgres_user,
            password=self.postgres_password.get_secret_value(),
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        ).render_as_string(hide_password=False)

    @computed_field
    @property
    def google_oauth_enabled(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret)

    @computed_field
    @property
    def avatar_storage_enabled(self) -> bool:
        return all(
            (
                self.aws_access_key_id,
                self.aws_secret_access_key.get_secret_value(),
                self.aws_storage_bucket_name,
                self.aws_s3_endpoint_url,
            )
        )

    @computed_field
    @property
    def trusted_request_origins(self) -> list[str]:
        origins: set[str] = set()
        for candidate in [self.frontend_url, self.backend_url, *self.cors_origin_list]:
            try:
                origins.add(_url_origin(candidate))
            except ValueError:
                continue
        return sorted(origins)

    @model_validator(mode="after")
    def validate_security_configuration(self) -> Self:
        if bool(self.google_client_id) != bool(self.google_client_secret):
            raise ValueError(
                "GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET must be configured together"
            )
        if self.cookie_samesite == "none" and not self.cookie_secure:
            raise ValueError("COOKIE_SAMESITE=none requires COOKIE_SECURE=true")
        if self.password_work_queue_timeout_seconds >= self.request_timeout_seconds:
            raise ValueError(
                "PASSWORD_WORK_QUEUE_TIMEOUT_SECONDS must be less than REQUEST_TIMEOUT_SECONDS"
            )

        s3_values = (
            self.aws_access_key_id,
            self.aws_secret_access_key.get_secret_value(),
            self.aws_storage_bucket_name,
            self.aws_s3_endpoint_url,
        )
        if any(s3_values) and not all(s3_values):
            raise ValueError(
                "AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_STORAGE_BUCKET_NAME "
                "and AWS_S3_ENDPOINT_URL must be configured together"
            )
        if self.avatar_storage_enabled:
            bucket = self.aws_storage_bucket_name
            if (
                not S3_BUCKET_PATTERN.fullmatch(bucket)
                or ".." in bucket
                or ".-" in bucket
                or "-." in bucket
            ):
                raise ValueError("AWS_STORAGE_BUCKET_NAME is not a valid S3 bucket name")
            try:
                endpoint = urlsplit(_url_origin(self.aws_s3_endpoint_url))
            except ValueError as exc:
                raise ValueError("AWS_S3_ENDPOINT_URL must be a safe HTTP(S) origin") from exc
            if self.environment == "production" and endpoint.scheme != "https":
                raise ValueError("AWS_S3_ENDPOINT_URL must use HTTPS in production")
            if self.environment == "production" and is_loopback_host(endpoint.hostname):
                raise ValueError("AWS_S3_ENDPOINT_URL must not use a loopback host in production")
            if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", self.aws_s3_region_name):
                raise ValueError("AWS_S3_REGION_NAME is invalid")
        if not self.clamav_host.strip() or any(
            character in self.clamav_host for character in "/:@?#"
        ):
            raise ValueError("CLAMAV_HOST must be a hostname or IP address without a scheme")

        if self.environment != "production":
            return self

        errors: list[str] = []
        supplied_postgres_fields = POSTGRES_COMPONENT_FIELDS & self.model_fields_set
        has_database_url_override = bool(self.database_url_override.get_secret_value())
        if supplied_postgres_fields and supplied_postgres_fields != POSTGRES_COMPONENT_FIELDS:
            missing_fields = sorted(POSTGRES_COMPONENT_FIELDS - supplied_postgres_fields)
            errors.append(
                "set every POSTGRES_* variable in production; missing "
                + ", ".join(field.upper() for field in missing_fields)
            )
        if has_database_url_override and supplied_postgres_fields:
            errors.append("DATABASE_URL and POSTGRES_* must not be configured together")
        if not has_database_url_override and supplied_postgres_fields != POSTGRES_COMPONENT_FIELDS:
            errors.append(
                "production PostgreSQL configuration must come from all POSTGRES_* variables"
            )
        jwt_secret = self.jwt_secret.strip()
        if jwt_secret == INSECURE_JWT_SECRET or len(jwt_secret) < 64:
            errors.append("JWT_SECRET must be a non-default secret of at least 64 characters")
        if len(set(jwt_secret)) < 16:
            errors.append("JWT_SECRET does not contain enough distinct characters")

        encoded_key = self.data_encryption_key.strip()
        try:
            padded = encoded_key + ("=" * (-len(encoded_key) % 4))
            decoded_key = base64.b64decode(
                padded.encode("ascii"),
                altchars=b"-_",
                validate=True,
            )
        except (UnicodeEncodeError, binascii.Error, ValueError):
            decoded_key = b""
        if len(decoded_key) != 32:
            errors.append("DATA_ENCRYPTION_KEY must be valid base64 for exactly 32 bytes")

        if not self.cookie_secure:
            errors.append("COOKIE_SECURE must be true")
        if self.cookie_domain is not None:
            errors.append("COOKIE_DOMAIN must be unset for host-only production cookies")
        if "noki_dev_password" in self.database_url.casefold():
            errors.append("DATABASE_URL must not use the development database password")
        if not self.upload_dir.is_absolute():
            errors.append("UPLOAD_DIR must be absolute")
        sender_address = parseaddr(self.mail_from)[1]
        sender_domain = sender_address.rpartition("@")[2].rstrip(".").casefold()
        if not sender_domain or not (
            sender_domain == MAIL_SENDER_DOMAIN or sender_domain.endswith(f".{MAIL_SENDER_DOMAIN}")
        ):
            errors.append("MAIL_FROM must use the noki.click domain or one of its subdomains")
        if self.avatar_storage_enabled and (
            self.clamav_unix_socket is None or not self.clamav_unix_socket.is_absolute()
        ):
            errors.append("S3 avatar storage requires an absolute CLAMAV_UNIX_SOCKET in production")

        try:
            database = urlsplit(self.database_url)
            _ = database.port
            database_host = database.hostname
            if (
                database.scheme != "postgresql+asyncpg"
                or not database_host
                or not database.username
                or not database.password
                or not database.path.strip("/")
            ):
                errors.append(
                    "DATABASE_URL must use postgresql+asyncpg with username, "
                    "password, hostname, and database name"
                )
            elif not (
                is_loopback_host(database_host) or database_host.casefold() in {"db", "postgres"}
            ):
                if database.query:
                    errors.append("remote DATABASE_URL must not configure TLS in query parameters")
                if (
                    self.database_ssl_ca_file is None
                    or not self.database_ssl_ca_file.is_absolute()
                    or not self.database_ssl_ca_file.is_file()
                ):
                    errors.append(
                        "remote DATABASE_URL requires an absolute, readable "
                        "DATABASE_SSL_CA_FILE for hostname-verifying TLS"
                    )
        except ValueError as exc:
            errors.append(f"DATABASE_URL is invalid: {exc}")

        try:
            redis = urlsplit(self.redis_url)
            _ = redis.port
            redis_host = redis.hostname
            if redis.scheme not in {"redis", "rediss"} or not redis_host or not redis.password:
                errors.append(
                    "REDIS_URL must use redis:// or rediss:// with a hostname and password"
                )
            elif (
                redis.scheme != "rediss"
                and not is_loopback_host(redis_host)
                and redis_host.casefold() != "redis"
            ):
                errors.append("remote REDIS_URL must use rediss://")
            elif (
                redis.scheme == "rediss"
                and not is_loopback_host(redis_host)
                and redis_host.casefold() != "redis"
                and redis.query
            ):
                errors.append(
                    "remote REDIS_URL must not override TLS verification in query parameters"
                )
        except ValueError as exc:
            errors.append(f"REDIS_URL is invalid: {exc}")

        trusted_hosts = self.trusted_host_list
        if not trusted_hosts:
            errors.append("TRUSTED_HOSTS must contain at least one hostname")
        if any("*" in host for host in trusted_hosts):
            errors.append("TRUSTED_HOSTS must not contain wildcard hosts")

        parsed_urls: dict[str, object] = {}
        url_values = {
            "BACKEND_URL": self.backend_url,
            "FRONTEND_URL": self.frontend_url,
        }
        for name, value in url_values.items():
            try:
                origin = _url_origin(value)
                parsed = urlsplit(origin)
                parsed_urls[name] = parsed
                if parsed.scheme != "https":
                    errors.append(f"{name} must use https")
                if is_loopback_host(parsed.hostname):
                    errors.append(f"{name} must not use a loopback hostname")
            except ValueError as exc:
                errors.append(f"{name} {exc}")

        backend = parsed_urls.get("BACKEND_URL")
        backend_host = getattr(backend, "hostname", None)
        if backend_host and backend_host.casefold() not in trusted_hosts:
            errors.append("TRUSTED_HOSTS must include the BACKEND_URL hostname")

        normalized_cors: set[str] = set()
        if not self.cors_origin_list:
            errors.append("CORS_ORIGINS must contain at least one origin")
        for origin in self.cors_origin_list:
            if "*" in origin:
                errors.append("CORS_ORIGINS must not contain wildcards")
                continue
            try:
                normalized = _url_origin(origin)
                parsed = urlsplit(normalized)
                normalized_cors.add(normalized)
                if parsed.scheme != "https":
                    errors.append("every CORS origin must use https")
                if is_loopback_host(parsed.hostname):
                    errors.append("CORS origins must not use loopback hostnames")
            except ValueError as exc:
                errors.append(f"CORS origin {origin!r} {exc}")

        try:
            frontend_origin = _url_origin(self.frontend_url)
            if frontend_origin not in normalized_cors:
                errors.append("CORS_ORIGINS must include FRONTEND_URL")
        except ValueError:
            pass

        if self.google_oauth_enabled:
            try:
                redirect = urlsplit(self.google_redirect_uri)
                expected_path = f"{self.api_v1_prefix}/auth/google/callback"
                if (
                    redirect.scheme != "https"
                    or not redirect.hostname
                    or redirect.username is not None
                    or redirect.password is not None
                    or redirect.query
                    or redirect.fragment
                    or redirect.path != expected_path
                ):
                    errors.append(
                        f"GOOGLE_REDIRECT_URI must be an HTTPS URL whose path is {expected_path}"
                    )
                _ = redirect.port
                redirect_origin = f"{redirect.scheme.lower()}://{redirect.netloc.lower()}".rstrip(
                    "/"
                )
                if redirect_origin != _url_origin(self.backend_url):
                    errors.append("GOOGLE_REDIRECT_URI must use the BACKEND_URL origin")
                if is_loopback_host(redirect.hostname):
                    errors.append("GOOGLE_REDIRECT_URI must not use a loopback hostname")
            except ValueError as exc:
                errors.append(f"GOOGLE_REDIRECT_URI is invalid: {exc}")

        if errors:
            raise ValueError("Unsafe production configuration: " + "; ".join(dict.fromkeys(errors)))
        return self


@lru_cache
def get_settings() -> Settings:
    # Production must be fully described by the service environment. Otherwise
    # an omitted PM2 variable could silently inherit a development value from
    # the repository's dotenv file.
    process_environment = next(
        (value for key, value in os.environ.items() if key.casefold() == "environment"),
        "",
    )
    if process_environment.strip().casefold() == "production":
        return Settings(_env_file=None)
    return Settings()


settings = get_settings()
