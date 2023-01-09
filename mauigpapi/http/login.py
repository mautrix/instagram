# mautrix-instagram - A Matrix-Instagram puppeting bridge.
# Copyright (C) 2022 Tulir Asokan
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
from __future__ import annotations

import base64
import io
import json
import struct
import time
import uuid

from Crypto.Cipher import AES, PKCS1_v1_5
from Crypto.PublicKey import RSA
from Crypto.Random import get_random_bytes

from ..types import FacebookLoginResponse, LoginErrorResponse, LoginResponse, LogoutResponse
from .base import BaseAndroidAPI


class LoginAPI(BaseAndroidAPI):
    async def get_mobile_config(self) -> None:
        req = {
            "bool_opt_policy": "0",
            "mobileconfigsessionless": "",
            "api_version": "3",
            "unit_type": "1",
            "query_hash": "dae17f1d3276207ebfe78f7a67cc9a04d4b88ff8c88dfc17e148fafb3f655b8e",
            "device_id": self.state.device.id,
            "fetch_type": "ASYNC_FULL",
            "family_device_id": self.state.device.fdid.upper(),
        }
        await self.std_http_post("/api/v1/launcher/mobileconfig/", data=req)

    async def login(
        self,
        username: str,
        password: str | None = None,
        encrypted_password: str | None = None,
    ) -> LoginResponse:
        if password:
            if encrypted_password:
                raise ValueError("Only one of password or encrypted_password must be provided")
            encrypted_password = self._encrypt_password(password)
        elif not encrypted_password:
            raise ValueError("One of password or encrypted_password is required")
        req = {
            "username": username,
            "enc_password": encrypted_password,
            "guid": self.state.device.uuid,
            "phone_id": self.state.device.phone_id,
            "device_id": self.state.device.id,
            "adid": self.state.device.adid,
            "google_tokens": "[]",
            "login_attempt_count": "0",  # TODO maybe cache this somewhere?
            "country_codes": json.dumps([{"country_code": "1", "source": "default"}]),
            "jazoest": self._jazoest,
        }
        return await self.std_http_post(
            "/api/v1/accounts/login/", data=req, response_type=LoginResponse
        )

    async def one_tap_app_login(self, user_id: str, nonce: str) -> LoginResponse:
        req = {
            "phone_id": self.state.device.phone_id,
            "user_id": user_id,
            "adid": self.state.device.adid,
            "guid": self.state.device.uuid,
            "device_id": self.state.device.id,
            "login_nonce": nonce,
        }
        return await self.std_http_post(
            "/api/v1/accounts/one_tap_app_login/", data=req, response_type=LoginResponse
        )

    async def send_two_factor_login_sms(
        self, username: str, identifier: str
    ) -> LoginErrorResponse:
        req = {
            "two_factor_identifier": identifier,
            "username": username,
            "guid": self.state.device.uuid,
            "device_id": self.state.device.id,
        }
        return await self.std_http_post(
            "/api/v1/accounts/send_two_factor_login_sms/",
            data=req,
            response_type=LoginErrorResponse,
        )

    async def two_factor_login(
        self,
        username: str,
        code: str,
        identifier: str,
        trust_device: bool = True,
        is_totp: bool = True,
    ) -> LoginResponse:
        req = {
            "verification_code": code,
            "two_factor_identifier": identifier,
            "username": username,
            "trust_this_device": "1" if trust_device else "0",
            "guid": self.state.device.uuid,
            "device_id": self.state.device.id,
            # TOTP = 3, Backup code = 2, SMS = 1
            "verification_method": "3" if is_totp else "1",
        }
        return await self.std_http_post(
            "/api/v1/accounts/two_factor_login/", data=req, response_type=LoginResponse
        )

    # async def two_factor_trusted_status(self, username: str, identifier: str, polling_nonce: str):
    #     pass

    async def facebook_signup(self, fb_access_token: str) -> FacebookLoginResponse:
        req = {
            "jazoest": self._jazoest,
            "dryrun": "true",
            "fb_req_flag": "false",
            "phone_id": self.state.device.phone_id,
            "force_signup_with_fb_after_cp_claiming": "false",
            "adid": self.state.device.adid,
            "guid": self.state.device.uuid,
            "device_id": self.state.device.id,
            # "waterfall_id": uuid4(),
            "fb_access_token": fb_access_token,
        }
        return await self.std_http_post(
            "/api/v1/fb/facebook_signup/", data=req, response_type=FacebookLoginResponse
        )

    async def logout(self, one_tap_app_login: bool | None = None) -> LogoutResponse:
        req = {
            "guid": self.state.device.uuid,
            "phone_id": self.state.device.phone_id,
            "device_id": self.state.device.id,
            "_uuid": self.state.device.uuid,
            "one_tap_app_login": one_tap_app_login,
        }
        return await self.std_http_post(
            "/api/v1/accounts/logout/", data=req, response_type=LogoutResponse
        )

    async def change_password(self, old_password: str, new_password: str):
        return self.change_password_encrypted(
            old_password=self._encrypt_password(old_password),
            new_password1=self._encrypt_password(new_password),
            new_password2=self._encrypt_password(new_password),
        )

    async def change_password_encrypted(
        self, old_password: str, new_password1: str, new_password2: str
    ):
        req = {
            "_csrftoken": self.state.cookies.csrf_token,
            "_uid": self.state.session.ds_user_id,
            "_uuid": self.state.device.uuid,
            "enc_old_password": old_password,
            "enc_new_password1": new_password1,
            "enc_new_password2": new_password2,
        }
        # TODO parse response content
        return await self.std_http_post("/api/v1/accounts/change_password/", data=req)

    def _encrypt_password(self, password: str) -> str:
        # Key and IV for AES encryption
        rand_key = get_random_bytes(32)
        iv = get_random_bytes(12)

        # Encrypt AES key with Instagram's RSA public key
        pubkey_bytes = base64.b64decode(self.state.session.password_encryption_pubkey)
        pubkey = RSA.import_key(pubkey_bytes)
        cipher_rsa = PKCS1_v1_5.new(pubkey)
        encrypted_rand_key = cipher_rsa.encrypt(rand_key)

        cipher_aes = AES.new(rand_key, AES.MODE_GCM, nonce=iv)
        # Add the current time to the additional authenticated data (AAD) section
        current_time = int(time.time())
        cipher_aes.update(str(current_time).encode("utf-8"))
        # Encrypt the password and get the AES MAC auth tag
        encrypted_passwd, auth_tag = cipher_aes.encrypt_and_digest(password.encode("utf-8"))

        buf = io.BytesIO()
        # 1 is presumably the version
        buf.write(bytes([1, int(self.state.session.password_encryption_key_id)]))
        buf.write(iv)
        # Length of the encrypted AES key as a little-endian 16-bit int
        buf.write(struct.pack("<h", len(encrypted_rand_key)))
        buf.write(encrypted_rand_key)
        buf.write(auth_tag)
        buf.write(encrypted_passwd)
        encoded = base64.b64encode(buf.getvalue()).decode("utf-8")
        return f"#PWD_INSTAGRAM:4:{current_time}:{encoded}"

    @property
    def _jazoest(self) -> str:
        return f"2{sum(ord(i) for i in self.state.device.phone_id)}"
