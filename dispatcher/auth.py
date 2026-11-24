from __future__ import annotations

import re
from dataclasses import dataclass, field

from .errors import ConfigError

_LOGIN_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass(frozen=True)
class Credentials:
    email: str
    password: str = field(repr=False)

    def validate(self) -> None:
        email = (self.email or "").strip()
        if not email:
            raise ConfigError("Enter your email address.", field="email")
        if not _LOGIN_EMAIL.match(email):
            raise ConfigError(f"'{email}' doesn't look like an email address.", field="email")
        if not self.password:
            raise ConfigError("Enter your password (or app password).", field="password")
        if self.password != self.password.strip():
            raise ConfigError(
                "Your password starts or ends with a space.",
                field="password",
                hint="Gmail app passwords are shown with spaces; that's fine in the middle, "
                     "but remove any space at the very start or end.",
            )

    @property
    def username(self) -> str:
        return self.email.strip()
