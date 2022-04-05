# mautrix-instagram - A Matrix-Instagram puppeting bridge.
# Copyright (C) 2020 Tulir Asokan
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
from typing import Optional, get_type_hints

from aiohttp import ClientResponse

from mautrix.types import JSON, Serializable

from ..types import (
    CheckpointResponse,
    ConsentRequiredResponse,
    LoginErrorResponse,
    LoginRequiredResponse,
    SpamResponse,
)
from .base import IGError


class IGChallengeWrongCodeError(IGError):
    pass


class IGResponseError(IGError):
    response: ClientResponse

    def __init__(self, response: ClientResponse, json: JSON) -> None:
        prefix = f"Request {response.request_info.method} {response.request_info.url.path} failed"
        message = f"HTTP {response.status}"
        self.response = response
        if "message" in json:
            message = json["message"]
        type_hint = get_type_hints(type(self)).get("body", JSON)
        if type_hint is not JSON and issubclass(type_hint, Serializable):
            self.body = type_hint.deserialize(json)
        else:
            self.body = json
        super().__init__(f"{prefix}: {self._message_override or message}")

    @property
    def _message_override(self) -> Optional[str]:
        return None


class IGActionSpamError(IGResponseError):
    body: SpamResponse

    @property
    def _message(self) -> str:
        return f"HTTP {self.body.message}"


class IGNotFoundError(IGResponseError):
    pass


class IGRateLimitError(IGResponseError):
    pass


class IGCheckpointError(IGResponseError):
    body: CheckpointResponse

    @property
    def url(self) -> str:
        return self.body.challenge.api_path


class IGConsentRequiredError(IGResponseError):
    body: ConsentRequiredResponse


class IGNotLoggedInError(IGResponseError):
    body: LoginRequiredResponse

    @property
    def proper_message(self) -> str:
        return (
            f"{self.body.error_title or self.body.message} "
            f"(reason code: {self.body.logout_reason})"
        )


class IGUserHasLoggedOutError(IGNotLoggedInError):
    pass


class IGLoginRequiredError(IGNotLoggedInError):
    pass


class IGPrivateUserError(IGResponseError):
    pass


class IGSentryBlockError(IGResponseError):
    pass


class IGInactiveUserError(IGResponseError):
    pass


class IGLoginError(IGResponseError):
    body: LoginErrorResponse


class IGLoginTwoFactorRequiredError(IGLoginError):
    pass


class IGLoginBadPasswordError(IGLoginError):
    pass


class IGLoginInvalidUserError(IGLoginError):
    pass


class IGFBNoContactPointFoundError(IGLoginError):
    pass


class IGBad2FACodeError(IGResponseError):
    pass
