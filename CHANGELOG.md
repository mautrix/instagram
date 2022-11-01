# v0.2.2 (2022-11-01)

* Added option to send captions in the same message using [MSC2530].
* Updated app version identifiers to bridge some new message types.
* Fixed race condition when backfilling chat with incoming message.

[MSC2530]: https://github.com/matrix-org/matrix-spec-proposals/pull/2530

# v0.2.1 (2022-09-19)

* Fixed login breaking due to an Instagram API change.
* Added support for SQLite as the bridge database.
* Added option to use [MSC2409] and [MSC3202] for end-to-bridge encryption.
  However, this may not work with the Synapse implementation as it hasn't been
  tested yet.
* The docker image now has an option to bypass the startup script by setting
  the `MAUTRIX_DIRECT_STARTUP` environment variable. Additionally, it will
  refuse to run as a non-root user if that variable is not set (and print an
  error message suggesting to either set the variable or use a custom command).
* Moved environment variable overrides for config fields to mautrix-python.
  The new system also allows loading JSON values to enable overriding maps like
  `login_shared_secret_map`.

[MSC2409]: https://github.com/matrix-org/matrix-spec-proposals/pull/2409
[MSC3202]: https://github.com/matrix-org/matrix-spec-proposals/pull/3202

# v0.2.0 (2022-08-26)

* Added handling for rate limit errors when connecting to Instagram.
* Added option to not bridge `m.notice` messages (thanks to [@bramenn] in [#55]).
* Fixed bridging voice messages to Instagram (broke due to server-side changes).
* Made Instagram message processing synchronous so messages are bridged in order.
* Updated Docker image to Alpine 3.16.
* Enabled appservice ephemeral events by default for new installations.
  * Existing bridges can turn it on by enabling `ephemeral_events` and disabling
    `sync_with_custom_puppets` in the config, then regenerating the registration
    file.
* Added options to make encryption more secure.
  * The `encryption` -> `verification_levels` config options can be used to
    make the bridge require encrypted messages to come from cross-signed
    devices, with trust-on-first-use validation of the cross-signing master
    key.
  * The `encryption` -> `require` option can be used to make the bridge ignore
    any unencrypted messages.
  * Key rotation settings can be configured with the `encryption` -> `rotation`
    config.

[@bramenn]: https://github.com/bramenn
[#55]: https://github.com/mautrix/instagram/pull/55

# v0.1.3 (2022-04-06)

* Added support for Matrix->Instagram replies.
* Added support for sending clickable links with previews to Instagram.
* Added support for creating DMs from Matrix (by starting a chat with a ghost).
* Added option to use [MSC2246] async media uploads.
* Added support for logging in with a Facebook token in the provisioning API.
* Added support for sending giphy gifs (requires client support).
* Changed some fields to stop the user from showing up as online on Instagram
  all the time.
* Fixed messages on Instagram not being marked as read if last event on Matrix
  is not a normal message.
* Fixed incoming messages not being deduplicated properly in some cases.
* Removed legacy `community_id` config option.
* Stopped running as root in Docker image (default user is now `1337`).
* Disabled file logging in Docker image by default.
  * If you want to enable it, set the `filename` in the file log handler to a
    path that is writable, then add `"file"` back to `logging.root.handlers`.
* Dropped Python 3.7 support.

[MSC2246]: https://github.com/matrix-org/matrix-spec-proposals/pull/2246

# v0.1.2 (2022-01-15)

* Added relay mode (see [docs](https://docs.mau.fi/bridges/general/relay-mode.html) for more info).
* Added notices for unsupported incoming message types.
* Added support for more message types:
  * "Tagged in post" messages
  * Reel clip shares
  * Profile shares
* Updated Docker image to Alpine 3.15.
* Formatted all code using [black](https://github.com/psf/black)
  and [isort](https://github.com/PyCQA/isort).

# v0.1.1 (2021-08-20)

**N.B.** Docker images have moved from `dock.mau.dev/tulir/mautrix-instagram`
to `dock.mau.dev/mautrix/instagram`. New versions are only available at the new
path.

* Added retrying failed syncs when refreshing Instagram connection.
* Updated displayname handling to fall back to username if user has no displayname set.
* Updated Docker image to Alpine 3.14.
* Fixed handling some Instagram message types.

# v0.1.0 (2021-04-07)

Initial tagged release.
