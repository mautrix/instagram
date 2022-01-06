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
from mautrix.util.logging.color import (
    MXID_COLOR,
    PREFIX,
    RESET,
    ColorFormatter as BaseColorFormatter,
)

MAUIGPAPI_COLOR = PREFIX + "35;1m"  # magenta


class ColorFormatter(BaseColorFormatter):
    def _color_name(self, module: str) -> str:
        if module.startswith("mauigpapi"):
            return MAUIGPAPI_COLOR + module + RESET
        elif module.startswith("mau.instagram"):
            mau, instagram, subtype, user_id = module.split(".", 3)
            return (
                MAUIGPAPI_COLOR
                + f"{mau}.{instagram}.{subtype}"
                + RESET
                + "."
                + MXID_COLOR
                + user_id
                + RESET
            )
        return super()._color_name(module)
