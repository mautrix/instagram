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
from typing import Optional

from attr import dataclass

from mautrix.types import SerializableAttrs, field

from .login import LoginResponseUser


@dataclass
class ChallengeStateData(SerializableAttrs):
    # Only for reset step
    choice: Optional[str] = None
    fb_access_token: Optional[str] = None
    big_blue_token: Optional[str] = None
    google_oauth_token: Optional[str] = None
    email: Optional[str] = None

    # Only for verify email step
    security_code: Optional[str] = None
    resend_delay: Optional[int] = None
    contact_point: Optional[str] = None
    form_type: Optional[str] = None


@dataclass
class ChallengeContext(SerializableAttrs):
    step_name: Optional[str] = None
    challenge_type_enum: Optional[str] = None
    cni: Optional[int] = None
    is_stateless: bool = False
    present_as_modal: bool = False


@dataclass(kw_only=True)
class ChallengeStateResponse(SerializableAttrs):
    # TODO enum?
    step_name: Optional[str] = None
    step_data: Optional[ChallengeStateData] = None
    logged_in_user: Optional[LoginResponseUser] = None
    user_id: Optional[int] = None
    nonce_code: Optional[str] = None
    # TODO enum?
    action: Optional[str] = None
    status: str

    flow_render_type: Optional[int] = None
    bloks_action: Optional[str] = None
    challenge_context_str: Optional[str] = field(default=None, json="challenge_context")
    challenge_type_enum_str: Optional[str] = None

    @property
    def challenge_context(self) -> ChallengeContext:
        return ChallengeContext.parse_json(self.challenge_context_str)
