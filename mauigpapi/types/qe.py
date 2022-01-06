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
from typing import Any, Dict, List, Optional
import json

from attr import attrib, dataclass

from mautrix.types import SerializableAttrs


@dataclass
class QeSyncExperimentParam(SerializableAttrs):
    name: str
    value: str


@dataclass
class AndroidExperiment:
    group: str
    params: Dict[str, Any] = attrib(factory=lambda: {})
    additional: List[Any] = attrib(factory=lambda: [])
    logging_id: Optional[str] = None


def _try_parse(val: str) -> Any:
    try:
        return json.loads(val)
    except json.JSONDecodeError:
        return val


@dataclass
class QeSyncExperiment(SerializableAttrs):
    name: str
    group: str
    additional_params: List[Any]
    params: List[QeSyncExperimentParam]
    logging_id: Optional[str] = None

    def parse(self) -> AndroidExperiment:
        return AndroidExperiment(
            group=self.group,
            additional=self.additional_params,
            logging_id=self.logging_id,
            params={param.name: _try_parse(param.value) for param in self.params},
        )


@dataclass
class QeSyncResponse(SerializableAttrs):
    experiments: List[QeSyncExperiment]
    status: str
