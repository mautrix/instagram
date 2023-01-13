import asyncio
import base64
import datetime
import getpass
import logging
import zlib

from mauigpapi import AndroidAPI, AndroidState
from mauigpapi.errors import IGChallengeError, IGLoginTwoFactorRequiredError
from mautrix.util.logging import TraceLogger


async def main():
    logging.basicConfig(level=logging.DEBUG)
    username = password = twofactor = None
    while not username:
        username = input("Username: ").strip()
    state = AndroidState()
    state.device.generate(username + str(datetime.date.today()))
    api_log: TraceLogger = logging.getLogger("api")
    api = AndroidAPI(state, log=api_log)
    try:
        print("Getting mobile config...")
        await api.get_mobile_config()
        while not password:
            password = getpass.getpass("Password: ")
        try:
            try:
                try:
                    print("Logging in...")
                    await api.login(username, password)
                except IGLoginTwoFactorRequiredError as e:
                    print(e)
                    print("Enter `r` to re-request SMS")
                    inf = e.body.two_factor_info
                    while not twofactor:
                        twofactor = input("2FA code: ").lower().strip()
                        if twofactor == "r":
                            if inf.sms_two_factor_on:
                                print("Re-requesting SMS code...")
                                resp = await api.send_two_factor_login_sms(
                                    username, identifier=inf.two_factor_identifier
                                )
                                print("SMS code re-requested")
                                inf = resp.two_factor_info
                                inf.totp_two_factor_on = False
                            else:
                                print("You don't have SMS 2FA on 🤔")
                            twofactor = None
                    print("Sending 2FA code...")
                    await api.two_factor_login(
                        username,
                        code=twofactor,
                        identifier=inf.two_factor_identifier,
                        is_totp=inf.totp_two_factor_on,
                    )
                print("Fetching current user...")
                user = await api.current_user()
            except IGChallengeError as e:
                print(e)
                print("Resetting challenge...")
                await api.challenge_auto(reset=True)
                print("Fetching current user...")
                user = await api.current_user()
        except Exception as e:
            print("💥", e)
            return
        if not user or not user.user:
            print("Login failed?")
            return
        print(f"Logged in as @{user.user.username}")
        print()
        print(
            base64.b64encode(zlib.compress(state.json().encode("utf-8"), level=9)).decode("utf-8")
        )
        print()
    finally:
        await api.http.close()


if __name__ == "__main__":
    asyncio.run(main())
