# v0.1.3 (unreleased)

* Added support for Matrix->Instagram replies.
* Added support for sending clickable links with previews to Instagram.
* Added support for creating DMs from Matrix (by starting a chat with a ghost).
* Added option to use [MSC2246] async media uploads.
* Added support for logging in with a Facebook token in the provisioning API.
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
