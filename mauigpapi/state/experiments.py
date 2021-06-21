# mautrix-instagram - A Matrix-Instagram puppeting bridge.
# Copyright (C) 2021 Tulir Asokan
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
from typing import Dict

from ..types import AndroidExperiment, QeSyncResponse


class AndroidExperiments:
    experiments: Dict[str, AndroidExperiment]

    def __init__(self) -> None:
        self.experiments = {}

    def update(self, updated: QeSyncResponse) -> None:
        self.experiments.update({item.name: item.parse() for item in updated.experiments})
